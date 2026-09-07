from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
import uuid
from unittest import mock

from fastapi.testclient import TestClient
import httpx
from pydantic import ValidationError
import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg import sql

from apps.windows_agent import (
    CoarseWindowAggregator, LocalActivitySample, elapsed_tick_seconds,
)
from apps.windows_agent.coarse_context import (
    ADAPTER_VERSION,
    CollectionNotAuthorized,
    ProbeUnavailable,
    WindowsCoarseContextAdapter,
    WindowsForegroundProbe,
)
from apps.windows_agent.offline_queue import (
    ProtectedOfflineQueue,
    WindowsDPAPIProtector,
    read_dpapi_secret,
    write_dpapi_secret,
)
from apps.windows_agent.runner import WindowsAgentRunner
from apps.windows_agent.transport import (
    ContextTransportError,
    ContextTransportRejected,
    ContextTransportUnavailable,
    WindowsAgentTransport,
)
from companion.events import (
    ContextSourceLifecyclePayload, EventEnvelope, EventType,
    LifeContextObservedPayload,
)
from companion.hashing import canonical_json, content_hash
from companion.identity import IdentityLoader
from companion.ids import uuid7
from companion.life_context import (
    ConsentScopeRevision,
    ContextObservationDraft,
    ContextCollectionPermit,
    ContextCollectionPermitRequest,
    ContextSourceHealthDraft,
    ContextSourceCapability,
    ContextSourceDescriptor,
    ContextSourceStateRevision,
    ContextCapabilityStateRevision,
    DeviceActivitySummary,
    LifeContextObservationV2,
    RetentionPolicy,
    SamplingPolicy,
    sign_observation_draft,
    sign_health_draft,
    sign_collection_permit_request,
    ContextSourceHealthV2,
    ContextRestoreQuarantine,
    ContextRetentionExpiryIntent,
    ContextRetentionExpiryReceipt,
    WindowsContextActivationBundle,
    classify_external_observation_eligibility,
)
from companion.persistence import (
    ContextIdempotencyConflict,
    ContextIngestRejected,
    PostgresRepository,
    Stage12ContextStore,
    Stage10PostgresStore,
    require_isolated_context_operator,
    apply_migrations,
)
from companion.operations.ledger import ErasureLedger
from companion.policy import DataPolicy, PrivacyClass
from services.api.app import create_app
from services.api.settings import Settings
from scripts.export_contract_schemas import CONTRACTS
from scripts.run_stage12a_windows_benchmark import run as run_windows_benchmark
from scripts.audit_stage12_fk_indexes import audit_stage12_fk_indexes


ROOT = Path(__file__).resolve().parents[1]
DATABASE_URL = os.getenv("HAVRE_TEST_DATABASE_URL")
SECRET = b"stage12a-controlled-test-secret-32-bytes"
ALLOWED_FIELDS = (
    "activity_state",
    "active_seconds",
    "dominant_category",
    "idle_seconds",
    "sample_count",
    "window_seconds",
)


class ReversingProtector:
    def protect(self, value: bytes) -> bytes:
        return b"protected:" + value[::-1]

    def unprotect(self, value: bytes) -> bytes:
        if not value.startswith(b"protected:"):
            raise ValueError("queue ciphertext marker is missing")
        return value[len(b"protected:"):][::-1]


def fixture_bundle(owner: uuid.UUID):
    now = datetime.now(UTC)
    source = ContextSourceDescriptor(
        owner_id=owner,
        source_kind="windows",
        provider_id="windows-native",
        device_binding_id=f"windows:test-{uuid.uuid4()}",
        adapter_version=ADAPTER_VERSION,
        source_version="windows-controlled-fixture-v1",
    )
    capability = ContextSourceCapability(
        owner_id=owner,
        source_instance_id=source.source_instance_id,
        capability_id="windows.device_activity_summary.v1",
        observation_kind="device_activity_summary",
        allowed_fields=ALLOWED_FIELDS,
    )
    policy = DataPolicy(
        privacy_class=PrivacyClass.LOCAL_ONLY,
        memory_eligible=False,
        cloud_eligible=False,
        decision_source="owner_explicit",
        authorization_ref="stage12a-controlled-test-fixture-only",
    )
    consent = ConsentScopeRevision(
        owner_id=owner,
        source_instance_id=source.source_instance_id,
        capability_revision_id=capability.capability_revision_id,
        revision=1,
        status="active",
        allowed_fields=ALLOWED_FIELDS,
        sampling_policy=SamplingPolicy(
            policy_version="windows-test-sampling-v1",
            sample_interval_seconds=10,
            summary_window_seconds=60,
            idle_threshold_seconds=300,
            fresh_for_seconds=300,
            max_clock_skew_seconds=60,
            offline_buffer_seconds=60,
        ),
        retention_policy=RetentionPolicy(
            policy_version="windows-test-retention-v1",
            normalized_draft_retention_seconds=0,
            canonical_retention_days=7,
        ),
        data_policy=policy,
        effective_at=now - timedelta(minutes=5),
        expires_at=now + timedelta(days=1),
        authorization_ref="stage12a-controlled-test-fixture-only",
    )
    return source, capability, consent


def fixture_draft(source, capability, consent, *, key: str | None = None):
    now = datetime.now(UTC).replace(microsecond=0)
    summary = DeviceActivitySummary(
        dominant_category="development",
        activity_state="active",
        active_seconds=50,
        idle_seconds=10,
        sample_count=6,
        window_seconds=60,
    )
    return sign_observation_draft(
        ContextObservationDraft(
            owner_id=source.owner_id,
            source_instance_id=source.source_instance_id,
            device_binding_id=source.device_binding_id,
            capability_revision_id=capability.capability_revision_id,
            capability_id=capability.capability_id,
            observation_kind=capability.observation_kind,
            value=summary,
            occurred_from=now - timedelta(seconds=60),
            occurred_to=now,
            source_observed_at=now,
            consent_scope_revision_id=consent.consent_scope_revision_id,
            sampling_policy_version=consent.sampling_policy.policy_version,
            retention_policy_version=consent.retention_policy.policy_version,
            adapter_version=source.adapter_version,
            data_policy=consent.data_policy,
            idempotency_key=key or f"stage12-test-{uuid.uuid4()}",
            trace_id=uuid.uuid4().hex,
        ),
        secret=SECRET,
    )


def fixture_permit(source, capability, consent, *, issued_at: datetime | None = None):
    instant = issued_at or datetime.now(UTC)
    return ContextCollectionPermit(
        source=source,
        source_state=ContextSourceStateRevision(
            owner_id=source.owner_id,
            source_instance_id=source.source_instance_id,
            revision=1,
            status="enabled",
            reason="registered",
            effective_at=consent.effective_at,
            authorization_ref=consent.authorization_ref,
        ),
        capability=capability,
        capability_state=ContextCapabilityStateRevision(
            owner_id=source.owner_id,
            capability_revision_id=capability.capability_revision_id,
            revision=1,
            status="enabled",
            reason="registered",
            effective_at=consent.effective_at,
            authorization_ref=consent.authorization_ref,
        ),
        consent=consent,
        issued_at=instant,
        valid_until=min(instant + timedelta(seconds=30), consent.expires_at),
    )


class Stage12WindowsContractTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows DPAPI/API benchmark requires Windows")
    def test_content_free_synthetic_windows_benchmark(self) -> None:
        report = run_windows_benchmark(iterations=100)
        self.assertTrue(report["passed"])
        self.assertFalse(report["workload"]["real_owner_activity_collected"])
        self.assertFalse(
            report["native_content_free_evidence"]["activity_sample_collected"]
        )

    @unittest.skipUnless(DATABASE_URL, "HAVRE_TEST_DATABASE_URL is required")
    def test_stage12_foreign_keys_have_left_prefix_indexes(self) -> None:
        self.assertEqual(audit_stage12_fk_indexes(DATABASE_URL), [])

    def test_schema_exports_match_authoritative_contracts(self) -> None:
        names = (
            "context-source-descriptor-v1",
            "context-source-capability-v1",
            "context-consent-scope-revision-v1",
            "context-sampling-policy-v1",
            "context-retention-policy-v1",
            "device-activity-summary-v1",
            "context-observation-draft-v1",
            "context-source-health-draft-v1",
            "context-source-state-revision-v1",
            "context-capability-state-revision-v1",
            "context-collection-permit-v1",
            "context-collection-permit-request-v1",
            "context-retention-expiry-intent-v1",
            "context-retention-expiry-receipt-v1",
            "windows-context-activation-bundle-v1",
            "life-context-observation-v2",
            "context-source-health-v2",
            "context-ingest-result-v1",
        )
        for name in names:
            committed = json.loads(
                (ROOT / "contracts" / "schemas" / f"{name}.json").read_text()
            )
            self.assertEqual(committed, CONTRACTS[name].model_json_schema())

    def test_coarse_summary_has_no_provider_native_content(self) -> None:
        owner = uuid.uuid4()
        source, capability, consent = fixture_bundle(owner)
        draft = fixture_draft(source, capability, consent)
        material = draft.model_dump_json().lower()
        for forbidden in (
            "process_name", "executable", "window_title", "url", "document",
            "clipboard", "keystroke", "screenshot", "microphone", "outlook.exe",
        ):
            self.assertNotIn(forbidden, material)
        self.assertEqual(set(draft.value.model_dump(exclude={"schema_version"})), set(ALLOWED_FIELDS))

    def test_policy_is_local_only_memory_training_and_cloud_ineligible(self) -> None:
        owner = uuid.uuid4()
        source, capability, consent = fixture_bundle(owner)
        self.assertEqual(consent.data_policy.privacy_class, PrivacyClass.LOCAL_ONLY)
        self.assertFalse(consent.data_policy.memory_eligible)
        self.assertFalse(consent.data_policy.training_eligible)
        self.assertFalse(consent.data_policy.cloud_eligible)
        with self.assertRaises(ValidationError):
            ConsentScopeRevision.model_validate(
                consent.model_dump(exclude={"content_hash"})
                | {
                    "data_policy": consent.data_policy.model_dump()
                    | {"memory_eligible": True}
                }
            )

    def test_window_aggregation_is_deterministic_and_not_interpretive(self) -> None:
        now = datetime.now(UTC)
        samples = tuple(
            LocalActivitySample(
                observed_at=now + timedelta(seconds=index * 10),
                category="development" if index < 4 else "browser",
                idle=index == 5,
            )
            for index in range(6)
        )
        summary = CoarseWindowAggregator(
            sample_interval_seconds=10, window_seconds=60
        ).summarize(samples)
        self.assertEqual(summary.dominant_category, "development")
        self.assertEqual(summary.active_seconds, 50)
        self.assertEqual(summary.idle_seconds, 10)
        self.assertNotIn("productive", summary.model_dump_json().lower())

    def test_adapter_requires_exact_source_capability_and_consent(self) -> None:
        owner = uuid.uuid4()
        source, capability, consent = fixture_bundle(owner)
        adapter = WindowsCoarseContextAdapter(
            source=source, capability=capability, consent=consent,
            signing_secret=SECRET,
        )
        draft = adapter.build_draft(
            summary=fixture_draft(source, capability, consent).value,
            occurred_from=datetime.now(UTC) - timedelta(seconds=60),
            occurred_to=datetime.now(UTC),
            source_observed_at=datetime.now(UTC),
        )
        self.assertTrue(draft.signature.startswith("hmac-sha256:"))

    def test_replaceable_sources_produce_the_same_canonical_semantics(self) -> None:
        owner = uuid.uuid4()
        source_a, capability_a, consent_a = fixture_bundle(owner)
        source_b, capability_b, consent_b = fixture_bundle(owner)
        source_b = ContextSourceDescriptor.model_validate(
            source_b.model_dump(exclude={"content_hash"})
            | {"provider_id": "windows-fixture-replacement"}
        )
        capability_b = ContextSourceCapability.model_validate(
            capability_b.model_dump(exclude={"content_hash"})
            | {"source_instance_id": source_b.source_instance_id}
        )
        consent_b = ConsentScopeRevision.model_validate(
            consent_b.model_dump(exclude={"content_hash"})
            | {
                "source_instance_id": source_b.source_instance_id,
                "capability_revision_id": capability_b.capability_revision_id,
            }
        )
        now = datetime.now(UTC)
        summary = fixture_draft(source_a, capability_a, consent_a).value
        drafts = tuple(
            WindowsCoarseContextAdapter(
                source=source, capability=capability, consent=consent,
                signing_secret=SECRET,
            ).build_draft(
                summary=summary,
                occurred_from=now - timedelta(seconds=60),
                occurred_to=now,
                source_observed_at=now,
            )
            for source, capability, consent in (
                (source_a, capability_a, consent_a),
                (source_b, capability_b, consent_b),
            )
        )
        self.assertEqual(drafts[0].value, drafts[1].value)
        self.assertEqual(drafts[0].observation_kind, drafts[1].observation_kind)

    def test_two_interchangeable_probe_implementations_conform(self) -> None:
        owner = uuid.uuid4()
        source, capability, consent = fixture_bundle(owner)

        class ControlledClock:
            def __init__(self) -> None:
                self.value = datetime.now(UTC)

            def sleep(self, seconds: float) -> None:
                self.value += timedelta(seconds=seconds)

            def now(self) -> datetime:
                return self.value

        def collect(probe_type) -> DeviceActivitySummary:
            clock = ControlledClock()

            class Probe(probe_type):
                def __init__(self, _threshold: int) -> None:
                    self.index = 0

                def sample(self) -> LocalActivitySample:
                    item = LocalActivitySample(
                        observed_at=clock.now(),
                        category="development" if self.index < 4 else "browser",
                        idle=self.index == 5,
                    )
                    self.index += 1
                    return item

            adapter = WindowsCoarseContextAdapter(
                source=source, capability=capability, consent=consent,
                signing_secret=SECRET,
                probe_factory=Probe,
                authorization_resolver=lambda: fixture_permit(
                    source, capability, consent, issued_at=clock.now()
                ),
                sleep_fn=clock.sleep,
                clock=clock.now,
            )
            return adapter.collect_window().value

        class ProviderFixtureA:
            pass

        class ProviderFixtureB:
            pass

        self.assertEqual(collect(ProviderFixtureA), collect(ProviderFixtureB))

    @unittest.skipUnless(os.name == "nt", "Windows API binding evidence requires Windows")
    def test_capability_check_never_samples_foreground_state(self) -> None:
        with mock.patch.object(
            WindowsForegroundProbe, "sample", side_effect=AssertionError("sampled")
        ):
            evidence = WindowsCoarseContextAdapter.content_free_probe_evidence()
        self.assertFalse(evidence["activity_sample_collected"])
        self.assertFalse(evidence["exact_process_identity_retained"])

    def test_collection_requires_a_live_permit_before_probe_construction(self) -> None:
        owner = uuid.uuid4()
        source, capability, consent = fixture_bundle(owner)
        constructed = False

        def probe_factory(_threshold):
            nonlocal constructed
            constructed = True
            raise AssertionError("probe must not be constructed")

        adapter = WindowsCoarseContextAdapter(
            source=source, capability=capability, consent=consent,
            signing_secret=SECRET, probe_factory=probe_factory,
        )
        with self.assertRaises(CollectionNotAuthorized):
            adapter.collect_window()
        self.assertFalse(constructed)

    def test_unavailable_probe_is_not_positive_activity(self) -> None:
        now = datetime.now(UTC)
        samples = tuple(
            LocalActivitySample(
                observed_at=now + timedelta(seconds=index * 10),
                category=None,
                idle=None,
                safe_error_category="foreground_unavailable",
            )
            for index in range(6)
        )
        with self.assertRaisesRegex(ProbeUnavailable, "foreground_unavailable"):
            CoarseWindowAggregator(
                sample_interval_seconds=10, window_seconds=60
            ).summarize(samples)

    def test_windows_tick_wrap_and_sparse_coverage_fail_safely(self) -> None:
        self.assertEqual(elapsed_tick_seconds(5_000, 0xFFFFF000), 9)
        now = datetime.now(UTC)
        sparse = tuple(
            LocalActivitySample(
                observed_at=now + timedelta(seconds=index * 15),
                category="development",
                idle=False,
            )
            for index in range(6)
        )
        with self.assertRaisesRegex(ValueError, "bounded interval"):
            CoarseWindowAggregator(
                sample_interval_seconds=10, window_seconds=60
            ).summarize(sparse)

    def test_offline_queue_is_fifo_bounded_encrypted_and_expiring(self) -> None:
        owner = uuid.uuid4()
        source, capability, consent = fixture_bundle(owner)
        draft_a = fixture_draft(source, capability, consent, key="queue-a")
        draft_b = fixture_draft(source, capability, consent, key="queue-b")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "queue.dpapi"
            queue = ProtectedOfflineQueue(
                path=path, protector=ReversingProtector()
            )
            first = queue.enqueue(
                kind="observation", draft=draft_a, max_age_seconds=60,
            )
            second = queue.enqueue(
                kind="observation", draft=draft_b, max_age_seconds=60,
            )
            self.assertEqual(
                [item.payload["idempotency_key"] for item in queue.load()],
                ["queue-a", "queue-b"],
            )
            self.assertNotIn(b"queue-a", path.read_bytes())
            queue.remove(first.queue_id)
            self.assertEqual(len(queue.load()), 1)
            self.assertEqual(queue.load()[0].queue_id, second.queue_id)
            self.assertEqual(
                queue.load(as_of=second.expires_at + timedelta(seconds=1)), ()
            )
            self.assertFalse(path.exists())

    def test_offline_queue_serializes_concurrent_writers(self) -> None:
        owner = uuid.uuid4()
        source, capability, consent = fixture_bundle(owner)
        with tempfile.TemporaryDirectory() as temporary:
            queue = ProtectedOfflineQueue(
                path=Path(temporary) / "queue.dpapi",
                protector=ReversingProtector(),
            )
            errors: list[BaseException] = []

            def enqueue(index: int) -> None:
                try:
                    queue.enqueue(
                        kind="observation",
                        draft=fixture_draft(
                            source, capability, consent, key=f"concurrent-{index}"
                        ),
                        max_age_seconds=60,
                    )
                except BaseException as error:  # pragma: no cover - asserted below
                    errors.append(error)

            threads = [threading.Thread(target=enqueue, args=(index,)) for index in range(12)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(5)
            self.assertEqual(errors, [])
            items = queue.load()
            self.assertEqual(len(items), 12)
            self.assertEqual([item.sequence for item in items], list(range(1, 13)))

    @unittest.skipUnless(os.name == "nt", "DPAPI evidence requires Windows")
    def test_real_dpapi_round_trip_does_not_expose_plaintext(self) -> None:
        protector = WindowsDPAPIProtector()
        plaintext = b"synthetic-stage12-no-private-data"
        ciphertext = protector.protect(plaintext)
        self.assertNotIn(plaintext, ciphertext)
        self.assertEqual(protector.unprotect(ciphertext), plaintext)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "device-secret.dpapi"
            secret = b"synthetic-stage12-device-secret-32-bytes"
            write_dpapi_secret(path, secret)
            self.assertNotIn(secret, path.read_bytes())
            self.assertEqual(read_dpapi_secret(path), secret)

    def test_runner_replays_fifo_and_handles_mid_window_authorization_failures(self) -> None:
        owner = uuid.uuid4()
        source, capability, consent = fixture_bundle(owner)
        permit = fixture_permit(source, capability, consent)

        class Transport:
            signing_secret = SECRET

            def __init__(self, failure) -> None:
                self.failure = failure
                self.permit_calls = 0
                self.submitted: list[str] = []

            def request_permit(self):
                self.permit_calls += 1
                if self.permit_calls > 1:
                    raise self.failure("controlled")
                return permit

            def submit_observation(self, draft):
                self.submitted.append(draft.idempotency_key)

            def submit_health(self, draft):
                raise AssertionError("health was not expected")

        with tempfile.TemporaryDirectory() as temporary:
            queue = ProtectedOfflineQueue(
                path=Path(temporary) / "queue.dpapi",
                protector=ReversingProtector(),
            )
            for key in ("fifo-a", "fifo-b"):
                queue.enqueue(
                    kind="observation",
                    draft=fixture_draft(source, capability, consent, key=key),
                    max_age_seconds=60,
                )
            rejected = Transport(ContextTransportRejected)
            result = WindowsAgentRunner(transport=rejected, queue=queue).run_once()
            self.assertEqual(rejected.submitted, ["fifo-a", "fifo-b"])
            self.assertEqual(result["status"], "authorization_rejected")
            self.assertEqual(queue.load(), ())

            unavailable = Transport(ContextTransportUnavailable)
            result = WindowsAgentRunner(transport=unavailable, queue=queue).run_once()
            self.assertEqual(result["status"], "core_unavailable")
            self.assertFalse(result["queued"])

    def test_transport_is_https_device_authenticated_without_owner_bearer(self) -> None:
        owner = uuid.uuid4()
        source, capability, consent = fixture_bundle(owner)
        observed_headers: list[httpx.Headers] = []

        def handler(request: httpx.Request) -> httpx.Response:
            observed_headers.append(request.headers)
            return httpx.Response(
                200,
                json=fixture_permit(
                    source, capability, consent, issued_at=datetime.now(UTC)
                ).model_dump(mode="json"),
            )

        client = httpx.Client(
            transport=httpx.MockTransport(handler), follow_redirects=False
        )
        transport = WindowsAgentTransport(
            base_url="https://owner-core.invalid",
            owner_id=owner,
            source_instance_id=source.source_instance_id,
            device_binding_id=source.device_binding_id,
            signing_secret=SECRET,
            client=client,
        )
        self.assertEqual(transport.request_permit().source, source)
        self.assertNotIn("authorization", observed_headers[0])
        redirecting = WindowsAgentTransport(
            base_url="https://owner-core.invalid",
            owner_id=owner,
            source_instance_id=source.source_instance_id,
            device_binding_id=source.device_binding_id,
            signing_secret=SECRET,
            client=httpx.Client(
                transport=httpx.MockTransport(
                    lambda _request: httpx.Response(
                        307, headers={"Location": "https://other.invalid"}
                    )
                ),
                follow_redirects=False,
            ),
        )
        with self.assertRaises(ContextTransportError):
            redirecting.request_permit()
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            WindowsAgentTransport(
                base_url="http://owner-core.invalid",
                owner_id=owner,
                source_instance_id=source.source_instance_id,
                device_binding_id=source.device_binding_id,
                signing_secret=SECRET,
            )

    def test_windows_task_installer_is_disabled_and_cannot_activate_collection(self) -> None:
        installer = (
            ROOT / "scripts" / "install_stage12a_windows_task.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("Disable-ScheduledTask", installer)
        self.assertIn("capability-check", installer)
        self.assertIn("expected-source-snapshot", installer)
        self.assertIn("ValidatePattern", installer)
        self.assertIn("EnableCollection", installer)
        self.assertIn("intentionally unavailable", installer)
        self.assertIn("queue-cleanup", installer)
        self.assertIn("Retention Cleanup", installer)
        self.assertIn("RepetitionInterval", installer)
        self.assertNotIn("run-once'", installer)
        uninstall = (
            ROOT / "scripts" / "uninstall_stage12a_windows_task.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("ConfirmLocalErasure", uninstall)
        self.assertIn("ProtectedSecretPath", uninstall)
        self.assertIn("Remove-Item -LiteralPath", uninstall)
        self.assertNotIn("-Recurse", uninstall)
        enrollment = (
            ROOT / "scripts" / "enroll_stage12a_windows_source.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"secret_disclosed": False', enrollment)
        self.assertIn('"collection_started": False', enrollment)
        self.assertIn("write_dpapi_secret", enrollment)


@unittest.skipUnless(DATABASE_URL, "HAVRE_TEST_DATABASE_URL is required")
class Stage12WindowsPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        assert DATABASE_URL is not None
        apply_migrations(DATABASE_URL, ROOT / "db" / "migrations")
        with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
            database_name = connection.execute("SELECT current_database()").fetchone()[0]
            roles_sql = (ROOT / "deploy" / "bootstrap_roles.sql").read_text(
                encoding="utf-8"
            ).replace(":DBNAME", f'"{database_name}"')
            roles_sql = "\n".join(
                line for line in roles_sql.splitlines()
                if not line.lstrip().startswith("\\set ")
            )
            connection.execute(roles_sql)
        cls.repository = PostgresRepository(DATABASE_URL)
        cls.repository.open()
        cls.owner = uuid.uuid4()
        cls.repository.bootstrap_owner_and_identity(
            owner_id=cls.owner, identity=IdentityLoader(ROOT / "identity").load()
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.repository.close()

    def make_store(self, source):
        return Stage12ContextStore(
            repository=self.repository,
            owner_id=self.owner,
            device_secret_resolver=lambda binding: (
                SECRET if binding == source.device_binding_id else (_ for _ in ()).throw(KeyError(binding))
            ),
        )

    def register(self):
        source, capability, consent = fixture_bundle(self.owner)
        store = self.make_store(source)
        store.register_source(source, data_policy=consent.data_policy)
        store.register_capability(capability, data_policy=consent.data_policy)
        store.save_consent(consent)
        return store, source, capability, consent

    def test_atomic_activation_is_exact_idempotent_and_restore_quarantine_safe(self) -> None:
        source, capability, consent = fixture_bundle(self.owner)
        bundle = WindowsContextActivationBundle(
            source=source,
            capability=capability,
            consent=consent,
            owner_activation_ref=consent.authorization_ref,
        )
        store = self.make_store(source)
        first_source_state, first_capability_state = store.activate_windows_bundle(bundle)
        replay_source_state, replay_capability_state = store.activate_windows_bundle(bundle)
        self.assertEqual(replay_source_state, first_source_state)
        self.assertEqual(replay_capability_state, first_capability_state)

        wrong_secret_store = Stage12ContextStore(
            repository=self.repository,
            owner_id=self.owner,
            device_secret_resolver=lambda _binding: b"wrong-secret-value-that-is-at-least-32-bytes",
        )
        with self.assertRaisesRegex(ContextIngestRejected, "exact activation bundle"):
            wrong_secret_store.activate_windows_bundle(bundle)

        quarantine = ContextRestoreQuarantine(
            owner_id=self.owner,
            source_instance_id=source.source_instance_id,
            restore_id=f"activation-replay-{uuid.uuid4()}",
            quarantined_at=datetime.now(UTC),
        )
        with self.repository.pool.connection() as connection:
            connection.execute(
                """
                INSERT INTO havre.context_restore_quarantines (
                    quarantine_id,schema_version,owner_id,source_instance_id,
                    restore_id,reason,quarantined_at,content_hash
                ) VALUES (%s,1,%s,%s,%s,%s,%s,%s)
                """,
                (
                    quarantine.quarantine_id, quarantine.owner_id,
                    quarantine.source_instance_id, quarantine.restore_id,
                    quarantine.reason, quarantine.quarantined_at,
                    quarantine.content_hash,
                ),
            )
        with self.assertRaisesRegex(ContextIngestRejected, "new source enrollment"):
            store.activate_windows_bundle(bundle)

    def test_actual_context_operator_login_is_narrow_and_can_activate(self) -> None:
        login = f"havre_context_test_{uuid.uuid4().hex[:12]}"
        password = f"stage12-{uuid.uuid4().hex}"
        conninfo = conninfo_to_dict(DATABASE_URL)
        context_url = make_conninfo(**(conninfo | {"user": login, "password": password}))
        with psycopg.connect(DATABASE_URL, autocommit=True) as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(login), sql.Literal(password)
                )
            )
            admin.execute(
                sql.SQL("GRANT havre_context_operator TO {}").format(
                    sql.Identifier(login)
                )
            )
        repository = None
        try:
            self.assertEqual(require_isolated_context_operator(context_url), login)
            source, capability, consent = fixture_bundle(self.owner)
            bundle = WindowsContextActivationBundle(
                source=source, capability=capability, consent=consent,
                owner_activation_ref=consent.authorization_ref,
            )
            repository = PostgresRepository(context_url)
            repository.open()
            store = Stage12ContextStore(
                repository=repository,
                owner_id=self.owner,
                device_secret_resolver=lambda _binding: SECRET,
            )
            source_state, capability_state = store.activate_windows_bundle(bundle)
            self.assertEqual(source_state.status, "enabled")
            self.assertEqual(capability_state.status, "enabled")
            with repository.pool.connection() as connection:
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    with connection.transaction():
                        connection.execute("SELECT * FROM havre.events LIMIT 1")
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    with connection.transaction():
                        connection.execute(
                            "INSERT INTO havre.release_approval_records DEFAULT VALUES"
                        )
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    with connection.transaction():
                        connection.execute("CREATE TABLE havre.context_operator_escape(x int)")
        finally:
            if repository is not None:
                repository.close()
            with psycopg.connect(DATABASE_URL, autocommit=True) as admin:
                admin.execute(
                    sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(login))
                )

    def direct_insert_observation(
        self, *, store, source, capability, consent, draft,
        fresh_from_source: bool = False,
        inject_duplicate_canonical_key: bool = False,
        use_noncanonical_time_offset: bool = False,
    ) -> None:
        now = datetime.now(UTC)
        observation = LifeContextObservationV2(
            draft_id=draft.draft_id,
            owner_id=self.owner,
            source_instance_id=draft.source_instance_id,
            capability_revision_id=draft.capability_revision_id,
            capability_id=draft.capability_id,
            observation_kind=draft.observation_kind,
            observation_schema_version=draft.observation_schema_version,
            value=draft.value,
            occurred_from=draft.occurred_from,
            occurred_to=draft.occurred_to,
            source_observed_at=draft.source_observed_at,
            ingested_at=now,
            fresh_until=(
                draft.source_observed_at if fresh_from_source else draft.occurred_to
            ) + timedelta(
                seconds=consent.sampling_policy.fresh_for_seconds
            ),
            retention_expires_at=now + timedelta(
                days=consent.retention_policy.canonical_retention_days
            ),
            consent_scope_revision_id=draft.consent_scope_revision_id,
            sampling_policy_version=draft.sampling_policy_version,
            retention_policy_version=draft.retention_policy_version,
            adapter_version=draft.adapter_version,
            data_policy=draft.data_policy,
            event_id=uuid7(),
            trace_id=draft.trace_id,
            idempotency_key=draft.idempotency_key,
            draft_content_hash=content_hash(
                draft.model_dump(mode="json", exclude={"signature"})
            ),
            device_binding_id=draft.device_binding_id,
            draft_signing_material=draft.signing_material(),
            device_signature=draft.signature,
        )
        canonical_material_override = None
        if inject_duplicate_canonical_key:
            legitimate_material = canonical_json(
                observation.model_dump(mode="json", exclude={"content_hash"})
            )
            canonical_material_override = (
                '{"limitations":["PRIVATE injected text"],'
                + legitimate_material[1:]
            )
            observation = observation.model_copy(update={
                "content_hash": "sha256:" + hashlib.sha256(
                    canonical_material_override.encode("utf-8")
                ).hexdigest()
            })
        elif use_noncanonical_time_offset:
            material = observation.model_dump(mode="json", exclude={"content_hash"})
            material["ingested_at"] = observation.ingested_at.astimezone(
                timezone(timedelta(hours=8))
            ).isoformat()
            canonical_material_override = canonical_json(material)
            observation = observation.model_copy(update={
                "content_hash": "sha256:" + hashlib.sha256(
                    canonical_material_override.encode("utf-8")
                ).hexdigest()
            })
        event = EventEnvelope(
            event_id=observation.event_id,
            event_type=EventType.LIFE_CONTEXT_OBSERVED,
            owner_id=self.owner,
            session_id=uuid7(),
            request_id=uuid7(),
            trace_id=draft.trace_id,
            data_policy=draft.data_policy,
            payload=LifeContextObservedPayload(
                observation_id=observation.observation_id,
                source_instance_id=observation.source_instance_id,
                capability_revision_id=observation.capability_revision_id,
                consent_scope_revision_id=observation.consent_scope_revision_id,
                observation_kind=observation.observation_kind,
                observation_content_hash=observation.content_hash,
            ),
        )
        with self.repository.pool.connection() as connection, connection.transaction():
            store._insert_event_scaffold(
                connection=connection, event=event,
                idempotency_key=f"direct:{draft.idempotency_key}",
                request_fingerprint=observation.draft_content_hash,
            )
            connection.execute("SET LOCAL ROLE havre_application")
            if canonical_material_override is None:
                store._insert_observation(connection, observation)
            else:
                with mock.patch(
                    "companion.persistence.life_context.canonical_json",
                    return_value=canonical_material_override,
                ):
                    store._insert_observation(connection, observation)

    def test_signed_ingest_is_durable_linked_and_idempotent(self) -> None:
        store, source, capability, consent = self.register()
        draft = fixture_draft(source, capability, consent)
        first = store.ingest(draft)
        replay = store.ingest(draft)
        self.assertFalse(first.idempotent_replay)
        self.assertTrue(replay.idempotent_replay)
        self.assertEqual(first.observation.content_hash, replay.observation.content_hash)
        with self.repository.pool.connection() as connection:
            row = connection.execute(
                """
                SELECT o.value, e.event_type, o.memory_eligible,
                       o.training_eligible, o.cloud_eligible
                FROM havre.life_context_observations o
                JOIN havre.events e ON e.event_id=o.event_id
                WHERE o.owner_id=%s AND o.observation_id=%s
                """,
                (self.owner, first.observation.observation_id),
            ).fetchone()
        self.assertEqual(row["event_type"], "LIFE_CONTEXT_OBSERVED")
        self.assertEqual(set(row["value"]), set(ALLOWED_FIELDS) | {"schema_version"})
        self.assertFalse(row["memory_eligible"])
        self.assertFalse(row["training_eligible"])
        self.assertFalse(row["cloud_eligible"])

    def test_signature_and_idempotency_conflict_fail_closed(self) -> None:
        store, source, capability, consent = self.register()
        draft = fixture_draft(source, capability, consent, key="stable-key")
        with self.assertRaisesRegex(ContextIngestRejected, "signature"):
            store.ingest(draft.model_copy(update={"signature": "hmac-sha256:" + "0" * 64}))
        store.ingest(draft)
        changed = sign_observation_draft(
            draft.model_copy(update={
                "signature": "",
                "value": draft.value.model_copy(update={"dominant_category": "browser"}),
            }),
            secret=SECRET,
        )
        with self.assertRaises(ContextIdempotencyConflict):
            store.ingest(changed)

    def test_application_role_cannot_bypass_signature_or_coverage_guards(self) -> None:
        store, source, capability, consent = self.register()
        with self.repository.pool.connection() as connection:
            privileges = connection.execute(
                """
                SELECT
                  has_table_privilege('havre_application',
                    'havre.context_device_bindings','SELECT') AS reads_key,
                  has_table_privilege('havre_application',
                    'havre.context_consent_scope_revisions','INSERT') AS writes_consent,
                  has_table_privilege('havre_application',
                    'havre.life_context_observations','INSERT') AS writes_signed_observation
                """
            ).fetchone()
        self.assertEqual(
            privileges,
            {"reads_key": False, "writes_consent": False,
             "writes_signed_observation": True},
        )
        invalid = fixture_draft(source, capability, consent).model_copy(update={
            "idempotency_key": f"invalid-signature-{uuid.uuid4()}",
            "signature": "hmac-sha256:" + "0" * 64,
        })
        with self.assertRaises(Exception) as raised:
            self.direct_insert_observation(
                store=store, source=source, capability=capability,
                consent=consent, draft=invalid,
            )
        self.assertEqual(
            getattr(raised.exception, "sqlstate", None), "55000",
            str(raised.exception),
        )

        now = datetime.now(UTC).replace(microsecond=0)
        ancient = fixture_draft(source, capability, consent).model_copy(update={
            "draft_id": uuid.uuid4(),
            "occurred_from": now - timedelta(days=30, seconds=60),
            "occurred_to": now - timedelta(days=30),
            "source_observed_at": now,
            "idempotency_key": f"direct-ancient-{uuid.uuid4()}",
            "trace_id": uuid.uuid4().hex,
            "signature": "",
        })
        ancient = sign_observation_draft(ancient, secret=SECRET)
        with self.assertRaises(Exception) as raised:
            self.direct_insert_observation(
                store=store, source=source, capability=capability,
                consent=consent, draft=ancient, fresh_from_source=True,
            )
        self.assertEqual(getattr(raised.exception, "sqlstate", None), "55000")
        with self.assertRaises(Exception) as raised:
            self.direct_insert_observation(
                store=store, source=source, capability=capability,
                consent=consent,
                draft=fixture_draft(source, capability, consent),
                use_noncanonical_time_offset=True,
            )
        self.assertEqual(getattr(raised.exception, "sqlstate", None), "55000")

        signed = fixture_draft(source, capability, consent)
        with self.assertRaises(Exception) as raised:
            self.direct_insert_observation(
                store=store, source=source, capability=capability,
                consent=consent, draft=signed,
                inject_duplicate_canonical_key=True,
            )
        self.assertEqual(getattr(raised.exception, "sqlstate", None), "55000")

    def test_clock_offline_window_and_owner_boundaries_fail_closed(self) -> None:
        store, source, capability, consent = self.register()
        future = fixture_draft(source, capability, consent).model_copy(update={
            "source_observed_at": datetime.now(UTC) + timedelta(minutes=5),
            "signature": "",
        })
        future = sign_observation_draft(future, secret=SECRET)
        with self.assertRaisesRegex(ContextIngestRejected, "future skew"):
            store.ingest(future)
        old_end = datetime.now(UTC) - timedelta(minutes=2)
        old = fixture_draft(source, capability, consent).model_copy(update={
            "occurred_from": old_end - timedelta(seconds=60),
            "occurred_to": old_end,
            "source_observed_at": old_end,
            "idempotency_key": f"old-{uuid.uuid4()}",
            "signature": "",
        })
        old = sign_observation_draft(old, secret=SECRET)
        with self.assertRaisesRegex(ContextIngestRejected, "offline buffer"):
            store.ingest(old)
        other = uuid.uuid4()
        with self.assertRaisesRegex(ContextIngestRejected, "owner mismatch"):
            store.ingest(
                fixture_draft(source, capability, consent).model_copy(
                    update={"owner_id": other}
                )
            )

    def test_later_revocation_blocks_previous_active_scope(self) -> None:
        store, source, capability, consent = self.register()
        revoked = ConsentScopeRevision(
            **(
                consent.model_dump(exclude={
                    "consent_scope_revision_id", "revision", "status", "content_hash"
                })
                | {
                    "consent_scope_revision_id": uuid.uuid4(),
                    "revision": 2,
                    "status": "revoked",
                }
            )
        )
        store.save_consent(revoked)
        with self.assertRaisesRegex(ContextIngestRejected, "not current"):
            store.ingest(fixture_draft(source, capability, consent))

    def test_parallel_consent_scope_for_same_capability_is_forbidden(self) -> None:
        store, source, capability, consent = self.register()
        parallel = ConsentScopeRevision(
            **(
                consent.model_dump(exclude={
                    "consent_scope_revision_id", "consent_scope_id", "content_hash"
                })
                | {
                    "consent_scope_revision_id": uuid.uuid4(),
                    "consent_scope_id": uuid.uuid4(),
                }
            )
        )
        with self.assertRaises(Exception) as raised:
            store.save_consent(parallel)
        self.assertEqual(getattr(raised.exception, "sqlstate", None), "55000")

    def test_concurrent_revocation_serializes_before_ingest(self) -> None:
        store, source, capability, consent = self.register()
        revoked = ConsentScopeRevision(
            **(
                consent.model_dump(exclude={
                    "consent_scope_revision_id", "revision", "status", "content_hash"
                })
                | {
                    "consent_scope_revision_id": uuid.uuid4(),
                    "revision": 2,
                    "status": "revoked",
                }
            )
        )
        errors: dict[str, BaseException | None] = {"revoke": None, "ingest": None}
        blocker = psycopg.connect(DATABASE_URL)
        blocker.execute("BEGIN")
        blocker.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (
                f"context-consent-semantic:{self.owner}:"
                f"{source.source_instance_id}:{capability.capability_revision_id}:"
                f"{consent.purpose}",
            ),
        )

        def revoke() -> None:
            try:
                store.save_consent(revoked)
            except BaseException as error:  # pragma: no cover - asserted below
                errors["revoke"] = error

        def ingest() -> None:
            try:
                store.ingest(fixture_draft(source, capability, consent))
            except BaseException as error:  # pragma: no cover - asserted below
                errors["ingest"] = error

        revoke_thread = threading.Thread(target=revoke)
        ingest_thread = threading.Thread(target=ingest)
        revoke_thread.start()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with self.repository.pool.connection() as connection:
                waiting = connection.execute(
                    "SELECT count(*) AS value FROM pg_locks WHERE locktype='advisory' AND NOT granted"
                ).fetchone()["value"]
            if waiting >= 1:
                break
            time.sleep(0.01)
        else:
            self.fail("revocation did not reach the consent lock")
        ingest_thread.start()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with self.repository.pool.connection() as connection:
                waiting = connection.execute(
                    "SELECT count(*) AS value FROM pg_locks WHERE locktype='advisory' AND NOT granted"
                ).fetchone()["value"]
            if waiting >= 2:
                break
            time.sleep(0.01)
        blocker.commit()
        blocker.close()
        revoke_thread.join(5)
        ingest_thread.join(5)
        self.assertFalse(revoke_thread.is_alive())
        self.assertFalse(ingest_thread.is_alive())
        self.assertIsNone(errors["revoke"])
        self.assertIsInstance(errors["ingest"], ContextIngestRejected)

    def test_capability_disable_serializes_before_permit_authority_time(self) -> None:
        store, source, capability, consent = self.register()
        disabled = ContextCapabilityStateRevision(
            owner_id=self.owner,
            capability_revision_id=capability.capability_revision_id,
            revision=2,
            status="disabled",
            reason="owner_disabled",
            effective_at=datetime.now(UTC),
            authorization_ref=consent.authorization_ref,
        )
        errors: dict[str, BaseException | None] = {"disable": None, "permit": None}
        blocker = psycopg.connect(DATABASE_URL)
        blocker.execute("BEGIN")
        blocker.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (f"context-capability:{self.owner}:{capability.capability_revision_id}",),
        )

        def disable() -> None:
            try:
                store.save_capability_state(disabled, data_policy=consent.data_policy)
            except BaseException as error:  # pragma: no cover - asserted below
                errors["disable"] = error

        def permit() -> None:
            try:
                store.current_collection_permit(
                    source_instance_id=source.source_instance_id,
                    device_binding_id=source.device_binding_id,
                )
            except BaseException as error:  # pragma: no cover - asserted below
                errors["permit"] = error

        disable_thread = threading.Thread(target=disable)
        permit_thread = threading.Thread(target=permit)
        disable_thread.start()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with self.repository.pool.connection() as connection:
                waiting = connection.execute(
                    "SELECT count(*) AS value FROM pg_locks WHERE locktype='advisory' AND NOT granted"
                ).fetchone()["value"]
            if waiting >= 1:
                break
            time.sleep(0.01)
        else:
            self.fail("capability disable did not reach its durable lock")
        permit_thread.start()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with self.repository.pool.connection() as connection:
                waiting = connection.execute(
                    "SELECT count(*) AS value FROM pg_locks WHERE locktype='advisory' AND NOT granted"
                ).fetchone()["value"]
            if waiting >= 2:
                break
            time.sleep(0.01)
        blocker.commit()
        blocker.close()
        disable_thread.join(5)
        permit_thread.join(5)
        self.assertFalse(disable_thread.is_alive())
        self.assertFalse(permit_thread.is_alive())
        self.assertIsNone(errors["disable"])
        self.assertIsInstance(errors["permit"], ContextIngestRejected)

    def test_source_disable_revokes_permit_and_ingest(self) -> None:
        store, source, capability, consent = self.register()
        permit = store.current_collection_permit(
            source_instance_id=source.source_instance_id,
            device_binding_id=source.device_binding_id,
        )
        self.assertEqual(permit.source_state.status, "enabled")
        future_health = sign_health_draft(
            ContextSourceHealthDraft(
                owner_id=self.owner,
                source_instance_id=source.source_instance_id,
                device_binding_id=source.device_binding_id,
                capability_revision_id=capability.capability_revision_id,
                status="degraded",
                checked_at=datetime.now(UTC)+timedelta(seconds=299),
                safe_error_category="foreground_unavailable",
                adapter_version=source.adapter_version,
                source_version=source.source_version,
                idempotency_key=f"future-health-{uuid.uuid4()}",
                trace_id=uuid.uuid4().hex,
            ),
            secret=SECRET,
        )
        self.assertEqual(store.ingest_health(future_health).status, "degraded")
        disable_event_id = store.save_source_state(
            ContextSourceStateRevision(
                owner_id=self.owner,
                source_instance_id=source.source_instance_id,
                revision=2,
                status="disabled",
                reason="lost_device",
                effective_at=datetime.now(UTC),
                authorization_ref=consent.authorization_ref,
            ),
            data_policy=consent.data_policy,
        )
        with self.assertRaisesRegex(ContextIngestRejected, "not valid"):
            store.current_collection_permit(
                source_instance_id=source.source_instance_id,
                device_binding_id=source.device_binding_id,
            )
        with self.assertRaisesRegex(ContextIngestRejected, "disabled"):
            store.ingest(fixture_draft(source, capability, consent))
        with self.repository.pool.connection() as connection:
            health = connection.execute(
                """
                SELECT status, safe_error_category
                FROM havre.context_source_health_records
                WHERE owner_id=%s AND source_instance_id=%s
                ORDER BY created_at DESC, health_id DESC LIMIT 1
                """,
                (self.owner, source.source_instance_id),
            ).fetchone()
        self.assertEqual(
            health,
            {"status": "permission_revoked", "safe_error_category": "permission_revoked"},
        )
        forged_state_id = uuid7()
        forged_hash = "sha256:" + "f" * 64
        forged_event = EventEnvelope(
            event_type=EventType.CONTEXT_SOURCE_STATE_REVISED,
            owner_id=self.owner,
            session_id=uuid7(), request_id=uuid7(), trace_id=uuid.uuid4().hex,
            data_policy=consent.data_policy,
            payload=ContextSourceLifecyclePayload(
                source_instance_id=source.source_instance_id,
                state_revision_id=forged_state_id,
                revision=3,
                action="enabled",
                reason="owner_disabled",
                source_content_hash=source.content_hash,
                state_content_hash=forged_hash,
            ),
        )
        with self.repository.pool.connection() as connection:
            with self.assertRaisesRegex(Exception, "terminal") as raised:
                with connection.transaction():
                    store._insert_event_scaffold(
                        connection=connection,event=forged_event,
                        idempotency_key=f"context-source:{forged_state_id}",
                        request_fingerprint=forged_hash,
                    )
                    connection.execute("SET LOCAL ROLE havre_context_operator")
                    connection.execute(
                        """
                        INSERT INTO havre.context_source_state_revisions (
                            state_revision_id,schema_version,owner_id,
                            source_instance_id,revision,status,reason,effective_at,
                            authorization_ref,decision_event_id,content_hash
                        ) VALUES (%s,1,%s,%s,3,'enabled','owner_disabled',
                                  statement_timestamp(),%s,%s,%s)
                        """,
                        (
                            forged_state_id,self.owner,source.source_instance_id,
                            consent.authorization_ref,forged_event.event_id,forged_hash,
                        ),
                    )
        self.assertEqual(getattr(raised.exception, "sqlstate", None), "55000")
        with tempfile.TemporaryDirectory() as temporary:
            ledger = ErasureLedger(Path(temporary) / "erasure-ledger.sqlite3")
            operations = Stage10PostgresStore(
                repository=self.repository,
                owner_id=self.owner,
                erasure_repository=self.repository,
            )
            with self.assertRaisesRegex(ValueError, "authority events"):
                operations.erase_source_event(
                    source_event_id=disable_event_id,
                    ledger=ledger,
                )
            self.assertEqual(ledger.current_sequence(), 0)
        with self.repository.pool.connection() as connection:
            closure = connection.execute(
                """
                SELECT
                  (SELECT count(*) FROM havre.events
                   WHERE owner_id=%s AND event_id=%s) AS events,
                  (SELECT count(*) FROM havre.context_source_health_records
                   WHERE owner_id=%s AND causal_event_id=%s) AS causal_health
                """,
                (self.owner,disable_event_id,self.owner,disable_event_id),
            ).fetchone()
        self.assertEqual(closure, {"events": 1, "causal_health": 1})
        self.assertEqual(self.repository.audit_provenance_integrity(), [])

    def test_server_time_expiry_and_ancient_coverage_fail_closed(self) -> None:
        source, capability, consent = fixture_bundle(self.owner)
        expired = ConsentScopeRevision.model_validate(
            consent.model_dump(exclude={"content_hash"})
            | {
                "effective_at": datetime.now(UTC) - timedelta(days=2),
                "expires_at": datetime.now(UTC) - timedelta(days=1),
            }
        )
        store = self.make_store(source)
        store.register_source(source, data_policy=expired.data_policy)
        store.register_capability(capability, data_policy=expired.data_policy)
        store.save_consent(expired)
        with self.assertRaisesRegex(ContextIngestRejected, "currently valid"):
            store.ingest(fixture_draft(source, capability, expired))

        store, source, capability, consent = self.register()
        now = datetime.now(UTC).replace(microsecond=0)
        ancient = fixture_draft(source, capability, consent).model_copy(update={
            "occurred_from": now - timedelta(days=30, seconds=60),
            "occurred_to": now - timedelta(days=30),
            "source_observed_at": now,
            "idempotency_key": f"ancient-{uuid.uuid4()}",
            "signature": "",
        })
        ancient = sign_observation_draft(ancient, secret=SECRET)
        with self.assertRaisesRegex(ContextIngestRejected, "coverage end"):
            store.ingest(ancient)

    def test_signed_health_and_out_of_order_observation_do_not_regress_head(self) -> None:
        store, source, capability, consent = self.register()
        latest = store.ingest(fixture_draft(source, capability, consent)).observation
        older_end = latest.occurred_to - timedelta(seconds=1)
        older = fixture_draft(source, capability, consent).model_copy(update={
            "occurred_from": older_end - timedelta(seconds=60),
            "occurred_to": older_end,
            "source_observed_at": older_end,
            "idempotency_key": f"older-{uuid.uuid4()}",
            "signature": "",
        })
        older = sign_observation_draft(older, secret=SECRET)
        historical = store.ingest(older).observation
        with self.repository.pool.connection() as connection:
            head = connection.execute(
                """
                SELECT last_successful_observation_id
                FROM havre.context_source_health_records
                WHERE owner_id=%s AND source_instance_id=%s AND status='healthy'
                ORDER BY coverage_to DESC LIMIT 1
                """,
                (self.owner, source.source_instance_id),
            ).fetchone()
        self.assertNotEqual(historical.observation_id, latest.observation_id)
        self.assertEqual(head["last_successful_observation_id"], latest.observation_id)

        checked_at = datetime.now(UTC)
        degraded = sign_health_draft(
            ContextSourceHealthDraft(
                owner_id=self.owner,
                source_instance_id=source.source_instance_id,
                device_binding_id=source.device_binding_id,
                capability_revision_id=capability.capability_revision_id,
                status="degraded",
                checked_at=checked_at,
                safe_error_category="foreground_unavailable",
                adapter_version=source.adapter_version,
                source_version=source.source_version,
                idempotency_key=f"health-{uuid.uuid4()}",
                trace_id=uuid.uuid4().hex,
            ),
            secret=SECRET,
        )
        self.assertEqual(store.ingest_health(degraded).status, "degraded")
        conflicting = sign_health_draft(
            degraded.model_copy(update={
                "draft_id": uuid.uuid4(),
                "status": "offline",
                "safe_error_category": "network_unavailable",
                "checked_at": checked_at + timedelta(milliseconds=1),
                "trace_id": uuid.uuid4().hex,
                "signature": "",
            }),
            secret=SECRET,
        )
        with self.assertRaises(ContextIdempotencyConflict):
            store.ingest_health(conflicting)
        stale = sign_health_draft(
            degraded.model_copy(update={
                "draft_id": uuid.uuid4(),
                "checked_at": checked_at - timedelta(seconds=1),
                "idempotency_key": f"health-{uuid.uuid4()}",
                "trace_id": uuid.uuid4().hex,
                "signature": "",
            }),
            secret=SECRET,
        )
        with self.assertRaisesRegex(ContextIngestRejected, "out-of-order"):
            store.ingest_health(stale)

    def test_health_is_bound_to_exact_source_capability_and_versions(self) -> None:
        store_a, source_a, capability_a, consent_a = self.register()
        _store_b, source_b, capability_b, _consent_b = self.register()
        checked_at = datetime.now(UTC)
        wrong_capability = sign_health_draft(
            ContextSourceHealthDraft(
                owner_id=self.owner,
                source_instance_id=source_a.source_instance_id,
                device_binding_id=source_a.device_binding_id,
                capability_revision_id=capability_b.capability_revision_id,
                status="degraded",
                checked_at=checked_at,
                safe_error_category="foreground_unavailable",
                adapter_version=source_a.adapter_version,
                source_version=source_a.source_version,
                idempotency_key=f"health-cross-source-{uuid.uuid4()}",
                trace_id=uuid.uuid4().hex,
            ),
            secret=SECRET,
        )
        with self.assertRaisesRegex(ContextIngestRejected, "source or capability"):
            store_a.ingest_health(wrong_capability)

        wrong_version = sign_health_draft(
            ContextSourceHealthDraft(
                **(
                    wrong_capability.model_dump(
                        exclude={"draft_id", "capability_revision_id", "source_version",
                                 "idempotency_key", "trace_id", "signature"}
                    )
                    | {
                        "capability_revision_id": capability_a.capability_revision_id,
                        "source_version": "forged-source-version-v1",
                        "idempotency_key": f"health-version-{uuid.uuid4()}",
                        "trace_id": uuid.uuid4().hex,
                    }
                )
            ),
            secret=SECRET,
        )
        with self.assertRaisesRegex(ContextIngestRejected, "source or capability"):
            store_a.ingest_health(wrong_version)

        forged_health = ContextSourceHealthV2(
            owner_id=self.owner,
            source_instance_id=source_a.source_instance_id,
            capability_revision_id=capability_b.capability_revision_id,
            status=wrong_capability.status,
            checked_at=wrong_capability.checked_at,
            safe_error_category=wrong_capability.safe_error_category,
            adapter_version=wrong_capability.adapter_version,
            source_version=wrong_capability.source_version,
            trace_id=wrong_capability.trace_id,
        )
        with self.repository.pool.connection() as connection, connection.transaction():
            store_a._insert_operational_scaffold(
                connection=connection,
                trace_id=wrong_capability.trace_id,
                idempotency_key=f"direct-{wrong_capability.idempotency_key}",
                request_fingerprint=content_hash(
                    wrong_capability.model_dump(mode="json", exclude={"signature"})
                ),
                recorded_at=checked_at,
            )
            connection.execute("SET LOCAL ROLE havre_application")
            with self.assertRaises(Exception) as raised:
                store_a._insert_health(
                    connection, forged_health, draft=wrong_capability
                )
        self.assertEqual(getattr(raised.exception, "sqlstate", None), "55000")

        unsigned = ContextSourceHealthV2(
            owner_id=self.owner,
            source_instance_id=source_a.source_instance_id,
            capability_revision_id=capability_a.capability_revision_id,
            status="permission_revoked",
            checked_at=datetime.now(UTC),
            safe_error_category="permission_revoked",
            adapter_version=source_a.adapter_version,
            source_version=source_a.source_version,
            trace_id=uuid.uuid4().hex,
        )
        with self.repository.pool.connection() as connection, connection.transaction():
            registration_event = connection.execute(
                """
                SELECT registration_event_id FROM havre.context_sources
                WHERE owner_id=%s AND source_instance_id=%s
                """,
                (self.owner, source_a.source_instance_id),
            ).fetchone()["registration_event_id"]
            store_a._insert_operational_scaffold(
                connection=connection,
                trace_id=unsigned.trace_id,
                idempotency_key=f"unsigned-health-{uuid.uuid4()}",
                request_fingerprint=unsigned.content_hash,
                recorded_at=unsigned.checked_at,
            )
            connection.execute("SET LOCAL ROLE havre_application")
            with self.assertRaisesRegex(Exception, "disable event") as causal_error:
                store_a._insert_health(
                    connection, unsigned, causal_event_id=registration_event
                )
        self.assertEqual(getattr(causal_error.exception, "sqlstate", None), "55000")

    def test_freshness_missingness_and_retention_are_not_owner_state(self) -> None:
        store, source, capability, consent = self.register()
        observation = store.ingest(
            fixture_draft(source, capability, consent)
        ).observation
        health = ContextSourceHealthV2(
            owner_id=self.owner,
            source_instance_id=source.source_instance_id,
            capability_revision_id=capability.capability_revision_id,
            status="healthy",
            checked_at=observation.ingested_at,
            last_successful_observation_id=observation.observation_id,
            last_successful_observation_at=observation.source_observed_at,
            coverage_from=observation.occurred_from,
            coverage_to=observation.occurred_to,
            adapter_version=source.adapter_version,
            source_version=source.source_version,
            trace_id=observation.trace_id,
        )
        self.assertEqual(
            classify_external_observation_eligibility(
                observation=observation, health=health, consent_status="active",
                as_of=observation.ingested_at,
            ),
            "eligible_observation_only",
        )
        self.assertEqual(
            classify_external_observation_eligibility(
                observation=observation, health=health, consent_status="active",
                as_of=observation.fresh_until,
            ),
            "ineligible_stale",
        )
        self.assertEqual(
            classify_external_observation_eligibility(
                observation=None, health=None, consent_status="active",
                as_of=observation.ingested_at,
            ),
            "unknown_not_negative_evidence",
        )

    def test_context_observation_is_immutable_and_erasure_closes_health(self) -> None:
        store, source, capability, consent = self.register()
        observation = store.ingest(
            fixture_draft(source, capability, consent)
        ).observation
        with self.repository.pool.connection() as connection:
            with self.assertRaises(Exception) as raised:
                with connection.transaction():
                    connection.execute(
                        """
                        UPDATE havre.life_context_observations
                        SET value=value WHERE owner_id=%s AND observation_id=%s
                        """,
                        (self.owner, observation.observation_id),
                    )
            self.assertEqual(getattr(raised.exception, "sqlstate", None), "55000")
        erased = self.repository.erase_source_event_derivatives(
            owner_id=self.owner, source_event_id=observation.event_id
        )
        self.assertEqual(erased["life_context_observations"], 1)
        self.assertEqual(erased["context_source_health_records"], 1)
        with self.repository.pool.connection() as connection:
            counts = connection.execute(
                """
                SELECT
                  (SELECT count(*) FROM havre.life_context_observations
                   WHERE owner_id=%s AND observation_id=%s) AS observations,
                  (SELECT count(*) FROM havre.context_source_health_records
                   WHERE owner_id=%s AND last_successful_observation_id=%s) AS health
                """,
                (
                    self.owner, observation.observation_id,
                    self.owner, observation.observation_id,
                ),
            ).fetchone()
        self.assertEqual(counts, {"observations": 0, "health": 0})
        self.assertEqual(self.repository.audit_provenance_integrity(), [])

    def test_retention_expiry_executes_erasure_ledger_and_receipt(self) -> None:
        store, source, capability, consent = self.register()
        observation = store.ingest(
            fixture_draft(source, capability, consent)
        ).observation
        operations = Stage10PostgresStore(
            repository=self.repository,
            owner_id=self.owner,
            erasure_repository=self.repository,
        )
        with tempfile.TemporaryDirectory() as temporary:
            ledger = ErasureLedger(Path(temporary) / "erasure-ledger.sqlite3")
            early = operations.expire_context_retention(ledger=ledger)
            self.assertEqual(early["expired_count"], 0)
            time.sleep(1.1)
            with self.repository.pool.connection() as connection, connection.transaction():
                connection.execute("SET LOCAL session_replication_role='replica'")
                connection.execute(
                    """
                    UPDATE havre.life_context_observations
                    SET retention_expires_at=ingested_at+interval '0.5 seconds'
                    WHERE owner_id=%s AND observation_id=%s
                    """,
                    (self.owner, observation.observation_id),
                )
            result = operations.expire_context_retention(ledger=ledger)
            self.assertGreaterEqual(result["expired_count"], 1)
            self.assertTrue(result["absence_verified"])
            self.assertEqual(len(ledger.verify()), result["expired_count"])
            with self.repository.pool.connection() as connection:
                row = connection.execute(
                    """
                    SELECT
                      (SELECT count(*) FROM havre.events
                       WHERE owner_id=%s AND event_id=%s) AS events,
                      (SELECT count(*) FROM havre.life_context_observations
                       WHERE owner_id=%s AND observation_id=%s) AS observations,
                      (SELECT count(*) FROM havre.context_retention_expiry_receipts
                       WHERE owner_id=%s AND source_event_id=%s
                         AND absence_verified) AS receipts
                    """,
                    (
                        self.owner, observation.event_id,
                        self.owner, observation.observation_id,
                        self.owner, observation.event_id,
                    ),
                ).fetchone()
            self.assertEqual(row, {"events": 0, "observations": 0, "receipts": 1})
            replay = operations.replay_erasure_directives(
                ledger=ledger, after_sequence=0,
                restore_id=f"stage12-retention-{uuid.uuid4()}",
            )
            self.assertTrue(replay["absence_verified"])
            self.assertEqual(replay["provenance_violations"], 0)
            self.assertGreaterEqual(replay["context_sources_quarantined"], 1)
            with self.assertRaisesRegex(ContextIngestRejected, "new source enrollment"):
                store.current_collection_permit(
                    source_instance_id=source.source_instance_id,
                    device_binding_id=source.device_binding_id,
                )

    def test_retention_receipt_cannot_cross_bind_another_owner_intent(self) -> None:
        store, source, capability, consent = self.register()
        observation = store.ingest(
            fixture_draft(source, capability, consent)
        ).observation
        with self.repository.pool.connection() as connection, connection.transaction():
            connection.execute("SET LOCAL session_replication_role='replica'")
            connection.execute(
                """
                UPDATE havre.life_context_observations
                SET retention_expires_at=ingested_at+interval '0.5 seconds'
                WHERE owner_id=%s AND observation_id=%s
                """,
                (self.owner, observation.observation_id),
            )
        time.sleep(1.1)
        with self.repository.pool.connection() as connection:
            row = connection.execute(
                """
                SELECT event_id,observation_id,retention_policy_version,
                       retention_expires_at
                FROM havre.life_context_observations
                WHERE owner_id=%s AND observation_id=%s
                """,
                (self.owner, observation.observation_id),
            ).fetchone()
        intent = ContextRetentionExpiryIntent(
            owner_id=self.owner,
            source_event_id=row["event_id"],
            observation_id=row["observation_id"],
            retention_policy_version=row["retention_policy_version"],
            retention_expires_at=row["retention_expires_at"],
            planned_at=datetime.now(UTC),
        )
        with self.repository.pool.connection() as connection:
            connection.execute(
                """
                INSERT INTO havre.context_retention_expiry_intents (
                    expiry_intent_id,schema_version,owner_id,source_event_id,
                    observation_id,retention_policy_version,
                    retention_expires_at,planned_at,content_hash
                ) VALUES (%s,1,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    intent.expiry_intent_id,intent.owner_id,intent.source_event_id,
                    intent.observation_id,intent.retention_policy_version,
                    intent.retention_expires_at,intent.planned_at,intent.content_hash,
                ),
            )
        mismatched = ContextRetentionExpiryReceipt(
            expiry_intent_id=intent.expiry_intent_id,
            owner_id=self.owner,
            source_event_id=uuid.uuid4(),
            observation_id=intent.observation_id,
            retention_policy_version=intent.retention_policy_version,
            retention_expires_at=intent.retention_expires_at,
            erased_at=datetime.now(UTC),
            directive_sequence=1,
            directive_hash="sha256:"+"c"*64,
        )
        with self.repository.pool.connection() as connection:
            with self.assertRaisesRegex(Exception, "owner-bound") as trigger_error:
                with connection.transaction():
                    connection.execute("SET LOCAL ROLE havre_erasure_executor")
                    connection.execute(
                        """
                        INSERT INTO havre.context_retention_expiry_receipts (
                            expiry_receipt_id,expiry_intent_id,schema_version,
                            owner_id,source_event_id,observation_id,
                            retention_policy_version,retention_expires_at,
                            erased_at,directive_sequence,directive_hash,
                            absence_verified,content_hash
                        ) VALUES (%s,%s,1,%s,%s,%s,%s,%s,%s,%s,%s,true,%s)
                        """,
                        (
                            mismatched.expiry_receipt_id,mismatched.expiry_intent_id,
                            mismatched.owner_id,mismatched.source_event_id,
                            mismatched.observation_id,
                            mismatched.retention_policy_version,
                            mismatched.retention_expires_at,mismatched.erased_at,
                            mismatched.directive_sequence,mismatched.directive_hash,
                            mismatched.content_hash,
                        ),
                    )
        self.assertEqual(getattr(trigger_error.exception, "sqlstate", None), "55000")
        other_owner = uuid.uuid4()
        self.repository.bootstrap_owner_and_identity(
            owner_id=other_owner, identity=IdentityLoader(ROOT / "identity").load()
        )
        forged = ContextRetentionExpiryReceipt(
            expiry_intent_id=intent.expiry_intent_id,
            owner_id=other_owner,
            source_event_id=intent.source_event_id,
            observation_id=intent.observation_id,
            retention_policy_version=intent.retention_policy_version,
            retention_expires_at=intent.retention_expires_at,
            erased_at=datetime.now(UTC),
            directive_sequence=1,
            directive_hash="sha256:"+"a"*64,
        )
        with self.repository.pool.connection() as connection:
            with self.assertRaises(psycopg.errors.ForeignKeyViolation) as raised:
                with connection.transaction():
                    # Disable only the receipt guard transactionally. PostgreSQL
                    # FK constraint triggers remain active, proving this exact
                    # owner-qualified relationship independently.
                    connection.execute(
                        """
                        ALTER TABLE havre.context_retention_expiry_receipts
                        DISABLE TRIGGER context_retention_expiry_receipt_guard
                        """
                    )
                    connection.execute(
                        """
                        INSERT INTO havre.context_retention_expiry_receipts (
                            expiry_receipt_id,expiry_intent_id,schema_version,
                            owner_id,source_event_id,observation_id,
                            retention_policy_version,retention_expires_at,
                            erased_at,directive_sequence,directive_hash,
                            absence_verified,content_hash
                        ) VALUES (%s,%s,1,%s,%s,%s,%s,%s,%s,1,%s,true,%s)
                        """,
                        (
                            forged.expiry_receipt_id,forged.expiry_intent_id,
                            forged.owner_id,forged.source_event_id,
                            forged.observation_id,forged.retention_policy_version,
                            forged.retention_expires_at,forged.erased_at,
                            forged.directive_hash,forged.content_hash,
                        ),
                    )
        self.assertEqual(raised.exception.sqlstate, "23503")
        self.assertEqual(
            raised.exception.diag.constraint_name,
            "context_retention_expiry_receipt_owner_id_expiry_intent_id_fkey",
        )

    def test_owner_export_redacts_device_verification_secret(self) -> None:
        store, source, capability, consent = self.register()
        operations = Stage10PostgresStore(
            repository=self.repository, owner_id=self.owner
        )
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "export"
            manifest = operations.export_owner_data(destination)
            self.assertTrue(
                any(
                    artifact.relative_path
                    == "tables/context_device_binding_metadata.jsonl"
                    for artifact in manifest.artifacts
                )
            )
            serialized = b"".join(
                path.read_bytes() for path in destination.rglob("*") if path.is_file()
            )
            self.assertNotIn(SECRET, serialized)
            self.assertFalse(
                (destination / "tables/context_device_bindings.jsonl").exists()
            )

    def test_api_uses_same_signed_ingest_boundary(self) -> None:
        source, capability, consent = fixture_bundle(self.owner)
        settings = Settings.from_env(require_owner_api_token=False).model_copy(update={
            "database_url": DATABASE_URL,
            "owner_id": self.owner,
            "provider_id": "deterministic-local",
            "context_device_binding_id": source.device_binding_id,
            "context_device_secret": SECRET.decode(),
            "owner_api_token": "stage12-owner-token-not-shared-with-device",
        })
        with TestClient(create_app(settings)) as client:
            runtime = client.app.state.runtime
            runtime.context_store.register_source(
                source, data_policy=consent.data_policy
            )
            runtime.context_store.register_capability(
                capability, data_policy=consent.data_policy
            )
            runtime.context_store.save_consent(consent)
            permit_request = sign_collection_permit_request(
                ContextCollectionPermitRequest(
                    owner_id=self.owner,
                    source_instance_id=source.source_instance_id,
                    device_binding_id=source.device_binding_id,
                    requested_at=datetime.now(UTC),
                    nonce=uuid.uuid4().hex,
                ),
                secret=SECRET,
            )
            permit_response = client.post(
                "/v1/context/collection-permit",
                json=permit_request.model_dump(mode="json"),
            )
            response = client.post(
                "/v1/context/observations",
                json=fixture_draft(source, capability, consent).model_dump(mode="json"),
            )
        self.assertEqual(permit_response.status_code, 200, permit_response.text)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["idempotent_replay"])


if __name__ == "__main__":
    unittest.main()
