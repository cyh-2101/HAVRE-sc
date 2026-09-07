from __future__ import annotations

import json
import os
import tempfile
import unittest
import uuid
from datetime import UTC, date, datetime, time, timedelta
from functools import partial
from pathlib import Path

import psycopg

from companion.application import InteractionCommand, InteractionService
from companion.context import ContextBuilder
from companion.identity import IdentityLoader
from companion.memory import DeterministicEmbeddingProvider
from companion.persistence import PostgresRepository, apply_migrations
from companion.persistence.operations import Stage10PostgresStore
from companion.operations.ledger import ErasureLedger
from companion.policy import PrivacyClass
from companion.product.diary_intelligence import (
    DiaryIntelligenceResult,
    DiaryIntelligenceService,
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


class DiaryIntelligenceContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = DiaryIntelligenceService(
            repository=None,  # contract-only tests never touch persistence
            owner_id=uuid.uuid4(),
            provider=None,
            embedding_provider=None,
        )
        self.source_id = uuid.uuid4()
        self.cloud_event = {
            "event_id": self.source_id,
            "event_type": "USER_MESSAGE",
            "role": "user",
            "content": "我长期偏好先看结论，再看必要证据。",
            "content_hash": "sha256:" + "1" * 64,
            "recorded_at": datetime.now(UTC),
            "privacy_class": "NORMAL",
            "memory_eligible": True,
            "cloud_eligible": True,
            "disposition": "cloud_summary",
        }

    def test_result_requires_short_first_person_diary_and_plain_json(self) -> None:
        accepted = DiaryIntelligenceResult.parse_provider_text(json.dumps({
            "schema_version": 1,
            "include_diary": True,
            "title": "更清楚的表达",
            "diary_text": "我今天把自己希望怎样沟通说得更清楚了。",
            "memory_updates": [],
            "user_model_updates": [],
            "quality_review": ["too_verbose"],
        }, ensure_ascii=False))
        self.assertTrue(accepted.include_diary)
        with self.assertRaisesRegex(ValueError, "first-person"):
            DiaryIntelligenceResult.parse_provider_text(json.dumps({
                "schema_version": 1,
                "include_diary": True,
                "title": "一段记录",
                "diary_text": "用户说清楚了自己的偏好。",
                "memory_updates": [], "user_model_updates": [],
                "quality_review": [],
            }, ensure_ascii=False))
        with self.assertRaisesRegex(ValueError, "markdown fence"):
            DiaryIntelligenceResult.parse_provider_text("```json\n{}\n```")

    def test_invalid_optional_provider_enums_do_not_discard_valid_diary(self) -> None:
        parsed = DiaryIntelligenceResult.parse_provider_text(json.dumps({
            "schema_version": 2,
            "include_diary": True,
            "title": "记下新的偏好",
            "diary_text": "我今天更清楚地说出了自己喜欢怎样聊天。",
            "memory_updates": [],
            "user_model_updates": [{
                "source_event_id": str(self.source_id),
                "source_quote": "我长期偏好先看结论，再看必要证据。",
                "belief_key": "communication-conclusion-first",
                "statement": "我偏好先看结论，再看必要证据。",
                "belief_type": "communication_preference",
                "confidence": 0.88,
            }],
            "quality_review": ["too_verbose", "context_awareness"],
            "improvement_suggestions": [{
                "category": "overconfident_claim",
                "observation": "回复说得太确定。",
                "recommendation": "按证据强度表达不确定性。",
                "reason": "这会减少误导。",
                "risk": "不要因此变得含糊。",
                "evidence_event_ids": [str(self.source_id)],
            }],
            "follow_up_suggestion": {
                "source_event_id": str(self.source_id),
                "source_quote": "我长期偏好先看结论，再看必要证据。",
                "memory_ref": None,
                "reason_kind": "natural_continuation",
                "message": "你最喜欢哪种先说结论的方式？",
            },
        }, ensure_ascii=False))
        self.assertEqual(parsed.user_model_updates[0].belief_type.value, "preference")
        self.assertEqual(
            [item.value for item in parsed.quality_review], ["too_verbose"]
        )
        self.assertEqual(
            parsed.improvement_suggestions[0].category.value, "experience"
        )
        assert parsed.follow_up_suggestion is not None
        self.assertEqual(
            parsed.follow_up_suggestion.reason_kind.value, "continue_topic"
        )

    def test_daily_review_retry_backoff_prevents_provider_retry_storm(self) -> None:
        self.assertEqual(self.service._retry_backoff(1), timedelta(minutes=1))
        self.assertEqual(self.service._retry_backoff(2), timedelta(minutes=5))
        self.assertEqual(self.service._retry_backoff(3), timedelta(minutes=15))
        self.assertEqual(self.service._retry_backoff(4), timedelta(hours=1))
        self.assertEqual(self.service._retry_backoff(40), timedelta(hours=6))

    def test_memory_mode_does_not_silently_drop_overlong_quote(self) -> None:
        text=json.dumps({"include_diary":False,"memory_updates":[{
            "source_event_id":str(self.source_id),"source_quote":"述"*558,
            "statement":"我讲过一段重要经历。","kind":"experience"}],"user_model_updates":[]})
        self.assertEqual(DiaryIntelligenceResult.parse_provider_text(text).memory_updates,())
        with self.assertRaisesRegex(ValueError,"retry required"):
            DiaryIntelligenceResult.parse_provider_text(text,strict_understanding=True)

    def test_memory_mode_rejects_nonexact_source_instead_of_successful_empty_result(self) -> None:
        parsed=DiaryIntelligenceResult(include_diary=False,memory_updates=[{
            "source_event_id":self.source_id,"source_quote":"不在原文中的话",
            "statement":"我讲过一段重要经历。","kind":"experience"}])
        with self.assertRaisesRegex(ValueError,"source quote does not match"):
            self.service._validated_updates(parsed,[self.cloud_event],strict_sources=True)

    def test_only_exact_memory_eligible_user_quotes_can_auto_update(self) -> None:
        parsed = DiaryIntelligenceResult.parse_provider_text(json.dumps({
            "schema_version": 1, "include_diary": False,
            "title": None, "diary_text": None,
            "memory_updates": [
                {
                    "source_event_id": str(self.source_id),
                    "source_quote": "长期偏好先看结论",
                    "statement": "我偏好先看结论，再看必要证据。",
                    "confidence": 0.9, "importance": 0.8,
                },
                {
                    "source_event_id": str(self.source_id),
                    "source_quote": "并不存在的原话",
                    "statement": "不应写入。",
                    "confidence": 0.9, "importance": 0.8,
                },
            ],
            "user_model_updates": [], "quality_review": [],
        }, ensure_ascii=False))
        memories, beliefs = self.service._validated_updates(
            parsed, [self.cloud_event]
        )
        self.assertEqual(len(memories), 1)
        self.assertEqual(beliefs, ())

    def test_request_contains_only_supplied_cloud_events_and_high_effort_binding(self) -> None:
        private_secret = "PRIVATE-SECRET-MUST-NOT-LEAVE"
        request = self.service._request(
            local_date=date(2026, 9, 3),
            timezone_name="America/Chicago",
            source_set_hash="sha256:" + "2" * 64,
            cloud_events=[self.cloud_event],
            private_count=1,
        )
        serialized = request.model_dump_json()
        self.assertEqual(request.purpose, "diary_intelligence")
        self.assertNotIn(private_secret, serialized)
        self.assertIn(str(self.source_id), serialized)
        self.assertRegex(
            request.metadata["cloud_request_binding_hash"],
            r"^sha256:[0-9a-f]{64}$",
        )
        prompt = CodexCliProvider._reply_prompt(request)
        self.assertIn("DIARY-INTELLIGENCE", prompt)
        self.assertIn("Return exactly one JSON object", prompt)
        self.assertIn(
            "belief_type may only use: fact,preference,value,strength,"
            "vulnerability,pattern,uncertainty",
            prompt,
        )
        self.assertIn(
            "category may only use: conversation,memory,diary,proactive,"
            "goal,privacy,experience",
            prompt,
        )
        self.assertIn(
            "reason_kind may only use: continue_topic,curiosity,notice_progress",
            prompt,
        )

    def test_run_policy_conservatively_inherits_private_reference(self) -> None:
        private = {
            **self.cloud_event,
            "event_id": uuid.uuid4(),
            "privacy_class": "LOCAL_ONLY",
            "cloud_eligible": False,
            "disposition": "private_reference",
        }
        self.assertEqual(
            self.service._run_policy([self.cloud_event, private]),
            ("LOCAL_ONLY", False),
        )

    def test_meaningful_single_experience_does_not_require_a_stable_trait(self) -> None:
        from companion.product.diary_intelligence import DiaryMemoryUpdate, DiaryBeliefUpdate
        source={**self.cloud_event,"content":"今天我第一次独自登台弹琴，虽然紧张，但完成后非常自豪。"}
        episode=DiaryMemoryUpdate(source_event_id=source["event_id"],source_quote=source["content"],
            statement=source["content"],kind="experience")
        result=DiaryIntelligenceResult(include_diary=False,memory_updates=(episode,),
            user_model_updates=(DiaryBeliefUpdate(source_event_id=source["event_id"],source_quote=source["content"],
                belief_key="transient-confidence",statement="今天我在台上很紧张",belief_type="pattern"),))
        memories,beliefs=self.service._validated_updates(result,[source])
        self.assertEqual(memories,(episode,))
        self.assertEqual(beliefs,())
        memories,_=self.service._validated_updates(result,[{**source,"memory_eligible":False}])
        self.assertEqual(memories,())


@unittest.skipUnless(DATABASE_URL, "HAVRE_TEST_DATABASE_URL is required")
class DiaryIntelligencePostgresTests(unittest.IsolatedAsyncioTestCase):
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
        self.prompts: list[str] = []

    async def _cleanup(self) -> None:
        self.temporary.cleanup()

    async def test_retryable_schedule_receipt_obeys_persisted_backoff(self) -> None:
        local_day = (datetime.now(UTC) - timedelta(hours=5)).date()
        instant = datetime.combine(
            local_day + timedelta(days=1), time(5, 1), tzinfo=UTC
        )
        with self.repository.pool.connection() as connection, connection.transaction():
            connection.execute(
                """INSERT INTO havre.daily_diary_schedule_receipts
                   (owner_id,local_date,timezone_name,scheduled_for,status,
                    attempt_count,error_code,created_at,updated_at)
                   VALUES (%s,%s,'UTC',%s,'retryable_failed',2,
                           'ValidationError',%s,%s)""",
                (self.owner, local_day, instant, instant, instant),
            )
        diary = DiaryIntelligenceService(
            repository=self.repository,
            owner_id=self.owner,
            provider=None,
            embedding_provider=self.embedding,
        )
        self.assertIsNone(await diary.run_scheduled_once(
            worker_id="test-backoff-worker",
            timezone_name="UTC",
            now=instant + timedelta(minutes=1),
        ))
        with self.repository.pool.connection() as connection:
            receipt = connection.execute(
                """SELECT status,attempt_count,error_code
                   FROM havre.daily_diary_schedule_receipts
                   WHERE owner_id=%s AND local_date=%s AND timezone_name='UTC'""",
                (self.owner, local_day),
            ).fetchone()
        self.assertEqual(dict(receipt), {
            "status": "retryable_failed",
            "attempt_count": 2,
            "error_code": "ValidationError",
        })

    async def _runner(self, args, stdin_text, _cwd, _environment, _timeout_ms):
        if args[-1] == "--version":
            return CodexProcessResult(0, "codex-cli 0.152.0\n", "")
        if args[1:] == ("login", "status"):
            return CodexProcessResult(0, "Logged in using ChatGPT\n", "")
        prompt = stdin_text or ""
        self.prompts.append(prompt)
        if "HAVRE DIARY-INTELLIGENCE" in prompt:
            raw = prompt.split("BEGIN_CANONICAL_HAVRE_REQUEST\n", 1)[1].split(
                "\nEND_CANONICAL_HAVRE_REQUEST", 1
            )[0]
            envelope = json.loads(raw)
            transcript = json.loads(envelope["messages"][1]["content"])
            owner_message = next(
                item for item in transcript["messages"] if item["role"] == "user"
            )
            output = json.dumps({
                "schema_version": 1,
                "include_diary": True,
                "title": "说清沟通偏好",
                "diary_text": "我今天把自己偏好的沟通方式说清楚了，希望先看到结论，再看必要证据。",
                "memory_updates": [{
                    "source_event_id": owner_message["source_event_id"],
                    "source_quote": "我长期偏好先看结论，再看必要证据。",
                    "statement": "我偏好先看结论，再看必要证据。",
                    "confidence": 0.9,
                    "importance": 0.8,
                }],
                "user_model_updates": [{
                    "source_event_id": owner_message["source_event_id"],
                    "source_quote": "我长期偏好先看结论，再看必要证据。",
                    "belief_key": "communication-conclusion-first",
                    "statement": "我偏好先看结论，再看必要证据。",
                    "belief_type": "preference",
                    "confidence": 0.88,
                }],
                "quality_review": ["too_verbose"],
                "improvement_suggestions": [{
                    "category": "conversation",
                    "observation": "回复有时先展开分析，再确认 owner 当下想聊什么。",
                    "recommendation": "先用一句自然回应接住，再根据 owner 的回应决定是否分析。",
                    "reason": "这样更符合先像人聊天、再解决问题的体验目标。",
                    "risk": "不能因此漏掉明确的紧急请求。",
                    "evidence_event_ids": [owner_message["source_event_id"]],
                }],
                "follow_up_suggestion": {
                    "source_event_id": owner_message["source_event_id"],
                    "source_quote": "我长期偏好先看结论，再看必要证据。",
                    "memory_ref": None,
                    "reason_kind": "curiosity",
                    "message": "你后来有没有遇到一次特别舒服的、先讲结论的对话？",
                },
            }, ensure_ascii=False)
        else:
            output = "我记住了这次明确表达。"
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
                    "input_tokens": 200, "cached_input_tokens": 0,
                    "output_tokens": 80, "reasoning_output_tokens": 20,
                },
            }),
        ))
        return CodexProcessResult(0, stdout, "")

    async def test_local_review_does_not_redirect_next_normal_gpt_turn(self) -> None:
        medium = CodexCliProvider(
            executable=self.executable, enabled=True,
            explicit_authorization_ref=CODEX_OWNER_AUTOMATIC_AUTHORIZATION_REF,
            reasoning_effort="medium", process_runner=self._runner,
            environment={"PATH": "safe", "CODEX_HOME": self.temporary.name},
        )
        cloud = InteractionService(
            owner_id=self.owner, identity=self.identity, repository=self.repository,
            context_builder=ContextBuilder(max_input_tokens=8192, reserved_output_tokens=256),
            router=Stage1Router(approved_cloud_provider_ids=frozenset({CODEX_CLI_PROVIDER_ID})),
            provider=medium, retrieval_service=self.retrieval,
            request_binders={CODEX_CLI_PROVIDER_ID: partial(
                bind_codex_cli_request, reasoning_effort="medium",
            )},
        )
        first = await cloud.interact(InteractionCommand(
            message="我长期偏好先看结论，再看必要证据。",
            privacy_class=PrivacyClass.NORMAL, memory_eligible=True, channel="web",
            idempotency_key=f"normal-review-cloud:{uuid.uuid4()}",
        ))
        local = InteractionService(
            owner_id=self.owner, identity=self.identity, repository=self.repository,
            context_builder=ContextBuilder(max_input_tokens=4096, reserved_output_tokens=256),
            router=Stage1Router(), provider=DeterministicLocalProvider(),
            retrieval_service=self.retrieval,
        )
        # A separate NORMAL session ran locally: the aggregate review remains
        # NORMAL but is not cloud eligible. Do not declassify it to restore GPT.
        await local.interact(InteractionCommand(
            message="LOCAL-SESSION-NOT-FOR-GPT-REVIEW",
            privacy_class=PrivacyClass.NORMAL, memory_eligible=False, channel="web",
            idempotency_key=f"normal-review-local:{uuid.uuid4()}",
        ))
        high = CodexCliProvider(
            executable=self.executable, enabled=True,
            explicit_authorization_ref=CODEX_OWNER_AUTOMATIC_AUTHORIZATION_REF,
            reasoning_effort="high", process_runner=self._runner,
            environment={"PATH": "safe", "CODEX_HOME": self.temporary.name},
        )
        diary = DiaryIntelligenceService(
            repository=self.repository, owner_id=self.owner, provider=high,
            embedding_provider=self.embedding,
            review_root=Path(self.temporary.name) / "reviews",
        )
        day = (datetime.now(UTC) - timedelta(hours=5)).date()
        await diary.sync_day(local_date=day, timezone_name="UTC")
        with self.repository.pool.connection() as connection:
            before = dict(connection.execute(
                """SELECT run_id,privacy_class,cloud_eligible,result
                   FROM havre.daily_diary_intelligence_runs
                   WHERE owner_id=%s AND status='completed'""", (self.owner,),
            ).fetchone())
        self.assertEqual(before["privacy_class"], "NORMAL")
        self.assertFalse(before["cloud_eligible"])
        self.assertEqual(before["result"]["quality_review"], ["too_verbose"])
        self.assertTrue(diary.diary_day(
            local_date=day, timezone_name="UTC",
        )["improvement_review_file"])
        follow_on = await cloud.interact(InteractionCommand(
            message="Let's just chat a little.", session_id=first.session_id,
            privacy_class=PrivacyClass.NORMAL, memory_eligible=False, channel="web",
            idempotency_key=f"normal-review-next:{uuid.uuid4()}",
        ))
        self.assertEqual(follow_on.provider_id, CODEX_CLI_PROVIDER_ID)
        self.assertTrue(follow_on.cloud_eligible)
        self.assertNotIn("LOCAL-SESSION-NOT-FOR-GPT-REVIEW", self.prompts[-1])
        with self.repository.pool.connection() as connection:
            after = dict(connection.execute(
                """SELECT run_id,privacy_class,cloud_eligible,result
                   FROM havre.daily_diary_intelligence_runs
                   WHERE owner_id=%s AND run_id=%s""",
                (self.owner, before["run_id"]),
            ).fetchone())
        self.assertEqual(after, before)

    async def test_private_exclusion_auto_updates_and_source_erasure_close(self) -> None:
        medium = CodexCliProvider(
            executable=self.executable,
            enabled=True,
            explicit_authorization_ref=CODEX_OWNER_AUTOMATIC_AUTHORIZATION_REF,
            reasoning_effort="medium",
            process_runner=self._runner,
            environment={"PATH": "safe", "CODEX_HOME": self.temporary.name},
        )
        cloud_service = InteractionService(
            owner_id=self.owner,
            identity=self.identity,
            repository=self.repository,
            context_builder=ContextBuilder(
                max_input_tokens=8_192, reserved_output_tokens=256
            ),
            router=Stage1Router(
                approved_cloud_provider_ids=frozenset({CODEX_CLI_PROVIDER_ID})
            ),
            provider=medium,
            retrieval_service=self.retrieval,
            request_binders={
                CODEX_CLI_PROVIDER_ID: partial(
                    bind_codex_cli_request, reasoning_effort="medium"
                )
            },
        )
        cloud_turn = await cloud_service.interact(InteractionCommand(
            message="我长期偏好先看结论，再看必要证据。",
            privacy_class=PrivacyClass.NORMAL,
            memory_eligible=True,
            channel="web",
            idempotency_key=f"diary-cloud:{uuid.uuid4()}",
        ))
        local_service = InteractionService(
            owner_id=self.owner,
            identity=self.identity,
            repository=self.repository,
            context_builder=ContextBuilder(
                max_input_tokens=4_096, reserved_output_tokens=256
            ),
            router=Stage1Router(),
            provider=DeterministicLocalProvider(),
            retrieval_service=self.retrieval,
        )
        private_secret = "PRIVATE-ONLY-HEALTH-DETAIL-9471"
        private_turn = await local_service.interact(InteractionCommand(
            message=private_secret,
            privacy_class=PrivacyClass.LOCAL_ONLY,
            memory_eligible=True,
            channel="web",
            idempotency_key=f"diary-private:{uuid.uuid4()}",
        ))
        high = CodexCliProvider(
            executable=self.executable,
            enabled=True,
            explicit_authorization_ref=CODEX_OWNER_AUTOMATIC_AUTHORIZATION_REF,
            reasoning_effort="high",
            process_runner=self._runner,
            environment={"PATH": "safe", "CODEX_HOME": self.temporary.name},
        )
        class CaptureProactive:
            def __init__(self):
                self.calls = []

            def enqueue_relationship_follow_up(self, **kwargs):
                self.calls.append(kwargs)
                return {"status": "pending"}

        proactive = CaptureProactive()
        review_root = Path(self.temporary.name) / "reviews"
        diary = DiaryIntelligenceService(
            repository=self.repository,
            owner_id=self.owner,
            provider=high,
            embedding_provider=self.embedding,
            review_root=review_root,
            proactive_store=proactive,
        )
        local_day = (datetime.now(UTC) - timedelta(hours=5)).date()
        before_cutoff = await diary.run_scheduled_once(
            worker_id="test-diary-worker",
            timezone_name="UTC",
            now=datetime.combine(
                local_day + timedelta(days=1), time(4, 59), tzinfo=UTC
            ),
        )
        self.assertIsNone(before_cutoff)
        scheduled = await diary.run_scheduled_once(
            worker_id="test-diary-worker",
            timezone_name="UTC",
            now=datetime.combine(
                local_day + timedelta(days=1), time(5, 1), tzinfo=UTC
            ),
        )
        self.assertEqual(scheduled["status"], "completed")
        entry = diary.diary_day(local_date=local_day, timezone_name="UTC")
        assert entry is not None
        diary_prompt = next(
            prompt for prompt in self.prompts
            if "HAVRE DIARY-INTELLIGENCE" in prompt
        )
        self.assertNotIn(private_secret, diary_prompt)
        self.assertEqual(entry["title"], "说清沟通偏好")
        self.assertEqual(len(entry["private_sources"]), 2)
        self.assertIn(private_secret, {
            item["content"] for item in entry["private_sources"]
        })
        self.assertEqual(entry["automatic_updates"], {
            "memory": 1, "user_model": 1,
        })
        self.assertEqual(len(proactive.calls), 1)
        self.assertEqual(proactive.calls[0]["source_kind"], "conversation")
        self.assertIsNotNone(entry["improvement_review_file"])
        review_path = review_root / entry["improvement_review_file"]
        self.assertTrue(review_path.is_file())
        review_text = review_path.read_text(encoding="utf-8")
        self.assertIn("先用一句自然回应接住", review_text)
        self.assertNotIn(private_secret, review_text)
        local_context = self.repository.select_personal_context(
            owner_id=self.owner, query_text='Hello', maximum_privacy_class=PrivacyClass.LOCAL_ONLY)
        self.assertFalse(any(item.section_id.startswith('diary-quality-review-') for item in local_context))
        replay = await diary.run_scheduled_once(
            worker_id="test-diary-worker",
            timezone_name="UTC",
            now=datetime.combine(
                local_day + timedelta(days=1), time(6, 0), tzinfo=UTC
            ),
        )
        self.assertEqual(replay["status"], "completed")
        with self.repository.pool.connection() as connection:
            memory = connection.execute(
                """SELECT revision.created_by,revision.confidence_method
                   FROM havre.memory_heads head
                   JOIN havre.memory_revisions revision
                     ON revision.owner_id=head.owner_id
                    AND revision.memory_id=head.memory_id
                    AND revision.revision=head.current_revision
                   WHERE head.owner_id=%s AND head.status='active'""",
                (self.owner,),
            ).fetchone()
            belief = connection.execute(
                """SELECT revision.confidence_method,head.status
                   FROM havre.belief_heads head
                   JOIN havre.user_belief_revisions revision
                     ON revision.owner_id=head.owner_id
                    AND revision.belief_id=head.belief_id
                    AND revision.revision=head.current_revision
                   WHERE head.owner_id=%s""",
                (self.owner,),
            ).fetchone()
        self.assertEqual(memory["created_by"], "owner_delegated_gpt")
        self.assertEqual(memory["confidence_method"],
                         "gpt-grounded-owner-authorized-v1")
        self.assertEqual(belief["confidence_method"], "owner-delegated-gpt-v1")
        self.assertEqual(belief["status"], "active")

        with self.repository.pool.connection() as connection:
            run = connection.execute(
                """SELECT run_id FROM havre.daily_diary_intelligence_runs
                   WHERE owner_id=%s AND status='completed'
                   ORDER BY created_at DESC LIMIT 1""",
                (self.owner,),
            ).fetchone()
            private_source = connection.execute(
                """SELECT event_id,event_content_hash
                   FROM havre.daily_diary_intelligence_sources
                   WHERE owner_id=%s AND run_id=%s AND event_id=%s""",
                (self.owner, run["run_id"], private_turn.user_event_id),
            ).fetchone()
            with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
                with connection.transaction():
                    connection.execute(
                        """INSERT INTO havre.daily_diary_intelligence_sources
                           (owner_id,run_id,ordinal,event_id,event_content_hash,
                            disposition)
                           VALUES (%s,%s,999,%s,%s,'cloud_summary')""",
                        (self.owner, run["run_id"], private_source["event_id"],
                         private_source["event_content_hash"]),
                    )
            with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
                with connection.transaction():
                    connection.execute(
                        """INSERT INTO havre.owner_delegated_gpt_memory_updates
                           (owner_id,run_id,source_event_id,statement_hash,
                            memory_id,memory_revision,authorization_ref)
                           VALUES (%s,%s,%s,%s,%s,1,%s)""",
                        (self.owner, run["run_id"], cloud_turn.user_event_id,
                         "sha256:" + "f" * 64, uuid.uuid4(),
                         "product-owner/gpt-diary-memory-user-model-paired-review-2026-09-03"),
                    )
            with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
                with connection.transaction():
                    connection.execute(
                        """INSERT INTO havre.owner_delegated_gpt_belief_updates
                           (owner_id,run_id,source_event_id,statement_hash,
                            belief_id,belief_revision,authorization_ref)
                           VALUES (%s,%s,%s,%s,%s,1,%s)""",
                        (self.owner, run["run_id"], cloud_turn.user_event_id,
                         "sha256:" + "e" * 64, uuid.uuid4(),
                         "product-owner/gpt-diary-memory-user-model-paired-review-2026-09-03"),
                    )

        erasure = Stage10PostgresStore(
            repository=self.repository,
            owner_id=self.owner,
            erasure_repository=self.repository,
            improvement_review_root=review_root,
        ).erase_source_event(
            source_event_id=cloud_turn.user_event_id,
            ledger=ErasureLedger(Path(self.temporary.name) / "erasure.sqlite3"),
        )
        erased = erasure["derived"]
        self.assertEqual(erasure["raw_source_events"], 1)
        self.assertFalse(review_path.exists())
        self.assertEqual(erased["daily_diary_intelligence_runs"], 1)
        self.assertEqual(erased["daily_improvement_review_files"], 1)
        self.assertEqual(erased["daily_diary_schedule_receipts"], 1)
        self.assertEqual(erased["memories"], 1)
        self.assertEqual(erased["belief_revisions"], 1)
        with self.repository.pool.connection() as connection:
            remaining = connection.execute(
                """SELECT
                     (SELECT count(*) FROM havre.daily_diary_intelligence_runs
                      WHERE owner_id=%s) AS runs,
                     (SELECT count(*) FROM havre.memory_heads
                      WHERE owner_id=%s) AS memories,
                     (SELECT count(*) FROM havre.belief_heads
                      WHERE owner_id=%s) AS beliefs""",
                (self.owner, self.owner, self.owner),
            ).fetchone()
        self.assertEqual(dict(remaining), {"runs": 0, "memories": 0, "beliefs": 0})


if __name__ == "__main__":
    unittest.main()
