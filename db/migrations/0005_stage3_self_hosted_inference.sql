-- Stage 3 self-hosted inference evidence. This migration is additive: historical
-- Stage 1/2 rows retain their original identifiers and remain readable.

ALTER TABLE havre.events DROP CONSTRAINT events_event_type_check;
ALTER TABLE havre.events ADD CONSTRAINT events_event_type_check CHECK (event_type IN (
    'USER_MESSAGE', 'ASSISTANT_MESSAGE', 'INTERACTION_FAILED',
    'MEMORY_CREATED', 'MEMORY_REVISED', 'MEMORY_RETRACTED'
));
ALTER TABLE havre.events
    ADD CONSTRAINT events_owner_request_event_pointer_key
        UNIQUE (owner_id, request_id, event_id);

-- The original schema used the successful response ID as the attempt primary
-- key. Stage 3 needs a terminal failed attempt even when no response exists.
ALTER TABLE havre.interaction_requests
    DROP CONSTRAINT interaction_requests_owner_inference_response_fk;

ALTER TABLE havre.inference_attempts
    DROP CONSTRAINT inference_attempts_pkey,
    DROP CONSTRAINT inference_attempts_inference_request_id_key,
    DROP CONSTRAINT inference_attempts_request_id_key,
    DROP CONSTRAINT inference_attempts_owner_response_key,
    DROP CONSTRAINT inference_attempts_status_check,
    DROP CONSTRAINT inference_attempts_finish_reason_check,
    ALTER COLUMN inference_response_id DROP NOT NULL,
    ALTER COLUMN finish_reason DROP NOT NULL,
    ALTER COLUMN provider_request_id DROP NOT NULL,
    ALTER COLUMN adapter_version_id DROP NOT NULL,
    ALTER COLUMN usage DROP NOT NULL,
    ALTER COLUMN timing_ms DROP NOT NULL,
    ALTER COLUMN output_content_hash DROP NOT NULL,
    ADD COLUMN inference_attempt_id uuid,
    ADD COLUMN attempt_number integer NOT NULL DEFAULT 1 CHECK (attempt_number > 0),
    ADD COLUMN provider_adapter_version_id text,
    ADD COLUMN serving_engine text,
    ADD COLUMN serving_engine_version text,
    ADD COLUMN model_artifact_hash text,
    ADD COLUMN failure jsonb;

-- Migration-only backfill: remove exactly this immutable trigger, update the
-- historical rows, then restore it before exposing the migrated schema.
DROP TRIGGER inference_attempts_are_immutable ON havre.inference_attempts;

UPDATE havre.inference_attempts SET
    inference_attempt_id = inference_response_id,
    provider_adapter_version_id = 'legacy-stage1-provider-adapter',
    serving_engine = 'legacy-unknown',
    serving_engine_version = 'legacy-unknown'
WHERE inference_attempt_id IS NULL;

CREATE TRIGGER inference_attempts_are_immutable
BEFORE UPDATE OR DELETE ON havre.inference_attempts
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();

ALTER TABLE havre.inference_attempts
    ALTER COLUMN inference_attempt_id SET NOT NULL,
    ALTER COLUMN provider_adapter_version_id SET NOT NULL,
    ALTER COLUMN serving_engine SET NOT NULL,
    ALTER COLUMN serving_engine_version SET NOT NULL,
    ADD CONSTRAINT inference_attempts_pkey PRIMARY KEY (inference_attempt_id),
    ADD CONSTRAINT inference_attempts_owner_attempt_key
        UNIQUE (owner_id, inference_attempt_id),
    ADD CONSTRAINT inference_attempts_owner_request_attempt_pointer_key
        UNIQUE (owner_id, request_id, inference_attempt_id),
    ADD CONSTRAINT inference_attempts_owner_request_response_key
        UNIQUE (owner_id, request_id, inference_response_id),
    ADD CONSTRAINT inference_attempts_owner_response_key
        UNIQUE (owner_id, inference_response_id),
    ADD CONSTRAINT inference_attempts_request_attempt_key
        UNIQUE (owner_id, request_id, attempt_number),
    ADD CONSTRAINT inference_attempts_inference_request_key
        UNIQUE (owner_id, inference_request_id),
    ADD CONSTRAINT inference_attempts_status_check
        CHECK (status IN ('completed', 'failed')),
    ADD CONSTRAINT inference_attempts_finish_reason_check
        CHECK (finish_reason IS NULL OR finish_reason IN ('stop', 'length')),
    ADD CONSTRAINT inference_attempts_model_artifact_hash_check
        CHECK (model_artifact_hash IS NULL OR model_artifact_hash ~ '^sha256:[0-9a-f]{64}$'),
    ADD CONSTRAINT inference_attempts_failure_shape_check CHECK (
        (status = 'completed'
         AND inference_response_id IS NOT NULL
         AND finish_reason IS NOT NULL
         AND provider_request_id IS NOT NULL
         AND usage IS NOT NULL AND jsonb_typeof(usage) = 'object'
         AND timing_ms IS NOT NULL AND jsonb_typeof(timing_ms) = 'object'
         AND output_content_hash IS NOT NULL
         AND failure IS NULL)
        OR
        (status = 'failed'
         AND inference_response_id IS NULL
         AND finish_reason IS NULL
         AND usage IS NULL
         AND output_content_hash IS NULL
         AND failure IS NOT NULL AND jsonb_typeof(failure) = 'object'
         AND failure->>'inference_request_id' IS NOT DISTINCT FROM inference_request_id::text
         AND failure->>'request_id' IS NOT DISTINCT FROM request_id::text
         AND failure->>'trace_id' IS NOT DISTINCT FROM trace_id
         AND failure->>'provider_id' IS NOT DISTINCT FROM provider_id
         AND failure->>'provider_class' IS NOT DISTINCT FROM provider_class
         AND failure ?& ARRAY[
             'schema_version', 'inference_request_id', 'request_id', 'trace_id',
             'provider_id', 'provider_class', 'code', 'retryable', 'safe_message',
             'provider_status_code', 'provider_error_code', 'created_at'
         ]
         AND failure->'schema_version' = '1'::jsonb
         AND jsonb_typeof(failure->'code') = 'string'
         AND failure->>'code' IN (
             'invalid_request', 'unsupported_capability',
             'privacy_constraint_unsatisfied', 'model_unavailable',
             'provider_rate_limited', 'provider_timeout',
             'context_limit_exceeded', 'content_blocked',
             'stream_interrupted', 'provider_protocol_error', 'internal_error'
         )
         AND jsonb_typeof(failure->'retryable') = 'boolean'
         AND jsonb_typeof(failure->'safe_message') = 'string'
         AND length(failure->>'safe_message') BETWEEN 1 AND 500
         AND (
             failure->'provider_status_code' = 'null'::jsonb
             OR (
                 jsonb_typeof(failure->'provider_status_code') = 'number'
                 AND failure->>'provider_status_code' ~ '^[0-9]+$'
                 AND (failure->>'provider_status_code')::integer BETWEEN 100 AND 599
             )
         )
         AND (
             failure->'provider_error_code' = 'null'::jsonb
             OR (
                 jsonb_typeof(failure->'provider_error_code') = 'string'
                 AND length(failure->>'provider_error_code') BETWEEN 1 AND 200
             )
         )
         AND jsonb_typeof(failure->'created_at') = 'string'
         AND length(failure->>'created_at') > 0)
    );

ALTER TABLE havre.interaction_requests
    ADD COLUMN inference_attempt_id uuid,
    ADD COLUMN failure_event_id uuid;

UPDATE havre.interaction_requests AS request SET
    inference_attempt_id = attempt.inference_attempt_id
FROM havre.inference_attempts AS attempt
WHERE attempt.owner_id = request.owner_id
  AND attempt.request_id = request.request_id;

ALTER TABLE havre.interaction_requests
    ADD CONSTRAINT interaction_requests_owner_inference_attempt_fk
        FOREIGN KEY (owner_id, request_id, inference_attempt_id)
        REFERENCES havre.inference_attempts(owner_id, request_id, inference_attempt_id),
    ADD CONSTRAINT interaction_requests_owner_inference_response_fk
        FOREIGN KEY (owner_id, request_id, inference_response_id)
        REFERENCES havre.inference_attempts(
            owner_id, request_id, inference_response_id
        ),
    ADD CONSTRAINT interaction_requests_owner_failure_event_fk
        FOREIGN KEY (owner_id, request_id, failure_event_id)
        REFERENCES havre.events(owner_id, request_id, event_id);

CREATE INDEX interaction_requests_owner_inference_attempt_id_idx
    ON havre.interaction_requests(owner_id, inference_attempt_id)
    WHERE inference_attempt_id IS NOT NULL;
CREATE INDEX interaction_requests_owner_failure_event_id_idx
    ON havre.interaction_requests(owner_id, failure_event_id)
    WHERE failure_event_id IS NOT NULL;

-- Bind every Stage 1/3 execution artifact to one exact owner/request/trace
-- lineage. Owner-only foreign keys prevent cross-owner references but are not
-- sufficient to prevent two requests belonging to the same owner being mixed.
ALTER TABLE havre.traces
    ADD CONSTRAINT traces_owner_root_request_trace_key
        UNIQUE (owner_id, root_request_id, trace_id);
ALTER TABLE havre.interaction_requests
    ADD CONSTRAINT interaction_requests_owner_request_trace_key
        UNIQUE (owner_id, request_id, trace_id);
ALTER TABLE havre.context_packs
    ADD CONSTRAINT context_packs_owner_request_trace_pack_key
        UNIQUE (owner_id, request_id, trace_id, context_pack_id);
ALTER TABLE havre.route_decisions
    ADD CONSTRAINT route_decisions_owner_request_trace_route_key
        UNIQUE (owner_id, request_id, trace_id, route_decision_id);
ALTER TABLE havre.interaction_requests
    ADD CONSTRAINT interaction_requests_exact_trace_fk
        FOREIGN KEY (owner_id, request_id, trace_id)
        REFERENCES havre.traces(owner_id, root_request_id, trace_id),
    ADD CONSTRAINT interaction_requests_exact_user_event_fk
        FOREIGN KEY (owner_id, request_id, user_event_id)
        REFERENCES havre.events(owner_id, request_id, event_id),
    ADD CONSTRAINT interaction_requests_exact_assistant_event_fk
        FOREIGN KEY (owner_id, request_id, assistant_event_id)
        REFERENCES havre.events(owner_id, request_id, event_id),
    ADD CONSTRAINT interaction_requests_exact_context_pack_fk
        FOREIGN KEY (owner_id, request_id, trace_id, context_pack_id)
        REFERENCES havre.context_packs(
            owner_id, request_id, trace_id, context_pack_id
        );
ALTER TABLE havre.events
    ADD CONSTRAINT events_owner_request_trace_fk
        FOREIGN KEY (owner_id, request_id, trace_id)
        REFERENCES havre.interaction_requests(owner_id, request_id, trace_id);
ALTER TABLE havre.context_packs
    ADD CONSTRAINT context_packs_owner_request_trace_fk
        FOREIGN KEY (owner_id, request_id, trace_id)
        REFERENCES havre.interaction_requests(owner_id, request_id, trace_id);
ALTER TABLE havre.route_decisions
    ADD CONSTRAINT route_decisions_owner_request_trace_fk
        FOREIGN KEY (owner_id, request_id, trace_id)
        REFERENCES havre.interaction_requests(owner_id, request_id, trace_id);
ALTER TABLE havre.inference_attempts
    ADD CONSTRAINT inference_attempts_owner_request_trace_fk
        FOREIGN KEY (owner_id, request_id, trace_id)
        REFERENCES havre.interaction_requests(owner_id, request_id, trace_id),
    ADD CONSTRAINT inference_attempts_exact_context_pack_fk
        FOREIGN KEY (owner_id, request_id, trace_id, context_pack_id)
        REFERENCES havre.context_packs(
            owner_id, request_id, trace_id, context_pack_id
        ),
    ADD CONSTRAINT inference_attempts_exact_route_decision_fk
        FOREIGN KEY (owner_id, request_id, trace_id, route_decision_id)
        REFERENCES havre.route_decisions(
            owner_id, request_id, trace_id, route_decision_id
        );

-- Stage 3 benchmark reports remain immutable evidence, separate from the
-- operational interaction tables and free of user-derived inputs.
CREATE TABLE havre.inference_benchmark_runs (
    benchmark_run_id uuid NOT NULL,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    report_kind text NOT NULL CHECK (report_kind IN ('systems_performance', 'behavior_compatibility')),
    system_manifest jsonb NOT NULL CHECK (jsonb_typeof(system_manifest) = 'object'),
    workload_manifest jsonb NOT NULL CHECK (jsonb_typeof(workload_manifest) = 'object'),
    environment_manifest jsonb NOT NULL CHECK (jsonb_typeof(environment_manifest) = 'object'),
    report jsonb NOT NULL CHECK (jsonb_typeof(report) = 'object'),
    content_hash text NOT NULL UNIQUE CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL,
    PRIMARY KEY (benchmark_run_id, report_kind)
);

CREATE TRIGGER inference_benchmark_runs_are_immutable
BEFORE UPDATE OR DELETE ON havre.inference_benchmark_runs
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();
