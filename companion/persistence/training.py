"""PostgreSQL persistence for the Stage 9 candidate-only dry-run foundation."""

from __future__ import annotations

from uuid import UUID

from psycopg.types.json import Jsonb

from companion.persistence.postgres import PostgresRepository
from mlsys.training import Stage9Experiment


class Stage9PostgresStore:
    def __init__(self, *, repository: PostgresRepository, owner_id: UUID) -> None:
        self.repository = repository
        self.owner_id = owner_id

    def _assert_owner(self, experiment: Stage9Experiment) -> None:
        records = (
            experiment.snapshot,
            experiment.holdout_suite,
            experiment.model,
            experiment.rendered_artifact,
            *experiment.training_runs,
            *experiment.adapters,
            *experiment.compatibility_reports,
            experiment.evaluation,
            experiment.rejection,
        )
        if any(record.owner_id != self.owner_id for record in records):
            raise ValueError("Stage 9 records must be bound to one owner")

    def persist_experiment(self, experiment: Stage9Experiment) -> None:
        self._assert_owner(experiment)
        if {run.config.method for run in experiment.training_runs} != {"lora", "qlora"}:
            raise ValueError("Stage 9 dry-run requires both LoRA and QLoRA")
        if any(not report.compatible for report in experiment.compatibility_reports):
            raise ValueError("incompatible adapters cannot enter candidate evaluation")
        training_ids = {example.example_id for example in experiment.snapshot.examples}
        holdout_ids = {case.example_id for case in experiment.holdout_suite.cases}
        if training_ids & holdout_ids:
            raise ValueError("evaluation holdout cannot enter the training snapshot")
        if holdout_ids != set(experiment.snapshot.excluded_evaluation_holdout_ids):
            raise ValueError("training snapshot exclusion manifest does not match holdout suite")
        if experiment.holdout_suite.member_manifest_hash != (
            experiment.snapshot.excluded_evaluation_holdout_manifest_hash
        ):
            raise ValueError("training snapshot is not bound to the exact holdout manifest")
        rendered_ids = {
            example.example_id for example in experiment.rendered_artifact.examples
        }
        if rendered_ids != training_ids or rendered_ids & holdout_ids:
            raise ValueError("rendered training artifact must equal training members only")
        if experiment.rendered_artifact.source_member_manifest_hash != (
            experiment.snapshot.member_manifest_hash
        ):
            raise ValueError("rendered training artifact must bind the exact member manifest")
        with self.repository.pool.connection() as connection, connection.transaction():
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"stage9-owner:{self.owner_id}",),
            )
            expected = experiment.training_runs[0].governance_versions
            identity_rows = connection.execute(
                """
                SELECT artifact_kind, artifact_version_id, content_hash
                FROM havre.identity_artifact_versions
                WHERE owner_id=%s
                """,
                (self.owner_id,),
            ).fetchall()
            identities = {
                (row["artifact_kind"], row["artifact_version_id"], row["content_hash"])
                for row in identity_rows
            }
            required = {
                ("constitution", expected.constitution_version, expected.constitution_hash),
                ("identity", expected.identity_version, expected.identity_hash),
                ("values", expected.values_version, expected.values_hash),
            }
            if not required.issubset(identities):
                raise ValueError("training run governance pins do not match durable identity artifacts")
            if any(run.governance_versions != expected for run in experiment.training_runs):
                raise ValueError("training runs must pin one unchanged governance version set")

            snapshot = experiment.snapshot
            connection.execute(
                """
                INSERT INTO havre.training_dataset_snapshots (
                    dataset_snapshot_id,schema_version,owner_id,name,semantic_version,
                    builder_version,split_policy_version,fixture_content_hash,
                    member_manifest_hash,excluded_holdout_manifest_hash,
                    user_event_source_count,contains_user_data,
                    local_only_build,immutable,payload,content_hash,created_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,false,true,true,%s,%s,%s)
                """,
                (
                    snapshot.dataset_snapshot_id, snapshot.schema_version, self.owner_id,
                    snapshot.name, snapshot.semantic_version, snapshot.builder_version,
                    snapshot.split_policy_version, snapshot.fixture_content_hash,
                    snapshot.member_manifest_hash,
                    snapshot.excluded_evaluation_holdout_manifest_hash,
                    Jsonb(snapshot.model_dump(mode="json")),
                    snapshot.content_hash, snapshot.created_at,
                ),
            )
            connection.cursor().executemany(
                """
                INSERT INTO havre.training_dataset_members (
                    owner_id,dataset_snapshot_id,example_id,source_kind,source_ref,
                    license_id,split,training_eligible,contains_user_data,privacy_class,
                    content_hash,payload
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,true,false,'PUBLIC',%s,%s)
                """,
                [
                    (
                        self.owner_id, snapshot.dataset_snapshot_id, example.example_id,
                        example.source_kind, example.source_ref, example.license_id,
                        example.split, example.content_hash,
                        Jsonb(example.model_dump(mode="json")),
                    )
                    for example in snapshot.examples
                ],
            )
            holdout = experiment.holdout_suite
            connection.execute(
                """
                INSERT INTO havre.evaluation_holdout_suites (
                    holdout_suite_id,schema_version,owner_id,dataset_snapshot_id,
                    fixture_content_hash,member_manifest_hash,purpose,training_eligible,
                    access_limited,local_only,immutable,payload,content_hash
                ) VALUES (%s,%s,%s,%s,%s,%s,'evaluation_holdout',false,true,true,true,%s,%s)
                """,
                (
                    holdout.holdout_suite_id, holdout.schema_version, self.owner_id,
                    holdout.dataset_snapshot_id, holdout.fixture_content_hash,
                    holdout.member_manifest_hash,
                    Jsonb(holdout.model_dump(mode="json")), holdout.content_hash,
                ),
            )
            connection.cursor().executemany(
                """
                INSERT INTO havre.evaluation_holdout_cases (
                    owner_id,holdout_suite_id,example_id,source_ref,training_eligible,
                    evaluation_only,access_limited,contains_user_data,privacy_class,
                    content_hash,payload
                ) VALUES (%s,%s,%s,%s,false,true,true,false,'PUBLIC',%s,%s)
                """,
                [
                    (
                        self.owner_id, holdout.holdout_suite_id, case.example_id,
                        case.source_ref, case.content_hash,
                        Jsonb(case.model_dump(mode="json")),
                    )
                    for case in holdout.cases
                ],
            )
            model = experiment.model
            connection.execute(
                """
                INSERT INTO havre.model_versions (
                    model_version_id,schema_version,owner_id,logical_name,upstream_model_id,
                    upstream_revision,artifact_uri,artifact_hash,tokenizer_version,
                    lifecycle_status,local_only,production_eligible,payload,content_hash
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'candidate',true,false,%s,%s)
                """,
                (
                    model.model_version_id, model.schema_version, self.owner_id,
                    model.logical_name, model.upstream_model_id, model.upstream_revision,
                    model.artifact_uri, model.artifact_hash, model.tokenizer_version,
                    Jsonb(model.model_dump(mode="json")), model.content_hash,
                ),
            )
            rendered = experiment.rendered_artifact
            connection.execute(
                """
                INSERT INTO havre.rendered_training_artifacts (
                    rendered_artifact_id,schema_version,owner_id,dataset_snapshot_id,
                    model_version_id,renderer_version,tokenizer_version,
                    source_member_manifest_hash,contains_user_data,local_only,immutable,
                    payload,content_hash
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,false,true,true,%s,%s)
                """,
                (
                    rendered.rendered_artifact_id, rendered.schema_version, self.owner_id,
                    rendered.dataset_snapshot_id, rendered.model_version_id,
                    rendered.renderer_version, rendered.tokenizer_version,
                    rendered.source_member_manifest_hash,
                    Jsonb(rendered.model_dump(mode="json")), rendered.content_hash,
                ),
            )
            for run in experiment.training_runs:
                connection.execute(
                    """
                    INSERT INTO havre.training_runs (
                        training_run_id,schema_version,owner_id,dataset_snapshot_id,
                        model_version_id,rendered_artifact_id,method,framework,seed,status,candidate_only,
                        governance_mutation_attempted,promotion_authorized,deployment_authorized,
                        used_user_data,local_only,cloud_transfer,governance_versions,payload,
                        content_hash,created_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'completed_dry_run',true,false,
                              false,false,false,true,false,%s,%s,%s,%s)
                    """,
                    (
                        run.training_run_id, run.schema_version, self.owner_id,
                        run.dataset_snapshot_id, run.model_version_id, run.rendered_artifact_id,
                        run.config.method, run.config.framework, run.config.seed,
                        Jsonb(run.governance_versions.model_dump(mode="json")),
                        Jsonb(run.model_dump(mode="json")), run.content_hash, run.created_at,
                    ),
                )
            for adapter in experiment.adapters:
                connection.execute(
                    """
                    INSERT INTO havre.adapter_versions (
                        adapter_version_id,schema_version,owner_id,adapter_type,
                        base_model_version_id,required_base_artifact_hash,dataset_snapshot_id,
                        training_run_id,artifact_uri,artifact_hash,lifecycle_status,candidate_only,
                        promotion_authorized,deployed,payload,content_hash
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'candidate',true,false,false,%s,%s)
                    """,
                    (
                        adapter.adapter_version_id, adapter.schema_version, self.owner_id,
                        adapter.adapter_type, adapter.base_model_version_id,
                        adapter.required_base_artifact_hash, adapter.dataset_snapshot_id,
                        adapter.training_run_id, adapter.artifact_uri, adapter.artifact_hash,
                        Jsonb(adapter.model_dump(mode="json")), adapter.content_hash,
                    ),
                )
            for report in experiment.compatibility_reports:
                connection.execute(
                    """
                    INSERT INTO havre.adapter_compatibility_reports (
                        compatibility_report_id,schema_version,owner_id,adapter_version_id,
                        model_version_id,checked_base_artifact_hash,compatible,load_performed,
                        payload,content_hash
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,false,%s,%s)
                    """,
                    (
                        report.compatibility_report_id, report.schema_version, self.owner_id,
                        report.adapter_version_id, report.model_version_id,
                        report.checked_base_artifact_hash, report.compatible,
                        Jsonb(report.model_dump(mode="json")), report.content_hash,
                    ),
                )
            evaluation = experiment.evaluation
            connection.execute(
                """
                INSERT INTO havre.personalization_evaluation_reports (
                    evaluation_report_id,schema_version,owner_id,dataset_snapshot_id,
                    holdout_suite_id,
                    model_version_id,adapter_version_id,arm_count,human_benefit_claimed,
                    release_promotion_authorized,payload,content_hash
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,4,false,false,%s,%s)
                """,
                (
                    evaluation.evaluation_report_id, evaluation.schema_version, self.owner_id,
                    evaluation.dataset_snapshot_id, evaluation.holdout_suite_id,
                    evaluation.model_version_id,
                    evaluation.adapter_version_id, Jsonb(evaluation.model_dump(mode="json")),
                    evaluation.content_hash,
                ),
            )
            rejection = experiment.rejection
            connection.execute(
                """
                INSERT INTO havre.adapter_rejection_records (
                    rejection_id,schema_version,owner_id,adapter_version_id,evaluation_report_id,
                    reason_code,active_adapter_before,active_adapter_after,
                    persistent_identity_unchanged,persistent_history_unchanged,rollback_effect,
                    payload,content_hash,rejected_at
                ) VALUES (%s,%s,%s,%s,%s,%s,NULL,NULL,true,true,%s,%s,%s,%s)
                """,
                (
                    rejection.rejection_id, rejection.schema_version, self.owner_id,
                    rejection.adapter_version_id, rejection.evaluation_report_id,
                    rejection.reason_code, rejection.rollback_effect,
                    Jsonb(rejection.model_dump(mode="json")), rejection.content_hash,
                    rejection.rejected_at,
                ),
            )
