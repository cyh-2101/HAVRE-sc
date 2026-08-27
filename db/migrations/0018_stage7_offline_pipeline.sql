-- Stage 7 reflection/consolidation workers and canonical offline dataset evidence.
-- Training eligibility remains false everywhere; snapshots are rejection-only.

CREATE TABLE havre.stage7_jobs (
    job_id uuid PRIMARY KEY,
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    job_type text NOT NULL CHECK (job_type IN ('daily_reflection', 'periodic_consolidation')),
    idempotency_key text NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 240),
    window_start timestamptz NOT NULL,
    window_end timestamptz NOT NULL,
    status text NOT NULL CHECK (status IN (
        'pending', 'leased', 'succeeded', 'retryable_failed', 'terminal_failed', 'cancelled'
    )),
    lease_owner text NULL,
    lease_expires_at timestamptz NULL,
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts integer NOT NULL DEFAULT 3 CHECK (max_attempts > 0),
    last_error_code text NULL,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    completed_at timestamptz NULL,
    UNIQUE (owner_id, job_id),
    UNIQUE (owner_id, job_type, idempotency_key),
    CHECK (window_end > window_start),
    CHECK ((status = 'leased') = (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL))
);
CREATE INDEX stage7_jobs_claim_idx
    ON havre.stage7_jobs(status, created_at, job_id)
    WHERE status IN ('pending', 'retryable_failed', 'leased');

CREATE TABLE havre.reflection_proposals (
    reflection_proposal_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    job_id uuid NOT NULL,
    proposal_kind text NOT NULL CHECK (proposal_kind IN (
        'pattern_check', 'unresolved_contradiction', 'progress_recognition', 'follow_up'
    )),
    source_snapshot_hash text NOT NULL CHECK (source_snapshot_hash ~ '^sha256:[0-9a-f]{64}$'),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    outreach_authority boolean NOT NULL CHECK (outreach_authority = false),
    delivery_authority boolean NOT NULL CHECK (delivery_authority = false),
    simulation_only boolean NOT NULL CHECK (simulation_only = true),
    privacy_class text NOT NULL CHECK (privacy_class IN (
        'PUBLIC', 'NORMAL', 'PRIVATE', 'HIGHLY_PRIVATE', 'LOCAL_ONLY'
    )),
    memory_eligible boolean NOT NULL,
    training_eligible boolean NOT NULL CHECK (training_eligible = false),
    cloud_eligible boolean NOT NULL,
    policy_version text NOT NULL CHECK (policy_version = 'data-policy-v1'),
    policy_revision_id uuid NOT NULL,
    policy_decision_source text NOT NULL CHECK (policy_decision_source = 'derived_conservative'),
    policy_authorization_ref text NULL,
    trace_id char(32) NOT NULL,
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL,
    UNIQUE (owner_id, reflection_proposal_id),
    UNIQUE (owner_id, job_id, proposal_kind),
    FOREIGN KEY (owner_id, job_id) REFERENCES havre.stage7_jobs(owner_id, job_id),
    CHECK (privacy_class <> 'LOCAL_ONLY' OR cloud_eligible = false)
);
CREATE INDEX reflection_proposals_owner_job_idx
    ON havre.reflection_proposals(owner_id, job_id);

CREATE TABLE havre.reflection_proposal_evidence (
    owner_id uuid NOT NULL,
    reflection_proposal_id uuid NOT NULL,
    source_event_id uuid NOT NULL,
    PRIMARY KEY (owner_id, reflection_proposal_id, source_event_id),
    FOREIGN KEY (owner_id, reflection_proposal_id)
        REFERENCES havre.reflection_proposals(owner_id, reflection_proposal_id),
    FOREIGN KEY (owner_id, source_event_id)
        REFERENCES havre.events(owner_id, event_id)
);
CREATE INDEX reflection_evidence_owner_source_idx
    ON havre.reflection_proposal_evidence(owner_id, source_event_id);

CREATE TABLE havre.memory_lifecycle_proposals (
    lifecycle_proposal_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    action text NOT NULL CHECK (action IN (
        'promote', 'contradict', 'supersede', 'retract', 'archive',
        'reconsolidate', 'regenerate'
    )),
    memory_class text NOT NULL CHECK (memory_class IN (
        'episodic', 'semantic', 'pattern', 'progress'
    )),
    target_memory_id uuid NULL,
    target_revision integer NULL CHECK (target_revision > 0),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    review_required boolean NOT NULL CHECK (review_required = true),
    automatically_applied boolean NOT NULL CHECK (automatically_applied = false),
    privacy_class text NOT NULL CHECK (privacy_class IN (
        'PUBLIC', 'NORMAL', 'PRIVATE', 'HIGHLY_PRIVATE', 'LOCAL_ONLY'
    )),
    memory_eligible boolean NOT NULL,
    training_eligible boolean NOT NULL CHECK (training_eligible = false),
    cloud_eligible boolean NOT NULL,
    policy_version text NOT NULL CHECK (policy_version = 'data-policy-v1'),
    policy_revision_id uuid NOT NULL,
    policy_decision_source text NOT NULL CHECK (policy_decision_source = 'derived_conservative'),
    policy_authorization_ref text NULL,
    trace_id char(32) NOT NULL,
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL,
    UNIQUE (owner_id, lifecycle_proposal_id),
    CHECK ((action IN ('contradict', 'supersede', 'retract', 'archive', 'reconsolidate'))
           = (target_memory_id IS NOT NULL AND target_revision IS NOT NULL)),
    CHECK (privacy_class <> 'LOCAL_ONLY' OR cloud_eligible = false)
);

CREATE TABLE havre.memory_lifecycle_proposal_evidence (
    owner_id uuid NOT NULL,
    lifecycle_proposal_id uuid NOT NULL,
    source_event_id uuid NOT NULL,
    PRIMARY KEY (owner_id, lifecycle_proposal_id, source_event_id),
    FOREIGN KEY (owner_id, lifecycle_proposal_id)
        REFERENCES havre.memory_lifecycle_proposals(owner_id, lifecycle_proposal_id),
    FOREIGN KEY (owner_id, source_event_id)
        REFERENCES havre.events(owner_id, event_id)
);
CREATE INDEX memory_lifecycle_evidence_owner_source_idx
    ON havre.memory_lifecycle_proposal_evidence(owner_id, source_event_id);

CREATE TABLE havre.memory_lifecycle_reviews (
    review_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    lifecycle_proposal_id uuid NOT NULL,
    decision text NOT NULL CHECK (decision IN ('accepted', 'rejected')),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    applied_artifact_ref text NULL CHECK (applied_artifact_ref IS NULL),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    reviewed_at timestamptz NOT NULL,
    UNIQUE (owner_id, review_id),
    UNIQUE (owner_id, lifecycle_proposal_id),
    FOREIGN KEY (owner_id, lifecycle_proposal_id)
        REFERENCES havre.memory_lifecycle_proposals(owner_id, lifecycle_proposal_id)
);

CREATE TABLE havre.canonical_dataset_snapshots (
    dataset_snapshot_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    source_snapshot_hash text NOT NULL CHECK (source_snapshot_hash ~ '^sha256:[0-9a-f]{64}$'),
    builder_version text NOT NULL CHECK (builder_version = 'canonical-dataset-builder-v1'),
    split_policy_version text NOT NULL CHECK (split_policy_version = 'source-grouped-holdout-v1'),
    member_manifest_hash text NOT NULL CHECK (member_manifest_hash ~ '^sha256:[0-9a-f]{64}$'),
    payload jsonb NOT NULL CHECK (
        jsonb_typeof(payload) = 'object'
        AND jsonb_array_length(payload->'members') = 0
    ),
    immutable boolean NOT NULL CHECK (immutable = true),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL,
    UNIQUE (owner_id, dataset_snapshot_id),
    UNIQUE (owner_id, source_snapshot_hash, builder_version)
);

CREATE TABLE havre.dataset_snapshot_sources (
    owner_id uuid NOT NULL,
    dataset_snapshot_id uuid NOT NULL,
    source_event_id uuid NOT NULL,
    source_content_hash text NOT NULL CHECK (source_content_hash ~ '^sha256:[0-9a-f]{64}$'),
    rejection_reason text NOT NULL CHECK (rejection_reason = 'training_not_eligible'),
    PRIMARY KEY (owner_id, dataset_snapshot_id, source_event_id),
    FOREIGN KEY (owner_id, dataset_snapshot_id)
        REFERENCES havre.canonical_dataset_snapshots(owner_id, dataset_snapshot_id),
    FOREIGN KEY (owner_id, source_event_id)
        REFERENCES havre.events(owner_id, event_id)
);
CREATE INDEX dataset_snapshot_sources_owner_event_idx
    ON havre.dataset_snapshot_sources(owner_id, source_event_id);

CREATE TABLE havre.offline_artifact_manifests (
    artifact_manifest_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    dataset_snapshot_id uuid NOT NULL,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    immutable boolean NOT NULL CHECK (immutable = true),
    reproducible boolean NOT NULL CHECK (reproducible = true),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL,
    UNIQUE (owner_id, artifact_manifest_id),
    UNIQUE (owner_id, dataset_snapshot_id),
    FOREIGN KEY (owner_id, dataset_snapshot_id)
        REFERENCES havre.canonical_dataset_snapshots(owner_id, dataset_snapshot_id)
);

DO $$
DECLARE table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'reflection_proposals', 'reflection_proposal_evidence',
        'memory_lifecycle_proposals', 'memory_lifecycle_proposal_evidence',
        'memory_lifecycle_reviews', 'canonical_dataset_snapshots',
        'dataset_snapshot_sources', 'offline_artifact_manifests'
    ] LOOP
        EXECUTE format(
            'CREATE TRIGGER %I_immutable BEFORE UPDATE OR DELETE ON havre.%I '
            'FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation()',
            table_name, table_name
        );
    END LOOP;
END
$$;

CREATE VIEW havre.stage7_required_provenance_violations AS
SELECT proposal.reflection_proposal_id AS provenance_edge_id, proposal.owner_id,
       'reflection_proposal'::text AS source_kind,
       proposal.reflection_proposal_id AS source_id, NULL::integer AS source_revision,
       'reflection_proposal_missing_evidence'::text AS violation_code
FROM havre.reflection_proposals AS proposal
WHERE NOT EXISTS (
    SELECT 1 FROM havre.reflection_proposal_evidence AS evidence
    WHERE evidence.owner_id = proposal.owner_id
      AND evidence.reflection_proposal_id = proposal.reflection_proposal_id
)
UNION ALL
SELECT proposal.lifecycle_proposal_id, proposal.owner_id,
       'memory_lifecycle_proposal', proposal.lifecycle_proposal_id, NULL::integer,
       'memory_lifecycle_proposal_missing_evidence'
FROM havre.memory_lifecycle_proposals AS proposal
WHERE jsonb_array_length(proposal.payload->'source_event_ids') > 0
  AND NOT EXISTS (
    SELECT 1 FROM havre.memory_lifecycle_proposal_evidence AS evidence
    WHERE evidence.owner_id = proposal.owner_id
      AND evidence.lifecycle_proposal_id = proposal.lifecycle_proposal_id
)
UNION ALL
SELECT snapshot.dataset_snapshot_id, snapshot.owner_id,
       'canonical_dataset_snapshot', snapshot.dataset_snapshot_id, NULL::integer,
       'training_policy_or_manifest_violation'
FROM havre.canonical_dataset_snapshots AS snapshot
WHERE jsonb_array_length(snapshot.payload->'members') <> 0
   OR EXISTS (
       SELECT 1 FROM havre.dataset_snapshot_sources AS source
       JOIN havre.events AS event
         ON event.owner_id = source.owner_id AND event.event_id = source.source_event_id
       WHERE source.owner_id = snapshot.owner_id
         AND source.dataset_snapshot_id = snapshot.dataset_snapshot_id
         AND event.training_eligible <> false
   );
