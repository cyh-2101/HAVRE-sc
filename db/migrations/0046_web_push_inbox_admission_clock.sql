-- Use one database clock for external-delivery eligibility ordering. Existing
-- inbox history remains NULL and is therefore permanently ineligible.

BEGIN;

ALTER TABLE havre.proactive_inbox_messages
  ADD COLUMN external_delivery_admitted_at timestamptz NULL;

CREATE FUNCTION havre.guard_external_delivery_admission() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='INSERT' THEN
    NEW.external_delivery_admitted_at := clock_timestamp();
    RETURN NEW;
  END IF;
  IF NEW.external_delivery_admitted_at IS DISTINCT FROM OLD.external_delivery_admitted_at THEN
    RAISE EXCEPTION 'external delivery admission time is immutable'
      USING ERRCODE='55000';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER guard_external_delivery_admission
BEFORE INSERT OR UPDATE ON havre.proactive_inbox_messages
FOR EACH ROW EXECUTE FUNCTION havre.guard_external_delivery_admission();

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
    AND inbox.external_delivery_admitted_at IS NOT NULL
    AND inbox.external_delivery_admitted_at>=subscription.delivery_eligible_from
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

COMMIT;
