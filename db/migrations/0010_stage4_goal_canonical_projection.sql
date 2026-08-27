-- Stage 4 Goal canonical projection completeness correction.
--
-- This migration is intentionally additive. Migrations 0001-0009 are an
-- immutable historical snapshot and may already be installed. Stage 5 and
-- proactive runtime remain inactive.

-- Reconstruct the one canonical JSON representation from the database-
-- validated Goal projection. This function never accepts caller-provided
-- JSON or a caller-provided digest.
CREATE FUNCTION havre.canonical_goal_projection(goal_row havre.goals)
RETURNS text
LANGUAGE sql
STABLE
STRICT
AS $$
    SELECT
        '{"data_policy":{' ||
        '"authorization_ref":' ||
            COALESCE(to_json(goal_row.policy_authorization_ref)::text, 'null') ||
        ',"cloud_eligible":' || goal_row.cloud_eligible::text ||
        ',"decision_source":' ||
            to_json(goal_row.policy_decision_source)::text ||
        ',"memory_eligible":' || goal_row.memory_eligible::text ||
        ',"policy_revision_id":' ||
            to_json(goal_row.policy_revision_id::text)::text ||
        ',"policy_version":' || to_json(goal_row.policy_version)::text ||
        ',"privacy_class":' || to_json(goal_row.privacy_class)::text ||
        ',"schema_version":1' ||
        ',"training_eligible":' || goal_row.training_eligible::text ||
        '},"goal_id":' || to_json(goal_row.goal_id::text)::text ||
        ',"last_event_id":' || to_json(goal_row.last_event_id::text)::text ||
        ',"next_action":' ||
            COALESCE(to_json(goal_row.next_action)::text, 'null') ||
        ',"owner_id":' || to_json(goal_row.owner_id::text)::text ||
        ',"priority":' || to_json(goal_row.priority)::text ||
        ',"review_at":' ||
            CASE
                WHEN goal_row.review_at IS NULL THEN 'null'
                ELSE to_json(
                    to_char(
                        goal_row.review_at AT TIME ZONE 'UTC',
                        'YYYY-MM-DD"T"HH24:MI:SS'
                    ) ||
                    CASE
                        WHEN to_char(
                            goal_row.review_at AT TIME ZONE 'UTC', 'US'
                        ) = '000000' THEN ''
                        ELSE '.' || to_char(
                            goal_row.review_at AT TIME ZONE 'UTC', 'US'
                        )
                    END || 'Z'
                )::text
            END ||
        ',"revision":' || goal_row.revision::text ||
        ',"schema_version":' || goal_row.schema_version::text ||
        ',"status":' || to_json(goal_row.status)::text ||
        ',"title":' || to_json(goal_row.title)::text ||
        ',"track":' || to_json(goal_row.track)::text ||
        ',"why":' || to_json(goal_row.why)::text ||
        '}'
$$;

-- Replace the active Goal guard without changing the historical definitions
-- installed by 0007-0009. The exact top-level and nested key sets are checked
-- before the caller's string is compared byte-for-byte with the database-
-- reconstructed canonical material.
CREATE OR REPLACE FUNCTION havre.guard_goal_projection_update() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    expected_event_type text;
    expected_action text;
    lifecycle_event record;
    supplied_canonical text;
    projection jsonb;
    projection_keys text[];
    policy_keys text[];
    database_canonical text;
    expected_hash text;
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

    supplied_canonical :=
        lifecycle_event.payload->>'projection_canonical_json';
    BEGIN
        projection := supplied_canonical::jsonb;
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION
            'goal projection guard: lifecycle projection material is invalid JSON'
            USING ERRCODE = '55000';
    END;

    IF jsonb_typeof(projection) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION
            'goal projection guard: lifecycle projection material violates the exact contract'
            USING ERRCODE = '55000';
    END IF;

    SELECT array_agg(key ORDER BY key) INTO projection_keys
    FROM jsonb_object_keys(projection) AS keys(key);
    IF projection_keys IS DISTINCT FROM ARRAY[
        'data_policy', 'goal_id', 'last_event_id', 'next_action', 'owner_id',
        'priority', 'review_at', 'revision', 'schema_version', 'status',
        'title', 'track', 'why'
    ]::text[]
       OR jsonb_typeof(projection->'data_policy') IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION
            'goal projection guard: lifecycle projection material violates the exact contract'
            USING ERRCODE = '55000';
    END IF;

    SELECT array_agg(key ORDER BY key) INTO policy_keys
    FROM jsonb_object_keys(projection->'data_policy') AS keys(key);
    IF policy_keys IS DISTINCT FROM ARRAY[
        'authorization_ref', 'cloud_eligible', 'decision_source',
        'memory_eligible', 'policy_revision_id', 'policy_version',
        'privacy_class', 'schema_version', 'training_eligible'
    ]::text[] THEN
        RAISE EXCEPTION
            'goal projection guard: lifecycle projection material violates the exact contract'
            USING ERRCODE = '55000';
    END IF;

    database_canonical := havre.canonical_goal_projection(NEW);
    IF supplied_canonical IS DISTINCT FROM database_canonical THEN
        RAISE EXCEPTION
            'goal projection guard: lifecycle projection is not the unique canonical serialization'
            USING ERRCODE = '55000';
    END IF;

    expected_hash := 'sha256:' || encode(
        sha256(convert_to(database_canonical, 'UTF8')), 'hex'
    );
    IF lifecycle_event.payload->>'projection_content_hash'
            IS DISTINCT FROM expected_hash
       OR NEW.content_hash IS DISTINCT FROM expected_hash THEN
        RAISE EXCEPTION
            'goal projection guard: content hash is not bound to the full lifecycle projection'
            USING ERRCODE = '55000';
    END IF;

    RETURN NEW;
END;
$$;
