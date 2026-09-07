from __future__ import annotations

import copy
import os
import asyncio
import json
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from companion.application import (
    IdempotencyConflict,
    InferenceTimeoutError,
    InteractionCommand,
    InteractionService,
)
from companion.context import ContextBudgetExceeded, ContextBuilder, PersonalContextItem
from companion.events import (
    EventEnvelope,
    EventType,
    InteractionFailurePayload,
    TextContentPart,
    UserMessagePayload,
)
from companion.hashing import content_hash
from companion.identity import IdentityLoader
from companion.ids import uuid7
from companion.persistence import PostgresRepository, apply_migrations
from companion.policy import DataPolicy, PrivacyClass
from companion.tracing import TraceContext
from mlsys.serving import (
    DeterministicLocalProvider,
    PrivacyClassRouter,
    ProviderInferenceError,
    Stage1Router,
)
from mlsys.serving.codex_cli import (
    CODEX_CLI_PROVIDER_ID,
    CODEX_OWNER_AUTOMATIC_AUTHORIZATION_REF,
    CodexCliProvider,
    CodexProcessResult,
    bind_codex_cli_request,
)


DATABASE_URL = os.getenv("HAVRE_TEST_DATABASE_URL")
PROJECT_ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(DATABASE_URL, "HAVRE_TEST_DATABASE_URL is required for integration tests")
class Stage1PostgresIntegrationTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        assert DATABASE_URL is not None
        apply_migrations(DATABASE_URL, PROJECT_ROOT / "db" / "migrations")
        reapplied = apply_migrations(DATABASE_URL, PROJECT_ROOT / "db" / "migrations")
        if reapplied:
            raise AssertionError(f"migrations were not idempotent: {reapplied}")
        with psycopg.connect(DATABASE_URL) as connection:
            has_erasure_role = connection.execute(
                "SELECT pg_has_role(current_user, 'havre_privileged_erasure', 'MEMBER')"
            ).fetchone()[0]
        if not has_erasure_role:
            raise AssertionError("migration runner lacks privileged erasure role")
        cls.owner_id = uuid.UUID("00000000-0000-7000-8000-000000000002")
        cls.second_owner_id = uuid.UUID("00000000-0000-7000-8000-000000000003")
        cls.identity = IdentityLoader(PROJECT_ROOT / "identity").load()
        cls.repository = PostgresRepository(DATABASE_URL)
        cls.repository.open()
        cls.repository.bootstrap_owner_and_identity(
            owner_id=cls.owner_id,
            identity=cls.identity,
        )
        cls.repository.bootstrap_owner_and_identity(
            owner_id=cls.second_owner_id,
            identity=cls.identity,
        )
        cls.service = InteractionService(
            owner_id=cls.owner_id,
            identity=cls.identity,
            repository=cls.repository,
            context_builder=ContextBuilder(
                max_input_tokens=4096,
                reserved_output_tokens=256,
            ),
            router=Stage1Router(),
            provider=DeterministicLocalProvider(),
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.repository.close()

    async def test_complete_request_is_durable_traceable_and_idempotent(self) -> None:
        key = f"integration-{uuid.uuid4()}"
        incoming_trace_id = uuid.uuid4().hex
        command = InteractionCommand(
            message="I am avoiding a hard task. Help me identify one grounded next step.",
            privacy_class=PrivacyClass.PRIVATE,
            channel="api",
            idempotency_key=key,
            traceparent=f"00-{incoming_trace_id}-00f067aa0ba902b7-01",
        )
        first = await self.service.interact(command)
        replay = await self.service.interact(command)
        self.assertFalse(first.idempotent_replay)
        self.assertTrue(replay.idempotent_replay)
        self.assertEqual(first.request_id, replay.request_id)
        self.assertEqual(first.user_event_id, replay.user_event_id)
        self.assertEqual(first.assistant_event_id, replay.assistant_event_id)
        self.assertEqual(first.trace_id, incoming_trace_id)

        evidence = self.repository.evidence(first.request_id, owner_id=self.owner_id)
        self.assertIsNotNone(evidence)
        assert evidence is not None
        self.assertEqual(evidence["request"]["status"], "completed")
        self.assertEqual(evidence["request"]["trace_id"], first.trace_id)
        self.assertEqual(
            [event["event_type"] for event in evidence["events"]],
            ["USER_MESSAGE", "ASSISTANT_MESSAGE"],
        )
        user_event, assistant_event = evidence["events"]
        self.assertEqual(assistant_event["causation_event_id"], user_event["event_id"])
        self.assertEqual(user_event["privacy_class"], "PRIVATE")
        self.assertFalse(user_event["training_eligible"])
        self.assertEqual(
            evidence["context_pack"]["sections"][1]["source_refs"],
            [f"event/{user_event['event_id']}"],
        )
        self.assertEqual(evidence["context_pack"]["effective_privacy_class"], "PRIVATE")
        self.assertEqual(evidence["inference"]["provider_id"], "deterministic-local")
        self.assertEqual(evidence["inference"]["model_version_id"], "deterministic-companion-v1")
        self.assertGreater(evidence["inference"]["usage"]["total_tokens"], 0)
        self.assertGreaterEqual(len(evidence["spans"]), 5)
        root_span = next(
            span for span in evidence["spans"] if span["name"] == "interaction.request"
        )
        self.assertEqual(
            root_span["attributes"]["orchestrator_version"],
            "interaction-orchestrator-v9",
        )
        response_policy = assistant_event["payload"]["response_policy_decision"]
        self.assertEqual(response_policy["policy_version"], "core-response-policy-v1")
        self.assertEqual(response_policy["action"], "pass_through")
        self.assertEqual(response_policy["category"], "ordinary")
        self.assertEqual(root_span["attributes"]["inference_timeout_ms"], 20_000)
        self.assertEqual(
            {item["artifact_kind"] for item in evidence["identity_versions"]},
            {"constitution", "identity", "values"},
        )

        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
            with psycopg.connect(DATABASE_URL) as connection:
                connection.execute(
                    "UPDATE havre.events SET event_version = 1 WHERE event_id = %s",
                    (user_event["event_id"],),
                )

    async def test_conversation_history_stays_in_current_session_by_default(self) -> None:
        isolated_owner = uuid.uuid4()
        self.repository.bootstrap_owner_and_identity(
            owner_id=isolated_owner,
            identity=self.identity,
        )
        service = InteractionService(
            owner_id=isolated_owner,
            identity=self.identity,
            repository=self.repository,
            context_builder=ContextBuilder(
                max_input_tokens=4096,
                reserved_output_tokens=256,
            ),
            router=Stage1Router(),
            provider=DeterministicLocalProvider(),
        )
        first_session = uuid.uuid4()
        second_session = uuid.uuid4()
        first = await service.interact(
            InteractionCommand(
                message="isolated first-session marker",
                session_id=first_session,
                idempotency_key=f"history-a-{uuid.uuid4()}",
            )
        )
        await service.interact(
            InteractionCommand(
                message="isolated second-session marker",
                session_id=second_session,
                idempotency_key=f"history-b-{uuid.uuid4()}",
            )
        )

        current_only = self.repository.select_conversation_history(
            owner_id=isolated_owner,
            session_id=first_session,
            exclude_event_id=uuid.uuid4(),
            maximum_privacy_class=PrivacyClass.NORMAL,
        )
        self.assertTrue(current_only)
        self.assertEqual({item.session_id for item in current_only}, {first_session})
        self.assertTrue(
            any(item.event_id == first.user_event_id for item in current_only)
        )

        empty_session = uuid.uuid4()
        self.assertEqual(
            self.repository.select_conversation_history(
                owner_id=isolated_owner,
                session_id=empty_session,
                exclude_event_id=uuid.uuid4(),
                maximum_privacy_class=PrivacyClass.NORMAL,
            ),
            (),
        )
        explicit_fallback = self.repository.select_conversation_history(
            owner_id=isolated_owner,
            session_id=empty_session,
            exclude_event_id=uuid.uuid4(),
            maximum_privacy_class=PrivacyClass.NORMAL,
            include_cross_session_fallback=True,
        )
        self.assertTrue(explicit_fallback)
        self.assertLessEqual(len(explicit_fallback), 6)
        self.assertNotIn(empty_session, {item.session_id for item in explicit_fallback})

    async def test_provider_failure_never_creates_delivered_assistant_event(self) -> None:
        class FailingProvider(DeterministicLocalProvider):
            async def generate(self, request):
                raise RuntimeError("synthetic_provider_failure")

        service = InteractionService(
            owner_id=self.owner_id,
            identity=self.identity,
            repository=self.repository,
            context_builder=ContextBuilder(max_input_tokens=4096, reserved_output_tokens=256),
            router=Stage1Router(),
            provider=FailingProvider(),
        )
        key = f"failure-{uuid.uuid4()}"
        with self.assertRaisesRegex(RuntimeError, "synthetic_provider_failure"):
            await service.interact(
                InteractionCommand(
                    message="This request should fail before delivery.",
                    privacy_class=PrivacyClass.NORMAL,
                    channel="api",
                    idempotency_key=key,
                )
            )
        with self.repository.pool.connection() as connection:
            request = connection.execute(
                """
                SELECT request_id, status, assistant_event_id
                FROM havre.interaction_requests
                WHERE owner_id = %s AND idempotency_key = %s
                """,
                (self.owner_id, key),
            ).fetchone()
        self.assertEqual(request["status"], "failed")
        self.assertIsNone(request["assistant_event_id"])
        from companion.product import DailyCompanionStore

        timeline = DailyCompanionStore(
            repository=self.repository,
            owner_id=self.owner_id,
        ).timeline(limit=100)
        failed_user = next(
            item
            for item in timeline["items"]
            if item["request_id"] == request["request_id"]
        )
        self.assertEqual(failed_user["role"], "user")
        self.assertEqual(failed_user["interaction_status"], "failed")
        self.assertIsNotNone(failed_user["interaction_error_code"])
        self.assertEqual(failed_user["provider_id"], "deterministic-local")
        self.assertEqual(
            failed_user["model_version_id"],
            "deterministic-companion-v1",
        )
        self.assertEqual(failed_user["execution_environment"], "local")
        evidence = self.repository.evidence(
            request["request_id"],
            owner_id=self.owner_id,
        )
        self.assertEqual(
            [event["event_type"] for event in evidence["events"]],
            ["USER_MESSAGE", "INTERACTION_FAILED"],
        )

    async def test_unexpected_pre_context_failure_is_typed_and_content_free(
        self,
    ) -> None:
        original = self.repository.select_personal_context
        sensitive_marker = "do-not-copy-this-early-failure-message"

        def fail_before_context(**_kwargs):
            raise RuntimeError(sensitive_marker)

        self.repository.select_personal_context = fail_before_context
        key = f"pre-context-error-{uuid.uuid4()}"
        try:
            with self.assertRaisesRegex(RuntimeError, sensitive_marker):
                await self.service.interact(InteractionCommand(
                    message="Persist only typed failure metadata for this error.",
                    privacy_class=PrivacyClass.NORMAL,
                    channel="api",
                    idempotency_key=key,
                ))
        finally:
            self.repository.select_personal_context = original

        with self.repository.pool.connection() as connection:
            request = connection.execute(
                """SELECT request_id,status,error_code,context_pack_id,
                          inference_attempt_id,assistant_event_id,failure_event_id
                   FROM havre.interaction_requests
                   WHERE owner_id=%s AND idempotency_key=%s""",
                (self.owner_id, key),
            ).fetchone()
            failure_payload = connection.execute(
                """SELECT payload FROM havre.events
                   WHERE owner_id=%s AND event_id=%s""",
                (self.owner_id, request["failure_event_id"]),
            ).fetchone()["payload"]
        self.assertEqual(request["status"], "failed")
        self.assertEqual(request["error_code"], "internal_error")
        self.assertIsNone(request["context_pack_id"])
        self.assertIsNone(request["inference_attempt_id"])
        self.assertIsNone(request["assistant_event_id"])
        self.assertIsNotNone(request["failure_event_id"])
        self.assertEqual(failure_payload["failure_stage"], "context_build")
        self.assertEqual(failure_payload["failure_code"], "internal_error")
        self.assertFalse(failure_payload["retryable"])
        self.assertNotIn(sensitive_marker, json.dumps(failure_payload))

    async def test_cancellation_before_context_is_typed_before_reraising(
        self,
    ) -> None:
        original = self.repository.select_personal_context
        entered = threading.Event()
        release = threading.Event()

        def block_before_context(**kwargs):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("pre-context cancellation fixture timed out")
            return original(**kwargs)

        self.repository.select_personal_context = block_before_context
        key = f"pre-context-cancel-{uuid.uuid4()}"
        task = asyncio.create_task(self.service.interact(InteractionCommand(
            message="Cancel only after the USER_MESSAGE is durable.",
            privacy_class=PrivacyClass.NORMAL,
            channel="api",
            idempotency_key=key,
        )))
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait, 5))
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        finally:
            release.set()
            self.repository.select_personal_context = original

        with self.repository.pool.connection() as connection:
            request = connection.execute(
                """SELECT request_id,status,error_code,context_pack_id,
                          inference_attempt_id,assistant_event_id,failure_event_id
                   FROM havre.interaction_requests
                   WHERE owner_id=%s AND idempotency_key=%s""",
                (self.owner_id, key),
            ).fetchone()
            failure_payload = connection.execute(
                """SELECT payload FROM havre.events
                   WHERE owner_id=%s AND event_id=%s""",
                (self.owner_id, request["failure_event_id"]),
            ).fetchone()["payload"]
        self.assertEqual(request["status"], "failed")
        self.assertEqual(request["error_code"], "interaction_cancelled")
        self.assertIsNone(request["context_pack_id"])
        self.assertIsNone(request["inference_attempt_id"])
        self.assertIsNone(request["assistant_event_id"])
        self.assertIsNotNone(request["failure_event_id"])
        self.assertEqual(failure_payload["failure_stage"], "context_build")
        self.assertEqual(failure_payload["failure_code"], "interaction_cancelled")
        self.assertTrue(failure_payload["retryable"])

    async def test_terminal_event_sql_guards_reject_shape_bypasses(self) -> None:
        completed = await self.service.interact(
            InteractionCommand(
                message="Create exact completion lineage for SQL guard attacks.",
                privacy_class=PrivacyClass.NORMAL,
                channel="api",
                idempotency_key=f"terminal-shape-completed-{uuid.uuid4()}",
            )
        )
        completed_evidence = self.repository.evidence(
            completed.request_id,
            owner_id=self.owner_id,
        )
        assistant_event_id = completed_evidence["request"]["assistant_event_id"]

        def cloned_hash() -> str:
            return "sha256:" + uuid.uuid4().hex + uuid.uuid4().hex

        processing_request_id = uuid7()
        processing_session_id = uuid7()
        processing_trace = TraceContext.from_traceparent(None)
        processing_policy = DataPolicy.owner_default(
            PrivacyClass.NORMAL,
            memory_eligible=True,
        )
        processing_user = EventEnvelope(
            event_type=EventType.USER_MESSAGE,
            owner_id=self.owner_id,
            session_id=processing_session_id,
            request_id=processing_request_id,
            trace_id=processing_trace.trace_id,
            data_policy=processing_policy,
            payload=UserMessagePayload(
                content_parts=(
                    TextContentPart(text="Processing request for shape attacks."),
                ),
                channel="api",
            ),
        )
        reservation = self.repository.reserve_interaction(
            idempotency_key=f"terminal-shape-processing-{uuid.uuid4()}",
            request_fingerprint=cloned_hash(),
            user_event=processing_user,
            trace=processing_trace,
            channel="api",
            trace_started_at=processing_user.recorded_at,
        )
        self.assertTrue(reservation.created)

        for inserted_status in ("completed", "failed"):
            with self.subTest(noncanonical_insert_status=inserted_status):
                inserted_request_id = uuid7()
                inserted_trace = TraceContext.from_traceparent(None)
                with self.assertRaises(
                    psycopg.errors.ObjectNotInPrerequisiteState
                ) as insert_error:
                    with self.repository.pool.connection() as connection:
                        with connection.transaction():
                            connection.execute(
                                """INSERT INTO havre.traces (
                                     trace_id,owner_id,root_request_id,
                                     incoming_parent_span_id,trace_flags,started_at
                                   ) VALUES (%s,%s,%s,%s,%s,%s)""",
                                (
                                    inserted_trace.trace_id,
                                    self.owner_id,
                                    inserted_request_id,
                                    inserted_trace.parent_span_id,
                                    inserted_trace.trace_flags,
                                    processing_user.recorded_at,
                                ),
                            )
                            connection.execute(
                                """INSERT INTO havre.interaction_requests (
                                     request_id,owner_id,session_id,trace_id,
                                     idempotency_key,request_fingerprint,status
                                   ) VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                                (
                                    inserted_request_id,
                                    self.owner_id,
                                    processing_session_id,
                                    inserted_trace.trace_id,
                                    f"forged-terminal-insert-{uuid.uuid4()}",
                                    cloned_hash(),
                                    inserted_status,
                                ),
                            )
                self.assertEqual(insert_error.exception.sqlstate, "55000")

        for payload_sql in (
            "payload - 'context_pack_id'",
            "payload - 'context_pack_id' - 'inference_response_id'",
        ):
            with self.subTest(payload_sql=payload_sql):
                with self.assertRaises(
                    psycopg.errors.ObjectNotInPrerequisiteState
                ) as assistant_error:
                    with self.repository.pool.connection() as connection:
                        with connection.transaction():
                            connection.execute(
                                f"""INSERT INTO havre.events (
                                     event_id,schema_version,event_type,event_version,
                                     owner_id,session_id,request_id,trace_id,
                                     causation_event_id,privacy_class,memory_eligible,
                                     training_eligible,cloud_eligible,policy_version,
                                     policy_revision_id,policy_decision_source,
                                     policy_authorization_ref,payload,content_hash,
                                     recorded_at
                                   )
                                   SELECT %s,schema_version,event_type,event_version,
                                          owner_id,%s,%s,%s,%s,
                                          privacy_class,memory_eligible,
                                          training_eligible,cloud_eligible,policy_version,
                                          policy_revision_id,policy_decision_source,
                                          policy_authorization_ref,{payload_sql},%s,
                                          clock_timestamp()
                                   FROM havre.events
                                   WHERE owner_id=%s AND event_id=%s""",
                                (
                                    uuid7(),
                                    processing_session_id,
                                    processing_request_id,
                                    processing_trace.trace_id,
                                    processing_user.event_id,
                                    cloned_hash(),
                                    self.owner_id,
                                    assistant_event_id,
                                ),
                            )
                self.assertEqual(assistant_error.exception.sqlstate, "55000")

        with self.assertRaises(
            psycopg.errors.ObjectNotInPrerequisiteState
        ) as duplicate_error:
            with self.repository.pool.connection() as connection:
                with connection.transaction():
                    connection.execute(
                        """INSERT INTO havre.events (
                             event_id,schema_version,event_type,event_version,
                             owner_id,session_id,request_id,trace_id,
                             causation_event_id,privacy_class,memory_eligible,
                             training_eligible,cloud_eligible,policy_version,
                             policy_revision_id,policy_decision_source,
                             policy_authorization_ref,payload,content_hash,
                             recorded_at
                           )
                           SELECT %s,schema_version,event_type,event_version,
                                  owner_id,session_id,request_id,trace_id,
                                  causation_event_id,privacy_class,memory_eligible,
                                  training_eligible,cloud_eligible,policy_version,
                                  policy_revision_id,policy_decision_source,
                                  policy_authorization_ref,payload,%s,
                                  clock_timestamp()
                           FROM havre.events
                           WHERE owner_id=%s AND event_id=%s""",
                        (
                            uuid7(),
                            cloned_hash(),
                            self.owner_id,
                            assistant_event_id,
                        ),
                    )
        self.assertEqual(duplicate_error.exception.sqlstate, "55000")

        class FailingProvider(DeterministicLocalProvider):
            async def generate(self, request):
                raise RuntimeError("failure fixture for SQL guard attacks")

        failing_service = InteractionService(
            owner_id=self.owner_id,
            identity=self.identity,
            repository=self.repository,
            context_builder=ContextBuilder(
                max_input_tokens=4096,
                reserved_output_tokens=256,
            ),
            router=Stage1Router(),
            provider=FailingProvider(),
        )
        failure_key = f"terminal-shape-failed-{uuid.uuid4()}"
        with self.assertRaisesRegex(RuntimeError, "failure fixture"):
            await failing_service.interact(
                InteractionCommand(
                    message="Create exact failed lineage for SQL guard attacks.",
                    privacy_class=PrivacyClass.NORMAL,
                    channel="api",
                    idempotency_key=failure_key,
                )
            )
        with self.repository.pool.connection() as connection:
            failed_request = connection.execute(
                """SELECT request_id,failure_event_id
                   FROM havre.interaction_requests
                   WHERE owner_id=%s AND idempotency_key=%s""",
                (self.owner_id, failure_key),
            ).fetchone()

        for stage in ("unknown_stage", "routing"):
            with self.subTest(failure_stage=stage):
                with self.assertRaises(
                    psycopg.errors.ObjectNotInPrerequisiteState
                ) as failure_error:
                    with self.repository.pool.connection() as connection:
                        with connection.transaction():
                            connection.execute(
                                """INSERT INTO havre.events (
                                     event_id,schema_version,event_type,event_version,
                                     owner_id,session_id,request_id,trace_id,
                                     causation_event_id,privacy_class,memory_eligible,
                                     training_eligible,cloud_eligible,policy_version,
                                     policy_revision_id,policy_decision_source,
                                     policy_authorization_ref,payload,content_hash,
                                     recorded_at
                                   )
                                   SELECT %s,schema_version,event_type,event_version,
                                          owner_id,%s,%s,%s,%s,
                                          privacy_class,memory_eligible,
                                          training_eligible,cloud_eligible,policy_version,
                                          policy_revision_id,policy_decision_source,
                                          policy_authorization_ref,
                                          jsonb_set(
                                              payload,
                                              '{failure_stage}',
                                              to_jsonb(%s::text)
                                          ),
                                          %s,clock_timestamp()
                                   FROM havre.events
                                   WHERE owner_id=%s AND event_id=%s""",
                                (
                                    uuid7(),
                                    processing_session_id,
                                    processing_request_id,
                                    processing_trace.trace_id,
                                    processing_user.event_id,
                                    stage,
                                    cloned_hash(),
                                    self.owner_id,
                                    failed_request["failure_event_id"],
                                ),
                            )
                self.assertEqual(failure_error.exception.sqlstate, "55000")

        for stage in ("version_check", "inference"):
            for missing_key in ("route_decision_id", "inference_request_id"):
                with self.subTest(
                    failure_stage=stage,
                    missing_required_key=missing_key,
                ):
                    with self.assertRaises(
                        psycopg.errors.ObjectNotInPrerequisiteState
                    ) as missing_key_error:
                        with self.repository.pool.connection() as connection:
                            with connection.transaction():
                                connection.execute(
                                    """INSERT INTO havre.events (
                                         event_id,schema_version,event_type,event_version,
                                         owner_id,session_id,request_id,trace_id,
                                         causation_event_id,privacy_class,memory_eligible,
                                         training_eligible,cloud_eligible,policy_version,
                                         policy_revision_id,policy_decision_source,
                                         policy_authorization_ref,payload,content_hash,
                                         recorded_at
                                       )
                                       SELECT %s,schema_version,event_type,event_version,
                                              owner_id,%s,%s,%s,%s,
                                              privacy_class,memory_eligible,
                                              training_eligible,cloud_eligible,policy_version,
                                              policy_revision_id,policy_decision_source,
                                              policy_authorization_ref,
                                              jsonb_set(
                                                  payload,
                                                  '{failure_stage}',
                                                  to_jsonb(%s::text)
                                              ) - %s,
                                              %s,clock_timestamp()
                                       FROM havre.events
                                       WHERE owner_id=%s AND event_id=%s""",
                                    (
                                        uuid7(),
                                        processing_session_id,
                                        processing_request_id,
                                        processing_trace.trace_id,
                                        processing_user.event_id,
                                        stage,
                                        missing_key,
                                        cloned_hash(),
                                        self.owner_id,
                                        failed_request["failure_event_id"],
                                    ),
                                )
                    self.assertEqual(
                        missing_key_error.exception.sqlstate,
                        "55000",
                    )

        terminal_mutations = (
            (
                "completed_clear",
                "UPDATE havre.interaction_requests "
                "SET assistant_event_id=NULL WHERE owner_id=%s AND request_id=%s",
                completed.request_id,
            ),
            (
                "completed_swap",
                "UPDATE havre.interaction_requests SET status='failed',"
                "failure_event_id=assistant_event_id,assistant_event_id=NULL,"
                "error_code='forged_terminal_swap' "
                "WHERE owner_id=%s AND request_id=%s",
                completed.request_id,
            ),
            (
                "completed_mutate",
                "UPDATE havre.interaction_requests "
                "SET context_pack_id=NULL WHERE owner_id=%s AND request_id=%s",
                completed.request_id,
            ),
            (
                "failed_clear",
                "UPDATE havre.interaction_requests "
                "SET failure_event_id=NULL WHERE owner_id=%s AND request_id=%s",
                failed_request["request_id"],
            ),
            (
                "failed_swap",
                "UPDATE havre.interaction_requests SET status='completed',"
                "assistant_event_id=failure_event_id,failure_event_id=NULL,"
                "error_code=NULL "
                "WHERE owner_id=%s AND request_id=%s",
                failed_request["request_id"],
            ),
            (
                "failed_mutate",
                "UPDATE havre.interaction_requests "
                "SET error_code='forged_terminal_error' "
                "WHERE owner_id=%s AND request_id=%s",
                failed_request["request_id"],
            ),
        )
        for name, statement, request_id in terminal_mutations:
            with self.subTest(terminal_mutation=name):
                with self.assertRaises(
                    psycopg.errors.ObjectNotInPrerequisiteState
                ) as mutation_error:
                    with self.repository.pool.connection() as connection:
                        with connection.transaction():
                            connection.execute(
                                statement,
                                (self.owner_id, request_id),
                            )
                self.assertEqual(mutation_error.exception.sqlstate, "55000")

        with self.repository.pool.connection() as connection:
            try:
                connection.execute("SET LOCAL havre.privileged_erasure = 'on'")
                tombstone = connection.execute(
                    """UPDATE havre.interaction_requests SET
                           assistant_event_id=NULL,context_pack_id=NULL,
                           inference_attempt_id=NULL,inference_response_id=NULL,
                           failure_event_id=NULL,status='failed',
                           error_code='source_erasure_propagated',
                           completed_at=COALESCE(completed_at,statement_timestamp())
                       WHERE owner_id=%s AND request_id=%s
                       RETURNING status,assistant_event_id,failure_event_id,
                                 context_pack_id,inference_attempt_id,
                                 inference_response_id,error_code,user_event_id,
                                 completed_at""",
                    (self.owner_id, completed.request_id),
                ).fetchone()
                self.assertEqual(tombstone["status"], "failed")
                self.assertEqual(
                    tombstone["error_code"],
                    "source_erasure_propagated",
                )
                self.assertTrue(all(
                    tombstone[column] is None
                    for column in (
                        "assistant_event_id",
                        "failure_event_id",
                        "context_pack_id",
                        "inference_attempt_id",
                        "inference_response_id",
                    )
                ))
                raw_pointer_cleared = connection.execute(
                    """UPDATE havre.interaction_requests
                       SET user_event_id=NULL
                       WHERE owner_id=%s AND request_id=%s
                       RETURNING user_event_id,error_code,completed_at""",
                    (self.owner_id, completed.request_id),
                ).fetchone()
                self.assertIsNone(raw_pointer_cleared["user_event_id"])
                self.assertEqual(
                    raw_pointer_cleared["error_code"],
                    "source_erasure_propagated",
                )
                self.assertEqual(
                    raw_pointer_cleared["completed_at"],
                    tombstone["completed_at"],
                )
            finally:
                # This probe proves the transition guard permits the exact
                # governed shape without altering the shared integration data.
                connection.rollback()

        with self.repository.pool.connection() as connection:
            try:
                connection.execute("SET LOCAL havre.privileged_erasure = 'on'")
                processing_tombstone = connection.execute(
                    """UPDATE havre.interaction_requests SET
                           assistant_event_id=NULL,context_pack_id=NULL,
                           inference_attempt_id=NULL,inference_response_id=NULL,
                           failure_event_id=NULL,status='failed',
                           error_code='source_erasure_propagated',
                           completed_at=COALESCE(completed_at,statement_timestamp())
                       WHERE owner_id=%s AND request_id=%s
                       RETURNING status,user_event_id,completed_at""",
                    (self.owner_id, processing_request_id),
                ).fetchone()
                self.assertEqual(processing_tombstone["status"], "failed")
                self.assertEqual(
                    processing_tombstone["user_event_id"],
                    processing_user.event_id,
                )
                self.assertIsNotNone(processing_tombstone["completed_at"])
            finally:
                connection.rollback()

    async def test_concurrent_terminal_events_commit_exactly_one_canonical_reply(
        self,
    ) -> None:
        completed = await self.service.interact(
            InteractionCommand(
                message="Create a canonical completion to seed a terminal race.",
                privacy_class=PrivacyClass.NORMAL,
                channel="api",
                idempotency_key=f"terminal-race-source-{uuid.uuid4()}",
            )
        )
        completed_evidence = self.repository.evidence(
            completed.request_id,
            owner_id=self.owner_id,
        )
        assert completed_evidence is not None

        def cloned_hash() -> str:
            return "sha256:" + uuid.uuid4().hex + uuid.uuid4().hex

        request_id = uuid7()
        session_id = uuid7()
        trace = TraceContext.from_traceparent(None)
        policy = DataPolicy.owner_default(
            PrivacyClass.NORMAL,
            memory_eligible=True,
        )
        user_event = EventEnvelope(
            event_type=EventType.USER_MESSAGE,
            owner_id=self.owner_id,
            session_id=session_id,
            request_id=request_id,
            trace_id=trace.trace_id,
            data_policy=policy,
            payload=UserMessagePayload(
                content_parts=(
                    TextContentPart(text="Two SQL writers race one terminal reply."),
                ),
                channel="api",
            ),
        )
        reservation = self.repository.reserve_interaction(
            idempotency_key=f"terminal-race-target-{uuid.uuid4()}",
            request_fingerprint=cloned_hash(),
            user_event=user_event,
            trace=trace,
            channel="api",
            trace_started_at=user_event.recorded_at,
        )
        self.assertTrue(reservation.created)

        with self.repository.pool.connection() as connection:
            source_context = dict(connection.execute(
                "SELECT * FROM havre.context_packs WHERE request_id=%s",
                (completed.request_id,),
            ).fetchone())
            source_route = dict(connection.execute(
                "SELECT * FROM havre.route_decisions WHERE request_id=%s",
                (completed.request_id,),
            ).fetchone())
            source_attempt = dict(connection.execute(
                "SELECT * FROM havre.inference_attempts WHERE request_id=%s",
                (completed.request_id,),
            ).fetchone())
            source_assistant = dict(connection.execute(
                "SELECT * FROM havre.events WHERE owner_id=%s AND event_id=%s",
                (
                    self.owner_id,
                    completed_evidence["request"]["assistant_event_id"],
                ),
            ).fetchone())

        context_pack_id = uuid7()
        route_decision_id = uuid7()
        inference_attempt_id = uuid7()
        inference_response_id = uuid7()

        context_row = copy.deepcopy(source_context)
        context_row.update({
            "context_pack_id": context_pack_id,
            "request_id": request_id,
            "trace_id": trace.trace_id,
            "content_hash": cloned_hash(),
            "retrieval_result_id": None,
        })
        route_row = copy.deepcopy(source_route)
        route_row.update({
            "route_decision_id": route_decision_id,
            "request_id": request_id,
            "trace_id": trace.trace_id,
        })
        attempt_row = copy.deepcopy(source_attempt)
        attempt_row.update({
            "inference_attempt_id": inference_attempt_id,
            "inference_response_id": inference_response_id,
            "inference_request_id": inference_attempt_id,
            "request_id": request_id,
            "trace_id": trace.trace_id,
            "context_pack_id": context_pack_id,
            "route_decision_id": route_decision_id,
            "attempt_number": 1,
            "provider_request_id": f"terminal-race-{uuid.uuid4()}",
        })

        def insert_row(connection, table: str, row: dict, json_columns: set[str]):
            adapted = dict(row)
            for column in json_columns:
                if adapted.get(column) is not None:
                    adapted[column] = Jsonb(adapted[column])
            columns = tuple(adapted)
            statement = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                sql.Identifier("havre", table),
                sql.SQL(", ").join(map(sql.Identifier, columns)),
                sql.SQL(", ").join(sql.Placeholder() for _ in columns),
            )
            connection.execute(
                statement,
                tuple(adapted[column] for column in columns),
            )

        with self.repository.pool.connection() as connection, connection.transaction():
            insert_row(
                connection,
                "context_packs",
                context_row,
                {"token_budget", "sections", "excluded_candidates"},
            )
            insert_row(
                connection,
                "route_decisions",
                route_row,
                {"eligible_candidates", "excluded_candidates"},
            )
            insert_row(
                connection,
                "inference_attempts",
                attempt_row,
                {"usage", "timing_ms", "failure"},
            )

        payload = copy.deepcopy(source_assistant["payload"])
        decision_id = uuid7()
        payload.update({
            "context_pack_id": str(context_pack_id),
            "inference_response_id": str(inference_response_id),
            "policy_decision_id": str(decision_id),
        })
        decision = payload["response_policy_decision"]
        decision.update({
            "decision_id": str(decision_id),
            "request_id": str(request_id),
            "trace_id": trace.trace_id,
            "context_pack_id": str(context_pack_id),
            "inference_response_id": str(inference_response_id),
        })
        decision["content_hash"] = content_hash({
            key: value
            for key, value in decision.items()
            if key not in {"content_hash", "created_at"}
        })

        def event_row(event_id, event_payload: dict | None = None) -> dict:
            row = copy.deepcopy(source_assistant)
            row.update({
                "event_id": event_id,
                "session_id": session_id,
                "request_id": request_id,
                "trace_id": trace.trace_id,
                "causation_event_id": user_event.event_id,
                "payload": copy.deepcopy(
                    payload if event_payload is None else event_payload
                ),
                "content_hash": cloned_hash(),
                "recorded_at": user_event.recorded_at,
            })
            return row

        missing_policy_id_payload = copy.deepcopy(payload)
        missing_policy_id_payload.pop("policy_decision_id")
        missing_decision_id_payload = copy.deepcopy(payload)
        missing_decision_id_payload["response_policy_decision"].pop("decision_id")
        for name, invalid_payload in (
            ("top_level_policy_decision_id", missing_policy_id_payload),
            ("nested_decision_id", missing_decision_id_payload),
        ):
            with self.subTest(missing_response_policy_id=name):
                with self.assertRaises(
                    psycopg.errors.ObjectNotInPrerequisiteState
                ) as missing_policy_error:
                    with self.repository.pool.connection() as connection:
                        with connection.transaction():
                            insert_row(
                                connection,
                                "events",
                                event_row(uuid7(), invalid_payload),
                                {"payload"},
                            )
                self.assertEqual(missing_policy_error.exception.sqlstate, "55000")

        tampered = event_row(uuid7())
        tampered["payload"]["content_parts"][0]["text"] += " forged"
        with self.assertRaises(
            psycopg.errors.ObjectNotInPrerequisiteState
        ) as tamper_error:
            with self.repository.pool.connection() as connection:
                with connection.transaction():
                    insert_row(connection, "events", tampered, {"payload"})
        self.assertEqual(tamper_error.exception.sqlstate, "55000")

        barrier = threading.Barrier(2)

        def compete(event_id) -> tuple[str, uuid.UUID]:
            try:
                with psycopg.connect(DATABASE_URL) as connection:
                    with connection.transaction():
                        barrier.wait(timeout=10)
                        insert_row(
                            connection,
                            "events",
                            event_row(event_id),
                            {"payload"},
                        )
                        connection.execute(
                            """UPDATE havre.interaction_requests SET
                                   status='completed',assistant_event_id=%s,
                                   context_pack_id=%s,inference_attempt_id=%s,
                                   inference_response_id=%s,
                                   completed_at=clock_timestamp()
                               WHERE owner_id=%s AND request_id=%s""",
                            (
                                event_id,
                                context_pack_id,
                                inference_attempt_id,
                                inference_response_id,
                                self.owner_id,
                                request_id,
                            ),
                        )
                return ("committed", event_id)
            except psycopg.Error as exc:
                return (exc.sqlstate or "database_error", event_id)

        first_event_id = uuid7()
        second_event_id = uuid7()
        outcomes = await asyncio.gather(
            asyncio.to_thread(compete, first_event_id),
            asyncio.to_thread(compete, second_event_id),
        )
        self.assertEqual(
            sorted(outcome for outcome, _event_id in outcomes),
            ["55000", "committed"],
        )
        committed_event_id = next(
            event_id for outcome, event_id in outcomes if outcome == "committed"
        )

        with self.repository.pool.connection() as connection:
            request_row = connection.execute(
                """SELECT status,assistant_event_id
                   FROM havre.interaction_requests
                   WHERE owner_id=%s AND request_id=%s""",
                (self.owner_id, request_id),
            ).fetchone()
            terminal_count = connection.execute(
                """SELECT count(*) AS terminal_count
                   FROM havre.events
                   WHERE owner_id=%s AND request_id=%s
                     AND event_type IN ('ASSISTANT_MESSAGE','INTERACTION_FAILED')""",
                (self.owner_id, request_id),
            ).fetchone()["terminal_count"]
        self.assertEqual(request_row["status"], "completed")
        self.assertEqual(request_row["assistant_event_id"], committed_event_id)
        self.assertEqual(terminal_count, 1)

        from companion.product import DailyCompanionStore

        timeline = DailyCompanionStore(
            repository=self.repository,
            owner_id=self.owner_id,
        ).timeline(limit=100)
        visible_assistants = [
            item
            for item in timeline["items"]
            if item["request_id"] == request_id and item["role"] == "assistant"
        ]
        self.assertEqual(len(visible_assistants), 1)
        self.assertEqual(visible_assistants[0]["event_id"], committed_event_id)

    async def test_timeout_is_enforced_and_request_does_not_stay_processing(self) -> None:
        class HangingProvider(DeterministicLocalProvider):
            cancelled = False

            async def generate(self, request):
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.cancelled = True
                    raise

        provider = HangingProvider()
        service = InteractionService(
            owner_id=self.owner_id,
            identity=self.identity,
            repository=self.repository,
            context_builder=ContextBuilder(max_input_tokens=4096, reserved_output_tokens=256),
            router=Stage1Router(),
            provider=provider,
            inference_timeout_ms=25,
        )
        key = f"timeout-{uuid.uuid4()}"
        started = time.perf_counter()
        with self.assertRaisesRegex(InferenceTimeoutError, "25 ms"):
            await service.interact(
                InteractionCommand(
                    message="The provider will hang.",
                    privacy_class=PrivacyClass.NORMAL,
                    channel="api",
                    idempotency_key=key,
                )
            )
        self.assertLess(time.perf_counter() - started, 1.0)
        self.assertTrue(provider.cancelled)
        with self.repository.pool.connection() as connection:
            request = connection.execute(
                """
                SELECT request_id, status, error_code, assistant_event_id
                FROM havre.interaction_requests
                WHERE owner_id = %s AND idempotency_key = %s
                """,
                (self.owner_id, key),
            ).fetchone()
        self.assertEqual(request["status"], "failed")
        self.assertEqual(request["error_code"], "provider_timeout")
        self.assertIsNone(request["assistant_event_id"])
        evidence = self.repository.evidence(
            request["request_id"],
            owner_id=self.owner_id,
        )
        self.assertEqual(
            [event["event_type"] for event in evidence["events"]],
            ["USER_MESSAGE", "INTERACTION_FAILED"],
        )

    async def test_idempotency_key_is_bound_to_request_content_and_policy(self) -> None:
        key = f"fingerprint-{uuid.uuid4()}"
        original = InteractionCommand(
            message="Original message.",
            privacy_class=PrivacyClass.NORMAL,
            channel="api",
            idempotency_key=key,
        )
        result = await self.service.interact(original)
        replay = await self.service.interact(original)
        self.assertEqual(result.request_id, replay.request_id)
        with self.assertRaises(IdempotencyConflict):
            await self.service.interact(
                original.model_copy(update={"message": "Different message."})
            )
        with self.assertRaises(IdempotencyConflict):
            await self.service.interact(
                original.model_copy(update={"privacy_class": PrivacyClass.PRIVATE})
            )
        with self.repository.pool.connection() as connection:
            counts = connection.execute(
                """
                SELECT
                    count(*) AS requests,
                    (SELECT count(*) FROM havre.events WHERE request_id = %s) AS events
                FROM havre.interaction_requests
                WHERE owner_id = %s AND idempotency_key = %s
                """,
                (result.request_id, self.owner_id, key),
            ).fetchone()
        self.assertEqual(counts["requests"], 1)
        self.assertEqual(counts["events"], 2)

    async def test_identity_versions_and_evidence_are_owner_isolated(self) -> None:
        self.repository.bootstrap_owner_and_identity(
            owner_id=self.owner_id,
            identity=self.identity,
        )
        self.repository.bootstrap_owner_and_identity(
            owner_id=self.second_owner_id,
            identity=self.identity,
        )
        with self.repository.pool.connection() as connection:
            owners = connection.execute(
                """
                SELECT owner_id, count(*) AS versions
                FROM havre.identity_artifact_versions
                WHERE owner_id IN (%s, %s)
                GROUP BY owner_id
                ORDER BY owner_id
                """,
                (self.owner_id, self.second_owner_id),
            ).fetchall()
        self.assertEqual({row["owner_id"] for row in owners}, {self.owner_id, self.second_owner_id})
        self.assertTrue(all(row["versions"] == 3 for row in owners))

        result = await self.service.interact(
            InteractionCommand(
                message="Owner-isolated evidence.",
                privacy_class=PrivacyClass.PRIVATE,
                channel="api",
                idempotency_key=f"owner-isolation-{uuid.uuid4()}",
            )
        )
        self.assertIsNotNone(
            self.repository.evidence(result.request_id, owner_id=self.owner_id)
        )
        self.assertIsNone(
            self.repository.evidence(result.request_id, owner_id=self.second_owner_id)
        )

        second_service = InteractionService(
            owner_id=self.second_owner_id,
            identity=self.identity,
            repository=self.repository,
            context_builder=ContextBuilder(max_input_tokens=4096, reserved_output_tokens=256),
            router=Stage1Router(),
            provider=DeterministicLocalProvider(),
        )
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            await second_service.interact(
                InteractionCommand(
                    message="Cross-owner session reuse must fail.",
                    privacy_class=PrivacyClass.NORMAL,
                    session_id=result.session_id,
                    channel="api",
                    idempotency_key=f"cross-owner-{uuid.uuid4()}",
                )
            )

    async def test_provider_swap_preserves_core_and_cannot_activate_identity(self) -> None:
        class AlternateProvider(DeterministicLocalProvider):
            provider_id = "deterministic-local-alternate"
            model_version_id = "deterministic-companion-v2-test"
            adapter_version_id = "deterministic-adapter-v2-test"
            serving_config_version = "deterministic-serving-v2-test"

        with self.repository.pool.connection() as connection:
            before = connection.execute(
                """
                SELECT count(*) FROM havre.identity_artifact_versions
                WHERE owner_id = %s
                """,
                (self.owner_id,),
            ).fetchone()["count"]
        swapped = InteractionService(
            owner_id=self.owner_id,
            identity=self.identity,
            repository=self.repository,
            context_builder=ContextBuilder(max_input_tokens=4096, reserved_output_tokens=256),
            router=Stage1Router(),
            provider=AlternateProvider(),
        )
        result = await swapped.interact(
            InteractionCommand(
                message="Exercise the alternate provider.",
                privacy_class=PrivacyClass.NORMAL,
                channel="api",
                idempotency_key=f"provider-swap-{uuid.uuid4()}",
            )
        )
        self.assertEqual(result.provider_id, "deterministic-local-alternate")
        self.assertEqual(result.model_version_id, "deterministic-companion-v2-test")
        with self.repository.pool.connection() as connection:
            after = connection.execute(
                """
                SELECT count(*) FROM havre.identity_artifact_versions
                WHERE owner_id = %s
                """,
                (self.owner_id,),
            ).fetchone()["count"]
        self.assertEqual(before, after)

    async def test_default_codex_route_is_core_governed_and_durable(self) -> None:
        async def runner(args, _stdin_text, _cwd, _environment, _timeout_ms):
            if args[-1] == "--version":
                return CodexProcessResult(0, "codex-cli 0.152.0\n", "")
            if args[1:] == ("login", "status"):
                return CodexProcessResult(0, "Logged in using ChatGPT\n", "")
            return CodexProcessResult(0, "\n".join((
                json.dumps({"type": "thread.started", "thread_id": "durable-thread"}),
                json.dumps({"type": "turn.started"}),
                json.dumps({
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": "我理解完整了。我们先处理最重要的一件事。"},
                }, ensure_ascii=False),
                json.dumps({
                    "type": "turn.completed",
                    "usage": {
                        "input_tokens": 120,
                        "cached_input_tokens": 0,
                        "output_tokens": 20,
                        "reasoning_output_tokens": 0,
                    },
                }),
            )), "")

        with tempfile.TemporaryDirectory() as value:
            executable = Path(value) / "codex.exe"
            executable.touch()
            provider = CodexCliProvider(
                executable=executable,
                enabled=True,
                explicit_authorization_ref=CODEX_OWNER_AUTOMATIC_AUTHORIZATION_REF,
                process_runner=runner,
            )
            service = InteractionService(
                owner_id=self.owner_id,
                identity=self.identity,
                repository=self.repository,
                context_builder=ContextBuilder(
                    max_input_tokens=4096,
                    reserved_output_tokens=256,
                ),
                router=Stage1Router(
                    approved_cloud_provider_ids=frozenset({CODEX_CLI_PROVIDER_ID})
                ),
                provider=provider,
                request_binder=bind_codex_cli_request,
                inference_timeout_ms=30_000,
            )
            result = await service.interact(InteractionCommand(
                message="请完整理解上下文后回答。",
                privacy_class=PrivacyClass.NORMAL,
                memory_eligible=True,
                channel="web",
                idempotency_key=f"codex-default-{uuid.uuid4()}",
            ))

        self.assertEqual(result.provider_id, CODEX_CLI_PROVIDER_ID)
        self.assertEqual(result.content, "我理解完整了。我们先处理最重要的一件事。")
        self.assertTrue(result.cloud_eligible)
        self.assertFalse(result.training_eligible)
        evidence = self.repository.evidence(result.request_id, owner_id=self.owner_id)
        self.assertIsNotNone(evidence)
        assert evidence is not None
        self.assertEqual(evidence["inference"]["provider_id"], CODEX_CLI_PROVIDER_ID)
        self.assertEqual(
            evidence["events"][-1]["payload"]["content_parts"][0]["text"],
            result.content,
        )

    async def test_privacy_router_uses_gpt_for_normal_and_unadapted_local_for_private(
        self,
    ) -> None:
        cloud_prompts: list[str] = []

        async def runner(args, stdin_text, _cwd, _environment, _timeout_ms):
            if args[-1] == "--version":
                return CodexProcessResult(0, "codex-cli 0.152.0\n", "")
            if args[1:] == ("login", "status"):
                return CodexProcessResult(0, "Logged in using ChatGPT\n", "")
            cloud_prompts.append(stdin_text or "")
            number = len(cloud_prompts)
            return CodexProcessResult(0, "\n".join((
                json.dumps({
                    "type": "thread.started",
                    "thread_id": f"privacy-route-cloud-{number}",
                }),
                json.dumps({"type": "turn.started"}),
                json.dumps({
                    "type": "item.completed",
                    "item": {
                        "type": "agent_message",
                        "text": f"cloud reply {number}",
                    },
                }),
                json.dumps({
                    "type": "turn.completed",
                    "usage": {
                        "input_tokens": 120,
                        "cached_input_tokens": 0,
                        "output_tokens": 10,
                        "reasoning_output_tokens": 0,
                    },
                }),
            )), "")

        class UnadaptedLocalProvider(DeterministicLocalProvider):
            provider_id = "local-qwen-base-test"
            model_version_id = "qwen3-8b-base-test"
            adapter_version_id = None
            output = "local private reply"

            def __init__(self):
                super().__init__(
                    active_adapter_version_id=None,
                    active_adapter_artifact_hash=None,
                )
                self.requests = []

            async def generate(self, request):
                self.requests.append(request)
                self.assert_local_request(request)
                return await super().generate(request)

            @staticmethod
            def assert_local_request(request):
                assert request.constraints.allowed_execution_environments == ("local",)
                assert not any(
                    key.startswith("cloud_") for key in request.metadata
                )

        with tempfile.TemporaryDirectory() as value:
            executable = Path(value) / "codex.exe"
            executable.touch()
            cloud = CodexCliProvider(
                executable=executable,
                enabled=True,
                explicit_authorization_ref=CODEX_OWNER_AUTOMATIC_AUTHORIZATION_REF,
                process_runner=runner,
            )
            local = UnadaptedLocalProvider()
            router = PrivacyClassRouter(
                cloud_provider_id=CODEX_CLI_PROVIDER_ID,
                local_provider_id=local.provider_id,
                approved_cloud_provider_ids=frozenset({CODEX_CLI_PROVIDER_ID}),
            )
            service = InteractionService(
                owner_id=self.owner_id,
                identity=self.identity,
                repository=self.repository,
                context_builder=ContextBuilder(
                    max_input_tokens=4096,
                    reserved_output_tokens=256,
                ),
                context_builders={
                    local.provider_id: ContextBuilder(
                        max_input_tokens=2048,
                        reserved_output_tokens=256,
                    )
                },
                router=router,
                provider=cloud,
                providers={
                    cloud.provider_id: cloud,
                    local.provider_id: local,
                },
                request_binders={
                    cloud.provider_id: bind_codex_cli_request,
                },
                inference_timeout_ms=30_000,
            )
            normal_command = InteractionCommand(
                message="普通日常对话",
                privacy_class=PrivacyClass.NORMAL,
                channel="web",
                idempotency_key=f"dual-normal-{uuid.uuid4()}",
            )
            normal = await service.interact(normal_command)
            normal_replay = await service.interact(normal_command)
            cloud_calls_after_normal_replay = len(cloud_prompts)
            private_command = InteractionCommand(
                message="这是私人对话",
                privacy_class=PrivacyClass.PRIVATE,
                channel="web",
                idempotency_key=f"dual-private-{uuid.uuid4()}",
            )
            private = await service.interact(private_command)
            private_replay = await service.interact(private_command)
            local_calls_after_private_replay = len(local.requests)
            highly_private = await service.interact(InteractionCommand(
                message="这是高度私人对话",
                privacy_class=PrivacyClass.HIGHLY_PRIVATE,
                channel="web",
                idempotency_key=f"dual-highly-private-{uuid.uuid4()}",
            ))
            synthetic_secret = "password: synthetic-secret-value-123"
            local_only = await service.interact(InteractionCommand(
                message=synthetic_secret,
                privacy_class=PrivacyClass.LOCAL_ONLY,
                channel="web",
                idempotency_key=f"dual-local-{uuid.uuid4()}",
            ))
            after_local_only = await service.interact(InteractionCommand(
                message="回到普通对话",
                privacy_class=PrivacyClass.NORMAL,
                session_id=local_only.session_id,
                channel="web",
                idempotency_key=f"dual-after-local-{uuid.uuid4()}",
            ))

        self.assertEqual(normal.provider_id, CODEX_CLI_PROVIDER_ID)
        self.assertTrue(normal_replay.idempotent_replay)
        self.assertEqual(normal_replay.request_id, normal.request_id)
        self.assertEqual(normal_replay.assistant_event_id, normal.assistant_event_id)
        self.assertEqual(cloud_calls_after_normal_replay, 1)
        self.assertTrue(private_replay.idempotent_replay)
        self.assertEqual(private_replay.request_id, private.request_id)
        self.assertEqual(private_replay.assistant_event_id, private.assistant_event_id)
        self.assertEqual(local_calls_after_private_replay, 1)
        self.assertEqual(after_local_only.provider_id, CODEX_CLI_PROVIDER_ID)
        self.assertEqual(private.provider_id, local.provider_id)
        self.assertEqual(highly_private.provider_id, local.provider_id)
        self.assertEqual(local_only.provider_id, local.provider_id)
        self.assertIsNone(private.adapter_version_id)
        self.assertEqual(len(cloud_prompts), 2)
        self.assertEqual(len(local.requests), 3)
        self.assertNotIn(synthetic_secret, cloud_prompts[-1])
        private_evidence = self.repository.evidence(
            private.request_id,
            owner_id=self.owner_id,
        )
        self.assertEqual(
            private_evidence["route_decision"]["reason"],
            "restricted_data_local_route",
        )
        self.assertEqual(
            private_evidence["route_decision"]["execution_environment"],
            "local",
        )
        local_only_evidence = self.repository.evidence(
            local_only.request_id,
            owner_id=self.owner_id,
        )
        local_only_user = local_only_evidence["events"][0]
        self.assertEqual(local_only_user["privacy_class"], "LOCAL_ONLY")
        for result, privacy_class in (
            (private, PrivacyClass.PRIVATE),
            (highly_private, PrivacyClass.HIGHLY_PRIVATE),
            (local_only, PrivacyClass.LOCAL_ONLY),
        ):
            with self.subTest(privacy_class=privacy_class):
                evidence = self.repository.evidence(
                    result.request_id,
                    owner_id=self.owner_id,
                )
                self.assertIsNotNone(evidence)
                assert evidence is not None
                self.assertEqual(
                    [event["event_type"] for event in evidence["events"]],
                    ["USER_MESSAGE", "ASSISTANT_MESSAGE"],
                )
                self.assertEqual(
                    evidence["events"][0]["privacy_class"],
                    privacy_class.value,
                )
                self.assertEqual(
                    evidence["route_decision"]["selected_provider_id"],
                    local.provider_id,
                )
                core_decision = evidence["events"][1]["payload"][
                    "response_policy_decision"
                ]
                self.assertEqual(
                    core_decision["policy_version"],
                    "core-response-policy-v1",
                )
                self.assertEqual(core_decision["action"], "pass_through")

    async def test_failed_gpt_route_never_calls_local_provider(self) -> None:
        cloud_inference_calls = 0
        local_calls = 0

        async def runner(args, _stdin_text, _cwd, _environment, _timeout_ms):
            nonlocal cloud_inference_calls
            if args[-1] == "--version":
                return CodexProcessResult(0, "codex-cli 0.152.0\n", "")
            if args[1:] == ("login", "status"):
                return CodexProcessResult(0, "Logged in using ChatGPT\n", "")
            cloud_inference_calls += 1
            return CodexProcessResult(1, "", "synthetic cloud failure")

        class CountingLocal(DeterministicLocalProvider):
            provider_id = "cloud-failure-local-qwen-base-test"
            model_version_id = "cloud-failure-qwen3-8b-base-test"
            adapter_version_id = None

            async def generate(self, request):
                nonlocal local_calls
                local_calls += 1
                return await super().generate(request)

        with tempfile.TemporaryDirectory() as value:
            executable = Path(value) / "codex.exe"
            executable.touch()
            cloud = CodexCliProvider(
                executable=executable,
                enabled=True,
                explicit_authorization_ref=CODEX_OWNER_AUTOMATIC_AUTHORIZATION_REF,
                process_runner=runner,
            )
            local = CountingLocal(
                active_adapter_version_id=None,
                active_adapter_artifact_hash=None,
            )
            service = InteractionService(
                owner_id=self.owner_id,
                identity=self.identity,
                repository=self.repository,
                context_builder=ContextBuilder(
                    max_input_tokens=4096,
                    reserved_output_tokens=256,
                ),
                router=PrivacyClassRouter(
                    cloud_provider_id=cloud.provider_id,
                    local_provider_id=local.provider_id,
                    approved_cloud_provider_ids=frozenset({cloud.provider_id}),
                ),
                provider=cloud,
                providers={
                    cloud.provider_id: cloud,
                    local.provider_id: local,
                },
                request_binders={
                    cloud.provider_id: bind_codex_cli_request,
                },
            )
            key = f"dual-cloud-failure-{uuid.uuid4()}"
            with self.assertRaises(ProviderInferenceError):
                await service.interact(InteractionCommand(
                    message="云端失败时不要改走本机。",
                    privacy_class=PrivacyClass.NORMAL,
                    channel="web",
                    idempotency_key=key,
                ))

        self.assertEqual(cloud_inference_calls, 1)
        self.assertEqual(local_calls, 0)
        with self.repository.pool.connection() as connection:
            request = connection.execute(
                """SELECT request_id,status,assistant_event_id,failure_event_id
                   FROM havre.interaction_requests
                   WHERE owner_id=%s AND idempotency_key=%s""",
                (self.owner_id, key),
            ).fetchone()
        self.assertEqual(request["status"], "failed")
        self.assertIsNone(request["assistant_event_id"])
        self.assertIsNotNone(request["failure_event_id"])
        evidence = self.repository.evidence(
            request["request_id"],
            owner_id=self.owner_id,
        )
        self.assertEqual(
            [event["event_type"] for event in evidence["events"]],
            ["USER_MESSAGE", "INTERACTION_FAILED"],
        )
        self.assertEqual(
            evidence["inference"]["provider_id"],
            CODEX_CLI_PROVIDER_ID,
        )
        from companion.product import DailyCompanionStore

        failed_user = next(
            item
            for item in DailyCompanionStore(
                repository=self.repository,
                owner_id=self.owner_id,
            ).timeline(limit=100)["items"]
            if item["request_id"] == request["request_id"]
        )
        self.assertEqual(failed_user["provider_id"], CODEX_CLI_PROVIDER_ID)
        self.assertEqual(failed_user["model_version_id"], "gpt-5.6-sol")
        self.assertEqual(failed_user["execution_environment"], "cloud")

    async def test_local_context_builder_overflow_is_typed_and_never_calls_codex(
        self,
    ) -> None:
        cloud_process_calls = 0
        local_inference_calls = 0

        async def runner(args, _stdin_text, _cwd, _environment, _timeout_ms):
            nonlocal cloud_process_calls
            cloud_process_calls += 1
            raise AssertionError("Codex must not run for LOCAL_ONLY overflow")

        class CountingLocal(DeterministicLocalProvider):
            provider_id = "overflow-local-qwen-base-test"
            model_version_id = "overflow-qwen3-8b-base-test"
            adapter_version_id = None

            async def generate(self, request):
                nonlocal local_inference_calls
                local_inference_calls += 1
                return await super().generate(request)

        with tempfile.TemporaryDirectory() as value:
            executable = Path(value) / "codex.exe"
            executable.touch()
            cloud = CodexCliProvider(
                executable=executable,
                enabled=True,
                explicit_authorization_ref=CODEX_OWNER_AUTOMATIC_AUTHORIZATION_REF,
                process_runner=runner,
            )
            local = CountingLocal(
                active_adapter_version_id=None,
                active_adapter_artifact_hash=None,
            )
            service = InteractionService(
                owner_id=self.owner_id,
                identity=self.identity,
                repository=self.repository,
                context_builder=ContextBuilder(
                    max_input_tokens=4096,
                    reserved_output_tokens=256,
                ),
                context_builders={
                    local.provider_id: ContextBuilder(
                        max_input_tokens=8192,
                        reserved_output_tokens=3072,
                    ),
                },
                router=PrivacyClassRouter(
                    cloud_provider_id=cloud.provider_id,
                    local_provider_id=local.provider_id,
                    approved_cloud_provider_ids=frozenset({cloud.provider_id}),
                ),
                provider=cloud,
                providers={
                    cloud.provider_id: cloud,
                    local.provider_id: local,
                },
                request_binders={
                    cloud.provider_id: bind_codex_cli_request,
                },
            )
            key = f"dual-local-overflow-{uuid.uuid4()}"
            with self.assertRaises(ContextBudgetExceeded):
                await service.interact(InteractionCommand(
                    message="x" * 30_000,
                    privacy_class=PrivacyClass.LOCAL_ONLY,
                    channel="web",
                    idempotency_key=key,
                ))

        self.assertEqual(cloud_process_calls, 0)
        self.assertEqual(local_inference_calls, 0)
        with self.repository.pool.connection() as connection:
            request = connection.execute(
                """SELECT request_id,status,context_pack_id,inference_attempt_id,
                          assistant_event_id,failure_event_id,error_code
                   FROM havre.interaction_requests
                   WHERE owner_id=%s AND idempotency_key=%s""",
                (self.owner_id, key),
            ).fetchone()
        self.assertEqual(request["status"], "failed")
        self.assertEqual(request["error_code"], "context_limit_exceeded")
        self.assertIsNone(request["context_pack_id"])
        self.assertIsNone(request["inference_attempt_id"])
        self.assertIsNone(request["assistant_event_id"])
        self.assertIsNotNone(request["failure_event_id"])
        evidence = self.repository.evidence(
            request["request_id"],
            owner_id=self.owner_id,
        )
        self.assertIsNone(evidence["context_pack"])
        self.assertIsNone(evidence["route_decision"])
        self.assertIsNone(evidence["inference"])
        self.assertEqual(
            [event["event_type"] for event in evidence["events"]],
            ["USER_MESSAGE", "INTERACTION_FAILED"],
        )
        failure_payload = evidence["events"][-1]["payload"]
        self.assertEqual(failure_payload["failure_stage"], "context_build")
        self.assertEqual(failure_payload["failure_code"], "context_limit_exceeded")
        self.assertIsNone(failure_payload["context_pack_id"])
        self.assertIsNone(failure_payload["route_decision_id"])
        self.assertIsNone(failure_payload["inference_request_id"])

    async def test_pre_context_failure_rejects_mismatched_request_lineage_atomically(
        self,
    ) -> None:
        request_id = uuid7()
        session_id = uuid7()
        trace = TraceContext.from_traceparent(None)
        policy = DataPolicy.owner_default(
            PrivacyClass.LOCAL_ONLY,
            memory_eligible=False,
        )
        user_event = EventEnvelope(
            event_type=EventType.USER_MESSAGE,
            owner_id=self.owner_id,
            session_id=session_id,
            request_id=request_id,
            trace_id=trace.trace_id,
            data_policy=policy,
            payload=UserMessagePayload(
                content_parts=(TextContentPart(text="synthetic overflow request"),),
                channel="web",
            ),
        )
        reservation = self.repository.reserve_interaction(
            idempotency_key=f"pre-context-lineage-{uuid.uuid4()}",
            request_fingerprint="sha256:" + "a" * 64,
            user_event=user_event,
            trace=trace,
            channel="web",
            trace_started_at=user_event.recorded_at,
        )
        self.assertTrue(reservation.created)

        mismatches = {
            "trace_id": {"trace_id": "0" * 32},
            "session_id": {"session_id": uuid7()},
            "causation_event_id": {"causation_event_id": uuid7()},
        }
        attempted_event_ids = []
        for field_name, updates in mismatches.items():
            with self.subTest(field_name=field_name):
                failure_event = EventEnvelope(
                    event_type=EventType.INTERACTION_FAILED,
                    owner_id=self.owner_id,
                    session_id=updates.get("session_id", session_id),
                    request_id=request_id,
                    trace_id=updates.get("trace_id", trace.trace_id),
                    causation_event_id=updates.get(
                        "causation_event_id",
                        user_event.event_id,
                    ),
                    data_policy=policy,
                    payload=InteractionFailurePayload(
                        failure_stage="context_build",
                        failure_code="context_limit_exceeded",
                        retryable=False,
                        safe_message="Synthetic context capacity failure.",
                    ),
                )
                attempted_event_ids.append(failure_event.event_id)
                with self.assertRaisesRegex(
                    ValueError,
                    "does not match interaction request lineage",
                ):
                    self.repository.fail_pre_context_interaction(
                        owner_id=self.owner_id,
                        failure_event=failure_event,
                        error_code="context_limit_exceeded",
                        spans=[],
                    )

        with self.repository.pool.connection() as connection:
            request = connection.execute(
                """SELECT status,context_pack_id,inference_attempt_id,
                          assistant_event_id,failure_event_id,error_code
                   FROM havre.interaction_requests
                   WHERE owner_id=%s AND request_id=%s""",
                (self.owner_id, request_id),
            ).fetchone()
            event_count = connection.execute(
                """SELECT count(*) AS count FROM havre.events
                   WHERE owner_id=%s AND request_id=%s""",
                (self.owner_id, request_id),
            ).fetchone()["count"]
            attempted_count = connection.execute(
                """SELECT count(*) AS count FROM havre.events
                   WHERE owner_id=%s AND event_id=ANY(%s)""",
                (self.owner_id, attempted_event_ids),
            ).fetchone()["count"]
        self.assertEqual(request["status"], "processing")
        self.assertIsNone(request["context_pack_id"])
        self.assertIsNone(request["inference_attempt_id"])
        self.assertIsNone(request["assistant_event_id"])
        self.assertIsNone(request["failure_event_id"])
        self.assertIsNone(request["error_code"])
        self.assertEqual(event_count, 1)
        self.assertEqual(attempted_count, 0)

    async def test_cloud_ineligible_normal_context_reroutes_to_local_before_inference(
        self,
    ) -> None:
        cloud_process_calls = 0
        local_requests = []
        mixed_owner_id = uuid.uuid4()
        self.repository.bootstrap_owner_and_identity(
            owner_id=mixed_owner_id,
            identity=self.identity,
        )

        async def runner(args, _stdin_text, _cwd, _environment, _timeout_ms):
            nonlocal cloud_process_calls
            cloud_process_calls += 1
            raise AssertionError("cloud-ineligible Context must not reach Codex")

        class RecordingLocal(DeterministicLocalProvider):
            provider_id = "mixed-policy-local-qwen-base-test"
            model_version_id = "mixed-policy-qwen3-8b-base-test"
            adapter_version_id = None

            async def generate(self, request):
                local_requests.append(request)
                return await super().generate(request)

        restricted_normal_policy = DataPolicy(
            privacy_class=PrivacyClass.NORMAL,
            memory_eligible=False,
            cloud_eligible=False,
            decision_source="derived_conservative",
        )

        def ambient_context_selector(**_kwargs):
            return (
                PersonalContextItem(
                    owner_id=mixed_owner_id,
                    section_id="mixed-policy-context",
                    section_type="calendar_availability",
                    content_text="A local-only source derived this ordinary-looking context.",
                    priority=99,
                    source_refs=("synthetic/mixed-policy-context",),
                    data_policy=restricted_normal_policy,
                    selector_version="stage12a-calendar-context-selector-v1",
                ),
            )

        with tempfile.TemporaryDirectory() as value:
            executable = Path(value) / "codex.exe"
            executable.touch()
            cloud = CodexCliProvider(
                executable=executable,
                enabled=True,
                explicit_authorization_ref=CODEX_OWNER_AUTOMATIC_AUTHORIZATION_REF,
                process_runner=runner,
            )
            local = RecordingLocal(
                active_adapter_version_id=None,
                active_adapter_artifact_hash=None,
            )
            service = InteractionService(
                owner_id=mixed_owner_id,
                identity=self.identity,
                repository=self.repository,
                context_builder=ContextBuilder(
                    max_input_tokens=16_384,
                    reserved_output_tokens=3_072,
                ),
                context_builders={
                    local.provider_id: ContextBuilder(
                        max_input_tokens=8_192,
                        reserved_output_tokens=3_072,
                    ),
                },
                router=PrivacyClassRouter(
                    cloud_provider_id=cloud.provider_id,
                    local_provider_id=local.provider_id,
                    approved_cloud_provider_ids=frozenset({cloud.provider_id}),
                ),
                provider=cloud,
                providers={
                    cloud.provider_id: cloud,
                    local.provider_id: local,
                },
                ambient_context_selector=ambient_context_selector,
                request_binders={
                    cloud.provider_id: bind_codex_cli_request,
                },
            )
            result = await service.interact(InteractionCommand(
                message="今天有什么安排？",
                privacy_class=PrivacyClass.NORMAL,
                channel="web",
                idempotency_key=f"dual-mixed-policy-{uuid.uuid4()}",
            ))

        self.assertEqual(cloud_process_calls, 0)
        self.assertEqual(len(local_requests), 1)
        self.assertEqual(result.provider_id, local.provider_id)
        self.assertFalse(
            local_requests[0].constraints.effective_data_policy.cloud_eligible
        )
        evidence = self.repository.evidence(
            result.request_id,
            owner_id=mixed_owner_id,
        )
        self.assertEqual(
            evidence["route_decision"]["reason"],
            "cloud_ineligible_local_route",
        )
        self.assertEqual(
            evidence["route_decision"]["execution_environment"],
            "local",
        )
        self.assertEqual(
            evidence["context_pack"]["token_budget"],
            {
                "max_input_tokens": 8_192,
                "reserved_output_tokens": 3_072,
                "estimator_id": "utf8-bytes-div4-v1",
                "target_tokenizer_version_id": "provider-neutral-estimator-v1",
            },
        )
        self.assertLessEqual(evidence["context_pack"]["estimated_total_tokens"], 5_120)
        self.assertIn(
            "synthetic/mixed-policy-context",
            {
                source_ref
                for section in evidence["context_pack"]["sections"]
                for source_ref in section["source_refs"]
            },
        )

    async def test_cloud_selected_restricted_context_that_exceeds_local_budget_fails_typed(
        self,
    ) -> None:
        cloud_process_calls = 0
        local_inference_calls = 0
        owner_id = uuid.uuid4()
        self.repository.bootstrap_owner_and_identity(
            owner_id=owner_id,
            identity=self.identity,
        )

        async def runner(args, _stdin_text, _cwd, _environment, _timeout_ms):
            nonlocal cloud_process_calls
            cloud_process_calls += 1
            raise AssertionError("overflow before inference must never reach Codex")

        class CountingLocal(DeterministicLocalProvider):
            provider_id = "rebind-overflow-local-qwen-base-test"
            model_version_id = "rebind-overflow-qwen3-8b-base-test"

            async def generate(self, request):
                nonlocal local_inference_calls
                local_inference_calls += 1
                return await super().generate(request)

        restricted_normal_policy = DataPolicy(
            privacy_class=PrivacyClass.NORMAL,
            memory_eligible=False,
            cloud_eligible=False,
            decision_source="derived_conservative",
        )

        def ambient_context_selector(**_kwargs):
            return (
                PersonalContextItem(
                    owner_id=owner_id,
                    section_id="oversized-restricted-context",
                    section_type="calendar_availability",
                    # UTF-8 CJK text stays within PersonalContextItem's
                    # 20,000-character contract while exceeding the local
                    # 5,120-token input allowance and fitting the cloud pack.
                    content_text="本" * 10_000,
                    priority=99,
                    source_refs=("synthetic/oversized-restricted-context",),
                    data_policy=restricted_normal_policy,
                    selector_version="stage12a-calendar-context-selector-v1",
                ),
            )

        key = f"dual-rebind-overflow-{uuid.uuid4()}"
        with tempfile.TemporaryDirectory() as value:
            executable = Path(value) / "codex.exe"
            executable.touch()
            cloud = CodexCliProvider(
                executable=executable,
                enabled=True,
                explicit_authorization_ref=CODEX_OWNER_AUTOMATIC_AUTHORIZATION_REF,
                process_runner=runner,
            )
            local = CountingLocal(
                active_adapter_version_id=None,
                active_adapter_artifact_hash=None,
            )
            service = InteractionService(
                owner_id=owner_id,
                identity=self.identity,
                repository=self.repository,
                context_builder=ContextBuilder(
                    max_input_tokens=16_384,
                    reserved_output_tokens=3_072,
                ),
                context_builders={
                    local.provider_id: ContextBuilder(
                        max_input_tokens=8_192,
                        reserved_output_tokens=3_072,
                    ),
                },
                router=PrivacyClassRouter(
                    cloud_provider_id=cloud.provider_id,
                    local_provider_id=local.provider_id,
                    approved_cloud_provider_ids=frozenset({cloud.provider_id}),
                ),
                provider=cloud,
                providers={
                    cloud.provider_id: cloud,
                    local.provider_id: local,
                },
                ambient_context_selector=ambient_context_selector,
                request_binders={cloud.provider_id: bind_codex_cli_request},
            )
            with self.assertRaises(ContextBudgetExceeded):
                await service.interact(InteractionCommand(
                    message="请结合本地信息回答。",
                    privacy_class=PrivacyClass.NORMAL,
                    channel="web",
                    idempotency_key=key,
                ))

        self.assertEqual(cloud_process_calls, 0)
        self.assertEqual(local_inference_calls, 0)
        with self.repository.pool.connection() as connection:
            request = connection.execute(
                """SELECT request_id,status,context_pack_id,inference_attempt_id,
                          assistant_event_id,failure_event_id,error_code
                   FROM havre.interaction_requests
                   WHERE owner_id=%s AND idempotency_key=%s""",
                (owner_id, key),
            ).fetchone()
        self.assertEqual(request["status"], "failed")
        self.assertEqual(request["error_code"], "context_limit_exceeded")
        self.assertIsNotNone(request["context_pack_id"])
        self.assertIsNone(request["inference_attempt_id"])
        self.assertIsNone(request["assistant_event_id"])
        self.assertIsNotNone(request["failure_event_id"])
        evidence = self.repository.evidence(request["request_id"], owner_id=owner_id)
        self.assertIsNotNone(evidence["context_pack"])
        self.assertIsNone(evidence["route_decision"])
        self.assertIsNone(evidence["inference"])
        self.assertEqual(
            evidence["context_pack"]["token_budget"],
            {
                "max_input_tokens": 16_384,
                "reserved_output_tokens": 3_072,
                "estimator_id": "utf8-bytes-div4-v1",
                "target_tokenizer_version_id": "provider-neutral-estimator-v1",
            },
        )
        self.assertGreater(evidence["context_pack"]["estimated_total_tokens"], 5_120)
        self.assertIn(
            "synthetic/oversized-restricted-context",
            {
                source_ref
                for section in evidence["context_pack"]["sections"]
                for source_ref in section["source_refs"]
            },
        )
        self.assertEqual(
            [event["event_type"] for event in evidence["events"]],
            ["USER_MESSAGE", "INTERACTION_FAILED"],
        )
        failure_payload = evidence["events"][-1]["payload"]
        self.assertEqual(failure_payload["failure_stage"], "routing")
        self.assertEqual(failure_payload["failure_code"], "context_limit_exceeded")
        self.assertEqual(
            failure_payload["context_pack_id"],
            str(evidence["context_pack"]["context_pack_id"]),
        )
        self.assertIsNone(failure_payload["route_decision_id"])
        self.assertIsNone(failure_payload["inference_request_id"])

    async def test_privacy_router_never_falls_back_from_failed_local_to_cloud(
        self,
    ) -> None:
        cloud_calls = 0

        async def runner(args, _stdin_text, _cwd, _environment, _timeout_ms):
            nonlocal cloud_calls
            if args[-1] == "--version":
                return CodexProcessResult(0, "codex-cli 0.152.0\n", "")
            if args[1:] == ("login", "status"):
                return CodexProcessResult(0, "Logged in using ChatGPT\n", "")
            cloud_calls += 1
            raise AssertionError("cloud must not be called for LOCAL_ONLY failure")

        class FailingUnadaptedLocal(DeterministicLocalProvider):
            provider_id = "failing-local-qwen-base-test"
            model_version_id = "failing-qwen3-8b-base-test"
            adapter_version_id = None

            async def generate(self, request):
                raise RuntimeError("synthetic_local_failure")

        with tempfile.TemporaryDirectory() as value:
            executable = Path(value) / "codex.exe"
            executable.touch()
            cloud = CodexCliProvider(
                executable=executable,
                enabled=True,
                explicit_authorization_ref=CODEX_OWNER_AUTOMATIC_AUTHORIZATION_REF,
                process_runner=runner,
            )
            local = FailingUnadaptedLocal(
                active_adapter_version_id=None,
                active_adapter_artifact_hash=None,
            )
            service = InteractionService(
                owner_id=self.owner_id,
                identity=self.identity,
                repository=self.repository,
                context_builder=ContextBuilder(
                    max_input_tokens=4096,
                    reserved_output_tokens=256,
                ),
                router=PrivacyClassRouter(
                    cloud_provider_id=cloud.provider_id,
                    local_provider_id=local.provider_id,
                    approved_cloud_provider_ids=frozenset({cloud.provider_id}),
                ),
                provider=cloud,
                providers={
                    cloud.provider_id: cloud,
                    local.provider_id: local,
                },
                request_binders={
                    cloud.provider_id: bind_codex_cli_request,
                },
            )
            key = f"dual-local-failure-{uuid.uuid4()}"
            with self.assertRaisesRegex(RuntimeError, "synthetic_local_failure"):
                await service.interact(InteractionCommand(
                    message="本地失败也不允许上传",
                    privacy_class=PrivacyClass.LOCAL_ONLY,
                    channel="web",
                    idempotency_key=key,
                ))

        self.assertEqual(cloud_calls, 0)
        with self.repository.pool.connection() as connection:
            request = connection.execute(
                """SELECT status,assistant_event_id
                   FROM havre.interaction_requests
                   WHERE owner_id=%s AND idempotency_key=%s""",
                (self.owner_id, key),
            ).fetchone()
        self.assertEqual(request["status"], "failed")
        self.assertIsNone(request["assistant_event_id"])


if __name__ == "__main__":
    unittest.main()
