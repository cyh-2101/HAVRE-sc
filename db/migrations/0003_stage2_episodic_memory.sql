CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE havre.events DROP CONSTRAINT events_event_type_check;
ALTER TABLE havre.events ADD CONSTRAINT events_event_type_check CHECK (event_type IN (
    'USER_MESSAGE', 'ASSISTANT_MESSAGE',
    'MEMORY_CREATED', 'MEMORY_REVISED', 'MEMORY_RETRACTED'
));

CREATE TABLE havre.background_jobs (
    job_id uuid PRIMARY KEY,
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    job_type text NOT NULL CHECK (job_type = 'episodic_memory_extract'),
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    idempotency_key text NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 240),
    status text NOT NULL CHECK (status IN (
        'pending', 'leased', 'succeeded', 'retryable_failed',
        'terminal_failed', 'cancelled'
    )),
    available_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    lease_owner text NULL,
    lease_expires_at timestamptz NULL,
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts integer NOT NULL DEFAULT 3 CHECK (max_attempts > 0),
    origin_trace_id char(32) NOT NULL,
    source_event_id uuid NOT NULL,
    source_request_id uuid NOT NULL,
    last_error_code text NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at timestamptz NULL,
    UNIQUE (owner_id, job_type, idempotency_key),
    UNIQUE (owner_id, job_id),
    FOREIGN KEY (owner_id, origin_trace_id)
        REFERENCES havre.traces(owner_id, trace_id),
    FOREIGN KEY (owner_id, source_event_id)
        REFERENCES havre.events(owner_id, event_id),
    FOREIGN KEY (owner_id, source_request_id)
        REFERENCES havre.interaction_requests(owner_id, request_id),
    CHECK (
        (status = 'leased' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)
        OR status <> 'leased'
    )
);
CREATE INDEX background_jobs_claim_idx
    ON havre.background_jobs(status, available_at, created_at)
    WHERE status IN ('pending', 'retryable_failed', 'leased');
CREATE INDEX background_jobs_owner_source_event_idx
    ON havre.background_jobs(owner_id, source_event_id);
CREATE INDEX background_jobs_owner_source_request_idx
    ON havre.background_jobs(owner_id, source_request_id);
CREATE INDEX background_jobs_owner_origin_trace_idx
    ON havre.background_jobs(owner_id, origin_trace_id);

CREATE TABLE havre.memory_candidates (
    candidate_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    source_event_id uuid NOT NULL,
    source_request_id uuid NOT NULL,
    job_id uuid NOT NULL,
    memory_class text NOT NULL CHECK (memory_class = 'episodic'),
    content jsonb NOT NULL CHECK (jsonb_typeof(content) = 'object'),
    content_text text NOT NULL CHECK (length(content_text) BETWEEN 1 AND 100000),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    confidence numeric(6,5) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    confidence_method text NOT NULL,
    importance numeric(6,5) NOT NULL CHECK (importance BETWEEN 0 AND 1),
    importance_policy_version text NOT NULL,
    extractor_version text NOT NULL,
    status text NOT NULL CHECK (status IN ('pending', 'accepted', 'rejected', 'duplicate')),
    reviewed_by text NULL,
    reviewed_at timestamptz NULL,
    review_reason text NULL,
    privacy_class text NOT NULL CHECK (privacy_class IN (
        'PUBLIC', 'NORMAL', 'PRIVATE', 'HIGHLY_PRIVATE', 'LOCAL_ONLY'
    )),
    memory_eligible boolean NOT NULL CHECK (memory_eligible = true),
    training_eligible boolean NOT NULL DEFAULT false CHECK (training_eligible = false),
    cloud_eligible boolean NOT NULL,
    policy_version text NOT NULL CHECK (policy_version = 'data-policy-v1'),
    policy_revision_id uuid NOT NULL,
    policy_decision_source text NOT NULL CHECK (policy_decision_source IN (
        'owner_default', 'owner_explicit', 'derived_conservative'
    )),
    policy_authorization_ref text NULL,
    trace_id char(32) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (owner_id, source_event_id, extractor_version),
    UNIQUE (owner_id, candidate_id),
    FOREIGN KEY (owner_id, source_event_id)
        REFERENCES havre.events(owner_id, event_id),
    FOREIGN KEY (owner_id, source_request_id)
        REFERENCES havre.interaction_requests(owner_id, request_id),
    FOREIGN KEY (owner_id, job_id)
        REFERENCES havre.background_jobs(owner_id, job_id),
    FOREIGN KEY (owner_id, trace_id)
        REFERENCES havre.traces(owner_id, trace_id),
    CHECK (privacy_class <> 'LOCAL_ONLY' OR cloud_eligible = false)
);
CREATE INDEX memory_candidates_owner_status_created_idx
    ON havre.memory_candidates(owner_id, status, created_at);
CREATE INDEX memory_candidates_owner_source_request_idx
    ON havre.memory_candidates(owner_id, source_request_id);
CREATE INDEX memory_candidates_owner_job_idx
    ON havre.memory_candidates(owner_id, job_id);
CREATE INDEX memory_candidates_owner_trace_idx
    ON havre.memory_candidates(owner_id, trace_id);

CREATE TABLE havre.embedding_versions (
    embedding_version_id text PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    provider_id text NOT NULL,
    model_revision text NOT NULL,
    dimension integer NOT NULL CHECK (dimension = 64),
    distance_metric text NOT NULL CHECK (distance_metric = 'cosine'),
    normalization text NOT NULL CHECK (normalization = 'l2'),
    tokenizer_version text NOT NULL,
    implementation_hash text NOT NULL CHECK (implementation_hash ~ '^sha256:[0-9a-f]{64}$'),
    status text NOT NULL CHECK (status IN ('active', 'retired')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE havre.memory_revisions (
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    memory_id uuid NOT NULL,
    revision integer NOT NULL CHECK (revision > 0),
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    memory_class text NOT NULL CHECK (memory_class = 'episodic'),
    content jsonb NOT NULL CHECK (jsonb_typeof(content) = 'object'),
    content_text text NOT NULL CHECK (length(content_text) BETWEEN 1 AND 100000),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    confidence numeric(6,5) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    confidence_method text NOT NULL,
    importance numeric(6,5) NOT NULL CHECK (importance BETWEEN 0 AND 1),
    importance_policy_version text NOT NULL,
    status text NOT NULL CHECK (status IN ('active', 'retracted')),
    valid_from timestamptz NULL,
    valid_to timestamptz NULL,
    source_occurred_at timestamptz NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    created_by text NOT NULL,
    transform_version text NOT NULL,
    supersedes_revision integer NULL CHECK (supersedes_revision > 0),
    candidate_id uuid NULL,
    created_event_id uuid NOT NULL,
    trace_id char(32) NOT NULL,
    privacy_class text NOT NULL CHECK (privacy_class IN (
        'PUBLIC', 'NORMAL', 'PRIVATE', 'HIGHLY_PRIVATE', 'LOCAL_ONLY'
    )),
    memory_eligible boolean NOT NULL CHECK (memory_eligible = true),
    training_eligible boolean NOT NULL DEFAULT false CHECK (training_eligible = false),
    cloud_eligible boolean NOT NULL,
    policy_version text NOT NULL CHECK (policy_version = 'data-policy-v1'),
    policy_revision_id uuid NOT NULL,
    policy_decision_source text NOT NULL CHECK (policy_decision_source IN (
        'owner_default', 'owner_explicit', 'derived_conservative'
    )),
    policy_authorization_ref text NULL,
    PRIMARY KEY (owner_id, memory_id, revision),
    UNIQUE (owner_id, memory_id, revision, status),
    FOREIGN KEY (owner_id, candidate_id)
        REFERENCES havre.memory_candidates(owner_id, candidate_id),
    FOREIGN KEY (owner_id, created_event_id)
        REFERENCES havre.events(owner_id, event_id),
    FOREIGN KEY (owner_id, trace_id)
        REFERENCES havre.traces(owner_id, trace_id),
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
    CHECK ((revision = 1 AND supersedes_revision IS NULL)
        OR (revision > 1 AND supersedes_revision = revision - 1)),
    CHECK (privacy_class <> 'LOCAL_ONLY' OR cloud_eligible = false)
);
CREATE INDEX memory_revisions_owner_created_idx
    ON havre.memory_revisions(owner_id, created_at, memory_id, revision);
CREATE INDEX memory_revisions_owner_created_event_idx
    ON havre.memory_revisions(owner_id, created_event_id);
CREATE INDEX memory_revisions_owner_candidate_idx
    ON havre.memory_revisions(owner_id, candidate_id) WHERE candidate_id IS NOT NULL;
CREATE INDEX memory_revisions_owner_trace_idx
    ON havre.memory_revisions(owner_id, trace_id);

CREATE TABLE havre.memory_heads (
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    memory_id uuid NOT NULL,
    current_revision integer NOT NULL CHECK (current_revision > 0),
    status text NOT NULL CHECK (status IN ('active', 'retracted')),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (owner_id, memory_id),
    FOREIGN KEY (owner_id, memory_id, current_revision, status)
        REFERENCES havre.memory_revisions(owner_id, memory_id, revision, status)
);
CREATE INDEX memory_heads_owner_active_idx
    ON havre.memory_heads(owner_id, updated_at DESC, memory_id)
    WHERE status = 'active';

CREATE TABLE havre.memory_embeddings (
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    memory_id uuid NOT NULL,
    memory_revision integer NOT NULL,
    embedding_version_id text NOT NULL REFERENCES havre.embedding_versions(embedding_version_id),
    chunk_index integer NOT NULL DEFAULT 0 CHECK (chunk_index = 0),
    embedding vector(64) NOT NULL,
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (owner_id, memory_id, memory_revision, embedding_version_id, chunk_index),
    FOREIGN KEY (owner_id, memory_id, memory_revision)
        REFERENCES havre.memory_revisions(owner_id, memory_id, revision)
);
CREATE INDEX memory_embeddings_owner_version_idx
    ON havre.memory_embeddings(owner_id, embedding_version_id, memory_id, memory_revision);

CREATE TABLE havre.provenance_edges (
    provenance_edge_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    source_kind text NOT NULL CHECK (source_kind IN ('event', 'memory_revision')),
    source_id uuid NOT NULL,
    source_revision integer NULL,
    derived_kind text NOT NULL CHECK (derived_kind = 'memory_revision'),
    derived_id uuid NOT NULL,
    derived_revision integer NOT NULL CHECK (derived_revision > 0),
    relation text NOT NULL CHECK (relation IN ('derived_from', 'supersedes', 'corrects', 'retracts')),
    weight numeric(6,5) NULL CHECK (weight BETWEEN 0 AND 1),
    transform_name text NOT NULL,
    transform_version text NOT NULL,
    created_event_id uuid NOT NULL,
    trace_id char(32) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (
        owner_id, source_kind, source_id, source_revision,
        derived_kind, derived_id, derived_revision, relation, transform_version
    ),
    FOREIGN KEY (owner_id, derived_id, derived_revision)
        REFERENCES havre.memory_revisions(owner_id, memory_id, revision),
    FOREIGN KEY (owner_id, created_event_id)
        REFERENCES havre.events(owner_id, event_id),
    FOREIGN KEY (owner_id, trace_id)
        REFERENCES havre.traces(owner_id, trace_id),
    CHECK (
        (source_kind = 'event' AND source_revision IS NULL)
        OR (source_kind = 'memory_revision' AND source_revision IS NOT NULL)
    )
);
CREATE INDEX provenance_edges_owner_source_idx
    ON havre.provenance_edges(owner_id, source_kind, source_id, source_revision);
CREATE INDEX provenance_edges_owner_derived_idx
    ON havre.provenance_edges(owner_id, derived_kind, derived_id, derived_revision);
CREATE INDEX provenance_edges_owner_created_event_idx
    ON havre.provenance_edges(owner_id, created_event_id);
CREATE INDEX provenance_edges_owner_trace_idx
    ON havre.provenance_edges(owner_id, trace_id);

CREATE TABLE havre.retrieval_results (
    retrieval_result_id uuid PRIMARY KEY,
    retrieval_request_id uuid NOT NULL UNIQUE,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    request_id uuid NOT NULL,
    query_event_id uuid NOT NULL,
    trace_id char(32) NOT NULL,
    as_of timestamptz NOT NULL,
    request_snapshot jsonb NOT NULL CHECK (jsonb_typeof(request_snapshot) = 'object'),
    algorithm_version text NOT NULL,
    embedding_version_id text NULL REFERENCES havre.embedding_versions(embedding_version_id),
    reranker_version_id text NULL,
    index_version text NOT NULL,
    candidates jsonb NOT NULL CHECK (jsonb_typeof(candidates) = 'array'),
    timing_ms jsonb NOT NULL CHECK (jsonb_typeof(timing_ms) = 'object'),
    degraded_components jsonb NOT NULL CHECK (jsonb_typeof(degraded_components) = 'array'),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL,
    UNIQUE (owner_id, retrieval_result_id),
    FOREIGN KEY (owner_id, request_id)
        REFERENCES havre.interaction_requests(owner_id, request_id),
    FOREIGN KEY (owner_id, query_event_id)
        REFERENCES havre.events(owner_id, event_id),
    FOREIGN KEY (owner_id, trace_id)
        REFERENCES havre.traces(owner_id, trace_id)
);
CREATE INDEX retrieval_results_owner_request_idx
    ON havre.retrieval_results(owner_id, request_id);
CREATE INDEX retrieval_results_owner_query_event_idx
    ON havre.retrieval_results(owner_id, query_event_id);
CREATE INDEX retrieval_results_owner_trace_idx
    ON havre.retrieval_results(owner_id, trace_id);
CREATE INDEX retrieval_results_owner_created_idx
    ON havre.retrieval_results(owner_id, created_at DESC);

ALTER TABLE havre.context_packs ADD COLUMN retrieval_result_id uuid NULL;
ALTER TABLE havre.context_packs ADD CONSTRAINT context_packs_owner_retrieval_result_fk
    FOREIGN KEY (owner_id, retrieval_result_id)
    REFERENCES havre.retrieval_results(owner_id, retrieval_result_id);
CREATE INDEX context_packs_owner_retrieval_result_idx
    ON havre.context_packs(owner_id, retrieval_result_id)
    WHERE retrieval_result_id IS NOT NULL;

CREATE TABLE havre.retrieval_benchmark_runs (
    benchmark_run_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    gold_set_version text NOT NULL,
    corpus_hash text NOT NULL CHECK (corpus_hash ~ '^sha256:[0-9a-f]{64}$'),
    algorithm_versions jsonb NOT NULL CHECK (jsonb_typeof(algorithm_versions) = 'array'),
    embedding_version_id text NOT NULL REFERENCES havre.embedding_versions(embedding_version_id),
    environment jsonb NOT NULL CHECK (jsonb_typeof(environment) = 'object'),
    metrics jsonb NOT NULL CHECK (jsonb_typeof(metrics) = 'object'),
    case_results jsonb NOT NULL CHECK (jsonb_typeof(case_results) = 'array'),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TRIGGER memory_candidates_are_immutable_after_review
BEFORE DELETE ON havre.memory_candidates
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();

CREATE TRIGGER memory_revisions_are_immutable
BEFORE UPDATE OR DELETE ON havre.memory_revisions
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();

CREATE TRIGGER memory_embeddings_are_immutable
BEFORE UPDATE OR DELETE ON havre.memory_embeddings
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();

CREATE TRIGGER provenance_edges_are_immutable
BEFORE UPDATE OR DELETE ON havre.provenance_edges
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();

CREATE TRIGGER retrieval_results_are_immutable
BEFORE UPDATE OR DELETE ON havre.retrieval_results
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();

CREATE TRIGGER retrieval_benchmark_runs_are_immutable
BEFORE UPDATE OR DELETE ON havre.retrieval_benchmark_runs
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();
