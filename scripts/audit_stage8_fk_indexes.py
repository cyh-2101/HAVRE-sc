"""Report Stage 8 foreign keys without a matching left-prefix index."""

from __future__ import annotations

import os

import psycopg


QUERY = r"""
WITH wanted(table_name) AS (
  VALUES ('memory_lifecycle_proposals'), ('evaluation_retention_policies'), ('evaluation_runs'),
    ('evaluation_case_results'), ('judge_calibration_runs'), ('evidence_bundles'),
    ('evidence_bundle_runs'), ('evidence_bundle_calibrations'),
    ('evidence_bundle_traces'), ('evaluation_artifacts'),
    ('evaluation_retention_reviews'),
    ('evaluation_artifact_access_grants'), ('evaluation_artifact_access_log'),
    ('release_comparisons'), ('evaluation_review_requests'),
    ('evaluation_review_decisions'), ('evidence_bundle_release_comparisons'),
    ('evidence_bundle_review_decisions')
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


def audit_stage8_fk_indexes(database_url: str) -> list[dict[str, str]]:
    with psycopg.connect(database_url, row_factory=psycopg.rows.dict_row) as connection:
        return connection.execute(QUERY).fetchall()


def main() -> None:
    url = os.getenv("HAVRE_TEST_DATABASE_URL")
    if not url:
        raise RuntimeError("HAVRE_TEST_DATABASE_URL is required")
    print(audit_stage8_fk_indexes(url))


if __name__ == "__main__":
    main()
