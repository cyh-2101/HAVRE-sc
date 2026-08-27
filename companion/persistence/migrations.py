"""Small checksum-verifying PostgreSQL migration runner."""

from __future__ import annotations

import hashlib
from pathlib import Path

import psycopg


class MigrationError(RuntimeError):
    pass


def apply_migrations(database_url: str, migrations_root: Path) -> list[str]:
    applied: list[str] = []
    migration_files = sorted(migrations_root.glob("*.sql"))
    if not migration_files:
        raise MigrationError(f"no migrations found in {migrations_root}")

    with psycopg.connect(database_url) as connection:
        with connection.transaction():
            connection.execute("SELECT pg_advisory_xact_lock(804_173_001)")
            # Migration 0036 is immutable and grants its new tables to the
            # cluster-wide application group.  A genuinely fresh cluster has
            # no such role yet, while the full post-migration role bootstrap
            # cannot run before the HAVRE schema/tables exist.  Create only the
            # NOLOGIN group needed by the migration here; bootstrap_roles.sql
            # applies the complete least-privilege grants after migration.
            connection.execute(
                """
                DO $role$
                BEGIN
                  IF NOT EXISTS (
                    SELECT 1 FROM pg_roles WHERE rolname='havre_application'
                  ) THEN
                    CREATE ROLE havre_application NOLOGIN NOSUPERUSER
                      NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT;
                  END IF;
                END
                $role$
                """
            )
            exists = connection.execute(
                "SELECT to_regclass('havre.schema_migrations') IS NOT NULL"
            ).fetchone()[0]
            known: dict[str, str] = {}
            if exists:
                known = dict(
                    connection.execute(
                        "SELECT migration_id, content_sha256 FROM havre.schema_migrations"
                    ).fetchall()
                )

            for path in migration_files:
                raw = path.read_bytes()
                digest = hashlib.sha256(raw).hexdigest()
                if path.name in known:
                    if known[path.name] != digest:
                        raise MigrationError(
                            f"applied migration {path.name} has changed on disk"
                        )
                    continue
                connection.execute(raw.decode("utf-8"))
                connection.execute(
                    """
                    INSERT INTO havre.schema_migrations (migration_id, content_sha256)
                    VALUES (%s, %s)
                    """,
                    (path.name, digest),
                )
                applied.append(path.name)
    return applied
