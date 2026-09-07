from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from functools import partial
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import psycopg

from companion.application import InteractionCommand, InteractionService
from companion.commitments.service import CommitmentBroker
from companion.context import ContextBuilder
from companion.identity import IdentityLoader
from companion.goals.models import GoalPriority, GoalTrack
from companion.memory import DeterministicEmbeddingProvider
from companion.persistence import PostgresRepository, apply_migrations
from companion.persistence.proactive import ProactivePostgresStore
from companion.policy import PrivacyClass
from companion.proactive import ProactivePreferenceRevision
from companion.product.relationship import (
    CONTINUATION_AUTHORIZATION_REF,
    CONTINUATION_REASONING_EFFORT,
    ContinuationPlan,
    ConversationContinuationService,
    LOCAL_TWO_BEAT_CONTINUATION_AUTHORIZATION_REF,
)
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


class LocalContinuationProvider(DeterministicLocalProvider):
    provider_id = "self-hosted-openai-compatible"
    model_version_id = "qwen3-8b-local-continuation-test"
    provider_adapter_version_id = "openai-compatible-local-test-v1"
    serving_config_version = "local-continuation-test-v1"
    output = json.dumps({
        "schema_version": 1,
        "send": True,
        "message": "等等，我还有点好奇——那碗面最离谱的是味道，还是口感？",
        "reason": "curiosity",
    }, ensure_ascii=False)


class RelationshipInitiativeContractTests(unittest.TestCase):
    def test_continuation_plan_requires_message_exactly_when_sending(self) -> None:
        plan = ContinuationPlan.parse_provider_text(LocalContinuationProvider.output)
        self.assertTrue(plan.send)
        with self.assertRaises(ValueError):
            ContinuationPlan.model_validate({
                "schema_version": 1, "send": False,
                "message": "still here", "reason": "not_suitable",
            })
        for message, reason in (
            ("是不是感觉轻松了很多？", "curiosity"),
            ("也许她只是藏着没说出口的担心？", "curiosity"),
            ("这运气真的太难得了。", "continue_topic"),
            ("听起来你今天真的挺辛苦的，要不要休息一下？", "curiosity"),
            ("是螺蛳粉吗？我上次吃的时候特别香。", "curiosity"),
        ):
            gated = ConversationContinuationService._quality_gate(
                ContinuationPlan(
                    schema_version=1, send=True, message=message, reason=reason
                )
            )
            self.assertFalse(gated.send)
        opinion = ConversationContinuationService._quality_gate(ContinuationPlan(
            schema_version=1,
            send=True,
            message="寸头还是算了吧。",
            reason="share_view",
        ))
        self.assertTrue(opinion.send)


@unittest.skipUnless(DATABASE_URL, "HAVRE_TEST_DATABASE_URL is required")
class RelationshipInitiativeIntegrationTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        assert DATABASE_URL is not None
        apply_migrations(DATABASE_URL, ROOT / "db" / "migrations")
        cls.identity = IdentityLoader(ROOT / "identity").load()
        cls.repository = PostgresRepository(DATABASE_URL)
        cls.repository.open()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.repository.close()

    async def asyncSetUp(self) -> None:
        self.owner = uuid4()
        self.repository.bootstrap_owner_and_identity(
            owner_id=self.owner, identity=self.identity
        )
        embedding = DeterministicEmbeddingProvider()
        self.repository.register_embedding_version(embedding.version)
        retrieval = RetrievalService(
            repository=self.repository, embedding_provider=embedding
        )
        self.retrieval = retrieval
        self.temporary = tempfile.TemporaryDirectory()
        self.addAsyncCleanup(self._cleanup)
        self.executable = Path(self.temporary.name) / "codex.exe"
        self.executable.touch()
        cloud = CodexCliProvider(
            executable=self.executable,
            enabled=True,
            explicit_authorization_ref=CODEX_OWNER_AUTOMATIC_AUTHORIZATION_REF,
            reasoning_effort="medium",
            process_runner=self._cloud_runner,
            environment={"PATH": "safe", "CODEX_HOME": self.temporary.name},
        )
        self.cloud_service = InteractionService(
            owner_id=self.owner,
            identity=self.identity,
            repository=self.repository,
            context_builder=ContextBuilder(
                max_input_tokens=8_192, reserved_output_tokens=256
            ),
            router=Stage1Router(
                approved_cloud_provider_ids=frozenset({CODEX_CLI_PROVIDER_ID})
            ),
            provider=cloud,
            retrieval_service=retrieval,
            request_binders={
                CODEX_CLI_PROVIDER_ID: partial(
                    bind_codex_cli_request, reasoning_effort="medium"
                )
            },
        )
        self.broker = CommitmentBroker(
            repository=self.repository, owner_id=self.owner
        )
        self.proactive = ProactivePostgresStore(
            repository=self.repository,
            owner_id=self.owner,
            identity=self.identity,
            commitment_broker=self.broker,
            relational_initiative_enabled=True,
        )
        self.proactive.save_preference(ProactivePreferenceRevision(
            owner_id=self.owner,
            revision=1,
            global_enabled=True,
            category_permissions={
                "owner_reminder": "allowed",
                "relationship_follow_up": "allowed",
                "conversation_continuation": "allowed",
            },
            allowed_channels=("web_inbox",),
            global_budget_per_24h=6,
            category_budget_per_24h={
                "owner_reminder": 3,
                "relationship_follow_up": 3,
                "conversation_continuation": 2,
            },
            cooldown_seconds=None,
            authorization_ref="synthetic-relationship-initiative-test",
        ))
        self.continuation_output = LocalContinuationProvider.output
        self.continuation_calls: list[str] = []
        self.continuation_provider = CodexCliProvider(
            executable=self.executable,
            enabled=True,
            explicit_authorization_ref=CODEX_OWNER_AUTOMATIC_AUTHORIZATION_REF,
            reasoning_effort=CONTINUATION_REASONING_EFFORT,
            process_runner=self._continuation_runner,
            environment={"PATH": "safe", "CODEX_HOME": self.temporary.name},
        )
        self.continuation = ConversationContinuationService(
            repository=self.repository,
            owner_id=self.owner,
            provider=self.continuation_provider,
            legacy_local_provider=LocalContinuationProvider(
                active_adapter_version_id=None,
                active_adapter_artifact_hash=None,
            ),
            proactive_store=self.proactive,
            commitment_broker=self.broker,
        )

    async def _cleanup(self) -> None:
        await self.cloud_service.provider.aclose()
        await self.continuation_provider.aclose()
        self.temporary.cleanup()

    async def _cloud_runner(self, args, stdin_text, _cwd, _environment, _timeout_ms):
        if args[-1] == "--version":
            return CodexProcessResult(0, "codex-cli 0.152.0\n", "")
        if args[1:] == ("login", "status"):
            return CodexProcessResult(0, "Logged in using ChatGPT\n", "")
        output = "听起来这碗面是真的很难吃，难吃到你都特地回来吐槽了。"
        stdout = "\n".join((
            json.dumps({"type": "thread.started", "thread_id": "thread-test"}),
            json.dumps({"type": "turn.started"}),
            json.dumps({
                "type": "item.completed",
                "item": {"type": "agent_message", "text": output},
            }, ensure_ascii=False),
            json.dumps({
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 120, "cached_input_tokens": 0,
                    "output_tokens": 30, "reasoning_output_tokens": 5,
                },
            }),
        ))
        return CodexProcessResult(0, stdout, "")

    async def _continuation_runner(
        self, args, stdin_text, _cwd, _environment, _timeout_ms
    ):
        if args[-1] == "--version":
            return CodexProcessResult(0, "codex-cli 0.152.0\n", "")
        if args[1:] == ("login", "status"):
            return CodexProcessResult(0, "Logged in using ChatGPT\n", "")
        self.continuation_calls.append(stdin_text)
        stdout = "\n".join((
            json.dumps({"type": "thread.started", "thread_id": "continuation-test"}),
            json.dumps({"type": "turn.started"}),
            json.dumps({
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "text": self.continuation_output,
                },
            }, ensure_ascii=False),
            json.dumps({
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 180,
                    "cached_input_tokens": 0,
                    "output_tokens": 45,
                    "reasoning_output_tokens": 10,
                },
            }),
        ))
        return CodexProcessResult(0, stdout, "")

    async def _turn(self, message: str):
        return await self.cloud_service.interact(InteractionCommand(
            message=message,
            privacy_class=PrivacyClass.NORMAL,
            memory_eligible=True,
            channel="web",
            idempotency_key=f"relationship-source:{uuid4()}",
        ))

    def _record(self, turn, message: str):
        user_event = self.repository.event_by_id(
            owner_id=self.owner, event_id=turn.user_event_id
        )
        assistant_event = self.repository.event_by_id(
            owner_id=self.owner, event_id=turn.assistant_event_id
        )
        plan = self.cloud_service.response_planner.plan(
            request_id=turn.request_id,
            trace_id=turn.trace_id,
            owner_id=self.owner,
            message=message,
            source_refs=(f"event/{turn.user_event_id}",),
        )
        run_id = self.continuation.record_candidate(
            user_event=user_event,
            assistant_event=assistant_event,
            response_plan=plan,
            user_message=message,
            assistant_message=turn.content,
            selected_provider_id=turn.provider_id,
            execution_environment="cloud",
        )
        self.assertIsNotNone(run_id)
        return run_id

    async def test_first_reply_question_still_creates_one_minute_beat(self) -> None:
        message = "今天那碗面真的太难吃了。"
        turn = await self._turn(message)
        user_event = self.repository.event_by_id(
            owner_id=self.owner, event_id=turn.user_event_id
        )
        assistant_event = self.repository.event_by_id(
            owner_id=self.owner, event_id=turn.assistant_event_id
        )
        plan = self.cloud_service.response_planner.plan(
            request_id=turn.request_id,
            trace_id=turn.trace_id,
            owner_id=self.owner,
            message=message,
            source_refs=(f"event/{turn.user_event_id}",),
        )
        run_id = self.continuation.record_candidate(
            user_event=user_event,
            assistant_event=assistant_event,
            response_plan=plan,
            user_message=message,
            assistant_message="这么难吃啊，是什么面，在哪儿吃的？",
            selected_provider_id=turn.provider_id,
            execution_environment="cloud",
        )
        self.assertIsNotNone(run_id)
        with self.repository.pool.connection() as connection:
            receipt = connection.execute(
                """SELECT beat_index,not_before,expires_at
                   FROM havre.owner_conversation_continuation_runs
                   WHERE owner_id=%s AND continuation_run_id=%s""",
                (self.owner, run_id),
            ).fetchone()
        self.assertEqual(receipt["beat_index"], 1)
        self.assertEqual(
            receipt["not_before"], assistant_event.recorded_at + timedelta(minutes=1)
        )

    def _lease_for_test(self, run_id):
        with self.repository.pool.connection() as connection, connection.transaction():
            row = connection.execute(
                """UPDATE havre.owner_conversation_continuation_runs
                   SET status='leased',lease_owner='relationship-test',
                       lease_expires_at=statement_timestamp()+interval '5 minutes',
                       attempt_count=attempt_count+1
                   WHERE owner_id=%s AND continuation_run_id=%s
                   RETURNING *""",
                (self.owner, run_id),
            ).fetchone()
        return dict(row)

    async def test_gpt_second_beat_is_queued_after_exact_source_receipt(self) -> None:
        message = "今天那碗面真的太难吃了。"
        turn = await self._turn(message)
        run_id = self._record(turn, message)
        with self.repository.pool.connection() as connection:
            receipt = connection.execute(
                """SELECT status,beat_index,not_before,expires_at
                   FROM havre.owner_conversation_continuation_runs
                   WHERE owner_id=%s AND continuation_run_id=%s""",
                (self.owner, run_id),
            ).fetchone()
        assistant = self.repository.event_by_id(
            owner_id=self.owner, event_id=turn.assistant_event_id
        )
        self.assertEqual(receipt["status"], "pending")
        self.assertEqual(receipt["beat_index"], 1)
        self.assertEqual(
            receipt["not_before"], assistant.recorded_at + timedelta(minutes=1)
        )
        self.assertEqual(
            receipt["expires_at"], assistant.recorded_at + timedelta(minutes=16)
        )
        leased = self._lease_for_test(run_id)
        with patch.object(self.continuation, "_claim", return_value=leased):
            result = await self.continuation.run_once(worker_id="relationship-test")
        self.assertEqual(result["status"], "completed")
        with self.repository.pool.connection() as connection:
            row = connection.execute(
                """SELECT status,provider_id,reasoning_effort,work_item_id
                   FROM havre.owner_conversation_continuation_runs
                   WHERE owner_id=%s AND continuation_run_id=%s""",
                (self.owner, run_id),
            ).fetchone()
            work = connection.execute(
                """SELECT command_payload FROM havre.proactive_work_items
                   WHERE owner_id=%s AND work_item_id=%s""",
                (self.owner, row["work_item_id"]),
            ).fetchone()["command_payload"]
        self.assertEqual(row["provider_id"], CODEX_CLI_PROVIDER_ID)
        self.assertEqual(row["reasoning_effort"], CONTINUATION_REASONING_EFFORT)
        self.assertEqual(len(self.continuation_calls), 1)
        self.assertIn(CONTINUATION_AUTHORIZATION_REF, self.continuation_calls[0])
        self.assertEqual(work["reason_code"], "conversation_continuation")
        self.assertEqual(work["source_kind"], "conversation")
        self.assertEqual(work["category"], "conversation_continuation")

    async def test_preexisting_local_receipt_keeps_its_original_provider(self) -> None:
        message = "刚才看见一只特别神气的小狗。"
        turn = await self._turn(message)
        user = self.repository.event_by_id(
            owner_id=self.owner, event_id=turn.user_event_id
        )
        assistant = self.repository.event_by_id(
            owner_id=self.owner, event_id=turn.assistant_event_id
        )
        run_id = uuid4()
        with self.repository.pool.connection() as connection, connection.transaction():
            connection.execute(
                """INSERT INTO havre.owner_conversation_continuation_runs (
                       continuation_run_id,owner_id,source_user_event_id,
                       source_user_content_hash,source_assistant_event_id,
                       source_assistant_content_hash,session_id,beat_index,
                       prior_continuation_run_id,status,not_before,expires_at,
                       authorization_ref
                   ) VALUES (%s,%s,%s,%s,%s,%s,%s,1,NULL,'pending',%s,%s,%s)""",
                (
                    run_id,
                    self.owner,
                    user.event_id,
                    user.content_hash,
                    assistant.event_id,
                    assistant.content_hash,
                    user.session_id,
                    assistant.recorded_at + timedelta(minutes=1),
                    assistant.recorded_at + timedelta(minutes=16),
                    LOCAL_TWO_BEAT_CONTINUATION_AUTHORIZATION_REF,
                ),
            )
        leased = self._lease_for_test(run_id)
        with patch.object(self.continuation, "_claim", return_value=leased):
            result = await self.continuation.run_once(worker_id="relationship-test")
        self.assertEqual(result["status"], "completed")
        with self.repository.pool.connection() as connection:
            row = connection.execute(
                """SELECT provider_id,reasoning_effort
                   FROM havre.owner_conversation_continuation_runs
                   WHERE owner_id=%s AND continuation_run_id=%s""",
                (self.owner, run_id),
            ).fetchone()
        self.assertEqual(row["provider_id"], "self-hosted-openai-compatible")
        self.assertIsNone(row["reasoning_effort"])
        self.assertEqual(self.continuation_calls, [])

    async def test_database_rejects_local_receipt_for_new_gpt_authorization(
        self,
    ) -> None:
        message = "今天路上的风特别大。"
        turn = await self._turn(message)
        run_id = self._record(turn, message)
        self._lease_for_test(run_id)
        digest = "sha256:" + "a" * 64
        with self.assertRaises(psycopg.errors.CheckViolation):
            with self.repository.pool.connection() as connection, connection.transaction():
                connection.execute(
                    """UPDATE havre.owner_conversation_continuation_runs
                       SET status='no_action',lease_owner=NULL,lease_expires_at=NULL,
                           inference_request_id=%s,request_binding_hash=%s,
                           provider_id='self-hosted-openai-compatible',
                           model_version_id='qwen3-8b-local-continuation-test',
                           provider_adapter_version_id='openai-compatible-local-test-v1',
                           serving_config_version='local-continuation-test-v1',
                           reasoning_effort=NULL,
                           result='{"schema_version":1,"send":false,
                                   "message":null,"reason":"not_suitable"}'::jsonb,
                           response_content_hash=%s,error_code=NULL
                       WHERE owner_id=%s AND continuation_run_id=%s""",
                    (uuid4(), digest, digest, self.owner, run_id),
                )

    async def test_gpt_failure_never_falls_back_to_legacy_local_provider(
        self,
    ) -> None:
        message = "刚才路边那只猫一直盯着我看。"
        turn = await self._turn(message)
        run_id = self._record(turn, message)
        leased = self._lease_for_test(run_id)
        cloud_generate = AsyncMock(side_effect=RuntimeError("synthetic GPT outage"))
        local_generate = AsyncMock(
            wraps=self.continuation.legacy_local_provider.generate
        )
        with (
            patch.object(self.continuation, "_claim", return_value=leased),
            patch.object(self.continuation.provider, "generate", cloud_generate),
            patch.object(
                self.continuation.legacy_local_provider,
                "generate",
                local_generate,
            ),
        ):
            result = await self.continuation.run_once(
                worker_id="relationship-test"
            )
        self.assertEqual(result["status"], "retryable_failed")
        cloud_generate.assert_awaited_once()
        local_generate.assert_not_awaited()
        with self.repository.pool.connection() as connection:
            row = connection.execute(
                """SELECT status,provider_id,work_item_id,error_code
                   FROM havre.owner_conversation_continuation_runs
                   WHERE owner_id=%s AND continuation_run_id=%s""",
                (self.owner, run_id),
            ).fetchone()
        self.assertEqual(row["status"], "retryable_failed")
        self.assertIsNone(row["provider_id"])
        self.assertIsNone(row["work_item_id"])
        self.assertEqual(row["error_code"], "RuntimeError")

    async def test_second_beat_waits_30_minutes_after_real_first_delivery_then_stops(
        self,
    ) -> None:
        message = "今天那碗面真的太难吃了。"
        turn = await self._turn(message)
        first_run_id = self._record(turn, message)
        first_lease = self._lease_for_test(first_run_id)
        with patch.object(self.continuation, "_claim", return_value=first_lease):
            first_plan = await self.continuation.run_once(
                worker_id="relationship-test"
            )
        first_delivery = self.proactive.run_work_once(
            worker_id="relationship-delivery-test"
        )
        self.assertEqual(first_delivery["status"], "succeeded")
        second_run_id = self.continuation.schedule_second_beat()
        self.assertIsNotNone(second_run_id)
        self.assertIsNone(self.continuation.schedule_second_beat())
        with self.repository.pool.connection() as connection:
            second = connection.execute(
                """SELECT beat_index,prior_continuation_run_id,not_before,expires_at
                   FROM havre.owner_conversation_continuation_runs
                   WHERE owner_id=%s AND continuation_run_id=%s""",
                (self.owner, second_run_id),
            ).fetchone()
            visible_at = connection.execute(
                """SELECT max(attempt.visible_at) AS visible_at
                   FROM havre.proactive_work_items work
                   JOIN havre.proactive_delivery_attempts attempt
                     ON attempt.owner_id=work.owner_id
                    AND attempt.proposal_id=work.proposal_id
                   WHERE work.owner_id=%s AND work.work_item_id=%s
                     AND attempt.status='delivered'""",
                (self.owner, first_plan["work_item_id"]),
            ).fetchone()["visible_at"]
        self.assertEqual(second["beat_index"], 2)
        self.assertEqual(second["prior_continuation_run_id"], first_run_id)
        self.assertEqual(second["not_before"], visible_at + timedelta(minutes=30))
        self.assertEqual(second["expires_at"], visible_at + timedelta(minutes=45))

        self.continuation_output = json.dumps({
            "schema_version": 1,
            "send": True,
            "message": "我又想到一个——它到底是调味翻车，还是面本身就很怪？",
            "reason": "curiosity",
        }, ensure_ascii=False)
        second_lease = self._lease_for_test(second_run_id)
        with patch.object(self.continuation, "_claim", return_value=second_lease):
            second_plan = await self.continuation.run_once(
                worker_id="relationship-test"
            )
        self.assertEqual(second_plan["status"], "completed")
        second_delivery = self.proactive.run_work_once(
            worker_id="relationship-delivery-test"
        )
        self.assertEqual(second_delivery["status"], "succeeded")
        self.assertIsNone(self.continuation.schedule_second_beat())
        with self.repository.pool.connection() as connection:
            count = connection.execute(
                """SELECT count(*) AS value
                   FROM havre.owner_conversation_continuation_runs
                   WHERE owner_id=%s AND source_assistant_event_id=%s""",
                (self.owner, turn.assistant_event_id),
            ).fetchone()["value"]
        self.assertEqual(count, 2)
        erased = self.repository.erase_source_event_derivatives(
            owner_id=self.owner, source_event_id=turn.assistant_event_id
        )
        self.assertEqual(erased["owner_conversation_continuation_runs"], 2)
        self.assertEqual(erased["proactive_work_items"], 2)
        self.assertEqual(self.repository.audit_provenance_integrity(), [])

    async def test_owner_reply_after_first_delivery_prevents_second_beat(self) -> None:
        message = "刚才看见一只特别神气的小狗。"
        turn = await self._turn(message)
        first_run_id = self._record(turn, message)
        first_lease = self._lease_for_test(first_run_id)
        with patch.object(self.continuation, "_claim", return_value=first_lease):
            await self.continuation.run_once(worker_id="relationship-test")
        delivered = self.proactive.run_work_once(
            worker_id="relationship-delivery-test"
        )
        self.assertEqual(delivered["status"], "succeeded")
        await self._turn("真的，它还冲我甩了两下尾巴。")
        self.assertIsNone(self.continuation.schedule_second_beat())

    async def test_new_owner_message_cancels_before_local_planning(self) -> None:
        message = "我今天真的有点累。"
        first = await self._turn(message)
        run_id = self._record(first, message)
        await self._turn("刚才朋友给我打电话了，我们聊了一会儿。")
        leased = self._lease_for_test(run_id)
        with patch.object(self.continuation, "_claim", return_value=leased):
            result = await self.continuation.run_once(worker_id="relationship-test")
        self.assertEqual(result, {"status": "cancelled", "reason": "conversation_moved"})

    async def test_relationship_work_defers_while_owner_is_chatting(self) -> None:
        message = "刚才路上看到一只特别神气的小狗。"
        turn = await self._turn(message)
        run_id = self._record(turn, message)
        leased = self._lease_for_test(run_id)
        with patch.object(self.continuation, "_claim", return_value=leased):
            planned = await self.continuation.run_once(worker_id="relationship-test")
        request_id = uuid4()
        self.broker.begin_interaction_activity(request_id=request_id)
        try:
            result = self.proactive.run_work_once(worker_id="relationship-delivery-test")
        finally:
            self.broker.end_interaction_activity(request_id=request_id)
        self.assertEqual(result["status"], "deferred")
        with self.repository.pool.connection() as connection:
            row = connection.execute(
                """SELECT status,request_id,proposal_id
                   FROM havre.proactive_work_items
                   WHERE owner_id=%s AND work_item_id=%s""",
                (self.owner, planned["work_item_id"]),
            ).fetchone()
            inbox_count = connection.execute(
                "SELECT count(*) AS value FROM havre.proactive_inbox_messages "
                "WHERE owner_id=%s",
                (self.owner,),
            ).fetchone()["value"]
        self.assertEqual(dict(row), {
            "status": "pending", "request_id": None, "proposal_id": None,
        })
        self.assertEqual(inbox_count, 0)

    async def test_new_owner_turn_cancels_already_planned_continuation(self) -> None:
        message = "我今天第一次试了那家新开的咖啡店。"
        turn = await self._turn(message)
        run_id = self._record(turn, message)
        leased = self._lease_for_test(run_id)
        with patch.object(self.continuation, "_claim", return_value=leased):
            planned = await self.continuation.run_once(worker_id="relationship-test")
        await self._turn("后来朋友来找我了，我们已经聊到别的事了。")
        result = self.proactive.run_work_once(worker_id="relationship-delivery-test")
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["error_code"], "relationship_conversation_moved")
        with self.repository.pool.connection() as connection:
            row = connection.execute(
                """SELECT status,last_error_code FROM havre.proactive_work_items
                   WHERE owner_id=%s AND work_item_id=%s""",
                (self.owner, planned["work_item_id"]),
            ).fetchone()
        self.assertEqual(dict(row), {
            "status": "cancelled",
            "last_error_code": "relationship_conversation_moved",
        })

    async def test_unanswered_relationship_cadence_is_24h_then_72h_then_pause(self) -> None:
        turn = await self._turn("最近傍晚出去走走还挺舒服的。")
        source = self.repository.event_by_id(
            owner_id=self.owner, event_id=turn.user_event_id
        )

        def deliver(index: int, *, category: str = "relationship_follow_up") -> None:
            now = datetime.now(UTC)
            self.proactive.execute_fixture(
                trigger_type=f"relationship_cadence_{index}",
                source_kind="memory" if category == "relationship_follow_up" else "goal",
                source_refs=(f"event/{turn.user_event_id}",),
                subject_refs=(f"cadence/{index}",),
                category=category,
                reason_code=(
                    "relationship_follow_up"
                    if category == "relationship_follow_up"
                    else "owner_goal_reminder"
                ),
                reason_summary=f"cadence message {index}",
                intended_benefit="verify bounded cadence",
                data_policy=source.data_policy,
                preference_revision=1,
                idempotency_key=f"cadence-execution:{uuid4()}",
                observed_at=source.recorded_at,
                earliest_eligible_at=now - timedelta(seconds=1),
                expires_at=now + timedelta(hours=1),
                deduplication_key=f"cadence-dedupe:{uuid4()}",
            )

        deliver(1)
        first = self.proactive.relationship_cadence_state()
        self.assertEqual(first["unanswered_count"], 1)
        self.assertEqual(
            first["next_eligible_at"], first["last_touch_at"] + timedelta(hours=24)
        )
        deliver(99, category="owner_reminder")
        self.assertEqual(
            self.proactive.relationship_cadence_state()["unanswered_count"], 1
        )
        deliver(2)
        second = self.proactive.relationship_cadence_state()
        self.assertEqual(second["unanswered_count"], 2)
        self.assertEqual(
            second["next_eligible_at"], second["last_touch_at"] + timedelta(hours=72)
        )
        deliver(3)
        third = self.proactive.relationship_cadence_state()
        self.assertEqual(third["unanswered_count"], 3)
        self.assertTrue(third["paused"])
        await self._turn("我回来啦，刚才在外面。")
        reset = self.proactive.relationship_cadence_state()
        self.assertEqual(reset["unanswered_count"], 0)
        self.assertFalse(reset["paused"])

    async def test_exact_assistant_source_erasure_removes_run_and_queue(self) -> None:
        message = "今天的晚霞颜色特别夸张。"
        turn = await self._turn(message)
        run_id = self._record(turn, message)
        leased = self._lease_for_test(run_id)
        with patch.object(self.continuation, "_claim", return_value=leased):
            planned = await self.continuation.run_once(worker_id="relationship-test")
        erased = self.repository.erase_source_event_derivatives(
            owner_id=self.owner, source_event_id=turn.assistant_event_id
        )
        self.assertEqual(erased["owner_conversation_continuation_runs"], 1)
        self.assertEqual(erased["proactive_work_items"], 1)
        with self.repository.pool.connection() as connection:
            remaining = connection.execute(
                """SELECT
                     (SELECT count(*) FROM havre.owner_conversation_continuation_runs
                      WHERE owner_id=%s AND continuation_run_id=%s) AS runs,
                     (SELECT count(*) FROM havre.proactive_work_items
                      WHERE owner_id=%s AND work_item_id=%s) AS work,
                     (SELECT count(*) FROM havre.events
                      WHERE owner_id=%s AND event_id=%s) AS raw_source""",
                (
                    self.owner, run_id,
                    self.owner, planned["work_item_id"],
                    self.owner, turn.assistant_event_id,
                ),
            ).fetchone()
        self.assertEqual(dict(remaining), {"runs": 0, "work": 0, "raw_source": 1})
        self.assertEqual(self.repository.audit_provenance_integrity(), [])

    async def test_prior_shared_history_erasure_closes_delayed_derivatives(self):
        first = await self._turn("读书会上我一直捏着绿色笔记本，后来终于敢发言了。")
        message = "刚才那个瞬间我还挺开心的，大家真的在听。"
        turn = await self._turn(message)
        run_id = self._record(turn, message)
        leased = self._lease_for_test(run_id)
        with patch.object(self.continuation, "_claim", return_value=leased):
            planned = await self.continuation.run_once(worker_id="relationship-test")
        self.assertIsNotNone(planned["work_item_id"])
        erased = self.repository.erase_source_event_derivatives(
            owner_id=self.owner, source_event_id=first.user_event_id
        )
        with self.repository.pool.connection() as connection:
            self.assertIsNone(connection.execute(
                "SELECT 1 FROM havre.owner_conversation_continuation_runs WHERE owner_id=%s AND continuation_run_id=%s",
                (self.owner, run_id),
            ).fetchone())
            self.assertIsNone(connection.execute(
                "SELECT 1 FROM havre.proactive_work_items WHERE owner_id=%s AND work_item_id=%s",
                (self.owner, planned["work_item_id"]),
            ).fetchone())
        self.assertEqual(self.repository.audit_provenance_integrity(), [])

    async def test_terminal_provider_constraint_rejects_null_and_unknown(self):
        message = "今天读书会挺开心的。"
        turn = await self._turn(message)
        run_id = self._record(turn, message)
        self._lease_for_test(run_id)
        for provider in (None, "unapproved-provider"):
            with self.subTest(provider=provider), self.repository.pool.connection() as connection:
                with self.assertRaises(psycopg.errors.CheckViolation) as caught:
                    with connection.transaction():
                        connection.execute(
                            """UPDATE havre.owner_conversation_continuation_runs
                            SET status='no_action',lease_owner=NULL,lease_expires_at=NULL,
                                inference_request_id=%s,request_binding_hash=%s,
                                provider_id=%s,model_version_id='gpt-5.6-sol',
                                provider_adapter_version_id='codex-cli-provider-v3-complete-reply',
                                serving_config_version='codex-cli-reply-only-no-tools-v2-high',
                                reasoning_effort='high',result='{"schema_version":1,"send":false,"message":null,"reason":"not_suitable"}',
                                response_content_hash=%s,error_code=NULL
                            WHERE owner_id=%s AND continuation_run_id=%s""",
                            (uuid4(),"sha256:"+"a"*64,provider,"sha256:"+"b"*64,self.owner,run_id),
                        )
                self.assertEqual(caught.exception.diag.constraint_name,
                                 "owner_conversation_continuation_terminal_provider_check")

    async def test_daily_goal_fill_is_stable_random_and_deduplicated(self) -> None:
        turn = await self._turn("提醒我继续准备下周的小测。")
        goal = self.repository.create_goal(
            owner_id=self.owner,
            track=GoalTrack.REALITY,
            title="准备下周的小测",
            why="owner explicitly asked for an ongoing reminder",
            source_event_id=turn.user_event_id,
            priority=GoalPriority.NORMAL,
        )
        zone = ZoneInfo("America/Chicago")
        seed_local = datetime.now(zone).replace(
            hour=11, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)
        self.proactive.enqueue_goal_reminder(
            goal_id=goal.goal_id,
            reminder_kind="start_window",
            reminder_text="明天开始记得准备小测。",
            remind_at=seed_local,
            expires_at=seed_local.replace(hour=22),
            idempotency_key=f"daily-goal-seed:{goal.goal_id}",
        )
        second_goal = self.repository.create_goal(
            owner_id=self.owner,
            track=GoalTrack.REALITY,
            title="整理本周课堂笔记",
            why="verify that daily filler does not create one message per Goal",
            source_event_id=turn.user_event_id,
            priority=GoalPriority.NORMAL,
        )
        self.proactive.enqueue_goal_reminder(
            goal_id=second_goal.goal_id,
            reminder_kind="start_window",
            reminder_text="明天开始整理课堂笔记。",
            remind_at=seed_local + timedelta(minutes=5),
            expires_at=seed_local.replace(hour=22),
            idempotency_key=f"daily-goal-seed:{second_goal.goal_id}",
        )
        after_seed = seed_local.replace(hour=21)
        first = self.proactive.enqueue_daily_goal_check_ins(
            timezone_name="America/Chicago", now=after_seed
        )
        second = self.proactive.enqueue_daily_goal_check_ins(
            timezone_name="America/Chicago", now=after_seed
        )
        self.assertEqual(first["eligible_goals"], 2)
        self.assertEqual(first["scheduled"], 1)
        self.assertEqual(second["scheduled"], 0)
        self.assertEqual(second["skipped_existing"], 1)
        scheduled = first["scheduled_items"][0]["remind_at"].astimezone(zone)
        self.assertEqual(scheduled.date(), after_seed.date() + timedelta(days=1))
        self.assertGreaterEqual(scheduled.hour * 60 + scheduled.minute, 10 * 60 + 30)
        self.assertLessEqual(scheduled.hour * 60 + scheduled.minute, 20 * 60 + 29)

    async def test_direct_sql_rejects_wrong_source_hash(self) -> None:
        message = "刚刚吃到一个特别奇怪的甜点。"
        turn = await self._turn(message)
        user = self.repository.event_by_id(
            owner_id=self.owner, event_id=turn.user_event_id
        )
        assistant = self.repository.event_by_id(
            owner_id=self.owner, event_id=turn.assistant_event_id
        )
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
            with self.repository.pool.connection() as connection, connection.transaction():
                connection.execute(
                    """INSERT INTO havre.owner_conversation_continuation_runs (
                           continuation_run_id,owner_id,source_user_event_id,
                           source_user_content_hash,source_assistant_event_id,
                           source_assistant_content_hash,session_id,status,not_before,
                           expires_at,authorization_ref
                       ) VALUES (%s,%s,%s,%s,%s,%s,%s,'pending',%s,%s,%s)""",
                    (
                        uuid4(), self.owner, user.event_id, "sha256:" + "0" * 64,
                        assistant.event_id, assistant.content_hash, user.session_id,
                        assistant.recorded_at + timedelta(seconds=30),
                        assistant.recorded_at + timedelta(minutes=15),
                        "product-owner/local-conversation-continuation-2026-09-04",
                    ),
                )

    async def test_direct_sql_rejects_wrong_first_beat_timing(self) -> None:
        message = "刚才路边那只猫一直盯着我看。"
        turn = await self._turn(message)
        user = self.repository.event_by_id(
            owner_id=self.owner, event_id=turn.user_event_id
        )
        assistant = self.repository.event_by_id(
            owner_id=self.owner, event_id=turn.assistant_event_id
        )
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
            with self.repository.pool.connection() as connection, connection.transaction():
                connection.execute(
                    """INSERT INTO havre.owner_conversation_continuation_runs (
                           continuation_run_id,owner_id,source_user_event_id,
                           source_user_content_hash,source_assistant_event_id,
                           source_assistant_content_hash,session_id,beat_index,status,
                           not_before,expires_at,authorization_ref
                       ) VALUES (%s,%s,%s,%s,%s,%s,%s,1,'pending',%s,%s,%s)""",
                    (
                        uuid4(), self.owner, user.event_id, user.content_hash,
                        assistant.event_id, assistant.content_hash, user.session_id,
                        assistant.recorded_at + timedelta(seconds=30),
                        assistant.recorded_at + timedelta(minutes=16),
                        "product-owner/two-beat-friend-conversation-2026-09-04",
                    ),
                )

    async def test_direct_sql_rejects_second_beat_without_delivered_first(self) -> None:
        message = "刚才路边那只猫一直盯着我看。"
        turn = await self._turn(message)
        first_run_id = self._record(turn, message)
        user = self.repository.event_by_id(
            owner_id=self.owner, event_id=turn.user_event_id
        )
        assistant = self.repository.event_by_id(
            owner_id=self.owner, event_id=turn.assistant_event_id
        )
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
            with self.repository.pool.connection() as connection, connection.transaction():
                connection.execute(
                    """INSERT INTO havre.owner_conversation_continuation_runs (
                           continuation_run_id,owner_id,source_user_event_id,
                           source_user_content_hash,source_assistant_event_id,
                           source_assistant_content_hash,session_id,beat_index,
                           prior_continuation_run_id,status,not_before,expires_at,
                           authorization_ref
                       ) VALUES (%s,%s,%s,%s,%s,%s,%s,2,%s,'pending',%s,%s,%s)""",
                    (
                        uuid4(), self.owner, user.event_id, user.content_hash,
                        assistant.event_id, assistant.content_hash, user.session_id,
                        first_run_id,
                        assistant.recorded_at + timedelta(minutes=31),
                        assistant.recorded_at + timedelta(minutes=46),
                        "product-owner/two-beat-friend-conversation-2026-09-04",
                    ),
                )

    async def test_direct_sql_rejects_mismatched_turn_pair(self) -> None:
        first = await self._turn("今天路上的风特别大。")
        second = await self._turn("不过晚霞还挺好看的。")
        user = self.repository.event_by_id(
            owner_id=self.owner, event_id=first.user_event_id
        )
        assistant = self.repository.event_by_id(
            owner_id=self.owner, event_id=second.assistant_event_id
        )
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
            with self.repository.pool.connection() as connection, connection.transaction():
                connection.execute(
                    """INSERT INTO havre.owner_conversation_continuation_runs (
                           continuation_run_id,owner_id,source_user_event_id,
                           source_user_content_hash,source_assistant_event_id,
                           source_assistant_content_hash,session_id,status,not_before,
                           expires_at,authorization_ref
                       ) VALUES (%s,%s,%s,%s,%s,%s,%s,'pending',%s,%s,%s)""",
                    (
                        uuid4(), self.owner, user.event_id, user.content_hash,
                        assistant.event_id, assistant.content_hash, user.session_id,
                        assistant.recorded_at + timedelta(seconds=30),
                        assistant.recorded_at + timedelta(minutes=15),
                        "product-owner/local-conversation-continuation-2026-09-04",
                    ),
                )

    async def test_direct_sql_rejects_local_private_source(self) -> None:
        local_service = InteractionService(
            owner_id=self.owner,
            identity=self.identity,
            repository=self.repository,
            context_builder=ContextBuilder(
                max_input_tokens=8_192, reserved_output_tokens=256
            ),
            router=Stage1Router(approved_cloud_provider_ids=frozenset()),
            provider=LocalContinuationProvider(
                active_adapter_version_id=None, active_adapter_artifact_hash=None
            ),
            retrieval_service=self.retrieval,
        )
        private = await local_service.interact(InteractionCommand(
            message="这是一条只允许留在本机的私人消息。",
            privacy_class=PrivacyClass.LOCAL_ONLY,
            memory_eligible=True,
            channel="web",
            idempotency_key=f"relationship-private-source:{uuid4()}",
        ))
        user = self.repository.event_by_id(
            owner_id=self.owner, event_id=private.user_event_id
        )
        assistant = self.repository.event_by_id(
            owner_id=self.owner, event_id=private.assistant_event_id
        )
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
            with self.repository.pool.connection() as connection, connection.transaction():
                connection.execute(
                    """INSERT INTO havre.owner_conversation_continuation_runs (
                           continuation_run_id,owner_id,source_user_event_id,
                           source_user_content_hash,source_assistant_event_id,
                           source_assistant_content_hash,session_id,status,not_before,
                           expires_at,authorization_ref
                       ) VALUES (%s,%s,%s,%s,%s,%s,%s,'pending',%s,%s,%s)""",
                    (
                        uuid4(), self.owner, user.event_id, user.content_hash,
                        assistant.event_id, assistant.content_hash, user.session_id,
                        assistant.recorded_at + timedelta(seconds=30),
                        assistant.recorded_at + timedelta(minutes=15),
                        "product-owner/local-conversation-continuation-2026-09-04",
                    ),
                )

    async def test_direct_sql_rejects_illegal_pending_transition(self) -> None:
        message = "今天在公园里看见好多小松鼠。"
        turn = await self._turn(message)
        run_id = self._record(turn, message)
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
            with self.repository.pool.connection() as connection, connection.transaction():
                connection.execute(
                    """UPDATE havre.owner_conversation_continuation_runs
                       SET status='retryable_failed',error_code='synthetic_attack'
                       WHERE owner_id=%s AND continuation_run_id=%s""",
                    (self.owner, run_id),
                )
