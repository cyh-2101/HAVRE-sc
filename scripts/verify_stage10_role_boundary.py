"""Verify ordinary application and privileged erasure database role separation."""

from __future__ import annotations

import json
import os

import psycopg


def verify(database_url: str) -> dict[str, object]:
    with psycopg.connect(database_url) as connection:
        (
            app_is_privileged,
            app_can_delete,
            app_can_approve_release,
            erasure_is_privileged,
            erasure_can_delete,
            release_can_approve,
            release_can_read_events,
            restore_is_privileged,
            restore_can_read_events,
        ) = (
            connection.execute(
                """
                SELECT
                    pg_has_role('havre_application','havre_privileged_erasure','MEMBER'),
                    has_table_privilege('havre_application','havre.events','DELETE'),
                    has_table_privilege('havre_application','havre.release_approval_records','INSERT'),
                    pg_has_role('havre_erasure_executor','havre_privileged_erasure','MEMBER'),
                    has_table_privilege('havre_erasure_executor','havre.events','DELETE'),
                    has_table_privilege('havre_release_operator','havre.release_approval_records','INSERT'),
                    has_table_privilege('havre_release_operator','havre.events','SELECT'),
                    pg_has_role('havre_restore_operator','havre_privileged_erasure','MEMBER'),
                    has_table_privilege('havre_restore_operator','havre.events','SELECT')
                """
            ).fetchone()
        )
        app_delete_rejected = False
        try:
            with connection.transaction():
                connection.execute("SET LOCAL ROLE havre_application")
                connection.execute("DELETE FROM havre.events WHERE false")
        except psycopg.errors.InsufficientPrivilege:
            app_delete_rejected = True
        app_approval_rejected = False
        try:
            with connection.transaction():
                connection.execute("SET LOCAL ROLE havre_application")
                connection.execute(
                    """
                    INSERT INTO havre.release_approval_records (
                        release_approval_id, schema_version, owner_id,
                        release_manifest_id, release_manifest_hash, approval_scope,
                        decision, actor, rationale, decided_at, content_hash
                    ) SELECT gen_random_uuid(),1,owner_id,gen_random_uuid(),
                        'sha256:' || repeat('a',64),'infrastructure_production_release',
                        'approved','product_owner','forbidden fixture',now(),
                        'sha256:' || repeat('b',64)
                    FROM havre.owners LIMIT 1
                    """
                )
        except psycopg.errors.InsufficientPrivilege:
            app_approval_rejected = True
        with connection.transaction():
            connection.execute("SET LOCAL ROLE havre_erasure_executor")
            connection.execute("DELETE FROM havre.events WHERE false")
        release_event_read_rejected = False
        try:
            with connection.transaction():
                connection.execute("SET LOCAL ROLE havre_release_operator")
                connection.execute("SELECT 1 FROM havre.events LIMIT 1")
        except psycopg.errors.InsufficientPrivilege:
            release_event_read_rejected = True
    result = {
        "application_inherits_privileged_erasure": app_is_privileged,
        "application_has_delete": app_can_delete,
        "application_has_release_approval_insert": app_can_approve_release,
        "application_delete_rejected": app_delete_rejected,
        "application_release_approval_rejected": app_approval_rejected,
        "erasure_executor_inherits_privileged_erasure": erasure_is_privileged,
        "erasure_executor_has_delete": erasure_can_delete,
        "erasure_executor_delete_path_available": True,
        "release_operator_has_release_approval_insert": release_can_approve,
        "release_operator_has_event_select": release_can_read_events,
        "release_operator_event_read_rejected": release_event_read_rejected,
        "restore_operator_inherits_privileged_erasure": restore_is_privileged,
        "restore_operator_has_event_select": restore_can_read_events,
    }
    expected = {
        "application_inherits_privileged_erasure": False,
        "application_has_delete": False,
        "application_has_release_approval_insert": False,
        "application_delete_rejected": True,
        "application_release_approval_rejected": True,
        "erasure_executor_inherits_privileged_erasure": True,
        "erasure_executor_has_delete": True,
        "erasure_executor_delete_path_available": True,
        "release_operator_has_release_approval_insert": True,
        "release_operator_has_event_select": False,
        "release_operator_event_read_rejected": True,
        "restore_operator_inherits_privileged_erasure": True,
        "restore_operator_has_event_select": False,
    }
    if result != expected:
        raise RuntimeError(f"Stage 10 database role boundary failed: {result}")
    return result


def main() -> None:
    url = os.getenv("HAVRE_TEST_DATABASE_URL")
    if not url:
        raise RuntimeError("HAVRE_TEST_DATABASE_URL is required")
    print(json.dumps(verify(url), indent=2))


if __name__ == "__main__":
    main()
