-- Stage 5 Intervention Policy, first-class Scene Sessions, and Web simulation.
-- This migration is additive. It does not activate Stage 6 proactive outreach,
-- scheduling, rendering, or delivery.

ALTER TABLE havre.interaction_requests
    ADD COLUMN request_kind text NOT NULL DEFAULT 'interaction';
ALTER TABLE havre.interaction_requests
    ADD CONSTRAINT interaction_requests_request_kind_check CHECK (
        request_kind IN ('interaction', 'scene_command')
    );

ALTER TABLE havre.events DROP CONSTRAINT events_event_type_check;
ALTER TABLE havre.events ADD CONSTRAINT events_event_type_check CHECK (event_type IN (
    'USER_MESSAGE', 'ASSISTANT_MESSAGE', 'INTERACTION_FAILED',
    'MEMORY_CREATED', 'MEMORY_REVISED', 'MEMORY_RETRACTED',
    'CURRENT_STATE_ESTIMATED',
    'USER_BELIEF_CREATED', 'USER_BELIEF_REVISED', 'USER_BELIEF_TRANSITIONED',
    'CONSOLIDATION_PROPOSED', 'CONSOLIDATION_REVIEWED',
    'GOAL_CREATED', 'GOAL_UPDATED', 'GOAL_COMPLETED', 'PROGRESS_RECORDED',
    'SCENE_SESSION_PLANNED', 'SCENE_SESSION_STARTED', 'SCENE_PHASE_CHANGED',
    'SCENE_SESSION_PAUSED', 'SCENE_SESSION_ENDED', 'USER_SIGNAL',
    'INTERVENTION_DECIDED', 'USER_ACTION_REPORTED', 'OUTCOME_REPORTED',
    'REFLECTION_CREATED'
));

CREATE TABLE havre.scene_sessions (
    scene_session_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    opened_session_id uuid NOT NULL,
    scene_type text NOT NULL CHECK (scene_type ~ '^[a-z][a-z0-9_]{1,63}$'),
    situation jsonb NOT NULL CHECK (jsonb_typeof(situation) = 'object'),
    planned_goal jsonb NOT NULL CHECK (jsonb_typeof(planned_goal) = 'object'),
    anticipated_triggers jsonb NOT NULL CHECK (jsonb_typeof(anticipated_triggers) = 'array'),
    phase text NOT NULL CHECK (phase IN ('before', 'during', 'after', 'closed')),
    status text NOT NULL CHECK (status IN (
        'planned', 'active', 'paused', 'completed', 'abandoned', 'cancelled'
    )),
    planned_start_at timestamptz NULL,
    started_at timestamptz NULL,
    ended_at timestamptz NULL,
    revision integer NOT NULL CHECK (revision > 0),
    created_event_id uuid NOT NULL,
    last_event_id uuid NOT NULL,
    trace_id char(32) NOT NULL,
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
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (owner_id, scene_session_id),
    UNIQUE (owner_id, scene_session_id, revision),
    FOREIGN KEY (opened_session_id, owner_id)
        REFERENCES havre.sessions(session_id, owner_id),
    FOREIGN KEY (owner_id, created_event_id)
        REFERENCES havre.events(owner_id, event_id) DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (owner_id, last_event_id)
        REFERENCES havre.events(owner_id, event_id) DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (owner_id, trace_id)
        REFERENCES havre.traces(owner_id, trace_id),
    CHECK (privacy_class <> 'LOCAL_ONLY' OR cloud_eligible = false),
    CHECK (
        privacy_class <> 'HIGHLY_PRIVATE'
        OR cloud_eligible = false
        OR (policy_decision_source = 'owner_explicit' AND policy_authorization_ref IS NOT NULL)
    ),
    CHECK ((phase = 'closed') = (status IN ('completed', 'abandoned', 'cancelled'))),
    CHECK (status <> 'planned' OR phase = 'before'),
    CHECK (status <> 'paused' OR phase = 'during'),
    CHECK (phase NOT IN ('during', 'after') OR started_at IS NOT NULL),
    CHECK (phase <> 'closed' OR status = 'cancelled' OR started_at IS NOT NULL),
    CHECK ((phase = 'closed') = (ended_at IS NOT NULL))
);
CREATE INDEX scene_sessions_owner_state_idx
    ON havre.scene_sessions(owner_id, status, phase, updated_at DESC);
CREATE INDEX scene_sessions_owner_opened_session_idx
    ON havre.scene_sessions(owner_id, opened_session_id);
CREATE INDEX scene_sessions_opened_session_owner_idx
    ON havre.scene_sessions(opened_session_id, owner_id);
CREATE INDEX scene_sessions_owner_created_event_idx
    ON havre.scene_sessions(owner_id, created_event_id);
CREATE INDEX scene_sessions_owner_last_event_idx
    ON havre.scene_sessions(owner_id, last_event_id);
CREATE INDEX scene_sessions_owner_trace_idx
    ON havre.scene_sessions(owner_id, trace_id);

ALTER TABLE havre.events ADD COLUMN scene_session_id uuid NULL;
ALTER TABLE havre.events
    ADD CONSTRAINT events_owner_scene_session_fk
    FOREIGN KEY (owner_id, scene_session_id)
    REFERENCES havre.scene_sessions(owner_id, scene_session_id)
    DEFERRABLE INITIALLY DEFERRED;
CREATE INDEX events_owner_scene_recorded_idx
    ON havre.events(owner_id, scene_session_id, recorded_at)
    WHERE scene_session_id IS NOT NULL;
CREATE INDEX events_owner_request_trace_idx
    ON havre.events(owner_id, request_id, trace_id);
CREATE INDEX events_session_owner_idx
    ON havre.events(session_id, owner_id);

CREATE TABLE havre.scene_records (
    scene_record_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    scene_session_id uuid NOT NULL,
    record_type text NOT NULL CHECK (record_type IN (
        'signal', 'intervention', 'action', 'outcome', 'reflection'
    )),
    phase text NOT NULL CHECK (phase IN ('before', 'during', 'after')),
    sequence_number integer NOT NULL CHECK (sequence_number > 0),
    occurred_at timestamptz NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    event_id uuid NOT NULL,
    assistant_event_id uuid NULL,
    artifact_kind text NULL CHECK (
        artifact_kind IS NULL OR artifact_kind = 'intervention_decision'
    ),
    artifact_id uuid NULL,
    artifact_revision integer NULL CHECK (artifact_revision > 0),
    causal_predecessor_id uuid NULL,
    source text NOT NULL CHECK (source IN (
        'owner_self_report', 'web_simulation', 'intervention_policy'
    )),
    uncertainty_note text NULL CHECK (
        uncertainty_note IS NULL OR length(uncertainty_note) BETWEEN 1 AND 1000
    ),
    content jsonb NOT NULL CHECK (jsonb_typeof(content) = 'object'),
    trace_id char(32) NOT NULL,
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
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    UNIQUE (owner_id, scene_record_id),
    UNIQUE (owner_id, scene_session_id, scene_record_id),
    UNIQUE (owner_id, scene_session_id, sequence_number),
    FOREIGN KEY (owner_id, scene_session_id)
        REFERENCES havre.scene_sessions(owner_id, scene_session_id),
    FOREIGN KEY (owner_id, event_id)
        REFERENCES havre.events(owner_id, event_id),
    FOREIGN KEY (owner_id, assistant_event_id)
        REFERENCES havre.events(owner_id, event_id),
    FOREIGN KEY (owner_id, scene_session_id, causal_predecessor_id)
        REFERENCES havre.scene_records(owner_id, scene_session_id, scene_record_id),
    FOREIGN KEY (owner_id, trace_id)
        REFERENCES havre.traces(owner_id, trace_id),
    CHECK (privacy_class <> 'LOCAL_ONLY' OR cloud_eligible = false),
    CHECK (
        (record_type = 'intervention') = (
            assistant_event_id IS NOT NULL AND artifact_kind IS NOT NULL
            AND artifact_id IS NOT NULL AND artifact_revision IS NOT NULL
        )
    ),
    CHECK (
        (artifact_kind IS NULL) = (artifact_id IS NULL)
        AND (artifact_id IS NULL) = (artifact_revision IS NULL)
    )
);
CREATE INDEX scene_records_owner_event_idx ON havre.scene_records(owner_id, event_id);
CREATE INDEX scene_records_owner_predecessor_idx
    ON havre.scene_records(owner_id, scene_session_id, causal_predecessor_id)
    WHERE causal_predecessor_id IS NOT NULL;
CREATE INDEX scene_records_owner_assistant_event_idx
    ON havre.scene_records(owner_id, assistant_event_id)
    WHERE assistant_event_id IS NOT NULL;
CREATE INDEX scene_records_owner_trace_idx
    ON havre.scene_records(owner_id, trace_id);

CREATE TABLE havre.intervention_decisions (
    intervention_decision_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    scene_session_id uuid NOT NULL,
    scene_revision integer NOT NULL CHECK (scene_revision > 0),
    input_event_id uuid NOT NULL,
    input_record_id uuid NULL,
    decision_event_id uuid NOT NULL,
    guidance_event_id uuid NOT NULL,
    phase text NOT NULL CHECK (phase IN ('before', 'during', 'after')),
    policy_version_id text NOT NULL CHECK (
        policy_version_id = 'intervention-policy-sim-v1'
    ),
    policy_release_status text NOT NULL CHECK (
        policy_release_status = 'candidate_owner_acceptance'
    ),
    constitution_version_id text NOT NULL,
    identity_version_id text NOT NULL,
    values_version_id text NOT NULL,
    branch text NOT NULL CHECK (branch IN (
        'safety_first', 'clarification', 'recovery', 'minimum_action',
        'preparation', 'reflection'
    )),
    recommended_intervention text NOT NULL,
    response_style text NOT NULL,
    guidance text NOT NULL CHECK (length(guidance) BETWEEN 1 AND 500),
    minimum_action text NULL CHECK (
        minimum_action IS NULL OR length(minimum_action) BETWEEN 1 AND 500
    ),
    clarification_question text NULL CHECK (
        clarification_question IS NULL OR length(clarification_question) BETWEEN 1 AND 500
    ),
    reason_codes jsonb NOT NULL CHECK (
        jsonb_typeof(reason_codes) = 'array' AND jsonb_array_length(reason_codes) > 0
    ),
    required_constraints jsonb NOT NULL CHECK (
        jsonb_typeof(required_constraints) = 'array'
        AND jsonb_array_length(required_constraints) > 0
    ),
    outreach_authorized boolean NOT NULL CHECK (outreach_authorized = false),
    simulation_only boolean NOT NULL CHECK (simulation_only = true),
    evidence_snapshot jsonb NOT NULL CHECK (jsonb_typeof(evidence_snapshot) = 'array'),
    trace_id char(32) NOT NULL,
    privacy_class text NOT NULL CHECK (privacy_class IN (
        'PUBLIC', 'NORMAL', 'PRIVATE', 'HIGHLY_PRIVATE', 'LOCAL_ONLY'
    )),
    memory_eligible boolean NOT NULL,
    training_eligible boolean NOT NULL DEFAULT false CHECK (training_eligible = false),
    cloud_eligible boolean NOT NULL,
    data_policy_version text NOT NULL CHECK (data_policy_version = 'data-policy-v1'),
    policy_revision_id uuid NOT NULL,
    policy_decision_source text NOT NULL CHECK (policy_decision_source = 'derived_conservative'),
    policy_authorization_ref text NULL,
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (owner_id, intervention_decision_id),
    UNIQUE (owner_id, scene_session_id, intervention_decision_id),
    UNIQUE (owner_id, decision_event_id),
    UNIQUE (owner_id, guidance_event_id),
    FOREIGN KEY (owner_id, scene_session_id)
        REFERENCES havre.scene_sessions(owner_id, scene_session_id),
    FOREIGN KEY (owner_id, input_event_id)
        REFERENCES havre.events(owner_id, event_id),
    FOREIGN KEY (owner_id, scene_session_id, input_record_id)
        REFERENCES havre.scene_records(owner_id, scene_session_id, scene_record_id),
    FOREIGN KEY (owner_id, decision_event_id)
        REFERENCES havre.events(owner_id, event_id),
    FOREIGN KEY (owner_id, guidance_event_id)
        REFERENCES havre.events(owner_id, event_id),
    FOREIGN KEY (owner_id, trace_id)
        REFERENCES havre.traces(owner_id, trace_id),
    CHECK (phase <> 'during' OR length(guidance) <= 240),
    CHECK ((branch = 'clarification') = (clarification_question IS NOT NULL)),
    CHECK (privacy_class <> 'LOCAL_ONLY' OR cloud_eligible = false)
);
CREATE INDEX intervention_decisions_owner_scene_idx
    ON havre.intervention_decisions(owner_id, scene_session_id, created_at);
CREATE INDEX intervention_decisions_owner_input_event_idx
    ON havre.intervention_decisions(owner_id, input_event_id);
CREATE INDEX intervention_decisions_owner_input_record_idx
    ON havre.intervention_decisions(owner_id, scene_session_id, input_record_id)
    WHERE input_record_id IS NOT NULL;
CREATE INDEX intervention_decisions_owner_trace_idx
    ON havre.intervention_decisions(owner_id, trace_id);

ALTER TABLE havre.scene_records
    ADD COLUMN typed_intervention_decision_id uuid GENERATED ALWAYS AS (
        CASE WHEN artifact_kind = 'intervention_decision' THEN artifact_id ELSE NULL END
    ) STORED;
ALTER TABLE havre.scene_records
    ADD CONSTRAINT scene_records_owner_intervention_decision_fk
    FOREIGN KEY (owner_id, scene_session_id, typed_intervention_decision_id)
    REFERENCES havre.intervention_decisions(
        owner_id, scene_session_id, intervention_decision_id
    ) DEFERRABLE INITIALLY DEFERRED;
CREATE INDEX scene_records_owner_intervention_decision_idx
    ON havre.scene_records(owner_id, scene_session_id, typed_intervention_decision_id)
    WHERE typed_intervention_decision_id IS NOT NULL;

CREATE TABLE havre.guidance_outcome_observations (
    outcome_observation_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    scene_session_id uuid NOT NULL,
    intervention_decision_id uuid NOT NULL,
    guidance_event_id uuid NOT NULL,
    action_record_id uuid NOT NULL,
    outcome_record_id uuid NOT NULL,
    reflection_record_id uuid NOT NULL,
    observation_window_started_at timestamptz NOT NULL,
    observation_window_ended_at timestamptz NOT NULL,
    reporter text NOT NULL CHECK (reporter = 'user_self_report'),
    action_attempted text NOT NULL CHECK (action_attempted IN ('yes', 'no', 'unknown')),
    planned_scene_status text NOT NULL CHECK (planned_scene_status IN (
        'completed', 'partial', 'abandoned', 'cancelled', 'unknown'
    )),
    helpfulness text NOT NULL CHECK (helpfulness IN (
        'helpful', 'not_helpful', 'uncertain', 'not_asked'
    )),
    too_passive text NOT NULL CHECK (too_passive IN ('yes', 'no', 'unknown')),
    too_forceful text NOT NULL CHECK (too_forceful IN ('yes', 'no', 'unknown')),
    later_regret text NOT NULL CHECK (later_regret IN ('yes', 'no', 'unsure', 'not_asked')),
    limitations jsonb NOT NULL CHECK (
        jsonb_typeof(limitations) = 'array' AND jsonb_array_length(limitations) > 0
    ),
    consented boolean NOT NULL CHECK (consented = true),
    evidence_snapshot jsonb NOT NULL CHECK (jsonb_typeof(evidence_snapshot) = 'array'),
    created_event_id uuid NOT NULL,
    trace_id char(32) NOT NULL,
    privacy_class text NOT NULL CHECK (privacy_class IN (
        'PUBLIC', 'NORMAL', 'PRIVATE', 'HIGHLY_PRIVATE', 'LOCAL_ONLY'
    )),
    memory_eligible boolean NOT NULL,
    training_eligible boolean NOT NULL DEFAULT false CHECK (training_eligible = false),
    cloud_eligible boolean NOT NULL,
    policy_version text NOT NULL CHECK (policy_version = 'data-policy-v1'),
    policy_revision_id uuid NOT NULL,
    policy_decision_source text NOT NULL CHECK (policy_decision_source = 'derived_conservative'),
    policy_authorization_ref text NULL,
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (owner_id, outcome_observation_id),
    FOREIGN KEY (owner_id, scene_session_id, intervention_decision_id)
        REFERENCES havre.intervention_decisions(
            owner_id, scene_session_id, intervention_decision_id
        ),
    FOREIGN KEY (owner_id, guidance_event_id)
        REFERENCES havre.events(owner_id, event_id),
    FOREIGN KEY (owner_id, scene_session_id, action_record_id)
        REFERENCES havre.scene_records(owner_id, scene_session_id, scene_record_id),
    FOREIGN KEY (owner_id, scene_session_id, outcome_record_id)
        REFERENCES havre.scene_records(owner_id, scene_session_id, scene_record_id),
    FOREIGN KEY (owner_id, scene_session_id, reflection_record_id)
        REFERENCES havre.scene_records(owner_id, scene_session_id, scene_record_id),
    FOREIGN KEY (owner_id, created_event_id)
        REFERENCES havre.events(owner_id, event_id),
    FOREIGN KEY (owner_id, trace_id)
        REFERENCES havre.traces(owner_id, trace_id),
    CHECK (observation_window_ended_at >= observation_window_started_at),
    CHECK (privacy_class <> 'LOCAL_ONLY' OR cloud_eligible = false)
);
CREATE INDEX guidance_outcomes_owner_scene_idx
    ON havre.guidance_outcome_observations(owner_id, scene_session_id, created_at);
CREATE INDEX guidance_outcomes_owner_intervention_idx
    ON havre.guidance_outcome_observations(
        owner_id, scene_session_id, intervention_decision_id
    );
CREATE INDEX guidance_outcomes_owner_action_idx
    ON havre.guidance_outcome_observations(owner_id, scene_session_id, action_record_id);
CREATE INDEX guidance_outcomes_owner_outcome_idx
    ON havre.guidance_outcome_observations(owner_id, scene_session_id, outcome_record_id);
CREATE INDEX guidance_outcomes_owner_reflection_idx
    ON havre.guidance_outcome_observations(
        owner_id, scene_session_id, reflection_record_id
    );
CREATE INDEX guidance_outcomes_owner_guidance_event_idx
    ON havre.guidance_outcome_observations(owner_id, guidance_event_id);
CREATE INDEX guidance_outcomes_owner_created_event_idx
    ON havre.guidance_outcome_observations(owner_id, created_event_id);
CREATE INDEX guidance_outcomes_owner_trace_idx
    ON havre.guidance_outcome_observations(owner_id, trace_id);

CREATE TABLE havre.scene_evaluation_runs (
    evaluation_run_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    suite_version text NOT NULL,
    fixture_hash text NOT NULL CHECK (fixture_hash ~ '^sha256:[0-9a-f]{64}$'),
    code_revision text NOT NULL,
    binding_evaluation boolean NOT NULL CHECK (binding_evaluation = false),
    gate_status text NOT NULL CHECK (gate_status = 'not_evaluated'),
    environment jsonb NOT NULL CHECK (jsonb_typeof(environment) = 'object'),
    metrics jsonb NOT NULL CHECK (jsonb_typeof(metrics) = 'object'),
    case_results jsonb NOT NULL CHECK (jsonb_typeof(case_results) = 'array'),
    limitations jsonb NOT NULL CHECK (jsonb_typeof(limitations) = 'array'),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp()
);

-- Extend the common provenance destination set for Stage 5 derived artifacts.
ALTER TABLE havre.provenance_edges
    DROP CONSTRAINT provenance_edges_derived_kind_check,
    DROP CONSTRAINT provenance_edges_derived_revision_check;
ALTER TABLE havre.provenance_edges
    ADD COLUMN derived_intervention_decision_id uuid GENERATED ALWAYS AS (
        CASE WHEN derived_kind = 'intervention_decision' THEN derived_id ELSE NULL END
    ) STORED,
    ADD COLUMN derived_outcome_observation_id uuid GENERATED ALWAYS AS (
        CASE WHEN derived_kind = 'guidance_outcome_observation' THEN derived_id ELSE NULL END
    ) STORED;
ALTER TABLE havre.provenance_edges
    ADD CONSTRAINT provenance_edges_derived_kind_check CHECK (
        derived_kind IN (
            'memory_revision', 'belief_revision', 'consolidation_proposal',
            'current_state_snapshot', 'goal_progress_record',
            'intervention_decision', 'guidance_outcome_observation'
        )
    ),
    ADD CONSTRAINT provenance_edges_derived_revision_check CHECK (
        (derived_kind IN ('memory_revision', 'belief_revision') AND derived_revision > 0)
        OR (
            derived_kind IN (
                'consolidation_proposal', 'current_state_snapshot',
                'goal_progress_record', 'intervention_decision',
                'guidance_outcome_observation'
            ) AND derived_revision IS NULL
        )
    ),
    ADD CONSTRAINT provenance_edges_owner_derived_intervention_fk
        FOREIGN KEY (owner_id, derived_intervention_decision_id)
        REFERENCES havre.intervention_decisions(owner_id, intervention_decision_id),
    ADD CONSTRAINT provenance_edges_owner_derived_outcome_observation_fk
        FOREIGN KEY (owner_id, derived_outcome_observation_id)
        REFERENCES havre.guidance_outcome_observations(owner_id, outcome_observation_id);
CREATE INDEX provenance_edges_owner_derived_intervention_idx
    ON havre.provenance_edges(owner_id, derived_intervention_decision_id)
    WHERE derived_intervention_decision_id IS NOT NULL;
CREATE INDEX provenance_edges_owner_derived_outcome_observation_idx
    ON havre.provenance_edges(owner_id, derived_outcome_observation_id)
    WHERE derived_outcome_observation_id IS NOT NULL;

CREATE FUNCTION havre.guard_scene_session_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.revision <> 1 OR NEW.phase <> 'before' OR NEW.status <> 'planned'
       OR NEW.created_event_id <> NEW.last_event_id
       OR NOT EXISTS (
            SELECT 1 FROM havre.events AS event
            WHERE event.owner_id = NEW.owner_id
              AND event.event_id = NEW.created_event_id
              AND event.event_type = 'SCENE_SESSION_PLANNED'
              AND event.scene_session_id = NEW.scene_session_id
              AND event.session_id = NEW.opened_session_id
              AND event.trace_id = NEW.trace_id
              AND event.payload->>'scene_session_id' = NEW.scene_session_id::text
              AND event.payload->>'scene_revision' = '1'
              AND event.payload->>'action' = 'planned'
              AND event.payload->'situation' = NEW.situation
              AND event.payload->'planned_goal' = NEW.planned_goal
              AND event.payload->'anticipated_triggers' = NEW.anticipated_triggers
       ) THEN
        RAISE EXCEPTION 'Scene Session insert requires one exact planned lifecycle event'
            USING ERRCODE = '55000';
    END IF;
    NEW.created_at := statement_timestamp();
    NEW.updated_at := NEW.created_at;
    RETURN NEW;
END;
$$;

CREATE FUNCTION havre.guard_scene_session_update() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    expected_lifecycle_event_type text;
BEGIN
    IF current_setting('havre.privileged_erasure', true) = 'on'
       AND pg_has_role(current_user, 'havre_privileged_erasure', 'MEMBER') THEN
        IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Scene Sessions are removed only through privileged erasure'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.owner_id <> OLD.owner_id OR NEW.scene_session_id <> OLD.scene_session_id
       OR NEW.opened_session_id <> OLD.opened_session_id
       OR NEW.scene_type <> OLD.scene_type OR NEW.situation <> OLD.situation
       OR NEW.planned_goal <> OLD.planned_goal
       OR NEW.anticipated_triggers <> OLD.anticipated_triggers
       OR NEW.planned_start_at IS DISTINCT FROM OLD.planned_start_at
       OR NEW.created_event_id <> OLD.created_event_id
       OR NEW.created_at <> OLD.created_at
       OR NEW.revision <> OLD.revision + 1 OR NEW.last_event_id = OLD.last_event_id
       OR NEW.privacy_class <> OLD.privacy_class
       OR NEW.memory_eligible <> OLD.memory_eligible
       OR NEW.training_eligible <> OLD.training_eligible
       OR NEW.cloud_eligible <> OLD.cloud_eligible
       OR NEW.policy_version <> OLD.policy_version
       OR NEW.policy_revision_id <> OLD.policy_revision_id
       OR NEW.policy_decision_source <> OLD.policy_decision_source
       OR NEW.policy_authorization_ref IS DISTINCT FROM OLD.policy_authorization_ref THEN
        RAISE EXCEPTION 'Scene projection update changed immutable or nonsequential material'
            USING ERRCODE = '55000';
    END IF;
    IF OLD.phase = 'before' AND OLD.status = 'planned'
       AND NEW.phase = 'during' AND NEW.status = 'active' THEN
        expected_lifecycle_event_type := 'SCENE_SESSION_STARTED';
    ELSIF OLD.phase = 'during' AND OLD.status = 'active'
       AND NEW.phase = 'during' AND NEW.status = 'paused' THEN
        expected_lifecycle_event_type := 'SCENE_SESSION_PAUSED';
    ELSIF OLD.phase = 'during' AND OLD.status = 'paused'
       AND NEW.phase = 'during' AND NEW.status = 'active' THEN
        expected_lifecycle_event_type := 'SCENE_SESSION_STARTED';
    ELSIF OLD.phase = 'during' AND OLD.status = 'active'
       AND NEW.phase = 'after' AND NEW.status = 'active' THEN
        expected_lifecycle_event_type := 'SCENE_PHASE_CHANGED';
    ELSIF NEW.phase = 'closed' AND NEW.status IN ('completed', 'abandoned', 'cancelled')
       AND ((OLD.phase = 'after' AND OLD.status = 'active')
            OR (OLD.phase = 'before' AND OLD.status = 'planned')) THEN
        expected_lifecycle_event_type := 'SCENE_SESSION_ENDED';
    ELSE
        RAISE EXCEPTION 'invalid Scene Session phase/status transition'
            USING ERRCODE = '55000';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM havre.events AS event
        WHERE event.owner_id = NEW.owner_id
          AND event.event_id = NEW.last_event_id
          AND event.event_type = expected_lifecycle_event_type
          AND event.scene_session_id = NEW.scene_session_id
          AND event.payload->>'scene_session_id' = NEW.scene_session_id::text
          AND event.payload->>'scene_revision' = NEW.revision::text
          AND event.payload->>'phase' = NEW.phase
          AND event.payload->>'status' = NEW.status
    ) THEN
        RAISE EXCEPTION 'Scene projection update lacks an exact lifecycle event'
            USING ERRCODE = '55000';
    END IF;
    NEW.updated_at := statement_timestamp();
    RETURN NEW;
END;
$$;

CREATE FUNCTION havre.guard_scene_record_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    current_scene record;
    predecessor_type text;
    predecessor_phase text;
    expected_event_type text;
    expected_sequence integer;
BEGIN
    SELECT * INTO current_scene FROM havre.scene_sessions
    WHERE owner_id = NEW.owner_id AND scene_session_id = NEW.scene_session_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Scene record lacks an owner-qualified Scene Session'
            USING ERRCODE = '55000';
    END IF;
    SELECT COALESCE(max(sequence_number), 0) + 1 INTO expected_sequence
    FROM havre.scene_records
    WHERE owner_id = NEW.owner_id AND scene_session_id = NEW.scene_session_id;
    IF NEW.sequence_number <> expected_sequence THEN
        RAISE EXCEPTION 'Scene record sequence must be the next exact value'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.causal_predecessor_id IS NOT NULL THEN
        SELECT record_type, phase INTO predecessor_type, predecessor_phase
        FROM havre.scene_records
        WHERE owner_id = NEW.owner_id
          AND scene_session_id = NEW.scene_session_id
          AND scene_record_id = NEW.causal_predecessor_id;
    END IF;
    expected_event_type := CASE NEW.record_type
        WHEN 'signal' THEN 'USER_SIGNAL'
        WHEN 'intervention' THEN 'INTERVENTION_DECIDED'
        WHEN 'action' THEN 'USER_ACTION_REPORTED'
        WHEN 'outcome' THEN 'OUTCOME_REPORTED'
        WHEN 'reflection' THEN 'REFLECTION_CREATED'
    END;
    IF NOT EXISTS (
        SELECT 1 FROM havre.events AS event
        WHERE event.owner_id = NEW.owner_id AND event.event_id = NEW.event_id
          AND event.event_type = expected_event_type
          AND event.scene_session_id = NEW.scene_session_id
          AND event.trace_id = NEW.trace_id
          AND event.payload->>'scene_session_id' = NEW.scene_session_id::text
          AND event.payload->>'scene_record_id' = NEW.scene_record_id::text
    ) THEN
        RAISE EXCEPTION 'Scene record event does not match its type/owner/Scene/trace'
            USING ERRCODE = '55000';
    END IF;
    IF (NEW.record_type = 'signal' AND NEW.phase <> 'during')
       OR (NEW.record_type = 'intervention' AND NOT (
            (NEW.phase = 'before' AND NEW.causal_predecessor_id IS NULL)
            OR (NEW.phase = 'during' AND predecessor_type = 'signal')
            OR (NEW.phase = 'after' AND NEW.causal_predecessor_id IS NULL)
          ))
       OR (NEW.record_type = 'action' AND (
            predecessor_type <> 'intervention' OR predecessor_phase <> 'during'
          ))
       OR (NEW.record_type = 'outcome' AND (
            NEW.phase <> 'after' OR predecessor_type <> 'action'
          ))
       OR (NEW.record_type = 'reflection' AND (
            NEW.phase <> 'after' OR predecessor_type <> 'outcome'
          )) THEN
        RAISE EXCEPTION 'Scene record violates phase or causal predecessor rules'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.record_type = 'intervention' AND NOT EXISTS (
        SELECT 1 FROM havre.events AS guidance
        WHERE guidance.owner_id = NEW.owner_id
          AND guidance.event_id = NEW.assistant_event_id
          AND guidance.event_type = 'ASSISTANT_MESSAGE'
          AND guidance.scene_session_id = NEW.scene_session_id
          AND guidance.payload->>'interaction_mode' = 'scene_guidance'
    ) THEN
        RAISE EXCEPTION 'intervention record requires exact visible Scene guidance'
            USING ERRCODE = '55000';
    END IF;
    NEW.recorded_at := statement_timestamp();
    RETURN NEW;
END;
$$;

CREATE FUNCTION havre.guard_intervention_decision_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT havre.stage4_evidence_snapshot_is_exact(NEW.evidence_snapshot)
       OR (
            (NEW.phase = 'during' AND NOT EXISTS (
                SELECT 1 FROM havre.scene_records AS input_record
                WHERE input_record.owner_id = NEW.owner_id
                  AND input_record.scene_session_id = NEW.scene_session_id
                  AND input_record.scene_record_id = NEW.input_record_id
                  AND input_record.record_type = 'signal'
                  AND input_record.event_id = NEW.input_event_id
            ))
            OR (NEW.phase IN ('before', 'after') AND NEW.input_record_id IS NOT NULL)
       )
       OR NOT EXISTS (
            SELECT 1 FROM havre.events AS decision_event
            WHERE decision_event.owner_id = NEW.owner_id
              AND decision_event.event_id = NEW.decision_event_id
              AND decision_event.event_type = 'INTERVENTION_DECIDED'
              AND decision_event.scene_session_id = NEW.scene_session_id
              AND decision_event.trace_id = NEW.trace_id
              AND decision_event.payload->>'intervention_decision_id' =
                    NEW.intervention_decision_id::text
              AND decision_event.payload->>'guidance_event_id' = NEW.guidance_event_id::text
              AND decision_event.payload->>'branch' = NEW.branch
              AND (decision_event.payload->>'outreach_authorized')::boolean = false
              AND (decision_event.payload->>'simulation_only')::boolean = true
       ) OR NOT EXISTS (
            SELECT 1 FROM havre.events AS guidance_event
            WHERE guidance_event.owner_id = NEW.owner_id
              AND guidance_event.event_id = NEW.guidance_event_id
              AND guidance_event.event_type = 'ASSISTANT_MESSAGE'
              AND guidance_event.scene_session_id = NEW.scene_session_id
              AND guidance_event.payload->>'interaction_mode' = 'scene_guidance'
              AND guidance_event.payload->>'intervention_decision_id' =
                    NEW.intervention_decision_id::text
       ) OR NOT EXISTS (
            SELECT 1 FROM havre.events AS input_event
            WHERE input_event.owner_id = NEW.owner_id
              AND input_event.event_id = NEW.input_event_id
              AND input_event.scene_session_id = NEW.scene_session_id
       ) THEN
        RAISE EXCEPTION 'Intervention Decision lacks exact input/decision/guidance evidence'
            USING ERRCODE = '55000';
    END IF;
    NEW.created_at := statement_timestamp();
    RETURN NEW;
END;
$$;

CREATE FUNCTION havre.guard_guidance_outcome_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT havre.stage4_evidence_snapshot_is_exact(NEW.evidence_snapshot)
       OR NOT EXISTS (
            SELECT 1
            FROM havre.scene_records AS action_record
            JOIN havre.scene_records AS intervention_record
              ON intervention_record.owner_id = action_record.owner_id
             AND intervention_record.scene_session_id = action_record.scene_session_id
             AND intervention_record.scene_record_id = action_record.causal_predecessor_id
             AND intervention_record.record_type = 'intervention'
            JOIN havre.scene_records AS outcome_record
              ON outcome_record.owner_id = action_record.owner_id
             AND outcome_record.scene_session_id = action_record.scene_session_id
             AND outcome_record.scene_record_id = NEW.outcome_record_id
             AND outcome_record.record_type = 'outcome'
             AND outcome_record.causal_predecessor_id = action_record.scene_record_id
            JOIN havre.scene_records AS reflection_record
              ON reflection_record.owner_id = action_record.owner_id
             AND reflection_record.scene_session_id = action_record.scene_session_id
             AND reflection_record.scene_record_id = NEW.reflection_record_id
             AND reflection_record.record_type = 'reflection'
             AND reflection_record.causal_predecessor_id = outcome_record.scene_record_id
            WHERE action_record.owner_id = NEW.owner_id
              AND action_record.scene_session_id = NEW.scene_session_id
              AND action_record.scene_record_id = NEW.action_record_id
              AND action_record.record_type = 'action'
              AND intervention_record.artifact_id = NEW.intervention_decision_id
              AND intervention_record.assistant_event_id = NEW.guidance_event_id
       )
       OR (SELECT record_type FROM havre.scene_records
           WHERE owner_id = NEW.owner_id AND scene_session_id = NEW.scene_session_id
             AND scene_record_id = NEW.action_record_id) <> 'action'
       OR (SELECT record_type FROM havre.scene_records
           WHERE owner_id = NEW.owner_id AND scene_session_id = NEW.scene_session_id
             AND scene_record_id = NEW.outcome_record_id) <> 'outcome'
       OR (SELECT record_type FROM havre.scene_records
           WHERE owner_id = NEW.owner_id AND scene_session_id = NEW.scene_session_id
             AND scene_record_id = NEW.reflection_record_id) <> 'reflection'
       OR NOT EXISTS (
            SELECT 1 FROM havre.events AS event
            WHERE event.owner_id = NEW.owner_id
              AND event.event_id = NEW.created_event_id
              AND event.event_type = 'REFLECTION_CREATED'
              AND event.scene_session_id = NEW.scene_session_id
              AND event.payload->>'outcome_observation_id' =
                    NEW.outcome_observation_id::text
       ) THEN
        RAISE EXCEPTION 'guidance outcome observation lacks exact Scene chain evidence'
            USING ERRCODE = '55000';
    END IF;
    NEW.created_at := statement_timestamp();
    RETURN NEW;
END;
$$;

CREATE FUNCTION havre.require_stage5_snapshot_provenance() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    derived_kind text;
    derived_id uuid;
BEGIN
    IF TG_TABLE_NAME = 'intervention_decisions' THEN
        derived_kind := 'intervention_decision';
        derived_id := NEW.intervention_decision_id;
    ELSIF TG_TABLE_NAME = 'guidance_outcome_observations' THEN
        derived_kind := 'guidance_outcome_observation';
        derived_id := NEW.outcome_observation_id;
    ELSE
        RAISE EXCEPTION 'unsupported Stage 5 provenance table';
    END IF;
    IF NOT havre.stage4_snapshot_provenance_matches(
        NEW.owner_id, derived_kind, derived_id, NEW.evidence_snapshot
    ) THEN
        RAISE EXCEPTION '% requires exact owner-qualified snapshot provenance', derived_kind
            USING ERRCODE = '55000';
    END IF;
    RETURN NULL;
END;
$$;

CREATE TRIGGER scene_sessions_are_insert_guarded
BEFORE INSERT ON havre.scene_sessions
FOR EACH ROW EXECUTE FUNCTION havre.guard_scene_session_insert();
CREATE TRIGGER scene_sessions_are_update_guarded
BEFORE UPDATE OR DELETE ON havre.scene_sessions
FOR EACH ROW EXECUTE FUNCTION havre.guard_scene_session_update();
CREATE TRIGGER scene_records_are_insert_guarded
BEFORE INSERT ON havre.scene_records
FOR EACH ROW EXECUTE FUNCTION havre.guard_scene_record_insert();
CREATE TRIGGER scene_records_are_immutable
BEFORE UPDATE OR DELETE ON havre.scene_records
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();
CREATE TRIGGER intervention_decisions_are_insert_guarded
BEFORE INSERT ON havre.intervention_decisions
FOR EACH ROW EXECUTE FUNCTION havre.guard_intervention_decision_insert();
CREATE TRIGGER intervention_decisions_are_immutable
BEFORE UPDATE OR DELETE ON havre.intervention_decisions
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();
CREATE CONSTRAINT TRIGGER intervention_decisions_require_provenance
AFTER INSERT ON havre.intervention_decisions
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION havre.require_stage5_snapshot_provenance();
CREATE TRIGGER guidance_outcomes_are_insert_guarded
BEFORE INSERT ON havre.guidance_outcome_observations
FOR EACH ROW EXECUTE FUNCTION havre.guard_guidance_outcome_insert();
CREATE TRIGGER guidance_outcomes_are_immutable
BEFORE UPDATE OR DELETE ON havre.guidance_outcome_observations
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();
CREATE CONSTRAINT TRIGGER guidance_outcomes_require_provenance
AFTER INSERT ON havre.guidance_outcome_observations
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION havre.require_stage5_snapshot_provenance();
CREATE TRIGGER scene_evaluation_runs_are_immutable
BEFORE UPDATE OR DELETE ON havre.scene_evaluation_runs
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();

CREATE VIEW havre.stage5_required_provenance_violations AS
SELECT
    decision.intervention_decision_id AS provenance_edge_id,
    decision.owner_id,
    'required_provenance'::text AS source_kind,
    decision.intervention_decision_id AS source_id,
    NULL::integer AS source_revision,
    'missing_or_mismatched_intervention_provenance'::text AS violation_code
FROM havre.intervention_decisions AS decision
WHERE NOT havre.stage4_snapshot_provenance_matches(
    decision.owner_id, 'intervention_decision',
    decision.intervention_decision_id, decision.evidence_snapshot
)
UNION ALL
SELECT
    observation.outcome_observation_id,
    observation.owner_id,
    'required_provenance',
    observation.outcome_observation_id,
    NULL::integer,
    'missing_or_mismatched_guidance_outcome_provenance'
FROM havre.guidance_outcome_observations AS observation
WHERE NOT havre.stage4_snapshot_provenance_matches(
    observation.owner_id, 'guidance_outcome_observation',
    observation.outcome_observation_id, observation.evidence_snapshot
);
