-- Govern one owner-triggered Strong Brain disclosure without changing source policy.

BEGIN;

CREATE TABLE havre.manual_cloud_disclosures (
  owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
  disclosure_id uuid NOT NULL,
  source_assistant_event_id uuid NOT NULL,
  provider_id text NOT NULL CHECK (provider_id='deepseek-cloud'),
  authorization_ref text NOT NULL CHECK (
    authorization_ref='product-owner/manual-strong-brain-selected-context-2026-08-28'
  ),
  data_boundary text NOT NULL CHECK (
    data_boundary='OWNER_MANUAL_SELECTED_CONTEXT_V1'
  ),
  policy_revision_id uuid NOT NULL,
  selected_source_refs jsonb NOT NULL CHECK (
    jsonb_typeof(selected_source_refs)='array'
    AND jsonb_array_length(selected_source_refs)>0
  ),
  selected_content_hash text NOT NULL CHECK (
    selected_content_hash ~ '^sha256:[0-9a-f]{64}$'
  ),
  status text NOT NULL CHECK (
    status IN ('prepared','bound','sent','failed','revoked')
  ),
  inference_request_id uuid NULL,
  request_binding_hash text NULL CHECK (
    request_binding_hash IS NULL OR request_binding_hash ~ '^sha256:[0-9a-f]{64}$'
  ),
  result_assistant_event_id uuid NULL,
  error_code text NULL CHECK (error_code IS NULL OR length(error_code) BETWEEN 1 AND 200),
  content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  bound_at timestamptz NULL,
  completed_at timestamptz NULL,
  revoked_at timestamptz NULL,
  PRIMARY KEY (owner_id,disclosure_id),
  UNIQUE (owner_id,inference_request_id),
  FOREIGN KEY (owner_id,source_assistant_event_id)
    REFERENCES havre.events(owner_id,event_id),
  FOREIGN KEY (owner_id,result_assistant_event_id)
    REFERENCES havre.events(owner_id,event_id),
  CHECK (
    (status='prepared' AND inference_request_id IS NULL
      AND request_binding_hash IS NULL AND result_assistant_event_id IS NULL
      AND error_code IS NULL AND bound_at IS NULL AND completed_at IS NULL
      AND revoked_at IS NULL)
    OR
    (status='bound' AND inference_request_id IS NOT NULL
      AND request_binding_hash IS NOT NULL AND result_assistant_event_id IS NULL
      AND error_code IS NULL AND bound_at IS NOT NULL AND completed_at IS NULL
      AND revoked_at IS NULL)
    OR
    (status='sent' AND inference_request_id IS NOT NULL
      AND request_binding_hash IS NOT NULL AND result_assistant_event_id IS NOT NULL
      AND error_code IS NULL AND bound_at IS NOT NULL AND completed_at IS NOT NULL
      AND revoked_at IS NULL)
    OR
    (status='failed' AND inference_request_id IS NOT NULL
      AND request_binding_hash IS NOT NULL AND result_assistant_event_id IS NULL
      AND error_code IS NOT NULL AND bound_at IS NOT NULL AND completed_at IS NOT NULL
      AND revoked_at IS NULL)
    OR
    (status='revoked' AND inference_request_id IS NULL
      AND request_binding_hash IS NULL AND result_assistant_event_id IS NULL
      AND error_code IS NULL AND bound_at IS NULL AND completed_at IS NULL
      AND revoked_at IS NOT NULL)
  )
);
CREATE INDEX manual_cloud_disclosures_source_idx
  ON havre.manual_cloud_disclosures(owner_id,source_assistant_event_id);
CREATE INDEX manual_cloud_disclosures_result_idx
  ON havre.manual_cloud_disclosures(owner_id,result_assistant_event_id)
  WHERE result_assistant_event_id IS NOT NULL;

CREATE FUNCTION havre.guard_manual_cloud_disclosure_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE source_type text;
BEGIN
  IF NEW.status<>'prepared' THEN
    RAISE EXCEPTION 'manual cloud disclosure must begin prepared'
      USING ERRCODE='55000';
  END IF;
  SELECT event_type INTO STRICT source_type
  FROM havre.events
  WHERE owner_id=NEW.owner_id AND event_id=NEW.source_assistant_event_id;
  IF source_type<>'ASSISTANT_MESSAGE' THEN
    RAISE EXCEPTION 'manual cloud disclosure source must be an assistant Event'
      USING ERRCODE='55000';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER guard_manual_cloud_disclosure_insert
BEFORE INSERT ON havre.manual_cloud_disclosures
FOR EACH ROW EXECUTE FUNCTION havre.guard_manual_cloud_disclosure_insert();

CREATE FUNCTION havre.guard_manual_cloud_disclosure_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF ROW(
    NEW.owner_id,NEW.disclosure_id,NEW.source_assistant_event_id,NEW.provider_id,
    NEW.authorization_ref,NEW.data_boundary,NEW.policy_revision_id,
    NEW.selected_source_refs,NEW.selected_content_hash,NEW.content_hash,NEW.created_at
  ) IS DISTINCT FROM ROW(
    OLD.owner_id,OLD.disclosure_id,OLD.source_assistant_event_id,OLD.provider_id,
    OLD.authorization_ref,OLD.data_boundary,OLD.policy_revision_id,
    OLD.selected_source_refs,OLD.selected_content_hash,OLD.content_hash,OLD.created_at
  ) THEN
    RAISE EXCEPTION 'manual cloud disclosure immutable material changed'
      USING ERRCODE='55000';
  END IF;
  IF OLD.status='prepared' AND NEW.status='bound'
     AND NEW.inference_request_id IS NOT NULL
     AND NEW.request_binding_hash IS NOT NULL AND NEW.bound_at IS NOT NULL THEN
    RETURN NEW;
  END IF;
  IF OLD.status='bound' AND NEW.status='sent'
     AND NEW.result_assistant_event_id IS NOT NULL
     AND NEW.completed_at IS NOT NULL THEN
    IF NOT EXISTS (
      SELECT 1 FROM havre.events
      WHERE owner_id=NEW.owner_id AND event_id=NEW.result_assistant_event_id
        AND event_type='ASSISTANT_MESSAGE'
    ) THEN
      RAISE EXCEPTION 'manual cloud disclosure result must be an assistant Event'
        USING ERRCODE='55000';
    END IF;
    RETURN NEW;
  END IF;
  IF OLD.status='bound' AND NEW.status='failed'
     AND NEW.error_code IS NOT NULL AND NEW.completed_at IS NOT NULL THEN
    RETURN NEW;
  END IF;
  IF OLD.status='prepared' AND NEW.status='revoked'
     AND NEW.revoked_at IS NOT NULL THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'invalid manual cloud disclosure transition'
    USING ERRCODE='55000';
END;
$$;
CREATE TRIGGER guard_manual_cloud_disclosure_update
BEFORE UPDATE ON havre.manual_cloud_disclosures
FOR EACH ROW EXECUTE FUNCTION havre.guard_manual_cloud_disclosure_update();

CREATE FUNCTION havre.guard_manual_cloud_disclosure_delete() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF current_setting('havre.privileged_erasure',true)='on'
     AND pg_has_role(current_user,'havre_privileged_erasure','MEMBER') THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'manual cloud disclosures require privileged erasure'
    USING ERRCODE='55000';
END;
$$;
CREATE TRIGGER guard_manual_cloud_disclosure_delete
BEFORE DELETE ON havre.manual_cloud_disclosures
FOR EACH ROW EXECUTE FUNCTION havre.guard_manual_cloud_disclosure_delete();

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='havre_application') THEN
    GRANT SELECT,INSERT,UPDATE ON havre.manual_cloud_disclosures TO havre_application;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='havre_privileged_erasure') THEN
    GRANT SELECT,DELETE ON havre.manual_cloud_disclosures TO havre_privileged_erasure;
  END IF;
END
$$;

-- Diary v2 remains event-derived and provenance-bound; keep v1 readable while
-- admitting only the focused concrete-event summarizer revision.
ALTER TABLE havre.daily_diary_entry_revisions
  DROP CONSTRAINT daily_diary_entry_revisions_summary_method_check;
ALTER TABLE havre.daily_diary_entry_revisions
  ADD CONSTRAINT daily_diary_entry_revisions_summary_method_check
  CHECK (summary_method IN (
    'evidence-extractive-diary-v1', 'evidence-event-diary-v2'
  ));

-- The existing validation trigger is intentionally narrow but queries its exact
-- lineage sources. Run only that trigger body with its owner privileges so the
-- least-privilege application role reaches the intended 55000 integrity guard
-- instead of failing earlier on broad Events SELECT permission.
ALTER FUNCTION havre.guard_web_push_real_device_validation_insert()
  SECURITY DEFINER
  SET search_path = pg_catalog, havre;

COMMIT;

