CREATE SCHEMA IF NOT EXISTS havre;

CREATE TABLE havre.schema_migrations (
    migration_id text PRIMARY KEY,
    content_sha256 char(64) NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    applied_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE havre.owners (
    owner_id uuid PRIMARY KEY,
    display_name text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 200),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE havre.approval_records (
    approval_id uuid PRIMARY KEY,
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    artifact_kind text NOT NULL CHECK (artifact_kind IN (
        'constitution', 'identity', 'values', 'privacy_rules', 'governance'
    )),
    artifact_version_id text NOT NULL,
    artifact_content_hash text NOT NULL CHECK (artifact_content_hash ~ '^sha256:[0-9a-f]{64}$'),
    decision text NOT NULL CHECK (decision = 'approved'),
    rationale text NOT NULL,
    scope text NOT NULL,
    approved_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (owner_id, artifact_kind, artifact_version_id)
);
CREATE INDEX approval_records_owner_id_idx ON havre.approval_records(owner_id);

CREATE TABLE havre.identity_artifact_versions (
    artifact_version_id text PRIMARY KEY,
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    artifact_kind text NOT NULL CHECK (artifact_kind IN ('constitution', 'identity', 'values')),
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    content text NOT NULL CHECK (length(content) > 0),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    approval_id uuid NOT NULL REFERENCES havre.approval_records(approval_id),
    source_files jsonb NOT NULL CHECK (jsonb_typeof(source_files) = 'array'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (owner_id, artifact_kind, content_hash)
);
CREATE INDEX identity_artifact_versions_owner_id_idx
    ON havre.identity_artifact_versions(owner_id);
CREATE INDEX identity_artifact_versions_approval_id_idx
    ON havre.identity_artifact_versions(approval_id);

CREATE TABLE havre.sessions (
    session_id uuid PRIMARY KEY,
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    channel text NOT NULL CHECK (channel IN ('api', 'cli', 'web')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    last_activity_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (session_id, owner_id)
);
CREATE INDEX sessions_owner_id_idx ON havre.sessions(owner_id);

CREATE TABLE havre.traces (
    trace_id char(32) PRIMARY KEY CHECK (
        trace_id ~ '^[0-9a-f]{32}$' AND trace_id <> repeat('0', 32)
    ),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    root_request_id uuid NOT NULL UNIQUE,
    incoming_parent_span_id char(16) NULL CHECK (
        incoming_parent_span_id IS NULL OR (
            incoming_parent_span_id ~ '^[0-9a-f]{16}$'
            AND incoming_parent_span_id <> repeat('0', 16)
        )
    ),
    trace_flags char(2) NOT NULL CHECK (trace_flags ~ '^[0-9a-f]{2}$'),
    started_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX traces_owner_id_idx ON havre.traces(owner_id);

CREATE TABLE havre.interaction_requests (
    request_id uuid PRIMARY KEY,
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    session_id uuid NOT NULL,
    trace_id char(32) NOT NULL REFERENCES havre.traces(trace_id),
    idempotency_key text NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 200),
    status text NOT NULL CHECK (status IN ('processing', 'completed', 'failed')),
    user_event_id uuid NULL,
    assistant_event_id uuid NULL,
    context_pack_id uuid NULL,
    inference_response_id uuid NULL,
    error_code text NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at timestamptz NULL,
    UNIQUE (owner_id, idempotency_key),
    FOREIGN KEY (session_id, owner_id) REFERENCES havre.sessions(session_id, owner_id)
);
CREATE INDEX interaction_requests_owner_id_idx ON havre.interaction_requests(owner_id);
CREATE INDEX interaction_requests_session_id_idx ON havre.interaction_requests(session_id);
CREATE INDEX interaction_requests_trace_id_idx ON havre.interaction_requests(trace_id);

CREATE TABLE havre.events (
    event_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    event_type text NOT NULL CHECK (event_type IN ('USER_MESSAGE', 'ASSISTANT_MESSAGE')),
    event_version smallint NOT NULL CHECK (event_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    session_id uuid NOT NULL,
    request_id uuid NOT NULL REFERENCES havre.interaction_requests(request_id),
    trace_id char(32) NOT NULL REFERENCES havre.traces(trace_id),
    causation_event_id uuid NULL REFERENCES havre.events(event_id),
    privacy_class text NOT NULL CHECK (privacy_class IN (
        'PUBLIC', 'NORMAL', 'PRIVATE', 'HIGHLY_PRIVATE', 'LOCAL_ONLY'
    )),
    memory_eligible boolean NOT NULL,
    training_eligible boolean NOT NULL DEFAULT false CHECK (training_eligible = false),
    cloud_eligible boolean NOT NULL,
    policy_version text NOT NULL CHECK (policy_version = 'data-policy-v1'),
    policy_revision_id uuid NOT NULL,
    policy_decision_source text NOT NULL CHECK (policy_decision_source IN (
        'owner_default', 'owner_explicit', 'derived_conservative'
    )),
    policy_authorization_ref text NULL,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (owner_id, content_hash),
    CHECK (privacy_class <> 'LOCAL_ONLY' OR cloud_eligible = false),
    CHECK (
        privacy_class <> 'HIGHLY_PRIVATE'
        OR cloud_eligible = false
        OR (policy_decision_source = 'owner_explicit' AND policy_authorization_ref IS NOT NULL)
    ),
    FOREIGN KEY (session_id, owner_id) REFERENCES havre.sessions(session_id, owner_id)
);
CREATE INDEX events_owner_id_recorded_at_idx ON havre.events(owner_id, recorded_at DESC);
CREATE INDEX events_session_id_recorded_at_idx ON havre.events(session_id, recorded_at);
CREATE INDEX events_request_id_idx ON havre.events(request_id);
CREATE INDEX events_trace_id_idx ON havre.events(trace_id);
CREATE INDEX events_causation_event_id_idx ON havre.events(causation_event_id)
    WHERE causation_event_id IS NOT NULL;

ALTER TABLE havre.interaction_requests
    ADD CONSTRAINT interaction_requests_user_event_fk
    FOREIGN KEY (user_event_id) REFERENCES havre.events(event_id),
    ADD CONSTRAINT interaction_requests_assistant_event_fk
    FOREIGN KEY (assistant_event_id) REFERENCES havre.events(event_id);
CREATE INDEX interaction_requests_user_event_id_idx
    ON havre.interaction_requests(user_event_id) WHERE user_event_id IS NOT NULL;
CREATE INDEX interaction_requests_assistant_event_id_idx
    ON havre.interaction_requests(assistant_event_id) WHERE assistant_event_id IS NOT NULL;

CREATE TABLE havre.context_packs (
    context_pack_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    request_id uuid NOT NULL UNIQUE REFERENCES havre.interaction_requests(request_id),
    trace_id char(32) NOT NULL REFERENCES havre.traces(trace_id),
    purpose text NOT NULL CHECK (purpose = 'companion_response'),
    builder_version text NOT NULL,
    constitution_version_id text NOT NULL REFERENCES havre.identity_artifact_versions(artifact_version_id),
    identity_version_id text NOT NULL REFERENCES havre.identity_artifact_versions(artifact_version_id),
    values_version_id text NOT NULL REFERENCES havre.identity_artifact_versions(artifact_version_id),
    token_budget jsonb NOT NULL CHECK (jsonb_typeof(token_budget) = 'object'),
    sections jsonb NOT NULL CHECK (jsonb_typeof(sections) = 'array'),
    excluded_candidates jsonb NOT NULL CHECK (jsonb_typeof(excluded_candidates) = 'array'),
    effective_privacy_class text NOT NULL CHECK (effective_privacy_class IN (
        'PUBLIC', 'NORMAL', 'PRIVATE', 'HIGHLY_PRIVATE', 'LOCAL_ONLY'
    )),
    effective_memory_eligible boolean NOT NULL,
    effective_training_eligible boolean NOT NULL CHECK (effective_training_eligible = false),
    effective_cloud_eligible boolean NOT NULL,
    effective_policy_version text NOT NULL CHECK (effective_policy_version = 'data-policy-v1'),
    effective_policy_revision_id uuid NOT NULL,
    estimated_total_tokens integer NOT NULL CHECK (estimated_total_tokens >= 0),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL,
    CHECK (effective_privacy_class <> 'LOCAL_ONLY' OR effective_cloud_eligible = false)
);
CREATE INDEX context_packs_owner_id_idx ON havre.context_packs(owner_id);
CREATE INDEX context_packs_trace_id_idx ON havre.context_packs(trace_id);
CREATE INDEX context_packs_constitution_version_id_idx ON havre.context_packs(constitution_version_id);
CREATE INDEX context_packs_identity_version_id_idx ON havre.context_packs(identity_version_id);
CREATE INDEX context_packs_values_version_id_idx ON havre.context_packs(values_version_id);

CREATE TABLE havre.route_decisions (
    route_decision_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    request_id uuid NOT NULL UNIQUE REFERENCES havre.interaction_requests(request_id),
    trace_id char(32) NOT NULL REFERENCES havre.traces(trace_id),
    router_version text NOT NULL,
    selected_provider_id text NOT NULL,
    selected_model_version_id text NOT NULL,
    execution_environment text NOT NULL CHECK (execution_environment IN ('local', 'cloud')),
    effective_policy_revision_id uuid NOT NULL,
    eligible_candidates jsonb NOT NULL CHECK (jsonb_typeof(eligible_candidates) = 'array'),
    excluded_candidates jsonb NOT NULL CHECK (jsonb_typeof(excluded_candidates) = 'array'),
    reason text NOT NULL,
    created_at timestamptz NOT NULL
);
CREATE INDEX route_decisions_owner_id_idx ON havre.route_decisions(owner_id);
CREATE INDEX route_decisions_trace_id_idx ON havre.route_decisions(trace_id);

CREATE TABLE havre.inference_attempts (
    inference_response_id uuid PRIMARY KEY,
    inference_request_id uuid NOT NULL UNIQUE,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    request_id uuid NOT NULL UNIQUE REFERENCES havre.interaction_requests(request_id),
    trace_id char(32) NOT NULL REFERENCES havre.traces(trace_id),
    context_pack_id uuid NOT NULL REFERENCES havre.context_packs(context_pack_id),
    route_decision_id uuid NOT NULL REFERENCES havre.route_decisions(route_decision_id),
    status text NOT NULL CHECK (status = 'completed'),
    finish_reason text NOT NULL CHECK (finish_reason IN ('stop', 'length')),
    provider_id text NOT NULL,
    provider_request_id text NOT NULL,
    provider_class text NOT NULL CHECK (provider_class IN ('local_test', 'self_hosted', 'cloud')),
    model_version_id text NOT NULL,
    adapter_version_id text NULL,
    tokenizer_version_id text NOT NULL,
    serving_config_version text NOT NULL,
    usage jsonb NOT NULL CHECK (jsonb_typeof(usage) = 'object'),
    timing_ms jsonb NOT NULL CHECK (jsonb_typeof(timing_ms) = 'object'),
    output_content_hash text NOT NULL CHECK (output_content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL
);
CREATE INDEX inference_attempts_owner_id_idx ON havre.inference_attempts(owner_id);
CREATE INDEX inference_attempts_trace_id_idx ON havre.inference_attempts(trace_id);
CREATE INDEX inference_attempts_context_pack_id_idx ON havre.inference_attempts(context_pack_id);
CREATE INDEX inference_attempts_route_decision_id_idx ON havre.inference_attempts(route_decision_id);

ALTER TABLE havre.interaction_requests
    ADD CONSTRAINT interaction_requests_context_pack_fk
    FOREIGN KEY (context_pack_id) REFERENCES havre.context_packs(context_pack_id),
    ADD CONSTRAINT interaction_requests_inference_response_fk
    FOREIGN KEY (inference_response_id) REFERENCES havre.inference_attempts(inference_response_id);
CREATE INDEX interaction_requests_context_pack_id_idx
    ON havre.interaction_requests(context_pack_id) WHERE context_pack_id IS NOT NULL;
CREATE INDEX interaction_requests_inference_response_id_idx
    ON havre.interaction_requests(inference_response_id) WHERE inference_response_id IS NOT NULL;

CREATE TABLE havre.spans (
    span_id char(16) PRIMARY KEY CHECK (span_id ~ '^[0-9a-f]{16}$'),
    trace_id char(32) NOT NULL REFERENCES havre.traces(trace_id),
    parent_span_id char(16) NULL,
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
    kind text NOT NULL CHECK (kind IN ('server', 'internal', 'client')),
    started_at timestamptz NOT NULL,
    ended_at timestamptz NOT NULL,
    duration_ms double precision NOT NULL CHECK (duration_ms >= 0),
    status text NOT NULL CHECK (status IN ('ok', 'error')),
    attributes jsonb NOT NULL CHECK (jsonb_typeof(attributes) = 'object'),
    CHECK (ended_at >= started_at)
);
CREATE INDEX spans_trace_id_started_at_idx ON havre.spans(trace_id, started_at);
CREATE INDEX spans_parent_span_id_idx ON havre.spans(parent_span_id)
    WHERE parent_span_id IS NOT NULL;

CREATE FUNCTION havre.reject_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is immutable; append a new record or use the privileged erasure path', TG_TABLE_NAME
        USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER events_are_immutable
BEFORE UPDATE OR DELETE ON havre.events
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();

CREATE TRIGGER identity_versions_are_immutable
BEFORE UPDATE OR DELETE ON havre.identity_artifact_versions
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();

CREATE TRIGGER approvals_are_immutable
BEFORE UPDATE OR DELETE ON havre.approval_records
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();

CREATE TRIGGER context_packs_are_immutable
BEFORE UPDATE OR DELETE ON havre.context_packs
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();

CREATE TRIGGER route_decisions_are_immutable
BEFORE UPDATE OR DELETE ON havre.route_decisions
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();

CREATE TRIGGER inference_attempts_are_immutable
BEFORE UPDATE OR DELETE ON havre.inference_attempts
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();

CREATE TRIGGER spans_are_immutable
BEFORE UPDATE OR DELETE ON havre.spans
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();
