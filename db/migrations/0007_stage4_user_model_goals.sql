-- Stage 4 governed User Model, consolidation, Current State, and Goals.
-- This migration is additive: 0001-0006 may already be applied and must not
-- be rewritten. Proactive interaction remains inactive.

ALTER TABLE havre.events DROP CONSTRAINT events_event_type_check;
ALTER TABLE havre.events ADD CONSTRAINT events_event_type_check CHECK (event_type IN (
    'USER_MESSAGE', 'ASSISTANT_MESSAGE', 'INTERACTION_FAILED',
    'MEMORY_CREATED', 'MEMORY_REVISED', 'MEMORY_RETRACTED',
    'CURRENT_STATE_ESTIMATED',
    'USER_BELIEF_CREATED', 'USER_BELIEF_REVISED', 'USER_BELIEF_TRANSITIONED',
    'CONSOLIDATION_PROPOSED', 'CONSOLIDATION_REVIEWED',
    'GOAL_CREATED', 'GOAL_UPDATED', 'GOAL_COMPLETED', 'PROGRESS_RECORDED'
));

ALTER TABLE havre.memory_revisions
    DROP CONSTRAINT memory_revisions_memory_class_check;
ALTER TABLE havre.memory_revisions
    ADD CONSTRAINT memory_revisions_memory_class_check CHECK (
        memory_class IN ('episodic', 'semantic', 'pattern', 'progress')
    );

CREATE TABLE havre.user_belief_revisions (
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    belief_id uuid NOT NULL,
    revision integer NOT NULL CHECK (revision > 0),
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    belief_key text NOT NULL CHECK (length(belief_key) BETWEEN 1 AND 240),
    statement text NOT NULL CHECK (length(statement) BETWEEN 1 AND 10000),
    belief_type text NOT NULL CHECK (belief_type IN (
        'fact', 'preference', 'value', 'strength', 'vulnerability', 'pattern', 'uncertainty'
    )),
    confidence numeric(6,5) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    confidence_method text NOT NULL CHECK (confidence_method = 'owner-reviewed-v1'),
    initial_status text NOT NULL CHECK (initial_status IN ('candidate', 'active')),
    evidence_occurred_from timestamptz NULL,
    evidence_occurred_to timestamptz NULL,
    learned_at timestamptz NOT NULL,
    valid_from timestamptz NULL,
    valid_to timestamptz NULL,
    supersedes_revision integer NULL CHECK (supersedes_revision > 0),
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
    policy_decision_source text NOT NULL CHECK (policy_decision_source = 'derived_conservative'),
    policy_authorization_ref text NULL,
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (owner_id, belief_id, revision),
    UNIQUE (owner_id, belief_id, revision, initial_status),
    FOREIGN KEY (owner_id, created_event_id)
        REFERENCES havre.events(owner_id, event_id),
    FOREIGN KEY (owner_id, trace_id)
        REFERENCES havre.traces(owner_id, trace_id),
    FOREIGN KEY (owner_id, belief_id, supersedes_revision)
        REFERENCES havre.user_belief_revisions(owner_id, belief_id, revision),
    CHECK (
        (revision = 1 AND supersedes_revision IS NULL)
        OR (revision > 1 AND supersedes_revision = revision - 1)
    ),
    CHECK (
        evidence_occurred_to IS NULL OR evidence_occurred_from IS NULL
        OR evidence_occurred_to >= evidence_occurred_from
    ),
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
    CHECK (privacy_class <> 'LOCAL_ONLY' OR cloud_eligible = false)
);
CREATE INDEX user_belief_revisions_owner_key_idx
    ON havre.user_belief_revisions(owner_id, belief_key, created_at);
CREATE INDEX user_belief_revisions_owner_created_event_idx
    ON havre.user_belief_revisions(owner_id, created_event_id);
CREATE INDEX user_belief_revisions_owner_trace_idx
    ON havre.user_belief_revisions(owner_id, trace_id);

CREATE TABLE havre.belief_revision_transitions (
    belief_transition_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    belief_id uuid NOT NULL,
    belief_revision integer NOT NULL CHECK (belief_revision > 0),
    transition_type text NOT NULL CHECK (transition_type IN (
        'activated', 'counter_evidence_recorded', 'contradicted',
        'superseded', 'retracted', 'invalidated'
    )),
    occurred_at timestamptz NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    reason text NOT NULL CHECK (length(reason) BETWEEN 1 AND 2000),
    causing_event_id uuid NOT NULL,
    replacement_belief_id uuid NULL,
    replacement_revision integer NULL CHECK (replacement_revision > 0),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    UNIQUE (owner_id, belief_transition_id),
    FOREIGN KEY (owner_id, belief_id, belief_revision)
        REFERENCES havre.user_belief_revisions(owner_id, belief_id, revision),
    FOREIGN KEY (owner_id, causing_event_id)
        REFERENCES havre.events(owner_id, event_id),
    FOREIGN KEY (owner_id, replacement_belief_id, replacement_revision)
        REFERENCES havre.user_belief_revisions(owner_id, belief_id, revision),
    CHECK ((replacement_belief_id IS NULL) = (replacement_revision IS NULL)),
    CHECK (transition_type <> 'superseded' OR replacement_belief_id IS NOT NULL)
);
CREATE INDEX belief_revision_transitions_replay_idx
    ON havre.belief_revision_transitions(
        owner_id, belief_id, belief_revision, recorded_at, belief_transition_id
    );
CREATE INDEX belief_revision_transitions_causing_event_idx
    ON havre.belief_revision_transitions(owner_id, causing_event_id);

CREATE TABLE havre.belief_heads (
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    belief_id uuid NOT NULL,
    belief_key text NOT NULL CHECK (length(belief_key) BETWEEN 1 AND 240),
    current_revision integer NOT NULL CHECK (current_revision > 0),
    status text NOT NULL CHECK (status IN (
        'candidate', 'active', 'contradicted', 'superseded', 'retracted', 'invalidated'
    )),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (owner_id, belief_id),
    UNIQUE (owner_id, belief_key),
    FOREIGN KEY (owner_id, belief_id, current_revision)
        REFERENCES havre.user_belief_revisions(owner_id, belief_id, revision)
);
CREATE INDEX belief_heads_owner_status_idx
    ON havre.belief_heads(owner_id, status, updated_at DESC, belief_id);

CREATE TABLE havre.consolidation_proposals (
    proposal_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    memory_class text NOT NULL CHECK (memory_class IN ('semantic', 'pattern', 'progress')),
    content jsonb NOT NULL CHECK (jsonb_typeof(content) = 'object'),
    content_text text NOT NULL CHECK (length(content_text) BETWEEN 1 AND 100000),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    confidence numeric(6,5) NOT NULL CHECK (confidence = 0.5),
    confidence_method text NOT NULL CHECK (confidence_method = 'unreviewed-proposal-v1'),
    importance numeric(6,5) NOT NULL CHECK (importance BETWEEN 0 AND 1),
    importance_policy_version text NOT NULL CHECK (
        importance_policy_version = 'owner-review-required-v1'
    ),
    detector_version text NOT NULL,
    evidence_snapshot jsonb NOT NULL CHECK (jsonb_typeof(evidence_snapshot) = 'array'),
    status text NOT NULL CHECK (status IN (
        'pending', 'accepted', 'accepted_with_correction', 'rejected'
    )),
    reviewed_by text NULL,
    reviewed_at timestamptz NULL,
    review_reason text NULL,
    accepted_memory_id uuid NULL,
    accepted_memory_revision integer NULL,
    created_event_id uuid NOT NULL,
    review_event_id uuid NULL,
    trace_id char(32) NOT NULL,
    privacy_class text NOT NULL CHECK (privacy_class IN (
        'PUBLIC', 'NORMAL', 'PRIVATE', 'HIGHLY_PRIVATE', 'LOCAL_ONLY'
    )),
    memory_eligible boolean NOT NULL CHECK (memory_eligible = true),
    training_eligible boolean NOT NULL DEFAULT false CHECK (training_eligible = false),
    cloud_eligible boolean NOT NULL,
    policy_version text NOT NULL CHECK (policy_version = 'data-policy-v1'),
    policy_revision_id uuid NOT NULL,
    policy_decision_source text NOT NULL CHECK (policy_decision_source = 'derived_conservative'),
    policy_authorization_ref text NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (owner_id, proposal_id),
    FOREIGN KEY (owner_id, created_event_id)
        REFERENCES havre.events(owner_id, event_id),
    FOREIGN KEY (owner_id, review_event_id)
        REFERENCES havre.events(owner_id, event_id),
    FOREIGN KEY (owner_id, accepted_memory_id, accepted_memory_revision)
        REFERENCES havre.memory_revisions(owner_id, memory_id, revision),
    FOREIGN KEY (owner_id, trace_id)
        REFERENCES havre.traces(owner_id, trace_id),
    CHECK ((accepted_memory_id IS NULL) = (accepted_memory_revision IS NULL)),
    CHECK (
        status IN ('accepted', 'accepted_with_correction')
        OR accepted_memory_id IS NULL
    ),
    CHECK (privacy_class <> 'LOCAL_ONLY' OR cloud_eligible = false)
);
CREATE INDEX consolidation_proposals_owner_status_idx
    ON havre.consolidation_proposals(owner_id, status, created_at, proposal_id);

CREATE TABLE havre.current_state_snapshots (
    state_snapshot_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    summary text NOT NULL CHECK (length(summary) BETWEEN 1 AND 2000),
    state jsonb NOT NULL CHECK (jsonb_typeof(state) = 'object'),
    uncertainty numeric(6,5) NOT NULL CHECK (uncertainty BETWEEN 0 AND 1),
    estimated_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL CHECK (expires_at > estimated_at),
    estimator_version text NOT NULL CHECK (estimator_version = 'owner-reported-state-v1'),
    evidence_snapshot jsonb NOT NULL CHECK (jsonb_typeof(evidence_snapshot) = 'array'),
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
    policy_decision_source text NOT NULL CHECK (policy_decision_source = 'derived_conservative'),
    policy_authorization_ref text NULL,
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (owner_id, state_snapshot_id),
    FOREIGN KEY (owner_id, created_event_id)
        REFERENCES havre.events(owner_id, event_id),
    FOREIGN KEY (owner_id, trace_id)
        REFERENCES havre.traces(owner_id, trace_id),
    CHECK (privacy_class <> 'LOCAL_ONLY' OR cloud_eligible = false)
);
CREATE INDEX current_state_snapshots_owner_active_idx
    ON havre.current_state_snapshots(owner_id, expires_at DESC, estimated_at DESC);

CREATE TABLE havre.goals (
    goal_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    track text NOT NULL CHECK (track IN ('reality', 'inner_life')),
    title text NOT NULL CHECK (length(title) BETWEEN 1 AND 500),
    why text NOT NULL CHECK (length(why) BETWEEN 1 AND 2000),
    priority text NOT NULL CHECK (priority IN ('low', 'normal', 'high')),
    status text NOT NULL CHECK (status IN ('active', 'paused', 'completed', 'abandoned')),
    next_action text NULL CHECK (next_action IS NULL OR length(next_action) BETWEEN 1 AND 2000),
    review_at timestamptz NULL,
    revision integer NOT NULL CHECK (revision > 0),
    last_event_id uuid NOT NULL,
    privacy_class text NOT NULL CHECK (privacy_class IN (
        'PUBLIC', 'NORMAL', 'PRIVATE', 'HIGHLY_PRIVATE', 'LOCAL_ONLY'
    )),
    memory_eligible boolean NOT NULL CHECK (memory_eligible = true),
    training_eligible boolean NOT NULL DEFAULT false CHECK (training_eligible = false),
    cloud_eligible boolean NOT NULL,
    policy_version text NOT NULL CHECK (policy_version = 'data-policy-v1'),
    policy_revision_id uuid NOT NULL,
    policy_decision_source text NOT NULL CHECK (
        policy_decision_source IN ('owner_default', 'owner_explicit', 'derived_conservative')
    ),
    policy_authorization_ref text NULL,
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (owner_id, goal_id),
    FOREIGN KEY (owner_id, last_event_id)
        REFERENCES havre.events(owner_id, event_id),
    CHECK (privacy_class <> 'LOCAL_ONLY' OR cloud_eligible = false)
);
CREATE INDEX goals_owner_status_track_idx
    ON havre.goals(owner_id, status, track, updated_at DESC, goal_id);

CREATE TABLE havre.goal_progress_records (
    progress_record_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    goal_id uuid NOT NULL,
    goal_revision integer NOT NULL CHECK (goal_revision > 0),
    direction text NOT NULL CHECK (direction IN ('toward', 'steady', 'away', 'unknown')),
    summary text NOT NULL CHECK (length(summary) BETWEEN 1 AND 2000),
    observed_at timestamptz NOT NULL,
    evidence_snapshot jsonb NOT NULL CHECK (jsonb_typeof(evidence_snapshot) = 'array'),
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
    policy_decision_source text NOT NULL CHECK (policy_decision_source = 'derived_conservative'),
    policy_authorization_ref text NULL,
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (owner_id, progress_record_id),
    FOREIGN KEY (owner_id, goal_id)
        REFERENCES havre.goals(owner_id, goal_id),
    FOREIGN KEY (owner_id, created_event_id)
        REFERENCES havre.events(owner_id, event_id),
    FOREIGN KEY (owner_id, trace_id)
        REFERENCES havre.traces(owner_id, trace_id),
    CHECK (privacy_class <> 'LOCAL_ONLY' OR cloud_eligible = false)
);
CREATE INDEX goal_progress_records_owner_goal_idx
    ON havre.goal_progress_records(owner_id, goal_id, observed_at, progress_record_id);

CREATE TABLE havre.user_model_evaluation_runs (
    evaluation_run_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    suite_version text NOT NULL,
    fixture_hash text NOT NULL CHECK (fixture_hash ~ '^sha256:[0-9a-f]{64}$'),
    code_revision text NOT NULL,
    environment jsonb NOT NULL CHECK (jsonb_typeof(environment) = 'object'),
    metrics jsonb NOT NULL CHECK (jsonb_typeof(metrics) = 'object'),
    case_results jsonb NOT NULL CHECK (jsonb_typeof(case_results) = 'array'),
    limitations jsonb NOT NULL CHECK (jsonb_typeof(limitations) = 'array'),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

-- Extend the generic provenance graph with owner-qualified Stage 4 sources and
-- destinations while retaining every Stage 2 edge unchanged.
DROP VIEW havre.provenance_integrity_violations;

ALTER TABLE havre.provenance_edges
    DROP CONSTRAINT provenance_edges_source_kind_check,
    DROP CONSTRAINT provenance_edges_derived_kind_check,
    DROP CONSTRAINT provenance_edges_relation_check,
    DROP CONSTRAINT provenance_edges_derived_revision_check,
    DROP CONSTRAINT IF EXISTS provenance_edges_check,
    DROP CONSTRAINT IF EXISTS provenance_edges_owner_id_derived_id_derived_revision_fkey;

ALTER TABLE havre.provenance_edges
    ALTER COLUMN derived_revision DROP NOT NULL;

ALTER TABLE havre.provenance_edges
    ADD COLUMN source_belief_id uuid GENERATED ALWAYS AS (
        CASE WHEN source_kind = 'belief_revision' THEN source_id ELSE NULL END
    ) STORED,
    ADD COLUMN source_belief_revision integer GENERATED ALWAYS AS (
        CASE WHEN source_kind = 'belief_revision' THEN source_revision ELSE NULL END
    ) STORED,
    ADD COLUMN derived_memory_id uuid GENERATED ALWAYS AS (
        CASE WHEN derived_kind = 'memory_revision' THEN derived_id ELSE NULL END
    ) STORED,
    ADD COLUMN derived_memory_revision integer GENERATED ALWAYS AS (
        CASE WHEN derived_kind = 'memory_revision' THEN derived_revision ELSE NULL END
    ) STORED,
    ADD COLUMN derived_belief_id uuid GENERATED ALWAYS AS (
        CASE WHEN derived_kind = 'belief_revision' THEN derived_id ELSE NULL END
    ) STORED,
    ADD COLUMN derived_belief_revision integer GENERATED ALWAYS AS (
        CASE WHEN derived_kind = 'belief_revision' THEN derived_revision ELSE NULL END
    ) STORED,
    ADD COLUMN derived_proposal_id uuid GENERATED ALWAYS AS (
        CASE WHEN derived_kind = 'consolidation_proposal' THEN derived_id ELSE NULL END
    ) STORED,
    ADD COLUMN derived_state_snapshot_id uuid GENERATED ALWAYS AS (
        CASE WHEN derived_kind = 'current_state_snapshot' THEN derived_id ELSE NULL END
    ) STORED,
    ADD COLUMN derived_goal_progress_id uuid GENERATED ALWAYS AS (
        CASE WHEN derived_kind = 'goal_progress_record' THEN derived_id ELSE NULL END
    ) STORED;

ALTER TABLE havre.provenance_edges
    ADD CONSTRAINT provenance_edges_source_kind_check CHECK (
        source_kind IN ('event', 'memory_revision', 'belief_revision')
    ),
    ADD CONSTRAINT provenance_edges_derived_kind_check CHECK (
        derived_kind IN (
            'memory_revision', 'belief_revision', 'consolidation_proposal',
            'current_state_snapshot', 'goal_progress_record'
        )
    ),
    ADD CONSTRAINT provenance_edges_relation_check CHECK (
        relation IN (
            'supports', 'contradicts', 'derived_from', 'supersedes',
            'corrects', 'retracts', 'progress_for'
        )
    ),
    ADD CONSTRAINT provenance_edges_source_revision_check CHECK (
        (source_kind = 'event' AND source_revision IS NULL)
        OR (source_kind IN ('memory_revision', 'belief_revision') AND source_revision > 0)
    ),
    ADD CONSTRAINT provenance_edges_derived_revision_check CHECK (
        (derived_kind IN ('memory_revision', 'belief_revision') AND derived_revision > 0)
        OR (
            derived_kind IN (
                'consolidation_proposal', 'current_state_snapshot', 'goal_progress_record'
            )
            AND derived_revision IS NULL
        )
    ),
    ADD CONSTRAINT provenance_edges_owner_source_belief_fk
        FOREIGN KEY (owner_id, source_belief_id, source_belief_revision)
        REFERENCES havre.user_belief_revisions(owner_id, belief_id, revision),
    ADD CONSTRAINT provenance_edges_owner_derived_memory_fk
        FOREIGN KEY (owner_id, derived_memory_id, derived_memory_revision)
        REFERENCES havre.memory_revisions(owner_id, memory_id, revision),
    ADD CONSTRAINT provenance_edges_owner_derived_belief_fk
        FOREIGN KEY (owner_id, derived_belief_id, derived_belief_revision)
        REFERENCES havre.user_belief_revisions(owner_id, belief_id, revision),
    ADD CONSTRAINT provenance_edges_owner_derived_proposal_fk
        FOREIGN KEY (owner_id, derived_proposal_id)
        REFERENCES havre.consolidation_proposals(owner_id, proposal_id),
    ADD CONSTRAINT provenance_edges_owner_derived_state_fk
        FOREIGN KEY (owner_id, derived_state_snapshot_id)
        REFERENCES havre.current_state_snapshots(owner_id, state_snapshot_id),
    ADD CONSTRAINT provenance_edges_owner_derived_goal_progress_fk
        FOREIGN KEY (owner_id, derived_goal_progress_id)
        REFERENCES havre.goal_progress_records(owner_id, progress_record_id);

CREATE INDEX provenance_edges_owner_source_belief_fk_idx
    ON havre.provenance_edges(owner_id, source_belief_id, source_belief_revision)
    WHERE source_belief_id IS NOT NULL;
CREATE INDEX provenance_edges_owner_derived_belief_fk_idx
    ON havre.provenance_edges(owner_id, derived_belief_id, derived_belief_revision)
    WHERE derived_belief_id IS NOT NULL;
CREATE INDEX provenance_edges_owner_derived_proposal_fk_idx
    ON havre.provenance_edges(owner_id, derived_proposal_id)
    WHERE derived_proposal_id IS NOT NULL;
CREATE INDEX provenance_edges_owner_derived_state_fk_idx
    ON havre.provenance_edges(owner_id, derived_state_snapshot_id)
    WHERE derived_state_snapshot_id IS NOT NULL;
CREATE INDEX provenance_edges_owner_derived_goal_progress_fk_idx
    ON havre.provenance_edges(owner_id, derived_goal_progress_id)
    WHERE derived_goal_progress_id IS NOT NULL;

CREATE VIEW havre.provenance_integrity_violations AS
SELECT
    edge.provenance_edge_id,
    edge.owner_id,
    edge.source_kind,
    edge.source_id,
    edge.source_revision,
    CASE
        WHEN edge.source_kind = 'event' AND source_event.event_id IS NULL
            THEN 'missing_or_cross_owner_event_source'
        WHEN edge.source_kind = 'memory_revision' AND source_memory.memory_id IS NULL
            THEN 'missing_or_cross_owner_memory_source'
        WHEN edge.source_kind = 'belief_revision' AND source_belief.belief_id IS NULL
            THEN 'missing_or_cross_owner_belief_source'
        WHEN edge.derived_kind = 'memory_revision' AND derived_memory.memory_id IS NULL
            THEN 'missing_or_cross_owner_memory_destination'
        WHEN edge.derived_kind = 'belief_revision' AND derived_belief.belief_id IS NULL
            THEN 'missing_or_cross_owner_belief_destination'
        WHEN edge.derived_kind = 'consolidation_proposal' AND derived_proposal.proposal_id IS NULL
            THEN 'missing_or_cross_owner_proposal_destination'
        WHEN edge.derived_kind = 'current_state_snapshot' AND derived_state.state_snapshot_id IS NULL
            THEN 'missing_or_cross_owner_state_destination'
        WHEN edge.derived_kind = 'goal_progress_record' AND derived_progress.progress_record_id IS NULL
            THEN 'missing_or_cross_owner_progress_destination'
    END AS violation_code
FROM havre.provenance_edges AS edge
LEFT JOIN havre.events AS source_event
  ON edge.source_kind = 'event'
 AND source_event.owner_id = edge.owner_id
 AND source_event.event_id = edge.source_id
LEFT JOIN havre.memory_revisions AS source_memory
  ON edge.source_kind = 'memory_revision'
 AND source_memory.owner_id = edge.owner_id
 AND source_memory.memory_id = edge.source_id
 AND source_memory.revision = edge.source_revision
LEFT JOIN havre.user_belief_revisions AS source_belief
  ON edge.source_kind = 'belief_revision'
 AND source_belief.owner_id = edge.owner_id
 AND source_belief.belief_id = edge.source_id
 AND source_belief.revision = edge.source_revision
LEFT JOIN havre.memory_revisions AS derived_memory
  ON edge.derived_kind = 'memory_revision'
 AND derived_memory.owner_id = edge.owner_id
 AND derived_memory.memory_id = edge.derived_id
 AND derived_memory.revision = edge.derived_revision
LEFT JOIN havre.user_belief_revisions AS derived_belief
  ON edge.derived_kind = 'belief_revision'
 AND derived_belief.owner_id = edge.owner_id
 AND derived_belief.belief_id = edge.derived_id
 AND derived_belief.revision = edge.derived_revision
LEFT JOIN havre.consolidation_proposals AS derived_proposal
  ON edge.derived_kind = 'consolidation_proposal'
 AND derived_proposal.owner_id = edge.owner_id
 AND derived_proposal.proposal_id = edge.derived_id
LEFT JOIN havre.current_state_snapshots AS derived_state
  ON edge.derived_kind = 'current_state_snapshot'
 AND derived_state.owner_id = edge.owner_id
 AND derived_state.state_snapshot_id = edge.derived_id
LEFT JOIN havre.goal_progress_records AS derived_progress
  ON edge.derived_kind = 'goal_progress_record'
 AND derived_progress.owner_id = edge.owner_id
 AND derived_progress.progress_record_id = edge.derived_id
WHERE (edge.source_kind = 'event' AND source_event.event_id IS NULL)
   OR (edge.source_kind = 'memory_revision' AND source_memory.memory_id IS NULL)
   OR (edge.source_kind = 'belief_revision' AND source_belief.belief_id IS NULL)
   OR (edge.derived_kind = 'memory_revision' AND derived_memory.memory_id IS NULL)
   OR (edge.derived_kind = 'belief_revision' AND derived_belief.belief_id IS NULL)
   OR (edge.derived_kind = 'consolidation_proposal' AND derived_proposal.proposal_id IS NULL)
   OR (edge.derived_kind = 'current_state_snapshot' AND derived_state.state_snapshot_id IS NULL)
   OR (edge.derived_kind = 'goal_progress_record' AND derived_progress.progress_record_id IS NULL);

CREATE FUNCTION havre.guard_consolidation_proposal_review() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF current_setting('havre.privileged_erasure', true) = 'on'
       AND pg_has_role(current_user, 'havre_privileged_erasure', 'MEMBER') THEN
        IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'consolidation_proposals is immutable outside privileged erasure'
            USING ERRCODE = '55000';
    END IF;
    IF OLD.status <> 'pending' OR NEW.status NOT IN (
        'accepted', 'accepted_with_correction', 'rejected'
    ) OR NEW.reviewed_by <> 'owner' OR NEW.reviewed_at IS NULL
       OR NEW.review_reason IS NULL OR NEW.review_event_id IS NULL THEN
        RAISE EXCEPTION 'proposal update must be one complete owner review transition'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.status IN ('accepted', 'accepted_with_correction')
       AND NEW.accepted_memory_id IS NULL THEN
        RAISE EXCEPTION 'accepted proposal requires an exact memory revision'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.status = 'rejected' AND NEW.accepted_memory_id IS NOT NULL THEN
        RAISE EXCEPTION 'rejected proposal cannot reference accepted memory'
            USING ERRCODE = '55000';
    END IF;
    IF (to_jsonb(NEW) - ARRAY[
            'status', 'reviewed_by', 'reviewed_at', 'review_reason',
            'accepted_memory_id', 'accepted_memory_revision', 'review_event_id'
        ]) IS DISTINCT FROM
       (to_jsonb(OLD) - ARRAY[
            'status', 'reviewed_by', 'reviewed_at', 'review_reason',
            'accepted_memory_id', 'accepted_memory_revision', 'review_event_id'
        ]) THEN
        RAISE EXCEPTION 'proposal content, evidence, and policy cannot change during review'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION havre.guard_goal_projection_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF current_setting('havre.privileged_erasure', true) = 'on'
       AND pg_has_role(current_user, 'havre_privileged_erasure', 'MEMBER') THEN
        IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'goals are deleted only through privileged erasure'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.owner_id <> OLD.owner_id OR NEW.goal_id <> OLD.goal_id
       OR NEW.track <> OLD.track OR NEW.created_at <> OLD.created_at
       OR NEW.policy_revision_id <> OLD.policy_revision_id
       OR NEW.revision <> OLD.revision + 1
       OR NEW.last_event_id = OLD.last_event_id THEN
        RAISE EXCEPTION 'goal updates require one sequential event-backed projection revision'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION havre.guard_belief_head_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF current_setting('havre.privileged_erasure', true) = 'on'
       AND pg_has_role(current_user, 'havre_privileged_erasure', 'MEMBER') THEN
        IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'belief heads are deleted only through privileged erasure'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.owner_id <> OLD.owner_id OR NEW.belief_id <> OLD.belief_id
       OR NEW.belief_key <> OLD.belief_key
       OR NEW.current_revision < OLD.current_revision
       OR NEW.current_revision > OLD.current_revision + 1 THEN
        RAISE EXCEPTION 'belief head update violates identity or sequential revision order'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER user_belief_revisions_are_immutable
BEFORE UPDATE OR DELETE ON havre.user_belief_revisions
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();

CREATE TRIGGER belief_revision_transitions_are_immutable
BEFORE UPDATE OR DELETE ON havre.belief_revision_transitions
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();

CREATE TRIGGER belief_heads_are_guarded
BEFORE UPDATE OR DELETE ON havre.belief_heads
FOR EACH ROW EXECUTE FUNCTION havre.guard_belief_head_update();

CREATE TRIGGER consolidation_proposals_are_review_guarded
BEFORE UPDATE OR DELETE ON havre.consolidation_proposals
FOR EACH ROW EXECUTE FUNCTION havre.guard_consolidation_proposal_review();

CREATE TRIGGER current_state_snapshots_are_immutable
BEFORE UPDATE OR DELETE ON havre.current_state_snapshots
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();

CREATE TRIGGER goals_are_projection_guarded
BEFORE UPDATE OR DELETE ON havre.goals
FOR EACH ROW EXECUTE FUNCTION havre.guard_goal_projection_update();

CREATE TRIGGER goal_progress_records_are_immutable
BEFORE UPDATE OR DELETE ON havre.goal_progress_records
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();

CREATE TRIGGER user_model_evaluation_runs_are_immutable
BEFORE UPDATE OR DELETE ON havre.user_model_evaluation_runs
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();
