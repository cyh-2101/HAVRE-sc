"""Checksum-bound PostgreSQL backup and restore primitives for Stage 10."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
from psycopg.conninfo import conninfo_to_dict

from companion.operations.ledger import ErasureLedger
from companion.operations.coordination import backup_erasure_lock, local_erasure_lock
from companion.operations.models import (
    BackupManifest,
    ReleaseManifest,
    RestoreErasureReplay,
)


_DATABASE_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,62}$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _postgres_process(
    *,
    executable: Path,
    database_url: str,
    arguments: list[str],
    append_database: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    connection = conninfo_to_dict(database_url)
    database = connection.get("dbname")
    if not database or not _DATABASE_NAME.fullmatch(database):
        raise ValueError("database URL must name one exact database")
    command = [str(executable)]
    for option, key in (("--host", "host"), ("--port", "port"), ("--username", "user")):
        if connection.get(key):
            command.extend((option, connection[key]))
    command.extend(arguments)
    if append_database:
        command.append(database)
    environment = os.environ.copy()
    if connection.get("password"):
        environment["PGPASSWORD"] = connection["password"]
    return subprocess.run(
        command,
        env=environment,
        capture_output=True,
        timeout=600,
        check=False,
        creationflags=(
            subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        ),
    )


def _migration_head(database_url: str) -> str:
    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            """
            SELECT migration_id FROM havre.schema_migrations
            ORDER BY migration_id DESC LIMIT 1
            """
        ).fetchone()
    if row is None:
        raise ValueError("database has no HAVRE migration head")
    return str(row[0])


def require_single_owner_database(database_url: str, owner_id: UUID) -> None:
    with psycopg.connect(database_url) as connection:
        owners = tuple(
            row[0]
            for row in connection.execute(
                "SELECT owner_id FROM havre.owners ORDER BY owner_id"
            ).fetchall()
        )
    if owners != (owner_id,):
        raise ValueError(
            "whole-database backup requires exactly the configured single owner"
        )


class BackupService:
    def __init__(
        self,
        *,
        pg_dump: Path,
        pg_restore: Path,
        ledger: ErasureLedger,
    ) -> None:
        self.pg_dump = pg_dump.resolve()
        self.pg_restore = pg_restore.resolve()
        self.ledger = ledger
        if not self.pg_dump.is_file() or not self.pg_restore.is_file():
            raise FileNotFoundError("pg_dump and pg_restore must be exact executable paths")

    def create_backup(
        self,
        *,
        database_url: str,
        destination: Path,
        release: ReleaseManifest,
        owner_id: UUID,
        expires_after: timedelta,
    ) -> tuple[Path, Path, BackupManifest]:
        if expires_after <= timedelta(0):
            raise ValueError("backup retention must be positive")
        destination = destination.resolve()
        destination.mkdir(parents=True, exist_ok=True)
        created_at = datetime.now(UTC)
        artifact = destination / f"havre-{created_at:%Y%m%dT%H%M%SZ}.dump"
        manifest_path = artifact.with_suffix(".manifest.json")
        if artifact.exists() or manifest_path.exists():
            raise FileExistsError("backup output already exists")
        with local_erasure_lock(self.ledger.path):
            with psycopg.connect(database_url, autocommit=True) as lock_connection:
                with backup_erasure_lock(lock_connection):
                    owners = tuple(
                        row[0]
                        for row in lock_connection.execute(
                            "SELECT owner_id FROM havre.owners ORDER BY owner_id"
                        ).fetchall()
                    )
                    if owners != (owner_id,):
                        raise ValueError(
                            "whole-database backup requires exactly the configured single owner"
                        )
                    ledger_sequence = self.ledger.completed_sequence()
                    completed = _postgres_process(
                        executable=self.pg_dump,
                        database_url=database_url,
                        arguments=(
                            [
                                "--format=custom",
                                "--compress=9",
                                "--no-owner",
                                "--file",
                                str(artifact),
                            ]
                        ),
                    )
        if completed.returncode != 0 or not artifact.is_file():
            artifact.unlink(missing_ok=True)
            raise RuntimeError(
                "pg_dump failed: "
                + completed.stderr.decode("utf-8", errors="replace")[-2000:]
            )
        artifact.chmod(0o600)
        database_name = conninfo_to_dict(database_url)["dbname"]
        manifest = BackupManifest(
            owner_id=owner_id,
            artifact_name=artifact.name,
            artifact_sha256=_sha256(artifact),
            artifact_size_bytes=artifact.stat().st_size,
            source_database_name=database_name,
            migration_head=_migration_head(database_url),
            release_manifest_id=release.release_manifest_id,
            release_manifest_hash=release.content_hash,
            erasure_ledger_sequence=ledger_sequence,
            created_at=created_at,
            expires_at=created_at + expires_after,
        )
        manifest_path.write_text(
            manifest.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        manifest_path.chmod(0o600)
        return artifact, manifest_path, manifest

    def verify_backup(
        self, *, artifact: Path, manifest_path: Path
    ) -> BackupManifest:
        artifact = artifact.resolve()
        manifest_path = manifest_path.resolve()
        manifest = BackupManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
        if artifact.name != manifest.artifact_name:
            raise ValueError("backup artifact name does not match manifest")
        if artifact.stat().st_size != manifest.artifact_size_bytes:
            raise ValueError("backup artifact size mismatch")
        if _sha256(artifact) != manifest.artifact_sha256:
            raise ValueError("backup artifact hash mismatch")
        return manifest

    def prune_expired_backups(
        self,
        *,
        root: Path,
        confirmed: bool,
        now: datetime | None = None,
    ) -> tuple[dict[str, object], ...]:
        if not confirmed:
            raise ValueError("expired backup pruning requires exact confirmation")
        root = root.resolve()
        if not root.is_dir():
            raise ValueError("backup prune root must be an existing directory")
        observed_at = (now or datetime.now(UTC)).astimezone(UTC)
        removed = []
        for manifest_path in sorted(root.glob("*.manifest.json")):
            manifest = BackupManifest.model_validate_json(
                manifest_path.read_text(encoding="utf-8")
            )
            if manifest.expires_at > observed_at:
                continue
            artifact = (root / manifest.artifact_name).resolve()
            try:
                artifact.relative_to(root)
            except ValueError as error:
                raise ValueError("backup artifact escapes prune root") from error
            self.verify_backup(artifact=artifact, manifest_path=manifest_path)
            artifact.unlink()
            manifest_path.unlink()
            removed.append(
                {
                    "backup_id": str(manifest.backup_id),
                    "artifact_name": manifest.artifact_name,
                    "manifest_hash": manifest.content_hash,
                    "expired_at": manifest.expires_at.isoformat(),
                }
            )
        return tuple(removed)

    def restore_verified_backup(
        self,
        *,
        artifact: Path,
        manifest_path: Path,
        target_database_url: str,
        restore_id: UUID,
        store_factory,
    ) -> dict[str, Any]:
        manifest = self.verify_backup(
            artifact=artifact,
            manifest_path=manifest_path,
        )
        if manifest.expires_at <= datetime.now(UTC):
            raise ValueError("expired backup cannot be restored")
        target = conninfo_to_dict(target_database_url).get("dbname")
        if not target or not _DATABASE_NAME.fullmatch(target):
            raise ValueError("restore target must name one exact database")
        if target == manifest.source_database_name:
            raise ValueError("restore must target a separate empty database")
        with psycopg.connect(target_database_url) as connection:
            occupied, vector_available = connection.execute(
                """
                SELECT
                    EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_schema='havre'
                    ),
                    EXISTS (
                        SELECT 1 FROM pg_extension WHERE extname='vector'
                    )
                """
            ).fetchone()
        if occupied:
            raise ValueError("restore target database is not empty")
        if not vector_available:
            raise ValueError(
                "restore target must have the vector extension preinstalled"
            )
        completed = _postgres_process(
            executable=self.pg_restore,
            database_url=target_database_url,
            arguments=[
                "--exit-on-error",
                "--no-owner",
                "--no-privileges",
                "--no-comments",
                "--dbname",
                target,
                str(artifact.resolve()),
            ],
            append_database=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "pg_restore failed: "
                + completed.stderr.decode("utf-8", errors="replace")[-2000:]
            )
        if _migration_head(target_database_url) != manifest.migration_head:
            raise ValueError("restored database migration head mismatch")
        require_single_owner_database(target_database_url, manifest.owner_id)
        with local_erasure_lock(self.ledger.path):
            with psycopg.connect(
                target_database_url,
                autocommit=True,
            ) as lock_connection:
                with backup_erasure_lock(lock_connection):
                    store = store_factory(target_database_url)
                    try:
                        if store.owner_id != manifest.owner_id:
                            raise ValueError(
                                "restore store owner does not match backup manifest"
                            )
                        store.persist_backup_manifest(
                            manifest,
                            artifact_uri=f"local://restores/{artifact.name}",
                        )
                        replay = store.replay_erasure_directives(
                            ledger=self.ledger,
                            after_sequence=manifest.erasure_ledger_sequence,
                            restore_id=str(restore_id),
                            _coordination_locked=True,
                        )
                        replay_record = RestoreErasureReplay(
                            replay_id=restore_id,
                            owner_id=store.owner_id,
                            backup_id=manifest.backup_id,
                            restored_database_name=target,
                            ledger_sequence_from=int(replay["ledger_sequence_from"]),
                            ledger_sequence_through=int(
                                replay["ledger_sequence_through"]
                            ),
                            directives_applied=int(replay["directives_applied"]),
                            absence_verified=True,
                            provenance_violations=0,
                        )
                        store.persist_restore_replay(replay_record)
                    finally:
                        store.repository.close()
        return {
            "cutover_ready": False,
            "required_next_step": "bootstrap_roles_and_verify_actual_login_boundaries",
            "backup_manifest_hash": manifest.content_hash,
            "restored_database_name": target,
            "migration_head": manifest.migration_head,
            "erasure_replay": replay,
            "restore_replay_hash": replay_record.content_hash,
        }
