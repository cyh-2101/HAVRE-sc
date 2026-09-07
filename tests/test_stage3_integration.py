from __future__ import annotations

import os
import unittest
import uuid
from pathlib import Path
from unittest import mock

import psycopg
import httpx
from psycopg import sql
from psycopg.types.json import Jsonb

from companion.application import InteractionCommand, InteractionService
from companion.hashing import content_hash
from companion.context import ContextBuilder
from companion.events import EventEnvelope, EventType, UserMessagePayload
from companion.identity import IdentityLoader
from companion.persistence import PostgresRepository, apply_migrations
from companion.policy import PrivacyClass
from evals.inference_benchmark import (
    NullResourceCollector,
    capture_environment_manifest,
    load_workload_manifest,
    run_inference_benchmark,
)
from evals.inference_runner import (
    build_stage1_compatibility_baseline,
    controlled_comparison_workload,
)
from mlsys.contracts.inference_benchmark import (
    InferenceCompatibilityReport,
    InferenceSystemBenchmarkReport,
)
from mlsys.contracts import InferenceFailure
from mlsys.serving import (
    DeterministicLocalProvider,
    OpenAICompatibleProvider,
    ProviderInferenceError,
    ProviderVersionError,
    RuntimeAttestation,
    Stage1Router,
)


DATABASE_URL = os.getenv("HAVRE_TEST_DATABASE_URL")
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def synthetic_runtime_attestation() -> RuntimeAttestation:
    now = "2026-08-14T00:00:00Z"
    payload = {
        "schema_version": 1,
        "attestation_id": "integration-runtime:4242:1",
        "runtime_state_hash": "sha256:" + "1" * 64,
        "engine_manifest_hash": "sha256:" + "2" * 64,
        "model_manifest_hash": "sha256:" + "3" * 64,
        "server_executable_hash": "sha256:" + "4" * 64,
        "server_executable_path_hash": "sha256:" + "5" * 64,
        "process_executable_hash": "sha256:" + "4" * 64,
        "model_artifact_hash": "sha256:" + "6" * 64,
        "model_path_hash": "sha256:" + "7" * 64,
        "model_size_bytes": 1,
        "server_pid": 4242,
        "process_started_at": now,
        "launch_arguments_hash": "sha256:" + "8" * 64,
        "base_url": "http://127.0.0.1:19090",
        "serving_engine": "llama.cpp",
        "serving_engine_version": "integration-test-build",
        "serving_config_version": "integration-serving-v1",
        "model_version_id": "integration-model-v1",
        "tokenizer_version_id": "integration-tokenizer-v1",
        "loaded_model_alias": "transport-model",
        "loopback_only": True,
        "request_logging_disabled": True,
        "web_ui_disabled": True,
        "attested_at": now,
    }
    return RuntimeAttestation.model_validate(
        {**payload, "attestation_hash": content_hash(payload)}
    )


@unittest.skipUnless(
    DATABASE_URL, "HAVRE_TEST_DATABASE_URL is required for integration tests"
)
class Stage3PostgresIntegrationTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        assert DATABASE_URL is not None
        apply_migrations(DATABASE_URL, PROJECT_ROOT / "db" / "migrations")
        cls.owner_id = uuid.UUID("00000000-0000-7000-8000-000000000032")
        cls.identity = IdentityLoader(PROJECT_ROOT / "identity").load()
        cls.repository = PostgresRepository(DATABASE_URL)
        cls.repository.open()
        cls.repository.bootstrap_owner_and_identity(
            owner_id=cls.owner_id,
            identity=cls.identity,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.repository.close()

    def _service(self, provider=None) -> InteractionService:
        return InteractionService(
            owner_id=self.owner_id,
            identity=self.identity,
            repository=self.repository,
            context_builder=ContextBuilder(
                max_input_tokens=4096,
                reserved_output_tokens=256,
            ),
            router=Stage1Router(),
            provider=provider or DeterministicLocalProvider(),
        )

    async def asyncSetUp(self) -> None:
        liveness = mock.patch(
            "mlsys.serving.openai_compatible.verify_attested_process_liveness"
        )
        liveness.start()
        self.addCleanup(liveness.stop)

    async def _interact(self, *, provider=None, message="Stage 3 evidence request"):
        return await self._service(provider).interact(
            InteractionCommand(
                message=message,
                privacy_class=PrivacyClass.LOCAL_ONLY,
                channel="api",
                idempotency_key=f"stage3-integration-{uuid.uuid4()}",
            )
        )

    async def test_completed_attempt_stores_exact_stage3_version_lineage(self) -> None:
        result = await self._interact()
        evidence = self.repository.evidence(result.request_id, owner_id=self.owner_id)

        self.assertIsNotNone(evidence)
        assert evidence is not None
        request = evidence["request"]
        attempt = evidence["inference"]
        self.assertEqual(request["status"], "completed")
        self.assertEqual(request["inference_attempt_id"], attempt["inference_attempt_id"])
        self.assertEqual(attempt["status"], "completed")
        self.assertEqual(
            attempt["provider_adapter_version_id"],
            DeterministicLocalProvider.provider_adapter_version_id,
        )
        self.assertEqual(attempt["serving_engine"], "deterministic-python")
        self.assertEqual(
            attempt["serving_engine_version"], "deterministic-python-v1"
        )
        self.assertIsNone(attempt["failure"])

    async def test_evidence_orders_equal_timestamps_by_event_id(self) -> None:
        result = await self._interact(
            message="Verify deterministic evidence ordering for tied timestamps."
        )
        with self.repository.pool.connection() as connection:
            original = connection.execute(
                "SELECT * FROM havre.events WHERE owner_id = %s AND event_id = %s",
                (self.owner_id, result.user_event_id),
            ).fetchone()
        self.assertIsNotNone(original)
        assert original is not None
        later_event_id = uuid.UUID(
            int=((1 << 128) - 1) - (uuid.uuid4().int & ((1 << 64) - 1))
        )
        self.assertGreater(later_event_id, original["event_id"])
        tied_event = EventEnvelope(
            event_id=later_event_id,
            event_type=EventType.USER_MESSAGE,
            owner_id=self.owner_id,
            session_id=original["session_id"],
            request_id=result.request_id,
            trace_id=original["trace_id"].strip(),
            data_policy=self.repository._policy_from_row(original),
            payload=UserMessagePayload(
                content_parts=(
                    {"type": "text", "text": "Tie-breaker evidence fixture."},
                ),
                channel="api",
            ),
            recorded_at=original["recorded_at"],
        )
        with self.repository.pool.connection() as connection, connection.transaction():
            PostgresRepository._insert_event(connection, tied_event)

        evidence = self.repository.evidence(result.request_id, owner_id=self.owner_id)
        assert evidence is not None
        tied_ids = [
            event["event_id"]
            for event in evidence["events"]
            if event["recorded_at"] == original["recorded_at"]
            and event["event_type"] == "USER_MESSAGE"
        ]
        self.assertEqual(len(tied_ids), 2)
        self.assertEqual(tied_ids, sorted(tied_ids))

    async def test_new_self_hosted_attempt_cannot_claim_legacy_contract_v0(self) -> None:
        result = await self._interact(message="Create an attempt row to clone safely.")
        with self.repository.pool.connection() as connection:
            source = connection.execute(
                "SELECT * FROM havre.inference_attempts WHERE request_id = %s",
                (result.request_id,),
            ).fetchone()
            self.assertIsNotNone(source)
            assert source is not None
            attempted = dict(source)
            attempted.update({
                "inference_attempt_id": uuid.uuid4(),
                "inference_response_id": uuid.uuid4(),
                "inference_request_id": uuid.uuid4(),
                "attempt_number": int(source["attempt_number"]) + 1,
                "provider_class": "self_hosted",
                "runtime_attestation_contract_version": 0,
                "runtime_attestation_id": None,
                "runtime_attestation_hash": None,
            })
            for json_column in ("usage", "timing_ms", "failure"):
                if attempted[json_column] is not None:
                    attempted[json_column] = Jsonb(attempted[json_column])
            columns = tuple(attempted)
            statement = sql.SQL("INSERT INTO havre.inference_attempts ({}) VALUES ({})").format(
                sql.SQL(", ").join(map(sql.Identifier, columns)),
                sql.SQL(", ").join(sql.Placeholder() for _ in columns),
            )
            with self.assertRaisesRegex(
                psycopg.errors.CheckViolation,
                "new inference attempts require runtime attestation contract version 1",
            ):
                with connection.transaction():
                    connection.execute(statement, tuple(attempted[column] for column in columns))

    async def test_database_guards_route_provider_model_and_attestation_lineage(
        self,
    ) -> None:
        result = await self._interact(
            message="Create exact route and attempt rows for 0052 attack probes."
        )
        with self.repository.pool.connection() as connection:
            source_route = dict(connection.execute(
                "SELECT * FROM havre.route_decisions WHERE request_id=%s",
                (result.request_id,),
            ).fetchone())
            source_attempt = dict(connection.execute(
                "SELECT * FROM havre.inference_attempts WHERE request_id=%s",
                (result.request_id,),
            ).fetchone())

        forged_route = dict(source_route)
        forged_route.update({
            "route_decision_id": uuid.uuid4(),
            "effective_policy_revision_id": uuid.uuid4(),
        })
        for column in ("eligible_candidates", "excluded_candidates"):
            forged_route[column] = Jsonb(forged_route[column])
        route_columns = tuple(forged_route)
        route_statement = sql.SQL(
            "INSERT INTO havre.route_decisions ({}) VALUES ({})"
        ).format(
            sql.SQL(", ").join(map(sql.Identifier, route_columns)),
            sql.SQL(", ").join(sql.Placeholder() for _ in route_columns),
        )
        with self.assertRaises(
            psycopg.errors.ObjectNotInPrerequisiteState
        ) as route_error:
            with self.repository.pool.connection() as connection:
                with connection.transaction():
                    connection.execute(
                        route_statement,
                        tuple(forged_route[column] for column in route_columns),
                    )
        self.assertEqual(route_error.exception.sqlstate, "55000")

        attestation = synthetic_runtime_attestation()
        self.repository.register_runtime_attestation(attestation)
        variants = {
            "provider": {"provider_id": "forged-provider-v1"},
            "model": {"model_version_id": "forged-model-v1"},
            "attestation": {
                "provider_class": "self_hosted",
                "runtime_attestation_contract_version": 1,
                "runtime_attestation_id": attestation.attestation_id,
                "runtime_attestation_hash": attestation.attestation_hash,
            },
        }
        for name, updates in variants.items():
            with self.subTest(lineage=name):
                forged_attempt = dict(source_attempt)
                forged_attempt.update({
                    "inference_attempt_id": uuid.uuid4(),
                    "inference_response_id": uuid.uuid4(),
                    "inference_request_id": uuid.uuid4(),
                    "attempt_number": int(source_attempt["attempt_number"]) + 1,
                    **updates,
                })
                for column in ("usage", "timing_ms", "failure"):
                    if forged_attempt[column] is not None:
                        forged_attempt[column] = Jsonb(forged_attempt[column])
                attempt_columns = tuple(forged_attempt)
                attempt_statement = sql.SQL(
                    "INSERT INTO havre.inference_attempts ({}) VALUES ({})"
                ).format(
                    sql.SQL(", ").join(map(sql.Identifier, attempt_columns)),
                    sql.SQL(", ").join(
                        sql.Placeholder() for _ in attempt_columns
                    ),
                )
                with self.assertRaises(
                    psycopg.errors.ObjectNotInPrerequisiteState
                ) as attempt_error:
                    with self.repository.pool.connection() as connection:
                        with connection.transaction():
                            connection.execute(
                                attempt_statement,
                                tuple(
                                    forged_attempt[column]
                                    for column in attempt_columns
                                ),
                            )
                self.assertEqual(attempt_error.exception.sqlstate, "55000")

    async def test_self_hosted_attempt_references_registered_runtime_attestation(self) -> None:
        attestation = synthetic_runtime_attestation()
        self.repository.register_runtime_attestation(attestation)
        self.repository.register_runtime_attestation(attestation)
        chunks = (
            'data: {"id":"attested-provider-request","model":"transport-model",'
            '"system_fingerprint":null,"choices":[{"delta":{"content":"Verified."},'
            '"finish_reason":null}]}\n\n'
            'data: {"id":"attested-provider-request","model":"transport-model",'
            '"system_fingerprint":null,"choices":[{"delta":{},"finish_reason":"stop"}],'
            '"usage":{"prompt_tokens":2,"completion_tokens":1,"total_tokens":3}}\n\n'
            'data: [DONE]\n\n'
        )

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/props":
                return httpx.Response(
                    200,
                    json={
                        "serving_engine": "llama.cpp",
                        "serving_engine_version": "integration-test-build",
                    },
                )
            if request.url.path == "/v1/models":
                return httpx.Response(200, json={"data": [{"id": "transport-model"}]})
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=chunks,
            )

        provider = OpenAICompatibleProvider(
            base_url="http://127.0.0.1:19090",
            transport_model_id="transport-model",
            model_version_id="integration-model-v1",
            tokenizer_version_id="integration-tokenizer-v1",
            serving_engine="llama.cpp",
            serving_engine_version="integration-test-build",
            serving_config_version="integration-serving-v1",
            model_artifact_hash="sha256:" + "6" * 64,
            version_path="/props",
            runtime_attestation=attestation,
            transport=httpx.MockTransport(handler),
        )
        self.addAsyncCleanup(provider.aclose)
        result = await self._interact(provider=provider)
        evidence = self.repository.evidence(result.request_id, owner_id=self.owner_id)
        assert evidence is not None
        self.assertEqual(result.runtime_attestation_id, attestation.attestation_id)
        self.assertEqual(result.runtime_attestation_hash, attestation.attestation_hash)
        self.assertEqual(
            evidence["inference"]["runtime_attestation_id"],
            attestation.attestation_id,
        )
        with self.repository.pool.connection() as connection:
            stored = connection.execute(
                """
                SELECT attestation_hash FROM havre.runtime_attestations
                WHERE runtime_attestation_id = %s
                """,
                (attestation.attestation_id,),
            ).fetchone()
        self.assertEqual(stored["attestation_hash"], attestation.attestation_hash)

    async def test_provider_failure_is_a_durable_failed_attempt(self) -> None:
        class FailingProvider(DeterministicLocalProvider):
            async def generate(self, request):
                raise RuntimeError("synthetic stage3 generation failure")

        key = f"stage3-failed-attempt-{uuid.uuid4()}"
        with self.assertRaisesRegex(RuntimeError, "synthetic stage3"):
            await self._service(FailingProvider()).interact(
                InteractionCommand(
                    message="Persist this terminal provider failure.",
                    privacy_class=PrivacyClass.LOCAL_ONLY,
                    channel="api",
                    idempotency_key=key,
                )
            )

        with self.repository.pool.connection() as connection:
            request = connection.execute(
                """
                SELECT request_id FROM havre.interaction_requests
                WHERE owner_id = %s AND idempotency_key = %s
                """,
                (self.owner_id, key),
            ).fetchone()
        evidence = self.repository.evidence(request["request_id"], owner_id=self.owner_id)
        assert evidence is not None
        attempt = evidence["inference"]
        self.assertEqual(evidence["request"]["status"], "failed")
        self.assertEqual(evidence["request"]["inference_attempt_id"], attempt["inference_attempt_id"])
        self.assertEqual(attempt["status"], "failed")
        self.assertEqual(attempt["failure"]["code"], "internal_error")
        self.assertIsNone(attempt["inference_response_id"])
        self.assertEqual(
            [event["event_type"] for event in evidence["events"]],
            ["USER_MESSAGE", "INTERACTION_FAILED"],
        )

    async def test_response_cannot_claim_adapter_absent_from_provider_version(self) -> None:
        class ForgedAdapterProvider(DeterministicLocalProvider):
            async def generate(self, request):
                response = await super().generate(request)
                return response.model_copy(update={
                    "versions": response.versions.model_copy(
                        update={"adapter_version_id": "forged-adapter-v1"}
                    )
                })

        provider = ForgedAdapterProvider(
            active_adapter_version_id=None,
            active_adapter_artifact_hash=None,
        )
        key = f"stage3-forged-adapter-{uuid.uuid4()}"
        with self.assertRaisesRegex(ValueError, "adapter_version_id"):
            await self._service(provider).interact(InteractionCommand(
                message="Reject response metadata not attested by the provider version.",
                privacy_class=PrivacyClass.LOCAL_ONLY,
                channel="api",
                idempotency_key=key,
            ))

        with self.repository.pool.connection() as connection:
            request = connection.execute(
                """SELECT request_id,status,assistant_event_id,error_code
                   FROM havre.interaction_requests
                   WHERE owner_id=%s AND idempotency_key=%s""",
                (self.owner_id, key),
            ).fetchone()
        self.assertEqual(request["status"], "failed")
        self.assertIsNone(request["assistant_event_id"])
        evidence = self.repository.evidence(request["request_id"], owner_id=self.owner_id)
        self.assertEqual(evidence["inference"]["status"], "failed")
        self.assertIsNone(evidence["inference"]["adapter_version_id"])
        self.assertEqual(
            [event["event_type"] for event in evidence["events"]],
            ["USER_MESSAGE", "INTERACTION_FAILED"],
        )

    async def test_adapter_http_failure_preserves_typed_code_through_application(self) -> None:
        attestation = synthetic_runtime_attestation()
        self.repository.register_runtime_attestation(attestation)

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/props":
                return httpx.Response(
                    200,
                    json={
                        "serving_engine": "llama.cpp",
                        "serving_engine_version": "integration-test-build",
                    },
                )
            if request.url.path == "/v1/models":
                return httpx.Response(200, json={"data": [{"id": "transport-model"}]})
            return httpx.Response(429, text="private provider body")

        provider = OpenAICompatibleProvider(
            base_url="http://127.0.0.1:19090",
            transport_model_id="transport-model",
            model_version_id="integration-model-v1",
            tokenizer_version_id="integration-tokenizer-v1",
            serving_engine="llama.cpp",
            serving_engine_version="integration-test-build",
            serving_config_version="integration-serving-v1",
            model_artifact_hash="sha256:" + "6" * 64,
            runtime_attestation=attestation,
            version_path="/props",
            transport=httpx.MockTransport(handler),
        )
        self.addAsyncCleanup(provider.aclose)
        key = f"stage3-adapter-failure-{uuid.uuid4()}"
        with self.assertRaises(ProviderInferenceError) as raised:
            await self._service(provider).interact(
                InteractionCommand(
                    message="Retain the provider's safe typed rate-limit code.",
                    privacy_class=PrivacyClass.LOCAL_ONLY,
                    channel="api",
                    idempotency_key=key,
                )
            )
        self.assertEqual(raised.exception.code, "provider_rate_limited")
        with self.repository.pool.connection() as connection:
            request = connection.execute(
                """
                SELECT request_id FROM havre.interaction_requests
                WHERE owner_id = %s AND idempotency_key = %s
                """,
                (self.owner_id, key),
            ).fetchone()
        evidence = self.repository.evidence(request["request_id"], owner_id=self.owner_id)
        assert evidence is not None
        self.assertEqual(evidence["request"]["error_code"], "provider_rate_limited")
        self.assertEqual(evidence["inference"]["failure"]["code"], "provider_rate_limited")
        self.assertNotIn(
            "private provider body",
            evidence["events"][-1]["payload"]["safe_message"],
        )

    async def test_direct_misbound_provider_failure_is_normalized_and_terminal(self) -> None:
        class MisboundFailureProvider(DeterministicLocalProvider):
            async def stream(self, request):
                raise ProviderInferenceError(
                    InferenceFailure(
                        inference_request_id=uuid.uuid4(),
                        request_id=request.request_id,
                        trace_id=request.trace_id,
                        provider_id="wrong-provider",
                        provider_class="cloud",
                        code="model_unavailable",
                        retryable=True,
                        safe_message="misbound synthetic failure",
                    )
                )
                yield  # pragma: no cover - keeps this an async generator

        key = f"stage3-misbound-failure-{uuid.uuid4()}"
        with self.assertRaises(ProviderInferenceError) as raised:
            await self._service(MisboundFailureProvider()).interact(
                InteractionCommand(
                    message="Reject a provider failure bound to another route.",
                    privacy_class=PrivacyClass.LOCAL_ONLY,
                    channel="api",
                    idempotency_key=key,
                )
            )
        self.assertEqual(raised.exception.code, "provider_protocol_error")
        with self.repository.pool.connection() as connection:
            request = connection.execute(
                """
                SELECT request_id, status, error_code
                FROM havre.interaction_requests
                WHERE owner_id = %s AND idempotency_key = %s
                """,
                (self.owner_id, key),
            ).fetchone()
        self.assertEqual(request["status"], "failed")
        self.assertEqual(request["error_code"], "provider_protocol_error")
        evidence = self.repository.evidence(request["request_id"], owner_id=self.owner_id)
        assert evidence is not None
        failure = evidence["inference"]["failure"]
        self.assertEqual(failure["code"], "provider_protocol_error")
        self.assertEqual(failure["provider_id"], DeterministicLocalProvider.provider_id)
        self.assertEqual(failure["request_id"], str(request["request_id"]))
        self.assertEqual(failure["trace_id"], evidence["request"]["trace_id"])

    async def test_database_rejects_failure_json_with_duplicated_wrong_lineage(self) -> None:
        class FailingProvider(DeterministicLocalProvider):
            async def generate(self, request):
                raise RuntimeError("create a valid failed-attempt fixture")

        key = f"stage3-failure-json-lineage-{uuid.uuid4()}"
        with self.assertRaises(RuntimeError):
            await self._service(FailingProvider()).interact(
                InteractionCommand(
                    message="Persist a valid failure before mutation is attempted.",
                    privacy_class=PrivacyClass.LOCAL_ONLY,
                    channel="api",
                    idempotency_key=key,
                )
            )
        with self.repository.pool.connection() as connection:
            attempt = connection.execute(
                """
                SELECT attempt.inference_attempt_id, attempt.failure
                FROM havre.inference_attempts AS attempt
                JOIN havre.interaction_requests AS request
                  ON request.owner_id = attempt.owner_id
                 AND request.request_id = attempt.request_id
                WHERE request.owner_id = %s AND request.idempotency_key = %s
                """,
                (self.owner_id, key),
            ).fetchone()
        tampered = dict(attempt["failure"])
        tampered["provider_id"] = "wrong-provider"
        with self.assertRaises(psycopg.errors.CheckViolation):
            with self.repository.pool.connection() as connection:
                connection.execute("SET LOCAL havre.privileged_erasure = 'on'")
                connection.execute(
                    """
                    UPDATE havre.inference_attempts SET failure = %s
                    WHERE inference_attempt_id = %s
                    """,
                    (Jsonb(tampered), attempt["inference_attempt_id"]),
                )
        missing_key = dict(attempt["failure"])
        del missing_key["provider_id"]
        with self.assertRaises(psycopg.errors.CheckViolation):
            with self.repository.pool.connection() as connection:
                connection.execute("SET LOCAL havre.privileged_erasure = 'on'")
                connection.execute(
                    """
                    UPDATE havre.inference_attempts SET failure = %s
                    WHERE inference_attempt_id = %s
                    """,
                    (Jsonb(missing_key), attempt["inference_attempt_id"]),
                )
        null_typed = dict(attempt["failure"])
        null_typed.update({"code": None, "retryable": None, "safe_message": None})
        with self.assertRaises(psycopg.errors.CheckViolation):
            with self.repository.pool.connection() as connection:
                connection.execute("SET LOCAL havre.privileged_erasure = 'on'")
                connection.execute(
                    """
                    UPDATE havre.inference_attempts SET failure = %s
                    WHERE inference_attempt_id = %s
                    """,
                    (Jsonb(null_typed), attempt["inference_attempt_id"]),
                )

    async def test_pre_inference_version_failure_does_not_invent_an_attempt(self) -> None:
        class VersionUnavailableProvider(DeterministicLocalProvider):
            async def version(self):
                raise ProviderVersionError(
                    code="model_unavailable",
                    retryable=True,
                    safe_message="The provider version endpoint is temporarily unavailable.",
                )

        key = f"stage3-version-failure-{uuid.uuid4()}"
        with self.assertRaises(ProviderInferenceError) as raised:
            await self._service(VersionUnavailableProvider()).interact(
                InteractionCommand(
                    message="Fail after routing but before inference starts.",
                    privacy_class=PrivacyClass.LOCAL_ONLY,
                    channel="api",
                    idempotency_key=key,
                )
            )
        self.assertEqual(raised.exception.code, "model_unavailable")
        self.assertTrue(raised.exception.retryable)

        with self.repository.pool.connection() as connection:
            request = connection.execute(
                """
                SELECT request_id FROM havre.interaction_requests
                WHERE owner_id = %s AND idempotency_key = %s
                """,
                (self.owner_id, key),
            ).fetchone()
        evidence = self.repository.evidence(request["request_id"], owner_id=self.owner_id)
        assert evidence is not None
        self.assertEqual(evidence["request"]["status"], "failed")
        self.assertIsNotNone(evidence["context_pack"])
        self.assertIsNotNone(evidence["route_decision"])
        self.assertIsNone(evidence["request"]["inference_attempt_id"])
        self.assertIsNone(evidence["inference"])
        self.assertEqual(evidence["request"]["error_code"], "model_unavailable")
        self.assertEqual(evidence["events"][-1]["payload"]["failure_stage"], "version_check")
        self.assertEqual(evidence["events"][-1]["payload"]["failure_code"], "model_unavailable")
        self.assertTrue(evidence["events"][-1]["payload"]["retryable"])
        self.assertEqual(
            [event["event_type"] for event in evidence["events"]],
            ["USER_MESSAGE", "INTERACTION_FAILED"],
        )

    async def test_route_and_exact_provider_version_cannot_select_different_models(self) -> None:
        class RouteVersionMismatchProvider(DeterministicLocalProvider):
            async def capabilities(self):
                capabilities = await super().capabilities()
                return capabilities.model_copy(
                    update={
                        "available_model_version_ids": (
                            self.model_version_id,
                            "different-model-v2",
                        )
                    }
                )

            async def version(self):
                version = await super().version()
                return version.model_copy(update={"model_version_id": "different-model-v2"})

        key = f"stage3-route-version-mismatch-{uuid.uuid4()}"
        with self.assertRaises(ProviderInferenceError) as raised:
            await self._service(RouteVersionMismatchProvider()).interact(
                InteractionCommand(
                    message="Fail closed when live model and route disagree.",
                    privacy_class=PrivacyClass.LOCAL_ONLY,
                    channel="api",
                    idempotency_key=key,
                )
            )
        self.assertEqual(raised.exception.code, "provider_protocol_error")
        self.assertFalse(raised.exception.retryable)
        with self.repository.pool.connection() as connection:
            request = connection.execute(
                """
                SELECT request_id, status FROM havre.interaction_requests
                WHERE owner_id = %s AND idempotency_key = %s
                """,
                (self.owner_id, key),
            ).fetchone()
        self.assertEqual(request["status"], "failed")
        evidence = self.repository.evidence(request["request_id"], owner_id=self.owner_id)
        assert evidence is not None
        self.assertEqual(
            evidence["route_decision"]["selected_model_version_id"],
            DeterministicLocalProvider.model_version_id,
        )
        self.assertIsNone(evidence["inference"])
        self.assertEqual(evidence["events"][-1]["payload"]["failure_stage"], "version_check")
        self.assertEqual(
            evidence["events"][-1]["payload"]["failure_code"],
            "provider_protocol_error",
        )
        self.assertFalse(evidence["events"][-1]["payload"]["retryable"])

    async def test_repository_rejects_misbound_pre_inference_failure_payload(self) -> None:
        class VersionUnavailableProvider(DeterministicLocalProvider):
            async def version(self):
                raise RuntimeError("capture a routed pre-inference fixture")

        repository_method = self.repository.fail_pre_inference_interaction

        def tamper(**kwargs):
            event = kwargs["failure_event"]
            payload = event.payload.model_copy(
                update={"inference_request_id": uuid.uuid4()}
            )
            kwargs["failure_event"] = event.model_copy(update={"payload": payload})
            return repository_method(**kwargs)

        key = f"stage3-pre-inference-misbound-{uuid.uuid4()}"
        with mock.patch.object(
            self.repository, "fail_pre_inference_interaction", side_effect=tamper
        ), self.assertRaisesRegex(ValueError, "failure event lineage"):
            await self._service(VersionUnavailableProvider()).interact(
                InteractionCommand(
                    message="Reject a pre-inference event with a foreign request ID.",
                    privacy_class=PrivacyClass.LOCAL_ONLY,
                    channel="api",
                    idempotency_key=key,
                )
            )

    async def test_repository_rejects_forged_completion_lineage_without_assistant(
        self,
    ) -> None:
        complete_interaction = self.repository.complete_interaction

        def tamper(**kwargs):
            kwargs["inference_request"] = kwargs["inference_request"].model_copy(
                update={"context_pack_id": uuid.uuid4()}
            )
            return complete_interaction(**kwargs)

        key = f"stage3-forged-completion-{uuid.uuid4()}"
        with mock.patch.object(
            self.repository,
            "complete_interaction",
            side_effect=tamper,
        ), self.assertRaisesRegex(ValueError, "inference request lineage"):
            await self._service().interact(InteractionCommand(
                message="Reject a completion bound to a foreign ContextPack.",
                privacy_class=PrivacyClass.LOCAL_ONLY,
                channel="api",
                idempotency_key=key,
            ))

        with self.repository.pool.connection() as connection:
            request = connection.execute(
                """SELECT request_id,status,assistant_event_id
                   FROM havre.interaction_requests
                   WHERE owner_id=%s AND idempotency_key=%s""",
                (self.owner_id, key),
            ).fetchone()
        self.assertEqual(request["status"], "failed")
        self.assertIsNone(request["assistant_event_id"])
        evidence = self.repository.evidence(request["request_id"], owner_id=self.owner_id)
        self.assertEqual(evidence["inference"]["status"], "failed")
        self.assertEqual(
            [event["event_type"] for event in evidence["events"]],
            ["USER_MESSAGE", "INTERACTION_FAILED"],
        )

    async def test_repository_rejects_forged_inference_failure_atomically(self) -> None:
        class FailingProvider(DeterministicLocalProvider):
            async def generate(self, request):
                raise RuntimeError("create inference failure fixture")

        fail_interaction = self.repository.fail_inference_interaction

        def tamper(**kwargs):
            kwargs["failure_event"] = kwargs["failure_event"].model_copy(
                update={"session_id": uuid.uuid4()}
            )
            return fail_interaction(**kwargs)

        key = f"stage3-forged-inference-failure-{uuid.uuid4()}"
        with mock.patch.object(
            self.repository,
            "fail_inference_interaction",
            side_effect=tamper,
        ), self.assertRaisesRegex(ValueError, "durable interaction request lineage"):
            await self._service(FailingProvider()).interact(InteractionCommand(
                message="Reject a failure Event with a foreign session.",
                privacy_class=PrivacyClass.LOCAL_ONLY,
                channel="api",
                idempotency_key=key,
            ))

        with self.repository.pool.connection() as connection:
            request = connection.execute(
                """SELECT request_id,status,context_pack_id,inference_attempt_id,
                          assistant_event_id,failure_event_id
                   FROM havre.interaction_requests
                   WHERE owner_id=%s AND idempotency_key=%s""",
                (self.owner_id, key),
            ).fetchone()
            event_types = connection.execute(
                """SELECT event_type FROM havre.events
                   WHERE owner_id=%s AND request_id=%s ORDER BY recorded_at,event_id""",
                (self.owner_id, request["request_id"]),
            ).fetchall()
        self.assertEqual(request["status"], "processing")
        self.assertIsNone(request["context_pack_id"])
        self.assertIsNone(request["inference_attempt_id"])
        self.assertIsNone(request["assistant_event_id"])
        self.assertIsNone(request["failure_event_id"])
        self.assertEqual([row["event_type"] for row in event_types], ["USER_MESSAGE"])

    async def test_capability_failure_retains_context_and_typed_failure_event(self) -> None:
        class CapabilitiesUnavailableProvider(DeterministicLocalProvider):
            async def capabilities(self):
                raise RuntimeError("synthetic capability endpoint failure")

        key = f"stage3-capability-failure-{uuid.uuid4()}"
        with self.assertRaisesRegex(RuntimeError, "capability endpoint"):
            await self._service(CapabilitiesUnavailableProvider()).interact(
                InteractionCommand(
                    message="Fail after context but before routing.",
                    privacy_class=PrivacyClass.LOCAL_ONLY,
                    channel="api",
                    idempotency_key=key,
                )
            )
        with self.repository.pool.connection() as connection:
            request = connection.execute(
                """
                SELECT request_id FROM havre.interaction_requests
                WHERE owner_id = %s AND idempotency_key = %s
                """,
                (self.owner_id, key),
            ).fetchone()
        evidence = self.repository.evidence(request["request_id"], owner_id=self.owner_id)
        assert evidence is not None
        self.assertEqual(evidence["request"]["error_code"], "model_unavailable")
        self.assertIsNotNone(evidence["context_pack"])
        self.assertIsNone(evidence["route_decision"])
        self.assertIsNone(evidence["inference"])
        self.assertEqual(evidence["events"][-1]["event_type"], "INTERACTION_FAILED")
        self.assertEqual(
            evidence["events"][-1]["payload"]["failure_stage"],
            "capability_check",
        )

    async def test_unsupported_streaming_is_durable_capability_failure(self) -> None:
        class NonStreamingProvider(DeterministicLocalProvider):
            async def capabilities(self):
                capabilities = await super().capabilities()
                return capabilities.model_copy(update={"supports_streaming": False})

        key = f"stage3-unsupported-streaming-{uuid.uuid4()}"
        with self.assertRaisesRegex(RuntimeError, "required streaming"):
            await self._service(NonStreamingProvider()).interact(
                InteractionCommand(
                    message="Require the Stage 3 streaming provider contract.",
                    privacy_class=PrivacyClass.LOCAL_ONLY,
                    channel="api",
                    idempotency_key=key,
                )
            )
        with self.repository.pool.connection() as connection:
            request = connection.execute(
                """
                SELECT request_id FROM havre.interaction_requests
                WHERE owner_id = %s AND idempotency_key = %s
                """,
                (self.owner_id, key),
            ).fetchone()
        evidence = self.repository.evidence(request["request_id"], owner_id=self.owner_id)
        assert evidence is not None
        self.assertEqual(evidence["request"]["error_code"], "unsupported_capability")
        self.assertIsNotNone(evidence["context_pack"])
        self.assertIsNone(evidence["route_decision"])
        self.assertEqual(
            evidence["events"][-1]["payload"]["failure_code"],
            "unsupported_capability",
        )

    async def test_attempt_pointer_cannot_cross_request_for_same_owner(self) -> None:
        first = await self._interact(message="First request for pointer isolation.")
        second = await self._interact(message="Second request for pointer isolation.")
        first_evidence = self.repository.evidence(first.request_id, owner_id=self.owner_id)
        assert first_evidence is not None

        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
            with self.repository.pool.connection() as connection:
                connection.execute(
                    """
                    UPDATE havre.interaction_requests
                    SET inference_attempt_id = %s
                    WHERE owner_id = %s AND request_id = %s
                    """,
                    (
                        first_evidence["inference"]["inference_attempt_id"],
                        self.owner_id,
                        second.request_id,
                    ),
                )
        second_evidence = self.repository.evidence(second.request_id, owner_id=self.owner_id)
        assert second_evidence is not None
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
            with self.repository.pool.connection() as connection:
                connection.execute(
                    """
                    UPDATE havre.interaction_requests
                    SET inference_response_id = %s
                    WHERE owner_id = %s AND request_id = %s
                    """,
                    (
                        first_evidence["inference"]["inference_response_id"],
                        self.owner_id,
                        second.request_id,
                    ),
                )
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            with self.repository.pool.connection() as connection:
                connection.execute("SET LOCAL havre.privileged_erasure = 'on'")
                connection.execute(
                    """
                    UPDATE havre.inference_attempts
                    SET context_pack_id = %s
                    WHERE owner_id = %s AND inference_attempt_id = %s
                    """,
                    (
                        first_evidence["context_pack"]["context_pack_id"],
                        self.owner_id,
                        second_evidence["inference"]["inference_attempt_id"],
                    ),
                )

    async def test_source_erasure_removes_stage3_failure_closure(self) -> None:
        class FailingProvider(DeterministicLocalProvider):
            async def generate(self, request):
                raise RuntimeError("synthetic erasure failure")

        key = f"stage3-erasure-{uuid.uuid4()}"
        with self.assertRaises(RuntimeError):
            await self._service(FailingProvider()).interact(
                InteractionCommand(
                    message="Erase every derivative of this failed request.",
                    privacy_class=PrivacyClass.LOCAL_ONLY,
                    channel="api",
                    idempotency_key=key,
                )
            )
        with self.repository.pool.connection() as connection:
            request = connection.execute(
                """
                SELECT request_id, user_event_id FROM havre.interaction_requests
                WHERE owner_id = %s AND idempotency_key = %s
                """,
                (self.owner_id, key),
            ).fetchone()

        erased = self.repository.erase_source_event_derivatives(
            owner_id=self.owner_id,
            source_event_id=request["user_event_id"],
        )
        self.assertEqual(erased["failure_events"], 1)
        self.assertEqual(erased["inference_attempts"], 1)
        evidence = self.repository.evidence(request["request_id"], owner_id=self.owner_id)
        assert evidence is not None
        self.assertEqual(
            [event["event_type"] for event in evidence["events"]],
            ["USER_MESSAGE"],
        )
        self.assertIsNone(evidence["context_pack"])
        self.assertIsNone(evidence["route_decision"])
        self.assertIsNone(evidence["inference"])
        self.assertIsNone(evidence["request"]["failure_event_id"])
        self.assertEqual(evidence["request"]["error_code"], "source_erasure_propagated")

    async def test_benchmark_report_pair_is_atomic_immutable_evidence(self) -> None:
        revision = "a" * 40
        provider, manifest = build_stage1_compatibility_baseline(
            code_revision=revision
        )
        baseline_provider, baseline_manifest = build_stage1_compatibility_baseline(
            code_revision=revision
        )
        workload = controlled_comparison_workload(
            load_workload_manifest(
                PROJECT_ROOT / "evals" / "fixtures" / "inference_workload_v1.json"
            )
        )
        systems, compatibility = await run_inference_benchmark(
            provider=provider,
            system_under_test=manifest,
            workload=workload,
            environment=capture_environment_manifest(),
            benchmark_code_revision=revision,
            baseline_provider=baseline_provider,
            baseline_manifest=baseline_manifest,
            resource_collector=NullResourceCollector(),
        )

        mismatched_payload = compatibility.model_dump(
            mode="json", exclude={"content_hash"}
        )
        mismatched_payload["candidate_samples"][0][
            "model_artifact_hash"
        ] = "sha256:" + "f" * 64
        mismatched_compatibility = InferenceCompatibilityReport.model_validate(
            mismatched_payload
        )
        with self.assertRaisesRegex(
            ValueError, "candidate samples must match the exact systems manifest"
        ):
            self.repository.persist_inference_benchmark_reports(
                system_report=systems,
                compatibility_report=mismatched_compatibility,
                workload_manifest=workload,
            )

        self.repository.persist_inference_benchmark_reports(
            system_report=systems,
            compatibility_report=compatibility,
            workload_manifest=workload,
        )
        # An exact replay is idempotent and cannot create partial duplicates.
        self.repository.persist_inference_benchmark_reports(
            system_report=systems,
            compatibility_report=compatibility,
            workload_manifest=workload,
        )
        changed_payload = systems.model_dump(mode="json", exclude={"content_hash"})
        changed_payload["limitations"] = [
            *changed_payload["limitations"],
            "Valid alternate report content for conflict testing.",
        ]
        changed_systems = InferenceSystemBenchmarkReport.model_validate(
            changed_payload
        )
        with self.assertRaisesRegex(ValueError, "already bound"):
            self.repository.persist_inference_benchmark_reports(
                system_report=changed_systems,
                compatibility_report=compatibility,
                workload_manifest=workload,
            )
        with self.repository.pool.connection() as connection:
            rows = connection.execute(
                """
                SELECT report_kind, content_hash
                FROM havre.inference_benchmark_runs
                WHERE benchmark_run_id = %s ORDER BY report_kind
                """,
                (systems.benchmark_run_id,),
            ).fetchall()
        self.assertEqual(
            [row["report_kind"] for row in rows],
            ["behavior_compatibility", "systems_performance"],
        )
        self.assertEqual(
            {row["content_hash"] for row in rows},
            {systems.content_hash, compatibility.content_hash},
        )
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
            with self.repository.pool.connection() as connection:
                connection.execute(
                    """
                    UPDATE havre.inference_benchmark_runs
                    SET schema_version = 1
                    WHERE benchmark_run_id = %s
                    """,
                    (systems.benchmark_run_id,),
                )


if __name__ == "__main__":
    unittest.main()
