-- Additive closure for governed Web Push state, backlog eligibility, integrity,
-- and durable worker liveness. Migration 0043 is intentionally unchanged.

BEGIN;

ALTER TABLE havre.web_push_subscriptions
  ADD COLUMN delivery_eligible_from timestamptz NULL;
UPDATE havre.web_push_subscriptions
SET delivery_eligible_from=clock_timestamp()
WHERE delivery_eligible_from IS NULL;
ALTER TABLE havre.web_push_subscriptions
  ALTER COLUMN delivery_eligible_from SET NOT NULL,
  ADD CONSTRAINT web_push_subscription_watermark_check
    CHECK (delivery_eligible_from>=created_at);

CREATE FUNCTION havre.guard_web_push_subscription_transition() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE'
     AND current_setting('havre.privileged_erasure',true)='on'
     AND pg_has_role(current_user,'havre_privileged_erasure','MEMBER') THEN
    RETURN OLD;
  END IF;
  IF TG_OP='DELETE'
     OR NEW.owner_id<>OLD.owner_id OR NEW.subscription_id<>OLD.subscription_id
     OR NEW.device_id<>OLD.device_id OR NEW.endpoint<>OLD.endpoint
     OR NEW.endpoint_hash<>OLD.endpoint_hash OR NEW.p256dh<>OLD.p256dh
     OR NEW.auth_secret<>OLD.auth_secret OR NEW.preview_level<>OLD.preview_level
     OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
     OR NEW.vapid_key_version IS DISTINCT FROM OLD.vapid_key_version
     OR NEW.delivery_eligible_from<>OLD.delivery_eligible_from
     OR NEW.created_at<>OLD.created_at OR NEW.updated_at<OLD.updated_at
     OR OLD.status<>'active' OR NEW.status NOT IN ('active','revoked','expired')
     OR (NEW.status='revoked' AND (OLD.revoked_at IS NOT NULL OR NEW.revoked_at IS NULL))
     OR (NEW.status<>'revoked' AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at) THEN
    RAISE EXCEPTION 'web push subscription identity is immutable and terminal states cannot reopen'
      USING ERRCODE='55000';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER guard_web_push_subscription_transition
BEFORE UPDATE OR DELETE ON havre.web_push_subscriptions
FOR EACH ROW EXECUTE FUNCTION havre.guard_web_push_subscription_transition();

ALTER TABLE havre.web_push_dispatches
  ADD COLUMN delivery_eligible_until timestamptz NULL;
SET LOCAL session_replication_role='replica';
UPDATE havre.web_push_dispatches dispatch
SET delivery_eligible_until=LEAST(decision.expires_at,proposal.expires_at)
FROM havre.proactive_delivery_attempts attempt
JOIN havre.interruption_decisions decision
  ON decision.owner_id=attempt.owner_id
 AND decision.interruption_decision_id=attempt.interruption_decision_id
JOIN havre.proactive_proposals proposal
  ON proposal.owner_id=decision.owner_id AND proposal.proposal_id=decision.proposal_id
WHERE dispatch.owner_id=attempt.owner_id
  AND dispatch.proactive_delivery_attempt_id=attempt.delivery_attempt_id
  AND dispatch.delivery_eligible_until IS NULL;
SET LOCAL session_replication_role='origin';
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM havre.web_push_dispatches WHERE delivery_eligible_until IS NULL
  ) THEN
    RAISE EXCEPTION 'existing web push dispatch lacks an exact delivery eligibility window'
      USING ERRCODE='55000';
  END IF;
END
$$;
ALTER TABLE havre.web_push_dispatches
  ALTER COLUMN delivery_eligible_until SET NOT NULL;

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
  IF source_privacy='LOCAL_ONLY' OR source_privacy NOT IN (
      'PUBLIC','NORMAL','PRIVATE','HIGHLY_PRIVATE'
  ) THEN
    RAISE EXCEPTION 'source privacy is not eligible for external generic preview'
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
    AND inbox.visible_at>=subscription.delivery_eligible_from
    AND subscription.status='active'
    AND subscription.vapid_key_version=NEW.vapid_key_version
    AND (subscription.expires_at IS NULL OR subscription.expires_at>clock_timestamp())
    AND device.revoked_at IS NULL AND device.session_expires_at>clock_timestamp();
  IF chain_valid IS DISTINCT FROM true THEN
    RAISE EXCEPTION 'web push dispatch lacks a current SEND_NOW/device/subscription window'
      USING ERRCODE='55000';
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION havre.guard_web_push_dispatch_transition() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF current_setting('havre.privileged_erasure',true)='on'
     AND pg_has_role(current_user,'havre_privileged_erasure','MEMBER') THEN
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
  END IF;
  IF TG_OP='DELETE'
     OR NEW.owner_id<>OLD.owner_id OR NEW.dispatch_id<>OLD.dispatch_id
     OR NEW.subscription_id<>OLD.subscription_id
     OR NEW.assistant_event_id<>OLD.assistant_event_id
     OR NEW.proactive_delivery_attempt_id<>OLD.proactive_delivery_attempt_id
     OR NEW.delivery_locator<>OLD.delivery_locator
     OR NEW.vapid_key_version<>OLD.vapid_key_version
     OR NEW.payload_policy_version<>OLD.payload_policy_version
     OR NEW.authorization_ref<>OLD.authorization_ref
     OR NEW.max_attempts<>OLD.max_attempts OR NEW.created_at<>OLD.created_at
     OR NEW.delivery_eligible_until<>OLD.delivery_eligible_until THEN
    RAISE EXCEPTION 'web push dispatch identity is immutable' USING ERRCODE='55000';
  END IF;
  IF OLD.status IN ('pending','retry_wait') AND NEW.status='expired' THEN
    IF NEW.attempt_count<>OLD.attempt_count OR NEW.lease_owner IS NOT NULL
       OR NEW.lease_expires_at IS NOT NULL
       OR OLD.delivery_eligible_until>clock_timestamp() THEN
      RAISE EXCEPTION 'invalid stale web push expiry' USING ERRCODE='55000';
    END IF;
  ELSIF NEW.status='leased' THEN
    IF NEW.attempt_count<>OLD.attempt_count+1 OR NEW.lease_owner IS NULL
       OR NEW.lease_expires_at<=clock_timestamp()
       OR NEW.completed_at IS NOT NULL
       OR NOT (OLD.status IN ('pending','retry_wait')) THEN
      RAISE EXCEPTION 'invalid web push lease claim' USING ERRCODE='55000';
    END IF;
  ELSIF OLD.status='leased' AND NEW.status IN (
      'retry_wait','accepted','blocked','revoked','expired','dead'
  ) THEN
    IF NEW.attempt_count<>OLD.attempt_count OR NEW.lease_owner IS NOT NULL
       OR NEW.lease_expires_at IS NOT NULL THEN
      RAISE EXCEPTION 'invalid web push lease completion' USING ERRCODE='55000';
    END IF;
  ELSE
    RAISE EXCEPTION 'invalid web push dispatch transition' USING ERRCODE='55000';
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION havre.guard_web_push_attempt_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE dispatch havre.web_push_dispatches%ROWTYPE;
DECLARE expected_payload_hash text;
BEGIN
  IF NEW.dispatch_id IS NULL THEN RETURN NEW; END IF;
  SELECT * INTO STRICT dispatch FROM havre.web_push_dispatches
  WHERE owner_id=NEW.owner_id AND dispatch_id=NEW.dispatch_id;
  expected_payload_hash := 'sha256:' || encode(
    public.digest(convert_to(havre.canonical_jsonb(NEW.payload),'UTF8'),'sha256'),'hex'
  );
  IF dispatch.status<>'leased'
     OR NEW.subscription_id<>dispatch.subscription_id
     OR NEW.assistant_event_id<>dispatch.assistant_event_id
     OR NEW.proactive_delivery_attempt_id<>dispatch.proactive_delivery_attempt_id
     OR NEW.attempt_number<>dispatch.attempt_count
     OR NEW.idempotency_key<>('web-push:'||dispatch.dispatch_id::text)
     OR NEW.preview_level<>'private' OR NEW.payload_hash<>expected_payload_hash
     OR NEW.payload->>'delivery_locator'<>dispatch.delivery_locator::text
     OR NEW.payload->>'title'<>'HAVRE'
     OR NEW.payload->>'body'<>'HAVRE 有条消息给你' THEN
    RAISE EXCEPTION 'web push attempt does not match its active dispatch lease'
      USING ERRCODE='55000';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TABLE havre.web_push_worker_heartbeats (
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    worker_instance_id uuid NOT NULL,
    worker_id text NOT NULL CHECK (length(worker_id) BETWEEN 1 AND 160),
    adapter_version text NOT NULL CHECK (length(adapter_version) BETWEEN 1 AND 120),
    status text NOT NULL CHECK (status IN ('running','stopped')),
    started_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL,
    live_until timestamptz NOT NULL,
    PRIMARY KEY (owner_id,worker_instance_id),
    CHECK (last_seen_at>=started_at),
    CHECK (live_until>=last_seen_at)
);
CREATE INDEX web_push_worker_live_idx
  ON havre.web_push_worker_heartbeats(owner_id,live_until DESC)
  WHERE status='running';

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='havre_application') THEN
    GRANT SELECT,INSERT,UPDATE ON havre.web_push_worker_heartbeats TO havre_application;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='havre_privileged_erasure') THEN
    GRANT SELECT,DELETE ON havre.web_push_worker_heartbeats TO havre_privileged_erasure;
  END IF;
END
$$;

COMMIT;
