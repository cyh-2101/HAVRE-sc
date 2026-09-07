-- Stage 15A owner-authorized commitment projection and conversation-safe
-- reminder fusion. Historical migrations remain immutable.

BEGIN;

CREATE TABLE havre.commitment_field_authorizations (
    authorization_id uuid PRIMARY KEY,
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    authorization_ref text NOT NULL,
    source_document_sha256 text NOT NULL CHECK (source_document_sha256 ~ '^sha256:[0-9a-f]{64}$'),
    allowed_fields text[] NOT NULL CHECK (
        allowed_fields = ARRAY['course_name','task_name','deadline','completion_state','reminder_history']::text[]
    ),
    policy_revision_id uuid NOT NULL,
    privacy_class text NOT NULL CHECK (privacy_class='NORMAL'),
    memory_eligible boolean NOT NULL CHECK (memory_eligible=false),
    training_eligible boolean NOT NULL CHECK (training_eligible=false),
    cloud_eligible boolean NOT NULL CHECK (cloud_eligible=true),
    policy_version text NOT NULL CHECK (policy_version='data-policy-v1'),
    policy_decision_source text NOT NULL CHECK (policy_decision_source='owner_explicit'),
    policy_authorization_ref text NOT NULL,
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (owner_id,authorization_id),
    UNIQUE (owner_id,authorization_ref,source_document_sha256),
    CHECK (authorization_ref=policy_authorization_ref)
);

CREATE TABLE havre.goal_transition_evidence (
    transition_evidence_id uuid PRIMARY KEY,
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    goal_id uuid NOT NULL,
    goal_revision integer NOT NULL CHECK (goal_revision>1),
    lifecycle_event_id uuid NOT NULL,
    lifecycle_event_content_hash text NOT NULL
      CHECK (lifecycle_event_content_hash ~ '^sha256:[0-9a-f]{64}$'),
    lifecycle_session_id uuid NOT NULL,
    lifecycle_request_id uuid NOT NULL,
    lifecycle_trace_id char(32) NOT NULL CHECK (lifecycle_trace_id ~ '^[0-9a-f]{32}$'),
    source_event_id uuid NOT NULL,
    source_event_content_hash text NOT NULL
      CHECK (source_event_content_hash ~ '^sha256:[0-9a-f]{64}$'),
    source_session_id uuid NOT NULL,
    source_request_id uuid NOT NULL,
    source_trace_id char(32) NOT NULL CHECK (source_trace_id ~ '^[0-9a-f]{32}$'),
    relation text NOT NULL CHECK (relation='owner_reported_completion'),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (owner_id,transition_evidence_id),
    UNIQUE (owner_id,goal_id,goal_revision,source_event_id),
    FOREIGN KEY (owner_id,goal_id) REFERENCES havre.goals(owner_id,goal_id),
    FOREIGN KEY (owner_id,lifecycle_event_id)
      REFERENCES havre.events(owner_id,event_id),
    FOREIGN KEY (owner_id,source_event_id)
      REFERENCES havre.events(owner_id,event_id)
);

CREATE FUNCTION havre.guard_goal_transition_evidence_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM havre.goals goal
    JOIN havre.events lifecycle
      ON lifecycle.owner_id=goal.owner_id
     AND lifecycle.event_id=goal.last_event_id
    JOIN havre.events source
      ON source.owner_id=goal.owner_id
     AND source.event_id=NEW.source_event_id
    WHERE goal.owner_id=NEW.owner_id AND goal.goal_id=NEW.goal_id
      AND goal.revision=NEW.goal_revision AND goal.status='completed'
      AND goal.last_event_id=NEW.lifecycle_event_id
      AND lifecycle.event_type='GOAL_COMPLETED'
      AND lifecycle.content_hash=NEW.lifecycle_event_content_hash
      AND lifecycle.session_id=NEW.lifecycle_session_id
      AND lifecycle.request_id=NEW.lifecycle_request_id
      AND lifecycle.trace_id=NEW.lifecycle_trace_id
      AND lifecycle.payload->>'goal_id'=NEW.goal_id::text
      AND lifecycle.payload->>'goal_revision'=NEW.goal_revision::text
      AND source.content_hash=NEW.source_event_content_hash
      AND source.event_type='USER_MESSAGE'
      AND source.session_id=NEW.source_session_id
      AND source.request_id=NEW.source_request_id
      AND source.trace_id=NEW.source_trace_id
      AND (CASE goal.privacy_class
             WHEN 'PUBLIC' THEN 0 WHEN 'NORMAL' THEN 1 WHEN 'PRIVATE' THEN 2
             WHEN 'HIGHLY_PRIVATE' THEN 3 WHEN 'LOCAL_ONLY' THEN 4 ELSE -1 END)
          >=
          (CASE source.privacy_class
             WHEN 'PUBLIC' THEN 0 WHEN 'NORMAL' THEN 1 WHEN 'PRIVATE' THEN 2
             WHEN 'HIGHLY_PRIVATE' THEN 3 WHEN 'LOCAL_ONLY' THEN 4 ELSE 99 END)
      AND NOT (source.cloud_eligible=false AND goal.cloud_eligible=true)
      AND NOT (source.training_eligible=false AND goal.training_eligible=true)
  ) THEN
    RAISE EXCEPTION 'Goal transition evidence lacks exact owner report lineage'
      USING ERRCODE='55000';
  END IF;
  NEW.content_hash := 'sha256:' || encode(sha256(convert_to(jsonb_build_object(
    'goal_id',NEW.goal_id::text,
    'goal_revision',NEW.goal_revision,
    'lifecycle_event_content_hash',NEW.lifecycle_event_content_hash,
    'lifecycle_event_id',NEW.lifecycle_event_id::text,
    'lifecycle_request_id',NEW.lifecycle_request_id::text,
    'lifecycle_session_id',NEW.lifecycle_session_id::text,
    'lifecycle_trace_id',NEW.lifecycle_trace_id,
    'owner_id',NEW.owner_id::text,
    'relation',NEW.relation,
    'source_event_content_hash',NEW.source_event_content_hash,
    'source_event_id',NEW.source_event_id::text,
    'source_request_id',NEW.source_request_id::text,
    'source_session_id',NEW.source_session_id::text,
    'source_trace_id',NEW.source_trace_id
  )::text,'UTF8')),'hex');
  RETURN NEW;
END;
$$;
CREATE TRIGGER goal_transition_evidence_exact_lineage
BEFORE INSERT ON havre.goal_transition_evidence
FOR EACH ROW EXECUTE FUNCTION havre.guard_goal_transition_evidence_insert();

CREATE VIEW havre.stage15_commitment_integrity_violations AS
SELECT evidence.transition_evidence_id AS provenance_edge_id,
       evidence.owner_id,
       'event'::text AS source_kind,
       evidence.source_event_id AS source_id,
       NULL::integer AS source_revision,
       'invalid_goal_transition_evidence'::text AS violation_code
FROM havre.goal_transition_evidence evidence
LEFT JOIN havre.events lifecycle
  ON lifecycle.owner_id=evidence.owner_id
 AND lifecycle.event_id=evidence.lifecycle_event_id
LEFT JOIN havre.events source
  ON source.owner_id=evidence.owner_id
 AND source.event_id=evidence.source_event_id
WHERE lifecycle.event_id IS NULL OR source.event_id IS NULL
   OR lifecycle.content_hash<>evidence.lifecycle_event_content_hash
   OR source.content_hash<>evidence.source_event_content_hash
   OR lifecycle.event_type<>'GOAL_COMPLETED'
   OR source.event_type<>'USER_MESSAGE'
   OR lifecycle.session_id<>evidence.lifecycle_session_id
   OR lifecycle.request_id<>evidence.lifecycle_request_id
   OR lifecycle.trace_id<>evidence.lifecycle_trace_id
   OR source.session_id<>evidence.source_session_id
   OR source.request_id<>evidence.source_request_id
   OR source.trace_id<>evidence.source_trace_id
   OR lifecycle.payload->>'goal_id'<>evidence.goal_id::text
   OR lifecycle.payload->>'goal_revision'<>evidence.goal_revision::text;

CREATE TABLE havre.commitment_projections (
    commitment_projection_id uuid PRIMARY KEY,
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    goal_id uuid NOT NULL,
    goal_revision integer NOT NULL CHECK (goal_revision>0),
    source_goal_content_hash text NOT NULL CHECK (source_goal_content_hash ~ '^sha256:[0-9a-f]{64}$'),
    source_event_id uuid NOT NULL,
    source_event_content_hash text NOT NULL CHECK (source_event_content_hash ~ '^sha256:[0-9a-f]{64}$'),
    authorization_id uuid NOT NULL,
    source_document_sha256 text NOT NULL CHECK (source_document_sha256 ~ '^sha256:[0-9a-f]{64}$'),
    entry_id text NOT NULL CHECK (length(entry_id) BETWEEN 1 AND 240),
    course_name text NOT NULL CHECK (length(course_name) BETWEEN 1 AND 160),
    task_name text NOT NULL CHECK (length(task_name) BETWEEN 1 AND 500),
    deadline_at timestamptz NULL,
    completion_state text NOT NULL CHECK (completion_state IN ('active','paused','completed','abandoned')),
    reminder_history jsonb NOT NULL CHECK (jsonb_typeof(reminder_history)='array'),
    privacy_class text NOT NULL CHECK (privacy_class='NORMAL'),
    memory_eligible boolean NOT NULL CHECK (memory_eligible=false),
    training_eligible boolean NOT NULL CHECK (training_eligible=false),
    cloud_eligible boolean NOT NULL CHECK (cloud_eligible=true),
    policy_version text NOT NULL CHECK (policy_version='data-policy-v1'),
    policy_revision_id uuid NOT NULL,
    policy_decision_source text NOT NULL CHECK (policy_decision_source='owner_explicit'),
    policy_authorization_ref text NOT NULL,
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (owner_id,commitment_projection_id),
    UNIQUE (owner_id,goal_id,goal_revision),
    FOREIGN KEY (owner_id,goal_id) REFERENCES havre.goals(owner_id,goal_id),
    FOREIGN KEY (owner_id,source_event_id) REFERENCES havre.events(owner_id,event_id),
    FOREIGN KEY (owner_id,authorization_id)
      REFERENCES havre.commitment_field_authorizations(owner_id,authorization_id)
);

CREATE FUNCTION havre.guard_commitment_projection_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE goal_row havre.goals%ROWTYPE;
DECLARE event_hash text;
DECLARE auth_row havre.commitment_field_authorizations%ROWTYPE;
BEGIN
  SELECT * INTO STRICT goal_row FROM havre.goals
  WHERE owner_id=NEW.owner_id AND goal_id=NEW.goal_id;
  SELECT content_hash INTO STRICT event_hash FROM havre.events
  WHERE owner_id=NEW.owner_id AND event_id=NEW.source_event_id;
  SELECT * INTO STRICT auth_row FROM havre.commitment_field_authorizations
  WHERE owner_id=NEW.owner_id AND authorization_id=NEW.authorization_id;
  IF goal_row.revision<>NEW.goal_revision
     OR goal_row.content_hash<>NEW.source_goal_content_hash
     OR goal_row.last_event_id<>NEW.source_event_id
     OR event_hash<>NEW.source_event_content_hash
     OR goal_row.status<>NEW.completion_state
     OR auth_row.source_document_sha256<>NEW.source_document_sha256
     OR auth_row.policy_revision_id<>NEW.policy_revision_id
     OR auth_row.authorization_ref<>NEW.policy_authorization_ref THEN
    RAISE EXCEPTION 'commitment projection lacks exact Goal/source/authorization lineage'
      USING ERRCODE='55000';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER commitment_projection_exact_lineage
BEFORE INSERT OR UPDATE ON havre.commitment_projections
FOR EACH ROW EXECUTE FUNCTION havre.guard_commitment_projection_insert();

CREATE TABLE havre.owner_conversation_delivery_state (
    owner_id uuid PRIMARY KEY REFERENCES havre.owners(owner_id),
    arrival_epoch bigint NOT NULL CHECK (arrival_epoch>=0),
    updated_at timestamptz NOT NULL
);

CREATE TABLE havre.interaction_activity_leases (
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    request_id uuid NOT NULL,
    arrival_epoch bigint NOT NULL CHECK (arrival_epoch>0),
    started_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    expires_at timestamptz NOT NULL,
    ended_at timestamptz NULL,
    PRIMARY KEY (owner_id,request_id),
    CHECK (expires_at>started_at),
    CHECK (ended_at IS NULL OR ended_at>=started_at)
);
CREATE INDEX interaction_activity_active_idx
  ON havre.interaction_activity_leases(owner_id,expires_at)
  WHERE ended_at IS NULL;

CREATE TABLE havre.proactive_fusion_claims (
    claim_id uuid PRIMARY KEY,
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    work_item_id uuid NOT NULL,
    request_id uuid NOT NULL,
    goal_id uuid NOT NULL,
    goal_revision integer NOT NULL CHECK (goal_revision>0),
    commitment_projection_id uuid NOT NULL,
    score numeric NOT NULL,
    status text NOT NULL CHECK (status IN ('claimed','delivered','deferred','cancelled')),
    reason text NULL,
    assistant_event_id uuid NULL,
    context_pack_id uuid NULL,
    claimed_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    resolved_at timestamptz NULL,
    UNIQUE (owner_id,claim_id),
    FOREIGN KEY (owner_id,work_item_id)
      REFERENCES havre.proactive_work_items(owner_id,work_item_id),
    FOREIGN KEY (owner_id,request_id)
      REFERENCES havre.interaction_requests(owner_id,request_id),
    FOREIGN KEY (owner_id,goal_id) REFERENCES havre.goals(owner_id,goal_id),
    FOREIGN KEY (owner_id,commitment_projection_id)
      REFERENCES havre.commitment_projections(owner_id,commitment_projection_id),
    FOREIGN KEY (owner_id,assistant_event_id) REFERENCES havre.events(owner_id,event_id),
    FOREIGN KEY (owner_id,context_pack_id) REFERENCES havre.context_packs(owner_id,context_pack_id),
    CHECK ((status='delivered')=(assistant_event_id IS NOT NULL AND context_pack_id IS NOT NULL)),
    CHECK ((status='claimed')=(resolved_at IS NULL))
);
CREATE UNIQUE INDEX proactive_fusion_one_active_claim_idx
  ON havre.proactive_fusion_claims(owner_id,work_item_id)
  WHERE status='claimed';

CREATE FUNCTION havre.guard_proactive_fusion_claim_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE request_status text;
DECLARE work_payload jsonb;
DECLARE projection_row havre.commitment_projections%ROWTYPE;
BEGIN
  SELECT status INTO STRICT request_status FROM havre.interaction_requests
  WHERE owner_id=NEW.owner_id AND request_id=NEW.request_id;
  SELECT command_payload INTO STRICT work_payload FROM havre.proactive_work_items
  WHERE owner_id=NEW.owner_id AND work_item_id=NEW.work_item_id;
  SELECT * INTO STRICT projection_row FROM havre.commitment_projections
  WHERE owner_id=NEW.owner_id
    AND commitment_projection_id=NEW.commitment_projection_id;
  IF request_status<>'processing'
     OR NOT EXISTS (
       SELECT 1 FROM havre.interaction_activity_leases lease
       WHERE lease.owner_id=NEW.owner_id AND lease.request_id=NEW.request_id
         AND lease.ended_at IS NULL AND lease.expires_at>statement_timestamp()
     )
     OR projection_row.goal_id<>NEW.goal_id
     OR projection_row.goal_revision<>NEW.goal_revision
     OR work_payload#>>'{source_guard,projection_id}'<>NEW.goal_id::text
     OR (work_payload#>>'{source_guard,projection_revision}')::integer<>NEW.goal_revision THEN
    RAISE EXCEPTION 'fusion claim lacks an active interaction or exact Goal lineage'
      USING ERRCODE='55000';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER proactive_fusion_claim_exact_lineage
BEFORE INSERT ON havre.proactive_fusion_claims
FOR EACH ROW EXECUTE FUNCTION havre.guard_proactive_fusion_claim_insert();

CREATE TABLE havre.commitment_reminder_deliveries (
    delivery_id uuid PRIMARY KEY,
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    work_item_id uuid NOT NULL,
    claim_id uuid NULL,
    goal_id uuid NOT NULL,
    goal_revision integer NOT NULL CHECK (goal_revision>0),
    commitment_projection_id uuid NOT NULL,
    reminder_kind text NOT NULL CHECK (reminder_kind IN ('start_window','check_in','encouragement')),
    delivery_mode text NOT NULL CHECK (delivery_mode IN ('conversation_fusion','standalone_web_inbox')),
    assistant_event_id uuid NOT NULL,
    context_pack_id uuid NULL,
    source_event_id uuid NOT NULL,
    source_event_content_hash text NOT NULL CHECK (source_event_content_hash ~ '^sha256:[0-9a-f]{64}$'),
    projection_content_hash text NOT NULL CHECK (projection_content_hash ~ '^sha256:[0-9a-f]{64}$'),
    inclusion_text text NOT NULL CHECK (length(inclusion_text) BETWEEN 1 AND 500),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    delivered_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (owner_id,delivery_id),
    UNIQUE (owner_id,work_item_id),
    FOREIGN KEY (owner_id,work_item_id)
      REFERENCES havre.proactive_work_items(owner_id,work_item_id),
    FOREIGN KEY (owner_id,claim_id) REFERENCES havre.proactive_fusion_claims(owner_id,claim_id),
    FOREIGN KEY (owner_id,goal_id) REFERENCES havre.goals(owner_id,goal_id),
    FOREIGN KEY (owner_id,commitment_projection_id)
      REFERENCES havre.commitment_projections(owner_id,commitment_projection_id),
    FOREIGN KEY (owner_id,assistant_event_id) REFERENCES havre.events(owner_id,event_id),
    FOREIGN KEY (owner_id,context_pack_id) REFERENCES havre.context_packs(owner_id,context_pack_id),
    FOREIGN KEY (owner_id,source_event_id) REFERENCES havre.events(owner_id,event_id),
    CHECK ((delivery_mode='conversation_fusion')=(claim_id IS NOT NULL AND context_pack_id IS NOT NULL))
);

CREATE FUNCTION havre.guard_commitment_reminder_delivery_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE assistant_text text;
DECLARE projection_row havre.commitment_projections%ROWTYPE;
DECLARE work_payload jsonb;
DECLARE context_has_source boolean;
BEGIN
  SELECT string_agg(part->>'text', E'\n') INTO STRICT assistant_text
  FROM havre.events event,
       LATERAL jsonb_array_elements(event.payload->'content_parts') part
  WHERE event.owner_id=NEW.owner_id AND event.event_id=NEW.assistant_event_id
    AND event.event_type='ASSISTANT_MESSAGE' AND part->>'type'='text';
  SELECT * INTO STRICT projection_row FROM havre.commitment_projections
  WHERE owner_id=NEW.owner_id
    AND commitment_projection_id=NEW.commitment_projection_id;
  SELECT command_payload INTO STRICT work_payload FROM havre.proactive_work_items
  WHERE owner_id=NEW.owner_id AND work_item_id=NEW.work_item_id;
  IF position(lower(NEW.inclusion_text) in lower(assistant_text))=0
     OR projection_row.goal_id<>NEW.goal_id
     OR projection_row.goal_revision<>NEW.goal_revision
     OR NOT EXISTS (
       SELECT 1 FROM havre.goals goal
       WHERE goal.owner_id=NEW.owner_id AND goal.goal_id=NEW.goal_id
         AND goal.revision=NEW.goal_revision AND goal.status='active'
         AND goal.content_hash=NEW.projection_content_hash
         AND goal.last_event_id=NEW.source_event_id
     )
     OR work_payload#>>'{source_guard,source_event_id}'<>NEW.source_event_id::text
     OR work_payload#>>'{source_guard,source_event_content_hash}'<>NEW.source_event_content_hash
     OR work_payload#>>'{source_guard,projection_content_hash}'<>NEW.projection_content_hash THEN
    RAISE EXCEPTION 'reminder delivery lacks actual inclusion or exact source lineage'
      USING ERRCODE='55000';
  END IF;
  IF NEW.delivery_mode='conversation_fusion' THEN
    SELECT EXISTS (
      SELECT 1 FROM havre.context_packs context,
        LATERAL jsonb_array_elements(context.sections) section,
        LATERAL jsonb_array_elements_text(section->'source_refs') source_ref
      WHERE context.owner_id=NEW.owner_id
        AND context.context_pack_id=NEW.context_pack_id
        AND source_ref=('commitment/'||NEW.commitment_projection_id::text)
    ) INTO context_has_source;
    IF context_has_source IS DISTINCT FROM true THEN
      RAISE EXCEPTION 'fused reminder ContextPack lacks its commitment projection'
        USING ERRCODE='55000';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER commitment_reminder_delivery_exact_lineage
BEFORE INSERT ON havre.commitment_reminder_deliveries
FOR EACH ROW EXECUTE FUNCTION havre.guard_commitment_reminder_delivery_insert();

CREATE TRIGGER commitment_authorizations_immutable
BEFORE UPDATE OR DELETE ON havre.commitment_field_authorizations
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();
CREATE TRIGGER goal_transition_evidence_immutable
BEFORE UPDATE OR DELETE ON havre.goal_transition_evidence
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();
CREATE TRIGGER commitment_projections_immutable
BEFORE UPDATE OR DELETE ON havre.commitment_projections
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();
CREATE TRIGGER commitment_reminder_deliveries_immutable
BEFORE UPDATE OR DELETE ON havre.commitment_reminder_deliveries
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='havre_application') THEN
    GRANT SELECT,INSERT ON havre.goal_transition_evidence TO havre_application;
    GRANT SELECT,INSERT ON havre.commitment_field_authorizations TO havre_application;
    GRANT SELECT,INSERT,UPDATE ON havre.commitment_projections TO havre_application;
    GRANT SELECT,INSERT,UPDATE ON havre.owner_conversation_delivery_state TO havre_application;
    GRANT SELECT,INSERT,UPDATE ON havre.interaction_activity_leases TO havre_application;
    GRANT SELECT,INSERT,UPDATE ON havre.proactive_fusion_claims TO havre_application;
    GRANT SELECT,INSERT ON havre.commitment_reminder_deliveries TO havre_application;
  END IF;
END
$$;

COMMIT;
