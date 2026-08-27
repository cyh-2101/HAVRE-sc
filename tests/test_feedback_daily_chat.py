from __future__ import annotations

import os
import asyncio
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from fastapi.testclient import TestClient

from companion.application import InteractionCommand, InteractionService
from companion.context import ContextBuilder
from companion.feedback import (
    FeedbackIssueAttribution,
    FeedbackRating,
    FeedbackReasonCode,
    FeedbackReviewDecision,
    FeedbackService,
)
from companion.identity import IdentityLoader
from companion.hashing import content_hash
from companion.operations.ledger import ErasureLedger
from companion.persistence import (
    PostgresRepository,
    Stage10PostgresStore,
    apply_migrations,
)
from companion.policy import PrivacyClass
from mlsys.serving import DeterministicLocalProvider, Stage1Router
from services.api.app import create_app
from services.api.settings import Settings


DATABASE_URL = os.getenv("HAVRE_TEST_DATABASE_URL")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
OWNER_ID = UUID("00000000-0000-7000-8000-000000000036")


class FeedbackDailyChatWebAssetsTests(unittest.TestCase):
    def test_history_render_does_not_pass_array_index_as_temporary_flag(self) -> None:
        chat = (PROJECT_ROOT / "apps" / "web" / "havre-chat.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("items.forEach(item=>renderMessage(item))", chat)
        self.assertNotIn("items.forEach(renderMessage)", chat)

    def test_mobile_chat_keeps_composer_in_chat_flow_and_exposes_drawers(self) -> None:
        chat = (PROJECT_ROOT / "apps" / "web" / "havre-chat.html").read_text(
            encoding="utf-8"
        )
        main_start = chat.index('<main class="chat">')
        main_end = chat.index("</main>", main_start)
        composer = chat.index('<div class="composer">')
        messages_end = chat.index('</div><div class="composer">', main_start)
        self.assertLess(main_start, messages_end)
        self.assertLess(messages_end, composer)
        self.assertLess(composer, main_end)
        self.assertIn("var(--app-height,100dvh)", chat)
        self.assertIn('id="openConversations"', chat)
        self.assertIn('id="openTools"', chat)
        self.assertIn("function setDrawer(name=null)", chat)
        self.assertIn(".top strong{min-width:0;flex:1", chat)
        self.assertIn(".composebox textarea{width:0;min-width:0", chat)
        self.assertIn(".send{flex:0 0 auto", chat)

    def test_pending_assistant_message_has_visible_generation_state(self) -> None:
        chat = (PROJECT_ROOT / "apps" / "web" / "havre-chat.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("Thinking…", chat)
        self.assertIn("assistant.scrollIntoView", chat)
        self.assertIn("window.visualViewport?.addEventListener('resize'", chat)


@unittest.skipUnless(DATABASE_URL, "HAVRE_TEST_DATABASE_URL is required")
class FeedbackDailyChatTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        assert DATABASE_URL is not None
        apply_migrations(DATABASE_URL, PROJECT_ROOT / "db" / "migrations")
        with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
            database_name = connection.execute("SELECT current_database()").fetchone()[0]
            roles_sql = (PROJECT_ROOT / "deploy" / "bootstrap_roles.sql").read_text(
                encoding="utf-8"
            ).replace(":DBNAME", f'"{database_name}"')
            roles_sql = "\n".join(
                line for line in roles_sql.splitlines()
                if not line.lstrip().startswith("\\set ")
            )
            connection.execute(roles_sql)
        cls.repository = PostgresRepository(DATABASE_URL)
        cls.repository.open()
        cls.identity = IdentityLoader(PROJECT_ROOT / "identity").load()
        cls.repository.bootstrap_owner_and_identity(owner_id=OWNER_ID, identity=cls.identity)
        cls.feedback = FeedbackService(repository=cls.repository, owner_id=OWNER_ID)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.repository.close()

    async def asyncSetUp(self) -> None:
        self.service = InteractionService(
            owner_id=OWNER_ID,
            identity=self.identity,
            repository=self.repository,
            context_builder=ContextBuilder(max_input_tokens=4096, reserved_output_tokens=256),
            router=Stage1Router(),
            provider=DeterministicLocalProvider(
                active_adapter_version_id="synthetic-candidate-fixture",
                active_adapter_artifact_hash="sha256:" + "a" * 64,
            ),
        )

    async def _interaction(self):
        return await self.service.interact(InteractionCommand(
            message="I had a difficult day.",
            idempotency_key=f"feedback-test-{uuid4()}",
            channel="web",
        ))

    async def test_original_response_and_owner_revision_are_both_preserved(self) -> None:
        result = await self._interaction()
        saved = self.feedback.save(
            assistant_event_id=result.assistant_event_id,
            rating=FeedbackRating.UNHELPFUL,
            reason_codes=(FeedbackReasonCode.TOO_AI, FeedbackReasonCode.TOO_LONG),
            owner_revision_text="That sounds hard. Want to tell me what happened?",
            expected_revision=0,
        )
        self.assertFalse(saved.training_eligible)
        conversation = self.feedback.conversation(session_id=result.session_id)
        assistant = [item for item in conversation if item["role"] == "assistant"][0]
        self.assertEqual(assistant["content"], result.content)
        self.assertNotEqual(assistant["content"], assistant["feedback"]["owner_revision_text"])
        self.assertFalse(assistant["feedback"]["training_eligible"])

    async def test_training_approval_is_separate_and_currently_fail_closed(self) -> None:
        result = await self._interaction()
        saved = self.feedback.save(
            assistant_event_id=result.assistant_event_id,
            rating=FeedbackRating.MIXED,
            owner_revision_text="Stay with me for a moment. What part hurt most?",
            expected_revision=0,
        )
        with self.assertRaisesRegex(ValueError, "Stage 9B training authorization"):
            self.feedback.review(
                feedback_id=saved.feedback_id,
                feedback_revision=saved.revision,
                decision=FeedbackReviewDecision.APPROVED_FOR_PERSONALIZATION_TRAINING,
                issue_attributions=(FeedbackIssueAttribution.PERSONALITY_COMMUNICATION,),
                review_notes="High-quality owner rewrite.",
                authorization_ref="owner-review:test-only",
            )
        self.assertFalse(saved.training_eligible)
        with psycopg.connect(DATABASE_URL, row_factory=dict_row) as connection:
            connection.execute("SET LOCAL ROLE havre_application")
            with self.assertRaises(psycopg.Error) as error:
                connection.execute(
                    """INSERT INTO havre.personalization_feedback_reviews (
                         owner_id,review_id,feedback_id,feedback_revision,decision,
                         issue_attributions,training_eligible,authorization_ref,content_hash
                       ) VALUES (%s,%s,%s,%s,'approved_for_personalization_training',
                                 ARRAY['personality_communication'],true,%s,%s)""",
                    (OWNER_ID,uuid4(),saved.feedback_id,saved.revision,
                     "owner-review:forged","sha256:" + "a" * 64),
                )
            self.assertEqual(error.exception.sqlstate, "55000")

    async def test_database_rejects_forged_model_lineage_and_mutation(self) -> None:
        result = await self._interaction()
        saved = self.feedback.save(
            assistant_event_id=result.assistant_event_id,
            rating=FeedbackRating.HELPFUL,
            expected_revision=0,
        )
        assert DATABASE_URL is not None
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute("SET LOCAL ROLE havre_application")
            with self.assertRaises(psycopg.Error) as error:
                connection.execute(
                    """UPDATE havre.response_feedback_heads SET current_revision=2
                       WHERE owner_id=%s AND feedback_id=%s""",
                    (OWNER_ID, saved.feedback_id),
                )
                connection.execute(
                    """
                    INSERT INTO havre.response_feedback_revisions (
                      owner_id,feedback_id,revision,rating,provider_id,model_version_id,
                      tokenizer_version_id,serving_config_version,privacy_class,
                      training_eligible,content_hash
                    ) SELECT owner_id,feedback_id,2,'helpful','forged',model_version_id,
                             tokenizer_version_id,serving_config_version,privacy_class,
                             false,%s
                      FROM havre.response_feedback_revisions
                     WHERE owner_id=%s AND feedback_id=%s AND revision=1
                    """,
                    ("sha256:" + "b" * 64, OWNER_ID, saved.feedback_id),
                )
            self.assertEqual(error.exception.sqlstate, "55000")
            connection.rollback()
            forged_material = saved.model_dump(
                mode="json", exclude={"content_hash", "created_at", "status"}
            )
            forged_material["revision"] = 2
            forged_material["privacy_class"] = "PUBLIC"
            with self.assertRaises(psycopg.Error) as error:
                connection.execute(
                    """UPDATE havre.response_feedback_heads SET current_revision=2
                       WHERE owner_id=%s AND feedback_id=%s""",
                    (OWNER_ID,saved.feedback_id),
                )
                connection.execute(
                    """INSERT INTO havre.response_feedback_revisions (
                         owner_id,feedback_id,revision,rating,reason_codes,
                         reason_text,owner_revision_text,provider_id,model_version_id,
                         adapter_version_id,tokenizer_version_id,serving_config_version,
                         privacy_class,training_eligible,content_hash
                       ) SELECT owner_id,feedback_id,2,rating,reason_codes,
                                reason_text,owner_revision_text,provider_id,model_version_id,
                                adapter_version_id,tokenizer_version_id,serving_config_version,
                                'PUBLIC',false,%s
                         FROM havre.response_feedback_revisions
                        WHERE owner_id=%s AND feedback_id=%s AND revision=1""",
                    (content_hash(forged_material),OWNER_ID,saved.feedback_id),
                )
            self.assertEqual(error.exception.sqlstate, "55000")
            connection.rollback()
            with self.assertRaises(psycopg.Error) as error:
                connection.execute(
                    """UPDATE havre.response_feedback_revisions SET rating='mixed'
                       WHERE owner_id=%s AND feedback_id=%s""",
                    (OWNER_ID, saved.feedback_id),
                )
            self.assertEqual(error.exception.sqlstate, "55000")

    async def test_communication_preference_enters_context_as_versioned_runtime_control(self) -> None:
        preference = self.feedback.set_preference(
            response_length="brief", reason="Owner prefers shorter daily replies"
        )
        self.assertGreaterEqual(preference.revision, 1)
        items = self.repository.select_personal_context(
            owner_id=OWNER_ID,
            query_text="hello",
            maximum_privacy_class=PrivacyClass.NORMAL,
        )
        item = [value for value in items if value.section_type == "communication_preference"][0]
        self.assertIn("concise", item.content_text)
        self.assertEqual(
            item.source_refs,
            (f"communication-preference/{preference.revision}",),
        )

    async def test_web_conversation_closes_as_complete_provenance_bound_episode(self) -> None:
        first = await self._interaction()
        second = await self.service.interact(InteractionCommand(
            message="Lately I worry that AI is doing the learning instead of me.",
            session_id=first.session_id,
            idempotency_key=f"feedback-test-{uuid4()}",
            channel="web",
        ))
        episode = self.feedback.close_episode(
            session_id=first.session_id,
            boundary_reason="owner_started_new_conversation",
        )
        self.assertEqual(episode["message_count"], 4)
        self.assertFalse(episode["training_eligible"])
        episodes = self.feedback.list_episodes()
        current = [value for value in episodes if value["episode_id"] == episode["episode_id"]][0]
        self.assertEqual(len(current["members"]), 4)
        self.assertEqual(
            {str(value["event_id"]) for value in current["members"]},
            {
                str(first.user_event_id), str(first.assistant_event_id),
                str(second.user_event_id), str(second.assistant_event_id),
            },
        )
        suggestions = self.feedback.list_episode_suggestions()
        self.assertEqual(len([x for x in suggestions if x["episode_id"] == episode["episode_id"]]), 1)
        with self.repository.pool.connection() as connection:
            per_message_jobs = connection.execute(
                """SELECT count(*) AS count FROM havre.background_jobs
                   WHERE owner_id=%s AND source_request_id IN (%s,%s)""",
                (OWNER_ID, first.request_id, second.request_id),
            ).fetchone()["count"]
        self.assertEqual(per_message_jobs, 0)
        recalled = self.repository.select_personal_context(
            owner_id=OWNER_ID,
            query_text="Do you remember that time I worried about AI doing the learning?",
            maximum_privacy_class=PrivacyClass.NORMAL,
        )
        episode_items = [x for x in recalled if x.section_type == "episodic_memory"]
        self.assertTrue(episode_items)
        self.assertIn(f"episode/{episode['episode_id']}", episode_items[0].source_refs)
        with self.assertRaisesRegex(ValueError, "conversation is closed"):
            await self.service.interact(InteractionCommand(
                message="This turn must never enter the closed episode.",
                session_id=first.session_id,
                idempotency_key=f"feedback-test-{uuid4()}",
                channel="web",
            ))
        session = [item for item in self.feedback.list_conversations()
                   if item["session_id"] == first.session_id][0]
        self.assertIsNotNone(session["closed_at"])
        assert DATABASE_URL is not None
        request_id = uuid4()
        trace_id = uuid4().hex
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute("SET LOCAL ROLE havre_application")
            connection.execute(
                """INSERT INTO havre.traces (
                     trace_id,owner_id,root_request_id,trace_flags,started_at
                   ) VALUES (%s,%s,%s,'01',clock_timestamp())""",
                (trace_id,OWNER_ID,request_id),
            )
            with self.assertRaises(psycopg.Error) as request_error:
                connection.execute(
                    """INSERT INTO havre.interaction_requests (
                         request_id,owner_id,session_id,trace_id,idempotency_key,
                         request_fingerprint,status
                       ) VALUES (%s,%s,%s,%s,%s,'closed-append','processing')""",
                    (request_id,OWNER_ID,first.session_id,trace_id,f"closed-{uuid4()}"),
                )
            self.assertEqual(request_error.exception.sqlstate,"55000")
            self.assertIn("closed conversation sessions are terminal",str(request_error.exception))
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute("SET LOCAL ROLE havre_application")
            with self.assertRaises(psycopg.Error) as event_error:
                connection.execute(
                    """INSERT INTO havre.events (
                         event_id,schema_version,event_type,event_version,owner_id,
                         session_id,request_id,trace_id,causation_event_id,
                         privacy_class,memory_eligible,training_eligible,cloud_eligible,
                         policy_version,policy_revision_id,policy_decision_source,
                         policy_authorization_ref,payload,content_hash,recorded_at
                       ) SELECT %s,schema_version,event_type,event_version,owner_id,
                                session_id,request_id,trace_id,causation_event_id,
                                privacy_class,memory_eligible,training_eligible,cloud_eligible,
                                policy_version,policy_revision_id,policy_decision_source,
                                policy_authorization_ref,payload,%s,clock_timestamp()
                         FROM havre.events WHERE owner_id=%s AND event_id=%s""",
                    (uuid4(),"sha256:" + "b" * 64,OWNER_ID,first.user_event_id),
                )
            self.assertEqual(event_error.exception.sqlstate,"55000")
            self.assertIn("closed conversation sessions are terminal",str(event_error.exception))

    async def test_episode_summary_whitespace_matches_database_canonicalization(self) -> None:
        result = await self.service.interact(InteractionCommand(
            message="\n\tHello from a whitespace boundary.\r\n",
            idempotency_key=f"feedback-test-{uuid4()}",channel="web",
        ))
        episode = self.feedback.close_episode(
            session_id=result.session_id,boundary_reason="owner_closed"
        )
        self.assertEqual(
            episode["summary_text"],
            "In this conversation, the owner said: Hello from a whitespace boundary.",
        )

    async def test_episode_close_rejects_an_inflight_interaction(self) -> None:
        class BlockingProvider(DeterministicLocalProvider):
            def __init__(self) -> None:
                super().__init__()
                self.entered = asyncio.Event()
                self.release = asyncio.Event()

            async def stream(self, request):
                self.entered.set()
                await self.release.wait()
                async for event in super().stream(request):
                    yield event

        first = await self._interaction()
        provider = BlockingProvider()
        service = InteractionService(
            owner_id=OWNER_ID,identity=self.identity,repository=self.repository,
            context_builder=ContextBuilder(max_input_tokens=4096,reserved_output_tokens=256),
            router=Stage1Router(),provider=provider,
        )
        task = asyncio.create_task(service.interact(InteractionCommand(
            message="Keep this request in flight.",session_id=first.session_id,
            idempotency_key=f"feedback-test-{uuid4()}",channel="web",
        )))
        await asyncio.wait_for(provider.entered.wait(),timeout=5)
        with self.assertRaisesRegex(ValueError, "interaction in progress"):
            self.feedback.close_episode(
                session_id=first.session_id,boundary_reason="owner_closed"
            )
        provider.release.set()
        await task
        episode = self.feedback.close_episode(
            session_id=first.session_id,boundary_reason="owner_closed"
        )
        self.assertEqual(episode["message_count"],4)

    async def test_cancelled_stream_reconciles_request_before_episode_close(self) -> None:
        class BlockingProvider(DeterministicLocalProvider):
            def __init__(self) -> None:
                super().__init__()
                self.entered = asyncio.Event()

            async def stream(self, request):
                self.entered.set()
                await asyncio.Event().wait()
                if False:
                    yield None

        provider = BlockingProvider()
        service = InteractionService(
            owner_id=OWNER_ID,identity=self.identity,repository=self.repository,
            context_builder=ContextBuilder(max_input_tokens=4096,reserved_output_tokens=256),
            router=Stage1Router(),provider=provider,
        )
        session_id = uuid4()
        idempotency_key = f"feedback-cancel-{uuid4()}"
        task = asyncio.create_task(service.interact(InteractionCommand(
            message="Cancel this disconnected browser request.",session_id=session_id,
            idempotency_key=idempotency_key,channel="web",
        )))
        await asyncio.wait_for(provider.entered.wait(),timeout=5)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        with self.repository.pool.connection() as connection:
            request = connection.execute(
                """SELECT status,error_code,assistant_event_id
                   FROM havre.interaction_requests
                   WHERE owner_id=%s AND idempotency_key=%s""",
                (OWNER_ID,idempotency_key),
            ).fetchone()
        self.assertEqual(request["status"],"failed")
        self.assertEqual(request["error_code"],"internal_error")
        self.assertIsNone(request["assistant_event_id"])
        episode = self.feedback.close_episode(
            session_id=session_id,boundary_reason="owner_closed"
        )
        self.assertEqual(episode["message_count"],1)

    async def test_cancel_during_reservation_waits_for_durable_failure_reconciliation(
        self,
    ) -> None:
        entered = threading.Event()
        release = threading.Event()
        original = self.repository.reserve_interaction

        def blocked_reservation(**kwargs):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("test reservation release timed out")
            return original(**kwargs)

        self.repository.reserve_interaction = blocked_reservation
        session_id = uuid4()
        idempotency_key = f"feedback-reserve-cancel-{uuid4()}"
        task = asyncio.create_task(self.service.interact(InteractionCommand(
            message="Disconnect while reserving this request.",session_id=session_id,
            idempotency_key=idempotency_key,channel="web",
        )))
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait,5))
            task.cancel()
            await asyncio.sleep(0.05)
            self.assertFalse(task.done())
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        finally:
            release.set()
            self.repository.reserve_interaction = original
        with self.repository.pool.connection() as connection:
            request = connection.execute(
                """SELECT status FROM havre.interaction_requests
                   WHERE owner_id=%s AND idempotency_key=%s""",
                (OWNER_ID,idempotency_key),
            ).fetchone()
        self.assertEqual(request["status"],"failed")
        self.assertEqual(self.feedback.close_episode(
            session_id=session_id,boundary_reason="owner_closed"
        )["message_count"],1)

    async def test_cancel_during_final_commit_resolves_as_completed_not_processing(
        self,
    ) -> None:
        entered = threading.Event()
        release = threading.Event()
        original = self.repository.complete_interaction

        def blocked_completion(**kwargs):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("test completion release timed out")
            return original(**kwargs)

        self.repository.complete_interaction = blocked_completion
        session_id = uuid4()
        idempotency_key = f"feedback-complete-cancel-{uuid4()}"
        task = asyncio.create_task(self.service.interact(InteractionCommand(
            message="Disconnect while committing this response.",session_id=session_id,
            idempotency_key=idempotency_key,channel="web",
        )))
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait,5))
            task.cancel()
            await asyncio.sleep(0.05)
            self.assertFalse(task.done())
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        finally:
            release.set()
            self.repository.complete_interaction = original
        with self.repository.pool.connection() as connection:
            request = connection.execute(
                """SELECT status,assistant_event_id FROM havre.interaction_requests
                   WHERE owner_id=%s AND idempotency_key=%s""",
                (OWNER_ID,idempotency_key),
            ).fetchone()
        self.assertEqual(request["status"],"completed")
        self.assertIsNotNone(request["assistant_event_id"])
        self.assertEqual(self.feedback.close_episode(
            session_id=session_id,boundary_reason="owner_closed"
        )["message_count"],2)

    async def test_model_receives_exact_prior_session_turns_with_roles(self) -> None:
        class CaptureProvider(DeterministicLocalProvider):
            def __init__(self) -> None:
                super().__init__()
                self.last_request = None

            async def stream(self, request):
                self.last_request = request
                async for event in super().stream(request):
                    yield event

        first = await self._interaction()
        provider = CaptureProvider()
        service = InteractionService(
            owner_id=OWNER_ID,identity=self.identity,repository=self.repository,
            context_builder=ContextBuilder(max_input_tokens=4096,reserved_output_tokens=256),
            router=Stage1Router(),provider=provider,
        )
        await service.interact(InteractionCommand(
            message="What did I just tell you?",session_id=first.session_id,
            idempotency_key=f"feedback-test-{uuid4()}",channel="web",
        ))
        self.assertIsNotNone(provider.last_request)
        prior = [
            (message.role,message.content_parts[0].text,message.source_refs)
            for message in provider.last_request.messages
            if f"event/{first.user_event_id}" in message.source_refs
            or f"event/{first.assistant_event_id}" in message.source_refs
        ]
        self.assertEqual([item[0] for item in prior],["user","assistant"])
        self.assertEqual(prior[0][1],"I had a difficult day.")
        self.assertEqual(prior[1][1],first.content)
        self.assertEqual(provider.last_request.messages[-1].role,"user")
        self.assertEqual(
            provider.last_request.messages[-1].content_parts[0].text,
            "What did I just tell you?",
        )

    async def test_database_rejects_cross_session_member_and_forged_summary(self) -> None:
        first = await self._interaction()
        other = await self._interaction()
        assert DATABASE_URL is not None
        cross_episode_id = uuid4()
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute("SET LOCAL ROLE havre_application")
            with self.assertRaises(psycopg.Error) as error:
                connection.execute(
                    """INSERT INTO havre.conversation_episodes (
                         owner_id,episode_id,session_id,status,boundary_reason,message_count,
                         summary_text,summary_method,privacy_class,memory_eligible,
                         training_eligible,cloud_eligible,policy_version,policy_revision_id,
                         policy_decision_source,content_hash,started_at,ended_at
                       ) SELECT %s,%s,%s,'closed','owner_closed',1,'forged',
                                'extractive-episode-summary-v1','NORMAL',true,false,true,
                                'data-policy-v1',%s,'derived_conservative',%s,
                                recorded_at,recorded_at
                         FROM havre.events WHERE owner_id=%s AND event_id=%s""",
                    (OWNER_ID,cross_episode_id,first.session_id,uuid4(),"sha256:" + "a"*64,
                     OWNER_ID,first.user_event_id),
                )
                connection.execute(
                    """INSERT INTO havre.conversation_episode_members
                       (owner_id,episode_id,ordinal,event_id,event_content_hash,event_type)
                       SELECT %s,%s,0,event_id,content_hash,event_type
                       FROM havre.events WHERE owner_id=%s AND event_id=%s""",
                    (OWNER_ID,cross_episode_id,OWNER_ID,other.user_event_id),
                )
            self.assertEqual(error.exception.sqlstate,"55000")
        forged = await self._interaction()
        with psycopg.connect(DATABASE_URL, row_factory=dict_row) as connection:
            rows = connection.execute(
                """SELECT * FROM havre.events WHERE owner_id=%s AND session_id=%s
                   AND event_type IN ('USER_MESSAGE','ASSISTANT_MESSAGE')
                   ORDER BY recorded_at,event_id""",
                (OWNER_ID,forged.session_id),
            ).fetchall()
        episode_id = uuid4()
        material = {
            "schema_version":1,"owner_id":str(OWNER_ID),
            "episode_id":str(episode_id),"session_id":str(forged.session_id),
            "member_event_hashes":[row["content_hash"] for row in rows],
            "summary_text":"forged but self-consistently hashed",
            "summary_method":"extractive-episode-summary-v1",
            "privacy_class":"NORMAL","memory_eligible":True,
            "training_eligible":False,"cloud_eligible":True,
            "boundary_reason":"owner_closed",
        }
        connection = psycopg.connect(DATABASE_URL)
        try:
            connection.execute("SET LOCAL ROLE havre_application")
            with self.assertRaises(psycopg.Error) as error:
                connection.execute(
                    """INSERT INTO havre.conversation_episodes (
                         owner_id,episode_id,session_id,status,boundary_reason,message_count,
                         summary_text,summary_method,privacy_class,memory_eligible,
                         training_eligible,cloud_eligible,policy_version,policy_revision_id,
                         policy_decision_source,content_hash,started_at,ended_at
                       ) VALUES (%s,%s,%s,'closed','owner_closed',%s,%s,
                         'extractive-episode-summary-v1','NORMAL',true,false,true,
                         'data-policy-v1',%s,'derived_conservative',%s,%s,%s)""",
                    (OWNER_ID,episode_id,forged.session_id,len(rows),material["summary_text"],
                     uuid4(),content_hash(material),rows[0]["recorded_at"],
                     rows[-1]["recorded_at"]),
                )
                for ordinal,row in enumerate(rows):
                    connection.execute(
                        """INSERT INTO havre.conversation_episode_members
                           (owner_id,episode_id,ordinal,event_id,event_content_hash,event_type)
                           VALUES (%s,%s,%s,%s,%s,%s)""",
                        (OWNER_ID,episode_id,ordinal,row["event_id"],row["content_hash"],
                         row["event_type"]),
                    )
                connection.commit()
        finally:
            connection.close()
        self.assertEqual(error.exception.sqlstate,"55000")

    async def test_daily_feedback_foreign_keys_have_left_prefix_indexes(self) -> None:
        assert DATABASE_URL is not None
        query = """
        WITH wanted(table_name) AS (
          VALUES ('response_feedback_heads'),('response_feedback_revisions'),
            ('personalization_feedback_reviews'),
            ('communication_preference_revisions'),('conversation_episodes'),
            ('conversation_episode_members'),('episode_memory_suggestions'),('sessions')
        ), fk AS (
          SELECT con.conname,con.conrelid,con.conkey,rel.relname
          FROM pg_constraint con
          JOIN pg_class rel ON rel.oid=con.conrelid
          JOIN pg_namespace ns ON ns.oid=rel.relnamespace
          JOIN wanted ON wanted.table_name=rel.relname
          WHERE con.contype='f' AND ns.nspname='havre'
        )
        SELECT fk.relname,fk.conname FROM fk WHERE NOT EXISTS (
          SELECT 1 FROM pg_index idx
          WHERE idx.indrelid=fk.conrelid AND idx.indisvalid
            AND (idx.indkey::smallint[])[0:cardinality(fk.conkey)-1]=fk.conkey
        ) ORDER BY 1,2
        """
        with psycopg.connect(DATABASE_URL) as connection:
            self.assertEqual(connection.execute(query).fetchall(),[])

    async def test_populated_0036_episode_upgrade_refuses_to_rewrite_owner_evidence(
        self,
    ) -> None:
        """A legacy reviewed derivative is never silently rewritten by 0037."""
        source = await self._interaction()
        assert DATABASE_URL is not None
        with psycopg.connect(DATABASE_URL, row_factory=dict_row) as connection:
            trace = connection.execute(
                "SELECT * FROM havre.traces WHERE trace_id=%s",(source.trace_id,)
            ).fetchone()
            request = connection.execute(
                "SELECT * FROM havre.interaction_requests WHERE request_id=%s",
                (source.request_id,),
            ).fetchone()
            events = connection.execute(
                """SELECT * FROM havre.events
                   WHERE owner_id=%s AND session_id=%s
                   ORDER BY CASE event_type WHEN 'USER_MESSAGE' THEN 0 ELSE 1 END""",
                (OWNER_ID,source.session_id),
            ).fetchall()
        self.assertIsNotNone(trace)
        self.assertIsNotNone(request)
        self.assertEqual(len(events),2)

        params = conninfo_to_dict(DATABASE_URL)
        database_name = f"havre_feedback_upgrade_{uuid4().hex[:12]}"
        admin_params = dict(params)
        admin_params["dbname"] = "postgres"
        target_params = dict(params)
        target_params["dbname"] = database_name
        admin_url = make_conninfo(**admin_params)
        target_url = make_conninfo(**target_params)
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        old_repository = None
        try:
            with tempfile.TemporaryDirectory() as temp:
                old_migrations = Path(temp) / "migrations"
                old_migrations.mkdir()
                for path in sorted((PROJECT_ROOT / "db" / "migrations").glob("*.sql")):
                    if path.name >= "0037_":
                        continue
                    shutil.copy2(path,old_migrations / path.name)
                applied = apply_migrations(target_url,old_migrations)
                self.assertEqual(applied[-1],"0036_owner_feedback_personalization.sql")

            old_repository = PostgresRepository(target_url)
            old_repository.open()
            old_repository.bootstrap_owner_and_identity(
                owner_id=OWNER_ID,identity=self.identity
            )
            legacy_episode_id = uuid4()
            legacy_summary = "Legacy summary copied owner and assistant text."
            with psycopg.connect(target_url) as connection:
                connection.execute(
                    "INSERT INTO havre.sessions (session_id,owner_id,channel) VALUES (%s,%s,'web')",
                    (source.session_id,OWNER_ID),
                )
                connection.execute(
                    """INSERT INTO havre.traces (
                         trace_id,owner_id,root_request_id,incoming_parent_span_id,
                         trace_flags,started_at,created_at
                       ) VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        trace["trace_id"],OWNER_ID,trace["root_request_id"],
                        trace["incoming_parent_span_id"],trace["trace_flags"],
                        trace["started_at"],trace["created_at"],
                    ),
                )
                connection.execute(
                    """INSERT INTO havre.interaction_requests (
                         request_id,owner_id,session_id,trace_id,idempotency_key,
                         request_fingerprint,status,created_at
                       ) VALUES (%s,%s,%s,%s,%s,%s,'processing',%s)""",
                    (
                        source.request_id,OWNER_ID,source.session_id,source.trace_id,
                        request["idempotency_key"],request["request_fingerprint"],
                        request["created_at"],
                    ),
                )
                for event in events:
                    connection.execute(
                        """INSERT INTO havre.events (
                             event_id,schema_version,event_type,event_version,owner_id,
                             session_id,request_id,trace_id,causation_event_id,
                             privacy_class,memory_eligible,training_eligible,cloud_eligible,
                             policy_version,policy_revision_id,policy_decision_source,
                             policy_authorization_ref,payload,content_hash,recorded_at
                           ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                                     %s,%s,%s,%s,%s,%s,%s)""",
                        (
                            event["event_id"],event["schema_version"],event["event_type"],
                            event["event_version"],OWNER_ID,event["session_id"],
                            event["request_id"],event["trace_id"],
                            event["causation_event_id"],event["privacy_class"],
                            event["memory_eligible"],event["training_eligible"],
                            event["cloud_eligible"],event["policy_version"],
                            event["policy_revision_id"],event["policy_decision_source"],
                            event["policy_authorization_ref"],Jsonb(event["payload"]),
                            event["content_hash"],event["recorded_at"],
                        ),
                    )
                connection.execute(
                    """INSERT INTO havre.conversation_episodes (
                         owner_id,episode_id,session_id,status,boundary_reason,message_count,
                         summary_text,summary_method,privacy_class,memory_eligible,
                         training_eligible,cloud_eligible,policy_version,policy_revision_id,
                         policy_decision_source,content_hash,started_at,ended_at
                       ) VALUES (%s,%s,%s,'closed','owner_closed',2,%s,
                         'extractive-episode-summary-v1','NORMAL',true,false,true,
                         'data-policy-v1',%s,'derived_conservative',%s,%s,%s)""",
                    (
                        OWNER_ID,legacy_episode_id,source.session_id,legacy_summary,uuid4(),
                        "sha256:" + "c" * 64,events[0]["recorded_at"],
                        events[-1]["recorded_at"],
                    ),
                )
                for ordinal,event in enumerate(events):
                    connection.execute(
                        """INSERT INTO havre.conversation_episode_members (
                             owner_id,episode_id,ordinal,event_id,event_content_hash,event_type
                           ) VALUES (%s,%s,%s,%s,%s,%s)""",
                        (
                            OWNER_ID,legacy_episode_id,ordinal,event["event_id"],
                            event["content_hash"],event["event_type"],
                        ),
                    )

            with self.assertRaises(psycopg.Error) as migration_error:
                apply_migrations(target_url,PROJECT_ROOT / "db" / "migrations")
            self.assertEqual(migration_error.exception.sqlstate,"55000")
            self.assertIn(
                "pre-correction episode evidence requires explicit governed migration",
                str(migration_error.exception),
            )
            with psycopg.connect(target_url) as connection:
                retained = connection.execute(
                    """SELECT summary_text FROM havre.conversation_episodes
                       WHERE owner_id=%s AND episode_id=%s""",
                    (OWNER_ID,legacy_episode_id),
                ).fetchone()[0]
                self.assertEqual(retained,legacy_summary)
                self.assertIsNone(connection.execute(
                    """SELECT 1 FROM havre.schema_migrations
                       WHERE migration_id='0037_daily_learning_canonical_hash_guards.sql'"""
                ).fetchone())
        finally:
            if old_repository is not None:
                old_repository.close()
            with psycopg.connect(admin_url, autocommit=True) as admin:
                admin.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                        sql.Identifier(database_name)
                    )
                )

    async def test_source_erasure_closes_feedback_and_episode_derivatives(self) -> None:
        result = await self._interaction()
        saved = self.feedback.save(
            assistant_event_id=result.assistant_event_id,
            rating=FeedbackRating.UNHELPFUL,
            owner_revision_text="A better answer.",
            expected_revision=0,
        )
        review = self.feedback.review(
            feedback_id=saved.feedback_id,feedback_revision=saved.revision,
            decision=FeedbackReviewDecision.RUNTIME_FIX,
            issue_attributions=(FeedbackIssueAttribution.MEMORY_RETRIEVAL,),
            review_notes="Keep as a runtime diagnosis, never automatic training.",
            authorization_ref=None,
        )
        episode = self.feedback.close_episode(
            session_id=result.session_id, boundary_reason="owner_closed"
        )
        store = Stage10PostgresStore(
            repository=self.repository,owner_id=OWNER_ID,
            erasure_repository=self.repository,
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            export_root = root / "owner-export"
            store.export_owner_data(export_root)
            self.assertIn(
                str(saved.feedback_id),
                (export_root / "tables/response_feedback_heads.jsonl").read_text(
                    encoding="utf-8"
                ),
            )
            self.assertIn(
                str(review.review_id),
                (export_root / "tables/personalization_feedback_reviews.jsonl").read_text(
                    encoding="utf-8"
                ),
            )
            self.assertIn(
                str(episode["episode_id"]),
                (export_root / "tables/conversation_episodes.jsonl").read_text(
                    encoding="utf-8"
                ),
            )
            ledger = ErasureLedger(root / "ledger.sqlite3")
            ledger.append(owner_id=OWNER_ID,source_event_id=result.user_event_id)
            replay = store.replay_erasure_directives(
                ledger=ledger,after_sequence=0,restore_id=str(uuid4())
            )
            self.assertEqual(replay["directives_applied"],1)
            self.assertTrue(replay["absence_verified"])
        with self.repository.pool.connection() as connection:
            for table,column,value in (
                ("response_feedback_heads","feedback_id",saved.feedback_id),
                ("response_feedback_revisions","feedback_id",saved.feedback_id),
                ("personalization_feedback_reviews","review_id",review.review_id),
                ("conversation_episodes","episode_id",episode["episode_id"]),
                ("conversation_episode_members","episode_id",episode["episode_id"]),
                ("episode_memory_suggestions","episode_id",episode["episode_id"]),
            ):
                self.assertIsNone(connection.execute(
                    f"SELECT 1 FROM havre.{table} WHERE owner_id=%s AND {column}=%s",
                    (OWNER_ID,value),
                ).fetchone(),table)
            session = connection.execute(
                """SELECT closed_at,closed_episode_id FROM havre.sessions
                   WHERE owner_id=%s AND session_id=%s""",
                (OWNER_ID,result.session_id),
            ).fetchone()
            self.assertIsNotNone(session["closed_at"])
            self.assertIsNone(session["closed_episode_id"])


@unittest.skipUnless(DATABASE_URL, "HAVRE_TEST_DATABASE_URL is required")
class FeedbackDailyChatApiTests(unittest.TestCase):
    def test_stream_history_feedback_and_episode_api(self) -> None:
        assert DATABASE_URL is not None
        settings = Settings(
            database_url=DATABASE_URL,
            owner_id=UUID("00000000-0000-7000-8000-000000000037"),
            identity_root=PROJECT_ROOT / "identity",
            provider_id="deterministic-local",
            self_hosted_base_url="http://127.0.0.1:1",
            self_hosted_model_manifest=PROJECT_ROOT / "README.md",
            self_hosted_engine_manifest=PROJECT_ROOT / "README.md",
            context_token_budget=4096,
            reserved_output_tokens=256,
            inference_timeout_ms=10_000,
            require_owner_api_token=False,
            enable_erasure_ledger=False,
        )
        with TestClient(create_app(settings)) as client:
            response = client.post(
                "/v1/interactions/stream",
                headers={"Idempotency-Key":f"api-feedback-{uuid4()}"},
                json={"message":"Please stay with me for a minute."},
            )
            self.assertEqual(response.status_code, 200)
            events = [__import__("json").loads(line) for line in response.text.splitlines()]
            self.assertEqual(events[0], {"type":"status","status":"thinking"})
            self.assertTrue(any(item["type"] == "delta" for item in events))
            completed = [item for item in events if item["type"] == "completed"][0]
            interaction = completed["interaction"]
            session_id = interaction["session_id"]
            history = client.get(f"/v1/conversations/{session_id}").json()
            self.assertEqual([item["role"] for item in history], ["user","assistant"])
            saved = client.post("/v1/feedback", json={
                "assistant_event_id":interaction["assistant_event_id"],
                "rating":"unhelpful","reason_codes":["too_long"],
                "owner_revision_text":"I'm here. What happened?", "expected_revision":0,
            })
            self.assertEqual(saved.status_code, 201, saved.text)
            self.assertFalse(saved.json()["training_eligible"])
            closed = client.post(
                f"/v1/conversations/{session_id}/close",
                json={"boundary_reason":"owner_closed"},
            )
            self.assertEqual(closed.status_code, 200, closed.text)
            self.assertEqual(closed.json()["message_count"], 2)
            self.assertEqual(client.get("/").status_code, 200)
            self.assertEqual(client.get("/").headers["cache-control"],"no-store")
            self.assertEqual(
                client.get(f"/v1/conversations/{session_id}").headers["cache-control"],
                "no-store",
            )
            original = client.app.state.runtime.service.interact
            async def secret_failure(_command):
                raise RuntimeError("SECRET INTERNAL PATH")
            client.app.state.runtime.service.interact = secret_failure
            failed = client.post(
                "/v1/interactions/stream",
                headers={"Idempotency-Key":f"api-feedback-{uuid4()}"},
                json={"message":"fail safely"},
            )
            client.app.state.runtime.service.interact = original
            self.assertNotIn("SECRET INTERNAL PATH",failed.text)
            self.assertIn("could not complete",failed.text)

        protected = settings.model_copy(update={
            "owner_id":UUID("00000000-0000-7000-8000-000000000038"),
            "owner_api_token":"o" * 48,
            "desktop_bootstrap_token":"b" * 48,
        })
        with TestClient(create_app(protected)) as client:
            self.assertEqual(client.get("/v1/conversations").status_code,401)
            rejected = client.post(
                "/v1/desktop/session",
                headers={"X-HAVRE-Desktop-Bootstrap":"wrong" * 10},
            )
            self.assertEqual(rejected.status_code,403)
            ready = client.post(
                "/v1/desktop/session",
                headers={"X-HAVRE-Desktop-Bootstrap":"b" * 48},
            )
            self.assertEqual(ready.status_code,200)
            self.assertIn("HttpOnly",ready.headers["set-cookie"])
            self.assertEqual(client.get("/v1/conversations").status_code,200)

    def test_desktop_launcher_uses_protected_application_credentials(self) -> None:
        start = (PROJECT_ROOT / "scripts" / "start_havre_desktop.ps1").read_text(
            encoding="utf-8"
        )
        prepare = (PROJECT_ROOT / "scripts" / "prepare_havre_desktop.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("prepare_havre_desktop",start)
        self.assertIn("HAVRE_OWNER_API_TOKEN_FILE",start)
        self.assertIn("HAVRE_DESKTOP_BOOTSTRAP_TOKEN_FILE",start)
        self.assertIn("HAVRE_DATABASE_URL_FILE",start)
        self.assertNotIn("Get-Content -Raw -LiteralPath $DatabaseSecret",start)
        self.assertNotIn(
            '$env:HAVRE_DATABASE_URL = "postgresql://postgres@',start
        )
        self.assertIn("GRANT havre_application",prepare)
        self.assertIn("NOSUPERUSER",prepare)
        self.assertLess(
            start.index("SetAccessRuleProtection($true,$false)"),
            start.index("-m scripts.prepare_havre_desktop"),
        )
        self.assertIn("Desktop secret directory is not owner-only",start)
        self.assertIn("must be pre-created with owner-only ACLs",prepare)
        migration_runner = (
            PROJECT_ROOT / "companion" / "persistence" / "migrations.py"
        ).read_text(encoding="utf-8")
        self.assertLess(
            migration_runner.index("CREATE ROLE havre_application"),
            migration_runner.index("for path in migration_files"),
        )


if __name__ == "__main__":
    unittest.main()
