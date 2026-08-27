CREATE TABLE havre.runtime_attestations (
    runtime_attestation_id text PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    attestation_hash text NOT NULL UNIQUE
        CHECK (attestation_hash ~ '^sha256:[0-9a-f]{64}$'),
    attestation jsonb NOT NULL CHECK (jsonb_typeof(attestation) = 'object'),
    created_at timestamptz NOT NULL,
    CONSTRAINT runtime_attestations_identity_shape_check CHECK (
        attestation ?& ARRAY[
            'schema_version', 'attestation_id', 'attestation_hash',
            'server_pid', 'process_started_at', 'model_artifact_hash'
        ]
        AND jsonb_typeof(attestation->'schema_version') = 'number'
        AND jsonb_typeof(attestation->'attestation_id') = 'string'
        AND jsonb_typeof(attestation->'attestation_hash') = 'string'
        AND jsonb_typeof(attestation->'server_pid') = 'number'
        AND attestation->>'attestation_id' = runtime_attestation_id
        AND (attestation->>'schema_version')::integer = schema_version
        AND attestation->>'attestation_hash' = attestation_hash
    ),
    CONSTRAINT runtime_attestations_identity_key
        UNIQUE (runtime_attestation_id, attestation_hash)
);

CREATE TRIGGER runtime_attestations_are_immutable
BEFORE UPDATE OR DELETE ON havre.runtime_attestations
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();

ALTER TABLE havre.inference_attempts
    ADD COLUMN runtime_attestation_contract_version smallint NOT NULL DEFAULT 0,
    ADD COLUMN runtime_attestation_id text,
    ADD COLUMN runtime_attestation_hash text,
    ADD CONSTRAINT inference_attempts_runtime_attestation_pair_check CHECK (
        (runtime_attestation_id IS NULL) = (runtime_attestation_hash IS NULL)
    ),
    ADD CONSTRAINT inference_attempts_runtime_attestation_hash_check CHECK (
        runtime_attestation_hash IS NULL
        OR runtime_attestation_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    ADD CONSTRAINT inference_attempts_runtime_attestation_fk
        FOREIGN KEY (runtime_attestation_id, runtime_attestation_hash)
        REFERENCES havre.runtime_attestations(
            runtime_attestation_id, attestation_hash
        ),
    ADD CONSTRAINT inference_attempts_runtime_attestation_required_check CHECK (
        runtime_attestation_contract_version IN (0, 1)
        AND (
            runtime_attestation_contract_version = 0
            OR provider_class <> 'self_hosted'
            OR runtime_attestation_id IS NOT NULL
        )
    );

ALTER TABLE havre.inference_attempts
    ALTER COLUMN runtime_attestation_contract_version SET DEFAULT 1;

CREATE FUNCTION havre.enforce_new_inference_attempt_runtime_attestation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.runtime_attestation_contract_version <> 1 THEN
        RAISE EXCEPTION
            'new inference attempts require runtime attestation contract version 1'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.provider_class = 'self_hosted'
       AND NEW.runtime_attestation_id IS NULL THEN
        RAISE EXCEPTION
            'new self-hosted inference attempts require runtime attestation'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER new_inference_attempts_require_runtime_attestation_v1
BEFORE INSERT ON havre.inference_attempts
FOR EACH ROW EXECUTE FUNCTION
    havre.enforce_new_inference_attempt_runtime_attestation();

CREATE INDEX inference_attempts_runtime_attestation_idx
    ON havre.inference_attempts(runtime_attestation_id)
    WHERE runtime_attestation_id IS NOT NULL;
