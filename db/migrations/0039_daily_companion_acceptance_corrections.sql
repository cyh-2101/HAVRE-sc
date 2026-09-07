-- Daily Companion acceptance corrections: keep one-time pairing and device
-- identity immutable outside their governed transitions, constrain Push payload
-- minimization at the database boundary, and grant the existing least-privilege
-- application role only the product operations it needs.

CREATE FUNCTION havre.guard_pairing_consumption() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF current_setting('havre.privileged_erasure',true)='on'
     AND pg_has_role(current_user,'havre_privileged_erasure','MEMBER') THEN
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
  END IF;
  IF TG_OP='DELETE' OR OLD.consumed_at IS NOT NULL
     OR NEW.owner_id<>OLD.owner_id OR NEW.pairing_id<>OLD.pairing_id
     OR NEW.code_hash<>OLD.code_hash OR NEW.expires_at<>OLD.expires_at
     OR NEW.created_at<>OLD.created_at OR NEW.consumed_at IS NULL
     OR NEW.consumed_device_id IS NULL THEN
    RAISE EXCEPTION 'pairing challenge permits one exact consumption only'
      USING ERRCODE='55000';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER guard_pairing_consumption
BEFORE UPDATE OR DELETE ON havre.device_pairing_challenges
FOR EACH ROW EXECUTE FUNCTION havre.guard_pairing_consumption();

CREATE FUNCTION havre.guard_companion_device_transition() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF current_setting('havre.privileged_erasure',true)='on'
     AND pg_has_role(current_user,'havre_privileged_erasure','MEMBER') THEN
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
  END IF;
  IF TG_OP='DELETE'
     OR NEW.owner_id<>OLD.owner_id OR NEW.device_id<>OLD.device_id
     OR NEW.display_name<>OLD.display_name OR NEW.device_kind<>OLD.device_kind
     OR NEW.session_token_hash<>OLD.session_token_hash
     OR NEW.session_expires_at<>OLD.session_expires_at
     OR NEW.created_at<>OLD.created_at
     OR (OLD.revoked_at IS NOT NULL AND NEW.revoked_at<>OLD.revoked_at) THEN
    RAISE EXCEPTION 'device identity is immutable; only last-seen and first revoke may advance'
      USING ERRCODE='55000';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER guard_companion_device_transition
BEFORE UPDATE OR DELETE ON havre.companion_devices
FOR EACH ROW EXECUTE FUNCTION havre.guard_companion_device_transition();

ALTER TABLE havre.web_push_delivery_attempts
  ADD CONSTRAINT web_push_payload_minimized_check CHECK (
    payload ?& ARRAY['title','body','event_id','url']
    AND payload-ARRAY['title','body','event_id','url']='{}'::jsonb
    AND length(payload->>'title') BETWEEN 1 AND 80
    AND length(payload->>'body') BETWEEN 1 AND 200
    AND payload->>'event_id'=assistant_event_id::text
    AND payload->>'url'=('/chat#message-'||assistant_event_id::text)
  );

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='havre_application') THEN
    GRANT SELECT,INSERT,UPDATE ON
      havre.companion_devices,
      havre.device_pairing_challenges,
      havre.device_read_cursors,
      havre.web_push_subscriptions,
      havre.web_push_delivery_attempts,
      havre.daily_diary_entry_heads
      TO havre_application;
    GRANT SELECT,INSERT ON
      havre.daily_diary_entry_revisions,
      havre.daily_diary_entry_sources
      TO havre_application;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='havre_privileged_erasure') THEN
    GRANT SELECT,DELETE ON
      havre.companion_devices,
      havre.device_pairing_challenges,
      havre.device_read_cursors,
      havre.web_push_subscriptions,
      havre.web_push_delivery_attempts,
      havre.daily_diary_entry_heads,
      havre.daily_diary_entry_revisions,
      havre.daily_diary_entry_sources
      TO havre_privileged_erasure;
  END IF;
END
$$;

