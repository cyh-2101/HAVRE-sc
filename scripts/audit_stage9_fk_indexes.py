"""Report Stage 9 foreign keys without a matching left-prefix index."""

from __future__ import annotations

import os

import psycopg


QUERY = r"""
WITH wanted(table_name) AS (
  VALUES ('training_dataset_snapshots'), ('training_dataset_members'),
    ('model_versions'), ('training_runs'), ('adapter_versions'),
    ('adapter_compatibility_reports'), ('personalization_evaluation_reports'),
    ('adapter_rejection_records'), ('rendered_training_artifacts')
    , ('stage9_candidate_invalidations'), ('evaluation_holdout_suites'),
    ('evaluation_holdout_cases')
), fk AS (
  SELECT con.conname, con.conrelid, con.conkey, rel.relname
  FROM pg_constraint con
  JOIN pg_class rel ON rel.oid=con.conrelid
  JOIN pg_namespace ns ON ns.oid=rel.relnamespace
  JOIN wanted ON wanted.table_name=rel.relname
  WHERE con.contype='f' AND ns.nspname='havre'
)
SELECT fk.relname AS table_name, fk.conname AS constraint_name
FROM fk WHERE NOT EXISTS (
  SELECT 1 FROM pg_index idx
  WHERE idx.indrelid=fk.conrelid AND idx.indisvalid
    AND (idx.indkey::smallint[])[0:cardinality(fk.conkey)-1]=fk.conkey
)
ORDER BY fk.relname,fk.conname
"""


def audit_stage9_fk_indexes(database_url: str) -> list[dict[str, str]]:
    with psycopg.connect(database_url, row_factory=psycopg.rows.dict_row) as connection:
        return connection.execute(QUERY).fetchall()


def main() -> None:
    url = os.getenv("HAVRE_TEST_DATABASE_URL")
    if not url:
        raise RuntimeError("HAVRE_TEST_DATABASE_URL is required")
    print(audit_stage9_fk_indexes(url))


if __name__ == "__main__":
    main()
