"""Populate the rejected 0028 shape and verify additive holdout invalidation."""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from companion.persistence import apply_migrations


OWNER = UUID("00000000-0000-7000-8000-000000000099")
SNAPSHOT = UUID("00000000-0000-7000-8000-000000000098")
SHA = "sha256:" + "1" * 64


def main() -> None:
    url = os.environ["HAVRE_TEST_DATABASE_URL"]
    project_root = Path(__file__).resolve().parents[1]
    examples = [
        {
            "example_id": f"legacy-{split}-{index}",
            "source_ref": f"fixture://stage9/synthetic/legacy-{split}-{index}",
            "split": split,
            "content_hash": "sha256:" + str(index + 2) * 64,
        }
        for index, split in enumerate(("train", "train", "validation", "holdout"))
    ]
    snapshot_payload = {
        "examples": examples,
        "contains_user_data": False,
        "user_event_source_count": 0,
        "local_only_build": True,
    }
    with psycopg.connect(url) as connection, connection.transaction():
        connection.execute(
            "INSERT INTO havre.owners(owner_id,display_name) VALUES (%s,'Legacy Stage9')",
            (OWNER,),
        )
        connection.execute(
            """
            INSERT INTO havre.training_dataset_snapshots (
                dataset_snapshot_id,schema_version,owner_id,name,semantic_version,
                builder_version,split_policy_version,fixture_content_hash,
                member_manifest_hash,user_event_source_count,contains_user_data,
                local_only_build,immutable,payload,content_hash,created_at
            ) VALUES (%s,1,%s,'stage9-synthetic-public-fixture-v1','1.0.0',
                      'stage9-canonical-fixture-builder-v1','fixed-source-grouped-v1',
                      %s,%s,0,false,true,true,%s,%s,clock_timestamp())
            """,
            (SNAPSHOT, OWNER, SHA, SHA, Jsonb(snapshot_payload), SHA),
        )
        for example in examples:
            payload = {
                **example,
                "training_eligible": True,
                "contains_user_data": False,
                "privacy_class": "PUBLIC",
            }
            connection.execute(
                """
                INSERT INTO havre.training_dataset_members (
                    owner_id,dataset_snapshot_id,example_id,source_kind,source_ref,
                    license_id,split,training_eligible,contains_user_data,privacy_class,
                    content_hash,payload
                ) VALUES (%s,%s,%s,'synthetic_fixture',%s,'CC0-1.0',%s,true,false,
                          'PUBLIC',%s,%s)
                """,
                (
                    OWNER, SNAPSHOT, example["example_id"], example["source_ref"],
                    example["split"], example["content_hash"], Jsonb(payload),
                ),
            )
    applied = apply_migrations(url, project_root / "db" / "migrations")
    with psycopg.connect(url, row_factory=psycopg.rows.dict_row) as connection:
        invalidation = connection.execute(
            """
            SELECT reason_code FROM havre.stage9_candidate_invalidations
            WHERE owner_id=%s AND dataset_snapshot_id=%s
            """,
            (OWNER, SNAPSHOT),
        ).fetchone()
        retained_holdout = connection.execute(
            """
            SELECT count(*) AS value FROM havre.training_dataset_members
            WHERE owner_id=%s AND dataset_snapshot_id=%s AND split='holdout'
            """,
            (OWNER, SNAPSHOT),
        ).fetchone()["value"]
        violations = connection.execute(
            "SELECT count(*) AS value FROM havre.stage9_integrity_violations WHERE owner_id=%s",
            (OWNER,),
        ).fetchone()["value"]
    if invalidation is None or invalidation["reason_code"] != (
        "evaluation_holdout_in_training_snapshot_v1"
    ):
        raise AssertionError("legacy contaminated snapshot was not invalidated")
    if retained_holdout != 1:
        raise AssertionError("upgrade must preserve rejected historical evidence")
    if violations != 0:
        raise AssertionError("explicitly invalidated historical candidate is not an active violation")
    print(json.dumps({
        "applied": applied,
        "invalidation": invalidation["reason_code"],
        "retained_historical_holdout": retained_holdout,
        "active_integrity_violations": violations,
    }))


if __name__ == "__main__":
    main()
