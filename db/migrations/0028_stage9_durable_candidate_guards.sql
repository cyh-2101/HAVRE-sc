-- Durable Stage 9 cross-record compatibility, evaluation, and rejection binding.

CREATE FUNCTION havre.guard_stage9_compatibility_report()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM havre.adapter_versions adapter
        JOIN havre.model_versions model
          ON model.owner_id=adapter.owner_id
         AND model.model_version_id=adapter.base_model_version_id
         AND model.artifact_hash=adapter.required_base_artifact_hash
        WHERE adapter.owner_id=NEW.owner_id
          AND adapter.adapter_version_id=NEW.adapter_version_id
          AND model.model_version_id=NEW.model_version_id
          AND model.artifact_hash=NEW.checked_base_artifact_hash
    ) OR NEW.compatible <> true THEN
        RAISE EXCEPTION 'compatibility report does not match the exact adapter base'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END $$;

CREATE CONSTRAINT TRIGGER adapter_compatibility_durable_guard
AFTER INSERT ON havre.adapter_compatibility_reports
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION havre.guard_stage9_compatibility_report();

CREATE FUNCTION havre.guard_stage9_factorial_evaluation()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE arm_count integer;
BEGIN
    SELECT count(DISTINCT item->>'arm') INTO arm_count
    FROM jsonb_array_elements(NEW.payload->'arms') item
    WHERE item->>'arm' IN ('base','base_memory','base_adapter','base_memory_adapter');
    IF arm_count <> 4 OR NOT EXISTS (
        SELECT 1
        FROM havre.adapter_versions adapter
        JOIN havre.adapter_compatibility_reports compatibility
          ON compatibility.owner_id=adapter.owner_id
         AND compatibility.adapter_version_id=adapter.adapter_version_id
         AND compatibility.model_version_id=adapter.base_model_version_id
         AND compatibility.compatible=true
        WHERE adapter.owner_id=NEW.owner_id
          AND adapter.adapter_version_id=NEW.adapter_version_id
          AND adapter.base_model_version_id=NEW.model_version_id
          AND adapter.dataset_snapshot_id=NEW.dataset_snapshot_id
    ) THEN
        RAISE EXCEPTION 'factorial evaluation is not bound to one compatible candidate'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END $$;

CREATE CONSTRAINT TRIGGER personalization_evaluation_durable_guard
AFTER INSERT ON havre.personalization_evaluation_reports
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION havre.guard_stage9_factorial_evaluation();

CREATE FUNCTION havre.guard_stage9_adapter_rejection()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM havre.personalization_evaluation_reports evaluation
        WHERE evaluation.owner_id=NEW.owner_id
          AND evaluation.evaluation_report_id=NEW.evaluation_report_id
          AND evaluation.adapter_version_id=NEW.adapter_version_id
          AND evaluation.release_promotion_authorized=false
    ) THEN
        RAISE EXCEPTION 'adapter rejection must bind the exact evaluated adapter'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END $$;

CREATE CONSTRAINT TRIGGER adapter_rejection_durable_guard
AFTER INSERT ON havre.adapter_rejection_records
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION havre.guard_stage9_adapter_rejection();

CREATE OR REPLACE VIEW havre.stage9_integrity_violations AS
SELECT run.training_run_id AS violation_id, run.owner_id,
       'training_run_without_safe_canonical_members'::text AS violation_code
FROM havre.training_runs run
WHERE NOT EXISTS (
    SELECT 1 FROM havre.training_dataset_members member
    WHERE member.owner_id=run.owner_id AND member.dataset_snapshot_id=run.dataset_snapshot_id
)
UNION ALL
SELECT run.training_run_id, run.owner_id, 'training_run_missing_rendered_artifact'
FROM havre.training_runs run
WHERE run.rendered_artifact_id IS NULL
   OR NOT EXISTS (
       SELECT 1 FROM havre.rendered_training_artifacts artifact
       WHERE artifact.owner_id=run.owner_id
         AND artifact.rendered_artifact_id=run.rendered_artifact_id
         AND artifact.dataset_snapshot_id=run.dataset_snapshot_id
         AND artifact.model_version_id=run.model_version_id
   )
UNION ALL
SELECT compatibility.compatibility_report_id, compatibility.owner_id,
       'compatibility_report_base_mismatch'
FROM havre.adapter_compatibility_reports compatibility
WHERE compatibility.compatible <> true OR NOT EXISTS (
    SELECT 1 FROM havre.adapter_versions adapter
    WHERE adapter.owner_id=compatibility.owner_id
      AND adapter.adapter_version_id=compatibility.adapter_version_id
      AND adapter.base_model_version_id=compatibility.model_version_id
      AND adapter.required_base_artifact_hash=compatibility.checked_base_artifact_hash
)
UNION ALL
SELECT evaluation.evaluation_report_id, evaluation.owner_id,
       'factorial_evaluation_candidate_mismatch'
FROM havre.personalization_evaluation_reports evaluation
WHERE NOT EXISTS (
    SELECT 1 FROM havre.adapter_versions adapter
    WHERE adapter.owner_id=evaluation.owner_id
      AND adapter.adapter_version_id=evaluation.adapter_version_id
      AND adapter.base_model_version_id=evaluation.model_version_id
      AND adapter.dataset_snapshot_id=evaluation.dataset_snapshot_id
)
UNION ALL
SELECT adapter.adapter_version_id, adapter.owner_id,
       'candidate_adapter_missing_rejection'
FROM havre.adapter_versions adapter
WHERE adapter.adapter_type='qlora'
  AND NOT EXISTS (
      SELECT 1 FROM havre.adapter_rejection_records rejection
      WHERE rejection.owner_id=adapter.owner_id
        AND rejection.adapter_version_id=adapter.adapter_version_id
  )
UNION ALL
SELECT rejection.rejection_id, rejection.owner_id,
       'adapter_rejection_evaluation_mismatch'
FROM havre.adapter_rejection_records rejection
WHERE NOT EXISTS (
    SELECT 1 FROM havre.personalization_evaluation_reports evaluation
    WHERE evaluation.owner_id=rejection.owner_id
      AND evaluation.evaluation_report_id=rejection.evaluation_report_id
      AND evaluation.adapter_version_id=rejection.adapter_version_id
);
