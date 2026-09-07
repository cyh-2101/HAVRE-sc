from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from companion.persistence import apply_migrations
from companion.persistence.migrations import (
    MigrationError,
    _migration_transaction_body,
)


DATABASE_URL = os.getenv("HAVRE_TEST_DATABASE_URL")


class MigrationEnvelopeTests(unittest.TestCase):
    def test_unwrapped_and_single_outer_wrapper_are_the_only_supported_shapes(
        self,
    ) -> None:
        unwrapped = b"CREATE TABLE example (value integer);\n"
        self.assertEqual(
            _migration_transaction_body(
                unwrapped,
                migration_id="0001_unwrapped.sql",
            ),
            unwrapped.decode("utf-8"),
        )

        wrapped = b"-- header\nBEGIN;\nSELECT 1;\nCOMMIT;\n-- footer\n"
        normalized = _migration_transaction_body(
            wrapped,
            migration_id="0002_wrapped.sql",
        )
        self.assertNotIn("BEGIN;", normalized)
        self.assertNotIn("COMMIT;", normalized)
        self.assertEqual(
            len(normalized.splitlines()),
            len(wrapped.decode("utf-8").splitlines()),
        )

        malformed = {
            "begin_only": b"BEGIN;\nSELECT 1;\n",
            "commit_only": b"SELECT 1;\nCOMMIT;\n",
            "inline_begin": b"BEGIN; SELECT 1;\nCOMMIT;\n",
            "start_transaction": b"START TRANSACTION;\nSELECT 1;\nCOMMIT;\n",
            "commit_work": b"BEGIN;\nSELECT 1;\nCOMMIT WORK;\n",
            "leading_sql": b"SELECT 0;\nBEGIN;\nSELECT 1;\nCOMMIT;\n",
            "trailing_sql": b"BEGIN;\nSELECT 1;\nCOMMIT;\nSELECT 2;\n",
            "nested": b"BEGIN;\nBEGIN;\nCOMMIT;\nCOMMIT;\n",
            "rollback": b"BEGIN;\nROLLBACK;\n",
        }
        for name, raw in malformed.items():
            with self.subTest(shape=name), self.assertRaisesRegex(
                MigrationError,
                "malformed transaction envelope",
            ):
                _migration_transaction_body(
                    raw,
                    migration_id=f"invalid_{name}.sql",
                )

    def test_every_checked_in_migration_has_a_supported_envelope(self) -> None:
        migrations = Path(__file__).resolve().parents[1] / "db" / "migrations"
        for path in sorted(migrations.glob("*.sql")):
            with self.subTest(migration=path.name):
                _migration_transaction_body(
                    path.read_bytes(),
                    migration_id=path.name,
                )


@unittest.skipUnless(DATABASE_URL, "HAVRE_TEST_DATABASE_URL is required")
class MigrationRunnerPostgresTests(unittest.TestCase):
    def setUp(self) -> None:
        assert DATABASE_URL is not None
        parameters = conninfo_to_dict(DATABASE_URL)
        self.database_name = f"havre_migration_runner_{uuid4().hex[:12]}"
        admin_parameters = dict(parameters)
        admin_parameters["dbname"] = "postgres"
        target_parameters = dict(parameters)
        target_parameters["dbname"] = self.database_name
        self.admin_url = make_conninfo(**admin_parameters)
        self.target_url = make_conninfo(**target_parameters)
        with psycopg.connect(self.admin_url, autocommit=True) as connection:
            connection.execute(
                sql.SQL("CREATE DATABASE {}").format(
                    sql.Identifier(self.database_name)
                )
            )

    def tearDown(self) -> None:
        with psycopg.connect(self.admin_url, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) "
                "FROM pg_stat_activity WHERE datname=%s",
                (self.database_name,),
            )
            connection.execute(
                sql.SQL("DROP DATABASE {}").format(
                    sql.Identifier(self.database_name)
                )
            )

    @staticmethod
    def _write(root: Path, migration_id: str, body: str) -> Path:
        path = root / migration_id
        path.write_text(body, encoding="utf-8", newline="\n")
        return path

    @staticmethod
    def _bootstrap_sql() -> str:
        # Migrations 0001-0033 predate file-level wrappers; keep this fixture
        # genuinely unwrapped so the compatibility path is exercised in DB.
        return """CREATE SCHEMA havre;
CREATE TABLE havre.schema_migrations (
    migration_id text PRIMARY KEY,
    content_sha256 text NOT NULL
);
"""

    def test_wrapped_migration_and_checksum_row_are_one_atomic_commit(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            bootstrap = self._write(
                root,
                "0001_bootstrap.sql",
                self._bootstrap_sql(),
            )
            successful = root / "0002_success.sql"
            successful.write_bytes(
                b"-- Preserve CRLF in the raw checksum.\r\n"
                b"BEGIN;\r\n"
                b"CREATE TABLE havre.committed_probe "
                b"(value integer PRIMARY KEY);\r\n"
                b"COMMIT;\r\n"
            )
            failing = self._write(
                root,
                "0003_failure.sql",
                """BEGIN;
CREATE TABLE havre.rolled_back_probe (value integer PRIMARY KEY);
DO $failure$
BEGIN
    RAISE EXCEPTION 'synthetic migration failure' USING ERRCODE='55000';
END
$failure$;
COMMIT;
""",
            )

            with self.assertRaises(
                psycopg.errors.ObjectNotInPrerequisiteState
            ):
                apply_migrations(self.target_url, root)

            with psycopg.connect(self.target_url) as connection:
                recorded = dict(connection.execute(
                    "SELECT migration_id,content_sha256 "
                    "FROM havre.schema_migrations ORDER BY migration_id"
                ).fetchall())
                committed_exists = connection.execute(
                    "SELECT to_regclass('havre.committed_probe') IS NOT NULL"
                ).fetchone()[0]
                rolled_back_exists = connection.execute(
                    "SELECT to_regclass('havre.rolled_back_probe') IS NOT NULL"
                ).fetchone()[0]
            self.assertEqual(
                recorded,
                {
                    bootstrap.name: hashlib.sha256(
                        bootstrap.read_bytes()
                    ).hexdigest(),
                    successful.name: hashlib.sha256(
                        successful.read_bytes()
                    ).hexdigest(),
                },
            )
            self.assertTrue(committed_exists)
            self.assertFalse(rolled_back_exists)

            failing.write_text(
                """BEGIN;
CREATE TABLE havre.rolled_back_probe (value integer PRIMARY KEY);
COMMIT;
""",
                encoding="utf-8",
                newline="\n",
            )
            self.assertEqual(
                apply_migrations(self.target_url, root),
                [failing.name],
            )
            self.assertEqual(apply_migrations(self.target_url, root), [])

    def test_ledger_insert_rejection_rolls_back_the_same_migration_body(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            self._write(
                root,
                "0001_bootstrap.sql",
                """CREATE SCHEMA havre;
CREATE TABLE havre.schema_migrations (
    migration_id text PRIMARY KEY,
    content_sha256 text NOT NULL,
    CONSTRAINT reject_synthetic_ledger_row CHECK (
        migration_id <> '0002_ledger_rejected.sql'
    )
);
""",
            )
            self.assertEqual(
                apply_migrations(self.target_url, root),
                ["0001_bootstrap.sql"],
            )
            self._write(
                root,
                "0002_ledger_rejected.sql",
                """BEGIN;
CREATE TABLE havre.ledger_rejected_probe (
    value integer PRIMARY KEY
);
COMMIT;
""",
            )

            with self.assertRaises(psycopg.errors.CheckViolation):
                apply_migrations(self.target_url, root)

            with psycopg.connect(self.target_url) as connection:
                self.assertFalse(connection.execute(
                    "SELECT to_regclass('havre.ledger_rejected_probe') IS NOT NULL"
                ).fetchone()[0])
                self.assertEqual(
                    connection.execute(
                        "SELECT migration_id FROM havre.schema_migrations"
                    ).fetchall(),
                    [("0001_bootstrap.sql",)],
                )

    def test_session_lock_serializes_checksum_discovery_and_apply(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            self._write(root, "0001_bootstrap.sql", self._bootstrap_sql())
            self._write(
                root,
                "0002_slow.sql",
                """BEGIN;
SELECT pg_sleep(0.2);
CREATE TABLE havre.serialized_probe (value integer PRIMARY KEY);
COMMIT;
""",
            )
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(apply_migrations, self.target_url, root)
                    for _ in range(2)
                ]
                results = [future.result(timeout=10) for future in futures]

            self.assertEqual(
                sorted(len(result) for result in results),
                [0, 2],
            )
            with psycopg.connect(self.target_url) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT count(*) FROM havre.schema_migrations"
                    ).fetchone()[0],
                    2,
                )
                self.assertTrue(connection.execute(
                    "SELECT to_regclass('havre.serialized_probe') IS NOT NULL"
                ).fetchone()[0])


if __name__ == "__main__":
    unittest.main()
