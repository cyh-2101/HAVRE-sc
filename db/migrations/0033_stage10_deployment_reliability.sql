-- Stage 10 immutable release, deployment, backup, and restore-replay evidence.
-- This migration does not promote or deploy a Stage 9 adapter.

ALTER TABLE havre.runtime_attestations
    DROP CONSTRAINT runtime_attestations_schema_version_check;
ALTER TABLE havre.runtime_attestations
    ADD CONSTRAINT runtime_attestations_schema_version_check
    CHECK (schema_version IN (1, 2));

CREATE TABLE havre.component_promotion_authorizations (
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    component text NOT NULL CHECK (component IN (
        'provider','foundation_model','adapter','tokenizer','serving_engine'
    )),
    version text NOT NULL CHECK (length(version) BETWEEN 1 AND 240),
    artifact_hash text NOT NULL CHECK (artifact_hash ~ '^sha256:[0-9a-f]{64}$'),
    decision text NOT NULL CHECK (decision = 'approved'),
    actor text NOT NULL CHECK (actor = 'product_owner'),
    rationale text NOT NULL CHECK (length(rationale) BETWEEN 1 AND 4000),
    decided_at timestamptz NOT NULL,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    PRIMARY KEY (owner_id, content_hash),
    UNIQUE (owner_id, component, version, artifact_hash)
);

CREATE TABLE havre.release_manifests (
    release_manifest_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    release_id text NOT NULL CHECK (release_id ~ '^[a-z0-9][a-z0-9._-]{2,119}$'),
    environment text NOT NULL CHECK (environment IN ('development','staging','production')),
    release_scope text NOT NULL CHECK (release_scope IN (
        'infrastructure_only','development_candidate_fixture','production'
    )),
    source_revision char(40) NOT NULL CHECK (source_revision ~ '^[0-9a-f]{40}$'),
    migration_head text NOT NULL CHECK (migration_head ~ '^[0-9]{4}_[a-z0-9_]+[.]sql$'),
    adapter_lifecycle_status text NULL CHECK (
        adapter_lifecycle_status IS NULL
        OR adapter_lifecycle_status IN ('approved','candidate_fixture')
    ),
    adapter_deployment_authorized boolean NOT NULL DEFAULT false,
    promotion_approval_ref text NULL,
    rollback_release_manifest_hash text NULL CHECK (
        rollback_release_manifest_hash IS NULL
        OR rollback_release_manifest_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    component_promotion_authorization_hashes jsonb NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(component_promotion_authorization_hashes) = 'array'),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL,
    UNIQUE (owner_id, release_manifest_id),
    UNIQUE (owner_id, release_manifest_id, content_hash),
    UNIQUE (owner_id, release_id, content_hash),
    CHECK (
        release_scope <> 'development_candidate_fixture'
        OR (
            environment <> 'production'
            AND adapter_lifecycle_status = 'candidate_fixture'
            AND NOT adapter_deployment_authorized
            AND promotion_approval_ref IS NULL
        )
    ),
    CHECK (
        adapter_lifecycle_status <> 'candidate_fixture'
        OR (
            environment <> 'production'
            AND release_scope = 'development_candidate_fixture'
            AND NOT adapter_deployment_authorized
        )
    ),
    CHECK (
        NOT adapter_deployment_authorized
        OR (
            release_scope = 'production'
            AND environment = 'production'
            AND adapter_lifecycle_status = 'approved'
            AND promotion_approval_ref IS NOT NULL
        )
    ),
    CHECK (adapter_deployment_authorized OR promotion_approval_ref IS NULL)
);
CREATE INDEX release_manifests_owner_created_idx
    ON havre.release_manifests(owner_id, created_at, release_manifest_id);

CREATE TABLE havre.release_approval_records (
    release_approval_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL,
    release_manifest_id uuid NOT NULL,
    release_manifest_hash text NOT NULL CHECK (
        release_manifest_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    approval_scope text NOT NULL CHECK (approval_scope IN (
        'infrastructure_production_release','personalized_adapter_release'
    )),
    decision text NOT NULL CHECK (decision IN ('approved','rejected')),
    actor text NOT NULL CHECK (actor = 'product_owner'),
    rationale text NOT NULL CHECK (length(rationale) BETWEEN 1 AND 4000),
    decided_at timestamptz NOT NULL,
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    UNIQUE (owner_id, release_approval_id),
    UNIQUE (owner_id, release_manifest_id, approval_scope),
    FOREIGN KEY (owner_id, release_manifest_id)
        REFERENCES havre.release_manifests(owner_id, release_manifest_id)
);
CREATE INDEX release_approvals_owner_manifest_idx
    ON havre.release_approval_records(owner_id, release_manifest_id);

CREATE OR REPLACE FUNCTION havre.guard_release_approval_binding()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    expected_hash text;
    adapter_authorized boolean;
BEGIN
    SELECT content_hash, adapter_deployment_authorized
      INTO expected_hash, adapter_authorized
    FROM havre.release_manifests
    WHERE owner_id = NEW.owner_id
      AND release_manifest_id = NEW.release_manifest_id;
    IF NOT FOUND OR NEW.release_manifest_hash <> expected_hash THEN
        RAISE EXCEPTION 'release approval is not bound to the exact manifest'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.approval_scope = 'personalized_adapter_release'
       AND NOT adapter_authorized THEN
        RAISE EXCEPTION 'manifest does not request personalized adapter deployment'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER release_approval_binding_guard
    BEFORE INSERT ON havre.release_approval_records
    FOR EACH ROW EXECUTE FUNCTION havre.guard_release_approval_binding();

CREATE TABLE havre.deployments (
    deployment_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL,
    release_manifest_id uuid NOT NULL,
    release_manifest_hash text NOT NULL CHECK (
        release_manifest_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    environment text NOT NULL CHECK (environment IN ('development','staging','production')),
    action text NOT NULL CHECK (action IN ('deploy','rollback')),
    status text NOT NULL CHECK (status IN ('planned','applied','failed')),
    previous_deployment_id uuid NULL,
    health_evidence jsonb NOT NULL CHECK (jsonb_typeof(health_evidence) = 'object'),
    failure_code text NULL CHECK (failure_code IS NULL OR length(failure_code) BETWEEN 1 AND 120),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    occurred_at timestamptz NOT NULL,
    UNIQUE (owner_id, deployment_id),
    FOREIGN KEY (owner_id, release_manifest_id)
        REFERENCES havre.release_manifests(owner_id, release_manifest_id),
    FOREIGN KEY (owner_id, previous_deployment_id)
        REFERENCES havre.deployments(owner_id, deployment_id),
    CHECK (action <> 'rollback' OR previous_deployment_id IS NOT NULL),
    CHECK (
        (status = 'applied') = (health_evidence <> '{}'::jsonb)
    ),
    CHECK ((status = 'failed') = (failure_code IS NOT NULL))
);
CREATE INDEX deployments_owner_environment_idx
    ON havre.deployments(owner_id, environment, occurred_at, deployment_id);
CREATE INDEX deployments_owner_release_idx
    ON havre.deployments(owner_id, release_manifest_id);
CREATE INDEX deployments_owner_previous_idx
    ON havre.deployments(owner_id, previous_deployment_id)
    WHERE previous_deployment_id IS NOT NULL;

CREATE OR REPLACE FUNCTION havre.guard_deployment_release_gate()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    manifest record;
    prior record;
    expected_image_digest text;
    latest_deployment_id uuid;
BEGIN
    IF NEW.status = 'applied' THEN
        PERFORM pg_advisory_xact_lock(
            hashtextextended(
                'havre-deployment:' || NEW.owner_id::text || ':' || NEW.environment,
                0
            )
        );
    END IF;
    SELECT * INTO manifest
    FROM havre.release_manifests
    WHERE owner_id = NEW.owner_id
      AND release_manifest_id = NEW.release_manifest_id;
    IF NOT FOUND
       OR manifest.content_hash <> NEW.release_manifest_hash
       OR manifest.environment <> NEW.environment THEN
        RAISE EXCEPTION 'deployment is not bound to its exact release manifest'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.status = 'applied' AND NEW.environment = 'production' AND NOT EXISTS (
        SELECT 1 FROM havre.release_approval_records
        WHERE owner_id = NEW.owner_id
          AND release_manifest_id = NEW.release_manifest_id
          AND release_manifest_hash = NEW.release_manifest_hash
          AND approval_scope = 'infrastructure_production_release'
          AND decision = 'approved'
    ) THEN
        RAISE EXCEPTION 'production deployment lacks Product Owner release approval'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.status = 'applied' THEN
        SELECT component->>'artifact_hash' INTO expected_image_digest
        FROM jsonb_array_elements(manifest.payload->'components') AS component
        WHERE component->>'component' = 'deployment_image';
        IF NEW.health_evidence->>'schema_version' <> '1'
           OR NEW.health_evidence->>'release_manifest_hash' <> NEW.release_manifest_hash
           OR NEW.health_evidence->>'environment' <> NEW.environment
           OR NEW.health_evidence->>'source_revision' <> manifest.source_revision
           OR NEW.health_evidence->>'ready' <> 'true'
           OR jsonb_typeof(NEW.health_evidence->'checks') <> 'array'
           OR jsonb_array_length(NEW.health_evidence->'checks') = 0
           OR NULLIF(NEW.health_evidence->>'checked_at', '')::timestamptz IS NULL
           OR (
                NEW.environment IN ('staging','production')
                AND NEW.health_evidence->>'runtime_image_digest'
                    IS DISTINCT FROM expected_image_digest
           ) THEN
            RAISE EXCEPTION 'applied deployment health evidence is invalid or unbound'
                USING ERRCODE = '55000';
        END IF;
    END IF;
    IF NEW.status = 'applied' AND manifest.adapter_deployment_authorized AND NOT EXISTS (
        SELECT 1 FROM havre.release_approval_records
        WHERE owner_id = NEW.owner_id
          AND release_manifest_id = NEW.release_manifest_id
          AND release_manifest_hash = NEW.release_manifest_hash
          AND approval_scope = 'personalized_adapter_release'
          AND decision = 'approved'
    ) THEN
        RAISE EXCEPTION 'adapter deployment lacks Product Owner promotion approval'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.action = 'rollback' THEN
        SELECT deployment_id INTO latest_deployment_id
        FROM havre.deployments
        WHERE owner_id=NEW.owner_id
          AND environment=NEW.environment
          AND status='applied'
        ORDER BY occurred_at DESC, deployment_id DESC
        LIMIT 1;
        IF latest_deployment_id IS DISTINCT FROM NEW.previous_deployment_id THEN
            RAISE EXCEPTION 'rollback source is not the latest applied deployment'
                USING ERRCODE = '55000';
        END IF;
        SELECT deployment.*, release.content_hash AS deployed_release_hash,
               release.rollback_release_manifest_hash
          INTO prior
        FROM havre.deployments AS deployment
        JOIN havre.release_manifests AS release
          ON release.owner_id = deployment.owner_id
         AND release.release_manifest_id = deployment.release_manifest_id
        WHERE deployment.owner_id = NEW.owner_id
          AND deployment.deployment_id = NEW.previous_deployment_id
          AND deployment.status = 'applied';
        IF NOT FOUND
           OR prior.rollback_release_manifest_hash IS NULL
           OR prior.rollback_release_manifest_hash <> NEW.release_manifest_hash THEN
            RAISE EXCEPTION 'rollback target is not pinned by the deployed release'
                USING ERRCODE = '55000';
        END IF;
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER deployment_release_gate_guard
    BEFORE INSERT ON havre.deployments
    FOR EACH ROW EXECUTE FUNCTION havre.guard_deployment_release_gate();

CREATE TABLE havre.backup_manifests (
    backup_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    artifact_uri text NOT NULL CHECK (artifact_uri ~ '^local://'),
    artifact_sha256 text NOT NULL CHECK (artifact_sha256 ~ '^sha256:[0-9a-f]{64}$'),
    artifact_size_bytes bigint NOT NULL CHECK (artifact_size_bytes > 0),
    source_database_name text NOT NULL CHECK (
        source_database_name ~ '^[A-Za-z0-9_][A-Za-z0-9_-]{0,62}$'
    ),
    migration_head text NOT NULL CHECK (migration_head ~ '^[0-9]{4}_[a-z0-9_]+[.]sql$'),
    release_manifest_id uuid NOT NULL,
    release_manifest_hash text NOT NULL CHECK (
        release_manifest_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    erasure_ledger_sequence bigint NOT NULL CHECK (erasure_ledger_sequence >= 0),
    created_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL CHECK (expires_at > created_at),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    UNIQUE (owner_id, backup_id),
    UNIQUE (owner_id, artifact_sha256),
    FOREIGN KEY (owner_id, release_manifest_id, release_manifest_hash)
        REFERENCES havre.release_manifests(
            owner_id, release_manifest_id, content_hash
        )
);
CREATE INDEX backup_manifests_owner_expiry_idx
    ON havre.backup_manifests(owner_id, expires_at, backup_id);

CREATE TABLE havre.restore_erasure_replays (
    replay_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    backup_id uuid NOT NULL,
    restored_database_name text NOT NULL CHECK (
        restored_database_name ~ '^[A-Za-z0-9_][A-Za-z0-9_-]{0,62}$'
    ),
    ledger_sequence_from bigint NOT NULL CHECK (ledger_sequence_from >= 0),
    ledger_sequence_through bigint NOT NULL CHECK (
        ledger_sequence_through >= ledger_sequence_from
    ),
    directives_applied integer NOT NULL CHECK (directives_applied >= 0),
    absence_verified boolean NOT NULL,
    provenance_violations integer NOT NULL CHECK (provenance_violations >= 0),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    completed_at timestamptz NOT NULL,
    UNIQUE (owner_id, replay_id),
    FOREIGN KEY (owner_id, backup_id)
        REFERENCES havre.backup_manifests(owner_id, backup_id),
    CHECK (absence_verified AND provenance_violations = 0)
);
CREATE INDEX restore_replays_owner_backup_idx
    ON havre.restore_erasure_replays(owner_id, backup_id, completed_at);

CREATE TRIGGER release_manifests_are_immutable
BEFORE UPDATE OR DELETE ON havre.release_manifests
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();
CREATE TRIGGER component_promotion_authorizations_are_immutable
BEFORE UPDATE OR DELETE ON havre.component_promotion_authorizations
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();
CREATE TRIGGER release_approvals_are_immutable
BEFORE UPDATE OR DELETE ON havre.release_approval_records
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();
CREATE TRIGGER deployments_are_immutable
BEFORE UPDATE OR DELETE ON havre.deployments
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();
CREATE TRIGGER backup_manifests_are_immutable
BEFORE UPDATE OR DELETE ON havre.backup_manifests
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();
CREATE TRIGGER restore_erasure_replays_are_immutable
BEFORE UPDATE OR DELETE ON havre.restore_erasure_replays
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();
