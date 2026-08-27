-- Stage 4 Goal initial-projection integrity correction.
--
-- This migration is intentionally additive. Migrations 0001-0010 are an
-- immutable historical snapshot and may already be installed. Stage 5 and
-- proactive runtime remain inactive.

CREATE FUNCTION havre.guard_goal_projection_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    lifecycle_event record;
    supplied_canonical text;
    projection jsonb;
    projection_keys text[];
    policy_keys text[];
    database_canonical text;
    expected_hash text;
BEGIN
    IF NEW.revision <> 1 OR NEW.status <> 'active' THEN
        RAISE EXCEPTION
            'goal projection insert guard: initial projection must be active revision 1'
            USING ERRCODE = '55000';
    END IF;

    -- The database authors both initial projection timestamps. Caller values
    -- cannot forge the durable creation/update time.
    NEW.created_at := statement_timestamp();
    NEW.updated_at := statement_timestamp();

    BEGIN
        SELECT event.* INTO lifecycle_event
        FROM havre.events AS event
        WHERE event.owner_id = NEW.owner_id
          AND event.event_id = NEW.last_event_id
          AND event.event_type = 'GOAL_CREATED'
          AND event.causation_event_id IS NOT NULL
          AND EXISTS (
                SELECT 1
                FROM havre.events AS source_event
                WHERE source_event.owner_id = NEW.owner_id
                  AND source_event.event_id = event.causation_event_id
          )
          AND event.payload->>'goal_id' = NEW.goal_id::text
          AND event.payload->>'goal_revision' = '1'
          AND event.payload->>'action' = 'created'
          AND event.payload->>'track' = NEW.track
          AND event.payload->>'title' = NEW.title
          AND event.payload->>'why' = NEW.why
          AND event.payload->>'priority' = NEW.priority
          AND event.payload->>'status' = 'active'
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
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION
            'goal projection insert guard: lifecycle event payload is invalid'
            USING ERRCODE = '55000';
    END;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'goal projection insert guard: insert lacks one exact immutable GOAL_CREATED event'
            USING ERRCODE = '55000';
    END IF;

    supplied_canonical :=
        lifecycle_event.payload->>'projection_canonical_json';
    BEGIN
        projection := supplied_canonical::jsonb;
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION
            'goal projection insert guard: lifecycle projection material is invalid JSON'
            USING ERRCODE = '55000';
    END;

    IF jsonb_typeof(projection) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION
            'goal projection insert guard: lifecycle projection material violates the exact contract'
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
            'goal projection insert guard: lifecycle projection material violates the exact contract'
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
            'goal projection insert guard: lifecycle projection material violates the exact contract'
            USING ERRCODE = '55000';
    END IF;

    database_canonical := havre.canonical_goal_projection(NEW);
    IF supplied_canonical IS DISTINCT FROM database_canonical THEN
        RAISE EXCEPTION
            'goal projection insert guard: lifecycle projection is not the unique canonical serialization'
            USING ERRCODE = '55000';
    END IF;

    expected_hash := 'sha256:' || encode(
        sha256(convert_to(database_canonical, 'UTF8')), 'hex'
    );
    IF lifecycle_event.payload->>'projection_content_hash'
            IS DISTINCT FROM expected_hash
       OR NEW.content_hash IS DISTINCT FROM expected_hash THEN
        RAISE EXCEPTION
            'goal projection insert guard: content hash is not bound to the full lifecycle projection'
            USING ERRCODE = '55000';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER goals_are_insert_guarded
BEFORE INSERT ON havre.goals
FOR EACH ROW EXECUTE FUNCTION havre.guard_goal_projection_insert();
