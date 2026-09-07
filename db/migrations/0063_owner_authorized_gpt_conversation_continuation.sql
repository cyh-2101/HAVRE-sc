-- Product Owner-authorized GPT-5.6-sol/high planning for the bounded two-beat
-- conversation continuation. Existing local receipts retain their original
-- provider authorization and remain processable without rewriting history.

BEGIN;

ALTER TABLE havre.owner_conversation_continuation_runs
  DROP CONSTRAINT owner_conversation_continuation_authorization_check;

ALTER TABLE havre.owner_conversation_continuation_runs
  DROP CONSTRAINT owner_conversation_continuation_runs_reasoning_effort_check;

DO $$
DECLARE terminal_constraint text;
BEGIN
  SELECT constraint_row.conname INTO STRICT terminal_constraint
  FROM pg_constraint constraint_row
  WHERE constraint_row.conrelid=
        'havre.owner_conversation_continuation_runs'::regclass
    AND constraint_row.contype='c'
    AND pg_get_constraintdef(constraint_row.oid)
        LIKE '%provider_id = ''self-hosted-openai-compatible''%'
    AND pg_get_constraintdef(constraint_row.oid)
        LIKE '%inference_request_id IS NOT NULL%';

  EXECUTE format(
    'ALTER TABLE havre.owner_conversation_continuation_runs DROP CONSTRAINT %I',
    terminal_constraint
  );
END
$$;

ALTER TABLE havre.owner_conversation_continuation_runs
  ADD CONSTRAINT owner_conversation_continuation_authorization_check
    CHECK (authorization_ref IN (
      'product-owner/local-conversation-continuation-2026-09-04',
      'product-owner/two-beat-friend-conversation-2026-09-04',
      'product-owner/gpt-two-beat-friend-conversation-2026-09-04'
    )),
  ADD CONSTRAINT owner_conversation_continuation_reasoning_effort_check
    CHECK (reasoning_effort IS NULL OR reasoning_effort='high'),
  ADD CONSTRAINT owner_conversation_continuation_terminal_provider_check
    CHECK (
      status NOT IN ('completed','no_action') OR (
        inference_request_id IS NOT NULL
        AND request_binding_hash IS NOT NULL
        AND model_version_id IS NOT NULL
        AND provider_adapter_version_id IS NOT NULL
        AND serving_config_version IS NOT NULL
        AND result IS NOT NULL
        AND response_content_hash IS NOT NULL
        AND error_code IS NULL
        AND (
          (
            authorization_ref IN (
              'product-owner/local-conversation-continuation-2026-09-04',
              'product-owner/two-beat-friend-conversation-2026-09-04'
            )
            AND provider_id='self-hosted-openai-compatible'
            AND reasoning_effort IS NULL
          )
          OR
          (
            authorization_ref=
              'product-owner/gpt-two-beat-friend-conversation-2026-09-04'
            AND provider_id='openai-codex-chatgpt'
            AND model_version_id='gpt-5.6-sol'
            AND provider_adapter_version_id=
              'codex-cli-provider-v2-owner-automatic'
            AND serving_config_version=
              'codex-cli-reply-only-no-tools-v2-high'
            AND reasoning_effort='high'
          )
        )
      )
    );

CREATE OR REPLACE FUNCTION havre.guard_owner_conversation_continuation_run()
RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE user_event havre.events%ROWTYPE;
DECLARE assistant_event havre.events%ROWTYPE;
DECLARE parent_run havre.owner_conversation_continuation_runs%ROWTYPE;
DECLARE routed_provider text;
DECLARE routed_environment text;
DECLARE parent_visible_at timestamptz;
BEGIN
  IF TG_OP='UPDATE' AND (
       NEW.continuation_run_id IS DISTINCT FROM OLD.continuation_run_id
       OR NEW.owner_id IS DISTINCT FROM OLD.owner_id
       OR NEW.source_user_event_id IS DISTINCT FROM OLD.source_user_event_id
       OR NEW.source_user_content_hash IS DISTINCT FROM OLD.source_user_content_hash
       OR NEW.source_assistant_event_id IS DISTINCT FROM OLD.source_assistant_event_id
       OR NEW.source_assistant_content_hash IS DISTINCT FROM OLD.source_assistant_content_hash
       OR NEW.session_id IS DISTINCT FROM OLD.session_id
       OR NEW.beat_index IS DISTINCT FROM OLD.beat_index
       OR NEW.prior_continuation_run_id IS DISTINCT FROM OLD.prior_continuation_run_id
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
  THEN
    RAISE EXCEPTION 'conversation continuation must match one exact eligible completed turn'
      USING ERRCODE='55000';
  END IF;

  IF NEW.authorization_ref=
     'product-owner/local-conversation-continuation-2026-09-04' THEN
    IF NEW.beat_index<>1
       OR NEW.prior_continuation_run_id IS NOT NULL
       OR NEW.not_before<assistant_event.recorded_at+interval '30 seconds'
       OR NEW.expires_at>assistant_event.recorded_at+interval '15 minutes'
    THEN
      RAISE EXCEPTION 'legacy continuation timing or shape is invalid'
        USING ERRCODE='55000';
    END IF;
  ELSIF NEW.beat_index=1 THEN
    IF NEW.prior_continuation_run_id IS NOT NULL
       OR NEW.not_before<>assistant_event.recorded_at+interval '1 minute'
       OR NEW.expires_at<>assistant_event.recorded_at+interval '16 minutes'
    THEN
      RAISE EXCEPTION 'first friend-conversation beat must use the exact one-minute window'
        USING ERRCODE='55000';
    END IF;
  ELSE
    SELECT * INTO STRICT parent_run
    FROM havre.owner_conversation_continuation_runs
    WHERE owner_id=NEW.owner_id
      AND continuation_run_id=NEW.prior_continuation_run_id;

    SELECT max(attempt.visible_at) INTO parent_visible_at
    FROM havre.proactive_work_items work
    JOIN havre.proactive_delivery_attempts attempt
      ON attempt.owner_id=work.owner_id
     AND attempt.proposal_id=work.proposal_id
    WHERE work.owner_id=NEW.owner_id
      AND work.work_item_id=parent_run.work_item_id
      AND work.status='succeeded'
      AND attempt.status='delivered';

    IF parent_run.beat_index<>1
       OR parent_run.authorization_ref<>NEW.authorization_ref
       OR parent_run.authorization_ref NOT IN (
          'product-owner/two-beat-friend-conversation-2026-09-04',
          'product-owner/gpt-two-beat-friend-conversation-2026-09-04'
       )
       OR parent_run.status<>'completed'
       OR COALESCE((parent_run.result->>'send')::boolean,false) IS NOT TRUE
       OR parent_run.source_user_event_id<>NEW.source_user_event_id
       OR parent_run.source_user_content_hash<>NEW.source_user_content_hash
       OR parent_run.source_assistant_event_id<>NEW.source_assistant_event_id
       OR parent_run.source_assistant_content_hash<>NEW.source_assistant_content_hash
       OR parent_run.session_id<>NEW.session_id
       OR parent_visible_at IS NULL
       OR NEW.not_before<>parent_visible_at+interval '30 minutes'
       OR NEW.expires_at<>parent_visible_at+interval '45 minutes'
    THEN
      RAISE EXCEPTION 'second friend-conversation beat requires one exact delivered first beat'
        USING ERRCODE='55000';
    END IF;
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

COMMIT;
