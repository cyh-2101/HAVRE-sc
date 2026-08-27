-- Stage 4 Product Owner acceptance corrections.
--
-- This migration is intentionally additive. Migrations 0001-0007 are an
-- immutable historical snapshot and may already be installed. Stage 5 and
-- proactive runtime remain inactive.

CREATE OR REPLACE FUNCTION havre.guard_belief_head_update() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    exact_transition_count integer;
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

    IF NEW.owner_id IS DISTINCT FROM OLD.owner_id
       OR NEW.belief_id IS DISTINCT FROM OLD.belief_id
       OR NEW.belief_key IS DISTINCT FROM OLD.belief_key THEN
        RAISE EXCEPTION 'belief head guard: identity is immutable'
            USING ERRCODE = '55000';
    END IF;

    IF NEW.updated_at <= OLD.updated_at THEN
        RAISE EXCEPTION 'belief head guard: updated_at must advance'
            USING ERRCODE = '55000';
    END IF;

    IF NEW.current_revision = OLD.current_revision THEN
        SELECT count(*) INTO exact_transition_count
        FROM havre.belief_revision_transitions AS transition
        JOIN havre.events AS event
          ON event.owner_id = transition.owner_id
         AND event.event_id = transition.causing_event_id
        WHERE transition.owner_id = OLD.owner_id
          AND transition.belief_id = OLD.belief_id
          AND transition.belief_revision = OLD.current_revision
          AND transition.recorded_at > OLD.updated_at
          AND transition.recorded_at <= NEW.updated_at
          AND transition.replacement_belief_id IS NULL
          AND transition.replacement_revision IS NULL
          AND event.event_type = 'USER_BELIEF_TRANSITIONED'
          AND event.payload->>'belief_transition_id'
                = transition.belief_transition_id::text
          AND event.payload->>'belief_id' = OLD.belief_id::text
          AND event.payload->>'belief_revision' = OLD.current_revision::text
          AND event.payload->>'transition_type' = transition.transition_type
          AND event.payload->>'replacement_belief_id' IS NULL
          AND event.payload->>'replacement_revision' IS NULL
          AND (
                (transition.transition_type = 'activated'
                 AND OLD.status = 'candidate' AND NEW.status = 'active')
             OR (transition.transition_type = 'counter_evidence_recorded'
                 AND NEW.status = OLD.status)
             OR (transition.transition_type = 'contradicted'
                 AND NEW.status = 'contradicted')
             OR (transition.transition_type = 'retracted'
                 AND NEW.status = 'retracted')
             OR (transition.transition_type = 'invalidated'
                 AND NEW.status = 'invalidated')
          );

        IF exact_transition_count <> 1 THEN
            RAISE EXCEPTION
                'belief head guard: status update lacks one exact immutable transition'
                USING ERRCODE = '55000';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.current_revision <> OLD.current_revision + 1 THEN
        RAISE EXCEPTION 'belief head guard: revision must advance exactly one'
            USING ERRCODE = '55000';
    END IF;

    SELECT count(*) INTO exact_transition_count
    FROM havre.user_belief_revisions AS revision
    JOIN havre.belief_revision_transitions AS transition
      ON transition.owner_id = revision.owner_id
     AND transition.belief_id = revision.belief_id
     AND transition.belief_revision = OLD.current_revision
     AND transition.transition_type = 'superseded'
     AND transition.replacement_belief_id = revision.belief_id
     AND transition.replacement_revision = revision.revision
    JOIN havre.events AS event
      ON event.owner_id = transition.owner_id
     AND event.event_id = transition.causing_event_id
    WHERE revision.owner_id = OLD.owner_id
      AND revision.belief_id = OLD.belief_id
      AND revision.revision = NEW.current_revision
      AND revision.supersedes_revision = OLD.current_revision
      AND NEW.status = revision.initial_status
      AND transition.recorded_at > OLD.updated_at
      AND transition.recorded_at <= NEW.updated_at
      AND event.event_type = 'USER_BELIEF_TRANSITIONED'
      AND event.payload->>'belief_transition_id'
            = transition.belief_transition_id::text
      AND event.payload->>'belief_id' = OLD.belief_id::text
      AND event.payload->>'belief_revision' = OLD.current_revision::text
      AND event.payload->>'transition_type' = 'superseded'
      AND event.payload->>'replacement_belief_id' = OLD.belief_id::text
      AND event.payload->>'replacement_revision' = NEW.current_revision::text;

    IF exact_transition_count <> 1 THEN
        RAISE EXCEPTION
            'belief head guard: revision advance lacks exact revision and superseded transition'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION havre.guard_goal_projection_update() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    expected_event_type text;
    expected_action text;
    exact_event_count integer;
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

    IF NEW.owner_id IS DISTINCT FROM OLD.owner_id
       OR NEW.goal_id IS DISTINCT FROM OLD.goal_id
       OR NEW.track IS DISTINCT FROM OLD.track
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'goal projection guard: identity and track are immutable'
            USING ERRCODE = '55000';
    END IF;

    IF OLD.status IN ('completed', 'abandoned') THEN
        RAISE EXCEPTION 'goal projection guard: closed goals cannot be updated'
            USING ERRCODE = '55000';
    END IF;

    IF NEW.revision <> OLD.revision + 1
       OR NEW.last_event_id = OLD.last_event_id THEN
        RAISE EXCEPTION
            'goal projection guard: revision must advance exactly one with a new event'
            USING ERRCODE = '55000';
    END IF;

    IF (CASE NEW.privacy_class
            WHEN 'PUBLIC' THEN 0
            WHEN 'NORMAL' THEN 1
            WHEN 'PRIVATE' THEN 2
            WHEN 'HIGHLY_PRIVATE' THEN 3
            WHEN 'LOCAL_ONLY' THEN 4
            ELSE -1
        END)
       < (CASE OLD.privacy_class
            WHEN 'PUBLIC' THEN 0
            WHEN 'NORMAL' THEN 1
            WHEN 'PRIVATE' THEN 2
            WHEN 'HIGHLY_PRIVATE' THEN 3
            WHEN 'LOCAL_ONLY' THEN 4
            ELSE -1
          END)
       OR (NOT OLD.memory_eligible AND NEW.memory_eligible)
       OR (NOT OLD.training_eligible AND NEW.training_eligible)
       OR (NOT OLD.cloud_eligible AND NEW.cloud_eligible) THEN
        RAISE EXCEPTION 'goal projection guard: DataPolicy cannot become less restrictive'
            USING ERRCODE = '55000';
    END IF;

    IF NEW.status = 'completed' THEN
        expected_event_type := 'GOAL_COMPLETED';
        expected_action := 'completed';
    ELSE
        expected_event_type := 'GOAL_UPDATED';
        expected_action := 'updated';
    END IF;

    SELECT count(*) INTO exact_event_count
    FROM havre.events AS event
    WHERE event.owner_id = OLD.owner_id
      AND event.event_id = NEW.last_event_id
      AND event.event_type = expected_event_type
      AND event.causation_event_id = OLD.last_event_id
      AND event.payload->>'goal_id' = NEW.goal_id::text
      AND event.payload->>'goal_revision' = NEW.revision::text
      AND event.payload->>'action' = expected_action
      AND event.payload->>'track' = NEW.track
      AND event.payload->>'title' = NEW.title
      AND event.payload->>'why' = NEW.why
      AND event.payload->>'priority' = NEW.priority
      AND event.payload->>'status' = NEW.status
      AND event.payload->>'next_action' IS NOT DISTINCT FROM NEW.next_action
      AND (event.payload->>'review_at')::timestamptz
            IS NOT DISTINCT FROM NEW.review_at
      AND event.privacy_class = NEW.privacy_class
      AND event.memory_eligible = NEW.memory_eligible
      AND event.training_eligible = NEW.training_eligible
      AND event.cloud_eligible = NEW.cloud_eligible
      AND event.policy_version = NEW.policy_version
      AND event.policy_revision_id = NEW.policy_revision_id
      AND event.policy_decision_source = NEW.policy_decision_source
      AND event.policy_authorization_ref
            IS NOT DISTINCT FROM NEW.policy_authorization_ref;

    IF exact_event_count <> 1 THEN
        RAISE EXCEPTION
            'goal projection guard: update lacks one exact immutable lifecycle event'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

-- Explicit indexes for Stage 4 referencing foreign keys. Existing generated-
-- column provenance indexes from 0004 and 0007 already cover event, memory,
-- belief, proposal, Current State, and goal-progress provenance endpoints.
CREATE INDEX user_belief_revisions_owner_supersedes_fk_idx
    ON havre.user_belief_revisions(owner_id, belief_id, supersedes_revision)
    WHERE supersedes_revision IS NOT NULL;
CREATE INDEX belief_revision_transitions_owner_replacement_fk_idx
    ON havre.belief_revision_transitions(
        owner_id, replacement_belief_id, replacement_revision
    ) WHERE replacement_belief_id IS NOT NULL;
CREATE INDEX belief_heads_owner_current_revision_fk_idx
    ON havre.belief_heads(owner_id, belief_id, current_revision);

CREATE INDEX consolidation_proposals_owner_accepted_memory_fk_idx
    ON havre.consolidation_proposals(
        owner_id, accepted_memory_id, accepted_memory_revision
    ) WHERE accepted_memory_id IS NOT NULL;
CREATE INDEX consolidation_proposals_owner_created_event_fk_idx
    ON havre.consolidation_proposals(owner_id, created_event_id);
CREATE INDEX consolidation_proposals_owner_review_event_fk_idx
    ON havre.consolidation_proposals(owner_id, review_event_id)
    WHERE review_event_id IS NOT NULL;
CREATE INDEX consolidation_proposals_owner_trace_fk_idx
    ON havre.consolidation_proposals(owner_id, trace_id);

CREATE INDEX current_state_snapshots_owner_created_event_fk_idx
    ON havre.current_state_snapshots(owner_id, created_event_id);
CREATE INDEX current_state_snapshots_owner_trace_fk_idx
    ON havre.current_state_snapshots(owner_id, trace_id);

CREATE INDEX goals_owner_last_event_fk_idx
    ON havre.goals(owner_id, last_event_id);

CREATE INDEX goal_progress_records_owner_created_event_fk_idx
    ON havre.goal_progress_records(owner_id, created_event_id);
CREATE INDEX goal_progress_records_owner_trace_fk_idx
    ON havre.goal_progress_records(owner_id, trace_id);
