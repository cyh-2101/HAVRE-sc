-- Governed automatic proactive trigger evaluation and the Product Owner-approved
-- generic-only Web Push envelope for LOCAL_ONLY assistant Events.

BEGIN;

CREATE TABLE havre.proactive_trigger_evaluations (
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    evaluation_id uuid NOT NULL,
    evaluator_version text NOT NULL CHECK (
        evaluator_version = 'proactive-trigger-evaluator-v1'
    ),
    source_event_id uuid NOT NULL,
    source_event_content_hash text NOT NULL CHECK (source_event_content_hash ~ '^sha256:[0-9a-f]{64}$'),
    source_event_type text NOT NULL CHECK (source_event_type IN (
        'USER_MESSAGE','GOAL_CREATED','GOAL_UPDATED','SCENE_SESSION_PLANNED',
        'MEMORY_CREATED','MEMORY_REVISED','CURRENT_STATE_ESTIMATED',
        'LIFE_CONTEXT_OBSERVED','USER_BELIEF_CREATED','USER_BELIEF_REVISED',
        'USER_BELIEF_TRANSITIONED'
    )),
    candidate_kind text NOT NULL CHECK (candidate_kind IN (
        'owner_reminder','goal_review','scene_start','context_only'
    )),
    disposition text NOT NULL CHECK (disposition IN (
        'enqueued','ignored','expired'
    )),
    reason_code text NOT NULL CHECK (reason_code ~ '^[a-z][a-z0-9_]{1,95}$'),
    work_item_id uuid NULL,
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    evaluated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (owner_id,evaluation_id),
    UNIQUE (owner_id,evaluator_version,source_event_id,source_event_content_hash),
    FOREIGN KEY (owner_id,source_event_id)
      REFERENCES havre.events(owner_id,event_id),
    FOREIGN KEY (owner_id,work_item_id)
      REFERENCES havre.proactive_work_items(owner_id,work_item_id),
    CHECK ((disposition='enqueued')=(work_item_id IS NOT NULL))
);
CREATE INDEX proactive_trigger_evaluations_source_idx
  ON havre.proactive_trigger_evaluations(owner_id,source_event_id);
CREATE INDEX proactive_trigger_evaluations_work_idx
  ON havre.proactive_trigger_evaluations(owner_id,work_item_id)
  WHERE work_item_id IS NOT NULL;

CREATE FUNCTION havre.guard_proactive_trigger_evaluation_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE source_row havre.events%ROWTYPE;
DECLARE work_payload jsonb;
BEGIN
  SELECT * INTO STRICT source_row FROM havre.events
  WHERE owner_id=NEW.owner_id AND event_id=NEW.source_event_id;
  IF source_row.content_hash<>NEW.source_event_content_hash
     OR source_row.event_type<>NEW.source_event_type THEN
    RAISE EXCEPTION 'trigger evaluation source does not match the exact Event'
      USING ERRCODE='55000';
  END IF;
  IF NEW.candidate_kind IN ('owner_reminder','goal_review','scene_start') AND NOT (
      (NEW.candidate_kind='owner_reminder' AND source_row.event_type='USER_MESSAGE')
      OR (NEW.candidate_kind='goal_review' AND source_row.event_type IN ('GOAL_CREATED','GOAL_UPDATED'))
      OR (NEW.candidate_kind='scene_start' AND source_row.event_type='SCENE_SESSION_PLANNED')
  ) THEN
    RAISE EXCEPTION 'trigger candidate kind does not match source Event type'
      USING ERRCODE='55000';
  END IF;
  IF NEW.candidate_kind='context_only' AND source_row.event_type NOT IN (
      'MEMORY_CREATED','MEMORY_REVISED','CURRENT_STATE_ESTIMATED',
      'LIFE_CONTEXT_OBSERVED','USER_BELIEF_CREATED','USER_BELIEF_REVISED',
      'USER_BELIEF_TRANSITIONED'
  ) THEN
    RAISE EXCEPTION 'context-only evaluation requires a context Event'
      USING ERRCODE='55000';
  END IF;
  IF NEW.work_item_id IS NOT NULL THEN
    SELECT command_payload INTO STRICT work_payload
    FROM havre.proactive_work_items
    WHERE owner_id=NEW.owner_id AND work_item_id=NEW.work_item_id;
    IF work_payload->>'trigger_source_version'<>NEW.evaluator_version
       OR work_payload#>>'{source_guard,source_event_id}'<>NEW.source_event_id::text
       OR work_payload#>>'{source_guard,source_event_content_hash}'<>NEW.source_event_content_hash THEN
      RAISE EXCEPTION 'queued proactive work is not bound to its exact evaluation source'
        USING ERRCODE='55000';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER guard_proactive_trigger_evaluation_insert
BEFORE INSERT ON havre.proactive_trigger_evaluations
FOR EACH ROW EXECUTE FUNCTION havre.guard_proactive_trigger_evaluation_insert();

CREATE FUNCTION havre.guard_proactive_trigger_evaluation_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE'
     AND current_setting('havre.privileged_erasure',true)='on'
     AND pg_has_role(current_user,'havre_privileged_erasure','MEMBER') THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'proactive trigger evaluations are immutable'
    USING ERRCODE='55000';
END;
$$;
CREATE TRIGGER guard_proactive_trigger_evaluation_immutable
BEFORE UPDATE OR DELETE ON havre.proactive_trigger_evaluations
FOR EACH ROW EXECUTE FUNCTION havre.guard_proactive_trigger_evaluation_immutable();

CREATE OR REPLACE FUNCTION havre.guard_web_push_dispatch_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE source_privacy text;
DECLARE chain_valid boolean;
BEGIN
  IF NEW.status<>'pending' OR NEW.attempt_count<>0 OR NEW.lease_owner IS NOT NULL
     OR NEW.lease_expires_at IS NOT NULL OR NEW.completed_at IS NOT NULL THEN
    RAISE EXCEPTION 'new web push dispatch must begin pending and unleased'
      USING ERRCODE='55000';
  END IF;
  SELECT event.privacy_class INTO STRICT source_privacy
  FROM havre.events event
  WHERE event.owner_id=NEW.owner_id AND event.event_id=NEW.assistant_event_id
    AND event.event_type='ASSISTANT_MESSAGE';
  IF source_privacy NOT IN ('PUBLIC','NORMAL','PRIVATE','HIGHLY_PRIVATE','LOCAL_ONLY') THEN
    RAISE EXCEPTION 'source privacy is not eligible for an external generic envelope'
      USING ERRCODE='55000';
  END IF;
  SELECT true INTO chain_valid
  FROM havre.proactive_inbox_messages inbox
  JOIN havre.proactive_delivery_attempts attempt
    ON attempt.owner_id=inbox.owner_id
   AND attempt.delivery_attempt_id=inbox.delivery_attempt_id
  JOIN havre.interruption_decisions decision
    ON decision.owner_id=attempt.owner_id
   AND decision.interruption_decision_id=attempt.interruption_decision_id
  JOIN havre.proactive_proposals proposal
    ON proposal.owner_id=decision.owner_id AND proposal.proposal_id=decision.proposal_id
  JOIN havre.proactive_preference_revisions preference
    ON preference.owner_id=decision.owner_id
   AND preference.preference_revision_id=decision.preference_revision_id
  JOIN havre.web_push_subscriptions subscription
    ON subscription.owner_id=inbox.owner_id
   AND subscription.subscription_id=NEW.subscription_id
  JOIN havre.companion_devices device
    ON device.owner_id=subscription.owner_id AND device.device_id=subscription.device_id
  WHERE inbox.owner_id=NEW.owner_id
    AND inbox.assistant_event_id=NEW.assistant_event_id
    AND inbox.delivery_attempt_id=NEW.proactive_delivery_attempt_id
    AND decision.decision='SEND_NOW' AND attempt.status='delivered'
    AND decision.expires_at>clock_timestamp()
    AND proposal.expires_at>clock_timestamp()
    AND NEW.delivery_eligible_until=LEAST(decision.expires_at,proposal.expires_at)
    AND inbox.external_delivery_admitted_at IS NOT NULL
    AND inbox.external_delivery_admitted_at>=subscription.delivery_eligible_from
    AND (
      source_privacy IN ('PUBLIC','NORMAL','PRIVATE','HIGHLY_PRIVATE')
      OR (
        source_privacy='LOCAL_ONLY'
        AND COALESCE((preference.payload->>'generic_push_for_local_only')::boolean,false)
      )
    )
    AND subscription.status='active'
    AND subscription.vapid_key_version=NEW.vapid_key_version
    AND (subscription.expires_at IS NULL OR subscription.expires_at>clock_timestamp())
    AND device.revoked_at IS NULL AND device.session_expires_at>clock_timestamp();
  IF chain_valid IS DISTINCT FROM true THEN
    RAISE EXCEPTION 'web push dispatch lacks a current authorized SEND_NOW/device/subscription window'
      USING ERRCODE='55000';
  END IF;
  RETURN NEW;
END;
$$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='havre_application') THEN
    GRANT SELECT,INSERT ON havre.proactive_trigger_evaluations TO havre_application;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='havre_privileged_erasure') THEN
    GRANT SELECT,DELETE ON havre.proactive_trigger_evaluations TO havre_privileged_erasure;
  END IF;
END
$$;

COMMIT;
