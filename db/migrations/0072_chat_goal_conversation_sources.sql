-- Immutable exact conversation sources for an explicitly requested chat action.
ALTER TABLE havre.owner_chat_goal_plan_runs ADD COLUMN source_manifest jsonb NOT NULL DEFAULT '[]'::jsonb
  CHECK (jsonb_typeof(source_manifest)='array' AND jsonb_array_length(source_manifest)<=9);
CREATE TABLE havre.owner_chat_goal_plan_sources (
  owner_id uuid NOT NULL,
  plan_run_id uuid NOT NULL,
  event_id uuid NOT NULL,
  event_content_hash text NOT NULL CHECK (event_content_hash ~ '^sha256:[0-9a-f]{64}$'),
  PRIMARY KEY(owner_id,plan_run_id,event_id),
  FOREIGN KEY(owner_id,plan_run_id) REFERENCES havre.owner_chat_goal_plan_runs(owner_id,plan_run_id) ON DELETE CASCADE,
  FOREIGN KEY(owner_id,event_id) REFERENCES havre.events(owner_id,event_id) ON DELETE CASCADE
);
CREATE INDEX chat_goal_plan_sources_event_idx ON havre.owner_chat_goal_plan_sources(owner_id,event_id);
CREATE FUNCTION havre.guard_chat_goal_plan_source() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM havre.owner_chat_goal_plan_runs run
    JOIN havre.events current_event ON current_event.owner_id=run.owner_id AND current_event.event_id=run.source_event_id
    JOIN havre.events source ON source.owner_id=NEW.owner_id AND source.event_id=NEW.event_id
    WHERE run.owner_id=NEW.owner_id AND run.plan_run_id=NEW.plan_run_id
      AND source.session_id=current_event.session_id AND source.recorded_at<=current_event.recorded_at
      AND source.recorded_at>=current_event.recorded_at-interval '24 hours'
      AND source.event_type IN ('USER_MESSAGE','ASSISTANT_MESSAGE')
      AND source.privacy_class IN ('PUBLIC','NORMAL') AND source.cloud_eligible
      AND source.content_hash=NEW.event_content_hash
      AND run.source_manifest @> jsonb_build_array(jsonb_build_object('event_id',NEW.event_id::text,'content_hash',NEW.event_content_hash))
      AND NOT EXISTS (SELECT 1 FROM havre.offline_source_revocations revoked WHERE revoked.owner_id=source.owner_id AND revoked.source_event_id=source.event_id)
  ) THEN RAISE EXCEPTION 'chat action conversation source mismatch' USING ERRCODE='55000'; END IF;
  RETURN NEW;
END; $$;
CREATE TRIGGER chat_goal_plan_source_guard BEFORE INSERT ON havre.owner_chat_goal_plan_sources
  FOR EACH ROW EXECUTE FUNCTION havre.guard_chat_goal_plan_source();
CREATE FUNCTION havre.require_chat_goal_source_manifest() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE manifest jsonb; actual jsonb;
BEGIN
  SELECT source_manifest INTO manifest FROM havre.owner_chat_goal_plan_runs WHERE owner_id=NEW.owner_id AND plan_run_id=NEW.plan_run_id;
  IF NOT FOUND OR manifest='[]'::jsonb THEN RETURN NULL; END IF;
  SELECT COALESCE(jsonb_agg(jsonb_build_object('event_id',event_id::text,'content_hash',event_content_hash) ORDER BY event_id), '[]'::jsonb)
    INTO actual FROM havre.owner_chat_goal_plan_sources WHERE owner_id=NEW.owner_id AND plan_run_id=NEW.plan_run_id;
  IF jsonb_array_length(manifest)<>jsonb_array_length(actual) OR NOT(manifest @> actual AND actual @> manifest) THEN
    RAISE EXCEPTION 'chat action source manifest is incomplete' USING ERRCODE='55000';
  END IF;
  RETURN NULL;
END; $$;
CREATE CONSTRAINT TRIGGER chat_goal_source_manifest_complete AFTER INSERT ON havre.owner_chat_goal_plan_runs
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION havre.require_chat_goal_source_manifest();
CREATE TRIGGER chat_goal_plan_sources_immutable BEFORE UPDATE OR DELETE ON havre.owner_chat_goal_plan_sources
  FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='havre_application') THEN
    GRANT SELECT,INSERT ON havre.owner_chat_goal_plan_sources TO havre_application;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='havre_privileged_erasure') THEN
    GRANT SELECT,DELETE ON havre.owner_chat_goal_plan_sources TO havre_privileged_erasure;
  END IF;
END; $$;
