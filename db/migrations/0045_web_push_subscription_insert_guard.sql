-- Bind subscription registration identity and eligibility time at the durable boundary.

BEGIN;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM havre.web_push_subscriptions
    WHERE endpoint_hash<>'sha256:' || encode(
      public.digest(convert_to(endpoint,'UTF8'),'sha256'),'hex'
    )
  ) THEN
    RAISE EXCEPTION 'existing web push subscription endpoint hash is not canonical'
      USING ERRCODE='55000';
  END IF;
END
$$;

CREATE OR REPLACE FUNCTION havre.guard_web_push_subscription_transition() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE expected_endpoint_hash text;
DECLARE registered_at timestamptz;
BEGIN
  IF TG_OP='INSERT' THEN
    expected_endpoint_hash := 'sha256:' || encode(
      public.digest(convert_to(NEW.endpoint,'UTF8'),'sha256'),'hex'
    );
    IF NEW.status<>'active' OR NEW.revoked_at IS NOT NULL
       OR NEW.last_success_at IS NOT NULL OR NEW.last_failure_at IS NOT NULL
       OR NEW.endpoint_hash<>expected_endpoint_hash THEN
      RAISE EXCEPTION 'new web push subscription lacks canonical active identity'
        USING ERRCODE='55000';
    END IF;
    registered_at := clock_timestamp();
    NEW.created_at := registered_at;
    NEW.updated_at := registered_at;
    NEW.delivery_eligible_from := registered_at;
    RETURN NEW;
  END IF;
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

DROP TRIGGER guard_web_push_subscription_transition
  ON havre.web_push_subscriptions;
CREATE TRIGGER guard_web_push_subscription_transition
BEFORE INSERT OR UPDATE OR DELETE ON havre.web_push_subscriptions
FOR EACH ROW EXECUTE FUNCTION havre.guard_web_push_subscription_transition();

COMMIT;
