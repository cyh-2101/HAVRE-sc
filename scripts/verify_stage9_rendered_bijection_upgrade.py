"""Verify a populated 0031 database upgrades to the 0032 bijection guard."""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from companion.hashing import content_hash
from companion.identity import IdentityLoader
from companion.persistence import PostgresRepository, Stage9PostgresStore, apply_migrations
from mlsys.training import GovernanceVersionSet, run_stage9_synthetic_dry_run


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OWNER = UUID("00000000-0000-7000-8000-000000000032")


def main() -> None:
    url = os.environ["HAVRE_TEST_DATABASE_URL"]
    if "/havre_s9_bijection_upgrade_" not in url:
        raise RuntimeError("upgrade probe requires a dedicated havre_s9_bijection_upgrade_ database")
    with psycopg.connect(url) as connection:
        latest = connection.execute(
            "SELECT migration_id FROM havre.schema_migrations ORDER BY migration_id DESC LIMIT 1"
        ).fetchone()[0]
    if latest != "0031_stage9_training_fixture_v2.sql":
        raise AssertionError(f"expected populated source schema 0031, got {latest}")

    identity = IdentityLoader(PROJECT_ROOT / "identity").load()
    governance = GovernanceVersionSet(
        constitution_version=identity.constitution.version_id,
        constitution_hash=identity.constitution.content_hash,
        identity_version=identity.identity.version_id,
        identity_hash=identity.identity.content_hash,
        values_version=identity.values.version_id,
        values_hash=identity.values.content_hash,
        intervention_policy_version="intervention-policy-sim-v1",
        intervention_policy_hash=content_hash({"version": "intervention-policy-sim-v1"}),
    )
    experiment = run_stage9_synthetic_dry_run(
        owner_id=OWNER,
        training_fixture_path=(
            PROJECT_ROOT / "mlsys" / "training" / "fixtures"
            / "stage9_synthetic_public_training_v2.json"
        ),
        holdout_fixture_path=(
            PROJECT_ROOT / "mlsys" / "training" / "fixtures"
            / "stage9_synthetic_public_holdout_v2.json"
        ),
        governance_versions=governance,
    )
    repository = PostgresRepository(url)
    repository.open()
    try:
        repository.bootstrap_owner_and_identity(owner_id=OWNER, identity=identity)
        Stage9PostgresStore(repository=repository, owner_id=OWNER).persist_experiment(experiment)
    finally:
        repository.close()

    applied = apply_migrations(url, PROJECT_ROOT / "db" / "migrations")
    if applied != ["0032_stage9_rendered_membership_bijection.sql"]:
        raise AssertionError(f"expected only additive 0032, got {applied}")

    rendered = experiment.rendered_artifact
    run = experiment.training_runs[0]
    forged_artifact_id = uuid4()
    forged_run_id = uuid4()
    forged_artifact = rendered.model_dump(mode="json")
    forged_artifact["rendered_artifact_id"] = str(forged_artifact_id)
    forged_artifact["examples"] = [
        dict(forged_artifact["examples"][0]) for _ in forged_artifact["examples"]
    ]
    forged_artifact["content_hash"] = "sha256:" + "6" * 64
    forged_run = run.model_dump(mode="json")
    forged_run["training_run_id"] = str(forged_run_id)
    forged_run["rendered_artifact_id"] = str(forged_artifact_id)
    forged_run["content_hash"] = "sha256:" + "5" * 64
    rejection_sqlstate = None
    try:
        with psycopg.connect(url) as connection, connection.transaction():
            connection.execute(
                """
                INSERT INTO havre.rendered_training_artifacts (
                    rendered_artifact_id,schema_version,owner_id,dataset_snapshot_id,
                    model_version_id,renderer_version,tokenizer_version,
                    source_member_manifest_hash,contains_user_data,local_only,immutable,
                    payload,content_hash
                ) VALUES (%s,1,%s,%s,%s,'stage9-renderer-v1','hashed-tokenizer-v1',
                          %s,false,true,true,%s,%s)
                """,
                (
                    forged_artifact_id,OWNER,rendered.dataset_snapshot_id,
                    rendered.model_version_id,rendered.source_member_manifest_hash,
                    Jsonb(forged_artifact),forged_artifact["content_hash"],
                ),
            )
            connection.execute(
                """
                INSERT INTO havre.training_runs (
                    training_run_id,schema_version,owner_id,dataset_snapshot_id,
                    model_version_id,rendered_artifact_id,method,framework,seed,status,
                    candidate_only,governance_mutation_attempted,promotion_authorized,
                    deployment_authorized,used_user_data,local_only,cloud_transfer,
                    governance_versions,payload,content_hash,created_at
                ) VALUES (%s,1,%s,%s,%s,%s,%s,%s,%s,'completed_dry_run',true,false,
                          false,false,false,true,false,%s,%s,%s,%s)
                """,
                (
                    forged_run_id,OWNER,run.dataset_snapshot_id,run.model_version_id,
                    forged_artifact_id,run.config.method,run.config.framework,run.config.seed,
                    Jsonb(run.governance_versions.model_dump(mode="json")),Jsonb(forged_run),
                    forged_run["content_hash"],run.created_at,
                ),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    except psycopg.Error as error:
        rejection_sqlstate = error.sqlstate
    if rejection_sqlstate != "55000":
        raise AssertionError(f"forged artifact/run was not rejected with 55000: {rejection_sqlstate}")

    with psycopg.connect(url, row_factory=dict_row) as connection:
        result = connection.execute(
            """
            SELECT
                (SELECT count(*) FROM havre.rendered_training_artifacts
                 WHERE owner_id=%s) AS retained_artifacts,
                (SELECT count(*) FROM havre.training_runs WHERE owner_id=%s) AS retained_runs,
                (SELECT count(*) FROM havre.rendered_training_artifacts
                 WHERE rendered_artifact_id=%s) AS forged_artifacts,
                (SELECT count(*) FROM havre.training_runs
                 WHERE training_run_id=%s) AS forged_runs,
                (SELECT count(*) FROM havre.stage9_integrity_violations
                 WHERE owner_id=%s) AS integrity_violations
            """,
            (OWNER, OWNER, forged_artifact_id, forged_run_id, OWNER),
        ).fetchone()
    expected = {
        "retained_artifacts": 1,
        "retained_runs": 2,
        "forged_artifacts": 0,
        "forged_runs": 0,
        "integrity_violations": 0,
    }
    if dict(result) != expected:
        raise AssertionError(f"unexpected populated-upgrade result: {dict(result)}")
    print(json.dumps({
        "applied": applied,
        "rejection_sqlstate": rejection_sqlstate,
        **dict(result),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
