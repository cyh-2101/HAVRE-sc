"""Run the Stage 10 backup, restore, and post-backup erasure replay drill."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from psycopg.conninfo import conninfo_to_dict

from companion.events import EventEnvelope, EventType, TextContentPart, UserMessagePayload
from companion.hashing import content_hash
from companion.identity import IdentityLoader
from companion.ids import uuid7
from companion.operations import (
    ComponentReference,
    DeploymentHealthEvidence,
    DeploymentRecord,
    ReleaseManifest,
)
from companion.operations.backup import BackupService
from companion.operations.ledger import ErasureLedger
from companion.persistence import PostgresRepository, Stage10PostgresStore, apply_migrations
from companion.policy import DataPolicy, PrivacyClass
from companion.tracing import TraceContext


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _database_name(url: str) -> str:
    value = str(conninfo_to_dict(url).get("dbname", ""))
    if not value.startswith("havre_stage10_"):
        raise ValueError("drill databases must use the havre_stage10_ prefix")
    return value


def _assert_target_empty(url: str) -> None:
    with psycopg.connect(url) as connection:
        occupied = connection.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables WHERE table_schema='havre'
            )
            """
        ).fetchone()[0]
    if occupied:
        raise ValueError("restore drill target database must be empty")


def _insert_source_event(repository: PostgresRepository, owner_id: UUID, marker: str):
    trace = TraceContext.from_traceparent(None)
    request_id = uuid7()
    session_id = uuid7()
    event = EventEnvelope(
        event_type=EventType.USER_MESSAGE,
        owner_id=owner_id,
        session_id=session_id,
        request_id=request_id,
        trace_id=trace.trace_id,
        data_policy=DataPolicy.owner_default(
            PrivacyClass.PRIVATE,
            memory_eligible=False,
        ),
        payload=UserMessagePayload(
            content_parts=(TextContentPart(text=marker),),
            channel="cli",
        ),
    )
    with repository.pool.connection() as connection, connection.transaction():
        connection.execute(
            "INSERT INTO havre.sessions (session_id, owner_id, channel) VALUES (%s,%s,'cli')",
            (session_id, owner_id),
        )
        connection.execute(
            """
            INSERT INTO havre.traces (
                trace_id, owner_id, root_request_id, trace_flags, started_at
            ) VALUES (%s,%s,%s,'01',%s)
            """,
            (trace.trace_id, owner_id, request_id, datetime.now(UTC)),
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
                owner_id,
                session_id,
                trace.trace_id,
                f"stage10-restore-{request_id}",
                content_hash({"marker": marker}),
            ),
        )
        PostgresRepository._insert_event(connection, event)
        connection.execute(
            """
            UPDATE havre.interaction_requests
            SET status='completed', user_event_id=%s,
                completed_at=statement_timestamp()
            WHERE owner_id=%s AND request_id=%s
            """,
            (event.event_id, owner_id, request_id),
        )
    return event.event_id


def run(
    *,
    source_url: str,
    target_url: str,
    output: Path,
    pg_dump: Path,
    pg_restore: Path,
) -> dict[str, object]:
    source_name = _database_name(source_url)
    target_name = _database_name(target_url)
    if source_name == target_name:
        raise ValueError("source and restore target must be different databases")
    _assert_target_empty(target_url)
    apply_migrations(source_url, PROJECT_ROOT / "db" / "migrations")
    owner_id = uuid4()
    repository = PostgresRepository(source_url)
    repository.open()
    repository.bootstrap_owner_and_identity(
        owner_id=owner_id,
        identity=IdentityLoader(PROJECT_ROOT / "identity").load(),
    )
    store = Stage10PostgresStore(
        repository=repository,
        owner_id=owner_id,
        erasure_repository=repository,
    )
    marker = f"PRIVATE-RESTORE-REPLAY-{uuid4()}"
    source_event_id = _insert_source_event(repository, owner_id, marker)
    release = ReleaseManifest(
        release_id=f"stage10-backup-drill-{uuid4()}",
        environment="development",
        release_scope="infrastructure_only",
        source_revision="a" * 40,
        migration_head="0034_stage10_backup_fk_index.sql",
        components=(
            ComponentReference(
                component="companion_core",
                version="stage10-backup-drill",
                artifact_hash="sha256:" + "a" * 64,
                lifecycle_status="approved",
            ),
        ),
        constitution_version_id="constitution-v1",
        identity_version_id="identity-v1",
        values_version_id="values-v1",
    )
    store.persist_release_manifest(release)
    store.record_deployment(
        DeploymentRecord(
            owner_id=owner_id,
            release_manifest_id=release.release_manifest_id,
            release_manifest_hash=release.content_hash,
            environment=release.environment,
            action="deploy",
            status="applied",
            health_evidence=DeploymentHealthEvidence(
                release_manifest_hash=release.content_hash,
                environment=release.environment,
                source_revision=release.source_revision,
                ready=True,
                checks=("database_readiness", "provider_health"),
            ),
        )
    )
    store.require_release_activation(release)
    ledger = ErasureLedger(output.resolve().parent / "erasure-ledger.sqlite3")
    service = BackupService(pg_dump=pg_dump, pg_restore=pg_restore, ledger=ledger)
    try:
        artifact, manifest_path, manifest = service.create_backup(
            database_url=source_url,
            destination=output,
            release=release,
            owner_id=owner_id,
            expires_after=timedelta(days=7),
        )
        store.persist_backup_manifest(
            manifest,
            artifact_uri=f"local://backups/{artifact.name}",
        )
        erased = store.erase_source_event(source_event_id=source_event_id, ledger=ledger)
        restore_id = uuid4()

        def store_factory(url: str) -> Stage10PostgresStore:
            restored_repository = PostgresRepository(url)
            restored_repository.open()
            return Stage10PostgresStore(
                repository=restored_repository,
                owner_id=owner_id,
                erasure_repository=restored_repository,
            )

        restored = service.restore_verified_backup(
            artifact=artifact,
            manifest_path=manifest_path,
            target_database_url=target_url,
            restore_id=restore_id,
            store_factory=store_factory,
        )
    finally:
        repository.close()
    with psycopg.connect(target_url) as connection:
        source_present = connection.execute(
            "SELECT EXISTS (SELECT 1 FROM havre.events WHERE owner_id=%s AND event_id=%s)",
            (owner_id, source_event_id),
        ).fetchone()[0]
        marker_present = connection.execute(
            "SELECT EXISTS (SELECT 1 FROM havre.events WHERE owner_id=%s AND payload::text LIKE %s)",
            (owner_id, f"%{marker}%"),
        ).fetchone()[0]
        replay = connection.execute(
            """
            SELECT directives_applied, absence_verified, provenance_violations
            FROM havre.restore_erasure_replays
            WHERE owner_id=%s AND replay_id=%s
            """,
            (owner_id, restore_id),
        ).fetchone()
    if source_present or marker_present or replay != (1, True, 0):
        raise RuntimeError("restored-backup erasure replay verification failed")
    return {
        "source_database": source_name,
        "restored_database": target_name,
        "backup_manifest_hash": manifest.content_hash,
        "backup_artifact_hash": manifest.artifact_sha256,
        "backup_watermark": manifest.erasure_ledger_sequence,
        "post_backup_erasure": erased,
        "restore": restored,
        "restored_source_absent": True,
        "restored_private_marker_absent": True,
        "restore_replay_persisted": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-url-file", type=Path, required=True)
    parser.add_argument("--target-url-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pg-dump", type=Path, required=True)
    parser.add_argument("--pg-restore", type=Path, required=True)
    args = parser.parse_args()
    source_url = args.source_url_file.read_text(encoding="utf-8").strip()
    target_url = args.target_url_file.read_text(encoding="utf-8").strip()
    if not source_url or not target_url:
        raise ValueError("database URL secret files must not be empty")
    print(
        json.dumps(
            run(
                source_url=source_url,
                target_url=target_url,
                output=args.output,
                pg_dump=args.pg_dump,
                pg_restore=args.pg_restore,
            ),
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
