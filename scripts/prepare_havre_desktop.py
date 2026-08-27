"""Provision least-privilege, owner-local desktop runtime credentials."""

from __future__ import annotations

import argparse
import os
import secrets
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import psycopg
from psycopg import sql

from companion.persistence import apply_migrations


ROLE_NAME = "havre_desktop_application"


def _application_url(admin_url: str, password: str) -> str:
    parsed = urlsplit(admin_url)
    host = parsed.hostname or "127.0.0.1"
    port = f":{parsed.port}" if parsed.port is not None else ""
    netloc = f"{ROLE_NAME}:{quote(password, safe='')}@{host}{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, ""))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--admin-database-url", required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--secret-root", type=Path, required=True)
    args = parser.parse_args()
    project_root = args.project_root.resolve()
    secret_root = args.secret_root.resolve()
    if os.name == "nt" and not secret_root.is_dir():
        raise ValueError(
            "Windows desktop secret root must be pre-created with owner-only ACLs"
        )
    secret_root.mkdir(parents=True, exist_ok=True)

    apply_migrations(args.admin_database_url, project_root / "db" / "migrations")
    database_password = secrets.token_urlsafe(48)
    owner_token = secrets.token_urlsafe(48)
    bootstrap_token = secrets.token_urlsafe(48)
    with psycopg.connect(args.admin_database_url, autocommit=True) as connection:
        database_name = connection.execute("SELECT current_database()").fetchone()[0]
        roles_sql = (project_root / "deploy" / "bootstrap_roles.sql").read_text(
            encoding="utf-8"
        ).replace(":DBNAME", f'"{database_name}"')
        roles_sql = "\n".join(
            line for line in roles_sql.splitlines()
            if not line.lstrip().startswith("\\set ")
        )
        connection.execute(roles_sql)
        connection.execute(
            sql.SQL(
                """DO $block$ BEGIN
                     IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname={role_literal}) THEN
                       CREATE ROLE {role_identifier} LOGIN INHERIT NOSUPERUSER
                         NOCREATEDB NOCREATEROLE NOREPLICATION;
                     END IF;
                   END $block$"""
            ).format(
                role_literal=sql.Literal(ROLE_NAME),
                role_identifier=sql.Identifier(ROLE_NAME),
            )
        )
        connection.execute(
            sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                sql.Identifier(ROLE_NAME), sql.Literal(database_password)
            )
        )
        connection.execute(
            sql.SQL("GRANT havre_application TO {}").format(
                sql.Identifier(ROLE_NAME)
            )
        )

    values = {
        "database-url.secret": _application_url(
            args.admin_database_url, database_password
        ),
        "owner-api-token.secret": owner_token,
        "desktop-bootstrap-token.secret": bootstrap_token,
    }
    for name, value in values.items():
        path = secret_root / name
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(value, encoding="utf-8")
        temporary.replace(path)
    print("HAVRE desktop least-privilege credentials prepared")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
