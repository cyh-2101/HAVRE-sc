-- Bind the daily interaction artifacts to one exact durable lineage. Existing
-- owner-qualified foreign keys prove that referenced rows exist; these guards
-- additionally prove that policy, provider, model, adapter, and terminal Event
-- facts agree across those rows.

BEGIN;

CREATE FUNCTION havre.guard_route_decision_context_lineage()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    context_policy_revision_id uuid;
BEGIN
    SELECT effective_policy_revision_id
    INTO context_policy_revision_id
    FROM havre.context_packs
    WHERE owner_id = NEW.owner_id
      AND request_id = NEW.request_id
      AND trace_id = NEW.trace_id;

    IF NOT FOUND
       OR NEW.effective_policy_revision_id IS DISTINCT FROM context_policy_revision_id THEN
        RAISE EXCEPTION
            'route decision does not match its exact ContextPack policy lineage'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER route_decisions_require_exact_context_lineage
BEFORE INSERT ON havre.route_decisions
FOR EACH ROW EXECUTE FUNCTION havre.guard_route_decision_context_lineage();

CREATE FUNCTION havre.guard_inference_attempt_lineage()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    route_row havre.route_decisions%ROWTYPE;
    context_policy_revision_id uuid;
    attestation jsonb;
BEGIN
    SELECT *
    INTO route_row
    FROM havre.route_decisions
    WHERE owner_id = NEW.owner_id
      AND request_id = NEW.request_id
      AND trace_id = NEW.trace_id
      AND route_decision_id = NEW.route_decision_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION
            'inference attempt does not reference its exact route'
            USING ERRCODE = '55000';
    END IF;

    SELECT effective_policy_revision_id
    INTO context_policy_revision_id
    FROM havre.context_packs
    WHERE owner_id = NEW.owner_id
      AND request_id = NEW.request_id
      AND trace_id = NEW.trace_id
      AND context_pack_id = NEW.context_pack_id;
    IF NOT FOUND
       OR route_row.effective_policy_revision_id
          IS DISTINCT FROM context_policy_revision_id THEN
        RAISE EXCEPTION
            'inference attempt route does not match its ContextPack policy'
            USING ERRCODE = '55000';
    END IF;

    IF NEW.provider_id IS DISTINCT FROM route_row.selected_provider_id
       OR NEW.model_version_id
          IS DISTINCT FROM route_row.selected_model_version_id THEN
        RAISE EXCEPTION
            'inference attempt provider or model does not match its route'
            USING ERRCODE = '55000';
    END IF;
    IF (NEW.provider_class = 'cloud' AND route_row.execution_environment <> 'cloud')
       OR (NEW.provider_class <> 'cloud'
           AND route_row.execution_environment <> 'local') THEN
        RAISE EXCEPTION
            'inference attempt provider class does not match route environment'
            USING ERRCODE = '55000';
    END IF;

    IF NEW.provider_class = 'self_hosted'
       AND NEW.runtime_attestation_contract_version = 1 THEN
        SELECT stored.attestation
        INTO attestation
        FROM havre.runtime_attestations AS stored
        WHERE stored.runtime_attestation_id = NEW.runtime_attestation_id
          AND stored.attestation_hash = NEW.runtime_attestation_hash;
        IF NOT FOUND THEN
            RAISE EXCEPTION
                'self-hosted inference attempt lacks its exact runtime attestation'
                USING ERRCODE = '55000';
        END IF;
        IF NEW.model_version_id
              IS DISTINCT FROM attestation->>'model_version_id'
           OR NEW.adapter_version_id
              IS DISTINCT FROM attestation->>'active_adapter_version_id'
           OR NEW.tokenizer_version_id
              IS DISTINCT FROM attestation->>'tokenizer_version_id'
           OR NEW.serving_config_version
              IS DISTINCT FROM attestation->>'serving_config_version'
           OR NEW.serving_engine
              IS DISTINCT FROM attestation->>'serving_engine'
           OR NEW.serving_engine_version
              IS DISTINCT FROM attestation->>'serving_engine_version'
           OR NEW.model_artifact_hash
              IS DISTINCT FROM attestation->>'model_artifact_hash' THEN
            RAISE EXCEPTION
                'self-hosted inference attempt does not match runtime attestation'
                USING ERRCODE = '55000';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER inference_attempts_require_exact_lineage
BEFORE INSERT ON havre.inference_attempts
FOR EACH ROW EXECUTE FUNCTION havre.guard_inference_attempt_lineage();

CREATE FUNCTION havre.guard_interaction_terminal_event_lineage()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    request_row havre.interaction_requests%ROWTYPE;
    context_row havre.context_packs%ROWTYPE;
    attempt_row havre.inference_attempts%ROWTYPE;
    failure_stage text;
    referenced_id uuid;
    decision jsonb;
    delivered_hash text;
    decision_hash text;
BEGIN
    SELECT *
    INTO request_row
    FROM havre.interaction_requests
    WHERE owner_id = NEW.owner_id
      AND request_id = NEW.request_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'terminal Event lacks its durable request'
            USING ERRCODE = '55000';
    END IF;

    -- ASSISTANT_MESSAGE is also used by proactive and Scene flows.  Apply this
    -- interaction contract when the durable request says interaction, when an
    -- interaction key is present, or when an ordinary ContextPack already
    -- exists.  This preserves the separately governed proactive/Scene shapes
    -- while preventing a normal reply from bypassing the guard by omitting one
    -- or both payload keys.
    IF NEW.event_type = 'ASSISTANT_MESSAGE'
       AND request_row.request_kind <> 'interaction'
       AND NOT (NEW.payload ? 'context_pack_id')
       AND NOT (NEW.payload ? 'inference_response_id')
       AND NOT EXISTS (
            SELECT 1
            FROM havre.context_packs
            WHERE owner_id = NEW.owner_id
              AND request_id = NEW.request_id
              AND trace_id = NEW.trace_id
       ) THEN
        RETURN NEW;
    END IF;

    IF request_row.request_kind <> 'interaction' THEN
        RAISE EXCEPTION
            'interaction-shaped terminal Event requires an interaction request'
            USING ERRCODE = '55000';
    END IF;
    IF request_row.status <> 'processing'
       OR request_row.assistant_event_id IS NOT NULL
       OR request_row.failure_event_id IS NOT NULL
       OR EXISTS (
            SELECT 1
            FROM havre.events AS terminal
            WHERE terminal.owner_id = NEW.owner_id
              AND terminal.request_id = NEW.request_id
              AND terminal.event_type IN (
                  'ASSISTANT_MESSAGE',
                  'INTERACTION_FAILED'
              )
       ) THEN
        RAISE EXCEPTION
            'interaction request already has or cannot accept a terminal Event'
            USING ERRCODE = '55000';
    END IF;

    IF NEW.trace_id IS DISTINCT FROM request_row.trace_id
       OR NEW.session_id IS DISTINCT FROM request_row.session_id
       OR NEW.causation_event_id IS DISTINCT FROM request_row.user_event_id THEN
        RAISE EXCEPTION
            'terminal interaction Event does not match its durable request'
            USING ERRCODE = '55000';
    END IF;

    IF NEW.event_type = 'ASSISTANT_MESSAGE' THEN
        IF NOT (NEW.payload ? 'context_pack_id')
           OR NOT (NEW.payload ? 'inference_response_id')
           OR jsonb_typeof(NEW.payload->'context_pack_id') <> 'string'
           OR jsonb_typeof(NEW.payload->'inference_response_id') <> 'string'
           OR NEW.payload->>'context_pack_id' !~* (
               '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-'
               '[0-9a-f]{4}-[0-9a-f]{12}$'
           )
           OR NEW.payload->>'inference_response_id' !~* (
               '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-'
               '[0-9a-f]{4}-[0-9a-f]{12}$'
           ) THEN
            RAISE EXCEPTION
                'interaction assistant Event requires exact ContextPack and inference response references'
                USING ERRCODE = '55000';
        END IF;
        referenced_id := (NEW.payload->>'context_pack_id')::uuid;
        SELECT *
        INTO context_row
        FROM havre.context_packs
        WHERE owner_id = NEW.owner_id
          AND request_id = NEW.request_id
          AND trace_id = NEW.trace_id
          AND context_pack_id = referenced_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION
                'assistant Event does not reference its exact ContextPack'
                USING ERRCODE = '55000';
        END IF;
        SELECT *
        INTO attempt_row
        FROM havre.inference_attempts
            WHERE owner_id = NEW.owner_id
              AND request_id = NEW.request_id
              AND trace_id = NEW.trace_id
              AND context_pack_id = context_row.context_pack_id
              AND inference_response_id =
                    (NEW.payload->>'inference_response_id')::uuid
              AND status = 'completed';
        IF NOT FOUND THEN
            RAISE EXCEPTION
                'assistant Event does not reference its completed inference response'
                USING ERRCODE = '55000';
        END IF;

        -- The response reference alone is insufficient: a direct SQL writer
        -- must not reuse a genuine inference response while changing the text
        -- made visible to the owner or forging the Core policy decision.
        decision := NEW.payload->'response_policy_decision';
        delivered_hash := 'sha256:' || encode(public.digest(
            convert_to(
                havre.canonical_jsonb(NEW.payload->'content_parts'),
                'UTF8'
            ),
            'sha256'
        ), 'hex');
        decision_hash := CASE
            WHEN jsonb_typeof(decision) = 'object' THEN
                'sha256:' || encode(public.digest(
                    convert_to(
                        havre.canonical_jsonb(
                            decision - 'content_hash' - 'created_at'
                        ),
                        'UTF8'
                    ),
                    'sha256'
                ), 'hex')
            ELSE NULL
        END;
        IF jsonb_typeof(NEW.payload->'policy_decision_id') <> 'string'
           OR jsonb_typeof(decision) <> 'object'
           OR NEW.payload->>'policy_decision_id'
              IS DISTINCT FROM decision->>'decision_id'
           OR decision->>'decision_id' !~* (
               '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-'
               '[0-9a-f]{4}-[0-9a-f]{12}$'
           )
           OR decision->>'schema_version' IS DISTINCT FROM '1'
           OR decision->>'policy_version'
              IS DISTINCT FROM 'core-response-policy-v1'
           OR decision->>'request_id' IS DISTINCT FROM NEW.request_id::text
           OR decision->>'trace_id' IS DISTINCT FROM NEW.trace_id
           OR decision->>'context_pack_id'
              IS DISTINCT FROM context_row.context_pack_id::text
           OR decision->>'inference_response_id'
              IS DISTINCT FROM attempt_row.inference_response_id::text
           OR decision->>'raw_output_content_hash'
              IS DISTINCT FROM attempt_row.output_content_hash
           OR decision->>'delivered_output_content_hash'
              IS DISTINCT FROM delivered_hash
           OR decision->>'content_hash' IS DISTINCT FROM decision_hash
           OR COALESCE(
               decision->>'action' NOT IN ('pass_through', 'replace'),
               true
           )
           OR COALESCE(
               decision->>'category' NOT IN (
                   'ordinary',
                   'memory_truth',
                   'urgent_safety',
                   'system_confidentiality',
                   'exact_structured_output',
                   'privacy_tool_boundary'
               ),
               true
           )
           OR (
               decision->>'action' = 'pass_through'
               AND (
                   decision->>'category' <> 'ordinary'
                   OR decision->>'raw_output_content_hash'
                      IS DISTINCT FROM decision->>'delivered_output_content_hash'
               )
           )
           OR (
               decision->>'action' = 'replace'
               AND decision->>'category' = 'ordinary'
           ) THEN
            RAISE EXCEPTION
                'assistant Event does not match its durable response policy decision'
                USING ERRCODE = '55000';
        END IF;
    ELSE
        failure_stage := NEW.payload->>'failure_stage';
        IF failure_stage IS NULL OR failure_stage NOT IN (
            'context_build',
            'capability_check',
            'routing',
            'version_check',
            'inference'
        ) THEN
            RAISE EXCEPTION
                'interaction failure Event has an invalid failure stage'
                USING ERRCODE = '55000';
        END IF;
        IF failure_stage = 'context_build' THEN
            IF NEW.payload->>'context_pack_id' IS NOT NULL
               OR NEW.payload->>'route_decision_id' IS NOT NULL
               OR NEW.payload->>'inference_request_id' IS NOT NULL THEN
                RAISE EXCEPTION
                    'context-build failure cannot claim context, route, or inference lineage'
                    USING ERRCODE = '55000';
            END IF;
            IF EXISTS (
                SELECT 1 FROM havre.context_packs
                WHERE owner_id = NEW.owner_id
                  AND request_id = NEW.request_id
                  AND trace_id = NEW.trace_id
            ) THEN
                RAISE EXCEPTION
                    'context-build failure cannot claim a completed ContextPack'
                    USING ERRCODE = '55000';
            END IF;
            SELECT
                event.privacy_class,
                event.memory_eligible,
                event.training_eligible,
                event.cloud_eligible,
                event.policy_version,
                event.policy_revision_id
            INTO
                context_row.effective_privacy_class,
                context_row.effective_memory_eligible,
                context_row.effective_training_eligible,
                context_row.effective_cloud_eligible,
                context_row.effective_policy_version,
                context_row.effective_policy_revision_id
            FROM havre.events AS event
            WHERE event.owner_id = NEW.owner_id
              AND event.event_id = request_row.user_event_id
              AND event.event_type = 'USER_MESSAGE';
            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'context-build failure lacks its causation USER_MESSAGE'
                    USING ERRCODE = '55000';
            END IF;
        ELSE
            IF jsonb_typeof(NEW.payload->'context_pack_id') <> 'string'
               OR NEW.payload->>'context_pack_id' !~* (
                   '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-'
                   '[0-9a-f]{4}-[0-9a-f]{12}$'
               ) THEN
                RAISE EXCEPTION
                    'post-context failure requires an exact ContextPack reference'
                    USING ERRCODE = '55000';
            END IF;
            IF failure_stage IN ('capability_check', 'routing')
               AND (
                   NEW.payload->>'route_decision_id' IS NOT NULL
                   OR NEW.payload->>'inference_request_id' IS NOT NULL
               ) THEN
                RAISE EXCEPTION
                    'pre-route failure cannot claim route or inference lineage'
                    USING ERRCODE = '55000';
            END IF;
            IF failure_stage IN ('version_check', 'inference')
               AND (
                   jsonb_typeof(NEW.payload->'route_decision_id') <> 'string'
                   OR jsonb_typeof(NEW.payload->'inference_request_id') <> 'string'
                   OR NEW.payload->>'route_decision_id' !~* (
                       '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-'
                       '[0-9a-f]{4}-[0-9a-f]{12}$'
                   )
                   OR NEW.payload->>'inference_request_id' !~* (
                       '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-'
                       '[0-9a-f]{4}-[0-9a-f]{12}$'
                   )
               ) THEN
                RAISE EXCEPTION
                    'routed failure requires exact route and inference references'
                    USING ERRCODE = '55000';
            END IF;
            referenced_id := (NEW.payload->>'context_pack_id')::uuid;
            SELECT *
            INTO context_row
            FROM havre.context_packs
            WHERE owner_id = NEW.owner_id
              AND request_id = NEW.request_id
              AND trace_id = NEW.trace_id
              AND context_pack_id = referenced_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'failure Event does not reference its exact ContextPack'
                    USING ERRCODE = '55000';
            END IF;
            IF failure_stage IN ('version_check', 'inference') AND NOT EXISTS (
                SELECT 1
                FROM havre.route_decisions
                WHERE owner_id = NEW.owner_id
                  AND request_id = NEW.request_id
                  AND trace_id = NEW.trace_id
                  AND route_decision_id =
                        (NEW.payload->>'route_decision_id')::uuid
                  AND effective_policy_revision_id =
                        context_row.effective_policy_revision_id
            ) THEN
                RAISE EXCEPTION
                    'failure Event does not reference its exact route'
                    USING ERRCODE = '55000';
            END IF;
            IF failure_stage = 'inference' AND NOT EXISTS (
                SELECT 1
                FROM havre.inference_attempts
                WHERE owner_id = NEW.owner_id
                  AND request_id = NEW.request_id
                  AND trace_id = NEW.trace_id
                  AND context_pack_id = context_row.context_pack_id
                  AND route_decision_id =
                        (NEW.payload->>'route_decision_id')::uuid
                  AND inference_request_id =
                        (NEW.payload->>'inference_request_id')::uuid
                  AND status = 'failed'
            ) THEN
                RAISE EXCEPTION
                    'inference failure Event does not reference its failed attempt'
                    USING ERRCODE = '55000';
            END IF;
        END IF;
    END IF;

    IF NEW.privacy_class IS DISTINCT FROM context_row.effective_privacy_class
       OR NEW.memory_eligible
          IS DISTINCT FROM context_row.effective_memory_eligible
       OR NEW.training_eligible
          IS DISTINCT FROM context_row.effective_training_eligible
       OR NEW.cloud_eligible
          IS DISTINCT FROM context_row.effective_cloud_eligible
       OR NEW.policy_version
          IS DISTINCT FROM context_row.effective_policy_version
       OR NEW.policy_revision_id
          IS DISTINCT FROM context_row.effective_policy_revision_id THEN
        RAISE EXCEPTION
            'terminal interaction Event policy does not match its effective context'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER interaction_terminal_events_require_exact_lineage
BEFORE INSERT ON havre.events
FOR EACH ROW
WHEN (
    NEW.event_type = 'INTERACTION_FAILED'
    OR NEW.event_type = 'ASSISTANT_MESSAGE'
)
EXECUTE FUNCTION havre.guard_interaction_terminal_event_lineage();

-- The Event insert guard is not sufficient by itself: an Event can be inserted
-- before its request pointer is adopted, and request rows are otherwise
-- mutable.  Validate both terminal shapes at adoption, and make the canonical
-- terminal state and lineage irreversible once committed.
CREATE FUNCTION havre.guard_interaction_assistant_adoption()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    assistant_row havre.events%ROWTYPE;
    failure_row havre.events%ROWTYPE;
    context_row havre.context_packs%ROWTYPE;
    failure_stage text;
BEGIN
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

CREATE TRIGGER interaction_requests_require_exact_assistant_adoption
BEFORE UPDATE ON havre.interaction_requests
FOR EACH ROW
EXECUTE FUNCTION havre.guard_interaction_assistant_adoption();

-- Terminal Events are inserted before their request pointer is updated in the
-- canonical transaction.  At commit, require that the same request adopted
-- exactly that Event; a standalone forged insert therefore cannot become
-- durable or appear in product projections.
CREATE FUNCTION havre.guard_interaction_terminal_event_adoption()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    request_row havre.interaction_requests%ROWTYPE;
BEGIN
    SELECT *
    INTO request_row
    FROM havre.interaction_requests
    WHERE owner_id = NEW.owner_id
      AND request_id = NEW.request_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION
            'terminal interaction Event was not adopted by a durable request'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.event_type = 'ASSISTANT_MESSAGE'
       AND request_row.request_kind <> 'interaction' THEN
        RETURN NULL;
    END IF;
    IF request_row.request_kind <> 'interaction'
       OR (
           NEW.event_type = 'ASSISTANT_MESSAGE'
           AND (
               request_row.status <> 'completed'
               OR request_row.assistant_event_id IS DISTINCT FROM NEW.event_id
               OR request_row.failure_event_id IS NOT NULL
           )
       )
       OR (
           NEW.event_type = 'INTERACTION_FAILED'
           AND (
               request_row.status <> 'failed'
               OR request_row.failure_event_id IS DISTINCT FROM NEW.event_id
               OR request_row.assistant_event_id IS NOT NULL
           )
       ) THEN
        RAISE EXCEPTION
            'terminal interaction Event was not adopted by its exact request'
            USING ERRCODE = '55000';
    END IF;
    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER interaction_terminal_events_require_adoption
AFTER INSERT ON havre.events
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
WHEN (
    NEW.event_type = 'INTERACTION_FAILED'
    OR NEW.event_type = 'ASSISTANT_MESSAGE'
)
EXECUTE FUNCTION havre.guard_interaction_terminal_event_adoption();

-- A populated upgrade must fail closed if any immutable historical row already
-- contradicts the lineage now enforced for new inserts.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM havre.route_decisions AS route
        LEFT JOIN havre.context_packs AS context
          ON context.owner_id = route.owner_id
         AND context.request_id = route.request_id
         AND context.trace_id = route.trace_id
        WHERE context.context_pack_id IS NULL
           OR route.effective_policy_revision_id
              IS DISTINCT FROM context.effective_policy_revision_id
    ) THEN
        RAISE EXCEPTION 'existing route/ContextPack lineage violates 0052'
            USING ERRCODE = '55000';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM havre.inference_attempts AS attempt
        LEFT JOIN havre.route_decisions AS route
          ON route.owner_id = attempt.owner_id
         AND route.request_id = attempt.request_id
         AND route.trace_id = attempt.trace_id
         AND route.route_decision_id = attempt.route_decision_id
        LEFT JOIN havre.context_packs AS context
          ON context.owner_id = attempt.owner_id
         AND context.request_id = attempt.request_id
         AND context.trace_id = attempt.trace_id
         AND context.context_pack_id = attempt.context_pack_id
        WHERE route.route_decision_id IS NULL
           OR context.context_pack_id IS NULL
           OR attempt.provider_id IS DISTINCT FROM route.selected_provider_id
           OR attempt.model_version_id
              IS DISTINCT FROM route.selected_model_version_id
           OR route.effective_policy_revision_id
              IS DISTINCT FROM context.effective_policy_revision_id
           OR (
                attempt.provider_class = 'cloud'
                AND route.execution_environment <> 'cloud'
           )
           OR (
                attempt.provider_class <> 'cloud'
                AND route.execution_environment <> 'local'
           )
    ) THEN
        RAISE EXCEPTION 'existing inference route lineage violates 0052'
            USING ERRCODE = '55000';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM havre.inference_attempts AS attempt
        LEFT JOIN havre.runtime_attestations AS stored
          ON stored.runtime_attestation_id = attempt.runtime_attestation_id
         AND stored.attestation_hash = attempt.runtime_attestation_hash
        WHERE attempt.provider_class = 'self_hosted'
          AND attempt.runtime_attestation_contract_version = 1
          AND (
              stored.runtime_attestation_id IS NULL
              OR attempt.model_version_id
                 IS DISTINCT FROM stored.attestation->>'model_version_id'
              OR attempt.adapter_version_id
                 IS DISTINCT FROM stored.attestation->>'active_adapter_version_id'
              OR attempt.tokenizer_version_id
                 IS DISTINCT FROM stored.attestation->>'tokenizer_version_id'
              OR attempt.serving_config_version
                 IS DISTINCT FROM stored.attestation->>'serving_config_version'
              OR attempt.serving_engine
                 IS DISTINCT FROM stored.attestation->>'serving_engine'
              OR attempt.serving_engine_version
                 IS DISTINCT FROM stored.attestation->>'serving_engine_version'
              OR attempt.model_artifact_hash
                 IS DISTINCT FROM stored.attestation->>'model_artifact_hash'
          )
    ) THEN
        RAISE EXCEPTION 'existing self-hosted attestation lineage violates 0052'
            USING ERRCODE = '55000';
    END IF;

    -- Completed ordinary interactions are identified by the request's durable
    -- assistant pointer, not by trusting optional JSON keys on the Event.
    IF EXISTS (
        SELECT 1
        FROM havre.interaction_requests AS request
        LEFT JOIN havre.events AS assistant
          ON assistant.owner_id = request.owner_id
         AND assistant.request_id = request.request_id
         AND assistant.event_id = request.assistant_event_id
        LEFT JOIN havre.context_packs AS context
          ON context.owner_id = request.owner_id
         AND context.request_id = request.request_id
         AND context.trace_id = request.trace_id
         AND context.context_pack_id = request.context_pack_id
        LEFT JOIN havre.inference_attempts AS attempt
          ON attempt.owner_id = request.owner_id
         AND attempt.request_id = request.request_id
         AND attempt.trace_id = request.trace_id
         AND attempt.context_pack_id = request.context_pack_id
         AND attempt.inference_attempt_id = request.inference_attempt_id
        WHERE request.request_kind = 'interaction'
          AND (
              request.status = 'completed'
              OR request.assistant_event_id IS NOT NULL
          )
          AND (
              request.status <> 'completed'
              OR request.assistant_event_id IS NULL
              OR request.context_pack_id IS NULL
              OR request.inference_attempt_id IS NULL
              OR request.inference_response_id IS NULL
              OR assistant.event_id IS NULL
              OR assistant.event_type <> 'ASSISTANT_MESSAGE'
              OR assistant.trace_id IS DISTINCT FROM request.trace_id
              OR assistant.session_id IS DISTINCT FROM request.session_id
              OR assistant.causation_event_id
                 IS DISTINCT FROM request.user_event_id
              OR jsonb_typeof(assistant.payload->'context_pack_id')
                 IS DISTINCT FROM 'string'
              OR jsonb_typeof(assistant.payload->'inference_response_id')
                 IS DISTINCT FROM 'string'
              OR assistant.payload->>'context_pack_id'
                 IS DISTINCT FROM request.context_pack_id::text
              OR assistant.payload->>'inference_response_id'
                 IS DISTINCT FROM request.inference_response_id::text
              OR context.context_pack_id IS NULL
              OR attempt.inference_attempt_id IS NULL
              OR attempt.inference_response_id
                 IS DISTINCT FROM request.inference_response_id
              OR attempt.status <> 'completed'
              OR assistant.privacy_class
                 IS DISTINCT FROM context.effective_privacy_class
              OR assistant.memory_eligible
                 IS DISTINCT FROM context.effective_memory_eligible
              OR assistant.training_eligible
                 IS DISTINCT FROM context.effective_training_eligible
              OR assistant.cloud_eligible
                 IS DISTINCT FROM context.effective_cloud_eligible
              OR assistant.policy_version
                 IS DISTINCT FROM context.effective_policy_version
               OR assistant.policy_revision_id
                  IS DISTINCT FROM context.effective_policy_revision_id
               OR (
                   assistant.payload ? 'response_policy_decision'
                   AND (
                       jsonb_typeof(assistant.payload->'policy_decision_id')
                          IS DISTINCT FROM 'string'
                       OR jsonb_typeof(
                           assistant.payload->'response_policy_decision'
                       ) IS DISTINCT FROM 'object'
                       OR assistant.payload->>'policy_decision_id'
                          IS DISTINCT FROM
                          assistant.payload->'response_policy_decision'->>'decision_id'
                       OR assistant.payload->'response_policy_decision'->>'request_id'
                          IS DISTINCT FROM request.request_id::text
                       OR assistant.payload->'response_policy_decision'->>'trace_id'
                          IS DISTINCT FROM request.trace_id
                       OR assistant.payload->'response_policy_decision'->>'context_pack_id'
                          IS DISTINCT FROM request.context_pack_id::text
                       OR assistant.payload->'response_policy_decision'->>'inference_response_id'
                          IS DISTINCT FROM request.inference_response_id::text
                       OR assistant.payload->'response_policy_decision'->>'raw_output_content_hash'
                          IS DISTINCT FROM attempt.output_content_hash
                       OR assistant.payload->'response_policy_decision'->>'delivered_output_content_hash'
                          IS DISTINCT FROM (
                              'sha256:' || encode(public.digest(
                                  convert_to(havre.canonical_jsonb(
                                      assistant.payload->'content_parts'
                                  ), 'UTF8'),
                                  'sha256'
                              ), 'hex')
                          )
                       OR assistant.payload->'response_policy_decision'->>'content_hash'
                          IS DISTINCT FROM (
                              'sha256:' || encode(public.digest(
                                  convert_to(havre.canonical_jsonb(
                                      (assistant.payload->'response_policy_decision')
                                      - 'content_hash' - 'created_at'
                                  ), 'UTF8'),
                                  'sha256'
                              ), 'hex')
                          )
                       OR COALESCE(
                           assistant.payload->'response_policy_decision'->>'action'
                               NOT IN ('pass_through', 'replace'),
                           true
                       )
                       OR COALESCE(
                           assistant.payload->'response_policy_decision'->>'category'
                               NOT IN (
                                   'ordinary',
                                   'memory_truth',
                                   'urgent_safety',
                                   'system_confidentiality',
                                   'exact_structured_output',
                                   'privacy_tool_boundary'
                               ),
                           true
                       )
                       OR (
                           assistant.payload->'response_policy_decision'->>'action'
                               = 'pass_through'
                           AND (
                               assistant.payload->'response_policy_decision'->>'category'
                                   <> 'ordinary'
                               OR assistant.payload->'response_policy_decision'->>'raw_output_content_hash'
                                  IS DISTINCT FROM
                                  assistant.payload->'response_policy_decision'->>'delivered_output_content_hash'
                           )
                       )
                       OR (
                           assistant.payload->'response_policy_decision'->>'action'
                               = 'replace'
                           AND assistant.payload->'response_policy_decision'->>'category'
                               = 'ordinary'
                       )
                   )
               )
           )
    ) THEN
        RAISE EXCEPTION 'existing completed interaction lineage violates 0052'
            USING ERRCODE = '55000';
    END IF;

    -- An interaction-shaped assistant Event must be the request's one adopted
    -- assistant.  LEFT JOIN is deliberate so owner/request orphans fail the
    -- populated upgrade rather than disappearing from the scan.
    IF EXISTS (
        SELECT 1
        FROM havre.events AS assistant
        LEFT JOIN havre.interaction_requests AS request
          ON request.owner_id = assistant.owner_id
         AND request.request_id = assistant.request_id
        WHERE assistant.event_type = 'ASSISTANT_MESSAGE'
          AND (
              request.request_kind = 'interaction'
              OR EXISTS (
                  SELECT 1
                  FROM havre.context_packs AS ordinary_context
                  WHERE ordinary_context.owner_id = assistant.owner_id
                    AND ordinary_context.request_id = assistant.request_id
                    AND ordinary_context.trace_id = assistant.trace_id
              )
              OR
              assistant.payload ? 'context_pack_id'
              OR assistant.payload ? 'inference_response_id'
          )
          AND (
              request.request_id IS NULL
              OR request.request_kind <> 'interaction'
              OR request.assistant_event_id IS DISTINCT FROM assistant.event_id
              OR jsonb_typeof(assistant.payload->'context_pack_id')
                 IS DISTINCT FROM 'string'
              OR jsonb_typeof(assistant.payload->'inference_response_id')
                 IS DISTINCT FROM 'string'
          )
    ) THEN
        RAISE EXCEPTION 'existing orphan interaction assistant Event violates 0052'
            USING ERRCODE = '55000';
    END IF;

    -- Failed interactions have stage-dependent lineage.  All joins compare
    -- canonical UUID text instead of casting untrusted JSON, so malformed
    -- historical payloads produce the stable 55000 migration failure below.
    IF EXISTS (
        SELECT 1
        FROM havre.events AS failure
        LEFT JOIN havre.interaction_requests AS request
          ON request.owner_id = failure.owner_id
         AND request.request_id = failure.request_id
        LEFT JOIN havre.events AS user_event
          ON user_event.owner_id = request.owner_id
         AND user_event.event_id = request.user_event_id
         AND user_event.event_type = 'USER_MESSAGE'
        LEFT JOIN havre.context_packs AS context
          ON context.owner_id = failure.owner_id
         AND context.request_id = failure.request_id
         AND context.trace_id = failure.trace_id
         AND context.context_pack_id::text =
             failure.payload->>'context_pack_id'
        LEFT JOIN havre.route_decisions AS route
          ON route.owner_id = failure.owner_id
         AND route.request_id = failure.request_id
         AND route.trace_id = failure.trace_id
         AND route.route_decision_id::text =
             failure.payload->>'route_decision_id'
         AND route.effective_policy_revision_id =
             context.effective_policy_revision_id
        LEFT JOIN havre.inference_attempts AS attempt
          ON attempt.owner_id = failure.owner_id
         AND attempt.request_id = failure.request_id
         AND attempt.trace_id = failure.trace_id
         AND attempt.context_pack_id = context.context_pack_id
         AND attempt.route_decision_id = route.route_decision_id
         AND attempt.inference_request_id::text =
             failure.payload->>'inference_request_id'
         AND attempt.status = 'failed'
        WHERE failure.event_type = 'INTERACTION_FAILED'
          AND (
              request.request_id IS NULL
              OR request.request_kind <> 'interaction'
              OR request.status <> 'failed'
              OR request.failure_event_id IS DISTINCT FROM failure.event_id
              OR request.error_code
                 IS DISTINCT FROM failure.payload->>'failure_code'
              OR failure.trace_id IS DISTINCT FROM request.trace_id
              OR failure.session_id IS DISTINCT FROM request.session_id
              OR failure.causation_event_id
                 IS DISTINCT FROM request.user_event_id
              OR COALESCE(
                  failure.payload->>'failure_stage' NOT IN (
                      'context_build',
                      'capability_check',
                      'routing',
                      'version_check',
                      'inference'
                  ),
                  true
              )
              OR (
                  failure.payload->>'failure_stage' = 'context_build'
                  AND (
                      failure.payload->>'context_pack_id' IS NOT NULL
                      OR failure.payload->>'route_decision_id' IS NOT NULL
                      OR failure.payload->>'inference_request_id' IS NOT NULL
                      OR EXISTS (
                          SELECT 1
                          FROM havre.context_packs AS claimed_context
                          WHERE claimed_context.owner_id = failure.owner_id
                            AND claimed_context.request_id = failure.request_id
                            AND claimed_context.trace_id = failure.trace_id
                      )
                      OR user_event.event_id IS NULL
                      OR failure.privacy_class
                         IS DISTINCT FROM user_event.privacy_class
                      OR failure.memory_eligible
                         IS DISTINCT FROM user_event.memory_eligible
                      OR failure.training_eligible
                         IS DISTINCT FROM user_event.training_eligible
                      OR failure.cloud_eligible
                         IS DISTINCT FROM user_event.cloud_eligible
                      OR failure.policy_version
                         IS DISTINCT FROM user_event.policy_version
                      OR failure.policy_revision_id
                         IS DISTINCT FROM user_event.policy_revision_id
                  )
              )
              OR (
                  failure.payload->>'failure_stage' <> 'context_build'
                  AND (
                      jsonb_typeof(failure.payload->'context_pack_id')
                         IS DISTINCT FROM 'string'
                      OR context.context_pack_id IS NULL
                      OR request.context_pack_id
                         IS DISTINCT FROM context.context_pack_id
                      OR failure.privacy_class
                         IS DISTINCT FROM context.effective_privacy_class
                      OR failure.memory_eligible
                         IS DISTINCT FROM context.effective_memory_eligible
                      OR failure.training_eligible
                         IS DISTINCT FROM context.effective_training_eligible
                      OR failure.cloud_eligible
                         IS DISTINCT FROM context.effective_cloud_eligible
                      OR failure.policy_version
                         IS DISTINCT FROM context.effective_policy_version
                      OR failure.policy_revision_id
                         IS DISTINCT FROM context.effective_policy_revision_id
                  )
              )
              OR (
                  failure.payload->>'failure_stage' IN (
                      'capability_check',
                      'routing'
                  )
                  AND (
                      failure.payload->>'route_decision_id' IS NOT NULL
                      OR failure.payload->>'inference_request_id' IS NOT NULL
                  )
              )
              OR (
                  failure.payload->>'failure_stage' IN (
                      'version_check',
                      'inference'
                  )
                  AND (
                      jsonb_typeof(failure.payload->'route_decision_id')
                         IS DISTINCT FROM 'string'
                      OR jsonb_typeof(failure.payload->'inference_request_id')
                         IS DISTINCT FROM 'string'
                      OR route.route_decision_id IS NULL
                  )
              )
              OR (
                  failure.payload->>'failure_stage' = 'inference'
                  AND (
                      attempt.inference_attempt_id IS NULL
                      OR request.inference_attempt_id
                         IS DISTINCT FROM attempt.inference_attempt_id
                  )
              )
          )
    ) THEN
        RAISE EXCEPTION 'existing failed interaction lineage violates 0052'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

COMMIT;
