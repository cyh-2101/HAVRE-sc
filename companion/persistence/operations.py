"""PostgreSQL-backed Stage 10 release, export, and erasure operations."""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager, ExitStack
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from psycopg import sql
import psycopg
from psycopg.types.json import Jsonb

from companion.hashing import canonical_json
from companion.life_context import (
    ContextRestoreQuarantine,
    ContextRetentionExpiryIntent,
    ContextRetentionExpiryReceipt,
    ContextSourceErasureTombstone,
)
from companion.operations.ledger import ErasureLedger
from companion.operations.coordination import backup_erasure_lock, local_erasure_lock
from companion.operations.models import (
    BackupManifest,
    ComponentPromotionAuthorization,
    DeploymentRecord,
    ExportArtifact,
    OwnerExportManifest,
    ReleaseApprovalRecord,
    ReleaseManifest,
    RestoreErasureReplay,
)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise ValueError("database export contains a naive timestamp")
        return value.astimezone(UTC).isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    return str(value)


class Stage10PostgresStore:
    def __init__(
        self,
        *,
        repository,
        owner_id: UUID,
        erasure_repository=None,
        erasure_repository_factory=None,
    ) -> None:
        self.repository = repository
        self.owner_id = owner_id
        self.erasure_repository = erasure_repository
        self.erasure_repository_factory = erasure_repository_factory

    @property
    def erasure_available(self) -> bool:
        return (
            self.erasure_repository is not None
            or self.erasure_repository_factory is not None
        )

    @contextmanager
    def _erasure_scope(self):
        if self.erasure_repository is not None:
            yield self.erasure_repository
            return
        if self.erasure_repository_factory is None:
            raise RuntimeError("privileged erasure connection is not configured")
        repository = self.erasure_repository_factory()
        try:
            yield repository
        finally:
            repository.close()

    def persist_release_manifest(self, manifest: ReleaseManifest) -> None:
        adapter = next(
            (item for item in manifest.components if item.component == "adapter"),
            None,
        )
        with self.repository.pool.connection() as connection, connection.transaction():
            inserted = connection.execute(
                """
                INSERT INTO havre.release_manifests (
                    release_manifest_id, schema_version, owner_id, release_id,
                    environment, release_scope, source_revision, migration_head,
                    adapter_lifecycle_status, adapter_deployment_authorized,
                    promotion_approval_ref, rollback_release_manifest_hash,
                    component_promotion_authorization_hashes,
                    payload, content_hash, created_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (release_manifest_id) DO NOTHING
                RETURNING release_manifest_id
                """,
                (
                    manifest.release_manifest_id,
                    manifest.schema_version,
                    self.owner_id,
                    manifest.release_id,
                    manifest.environment,
                    manifest.release_scope,
                    manifest.source_revision,
                    manifest.migration_head,
                    None if adapter is None else adapter.lifecycle_status,
                    manifest.adapter_deployment_authorized,
                    manifest.promotion_approval_ref,
                    manifest.rollback_release_manifest_hash,
                    Jsonb(list(manifest.component_promotion_authorization_hashes)),
                    Jsonb(manifest.model_dump(mode="json")),
                    manifest.content_hash,
                    manifest.created_at,
                ),
            ).fetchone()
            if inserted is None:
                existing = connection.execute(
                    """
                    SELECT content_hash FROM havre.release_manifests
                    WHERE owner_id=%s AND release_manifest_id=%s
                    """,
                    (self.owner_id, manifest.release_manifest_id),
                ).fetchone()
                if existing is None or existing["content_hash"] != manifest.content_hash:
                    raise ValueError("release manifest identity already binds other bytes")

    def persist_component_promotion_authorization(
        self,
        authorization: ComponentPromotionAuthorization,
    ) -> None:
        with self.repository.pool.connection() as connection, connection.transaction():
            inserted = connection.execute(
                """
                INSERT INTO havre.component_promotion_authorizations (
                    owner_id, schema_version, component, version, artifact_hash,
                    decision, actor, rationale, decided_at, payload, content_hash
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (owner_id, content_hash) DO NOTHING
                RETURNING content_hash
                """,
                (
                    self.owner_id,
                    authorization.schema_version,
                    authorization.component,
                    authorization.version,
                    authorization.artifact_hash,
                    authorization.decision,
                    authorization.actor,
                    authorization.rationale,
                    authorization.decided_at,
                    Jsonb(authorization.model_dump(mode="json")),
                    authorization.content_hash,
                ),
            ).fetchone()
            if inserted is None:
                existing = connection.execute(
                    """
                    SELECT payload FROM havre.component_promotion_authorizations
                    WHERE owner_id=%s AND content_hash=%s
                    """,
                    (self.owner_id, authorization.content_hash),
                ).fetchone()
                if existing is None or existing["payload"] != authorization.model_dump(
                    mode="json"
                ):
                    raise ValueError("component authorization hash binds other bytes")

    def record_deployment(self, record: DeploymentRecord) -> None:
        if record.owner_id != self.owner_id:
            raise ValueError("deployment owner mismatch")
        with self.repository.pool.connection() as connection, connection.transaction():
            inserted = connection.execute(
                """
                INSERT INTO havre.deployments (
                    deployment_id, schema_version, owner_id, release_manifest_id,
                    release_manifest_hash, environment, action, status,
                    previous_deployment_id, health_evidence, failure_code,
                    payload, content_hash, occurred_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (deployment_id) DO NOTHING
                RETURNING deployment_id
                """,
                (
                    record.deployment_id,
                    record.schema_version,
                    self.owner_id,
                    record.release_manifest_id,
                    record.release_manifest_hash,
                    record.environment,
                    record.action,
                    record.status,
                    record.previous_deployment_id,
                    Jsonb(
                        {}
                        if record.health_evidence is None
                        else record.health_evidence.model_dump(mode="json")
                    ),
                    record.failure_code,
                    Jsonb(record.model_dump(mode="json")),
                    record.content_hash,
                    record.occurred_at,
                ),
            ).fetchone()
            if inserted is None:
                existing = connection.execute(
                    """
                    SELECT content_hash FROM havre.deployments
                    WHERE owner_id=%s AND deployment_id=%s
                    """,
                    (self.owner_id, record.deployment_id),
                ).fetchone()
                if existing is None or existing["content_hash"] != record.content_hash:
                    raise ValueError("deployment identity already binds other evidence")

    def persist_release_approval(self, approval: ReleaseApprovalRecord) -> None:
        if approval.owner_id != self.owner_id:
            raise ValueError("release approval owner mismatch")
        with self.repository.pool.connection() as connection, connection.transaction():
            inserted = connection.execute(
                """
                INSERT INTO havre.release_approval_records (
                    release_approval_id, schema_version, owner_id,
                    release_manifest_id, release_manifest_hash, approval_scope,
                    decision, actor, rationale, decided_at, content_hash
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (release_approval_id) DO NOTHING
                RETURNING release_approval_id
                """,
                (
                    approval.release_approval_id,
                    approval.schema_version,
                    self.owner_id,
                    approval.release_manifest_id,
                    approval.release_manifest_hash,
                    approval.approval_scope,
                    approval.decision,
                    approval.actor,
                    approval.rationale,
                    approval.decided_at,
                    approval.content_hash,
                ),
            ).fetchone()
            if inserted is None:
                existing = connection.execute(
                    """
                    SELECT content_hash FROM havre.release_approval_records
                    WHERE owner_id=%s AND release_approval_id=%s
                    """,
                    (self.owner_id, approval.release_approval_id),
                ).fetchone()
                if existing is None or existing["content_hash"] != approval.content_hash:
                    raise ValueError("release approval identity already binds other evidence")

    def persist_backup_manifest(
        self, manifest: BackupManifest, *, artifact_uri: str
    ) -> None:
        if not artifact_uri.startswith("local://"):
            raise ValueError("backup artifacts must remain local")
        if manifest.owner_id != self.owner_id:
            raise ValueError("backup manifest owner mismatch")
        with self.repository.pool.connection() as connection, connection.transaction():
            inserted = connection.execute(
                """
                INSERT INTO havre.backup_manifests (
                    backup_id, schema_version, owner_id, artifact_uri,
                    artifact_sha256, artifact_size_bytes, source_database_name,
                    migration_head, release_manifest_id, release_manifest_hash,
                    erasure_ledger_sequence, created_at, expires_at,
                    payload, content_hash
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (backup_id) DO NOTHING
                RETURNING backup_id
                """,
                (
                    manifest.backup_id,
                    manifest.schema_version,
                    self.owner_id,
                    artifact_uri,
                    manifest.artifact_sha256,
                    manifest.artifact_size_bytes,
                    manifest.source_database_name,
                    manifest.migration_head,
                    manifest.release_manifest_id,
                    manifest.release_manifest_hash,
                    manifest.erasure_ledger_sequence,
                    manifest.created_at,
                    manifest.expires_at,
                    Jsonb(manifest.model_dump(mode="json")),
                    manifest.content_hash,
                ),
            ).fetchone()
            if inserted is None:
                existing = connection.execute(
                    """
                    SELECT content_hash FROM havre.backup_manifests
                    WHERE owner_id=%s AND backup_id=%s
                    """,
                    (self.owner_id, manifest.backup_id),
                ).fetchone()
                if existing is None or existing["content_hash"] != manifest.content_hash:
                    raise ValueError("backup identity already binds other evidence")

    def persist_restore_replay(self, replay: RestoreErasureReplay) -> None:
        if replay.owner_id != self.owner_id:
            raise ValueError("restore replay owner mismatch")
        with self.repository.pool.connection() as connection, connection.transaction():
            inserted = connection.execute(
                """
                INSERT INTO havre.restore_erasure_replays (
                    replay_id, schema_version, owner_id, backup_id,
                    restored_database_name, ledger_sequence_from,
                    ledger_sequence_through, directives_applied,
                    absence_verified, provenance_violations, payload,
                    content_hash, completed_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (replay_id) DO NOTHING
                RETURNING replay_id
                """,
                (
                    replay.replay_id,
                    replay.schema_version,
                    self.owner_id,
                    replay.backup_id,
                    replay.restored_database_name,
                    replay.ledger_sequence_from,
                    replay.ledger_sequence_through,
                    replay.directives_applied,
                    replay.absence_verified,
                    replay.provenance_violations,
                    Jsonb(replay.model_dump(mode="json")),
                    replay.content_hash,
                    replay.completed_at,
                ),
            ).fetchone()
            if inserted is None:
                existing = connection.execute(
                    """
                    SELECT content_hash FROM havre.restore_erasure_replays
                    WHERE owner_id=%s AND replay_id=%s
                    """,
                    (self.owner_id, replay.replay_id),
                ).fetchone()
                if existing is None or existing["content_hash"] != replay.content_hash:
                    raise ValueError("restore replay identity already binds other evidence")

    def readiness(self) -> dict[str, object]:
        with self.repository.pool.connection() as connection:
            row = connection.execute(
                """
                SELECT
                    (SELECT migration_id FROM havre.schema_migrations
                     ORDER BY migration_id DESC LIMIT 1) AS migration_head,
                    (SELECT count(*) FROM havre.background_jobs
                     WHERE owner_id=%s AND status='failed') AS failed_memory_jobs,
                    (SELECT count(*) FROM havre.proactive_work_items
                     WHERE owner_id=%s AND status='failed') AS failed_proactive_jobs,
                    (SELECT count(*) FROM havre.stage7_jobs
                     WHERE owner_id=%s AND status='failed') AS failed_offline_jobs
                """,
                (self.owner_id, self.owner_id, self.owner_id),
            ).fetchone()
        return {
            "database": "ready",
            "migration_head": row["migration_head"],
            "failed_jobs": {
                "memory": row["failed_memory_jobs"],
                "proactive": row["failed_proactive_jobs"],
                "offline": row["failed_offline_jobs"],
            },
        }

    def require_release_preflight(self, manifest: ReleaseManifest) -> None:
        """Require exact operator persistence and Product Owner approvals."""
        with self.repository.pool.connection() as connection:
            release = connection.execute(
                """
                SELECT content_hash FROM havre.release_manifests
                WHERE owner_id=%s AND release_manifest_id=%s
                """,
                (self.owner_id, manifest.release_manifest_id),
            ).fetchone()
            if release is None or release["content_hash"] != manifest.content_hash:
                raise ValueError("runtime release manifest is not operator-persisted")
            authorization_rows = connection.execute(
                """
                SELECT component, version, artifact_hash, content_hash
                FROM havre.component_promotion_authorizations
                WHERE owner_id=%s AND content_hash = ANY(%s::text[])
                """,
                (
                    self.owner_id,
                    list(manifest.component_promotion_authorization_hashes),
                ),
            ).fetchall()
            if {row["content_hash"] for row in authorization_rows} != set(
                manifest.component_promotion_authorization_hashes
            ):
                raise ValueError("release component authorizations are not durable")
            authorized_components = {
                (row["component"], row["version"], row["artifact_hash"])
                for row in authorization_rows
            }
            for component in manifest.components:
                if (
                    component.component
                    in {"provider", "foundation_model", "adapter", "tokenizer"}
                    and component.lifecycle_status == "approved"
                    and (
                        component.component,
                        component.version,
                        component.artifact_hash,
                    ) not in authorized_components
                ):
                    raise ValueError("approved release component lacks durable authorization")
            if manifest.environment == "production":
                approval_scopes = {
                    row["approval_scope"]
                    for row in connection.execute(
                        """
                        SELECT approval_scope
                        FROM havre.release_approval_records
                        WHERE owner_id=%s AND release_manifest_id=%s
                          AND release_manifest_hash=%s AND decision='approved'
                        """,
                        (
                            self.owner_id,
                            manifest.release_manifest_id,
                            manifest.content_hash,
                        ),
                    ).fetchall()
                }
                if "infrastructure_production_release" not in approval_scopes:
                    raise ValueError("production runtime lacks Product Owner release approval")
                if (
                    manifest.adapter_deployment_authorized
                    and "personalized_adapter_release" not in approval_scopes
                ):
                    raise ValueError("production adapter lacks Product Owner approval")

    def release_activation_status(self, manifest: ReleaseManifest) -> bool:
        with self.repository.pool.connection() as connection:
            latest = connection.execute(
                """
                SELECT release_manifest_id, release_manifest_hash, environment
                FROM havre.deployments
                WHERE owner_id=%s AND environment=%s AND status='applied'
                ORDER BY occurred_at DESC, deployment_id DESC
                LIMIT 1
                """,
                (self.owner_id, manifest.environment),
            ).fetchone()
        return bool(
            latest is not None
            and latest["release_manifest_id"] == manifest.release_manifest_id
            and latest["release_manifest_hash"] == manifest.content_hash
            and latest["environment"] == manifest.environment
        )

    def require_release_activation(self, manifest: ReleaseManifest) -> None:
        self.require_release_preflight(manifest)
        if not self.release_activation_status(manifest):
            raise ValueError("runtime release manifest is not the applied deployment")

    def export_owner_data(
        self,
        destination: Path,
        *,
        erasure_ledger: ErasureLedger | None = None,
    ) -> OwnerExportManifest:
        destination = destination.resolve()
        if destination.exists():
            raise FileExistsError("owner export destination must not already exist")
        destination.mkdir(parents=True, mode=0o700)
        artifacts: list[ExportArtifact] = []
        with self.repository.pool.connection() as connection, connection.transaction():
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            migrations = tuple(
                row["migration_id"]
                for row in connection.execute(
                    "SELECT migration_id FROM havre.schema_migrations ORDER BY migration_id"
                ).fetchall()
            )
            tables = tuple(
                row["table_name"]
                for row in connection.execute(
                    """
                    SELECT DISTINCT table_name
                    FROM information_schema.columns
                    WHERE table_schema='havre' AND column_name='owner_id'
                      AND table_name <> 'context_device_bindings'
                    ORDER BY table_name
                    """
                ).fetchall()
            )
            for table in tables:
                rows = connection.execute(
                    sql.SQL(
                        "SELECT row_to_json(item) AS payload FROM "
                        "(SELECT * FROM havre.{} WHERE owner_id=%s) AS item "
                        "ORDER BY row_to_json(item)::text"
                    ).format(sql.Identifier(table)),
                    (self.owner_id,),
                ).fetchall()
                path = destination / f"tables/{table}.jsonl"
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("w", encoding="utf-8", newline="\n") as handle:
                    for row in rows:
                        handle.write(
                            json.dumps(
                                row["payload"],
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                                default=_json_default,
                            )
                            + "\n"
                        )
                artifacts.append(
                    ExportArtifact(
                        relative_path=path.relative_to(destination).as_posix(),
                        media_type="application/x-ndjson",
                        sha256=_file_sha256(path),
                        size_bytes=path.stat().st_size,
                        row_count=len(rows),
                    )
                )
                path.chmod(0o600)
            span_rows = connection.execute(
                """
                SELECT row_to_json(item) AS payload
                FROM (
                    SELECT span.* FROM havre.spans AS span
                    JOIN havre.traces AS trace ON trace.trace_id=span.trace_id
                    WHERE trace.owner_id=%s
                ) AS item
                ORDER BY row_to_json(item)::text
                """,
                (self.owner_id,),
            ).fetchall()
            span_path = destination / "tables/spans.jsonl"
            with span_path.open("w", encoding="utf-8", newline="\n") as handle:
                for row in span_rows:
                    handle.write(
                        json.dumps(
                            row["payload"],
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                            default=_json_default,
                        )
                        + "\n"
                    )
            artifacts.append(
                ExportArtifact(
                    relative_path="tables/spans.jsonl",
                    media_type="application/x-ndjson",
                    sha256=_file_sha256(span_path),
                    size_bytes=span_path.stat().st_size,
                    row_count=len(span_rows),
                )
            )
            span_path.chmod(0o600)
        migration_path = destination / "schema-migrations.json"
        migration_path.write_text(
            json.dumps(migrations, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        migration_path.chmod(0o600)
        artifacts.append(
            ExportArtifact(
                relative_path=migration_path.name,
                media_type="application/json",
                sha256=_file_sha256(migration_path),
                size_bytes=migration_path.stat().st_size,
                row_count=len(migrations),
            )
        )
        if erasure_ledger is not None:
            directives = tuple(
                item for item in erasure_ledger.verify() if item.owner_id == self.owner_id
            )
            ledger_path = destination / "operations/erasure-directives.jsonl"
            ledger_path.parent.mkdir(parents=True, exist_ok=True)
            with ledger_path.open("w", encoding="utf-8", newline="\n") as handle:
                for directive in directives:
                    handle.write(canonical_json(directive) + "\n")
            artifacts.append(
                ExportArtifact(
                    relative_path=ledger_path.relative_to(destination).as_posix(),
                    media_type="application/x-ndjson",
                    sha256=_file_sha256(ledger_path),
                    size_bytes=ledger_path.stat().st_size,
                    row_count=len(directives),
                )
            )
            ledger_path.chmod(0o600)
        manifest = OwnerExportManifest(
            owner_id=self.owner_id,
            database_schema_migrations=migrations,
            artifacts=tuple(artifacts),
        )
        manifest_path = destination / "manifest.json"
        manifest_path.write_text(
            manifest.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        manifest_path.chmod(0o600)
        return manifest

    @staticmethod
    def verify_owner_export(destination: Path) -> OwnerExportManifest:
        destination = destination.resolve()
        if any(path.is_symlink() for path in destination.rglob("*")):
            raise ValueError("owner export cannot contain symbolic links")
        manifest = OwnerExportManifest.model_validate_json(
            (destination / "manifest.json").read_text(encoding="utf-8")
        )
        expected_paths = {
            "manifest.json",
            *(artifact.relative_path for artifact in manifest.artifacts),
        }
        actual_paths = {
            path.relative_to(destination).as_posix()
            for path in destination.rglob("*")
            if path.is_file()
        }
        if actual_paths != expected_paths:
            raise ValueError("owner export file membership does not match its manifest")
        for artifact in manifest.artifacts:
            path = (destination / artifact.relative_path).resolve()
            try:
                path.relative_to(destination)
            except ValueError as error:
                raise ValueError("owner export artifact escapes its root") from error
            if not path.is_file():
                raise FileNotFoundError(f"owner export artifact is missing: {path}")
            if path.stat().st_size != artifact.size_bytes:
                raise ValueError("owner export artifact size mismatch")
            if _file_sha256(path) != artifact.sha256:
                raise ValueError("owner export artifact hash mismatch")
        return manifest

    def erase_source_event(
        self,
        *,
        source_event_id: UUID,
        ledger: ErasureLedger,
        _coordination_locked: bool = False,
    ) -> dict[str, Any]:
        with self._erasure_scope() as erasure_repository:
            with ExitStack() as coordination:
                if not _coordination_locked:
                    coordination.enter_context(local_erasure_lock(ledger.path))
                    lock_connection = coordination.enter_context(
                        psycopg.connect(
                            erasure_repository.pool.conninfo,
                            autocommit=True,
                        )
                    )
                    coordination.enter_context(backup_erasure_lock(lock_connection))
                with erasure_repository.pool.connection() as connection:
                    source = connection.execute(
                        """
                        SELECT event_type FROM havre.events
                        WHERE owner_id=%s AND event_id=%s
                        """,
                        (self.owner_id, source_event_id),
                    ).fetchone()
                source_exists = source is not None
                if source is not None and source["event_type"] in {
                    "CONTEXT_SOURCE_STATE_REVISED",
                    "CONTEXT_CAPABILITY_STATE_REVISED",
                    "CONTEXT_CONSENT_REVISED",
                }:
                    raise ValueError(
                        "context authority events require source disablement and "
                        "a separately governed source-erasure closure"
                    )
                directive = ledger.append(
                    owner_id=self.owner_id,
                    source_event_id=source_event_id,
                )
                counts = (
                    erasure_repository.erase_source_event_derivatives(
                        owner_id=self.owner_id,
                        source_event_id=source_event_id,
                    )
                    if source_exists
                    else {}
                )
                with (
                    erasure_repository.pool.connection() as connection,
                    connection.transaction(),
                ):
                    connection.execute("SET LOCAL havre.privileged_erasure = 'on'")
                    source = connection.execute(
                        """
                        SELECT request_id FROM havre.events
                        WHERE owner_id=%s AND event_id=%s
                        FOR UPDATE
                        """,
                        (self.owner_id, source_event_id),
                    ).fetchone()
                    raw_deleted = 0
                    if source is not None:
                        connection.execute(
                            """
                            DELETE FROM havre.offline_source_revocations
                            WHERE owner_id=%s AND source_event_id=%s
                            """,
                            (self.owner_id, source_event_id),
                        )
                        connection.execute(
                            """
                            UPDATE havre.interaction_requests SET user_event_id=NULL
                            WHERE owner_id=%s AND request_id=%s AND user_event_id=%s
                            """,
                            (self.owner_id, source["request_id"], source_event_id),
                        )
                        raw_deleted = connection.execute(
                            """
                            DELETE FROM havre.events
                            WHERE owner_id=%s AND event_id=%s
                            RETURNING 1
                            """,
                            (self.owner_id, source_event_id),
                        ).rowcount
                    remaining = connection.execute(
                        """
                        SELECT
                            EXISTS (SELECT 1 FROM havre.events
                                    WHERE owner_id=%s AND event_id=%s)
                            OR EXISTS (SELECT 1 FROM havre.provenance_edges
                                       WHERE owner_id=%s AND source_kind='event'
                                         AND source_id=%s) AS present
                        """,
                        (
                            self.owner_id,
                            source_event_id,
                            self.owner_id,
                            source_event_id,
                        ),
                    ).fetchone()["present"]
                    if remaining:
                        raise RuntimeError("source erasure absence verification failed")
                ledger.mark_completed(sequence=directive.sequence)
        return {
            "directive_sequence": directive.sequence,
            "directive_hash": directive.content_hash,
            "raw_source_events": raw_deleted,
            "derived": counts,
            "absence_verified": True,
        }

    def erase_context_source(
        self,
        *,
        source_instance_id: UUID,
        ledger: ErasureLedger,
        _coordination_locked: bool = False,
    ) -> dict[str, Any]:
        """Erase one complete external Context Source and retain only a tombstone."""

        with self._erasure_scope() as erasure_repository:
            with ExitStack() as coordination:
                if not _coordination_locked:
                    coordination.enter_context(local_erasure_lock(ledger.path))
                    lock_connection = coordination.enter_context(
                        psycopg.connect(erasure_repository.pool.conninfo, autocommit=True)
                    )
                    coordination.enter_context(backup_erasure_lock(lock_connection))
                with erasure_repository.pool.connection() as connection:
                    source = connection.execute(
                        """
                        SELECT registration_event_id FROM havre.context_sources
                        WHERE owner_id=%s AND source_instance_id=%s
                        """,
                        (self.owner_id, source_instance_id),
                    ).fetchone()
                    if source is None:
                        tombstone = connection.execute(
                            """
                            SELECT * FROM havre.context_source_erasure_tombstones
                            WHERE owner_id=%s AND source_instance_id=%s
                            """,
                            (self.owner_id, source_instance_id),
                        ).fetchone()
                        if tombstone is None:
                            raise ValueError("unknown context source")
                        return {
                            "directive_sequence": tombstone["directive_sequence"],
                            "directive_hash": tombstone["directive_hash"],
                            "source_instance_id": str(source_instance_id),
                            "absence_verified": True,
                            "already_erased": True,
                        }
                return self._erase_context_source_by_registration_event(
                    registration_event_id=source["registration_event_id"],
                    ledger=ledger,
                    _coordination_locked=True,
                )

    def _erase_context_source_by_registration_event(
        self,
        *,
        registration_event_id: UUID,
        ledger: ErasureLedger,
        _coordination_locked: bool,
    ) -> dict[str, Any]:
        with self._erasure_scope() as erasure_repository:
            directive = ledger.append(
                owner_id=self.owner_id,
                source_event_id=registration_event_id,
                scope="context_source_and_derived",
            )
            with erasure_repository.pool.connection() as connection:
                source = connection.execute(
                    """
                    SELECT source_instance_id FROM havre.context_sources
                    WHERE owner_id=%s AND registration_event_id=%s
                    """,
                    (self.owner_id, registration_event_id),
                ).fetchone()
                if source is None:
                    existing = connection.execute(
                        """
                        SELECT * FROM havre.context_source_erasure_tombstones
                        WHERE owner_id=%s AND registration_event_id=%s
                        """,
                        (self.owner_id, registration_event_id),
                    ).fetchone()
                    if existing is not None:
                        ledger.mark_completed(sequence=directive.sequence)
                        return {
                            "directive_sequence": directive.sequence,
                            "directive_hash": directive.content_hash,
                            "source_instance_id": str(existing["source_instance_id"]),
                            "absence_verified": True,
                            "already_erased": True,
                        }
                    # A restore may predate the source itself. Absence is already closed.
                    ledger.mark_completed(sequence=directive.sequence)
                    return {
                        "directive_sequence": directive.sequence,
                        "directive_hash": directive.content_hash,
                        "source_instance_id": None,
                        "absence_verified": True,
                        "already_erased": True,
                    }
                source_instance_id = source["source_instance_id"]
                observation_events = [
                    row["event_id"]
                    for row in connection.execute(
                        """
                        SELECT event_id FROM havre.life_context_observations
                        WHERE owner_id=%s AND source_instance_id=%s
                        ORDER BY event_id
                        """,
                        (self.owner_id, source_instance_id),
                    ).fetchall()
                ]
            derived_counts: dict[str, int] = {}
            for event_id in observation_events:
                counts = erasure_repository.erase_source_event_derivatives(
                    owner_id=self.owner_id, source_event_id=event_id
                )
                for name, count in counts.items():
                    derived_counts[name] = derived_counts.get(name, 0) + int(count)

            erased_at = datetime.now(UTC)
            tombstone = ContextSourceErasureTombstone(
                owner_id=self.owner_id,
                source_instance_id=source_instance_id,
                registration_event_id=registration_event_id,
                erased_at=erased_at,
                directive_sequence=directive.sequence,
                directive_hash=directive.content_hash,
            )
            with (
                erasure_repository.pool.connection() as connection,
                connection.transaction(),
            ):
                connection.execute("SET LOCAL havre.privileged_erasure = 'on'")
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                    (f"context-source:{self.owner_id}:{source_instance_id}",),
                )
                authority_event_ids = [
                    row["event_id"]
                    for row in connection.execute(
                        """
                        SELECT event_id FROM (
                            SELECT registration_event_id AS event_id
                            FROM havre.context_sources
                            WHERE owner_id=%s AND source_instance_id=%s
                            UNION
                            SELECT decision_event_id FROM havre.context_source_state_revisions
                            WHERE owner_id=%s AND source_instance_id=%s
                            UNION
                            SELECT registration_event_id FROM havre.context_source_capabilities
                            WHERE owner_id=%s AND source_instance_id=%s
                            UNION
                            SELECT state.decision_event_id
                            FROM havre.context_capability_state_revisions state
                            JOIN havre.context_source_capabilities capability
                              ON capability.owner_id=state.owner_id
                             AND capability.capability_revision_id=state.capability_revision_id
                            WHERE capability.owner_id=%s AND capability.source_instance_id=%s
                            UNION
                            SELECT decision_event_id FROM havre.context_consent_scope_revisions
                            WHERE owner_id=%s AND source_instance_id=%s
                            UNION
                            SELECT event_id FROM havre.life_context_observations
                            WHERE owner_id=%s AND source_instance_id=%s
                        ) governed_events
                        """,
                        (
                            self.owner_id,source_instance_id,
                            self.owner_id,source_instance_id,
                            self.owner_id,source_instance_id,
                            self.owner_id,source_instance_id,
                            self.owner_id,source_instance_id,
                            self.owner_id,source_instance_id,
                        ),
                    ).fetchall()
                ]
                event_ids = list(dict.fromkeys([
                    *observation_events,
                    *authority_event_ids,
                ]))
                connection.execute(
                    """
                    DELETE FROM havre.context_retention_expiry_receipts
                    WHERE owner_id=%s AND source_event_id=ANY(%s::uuid[])
                    """,
                    (self.owner_id, event_ids),
                )
                connection.execute(
                    """
                    DELETE FROM havre.context_retention_expiry_intents
                    WHERE owner_id=%s AND source_event_id=ANY(%s::uuid[])
                    """,
                    (self.owner_id, event_ids),
                )
                for table in (
                    "context_source_health_records",
                    "life_context_observations",
                    "context_restore_quarantines",
                    "context_consent_scope_revisions",
                ):
                    connection.execute(
                        sql.SQL("DELETE FROM havre.{} WHERE owner_id=%s AND source_instance_id=%s")
                        .format(sql.Identifier(table)),
                        (self.owner_id, source_instance_id),
                    )
                connection.execute(
                    """
                    DELETE FROM havre.context_capability_state_revisions state
                    USING havre.context_source_capabilities capability
                    WHERE state.owner_id=%s AND capability.owner_id=state.owner_id
                      AND capability.capability_revision_id=state.capability_revision_id
                      AND capability.source_instance_id=%s
                    """,
                    (self.owner_id, source_instance_id),
                )
                for table in (
                    "context_source_capabilities",
                    "context_source_state_revisions",
                    "context_device_bindings",
                ):
                    connection.execute(
                        sql.SQL("DELETE FROM havre.{} WHERE owner_id=%s AND source_instance_id=%s")
                        .format(sql.Identifier(table)),
                        (self.owner_id, source_instance_id),
                    )
                connection.execute(
                    "DELETE FROM havre.context_sources WHERE owner_id=%s AND source_instance_id=%s",
                    (self.owner_id, source_instance_id),
                )
                connection.execute(
                    """
                    DELETE FROM havre.offline_source_revocations
                    WHERE owner_id=%s AND source_event_id=ANY(%s::uuid[])
                    """,
                    (self.owner_id, event_ids),
                )
                connection.execute(
                    """
                    UPDATE havre.interaction_requests request
                    SET user_event_id=NULL, assistant_event_id=NULL
                    WHERE owner_id=%s AND (
                        user_event_id=ANY(%s::uuid[]) OR assistant_event_id=ANY(%s::uuid[])
                    )
                    """,
                    (self.owner_id, event_ids, event_ids),
                )
                connection.execute(
                    "DELETE FROM havre.events WHERE owner_id=%s AND event_id=ANY(%s::uuid[])",
                    (self.owner_id, event_ids),
                )
                connection.execute(
                    """
                    INSERT INTO havre.context_source_erasure_tombstones (
                        tombstone_id,schema_version,owner_id,source_instance_id,
                        registration_event_id,erased_at,directive_sequence,
                        directive_hash,absence_verified,content_hash
                    ) VALUES (%s,1,%s,%s,%s,%s,%s,%s,true,%s)
                    """,
                    (
                        tombstone.tombstone_id,self.owner_id,source_instance_id,
                        registration_event_id,erased_at,directive.sequence,
                        directive.content_hash,tombstone.content_hash,
                    ),
                )
                remaining = connection.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM havre.context_sources
                        WHERE owner_id=%s AND source_instance_id=%s
                    ) OR EXISTS (
                        SELECT 1 FROM havre.life_context_observations
                        WHERE owner_id=%s AND source_instance_id=%s
                    ) OR EXISTS (
                        SELECT 1 FROM havre.context_device_bindings
                        WHERE owner_id=%s AND source_instance_id=%s
                    ) AS present
                    """,
                    (
                        self.owner_id,source_instance_id,
                        self.owner_id,source_instance_id,
                        self.owner_id,source_instance_id,
                    ),
                ).fetchone()["present"]
                if remaining:
                    raise RuntimeError("context source erasure absence verification failed")
            ledger.mark_completed(sequence=directive.sequence)
            return {
                "directive_sequence": directive.sequence,
                "directive_hash": directive.content_hash,
                "source_instance_id": str(source_instance_id),
                "derived": derived_counts,
                "absence_verified": True,
                "already_erased": False,
            }

    def expire_context_retention(
        self, *, ledger: ErasureLedger
    ) -> dict[str, object]:
        """Execute pre-approved context retention through the erasure ledger.

        The durable intent is written before cross-store deletion so a crash can
        resume safely. The ordinary app role cannot create intents or receipts.
        """
        with self._erasure_scope() as erasure_repository:
            with erasure_repository.pool.connection() as connection, connection.transaction():
                instant = connection.execute(
                    "SELECT statement_timestamp() AS evaluated_at"
                ).fetchone()["evaluated_at"]
                rows = connection.execute(
                    """
                    SELECT observation_id, event_id, retention_policy_version,
                           retention_expires_at
                    FROM havre.life_context_observations
                    WHERE owner_id=%s AND retention_expires_at<=statement_timestamp()
                    ORDER BY retention_expires_at, observation_id
                    """,
                    (self.owner_id,),
                ).fetchall()
                for row in rows:
                    intent = ContextRetentionExpiryIntent(
                        owner_id=self.owner_id,
                        source_event_id=row["event_id"],
                        observation_id=row["observation_id"],
                        retention_policy_version=row["retention_policy_version"],
                        retention_expires_at=row["retention_expires_at"],
                        planned_at=datetime.now(UTC),
                    )
                    connection.execute(
                        """
                        INSERT INTO havre.context_retention_expiry_intents (
                            expiry_intent_id, schema_version, owner_id,
                            source_event_id, observation_id,
                            retention_policy_version, retention_expires_at,
                            planned_at, content_hash
                        ) VALUES (%s,1,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (owner_id, source_event_id) DO NOTHING
                        """,
                        (
                            intent.expiry_intent_id, self.owner_id, row["event_id"],
                            row["observation_id"], row["retention_policy_version"],
                            row["retention_expires_at"], intent.planned_at,
                            intent.content_hash,
                        ),
                    )
                pending = connection.execute(
                    """
                    SELECT intent.*
                    FROM havre.context_retention_expiry_intents intent
                    LEFT JOIN havre.context_retention_expiry_receipts receipt
                      ON receipt.expiry_intent_id=intent.expiry_intent_id
                    WHERE intent.owner_id=%s AND receipt.expiry_receipt_id IS NULL
                      AND intent.retention_expires_at<=statement_timestamp()
                    ORDER BY intent.retention_expires_at, intent.expiry_intent_id
                    """,
                    (self.owner_id,),
                ).fetchall()
        receipts: list[dict[str, object]] = []
        for intent in pending:
            erased = self.erase_source_event(
                source_event_id=intent["source_event_id"], ledger=ledger
            )
            erased_at = datetime.now(UTC)
            receipt = ContextRetentionExpiryReceipt(
                expiry_intent_id=intent["expiry_intent_id"],
                owner_id=self.owner_id,
                source_event_id=intent["source_event_id"],
                observation_id=intent["observation_id"],
                retention_policy_version=intent["retention_policy_version"],
                retention_expires_at=intent["retention_expires_at"],
                erased_at=erased_at,
                directive_sequence=erased["directive_sequence"],
                directive_hash=erased["directive_hash"],
            )
            with self._erasure_scope() as erasure_repository:
                with erasure_repository.pool.connection() as connection, connection.transaction():
                    connection.execute(
                        """
                        INSERT INTO havre.context_retention_expiry_receipts (
                            expiry_receipt_id, expiry_intent_id, schema_version,
                            owner_id, source_event_id, observation_id,
                            retention_policy_version, retention_expires_at,
                            erased_at, directive_sequence, directive_hash,
                            absence_verified, content_hash
                        ) VALUES (%s,%s,1,%s,%s,%s,%s,%s,%s,%s,%s,true,%s)
                        ON CONFLICT (expiry_intent_id) DO NOTHING
                        """,
                        (
                            receipt.expiry_receipt_id, intent["expiry_intent_id"], self.owner_id,
                            intent["source_event_id"], intent["observation_id"],
                            intent["retention_policy_version"],
                            intent["retention_expires_at"], erased_at,
                            erased["directive_sequence"], erased["directive_hash"],
                            receipt.content_hash,
                        ),
                    )
            receipts.append({
                "source_event_id": str(intent["source_event_id"]),
                "directive_sequence": erased["directive_sequence"],
                "directive_hash": erased["directive_hash"],
                "absence_verified": erased["absence_verified"],
            })
        return {
            "evaluated_at": instant.isoformat(),
            "expired_count": len(receipts),
            "receipts": receipts,
            "absence_verified": all(item["absence_verified"] for item in receipts),
        }

    def replay_erasure_directives(
        self,
        *,
        ledger: ErasureLedger,
        after_sequence: int,
        restore_id: str,
        _coordination_locked: bool = False,
    ) -> dict[str, object]:
        directives = ledger.directives_after(after_sequence)
        applied = 0
        for directive in directives:
            if directive.owner_id != self.owner_id:
                continue
            if directive.scope == "context_source_and_derived":
                self._erase_context_source_by_registration_event(
                    registration_event_id=directive.source_event_id,
                    ledger=ledger,
                    _coordination_locked=True,
                )
            else:
                self.erase_source_event(
                    source_event_id=directive.source_event_id,
                    ledger=ledger,
                    _coordination_locked=_coordination_locked,
                )
            ledger.mark_applied(restore_id=restore_id, sequence=directive.sequence)
            applied += 1
        with self._erasure_scope() as erasure_repository:
            with erasure_repository.pool.connection() as connection, connection.transaction():
                quarantined = 0
                stage12_present = connection.execute(
                    "SELECT to_regclass('havre.context_sources') IS NOT NULL AS present"
                ).fetchone()["present"]
                if stage12_present:
                    sources = connection.execute(
                        """
                        SELECT source_instance_id FROM havre.context_sources
                        WHERE owner_id=%s ORDER BY source_instance_id
                        """,
                        (self.owner_id,),
                    ).fetchall()
                    for row in sources:
                        quarantine = ContextRestoreQuarantine(
                            owner_id=self.owner_id,
                            source_instance_id=row["source_instance_id"],
                            restore_id=restore_id,
                            quarantined_at=datetime.now(UTC),
                        )
                        quarantined += connection.execute(
                            """
                            INSERT INTO havre.context_restore_quarantines (
                                quarantine_id,schema_version,owner_id,source_instance_id,
                                restore_id,reason,quarantined_at,content_hash
                            ) VALUES (%s,1,%s,%s,%s,%s,%s,%s)
                            ON CONFLICT (owner_id,source_instance_id,restore_id) DO NOTHING
                            """,
                            (
                                quarantine.quarantine_id,self.owner_id,
                                quarantine.source_instance_id,quarantine.restore_id,
                                quarantine.reason,quarantine.quarantined_at,
                                quarantine.content_hash,
                            ),
                        ).rowcount
            violations = erasure_repository.audit_provenance_integrity()
        if violations:
            raise RuntimeError("restore erasure replay left provenance violations")
        return {
            "restore_id": restore_id,
            "ledger_sequence_from": after_sequence,
            "ledger_sequence_through": ledger.current_sequence(),
            "directives_applied": applied,
            "context_sources_quarantined": quarantined,
            "absence_verified": True,
            "provenance_violations": 0,
        }
