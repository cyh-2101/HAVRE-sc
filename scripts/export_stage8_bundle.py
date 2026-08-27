"""Export and validate the latest immutable Stage 8 closure bundle."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from companion.evaluation import EvidenceBundle


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path,
        default=Path("evals/reports/stage8_20260819/evidence-bundle.json"),
    )
    args = parser.parse_args()
    database_url = os.getenv("HAVRE_TEST_DATABASE_URL")
    if not database_url:
        raise RuntimeError("HAVRE_TEST_DATABASE_URL is required")
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        row = connection.execute(
            """
            SELECT payload FROM havre.evidence_bundles
            WHERE explicit_decision='accepted_for_stage9_candidate_foundation'
            ORDER BY created_at DESC, evidence_bundle_id DESC LIMIT 1
            """
        ).fetchone()
    if row is None:
        raise RuntimeError("no accepted Stage 8 closure bundle exists")
    bundle = EvidenceBundle.model_validate(row["payload"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(bundle.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(bundle.evidence_bundle_id)
    print(bundle.content_hash)


if __name__ == "__main__":
    main()
