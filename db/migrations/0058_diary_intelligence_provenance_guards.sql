-- Additive hardening for 0057. 0057 may already be applied and remains immutable.
-- Cloud Diary sources must be completed GPT cloud routes; delegated updates must
-- close over the exact run, source Event, lifecycle Event, head, and provenance.

CREATE OR REPLACE FUNCTION havre.guard_daily_diary_intelligence_source()
RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE source_event havre.events%ROWTYPE;
DECLARE run_row havre.daily_diary_intelligence_runs%ROWTYPE;
DECLARE routed_provider text;
BEGIN
  SELECT * INTO STRICT source_event FROM havre.events
  WHERE owner_id=NEW.owner_id AND event_id=NEW.event_id;
  SELECT * INTO STRICT run_row FROM havre.daily_diary_intelligence_runs
  WHERE owner_id=NEW.owner_id AND run_id=NEW.run_id;
  IF source_event.event_type NOT IN ('USER_MESSAGE','ASSISTANT_MESSAGE')
     OR source_event.content_hash<>NEW.event_content_hash
     OR (source_event.recorded_at AT TIME ZONE run_row.timezone_name)::date<>run_row.local_date THEN
    RAISE EXCEPTION 'Diary intelligence source must match its exact owner-local message Event'
      USING ERRCODE='55000';
  END IF;
  IF NEW.disposition='cloud_summary' AND (
       source_event.privacy_class NOT IN ('PUBLIC','NORMAL')
       OR NOT source_event.cloud_eligible
  ) THEN
    RAISE EXCEPTION 'private or non-cloud Event cannot enter Diary cloud summary input'
      USING ERRCODE='55000';
  END IF;
  IF NEW.disposition='cloud_summary' THEN
    SELECT route.selected_provider_id INTO routed_provider
    FROM havre.route_decisions route
    JOIN havre.interaction_requests request
      ON request.owner_id=route.owner_id AND request.request_id=route.request_id
    WHERE route.owner_id=NEW.owner_id
      AND route.request_id=source_event.request_id
      AND route.execution_environment='cloud'
      AND request.status='completed';
    IF routed_provider IS DISTINCT FROM 'openai-codex-chatgpt' THEN
      RAISE EXCEPTION 'only completed cloud GPT-routed Events may enter Diary cloud summary input'
        USING ERRCODE='55000';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

CREATE FUNCTION havre.guard_owner_delegated_gpt_memory_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.authorization_ref<>'product-owner/gpt-diary-memory-user-model-paired-review-2026-09-03'
     OR NOT EXISTS (
       SELECT 1
       FROM havre.daily_diary_intelligence_runs run
       JOIN havre.daily_diary_intelligence_sources source
         ON source.owner_id=run.owner_id AND source.run_id=run.run_id
       JOIN havre.events event
         ON event.owner_id=source.owner_id AND event.event_id=source.event_id
       JOIN havre.memory_revisions revision
         ON revision.owner_id=NEW.owner_id AND revision.memory_id=NEW.memory_id
        AND revision.revision=NEW.memory_revision
       JOIN havre.memory_heads head
         ON head.owner_id=revision.owner_id AND head.memory_id=revision.memory_id
       JOIN havre.events lifecycle
         ON lifecycle.owner_id=revision.owner_id
        AND lifecycle.event_id=revision.created_event_id
       WHERE run.owner_id=NEW.owner_id AND run.run_id=NEW.run_id
         AND run.status='completed'
         AND run.provider_id='openai-codex-chatgpt'
         AND run.reasoning_effort='high'
         AND run.policy_authorization_ref=NEW.authorization_ref
         AND source.event_id=NEW.source_event_id
         AND source.disposition='cloud_summary'
         AND event.event_type='USER_MESSAGE'
         AND event.memory_eligible AND event.cloud_eligible
         AND event.privacy_class IN ('PUBLIC','NORMAL')
         AND revision.revision=1
         AND revision.created_by='owner_delegated_gpt'
         AND revision.confidence_method='gpt-grounded-owner-authorized-v1'
         AND revision.transform_version='gpt-owner-diary-intelligence-v1'
         AND revision.candidate_id IS NULL
         AND revision.policy_decision_source='derived_conservative'
         AND revision.policy_authorization_ref=NEW.authorization_ref
         AND head.current_revision=revision.revision AND head.status='active'
         AND lifecycle.event_type='MEMORY_CREATED'
         AND lifecycle.causation_event_id=NEW.source_event_id
         AND EXISTS (
           SELECT 1 FROM havre.provenance_edges edge
           WHERE edge.owner_id=NEW.owner_id
             AND edge.source_kind='event'
             AND edge.source_id=NEW.source_event_id
             AND edge.source_revision IS NULL
             AND edge.derived_kind='memory_revision'
             AND edge.derived_id=NEW.memory_id
             AND edge.derived_revision=NEW.memory_revision
             AND edge.relation='derived_from'
             AND edge.transform_name='owner_delegated_gpt_diary_memory'
             AND edge.transform_version='gpt-owner-diary-intelligence-v1'
         )
     ) THEN
    RAISE EXCEPTION 'owner-delegated GPT Memory mapping lacks exact eligible run and provenance'
      USING ERRCODE='55000';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER owner_delegated_gpt_memory_update_guard
BEFORE INSERT ON havre.owner_delegated_gpt_memory_updates
FOR EACH ROW EXECUTE FUNCTION havre.guard_owner_delegated_gpt_memory_update();

CREATE FUNCTION havre.guard_owner_delegated_gpt_belief_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.authorization_ref<>'product-owner/gpt-diary-memory-user-model-paired-review-2026-09-03'
     OR NOT EXISTS (
       SELECT 1
       FROM havre.daily_diary_intelligence_runs run
       JOIN havre.daily_diary_intelligence_sources source
         ON source.owner_id=run.owner_id AND source.run_id=run.run_id
       JOIN havre.events event
         ON event.owner_id=source.owner_id AND event.event_id=source.event_id
       JOIN havre.user_belief_revisions revision
         ON revision.owner_id=NEW.owner_id AND revision.belief_id=NEW.belief_id
        AND revision.revision=NEW.belief_revision
       JOIN havre.belief_heads head
         ON head.owner_id=revision.owner_id AND head.belief_id=revision.belief_id
       JOIN havre.events lifecycle
         ON lifecycle.owner_id=revision.owner_id
        AND lifecycle.event_id=revision.created_event_id
       JOIN havre.belief_revision_transitions transition
         ON transition.owner_id=head.owner_id
        AND transition.belief_transition_id=head.last_transition_id
       WHERE run.owner_id=NEW.owner_id AND run.run_id=NEW.run_id
         AND run.status='completed'
         AND run.provider_id='openai-codex-chatgpt'
         AND run.reasoning_effort='high'
         AND run.policy_authorization_ref=NEW.authorization_ref
         AND source.event_id=NEW.source_event_id
         AND source.disposition='cloud_summary'
         AND event.event_type='USER_MESSAGE'
         AND event.memory_eligible AND event.cloud_eligible
         AND event.privacy_class IN ('PUBLIC','NORMAL')
         AND revision.revision=1
         AND revision.confidence_method='owner-delegated-gpt-v1'
         AND revision.initial_status='candidate'
         AND revision.belief_key LIKE 'owner-delegated-gpt:%'
         AND revision.policy_decision_source='derived_conservative'
         AND revision.policy_authorization_ref=NEW.authorization_ref
         AND head.current_revision=revision.revision AND head.status='active'
         AND lifecycle.event_type='USER_BELIEF_CREATED'
         AND lifecycle.causation_event_id=NEW.source_event_id
         AND transition.belief_id=NEW.belief_id
         AND transition.belief_revision=NEW.belief_revision
         AND transition.transition_type='activated'
         AND transition.reason=NEW.authorization_ref
         AND EXISTS (
           SELECT 1 FROM havre.provenance_edges edge
           WHERE edge.owner_id=NEW.owner_id
             AND edge.source_kind='event'
             AND edge.source_id=NEW.source_event_id
             AND edge.source_revision IS NULL
             AND edge.derived_kind='belief_revision'
             AND edge.derived_id=NEW.belief_id
             AND edge.derived_revision=NEW.belief_revision
             AND edge.relation='supports'
             AND edge.transform_name='owner_delegated_gpt_diary_belief'
             AND edge.transform_version='gpt-owner-diary-intelligence-v1'
         )
     ) THEN
    RAISE EXCEPTION 'owner-delegated GPT belief mapping lacks exact eligible run and provenance'
      USING ERRCODE='55000';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER owner_delegated_gpt_belief_update_guard
BEFORE INSERT ON havre.owner_delegated_gpt_belief_updates
FOR EACH ROW EXECUTE FUNCTION havre.guard_owner_delegated_gpt_belief_update();
