-- Shared source-qualified GPT understanding ledger. Historical daily rows retain
-- their midnight window; new daily reviews and real-time extraction are distinct.
ALTER TABLE havre.daily_diary_intelligence_runs
 ADD COLUMN run_kind text NOT NULL DEFAULT 'daily_review'
   CHECK (run_kind IN ('daily_review','realtime_memory')),
 ADD COLUMN window_start_hour integer NOT NULL DEFAULT 0
   CHECK (window_start_hour IN (0,5));
ALTER TABLE havre.daily_diary_intelligence_runs ADD CONSTRAINT realtime_run_no_diary_effects
 CHECK (run_kind <> 'realtime_memory' OR COALESCE((
   status='completed' AND result IS NOT NULL
   AND result->>'include_diary'='false'
   AND result->'quality_review'='[]'::jsonb
   AND result->'improvement_suggestions'='[]'::jsonb
   AND result->'follow_up_suggestion'='null'::jsonb
 ),false));
ALTER TABLE havre.daily_diary_entry_revisions DROP CONSTRAINT daily_diary_entry_revisions_summary_method_check;
ALTER TABLE havre.daily_diary_entry_revisions ADD CONSTRAINT daily_diary_entry_revisions_summary_method_check
 CHECK (summary_method IN ('evidence-extractive-diary-v1','evidence-event-diary-v2',
 'curated-owner-day-diary-v3','gpt-owner-day-diary-v4','gpt-owner-day-diary-v5','gpt-owner-five-am-diary-v6'));

CREATE TABLE havre.realtime_memory_jobs (
 owner_id uuid NOT NULL,
 source_user_event_id uuid NOT NULL,
 source_assistant_event_id uuid NOT NULL,
 source_request_id uuid NOT NULL,
 status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','leased','completed','retryable_failed')),
 attempt_count integer NOT NULL DEFAULT 0 CHECK(attempt_count>=0),
 available_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 lease_token uuid NULL,
 lease_expires_at timestamptz NULL,
 run_id uuid NULL,
 error_code text NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(owner_id,source_user_event_id),
 UNIQUE(owner_id,source_request_id),
 FOREIGN KEY(owner_id,source_user_event_id) REFERENCES havre.events(owner_id,event_id) ON DELETE CASCADE,
 FOREIGN KEY(owner_id,source_assistant_event_id) REFERENCES havre.events(owner_id,event_id) ON DELETE CASCADE,
 FOREIGN KEY(owner_id,source_request_id) REFERENCES havre.interaction_requests(owner_id,request_id) ON DELETE CASCADE,
 FOREIGN KEY(owner_id,run_id) REFERENCES havre.daily_diary_intelligence_runs(owner_id,run_id) ON DELETE CASCADE,
 CHECK((status='leased')=(lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)),
 CHECK((status='completed')=(run_id IS NOT NULL))
);
CREATE INDEX realtime_memory_claim_idx ON havre.realtime_memory_jobs(owner_id,available_at,created_at)
 WHERE status IN ('pending','leased','retryable_failed');
CREATE INDEX realtime_memory_assistant_idx ON havre.realtime_memory_jobs(owner_id,source_assistant_event_id);
CREATE INDEX realtime_memory_run_idx ON havre.realtime_memory_jobs(owner_id,run_id) WHERE run_id IS NOT NULL;

CREATE FUNCTION havre.guard_realtime_memory_job() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN
   IF current_setting('havre.privileged_erasure',true) IS DISTINCT FROM 'on' THEN
     RAISE EXCEPTION 'memory job deletion requires privileged erasure';
   END IF;
   RETURN OLD;
 END IF;
 IF TG_OP='UPDATE' AND (NEW.owner_id,NEW.source_user_event_id,NEW.source_assistant_event_id,NEW.source_request_id,NEW.created_at)
   IS DISTINCT FROM (OLD.owner_id,OLD.source_user_event_id,OLD.source_assistant_event_id,OLD.source_request_id,OLD.created_at) THEN
   RAISE EXCEPTION 'memory job source identity is immutable';
 END IF;
 IF TG_OP='UPDATE' AND OLD.status='completed' THEN RAISE EXCEPTION 'completed memory job is immutable'; END IF;
 IF TG_OP='INSERT' AND (NEW.status<>'pending' OR NEW.attempt_count<>0) THEN
  RAISE EXCEPTION 'new memory job must start pending'; END IF;
 IF TG_OP='UPDATE' AND NEW.status IN ('completed','retryable_failed') AND OLD.status<>'leased' THEN
  RAISE EXCEPTION 'memory completion or failure requires a lease'; END IF;
 IF NOT EXISTS (
   SELECT 1 FROM havre.interaction_requests i
   JOIN havre.events u ON u.owner_id=i.owner_id AND u.event_id=i.user_event_id
   JOIN havre.events a ON a.owner_id=i.owner_id AND a.event_id=i.assistant_event_id
   JOIN havre.route_decisions r ON r.owner_id=i.owner_id AND r.request_id=i.request_id
   WHERE i.owner_id=NEW.owner_id AND i.request_id=NEW.source_request_id
    AND i.user_event_id=NEW.source_user_event_id AND i.assistant_event_id=NEW.source_assistant_event_id
    AND i.status='completed' AND i.request_kind='interaction'
    AND u.event_type='USER_MESSAGE' AND a.event_type='ASSISTANT_MESSAGE'
    AND a.causation_event_id=u.event_id AND u.memory_eligible
    AND u.cloud_eligible AND a.cloud_eligible
    AND u.privacy_class IN ('PUBLIC','NORMAL') AND a.privacy_class IN ('PUBLIC','NORMAL')
    AND r.execution_environment='cloud' AND r.selected_provider_id='openai-codex-chatgpt'
    AND NOT EXISTS(SELECT 1 FROM havre.offline_source_revocations x WHERE x.owner_id=i.owner_id AND x.source_event_id IN (u.event_id,a.event_id))
 ) THEN RAISE EXCEPTION 'realtime memory requires an exact eligible completed GPT pair'; END IF;
 IF NEW.status='completed' AND NOT EXISTS(
   SELECT 1 FROM havre.daily_diary_intelligence_runs r
   JOIN havre.daily_diary_intelligence_sources s ON s.owner_id=r.owner_id AND s.run_id=r.run_id
   WHERE r.owner_id=NEW.owner_id AND r.run_id=NEW.run_id AND r.run_kind='realtime_memory'
    AND r.status='completed' AND r.provider_id='openai-codex-chatgpt' AND r.reasoning_effort='high'
    AND s.event_id=NEW.source_user_event_id AND s.disposition='cloud_summary'
 ) THEN RAISE EXCEPTION 'completed memory job lacks its exact GPT-high run'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER realtime_memory_job_guard BEFORE INSERT OR UPDATE OR DELETE ON havre.realtime_memory_jobs
 FOR EACH ROW EXECUTE FUNCTION havre.guard_realtime_memory_job();

CREATE FUNCTION havre.enqueue_completed_gpt_memory() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.status='completed' AND OLD.status IS DISTINCT FROM 'completed' AND NEW.request_kind='interaction'
  AND EXISTS(SELECT 1 FROM havre.events u JOIN havre.events a ON a.owner_id=u.owner_id AND a.event_id=NEW.assistant_event_id
   JOIN havre.route_decisions r ON r.owner_id=u.owner_id AND r.request_id=u.request_id
   WHERE u.owner_id=NEW.owner_id AND u.event_id=NEW.user_event_id AND u.memory_eligible
    AND u.cloud_eligible AND a.cloud_eligible AND u.privacy_class IN ('PUBLIC','NORMAL') AND a.privacy_class IN ('PUBLIC','NORMAL')
    AND r.execution_environment='cloud' AND r.selected_provider_id='openai-codex-chatgpt') THEN
   INSERT INTO havre.realtime_memory_jobs(owner_id,source_user_event_id,source_assistant_event_id,source_request_id)
    VALUES(NEW.owner_id,NEW.user_event_id,NEW.assistant_event_id,NEW.request_id) ON CONFLICT DO NOTHING;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER interaction_realtime_memory_after_completed AFTER UPDATE OF status ON havre.interaction_requests
 FOR EACH ROW EXECUTE FUNCTION havre.enqueue_completed_gpt_memory();

CREATE OR REPLACE FUNCTION havre.guard_daily_diary_intelligence_source() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE e havre.events%ROWTYPE; r havre.daily_diary_intelligence_runs%ROWTYPE;
 source_day date; routed text;
BEGIN
 SELECT * INTO STRICT e FROM havre.events WHERE owner_id=NEW.owner_id AND event_id=NEW.event_id;
 SELECT * INTO STRICT r FROM havre.daily_diary_intelligence_runs WHERE owner_id=NEW.owner_id AND run_id=NEW.run_id;
 source_day:=((e.recorded_at AT TIME ZONE r.timezone_name)-make_interval(hours=>r.window_start_hour))::date;
 IF e.event_type NOT IN ('USER_MESSAGE','ASSISTANT_MESSAGE') OR e.content_hash<>NEW.event_content_hash THEN
  RAISE EXCEPTION 'intelligence source must match exact owner Event' USING ERRCODE='55000'; END IF;
 IF r.run_kind='daily_review' AND (
   (NEW.disposition IN ('cloud_summary','private_reference') AND source_day<>r.local_date)
   OR (NEW.disposition='prior_context' AND (source_day>=r.local_date OR source_day<r.local_date-7))) THEN
  RAISE EXCEPTION 'Diary source outside exact owner-local window' USING ERRCODE='55000'; END IF;
 IF r.run_kind='realtime_memory' AND (NEW.disposition<>'cloud_summary' OR NOT EXISTS(
   SELECT 1 FROM havre.realtime_memory_jobs j WHERE j.owner_id=NEW.owner_id
   AND j.status='leased' AND j.lease_expires_at>clock_timestamp()
   AND NEW.event_id IN (j.source_user_event_id,j.source_assistant_event_id))) THEN
  RAISE EXCEPTION 'realtime source requires a live exact-pair lease' USING ERRCODE='55000'; END IF;
 IF NEW.disposition IN ('cloud_summary','prior_context') THEN
  IF e.privacy_class NOT IN ('PUBLIC','NORMAL') OR NOT e.cloud_eligible THEN
   RAISE EXCEPTION 'private or non-cloud Event cannot enter GPT input' USING ERRCODE='55000'; END IF;
  SELECT route.selected_provider_id INTO routed FROM havre.route_decisions route
   JOIN havre.interaction_requests i ON i.owner_id=route.owner_id AND i.request_id=route.request_id
   WHERE route.owner_id=NEW.owner_id AND route.request_id=e.request_id AND route.execution_environment='cloud' AND i.status='completed';
  IF routed IS DISTINCT FROM 'openai-codex-chatgpt' THEN
   RAISE EXCEPTION 'only completed GPT cloud sources allowed' USING ERRCODE='55000'; END IF;
 END IF;
 RETURN NEW;
END $$;

GRANT SELECT,INSERT,UPDATE ON havre.realtime_memory_jobs TO havre_application;
DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='havre_privileged_erasure') THEN
 GRANT SELECT,DELETE ON havre.realtime_memory_jobs TO havre_privileged_erasure;
END IF; END $$;
