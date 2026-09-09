-- Preserve historical decisions and admit the versioned action-truth boundary.
CREATE OR REPLACE FUNCTION havre.guard_interaction_terminal_event_lineage()
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
           OR COALESCE(decision->>'policy_version' NOT IN ('core-response-policy-v1','core-response-policy-v2-action-receipts'),true)
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
