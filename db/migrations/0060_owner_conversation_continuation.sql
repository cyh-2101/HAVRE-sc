-- Owner-authorized, source-bound same-conversation continuation planning.
-- One eligible sharing turn may be reviewed after 30 seconds; a new owner
-- message cancels it, and Core remains the only delivery authority.

BEGIN;

CREATE TABLE havre.owner_conversation_continuation_runs (
    continuation_run_id uuid PRIMARY KEY,
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    source_user_event_id uuid NOT NULL,
    source_user_content_hash text NOT NULL CHECK (
      source_user_content_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    source_assistant_event_id uuid NOT NULL,
    source_assistant_content_hash text NOT NULL CHECK (
      source_assistant_content_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    session_id uuid NOT NULL,
    status text NOT NULL CHECK (status IN (
      'pending','leased','completed','no_action','retryable_failed','cancelled'
    )),
    not_before timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    lease_owner text NULL,
    lease_expires_at timestamptz NULL,
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count>=0),
    inference_request_id uuid NULL,
    request_binding_hash text NULL CHECK (
      request_binding_hash IS NULL OR request_binding_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    provider_id text NULL,
    model_version_id text NULL,
    provider_adapter_version_id text NULL,
    serving_config_version text NULL,
    reasoning_effort text NULL CHECK (reasoning_effort IS NULL),
    result jsonb NULL CHECK (result IS NULL OR jsonb_typeof(result)='object'),
    response_content_hash text NULL CHECK (
      response_content_hash IS NULL OR response_content_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    work_item_id uuid NULL,
    error_code text NULL,
    authorization_ref text NOT NULL CHECK (
      authorization_ref='product-owner/local-conversation-continuation-2026-09-04'
    ),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (owner_id,continuation_run_id),
    UNIQUE (owner_id,source_assistant_event_id),
    FOREIGN KEY (owner_id,source_user_event_id)
      REFERENCES havre.events(owner_id,event_id) ON DELETE CASCADE,
    FOREIGN KEY (owner_id,source_assistant_event_id)
      REFERENCES havre.events(owner_id,event_id) ON DELETE CASCADE,
    CHECK (expires_at>not_before),
    CHECK ((status='leased')=(lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)),
    CHECK (
      status NOT IN ('completed','no_action') OR (
        inference_request_id IS NOT NULL
        AND request_binding_hash IS NOT NULL
        AND provider_id='self-hosted-openai-compatible'
        AND model_version_id IS NOT NULL
        AND provider_adapter_version_id IS NOT NULL
        AND serving_config_version IS NOT NULL
        AND reasoning_effort IS NULL
        AND result IS NOT NULL
        AND response_content_hash IS NOT NULL
        AND error_code IS NULL
      )
    ),
    CHECK (status<>'completed' OR work_item_id IS NOT NULL),
    CHECK (status<>'no_action' OR work_item_id IS NULL),
    CHECK (status NOT IN ('retryable_failed','cancelled') OR error_code IS NOT NULL)
);

CREATE INDEX owner_conversation_continuation_claim_idx
  ON havre.owner_conversation_continuation_runs(status,not_before,created_at)
  WHERE status IN ('pending','retryable_failed','leased');
CREATE INDEX owner_conversation_continuation_user_source_idx
  ON havre.owner_conversation_continuation_runs(owner_id,source_user_event_id);
CREATE INDEX owner_conversation_continuation_work_idx
  ON havre.owner_conversation_continuation_runs(owner_id,work_item_id)
  WHERE work_item_id IS NOT NULL;

CREATE FUNCTION havre.guard_owner_conversation_continuation_run()
RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE user_event havre.events%ROWTYPE;
DECLARE assistant_event havre.events%ROWTYPE;
DECLARE routed_provider text;
DECLARE routed_environment text;
BEGIN
  IF TG_OP='UPDATE' AND (
       NEW.continuation_run_id IS DISTINCT FROM OLD.continuation_run_id
       OR NEW.owner_id IS DISTINCT FROM OLD.owner_id
       OR NEW.source_user_event_id IS DISTINCT FROM OLD.source_user_event_id
       OR NEW.source_user_content_hash IS DISTINCT FROM OLD.source_user_content_hash
       OR NEW.source_assistant_event_id IS DISTINCT FROM OLD.source_assistant_event_id
       OR NEW.source_assistant_content_hash IS DISTINCT FROM OLD.source_assistant_content_hash
       OR NEW.session_id IS DISTINCT FROM OLD.session_id
       OR NEW.not_before IS DISTINCT FROM OLD.not_before
       OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
       OR NEW.authorization_ref IS DISTINCT FROM OLD.authorization_ref
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
  ) THEN
    RAISE EXCEPTION 'conversation continuation source identity is immutable'
      USING ERRCODE='55000';
  END IF;

  SELECT * INTO STRICT user_event FROM havre.events
  WHERE owner_id=NEW.owner_id AND event_id=NEW.source_user_event_id;
  SELECT * INTO STRICT assistant_event FROM havre.events
  WHERE owner_id=NEW.owner_id AND event_id=NEW.source_assistant_event_id;
  SELECT route.selected_provider_id,route.execution_environment
    INTO routed_provider,routed_environment
  FROM havre.route_decisions route
  JOIN havre.interaction_requests request
    ON request.owner_id=route.owner_id AND request.request_id=route.request_id
  WHERE route.owner_id=NEW.owner_id AND route.request_id=user_event.request_id
    AND request.status='completed';
  IF user_event.event_type<>'USER_MESSAGE'
     OR assistant_event.event_type<>'ASSISTANT_MESSAGE'
     OR user_event.content_hash<>NEW.source_user_content_hash
     OR assistant_event.content_hash<>NEW.source_assistant_content_hash
     OR user_event.session_id<>NEW.session_id
     OR assistant_event.session_id<>NEW.session_id
     OR assistant_event.request_id<>user_event.request_id
     OR assistant_event.causation_event_id<>user_event.event_id
     OR user_event.privacy_class NOT IN ('PUBLIC','NORMAL')
     OR assistant_event.privacy_class NOT IN ('PUBLIC','NORMAL')
     OR NOT user_event.cloud_eligible OR NOT assistant_event.cloud_eligible
     OR routed_provider IS DISTINCT FROM 'openai-codex-chatgpt'
     OR routed_environment IS DISTINCT FROM 'cloud'
     OR NEW.not_before<assistant_event.recorded_at+interval '30 seconds'
     OR NEW.expires_at>assistant_event.recorded_at+interval '15 minutes'
  THEN
    RAISE EXCEPTION 'conversation continuation must match one exact eligible completed turn'
      USING ERRCODE='55000';
  END IF;

  IF TG_OP='UPDATE' THEN
    IF OLD.status IN ('completed','no_action','cancelled')
       AND NEW.status<>OLD.status THEN
      RAISE EXCEPTION 'terminal conversation continuation status is immutable'
        USING ERRCODE='55000';
    END IF;
    IF OLD.status='pending' AND NEW.status NOT IN ('pending','leased','cancelled') THEN
      RAISE EXCEPTION 'invalid pending conversation continuation transition'
        USING ERRCODE='55000';
    END IF;
    IF OLD.status='leased' AND NEW.status NOT IN (
         'pending','leased','completed','no_action','retryable_failed','cancelled'
       ) THEN
      RAISE EXCEPTION 'invalid leased conversation continuation transition'
        USING ERRCODE='55000';
    END IF;
    IF OLD.status='retryable_failed' AND NEW.status NOT IN (
         'retryable_failed','leased','cancelled'
       ) THEN
      RAISE EXCEPTION 'invalid retryable conversation continuation transition'
        USING ERRCODE='55000';
    END IF;
  END IF;
  NEW.updated_at := statement_timestamp();
  RETURN NEW;
END;
$$;

CREATE TRIGGER owner_conversation_continuation_guard
BEFORE INSERT OR UPDATE ON havre.owner_conversation_continuation_runs
FOR EACH ROW EXECUTE FUNCTION havre.guard_owner_conversation_continuation_run();

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='havre_application') THEN
    GRANT SELECT,INSERT,UPDATE ON havre.owner_conversation_continuation_runs
      TO havre_application;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='havre_privileged_erasure') THEN
    GRANT SELECT,DELETE ON havre.owner_conversation_continuation_runs
      TO havre_privileged_erasure;
  END IF;
END
$$;

COMMIT;
