BEGIN;

ALTER TABLE havre.life_context_observations
  DROP CONSTRAINT life_context_observations_draft_signing_material_check,
  ADD CONSTRAINT life_context_observations_draft_signing_material_check
    CHECK (length(draft_signing_material) BETWEEN 2 AND 262144),
  DROP CONSTRAINT life_context_observations_canonical_content_material_check,
  ADD CONSTRAINT life_context_observations_canonical_content_material_check
    CHECK (length(canonical_content_material) BETWEEN 2 AND 262144);

ALTER TABLE havre.device_pairing_challenges
  ADD COLUMN failed_attempts integer NOT NULL DEFAULT 0 CHECK (failed_attempts BETWEEN 0 AND 5),
  ADD COLUMN last_failed_at timestamptz NULL,
  ADD CONSTRAINT pairing_failure_clock_check CHECK ((failed_attempts=0)=(last_failed_at IS NULL));

DROP TRIGGER guard_pairing_consumption ON havre.device_pairing_challenges;
CREATE OR REPLACE FUNCTION havre.guard_pairing_consumption() RETURNS trigger
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
     OR NEW.created_at<>OLD.created_at THEN
    RAISE EXCEPTION 'pairing challenge transition is invalid' USING ERRCODE='55000';
  END IF;
  IF NEW.consumed_at IS NULL THEN
    IF NEW.consumed_device_id IS NOT NULL
       OR NEW.failed_attempts<>OLD.failed_attempts+1
       OR NEW.failed_attempts>5 OR NEW.last_failed_at IS NULL
       OR (OLD.last_failed_at IS NOT NULL AND NEW.last_failed_at<=OLD.last_failed_at) THEN
      RAISE EXCEPTION 'pairing failure counter must advance exactly once' USING ERRCODE='55000';
    END IF;
  ELSIF NEW.consumed_device_id IS NULL
        OR NEW.failed_attempts<>OLD.failed_attempts
        OR NEW.last_failed_at IS DISTINCT FROM OLD.last_failed_at THEN
    RAISE EXCEPTION 'pairing challenge permits one exact consumption only' USING ERRCODE='55000';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER guard_pairing_consumption
BEFORE UPDATE OR DELETE ON havre.device_pairing_challenges
FOR EACH ROW EXECUTE FUNCTION havre.guard_pairing_consumption();

COMMIT;
