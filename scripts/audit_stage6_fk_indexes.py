"""Report Stage 6 foreign keys without a matching left-prefix index."""

from __future__ import annotations

import os
import psycopg

QUERY = r"""
WITH stage6_tables(table_name) AS (
    VALUES ('proactive_preference_revisions'), ('proactive_triggers'),
      ('proactive_proposals'), ('interruption_decisions'),
      ('proactive_context_packs'), ('rendered_proactive_messages'),
      ('proactive_delivery_attempts'), ('proactive_inbox_messages'),
      ('proactive_lifecycle_events'), ('proactive_owner_actions'),
      ('proactive_work_items')
), fk AS (
    SELECT con.conname, con.conrelid, con.conkey, rel.relname
    FROM pg_constraint AS con
    JOIN pg_class AS rel ON rel.oid = con.conrelid
    JOIN pg_namespace AS ns ON ns.oid = rel.relnamespace
    JOIN stage6_tables AS wanted ON wanted.table_name = rel.relname
    WHERE con.contype = 'f' AND ns.nspname = 'havre'
)
SELECT fk.relname AS table_name, fk.conname AS constraint_name
FROM fk
WHERE NOT EXISTS (
    SELECT 1 FROM pg_index AS idx
    WHERE idx.indrelid = fk.conrelid AND idx.indisvalid
      AND (idx.indkey::smallint[])[0:cardinality(fk.conkey)-1] = fk.conkey
)
ORDER BY fk.relname, fk.conname
"""

def audit_stage6_fk_indexes(database_url: str) -> list[dict[str, str]]:
    with psycopg.connect(database_url, row_factory=psycopg.rows.dict_row) as connection:
        return connection.execute(QUERY).fetchall()

def main() -> None:
    database_url = os.getenv("HAVRE_TEST_DATABASE_URL")
    if not database_url:
        raise RuntimeError("HAVRE_TEST_DATABASE_URL is required")
    print(audit_stage6_fk_indexes(database_url))

if __name__ == "__main__":
    main()
