-- Stage 9 local synthetic/public candidate foundation. No promotion/deployment path exists.

CREATE TABLE havre.training_dataset_snapshots (
    dataset_snapshot_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    name text NOT NULL CHECK (name = 'stage9-synthetic-public-fixture-v1'),
    semantic_version text NOT NULL CHECK (semantic_version = '1.0.0'),
    builder_version text NOT NULL CHECK (builder_version = 'stage9-canonical-fixture-builder-v1'),
    split_policy_version text NOT NULL CHECK (split_policy_version = 'fixed-source-grouped-v1'),
    fixture_content_hash text NOT NULL CHECK (fixture_content_hash ~ '^sha256:[0-9a-f]{64}$'),
    member_manifest_hash text NOT NULL CHECK (member_manifest_hash ~ '^sha256:[0-9a-f]{64}$'),
    user_event_source_count integer NOT NULL CHECK (user_event_source_count = 0),
    contains_user_data boolean NOT NULL CHECK (contains_user_data = false),
    local_only_build boolean NOT NULL CHECK (local_only_build = true),
    immutable boolean NOT NULL CHECK (immutable = true),
    payload jsonb NOT NULL CHECK (
        jsonb_typeof(payload) = 'object'
        AND jsonb_typeof(payload->'examples') = 'array'
        AND jsonb_array_length(payload->'examples') >= 4
        AND (payload->>'contains_user_data')::boolean = false
        AND (payload->>'user_event_source_count')::integer = 0
        AND (payload->>'local_only_build')::boolean = true
    ),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL,
    UNIQUE (owner_id, dataset_snapshot_id)
);

CREATE TABLE havre.training_dataset_members (
    owner_id uuid NOT NULL,
    dataset_snapshot_id uuid NOT NULL,
    example_id text NOT NULL CHECK (example_id ~ '^[a-z0-9][a-z0-9_-]{2,79}$'),
    source_kind text NOT NULL CHECK (source_kind IN ('synthetic_fixture','public_fixture')),
    source_ref text NOT NULL CHECK (source_ref ~ '^fixture://stage9/[a-z0-9/_-]+$'),
    license_id text NOT NULL CHECK (license_id = 'CC0-1.0'),
    split text NOT NULL CHECK (split IN ('train','validation','holdout')),
    training_eligible boolean NOT NULL CHECK (training_eligible = true),
    contains_user_data boolean NOT NULL CHECK (contains_user_data = false),
    privacy_class text NOT NULL CHECK (privacy_class = 'PUBLIC'),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    payload jsonb NOT NULL CHECK (
        jsonb_typeof(payload) = 'object'
        AND (payload->>'training_eligible')::boolean = true
        AND (payload->>'contains_user_data')::boolean = false
        AND payload->>'privacy_class' = 'PUBLIC'
    ),
    PRIMARY KEY (owner_id, dataset_snapshot_id, example_id),
    UNIQUE (owner_id, dataset_snapshot_id, source_ref),
    FOREIGN KEY (owner_id, dataset_snapshot_id)
        REFERENCES havre.training_dataset_snapshots(owner_id, dataset_snapshot_id)
);

CREATE TABLE havre.model_versions (
    model_version_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    logical_name text NOT NULL CHECK (logical_name = 'havre-stage9-toy-base'),
    upstream_model_id text NOT NULL CHECK (upstream_model_id = 'local://havre/stage9-toy-matrix'),
    upstream_revision text NOT NULL CHECK (upstream_revision ~ '^sha256:[0-9a-f]{64}$'),
    artifact_uri text NOT NULL CHECK (artifact_uri ~ '^local-artifact://stage9/[a-z0-9/_-]+$'),
    artifact_hash text NOT NULL CHECK (artifact_hash ~ '^sha256:[0-9a-f]{64}$'),
    tokenizer_version text NOT NULL CHECK (tokenizer_version = 'hashed-tokenizer-v1'),
    lifecycle_status text NOT NULL CHECK (lifecycle_status = 'candidate'),
    local_only boolean NOT NULL CHECK (local_only = true),
    production_eligible boolean NOT NULL CHECK (production_eligible = false),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    UNIQUE (owner_id, model_version_id),
    UNIQUE (owner_id, model_version_id, artifact_hash)
);

CREATE TABLE havre.training_runs (
    training_run_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    dataset_snapshot_id uuid NOT NULL,
    model_version_id uuid NOT NULL,
    method text NOT NULL CHECK (method IN ('lora','qlora')),
    framework text NOT NULL CHECK (framework = 'havre-local-matrix-dry-run-v1'),
    seed integer NOT NULL CHECK (seed >= 0),
    status text NOT NULL CHECK (status = 'completed_dry_run'),
    candidate_only boolean NOT NULL CHECK (candidate_only = true),
    governance_mutation_attempted boolean NOT NULL CHECK (governance_mutation_attempted = false),
    promotion_authorized boolean NOT NULL CHECK (promotion_authorized = false),
    deployment_authorized boolean NOT NULL CHECK (deployment_authorized = false),
    used_user_data boolean NOT NULL CHECK (used_user_data = false),
    local_only boolean NOT NULL CHECK (local_only = true),
    cloud_transfer boolean NOT NULL CHECK (cloud_transfer = false),
    governance_versions jsonb NOT NULL CHECK (
        jsonb_typeof(governance_versions) = 'object'
        AND governance_versions ?& ARRAY[
            'constitution_version','constitution_hash','identity_version','identity_hash',
            'values_version','values_hash','intervention_policy_version','intervention_policy_hash'
        ]
    ),
    payload jsonb NOT NULL CHECK (
        jsonb_typeof(payload) = 'object'
        AND (payload->>'candidate_only')::boolean = true
        AND (payload->>'governance_mutation_attempted')::boolean = false
        AND (payload->>'promotion_authorized')::boolean = false
        AND (payload->>'deployment_authorized')::boolean = false
        AND (payload->>'used_user_data')::boolean = false
        AND (payload->'config'->>'dry_run')::boolean = true
        AND (payload->'config'->>'local_only')::boolean = true
        AND (payload->'config'->>'cloud_transfer')::boolean = false
    ),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL,
    UNIQUE (owner_id, training_run_id),
    UNIQUE (owner_id, training_run_id, dataset_snapshot_id, model_version_id, method),
    FOREIGN KEY (owner_id, dataset_snapshot_id)
        REFERENCES havre.training_dataset_snapshots(owner_id, dataset_snapshot_id),
    FOREIGN KEY (owner_id, model_version_id)
        REFERENCES havre.model_versions(owner_id, model_version_id)
);

CREATE TABLE havre.adapter_versions (
    adapter_version_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    adapter_type text NOT NULL CHECK (adapter_type IN ('lora','qlora')),
    base_model_version_id uuid NOT NULL,
    required_base_artifact_hash text NOT NULL CHECK (required_base_artifact_hash ~ '^sha256:[0-9a-f]{64}$'),
    dataset_snapshot_id uuid NOT NULL,
    training_run_id uuid NOT NULL,
    artifact_uri text NOT NULL CHECK (artifact_uri ~ '^local-artifact://stage9/adapters/[a-z0-9/_-]+$'),
    artifact_hash text NOT NULL CHECK (artifact_hash ~ '^sha256:[0-9a-f]{64}$'),
    lifecycle_status text NOT NULL CHECK (lifecycle_status = 'candidate'),
    candidate_only boolean NOT NULL CHECK (candidate_only = true),
    promotion_authorized boolean NOT NULL CHECK (promotion_authorized = false),
    deployed boolean NOT NULL CHECK (deployed = false),
    payload jsonb NOT NULL CHECK (
        jsonb_typeof(payload) = 'object'
        AND (payload->>'candidate_only')::boolean = true
        AND (payload->>'promotion_authorized')::boolean = false
        AND (payload->>'deployed')::boolean = false
    ),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    UNIQUE (owner_id, adapter_version_id),
    FOREIGN KEY (owner_id, base_model_version_id, required_base_artifact_hash)
        REFERENCES havre.model_versions(owner_id, model_version_id, artifact_hash),
    FOREIGN KEY (owner_id, training_run_id, dataset_snapshot_id, base_model_version_id, adapter_type)
        REFERENCES havre.training_runs(owner_id, training_run_id, dataset_snapshot_id, model_version_id, method)
);

CREATE TABLE havre.adapter_compatibility_reports (
    compatibility_report_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    adapter_version_id uuid NOT NULL,
    model_version_id uuid NOT NULL,
    checked_base_artifact_hash text NOT NULL CHECK (checked_base_artifact_hash ~ '^sha256:[0-9a-f]{64}$'),
    compatible boolean NOT NULL,
    load_performed boolean NOT NULL CHECK (load_performed = false),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    UNIQUE (owner_id, compatibility_report_id),
    FOREIGN KEY (owner_id, adapter_version_id)
        REFERENCES havre.adapter_versions(owner_id, adapter_version_id),
    FOREIGN KEY (owner_id, model_version_id, checked_base_artifact_hash)
        REFERENCES havre.model_versions(owner_id, model_version_id, artifact_hash)
);

CREATE TABLE havre.personalization_evaluation_reports (
    evaluation_report_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    dataset_snapshot_id uuid NOT NULL,
    model_version_id uuid NOT NULL,
    adapter_version_id uuid NOT NULL,
    arm_count integer NOT NULL CHECK (arm_count = 4),
    human_benefit_claimed boolean NOT NULL CHECK (human_benefit_claimed = false),
    release_promotion_authorized boolean NOT NULL CHECK (release_promotion_authorized = false),
    payload jsonb NOT NULL CHECK (
        jsonb_typeof(payload) = 'object'
        AND jsonb_array_length(payload->'arms') = 4
        AND (payload->>'human_benefit_claimed')::boolean = false
        AND (payload->>'release_promotion_authorized')::boolean = false
    ),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    UNIQUE (owner_id, evaluation_report_id),
    FOREIGN KEY (owner_id, dataset_snapshot_id)
        REFERENCES havre.training_dataset_snapshots(owner_id, dataset_snapshot_id),
    FOREIGN KEY (owner_id, model_version_id)
        REFERENCES havre.model_versions(owner_id, model_version_id),
    FOREIGN KEY (owner_id, adapter_version_id)
        REFERENCES havre.adapter_versions(owner_id, adapter_version_id)
);

CREATE TABLE havre.adapter_rejection_records (
    rejection_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    adapter_version_id uuid NOT NULL,
    evaluation_report_id uuid NOT NULL,
    reason_code text NOT NULL CHECK (reason_code = 'synthetic_dry_run_not_promotion_evidence'),
    active_adapter_before uuid NULL CHECK (active_adapter_before IS NULL),
    active_adapter_after uuid NULL CHECK (active_adapter_after IS NULL),
    persistent_identity_unchanged boolean NOT NULL CHECK (persistent_identity_unchanged = true),
    persistent_history_unchanged boolean NOT NULL CHECK (persistent_history_unchanged = true),
    rollback_effect text NOT NULL CHECK (rollback_effect = 'no_activation_to_rollback'),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    rejected_at timestamptz NOT NULL,
    UNIQUE (owner_id, rejection_id),
    UNIQUE (owner_id, adapter_version_id),
    FOREIGN KEY (owner_id, adapter_version_id)
        REFERENCES havre.adapter_versions(owner_id, adapter_version_id),
    FOREIGN KEY (owner_id, evaluation_report_id)
        REFERENCES havre.personalization_evaluation_reports(owner_id, evaluation_report_id)
);

CREATE FUNCTION havre.guard_stage9_dataset_snapshot()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    linked_count integer;
    payload_count integer;
BEGIN
    SELECT count(*) INTO linked_count
    FROM havre.training_dataset_members
    WHERE owner_id = NEW.owner_id AND dataset_snapshot_id = NEW.dataset_snapshot_id;
    payload_count := jsonb_array_length(NEW.payload->'examples');
    IF payload_count IS NULL OR linked_count <> payload_count OR linked_count < 4 THEN
        RAISE EXCEPTION 'Stage 9 dataset membership differs from canonical payload'
            USING ERRCODE = '55000';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM havre.training_dataset_members WHERE owner_id=NEW.owner_id AND dataset_snapshot_id=NEW.dataset_snapshot_id AND split='train')
       OR NOT EXISTS (SELECT 1 FROM havre.training_dataset_members WHERE owner_id=NEW.owner_id AND dataset_snapshot_id=NEW.dataset_snapshot_id AND split='validation')
       OR NOT EXISTS (SELECT 1 FROM havre.training_dataset_members WHERE owner_id=NEW.owner_id AND dataset_snapshot_id=NEW.dataset_snapshot_id AND split='holdout') THEN
        RAISE EXCEPTION 'Stage 9 dataset requires train, validation, and holdout'
            USING ERRCODE = '55000';
    END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(NEW.payload->'examples') item
        WHERE NOT EXISTS (
            SELECT 1 FROM havre.training_dataset_members member
            WHERE member.owner_id=NEW.owner_id
              AND member.dataset_snapshot_id=NEW.dataset_snapshot_id
              AND member.example_id=item->>'example_id'
              AND member.content_hash=item->>'content_hash'
              AND member.source_ref=item->>'source_ref'
              AND member.split=item->>'split'
        )
    ) THEN
        RAISE EXCEPTION 'Stage 9 canonical member payload is not durably linked'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END $$;

CREATE CONSTRAINT TRIGGER training_dataset_snapshots_durable_guard
AFTER INSERT ON havre.training_dataset_snapshots
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION havre.guard_stage9_dataset_snapshot();

CREATE VIEW havre.stage9_integrity_violations AS
SELECT run.training_run_id AS violation_id, run.owner_id,
       'training_run_without_safe_canonical_members'::text AS violation_code
FROM havre.training_runs run
WHERE NOT EXISTS (
    SELECT 1 FROM havre.training_dataset_members member
    WHERE member.owner_id=run.owner_id AND member.dataset_snapshot_id=run.dataset_snapshot_id
)
UNION ALL
SELECT adapter.adapter_version_id, adapter.owner_id,
       'candidate_adapter_missing_rejection'::text
FROM havre.adapter_versions adapter
WHERE adapter.adapter_type='qlora'
  AND NOT EXISTS (
      SELECT 1 FROM havre.adapter_rejection_records rejection
      WHERE rejection.owner_id=adapter.owner_id
        AND rejection.adapter_version_id=adapter.adapter_version_id
  );

DO $$
DECLARE table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'training_dataset_snapshots','training_dataset_members','model_versions',
        'training_runs','adapter_versions','adapter_compatibility_reports',
        'personalization_evaluation_reports','adapter_rejection_records'
    ] LOOP
        EXECUTE format(
            'CREATE TRIGGER %I_immutable BEFORE UPDATE OR DELETE ON havre.%I '
            'FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation()',
            table_name, table_name
        );
    END LOOP;
END $$;
