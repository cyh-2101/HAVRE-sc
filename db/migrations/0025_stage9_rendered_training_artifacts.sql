-- Additive Stage 9 model-specific rendering/tokenization artifact binding.

CREATE TABLE havre.rendered_training_artifacts (
    rendered_artifact_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    dataset_snapshot_id uuid NOT NULL,
    model_version_id uuid NOT NULL,
    renderer_version text NOT NULL CHECK (renderer_version = 'stage9-renderer-v1'),
    tokenizer_version text NOT NULL CHECK (tokenizer_version = 'hashed-tokenizer-v1'),
    source_member_manifest_hash text NOT NULL CHECK (source_member_manifest_hash ~ '^sha256:[0-9a-f]{64}$'),
    contains_user_data boolean NOT NULL CHECK (contains_user_data = false),
    local_only boolean NOT NULL CHECK (local_only = true),
    immutable boolean NOT NULL CHECK (immutable = true),
    payload jsonb NOT NULL CHECK (
        jsonb_typeof(payload) = 'object'
        AND jsonb_typeof(payload->'examples') = 'array'
        AND jsonb_array_length(payload->'examples') >= 4
        AND (payload->>'contains_user_data')::boolean = false
        AND (payload->>'local_only')::boolean = true
    ),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    UNIQUE (owner_id, rendered_artifact_id),
    UNIQUE (owner_id, rendered_artifact_id, dataset_snapshot_id, model_version_id),
    FOREIGN KEY (owner_id, dataset_snapshot_id)
        REFERENCES havre.training_dataset_snapshots(owner_id, dataset_snapshot_id),
    FOREIGN KEY (owner_id, model_version_id)
        REFERENCES havre.model_versions(owner_id, model_version_id)
);

ALTER TABLE havre.training_runs
    ADD COLUMN rendered_artifact_id uuid NULL;

ALTER TABLE havre.training_runs
    ADD CONSTRAINT training_runs_rendered_artifact_fk
    FOREIGN KEY (owner_id, rendered_artifact_id, dataset_snapshot_id, model_version_id)
    REFERENCES havre.rendered_training_artifacts(
        owner_id, rendered_artifact_id, dataset_snapshot_id, model_version_id
    );

CREATE FUNCTION havre.guard_stage9_training_run_rendering()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.rendered_artifact_id IS NULL THEN
        RAISE EXCEPTION 'Stage 9 training run requires exact rendered artifact'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END $$;

CREATE CONSTRAINT TRIGGER training_runs_rendered_artifact_guard
AFTER INSERT ON havre.training_runs
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION havre.guard_stage9_training_run_rendering();

CREATE TRIGGER rendered_training_artifacts_immutable
BEFORE UPDATE OR DELETE ON havre.rendered_training_artifacts
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();
