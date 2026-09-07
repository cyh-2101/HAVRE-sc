-- Governed external Web Push activation. The existing Stage 6 web_inbox
-- lifecycle remains unchanged; this migration adds a separately authorized,
-- generic-only delivery queue after the canonical assistant Event exists.

BEGIN;

CREATE TABLE havre.web_push_vapid_key_versions (
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    vapid_key_version text NOT NULL CHECK (vapid_key_version ~ '^vapid-[a-z0-9][a-z0-9._-]{1,63}$'),
    public_key text NOT NULL CHECK (length(public_key) BETWEEN 40 AND 256),
    public_key_hash text NOT NULL CHECK (public_key_hash ~ '^sha256:[0-9a-f]{64}$'),
    secret_storage text NOT NULL CHECK (secret_storage='windows_dpapi_current_user'),
    status text NOT NULL CHECK (status IN ('active','retired')),
    authorization_ref text NOT NULL CHECK (length(authorization_ref) BETWEEN 1 AND 500),
    activated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    retired_at timestamptz NULL,
    PRIMARY KEY (owner_id,vapid_key_version),
    CHECK ((status='retired')=(retired_at IS NOT NULL))
);
CREATE UNIQUE INDEX web_push_one_active_vapid_key_per_owner
  ON havre.web_push_vapid_key_versions(owner_id) WHERE status='active';

CREATE FUNCTION havre.guard_web_push_vapid_key_transition() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF current_setting('havre.privileged_erasure',true)='on'
     AND pg_has_role(current_user,'havre_privileged_erasure','MEMBER') THEN
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
  END IF;
  IF TG_OP='DELETE' OR NEW.owner_id<>OLD.owner_id
     OR NEW.vapid_key_version<>OLD.vapid_key_version
     OR NEW.public_key<>OLD.public_key OR NEW.public_key_hash<>OLD.public_key_hash
     OR NEW.secret_storage<>OLD.secret_storage
     OR NEW.authorization_ref<>OLD.authorization_ref
     OR NEW.activated_at<>OLD.activated_at
     OR OLD.status<>'active' OR NEW.status<>'retired'
     OR OLD.retired_at IS NOT NULL OR NEW.retired_at IS NULL THEN
    RAISE EXCEPTION 'VAPID key identity is immutable; only first retirement is allowed'
      USING ERRCODE='55000';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER guard_web_push_vapid_key_transition
BEFORE UPDATE OR DELETE ON havre.web_push_vapid_key_versions
FOR EACH ROW EXECUTE FUNCTION havre.guard_web_push_vapid_key_transition();

ALTER TABLE havre.web_push_subscriptions
  ADD COLUMN vapid_key_version text NULL,
  ADD CONSTRAINT web_push_subscription_vapid_fk
    FOREIGN KEY (owner_id,vapid_key_version)
    REFERENCES havre.web_push_vapid_key_versions(owner_id,vapid_key_version),
  ADD CONSTRAINT web_push_apple_endpoint_check CHECK (
    endpoint ~ '^https://web[.]push[.]apple[.]com(?::443)?/[^#[:space:]]+$'
  ) NOT VALID;
CREATE INDEX web_push_subscriptions_vapid_fk_idx
  ON havre.web_push_subscriptions(owner_id,vapid_key_version)
  WHERE vapid_key_version IS NOT NULL;

CREATE TABLE havre.web_push_dispatches (
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    dispatch_id uuid NOT NULL,
    subscription_id uuid NOT NULL,
    assistant_event_id uuid NOT NULL,
    proactive_delivery_attempt_id uuid NOT NULL,
    delivery_locator uuid NOT NULL,
    vapid_key_version text NOT NULL,
    payload_policy_version text NOT NULL
      CHECK (payload_policy_version='generic-private-preview-v1'),
    authorization_ref text NOT NULL
      CHECK (authorization_ref='po-private-web-push-2026-08-27'),
    status text NOT NULL CHECK (status IN (
      'pending','leased','retry_wait','accepted','blocked','revoked','expired','dead'
    )),
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count BETWEEN 0 AND 8),
    max_attempts integer NOT NULL DEFAULT 4 CHECK (max_attempts BETWEEN 1 AND 8),
    next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    lease_owner text NULL CHECK (lease_owner IS NULL OR length(lease_owner) BETWEEN 1 AND 160),
    lease_expires_at timestamptz NULL,
    last_error_code text NULL CHECK (last_error_code IS NULL OR length(last_error_code)<=120),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at timestamptz NULL,
    PRIMARY KEY (owner_id,dispatch_id),
    UNIQUE (owner_id,subscription_id,assistant_event_id),
    UNIQUE (owner_id,delivery_locator),
    FOREIGN KEY (owner_id,subscription_id)
      REFERENCES havre.web_push_subscriptions(owner_id,subscription_id),
    FOREIGN KEY (owner_id,assistant_event_id)
      REFERENCES havre.events(owner_id,event_id),
    FOREIGN KEY (owner_id,proactive_delivery_attempt_id)
      REFERENCES havre.proactive_delivery_attempts(owner_id,delivery_attempt_id),
    FOREIGN KEY (owner_id,vapid_key_version)
      REFERENCES havre.web_push_vapid_key_versions(owner_id,vapid_key_version),
    CHECK ((status='leased')=(lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)),
    CHECK ((status IN ('accepted','blocked','revoked','expired','dead'))=(completed_at IS NOT NULL))
);
CREATE INDEX web_push_dispatch_claim_idx
  ON havre.web_push_dispatches(owner_id,next_attempt_at,created_at)
  WHERE status IN ('pending','leased','retry_wait');
CREATE INDEX web_push_dispatch_event_fk_idx
  ON havre.web_push_dispatches(owner_id,assistant_event_id);
CREATE INDEX web_push_dispatch_proactive_attempt_fk_idx
  ON havre.web_push_dispatches(owner_id,proactive_delivery_attempt_id);
CREATE INDEX web_push_dispatch_vapid_fk_idx
  ON havre.web_push_dispatches(owner_id,vapid_key_version);

CREATE FUNCTION havre.guard_web_push_dispatch_insert() RETURNS trigger
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
  JOIN havre.web_push_subscriptions subscription
    ON subscription.owner_id=inbox.owner_id
   AND subscription.subscription_id=NEW.subscription_id
  JOIN havre.companion_devices device
    ON device.owner_id=subscription.owner_id AND device.device_id=subscription.device_id
  WHERE inbox.owner_id=NEW.owner_id
    AND inbox.assistant_event_id=NEW.assistant_event_id
    AND inbox.delivery_attempt_id=NEW.proactive_delivery_attempt_id
    AND decision.decision='SEND_NOW'
    AND attempt.status='delivered'
    AND subscription.status='active'
    AND subscription.vapid_key_version=NEW.vapid_key_version
    AND (subscription.expires_at IS NULL OR subscription.expires_at>clock_timestamp())
    AND device.revoked_at IS NULL AND device.session_expires_at>clock_timestamp();
  IF chain_valid IS DISTINCT FROM true THEN
    RAISE EXCEPTION 'web push dispatch lacks an active SEND_NOW/device/subscription chain'
      USING ERRCODE='55000';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER guard_web_push_dispatch_insert
BEFORE INSERT ON havre.web_push_dispatches
FOR EACH ROW EXECUTE FUNCTION havre.guard_web_push_dispatch_insert();

CREATE FUNCTION havre.guard_web_push_dispatch_transition() RETURNS trigger
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
     OR NEW.max_attempts<>OLD.max_attempts OR NEW.created_at<>OLD.created_at THEN
    RAISE EXCEPTION 'web push dispatch identity is immutable' USING ERRCODE='55000';
  END IF;
  IF NEW.status='leased' THEN
    IF NEW.attempt_count<>OLD.attempt_count+1 OR NEW.lease_owner IS NULL
       OR NEW.lease_expires_at<=clock_timestamp()
       OR NEW.completed_at IS NOT NULL
       OR NOT (
         OLD.status IN ('pending','retry_wait')
         OR (OLD.status='leased' AND OLD.lease_expires_at<=clock_timestamp())
       ) THEN
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
CREATE TRIGGER guard_web_push_dispatch_transition
BEFORE UPDATE OR DELETE ON havre.web_push_dispatches
FOR EACH ROW EXECUTE FUNCTION havre.guard_web_push_dispatch_transition();

ALTER TABLE havre.web_push_delivery_attempts
  ADD COLUMN dispatch_id uuid NULL,
  ADD CONSTRAINT web_push_delivery_dispatch_fk
    FOREIGN KEY (owner_id,dispatch_id)
    REFERENCES havre.web_push_dispatches(owner_id,dispatch_id);
CREATE INDEX web_push_delivery_dispatch_fk_idx
  ON havre.web_push_delivery_attempts(owner_id,dispatch_id)
  WHERE dispatch_id IS NOT NULL;

CREATE FUNCTION havre.guard_web_push_attempt_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE dispatch havre.web_push_dispatches%ROWTYPE;
BEGIN
  IF NEW.dispatch_id IS NULL THEN RETURN NEW; END IF;
  SELECT * INTO STRICT dispatch FROM havre.web_push_dispatches
  WHERE owner_id=NEW.owner_id AND dispatch_id=NEW.dispatch_id;
  IF dispatch.status<>'leased'
     OR NEW.subscription_id<>dispatch.subscription_id
     OR NEW.assistant_event_id<>dispatch.assistant_event_id
     OR NEW.proactive_delivery_attempt_id<>dispatch.proactive_delivery_attempt_id
     OR NEW.attempt_number<>dispatch.attempt_count
     OR NEW.idempotency_key<>('web-push:'||dispatch.dispatch_id::text)
     OR NEW.preview_level<>'private'
     OR NEW.payload->>'delivery_locator'<>dispatch.delivery_locator::text
     OR NEW.payload->>'title'<>'HAVRE'
     OR NEW.payload->>'body'<>'HAVRE 有条消息给你' THEN
    RAISE EXCEPTION 'web push attempt does not match its active dispatch lease'
      USING ERRCODE='55000';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER guard_web_push_attempt_insert
BEFORE INSERT ON havre.web_push_delivery_attempts
FOR EACH ROW EXECUTE FUNCTION havre.guard_web_push_attempt_insert();

CREATE FUNCTION havre.guard_web_push_attempt_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE'
     AND current_setting('havre.privileged_erasure',true)='on'
     AND pg_has_role(current_user,'havre_privileged_erasure','MEMBER') THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'web push delivery attempts are immutable'
    USING ERRCODE='55000';
END;
$$;
CREATE TRIGGER guard_web_push_attempt_immutable
BEFORE UPDATE OR DELETE ON havre.web_push_delivery_attempts
FOR EACH ROW EXECUTE FUNCTION havre.guard_web_push_attempt_immutable();

CREATE FUNCTION havre.require_web_push_completion_attempt() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE expected_status text;
BEGIN
  IF OLD.status='leased' AND NEW.status<>'leased' THEN
    expected_status := CASE WHEN NEW.status='accepted' THEN 'delivered' ELSE 'failed' END;
    IF NOT EXISTS (
      SELECT 1 FROM havre.web_push_delivery_attempts attempt
      WHERE attempt.owner_id=NEW.owner_id AND attempt.dispatch_id=NEW.dispatch_id
        AND attempt.attempt_number=NEW.attempt_count
        AND attempt.status=expected_status
    ) THEN
      RAISE EXCEPTION 'web push completion lacks its exact durable attempt'
        USING ERRCODE='55000';
    END IF;
  END IF;
  RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER require_web_push_completion_attempt
AFTER UPDATE ON havre.web_push_dispatches DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION havre.require_web_push_completion_attempt();

ALTER TABLE havre.web_push_delivery_attempts
  DROP CONSTRAINT web_push_payload_minimized_check,
  ADD CONSTRAINT web_push_payload_minimized_check CHECK (
    (
      dispatch_id IS NULL
      AND payload ?& ARRAY['title','body','event_id','url']
      AND payload-ARRAY['title','body','event_id','url']='{}'::jsonb
      AND payload->>'event_id'=assistant_event_id::text
      AND payload->>'url'=('/chat#message-'||assistant_event_id::text)
    ) OR (
      dispatch_id IS NOT NULL
      AND payload ?& ARRAY['title','body','delivery_locator','url']
      AND payload-ARRAY['title','body','delivery_locator','url']='{}'::jsonb
      AND payload->>'title'='HAVRE'
      AND payload->>'body'='HAVRE 有条消息给你'
      AND payload->>'url'=('/chat#delivery-'||(payload->>'delivery_locator'))
      AND length(payload->>'delivery_locator')=36
    )
  );

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='havre_application') THEN
    GRANT SELECT,INSERT,UPDATE ON
      havre.web_push_vapid_key_versions,
      havre.web_push_dispatches
      TO havre_application;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='havre_privileged_erasure') THEN
    GRANT SELECT,DELETE ON
      havre.web_push_vapid_key_versions,
      havre.web_push_dispatches
      TO havre_privileged_erasure;
  END IF;
END
$$;

COMMIT;
