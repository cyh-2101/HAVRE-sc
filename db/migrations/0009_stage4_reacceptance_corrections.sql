-- Stage 4 second Product Owner reacceptance corrections.
--
-- This migration is intentionally additive. Migrations 0001-0008 are an
-- immutable historical snapshot and may already be installed. Stage 5 and
-- proactive runtime remain inactive.

-- A transition identity is consumed exactly once when it projects a belief
-- head. The identity is qualified by the same owner, belief, and source
-- revision as the immutable transition; no application/database clock
-- comparison participates in admission.
CREATE UNIQUE INDEX belief_revision_transitions_projection_identity_key
    ON havre.belief_revision_transitions(
        owner_id, belief_id, belief_revision, belief_transition_id
    );

CREATE TABLE havre.belief_head_projection_consumptions (
    belief_transition_id uuid PRIMARY KEY,
    owner_id uuid NOT NULL,
    belief_id uuid NOT NULL,
    source_revision integer NOT NULL CHECK (source_revision > 0),
    target_revision integer NOT NULL CHECK (target_revision > 0),
    target_status text NOT NULL CHECK (target_status IN (
        'candidate', 'active', 'contradicted', 'superseded', 'retracted', 'invalidated'
    )),
    consumed_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    FOREIGN KEY (owner_id, belief_id, source_revision, belief_transition_id)
        REFERENCES havre.belief_revision_transitions(
            owner_id, belief_id, belief_revision, belief_transition_id
        ) ON DELETE CASCADE,
    FOREIGN KEY (owner_id, belief_id, target_revision)
        REFERENCES havre.user_belief_revisions(owner_id, belief_id, revision)
);

CREATE INDEX belief_head_consumptions_transition_fk_idx
    ON havre.belief_head_projection_consumptions(
        owner_id, belief_id, source_revision, belief_transition_id
    );
CREATE INDEX belief_head_consumptions_target_revision_fk_idx
    ON havre.belief_head_projection_consumptions(
        owner_id, belief_id, target_revision
    );

-- Every pre-0009 transition is historical and therefore unavailable for a
-- future projection update. This makes an in-place upgrade fail closed.
INSERT INTO havre.belief_head_projection_consumptions (
    belief_transition_id, owner_id, belief_id, source_revision,
    target_revision, target_status, consumed_at
)
SELECT
    transition.belief_transition_id,
    transition.owner_id,
    transition.belief_id,
    transition.belief_revision,
    COALESCE(transition.replacement_revision, transition.belief_revision),
    CASE transition.transition_type
        WHEN 'activated' THEN 'active'
        WHEN 'contradicted' THEN 'contradicted'
        WHEN 'superseded' THEN 'active'
        WHEN 'retracted' THEN 'retracted'
        WHEN 'invalidated' THEN 'invalidated'
        ELSE revision.initial_status
    END,
    statement_timestamp()
FROM havre.belief_revision_transitions AS transition
JOIN havre.user_belief_revisions AS revision
  ON revision.owner_id = transition.owner_id
 AND revision.belief_id = transition.belief_id
 AND revision.revision = COALESCE(
        transition.replacement_revision, transition.belief_revision
    );

CREATE TRIGGER belief_head_projection_consumptions_are_immutable
BEFORE UPDATE OR DELETE ON havre.belief_head_projection_consumptions
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();

ALTER TABLE havre.belief_heads
    ADD COLUMN last_transition_id uuid NULL,
    ADD CONSTRAINT belief_heads_owner_last_transition_fk
        FOREIGN KEY (owner_id, last_transition_id)
        REFERENCES havre.belief_revision_transitions(
            owner_id, belief_transition_id
        ) ON DELETE SET NULL (last_transition_id);

CREATE INDEX belief_heads_owner_last_transition_fk_idx
    ON havre.belief_heads(owner_id, last_transition_id)
    WHERE last_transition_id IS NOT NULL;

CREATE OR REPLACE FUNCTION havre.guard_belief_head_update() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    exact_transition record;
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

    IF NEW.updated_at IS DISTINCT FROM statement_timestamp() THEN
        RAISE EXCEPTION
            'belief head guard: updated_at must equal database statement time'
            USING ERRCODE = '55000';
    END IF;

    IF NEW.current_revision <> OLD.current_revision
       AND NEW.current_revision <> OLD.current_revision + 1 THEN
        RAISE EXCEPTION 'belief head guard: revision must advance exactly one'
            USING ERRCODE = '55000';
    END IF;

    IF NEW.last_transition_id IS NULL
       OR NEW.last_transition_id IS NOT DISTINCT FROM OLD.last_transition_id THEN
        RAISE EXCEPTION
            'belief head guard: update lacks a new explicit transition identity'
            USING ERRCODE = '55000';
    END IF;

    SELECT transition.* INTO exact_transition
    FROM havre.belief_revision_transitions AS transition
    JOIN havre.events AS event
      ON event.owner_id = transition.owner_id
     AND event.event_id = transition.causing_event_id
    WHERE transition.owner_id = OLD.owner_id
      AND transition.belief_id = OLD.belief_id
      AND transition.belief_transition_id = NEW.last_transition_id
      AND event.event_type = 'USER_BELIEF_TRANSITIONED'
      AND event.payload->>'belief_transition_id'
            = transition.belief_transition_id::text
      AND event.payload->>'belief_id' = transition.belief_id::text
      AND event.payload->>'belief_revision' = transition.belief_revision::text
      AND event.payload->>'transition_type' = transition.transition_type
      AND event.payload->>'replacement_belief_id'
            IS NOT DISTINCT FROM transition.replacement_belief_id::text
      AND event.payload->>'replacement_revision'
            IS NOT DISTINCT FROM transition.replacement_revision::text;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'belief head guard: transition identity is not exact for this owner and belief'
            USING ERRCODE = '55000';
    END IF;

    IF NEW.current_revision = OLD.current_revision THEN
        IF exact_transition.belief_revision <> OLD.current_revision
           OR exact_transition.replacement_belief_id IS NOT NULL
           OR exact_transition.replacement_revision IS NOT NULL
           OR NOT (
                (exact_transition.transition_type = 'activated'
                 AND OLD.status = 'candidate' AND NEW.status = 'active')
             OR (exact_transition.transition_type = 'counter_evidence_recorded'
                 AND NEW.status = OLD.status)
             OR (exact_transition.transition_type = 'contradicted'
                 AND NEW.status = 'contradicted')
             OR (exact_transition.transition_type = 'retracted'
                 AND NEW.status = 'retracted')
             OR (exact_transition.transition_type = 'invalidated'
                 AND NEW.status = 'invalidated')
           ) THEN
            RAISE EXCEPTION
                'belief head guard: status update lacks the exact immutable transition'
                USING ERRCODE = '55000';
        END IF;
    ELSE
        IF exact_transition.belief_revision <> OLD.current_revision
           OR exact_transition.transition_type <> 'superseded'
           OR exact_transition.replacement_belief_id <> OLD.belief_id
           OR exact_transition.replacement_revision <> NEW.current_revision
           OR NOT EXISTS (
                SELECT 1
                FROM havre.user_belief_revisions AS revision
                WHERE revision.owner_id = OLD.owner_id
                  AND revision.belief_id = OLD.belief_id
                  AND revision.revision = NEW.current_revision
                  AND revision.supersedes_revision = OLD.current_revision
                  AND NEW.status = revision.initial_status
           ) THEN
            RAISE EXCEPTION
                'belief head guard: revision advance lacks exact revision and superseded transition'
                USING ERRCODE = '55000';
        END IF;
    END IF;

    BEGIN
        INSERT INTO havre.belief_head_projection_consumptions (
            belief_transition_id, owner_id, belief_id, source_revision,
            target_revision, target_status
        ) VALUES (
            exact_transition.belief_transition_id,
            exact_transition.owner_id,
            exact_transition.belief_id,
            exact_transition.belief_revision,
            NEW.current_revision,
            NEW.status
        );
    EXCEPTION WHEN unique_violation THEN
        RAISE EXCEPTION
            'belief head guard: transition identity was already consumed'
            USING ERRCODE = '55000';
    END;

    RETURN NEW;
END;
$$;

-- Goal lifecycle events carry the complete canonical projection material and
-- its digest. The guard verifies the digest, every material field, the event
-- relationship, and a single PostgreSQL statement timestamp.
CREATE OR REPLACE FUNCTION havre.guard_goal_projection_update() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    expected_event_type text;
    expected_action text;
    lifecycle_event record;
    canonical_projection text;
    projection jsonb;
    expected_hash text;
    projection_matches boolean;
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

    IF NEW.updated_at IS DISTINCT FROM statement_timestamp() THEN
        RAISE EXCEPTION
            'goal projection guard: updated_at must equal database statement time'
            USING ERRCODE = '55000';
    END IF;

    IF (CASE NEW.privacy_class
            WHEN 'PUBLIC' THEN 0 WHEN 'NORMAL' THEN 1 WHEN 'PRIVATE' THEN 2
            WHEN 'HIGHLY_PRIVATE' THEN 3 WHEN 'LOCAL_ONLY' THEN 4 ELSE -1
        END)
       < (CASE OLD.privacy_class
            WHEN 'PUBLIC' THEN 0 WHEN 'NORMAL' THEN 1 WHEN 'PRIVATE' THEN 2
            WHEN 'HIGHLY_PRIVATE' THEN 3 WHEN 'LOCAL_ONLY' THEN 4 ELSE -1
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

    SELECT event.* INTO lifecycle_event
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

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'goal projection guard: update lacks one exact immutable lifecycle event'
            USING ERRCODE = '55000';
    END IF;

    canonical_projection :=
        lifecycle_event.payload->>'projection_canonical_json';

    BEGIN
        projection := canonical_projection::jsonb;
        expected_hash := 'sha256:' || encode(
            sha256(convert_to(canonical_projection, 'UTF8')), 'hex'
        );
        projection_matches :=
            (projection->>'schema_version')::smallint = NEW.schema_version
            AND projection->>'goal_id' = NEW.goal_id::text
            AND projection->>'owner_id' = NEW.owner_id::text
            AND projection->>'track' = NEW.track
            AND projection->>'title' = NEW.title
            AND projection->>'why' = NEW.why
            AND projection->>'priority' = NEW.priority
            AND projection->>'status' = NEW.status
            AND projection->>'next_action' IS NOT DISTINCT FROM NEW.next_action
            AND (projection->>'review_at')::timestamptz
                IS NOT DISTINCT FROM NEW.review_at
            AND (projection->>'revision')::integer = NEW.revision
            AND projection->>'last_event_id' = NEW.last_event_id::text
            AND (projection->'data_policy'->>'schema_version')::smallint = 1
            AND projection->'data_policy'->>'policy_revision_id'
                = NEW.policy_revision_id::text
            AND projection->'data_policy'->>'privacy_class' = NEW.privacy_class
            AND (projection->'data_policy'->>'memory_eligible')::boolean
                = NEW.memory_eligible
            AND (projection->'data_policy'->>'training_eligible')::boolean
                = NEW.training_eligible
            AND (projection->'data_policy'->>'cloud_eligible')::boolean
                = NEW.cloud_eligible
            AND projection->'data_policy'->>'policy_version' = NEW.policy_version
            AND projection->'data_policy'->>'decision_source'
                = NEW.policy_decision_source
            AND projection->'data_policy'->>'authorization_ref'
                IS NOT DISTINCT FROM NEW.policy_authorization_ref;
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION
            'goal projection guard: lifecycle projection material is invalid'
            USING ERRCODE = '55000';
    END;

    IF lifecycle_event.payload->>'projection_content_hash'
            IS DISTINCT FROM NEW.content_hash
       OR expected_hash IS DISTINCT FROM NEW.content_hash
       OR projection_matches IS DISTINCT FROM true THEN
        RAISE EXCEPTION
            'goal projection guard: content hash is not bound to the full lifecycle projection'
            USING ERRCODE = '55000';
    END IF;

    RETURN NEW;
END;
$$;

-- Missing Stage 4 provenance FK-side coverage identified by the reacceptance
-- catalog audit. Existing partial generated-column indexes remain unchanged.
CREATE INDEX provenance_edges_owner_derived_memory_fk_idx
    ON havre.provenance_edges(
        owner_id, derived_memory_id, derived_memory_revision
    ) WHERE derived_memory_id IS NOT NULL;
