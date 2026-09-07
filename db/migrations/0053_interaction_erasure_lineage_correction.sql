-- Preserve the exact interaction terminal lineage introduced by migration
-- 0052 while admitting the two narrowly governed source-erasure transitions.

BEGIN;

CREATE OR REPLACE FUNCTION havre.guard_interaction_assistant_adoption()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    assistant_row havre.events%ROWTYPE;
    failure_row havre.events%ROWTYPE;
    context_row havre.context_packs%ROWTYPE;
    failure_stage text;
    privileged_erasure boolean;
BEGIN
    privileged_erasure :=
        current_setting('havre.privileged_erasure', true) = 'on'
        AND pg_has_role(current_user, 'havre_privileged_erasure', 'MEMBER');

    -- Phase A converts a processing or terminal interaction to the exact
    -- source-erasure tombstone.  Phase B clears only its USER_MESSAGE pointer
    -- immediately before the raw source Event is deleted.  Both preserve every
    -- other request identity field and require the role plus transaction flag.
    IF privileged_erasure
       AND OLD.request_kind = 'interaction'
       AND NEW.owner_id IS NOT DISTINCT FROM OLD.owner_id
       AND NEW.request_id IS NOT DISTINCT FROM OLD.request_id
       AND NEW.request_kind IS NOT DISTINCT FROM OLD.request_kind
       AND NEW.session_id IS NOT DISTINCT FROM OLD.session_id
       AND NEW.trace_id IS NOT DISTINCT FROM OLD.trace_id
       AND NEW.idempotency_key IS NOT DISTINCT FROM OLD.idempotency_key
       AND NEW.request_fingerprint IS NOT DISTINCT FROM OLD.request_fingerprint
       AND NEW.created_at IS NOT DISTINCT FROM OLD.created_at
       AND NEW.status = 'failed'
       AND NEW.assistant_event_id IS NULL
       AND NEW.failure_event_id IS NULL
       AND NEW.context_pack_id IS NULL
       AND NEW.inference_attempt_id IS NULL
       AND NEW.inference_response_id IS NULL
       AND NEW.error_code = 'source_erasure_propagated'
       AND (
           (
               NEW.user_event_id IS NOT DISTINCT FROM OLD.user_event_id
               AND (
                   (
                       OLD.completed_at IS NOT NULL
                       AND NEW.completed_at IS NOT DISTINCT FROM OLD.completed_at
                   )
                   OR (
                       OLD.completed_at IS NULL
                       AND NEW.completed_at IS NOT NULL
                   )
               )
           )
           OR (
               OLD.status = 'failed'
               AND OLD.error_code = 'source_erasure_propagated'
               AND OLD.assistant_event_id IS NULL
               AND OLD.failure_event_id IS NULL
               AND OLD.context_pack_id IS NULL
               AND OLD.inference_attempt_id IS NULL
               AND OLD.inference_response_id IS NULL
               AND OLD.completed_at IS NOT NULL
               AND NEW.completed_at IS NOT DISTINCT FROM OLD.completed_at
               AND NEW.user_event_id IS NULL
           )
       ) THEN
        RETURN NEW;
    END IF;

    IF OLD.request_kind = 'interaction'
       AND OLD.status IN ('completed', 'failed')
       AND (
           NEW.owner_id IS DISTINCT FROM OLD.owner_id
           OR NEW.request_id IS DISTINCT FROM OLD.request_id
           OR NEW.request_kind IS DISTINCT FROM OLD.request_kind
           OR NEW.status IS DISTINCT FROM OLD.status
           OR NEW.session_id IS DISTINCT FROM OLD.session_id
           OR NEW.trace_id IS DISTINCT FROM OLD.trace_id
           OR NEW.user_event_id IS DISTINCT FROM OLD.user_event_id
           OR NEW.assistant_event_id IS DISTINCT FROM OLD.assistant_event_id
           OR NEW.failure_event_id IS DISTINCT FROM OLD.failure_event_id
           OR NEW.context_pack_id IS DISTINCT FROM OLD.context_pack_id
           OR NEW.inference_attempt_id IS DISTINCT FROM OLD.inference_attempt_id
           OR NEW.inference_response_id IS DISTINCT FROM OLD.inference_response_id
           OR NEW.error_code IS DISTINCT FROM OLD.error_code
           OR NEW.completed_at IS DISTINCT FROM OLD.completed_at
       ) THEN
        RAISE EXCEPTION
            'terminal interaction request lineage is immutable'
            USING ERRCODE = '55000';
    END IF;

    IF NEW.request_kind <> 'interaction' THEN
        RETURN NEW;
    END IF;

    IF NEW.status = 'processing' THEN
        IF NEW.assistant_event_id IS NOT NULL
           OR NEW.failure_event_id IS NOT NULL
           OR NEW.context_pack_id IS NOT NULL
           OR NEW.inference_attempt_id IS NOT NULL
           OR NEW.inference_response_id IS NOT NULL
           OR NEW.error_code IS NOT NULL
           OR NEW.completed_at IS NOT NULL THEN
            RAISE EXCEPTION
                'processing interaction request cannot claim terminal lineage'
                USING ERRCODE = '55000';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.status = 'failed' THEN
        IF NEW.failure_event_id IS NULL
           OR NEW.assistant_event_id IS NOT NULL
           OR NEW.inference_response_id IS NOT NULL
           OR NEW.error_code IS NULL
           OR NEW.completed_at IS NULL THEN
            RAISE EXCEPTION
                'failed interaction request requires one exact failure Event'
                USING ERRCODE = '55000';
        END IF;
        SELECT *
        INTO failure_row
        FROM havre.events
        WHERE owner_id = NEW.owner_id
          AND request_id = NEW.request_id
          AND event_id = NEW.failure_event_id;
        IF NOT FOUND
           OR failure_row.event_type <> 'INTERACTION_FAILED'
           OR failure_row.trace_id IS DISTINCT FROM NEW.trace_id
           OR failure_row.session_id IS DISTINCT FROM NEW.session_id
           OR failure_row.causation_event_id IS DISTINCT FROM NEW.user_event_id
           OR failure_row.payload->>'failure_code'
              IS DISTINCT FROM NEW.error_code THEN
            RAISE EXCEPTION
                'interaction request cannot adopt a failure Event with different lineage'
                USING ERRCODE = '55000';
        END IF;

        failure_stage := failure_row.payload->>'failure_stage';
        IF failure_stage NOT IN (
            'context_build',
            'capability_check',
            'routing',
            'version_check',
            'inference'
        ) THEN
            RAISE EXCEPTION
                'interaction request cannot adopt an invalid failure stage'
                USING ERRCODE = '55000';
        END IF;
        IF failure_stage = 'context_build' THEN
            IF NEW.context_pack_id IS NOT NULL
               OR NEW.inference_attempt_id IS NOT NULL
               OR failure_row.payload->>'context_pack_id' IS NOT NULL
               OR failure_row.payload->>'route_decision_id' IS NOT NULL
               OR failure_row.payload->>'inference_request_id' IS NOT NULL THEN
                RAISE EXCEPTION
                    'context-build failure request claims later lineage'
                    USING ERRCODE = '55000';
            END IF;
        ELSE
            IF NEW.context_pack_id IS NULL
               OR failure_row.payload->>'context_pack_id'
                  IS DISTINCT FROM NEW.context_pack_id::text THEN
                RAISE EXCEPTION
                    'failed interaction request does not adopt its exact ContextPack'
                    USING ERRCODE = '55000';
            END IF;
            IF failure_stage IN (
                'capability_check', 'routing', 'version_check'
            ) AND NEW.inference_attempt_id IS NOT NULL THEN
                RAISE EXCEPTION
                    'pre-inference failure request cannot claim an attempt'
                    USING ERRCODE = '55000';
            END IF;
            IF failure_stage = 'inference' AND (
                NEW.inference_attempt_id IS NULL
                OR NOT EXISTS (
                    SELECT 1
                    FROM havre.inference_attempts
                    WHERE owner_id = NEW.owner_id
                      AND request_id = NEW.request_id
                      AND trace_id = NEW.trace_id
                      AND context_pack_id = NEW.context_pack_id
                      AND inference_attempt_id = NEW.inference_attempt_id
                      AND inference_request_id::text =
                          failure_row.payload->>'inference_request_id'
                      AND status = 'failed'
                )
            ) THEN
                RAISE EXCEPTION
                    'inference failure request does not adopt its exact failed attempt'
                    USING ERRCODE = '55000';
            END IF;
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.assistant_event_id IS NULL
       OR NEW.failure_event_id IS NOT NULL
       OR NEW.error_code IS NOT NULL
       OR NEW.completed_at IS NULL THEN
        RAISE EXCEPTION
            'completed interaction request requires one exact assistant Event'
            USING ERRCODE = '55000';
    END IF;

    SELECT *
    INTO assistant_row
    FROM havre.events
    WHERE owner_id = NEW.owner_id
      AND request_id = NEW.request_id
      AND event_id = NEW.assistant_event_id;
    IF NOT FOUND
       OR assistant_row.event_type <> 'ASSISTANT_MESSAGE'
       OR assistant_row.trace_id IS DISTINCT FROM NEW.trace_id
       OR assistant_row.session_id IS DISTINCT FROM NEW.session_id
       OR assistant_row.causation_event_id IS DISTINCT FROM NEW.user_event_id THEN
        RAISE EXCEPTION
            'interaction request cannot adopt an assistant Event with different lineage'
            USING ERRCODE = '55000';
    END IF;

    IF NEW.status <> 'completed'
       OR NEW.context_pack_id IS NULL
       OR NEW.inference_attempt_id IS NULL
       OR NEW.inference_response_id IS NULL
       OR NOT (assistant_row.payload ? 'context_pack_id')
       OR NOT (assistant_row.payload ? 'inference_response_id')
       OR jsonb_typeof(assistant_row.payload->'context_pack_id') <> 'string'
       OR jsonb_typeof(assistant_row.payload->'inference_response_id') <> 'string'
       OR assistant_row.payload->>'context_pack_id'
          IS DISTINCT FROM NEW.context_pack_id::text
       OR assistant_row.payload->>'inference_response_id'
          IS DISTINCT FROM NEW.inference_response_id::text THEN
        RAISE EXCEPTION
            'interaction request cannot adopt an incomplete assistant lineage'
            USING ERRCODE = '55000';
    END IF;

    SELECT *
    INTO context_row
    FROM havre.context_packs
    WHERE owner_id = NEW.owner_id
      AND request_id = NEW.request_id
      AND trace_id = NEW.trace_id
      AND context_pack_id = NEW.context_pack_id;
    IF NOT FOUND OR NOT EXISTS (
        SELECT 1
        FROM havre.inference_attempts
        WHERE owner_id = NEW.owner_id
          AND request_id = NEW.request_id
          AND trace_id = NEW.trace_id
          AND context_pack_id = NEW.context_pack_id
          AND inference_attempt_id = NEW.inference_attempt_id
          AND inference_response_id = NEW.inference_response_id
          AND status = 'completed'
    ) THEN
        RAISE EXCEPTION
            'interaction request cannot adopt an assistant Event without its exact completed inference'
            USING ERRCODE = '55000';
    END IF;

    IF assistant_row.privacy_class
          IS DISTINCT FROM context_row.effective_privacy_class
       OR assistant_row.memory_eligible
          IS DISTINCT FROM context_row.effective_memory_eligible
       OR assistant_row.training_eligible
          IS DISTINCT FROM context_row.effective_training_eligible
       OR assistant_row.cloud_eligible
          IS DISTINCT FROM context_row.effective_cloud_eligible
       OR assistant_row.policy_version
          IS DISTINCT FROM context_row.effective_policy_version
       OR assistant_row.policy_revision_id
          IS DISTINCT FROM context_row.effective_policy_revision_id THEN
        RAISE EXCEPTION
            'interaction request cannot adopt an assistant Event with different policy'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

-- Migration 0052 used ordinary inequality for a few jsonb type checks. Missing
-- keys therefore produced SQL NULL rather than TRUE. Close that three-valued
-- logic gap before the broader 0052 lineage trigger runs.
CREATE FUNCTION havre.guard_interaction_terminal_required_keys_v2()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    request_kind text;
    failure_stage text;
BEGIN
    SELECT request.request_kind
    INTO request_kind
    FROM havre.interaction_requests AS request
    WHERE request.owner_id = NEW.owner_id
      AND request.request_id = NEW.request_id;
    IF NOT FOUND OR request_kind <> 'interaction' THEN
        RETURN NEW;
    END IF;

    IF NEW.event_type = 'ASSISTANT_MESSAGE' THEN
        IF jsonb_typeof(NEW.payload->'policy_decision_id')
              IS DISTINCT FROM 'string'
           OR jsonb_typeof(NEW.payload->'response_policy_decision')
              IS DISTINCT FROM 'object'
           OR jsonb_typeof(
               NEW.payload->'response_policy_decision'->'decision_id'
           ) IS DISTINCT FROM 'string' THEN
            RAISE EXCEPTION
                'interaction assistant Event requires exact response policy IDs'
                USING ERRCODE = '55000';
        END IF;
        RETURN NEW;
    END IF;

    failure_stage := NEW.payload->>'failure_stage';
    IF failure_stage IN ('version_check', 'inference')
       AND (
           jsonb_typeof(NEW.payload->'route_decision_id')
              IS DISTINCT FROM 'string'
           OR jsonb_typeof(NEW.payload->'inference_request_id')
              IS DISTINCT FROM 'string'
       ) THEN
        RAISE EXCEPTION
            'routed failure requires exact route and inference request IDs'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER interaction_terminal_events_require_complete_keys_v2
BEFORE INSERT ON havre.events
FOR EACH ROW
WHEN (
    NEW.event_type = 'INTERACTION_FAILED'
    OR NEW.event_type = 'ASSISTANT_MESSAGE'
)
EXECUTE FUNCTION havre.guard_interaction_terminal_required_keys_v2();

-- Repository reservation is the sole birth shape for an ordinary interaction:
-- it starts processing with no Event or derived/terminal pointer.  Later
-- statements adopt the USER_MESSAGE and eventually one terminal Event.  Do not
-- let direct SQL bypass the UPDATE guards by inserting a pre-terminalized row.
CREATE FUNCTION havre.guard_interaction_request_insert_v2()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.request_kind = 'interaction'
       AND (
           NEW.status <> 'processing'
           OR NEW.user_event_id IS NOT NULL
           OR NEW.assistant_event_id IS NOT NULL
           OR NEW.failure_event_id IS NOT NULL
           OR NEW.context_pack_id IS NOT NULL
           OR NEW.inference_attempt_id IS NOT NULL
           OR NEW.inference_response_id IS NOT NULL
           OR NEW.error_code IS NOT NULL
           OR NEW.completed_at IS NOT NULL
       ) THEN
        RAISE EXCEPTION
            'interaction request must begin in canonical processing shape'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER interaction_requests_require_processing_insert_v2
BEFORE INSERT ON havre.interaction_requests
FOR EACH ROW EXECUTE FUNCTION havre.guard_interaction_request_insert_v2();

-- A populated database may contain pre-0052 mark_failed rows with no durable
-- failure Event. They are not trustworthy lineage and must stop the upgrade.
-- The one intentional exception is the exact source-erasure tombstone, whose
-- derived pointers and terminal Events were deliberately removed.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM havre.interaction_requests AS request
        LEFT JOIN havre.events AS failure
          ON failure.owner_id = request.owner_id
         AND failure.request_id = request.request_id
         AND failure.event_id = request.failure_event_id
        WHERE request.request_kind = 'interaction'
          AND (
              request.status = 'failed'
              OR request.failure_event_id IS NOT NULL
          )
          AND NOT (
              request.status = 'failed'
              AND request.error_code = 'source_erasure_propagated'
              AND request.assistant_event_id IS NULL
              AND request.failure_event_id IS NULL
              AND request.context_pack_id IS NULL
              AND request.inference_attempt_id IS NULL
              AND request.inference_response_id IS NULL
              AND request.completed_at IS NOT NULL
          )
          AND (
              request.status <> 'failed'
              OR request.failure_event_id IS NULL
              OR request.assistant_event_id IS NOT NULL
              OR request.inference_response_id IS NOT NULL
              OR request.error_code IS NULL
              OR request.completed_at IS NULL
              OR failure.event_id IS NULL
              OR failure.event_type <> 'INTERACTION_FAILED'
              OR failure.trace_id IS DISTINCT FROM request.trace_id
              OR failure.session_id IS DISTINCT FROM request.session_id
              OR failure.causation_event_id
                 IS DISTINCT FROM request.user_event_id
              OR failure.payload->>'failure_code'
                 IS DISTINCT FROM request.error_code
          )
    ) THEN
        RAISE EXCEPTION 'existing failed interaction request violates 0053'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

COMMIT;
