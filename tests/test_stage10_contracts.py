from __future__ import annotations

import json
import hashlib
import os
import re
import sqlite3
import subprocess
import tempfile
import unittest
import sys
from types import SimpleNamespace
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import UUID

from pydantic import ValidationError

from companion.hashing import content_hash
from companion.operations import (
    BackupManifest,
    ComponentReference,
    ComponentPromotionAuthorization,
    DeploymentHealthEvidence,
    DeploymentRecord,
    ReleaseApprovalRecord,
    ReleaseManifest,
)
from companion.operations.backup import BackupService
from companion.operations.ledger import ErasureLedger
from mlsys.contracts import ProviderVersion
from scripts.export_contract_schemas import CONTRACTS
from services.api.settings import Settings
from services.api.app import create_app
from services.api.metrics import OperationalMetrics
from services.api.image_context import verify_image_context
from services.api.source_provenance import (
    DEPLOYMENT_EXACT_FILES,
    deployment_file_snapshot_revision,
    deployment_source_paths,
    deployment_source_snapshot_revision,
)
from scripts.verify_stage10_deployment_config import (
    resolve_release_manifest_path,
    verify_image_references,
    verify_release_source_binding,
)
from services.api.cli import (
    _parser,
    _require_active_behavior_release,
    _worker_loop,
)
from services.api.release_binding import (
    expected_release_components,
    require_provider_version_binding,
)
from services.api.operations_cli import restore_backup, verify_release_preflight
from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OWNER_ID = UUID("00000000-0000-7000-8000-000000000001")
SHA = "sha256:" + "a" * 64


def _component(
    component: str,
    *,
    lifecycle_status: str = "approved",
) -> ComponentReference:
    return ComponentReference(
        component=component,
        version=f"{component}-v1",
        artifact_hash=SHA,
        lifecycle_status=lifecycle_status,
    )


def _release(**updates) -> ReleaseManifest:
    values = {
        "release_id": "stage10-test-v1",
        "environment": "development",
        "release_scope": "infrastructure_only",
        "source_revision": "b" * 40,
        "migration_head": "0034_stage10_backup_fk_index.sql",
        "components": (
            _component("companion_core"),
            _component("database_schema"),
        ),
        "constitution_version_id": "constitution-v1",
        "identity_version_id": "identity-v1",
        "values_version_id": "values-v1",
    }
    values.update(updates)
    if values["environment"] in {"staging", "production"}:
        values["components"] = (
            *values["components"],
            _component("deployment_image"),
            _component("database_image"),
            _component("proxy_image"),
            _component("operations_image"),
        )
    return ReleaseManifest(**values)


def _health(release: ReleaseManifest) -> DeploymentHealthEvidence:
    image = next(
        (item for item in release.components if item.component == "deployment_image"),
        None,
    )
    return DeploymentHealthEvidence(
        release_manifest_hash=release.content_hash,
        environment=release.environment,
        source_revision=release.source_revision,
        runtime_image_digest=None if image is None else image.artifact_hash,
        ready=True,
        checks=("provider_health", "database_readiness"),
    )


class Stage10ReleaseContractTests(unittest.TestCase):
    def test_release_preflight_is_read_only_and_uses_the_actual_release_store(self) -> None:
        release = _release()
        repository = MagicMock()
        store = MagicMock()
        store.release_activation_status.return_value = True
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "release.json"
            manifest.write_text(release.model_dump_json(), encoding="utf-8")
            with patch(
                "services.api.operations_cli._release_store",
                return_value=(repository, store),
            ):
                result = verify_release_preflight(
                    settings=Settings.from_env(require_owner_api_token=False),
                    manifest_path=manifest,
                )
        store.require_release_preflight.assert_called_once()
        store.release_activation_status.assert_called_once()
        repository.close.assert_called_once()
        self.assertTrue(result["preflight_verified"])
        self.assertTrue(result["applied_deployment"])

    def test_release_approval_is_explicit_owner_decision_evidence(self) -> None:
        release = _release()
        approval = ReleaseApprovalRecord(
            owner_id=OWNER_ID,
            release_manifest_id=release.release_manifest_id,
            release_manifest_hash=release.content_hash,
            approval_scope="infrastructure_production_release",
            decision="rejected",
            rationale="Product Owner decision fixture",
        )
        self.assertEqual(approval.actor, "product_owner")
        self.assertTrue(approval.content_hash.startswith("sha256:"))

    def test_candidate_adapter_is_fixture_only_and_never_production(self) -> None:
        adapter = _component("adapter", lifecycle_status="candidate_fixture")
        fixture = _release(
            release_scope="development_candidate_fixture",
            components=(*_release().components, adapter),
        )
        self.assertFalse(fixture.adapter_deployment_authorized)
        with self.assertRaisesRegex(ValidationError, "production"):
            _release(
                environment="production",
                release_scope="development_candidate_fixture",
                components=(*_release().components, adapter),
            )
        with self.assertRaisesRegex(ValidationError, "cannot claim promotion"):
            _release(
                release_scope="development_candidate_fixture",
                components=(*_release().components, adapter),
                adapter_deployment_authorized=True,
                promotion_approval_ref="owner/forged",
            )
        with self.assertRaisesRegex(ValidationError, "approved components"):
            _release(
                environment="production",
                release_scope="production",
                components=(*_release().components, adapter),
            )

    def test_adapter_deployment_requires_exact_approved_production_gate(self) -> None:
        adapter = _component("adapter", lifecycle_status="approved")
        with self.assertRaisesRegex(ValidationError, "approved production gate"):
            _release(
                environment="staging",
                release_scope="production",
                components=(*_release().components, adapter),
                adapter_deployment_authorized=True,
                promotion_approval_ref=SHA,
                component_promotion_authorization_hashes=(SHA,),
            )
        approved = _release(
            environment="production",
            release_scope="production",
            components=(*_release().components, adapter),
            adapter_deployment_authorized=True,
            promotion_approval_ref=SHA,
            component_promotion_authorization_hashes=(SHA,),
        )
        self.assertTrue(approved.adapter_deployment_authorized)
        provider_version = SimpleNamespace(
            provider_id="provider-v1",
            model_version_id="unused",
            model_artifact_hash=None,
            tokenizer_version_id="unused",
            active_adapter_version_id=adapter.version,
            active_adapter_artifact_hash=adapter.artifact_hash,
        )
        require_provider_version_binding(
            components=(*approved.components, _component("provider")),
            provider_version=provider_version,
        )
        with self.assertRaisesRegex(ValueError, "active adapter"):
            require_provider_version_binding(
                components=(*approved.components, _component("provider")),
                provider_version=SimpleNamespace(
                    **{
                        **provider_version.__dict__,
                        "active_adapter_artifact_hash": "sha256:" + "0" * 64,
                    }
                ),
            )

    def test_applied_deployment_requires_health_and_rollback_target(self) -> None:
        release = _release()
        with self.assertRaisesRegex(ValidationError, "health evidence"):
            DeploymentRecord(
                owner_id=OWNER_ID,
                release_manifest_id=release.release_manifest_id,
                release_manifest_hash=release.content_hash,
                environment="development",
                action="deploy",
                status="applied",
            )
        with self.assertRaisesRegex(ValidationError, "being rolled back"):
            DeploymentRecord(
                owner_id=OWNER_ID,
                release_manifest_id=release.release_manifest_id,
                release_manifest_hash=release.content_hash,
                environment="development",
                action="rollback",
                status="planned",
            )
        valid = DeploymentRecord(
            owner_id=OWNER_ID,
            release_manifest_id=release.release_manifest_id,
            release_manifest_hash=release.content_hash,
            environment=release.environment,
            action="deploy",
            status="applied",
            health_evidence=_health(release),
        )
        self.assertTrue(valid.health_evidence.ready)
        with self.assertRaisesRegex(ValidationError, "bound"):
            DeploymentRecord(
                owner_id=OWNER_ID,
                release_manifest_id=release.release_manifest_id,
                release_manifest_hash=release.content_hash,
                environment=release.environment,
                action="deploy",
                status="applied",
                health_evidence=_health(release).model_copy(
                    update={"release_manifest_hash": "sha256:" + "0" * 64}
                ),
            )

    def test_release_hash_detects_tampering(self) -> None:
        payload = _release().model_dump(mode="json")
        payload["release_id"] = "stage10-tampered"
        with self.assertRaisesRegex(ValidationError, "content_hash"):
            ReleaseManifest.model_validate(payload)


class Stage10ErasureLedgerTests(unittest.TestCase):
    def test_ledger_is_idempotent_contiguous_and_hash_chained(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = ErasureLedger(Path(directory) / "ledger.sqlite3")
            first = ledger.append(owner_id=OWNER_ID, source_event_id=UUID(int=1))
            repeated = ledger.append(owner_id=OWNER_ID, source_event_id=UUID(int=1))
            second = ledger.append(owner_id=OWNER_ID, source_event_id=UUID(int=2))
            self.assertEqual(first, repeated)
            self.assertEqual(second.previous_content_hash, first.content_hash)
            self.assertEqual(ledger.current_sequence(), 2)
            self.assertEqual(ledger.completed_sequence(), 0)
            ledger.mark_completed(sequence=first.sequence)
            self.assertEqual(ledger.completed_sequence(), 1)
            ledger.mark_completed(sequence=second.sequence)
            self.assertEqual(ledger.completed_sequence(), 2)
            self.assertEqual(
                [item.sequence for item in ledger.directives_after(1)], [2]
            )

    def test_ledger_rejects_resigned_or_broken_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite3"
            ledger = ErasureLedger(path)
            ledger.append(owner_id=OWNER_ID, source_event_id=UUID(int=1))
            ledger.append(owner_id=OWNER_ID, source_event_id=UUID(int=2))
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute(
                    "UPDATE erasure_directives SET previous_content_hash=? WHERE sequence=2",
                    ("sha256:" + "0" * 64,),
                )
            with self.assertRaises((ValueError, ValidationError)):
                ledger.verify()


class Stage10BackupContractTests(unittest.TestCase):
    def test_restore_rejects_nonisolated_or_superuser_credential(self) -> None:
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.execute.return_value.fetchone.return_value = (
            "shared_login",
            True,
            True,
            "shared_login",
            True,
            False,
            False,
        )
        with patch(
            "services.api.operations_cli.psycopg.connect",
            return_value=connection,
        ):
            with self.assertRaisesRegex(ValueError, "isolated target owner"):
                restore_backup(
                    settings=Settings.from_env(require_owner_api_token=False),
                    artifact=Path("fixture.dump"),
                    manifest=Path("fixture.manifest.json"),
                    target_database_url="postgresql://restore/target",
                    restore_id=UUID(int=6),
                    pg_dump=Path(sys.executable),
                    pg_restore=Path(sys.executable),
                )

    def test_restore_requires_preinstalled_vector_and_skips_extension_comments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = BackupService(
                pg_dump=Path(sys.executable),
                pg_restore=Path(sys.executable),
                ledger=ErasureLedger(root / "ledger.sqlite3"),
            )
            manifest = BackupManifest(
                owner_id=OWNER_ID,
                artifact_name="fixture.dump",
                artifact_sha256=SHA,
                artifact_size_bytes=1,
                source_database_name="havre_source",
                migration_head="0034_stage10_backup_fk_index.sql",
                release_manifest_id=UUID(int=4),
                release_manifest_hash=SHA,
                erasure_ledger_sequence=0,
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
            connection = MagicMock()
            connection.__enter__.return_value = connection
            connection.execute.return_value.fetchone.return_value = (False, False)
            with (
                patch.object(service, "verify_backup", return_value=manifest),
                patch(
                    "companion.operations.backup.psycopg.connect",
                    return_value=connection,
                ),
            ):
                with self.assertRaisesRegex(ValueError, "vector extension"):
                    service.restore_verified_backup(
                        artifact=root / "fixture.dump",
                        manifest_path=root / "fixture.manifest.json",
                        target_database_url="postgresql://restore/target",
                        restore_id=UUID(int=5),
                        store_factory=None,
                    )

            connection.execute.return_value.fetchone.return_value = (False, True)
            process = subprocess.CompletedProcess([], 1, b"", b"fixture failure")
            with (
                patch.object(service, "verify_backup", return_value=manifest),
                patch(
                    "companion.operations.backup.psycopg.connect",
                    return_value=connection,
                ),
                patch(
                    "companion.operations.backup._postgres_process",
                    return_value=process,
                ) as postgres_process,
            ):
                with self.assertRaisesRegex(RuntimeError, "fixture failure"):
                    service.restore_verified_backup(
                        artifact=root / "fixture.dump",
                        manifest_path=root / "fixture.manifest.json",
                        target_database_url="postgresql://restore/target",
                        restore_id=UUID(int=5),
                        store_factory=None,
                    )
            self.assertIn(
                "--no-comments",
                postgres_process.call_args.kwargs["arguments"],
            )

    def test_expired_backup_is_rejected_and_pruned_only_after_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "havre-expired.dump"
            artifact.write_bytes(b"synthetic-backup")
            digest = "sha256:" + hashlib.sha256(artifact.read_bytes()).hexdigest()
            created = datetime.now(UTC) - timedelta(days=2)
            manifest = BackupManifest(
                owner_id=OWNER_ID,
                artifact_name=artifact.name,
                artifact_sha256=digest,
                artifact_size_bytes=artifact.stat().st_size,
                source_database_name="havre_stage10_fixture",
                migration_head="0034_stage10_backup_fk_index.sql",
                release_manifest_id=UUID(int=4),
                release_manifest_hash=SHA,
                erasure_ledger_sequence=0,
                created_at=created,
                expires_at=created + timedelta(days=1),
            )
            manifest_path = artifact.with_suffix(".manifest.json")
            manifest_path.write_text(manifest.model_dump_json(), encoding="utf-8")
            executable = Path(sys.executable)
            service = BackupService(
                pg_dump=executable,
                pg_restore=executable,
                ledger=ErasureLedger(root / "ledger.sqlite3"),
            )
            with self.assertRaisesRegex(ValueError, "confirmation"):
                service.prune_expired_backups(root=root, confirmed=False)
            with patch.object(service, "verify_backup", return_value=manifest):
                with self.assertRaisesRegex(ValueError, "expired"):
                    service.restore_verified_backup(
                        artifact=artifact,
                        manifest_path=manifest_path,
                        target_database_url="postgresql://invalid/unused",
                        restore_id=UUID(int=3),
                        store_factory=None,
                    )
            removed = service.prune_expired_backups(root=root, confirmed=True)
            self.assertEqual(len(removed), 1)
            self.assertFalse(artifact.exists())
            self.assertFalse(manifest_path.exists())


class Stage10DeploymentAssetTests(unittest.TestCase):
    def test_migrate_owner_bootstrap_is_explicit(self) -> None:
        self.assertFalse(_parser().parse_args(["migrate"]).bootstrap_owner)
        self.assertTrue(
            _parser().parse_args(["migrate", "--bootstrap-owner"]).bootstrap_owner
        )

    def test_metrics_bound_untrusted_route_cardinality_and_label_text(self) -> None:
        metrics = OperationalMetrics()
        for index in range(500):
            metrics.observe(
                method='GET"\nforged',
                route=f'/attacker/{index}/"\n',
                status_code=401,
                started=metrics.timer(),
            )
        rendered = metrics.render(readiness={})
        self.assertEqual(rendered.count('route="/unmatched"'), 2)
        self.assertNotIn("forged", rendered)
        self.assertNotIn("attacker", rendered)

    def test_behavior_worker_requires_scope_and_applied_activation(self) -> None:
        settings = Settings.from_env(require_owner_api_token=False).model_copy(
            update={"deployment_environment": "production"}
        )
        infrastructure = SimpleNamespace(
            release_scope="infrastructure_only",
        )
        runtime = SimpleNamespace(
            release_manifest=infrastructure,
            operations_store=SimpleNamespace(),
            close=lambda: None,
        )
        with patch("services.api.cli.build_runtime", return_value=runtime):
            with self.assertRaisesRegex(RuntimeError, "infrastructure-only"):
                _worker_loop(settings, poll_seconds=0.1)
        with self.assertRaisesRegex(RuntimeError, "infrastructure-only"):
            _require_active_behavior_release(runtime, settings, actor="demo")
        behavioral = SimpleNamespace(release_scope="production")
        operations = SimpleNamespace(
            require_release_activation=lambda manifest: (_ for _ in ()).throw(
                ValueError("not applied")
            )
        )
        runtime = SimpleNamespace(
            release_manifest=behavioral,
            operations_store=operations,
            close=lambda: None,
        )
        with patch("services.api.cli.build_runtime", return_value=runtime):
            with self.assertRaisesRegex(ValueError, "not applied"):
                _worker_loop(settings, poll_seconds=0.1)

    def test_runtime_adapter_binding_is_generic_and_atomic(self) -> None:
        base = Settings.from_env(require_owner_api_token=False)
        with self.assertRaisesRegex(ValidationError, "atomic"):
            Settings.model_validate(
                {
                    **base.model_dump(),
                    "runtime_adapter_version": "synthetic-approved-v1",
                }
            )
        authorization = ComponentPromotionAuthorization(
            component="adapter",
            version="synthetic-approved-v1",
            artifact_hash=SHA,
            rationale="Synthetic Product Owner promotion artifact fixture",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "authorizations.json"
            path.write_text(
                json.dumps([authorization.model_dump(mode="json")]),
                encoding="utf-8",
            )
            settings = Settings.model_validate(
                {
                    **base.model_dump(),
                    "provider_id": "self-hosted-openai-compatible",
                    "runtime_adapter_version": authorization.version,
                    "runtime_adapter_hash": authorization.artifact_hash,
                    "component_promotion_authorizations_path": path,
                }
            )
            migration = PROJECT_ROOT / "db" / "migrations" / (
                "0034_stage10_backup_fk_index.sql"
            )
            components = expected_release_components(
                settings=settings,
                source_snapshot_hash=SHA,
                migration_path=migration,
            )
            adapter = next(item for item in components if item.component == "adapter")
            self.assertEqual(adapter.version, authorization.version)
            self.assertEqual(adapter.lifecycle_status, "approved")
            deterministic = expected_release_components(
                settings=settings.model_copy(update={"provider_id": "deterministic-local"}),
                source_snapshot_hash=SHA,
                migration_path=migration,
            )
            deterministic_adapter = next(
                item for item in deterministic if item.component == "adapter"
            )
            self.assertEqual(deterministic_adapter.lifecycle_status, "candidate_fixture")

    def test_production_release_stays_quarantined_until_exact_applied_record(self) -> None:
        release = _release(
            environment="production",
            release_scope="production",
            components=(*_release().components, _component("provider")),
        )

        class Operations:
            active = False

            def readiness(self):
                return {"database": "ready", "migration_head": release.migration_head}

            def release_activation_status(self, observed):
                return self.active and observed.content_hash == release.content_hash

        class RuntimeFixture:
            def __init__(self):
                self.repository = SimpleNamespace(recover_expired_interactions=lambda **kwargs: [])
                self.operations_store = Operations()
                self.retrieval_service = SimpleNamespace(
                    default_algorithm="retrieval-r1-vector-gated-v2",
                    embedding_provider=SimpleNamespace(version=SimpleNamespace(
                        embedding_version_id="embedding-deterministic-hash-v1")),
                )
                self.release_manifest = release
                self.service = SimpleNamespace(
                    provider=SimpleNamespace(
                        provider_id="provider-v1",
                        health=lambda: None,
                    )
                )

            async def aclose(self):
                return None

        runtime = RuntimeFixture()

        async def healthy():
            return SimpleNamespace(
                status="healthy",
                model_dump=lambda mode="json": {"status": "healthy"},
            )

        runtime.service.provider.health = healthy

        async def version():
            return ProviderVersion(
                provider_id="provider-v1",
                provider_class="cloud",
                execution_environment="cloud",
                provider_adapter_version_id="stage10-provider-adapter-v1",
                serving_engine="stage10-test-engine",
                serving_engine_version="stage10-test-engine-v1",
                serving_config_version="stage10-test-config-v1",
                model_version_id="unused",
                model_artifact_hash=None,
                tokenizer_version_id="unused",
                active_adapter_version_id=None,
                active_adapter_artifact_hash=None,
            )

        runtime.service.provider.version = version
        settings = Settings.from_env(require_owner_api_token=False).model_copy(
            update={
                "deployment_environment": "production",
                "owner_api_token": None,
            }
        )
        with patch("services.api.app.build_runtime", return_value=runtime):
            with TestClient(create_app(settings)) as client:
                preflight = client.get("/health/preflight")
                self.assertEqual(preflight.status_code, 200)
                self.assertEqual(
                    preflight.json()["providers"]["provider-v1"]["version"][
                        "provider_id"
                    ],
                    "provider-v1",
                )
                version_response = client.get("/version")
                self.assertEqual(version_response.status_code, 200)
                self.assertEqual(
                    version_response.json()["providers"]["provider-v1"][
                        "provider_id"
                    ],
                    "provider-v1",
                )
                ready = client.get("/health/ready")
                self.assertEqual(ready.status_code, 200)
                self.assertFalse(ready.json()["release_active"])
                self.assertEqual(client.get("/v1/not-a-route").status_code, 503)
                runtime.operations_store.active = True
                ready = client.get("/health/ready")
                self.assertEqual(ready.status_code, 200)
                self.assertTrue(ready.json()["release_active"])
                self.assertEqual(client.get("/v1/not-a-route").status_code, 404)

    def test_production_settings_require_https_and_secret_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "database-url"
            privileged = root / "privileged-database-url"
            token = root / "owner-token"
            database.write_text(
                "postgresql://app:secret@postgres:5432/havre\n", encoding="utf-8"
            )
            privileged.write_text(
                "postgresql://erasure:secret@postgres:5432/havre\n",
                encoding="utf-8",
            )
            token.write_text("owner-secret-" + "x" * 32 + "\n", encoding="utf-8")
            environment = {
                "HAVRE_DATABASE_URL_FILE": str(database),
                "HAVRE_PRIVILEGED_DATABASE_URL_FILE": str(privileged),
                "HAVRE_OWNER_API_TOKEN_FILE": str(token),
                "HAVRE_DEPLOYMENT_ENVIRONMENT": "production",
                "HAVRE_PUBLIC_BASE_URL": "https://havre.owner.example",
                "HAVRE_RELEASE_MANIFEST_PATH": str(root / "release.json"),
                "HAVRE_RUNTIME_IMAGE_REFERENCE": "owner/havre@sha256:" + "a" * 64,
                "HAVRE_RUNTIME_IMAGE_DIGEST": "sha256:" + "a" * 64,
                "HAVRE_POSTGRES_IMAGE": "owner/postgres@sha256:" + "b" * 64,
                "HAVRE_CADDY_IMAGE": "owner/caddy@sha256:" + "c" * 64,
                "HAVRE_OPERATIONS_IMAGE": "owner/operations@sha256:" + "d" * 64,
            }
            with patch.dict(os.environ, environment, clear=True):
                settings = Settings.from_env()
            self.assertTrue(settings.database_url_from_secret_file)
            self.assertTrue(settings.privileged_database_url_from_secret_file)
            self.assertTrue(settings.owner_api_token_from_secret_file)
            self.assertEqual(settings.owner_api_token, "owner-secret-" + "x" * 32)
            with patch.dict(os.environ, environment, clear=True):
                with self.assertRaisesRegex(
                    ValidationError, "context API requires one exact device"
                ):
                    Settings.from_env(require_context_device=True)
            context_secret = root / "context-device-secret"
            context_secret.write_text("x" * 32 + "\n", encoding="utf-8")
            environment.update({
                "HAVRE_CONTEXT_DEVICE_BINDING_ID": "windows:owner-primary",
                "HAVRE_CONTEXT_DEVICE_SECRET_FILE": str(context_secret),
            })
            with patch.dict(os.environ, environment, clear=True):
                context_settings = Settings.from_env(require_context_device=True)
            self.assertTrue(context_settings.context_device_secret_from_file)
            environment["HAVRE_PUBLIC_BASE_URL"] = "http://havre.owner.example"
            with patch.dict(os.environ, environment, clear=True):
                with self.assertRaisesRegex(ValidationError, "HTTPS"):
                    Settings.from_env()
            environment["HAVRE_PUBLIC_BASE_URL"] = "https://havre.owner.example"
            environment.pop("HAVRE_RUNTIME_IMAGE_REFERENCE")
            with patch.dict(os.environ, environment, clear=True):
                with self.assertRaisesRegex(ValidationError, "exact runtime image"):
                    Settings.from_env()
            environment["HAVRE_RUNTIME_IMAGE_REFERENCE"] = (
                "owner/havre@sha256:" + "b" * 64
            )
            with patch.dict(os.environ, environment, clear=True):
                with self.assertRaisesRegex(ValidationError, "exact configured digest"):
                    Settings.from_env()

    def test_public_product_and_web_push_require_owner_authentication(self) -> None:
        base = Settings.from_env(require_owner_api_token=False)
        with self.assertRaisesRegex(ValidationError, "require owner authentication"):
            Settings.model_validate({
                **base.model_dump(),
                "public_base_url": "https://havre.owner.example",
            })
        with self.assertRaisesRegex(ValidationError, "require owner authentication"):
            Settings.model_validate({
                **base.model_dump(),
                "public_base_url": "https://localhost:8443",
                "web_push_enabled": True,
                "web_push_vapid_public_key": "public",
                "web_push_vapid_private_key": "private",
                "web_push_vapid_subject": "mailto:owner@example.test",
            })

    def test_web_push_requires_dpapi_and_exact_private_tailnet_origin(self) -> None:
        base = Settings.from_env(require_owner_api_token=False)
        common = {
            **base.model_dump(),
            "require_owner_api_token": True,
            "owner_api_token": "o" * 48,
            "web_push_enabled": True,
            "web_push_vapid_public_key": "public",
            "web_push_vapid_private_key": "private",
            "web_push_vapid_key_version": "vapid-owner-test",
            "web_push_vapid_subject": "mailto:owner@example.test",
        }
        with self.assertRaisesRegex(ValidationError, "DPAPI-only"):
            Settings.model_validate({
                **common,
                "public_base_url": "https://havre-node.tail-test.ts.net",
                "web_push_vapid_private_key_from_dpapi": False,
            })
        for origin in (
            "https://havre.owner.example",
            "https://havre-node.tail-test.ts.net:443",
            "https://havre-node.tail-test.ts.net/path",
            "https://user@havre-node.tail-test.ts.net",
        ):
            with self.subTest(origin=origin), self.assertRaisesRegex(
                ValidationError, "private ts.net"
            ):
                Settings.model_validate({
                    **common,
                    "public_base_url": origin,
                    "web_push_vapid_private_key_from_dpapi": True,
                })
        accepted = Settings.model_validate({
            **common,
            "public_base_url": "https://havre-node.tail-test.ts.net",
            "web_push_vapid_private_key_from_dpapi": True,
            "tailscale_cli_path": "C:/Program Files/Tailscale/tailscale.exe",
        })
        self.assertTrue(accepted.web_push_enabled)

    def test_direct_and_file_secret_cannot_be_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            secret = Path(directory) / "database-url"
            secret.write_text("postgresql://file/havre", encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "HAVRE_DATABASE_URL": "postgresql://direct/havre",
                    "HAVRE_DATABASE_URL_FILE": str(secret),
                },
                clear=True,
            ):
                with self.assertRaisesRegex(ValueError, "cannot both be set"):
                    Settings.from_env()

    def test_compose_uses_https_internal_network_secrets_and_replaceable_provider(self) -> None:
        compose = (PROJECT_ROOT / "deploy" / "compose.yaml").read_text(
            encoding="utf-8"
        )
        windows_overlay = (
            PROJECT_ROOT / "deploy" / "compose.stage12a-windows.yaml"
        ).read_text(encoding="utf-8")
        caddy = (PROJECT_ROOT / "deploy" / "Caddyfile").read_text(encoding="utf-8")
        combined = (compose + caddy).lower()
        self.assertNotIn("9201", combined)
        self.assertNotIn("9202", combined)
        self.assertIn('"443:443"', compose)
        self.assertIn("internal: true", compose)
        self.assertNotIn('"5432:5432"', compose)
        self.assertIn("postgres_data:/var/lib/postgresql", compose)
        self.assertNotIn("postgres_data:/var/lib/postgresql/data", compose)
        self.assertIn('command: ["migrate", "--bootstrap-owner"]', compose)
        self.assertNotIn("tmpfs: [/tmp:", compose)
        storage_init_section = compose.split("  storage-init:", 1)[1].split(
            "  api:", 1
        )[0]
        self.assertIn('user: "0:0"', storage_init_section)
        self.assertIn("network_mode: none", storage_init_section)
        self.assertIn('cap_drop: ["ALL"]', storage_init_section)
        self.assertIn('cap_add: ["CHOWN", "FOWNER"]', storage_init_section)
        self.assertNotIn("secrets:", storage_init_section)
        self.assertIn("owner_backups:/var/lib/havre-backups", storage_init_section)
        self.assertIn("HAVRE_PROVIDER_ID", compose)
        self.assertIn("_FILE", compose)
        self.assertIn("HAVRE_PRIVILEGED_DATABASE_URL_FILE", compose)
        worker_section = compose.split("  worker:", 1)[1].split(
            "  release-operations:", 1
        )[0]
        self.assertNotIn("HAVRE_PRIVILEGED_DATABASE_URL_FILE", worker_section)
        self.assertNotIn("havre_owner_api_token", worker_section)
        self.assertNotIn("erasure_ledger", worker_section)
        api_section = compose.split("  api:", 1)[1].split("  worker:", 1)[0]
        self.assertNotIn("HAVRE_CONTEXT_DEVICE_SECRET_FILE", api_section)
        self.assertIn("HAVRE_CONTEXT_DEVICE_SECRET_FILE", windows_overlay)
        self.assertIn("HAVRE_CONTEXT_DEVICE_BINDING_ID", windows_overlay)
        self.assertNotIn("HAVRE_RELEASE_DATABASE_URL_FILE", api_section)
        self.assertNotIn("HAVRE_RELEASE_DATABASE_URL_FILE", worker_section)
        release_section = compose.split("  release-operations:", 1)[1].split(
            "  backup-operations:", 1
        )[0]
        backup_section = compose.split("  backup-operations:", 1)[1].split(
            "  restore-operations:", 1
        )[0]
        restore_section = compose.split("  restore-operations:", 1)[1].split(
            "  context-retention-operations:", 1
        )[0]
        retention_section = compose.split(
            "  context-retention-operations:", 1
        )[1].split("  caddy:", 1)[0]
        self.assertIn("HAVRE_RELEASE_DATABASE_URL_FILE", release_section)
        self.assertNotIn("havre_app_database_url", release_section)
        self.assertNotIn("havre_restore_database_url", release_section)
        self.assertNotIn("havre_owner_api_token", release_section)
        self.assertIn("HAVRE_RELEASE_DATABASE_URL_FILE", backup_section)
        self.assertIn("havre_app_database_url", backup_section)
        self.assertNotIn("havre_restore_database_url", backup_section)
        self.assertNotIn("havre_owner_api_token", backup_section)
        self.assertIn("havre_restore_database_url", restore_section)
        self.assertNotIn("havre_app_database_url", restore_section)
        self.assertNotIn("havre_release_database_url", restore_section)
        self.assertNotIn("havre_owner_api_token", restore_section)
        self.assertIn("havre_erasure_database_url", retention_section)
        self.assertIn("havre_app_database_url", retention_section)
        self.assertNotIn("havre_owner_api_token", retention_section)
        self.assertIn("owner_backups:/var/lib/havre-backups", backup_section)
        self.assertIn("owner_backups:/var/lib/havre-backups", restore_section)
        self.assertIn("HAVRE_RUNTIME_IMAGE_REFERENCE", worker_section)
        self.assertIn("HAVRE_RUNTIME_IMAGE_DIGEST", worker_section)
        for bound in ("cpus:", "mem_limit:", "pids_limit:"):
            self.assertIn(bound, compose)
        roles = (PROJECT_ROOT / "deploy" / "bootstrap_roles.sql").read_text(
            encoding="utf-8"
        )
        finalize_restore = (
            PROJECT_ROOT / "deploy" / "finalize_restore.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("havre_application", roles)
        self.assertIn("havre_erasure_executor", roles)
        self.assertIn("havre_restore_operator", roles)
        self.assertIn(
            "GRANT havre_privileged_erasure TO havre_restore_operator",
            roles,
        )
        self.assertIn("REVOKE DELETE", roles)
        self.assertIn("REVOKE CONNECT ON DATABASE :DBNAME FROM PUBLIC", roles)
        self.assertIn("havre_restore_operator", roles)
        self.assertIn(
            'REASSIGN OWNED BY :"RESTORE_LOGIN" TO CURRENT_USER',
            finalize_restore,
        )
        self.assertIn(
            'ALTER DATABASE :"DBNAME" OWNER TO CURRENT_USER',
            finalize_restore,
        )
        self.assertIn("r.rolname = :'RESTORE_LOGIN'", finalize_restore)
        self.assertNotIn("PASSWORD", roles)
        self.assertIn("Strict-Transport-Security", caddy)

    def test_deployment_manifest_relative_path_uses_compose_directory(self) -> None:
        root = Path("C:/owner/havre")
        self.assertEqual(
            resolve_release_manifest_path("release-manifest.json", root),
            (root / "deploy" / "release-manifest.json").resolve(),
        )
        absolute = (root / "var" / "release-manifest.json").resolve()
        self.assertEqual(
            resolve_release_manifest_path(str(absolute), root),
            absolute,
        )

    def test_docker_context_is_strict_allowlist_without_private_evidence(self) -> None:
        dockerignore = (PROJECT_ROOT / ".dockerignore").read_text(encoding="utf-8")
        lines = tuple(
            line.strip() for line in dockerignore.splitlines() if line.strip()
        )
        self.assertEqual(lines[0], "**")
        self.assertEqual(lines, ("**", "!.havre-build-context-manifest.json"))
        dockerfile = (PROJECT_ROOT / "deploy" / "Dockerfile").read_text(
            encoding="utf-8"
        )
        operations_dockerfile = (
            PROJECT_ROOT / "deploy" / "Operations.Dockerfile"
        ).read_text(encoding="utf-8")
        for forbidden in (
            "COPY evals", "COPY var", "COPY .git", "COPY data",
            "COPY artifacts", "COPY models", "COPY . /app",
        ):
            self.assertNotIn(forbidden, dockerfile)
        self.assertIn("COPY deploy /app/deploy", dockerfile)
        self.assertIn("python -m services.api.image_context", dockerfile)
        self.assertIn("deploy/runtime-requirements.lock", dockerfile)
        self.assertIn("--require-hashes --only-binary=:all:", dockerfile)
        self.assertIn("/tmp/havre-runtime-requirements.lock", dockerfile)
        self.assertLess(
            dockerfile.index("/tmp/havre-runtime-requirements.lock"),
            dockerfile.index("ARG HAVRE_SOURCE_REVISION"),
        )
        self.assertNotIn("pip install --upgrade", dockerfile)
        runtime_lock = (
            PROJECT_ROOT / "deploy" / "runtime-requirements.lock"
        ).read_text(encoding="utf-8")
        requirements = [
            line
            for line in runtime_lock.splitlines()
            if line and not line.startswith(("#", " "))
        ]
        hashes = [
            line.strip()
            for line in runtime_lock.splitlines()
            if line.strip().startswith("--hash=sha256:")
        ]
        self.assertEqual(len(requirements), len(hashes))
        self.assertTrue(all(line.endswith(" \\") for line in requirements))
        self.assertTrue(
            all(re.fullmatch(r"--hash=sha256:[0-9a-f]{64}", line) for line in hashes)
        )
        self.assertIn("--no-deps --no-build-isolation .", dockerfile)
        self.assertIn("python -m pip check", dockerfile)
        self.assertNotIn("mlsys/training", dockerfile)
        self.assertIn("ARG POSTGRES_CLIENT_IMAGE", operations_dockerfile)
        self.assertIn("FROM ${POSTGRES_CLIENT_IMAGE}", operations_dockerfile)
        self.assertIn(
            "COPY --from=havre_api /usr/local /usr/local",
            operations_dockerfile,
        )
        self.assertNotIn(
            "COPY --from=havre_api --chown=10001:10001 /app /app",
            operations_dockerfile,
        )
        self.assertIn(
            "COPY --from=havre_api /app/companion /app/companion",
            operations_dockerfile,
        )
        self.assertNotIn("apt-get", operations_dockerfile)
        self.assertIn("pg_dump --version", operations_dockerfile)
        self.assertIn("pg_restore --version", operations_dockerfile)
        deployment_paths = deployment_source_paths(PROJECT_ROOT)
        self.assertIn("deploy/runtime-requirements.lock", DEPLOYMENT_EXACT_FILES)
        self.assertIn("deploy/finalize_restore.sql", DEPLOYMENT_EXACT_FILES)
        self.assertFalse(
            any(
                path.startswith(("evals/", "mlsys/training/", "var/", "data/"))
                for path in deployment_paths
            )
        )
        for required_copy in (
            "COPY pyproject.toml README.md /app/",
            "COPY companion /app/companion",
            "COPY db/migrations /app/db/migrations",
            "COPY identity /app/identity",
            "COPY mlsys /app/mlsys",
            "COPY services /app/services",
            "COPY scripts/build_stage10_image_context.py",
            "COPY scripts/verify_stage10_deployment_config.py",
        ):
            self.assertIn(required_copy, dockerfile)

    def test_image_context_rejects_tampered_committed_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "services" / "fixture.py"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"committed bytes\n")
            revision = "a" * 40
            snapshot = deployment_file_snapshot_revision(
                root, relative_paths=("services/fixture.py",)
            )
            manifest = root / ".havre-build-context-manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "source_revision": revision,
                        "source_snapshot": snapshot,
                        "files": {
                            "services/fixture.py": "sha256:"
                            + hashlib.sha256(source.read_bytes()).hexdigest()
                        },
                    }
                ),
                encoding="utf-8",
            )
            verify_image_context(
                root=root,
                manifest_path=manifest,
                expected_revision=revision,
                expected_snapshot=snapshot,
            )
            source.write_bytes(b"tampered bytes\n")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                verify_image_context(
                    root=root,
                    manifest_path=manifest,
                    expected_revision=revision,
                    expected_snapshot=snapshot,
                )

    def test_deployment_snapshot_uses_commit_blobs_and_excludes_untracked_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "services").mkdir()
            fixture = root / "services" / "fixture.py"
            fixture.write_bytes(b"committed LF bytes\n")
            for arguments in (
                ("init", "-q"),
                ("config", "user.email", "stage10@example.invalid"),
                ("config", "user.name", "Stage 10 Test"),
                ("add", "services/fixture.py"),
                ("commit", "-q", "-m", "fixture"),
            ):
                subprocess.run(
                    ["git", *arguments], cwd=root, check=True, capture_output=True
                )
            revision = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            exact_root = root / "exact"
            (exact_root / "services").mkdir(parents=True)
            (exact_root / "services" / "fixture.py").write_bytes(
                b"committed LF bytes\n"
            )
            expected = deployment_file_snapshot_revision(
                exact_root, relative_paths=("services/fixture.py",)
            )
            fixture.write_bytes(b"committed LF bytes\r\n")
            (root / "services" / ".env").write_text(
                "PRIVATE_SECRET=must-not-enter-context\n", encoding="utf-8"
            )
            self.assertEqual(
                deployment_source_snapshot_revision(root, revision=revision),
                expected,
            )
            self.assertEqual(
                deployment_source_paths(root, revision=revision),
                ("services/fixture.py",),
            )

    def test_deployment_config_tampering_breaks_the_image_context_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            compose = root / "deploy" / "compose.yaml"
            compose.parent.mkdir()
            compose.write_bytes(b"networks:\n  backend:\n    internal: true\n")
            snapshot = deployment_file_snapshot_revision(
                root, relative_paths=("deploy/compose.yaml",)
            )
            manifest = root / ".havre-build-context-manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "source_revision": "a" * 40,
                        "source_snapshot": snapshot,
                        "files": {
                            "deploy/compose.yaml": "sha256:"
                            + hashlib.sha256(compose.read_bytes()).hexdigest()
                        },
                    }
                ),
                encoding="utf-8",
            )
            compose.write_bytes(b"ports: ['5432:5432']\n")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                verify_image_context(
                    root=root,
                    manifest_path=manifest,
                    expected_revision="a" * 40,
                    expected_snapshot=snapshot,
                )

    def test_host_deployment_preflight_rejects_dirty_executable_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "deploy").mkdir()
            compose = root / "deploy" / "compose.yaml"
            compose.write_bytes(b"networks:\n  backend:\n    internal: true\n")
            for arguments in (
                ("init", "-q"),
                ("config", "user.email", "stage10@example.invalid"),
                ("config", "user.name", "Stage 10 Test"),
                ("add", "deploy/compose.yaml"),
                ("commit", "-q", "-m", "fixture"),
            ):
                subprocess.run(
                    ["git", *arguments], cwd=root, check=True, capture_output=True
                )
            revision = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=root, check=True,
                capture_output=True, text=True,
            ).stdout.strip()
            snapshot = deployment_file_snapshot_revision(
                root, relative_paths=("deploy/compose.yaml",)
            )
            release = ReleaseManifest(
                release_id="host-config-test",
                environment="development",
                release_scope="infrastructure_only",
                source_revision=revision,
                migration_head="0034_stage10_backup_fk_index.sql",
                components=(
                    ComponentReference(
                        component="companion_core",
                        version="test",
                        artifact_hash=snapshot,
                        lifecycle_status="approved",
                    ),
                ),
                constitution_version_id="constitution-v1",
                identity_version_id="identity-v1",
                values_version_id="values-v1",
            )
            manifest = root / "release.json"
            manifest.write_text(release.model_dump_json(), encoding="utf-8")
            verify_release_source_binding(
                release_manifest_path=manifest, project_root=root
            )
            override = root / "deploy" / "compose.override.yaml"
            override.write_text("services: {postgres: {ports: ['5432:5432']}}\n")
            with self.assertRaisesRegex(ValueError, "Compose override"):
                verify_release_source_binding(
                    release_manifest_path=manifest, project_root=root
                )
            override.unlink()
            compose.write_bytes(
                b"networks:\r\n  backend:\r\n    internal: true\r\n"
            )
            with patch(
                "scripts.verify_stage10_deployment_config._tracked_paths_clean",
                return_value=True,
            ):
                verify_release_source_binding(
                    release_manifest_path=manifest, project_root=root
                )
            compose.write_bytes(b"ports: ['5432:5432']\n")
            with self.assertRaisesRegex(ValueError, "host deployment source"):
                verify_release_source_binding(
                    release_manifest_path=manifest, project_root=root
                )

    def test_deployment_imports_without_evaluation_or_training_packages(self) -> None:
        script = """
import builtins
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if (name == 'evals' or name.startswith('evals.') or
            name == 'mlsys.training' or name.startswith('mlsys.training.')):
        raise ModuleNotFoundError('evaluation and training packages intentionally absent')
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
import services.api.operations_cli
import services.api.cli
"""
        completed = subprocess.run(
            [str(Path(sys.executable)), "-c", script],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_deployment_image_preflight_rejects_mutable_or_mismatched_refs(self) -> None:
        digest = "sha256:" + "a" * 64
        result = verify_image_references(
            api_image="owner/havre@" + digest,
            api_image_digest=digest,
            postgres_image="pgvector/postgres@" + digest,
            caddy_image="caddy@" + digest,
            operations_image="owner/havre-operations@" + digest,
        )
        self.assertIn("postgres_image", result)
        with self.assertRaisesRegex(ValueError, "immutable digest"):
            verify_image_references(
                api_image="owner/havre:latest",
                api_image_digest=digest,
                postgres_image="postgres:latest",
                caddy_image="caddy:latest",
                operations_image="owner/havre-operations:latest",
            )
        with self.assertRaisesRegex(ValueError, "disagree"):
            verify_image_references(
                api_image="owner/havre@" + digest,
                api_image_digest="sha256:" + "b" * 64,
                postgres_image="pgvector/postgres@" + digest,
                caddy_image="caddy@" + digest,
                operations_image="owner/havre-operations@" + digest,
            )

    def test_stage10_contract_schemas_are_exported_exactly(self) -> None:
        names = {
            "release-manifest-v1",
            "release-component-reference-v1",
            "component-promotion-authorization-v1",
            "deployment-record-v1",
            "deployment-health-evidence-v1",
            "backup-manifest-v1",
            "erasure-directive-v1",
            "owner-export-artifact-v1",
            "owner-export-manifest-v1",
            "restore-erasure-replay-v1",
        }
        for name in names:
            expected = json.dumps(
                CONTRACTS[name].model_json_schema(),
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            ) + "\n"
            self.assertEqual(
                (PROJECT_ROOT / "contracts" / "schemas" / f"{name}.json").read_text(
                    encoding="utf-8"
                ),
                expected,
            )


if __name__ == "__main__":
    unittest.main()
