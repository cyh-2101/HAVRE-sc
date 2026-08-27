-- Stage 6/7 acceptance corrections: revocation admission, owner controls,
-- response linkage, and durable scheduled/event-driven proactive work.

CREATE OR REPLACE FUNCTION havre.reject_revoked_offline_source()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM havre.offline_source_revocations AS revoked
        WHERE revoked.owner_id = NEW.owner_id
          AND revoked.source_event_id = NEW.source_event_id
    ) THEN
        RAISE EXCEPTION 'revoked offline source cannot be reused'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER reflection_evidence_reject_revoked
    BEFORE INSERT ON havre.reflection_proposal_evidence
    FOR EACH ROW EXECUTE FUNCTION havre.reject_revoked_offline_source();
CREATE TRIGGER memory_lifecycle_evidence_reject_revoked
    BEFORE INSERT ON havre.memory_lifecycle_proposal_evidence
    FOR EACH ROW EXECUTE FUNCTION havre.reject_revoked_offline_source();
CREATE TRIGGER dataset_snapshot_source_reject_revoked
    BEFORE INSERT ON havre.dataset_snapshot_sources
    FOR EACH ROW EXECUTE FUNCTION havre.reject_revoked_offline_source();

CREATE TABLE havre.proactive_owner_actions (
    action_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    proposal_id uuid NOT NULL,
    idempotency_key text NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 200),
    action_type text NOT NULL CHECK (action_type IN (
        'responded', 'dismissed', 'snoozed', 'non_response', 'stopped'
    )),
    inbox_message_id uuid NULL,
    response_event_id uuid NULL,
    snooze_until timestamptz NULL,
    deduplication_key text NOT NULL CHECK (length(deduplication_key) BETWEEN 1 AND 240),
    subject_refs text[] NOT NULL DEFAULT '{}',
    reason text NOT NULL CHECK (length(reason) BETWEEN 1 AND 1000),
    observed_at timestamptz NOT NULL,
    trace_id char(32) NOT NULL,
    simulation_only boolean NOT NULL CHECK (simulation_only = true),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    recorded_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (owner_id, action_id),
    UNIQUE (owner_id, idempotency_key),
    FOREIGN KEY (owner_id, proposal_id)
        REFERENCES havre.proactive_proposals(owner_id, proposal_id),
    FOREIGN KEY (owner_id, inbox_message_id)
        REFERENCES havre.proactive_inbox_messages(owner_id, inbox_message_id),
    FOREIGN KEY (owner_id, response_event_id)
        REFERENCES havre.events(owner_id, event_id),
    FOREIGN KEY (owner_id, trace_id)
        REFERENCES havre.traces(owner_id, trace_id),
    CHECK ((action_type = 'responded') = (response_event_id IS NOT NULL)),
    CHECK ((action_type = 'snoozed') = (snooze_until IS NOT NULL)),
    CHECK (snooze_until IS NULL OR snooze_until > observed_at),
    CHECK (action_type NOT IN ('responded', 'dismissed', 'non_response')
           OR inbox_message_id IS NOT NULL)
);
CREATE INDEX proactive_owner_actions_dedupe_idx
    ON havre.proactive_owner_actions(
        owner_id, deduplication_key, observed_at DESC, action_id DESC
    );
CREATE INDEX proactive_owner_actions_subject_idx
    ON havre.proactive_owner_actions USING gin(subject_refs);
CREATE INDEX proactive_owner_actions_proposal_idx
    ON havre.proactive_owner_actions(owner_id, proposal_id);
CREATE INDEX proactive_owner_actions_trace_idx
    ON havre.proactive_owner_actions(owner_id, trace_id);
CREATE INDEX proactive_owner_actions_inbox_idx
    ON havre.proactive_owner_actions(owner_id, inbox_message_id)
    WHERE inbox_message_id IS NOT NULL;
CREATE INDEX proactive_owner_actions_response_idx
    ON havre.proactive_owner_actions(owner_id, response_event_id)
    WHERE response_event_id IS NOT NULL;

CREATE OR REPLACE FUNCTION havre.guard_proactive_owner_action()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    proposal_row havre.proactive_proposals%ROWTYPE;
    inbox_visible_at timestamptz;
    response_recorded_at timestamptz;
    response_type text;
BEGIN
    SELECT * INTO proposal_row
    FROM havre.proactive_proposals
    WHERE owner_id = NEW.owner_id AND proposal_id = NEW.proposal_id;
    IF NOT FOUND OR proposal_row.deduplication_key <> NEW.deduplication_key
       OR proposal_row.trace_id <> NEW.trace_id
       OR ARRAY(
            SELECT jsonb_array_elements_text(proposal_row.payload->'subject_refs')
          ) <> NEW.subject_refs THEN
        RAISE EXCEPTION 'proactive owner action does not match proposal'
            USING ERRCODE = '55000';
    END IF;

    IF NEW.inbox_message_id IS NOT NULL THEN
        SELECT visible_at INTO inbox_visible_at
        FROM havre.proactive_inbox_messages
        WHERE owner_id = NEW.owner_id
          AND inbox_message_id = NEW.inbox_message_id
          AND proposal_id = NEW.proposal_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'proactive owner action inbox does not match proposal'
                USING ERRCODE = '55000';
        END IF;
    END IF;

    IF NEW.action_type = 'responded' THEN
        SELECT event_type, recorded_at INTO response_type, response_recorded_at
        FROM havre.events
        WHERE owner_id = NEW.owner_id AND event_id = NEW.response_event_id;
        IF NOT FOUND OR response_type <> 'USER_MESSAGE'
           OR response_recorded_at < inbox_visible_at THEN
            RAISE EXCEPTION 'response linkage requires a later owner message event'
                USING ERRCODE = '55000';
        END IF;
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER proactive_owner_actions_guard
    BEFORE INSERT ON havre.proactive_owner_actions
    FOR EACH ROW EXECUTE FUNCTION havre.guard_proactive_owner_action();
CREATE TRIGGER proactive_owner_actions_immutable
    BEFORE UPDATE OR DELETE ON havre.proactive_owner_actions
    FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();

ALTER TABLE havre.proactive_lifecycle_events
    DROP CONSTRAINT proactive_lifecycle_events_event_type_check;
ALTER TABLE havre.proactive_lifecycle_events
    ADD CONSTRAINT proactive_lifecycle_events_event_type_check CHECK (event_type IN (
        'PROACTIVE_TRIGGER_RECORDED', 'PROACTIVE_PROPOSAL_CREATED',
        'PROACTIVE_POLICY_DECIDED', 'PROACTIVE_MESSAGE_RENDERED',
        'PROACTIVE_DELIVERY_ATTEMPTED', 'PROACTIVE_MESSAGE_DELIVERED',
        'PROACTIVE_PROPOSAL_DEFERRED', 'PROACTIVE_PROPOSAL_DROPPED',
        'PROACTIVE_OWNER_CONFIRMATION_REQUESTED',
        'PROACTIVE_OWNER_RESPONDED', 'PROACTIVE_OWNER_DISMISSED',
        'PROACTIVE_OWNER_SNOOZED', 'PROACTIVE_NON_RESPONSE_RECORDED',
        'PROACTIVE_OWNER_STOPPED'
    ));

CREATE TABLE havre.proactive_work_items (
    work_item_id uuid PRIMARY KEY,
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    work_kind text NOT NULL CHECK (work_kind IN ('scheduled', 'event_driven')),
    idempotency_key text NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 200),
    input_fingerprint text NOT NULL CHECK (input_fingerprint ~ '^sha256:[0-9a-f]{64}$'),
    command_payload jsonb NOT NULL CHECK (jsonb_typeof(command_payload) = 'object'),
    not_before timestamptz NOT NULL,
    status text NOT NULL CHECK (status IN (
        'pending', 'leased', 'succeeded', 'retryable_failed',
        'terminal_failed', 'cancelled'
    )),
    lease_owner text NULL,
    lease_expires_at timestamptz NULL,
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts integer NOT NULL DEFAULT 3 CHECK (max_attempts > 0),
    last_error_code text NULL,
    request_id uuid NULL,
    proposal_id uuid NULL,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    completed_at timestamptz NULL,
    UNIQUE (owner_id, work_item_id),
    UNIQUE (owner_id, work_kind, idempotency_key),
    FOREIGN KEY (owner_id, request_id)
        REFERENCES havre.interaction_requests(owner_id, request_id),
    FOREIGN KEY (owner_id, proposal_id)
        REFERENCES havre.proactive_proposals(owner_id, proposal_id),
    CHECK ((status = 'leased') = (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)),
    CHECK ((request_id IS NULL) = (proposal_id IS NULL))
);
CREATE INDEX proactive_work_items_claim_idx
    ON havre.proactive_work_items(status, not_before, created_at, work_item_id)
    WHERE status IN ('pending', 'leased', 'retryable_failed');
CREATE INDEX proactive_work_items_request_idx
    ON havre.proactive_work_items(owner_id, request_id)
    WHERE request_id IS NOT NULL;
CREATE INDEX proactive_work_items_proposal_idx
    ON havre.proactive_work_items(owner_id, proposal_id)
    WHERE proposal_id IS NOT NULL;
