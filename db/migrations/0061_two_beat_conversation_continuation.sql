-- Owner-authorized two-beat continuation for an active everyday conversation.
-- The first beat is due one minute after the completed turn. A second beat may
-- exist only after the first was actually delivered and is due 30 minutes later.

BEGIN;

ALTER TABLE havre.owner_conversation_continuation_runs
  ADD COLUMN beat_index smallint NOT NULL DEFAULT 1,
  ADD COLUMN prior_continuation_run_id uuid NULL;

ALTER TABLE havre.owner_conversation_continuation_runs
  DROP CONSTRAINT owner_conversation_continuati_owner_id_source_assistant_eve_key,
  DROP CONSTRAINT owner_conversation_continuation_runs_authorization_ref_check;

ALTER TABLE havre.owner_conversation_continuation_runs
  ADD CONSTRAINT owner_conversation_continuation_beat_check
    CHECK (beat_index IN (1,2)),
  ADD CONSTRAINT owner_conversation_continuation_parent_shape_check
    CHECK (
      (beat_index=1 AND prior_continuation_run_id IS NULL)
      OR (beat_index=2 AND prior_continuation_run_id IS NOT NULL)
    ),
  ADD CONSTRAINT owner_conversation_continuation_authorization_check
    CHECK (authorization_ref IN (
      'product-owner/local-conversation-continuation-2026-09-04',
      'product-owner/two-beat-friend-conversation-2026-09-04'
    )),
  ADD CONSTRAINT owner_conversation_continuation_source_beat_key
    UNIQUE (owner_id,source_assistant_event_id,beat_index),
  ADD CONSTRAINT owner_conversation_continuation_parent_fkey
    FOREIGN KEY (owner_id,prior_continuation_run_id)
    REFERENCES havre.owner_conversation_continuation_runs(
      owner_id,continuation_run_id
    ) ON DELETE CASCADE;

CREATE INDEX owner_conversation_continuation_parent_idx
  ON havre.owner_conversation_continuation_runs(
    owner_id,prior_continuation_run_id
  ) WHERE prior_continuation_run_id IS NOT NULL;

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

  IF NEW.authorization_ref='product-owner/local-conversation-continuation-2026-09-04' THEN
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
      AND work.status='completed'
      AND attempt.status='delivered';

    IF parent_run.beat_index<>1
       OR parent_run.authorization_ref<>
          'product-owner/two-beat-friend-conversation-2026-09-04'
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
