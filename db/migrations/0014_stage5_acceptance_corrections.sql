-- Stage 5 acceptance corrections.
--
-- This migration is intentionally additive. Migration 0013 is an immutable
-- historical snapshot that may already be installed. Nothing in this file
-- activates Stage 6 outreach, scheduling, rendering, or delivery.

-- Compact, recursively key-sorted JSON matching companion.hashing.canonical_json
-- for the Stage 5 contract's strings, integers, booleans, nulls, arrays, and
-- objects. Durable hashes are reconstructed from database rows, never trusted
-- from caller-provided JSON.
CREATE FUNCTION havre.stage5_canonical_jsonb(material jsonb)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
STRICT
AS $$
DECLARE
    rendered text;
BEGIN
    CASE jsonb_typeof(material)
        WHEN 'object' THEN
            SELECT '{' || COALESCE(string_agg(
                to_json(entry.key)::text || ':' ||
                havre.stage5_canonical_jsonb(entry.value),
                ',' ORDER BY entry.key
            ), '') || '}'
            INTO rendered
            FROM jsonb_each(material) AS entry(key, value);
            RETURN rendered;
        WHEN 'array' THEN
            SELECT '[' || COALESCE(string_agg(
                havre.stage5_canonical_jsonb(entry.value),
                ',' ORDER BY entry.ordinality
            ), '') || ']'
            INTO rendered
            FROM jsonb_array_elements(material)
                 WITH ORDINALITY AS entry(value, ordinality);
            RETURN rendered;
        ELSE
            RETURN material::text;
    END CASE;
END;
$$;

CREATE FUNCTION havre.stage5_timestamp_json(value timestamptz)
RETURNS jsonb
LANGUAGE sql
STABLE
AS $$
    SELECT CASE
        WHEN value IS NULL THEN 'null'::jsonb
        ELSE to_jsonb(
            to_char(value AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS') ||
            CASE
                WHEN to_char(value AT TIME ZONE 'UTC', 'US') = '000000' THEN ''
                ELSE '.' || to_char(value AT TIME ZONE 'UTC', 'US')
            END || 'Z'
        )
    END
$$;

CREATE FUNCTION havre.stage5_data_policy_material(
    privacy_class text,
    memory_eligible boolean,
    training_eligible boolean,
    cloud_eligible boolean,
    policy_version text,
    policy_revision_id uuid,
    decision_source text,
    authorization_ref text
)
RETURNS jsonb
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT jsonb_build_object(
        'schema_version', 1,
        'policy_revision_id', policy_revision_id,
        'privacy_class', privacy_class,
        'memory_eligible', memory_eligible,
        'training_eligible', training_eligible,
        'cloud_eligible', cloud_eligible,
        'policy_version', policy_version,
        'decision_source', decision_source,
        'authorization_ref', authorization_ref
    )
$$;

CREATE FUNCTION havre.stage5_content_hash(material jsonb)
RETURNS text
LANGUAGE sql
IMMUTABLE
STRICT
AS $$
    SELECT 'sha256:' || encode(
        sha256(convert_to(havre.stage5_canonical_jsonb(material), 'UTF8')),
        'hex'
    )
$$;

CREATE FUNCTION havre.stage5_scene_session_material(scene_row havre.scene_sessions)
RETURNS jsonb
LANGUAGE sql
STABLE
STRICT
AS $$
    SELECT jsonb_build_object(
        'schema_version', scene_row.schema_version,
        'scene_session_id', scene_row.scene_session_id,
        'owner_id', scene_row.owner_id,
        'opened_session_id', scene_row.opened_session_id,
        'scene_type', scene_row.scene_type,
        'situation', scene_row.situation,
        'planned_goal', scene_row.planned_goal,
        'anticipated_triggers', scene_row.anticipated_triggers,
        'phase', scene_row.phase,
        'status', scene_row.status,
        'planned_start_at', havre.stage5_timestamp_json(scene_row.planned_start_at),
        'started_at', havre.stage5_timestamp_json(scene_row.started_at),
        'ended_at', havre.stage5_timestamp_json(scene_row.ended_at),
        'revision', scene_row.revision,
        'created_event_id', scene_row.created_event_id,
        'last_event_id', scene_row.last_event_id,
        'trace_id', scene_row.trace_id::text,
        'data_policy', havre.stage5_data_policy_material(
            scene_row.privacy_class, scene_row.memory_eligible,
            scene_row.training_eligible, scene_row.cloud_eligible,
            scene_row.policy_version, scene_row.policy_revision_id,
            scene_row.policy_decision_source, scene_row.policy_authorization_ref
        )
    )
$$;

CREATE FUNCTION havre.stage5_scene_record_material(record_row havre.scene_records)
RETURNS jsonb
LANGUAGE sql
STABLE
STRICT
AS $$
    SELECT jsonb_build_object(
        'schema_version', record_row.schema_version,
        'scene_record_id', record_row.scene_record_id,
        'owner_id', record_row.owner_id,
        'scene_session_id', record_row.scene_session_id,
        'record_type', record_row.record_type,
        'phase', record_row.phase,
        'sequence_number', record_row.sequence_number,
        'occurred_at', havre.stage5_timestamp_json(record_row.occurred_at),
        'event_id', record_row.event_id,
        'assistant_event_id', record_row.assistant_event_id,
        'artifact_kind', record_row.artifact_kind,
        'artifact_id', record_row.artifact_id,
        'artifact_revision', record_row.artifact_revision,
        'causal_predecessor_id', record_row.causal_predecessor_id,
        'source', record_row.source,
        'uncertainty_note', record_row.uncertainty_note,
        'content', record_row.content,
        'trace_id', record_row.trace_id::text,
        'data_policy', havre.stage5_data_policy_material(
            record_row.privacy_class, record_row.memory_eligible,
            record_row.training_eligible, record_row.cloud_eligible,
            record_row.policy_version, record_row.policy_revision_id,
            record_row.policy_decision_source, record_row.policy_authorization_ref
        )
    )
$$;

CREATE FUNCTION havre.stage5_intervention_decision_material(
    decision_row havre.intervention_decisions
)
RETURNS jsonb
LANGUAGE sql
STABLE
STRICT
AS $$
    SELECT jsonb_build_object(
        'schema_version', decision_row.schema_version,
        'intervention_decision_id', decision_row.intervention_decision_id,
        'owner_id', decision_row.owner_id,
        'scene_session_id', decision_row.scene_session_id,
        'scene_revision', decision_row.scene_revision,
        'input_event_id', decision_row.input_event_id,
        'input_record_id', decision_row.input_record_id,
        'phase', decision_row.phase,
        'policy_version', decision_row.policy_version_id,
        'policy_release_status', decision_row.policy_release_status,
        'constitution_version_id', decision_row.constitution_version_id,
        'identity_version_id', decision_row.identity_version_id,
        'values_version_id', decision_row.values_version_id,
        'branch', decision_row.branch,
        'recommended_intervention', decision_row.recommended_intervention,
        'response_style', decision_row.response_style,
        'guidance', decision_row.guidance,
        'minimum_action', decision_row.minimum_action,
        'clarification_question', decision_row.clarification_question,
        'reason_codes', decision_row.reason_codes,
        'required_constraints', decision_row.required_constraints,
        'outreach_authorized', decision_row.outreach_authorized,
        'simulation_only', decision_row.simulation_only,
        'trace_id', decision_row.trace_id::text,
        'data_policy', havre.stage5_data_policy_material(
            decision_row.privacy_class, decision_row.memory_eligible,
            decision_row.training_eligible, decision_row.cloud_eligible,
            decision_row.data_policy_version, decision_row.policy_revision_id,
            decision_row.policy_decision_source,
            decision_row.policy_authorization_ref
        )
    )
$$;

CREATE FUNCTION havre.stage5_guidance_outcome_material(
    observation_row havre.guidance_outcome_observations
)
RETURNS jsonb
LANGUAGE sql
STABLE
STRICT
AS $$
    SELECT jsonb_build_object(
        'schema_version', observation_row.schema_version,
        'outcome_observation_id', observation_row.outcome_observation_id,
        'owner_id', observation_row.owner_id,
        'scene_session_id', observation_row.scene_session_id,
        'intervention_decision_id', observation_row.intervention_decision_id,
        'guidance_event_id', observation_row.guidance_event_id,
        'action_record_id', observation_row.action_record_id,
        'outcome_record_id', observation_row.outcome_record_id,
        'reflection_record_id', observation_row.reflection_record_id,
        'observation_window_started_at',
            havre.stage5_timestamp_json(observation_row.observation_window_started_at),
        'observation_window_ended_at',
            havre.stage5_timestamp_json(observation_row.observation_window_ended_at),
        'reporter', observation_row.reporter,
        'action_attempted', observation_row.action_attempted,
        'planned_scene_status', observation_row.planned_scene_status,
        'helpfulness', observation_row.helpfulness,
        'too_passive', observation_row.too_passive,
        'too_forceful', observation_row.too_forceful,
        'later_regret', observation_row.later_regret,
        'limitations', observation_row.limitations,
        'consented', observation_row.consented,
        'evidence_snapshot', observation_row.evidence_snapshot,
        'created_event_id', observation_row.created_event_id,
        'trace_id', observation_row.trace_id::text,
        'data_policy', havre.stage5_data_policy_material(
            observation_row.privacy_class, observation_row.memory_eligible,
            observation_row.training_eligible, observation_row.cloud_eligible,
            observation_row.policy_version, observation_row.policy_revision_id,
            observation_row.policy_decision_source,
            observation_row.policy_authorization_ref
        )
    )
$$;

CREATE OR REPLACE FUNCTION havre.guard_scene_session_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    expected_hash text;
BEGIN
    IF NEW.revision <> 1 OR NEW.phase <> 'before' OR NEW.status <> 'planned'
       OR NEW.started_at IS NOT NULL OR NEW.ended_at IS NOT NULL
       OR NEW.created_event_id <> NEW.last_event_id
       OR NOT EXISTS (
            SELECT 1 FROM havre.events AS event
            WHERE event.owner_id = NEW.owner_id
              AND event.event_id = NEW.created_event_id
              AND event.event_type = 'SCENE_SESSION_PLANNED'
              AND event.scene_session_id = NEW.scene_session_id
              AND event.session_id = NEW.opened_session_id
              AND event.trace_id = NEW.trace_id
              AND event.causation_event_id IS NULL
              AND event.payload->>'scene_session_id' = NEW.scene_session_id::text
              AND event.payload->>'scene_revision' = '1'
              AND event.payload->>'action' = 'planned'
              AND event.payload->>'phase' = 'before'
              AND event.payload->>'status' = 'planned'
              AND event.payload->'situation' = NEW.situation
              AND event.payload->'planned_goal' = NEW.planned_goal
              AND event.payload->'anticipated_triggers' = NEW.anticipated_triggers
              AND event.privacy_class = NEW.privacy_class
              AND event.memory_eligible = NEW.memory_eligible
              AND event.training_eligible = NEW.training_eligible
              AND event.cloud_eligible = NEW.cloud_eligible
              AND event.policy_version = NEW.policy_version
              AND event.policy_revision_id = NEW.policy_revision_id
              AND event.policy_decision_source = NEW.policy_decision_source
              AND event.policy_authorization_ref
                    IS NOT DISTINCT FROM NEW.policy_authorization_ref
       ) THEN
        RAISE EXCEPTION
            'Scene Session insert requires one exact planned lifecycle event'
            USING ERRCODE = '55000';
    END IF;
    expected_hash := havre.stage5_content_hash(
        havre.stage5_scene_session_material(NEW)
    );
    IF NEW.content_hash IS DISTINCT FROM expected_hash THEN
        RAISE EXCEPTION 'Scene Session insert has a noncanonical content hash'
            USING ERRCODE = '55000';
    END IF;
    NEW.created_at := statement_timestamp();
    NEW.updated_at := NEW.created_at;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION havre.guard_scene_session_update() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    expected_lifecycle_event_type text;
    expected_action text;
    expected_hash text;
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
    IF NEW.owner_id IS DISTINCT FROM OLD.owner_id
       OR NEW.scene_session_id IS DISTINCT FROM OLD.scene_session_id
       OR NEW.opened_session_id IS DISTINCT FROM OLD.opened_session_id
       OR NEW.scene_type IS DISTINCT FROM OLD.scene_type
       OR NEW.situation IS DISTINCT FROM OLD.situation
       OR NEW.planned_goal IS DISTINCT FROM OLD.planned_goal
       OR NEW.anticipated_triggers IS DISTINCT FROM OLD.anticipated_triggers
       OR NEW.planned_start_at IS DISTINCT FROM OLD.planned_start_at
       OR NEW.created_event_id IS DISTINCT FROM OLD.created_event_id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.trace_id IS DISTINCT FROM OLD.trace_id
       OR NEW.revision <> OLD.revision + 1
       OR NEW.last_event_id = OLD.last_event_id
       OR NEW.privacy_class IS DISTINCT FROM OLD.privacy_class
       OR NEW.memory_eligible IS DISTINCT FROM OLD.memory_eligible
       OR NEW.training_eligible IS DISTINCT FROM OLD.training_eligible
       OR NEW.cloud_eligible IS DISTINCT FROM OLD.cloud_eligible
       OR NEW.policy_version IS DISTINCT FROM OLD.policy_version
       OR NEW.policy_revision_id IS DISTINCT FROM OLD.policy_revision_id
       OR NEW.policy_decision_source IS DISTINCT FROM OLD.policy_decision_source
       OR NEW.policy_authorization_ref IS DISTINCT FROM OLD.policy_authorization_ref
       OR NEW.updated_at IS DISTINCT FROM transaction_timestamp() THEN
        RAISE EXCEPTION
            'Scene projection update changed immutable, nonsequential, or caller-timed material'
            USING ERRCODE = '55000';
    END IF;

    IF OLD.phase = 'before' AND OLD.status = 'planned'
       AND NEW.phase = 'during' AND NEW.status = 'active' THEN
        expected_lifecycle_event_type := 'SCENE_SESSION_STARTED';
        expected_action := 'started';
        IF OLD.started_at IS NOT NULL
           OR NEW.started_at IS DISTINCT FROM transaction_timestamp()
           OR NEW.ended_at IS NOT NULL THEN
            RAISE EXCEPTION 'Scene start timestamps must be database-authored'
                USING ERRCODE = '55000';
        END IF;
    ELSIF OLD.phase = 'during' AND OLD.status = 'active'
       AND NEW.phase = 'during' AND NEW.status = 'paused' THEN
        expected_lifecycle_event_type := 'SCENE_SESSION_PAUSED';
        expected_action := 'paused';
        IF NEW.started_at IS DISTINCT FROM OLD.started_at
           OR NEW.ended_at IS DISTINCT FROM OLD.ended_at THEN
            RAISE EXCEPTION 'pause cannot rewrite Scene timestamps'
                USING ERRCODE = '55000';
        END IF;
    ELSIF OLD.phase = 'during' AND OLD.status = 'paused'
       AND NEW.phase = 'during' AND NEW.status = 'active' THEN
        expected_lifecycle_event_type := 'SCENE_SESSION_STARTED';
        expected_action := 'resumed';
        IF NEW.started_at IS DISTINCT FROM OLD.started_at
           OR NEW.ended_at IS DISTINCT FROM OLD.ended_at THEN
            RAISE EXCEPTION 'resume cannot rewrite Scene timestamps'
                USING ERRCODE = '55000';
        END IF;
    ELSIF OLD.phase = 'during' AND OLD.status = 'active'
       AND NEW.phase = 'after' AND NEW.status = 'active' THEN
        expected_lifecycle_event_type := 'SCENE_PHASE_CHANGED';
        expected_action := 'phase_changed';
        IF NEW.started_at IS DISTINCT FROM OLD.started_at
           OR NEW.ended_at IS DISTINCT FROM OLD.ended_at THEN
            RAISE EXCEPTION 'After transition cannot rewrite Scene timestamps'
                USING ERRCODE = '55000';
        END IF;
    ELSIF NEW.phase = 'closed'
       AND NEW.status IN ('completed', 'abandoned', 'cancelled')
       AND ((OLD.phase = 'after' AND OLD.status = 'active')
            OR (OLD.phase = 'before' AND OLD.status = 'planned'
                AND NEW.status = 'cancelled')) THEN
        expected_lifecycle_event_type := 'SCENE_SESSION_ENDED';
        expected_action := 'ended';
        IF NEW.started_at IS DISTINCT FROM OLD.started_at
           OR OLD.ended_at IS NOT NULL
           OR NEW.ended_at IS DISTINCT FROM transaction_timestamp() THEN
            RAISE EXCEPTION 'Scene close timestamps must be database-authored'
                USING ERRCODE = '55000';
        END IF;
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
          AND event.session_id = NEW.opened_session_id
          AND event.causation_event_id = OLD.last_event_id
          AND event.payload->>'scene_session_id' = NEW.scene_session_id::text
          AND event.payload->>'scene_revision' = NEW.revision::text
          AND event.payload->>'action' = expected_action
          AND event.payload->>'phase' = NEW.phase
          AND event.payload->>'status' = NEW.status
          AND event.privacy_class = NEW.privacy_class
          AND event.memory_eligible = NEW.memory_eligible
          AND event.training_eligible = NEW.training_eligible
          AND event.cloud_eligible = NEW.cloud_eligible
          AND event.policy_version = NEW.policy_version
          AND event.policy_revision_id = NEW.policy_revision_id
          AND event.policy_decision_source = NEW.policy_decision_source
          AND event.policy_authorization_ref
                IS NOT DISTINCT FROM NEW.policy_authorization_ref
    ) THEN
        RAISE EXCEPTION 'Scene projection update lacks an exact lifecycle event'
            USING ERRCODE = '55000';
    END IF;

    expected_hash := havre.stage5_content_hash(
        havre.stage5_scene_session_material(NEW)
    );
    IF NEW.content_hash IS DISTINCT FROM expected_hash THEN
        RAISE EXCEPTION 'Scene projection update has a noncanonical content hash'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION havre.guard_intervention_decision_insert()
RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    current_scene havre.scene_sessions%ROWTYPE;
    expected_hash text;
    expected_evidence_count integer;
BEGIN
    SELECT * INTO current_scene
    FROM havre.scene_sessions
    WHERE owner_id = NEW.owner_id
      AND scene_session_id = NEW.scene_session_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Intervention Decision lacks an owner-qualified Scene'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.scene_revision <> current_scene.revision
       OR NEW.phase <> current_scene.phase
       OR NOT (
            (NEW.phase = 'before' AND current_scene.status = 'planned')
            OR (NEW.phase IN ('during', 'after') AND current_scene.status = 'active')
       ) THEN
        RAISE EXCEPTION 'Intervention Decision does not match current Scene state'
            USING ERRCODE = '55000';
    END IF;
    IF NOT havre.stage4_evidence_snapshot_is_exact(NEW.evidence_snapshot) THEN
        RAISE EXCEPTION 'Intervention Decision evidence snapshot is not exact'
            USING ERRCODE = '55000';
    END IF;
    expected_evidence_count := CASE WHEN NEW.phase = 'before' THEN 1 ELSE 2 END;
    IF jsonb_array_length(NEW.evidence_snapshot) <> expected_evidence_count
       OR NOT EXISTS (
            SELECT 1 FROM jsonb_array_elements(NEW.evidence_snapshot) AS evidence
            WHERE evidence->>'source_kind' = 'event'
              AND (evidence->>'source_id')::uuid = current_scene.created_event_id
              AND evidence->>'relation' = 'supports'
       ) OR (NEW.phase <> 'before' AND NOT EXISTS (
            SELECT 1 FROM jsonb_array_elements(NEW.evidence_snapshot) AS evidence
            WHERE evidence->>'source_kind' = 'event'
              AND (evidence->>'source_id')::uuid = NEW.input_event_id
              AND evidence->>'relation' = 'supports'
       )) THEN
        RAISE EXCEPTION 'Intervention Decision evidence does not bind exact Scene inputs'
            USING ERRCODE = '55000';
    END IF;
    IF (NEW.phase = 'during' AND NOT EXISTS (
            SELECT 1 FROM havre.scene_records AS input_record
            WHERE input_record.owner_id = NEW.owner_id
              AND input_record.scene_session_id = NEW.scene_session_id
              AND input_record.scene_record_id = NEW.input_record_id
              AND input_record.record_type = 'signal'
              AND input_record.phase = 'during'
              AND input_record.event_id = NEW.input_event_id
       )) OR (NEW.phase IN ('before', 'after') AND (
            NEW.input_record_id IS NOT NULL
            OR NEW.input_event_id <> CASE
                WHEN NEW.phase = 'before' THEN current_scene.created_event_id
                ELSE current_scene.last_event_id
            END
       )) THEN
        RAISE EXCEPTION 'Intervention Decision input does not match its Scene phase'
            USING ERRCODE = '55000';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM havre.events AS decision_event
        WHERE decision_event.owner_id = NEW.owner_id
          AND decision_event.event_id = NEW.decision_event_id
          AND decision_event.event_type = 'INTERVENTION_DECIDED'
          AND decision_event.scene_session_id = NEW.scene_session_id
          AND decision_event.session_id = current_scene.opened_session_id
          AND decision_event.trace_id = NEW.trace_id
          AND decision_event.causation_event_id = NEW.input_event_id
          AND decision_event.payload->>'scene_session_id' = NEW.scene_session_id::text
          AND decision_event.payload->>'intervention_decision_id' =
                NEW.intervention_decision_id::text
          AND decision_event.payload->>'input_record_id'
                IS NOT DISTINCT FROM NEW.input_record_id::text
          AND decision_event.payload->>'guidance_event_id' = NEW.guidance_event_id::text
          AND decision_event.payload->>'branch' = NEW.branch
          AND decision_event.payload->>'policy_version' = NEW.policy_version_id
          AND (decision_event.payload->>'outreach_authorized')::boolean = false
          AND (decision_event.payload->>'simulation_only')::boolean = true
          AND decision_event.privacy_class = NEW.privacy_class
          AND decision_event.memory_eligible = NEW.memory_eligible
          AND decision_event.training_eligible = NEW.training_eligible
          AND decision_event.cloud_eligible = NEW.cloud_eligible
          AND decision_event.policy_version = NEW.data_policy_version
          AND decision_event.policy_revision_id = NEW.policy_revision_id
          AND decision_event.policy_decision_source = NEW.policy_decision_source
          AND decision_event.policy_authorization_ref
                IS NOT DISTINCT FROM NEW.policy_authorization_ref
    ) OR NOT EXISTS (
        SELECT 1
        FROM havre.events AS guidance_event
        JOIN havre.events AS decision_event
          ON decision_event.owner_id = guidance_event.owner_id
         AND decision_event.event_id = NEW.decision_event_id
        WHERE guidance_event.owner_id = NEW.owner_id
          AND guidance_event.event_id = NEW.guidance_event_id
          AND guidance_event.event_type = 'ASSISTANT_MESSAGE'
          AND guidance_event.scene_session_id = NEW.scene_session_id
          AND guidance_event.session_id = current_scene.opened_session_id
          AND guidance_event.request_id = decision_event.request_id
          AND guidance_event.trace_id = NEW.trace_id
          AND guidance_event.causation_event_id = NEW.decision_event_id
          AND guidance_event.payload->>'interaction_mode' = 'scene_guidance'
          AND guidance_event.payload->>'intervention_decision_id' =
                NEW.intervention_decision_id::text
          AND guidance_event.payload->>'renderer_version' =
                'scene-guidance-template-v1'
          AND guidance_event.payload->>'status' = 'completed'
          AND guidance_event.payload->'content_parts' = jsonb_build_array(
                jsonb_build_object('type', 'text', 'text', NEW.guidance)
          )
          AND guidance_event.privacy_class = NEW.privacy_class
          AND guidance_event.memory_eligible = NEW.memory_eligible
          AND guidance_event.training_eligible = NEW.training_eligible
          AND guidance_event.cloud_eligible = NEW.cloud_eligible
          AND guidance_event.policy_version = NEW.data_policy_version
          AND guidance_event.policy_revision_id = NEW.policy_revision_id
          AND guidance_event.policy_decision_source = NEW.policy_decision_source
          AND guidance_event.policy_authorization_ref
                IS NOT DISTINCT FROM NEW.policy_authorization_ref
    ) THEN
        RAISE EXCEPTION 'Intervention Decision lacks exact decision/guidance events'
            USING ERRCODE = '55000';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM havre.identity_artifact_versions AS artifact
        WHERE artifact.owner_id = NEW.owner_id
          AND artifact.artifact_kind = 'constitution'
          AND artifact.artifact_version_id = NEW.constitution_version_id
    ) OR NOT EXISTS (
        SELECT 1 FROM havre.identity_artifact_versions AS artifact
        WHERE artifact.owner_id = NEW.owner_id
          AND artifact.artifact_kind = 'identity'
          AND artifact.artifact_version_id = NEW.identity_version_id
    ) OR NOT EXISTS (
        SELECT 1 FROM havre.identity_artifact_versions AS artifact
        WHERE artifact.owner_id = NEW.owner_id
          AND artifact.artifact_kind = 'values'
          AND artifact.artifact_version_id = NEW.values_version_id
    ) THEN
        RAISE EXCEPTION 'Intervention Decision references unapproved identity versions'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.required_constraints <> jsonb_build_array(
            'preserve_user_choice', 'no_shame_or_coercion',
            'do_not_treat_feeling_as_fact', 'do_not_optimize_engagement',
            'no_proactive_outreach_authority'
       ) OR NOT (CASE NEW.branch
            WHEN 'safety_first' THEN
                NEW.recommended_intervention = 'prioritize_safety_and_help'
                AND NEW.response_style = 'calm_direct'
                AND NEW.reason_codes = jsonb_build_array(
                    'danger_or_help_signal_overrides_action_pressure'
                )
            WHEN 'clarification' THEN
                NEW.recommended_intervention = 'clarify_before_pressure'
                AND NEW.response_style IN ('calm_direct', 'curious_reflective')
                AND NEW.reason_codes IN (
                    jsonb_build_array('unresolved_safety_defaults_to_clarification'),
                    jsonb_build_array('ambiguous_context_defaults_to_clarification')
                )
            WHEN 'recovery' THEN
                NEW.recommended_intervention = 'support_recovery_with_restart'
                AND NEW.response_style = 'supportive_recovery'
                AND NEW.reason_codes = jsonb_build_array(
                    'exhaustion_without_urgent_goal_prefers_recovery'
                )
            WHEN 'minimum_action' THEN
                NEW.recommended_intervention = 'smallest_viable_action'
                AND NEW.response_style = 'warm_firm'
                AND NEW.reason_codes = jsonb_build_array(
                    'low_danger_meaningful_goal_supports_minimum_action'
                )
            WHEN 'preparation' THEN
                NEW.recommended_intervention = 'prepare_with_user_owned_plan'
                AND NEW.response_style = 'warm_firm'
                AND NEW.reason_codes = jsonb_build_array(
                    'before_scene_prepares_without_catastrophizing'
                )
            WHEN 'reflection' THEN
                NEW.recommended_intervention = 'reflect_without_self_judgment'
                AND NEW.response_style = 'curious_reflective'
                AND NEW.reason_codes = jsonb_build_array(
                    'after_scene_prefers_evidence_and_adjustment'
                )
            ELSE false
       END) THEN
        RAISE EXCEPTION 'Intervention Decision violates the candidate policy contract'
            USING ERRCODE = '55000';
    END IF;
    expected_hash := havre.stage5_content_hash(
        havre.stage5_intervention_decision_material(NEW)
    );
    IF NEW.content_hash IS DISTINCT FROM expected_hash THEN
        RAISE EXCEPTION 'Intervention Decision has a noncanonical content hash'
            USING ERRCODE = '55000';
    END IF;
    NEW.created_at := statement_timestamp();
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION havre.guard_scene_record_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    current_scene havre.scene_sessions%ROWTYPE;
    predecessor havre.scene_records%ROWTYPE;
    expected_event_type text;
    expected_sequence integer;
    expected_hash text;
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
        SELECT * INTO predecessor FROM havre.scene_records
        WHERE owner_id = NEW.owner_id
          AND scene_session_id = NEW.scene_session_id
          AND scene_record_id = NEW.causal_predecessor_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Scene record lacks its owner-qualified predecessor'
                USING ERRCODE = '55000';
        END IF;
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
        WHERE event.owner_id = NEW.owner_id
          AND event.event_id = NEW.event_id
          AND event.event_type = expected_event_type
          AND event.scene_session_id = NEW.scene_session_id
          AND event.trace_id = NEW.trace_id
          AND event.payload->>'scene_session_id' = NEW.scene_session_id::text
          AND event.payload->>'scene_record_id' = NEW.scene_record_id::text
          AND event.privacy_class = NEW.privacy_class
          AND event.memory_eligible = NEW.memory_eligible
          AND event.training_eligible = NEW.training_eligible
          AND event.cloud_eligible = NEW.cloud_eligible
          AND event.policy_version = NEW.policy_version
          AND event.policy_revision_id = NEW.policy_revision_id
          AND event.policy_decision_source = NEW.policy_decision_source
          AND event.policy_authorization_ref
                IS NOT DISTINCT FROM NEW.policy_authorization_ref
          AND CASE NEW.record_type
              WHEN 'signal' THEN
                  event.causation_event_id = current_scene.last_event_id
                  AND (event.payload->>'occurred_at')::timestamptz = NEW.occurred_at
                  AND NEW.source = 'web_simulation'
                  AND NEW.content = jsonb_build_object(
                      'signal_type', event.payload->>'signal_type',
                      'danger', event.payload->>'danger',
                      'avoidance', event.payload->>'avoidance',
                      'energy', event.payload->>'energy',
                      'coercion', event.payload->>'coercion',
                      'goal_alignment', event.payload->>'goal_alignment',
                      'goal_urgency', event.payload->>'goal_urgency',
                      'input_method', event.payload->>'input_method'
                  )
              WHEN 'action' THEN
                  event.causation_event_id = predecessor.event_id
                  AND event.payload->>'intervention_record_id' =
                        predecessor.scene_record_id::text
                  AND (event.payload->>'occurred_at')::timestamptz = NEW.occurred_at
                  AND NEW.source = 'owner_self_report'
                  AND NEW.content = jsonb_build_object(
                      'action', event.payload->>'action',
                      'action_attempted', event.payload->>'action_attempted',
                      'reporter', event.payload->>'reporter'
                  )
              WHEN 'outcome' THEN
                  event.causation_event_id = predecessor.event_id
                  AND event.payload->>'action_record_id' =
                        predecessor.scene_record_id::text
                  AND (event.payload->>'occurred_at')::timestamptz = NEW.occurred_at
                  AND NEW.source = 'owner_self_report'
                  AND NEW.content = jsonb_build_object(
                      'outcome', event.payload->>'outcome',
                      'reporter', event.payload->>'reporter',
                      'observation_scope', event.payload->>'observation_scope'
                  )
              WHEN 'reflection' THEN
                  event.causation_event_id = predecessor.event_id
                  AND event.payload->>'outcome_record_id' =
                        predecessor.scene_record_id::text
                  AND event.recorded_at = NEW.occurred_at
                  AND NEW.source = 'owner_self_report'
                  AND NEW.content = jsonb_build_object(
                      'reflection', event.payload->>'reflection',
                      'next_adjustment', event.payload->'next_adjustment',
                      'outcome_observation_id',
                          event.payload->>'outcome_observation_id'
                  )
              ELSE true
          END
    ) THEN
        RAISE EXCEPTION 'Scene record event does not exactly match its durable record'
            USING ERRCODE = '55000';
    END IF;
    IF (NEW.record_type <> 'intervention' AND (
            NEW.assistant_event_id IS NOT NULL OR NEW.artifact_kind IS NOT NULL
            OR NEW.artifact_id IS NOT NULL OR NEW.artifact_revision IS NOT NULL
       )) OR (NEW.record_type = 'signal' AND (
            NEW.phase <> 'during' OR current_scene.phase <> 'during'
            OR current_scene.status <> 'active'
            OR NEW.causal_predecessor_id IS NOT NULL
       )) OR (NEW.record_type = 'intervention' AND (
            NEW.phase <> current_scene.phase
            OR NOT (
                (NEW.phase = 'before' AND current_scene.status = 'planned'
                 AND NEW.causal_predecessor_id IS NULL)
                OR (NEW.phase = 'during' AND current_scene.status = 'active'
                    AND predecessor.record_type = 'signal'
                    AND predecessor.phase = 'during')
                OR (NEW.phase = 'after' AND current_scene.status = 'active'
                    AND NEW.causal_predecessor_id IS NULL)
            )
       )) OR (NEW.record_type = 'action' AND (
            NEW.phase <> 'during' OR current_scene.phase <> 'during'
            OR current_scene.status <> 'active'
            OR predecessor.record_type <> 'intervention'
            OR predecessor.phase <> 'during'
       )) OR (NEW.record_type = 'outcome' AND (
            NEW.phase <> 'after' OR current_scene.phase <> 'after'
            OR current_scene.status <> 'active'
            OR predecessor.record_type <> 'action'
            OR predecessor.phase <> 'during'
       )) OR (NEW.record_type = 'reflection' AND (
            NEW.phase <> 'after' OR current_scene.phase <> 'after'
            OR current_scene.status <> 'active'
            OR predecessor.record_type <> 'outcome'
            OR predecessor.phase <> 'after'
       )) THEN
        RAISE EXCEPTION 'Scene record violates current phase or causal predecessor rules'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.record_type = 'intervention' AND NOT EXISTS (
        SELECT 1
        FROM havre.intervention_decisions AS decision
        JOIN havre.events AS decision_event
          ON decision_event.owner_id = decision.owner_id
         AND decision_event.event_id = decision.decision_event_id
        JOIN havre.events AS guidance_event
          ON guidance_event.owner_id = decision.owner_id
         AND guidance_event.event_id = decision.guidance_event_id
        WHERE decision.owner_id = NEW.owner_id
          AND decision.scene_session_id = NEW.scene_session_id
          AND decision.intervention_decision_id = NEW.artifact_id
          AND NEW.artifact_kind = 'intervention_decision'
          AND NEW.artifact_revision = 1
          AND decision.decision_event_id = NEW.event_id
          AND decision.guidance_event_id = NEW.assistant_event_id
          AND decision.input_record_id IS NOT DISTINCT FROM NEW.causal_predecessor_id
          AND decision.phase = NEW.phase
          AND decision.trace_id = NEW.trace_id
          AND decision_event.causation_event_id = decision.input_event_id
          AND decision_event.payload->>'scene_record_id' = NEW.scene_record_id::text
          AND guidance_event.causation_event_id = decision.decision_event_id
          AND guidance_event.payload->>'interaction_mode' = 'scene_guidance'
          AND guidance_event.payload->>'intervention_decision_id' =
                decision.intervention_decision_id::text
          AND guidance_event.payload->'content_parts' = jsonb_build_array(
                jsonb_build_object('type', 'text', 'text', decision.guidance)
          )
          AND NEW.content = jsonb_build_object(
                'branch', decision.branch,
                'recommended_intervention', decision.recommended_intervention,
                'guidance', decision.guidance,
                'minimum_action', decision.minimum_action,
                'reason_codes', decision.reason_codes,
                'outreach_authorized', decision.outreach_authorized,
                'simulation_only', decision.simulation_only
          )
    ) THEN
        RAISE EXCEPTION
            'intervention record does not bind one exact decision and visible guidance'
            USING ERRCODE = '55000';
    END IF;
    expected_hash := havre.stage5_content_hash(
        havre.stage5_scene_record_material(NEW)
    );
    IF NEW.content_hash IS DISTINCT FROM expected_hash THEN
        RAISE EXCEPTION 'Scene record has a noncanonical content hash'
            USING ERRCODE = '55000';
    END IF;
    NEW.recorded_at := statement_timestamp();
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION havre.guard_guidance_outcome_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    current_scene havre.scene_sessions%ROWTYPE;
    expected_hash text;
BEGIN
    SELECT * INTO current_scene FROM havre.scene_sessions
    WHERE owner_id = NEW.owner_id AND scene_session_id = NEW.scene_session_id
    FOR UPDATE;
    IF NOT FOUND OR current_scene.phase <> 'after'
       OR current_scene.status <> 'active' THEN
        RAISE EXCEPTION 'guidance outcome requires one active After Scene'
            USING ERRCODE = '55000';
    END IF;
    IF NOT havre.stage4_evidence_snapshot_is_exact(NEW.evidence_snapshot)
       OR jsonb_array_length(NEW.evidence_snapshot) <> 3
       OR NOT EXISTS (
            SELECT 1
            FROM havre.scene_records AS action_record
            JOIN havre.scene_records AS intervention_record
              ON intervention_record.owner_id = action_record.owner_id
             AND intervention_record.scene_session_id = action_record.scene_session_id
             AND intervention_record.scene_record_id = action_record.causal_predecessor_id
             AND intervention_record.record_type = 'intervention'
             AND intervention_record.phase = 'during'
            JOIN havre.scene_records AS outcome_record
              ON outcome_record.owner_id = action_record.owner_id
             AND outcome_record.scene_session_id = action_record.scene_session_id
             AND outcome_record.scene_record_id = NEW.outcome_record_id
             AND outcome_record.record_type = 'outcome'
             AND outcome_record.phase = 'after'
             AND outcome_record.causal_predecessor_id = action_record.scene_record_id
            JOIN havre.scene_records AS reflection_record
              ON reflection_record.owner_id = action_record.owner_id
             AND reflection_record.scene_session_id = action_record.scene_session_id
             AND reflection_record.scene_record_id = NEW.reflection_record_id
             AND reflection_record.record_type = 'reflection'
             AND reflection_record.phase = 'after'
             AND reflection_record.causal_predecessor_id = outcome_record.scene_record_id
            JOIN havre.intervention_decisions AS decision
              ON decision.owner_id = intervention_record.owner_id
             AND decision.scene_session_id = intervention_record.scene_session_id
             AND decision.intervention_decision_id = intervention_record.artifact_id
            JOIN havre.events AS reflection_event
              ON reflection_event.owner_id = reflection_record.owner_id
             AND reflection_event.event_id = reflection_record.event_id
            WHERE action_record.owner_id = NEW.owner_id
              AND action_record.scene_session_id = NEW.scene_session_id
              AND action_record.scene_record_id = NEW.action_record_id
              AND action_record.record_type = 'action'
              AND action_record.phase = 'during'
              AND decision.intervention_decision_id = NEW.intervention_decision_id
              AND decision.guidance_event_id = NEW.guidance_event_id
              AND NEW.action_attempted = action_record.content->>'action_attempted'
              AND NEW.observation_window_started_at = decision.created_at
              AND NEW.observation_window_ended_at = reflection_event.recorded_at
              AND NEW.created_event_id = reflection_event.event_id
              AND reflection_event.event_type = 'REFLECTION_CREATED'
              AND reflection_event.scene_session_id = NEW.scene_session_id
              AND reflection_event.trace_id = NEW.trace_id
              AND reflection_event.payload->>'outcome_observation_id' =
                    NEW.outcome_observation_id::text
       ) THEN
        RAISE EXCEPTION 'guidance outcome observation lacks exact Scene chain evidence'
            USING ERRCODE = '55000';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM jsonb_array_elements(NEW.evidence_snapshot) AS evidence
        JOIN havre.scene_records AS record
          ON record.owner_id = NEW.owner_id
         AND record.scene_session_id = NEW.scene_session_id
         AND record.scene_record_id = NEW.action_record_id
         AND record.event_id = (evidence->>'source_id')::uuid
        WHERE evidence->>'source_kind' = 'event'
          AND evidence->>'relation' = 'supports'
    ) OR NOT EXISTS (
        SELECT 1 FROM jsonb_array_elements(NEW.evidence_snapshot) AS evidence
        JOIN havre.scene_records AS record
          ON record.owner_id = NEW.owner_id
         AND record.scene_session_id = NEW.scene_session_id
         AND record.scene_record_id = NEW.outcome_record_id
         AND record.event_id = (evidence->>'source_id')::uuid
        WHERE evidence->>'source_kind' = 'event'
          AND evidence->>'relation' = 'supports'
    ) OR NOT EXISTS (
        SELECT 1 FROM jsonb_array_elements(NEW.evidence_snapshot) AS evidence
        WHERE evidence->>'source_kind' = 'event'
          AND (evidence->>'source_id')::uuid = NEW.created_event_id
          AND evidence->>'relation' = 'supports'
    ) THEN
        RAISE EXCEPTION 'guidance outcome snapshot does not contain the exact event chain'
            USING ERRCODE = '55000';
    END IF;
    expected_hash := havre.stage5_content_hash(
        havre.stage5_guidance_outcome_material(NEW)
    );
    IF NEW.content_hash IS DISTINCT FROM expected_hash THEN
        RAISE EXCEPTION 'guidance outcome has a noncanonical content hash'
            USING ERRCODE = '55000';
    END IF;
    NEW.created_at := statement_timestamp();
    RETURN NEW;
END;
$$;
