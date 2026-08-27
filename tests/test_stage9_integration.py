from __future__ import annotations

import os
import unittest
import uuid
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from companion.hashing import content_hash
from companion.identity import IdentityLoader
from companion.persistence import PostgresRepository, Stage9PostgresStore, apply_migrations
from mlsys.training import GovernanceVersionSet, run_stage9_synthetic_dry_run


DATABASE_URL = os.getenv("HAVRE_TEST_DATABASE_URL")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRAINING_FIXTURE = (
    PROJECT_ROOT / "mlsys" / "training" / "fixtures"
    / "stage9_synthetic_public_training_v2.json"
)
HOLDOUT_FIXTURE = (
    PROJECT_ROOT / "mlsys" / "training" / "fixtures"
    / "stage9_synthetic_public_holdout_v2.json"
)


@unittest.skipUnless(DATABASE_URL, "HAVRE_TEST_DATABASE_URL is required")
class Stage9PostgresIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        assert DATABASE_URL is not None
        apply_migrations(DATABASE_URL, PROJECT_ROOT / "db" / "migrations")
        cls.owner = uuid.uuid4()
        cls.repository = PostgresRepository(DATABASE_URL)
        cls.repository.open()
        identity = IdentityLoader(PROJECT_ROOT / "identity").load()
        cls.repository.bootstrap_owner_and_identity(owner_id=cls.owner, identity=identity)
        cls.governance = GovernanceVersionSet(
            constitution_version=identity.constitution.version_id,
            constitution_hash=identity.constitution.content_hash,
            identity_version=identity.identity.version_id,
            identity_hash=identity.identity.content_hash,
            values_version=identity.values.version_id,
            values_hash=identity.values.content_hash,
            intervention_policy_version="intervention-policy-sim-v1",
            intervention_policy_hash=content_hash({"version": "intervention-policy-sim-v1"}),
        )
        cls.experiment = run_stage9_synthetic_dry_run(
            owner_id=cls.owner, training_fixture_path=TRAINING_FIXTURE,
            holdout_fixture_path=HOLDOUT_FIXTURE, governance_versions=cls.governance,
        )
        cls.store = Stage9PostgresStore(repository=cls.repository, owner_id=cls.owner)
        with cls.repository.pool.connection() as connection:
            cls.identity_before = tuple(connection.execute(
                """
                SELECT artifact_kind,artifact_version_id,content_hash
                FROM havre.identity_artifact_versions WHERE owner_id=%s
                ORDER BY artifact_kind,artifact_version_id
                """,
                (cls.owner,),
            ).fetchall())
        cls.store.persist_experiment(cls.experiment)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.repository.close()

    def test_durable_registry_and_four_arm_evidence(self) -> None:
        with self.repository.pool.connection() as connection:
            counts = {
                table: connection.execute(
                    f"SELECT count(*) AS value FROM havre.{table} WHERE owner_id=%s",
                    (self.owner,),
                ).fetchone()["value"]
                for table in (
                    "training_dataset_snapshots", "training_dataset_members",
                    "evaluation_holdout_suites", "evaluation_holdout_cases",
                    "rendered_training_artifacts",
                    "model_versions", "training_runs", "adapter_versions",
                    "adapter_compatibility_reports", "personalization_evaluation_reports",
                    "adapter_rejection_records",
                )
            }
            violations = connection.execute(
                "SELECT count(*) AS value FROM havre.stage9_integrity_violations WHERE owner_id=%s",
                (self.owner,),
            ).fetchone()["value"]
        self.assertEqual(counts["training_dataset_snapshots"], 1)
        self.assertEqual(counts["training_dataset_members"], 6)
        self.assertEqual(counts["evaluation_holdout_suites"], 1)
        self.assertEqual(counts["evaluation_holdout_cases"], 2)
        self.assertEqual(counts["rendered_training_artifacts"], 1)
        self.assertEqual(counts["training_runs"], 2)
        self.assertEqual(counts["adapter_versions"], 2)
        self.assertEqual(counts["adapter_compatibility_reports"], 2)
        self.assertEqual(counts["personalization_evaluation_reports"], 1)
        self.assertEqual(counts["adapter_rejection_records"], 1)
        self.assertEqual(violations, 0)

    def test_training_and_rendered_artifacts_exclude_holdout_durably(self) -> None:
        with self.repository.pool.connection() as connection:
            split_counts = {
                row["split"]: row["value"] for row in connection.execute(
                """
                SELECT split,count(*) AS value FROM havre.training_dataset_members
                WHERE owner_id=%s AND dataset_snapshot_id=%s GROUP BY split
                """,
                (self.owner,self.experiment.snapshot.dataset_snapshot_id),
                ).fetchall()
            }
            rendered_ids = {
                row["example_id"] for row in connection.execute(
                    """
                    SELECT item->>'example_id' AS example_id
                    FROM havre.rendered_training_artifacts artifact,
                         jsonb_array_elements(artifact.payload->'examples') item
                    WHERE artifact.owner_id=%s AND artifact.rendered_artifact_id=%s
                    """,
                    (self.owner,self.experiment.rendered_artifact.rendered_artifact_id),
                ).fetchall()
            }
            holdout_rows = connection.execute(
                """
                SELECT example_id,training_eligible,evaluation_only,access_limited
                FROM havre.evaluation_holdout_cases
                WHERE owner_id=%s AND holdout_suite_id=%s
                """,
                (self.owner,self.experiment.holdout_suite.holdout_suite_id),
            ).fetchall()
        holdout_ids = {row["example_id"] for row in holdout_rows}
        self.assertEqual(split_counts, {"train": 4, "validation": 2})
        self.assertEqual(rendered_ids, {item.example_id for item in self.experiment.snapshot.examples})
        self.assertFalse(rendered_ids & holdout_ids)
        self.assertTrue(all(not row["training_eligible"] for row in holdout_rows))
        self.assertTrue(all(row["evaluation_only"] and row["access_limited"] for row in holdout_rows))

    def test_direct_sql_cannot_insert_holdout_into_training_members(self) -> None:
        case = self.experiment.holdout_suite.cases[0]
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
            with self.repository.pool.connection() as connection, connection.transaction():
                connection.execute(
                    """
                    INSERT INTO havre.training_dataset_members (
                        owner_id,dataset_snapshot_id,example_id,source_kind,source_ref,
                        license_id,split,training_eligible,contains_user_data,privacy_class,
                        content_hash,payload
                    ) VALUES (%s,%s,%s,%s,%s,'CC0-1.0','holdout',true,false,'PUBLIC',%s,%s)
                    """,
                    (
                        self.owner,self.experiment.snapshot.dataset_snapshot_id,
                        case.example_id,case.source_kind,case.source_ref,case.content_hash,
                        Jsonb({**case.model_dump(mode="json"),"training_eligible": True}),
                    ),
                )

    def test_direct_sql_cannot_render_a_holdout_case_as_training(self) -> None:
        rendered = self.experiment.rendered_artifact
        forged = rendered.model_dump(mode="json")
        holdout = self.experiment.holdout_suite.cases[0]
        forged["rendered_artifact_id"] = str(uuid.uuid4())
        forged["examples"].append({
            "example_id": holdout.example_id,
            "rendered_text": f"<user>{holdout.input_text}</user><assistant>{holdout.expected_text}</assistant>",
            "input_token_ids": [1], "target_token_ids": [1],
            "source_content_hash": holdout.content_hash,
        })
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
            with self.repository.pool.connection() as connection, connection.transaction():
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
                        uuid.UUID(forged["rendered_artifact_id"]),self.owner,
                        rendered.dataset_snapshot_id,rendered.model_version_id,
                        rendered.source_member_manifest_hash,Jsonb(forged),
                        "sha256:"+"7"*64,
                    ),
                )

    def test_direct_sql_rejects_duplicated_member_artifact_and_bound_run(self) -> None:
        rendered = self.experiment.rendered_artifact
        run = self.experiment.training_runs[0]
        forged_artifact_id = uuid.uuid4()
        forged_run_id = uuid.uuid4()
        forged_artifact = rendered.model_dump(mode="json")
        forged_artifact["rendered_artifact_id"] = str(forged_artifact_id)
        forged_artifact["examples"] = [
            dict(forged_artifact["examples"][0])
            for _ in forged_artifact["examples"]
        ]
        forged_artifact["content_hash"] = "sha256:" + "6" * 64
        forged_run = run.model_dump(mode="json")
        forged_run["training_run_id"] = str(forged_run_id)
        forged_run["rendered_artifact_id"] = str(forged_artifact_id)
        forged_run["content_hash"] = "sha256:" + "5" * 64

        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
            with self.repository.pool.connection() as connection, connection.transaction():
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
                        forged_artifact_id,self.owner,rendered.dataset_snapshot_id,
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
                        forged_run_id,self.owner,run.dataset_snapshot_id,run.model_version_id,
                        forged_artifact_id,run.config.method,run.config.framework,run.config.seed,
                        Jsonb(run.governance_versions.model_dump(mode="json")),
                        Jsonb(forged_run),forged_run["content_hash"],run.created_at,
                    ),
                )
                connection.execute("SET CONSTRAINTS ALL IMMEDIATE")

        with self.repository.pool.connection() as connection:
            artifact_count = connection.execute(
                """SELECT count(*) AS value FROM havre.rendered_training_artifacts
                   WHERE rendered_artifact_id=%s""",
                (forged_artifact_id,),
            ).fetchone()["value"]
            run_count = connection.execute(
                "SELECT count(*) AS value FROM havre.training_runs WHERE training_run_id=%s",
                (forged_run_id,),
            ).fetchone()["value"]
        self.assertEqual((artifact_count, run_count), (0, 0))

    def test_direct_sql_rejects_noncanonical_source_member_manifest(self) -> None:
        rendered = self.experiment.rendered_artifact
        forged_artifact_id = uuid.uuid4()
        forged_manifest = "sha256:" + "4" * 64
        forged = rendered.model_dump(mode="json")
        forged["rendered_artifact_id"] = str(forged_artifact_id)
        forged["source_member_manifest_hash"] = forged_manifest
        forged["content_hash"] = "sha256:" + "3" * 64
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
            with self.repository.pool.connection() as connection, connection.transaction():
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
                        forged_artifact_id,self.owner,rendered.dataset_snapshot_id,
                        rendered.model_version_id,forged_manifest,Jsonb(forged),
                        forged["content_hash"],
                    ),
                )
                connection.execute("SET CONSTRAINTS ALL IMMEDIATE")

        with self.repository.pool.connection() as connection:
            count = connection.execute(
                """SELECT count(*) AS value FROM havre.rendered_training_artifacts
                   WHERE rendered_artifact_id=%s""",
                (forged_artifact_id,),
            ).fetchone()["value"]
        self.assertEqual(count, 0)

    def test_training_eligible_false_cannot_be_inserted_directly(self) -> None:
        snapshot = self.experiment.snapshot
        with self.assertRaises(psycopg.errors.CheckViolation):
            with self.repository.pool.connection() as connection, connection.transaction():
                connection.execute(
                    """
                    INSERT INTO havre.training_dataset_members (
                        owner_id,dataset_snapshot_id,example_id,source_kind,source_ref,
                        license_id,split,training_eligible,contains_user_data,privacy_class,
                        content_hash,payload
                    ) VALUES (%s,%s,'forged-ineligible','synthetic_fixture',
                              'fixture://stage9/synthetic/forged-ineligible','CC0-1.0',
                              'train',false,false,'PUBLIC',%s,%s)
                    """,
                    (
                        self.owner, snapshot.dataset_snapshot_id, "sha256:" + "0" * 64,
                        Jsonb({"training_eligible": False, "contains_user_data": False,
                               "privacy_class": "PUBLIC"}),
                    ),
                )

    def test_promotion_deployment_and_base_hash_forgery_fail_direct_sql(self) -> None:
        adapter = self.experiment.adapters[0]
        with self.assertRaises(psycopg.errors.CheckViolation):
            with self.repository.pool.connection() as connection, connection.transaction():
                connection.execute(
                    """
                    INSERT INTO havre.adapter_versions (
                        adapter_version_id,schema_version,owner_id,adapter_type,
                        base_model_version_id,required_base_artifact_hash,dataset_snapshot_id,
                        training_run_id,artifact_uri,artifact_hash,lifecycle_status,candidate_only,
                        promotion_authorized,deployed,payload,content_hash
                    ) VALUES (%s,1,%s,%s,%s,%s,%s,%s,
                              'local-artifact://stage9/adapters/forged-promotion',%s,
                              'candidate',true,true,false,%s,%s)
                    """,
                    (
                        uuid.uuid4(), self.owner, adapter.adapter_type,
                        adapter.base_model_version_id, adapter.required_base_artifact_hash,
                        adapter.dataset_snapshot_id, adapter.training_run_id,
                        adapter.artifact_hash, Jsonb({"candidate_only": True,
                            "promotion_authorized": True, "deployed": False}),
                        "sha256:" + "1" * 64,
                    ),
                )
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            with self.repository.pool.connection() as connection, connection.transaction():
                connection.execute(
                    """
                    INSERT INTO havre.adapter_versions (
                        adapter_version_id,schema_version,owner_id,adapter_type,
                        base_model_version_id,required_base_artifact_hash,dataset_snapshot_id,
                        training_run_id,artifact_uri,artifact_hash,lifecycle_status,candidate_only,
                        promotion_authorized,deployed,payload,content_hash
                    ) VALUES (%s,1,%s,%s,%s,%s,%s,%s,
                              'local-artifact://stage9/adapters/forged-base',%s,
                              'candidate',true,false,false,%s,%s)
                    """,
                    (
                        uuid.uuid4(), self.owner, adapter.adapter_type,
                        adapter.base_model_version_id, "sha256:" + "9" * 64,
                        adapter.dataset_snapshot_id, adapter.training_run_id,
                        adapter.artifact_hash, Jsonb({"candidate_only": True,
                            "promotion_authorized": False, "deployed": False}),
                        "sha256:" + "2" * 64,
                    ),
                )

    def test_training_does_not_mutate_governance_or_history(self) -> None:
        with self.repository.pool.connection() as connection:
            identity_after = tuple(connection.execute(
                """
                SELECT artifact_kind,artifact_version_id,content_hash
                FROM havre.identity_artifact_versions WHERE owner_id=%s
                ORDER BY artifact_kind,artifact_version_id
                """,
                (self.owner,),
            ).fetchall())
            event_count = connection.execute(
                "SELECT count(*) AS value FROM havre.events WHERE owner_id=%s",
                (self.owner,),
            ).fetchone()["value"]
            non_fixture = connection.execute(
                """
                SELECT count(*) AS value FROM havre.training_dataset_members
                WHERE owner_id=%s AND source_ref NOT LIKE 'fixture://stage9/%%'
                """,
                (self.owner,),
            ).fetchone()["value"]
        self.assertEqual(self.identity_before, identity_after)
        self.assertEqual(event_count, 0)
        self.assertEqual(non_fixture, 0)

    def test_rejection_cannot_be_bound_to_a_different_adapter(self) -> None:
        other_adapter = self.experiment.adapters[0]
        evaluation = self.experiment.evaluation
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
            with self.repository.pool.connection() as connection, connection.transaction():
                connection.execute(
                    """
                    INSERT INTO havre.adapter_rejection_records (
                        rejection_id,schema_version,owner_id,adapter_version_id,
                        evaluation_report_id,reason_code,active_adapter_before,
                        active_adapter_after,persistent_identity_unchanged,
                        persistent_history_unchanged,rollback_effect,payload,content_hash,rejected_at
                    ) VALUES (%s,1,%s,%s,%s,'synthetic_dry_run_not_promotion_evidence',
                              NULL,NULL,true,true,'no_activation_to_rollback',%s,%s,clock_timestamp())
                    """,
                    (
                        uuid.uuid4(), self.owner, other_adapter.adapter_version_id,
                        evaluation.evaluation_report_id,
                        Jsonb({"forged": True}), "sha256:" + "8" * 64,
                    ),
                )
