from __future__ import annotations

import os
import asyncio
import time
import unittest
import uuid
from pathlib import Path

import psycopg

from companion.application import (
    IdempotencyConflict,
    InferenceTimeoutError,
    InteractionCommand,
    InteractionService,
)
from companion.context import ContextBuilder
from companion.identity import IdentityLoader
from companion.ids import uuid7
from companion.persistence import PostgresRepository, apply_migrations
from companion.policy import PrivacyClass
from mlsys.serving import DeterministicLocalProvider, Stage1Router


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
            "interaction-orchestrator-v6",
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
        evidence = self.repository.evidence(
            request["request_id"],
            owner_id=self.owner_id,
        )
        self.assertEqual(
            [event["event_type"] for event in evidence["events"]],
            ["USER_MESSAGE", "INTERACTION_FAILED"],
        )

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


if __name__ == "__main__":
    unittest.main()
