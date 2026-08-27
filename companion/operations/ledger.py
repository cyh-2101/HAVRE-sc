"""Local append-only erasure directives kept outside PostgreSQL backups."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from companion.operations.models import ErasureDirective


class ErasureLedger:
    """Hash-chained deletion directives for restore-time replay.

    The ledger must live on a volume that is not replaced by a PostgreSQL
    restore. It contains identifiers and timestamps only, never message text.
    """

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS erasure_directives (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                schema_version INTEGER NOT NULL CHECK (schema_version = 1),
                owner_id TEXT NOT NULL,
                source_event_id TEXT NOT NULL,
                scope TEXT NOT NULL CHECK (scope IN (
                    'raw_source_and_derived','context_source_and_derived'
                )),
                requested_at TEXT NOT NULL,
                previous_content_hash TEXT NULL,
                content_hash TEXT NOT NULL UNIQUE,
                completed_at TEXT NULL,
                UNIQUE (owner_id, source_event_id)
            )
            """
        )
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(erasure_directives)")
        }
        if "completed_at" not in columns:
            connection.execute(
                "ALTER TABLE erasure_directives ADD COLUMN completed_at TEXT NULL"
            )
        table_sql = str(connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='erasure_directives'"
        ).fetchone()[0])
        if "context_source_and_derived" not in table_sql:
            # Preserve the immutable Stage 10 chain and replay receipts while
            # widening only the enumerated scope. SQLite cannot ALTER CHECK.
            connection.commit()
            connection.execute("PRAGMA foreign_keys=OFF")
            with connection:
                replay_rows = (
                    connection.execute(
                        "SELECT * FROM replay_applications ORDER BY application_id"
                    ).fetchall()
                    if connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='replay_applications'"
                    ).fetchone() is not None
                    else []
                )
                connection.execute("DROP TABLE IF EXISTS replay_applications")
                connection.execute("ALTER TABLE erasure_directives RENAME TO erasure_directives_stage10")
                connection.execute(
                    """
                    CREATE TABLE erasure_directives (
                        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                        schema_version INTEGER NOT NULL CHECK (schema_version = 1),
                        owner_id TEXT NOT NULL,
                        source_event_id TEXT NOT NULL,
                        scope TEXT NOT NULL CHECK (scope IN (
                            'raw_source_and_derived','context_source_and_derived'
                        )),
                        requested_at TEXT NOT NULL,
                        previous_content_hash TEXT NULL,
                        content_hash TEXT NOT NULL UNIQUE,
                        completed_at TEXT NULL,
                        UNIQUE (owner_id, source_event_id)
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO erasure_directives (
                        sequence,schema_version,owner_id,source_event_id,scope,
                        requested_at,previous_content_hash,content_hash,completed_at
                    )
                    SELECT sequence,schema_version,owner_id,source_event_id,scope,
                           requested_at,previous_content_hash,content_hash,completed_at
                    FROM erasure_directives_stage10 ORDER BY sequence
                    """
                )
                connection.execute("DROP TABLE erasure_directives_stage10")
                connection.execute(
                    """
                    CREATE TABLE replay_applications (
                        application_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        restore_id TEXT NOT NULL,
                        directive_sequence INTEGER NOT NULL,
                        applied_at TEXT NOT NULL,
                        UNIQUE (restore_id, directive_sequence),
                        FOREIGN KEY (directive_sequence)
                            REFERENCES erasure_directives(sequence)
                    )
                    """
                )
                connection.executemany(
                    """
                    INSERT INTO replay_applications (
                        application_id,restore_id,directive_sequence,applied_at
                    ) VALUES (?,?,?,?)
                    """,
                    [
                        (
                            row["application_id"],row["restore_id"],
                            row["directive_sequence"],row["applied_at"],
                        )
                        for row in replay_rows
                    ],
                )
            connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS replay_applications (
                application_id INTEGER PRIMARY KEY AUTOINCREMENT,
                restore_id TEXT NOT NULL,
                directive_sequence INTEGER NOT NULL,
                applied_at TEXT NOT NULL,
                UNIQUE (restore_id, directive_sequence),
                FOREIGN KEY (directive_sequence)
                    REFERENCES erasure_directives(sequence)
            )
            """
        )
        self.path.chmod(0o600)
        return connection

    def append(
        self,
        *,
        owner_id: UUID,
        source_event_id: UUID,
        requested_at: datetime | None = None,
        scope: str = "raw_source_and_derived",
    ) -> ErasureDirective:
        timestamp = (requested_at or datetime.now(UTC)).astimezone(UTC)
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT * FROM erasure_directives
                WHERE owner_id = ? AND source_event_id = ?
                """,
                (str(owner_id), str(source_event_id)),
            ).fetchone()
            if existing is not None:
                return self._from_row(existing)
            prior = connection.execute(
                """
                SELECT sequence, content_hash FROM erasure_directives
                ORDER BY sequence DESC LIMIT 1
                """
            ).fetchone()
            sequence = 1 if prior is None else int(prior["sequence"]) + 1
            directive = ErasureDirective(
                sequence=sequence,
                owner_id=owner_id,
                source_event_id=source_event_id,
                requested_at=timestamp,
                scope=scope,
                previous_content_hash=(
                    None if prior is None else str(prior["content_hash"])
                ),
            )
            connection.execute(
                """
                INSERT INTO erasure_directives (
                    sequence, schema_version, owner_id, source_event_id, scope,
                    requested_at, previous_content_hash, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    directive.sequence,
                    directive.schema_version,
                    str(directive.owner_id),
                    str(directive.source_event_id),
                    directive.scope,
                    directive.requested_at.isoformat(),
                    directive.previous_content_hash,
                    directive.content_hash,
                ),
            )
            return directive

    def verify(self) -> tuple[ErasureDirective, ...]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM erasure_directives ORDER BY sequence"
            ).fetchall()
        directives = tuple(self._from_row(row) for row in rows)
        prior: str | None = None
        for expected_sequence, directive in enumerate(directives, start=1):
            if directive.sequence != expected_sequence:
                raise ValueError("erasure ledger sequence is not contiguous")
            if directive.previous_content_hash != prior:
                raise ValueError("erasure ledger hash chain is broken")
            prior = directive.content_hash
        return directives

    def current_sequence(self) -> int:
        directives = self.verify()
        return 0 if not directives else directives[-1].sequence

    def completed_sequence(self) -> int:
        self.verify()
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT sequence, completed_at FROM erasure_directives ORDER BY sequence"
            ).fetchall()
        completed = 0
        for row in rows:
            if row["completed_at"] is None:
                break
            completed = int(row["sequence"])
        return completed

    def mark_completed(self, *, sequence: int) -> None:
        if sequence <= 0:
            raise ValueError("completed directive sequence is invalid")
        with closing(self._connect()) as connection, connection:
            updated = connection.execute(
                """
                UPDATE erasure_directives
                SET completed_at=COALESCE(completed_at, ?)
                WHERE sequence=?
                """,
                (datetime.now(UTC).isoformat(), sequence),
            ).rowcount
            if updated != 1:
                raise ValueError("completed directive does not exist")

    def directives_after(self, sequence: int) -> tuple[ErasureDirective, ...]:
        if sequence < 0:
            raise ValueError("erasure ledger sequence cannot be negative")
        return tuple(item for item in self.verify() if item.sequence > sequence)

    def mark_applied(self, *, restore_id: str, sequence: int) -> None:
        if not restore_id.strip() or sequence <= 0:
            raise ValueError("restore application identity is invalid")
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO replay_applications (
                    restore_id, directive_sequence, applied_at
                ) VALUES (?, ?, ?)
                ON CONFLICT (restore_id, directive_sequence) DO NOTHING
                """,
                (restore_id, sequence, datetime.now(UTC).isoformat()),
            )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> ErasureDirective:
        return ErasureDirective(
            sequence=int(row["sequence"]),
            owner_id=UUID(str(row["owner_id"])),
            source_event_id=UUID(str(row["source_event_id"])),
            scope=str(row["scope"]),
            requested_at=datetime.fromisoformat(str(row["requested_at"])),
            previous_content_hash=(
                None
                if row["previous_content_hash"] is None
                else str(row["previous_content_hash"])
            ),
            content_hash=str(row["content_hash"]),
        )
