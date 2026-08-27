"""Audit FK-side index coverage for every active Stage 4 table."""

from __future__ import annotations

import json
import os

import psycopg


STAGE4_TABLES = (
    "belief_head_projection_consumptions",
    "belief_heads",
    "belief_revision_transitions",
    "consolidation_proposals",
    "current_state_snapshots",
    "goal_progress_records",
    "goals",
    "provenance_edges",
    "user_belief_revisions",
    "user_model_evaluation_runs",
)


def audit_stage4_fk_indexes(database_url: str) -> list[dict[str, object]]:
    """Return Stage 4 foreign keys lacking a matching index-column prefix."""

    with psycopg.connect(database_url) as connection:
        rows = connection.execute(
            """
            SELECT
                relation.relname AS table_name,
                constraint_row.conname AS constraint_name,
                ARRAY(
                    SELECT attribute.attname
                    FROM unnest(constraint_row.conkey)
                         WITH ORDINALITY AS key_column(attnum, position)
                    JOIN pg_attribute AS attribute
                      ON attribute.attrelid = constraint_row.conrelid
                     AND attribute.attnum = key_column.attnum
                    ORDER BY key_column.position
                ) AS fk_columns
            FROM pg_constraint AS constraint_row
            JOIN pg_class AS relation
              ON relation.oid = constraint_row.conrelid
            JOIN pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            WHERE constraint_row.contype = 'f'
              AND namespace.nspname = 'havre'
              AND relation.relname = ANY(%s)
              AND NOT EXISTS (
                    SELECT 1
                    FROM pg_index AS index_row
                    WHERE index_row.indrelid = constraint_row.conrelid
                      AND index_row.indisvalid
                      AND index_row.indisready
                      AND index_row.indnkeyatts
                            >= cardinality(constraint_row.conkey)
                      AND NOT EXISTS (
                            SELECT 1
                            FROM unnest(constraint_row.conkey)
                                 WITH ORDINALITY AS fk_column(attnum, position)
                            WHERE (index_row.indkey::smallint[])
                                      [fk_column.position - 1]
                                  IS DISTINCT FROM fk_column.attnum
                      )
              )
            ORDER BY relation.relname, constraint_row.conname
            """,
            (list(STAGE4_TABLES),),
        ).fetchall()
    return [dict(row) for row in rows]


def main() -> int:
    database_url = os.getenv("HAVRE_TEST_DATABASE_URL")
    if not database_url:
        raise RuntimeError("HAVRE_TEST_DATABASE_URL is required")
    violations = audit_stage4_fk_indexes(database_url)
    print(json.dumps(violations, indent=2, sort_keys=True))
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
