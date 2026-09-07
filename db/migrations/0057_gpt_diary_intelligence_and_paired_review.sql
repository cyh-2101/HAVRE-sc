-- Owner-authorized GPT diary intelligence, source-separated private transcript
-- references, delegated Memory/User Model updates, and paired review writes.
-- Historical Diary v1-v3 revisions remain immutable.

ALTER TABLE havre.daily_diary_entry_revisions
  DROP CONSTRAINT daily_diary_entry_revisions_summary_method_check;

ALTER TABLE havre.daily_diary_entry_revisions
  ADD CONSTRAINT daily_diary_entry_revisions_summary_method_check
  CHECK (summary_method IN (
    'evidence-extractive-diary-v1',
    'evidence-event-diary-v2',
    'curated-owner-day-diary-v3',
    'gpt-owner-day-diary-v4'
  ));

ALTER TABLE havre.user_belief_revisions
  DROP CONSTRAINT user_belief_revisions_confidence_method_check;

ALTER TABLE havre.user_belief_revisions
  ADD CONSTRAINT user_belief_revisions_confidence_method_check
  CHECK (confidence_method IN (
    'owner-reviewed-v1',
    'owner-delegated-gpt-v1'
  ));

CREATE TABLE havre.daily_diary_intelligence_runs (
    run_id uuid PRIMARY KEY,
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    local_date date NOT NULL,
    timezone_name text NOT NULL CHECK (length(timezone_name) BETWEEN 1 AND 80),
    source_set_hash text NOT NULL CHECK (source_set_hash ~ '^sha256:[0-9a-f]{64}$'),
    status text NOT NULL CHECK (status IN ('completed','private_only','failed')),
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
    privacy_class text NOT NULL CHECK (privacy_class IN (
      'PUBLIC','NORMAL','PRIVATE','HIGHLY_PRIVATE','LOCAL_ONLY'
    )),
    memory_eligible boolean NOT NULL CHECK (memory_eligible=false),
    training_eligible boolean NOT NULL CHECK (training_eligible=false),
    cloud_eligible boolean NOT NULL,
    policy_version text NOT NULL CHECK (policy_version='data-policy-v1'),
    policy_revision_id uuid NOT NULL,
    policy_decision_source text NOT NULL CHECK (
      policy_decision_source='derived_conservative'
    ),
    policy_authorization_ref text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (owner_id,run_id),
    CHECK (privacy_class<>'LOCAL_ONLY' OR cloud_eligible=false),
    CHECK (privacy_class<>'HIGHLY_PRIVATE' OR cloud_eligible=false),
    CHECK (
      (status='completed' AND inference_request_id IS NOT NULL
       AND request_binding_hash IS NOT NULL AND provider_id IS NOT NULL
       AND model_version_id IS NOT NULL AND provider_adapter_version_id IS NOT NULL
       AND serving_config_version IS NOT NULL AND reasoning_effort='high'
       AND result IS NOT NULL AND response_content_hash IS NOT NULL
       AND error_code IS NULL)
      OR
      (status='private_only' AND inference_request_id IS NULL
       AND request_binding_hash IS NULL AND provider_id IS NULL
       AND model_version_id IS NULL AND provider_adapter_version_id IS NULL
       AND serving_config_version IS NULL AND reasoning_effort IS NULL
       AND result IS NOT NULL AND response_content_hash IS NULL
       AND error_code IS NULL)
      OR
      (status='failed' AND result IS NULL AND error_code IS NOT NULL)
    )
);
CREATE UNIQUE INDEX daily_diary_intelligence_success_source_idx
  ON havre.daily_diary_intelligence_runs(
    owner_id,local_date,timezone_name,source_set_hash
  ) WHERE status IN ('completed','private_only');

CREATE TABLE havre.daily_diary_intelligence_sources (
    owner_id uuid NOT NULL,
    run_id uuid NOT NULL,
    ordinal integer NOT NULL CHECK (ordinal>=0),
    event_id uuid NOT NULL,
    event_content_hash text NOT NULL CHECK (event_content_hash ~ '^sha256:[0-9a-f]{64}$'),
    disposition text NOT NULL CHECK (disposition IN ('cloud_summary','private_reference')),
    PRIMARY KEY (owner_id,run_id,ordinal),
    UNIQUE (owner_id,run_id,event_id),
    FOREIGN KEY (owner_id,run_id)
      REFERENCES havre.daily_diary_intelligence_runs(owner_id,run_id) ON DELETE CASCADE,
    FOREIGN KEY (owner_id,event_id)
      REFERENCES havre.events(owner_id,event_id) ON DELETE CASCADE
);
CREATE INDEX daily_diary_intelligence_sources_event_idx
  ON havre.daily_diary_intelligence_sources(owner_id,event_id);

ALTER TABLE havre.daily_diary_entry_revisions
  ADD COLUMN intelligence_run_id uuid NULL;

ALTER TABLE havre.daily_diary_entry_revisions
  ADD CONSTRAINT daily_diary_entry_revisions_intelligence_run_fk
  FOREIGN KEY (owner_id,intelligence_run_id)
  REFERENCES havre.daily_diary_intelligence_runs(owner_id,run_id);

CREATE UNIQUE INDEX daily_diary_entry_revisions_intelligence_run_idx
  ON havre.daily_diary_entry_revisions(owner_id,intelligence_run_id)
  WHERE intelligence_run_id IS NOT NULL;

CREATE TABLE havre.owner_delegated_gpt_memory_updates (
    owner_id uuid NOT NULL,
    run_id uuid NOT NULL,
    source_event_id uuid NOT NULL,
    statement_hash text NOT NULL CHECK (statement_hash ~ '^sha256:[0-9a-f]{64}$'),
    memory_id uuid NOT NULL,
    memory_revision integer NOT NULL CHECK (memory_revision>0),
    authorization_ref text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (owner_id,run_id,source_event_id,statement_hash),
    UNIQUE (owner_id,memory_id,memory_revision),
    FOREIGN KEY (owner_id,run_id)
      REFERENCES havre.daily_diary_intelligence_runs(owner_id,run_id) ON DELETE CASCADE,
    FOREIGN KEY (owner_id,source_event_id)
      REFERENCES havre.events(owner_id,event_id) ON DELETE CASCADE,
    FOREIGN KEY (owner_id,memory_id,memory_revision)
      REFERENCES havre.memory_revisions(owner_id,memory_id,revision) ON DELETE CASCADE
);
CREATE INDEX owner_delegated_gpt_memory_source_idx
  ON havre.owner_delegated_gpt_memory_updates(owner_id,source_event_id);
CREATE UNIQUE INDEX owner_delegated_gpt_memory_statement_idx
  ON havre.owner_delegated_gpt_memory_updates(
    owner_id,source_event_id,statement_hash
  );

CREATE TABLE havre.owner_delegated_gpt_belief_updates (
    owner_id uuid NOT NULL,
    run_id uuid NOT NULL,
    source_event_id uuid NOT NULL,
    statement_hash text NOT NULL CHECK (statement_hash ~ '^sha256:[0-9a-f]{64}$'),
    belief_id uuid NOT NULL,
    belief_revision integer NOT NULL CHECK (belief_revision>0),
    authorization_ref text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (owner_id,run_id,source_event_id,statement_hash),
    UNIQUE (owner_id,belief_id,belief_revision),
    FOREIGN KEY (owner_id,run_id)
      REFERENCES havre.daily_diary_intelligence_runs(owner_id,run_id) ON DELETE CASCADE,
    FOREIGN KEY (owner_id,source_event_id)
      REFERENCES havre.events(owner_id,event_id) ON DELETE CASCADE,
    FOREIGN KEY (owner_id,belief_id,belief_revision)
      REFERENCES havre.user_belief_revisions(owner_id,belief_id,revision) ON DELETE CASCADE
);
CREATE INDEX owner_delegated_gpt_belief_source_idx
  ON havre.owner_delegated_gpt_belief_updates(owner_id,source_event_id);
CREATE UNIQUE INDEX owner_delegated_gpt_belief_statement_idx
  ON havre.owner_delegated_gpt_belief_updates(
    owner_id,source_event_id,statement_hash
  );

CREATE FUNCTION havre.guard_daily_diary_intelligence_source() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE source_event havre.events%ROWTYPE;
DECLARE run_row havre.daily_diary_intelligence_runs%ROWTYPE;
DECLARE routed_provider text;
BEGIN
  SELECT * INTO STRICT source_event FROM havre.events
  WHERE owner_id=NEW.owner_id AND event_id=NEW.event_id;
  SELECT * INTO STRICT run_row FROM havre.daily_diary_intelligence_runs
  WHERE owner_id=NEW.owner_id AND run_id=NEW.run_id;
  IF source_event.event_type NOT IN ('USER_MESSAGE','ASSISTANT_MESSAGE')
     OR source_event.content_hash<>NEW.event_content_hash
     OR (source_event.recorded_at AT TIME ZONE run_row.timezone_name)::date<>run_row.local_date THEN
    RAISE EXCEPTION 'Diary intelligence source must match its exact owner-local message Event'
      USING ERRCODE='55000';
  END IF;
  IF NEW.disposition='cloud_summary' AND (
       source_event.privacy_class NOT IN ('PUBLIC','NORMAL')
       OR NOT source_event.cloud_eligible
  ) THEN
    RAISE EXCEPTION 'private or non-cloud Event cannot enter Diary cloud summary input'
      USING ERRCODE='55000';
  END IF;
  IF NEW.disposition='cloud_summary' THEN
    SELECT selected_provider_id INTO routed_provider
    FROM havre.route_decisions
    WHERE owner_id=NEW.owner_id AND request_id=source_event.request_id;
    IF routed_provider IS DISTINCT FROM 'openai-codex-chatgpt' THEN
      RAISE EXCEPTION 'only GPT-routed Events may enter Diary cloud summary input'
        USING ERRCODE='55000';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER daily_diary_intelligence_source_guard
BEFORE INSERT ON havre.daily_diary_intelligence_sources
FOR EACH ROW EXECUTE FUNCTION havre.guard_daily_diary_intelligence_source();

CREATE TRIGGER daily_diary_intelligence_runs_immutable
BEFORE UPDATE OR DELETE ON havre.daily_diary_intelligence_runs
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();
CREATE TRIGGER daily_diary_intelligence_sources_immutable
BEFORE UPDATE OR DELETE ON havre.daily_diary_intelligence_sources
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();
CREATE TRIGGER owner_delegated_gpt_memory_updates_immutable
BEFORE UPDATE OR DELETE ON havre.owner_delegated_gpt_memory_updates
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();
CREATE TRIGGER owner_delegated_gpt_belief_updates_immutable
BEFORE UPDATE OR DELETE ON havre.owner_delegated_gpt_belief_updates
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='havre_application') THEN
    GRANT SELECT,INSERT ON havre.daily_diary_intelligence_runs TO havre_application;
    GRANT SELECT,INSERT ON havre.daily_diary_intelligence_sources TO havre_application;
    GRANT SELECT,INSERT ON havre.owner_delegated_gpt_memory_updates TO havre_application;
    GRANT SELECT,INSERT ON havre.owner_delegated_gpt_belief_updates TO havre_application;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='havre_privileged_erasure') THEN
    GRANT SELECT,DELETE ON havre.daily_diary_intelligence_runs TO havre_privileged_erasure;
    GRANT SELECT,DELETE ON havre.daily_diary_intelligence_sources TO havre_privileged_erasure;
    GRANT SELECT,DELETE ON havre.owner_delegated_gpt_memory_updates TO havre_privileged_erasure;
    GRANT SELECT,DELETE ON havre.owner_delegated_gpt_belief_updates TO havre_privileged_erasure;
  END IF;
END
$$;
