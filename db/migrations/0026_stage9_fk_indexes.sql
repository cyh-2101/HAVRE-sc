-- Stage 9 child-side foreign-key indexes for bounded owner-scoped checks.

CREATE INDEX training_runs_owner_dataset_idx
    ON havre.training_runs(owner_id, dataset_snapshot_id);
CREATE INDEX training_runs_owner_model_idx
    ON havre.training_runs(owner_id, model_version_id);
CREATE INDEX adapter_versions_owner_base_idx
    ON havre.adapter_versions(owner_id, base_model_version_id, required_base_artifact_hash);
CREATE INDEX adapter_versions_owner_training_idx
    ON havre.adapter_versions(
        owner_id, training_run_id, dataset_snapshot_id, base_model_version_id, adapter_type
    );
CREATE INDEX adapter_compatibility_owner_adapter_idx
    ON havre.adapter_compatibility_reports(owner_id, adapter_version_id);
CREATE INDEX adapter_compatibility_owner_model_idx
    ON havre.adapter_compatibility_reports(
        owner_id, model_version_id, checked_base_artifact_hash
    );
CREATE INDEX personalization_eval_owner_dataset_idx
    ON havre.personalization_evaluation_reports(owner_id, dataset_snapshot_id);
CREATE INDEX personalization_eval_owner_model_idx
    ON havre.personalization_evaluation_reports(owner_id, model_version_id);
CREATE INDEX personalization_eval_owner_adapter_idx
    ON havre.personalization_evaluation_reports(owner_id, adapter_version_id);
CREATE INDEX adapter_rejection_owner_eval_idx
    ON havre.adapter_rejection_records(owner_id, evaluation_report_id);
CREATE INDEX rendered_training_owner_dataset_idx
    ON havre.rendered_training_artifacts(owner_id, dataset_snapshot_id);
CREATE INDEX rendered_training_owner_model_idx
    ON havre.rendered_training_artifacts(owner_id, model_version_id);
