-- Owner-authorized experience-first daily review. Historical migrations remain
-- immutable. The worker schedules the just-finished owner-local day at 05:00,
-- may admit bounded eligible prior context, and records local review artifacts.

BEGIN;

ALTER TABLE havre.daily_diary_entry_revisions
  DROP CONSTRAINT daily_diary_entry_revisions_summary_method_check;
ALTER TABLE havre.daily_diary_entry_revisions
  ADD CONSTRAINT daily_diary_entry_revisions_summary_method_check
  CHECK (summary_method IN (
    'evidence-extractive-diary-v1','evidence-event-diary-v2',
    'curated-owner-day-diary-v3','gpt-owner-day-diary-v4',
    'gpt-owner-day-diary-v5'
  ));

ALTER TABLE havre.daily_diary_intelligence_sources
  DROP CONSTRAINT daily_diary_intelligence_sources_disposition_check;
ALTER TABLE havre.daily_diary_intelligence_sources
  ADD CONSTRAINT daily_diary_intelligence_sources_disposition_check
  CHECK (disposition IN ('cloud_summary','private_reference','prior_context'));

CREATE OR REPLACE FUNCTION havre.guard_daily_diary_intelligence_source()
RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE source_event havre.events%ROWTYPE;
DECLARE run_row havre.daily_diary_intelligence_runs%ROWTYPE;
DECLARE routed_provider text;
DECLARE source_local_date date;
BEGIN
  SELECT * INTO STRICT source_event FROM havre.events
  WHERE owner_id=NEW.owner_id AND event_id=NEW.event_id;
  SELECT * INTO STRICT run_row FROM havre.daily_diary_intelligence_runs
  WHERE owner_id=NEW.owner_id AND run_id=NEW.run_id;
  source_local_date := (source_event.recorded_at AT TIME ZONE run_row.timezone_name)::date;
  IF source_event.event_type NOT IN ('USER_MESSAGE','ASSISTANT_MESSAGE')
     OR source_event.content_hash<>NEW.event_content_hash
     OR (NEW.disposition IN ('cloud_summary','private_reference')
         AND source_local_date<>run_row.local_date)
     OR (NEW.disposition='prior_context'
         AND (source_local_date>=run_row.local_date
              OR source_local_date<run_row.local_date-7)) THEN
    RAISE EXCEPTION 'Diary intelligence source must match its bounded owner-local message Event'
      USING ERRCODE='55000';
  END IF;
  IF NEW.disposition IN ('cloud_summary','prior_context') AND (
       source_event.privacy_class NOT IN ('PUBLIC','NORMAL')
       OR NOT source_event.cloud_eligible
  ) THEN
    RAISE EXCEPTION 'private or non-cloud Event cannot enter Diary cloud input'
      USING ERRCODE='55000';
  END IF;
  IF NEW.disposition IN ('cloud_summary','prior_context') THEN
    SELECT route.selected_provider_id INTO routed_provider
    FROM havre.route_decisions route
    JOIN havre.interaction_requests request
      ON request.owner_id=route.owner_id AND request.request_id=route.request_id
    WHERE route.owner_id=NEW.owner_id
      AND route.request_id=source_event.request_id
      AND route.execution_environment='cloud'
      AND request.status='completed';
    IF routed_provider IS DISTINCT FROM 'openai-codex-chatgpt' THEN
      RAISE EXCEPTION 'only completed cloud GPT-routed Events may enter Diary cloud input'
        USING ERRCODE='55000';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

CREATE TABLE havre.daily_diary_review_memory_sources (
    owner_id uuid NOT NULL,
    run_id uuid NOT NULL,
    ordinal integer NOT NULL CHECK (ordinal>=0),
    memory_id uuid NOT NULL,
    memory_revision integer NOT NULL CHECK (memory_revision>0),
    memory_content_hash text NOT NULL CHECK (memory_content_hash ~ '^sha256:[0-9a-f]{64}$'),
    PRIMARY KEY (owner_id,run_id,ordinal),
    UNIQUE (owner_id,run_id,memory_id,memory_revision),
    FOREIGN KEY (owner_id,run_id)
      REFERENCES havre.daily_diary_intelligence_runs(owner_id,run_id) ON DELETE CASCADE,
    FOREIGN KEY (owner_id,memory_id,memory_revision)
      REFERENCES havre.memory_revisions(owner_id,memory_id,revision) ON DELETE CASCADE
);
CREATE INDEX daily_diary_review_memory_source_idx
  ON havre.daily_diary_review_memory_sources(owner_id,memory_id,memory_revision);

CREATE FUNCTION havre.guard_daily_diary_review_memory_source() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM havre.daily_diary_intelligence_runs run
    JOIN havre.memory_revisions revision
      ON revision.owner_id=NEW.owner_id
     AND revision.memory_id=NEW.memory_id
     AND revision.revision=NEW.memory_revision
    JOIN havre.memory_heads head
      ON head.owner_id=revision.owner_id AND head.memory_id=revision.memory_id
    WHERE run.owner_id=NEW.owner_id AND run.run_id=NEW.run_id
      AND run.status='completed'
      AND revision.content_hash=NEW.memory_content_hash
      AND revision.privacy_class IN ('PUBLIC','NORMAL')
      AND revision.cloud_eligible
      AND head.current_revision=revision.revision AND head.status='active'
  ) THEN
    RAISE EXCEPTION 'Diary review Memory must be current and cloud-eligible'
      USING ERRCODE='55000';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER daily_diary_review_memory_source_guard
BEFORE INSERT ON havre.daily_diary_review_memory_sources
FOR EACH ROW EXECUTE FUNCTION havre.guard_daily_diary_review_memory_source();
CREATE TRIGGER daily_diary_review_memory_sources_immutable
BEFORE UPDATE OR DELETE ON havre.daily_diary_review_memory_sources
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();

CREATE TABLE havre.daily_diary_schedule_receipts (
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    local_date date NOT NULL,
    timezone_name text NOT NULL CHECK (length(timezone_name) BETWEEN 1 AND 80),
    scheduled_for timestamptz NOT NULL,
    status text NOT NULL CHECK (status IN ('pending','leased','completed','no_events','retryable_failed')),
    lease_owner text NULL,
    lease_expires_at timestamptz NULL,
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count>=0),
    run_id uuid NULL,
    error_code text NULL,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (owner_id,local_date,timezone_name),
    FOREIGN KEY (owner_id,run_id)
      REFERENCES havre.daily_diary_intelligence_runs(owner_id,run_id) ON DELETE CASCADE,
    CHECK ((status='leased')=(lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)),
    CHECK ((status='completed')=(run_id IS NOT NULL))
);
CREATE INDEX daily_diary_schedule_claim_idx
  ON havre.daily_diary_schedule_receipts(status,scheduled_for,updated_at)
  WHERE status IN ('pending','leased','retryable_failed');
CREATE INDEX daily_diary_schedule_run_idx
  ON havre.daily_diary_schedule_receipts(owner_id,run_id)
  WHERE run_id IS NOT NULL;

CREATE TABLE havre.daily_improvement_review_files (
    owner_id uuid NOT NULL,
    run_id uuid NOT NULL,
    relative_path text NOT NULL CHECK (
      length(relative_path) BETWEEN 1 AND 300
      AND relative_path !~ '(^|[\\/])[.][.]([\\/]|$)'
      AND relative_path !~ '^[A-Za-z]:[\\/]'
      AND relative_path !~ '^[\\/]'
      AND relative_path ~ '[.]md$'
    ),
    file_sha256 text NOT NULL CHECK (file_sha256 ~ '^sha256:[0-9a-f]{64}$'),
    source_set_hash text NOT NULL CHECK (source_set_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (owner_id,run_id),
    UNIQUE (owner_id,relative_path),
    FOREIGN KEY (owner_id,run_id)
      REFERENCES havre.daily_diary_intelligence_runs(owner_id,run_id) ON DELETE CASCADE
);
CREATE TRIGGER daily_improvement_review_files_immutable
BEFORE UPDATE OR DELETE ON havre.daily_improvement_review_files
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();

CREATE TABLE havre.owner_chat_goal_plan_runs (
    plan_run_id uuid PRIMARY KEY,
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    source_event_id uuid NOT NULL,
    source_event_content_hash text NOT NULL CHECK (source_event_content_hash ~ '^sha256:[0-9a-f]{64}$'),
    explicit_intent_hash text NOT NULL CHECK (explicit_intent_hash ~ '^sha256:[0-9a-f]{64}$'),
    status text NOT NULL CHECK (status IN ('completed','no_action','failed')),
    inference_request_id uuid NULL,
    request_binding_hash text NULL CHECK (
      request_binding_hash IS NULL OR request_binding_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    provider_id text NULL,
    model_version_id text NULL,
    provider_adapter_version_id text NULL,
    serving_config_version text NULL,
    reasoning_effort text NULL CHECK (reasoning_effort IS NULL OR reasoning_effort='high'),
    result jsonb NULL CHECK (result IS NULL OR jsonb_typeof(result)='object'),
    response_content_hash text NULL CHECK (
      response_content_hash IS NULL OR response_content_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    error_code text NULL,
    authorization_ref text NOT NULL CHECK (
      authorization_ref='product-owner/explicit-chat-goal-planning-2026-09-04'
    ),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (owner_id,plan_run_id),
    UNIQUE (owner_id,source_event_id),
    FOREIGN KEY (owner_id,source_event_id)
      REFERENCES havre.events(owner_id,event_id) ON DELETE CASCADE,
    CHECK (
      (status IN ('completed','no_action') AND inference_request_id IS NOT NULL
       AND request_binding_hash IS NOT NULL AND provider_id='openai-codex-chatgpt'
       AND model_version_id IS NOT NULL AND provider_adapter_version_id IS NOT NULL
       AND serving_config_version IS NOT NULL AND reasoning_effort='high'
       AND result IS NOT NULL AND response_content_hash IS NOT NULL
       AND error_code IS NULL)
      OR
      (status='failed' AND inference_request_id IS NULL AND result IS NULL
       AND error_code IS NOT NULL)
    )
);

CREATE TABLE havre.owner_chat_goal_actions (
    owner_id uuid NOT NULL,
    plan_run_id uuid NOT NULL,
    source_event_id uuid NOT NULL,
    goal_id uuid NOT NULL,
    goal_revision integer NOT NULL CHECK (goal_revision=1),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (owner_id,plan_run_id,goal_id),
    UNIQUE (owner_id,source_event_id,goal_id),
    FOREIGN KEY (owner_id,plan_run_id)
      REFERENCES havre.owner_chat_goal_plan_runs(owner_id,plan_run_id) ON DELETE CASCADE,
    FOREIGN KEY (owner_id,source_event_id)
      REFERENCES havre.events(owner_id,event_id) ON DELETE CASCADE,
    FOREIGN KEY (owner_id,goal_id)
      REFERENCES havre.goals(owner_id,goal_id) ON DELETE CASCADE
);
CREATE INDEX owner_chat_goal_actions_goal_idx
  ON havre.owner_chat_goal_actions(owner_id,goal_id);

CREATE FUNCTION havre.guard_owner_chat_goal_action() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM havre.owner_chat_goal_plan_runs run
    JOIN havre.goals goal
      ON goal.owner_id=NEW.owner_id AND goal.goal_id=NEW.goal_id
    JOIN havre.events lifecycle
      ON lifecycle.owner_id=goal.owner_id AND lifecycle.event_id=goal.last_event_id
    WHERE run.owner_id=NEW.owner_id AND run.plan_run_id=NEW.plan_run_id
      AND run.source_event_id=NEW.source_event_id AND run.status='completed'
      AND goal.revision=NEW.goal_revision
      AND lifecycle.event_type='GOAL_CREATED'
      AND lifecycle.causation_event_id=NEW.source_event_id
      AND lifecycle.payload->>'goal_id'=NEW.goal_id::text
      AND lifecycle.payload->>'goal_revision'=NEW.goal_revision::text
  ) THEN
    RAISE EXCEPTION 'chat Goal action lacks exact source-bound plan and lifecycle'
      USING ERRCODE='55000';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER owner_chat_goal_action_guard
BEFORE INSERT ON havre.owner_chat_goal_actions
FOR EACH ROW EXECUTE FUNCTION havre.guard_owner_chat_goal_action();
CREATE TRIGGER owner_chat_goal_plan_runs_immutable
BEFORE UPDATE OR DELETE ON havre.owner_chat_goal_plan_runs
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();
CREATE TRIGGER owner_chat_goal_actions_immutable
BEFORE UPDATE OR DELETE ON havre.owner_chat_goal_actions
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();

ALTER TABLE havre.proactive_triggers
  DROP CONSTRAINT proactive_triggers_source_kind_check;
ALTER TABLE havre.proactive_triggers
  ADD CONSTRAINT proactive_triggers_source_kind_check CHECK (source_kind IN (
    'scheduled_time','goal','scene_session','owner_reminder',
    'belief_confirmation','system_operational','synthetic_life_context',
    'memory','conversation'
  ));

CREATE OR REPLACE FUNCTION havre.guard_owner_delegated_gpt_memory_update()
RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.authorization_ref<>'product-owner/experience-first-daily-review-2026-09-04'
     OR NOT EXISTS (
       SELECT 1
       FROM havre.daily_diary_intelligence_runs run
       JOIN havre.daily_diary_intelligence_sources source
         ON source.owner_id=run.owner_id AND source.run_id=run.run_id
       JOIN havre.events event
         ON event.owner_id=source.owner_id AND event.event_id=source.event_id
       JOIN havre.memory_revisions revision
         ON revision.owner_id=NEW.owner_id AND revision.memory_id=NEW.memory_id
        AND revision.revision=NEW.memory_revision
       JOIN havre.memory_heads head
         ON head.owner_id=revision.owner_id AND head.memory_id=revision.memory_id
       JOIN havre.events lifecycle
         ON lifecycle.owner_id=revision.owner_id
        AND lifecycle.event_id=revision.created_event_id
       WHERE run.owner_id=NEW.owner_id AND run.run_id=NEW.run_id
         AND run.status='completed'
         AND run.provider_id='openai-codex-chatgpt'
         AND run.reasoning_effort='high'
         AND run.policy_authorization_ref=NEW.authorization_ref
         AND source.event_id=NEW.source_event_id
         AND source.disposition='cloud_summary'
         AND event.event_type='USER_MESSAGE'
         AND event.memory_eligible AND event.cloud_eligible
         AND event.privacy_class IN ('PUBLIC','NORMAL')
         AND revision.revision=1
         AND revision.created_by='owner_delegated_gpt'
         AND revision.confidence_method='gpt-grounded-owner-authorized-v1'
         AND revision.transform_version='gpt-owner-diary-intelligence-v2'
         AND revision.candidate_id IS NULL
         AND revision.policy_decision_source='derived_conservative'
         AND revision.policy_authorization_ref=NEW.authorization_ref
         AND head.current_revision=revision.revision AND head.status='active'
         AND lifecycle.event_type='MEMORY_CREATED'
         AND lifecycle.causation_event_id=NEW.source_event_id
         AND EXISTS (
           SELECT 1 FROM havre.provenance_edges edge
           WHERE edge.owner_id=NEW.owner_id
             AND edge.source_kind='event'
             AND edge.source_id=NEW.source_event_id
             AND edge.source_revision IS NULL
             AND edge.derived_kind='memory_revision'
             AND edge.derived_id=NEW.memory_id
             AND edge.derived_revision=NEW.memory_revision
             AND edge.relation='derived_from'
             AND edge.transform_name='owner_delegated_gpt_diary_memory'
             AND edge.transform_version='gpt-owner-diary-intelligence-v2'
         )
     ) THEN
    RAISE EXCEPTION 'owner-delegated GPT Memory mapping lacks exact eligible run and provenance'
      USING ERRCODE='55000';
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION havre.guard_owner_delegated_gpt_belief_update()
RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.authorization_ref<>'product-owner/experience-first-daily-review-2026-09-04'
     OR NOT EXISTS (
       SELECT 1
       FROM havre.daily_diary_intelligence_runs run
       JOIN havre.daily_diary_intelligence_sources source
         ON source.owner_id=run.owner_id AND source.run_id=run.run_id
       JOIN havre.events event
         ON event.owner_id=source.owner_id AND event.event_id=source.event_id
       JOIN havre.user_belief_revisions revision
         ON revision.owner_id=NEW.owner_id AND revision.belief_id=NEW.belief_id
        AND revision.revision=NEW.belief_revision
       JOIN havre.belief_heads head
         ON head.owner_id=revision.owner_id AND head.belief_id=revision.belief_id
       JOIN havre.events lifecycle
         ON lifecycle.owner_id=revision.owner_id
        AND lifecycle.event_id=revision.created_event_id
       JOIN havre.belief_revision_transitions transition
         ON transition.owner_id=head.owner_id
        AND transition.belief_transition_id=head.last_transition_id
       WHERE run.owner_id=NEW.owner_id AND run.run_id=NEW.run_id
         AND run.status='completed'
         AND run.provider_id='openai-codex-chatgpt'
         AND run.reasoning_effort='high'
         AND run.policy_authorization_ref=NEW.authorization_ref
         AND source.event_id=NEW.source_event_id
         AND source.disposition='cloud_summary'
         AND event.event_type='USER_MESSAGE'
         AND event.memory_eligible AND event.cloud_eligible
         AND event.privacy_class IN ('PUBLIC','NORMAL')
         AND revision.revision=1
         AND revision.confidence_method='owner-delegated-gpt-v1'
         AND revision.initial_status='candidate'
         AND revision.belief_key LIKE 'owner-delegated-gpt:%'
         AND revision.policy_decision_source='derived_conservative'
         AND revision.policy_authorization_ref=NEW.authorization_ref
         AND head.current_revision=revision.revision AND head.status='active'
         AND lifecycle.event_type='USER_BELIEF_CREATED'
         AND lifecycle.causation_event_id=NEW.source_event_id
         AND transition.belief_id=NEW.belief_id
         AND transition.belief_revision=NEW.belief_revision
         AND transition.transition_type='activated'
         AND transition.reason=NEW.authorization_ref
         AND EXISTS (
           SELECT 1 FROM havre.provenance_edges edge
           WHERE edge.owner_id=NEW.owner_id
             AND edge.source_kind='event'
             AND edge.source_id=NEW.source_event_id
             AND edge.source_revision IS NULL
             AND edge.derived_kind='belief_revision'
             AND edge.derived_id=NEW.belief_id
             AND edge.derived_revision=NEW.belief_revision
             AND edge.relation='supports'
             AND edge.transform_name='owner_delegated_gpt_diary_belief'
             AND edge.transform_version='gpt-owner-diary-intelligence-v2'
         )
     ) THEN
    RAISE EXCEPTION 'owner-delegated GPT belief mapping lacks exact eligible run and provenance'
      USING ERRCODE='55000';
  END IF;
  RETURN NEW;
END;
$$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='havre_application') THEN
    GRANT SELECT,INSERT ON havre.daily_diary_review_memory_sources TO havre_application;
    GRANT SELECT,INSERT,UPDATE ON havre.daily_diary_schedule_receipts TO havre_application;
    GRANT SELECT,INSERT ON havre.daily_improvement_review_files TO havre_application;
    GRANT SELECT,INSERT ON havre.owner_chat_goal_plan_runs TO havre_application;
    GRANT SELECT,INSERT ON havre.owner_chat_goal_actions TO havre_application;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='havre_privileged_erasure') THEN
    GRANT SELECT,DELETE ON havre.daily_diary_review_memory_sources TO havre_privileged_erasure;
    GRANT SELECT,DELETE ON havre.daily_diary_schedule_receipts TO havre_privileged_erasure;
    GRANT SELECT,DELETE ON havre.daily_improvement_review_files TO havre_privileged_erasure;
    GRANT SELECT,DELETE ON havre.owner_chat_goal_plan_runs TO havre_privileged_erasure;
    GRANT SELECT,DELETE ON havre.owner_chat_goal_actions TO havre_privileged_erasure;
  END IF;
END
$$;

COMMIT;
