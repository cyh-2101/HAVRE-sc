-- Reject the initial Stage 9 candidate trust boundary and separate evaluation holdout.

CREATE TABLE havre.stage9_candidate_invalidations (
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    dataset_snapshot_id uuid NOT NULL,
    reason_code text NOT NULL CHECK (reason_code = 'evaluation_holdout_in_training_snapshot_v1'),
    invalidated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (owner_id, dataset_snapshot_id),
    FOREIGN KEY (owner_id, dataset_snapshot_id)
        REFERENCES havre.training_dataset_snapshots(owner_id, dataset_snapshot_id)
);

INSERT INTO havre.stage9_candidate_invalidations (
    owner_id,dataset_snapshot_id,reason_code
)
SELECT DISTINCT owner_id,dataset_snapshot_id,
       'evaluation_holdout_in_training_snapshot_v1'
FROM havre.training_dataset_members
WHERE split='holdout';

CREATE TABLE havre.evaluation_holdout_suites (
    holdout_suite_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version=1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    dataset_snapshot_id uuid NOT NULL,
    fixture_content_hash text NOT NULL CHECK (fixture_content_hash ~ '^sha256:[0-9a-f]{64}$'),
    member_manifest_hash text NOT NULL CHECK (member_manifest_hash ~ '^sha256:[0-9a-f]{64}$'),
    purpose text NOT NULL CHECK (purpose='evaluation_holdout'),
    training_eligible boolean NOT NULL CHECK (training_eligible=false),
    access_limited boolean NOT NULL CHECK (access_limited=true),
    local_only boolean NOT NULL CHECK (local_only=true),
    immutable boolean NOT NULL CHECK (immutable=true),
    payload jsonb NOT NULL CHECK (
        jsonb_typeof(payload)='object'
        AND jsonb_typeof(payload->'cases')='array'
        AND jsonb_array_length(payload->'cases') > 0
        AND (payload->>'training_eligible')::boolean=false
        AND (payload->>'access_limited')::boolean=true
    ),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    UNIQUE (owner_id,holdout_suite_id),
    UNIQUE (owner_id,holdout_suite_id,dataset_snapshot_id),
    UNIQUE (owner_id,dataset_snapshot_id),
    FOREIGN KEY (owner_id,dataset_snapshot_id)
        REFERENCES havre.training_dataset_snapshots(owner_id,dataset_snapshot_id)
);

CREATE TABLE havre.evaluation_holdout_cases (
    owner_id uuid NOT NULL,
    holdout_suite_id uuid NOT NULL,
    example_id text NOT NULL CHECK (example_id ~ '^[a-z0-9][a-z0-9_-]{2,79}$'),
    source_ref text NOT NULL CHECK (source_ref ~ '^fixture://stage9/[a-z0-9/_-]+$'),
    training_eligible boolean NOT NULL CHECK (training_eligible=false),
    evaluation_only boolean NOT NULL CHECK (evaluation_only=true),
    access_limited boolean NOT NULL CHECK (access_limited=true),
    contains_user_data boolean NOT NULL CHECK (contains_user_data=false),
    privacy_class text NOT NULL CHECK (privacy_class='PUBLIC'),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    payload jsonb NOT NULL CHECK (
        jsonb_typeof(payload)='object'
        AND payload->>'split'='holdout'
        AND (payload->>'training_eligible')::boolean=false
        AND (payload->>'evaluation_only')::boolean=true
        AND (payload->>'access_limited')::boolean=true
    ),
    PRIMARY KEY (owner_id,holdout_suite_id,example_id),
    UNIQUE (owner_id,holdout_suite_id,source_ref),
    FOREIGN KEY (owner_id,holdout_suite_id)
        REFERENCES havre.evaluation_holdout_suites(owner_id,holdout_suite_id)
);

ALTER TABLE havre.training_dataset_snapshots
    ADD COLUMN excluded_holdout_manifest_hash text NULL
    CHECK (excluded_holdout_manifest_hash IS NULL OR excluded_holdout_manifest_hash ~ '^sha256:[0-9a-f]{64}$');

ALTER TABLE havre.personalization_evaluation_reports
    ADD COLUMN holdout_suite_id uuid NULL;
ALTER TABLE havre.personalization_evaluation_reports
    ADD CONSTRAINT personalization_evaluation_holdout_fk
    FOREIGN KEY (owner_id,holdout_suite_id,dataset_snapshot_id)
    REFERENCES havre.evaluation_holdout_suites(owner_id,holdout_suite_id,dataset_snapshot_id);

CREATE FUNCTION havre.reject_stage9_training_holdout()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.split='holdout' OR NEW.payload->>'split'='holdout' THEN
        RAISE EXCEPTION 'evaluation holdout cannot enter training dataset membership'
            USING ERRCODE='55000';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER training_dataset_members_reject_holdout
BEFORE INSERT ON havre.training_dataset_members
FOR EACH ROW EXECUTE FUNCTION havre.reject_stage9_training_holdout();

CREATE OR REPLACE FUNCTION havre.guard_stage9_dataset_snapshot()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE linked_count integer; payload_count integer; excluded_count integer;
BEGIN
    SELECT count(*) INTO linked_count FROM havre.training_dataset_members
    WHERE owner_id=NEW.owner_id AND dataset_snapshot_id=NEW.dataset_snapshot_id;
    payload_count := jsonb_array_length(NEW.payload->'examples');
    excluded_count := jsonb_array_length(NEW.payload->'excluded_evaluation_holdout_ids');
    IF payload_count IS NULL OR linked_count <> payload_count OR linked_count < 4
       OR excluded_count IS NULL OR excluded_count < 1
       OR NEW.excluded_holdout_manifest_hash IS NULL
       OR NEW.excluded_holdout_manifest_hash <>
          NEW.payload->>'excluded_evaluation_holdout_manifest_hash' THEN
        RAISE EXCEPTION 'Stage 9 training snapshot lacks exact holdout exclusion evidence'
            USING ERRCODE='55000';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM havre.training_dataset_members WHERE owner_id=NEW.owner_id AND dataset_snapshot_id=NEW.dataset_snapshot_id AND split='train')
       OR NOT EXISTS (SELECT 1 FROM havre.training_dataset_members WHERE owner_id=NEW.owner_id AND dataset_snapshot_id=NEW.dataset_snapshot_id AND split='validation')
       OR EXISTS (SELECT 1 FROM havre.training_dataset_members WHERE owner_id=NEW.owner_id AND dataset_snapshot_id=NEW.dataset_snapshot_id AND split='holdout') THEN
        RAISE EXCEPTION 'training snapshot requires train/validation and forbids holdout'
            USING ERRCODE='55000';
    END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(NEW.payload->'examples') item
        WHERE item->>'split'='holdout' OR NOT EXISTS (
            SELECT 1 FROM havre.training_dataset_members member
            WHERE member.owner_id=NEW.owner_id
              AND member.dataset_snapshot_id=NEW.dataset_snapshot_id
              AND member.example_id=item->>'example_id'
              AND member.content_hash=item->>'content_hash'
              AND member.source_ref=item->>'source_ref'
              AND member.split=item->>'split'
        )
    ) THEN
        RAISE EXCEPTION 'training snapshot payload is not exact holdout-free membership'
            USING ERRCODE='55000';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM havre.evaluation_holdout_suites suite
        WHERE suite.owner_id=NEW.owner_id
          AND suite.dataset_snapshot_id=NEW.dataset_snapshot_id
          AND suite.member_manifest_hash=NEW.excluded_holdout_manifest_hash
          AND (SELECT count(*) FROM havre.evaluation_holdout_cases c
               WHERE c.owner_id=suite.owner_id AND c.holdout_suite_id=suite.holdout_suite_id)=excluded_count
          AND NOT EXISTS (
              SELECT 1 FROM jsonb_array_elements_text(
                  NEW.payload->'excluded_evaluation_holdout_ids'
              ) excluded(id)
              WHERE NOT EXISTS (
                  SELECT 1 FROM havre.evaluation_holdout_cases c
                  WHERE c.owner_id=suite.owner_id
                    AND c.holdout_suite_id=suite.holdout_suite_id
                    AND c.example_id=excluded.id
              )
          )
    ) THEN
        RAISE EXCEPTION 'excluded holdout manifest lacks separate evaluation suite'
            USING ERRCODE='55000';
    END IF;
    RETURN NEW;
END $$;

CREATE FUNCTION havre.guard_stage9_rendered_training_artifact()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE linked_count integer; rendered_count integer;
BEGIN
    SELECT count(*) INTO linked_count FROM havre.training_dataset_members
    WHERE owner_id=NEW.owner_id AND dataset_snapshot_id=NEW.dataset_snapshot_id;
    rendered_count := jsonb_array_length(NEW.payload->'examples');
    IF rendered_count IS NULL OR rendered_count <> linked_count OR EXISTS (
        SELECT 1 FROM jsonb_array_elements(NEW.payload->'examples') item
        WHERE NOT EXISTS (
            SELECT 1 FROM havre.training_dataset_members member
            WHERE member.owner_id=NEW.owner_id
              AND member.dataset_snapshot_id=NEW.dataset_snapshot_id
              AND member.example_id=item->>'example_id'
              AND member.content_hash=item->>'source_content_hash'
              AND item->>'rendered_text' =
                  '<user>' || (member.payload->>'input_text') ||
                  '</user><assistant>' || (member.payload->>'expected_text') || '</assistant>'
        )
    ) THEN
        RAISE EXCEPTION 'rendered artifact is not exact training-only membership'
            USING ERRCODE='55000';
    END IF;
    RETURN NEW;
END $$;

CREATE CONSTRAINT TRIGGER rendered_training_artifact_membership_guard
AFTER INSERT ON havre.rendered_training_artifacts
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION havre.guard_stage9_rendered_training_artifact();

CREATE OR REPLACE FUNCTION havre.guard_stage9_training_run_rendering()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.rendered_artifact_id IS NULL OR EXISTS (
        SELECT 1 FROM havre.stage9_candidate_invalidations invalidation
        WHERE invalidation.owner_id=NEW.owner_id
          AND invalidation.dataset_snapshot_id=NEW.dataset_snapshot_id
    ) THEN
        RAISE EXCEPTION 'Stage 9 training run requires valid holdout-free rendered artifact'
            USING ERRCODE='55000';
    END IF;
    RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION havre.guard_stage9_factorial_evaluation()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE arm_count integer;
BEGIN
    SELECT count(DISTINCT item->>'arm') INTO arm_count
    FROM jsonb_array_elements(NEW.payload->'arms') item
    WHERE item->>'arm' IN ('base','base_memory','base_adapter','base_memory_adapter');
    IF arm_count <> 4 OR NEW.holdout_suite_id IS NULL
       OR (NEW.payload->>'holdout_suite_id')::uuid <> NEW.holdout_suite_id
       OR NOT EXISTS (
           SELECT 1 FROM havre.evaluation_holdout_suites suite
           WHERE suite.owner_id=NEW.owner_id
             AND suite.holdout_suite_id=NEW.holdout_suite_id
             AND suite.dataset_snapshot_id=NEW.dataset_snapshot_id
             AND suite.training_eligible=false
             AND suite.access_limited=true
       ) OR NOT EXISTS (
           SELECT 1 FROM havre.adapter_versions adapter
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
        RAISE EXCEPTION 'factorial evaluation lacks separate exact holdout suite'
            USING ERRCODE='55000';
    END IF;
    RETURN NEW;
END $$;

CREATE INDEX evaluation_holdout_cases_owner_suite_idx
    ON havre.evaluation_holdout_cases(owner_id,holdout_suite_id);
CREATE INDEX personalization_eval_owner_holdout_idx
    ON havre.personalization_evaluation_reports(
        owner_id,holdout_suite_id,dataset_snapshot_id
    );
CREATE INDEX stage9_invalidations_owner_snapshot_idx
    ON havre.stage9_candidate_invalidations(owner_id,dataset_snapshot_id);

CREATE TRIGGER stage9_candidate_invalidations_immutable
BEFORE UPDATE OR DELETE ON havre.stage9_candidate_invalidations
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();
CREATE TRIGGER evaluation_holdout_suites_immutable
BEFORE UPDATE OR DELETE ON havre.evaluation_holdout_suites
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();
CREATE TRIGGER evaluation_holdout_cases_immutable
BEFORE UPDATE OR DELETE ON havre.evaluation_holdout_cases
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();

CREATE OR REPLACE VIEW havre.stage9_integrity_violations AS
SELECT run.training_run_id AS violation_id,run.owner_id,
       'training_run_without_safe_canonical_members'::text AS violation_code
FROM havre.training_runs run
WHERE NOT EXISTS (SELECT 1 FROM havre.stage9_candidate_invalidations i
                  WHERE i.owner_id=run.owner_id AND i.dataset_snapshot_id=run.dataset_snapshot_id)
  AND NOT EXISTS (SELECT 1 FROM havre.training_dataset_members m
                  WHERE m.owner_id=run.owner_id AND m.dataset_snapshot_id=run.dataset_snapshot_id)
UNION ALL
SELECT snapshot.dataset_snapshot_id,snapshot.owner_id,'training_snapshot_contains_holdout'
FROM havre.training_dataset_snapshots snapshot
WHERE NOT EXISTS (SELECT 1 FROM havre.stage9_candidate_invalidations i
                  WHERE i.owner_id=snapshot.owner_id AND i.dataset_snapshot_id=snapshot.dataset_snapshot_id)
  AND (snapshot.excluded_holdout_manifest_hash IS NULL OR EXISTS (
      SELECT 1 FROM havre.training_dataset_members m
      WHERE m.owner_id=snapshot.owner_id AND m.dataset_snapshot_id=snapshot.dataset_snapshot_id
        AND m.split='holdout'))
UNION ALL
SELECT run.training_run_id,run.owner_id,'training_run_missing_rendered_artifact'
FROM havre.training_runs run
WHERE NOT EXISTS (SELECT 1 FROM havre.stage9_candidate_invalidations i
                  WHERE i.owner_id=run.owner_id AND i.dataset_snapshot_id=run.dataset_snapshot_id)
  AND (run.rendered_artifact_id IS NULL OR NOT EXISTS (
      SELECT 1 FROM havre.rendered_training_artifacts a
      WHERE a.owner_id=run.owner_id AND a.rendered_artifact_id=run.rendered_artifact_id
        AND a.dataset_snapshot_id=run.dataset_snapshot_id AND a.model_version_id=run.model_version_id))
UNION ALL
SELECT compatibility.compatibility_report_id,compatibility.owner_id,'compatibility_report_base_mismatch'
FROM havre.adapter_compatibility_reports compatibility
WHERE compatibility.compatible<>true OR NOT EXISTS (
    SELECT 1 FROM havre.adapter_versions adapter
    WHERE adapter.owner_id=compatibility.owner_id
      AND adapter.adapter_version_id=compatibility.adapter_version_id
      AND adapter.base_model_version_id=compatibility.model_version_id
      AND adapter.required_base_artifact_hash=compatibility.checked_base_artifact_hash)
UNION ALL
SELECT evaluation.evaluation_report_id,evaluation.owner_id,'factorial_evaluation_holdout_or_candidate_mismatch'
FROM havre.personalization_evaluation_reports evaluation
WHERE NOT EXISTS (SELECT 1 FROM havre.stage9_candidate_invalidations i
                  WHERE i.owner_id=evaluation.owner_id AND i.dataset_snapshot_id=evaluation.dataset_snapshot_id)
  AND (evaluation.holdout_suite_id IS NULL OR NOT EXISTS (
      SELECT 1 FROM havre.evaluation_holdout_suites suite
      WHERE suite.owner_id=evaluation.owner_id
        AND suite.holdout_suite_id=evaluation.holdout_suite_id
        AND suite.dataset_snapshot_id=evaluation.dataset_snapshot_id))
UNION ALL
SELECT adapter.adapter_version_id,adapter.owner_id,'candidate_adapter_missing_rejection'
FROM havre.adapter_versions adapter
WHERE adapter.adapter_type='qlora'
  AND NOT EXISTS (SELECT 1 FROM havre.stage9_candidate_invalidations i
                  WHERE i.owner_id=adapter.owner_id AND i.dataset_snapshot_id=adapter.dataset_snapshot_id)
  AND NOT EXISTS (SELECT 1 FROM havre.adapter_rejection_records rejection
                  WHERE rejection.owner_id=adapter.owner_id
                    AND rejection.adapter_version_id=adapter.adapter_version_id)
UNION ALL
SELECT rejection.rejection_id,rejection.owner_id,'adapter_rejection_evaluation_mismatch'
FROM havre.adapter_rejection_records rejection
JOIN havre.adapter_versions adapter
  ON adapter.owner_id=rejection.owner_id AND adapter.adapter_version_id=rejection.adapter_version_id
WHERE NOT EXISTS (SELECT 1 FROM havre.stage9_candidate_invalidations i
                  WHERE i.owner_id=adapter.owner_id AND i.dataset_snapshot_id=adapter.dataset_snapshot_id)
  AND NOT EXISTS (SELECT 1 FROM havre.personalization_evaluation_reports evaluation
                  WHERE evaluation.owner_id=rejection.owner_id
                    AND evaluation.evaluation_report_id=rejection.evaluation_report_id
                    AND evaluation.adapter_version_id=rejection.adapter_version_id);
