from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch
import uuid
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path

from companion.application import InteractionCommand, InteractionService
from companion.context import ContextBuilder
from companion.goals.service import GoalService
from companion.identity import IdentityLoader
from companion.memory import DeterministicEmbeddingProvider
from companion.persistence import PostgresRepository, apply_migrations
from companion.persistence.proactive import ProactivePostgresStore
from companion.policy import PrivacyClass
from companion.proactive import ProactivePreferenceRevision
from companion.product.chat_goals import ChatGoalPlan, ExplicitChatGoalPlanner
from mlsys.retrieval.service import RetrievalService
from mlsys.serving import DeterministicLocalProvider, Stage1Router
from mlsys.serving.codex_cli import (
    CODEX_CLI_PROVIDER_ID,
    CODEX_OWNER_AUTOMATIC_AUTHORIZATION_REF,
    CodexCliProvider,
    CodexProcessResult,
    bind_codex_cli_request,
)


ROOT = Path(__file__).resolve().parents[1]
DATABASE_URL = os.getenv("HAVRE_TEST_DATABASE_URL")


class ChatGoalPlanContractTests(unittest.TestCase):
    def test_structured_output_requires_all_nullable_fields(self):
        schema = ChatGoalPlan.provider_schema()
        self.assertEqual(set(schema["required"]), set(schema["properties"]))
        reminder = schema["$defs"]["PlannedReminder"]
        self.assertEqual(set(reminder["required"]), set(reminder["properties"]))
        self.assertFalse(reminder["additionalProperties"])
        self.assertFalse(ExplicitChatGoalPlanner.explicitly_requests_action("我想吃面"))
        self.assertTrue(ExplicitChatGoalPlanner.explicitly_requests_action("我希望以后每天练琴，慢慢成为更耐心的人"))
        self.assertFalse(ExplicitChatGoalPlanner.explicitly_requests_action("我觉得应该吃面"))
        self.assertTrue(ExplicitChatGoalPlanner.explicitly_requests_action(
            "我认真想了一下应该多花点时间练琴，不只是买器材。"
            "平时先从一小段旋律练起，遇到难处不要立刻换曲子。"
            "我需要尝试更耐心一点，练完可以简单写下哪里顺了、哪里还不熟，慢慢积累。"
        ))

    def test_only_explicit_language_opens_the_action_path(self) -> None:
        self.assertFalse(
            ExplicitChatGoalPlanner.explicitly_requests_action("今天好累，作业好多")
        )
        self.assertTrue(
            ExplicitChatGoalPlanner.explicitly_requests_action(
                "帮我创建一个目标：这周把作业写完"
            )
        )
        self.assertTrue(
            ExplicitChatGoalPlanner.explicitly_requests_action(
                "提醒我后天交作业"
            )
        )

    def test_plan_requires_complete_goal_or_exact_no_action(self) -> None:
        plan = ChatGoalPlan.model_validate({
            "schema_version": 1,
            "create_goal": False,
            "source_quote": None,
            "track": None,
            "title": None,
            "why": None,
            "priority": None,
            "next_action": None,
            "review_at": None,
            "reminders": [],
        })
        self.assertFalse(plan.create_goal)
        with self.assertRaises(ValueError):
            ChatGoalPlan.model_validate({
                **plan.model_dump(mode="json"),
                "create_goal": True,
                "title": "缺少来源",
            })


@unittest.skipUnless(DATABASE_URL, "HAVRE_TEST_DATABASE_URL is required")
class ChatGoalPlannerPostgresTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        assert DATABASE_URL is not None
        apply_migrations(DATABASE_URL, ROOT / "db/migrations")
        cls.identity = IdentityLoader(ROOT / "identity").load()
        cls.repository = PostgresRepository(DATABASE_URL)
        cls.repository.open()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.repository.close()

    async def asyncSetUp(self) -> None:
        self.owner = uuid.uuid4()
        self.repository.bootstrap_owner_and_identity(
            owner_id=self.owner, identity=self.identity
        )
        self.embedding = DeterministicEmbeddingProvider()
        self.repository.register_embedding_version(self.embedding.version)
        self.retrieval = RetrievalService(
            repository=self.repository, embedding_provider=self.embedding
        )
        self.temporary = tempfile.TemporaryDirectory()
        self.addAsyncCleanup(self._cleanup)
        self.executable = Path(self.temporary.name) / "codex.exe"
        self.executable.touch()
        self.plan_calls = 0

    async def _cleanup(self) -> None:
        self.temporary.cleanup()

    async def _runner(self, args, stdin_text, _cwd, _environment, _timeout_ms):
        if args[-1] == "--version":
            return CodexProcessResult(0, "codex-cli 0.152.0\n", "")
        if args[1:] == ("login", "status"):
            return CodexProcessResult(0, "Logged in using ChatGPT\n", "")
        prompt = stdin_text or ""
        if "HAVRE OWNER-CHAT-GOAL-PLAN" in prompt:
            self.assertIn("--output-schema", args)
            schema = json.loads(Path(args[args.index("--output-schema") + 1]).read_text())
            self.assertEqual(set(schema["required"]), set(schema["properties"]))
            self.plan_calls += 1
            remind_at = datetime.now(UTC) + timedelta(days=2)
            output = json.dumps({
                "schema_version": 1,
                "create_goal": True,
                "source_quote": "帮我创建一个目标",
                "track": "reality",
                "title": "完成这周的作业",
                "why": "我明确希望把本周作业完成并按时提交。",
                "priority": "high",
                "next_action": "先列出还没完成的题目。",
                "review_at": None,
                "reminders": [{
                    "kind": "check_in",
                    "text": "作业进度怎么样了？",
                    "remind_at": remind_at.isoformat(),
                    "expires_at": (remind_at + timedelta(hours=3)).isoformat(),
                }],
            }, ensure_ascii=False)
        else:
            output = "好，我按你刚才明确说的来。"
        stdout = "\n".join((
            json.dumps({"type": "thread.started", "thread_id": "thread-goal"}),
            json.dumps({"type": "turn.started"}),
            json.dumps({
                "type": "item.completed",
                "item": {"type": "agent_message", "text": output},
            }, ensure_ascii=False),
            json.dumps({
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 200, "cached_input_tokens": 0,
                    "output_tokens": 80, "reasoning_output_tokens": 20,
                },
            }),
        ))
        return CodexProcessResult(0, stdout, "")

    async def test_queue_failure_rolls_back_goal_action_and_success_receipt(self) -> None:
        provider = CodexCliProvider(executable=self.executable, enabled=True,
            explicit_authorization_ref=CODEX_OWNER_AUTOMATIC_AUTHORIZATION_REF,
            reasoning_effort="high", process_runner=self._runner,
            environment={"PATH":"safe", "CODEX_HOME":self.temporary.name})
        goals = GoalService(repository=self.repository)
        proactive = ProactivePostgresStore(repository=self.repository, owner_id=self.owner, identity=self.identity)
        planner = ExplicitChatGoalPlanner(repository=self.repository, owner_id=self.owner,
            provider=provider, goal_service=goals, proactive_store=proactive, owner_timezone="UTC")
        service = InteractionService(owner_id=self.owner, identity=self.identity,
            repository=self.repository, context_builder=ContextBuilder(max_input_tokens=8192,reserved_output_tokens=256),
            router=Stage1Router(), provider=DeterministicLocalProvider(),
            retrieval_service=self.retrieval, chat_goal_planner=planner)
        with patch.object(proactive, "enqueue_goal_reminder", side_effect=RuntimeError("queue unavailable")):
            await service.interact(InteractionCommand(message="帮我创建一个目标：这周把作业写完，并提醒我检查进度。",
                privacy_class=PrivacyClass.NORMAL, channel="web", idempotency_key=str(uuid.uuid4())))
        self.assertEqual(len(goals.list(owner_id=self.owner)), 0)
        with self.repository.pool.connection() as connection:
            rows=connection.execute("SELECT status FROM havre.owner_chat_goal_plan_runs WHERE owner_id=%s",(self.owner,)).fetchall()
            count=connection.execute("SELECT count(*) AS n FROM havre.owner_chat_goal_actions WHERE owner_id=%s",(self.owner,)).fetchone()
        self.assertEqual([r["status"] for r in rows], ["failed"])
        self.assertEqual(count["n"], 0)
        await provider.aclose()

    async def test_explicit_request_writes_goal_and_reminder_but_ordinary_and_private_do_not(self) -> None:
        provider = CodexCliProvider(
            executable=self.executable,
            enabled=True,
            explicit_authorization_ref=CODEX_OWNER_AUTOMATIC_AUTHORIZATION_REF,
            reasoning_effort="high",
            process_runner=self._runner,
            environment={"PATH": "safe", "CODEX_HOME": self.temporary.name},
        )
        proactive = ProactivePostgresStore(
            repository=self.repository,
            owner_id=self.owner,
            identity=self.identity,
        )
        proactive.save_preference(ProactivePreferenceRevision(
            owner_id=self.owner,
            revision=1,
            global_enabled=True,
            category_permissions={
                "owner_reminder": "allowed",
                "relationship_follow_up": "allowed",
            },
            allowed_channels=("web_inbox",),
            global_budget_per_24h=5,
            category_budget_per_24h={
                "owner_reminder": 4,
                "relationship_follow_up": 1,
            },
            authorization_ref="test-owner-explicit-chat-goal",
        ))
        goals = GoalService(repository=self.repository)
        planner = ExplicitChatGoalPlanner(
            repository=self.repository,
            owner_id=self.owner,
            provider=provider,
            goal_service=goals,
            proactive_store=proactive,
            owner_timezone="UTC",
        )
        service = InteractionService(
            owner_id=self.owner,
            identity=self.identity,
            repository=self.repository,
            context_builder=ContextBuilder(
                max_input_tokens=8_192, reserved_output_tokens=256
            ),
            router=Stage1Router(
                approved_cloud_provider_ids=frozenset({CODEX_CLI_PROVIDER_ID})
            ),
            provider=provider,
            retrieval_service=self.retrieval,
            request_binders={
                CODEX_CLI_PROVIDER_ID: partial(
                    bind_codex_cli_request, reasoning_effort="high"
                )
            },
            chat_goal_planner=planner,
        )
        explicit = await service.interact(InteractionCommand(
            message="帮我创建一个目标：这周把作业写完，并提醒我检查进度。",
            privacy_class=PrivacyClass.NORMAL,
            channel="web",
            idempotency_key=f"chat-goal:{uuid.uuid4()}",
        ))
        self.assertEqual(self.plan_calls, 1)
        self.assertEqual(len(goals.list(owner_id=self.owner)), 1)
        with self.repository.pool.connection() as connection:
            counts = connection.execute(
                """SELECT
                     (SELECT count(*) FROM havre.owner_chat_goal_plan_runs
                      WHERE owner_id=%s AND status='completed') AS plans,
                     (SELECT count(*) FROM havre.owner_chat_goal_actions
                      WHERE owner_id=%s) AS actions,
                     (SELECT count(*) FROM havre.proactive_work_items
                      WHERE owner_id=%s AND status='pending') AS reminders""",
                (self.owner, self.owner, self.owner),
            ).fetchone()
        self.assertEqual(dict(counts), {"plans": 1, "actions": 1, "reminders": 1})

        await service.interact(InteractionCommand(
            message="今天作业好多，我有点累。",
            privacy_class=PrivacyClass.NORMAL,
            channel="web",
            idempotency_key=f"ordinary:{uuid.uuid4()}",
        ))
        self.assertEqual(self.plan_calls, 1)
        self.assertEqual(len(goals.list(owner_id=self.owner)), 1)

        local_service = InteractionService(
            owner_id=self.owner,
            identity=self.identity,
            repository=self.repository,
            context_builder=ContextBuilder(
                max_input_tokens=8_192, reserved_output_tokens=256
            ),
            router=Stage1Router(),
            provider=DeterministicLocalProvider(),
            retrieval_service=self.retrieval,
            chat_goal_planner=planner,
        )
        await local_service.interact(InteractionCommand(
            message="帮我创建一个目标：这是 private 的事。",
            privacy_class=PrivacyClass.LOCAL_ONLY,
            channel="web",
            idempotency_key=f"private-goal:{uuid.uuid4()}",
        ))
        self.assertEqual(self.plan_calls, 1)
        self.assertEqual(len(goals.list(owner_id=self.owner)), 1)

        erased = self.repository.erase_source_event_derivatives(
            owner_id=self.owner, source_event_id=explicit.user_event_id
        )
        self.assertEqual(erased["goals"], 1)
        self.assertEqual(erased["owner_chat_goal_actions"], 1)
        self.assertEqual(erased["owner_chat_goal_plan_runs"], 1)
        self.assertGreaterEqual(erased["proactive_work_items"], 1)


if __name__ == "__main__":
    unittest.main()
