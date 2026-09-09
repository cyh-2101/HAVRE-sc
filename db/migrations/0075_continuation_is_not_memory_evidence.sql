-- A tap contains no new autobiographical evidence; do not enqueue understanding from it.
CREATE OR REPLACE FUNCTION havre.guard_realtime_memory_job() RETURNS trigger LANGUAGE plpgsql AS $$
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
    AND COALESCE(u.payload->>'input_origin','owner_text') <> 'continuation_button'
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

CREATE OR REPLACE FUNCTION havre.enqueue_completed_gpt_memory() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.status='completed' AND OLD.status IS DISTINCT FROM 'completed' AND NEW.request_kind='interaction'
  AND EXISTS(SELECT 1 FROM havre.events u JOIN havre.events a ON a.owner_id=u.owner_id AND a.event_id=NEW.assistant_event_id
   JOIN havre.route_decisions r ON r.owner_id=u.owner_id AND r.request_id=u.request_id
   WHERE u.owner_id=NEW.owner_id AND u.event_id=NEW.user_event_id AND u.memory_eligible
    AND COALESCE(u.payload->>'input_origin','owner_text') <> 'continuation_button'
    AND u.cloud_eligible AND a.cloud_eligible AND u.privacy_class IN ('PUBLIC','NORMAL') AND a.privacy_class IN ('PUBLIC','NORMAL')
    AND r.execution_environment='cloud' AND r.selected_provider_id='openai-codex-chatgpt') THEN
   INSERT INTO havre.realtime_memory_jobs(owner_id,source_user_event_id,source_assistant_event_id,source_request_id)
    VALUES(NEW.owner_id,NEW.user_event_id,NEW.assistant_event_id,NEW.request_id) ON CONFLICT DO NOTHING;
 END IF;
 RETURN NEW;
END $$;
