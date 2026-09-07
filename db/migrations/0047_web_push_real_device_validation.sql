-- Durable owner-confirmed closure for a real-device Web Push delivery.
-- This records physical receipt/tap/timeline evidence only after an accepted
-- governed dispatch. It does not authorize a dispatch or change Reach Out.

BEGIN;

CREATE TABLE havre.web_push_real_device_validations (
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    validation_id uuid NOT NULL,
    dispatch_id uuid NOT NULL,
    web_push_attempt_id uuid NOT NULL,
    subscription_id uuid NOT NULL,
    device_id uuid NOT NULL,
    assistant_event_id uuid NOT NULL,
    delivery_locator uuid NOT NULL,
    validation_kind text NOT NULL CHECK (
      validation_kind='lock_screen_tap_timeline_located'
    ),
    pwa_shell_version text NOT NULL CHECK (
      pwa_shell_version ~ '^havre-shell-v[0-9]+$'
    ),
    owner_confirmation_ref text NOT NULL CHECK (
      length(owner_confirmation_ref) BETWEEN 1 AND 500
    ),
    lock_screen_received boolean NOT NULL CHECK (lock_screen_received),
    notification_tap_opened boolean NOT NULL CHECK (notification_tap_opened),
    timeline_message_located boolean NOT NULL CHECK (timeline_message_located),
    validated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (owner_id,validation_id),
    UNIQUE (owner_id,dispatch_id),
    FOREIGN KEY (owner_id,dispatch_id)
      REFERENCES havre.web_push_dispatches(owner_id,dispatch_id),
    FOREIGN KEY (owner_id,web_push_attempt_id)
      REFERENCES havre.web_push_delivery_attempts(owner_id,web_push_attempt_id),
    FOREIGN KEY (owner_id,subscription_id)
      REFERENCES havre.web_push_subscriptions(owner_id,subscription_id),
    FOREIGN KEY (owner_id,device_id)
      REFERENCES havre.companion_devices(owner_id,device_id),
    FOREIGN KEY (owner_id,assistant_event_id)
      REFERENCES havre.events(owner_id,event_id),
    UNIQUE (owner_id,delivery_locator)
);
CREATE INDEX web_push_real_device_validation_attempt_idx
  ON havre.web_push_real_device_validations(owner_id,web_push_attempt_id);
CREATE INDEX web_push_real_device_validation_subscription_idx
  ON havre.web_push_real_device_validations(owner_id,subscription_id);
CREATE INDEX web_push_real_device_validation_device_idx
  ON havre.web_push_real_device_validations(owner_id,device_id);
CREATE INDEX web_push_real_device_validation_event_idx
  ON havre.web_push_real_device_validations(owner_id,assistant_event_id);

CREATE FUNCTION havre.guard_web_push_real_device_validation_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE chain_valid boolean;
BEGIN
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
CREATE TRIGGER guard_web_push_real_device_validation_insert
BEFORE INSERT ON havre.web_push_real_device_validations
FOR EACH ROW EXECUTE FUNCTION havre.guard_web_push_real_device_validation_insert();

CREATE FUNCTION havre.guard_web_push_real_device_validation_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE'
     AND current_setting('havre.privileged_erasure',true)='on'
     AND pg_has_role(current_user,'havre_privileged_erasure','MEMBER') THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'real-device validations are immutable'
    USING ERRCODE='55000';
END;
$$;
CREATE TRIGGER guard_web_push_real_device_validation_immutable
BEFORE UPDATE OR DELETE ON havre.web_push_real_device_validations
FOR EACH ROW EXECUTE FUNCTION havre.guard_web_push_real_device_validation_immutable();

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='havre_application') THEN
    GRANT SELECT,INSERT ON havre.web_push_real_device_validations
      TO havre_application;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='havre_privileged_erasure') THEN
    GRANT SELECT,DELETE ON havre.web_push_real_device_validations
      TO havre_privileged_erasure;
  END IF;
END
$$;

COMMIT;
