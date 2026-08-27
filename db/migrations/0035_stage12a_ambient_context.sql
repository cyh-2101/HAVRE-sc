BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE FUNCTION havre.canonical_jsonb(value jsonb) RETURNS text
LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE
    rendered text;
BEGIN
    CASE jsonb_typeof(value)
        WHEN 'object' THEN
            SELECT '{' || coalesce(string_agg(
                to_jsonb(item.key)::text || ':' || havre.canonical_jsonb(item.value),
                ',' ORDER BY item.key
            ), '') || '}'
            INTO rendered
            FROM jsonb_each(value) AS item;
        WHEN 'array' THEN
            SELECT '[' || coalesce(string_agg(
                havre.canonical_jsonb(item.value), ',' ORDER BY item.ordinality
            ), '') || ']'
            INTO rendered
            FROM jsonb_array_elements(value) WITH ORDINALITY AS item(value, ordinality);
        ELSE
            rendered := value::text;
    END CASE;
    RETURN rendered;
END;
$$;

CREATE FUNCTION havre.utc_json_timestamp(value timestamptz) RETURNS text
LANGUAGE sql IMMUTABLE STRICT AS $$
    SELECT to_char(value AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS') ||
        CASE WHEN extract(microseconds FROM value)::bigint % 1000000 = 0
             THEN 'Z'
             ELSE '.' || to_char(value AT TIME ZONE 'UTC', 'US') || 'Z'
        END
$$;

ALTER TABLE havre.events DROP CONSTRAINT events_event_type_check;
ALTER TABLE havre.events ADD CONSTRAINT events_event_type_check CHECK (event_type IN (
    'USER_MESSAGE', 'ASSISTANT_MESSAGE', 'INTERACTION_FAILED',
    'MEMORY_CREATED', 'MEMORY_REVISED', 'MEMORY_RETRACTED',
    'CURRENT_STATE_ESTIMATED',
    'USER_BELIEF_CREATED', 'USER_BELIEF_REVISED', 'USER_BELIEF_TRANSITIONED',
    'CONSOLIDATION_PROPOSED', 'CONSOLIDATION_REVIEWED',
    'GOAL_CREATED', 'GOAL_UPDATED', 'GOAL_COMPLETED', 'PROGRESS_RECORDED',
    'SCENE_SESSION_PLANNED', 'SCENE_SESSION_STARTED', 'SCENE_PHASE_CHANGED',
    'SCENE_SESSION_PAUSED', 'SCENE_SESSION_ENDED', 'USER_SIGNAL',
    'INTERVENTION_DECIDED', 'USER_ACTION_REPORTED', 'OUTCOME_REPORTED',
    'REFLECTION_CREATED', 'CONTEXT_SOURCE_STATE_REVISED',
    'CONTEXT_CAPABILITY_STATE_REVISED', 'CONTEXT_CONSENT_REVISED',
    'LIFE_CONTEXT_OBSERVED'
));

ALTER TABLE havre.interaction_requests
    DROP CONSTRAINT interaction_requests_request_kind_check;
ALTER TABLE havre.interaction_requests
    ADD CONSTRAINT interaction_requests_request_kind_check CHECK (
        request_kind IN (
            'interaction', 'scene_command', 'proactive_work', 'context_ingest'
        )
    );

CREATE TABLE havre.context_sources (
    source_instance_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    source_kind text NOT NULL CHECK (source_kind IN ('windows', 'calendar')),
    provider_id text NOT NULL CHECK (provider_id ~ '^[a-z][a-z0-9_.-]{1,95}$'),
    device_binding_id text NOT NULL CHECK (device_binding_id ~ '^[a-z][a-z0-9_.:-]{2,127}$'),
    adapter_version text NOT NULL CHECK (adapter_version ~ '^[a-z][a-z0-9_.-]{2,127}$'),
    source_version text NOT NULL CHECK (length(source_version) BETWEEN 1 AND 200),
    provider_tenant_binding text CHECK (
        provider_tenant_binding IS NULL OR
        provider_tenant_binding ~ '^sha256:[0-9a-f]{64}$'
    ),
    provider_account_binding text CHECK (
        provider_account_binding IS NULL OR
        provider_account_binding ~ '^sha256:[0-9a-f]{64}$'
    ),
    enrollment_status text NOT NULL CHECK (enrollment_status = 'enabled'),
    registration_event_id uuid NOT NULL UNIQUE REFERENCES havre.events(event_id),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (owner_id, source_instance_id),
    UNIQUE (owner_id, device_binding_id),
    CONSTRAINT context_sources_provider_profile_check CHECK (
        (source_kind='calendar' AND provider_id='manual-ics'
         AND adapter_version='manual-ics-calendar-v1'
         AND source_version='rfc5545-bounded-v1'
         AND provider_tenant_binding IS NOT NULL
         AND provider_account_binding IS NOT NULL)
        OR
        (source_kind='windows' AND provider_tenant_binding IS NULL
         AND provider_account_binding IS NULL)
    )
);
CREATE INDEX context_sources_owner_id_idx ON havre.context_sources(owner_id);

CREATE TABLE havre.context_source_erasure_tombstones (
    tombstone_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version=1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    source_instance_id uuid NOT NULL,
    registration_event_id uuid NOT NULL,
    erased_at timestamptz NOT NULL,
    directive_sequence bigint NOT NULL CHECK (directive_sequence>0),
    directive_hash text NOT NULL CHECK (directive_hash ~ '^sha256:[0-9a-f]{64}$'),
    absence_verified boolean NOT NULL CHECK (absence_verified),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    UNIQUE (owner_id, source_instance_id),
    UNIQUE (owner_id, registration_event_id),
    UNIQUE (owner_id, directive_hash)
);
CREATE INDEX context_source_erasure_tombstones_owner_idx
    ON havre.context_source_erasure_tombstones(owner_id, erased_at DESC);

CREATE TABLE havre.context_restore_quarantines (
    quarantine_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version=1),
    owner_id uuid NOT NULL,
    source_instance_id uuid NOT NULL,
    restore_id text NOT NULL CHECK (length(restore_id) BETWEEN 1 AND 200),
    reason text NOT NULL CHECK (reason='backup_restore_requires_new_source_enrollment'),
    quarantined_at timestamptz NOT NULL,
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    UNIQUE (owner_id, source_instance_id, restore_id),
    FOREIGN KEY (owner_id, source_instance_id)
        REFERENCES havre.context_sources(owner_id, source_instance_id)
);
CREATE INDEX context_restore_quarantines_source_idx
    ON havre.context_restore_quarantines(owner_id,source_instance_id,quarantined_at DESC);

-- HMAC keys are used only by durable verification triggers. Ordinary
-- application credentials are denied every privilege on this table.
CREATE TABLE havre.context_device_bindings (
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    device_binding_id text NOT NULL,
    source_instance_id uuid NOT NULL,
    key_version integer NOT NULL CHECK (key_version > 0),
    signing_secret bytea NOT NULL CHECK (octet_length(signing_secret) >= 32),
    status text NOT NULL CHECK (status = 'enabled'),
    registered_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (owner_id, device_binding_id, key_version),
    UNIQUE (owner_id, source_instance_id),
    FOREIGN KEY (owner_id, source_instance_id)
        REFERENCES havre.context_sources(owner_id, source_instance_id)
);

CREATE TABLE havre.context_source_state_revisions (
    state_revision_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL,
    source_instance_id uuid NOT NULL,
    revision integer NOT NULL CHECK (revision > 0),
    status text NOT NULL CHECK (status IN ('enabled', 'disabled')),
    reason text NOT NULL CHECK (
        reason IN ('registered', 'owner_disabled', 'lost_device', 'key_rotated')
    ),
    effective_at timestamptz NOT NULL,
    authorization_ref text NOT NULL CHECK (length(authorization_ref) BETWEEN 1 AND 500),
    decision_event_id uuid NOT NULL UNIQUE REFERENCES havre.events(event_id),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (owner_id, state_revision_id),
    UNIQUE (owner_id, source_instance_id, revision),
    FOREIGN KEY (owner_id, source_instance_id)
        REFERENCES havre.context_sources(owner_id, source_instance_id),
    CHECK ((revision = 1) = (reason = 'registered')),
    CHECK (revision <> 1 OR status = 'enabled')
);
CREATE INDEX context_source_state_head_idx
    ON havre.context_source_state_revisions(owner_id, source_instance_id, revision DESC);

CREATE TABLE havre.context_source_capabilities (
    capability_revision_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL,
    source_instance_id uuid NOT NULL,
    capability_id text NOT NULL CHECK (capability_id IN (
        'windows.device_activity_summary.v1','calendar.read_availability.v1'
    )),
    revision integer NOT NULL CHECK (revision = 1),
    observation_kind text NOT NULL CHECK (observation_kind IN (
        'device_activity_summary','calendar_availability_window'
    )),
    observation_schema_version smallint NOT NULL CHECK (observation_schema_version = 1),
    allowed_fields jsonb NOT NULL,
    precision text NOT NULL CHECK (precision IN (
        'coarse_category_window','availability_only_no_content'
    )),
    sampling_modes jsonb NOT NULL,
    conformance_version text NOT NULL,
    status text NOT NULL CHECK (status = 'enabled'),
    registration_event_id uuid NOT NULL UNIQUE REFERENCES havre.events(event_id),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (owner_id, capability_revision_id),
    UNIQUE (owner_id, source_instance_id, capability_id, revision),
    FOREIGN KEY (owner_id, source_instance_id)
        REFERENCES havre.context_sources(owner_id, source_instance_id),
    CHECK (
      (capability_id='windows.device_activity_summary.v1'
       AND observation_kind='device_activity_summary'
       AND allowed_fields='["activity_state","active_seconds","dominant_category","idle_seconds","sample_count","window_seconds"]'::jsonb
       AND precision='coarse_category_window'
       AND sampling_modes='["bounded_interval"]'::jsonb
       AND conformance_version='windows-coarse-adapter-conformance-v1')
      OR
      (capability_id='calendar.read_availability.v1'
       AND observation_kind='calendar_availability_window'
       AND allowed_fields='["busy_intervals"]'::jsonb
       AND precision='availability_only_no_content'
       AND sampling_modes='["owner_initiated_import"]'::jsonb
       AND conformance_version='calendar-availability-adapter-conformance-v1')
    )
);
CREATE INDEX context_source_capabilities_source_idx
    ON havre.context_source_capabilities(owner_id, source_instance_id);

CREATE TABLE havre.context_capability_state_revisions (
    state_revision_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL,
    capability_revision_id uuid NOT NULL,
    revision integer NOT NULL CHECK (revision > 0),
    status text NOT NULL CHECK (status IN ('enabled', 'disabled')),
    reason text NOT NULL CHECK (
        reason IN ('registered', 'owner_disabled', 'source_disabled')
    ),
    effective_at timestamptz NOT NULL,
    authorization_ref text NOT NULL CHECK (length(authorization_ref) BETWEEN 1 AND 500),
    decision_event_id uuid NOT NULL UNIQUE REFERENCES havre.events(event_id),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (owner_id, state_revision_id),
    UNIQUE (owner_id, capability_revision_id, revision),
    FOREIGN KEY (owner_id, capability_revision_id)
        REFERENCES havre.context_source_capabilities(owner_id, capability_revision_id),
    CHECK ((revision = 1) = (reason = 'registered')),
    CHECK (revision <> 1 OR status = 'enabled')
);
CREATE INDEX context_capability_state_head_idx
    ON havre.context_capability_state_revisions(
        owner_id, capability_revision_id, revision DESC
    );

CREATE TABLE havre.context_consent_scope_revisions (
    consent_scope_revision_id uuid PRIMARY KEY,
    consent_scope_id uuid NOT NULL,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL,
    source_instance_id uuid NOT NULL,
    capability_revision_id uuid NOT NULL,
    revision integer NOT NULL CHECK (revision > 0),
    status text NOT NULL CHECK (status IN ('active', 'revoked', 'expired')),
    purpose text NOT NULL CHECK (purpose = 'companion_timing_context'),
    allowed_observation_kinds jsonb NOT NULL,
    allowed_fields jsonb NOT NULL,
    permitted_destinations jsonb NOT NULL CHECK (
        permitted_destinations = '["owner_core_local"]'::jsonb
    ),
    sampling_policy jsonb NOT NULL CHECK (jsonb_typeof(sampling_policy) = 'object'),
    retention_policy jsonb NOT NULL CHECK (jsonb_typeof(retention_policy) = 'object'),
    data_policy jsonb NOT NULL CHECK (jsonb_typeof(data_policy) = 'object'),
    effective_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    authorization_ref text NOT NULL CHECK (length(authorization_ref) BETWEEN 1 AND 500),
    decision_event_id uuid NOT NULL UNIQUE REFERENCES havre.events(event_id),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (owner_id, consent_scope_revision_id),
    UNIQUE (owner_id, consent_scope_id, revision),
    FOREIGN KEY (owner_id, source_instance_id)
        REFERENCES havre.context_sources(owner_id, source_instance_id),
    FOREIGN KEY (owner_id, capability_revision_id)
        REFERENCES havre.context_source_capabilities(owner_id, capability_revision_id),
    CHECK (expires_at > effective_at),
    CHECK (data_policy->>'privacy_class' = 'LOCAL_ONLY'),
    CHECK ((data_policy->>'memory_eligible')::boolean = false),
    CHECK ((data_policy->>'training_eligible')::boolean = false),
    CHECK ((data_policy->>'cloud_eligible')::boolean = false),
    CHECK (data_policy->>'decision_source' = 'owner_explicit'),
    CHECK (data_policy->>'authorization_ref' = authorization_ref),
    CHECK ((retention_policy->>'source_native_retention_seconds')::integer = 0),
    CHECK (retention_policy->>'expiry_action' = 'erase_with_provenance_closure'),
    CHECK (
      (allowed_observation_kinds='["device_activity_summary"]'::jsonb
       AND allowed_fields='["activity_state","active_seconds","dominant_category","idle_seconds","sample_count","window_seconds"]'::jsonb
       AND sampling_policy->>'mode'='bounded_interval')
      OR
      (allowed_observation_kinds='["calendar_availability_window"]'::jsonb
       AND allowed_fields='["busy_intervals"]'::jsonb
       AND sampling_policy->>'mode'='owner_initiated_import')
    )
);
CREATE INDEX context_consent_source_capability_idx
    ON havre.context_consent_scope_revisions(
        owner_id, source_instance_id, capability_revision_id, revision DESC
    );
CREATE INDEX context_consent_capability_fk_idx
    ON havre.context_consent_scope_revisions(owner_id, capability_revision_id);

CREATE TABLE havre.life_context_observations (
    observation_id uuid PRIMARY KEY,
    draft_id uuid NOT NULL,
    schema_version smallint NOT NULL CHECK (schema_version = 2),
    owner_id uuid NOT NULL,
    source_instance_id uuid NOT NULL,
    capability_revision_id uuid NOT NULL,
    capability_id text NOT NULL CHECK (capability_id IN (
        'windows.device_activity_summary.v1','calendar.read_availability.v1'
    )),
    observation_kind text NOT NULL CHECK (observation_kind IN (
        'device_activity_summary','calendar_availability_window'
    )),
    observation_schema_version smallint NOT NULL CHECK (observation_schema_version = 1),
    value jsonb NOT NULL CHECK (jsonb_typeof(value) = 'object'),
    occurred_from timestamptz NOT NULL,
    occurred_to timestamptz NOT NULL,
    source_observed_at timestamptz NOT NULL,
    ingested_at timestamptz NOT NULL,
    fresh_until timestamptz NOT NULL,
    retention_expires_at timestamptz NOT NULL,
    consent_scope_revision_id uuid NOT NULL,
    sampling_policy_version text NOT NULL,
    retention_policy_version text NOT NULL,
    adapter_version text NOT NULL,
    privacy_class text NOT NULL CHECK (privacy_class = 'LOCAL_ONLY'),
    memory_eligible boolean NOT NULL CHECK (memory_eligible = false),
    training_eligible boolean NOT NULL CHECK (training_eligible = false),
    cloud_eligible boolean NOT NULL CHECK (cloud_eligible = false),
    policy_version text NOT NULL CHECK (policy_version = 'data-policy-v1'),
    policy_revision_id uuid NOT NULL,
    policy_decision_source text NOT NULL CHECK (policy_decision_source = 'owner_explicit'),
    policy_authorization_ref text NOT NULL,
    event_id uuid NOT NULL UNIQUE REFERENCES havre.events(event_id),
    trace_id char(32) NOT NULL,
    idempotency_key text NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 200),
    draft_content_hash text NOT NULL CHECK (draft_content_hash ~ '^sha256:[0-9a-f]{64}$'),
    device_binding_id text NOT NULL,
    draft_signing_material text NOT NULL CHECK (length(draft_signing_material) BETWEEN 2 AND 16384),
    device_signature text NOT NULL CHECK (device_signature ~ '^hmac-sha256:[0-9a-f]{64}$'),
    measurement_quality text NOT NULL,
    clock_quality text NOT NULL,
    limitations jsonb NOT NULL,
    canonical_content_material text NOT NULL
        CHECK (length(canonical_content_material) BETWEEN 2 AND 32768),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    UNIQUE (owner_id, observation_id),
    UNIQUE (owner_id, draft_id),
    UNIQUE (owner_id, source_instance_id, idempotency_key),
    FOREIGN KEY (owner_id, source_instance_id)
        REFERENCES havre.context_sources(owner_id, source_instance_id),
    FOREIGN KEY (owner_id, capability_revision_id)
        REFERENCES havre.context_source_capabilities(owner_id, capability_revision_id),
    FOREIGN KEY (owner_id, consent_scope_revision_id)
        REFERENCES havre.context_consent_scope_revisions(owner_id, consent_scope_revision_id),
    FOREIGN KEY (owner_id, trace_id) REFERENCES havre.traces(owner_id, trace_id),
    CHECK (occurred_to > occurred_from),
    CHECK (
      (observation_kind='device_activity_summary' AND source_observed_at>=occurred_to)
      OR
      (observation_kind='calendar_availability_window'
       AND source_observed_at>=occurred_from AND source_observed_at<occurred_to)
    ),
    CHECK (fresh_until > source_observed_at),
    CHECK (retention_expires_at > ingested_at),
    CONSTRAINT life_context_observation_exact_kind_value_check CHECK (
      (capability_id='windows.device_activity_summary.v1'
       AND observation_kind='device_activity_summary'
       AND value ?& ARRAY['active_seconds','activity_state','dominant_category','idle_seconds','sample_count','schema_version','window_seconds']
       AND value-ARRAY['active_seconds','activity_state','dominant_category','idle_seconds','sample_count','schema_version','window_seconds']='{}'::jsonb
       AND value->>'dominant_category' IN ('browser','communication','development','game','media','office','other','system','unknown')
       AND value->>'activity_state' IN ('active','idle','unknown')
       AND (value->>'active_seconds')::integer>=0
       AND (value->>'idle_seconds')::integer>=0
       AND (value->>'sample_count')::integer>0
       AND measurement_quality='coarse_local_aggregate'
       AND clock_quality='host_utc_clock'
       AND limitations='["coarse category only","no application identity or content retained","not an interpretation of intent or productivity"]'::jsonb)
      OR
      (capability_id='calendar.read_availability.v1'
       AND observation_kind='calendar_availability_window'
       AND value ?& ARRAY['busy_intervals','schema_version']
       AND value-ARRAY['busy_intervals','schema_version']='{}'::jsonb
       AND jsonb_typeof(value->'busy_intervals')='array'
       AND jsonb_array_length(value->'busy_intervals')<=512
       AND measurement_quality='owner_supplied_ics_projection'
       AND clock_quality='ics_timezone_normalized'
       AND limitations='["availability only; no subject, body, location, organizer, or attendees retained","owner-supplied snapshot can become outdated until manually replaced","missing calendar data is not negative evidence about the owner"]'::jsonb)
    )
);
CREATE INDEX life_context_observations_owner_time_idx
    ON havre.life_context_observations(owner_id, occurred_to DESC);
CREATE INDEX life_context_observations_source_idx
    ON havre.life_context_observations(owner_id, source_instance_id, occurred_to DESC);
CREATE INDEX life_context_observations_event_idx
    ON havre.life_context_observations(event_id);
CREATE INDEX life_context_observations_capability_fk_idx
    ON havre.life_context_observations(owner_id, capability_revision_id);
CREATE INDEX life_context_observations_consent_fk_idx
    ON havre.life_context_observations(owner_id, consent_scope_revision_id);
CREATE INDEX life_context_observations_trace_fk_idx
    ON havre.life_context_observations(owner_id, trace_id);

CREATE TABLE havre.context_source_health_records (
    health_id uuid PRIMARY KEY,
    health_draft_id uuid NULL,
    schema_version smallint NOT NULL CHECK (schema_version = 2),
    owner_id uuid NOT NULL,
    source_instance_id uuid NOT NULL,
    capability_revision_id uuid NOT NULL,
    status text NOT NULL CHECK (status IN (
        'unknown','healthy','degraded','stale','offline','permission_revoked','unsupported'
    )),
    checked_at timestamptz NOT NULL,
    last_successful_observation_id uuid NULL,
    last_successful_observation_at timestamptz NULL,
    coverage_from timestamptz NULL,
    coverage_to timestamptz NULL,
    safe_error_category text NULL CHECK (
        safe_error_category IS NULL OR length(safe_error_category) BETWEEN 1 AND 100
    ),
    adapter_version text NOT NULL,
    source_version text NOT NULL,
    trace_id char(32) NOT NULL,
    idempotency_key text NULL,
    device_binding_id text NULL,
    draft_signing_material text NULL,
    device_signature text NULL,
    causal_event_id uuid NULL,
    canonical_content_material text NOT NULL
        CHECK (length(canonical_content_material) BETWEEN 2 AND 32768),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (owner_id, health_id),
    UNIQUE (owner_id, source_instance_id, idempotency_key),
    FOREIGN KEY (owner_id, source_instance_id)
        REFERENCES havre.context_sources(owner_id, source_instance_id),
    FOREIGN KEY (owner_id, capability_revision_id)
        REFERENCES havre.context_source_capabilities(owner_id, capability_revision_id),
    FOREIGN KEY (owner_id, last_successful_observation_id)
        REFERENCES havre.life_context_observations(owner_id, observation_id),
    FOREIGN KEY (owner_id, trace_id) REFERENCES havre.traces(owner_id, trace_id),
    FOREIGN KEY (owner_id, causal_event_id)
        REFERENCES havre.events(owner_id, event_id),
    CHECK ((last_successful_observation_id IS NULL) = (last_successful_observation_at IS NULL)),
    CHECK ((coverage_from IS NULL) = (coverage_to IS NULL)),
    CHECK (coverage_from IS NULL OR coverage_to > coverage_from),
    CHECK ((status = 'healthy') = (last_successful_observation_id IS NOT NULL)),
    CHECK (status='healthy' OR (
        last_successful_observation_at IS NULL
        AND coverage_from IS NULL AND coverage_to IS NULL
    )),
    CHECK (
        (health_draft_id IS NULL AND status='healthy'
            AND idempotency_key IS NULL AND device_binding_id IS NULL
            AND draft_signing_material IS NULL AND device_signature IS NULL
            AND causal_event_id IS NOT NULL)
        OR
        (health_draft_id IS NULL AND status='permission_revoked'
            AND safe_error_category='permission_revoked' AND idempotency_key IS NULL
            AND device_binding_id IS NULL AND draft_signing_material IS NULL
            AND device_signature IS NULL AND causal_event_id IS NOT NULL)
        OR
        (health_draft_id IS NOT NULL AND idempotency_key IS NOT NULL
            AND device_binding_id IS NOT NULL AND draft_signing_material IS NOT NULL
            AND device_signature ~ '^hmac-sha256:[0-9a-f]{64}$'
            AND causal_event_id IS NULL)
    )
);
CREATE INDEX context_source_health_owner_source_idx
    ON havre.context_source_health_records(owner_id, source_instance_id, created_at DESC);
CREATE INDEX context_source_health_capability_fk_idx
    ON havre.context_source_health_records(owner_id, capability_revision_id);
CREATE INDEX context_source_health_observation_fk_idx
    ON havre.context_source_health_records(owner_id, last_successful_observation_id);
CREATE INDEX context_source_health_trace_fk_idx
    ON havre.context_source_health_records(owner_id, trace_id);
CREATE INDEX context_source_health_causal_event_fk_idx
    ON havre.context_source_health_records(owner_id, causal_event_id);

CREATE TABLE havre.context_retention_expiry_intents (
    expiry_intent_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    source_event_id uuid NOT NULL,
    observation_id uuid NOT NULL,
    retention_policy_version text NOT NULL,
    retention_expires_at timestamptz NOT NULL,
    planned_at timestamptz NOT NULL,
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    UNIQUE (owner_id, source_event_id),
    UNIQUE (owner_id, observation_id),
    UNIQUE (owner_id, expiry_intent_id)
);

CREATE TABLE havre.context_retention_expiry_receipts (
    expiry_receipt_id uuid PRIMARY KEY,
    expiry_intent_id uuid NOT NULL UNIQUE,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    source_event_id uuid NOT NULL,
    observation_id uuid NOT NULL,
    retention_policy_version text NOT NULL,
    retention_expires_at timestamptz NOT NULL,
    erased_at timestamptz NOT NULL,
    directive_sequence bigint NOT NULL CHECK (directive_sequence > 0),
    directive_hash text NOT NULL CHECK (directive_hash ~ '^sha256:[0-9a-f]{64}$'),
    absence_verified boolean NOT NULL CHECK (absence_verified),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    UNIQUE (owner_id, source_event_id),
    UNIQUE (owner_id, directive_sequence),
    FOREIGN KEY (owner_id, expiry_intent_id)
        REFERENCES havre.context_retention_expiry_intents(owner_id, expiry_intent_id)
);
CREATE INDEX context_retention_receipts_intent_fk_idx
    ON havre.context_retention_expiry_receipts(owner_id, expiry_intent_id);

CREATE FUNCTION havre.guard_context_source_state_revision() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,havre AS $$
DECLARE
    source_row havre.context_sources%ROWTYPE;
    event_row havre.events%ROWTYPE;
    prior_revision integer;
    prior_status text;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'context-source:' || NEW.owner_id::text || ':' || NEW.source_instance_id::text, 0
    ));
    SELECT * INTO STRICT source_row FROM havre.context_sources
        WHERE owner_id=NEW.owner_id AND source_instance_id=NEW.source_instance_id;
    SELECT * INTO STRICT event_row FROM havre.events WHERE event_id=NEW.decision_event_id;
    SELECT revision,status INTO prior_revision,prior_status
    FROM havre.context_source_state_revisions
    WHERE owner_id=NEW.owner_id AND source_instance_id=NEW.source_instance_id
    ORDER BY revision DESC LIMIT 1;
    IF (prior_revision IS NULL AND NEW.revision <> 1)
       OR (prior_revision IS NOT NULL AND NEW.revision <> prior_revision + 1) THEN
        RAISE EXCEPTION 'source state revisions must be contiguous' USING ERRCODE='55000';
    END IF;
    IF prior_revision IS NOT NULL AND (
        NEW.status<>'disabled' OR prior_status='disabled'
    ) THEN
        RAISE EXCEPTION 'disabled source is terminal; enroll a new source'
            USING ERRCODE='55000';
    END IF;
    IF event_row.owner_id <> NEW.owner_id
       OR event_row.event_type <> 'CONTEXT_SOURCE_STATE_REVISED'
       OR event_row.payload->>'source_instance_id' <> NEW.source_instance_id::text
       OR event_row.payload->>'state_revision_id' <> NEW.state_revision_id::text
       OR (event_row.payload->>'revision')::integer <> NEW.revision
       OR event_row.payload->>'action' <> NEW.status
       OR event_row.payload->>'reason' <> NEW.reason
       OR event_row.payload->>'source_content_hash' <> source_row.content_hash
       OR event_row.payload->>'state_content_hash' <> NEW.content_hash
       OR event_row.policy_authorization_ref <> NEW.authorization_ref THEN
        RAISE EXCEPTION 'source state event mismatch' USING ERRCODE='55000';
    END IF;
    IF NEW.revision=1 AND source_row.registration_event_id <> NEW.decision_event_id THEN
        RAISE EXCEPTION 'source registration event mismatch' USING ERRCODE='55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION havre.guard_context_source_registration() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,havre AS $$
DECLARE
    expected_hash text;
BEGIN
    IF EXISTS (
        SELECT 1 FROM havre.context_source_erasure_tombstones tombstone
        WHERE tombstone.owner_id=NEW.owner_id
          AND tombstone.source_instance_id=NEW.source_instance_id
    ) THEN
        RAISE EXCEPTION 'erased context source identity cannot be reused'
            USING ERRCODE='55000';
    END IF;
    expected_hash := 'sha256:' || encode(public.digest(convert_to(havre.canonical_jsonb(
        jsonb_build_object(
            'schema_version', NEW.schema_version,
            'source_instance_id', NEW.source_instance_id::text,
            'owner_id', NEW.owner_id::text,
            'source_kind', NEW.source_kind,
            'provider_id', NEW.provider_id,
            'device_binding_id', NEW.device_binding_id,
            'adapter_version', NEW.adapter_version,
            'source_version', NEW.source_version,
            'provider_tenant_binding', NEW.provider_tenant_binding,
            'provider_account_binding', NEW.provider_account_binding,
            'enrollment_status', NEW.enrollment_status
        )
    ), 'UTF8'), 'sha256'), 'hex');
    IF NEW.content_hash <> expected_hash THEN
        RAISE EXCEPTION 'context source canonical hash mismatch'
            USING ERRCODE='55000';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER context_source_registration_guard BEFORE INSERT
ON havre.context_sources FOR EACH ROW
EXECUTE FUNCTION havre.guard_context_source_registration();
CREATE TRIGGER context_source_state_guard BEFORE INSERT
ON havre.context_source_state_revisions FOR EACH ROW
EXECUTE FUNCTION havre.guard_context_source_state_revision();

CREATE FUNCTION havre.guard_context_capability_state_revision() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,havre AS $$
DECLARE
    capability_row havre.context_source_capabilities%ROWTYPE;
    event_row havre.events%ROWTYPE;
    prior_revision integer;
    prior_status text;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'context-capability:' || NEW.owner_id::text || ':' || NEW.capability_revision_id::text, 0
    ));
    SELECT * INTO STRICT capability_row FROM havre.context_source_capabilities
        WHERE owner_id=NEW.owner_id AND capability_revision_id=NEW.capability_revision_id;
    SELECT * INTO STRICT event_row FROM havre.events WHERE event_id=NEW.decision_event_id;
    SELECT revision,status INTO prior_revision,prior_status
    FROM havre.context_capability_state_revisions
    WHERE owner_id=NEW.owner_id AND capability_revision_id=NEW.capability_revision_id
    ORDER BY revision DESC LIMIT 1;
    IF (prior_revision IS NULL AND NEW.revision <> 1)
       OR (prior_revision IS NOT NULL AND NEW.revision <> prior_revision + 1) THEN
        RAISE EXCEPTION 'capability state revisions must be contiguous' USING ERRCODE='55000';
    END IF;
    IF prior_revision IS NOT NULL AND (
        NEW.status<>'disabled' OR prior_status='disabled'
    ) THEN
        RAISE EXCEPTION 'disabled capability is terminal; register a new revision'
            USING ERRCODE='55000';
    END IF;
    IF event_row.owner_id <> NEW.owner_id
       OR event_row.event_type <> 'CONTEXT_CAPABILITY_STATE_REVISED'
       OR event_row.payload->>'source_instance_id' <> capability_row.source_instance_id::text
       OR event_row.payload->>'capability_revision_id' <> NEW.capability_revision_id::text
       OR event_row.payload->>'state_revision_id' <> NEW.state_revision_id::text
       OR (event_row.payload->>'revision')::integer <> NEW.revision
       OR event_row.payload->>'action' <> NEW.status
       OR event_row.payload->>'reason' <> NEW.reason
       OR event_row.payload->>'capability_content_hash' <> capability_row.content_hash
       OR event_row.payload->>'state_content_hash' <> NEW.content_hash
       OR event_row.policy_authorization_ref <> NEW.authorization_ref THEN
        RAISE EXCEPTION 'capability state event mismatch' USING ERRCODE='55000';
    END IF;
    IF NEW.revision=1 AND capability_row.registration_event_id <> NEW.decision_event_id THEN
        RAISE EXCEPTION 'capability registration event mismatch' USING ERRCODE='55000';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER context_capability_state_guard BEFORE INSERT
ON havre.context_capability_state_revisions FOR EACH ROW
EXECUTE FUNCTION havre.guard_context_capability_state_revision();

CREATE FUNCTION havre.guard_context_consent_revision() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,havre AS $$
DECLARE
    event_row havre.events%ROWTYPE;
    capability_row havre.context_source_capabilities%ROWTYPE;
    source_status text;
    capability_status text;
    prior_revision integer;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'context-consent-semantic:' || NEW.owner_id::text || ':' ||
        NEW.source_instance_id::text || ':' || NEW.capability_revision_id::text || ':' ||
        NEW.purpose, 0
    ));
    SELECT * INTO STRICT event_row FROM havre.events WHERE event_id=NEW.decision_event_id;
    SELECT * INTO STRICT capability_row FROM havre.context_source_capabilities
        WHERE owner_id=NEW.owner_id AND capability_revision_id=NEW.capability_revision_id;
    SELECT status INTO STRICT source_status FROM havre.context_source_state_revisions
        WHERE owner_id=NEW.owner_id AND source_instance_id=NEW.source_instance_id
        ORDER BY revision DESC LIMIT 1;
    SELECT status INTO STRICT capability_status FROM havre.context_capability_state_revisions
        WHERE owner_id=NEW.owner_id AND capability_revision_id=NEW.capability_revision_id
        ORDER BY revision DESC LIMIT 1;
    IF capability_row.source_instance_id <> NEW.source_instance_id
       OR source_status <> 'enabled' OR capability_status <> 'enabled'
       OR NEW.allowed_observation_kinds <> jsonb_build_array(capability_row.observation_kind)
       OR NEW.allowed_fields <> capability_row.allowed_fields
       OR NOT capability_row.sampling_modes ? (NEW.sampling_policy->>'mode') THEN
        RAISE EXCEPTION 'consent source/capability is disabled' USING ERRCODE='55000';
    END IF;
    IF EXISTS (
        SELECT 1 FROM havre.context_consent_scope_revisions existing
        WHERE existing.owner_id=NEW.owner_id
          AND existing.source_instance_id=NEW.source_instance_id
          AND existing.capability_revision_id=NEW.capability_revision_id
          AND existing.purpose=NEW.purpose
          AND existing.consent_scope_id<>NEW.consent_scope_id
    ) THEN
        RAISE EXCEPTION 'parallel consent scopes are forbidden' USING ERRCODE='55000';
    END IF;
    SELECT max(revision) INTO prior_revision FROM havre.context_consent_scope_revisions
        WHERE owner_id=NEW.owner_id AND consent_scope_id=NEW.consent_scope_id;
    IF (prior_revision IS NULL AND NEW.revision <> 1)
       OR (prior_revision IS NOT NULL AND NEW.revision <> prior_revision + 1) THEN
        RAISE EXCEPTION 'consent revisions must be contiguous' USING ERRCODE='55000';
    END IF;
    IF event_row.owner_id <> NEW.owner_id
       OR event_row.event_type <> 'CONTEXT_CONSENT_REVISED'
       OR event_row.payload->>'consent_scope_revision_id' <> NEW.consent_scope_revision_id::text
       OR event_row.payload->>'consent_scope_id' <> NEW.consent_scope_id::text
       OR (event_row.payload->>'revision')::integer <> NEW.revision
       OR event_row.payload->>'source_instance_id' <> NEW.source_instance_id::text
       OR event_row.payload->>'capability_revision_id' <> NEW.capability_revision_id::text
       OR event_row.payload->>'consent_content_hash' <> NEW.content_hash
       OR event_row.privacy_class <> NEW.data_policy->>'privacy_class'
       OR event_row.policy_authorization_ref <> NEW.authorization_ref THEN
        RAISE EXCEPTION 'consent decision event mismatch' USING ERRCODE='55000';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER context_consent_guard BEFORE INSERT
ON havre.context_consent_scope_revisions FOR EACH ROW
EXECUTE FUNCTION havre.guard_context_consent_revision();

CREATE FUNCTION havre.guard_life_context_observation() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,havre AS $$
DECLARE
    source_row havre.context_sources%ROWTYPE;
    capability_row havre.context_source_capabilities%ROWTYPE;
    consent_row havre.context_consent_scope_revisions%ROWTYPE;
    event_row havre.events%ROWTYPE;
    binding_row havre.context_device_bindings%ROWTYPE;
    source_status text;
    capability_status text;
    latest_consent_revision integer;
    sampling_interval integer;
    summary_window integer;
    lookback_seconds integer;
    lookahead_seconds integer;
    skew_seconds integer;
    offline_seconds integer;
    interval_item jsonb;
    interval_start timestamptz;
    interval_end timestamptz;
    prior_interval_start timestamptz;
    prior_interval_end timestamptz;
    prior_availability text;
    signed jsonb;
    canonical jsonb;
BEGIN
    SELECT * INTO STRICT consent_row FROM havre.context_consent_scope_revisions
        WHERE owner_id=NEW.owner_id AND consent_scope_revision_id=NEW.consent_scope_revision_id;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'context-consent-semantic:' || NEW.owner_id::text || ':' ||
        consent_row.source_instance_id::text || ':' ||
        consent_row.capability_revision_id::text || ':' || consent_row.purpose, 0
    ));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'context-source:' || NEW.owner_id::text || ':' || NEW.source_instance_id::text, 0
    ));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'context-capability:' || NEW.owner_id::text || ':' || NEW.capability_revision_id::text, 0
    ));
    SELECT * INTO STRICT source_row FROM havre.context_sources
        WHERE owner_id=NEW.owner_id AND source_instance_id=NEW.source_instance_id;
    IF EXISTS (
        SELECT 1 FROM havre.context_restore_quarantines quarantine
        WHERE quarantine.owner_id=NEW.owner_id
          AND quarantine.source_instance_id=NEW.source_instance_id
    ) THEN
        RAISE EXCEPTION 'restored context source requires new enrollment'
            USING ERRCODE='55000';
    END IF;
    SELECT * INTO STRICT capability_row FROM havre.context_source_capabilities
        WHERE owner_id=NEW.owner_id AND capability_revision_id=NEW.capability_revision_id;
    SELECT * INTO STRICT event_row FROM havre.events WHERE event_id=NEW.event_id;
    SELECT * INTO STRICT binding_row FROM havre.context_device_bindings
        WHERE owner_id=NEW.owner_id AND source_instance_id=NEW.source_instance_id
          AND device_binding_id=NEW.device_binding_id AND status='enabled';
    SELECT status INTO STRICT source_status FROM havre.context_source_state_revisions
        WHERE owner_id=NEW.owner_id AND source_instance_id=NEW.source_instance_id
          AND effective_at <= statement_timestamp() ORDER BY revision DESC LIMIT 1;
    SELECT status INTO STRICT capability_status FROM havre.context_capability_state_revisions
        WHERE owner_id=NEW.owner_id AND capability_revision_id=NEW.capability_revision_id
          AND effective_at <= statement_timestamp() ORDER BY revision DESC LIMIT 1;
    SELECT max(revision) INTO latest_consent_revision
        FROM havre.context_consent_scope_revisions
        WHERE owner_id=NEW.owner_id AND consent_scope_id=consent_row.consent_scope_id;

    IF source_status <> 'enabled' OR capability_status <> 'enabled'
       OR capability_row.source_instance_id <> NEW.source_instance_id
       OR capability_row.capability_id <> NEW.capability_id
       OR capability_row.observation_kind <> NEW.observation_kind
       OR source_row.device_binding_id <> NEW.device_binding_id
       OR source_row.adapter_version <> NEW.adapter_version THEN
        RAISE EXCEPTION 'source, device, or capability is not eligible' USING ERRCODE='55000';
    END IF;
    IF consent_row.status <> 'active'
       OR consent_row.revision <> latest_consent_revision
       OR statement_timestamp() < consent_row.effective_at
       OR statement_timestamp() >= consent_row.expires_at
       OR consent_row.source_instance_id <> NEW.source_instance_id
       OR consent_row.capability_revision_id <> NEW.capability_revision_id
       OR consent_row.sampling_policy->>'policy_version' <> NEW.sampling_policy_version
       OR consent_row.retention_policy->>'policy_version' <> NEW.retention_policy_version THEN
        RAISE EXCEPTION 'current active consent is required' USING ERRCODE='55000';
    END IF;

    signed := NEW.draft_signing_material::jsonb;
    IF NEW.draft_signing_material<>havre.canonical_jsonb(signed)
       OR signed - ARRAY[
          'schema_version','draft_id','owner_id','source_instance_id',
          'device_binding_id','capability_revision_id','capability_id',
          'observation_kind','observation_schema_version','value','occurred_from',
          'occurred_to','source_observed_at','consent_scope_revision_id',
          'sampling_policy_version','retention_policy_version','adapter_version',
          'data_policy','idempotency_key','trace_id'
       ] <> '{}'::jsonb
       OR (signed->>'schema_version')::integer <> 1
       OR signed->>'draft_id' <> NEW.draft_id::text
       OR signed->>'owner_id' <> NEW.owner_id::text
       OR signed->>'source_instance_id' <> NEW.source_instance_id::text
       OR signed->>'device_binding_id' <> NEW.device_binding_id
       OR signed->>'capability_revision_id' <> NEW.capability_revision_id::text
       OR signed->>'capability_id' <> NEW.capability_id
       OR signed->>'observation_kind' <> NEW.observation_kind
       OR (signed->>'observation_schema_version')::integer <> NEW.observation_schema_version
       OR signed->'value' <> NEW.value
       OR signed->>'occurred_from' <> havre.utc_json_timestamp(NEW.occurred_from)
       OR signed->>'occurred_to' <> havre.utc_json_timestamp(NEW.occurred_to)
       OR signed->>'source_observed_at' <> havre.utc_json_timestamp(NEW.source_observed_at)
       OR signed->>'consent_scope_revision_id' <> NEW.consent_scope_revision_id::text
       OR signed->>'sampling_policy_version' <> NEW.sampling_policy_version
       OR signed->>'retention_policy_version' <> NEW.retention_policy_version
       OR signed->>'adapter_version' <> NEW.adapter_version
       OR signed->'data_policy' <> consent_row.data_policy
       OR signed->>'idempotency_key' <> NEW.idempotency_key
       OR signed->>'trace_id' <> btrim(NEW.trace_id)
       OR NEW.draft_content_hash <> 'sha256:' || encode(
            public.digest(convert_to(NEW.draft_signing_material, 'UTF8'), 'sha256'), 'hex'
       )
       OR decode(substring(NEW.device_signature from 13), 'hex') <> public.hmac(
            convert_to(NEW.draft_signing_material, 'UTF8'),
            binding_row.signing_secret, 'sha256'
       ) THEN
        RAISE EXCEPTION 'signed device draft mismatch' USING ERRCODE='55000';
    END IF;

    skew_seconds := (consent_row.sampling_policy->>'max_clock_skew_seconds')::integer;
    offline_seconds := (consent_row.sampling_policy->>'offline_buffer_seconds')::integer;
    IF abs(extract(epoch FROM (NEW.ingested_at - statement_timestamp()))) > 5
       OR NEW.source_observed_at > statement_timestamp() + make_interval(secs=>skew_seconds)
       OR NEW.source_observed_at < statement_timestamp() - make_interval(secs=>offline_seconds)
       OR NEW.retention_expires_at <> NEW.ingested_at
            + make_interval(days=>(consent_row.retention_policy->>'canonical_retention_days')::integer) THEN
        RAISE EXCEPTION 'clock, coverage, freshness, or retention mismatch' USING ERRCODE='55000';
    END IF;
    IF NEW.observation_kind='device_activity_summary' THEN
        sampling_interval := (consent_row.sampling_policy->>'sample_interval_seconds')::integer;
        summary_window := (consent_row.sampling_policy->>'summary_window_seconds')::integer;
        IF NEW.source_observed_at - NEW.occurred_to > make_interval(secs=>skew_seconds)
           OR NEW.occurred_to - NEW.occurred_from <> make_interval(secs=>summary_window)
           OR (NEW.value->>'window_seconds')::integer <> summary_window
           OR (NEW.value->>'sample_count')::integer <> summary_window/sampling_interval
           OR (NEW.value->>'active_seconds')::integer+(NEW.value->>'idle_seconds')::integer
                <> summary_window
           OR NEW.fresh_until <> NEW.occurred_to
                + make_interval(secs=>(consent_row.sampling_policy->>'fresh_for_seconds')::integer) THEN
            RAISE EXCEPTION 'Windows clock, coverage, or freshness mismatch'
                USING ERRCODE='55000';
        END IF;
    ELSIF NEW.observation_kind='calendar_availability_window' THEN
        IF consent_row.sampling_policy->>'mode'<>'owner_initiated_import'
           OR NEW.source_observed_at >= NEW.occurred_to
           OR NEW.occurred_to > consent_row.expires_at
           OR extract(epoch FROM (NEW.occurred_to-NEW.occurred_from))
                > (consent_row.sampling_policy->>'max_coverage_seconds')::integer
           OR NEW.fresh_until <> NEW.occurred_to THEN
            RAISE EXCEPTION 'Calendar clock, coverage, or freshness mismatch'
                USING ERRCODE='55000';
        END IF;
        FOR interval_item IN SELECT value FROM jsonb_array_elements(NEW.value->'busy_intervals')
        LOOP
            IF jsonb_typeof(interval_item)<>'object'
               OR NOT interval_item ?& ARRAY['starts_at','ends_at','availability','is_all_day']
               OR interval_item-ARRAY['starts_at','ends_at','availability','is_all_day']<>'{}'::jsonb
               OR jsonb_typeof(interval_item->'is_all_day')<>'boolean'
               OR interval_item->>'availability' NOT IN (
                    'busy','tentative','out_of_office','working_elsewhere'
               ) THEN
                RAISE EXCEPTION 'Calendar interval shape is invalid' USING ERRCODE='55000';
            END IF;
            interval_start := (interval_item->>'starts_at')::timestamptz;
            interval_end := (interval_item->>'ends_at')::timestamptz;
            IF interval_item->>'starts_at'<>havre.utc_json_timestamp(interval_start)
               OR interval_item->>'ends_at'<>havre.utc_json_timestamp(interval_end)
               OR interval_start<NEW.occurred_from OR interval_end>NEW.occurred_to
               OR interval_end<=interval_start
               OR (prior_interval_start IS NOT NULL AND (
                    interval_start<prior_interval_start
                    OR (interval_start=prior_interval_start AND interval_end<prior_interval_end)
                    OR (interval_start=prior_interval_start AND interval_end=prior_interval_end
                        AND interval_item->>'availability'<prior_availability)
               )) THEN
                RAISE EXCEPTION 'Calendar interval time or ordering is invalid'
                    USING ERRCODE='55000';
            END IF;
            prior_interval_start := interval_start;
            prior_interval_end := interval_end;
            prior_availability := interval_item->>'availability';
        END LOOP;
    ELSE
        RAISE EXCEPTION 'unsupported context observation kind' USING ERRCODE='55000';
    END IF;
    canonical := NEW.canonical_content_material::jsonb;
    IF NEW.canonical_content_material<>havre.canonical_jsonb(canonical)
       OR NOT canonical ?& ARRAY[
          'schema_version','observation_id','draft_id','owner_id',
          'source_instance_id','capability_revision_id','capability_id',
          'observation_kind','observation_schema_version','value','occurred_from',
          'occurred_to','source_observed_at','ingested_at','fresh_until',
          'retention_expires_at','consent_scope_revision_id',
          'sampling_policy_version','retention_policy_version','adapter_version',
          'data_policy','event_id','trace_id','idempotency_key',
          'draft_content_hash','device_binding_id','draft_signing_material',
          'device_signature','measurement_quality','clock_quality','limitations'
       ]
       OR canonical - ARRAY[
          'schema_version','observation_id','draft_id','owner_id',
          'source_instance_id','capability_revision_id','capability_id',
          'observation_kind','observation_schema_version','value','occurred_from',
          'occurred_to','source_observed_at','ingested_at','fresh_until',
          'retention_expires_at','consent_scope_revision_id',
          'sampling_policy_version','retention_policy_version','adapter_version',
          'data_policy','event_id','trace_id','idempotency_key',
          'draft_content_hash','device_binding_id','draft_signing_material',
          'device_signature','measurement_quality','clock_quality','limitations'
       ] <> '{}'::jsonb
       OR (canonical->>'schema_version')::integer<>NEW.schema_version
       OR canonical->>'observation_id'<>NEW.observation_id::text
       OR canonical->>'draft_id'<>NEW.draft_id::text
       OR canonical->>'owner_id'<>NEW.owner_id::text
       OR canonical->>'source_instance_id'<>NEW.source_instance_id::text
       OR canonical->>'capability_revision_id'<>NEW.capability_revision_id::text
       OR canonical->>'capability_id'<>NEW.capability_id
       OR canonical->>'observation_kind'<>NEW.observation_kind
       OR (canonical->>'observation_schema_version')::integer<>NEW.observation_schema_version
       OR canonical->'value'<>NEW.value
       OR canonical->>'occurred_from'<>havre.utc_json_timestamp(NEW.occurred_from)
       OR canonical->>'occurred_to'<>havre.utc_json_timestamp(NEW.occurred_to)
       OR canonical->>'source_observed_at'<>havre.utc_json_timestamp(NEW.source_observed_at)
       OR canonical->>'ingested_at'<>havre.utc_json_timestamp(NEW.ingested_at)
       OR canonical->>'fresh_until'<>havre.utc_json_timestamp(NEW.fresh_until)
       OR canonical->>'retention_expires_at'<>havre.utc_json_timestamp(NEW.retention_expires_at)
       OR canonical->>'consent_scope_revision_id'<>NEW.consent_scope_revision_id::text
       OR canonical->>'sampling_policy_version'<>NEW.sampling_policy_version
       OR canonical->>'retention_policy_version'<>NEW.retention_policy_version
       OR canonical->>'adapter_version'<>NEW.adapter_version
       OR canonical->'data_policy'<>jsonb_build_object(
            'schema_version',1,
            'policy_revision_id',NEW.policy_revision_id::text,
            'privacy_class',NEW.privacy_class,
            'memory_eligible',NEW.memory_eligible,
            'training_eligible',NEW.training_eligible,
            'cloud_eligible',NEW.cloud_eligible,
            'policy_version',NEW.policy_version,
            'decision_source',NEW.policy_decision_source,
            'authorization_ref',NEW.policy_authorization_ref
       )
       OR canonical->>'event_id'<>NEW.event_id::text
       OR canonical->>'trace_id'<>btrim(NEW.trace_id)
       OR canonical->>'idempotency_key'<>NEW.idempotency_key
       OR canonical->>'draft_content_hash'<>NEW.draft_content_hash
       OR canonical->>'device_binding_id'<>NEW.device_binding_id
       OR canonical->>'draft_signing_material'<>NEW.draft_signing_material
       OR canonical->>'device_signature'<>NEW.device_signature
       OR canonical->>'measurement_quality'<>NEW.measurement_quality
       OR canonical->>'clock_quality'<>NEW.clock_quality
       OR canonical->'limitations'<>NEW.limitations
       OR NEW.content_hash<>'sha256:' || encode(
            public.digest(convert_to(NEW.canonical_content_material,'UTF8'),'sha256'),'hex'
       ) THEN
        RAISE EXCEPTION 'canonical observation material or content hash mismatch'
            USING ERRCODE='55000';
    END IF;
    IF event_row.owner_id <> NEW.owner_id OR event_row.trace_id <> NEW.trace_id
       OR event_row.event_type <> 'LIFE_CONTEXT_OBSERVED'
       OR event_row.payload->>'observation_id' <> NEW.observation_id::text
       OR event_row.payload->>'observation_content_hash' <> NEW.content_hash
       OR event_row.payload->>'source_instance_id' <> NEW.source_instance_id::text
       OR event_row.payload->>'capability_revision_id' <> NEW.capability_revision_id::text
       OR event_row.payload->>'consent_scope_revision_id' <> NEW.consent_scope_revision_id::text
       OR event_row.privacy_class <> NEW.privacy_class
       OR event_row.policy_revision_id <> NEW.policy_revision_id THEN
        RAISE EXCEPTION 'life context event mismatch' USING ERRCODE='55000';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER life_context_observation_guard BEFORE INSERT
ON havre.life_context_observations FOR EACH ROW
EXECUTE FUNCTION havre.guard_life_context_observation();

CREATE FUNCTION havre.guard_context_source_health() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,havre AS $$
DECLARE
    observation_row havre.life_context_observations%ROWTYPE;
    source_row havre.context_sources%ROWTYPE;
    capability_row havre.context_source_capabilities%ROWTYPE;
    causal_event havre.events%ROWTYPE;
    binding_secret bytea;
    source_status text;
    capability_status text;
    prior_checked_at timestamptz;
    canonical jsonb;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'context-source:' || NEW.owner_id::text || ':' || NEW.source_instance_id::text, 0
    ));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'context-capability:' || NEW.owner_id::text || ':' || NEW.capability_revision_id::text, 0
    ));
    SELECT * INTO STRICT source_row FROM havre.context_sources
        WHERE owner_id=NEW.owner_id AND source_instance_id=NEW.source_instance_id;
    SELECT * INTO STRICT capability_row FROM havre.context_source_capabilities
        WHERE owner_id=NEW.owner_id
          AND capability_revision_id=NEW.capability_revision_id;
    IF EXISTS (
        SELECT 1 FROM havre.context_restore_quarantines quarantine
        WHERE quarantine.owner_id=NEW.owner_id
          AND quarantine.source_instance_id=NEW.source_instance_id
    ) THEN
        RAISE EXCEPTION 'restored context source requires new enrollment'
            USING ERRCODE='55000';
    END IF;
    SELECT status INTO STRICT source_status FROM havre.context_source_state_revisions
        WHERE owner_id=NEW.owner_id AND source_instance_id=NEW.source_instance_id
          AND effective_at<=statement_timestamp() ORDER BY revision DESC LIMIT 1;
    SELECT status INTO STRICT capability_status FROM havre.context_capability_state_revisions
        WHERE owner_id=NEW.owner_id AND capability_revision_id=NEW.capability_revision_id
          AND effective_at<=statement_timestamp() ORDER BY revision DESC LIMIT 1;
    SELECT max(checked_at) INTO prior_checked_at
    FROM havre.context_source_health_records
    WHERE owner_id=NEW.owner_id
      AND source_instance_id=NEW.source_instance_id
      AND capability_revision_id=NEW.capability_revision_id;
    IF source_status <> 'enabled' OR capability_status <> 'enabled'
       OR capability_row.source_instance_id <> NEW.source_instance_id
       OR source_row.adapter_version <> NEW.adapter_version
       OR source_row.source_version <> NEW.source_version
       OR abs(extract(epoch FROM (NEW.checked_at-statement_timestamp()))) > 300
       OR (
            NEW.health_draft_id IS NOT NULL
            AND prior_checked_at IS NOT NULL
            AND NEW.checked_at<=prior_checked_at
       ) THEN
        RAISE EXCEPTION 'source health state or clock is invalid' USING ERRCODE='55000';
    END IF;
    canonical := NEW.canonical_content_material::jsonb;
    IF NEW.canonical_content_material<>havre.canonical_jsonb(canonical)
       OR NOT canonical ?& ARRAY[
          'schema_version','health_id','owner_id','source_instance_id',
          'capability_revision_id','status','checked_at',
          'last_successful_observation_id','last_successful_observation_at',
          'coverage_from','coverage_to','safe_error_category','adapter_version',
          'source_version','trace_id'
       ]
       OR canonical - ARRAY[
          'schema_version','health_id','owner_id','source_instance_id',
          'capability_revision_id','status','checked_at',
          'last_successful_observation_id','last_successful_observation_at',
          'coverage_from','coverage_to','safe_error_category','adapter_version',
          'source_version','trace_id'
       ] <> '{}'::jsonb
       OR (canonical->>'schema_version')::integer<>NEW.schema_version
       OR canonical->>'health_id'<>NEW.health_id::text
       OR canonical->>'owner_id'<>NEW.owner_id::text
       OR canonical->>'source_instance_id'<>NEW.source_instance_id::text
       OR canonical->>'capability_revision_id'<>NEW.capability_revision_id::text
       OR canonical->>'status'<>NEW.status
       OR canonical->>'checked_at'<>havre.utc_json_timestamp(NEW.checked_at)
       OR canonical->>'last_successful_observation_id'
            IS DISTINCT FROM NEW.last_successful_observation_id::text
       OR canonical->>'last_successful_observation_at'
            IS DISTINCT FROM (CASE WHEN NEW.last_successful_observation_at IS NULL
                THEN NULL ELSE havre.utc_json_timestamp(NEW.last_successful_observation_at) END)
       OR canonical->>'coverage_from'
            IS DISTINCT FROM (CASE WHEN NEW.coverage_from IS NULL
                THEN NULL ELSE havre.utc_json_timestamp(NEW.coverage_from) END)
       OR canonical->>'coverage_to'
            IS DISTINCT FROM (CASE WHEN NEW.coverage_to IS NULL
                THEN NULL ELSE havre.utc_json_timestamp(NEW.coverage_to) END)
       OR canonical->>'safe_error_category' IS DISTINCT FROM NEW.safe_error_category
       OR canonical->>'adapter_version'<>NEW.adapter_version
       OR canonical->>'source_version'<>NEW.source_version
       OR canonical->>'trace_id'<>btrim(NEW.trace_id)
       OR NEW.content_hash<>'sha256:' || encode(
            public.digest(convert_to(NEW.canonical_content_material,'UTF8'),'sha256'),'hex'
       ) THEN
        RAISE EXCEPTION 'canonical source health material or content hash mismatch'
            USING ERRCODE='55000';
    END IF;
    IF NEW.status='healthy' THEN
        SELECT * INTO STRICT observation_row FROM havre.life_context_observations
            WHERE owner_id=NEW.owner_id
              AND observation_id=NEW.last_successful_observation_id;
        IF observation_row.source_instance_id <> NEW.source_instance_id
           OR observation_row.capability_revision_id <> NEW.capability_revision_id
           OR NEW.last_successful_observation_at <> observation_row.source_observed_at
           OR NEW.coverage_from <> observation_row.occurred_from
           OR NEW.coverage_to <> observation_row.occurred_to
           OR NEW.safe_error_category IS NOT NULL
           OR NEW.causal_event_id<>observation_row.event_id THEN
            RAISE EXCEPTION 'healthy source record does not match observation' USING ERRCODE='55000';
        END IF;
    ELSIF NEW.health_draft_id IS NULL THEN
        IF NEW.status <> 'permission_revoked'
           OR NEW.safe_error_category <> 'permission_revoked' THEN
            RAISE EXCEPTION 'unsigned health is limited to Core revocation' USING ERRCODE='55000';
        END IF;
        SELECT * INTO STRICT causal_event FROM havre.events
        WHERE owner_id=NEW.owner_id AND event_id=NEW.causal_event_id;
        IF causal_event.event_type<>'CONTEXT_SOURCE_STATE_REVISED'
           OR causal_event.payload->>'source_instance_id'<>NEW.source_instance_id::text
           OR causal_event.payload->>'action'<>'disabled' THEN
            RAISE EXCEPTION 'unsigned revocation health requires its disable event'
                USING ERRCODE='55000';
        END IF;
    ELSE
        SELECT signing_secret INTO STRICT binding_secret
        FROM havre.context_device_bindings
        WHERE owner_id=NEW.owner_id AND source_instance_id=NEW.source_instance_id
          AND device_binding_id=NEW.device_binding_id AND status='enabled';
        IF NEW.draft_signing_material<>havre.canonical_jsonb(NEW.draft_signing_material::jsonb)
           OR NOT NEW.draft_signing_material::jsonb ?& ARRAY[
              'schema_version','draft_id','owner_id','source_instance_id',
              'device_binding_id','capability_revision_id','status','checked_at',
              'safe_error_category','adapter_version','source_version',
              'idempotency_key','trace_id'
           ]
           OR NEW.draft_signing_material::jsonb - ARRAY[
              'schema_version','draft_id','owner_id','source_instance_id',
              'device_binding_id','capability_revision_id','status','checked_at',
              'safe_error_category','adapter_version','source_version',
              'idempotency_key','trace_id'
           ] <> '{}'::jsonb
           OR (NEW.draft_signing_material::jsonb->>'schema_version')::integer <> 1
           OR NEW.draft_signing_material::jsonb->>'draft_id' <> NEW.health_draft_id::text
           OR NEW.draft_signing_material::jsonb->>'owner_id' <> NEW.owner_id::text
           OR NEW.draft_signing_material::jsonb->>'source_instance_id' <> NEW.source_instance_id::text
           OR NEW.draft_signing_material::jsonb->>'capability_revision_id' <> NEW.capability_revision_id::text
           OR NEW.draft_signing_material::jsonb->>'status' <> NEW.status
           OR NEW.draft_signing_material::jsonb->>'checked_at' <> havre.utc_json_timestamp(NEW.checked_at)
           OR NEW.draft_signing_material::jsonb->>'safe_error_category' <> NEW.safe_error_category
           OR NEW.draft_signing_material::jsonb->>'device_binding_id' <> NEW.device_binding_id
           OR NEW.draft_signing_material::jsonb->>'adapter_version' <> NEW.adapter_version
           OR NEW.draft_signing_material::jsonb->>'source_version' <> NEW.source_version
           OR NEW.draft_signing_material::jsonb->>'idempotency_key' <> NEW.idempotency_key
           OR NEW.draft_signing_material::jsonb->>'trace_id' <> btrim(NEW.trace_id)
           OR decode(substring(NEW.device_signature from 13), 'hex') <> public.hmac(
                convert_to(NEW.draft_signing_material, 'UTF8'), binding_secret, 'sha256'
           ) THEN
            RAISE EXCEPTION 'signed source health draft mismatch' USING ERRCODE='55000';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER context_source_health_guard BEFORE INSERT
ON havre.context_source_health_records FOR EACH ROW
EXECUTE FUNCTION havre.guard_context_source_health();

CREATE FUNCTION havre.guard_context_retention_expiry_intent() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    observation_row havre.life_context_observations%ROWTYPE;
BEGIN
    SELECT * INTO STRICT observation_row
    FROM havre.life_context_observations
    WHERE owner_id=NEW.owner_id AND observation_id=NEW.observation_id;
    IF observation_row.event_id<>NEW.source_event_id
       OR observation_row.retention_policy_version<>NEW.retention_policy_version
       OR observation_row.retention_expires_at<>NEW.retention_expires_at
       OR NEW.retention_expires_at>statement_timestamp()
       OR abs(extract(epoch FROM (NEW.planned_at-statement_timestamp())))>5 THEN
        RAISE EXCEPTION 'retention expiry intent is not due or is not source-bound'
            USING ERRCODE='55000';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER context_retention_expiry_intent_guard BEFORE INSERT
ON havre.context_retention_expiry_intents FOR EACH ROW
EXECUTE FUNCTION havre.guard_context_retention_expiry_intent();

CREATE FUNCTION havre.guard_context_retention_expiry_receipt() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,havre AS $$
DECLARE
    intent_row havre.context_retention_expiry_intents%ROWTYPE;
    canonical_material text;
BEGIN
    SELECT * INTO intent_row
    FROM havre.context_retention_expiry_intents
    WHERE owner_id=NEW.owner_id AND expiry_intent_id=NEW.expiry_intent_id;
    IF intent_row.expiry_intent_id IS NULL
       OR NEW.source_event_id<>intent_row.source_event_id
       OR NEW.observation_id<>intent_row.observation_id
       OR NEW.retention_policy_version<>intent_row.retention_policy_version
       OR NEW.retention_expires_at<>intent_row.retention_expires_at
       OR NEW.erased_at<NEW.retention_expires_at
       OR abs(extract(epoch FROM (NEW.erased_at-statement_timestamp())))>30
       OR NOT NEW.absence_verified
       OR EXISTS (
            SELECT 1 FROM havre.events
            WHERE owner_id=NEW.owner_id AND event_id=NEW.source_event_id
       )
       OR EXISTS (
            SELECT 1 FROM havre.life_context_observations
            WHERE owner_id=NEW.owner_id AND observation_id=NEW.observation_id
       ) THEN
        RAISE EXCEPTION 'retention receipt is not owner-bound to completed expiry'
            USING ERRCODE='55000';
    END IF;
    canonical_material := havre.canonical_jsonb(jsonb_build_object(
        'schema_version',NEW.schema_version,
        'expiry_receipt_id',NEW.expiry_receipt_id::text,
        'expiry_intent_id',NEW.expiry_intent_id::text,
        'owner_id',NEW.owner_id::text,
        'source_event_id',NEW.source_event_id::text,
        'observation_id',NEW.observation_id::text,
        'retention_policy_version',NEW.retention_policy_version,
        'retention_expires_at',havre.utc_json_timestamp(NEW.retention_expires_at),
        'erased_at',havre.utc_json_timestamp(NEW.erased_at),
        'directive_sequence',NEW.directive_sequence,
        'directive_hash',NEW.directive_hash,
        'absence_verified',NEW.absence_verified
    ));
    IF NEW.content_hash<>'sha256:' || encode(
        public.digest(convert_to(canonical_material,'UTF8'),'sha256'),'hex'
    ) THEN
        RAISE EXCEPTION 'retention receipt content hash mismatch' USING ERRCODE='55000';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER context_retention_expiry_receipt_guard BEFORE INSERT
ON havre.context_retention_expiry_receipts FOR EACH ROW
EXECUTE FUNCTION havre.guard_context_retention_expiry_receipt();

CREATE FUNCTION havre.guard_context_source_erasure_tombstone() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    canonical_material text;
BEGIN
    canonical_material := havre.canonical_jsonb(jsonb_build_object(
        'schema_version',NEW.schema_version,
        'tombstone_id',NEW.tombstone_id::text,
        'owner_id',NEW.owner_id::text,
        'source_instance_id',NEW.source_instance_id::text,
        'registration_event_id',NEW.registration_event_id::text,
        'erased_at',havre.utc_json_timestamp(NEW.erased_at),
        'directive_sequence',NEW.directive_sequence,
        'directive_hash',NEW.directive_hash,
        'absence_verified',NEW.absence_verified
    ));
    IF abs(extract(epoch FROM (NEW.erased_at-statement_timestamp())))>30
       OR NEW.content_hash<>'sha256:' || encode(
            public.digest(convert_to(canonical_material,'UTF8'),'sha256'),'hex'
       ) THEN
        RAISE EXCEPTION 'context source erasure tombstone mismatch'
            USING ERRCODE='55000';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER context_source_erasure_tombstone_guard BEFORE INSERT
ON havre.context_source_erasure_tombstones FOR EACH ROW
EXECUTE FUNCTION havre.guard_context_source_erasure_tombstone();

CREATE TRIGGER context_restore_quarantines_immutable BEFORE UPDATE OR DELETE
ON havre.context_restore_quarantines FOR EACH ROW
EXECUTE FUNCTION havre.reject_mutation();
CREATE FUNCTION havre.reject_context_tombstone_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'context source erasure tombstones are immutable'
        USING ERRCODE='55000';
END;
$$;
CREATE TRIGGER context_source_erasure_tombstones_immutable BEFORE UPDATE OR DELETE
ON havre.context_source_erasure_tombstones FOR EACH ROW
EXECUTE FUNCTION havre.reject_context_tombstone_mutation();

CREATE TRIGGER context_sources_immutable BEFORE UPDATE OR DELETE ON havre.context_sources
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();
CREATE TRIGGER context_device_bindings_immutable BEFORE UPDATE OR DELETE ON havre.context_device_bindings
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();
CREATE TRIGGER context_source_states_immutable BEFORE UPDATE OR DELETE ON havre.context_source_state_revisions
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();
CREATE TRIGGER context_capabilities_immutable BEFORE UPDATE OR DELETE ON havre.context_source_capabilities
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();
CREATE TRIGGER context_capability_states_immutable BEFORE UPDATE OR DELETE ON havre.context_capability_state_revisions
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();
CREATE TRIGGER context_consent_immutable BEFORE UPDATE OR DELETE ON havre.context_consent_scope_revisions
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();
CREATE TRIGGER life_context_observations_immutable BEFORE UPDATE OR DELETE ON havre.life_context_observations
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();
CREATE TRIGGER context_source_health_immutable BEFORE UPDATE OR DELETE ON havre.context_source_health_records
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();
CREATE TRIGGER context_retention_receipts_immutable BEFORE UPDATE OR DELETE ON havre.context_retention_expiry_receipts
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();
CREATE TRIGGER context_retention_intents_immutable BEFORE UPDATE OR DELETE ON havre.context_retention_expiry_intents
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();

CREATE VIEW havre.stage12_context_integrity_violations AS
SELECT observation.observation_id AS provenance_edge_id, observation.owner_id,
       'life_context_observation'::text AS source_kind,
       observation.observation_id AS source_id, NULL::integer AS source_revision,
       'event_or_consent_binding_mismatch'::text AS violation_code
FROM havre.life_context_observations observation
JOIN havre.events event ON event.event_id=observation.event_id
JOIN havre.context_consent_scope_revisions consent
  ON consent.owner_id=observation.owner_id
 AND consent.consent_scope_revision_id=observation.consent_scope_revision_id
WHERE event.owner_id <> observation.owner_id
   OR event.trace_id <> observation.trace_id
   OR event.event_type <> 'LIFE_CONTEXT_OBSERVED'
   OR event.payload->>'observation_id' <> observation.observation_id::text
   OR event.payload->>'observation_content_hash' <> observation.content_hash
   OR consent.source_instance_id <> observation.source_instance_id
   OR consent.capability_revision_id <> observation.capability_revision_id
UNION ALL
SELECT health.health_id, health.owner_id, 'context_source_health', health.health_id,
       NULL::integer, 'health_observation_or_trace_mismatch'
FROM havre.context_source_health_records health
LEFT JOIN havre.traces trace
  ON trace.owner_id=health.owner_id AND trace.trace_id=health.trace_id
LEFT JOIN havre.life_context_observations observation
  ON observation.owner_id=health.owner_id
 AND observation.observation_id=health.last_successful_observation_id
LEFT JOIN havre.context_source_capabilities capability
  ON capability.owner_id=health.owner_id
 AND capability.capability_revision_id=health.capability_revision_id
WHERE trace.trace_id IS NULL
   OR capability.capability_revision_id IS NULL
   OR capability.source_instance_id<>health.source_instance_id
   OR (
        health.health_draft_id IS NULL
        AND NOT EXISTS (
            SELECT 1 FROM havre.events causal
            WHERE causal.owner_id=health.owner_id
              AND causal.event_id=health.causal_event_id
        )
   )
   OR (health.status='healthy' AND (
        observation.observation_id IS NULL
        OR observation.source_instance_id <> health.source_instance_id
        OR observation.capability_revision_id <> health.capability_revision_id
   ))
UNION ALL
SELECT tombstone.tombstone_id,tombstone.owner_id,
       'context_source_erasure_tombstone',tombstone.source_instance_id,
       NULL::integer,'erased_context_source_resurrected'
FROM havre.context_source_erasure_tombstones tombstone
WHERE EXISTS (
    SELECT 1 FROM havre.context_sources source
    WHERE source.owner_id=tombstone.owner_id
      AND source.source_instance_id=tombstone.source_instance_id
);

CREATE VIEW havre.context_device_binding_metadata AS
SELECT owner_id, device_binding_id, source_instance_id, key_version, status,
       registered_at
FROM havre.context_device_bindings;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='havre_application') THEN
        GRANT USAGE ON SCHEMA havre TO havre_application;
        GRANT SELECT ON havre.context_sources,
            havre.context_source_erasure_tombstones,
            havre.context_restore_quarantines,
            havre.context_source_state_revisions,
            havre.context_source_capabilities,
            havre.context_capability_state_revisions,
            havre.context_consent_scope_revisions,
            havre.life_context_observations,
            havre.context_source_health_records,
            havre.context_retention_expiry_intents,
            havre.context_retention_expiry_receipts,
            havre.context_device_binding_metadata TO havre_application;
        GRANT INSERT ON havre.life_context_observations,
            havre.context_source_health_records TO havre_application;
        REVOKE ALL ON havre.context_device_bindings FROM havre_application;
        REVOKE INSERT, UPDATE, DELETE ON havre.context_sources,
            havre.context_source_state_revisions,
            havre.context_source_capabilities,
            havre.context_capability_state_revisions,
            havre.context_consent_scope_revisions,
            havre.context_retention_expiry_intents,
            havre.context_retention_expiry_receipts FROM havre_application;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='havre_privileged_erasure') THEN
        GRANT SELECT, DELETE ON havre.context_sources,
            havre.context_device_bindings,
            havre.context_source_state_revisions,
            havre.context_source_capabilities,
            havre.context_capability_state_revisions,
            havre.context_consent_scope_revisions,
            havre.life_context_observations,
            havre.context_source_health_records TO havre_privileged_erasure;
        GRANT DELETE ON havre.context_restore_quarantines,
            havre.context_retention_expiry_intents,
            havre.context_retention_expiry_receipts TO havre_privileged_erasure;
        GRANT SELECT ON havre.context_source_erasure_tombstones
            TO havre_privileged_erasure;
        GRANT INSERT, SELECT ON havre.context_restore_quarantines
            TO havre_privileged_erasure;
        GRANT INSERT, SELECT ON havre.context_source_erasure_tombstones
            TO havre_privileged_erasure;
        REVOKE UPDATE, DELETE ON havre.context_source_erasure_tombstones
            FROM havre_privileged_erasure;
        GRANT INSERT ON havre.context_retention_expiry_intents,
            havre.context_retention_expiry_receipts TO havre_privileged_erasure;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='havre_context_operator') THEN
        GRANT USAGE ON SCHEMA havre TO havre_context_operator;
        GRANT SELECT ON havre.context_sources,
            havre.context_source_erasure_tombstones,
            havre.context_device_bindings,
            havre.context_source_state_revisions,
            havre.context_source_capabilities,
            havre.context_capability_state_revisions,
            havre.context_consent_scope_revisions,
            havre.context_restore_quarantines TO havre_context_operator;
        GRANT INSERT ON havre.sessions, havre.traces,
            havre.interaction_requests, havre.events,
            havre.context_sources, havre.context_device_bindings,
            havre.context_source_state_revisions,
            havre.context_source_capabilities,
            havre.context_capability_state_revisions,
            havre.context_consent_scope_revisions,
            havre.context_source_health_records TO havre_context_operator;
    END IF;
END;
$$;

REVOKE ALL ON havre.context_device_bindings FROM PUBLIC;

COMMIT;
