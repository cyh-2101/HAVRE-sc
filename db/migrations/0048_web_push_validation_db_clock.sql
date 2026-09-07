-- Bind real-device validation time to PostgreSQL statement time without
-- rewriting the already-applied 0047 migration.

BEGIN;

CREATE OR REPLACE FUNCTION havre.guard_web_push_real_device_validation_insert()
RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE chain_valid boolean;
BEGIN
  NEW.validated_at := clock_timestamp();
  SELECT true INTO chain_valid
  FROM havre.web_push_dispatches dispatch
  JOIN havre.web_push_delivery_attempts attempt
    ON attempt.owner_id=dispatch.owner_id
   AND attempt.dispatch_id=dispatch.dispatch_id
  JOIN havre.web_push_subscriptions subscription
    ON subscription.owner_id=dispatch.owner_id
   AND subscription.subscription_id=dispatch.subscription_id
  JOIN havre.companion_devices device
    ON device.owner_id=subscription.owner_id
   AND device.device_id=subscription.device_id
  JOIN havre.events event
    ON event.owner_id=dispatch.owner_id
   AND event.event_id=dispatch.assistant_event_id
  WHERE dispatch.owner_id=NEW.owner_id
    AND dispatch.dispatch_id=NEW.dispatch_id
    AND dispatch.status='accepted'
    AND dispatch.delivery_locator=NEW.delivery_locator
    AND dispatch.subscription_id=NEW.subscription_id
    AND dispatch.assistant_event_id=NEW.assistant_event_id
    AND attempt.web_push_attempt_id=NEW.web_push_attempt_id
    AND attempt.subscription_id=NEW.subscription_id
    AND attempt.assistant_event_id=NEW.assistant_event_id
    AND attempt.status='delivered'
    AND attempt.provider_receipt_id IS NOT NULL
    AND attempt.preview_level='private'
    AND attempt.payload->>'delivery_locator'=NEW.delivery_locator::text
    AND subscription.device_id=NEW.device_id
    AND event.event_type='ASSISTANT_MESSAGE';
  IF chain_valid IS DISTINCT FROM true THEN
    RAISE EXCEPTION 'real-device validation lacks an exact delivered dispatch chain'
      USING ERRCODE='55000';
  END IF;
  RETURN NEW;
END;
$$;

COMMIT;
