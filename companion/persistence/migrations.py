"""Small checksum-verifying PostgreSQL migration runner."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re

import psycopg


class MigrationError(RuntimeError):
    pass


_MIGRATION_LOCK_ID = 804_173_001
_DOLLAR_QUOTE = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$")
_TRANSACTION_CONTROL = re.compile(
    r"^(?:BEGIN|START\s+TRANSACTION|COMMIT|END|ROLLBACK|ABORT|"
    r"SAVEPOINT|RELEASE(?:\s+SAVEPOINT)?|PREPARE\s+TRANSACTION)\b",
    re.IGNORECASE,
)


def _top_level_sql_statements(text: str) -> list[str]:
    """Split SQL statements while ignoring quoted procedural bodies.

    This is deliberately only a transaction-control detector, not a general
    SQL parser.  It handles the PostgreSQL quoting and comment forms used by
    checked-in migrations so controls inside PL/pgSQL bodies or string literals
    are not mistaken for file-level transaction boundaries.
    """

    statements: list[str] = []
    current: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        if text.startswith("--", index):
            newline = text.find("\n", index + 2)
            if newline < 0:
                current.append(" ")
                break
            current.append("\n")
            index = newline + 1
            continue
        if text.startswith("/*", index):
            depth = 1
            index += 2
            while index < length and depth:
                if text.startswith("/*", index):
                    depth += 1
                    index += 2
                elif text.startswith("*/", index):
                    depth -= 1
                    index += 2
                else:
                    index += 1
            current.append(" ")
            continue

        character = text[index]
        if character in {"'", '"'}:
            quote = character
            current.append(character)
            index += 1
            while index < length:
                character = text[index]
                current.append(character)
                index += 1
                if character == "\\" and index < length:
                    current.append(text[index])
                    index += 1
                    continue
                if character != quote:
                    continue
                if index < length and text[index] == quote:
                    current.append(text[index])
                    index += 1
                    continue
                break
            continue

        if character == "$":
            match = _DOLLAR_QUOTE.match(text, index)
            if match:
                delimiter = match.group(0)
                end = text.find(delimiter, match.end())
                if end < 0:
                    current.append(text[index:])
                    index = length
                else:
                    end += len(delimiter)
                    current.append(text[index:end])
                    index = end
                continue

        current.append(character)
        index += 1
        if character == ";":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []

    trailing = "".join(current).strip()
    if trailing:
        statements.append(trailing)
    return statements


def _migration_transaction_body(raw: bytes, *, migration_id: str) -> str:
    """Remove one file-level transaction wrapper owned by the runner.

    Historical migrations from 0034 onward include a standalone outer
    ``BEGIN;``/``COMMIT;`` pair.  Executing those controls inside a runner-wide
    transaction lets a migration commit its DDL before the checksum row is
    durable.  Keep hashing the exact checked-in bytes, but execute the body in
    the runner's per-file transaction instead.
    """

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise MigrationError(
            f"migration {migration_id} is not valid UTF-8"
        ) from error
    lines = text.splitlines(keepends=True)
    line_controls: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        # A comment after a standalone transaction statement does not change
        # its meaning.  No other transaction-control spelling is normalized.
        statement = line.split("--", 1)[0].strip().upper()
        if statement in {"BEGIN;", "COMMIT;", "ROLLBACK;"}:
            line_controls.append((index, statement))

    statements = _top_level_sql_statements(text)
    transaction_controls = [
        (index, " ".join(statement.split()).upper())
        for index, statement in enumerate(statements)
        if _TRANSACTION_CONTROL.match(statement)
    ]
    if not transaction_controls and not line_controls:
        return text
    if (
        transaction_controls
        != [(0, "BEGIN;"), (len(statements) - 1, "COMMIT;")]
        or len(line_controls) != 2
        or line_controls[0][1] != "BEGIN;"
        or line_controls[1][1] != "COMMIT;"
    ):
        raise MigrationError(
            f"migration {migration_id} has a malformed transaction envelope"
        )
    begin_index = line_controls[0][0]
    commit_index = line_controls[1][0]
    # Keep PostgreSQL error line numbers aligned with the checked-in file.
    for index in (begin_index, commit_index):
        if lines[index].endswith("\r\n"):
            lines[index] = "\r\n"
        elif lines[index].endswith("\n"):
            lines[index] = "\n"
        else:
            lines[index] = ""
    return "".join(lines)


def apply_migrations(database_url: str, migrations_root: Path) -> list[str]:
    applied: list[str] = []
    migration_files = sorted(migrations_root.glob("*.sql"))
    if not migration_files:
        raise MigrationError(f"no migrations found in {migrations_root}")

    # A transaction-scoped lock cannot protect the gap between independently
    # committed per-migration transactions.  Hold one session lock across the
    # full checksum/read/apply sequence; connection close is the final fallback
    # release if an error interrupts the explicit unlock.
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute("SELECT pg_advisory_lock(%s)", (_MIGRATION_LOCK_ID,))
        try:
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
                body = _migration_transaction_body(
                    raw,
                    migration_id=path.name,
                )
                with connection.transaction():
                    connection.execute(body)
                    connection.execute(
                        """
                        INSERT INTO havre.schema_migrations (
                            migration_id, content_sha256
                        ) VALUES (%s, %s)
                        """,
                        (path.name, digest),
                    )
                known[path.name] = digest
                applied.append(path.name)
        finally:
            try:
                connection.execute(
                    "SELECT pg_advisory_unlock(%s)",
                    (_MIGRATION_LOCK_ID,),
                )
            except psycopg.Error:
                # Closing the session releases every session-level advisory
                # lock; do not disguise the original migration failure.
                pass
    return applied
