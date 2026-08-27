-- Stage 6 governed proactive Core. This migration permits only simulated,
-- local Web/inbox delivery. External delivery remains impossible by CHECK.

ALTER TABLE havre.interaction_requests
    DROP CONSTRAINT interaction_requests_request_kind_check;
ALTER TABLE havre.interaction_requests
    ADD CONSTRAINT interaction_requests_request_kind_check CHECK (
        request_kind IN ('interaction', 'scene_command', 'proactive_work')
    );

CREATE TABLE havre.proactive_preference_revisions (
    preference_revision_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    revision integer NOT NULL CHECK (revision > 0),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    simulation_only boolean NOT NULL CHECK (simulation_only = true),
    external_delivery_authorized boolean NOT NULL CHECK (external_delivery_authorized = false),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL,
    UNIQUE (owner_id, preference_revision_id),
    UNIQUE (owner_id, revision)
);

CREATE TABLE havre.proactive_triggers (
    trigger_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    request_id uuid NOT NULL,
    trace_id char(32) NOT NULL,
    trigger_type text NOT NULL CHECK (trigger_type ~ '^[a-z][a-z0-9_]{1,63}$'),
    source_kind text NOT NULL CHECK (source_kind IN (
        'scheduled_time', 'goal', 'scene_session', 'owner_reminder',
        'belief_confirmation', 'system_operational', 'synthetic_life_context'
    )),
    source_refs jsonb NOT NULL CHECK (
        jsonb_typeof(source_refs) = 'array' AND jsonb_array_length(source_refs) > 0
    ),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    privacy_class text NOT NULL CHECK (privacy_class IN (
        'PUBLIC', 'NORMAL', 'PRIVATE', 'HIGHLY_PRIVATE', 'LOCAL_ONLY'
    )),
    memory_eligible boolean NOT NULL,
    training_eligible boolean NOT NULL CHECK (training_eligible = false),
    cloud_eligible boolean NOT NULL,
    policy_version text NOT NULL CHECK (policy_version = 'data-policy-v1'),
    policy_revision_id uuid NOT NULL,
    policy_decision_source text NOT NULL CHECK (policy_decision_source IN (
        'owner_default', 'owner_explicit', 'derived_conservative'
    )),
    policy_authorization_ref text NULL,
    simulation_only boolean NOT NULL CHECK (simulation_only = true),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    observed_at timestamptz NOT NULL,
    recorded_at timestamptz NOT NULL,
    UNIQUE (owner_id, trigger_id),
    FOREIGN KEY (owner_id, request_id, trace_id)
        REFERENCES havre.interaction_requests(owner_id, request_id, trace_id),
    CHECK (privacy_class <> 'LOCAL_ONLY' OR cloud_eligible = false)
);
CREATE INDEX proactive_triggers_owner_source_idx
    ON havre.proactive_triggers(owner_id, source_kind, recorded_at, trigger_id);

CREATE TABLE havre.proactive_proposals (
    proposal_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    request_id uuid NOT NULL,
    trace_id char(32) NOT NULL,
    category text NOT NULL CHECK (category ~ '^[a-z][a-z0-9_]{1,63}$'),
    primary_trigger_id uuid NOT NULL,
    trigger_refs jsonb NOT NULL CHECK (
        jsonb_typeof(trigger_refs) = 'array' AND jsonb_array_length(trigger_refs) > 0
    ),
    deduplication_key text NOT NULL CHECK (length(deduplication_key) BETWEEN 1 AND 240),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    privacy_class text NOT NULL CHECK (privacy_class IN (
        'PUBLIC', 'NORMAL', 'PRIVATE', 'HIGHLY_PRIVATE', 'LOCAL_ONLY'
    )),
    memory_eligible boolean NOT NULL,
    training_eligible boolean NOT NULL CHECK (training_eligible = false),
    cloud_eligible boolean NOT NULL,
    policy_version text NOT NULL CHECK (policy_version = 'data-policy-v1'),
    policy_revision_id uuid NOT NULL,
    policy_decision_source text NOT NULL CHECK (policy_decision_source IN (
        'owner_default', 'owner_explicit', 'derived_conservative'
    )),
    policy_authorization_ref text NULL,
    earliest_eligible_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    simulation_only boolean NOT NULL CHECK (simulation_only = true),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL,
    UNIQUE (owner_id, proposal_id),
    FOREIGN KEY (owner_id, primary_trigger_id)
        REFERENCES havre.proactive_triggers(owner_id, trigger_id),
    FOREIGN KEY (owner_id, request_id, trace_id)
        REFERENCES havre.interaction_requests(owner_id, request_id, trace_id),
    CHECK (expires_at > earliest_eligible_at),
    CHECK (privacy_class <> 'LOCAL_ONLY' OR cloud_eligible = false)
);
CREATE INDEX proactive_proposals_owner_dedupe_idx
    ON havre.proactive_proposals(owner_id, deduplication_key, expires_at);

CREATE TABLE havre.interruption_decisions (
    interruption_decision_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    proposal_id uuid NOT NULL,
    preference_revision_id uuid NOT NULL,
    decision text NOT NULL CHECK (decision IN (
        'SEND_NOW', 'DEFER', 'DROP', 'REQUEST_OWNER_CONFIRMATION'
    )),
    policy_version text NOT NULL CHECK (policy_version = 'interruption-policy-conservative-v1'),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    trace_id char(32) NOT NULL,
    defer_until timestamptz NULL,
    expires_at timestamptz NOT NULL,
    simulation_only boolean NOT NULL CHECK (simulation_only = true),
    external_delivery_authorized boolean NOT NULL CHECK (external_delivery_authorized = false),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    decided_at timestamptz NOT NULL,
    UNIQUE (owner_id, interruption_decision_id),
    UNIQUE (owner_id, proposal_id),
    FOREIGN KEY (owner_id, proposal_id)
        REFERENCES havre.proactive_proposals(owner_id, proposal_id),
    FOREIGN KEY (owner_id, preference_revision_id)
        REFERENCES havre.proactive_preference_revisions(owner_id, preference_revision_id),
    FOREIGN KEY (owner_id, trace_id) REFERENCES havre.traces(owner_id, trace_id),
    CHECK ((decision = 'DEFER') = (defer_until IS NOT NULL))
);

CREATE TABLE havre.proactive_context_packs (
    proactive_context_pack_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    proposal_id uuid NOT NULL,
    interruption_decision_id uuid NOT NULL,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    privacy_class text NOT NULL CHECK (privacy_class IN (
        'PUBLIC', 'NORMAL', 'PRIVATE', 'HIGHLY_PRIVATE', 'LOCAL_ONLY'
    )),
    training_eligible boolean NOT NULL CHECK (training_eligible = false),
    cloud_eligible boolean NOT NULL,
    trace_id char(32) NOT NULL,
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (owner_id, proactive_context_pack_id),
    UNIQUE (owner_id, interruption_decision_id),
    FOREIGN KEY (owner_id, proposal_id)
        REFERENCES havre.proactive_proposals(owner_id, proposal_id),
    FOREIGN KEY (owner_id, interruption_decision_id)
        REFERENCES havre.interruption_decisions(owner_id, interruption_decision_id),
    FOREIGN KEY (owner_id, trace_id) REFERENCES havre.traces(owner_id, trace_id),
    CHECK (privacy_class <> 'LOCAL_ONLY' OR cloud_eligible = false)
);

CREATE TABLE havre.rendered_proactive_messages (
    rendering_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    proposal_id uuid NOT NULL,
    interruption_decision_id uuid NOT NULL,
    proactive_context_pack_id uuid NOT NULL,
    renderer_version text NOT NULL CHECK (renderer_version = 'proactive-template-v1'),
    content_text text NOT NULL CHECK (length(content_text) BETWEEN 1 AND 500),
    preview_policy text NOT NULL CHECK (preview_policy IN ('none', 'generic_private')),
    preview_text text NULL CHECK (preview_text IS NULL OR length(preview_text) <= 200),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    trace_id char(32) NOT NULL,
    simulation_only boolean NOT NULL CHECK (simulation_only = true),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (owner_id, rendering_id),
    UNIQUE (owner_id, interruption_decision_id),
    FOREIGN KEY (owner_id, proposal_id)
        REFERENCES havre.proactive_proposals(owner_id, proposal_id),
    FOREIGN KEY (owner_id, interruption_decision_id)
        REFERENCES havre.interruption_decisions(owner_id, interruption_decision_id),
    FOREIGN KEY (owner_id, proactive_context_pack_id)
        REFERENCES havre.proactive_context_packs(owner_id, proactive_context_pack_id),
    FOREIGN KEY (owner_id, trace_id) REFERENCES havre.traces(owner_id, trace_id),
    CHECK (preview_policy <> 'none' OR preview_text IS NULL)
);

CREATE TABLE havre.proactive_delivery_attempts (
    delivery_attempt_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    proposal_id uuid NOT NULL,
    interruption_decision_id uuid NOT NULL,
    rendering_id uuid NOT NULL,
    channel text NOT NULL CHECK (channel = 'web_inbox'),
    adapter_version text NOT NULL CHECK (adapter_version = 'local-web-inbox-v1'),
    idempotency_key text NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 240),
    attempt_number integer NOT NULL CHECK (attempt_number = 1),
    status text NOT NULL CHECK (status IN ('delivered', 'failed', 'expired', 'cancelled')),
    retryable boolean NOT NULL CHECK (retryable = false),
    provider_receipt_id text NULL,
    failure_code text NULL,
    visible_at timestamptz NULL,
    trace_id char(32) NOT NULL,
    simulation_only boolean NOT NULL CHECK (simulation_only = true),
    external_delivery_authorized boolean NOT NULL CHECK (external_delivery_authorized = false),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL,
    UNIQUE (owner_id, delivery_attempt_id),
    UNIQUE (owner_id, channel, idempotency_key),
    UNIQUE (owner_id, interruption_decision_id),
    FOREIGN KEY (owner_id, proposal_id)
        REFERENCES havre.proactive_proposals(owner_id, proposal_id),
    FOREIGN KEY (owner_id, interruption_decision_id)
        REFERENCES havre.interruption_decisions(owner_id, interruption_decision_id),
    FOREIGN KEY (owner_id, rendering_id)
        REFERENCES havre.rendered_proactive_messages(owner_id, rendering_id),
    FOREIGN KEY (owner_id, trace_id) REFERENCES havre.traces(owner_id, trace_id),
    CHECK ((status = 'delivered') = (provider_receipt_id IS NOT NULL AND visible_at IS NOT NULL)),
    CHECK (status <> 'delivered' OR failure_code IS NULL)
);

CREATE TABLE havre.proactive_inbox_messages (
    inbox_message_id uuid PRIMARY KEY,
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    proposal_id uuid NOT NULL,
    delivery_attempt_id uuid NOT NULL,
    rendering_id uuid NOT NULL,
    assistant_event_id uuid NOT NULL,
    content_text text NOT NULL CHECK (length(content_text) BETWEEN 1 AND 500),
    visible_at timestamptz NOT NULL,
    simulation_only boolean NOT NULL CHECK (simulation_only = true),
    UNIQUE (owner_id, inbox_message_id),
    UNIQUE (owner_id, proposal_id),
    UNIQUE (owner_id, delivery_attempt_id),
    UNIQUE (owner_id, assistant_event_id),
    FOREIGN KEY (owner_id, proposal_id)
        REFERENCES havre.proactive_proposals(owner_id, proposal_id),
    FOREIGN KEY (owner_id, delivery_attempt_id)
        REFERENCES havre.proactive_delivery_attempts(owner_id, delivery_attempt_id),
    FOREIGN KEY (owner_id, rendering_id)
        REFERENCES havre.rendered_proactive_messages(owner_id, rendering_id),
    FOREIGN KEY (owner_id, assistant_event_id)
        REFERENCES havre.events(owner_id, event_id) DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE havre.proactive_lifecycle_events (
    lifecycle_event_id uuid PRIMARY KEY,
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    proposal_id uuid NULL,
    event_type text NOT NULL CHECK (event_type IN (
        'PROACTIVE_TRIGGER_RECORDED', 'PROACTIVE_PROPOSAL_CREATED',
        'PROACTIVE_POLICY_DECIDED', 'PROACTIVE_MESSAGE_RENDERED',
        'PROACTIVE_DELIVERY_ATTEMPTED', 'PROACTIVE_MESSAGE_DELIVERED',
        'PROACTIVE_PROPOSAL_DEFERRED', 'PROACTIVE_PROPOSAL_DROPPED',
        'PROACTIVE_OWNER_CONFIRMATION_REQUESTED'
    )),
    artifact_kind text NOT NULL,
    artifact_id uuid NOT NULL,
    trace_id char(32) NOT NULL,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    recorded_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    FOREIGN KEY (owner_id, proposal_id)
        REFERENCES havre.proactive_proposals(owner_id, proposal_id) DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (owner_id, trace_id) REFERENCES havre.traces(owner_id, trace_id)
);
CREATE INDEX proactive_lifecycle_owner_proposal_idx
    ON havre.proactive_lifecycle_events(owner_id, proposal_id, recorded_at, lifecycle_event_id);

DO $$
DECLARE table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'proactive_preference_revisions', 'proactive_triggers',
        'proactive_proposals', 'interruption_decisions',
        'proactive_context_packs', 'rendered_proactive_messages',
        'proactive_delivery_attempts', 'proactive_inbox_messages',
        'proactive_lifecycle_events'
    ] LOOP
        EXECUTE format(
            'CREATE TRIGGER %I_immutable BEFORE UPDATE OR DELETE ON havre.%I '
            'FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation()',
            table_name, table_name
        );
    END LOOP;
END
$$;
