from __future__ import annotations

import os
import sys
import tempfile
import threading
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from companion.events import (
    EventEnvelope,
    EventType,
    TextContentPart,
    UserMessagePayload,
)
from companion.hashing import content_hash
from companion.identity import IdentityLoader
from companion.ids import uuid7
from companion.operations import (
    BackupManifest,
    ComponentReference,
    ComponentPromotionAuthorization,
    DeploymentHealthEvidence,
    DeploymentRecord,
    ReleaseApprovalRecord,
    ReleaseManifest,
)
from companion.operations.ledger import ErasureLedger
from companion.operations.backup import BackupService
from companion.operations.coordination import (
    BACKUP_ERASURE_ADVISORY_LOCK,
    local_erasure_lock,
)
from companion.persistence import PostgresRepository, Stage10PostgresStore, apply_migrations
from companion.policy import DataPolicy, PrivacyClass
from companion.tracing import TraceContext
from services.api.app import create_app
from services.api.settings import Settings


DATABASE_URL = os.getenv("HAVRE_TEST_DATABASE_URL")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_HEAD = "0071_current_state_delivery_freshness_lock.sql"
HASH_A = "sha256:" + "a" * 64


@unittest.skipUnless(DATABASE_URL, "HAVRE_TEST_DATABASE_URL is required")
class Stage10PostgresIntegrationTests(unittest.TestCase):
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
            restore_boundary = connection.execute(
                """
                SELECT
                    has_database_privilege('havre_restore_operator', current_database(), 'CONNECT'),
                    has_schema_privilege('havre_restore_operator', 'havre', 'USAGE'),
                    has_table_privilege('havre_restore_operator', 'havre.events', 'SELECT'),
                    has_table_privilege(
                        'havre_restore_operator',
                        'havre.release_approval_records',
                        'INSERT'
                    )
                """
            ).fetchone()
            if restore_boundary != (True, False, False, False):
                raise RuntimeError(
                    f"restore operator least-privilege boundary failed: {restore_boundary}"
                )
        cls.owner = uuid.uuid4()
        cls.repository = PostgresRepository(DATABASE_URL)
        cls.repository.open()
        cls.repository.bootstrap_owner_and_identity(
            owner_id=cls.owner,
            identity=IdentityLoader(PROJECT_ROOT / "identity").load(),
        )
        cls.store = Stage10PostgresStore(
            repository=cls.repository,
            owner_id=cls.owner,
            erasure_repository=cls.repository,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.repository.close()

    def _release(
        self,
        *,
        release_id: str,
        environment: str = "development",
        scope: str = "infrastructure_only",
        rollback_hash: str | None = None,
        candidate_adapter: bool = False,
    ) -> ReleaseManifest:
        components = [
            ComponentReference(
                component="companion_core",
                version="stage10-test",
                artifact_hash=HASH_A,
                lifecycle_status="approved",
            )
        ]
        if candidate_adapter:
            components.append(
                ComponentReference(
                    component="adapter",
                    version="stage9-candidate-fixture",
                    artifact_hash="sha256:" + "b" * 64,
                    lifecycle_status="candidate_fixture",
                )
            )
        if environment in {"staging", "production"}:
            for component, image in (
                ("deployment_image", "havre"),
                ("database_image", "postgres"),
                ("proxy_image", "caddy"),
                ("operations_image", "operations"),
            ):
                components.append(
                    ComponentReference(
                        component=component,
                        version=f"owner/{image}@sha256:" + "d" * 64,
                        artifact_hash="sha256:" + "d" * 64,
                        lifecycle_status="approved",
                    )
                )
        return ReleaseManifest(
            release_id=release_id,
            environment=environment,
            release_scope=scope,
            source_revision="a" * 40,
            migration_head=MIGRATION_HEAD,
            components=tuple(components),
            constitution_version_id="constitution-v1",
            identity_version_id="identity-v1",
            values_version_id="values-v1",
            rollback_release_manifest_hash=rollback_hash,
        )

    def _deployment(
        self,
        release: ReleaseManifest,
        *,
        action: str = "deploy",
        previous_deployment_id=None,
    ) -> DeploymentRecord:
        image = next(
            (item for item in release.components if item.component == "deployment_image"),
            None,
        )
        return DeploymentRecord(
            owner_id=self.owner,
            release_manifest_id=release.release_manifest_id,
            release_manifest_hash=release.content_hash,
            environment=release.environment,
            action=action,
            status="applied",
            previous_deployment_id=previous_deployment_id,
            health_evidence=DeploymentHealthEvidence(
                release_manifest_hash=release.content_hash,
                environment=release.environment,
                source_revision=release.source_revision,
                runtime_image_digest=None if image is None else image.artifact_hash,
                ready=True,
                checks=("provider_health", "database_readiness"),
            ),
        )

    def _insert_source_event(self, text: str):
        trace = TraceContext.from_traceparent(None)
        request_id = uuid7()
        session_id = uuid7()
        event = EventEnvelope(
            event_type=EventType.USER_MESSAGE,
            owner_id=self.owner,
            session_id=session_id,
            request_id=request_id,
            trace_id=trace.trace_id,
            data_policy=DataPolicy.owner_default(
                PrivacyClass.PRIVATE,
                memory_eligible=False,
            ),
            payload=UserMessagePayload(
                content_parts=(TextContentPart(text=text),),
                channel="web",
            ),
        )
        with self.repository.pool.connection() as connection, connection.transaction():
            connection.execute(
                "INSERT INTO havre.sessions (session_id, owner_id, channel) VALUES (%s,%s,'web')",
                (session_id, self.owner),
            )
            connection.execute(
                """
                INSERT INTO havre.traces (
                    trace_id, owner_id, root_request_id, trace_flags, started_at
                ) VALUES (%s,%s,%s,'01',%s)
                """,
                (trace.trace_id, self.owner, request_id, datetime.now(UTC)),
            )
            connection.execute(
                """
                INSERT INTO havre.interaction_requests (
                    request_id, owner_id, session_id, trace_id, idempotency_key,
                    request_fingerprint, request_kind, status
                ) VALUES (%s,%s,%s,%s,%s,%s,'interaction','processing')
                """,
                (
                    request_id,
                    self.owner,
                    session_id,
                    trace.trace_id,
                    f"stage10-source-{request_id}",
                    content_hash({"text": text}),
                ),
            )
            PostgresRepository._insert_event(connection, event)
            connection.execute(
                """
                UPDATE havre.interaction_requests
                SET user_event_id=%s
                WHERE owner_id=%s AND request_id=%s
                """,
                (event.event_id, self.owner, request_id),
            )
        return event.event_id

    def test_candidate_fixture_can_be_recorded_only_as_nonproduction_evidence(self) -> None:
        release = self._release(
            release_id=f"candidate-fixture-{uuid.uuid4()}",
            scope="development_candidate_fixture",
            candidate_adapter=True,
        )
        self.store.persist_release_manifest(release)
        deployment = self._deployment(release)
        self.store.record_deployment(deployment)
        with self.repository.pool.connection() as connection:
            row = connection.execute(
                """
                SELECT release_scope, adapter_lifecycle_status,
                       adapter_deployment_authorized
                FROM havre.release_manifests
                WHERE owner_id=%s AND release_manifest_id=%s
                """,
                (self.owner, release.release_manifest_id),
            ).fetchone()
        self.assertEqual(row["release_scope"], "development_candidate_fixture")
        self.assertEqual(row["adapter_lifecycle_status"], "candidate_fixture")
        self.assertFalse(row["adapter_deployment_authorized"])

    def test_direct_sql_cannot_place_candidate_adapter_in_production(self) -> None:
        with self.assertRaises(psycopg.errors.CheckViolation):
            with self.repository.pool.connection() as connection, connection.transaction():
                connection.execute(
                    """
                    INSERT INTO havre.release_manifests (
                        release_manifest_id, schema_version, owner_id, release_id,
                        environment, release_scope, source_revision, migration_head,
                        adapter_lifecycle_status, adapter_deployment_authorized,
                        promotion_approval_ref, rollback_release_manifest_hash,
                        payload, content_hash, created_at
                    ) VALUES (%s,1,%s,%s,'production','production',%s,%s,
                              'candidate_fixture',false,NULL,NULL,%s,%s,%s)
                    """,
                    (
                        uuid7(),
                        self.owner,
                        f"forged-candidate-production-{uuid.uuid4()}",
                        "a" * 40,
                        MIGRATION_HEAD,
                        Jsonb({"adapter": "candidate_fixture"}),
                        "sha256:" + "c" * 64,
                        datetime.now(UTC),
                    ),
                )

    def test_production_apply_fails_without_product_owner_release_approval(self) -> None:
        release = self._release(
            release_id=f"production-infrastructure-{uuid.uuid4()}",
            environment="production",
        )
        self.store.persist_release_manifest(release)
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
            self.store.record_deployment(self._deployment(release))

    def test_exact_infrastructure_approval_enables_only_its_bound_release(self) -> None:
        release = self._release(
            release_id=f"approved-infrastructure-{uuid.uuid4()}",
            environment="production",
        )
        self.store.persist_release_manifest(release)
        approval = ReleaseApprovalRecord(
            owner_id=self.owner,
            release_manifest_id=release.release_manifest_id,
            release_manifest_hash=release.content_hash,
            approval_scope="infrastructure_production_release",
            decision="approved",
            rationale="Synthetic integration fixture for the exact release gate",
        )
        self.store.persist_release_approval(approval)
        self.store.require_release_preflight(release)
        self.assertFalse(self.store.release_activation_status(release))
        self.store.record_deployment(self._deployment(release))
        self.store.require_release_activation(release)
        personalized = approval.model_copy(
            update={
                "release_approval_id": uuid7(),
                "approval_scope": "personalized_adapter_release",
                "content_hash": "",
            }
        )
        personalized = ReleaseApprovalRecord.model_validate(
            personalized.model_dump(mode="json")
        )
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
            self.store.persist_release_approval(personalized)

    def test_component_promotion_requires_durable_exact_owner_authorization(self) -> None:
        authorization = ComponentPromotionAuthorization(
            component="adapter",
            version="synthetic-attested-adapter-v1",
            artifact_hash="sha256:" + "9" * 64,
            rationale="Synthetic exact promotion authorization fixture",
        )
        release = ReleaseManifest(
            release_id=f"promoted-component-{uuid.uuid4()}",
            environment="production",
            release_scope="production",
            source_revision="a" * 40,
            migration_head=MIGRATION_HEAD,
            components=(
                ComponentReference(
                    component="companion_core",
                    version="stage10-test",
                    artifact_hash=HASH_A,
                    lifecycle_status="approved",
                ),
                ComponentReference(
                    component="deployment_image",
                    version="owner/havre@sha256:" + "d" * 64,
                    artifact_hash="sha256:" + "d" * 64,
                    lifecycle_status="approved",
                ),
                ComponentReference(
                    component="database_image",
                    version="owner/postgres@sha256:" + "d" * 64,
                    artifact_hash="sha256:" + "d" * 64,
                    lifecycle_status="approved",
                ),
                ComponentReference(
                    component="proxy_image",
                    version="owner/caddy@sha256:" + "d" * 64,
                    artifact_hash="sha256:" + "d" * 64,
                    lifecycle_status="approved",
                ),
                ComponentReference(
                    component="operations_image",
                    version="owner/operations@sha256:" + "d" * 64,
                    artifact_hash="sha256:" + "d" * 64,
                    lifecycle_status="approved",
                ),
                ComponentReference(
                    component="adapter",
                    version=authorization.version,
                    artifact_hash=authorization.artifact_hash,
                    lifecycle_status="approved",
                ),
            ),
            constitution_version_id="constitution-v1",
            identity_version_id="identity-v1",
            values_version_id="values-v1",
            adapter_deployment_authorized=True,
            promotion_approval_ref=authorization.content_hash,
            component_promotion_authorization_hashes=(authorization.content_hash,),
        )
        self.store.persist_release_manifest(release)
        with self.assertRaisesRegex(ValueError, "not durable"):
            self.store.require_release_preflight(release)
        self.store.persist_component_promotion_authorization(authorization)
        for scope in (
            "infrastructure_production_release",
            "personalized_adapter_release",
        ):
            self.store.persist_release_approval(
                ReleaseApprovalRecord(
                    owner_id=self.owner,
                    release_manifest_id=release.release_manifest_id,
                    release_manifest_hash=release.content_hash,
                    approval_scope=scope,
                    decision="approved",
                    rationale=f"Synthetic exact {scope} fixture",
                )
            )
        self.store.require_release_preflight(release)

    def test_unbound_health_evidence_is_rejected_by_direct_sql(self) -> None:
        release = self._release(release_id=f"health-binding-{uuid.uuid4()}")
        self.store.persist_release_manifest(release)
        payload = {
            "schema_version": 1,
            "release_manifest_hash": release.content_hash,
            "environment": release.environment,
            "source_revision": release.source_revision,
            "runtime_image_digest": None,
            "ready": False,
            "checks": ["unrelated"],
            "checked_at": datetime.now(UTC).isoformat(),
        }
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
            with self.repository.pool.connection() as connection, connection.transaction():
                connection.execute(
                    """
                    INSERT INTO havre.deployments (
                        deployment_id, schema_version, owner_id, release_manifest_id,
                        release_manifest_hash, environment, action, status,
                        previous_deployment_id, health_evidence, failure_code,
                        payload, content_hash, occurred_at
                    ) VALUES (%s,1,%s,%s,%s,%s,'deploy','applied',NULL,%s,NULL,%s,%s,%s)
                    """,
                    (
                        uuid7(), self.owner, release.release_manifest_id,
                        release.content_hash, release.environment, Jsonb(payload),
                        Jsonb({"forged": True}), "sha256:" + "f" * 64,
                        datetime.now(UTC),
                    ),
                )

    def test_application_role_cannot_forge_release_gate(self) -> None:
        release = self._release(release_id=f"role-boundary-{uuid.uuid4()}")
        with self.repository.pool.connection() as connection:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                with connection.transaction():
                    connection.execute("SET LOCAL ROLE havre_application")
                    connection.execute(
                        """
                        INSERT INTO havre.release_manifests (
                            release_manifest_id, schema_version, owner_id, release_id,
                            environment, release_scope, source_revision, migration_head,
                            adapter_lifecycle_status, adapter_deployment_authorized,
                            promotion_approval_ref, rollback_release_manifest_hash,
                            payload, content_hash, created_at
                        ) VALUES (%s,1,%s,%s,%s,%s,%s,%s,NULL,false,NULL,NULL,%s,%s,%s)
                        """,
                        (
                            release.release_manifest_id, self.owner, release.release_id,
                            release.environment, release.release_scope,
                            release.source_revision, release.migration_head,
                            Jsonb(release.model_dump(mode="json")), release.content_hash,
                            release.created_at,
                        ),
                    )
        with self.repository.pool.connection() as connection, connection.transaction():
            connection.execute("SET LOCAL ROLE havre_release_operator")
            connection.execute(
                """
                INSERT INTO havre.release_manifests (
                    release_manifest_id, schema_version, owner_id, release_id,
                    environment, release_scope, source_revision, migration_head,
                    adapter_lifecycle_status, adapter_deployment_authorized,
                    promotion_approval_ref, rollback_release_manifest_hash,
                    payload, content_hash, created_at
                ) VALUES (%s,1,%s,%s,%s,%s,%s,%s,NULL,false,NULL,NULL,%s,%s,%s)
                """,
                (
                    release.release_manifest_id, self.owner, release.release_id,
                    release.environment, release.release_scope,
                    release.source_revision, release.migration_head,
                    Jsonb(release.model_dump(mode="json")), release.content_hash,
                    release.created_at,
                ),
            )
        with self.repository.pool.connection() as connection:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                with connection.transaction():
                    connection.execute("SET LOCAL ROLE havre_release_operator")
                    connection.execute("SELECT 1 FROM havre.events LIMIT 1")

    def test_backup_manifest_is_bound_to_exact_release(self) -> None:
        manifest = BackupManifest(
            owner_id=self.owner,
            artifact_name="stage10-fixture.dump",
            artifact_sha256="sha256:" + "e" * 64,
            artifact_size_bytes=1,
            source_database_name="stage10_fixture",
            migration_head=MIGRATION_HEAD,
            release_manifest_id=uuid7(),
            release_manifest_hash="sha256:" + "e" * 64,
            erasure_ledger_sequence=0,
            expires_at=datetime.now(UTC) + timedelta(days=365),
        )
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            self.store.persist_backup_manifest(
                manifest,
                artifact_uri="local://backups/stage10-fixture.dump",
            )

    def test_pending_erasure_replays_and_backup_lock_serializes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            ledger = ErasureLedger(Path(temp) / "ledger.sqlite3")
            pending_event = self._insert_source_event(f"PENDING-{uuid.uuid4()}")
            directive = ledger.append(
                owner_id=self.owner,
                source_event_id=pending_event,
            )
            self.assertEqual(ledger.completed_sequence(), 0)
            replay = self.store.replay_erasure_directives(
                ledger=ledger,
                after_sequence=0,
                restore_id=str(uuid7()),
            )
            self.assertEqual(replay["directives_applied"], 1)
            self.assertEqual(ledger.completed_sequence(), directive.sequence)

            blocked_event = self._insert_source_event(f"LOCKED-{uuid.uuid4()}")
            finished = threading.Event()
            failure: list[BaseException] = []

            def erase() -> None:
                try:
                    self.store.erase_source_event(
                        source_event_id=blocked_event,
                        ledger=ledger,
                    )
                except BaseException as error:
                    failure.append(error)
                finally:
                    finished.set()

            with local_erasure_lock(ledger.path):
                thread = threading.Thread(target=erase, daemon=True)
                thread.start()
                self.assertFalse(finished.wait(0.25))
                self.assertEqual(ledger.current_sequence(), directive.sequence)
            self.assertTrue(finished.wait(10))
            thread.join(timeout=1)
            self.assertEqual(failure, [])

            advisory_event = self._insert_source_event(f"ADVISORY-{uuid.uuid4()}")
            advisory_finished = threading.Event()
            advisory_failure: list[BaseException] = []

            def advisory_erase() -> None:
                try:
                    self.store.erase_source_event(
                        source_event_id=advisory_event,
                        ledger=ledger,
                    )
                except BaseException as error:
                    advisory_failure.append(error)
                finally:
                    advisory_finished.set()

            with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
                connection.execute(
                    "SELECT pg_advisory_lock(%s)",
                    (BACKUP_ERASURE_ADVISORY_LOCK,),
                )
                thread = threading.Thread(target=advisory_erase, daemon=True)
                thread.start()
                self.assertFalse(advisory_finished.wait(0.25))
                connection.execute(
                    "SELECT pg_advisory_unlock(%s)",
                    (BACKUP_ERASURE_ADVISORY_LOCK,),
                )
            self.assertTrue(advisory_finished.wait(10))
            thread.join(timeout=1)
            self.assertEqual(advisory_failure, [])

    def test_whole_database_backup_rejects_multiple_owners(self) -> None:
        other_owner = uuid.uuid4()
        self.repository.bootstrap_owner_and_identity(
            owner_id=other_owner,
            identity=IdentityLoader(PROJECT_ROOT / "identity").load(),
        )
        release = self._release(release_id=f"multi-owner-backup-{uuid.uuid4()}")
        with tempfile.TemporaryDirectory() as temp:
            service = BackupService(
                pg_dump=Path(sys.executable),
                pg_restore=Path(sys.executable),
                ledger=ErasureLedger(Path(temp) / "ledger.sqlite3"),
            )
            with self.assertRaisesRegex(ValueError, "exactly the configured single owner"):
                service.create_backup(
                    database_url=DATABASE_URL,
                    destination=Path(temp) / "backup",
                    release=release,
                    owner_id=self.owner,
                    expires_after=timedelta(days=1),
                )

    def test_rollback_must_use_the_target_pinned_by_current_release(self) -> None:
        old = self._release(release_id=f"rollback-old-{uuid.uuid4()}")
        self.store.persist_release_manifest(old)
        current = self._release(
            release_id=f"rollback-current-{uuid.uuid4()}",
            rollback_hash=old.content_hash,
        )
        self.store.persist_release_manifest(current)
        current_deployment = self._deployment(current)
        self.store.record_deployment(current_deployment)
        self.store.record_deployment(
            self._deployment(
                old,
                action="rollback",
                previous_deployment_id=current_deployment.deployment_id,
            )
        )
        self.assertFalse(self.store.release_activation_status(current))
        self.assertTrue(self.store.release_activation_status(old))
        redeployment = self._deployment(current)
        self.store.record_deployment(redeployment)
        with self.assertRaisesRegex(
            psycopg.errors.ObjectNotInPrerequisiteState,
            "latest applied",
        ):
            self.store.record_deployment(
                self._deployment(
                    old,
                    action="rollback",
                    previous_deployment_id=current_deployment.deployment_id,
                )
            )
        wrong = self._release(release_id=f"rollback-wrong-{uuid.uuid4()}")
        self.store.persist_release_manifest(wrong)
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
            self.store.record_deployment(
                self._deployment(
                    wrong,
                    action="rollback",
                    previous_deployment_id=current_deployment.deployment_id,
                )
            )

    def test_release_and_deployment_evidence_is_immutable(self) -> None:
        release = self._release(release_id=f"immutable-release-{uuid.uuid4()}")
        self.store.persist_release_manifest(release)
        deployment = self._deployment(release)
        self.store.record_deployment(deployment)
        for table, identity_column, identity in (
            ("release_manifests", "release_manifest_id", release.release_manifest_id),
            ("deployments", "deployment_id", deployment.deployment_id),
        ):
            with self.assertRaises(psycopg.Error):
                with self.repository.pool.connection() as connection, connection.transaction():
                    connection.execute(
                        f"DELETE FROM havre.{table} WHERE owner_id=%s AND {identity_column}=%s",
                        (self.owner, identity),
                    )

    def test_export_is_complete_hash_bound_and_source_erasure_is_idempotent(self) -> None:
        marker = f"PRIVATE-STAGE10-{uuid.uuid4()}"
        event_id = self._insert_source_event(marker)
        other_owner = uuid.uuid4()
        self.repository.bootstrap_owner_and_identity(
            owner_id=other_owner,
            identity=IdentityLoader(PROJECT_ROOT / "identity").load(),
        )
        own_span_marker = f"OWN-SPAN-{uuid.uuid4()}"
        other_span_marker = f"OTHER-SPAN-{uuid.uuid4()}"
        with self.repository.pool.connection() as connection, connection.transaction():
            own_trace = connection.execute(
                "SELECT trace_id FROM havre.events WHERE owner_id=%s AND event_id=%s",
                (self.owner, event_id),
            ).fetchone()["trace_id"]
            other_trace = uuid.uuid4().hex
            now = datetime.now(UTC)
            connection.execute(
                """
                INSERT INTO havre.traces (
                    trace_id, owner_id, root_request_id, trace_flags, started_at
                ) VALUES (%s,%s,%s,'01',%s)
                """,
                (other_trace, other_owner, uuid7(), now),
            )
            connection.execute(
                """
                INSERT INTO havre.spans (
                    span_id, trace_id, name, kind, started_at, ended_at,
                    duration_ms, status, attributes
                ) VALUES (%s,%s,'owner export fixture','internal',%s,%s,0,'ok',%s),
                         (%s,%s,'other owner fixture','internal',%s,%s,0,'ok',%s)
                """,
                (
                    uuid.uuid4().hex[:16], own_trace, now, now,
                    Jsonb({"marker": own_span_marker}),
                    uuid.uuid4().hex[:16], other_trace, now, now,
                    Jsonb({"marker": other_span_marker}),
                ),
            )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ledger = ErasureLedger(root / "operations" / "ledger.sqlite3")
            before = root / "before"
            manifest = self.store.export_owner_data(before, erasure_ledger=ledger)
            verified = self.store.verify_owner_export(before)
            self.assertEqual(verified.content_hash, manifest.content_hash)
            extra = before / "unmanifested-private.txt"
            extra.write_text(marker, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "membership"):
                self.store.verify_owner_export(before)
            extra.unlink()
            self.assertIn(marker, (before / "tables" / "events.jsonl").read_text(encoding="utf-8"))
            spans = (before / "tables" / "spans.jsonl").read_text(encoding="utf-8")
            self.assertIn(own_span_marker, spans)
            self.assertNotIn(other_span_marker, spans)

            first = self.store.erase_source_event(source_event_id=event_id, ledger=ledger)
            second = self.store.erase_source_event(source_event_id=event_id, ledger=ledger)
            self.assertTrue(first["absence_verified"])
            self.assertEqual(first["raw_source_events"], 1)
            self.assertEqual(second["raw_source_events"], 0)
            self.assertEqual(first["directive_hash"], second["directive_hash"])

            after = root / "after"
            self.store.export_owner_data(after, erasure_ledger=ledger)
            self.store.verify_owner_export(after)
            for path in after.rglob("*"):
                if path.is_file():
                    self.assertNotIn(marker, path.read_text(encoding="utf-8"))
        self.assertEqual(self.repository.audit_provenance_integrity(), [])

    def test_health_version_metrics_and_owner_auth_are_operational(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            token = "stage10-test-token-" + "x" * 32
            base = Settings.from_env(require_owner_api_token=False).model_copy(
                update={
                    "database_url": DATABASE_URL,
                    "owner_id": self.owner,
                    "provider_id": "deterministic-local",
                    "owner_api_token": token,
                    "require_owner_api_token": True,
                    "erasure_ledger_path": Path(temp) / "ledger.sqlite3",
                    "owner_export_root": Path(temp) / "exports",
                }
            )
            with TestClient(create_app(base)) as client:
                self.assertEqual(client.get("/health/live").status_code, 200)
                ready = client.get("/health/ready")
                self.assertEqual(ready.status_code, 200, ready.text)
                self.assertEqual(ready.json()["database"]["migration_head"], MIGRATION_HEAD)
                version = client.get("/version")
                self.assertEqual(version.status_code, 200, version.text)
                self.assertEqual(version.json()["stage"], 10)
                self.assertIsNone(version.json()["release"])
                unauthorized = client.get("/metrics")
                self.assertEqual(unauthorized.status_code, 401)
                unavailable_erasure = client.post(
                    f"/v1/privacy/erasure/source-events/{uuid7()}",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "X-HAVRE-Erasure-Confirm": "raw_source_and_derived",
                    },
                )
                self.assertEqual(unavailable_erasure.status_code, 503)
                authorized = client.get(
                    "/metrics",
                    headers={"Authorization": f"Bearer {token}"},
                )
                self.assertEqual(authorized.status_code, 200, authorized.text)
                self.assertIn("havre_http_requests_total", authorized.text)
                self.assertNotIn("PRIVATE-STAGE10", authorized.text)


if __name__ == "__main__":
    unittest.main()
