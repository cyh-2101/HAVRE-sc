-- Corrective durable boundaries for daily feedback and episode learning.
-- 0036 may already be applied and remains immutable.

ALTER TABLE havre.sessions
  ADD COLUMN closed_at timestamptz NULL,
  ADD COLUMN closed_reason text NULL,
  ADD COLUMN closed_episode_id uuid NULL,
  ADD CONSTRAINT sessions_close_fields_atomic CHECK (
    (closed_at IS NULL AND closed_reason IS NULL AND closed_episode_id IS NULL)
    OR
    (closed_at IS NOT NULL
     AND closed_reason IN ('owner_started_new_conversation','owner_closed','idle_boundary'))
  ),
  ADD CONSTRAINT sessions_closed_episode_fk
    FOREIGN KEY (owner_id,closed_episode_id)
    REFERENCES havre.conversation_episodes(owner_id,episode_id);

UPDATE havre.sessions session
SET closed_at=episode.created_at,
    closed_reason=episode.boundary_reason,
    closed_episode_id=episode.episode_id
FROM havre.conversation_episodes episode
WHERE episode.owner_id=session.owner_id AND episode.session_id=session.session_id;

CREATE FUNCTION havre.guard_session_terminal_close() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE episode havre.conversation_episodes%ROWTYPE;
BEGIN
  IF current_setting('havre.privileged_erasure', true)='on'
     AND pg_has_role(current_user,'havre_privileged_erasure','MEMBER') THEN
    RETURN NEW;
  END IF;
  IF OLD.closed_at IS NOT NULL THEN
    RAISE EXCEPTION 'closed conversation sessions are terminal' USING ERRCODE='55000';
  END IF;
  IF NEW.closed_at IS NOT NULL THEN
    SELECT * INTO episode FROM havre.conversation_episodes
      WHERE owner_id=NEW.owner_id AND episode_id=NEW.closed_episode_id;
    IF episode IS NULL OR episode.session_id<>NEW.session_id
       OR episode.boundary_reason<>NEW.closed_reason THEN
      RAISE EXCEPTION 'session close must bind its exact durable episode'
        USING ERRCODE='55000';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER guard_session_terminal_close
BEFORE UPDATE ON havre.sessions
FOR EACH ROW EXECUTE FUNCTION havre.guard_session_terminal_close();

CREATE INDEX sessions_owner_closed_episode_idx
  ON havre.sessions(owner_id,closed_episode_id);

-- 0036 is immutable; add the FK-side indexes required for bounded owner
-- erasure and parent-row checks here rather than rewriting that migration.
CREATE INDEX response_feedback_heads_session_owner_idx
  ON havre.response_feedback_heads(session_id,owner_id);
CREATE INDEX response_feedback_heads_owner_request_idx
  ON havre.response_feedback_heads(owner_id,request_id);
CREATE INDEX response_feedback_heads_owner_user_event_idx
  ON havre.response_feedback_heads(owner_id,user_event_id);
CREATE INDEX response_feedback_heads_owner_context_pack_idx
  ON havre.response_feedback_heads(owner_id,context_pack_id);
CREATE INDEX response_feedback_heads_owner_route_idx
  ON havre.response_feedback_heads(owner_id,route_decision_id);
CREATE INDEX response_feedback_heads_owner_inference_idx
  ON havre.response_feedback_heads(owner_id,inference_response_id);
CREATE INDEX response_feedback_heads_owner_request_trace_idx
  ON havre.response_feedback_heads(owner_id,request_id,trace_id);
CREATE INDEX response_feedback_heads_owner_request_trace_context_idx
  ON havre.response_feedback_heads(owner_id,request_id,trace_id,context_pack_id);
CREATE INDEX response_feedback_heads_owner_request_trace_route_idx
  ON havre.response_feedback_heads(owner_id,request_id,trace_id,route_decision_id);
CREATE INDEX response_feedback_heads_owner_request_inference_idx
  ON havre.response_feedback_heads(owner_id,request_id,inference_response_id);
CREATE INDEX conversation_episodes_session_owner_idx
  ON havre.conversation_episodes(session_id,owner_id);

CREATE FUNCTION havre.guard_open_conversation_append() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,havre AS $$
DECLARE source_session havre.sessions%ROWTYPE;
BEGIN
  SELECT * INTO source_session FROM havre.sessions
    WHERE owner_id=NEW.owner_id AND session_id=NEW.session_id
    FOR KEY SHARE;
  IF source_session IS NOT NULL AND source_session.closed_at IS NOT NULL THEN
    RAISE EXCEPTION 'closed conversation sessions are terminal'
      USING ERRCODE='55000';
  END IF;
  RETURN NEW;
END;
$$;
-- The alphabetical prefix makes the terminal check run before older payload
-- guards, so a direct SQL append is rejected for the exact closed-session
-- relationship rather than incidentally by an unrelated constraint.
CREATE TRIGGER a_guard_open_conversation_request
BEFORE INSERT ON havre.interaction_requests
FOR EACH ROW EXECUTE FUNCTION havre.guard_open_conversation_append();
CREATE TRIGGER a_guard_open_conversation_event
BEFORE INSERT ON havre.events
FOR EACH ROW EXECUTE FUNCTION havre.guard_open_conversation_append();

ALTER TABLE havre.episode_memory_suggestions
  ADD COLUMN privacy_class text NULL,
  ADD COLUMN memory_eligible boolean NULL,
  ADD COLUMN cloud_eligible boolean NULL,
  ADD COLUMN policy_version text NULL,
  ADD COLUMN policy_revision_id uuid NULL,
  ADD COLUMN policy_decision_source text NULL,
  ADD COLUMN policy_authorization_ref text NULL;

UPDATE havre.episode_memory_suggestions suggestion
SET privacy_class=episode.privacy_class,
    memory_eligible=episode.memory_eligible,
    cloud_eligible=episode.cloud_eligible,
    policy_version=episode.policy_version,
    policy_revision_id=episode.policy_revision_id,
    policy_decision_source=episode.policy_decision_source,
    policy_authorization_ref=episode.policy_authorization_ref
FROM havre.conversation_episodes episode
WHERE episode.owner_id=suggestion.owner_id
  AND episode.episode_id=suggestion.episode_id;

ALTER TABLE havre.episode_memory_suggestions
  ALTER COLUMN privacy_class SET NOT NULL,
  ALTER COLUMN memory_eligible SET NOT NULL,
  ALTER COLUMN cloud_eligible SET NOT NULL,
  ALTER COLUMN policy_version SET NOT NULL,
  ALTER COLUMN policy_revision_id SET NOT NULL,
  ALTER COLUMN policy_decision_source SET NOT NULL,
  ADD CONSTRAINT episode_suggestion_privacy_class_check CHECK (
    privacy_class IN ('PUBLIC','NORMAL','PRIVATE','HIGHLY_PRIVATE','LOCAL_ONLY')
  ),
  ADD CONSTRAINT episode_suggestion_policy_version_check
    CHECK (policy_version='data-policy-v1'),
  ADD CONSTRAINT episode_suggestion_decision_source_check
    CHECK (policy_decision_source='derived_conservative'),
  ADD CONSTRAINT episode_suggestion_local_cloud_check
    CHECK (privacy_class<>'LOCAL_ONLY' OR cloud_eligible=false);

-- Rebind any pre-correction local suggestions before strengthening the update
-- guard below. 0036's original guard does not yet know these policy fields.
DROP TRIGGER guard_episode_suggestion_review ON havre.episode_memory_suggestions;
UPDATE havre.episode_memory_suggestions suggestion
SET content_hash='sha256:' || encode(public.digest(convert_to(havre.canonical_jsonb(
  jsonb_build_object(
    'schema_version',suggestion.schema_version,'owner_id',suggestion.owner_id,
    'suggestion_id',suggestion.suggestion_id,'episode_id',suggestion.episode_id,
    'memory_class',suggestion.memory_class,'content_text',suggestion.content_text,
    'extractor_version',suggestion.extractor_version,
    'privacy_class',suggestion.privacy_class,
    'memory_eligible',suggestion.memory_eligible,
    'training_eligible',suggestion.training_eligible,
    'cloud_eligible',suggestion.cloud_eligible,
    'policy_version',suggestion.policy_version,
    'policy_revision_id',suggestion.policy_revision_id,
    'policy_decision_source',suggestion.policy_decision_source,
    'policy_authorization_ref',suggestion.policy_authorization_ref
  )),'UTF8'),'sha256'),'hex');

CREATE OR REPLACE FUNCTION havre.guard_episode_suggestion_review() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF current_setting('havre.privileged_erasure', true)='on'
     AND pg_has_role(current_user,'havre_privileged_erasure','MEMBER') THEN
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
  END IF;
  IF OLD.status<>'pending' OR NEW.status NOT IN ('accepted','rejected')
     OR NEW.owner_id<>OLD.owner_id OR NEW.suggestion_id<>OLD.suggestion_id
     OR NEW.episode_id<>OLD.episode_id OR NEW.memory_class<>OLD.memory_class
     OR NEW.content_text<>OLD.content_text
     OR NEW.extractor_version<>OLD.extractor_version
     OR NEW.privacy_class<>OLD.privacy_class
     OR NEW.memory_eligible<>OLD.memory_eligible
     OR NEW.training_eligible<>OLD.training_eligible
     OR NEW.cloud_eligible<>OLD.cloud_eligible
     OR NEW.policy_version<>OLD.policy_version
     OR NEW.policy_revision_id<>OLD.policy_revision_id
     OR NEW.policy_decision_source<>OLD.policy_decision_source
     OR NEW.policy_authorization_ref IS DISTINCT FROM OLD.policy_authorization_ref
     OR NEW.content_hash<>OLD.content_hash OR NEW.created_at<>OLD.created_at
     OR NEW.review_reason IS NULL OR NEW.reviewed_at IS NULL THEN
    RAISE EXCEPTION 'episode suggestion review may change status and review fields only'
      USING ERRCODE='55000';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER guard_episode_suggestion_review
BEFORE UPDATE ON havre.episode_memory_suggestions
FOR EACH ROW EXECUTE FUNCTION havre.guard_episode_suggestion_review();

CREATE FUNCTION havre.guard_feedback_revision_canonical_hash() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE head havre.response_feedback_heads%ROWTYPE;
DECLARE source_privacy text;
DECLARE material jsonb;
DECLARE expected text;
BEGIN
  SELECT * INTO head FROM havre.response_feedback_heads
    WHERE owner_id=NEW.owner_id AND feedback_id=NEW.feedback_id;
  SELECT privacy_class INTO source_privacy FROM havre.events
    WHERE owner_id=head.owner_id AND event_id=head.assistant_event_id;
  material := jsonb_build_object(
    'schema_version',NEW.schema_version,'feedback_id',NEW.feedback_id,
    'revision',NEW.revision,'owner_id',NEW.owner_id,
    'request_id',head.request_id,'session_id',head.session_id,
    'trace_id',head.trace_id,'user_event_id',head.user_event_id,
    'assistant_event_id',head.assistant_event_id,
    'context_pack_id',head.context_pack_id,
    'route_decision_id',head.route_decision_id,
    'inference_response_id',head.inference_response_id,
    'provider_id',NEW.provider_id,'model_version_id',NEW.model_version_id,
    'adapter_version_id',NEW.adapter_version_id,
    'tokenizer_version_id',NEW.tokenizer_version_id,
    'serving_config_version',NEW.serving_config_version,
    'rating',NEW.rating,'reason_codes',to_jsonb(NEW.reason_codes),
    'reason_text',NEW.reason_text,'owner_revision_text',NEW.owner_revision_text,
    'privacy_class',NEW.privacy_class,'training_eligible',NEW.training_eligible
  );
  expected := 'sha256:' || encode(
    public.digest(convert_to(havre.canonical_jsonb(material),'UTF8'),'sha256'),'hex'
  );
  IF head IS NULL OR NEW.privacy_class<>source_privacy OR NEW.content_hash<>expected THEN
    RAISE EXCEPTION 'feedback revision canonical privacy or hash mismatch'
      USING ERRCODE='55000';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER guard_feedback_revision_canonical_hash
BEFORE INSERT ON havre.response_feedback_revisions
FOR EACH ROW EXECUTE FUNCTION havre.guard_feedback_revision_canonical_hash();

CREATE FUNCTION havre.guard_feedback_review_canonical_hash() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE material jsonb;
DECLARE expected text;
BEGIN
  IF NEW.training_eligible
     OR NEW.decision='approved_for_personalization_training' THEN
    RAISE EXCEPTION 'Stage 9B training authorization is not active'
      USING ERRCODE='55000';
  END IF;
  material := jsonb_build_object(
    'schema_version',NEW.schema_version,'review_id',NEW.review_id,
    'owner_id',NEW.owner_id,'feedback_id',NEW.feedback_id,
    'feedback_revision',NEW.feedback_revision,'decision',NEW.decision,
    'issue_attributions',to_jsonb(NEW.issue_attributions),
    'review_notes',NEW.review_notes,'training_eligible',NEW.training_eligible,
    'authorization_ref',NEW.authorization_ref
  );
  expected := 'sha256:' || encode(
    public.digest(convert_to(havre.canonical_jsonb(material),'UTF8'),'sha256'),'hex'
  );
  IF NEW.content_hash<>expected THEN
    RAISE EXCEPTION 'feedback review canonical hash mismatch' USING ERRCODE='55000';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER guard_feedback_review_canonical_hash
BEFORE INSERT ON havre.personalization_feedback_reviews
FOR EACH ROW EXECUTE FUNCTION havre.guard_feedback_review_canonical_hash();

CREATE FUNCTION havre.guard_communication_preference_canonical_hash() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE material jsonb;
DECLARE expected text;
BEGIN
  material := jsonb_build_object(
    'schema_version',NEW.schema_version,'owner_id',NEW.owner_id,
    'revision',NEW.revision,'response_length',NEW.response_length,'reason',NEW.reason
  );
  expected := 'sha256:' || encode(
    public.digest(convert_to(havre.canonical_jsonb(material),'UTF8'),'sha256'),'hex'
  );
  IF NEW.content_hash<>expected THEN
    RAISE EXCEPTION 'communication preference canonical hash mismatch'
      USING ERRCODE='55000';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER guard_communication_preference_canonical_hash
BEFORE INSERT ON havre.communication_preference_revisions
FOR EACH ROW EXECUTE FUNCTION havre.guard_communication_preference_canonical_hash();

CREATE FUNCTION havre.guard_episode_member_lineage() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE episode havre.conversation_episodes%ROWTYPE;
DECLARE source_event havre.events%ROWTYPE;
BEGIN
  SELECT * INTO episode FROM havre.conversation_episodes
    WHERE owner_id=NEW.owner_id AND episode_id=NEW.episode_id;
  SELECT * INTO source_event FROM havre.events
    WHERE owner_id=NEW.owner_id AND event_id=NEW.event_id;
  IF episode IS NULL OR source_event IS NULL
     OR source_event.session_id<>episode.session_id
     OR source_event.event_type<>NEW.event_type
     OR source_event.content_hash<>NEW.event_content_hash THEN
    RAISE EXCEPTION 'episode member must bind an exact Event from its session'
      USING ERRCODE='55000';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER guard_episode_member_lineage
BEFORE INSERT ON havre.conversation_episode_members
FOR EACH ROW EXECUTE FUNCTION havre.guard_episode_member_lineage();

CREATE FUNCTION havre.require_episode_canonical_closure() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE episode havre.conversation_episodes%ROWTYPE;
DECLARE member_hashes jsonb;
DECLARE member_count integer;
DECLARE source_count integer;
DECLARE bad_order integer;
DECLARE expected_privacy text;
DECLARE expected_memory boolean;
DECLARE expected_cloud boolean;
DECLARE expected_started timestamptz;
DECLARE expected_ended timestamptz;
DECLARE owner_text text;
DECLARE expected_summary text;
DECLARE material jsonb;
DECLARE expected_hash text;
BEGIN
  SELECT * INTO episode FROM havre.conversation_episodes
    WHERE owner_id=NEW.owner_id AND episode_id=NEW.episode_id;
  IF episode IS NULL THEN RETURN NULL; END IF;

  SELECT count(*),
         COALESCE(jsonb_agg(to_jsonb(event_content_hash) ORDER BY ordinal),'[]'::jsonb)
    INTO member_count,member_hashes
  FROM havre.conversation_episode_members
  WHERE owner_id=episode.owner_id AND episode_id=episode.episode_id;
  SELECT count(*),min(recorded_at),max(recorded_at)
    INTO source_count,expected_started,expected_ended
  FROM havre.events
  WHERE owner_id=episode.owner_id AND session_id=episode.session_id
    AND event_type IN ('USER_MESSAGE','ASSISTANT_MESSAGE');
  SELECT count(*) INTO bad_order
  FROM (
    SELECT member.ordinal,
           row_number() OVER (ORDER BY event.recorded_at,event.event_id)-1 AS expected_ordinal
    FROM havre.conversation_episode_members member
    JOIN havre.events event
      ON event.owner_id=member.owner_id AND event.event_id=member.event_id
    WHERE member.owner_id=episode.owner_id AND member.episode_id=episode.episode_id
  ) ordered
  WHERE ordinal<>expected_ordinal;
  IF member_count<>source_count OR member_count<>episode.message_count OR bad_order<>0 THEN
    RAISE EXCEPTION 'episode membership is not the exact ordered session closure'
      USING ERRCODE='55000';
  END IF;

  SELECT CASE max(CASE event.privacy_class
           WHEN 'PUBLIC' THEN 0 WHEN 'NORMAL' THEN 1 WHEN 'PRIVATE' THEN 2
           WHEN 'HIGHLY_PRIVATE' THEN 3 WHEN 'LOCAL_ONLY' THEN 4 END)
           WHEN 0 THEN 'PUBLIC' WHEN 1 THEN 'NORMAL' WHEN 2 THEN 'PRIVATE'
           WHEN 3 THEN 'HIGHLY_PRIVATE' WHEN 4 THEN 'LOCAL_ONLY' END,
         bool_and(event.memory_eligible) FILTER (WHERE event.event_type='USER_MESSAGE'),
         bool_and(event.cloud_eligible) FILTER (WHERE event.event_type='USER_MESSAGE')
    INTO expected_privacy,expected_memory,expected_cloud
  FROM havre.conversation_episode_members member
  JOIN havre.events event
    ON event.owner_id=member.owner_id AND event.event_id=member.event_id
  WHERE member.owner_id=episode.owner_id AND member.episode_id=episode.episode_id;

  SELECT string_agg(message_text,' ' ORDER BY recorded_at,event_id)
    INTO owner_text
  FROM (
    SELECT event.event_id,event.recorded_at,
           btrim(COALESCE((
             SELECT string_agg(part.value->>'text',E'\n' ORDER BY part.ordinality)
             FROM jsonb_array_elements(COALESCE(event.payload->'content_parts','[]'::jsonb))
                  WITH ORDINALITY AS part(value,ordinality)
             WHERE part.value->>'type'='text'
           ),''),E' \t\n\r\f\v') AS message_text
    FROM havre.conversation_episode_members member
    JOIN havre.events event
      ON event.owner_id=member.owner_id AND event.event_id=member.event_id
    WHERE member.owner_id=episode.owner_id AND member.episode_id=episode.episode_id
      AND event.event_type='USER_MESSAGE' AND event.memory_eligible
  ) messages
  WHERE message_text<>'';
  IF char_length(owner_text)>900 THEN
    owner_text := rtrim(left(owner_text,897),E' \t\n\r\f\v') || '…';
  END IF;
  IF owner_text IS NULL OR owner_text='' THEN
    expected_summary := 'Conversation retained as raw history; summary content was omitted because its effective policy was not Memory-eligible.';
  ELSE
    expected_summary := 'In this conversation, the owner said: ' || owner_text;
  END IF;

  IF episode.privacy_class<>expected_privacy
     OR episode.memory_eligible IS DISTINCT FROM expected_memory
     OR episode.cloud_eligible IS DISTINCT FROM expected_cloud
     OR episode.training_eligible
     OR episode.policy_version<>'data-policy-v1'
     OR episode.policy_decision_source<>'derived_conservative'
     OR episode.policy_authorization_ref IS NOT NULL
     OR episode.summary_text<>expected_summary
     OR episode.started_at<>expected_started OR episode.ended_at<>expected_ended THEN
    RAISE EXCEPTION 'episode summary or DataPolicy is not its exact conservative derivative'
      USING ERRCODE='55000';
  END IF;

  material := jsonb_build_object(
    'schema_version',episode.schema_version,'owner_id',episode.owner_id,
    'episode_id',episode.episode_id,'session_id',episode.session_id,
    'member_event_hashes',member_hashes,'summary_text',episode.summary_text,
    'summary_method',episode.summary_method,'privacy_class',episode.privacy_class,
    'memory_eligible',episode.memory_eligible,
    'training_eligible',episode.training_eligible,
    'cloud_eligible',episode.cloud_eligible,
    'boundary_reason',episode.boundary_reason
  );
  expected_hash := 'sha256:' || encode(
    public.digest(convert_to(havre.canonical_jsonb(material),'UTF8'),'sha256'),'hex'
  );
  IF episode.content_hash<>expected_hash THEN
    RAISE EXCEPTION 'conversation episode canonical hash mismatch' USING ERRCODE='55000';
  END IF;
  RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER require_episode_canonical_closure_from_episode
AFTER INSERT ON havre.conversation_episodes
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION havre.require_episode_canonical_closure();
CREATE CONSTRAINT TRIGGER require_episode_canonical_closure_from_member
AFTER INSERT ON havre.conversation_episode_members
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION havre.require_episode_canonical_closure();

CREATE FUNCTION havre.guard_episode_suggestion_canonical_hash() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE episode havre.conversation_episodes%ROWTYPE;
DECLARE material jsonb;
DECLARE expected text;
BEGIN
  SELECT * INTO episode FROM havre.conversation_episodes
    WHERE owner_id=NEW.owner_id AND episode_id=NEW.episode_id;
  IF episode IS NULL OR NEW.memory_class<>'episodic'
     OR NEW.content_text<>episode.summary_text
     OR NEW.privacy_class<>episode.privacy_class
     OR NEW.memory_eligible<>episode.memory_eligible
     OR NEW.cloud_eligible<>episode.cloud_eligible
     OR NEW.policy_version<>episode.policy_version
     OR NEW.policy_revision_id<>episode.policy_revision_id
     OR NEW.policy_decision_source<>episode.policy_decision_source
     OR NEW.policy_authorization_ref IS DISTINCT FROM episode.policy_authorization_ref THEN
    RAISE EXCEPTION 'episode suggestion must inherit exact episode content and DataPolicy'
      USING ERRCODE='55000';
  END IF;
  material := jsonb_build_object(
    'schema_version',NEW.schema_version,'owner_id',NEW.owner_id,
    'suggestion_id',NEW.suggestion_id,'episode_id',NEW.episode_id,
    'memory_class',NEW.memory_class,'content_text',NEW.content_text,
    'extractor_version',NEW.extractor_version,
    'privacy_class',NEW.privacy_class,'memory_eligible',NEW.memory_eligible,
    'training_eligible',NEW.training_eligible,'cloud_eligible',NEW.cloud_eligible,
    'policy_version',NEW.policy_version,'policy_revision_id',NEW.policy_revision_id,
    'policy_decision_source',NEW.policy_decision_source,
    'policy_authorization_ref',NEW.policy_authorization_ref
  );
  expected := 'sha256:' || encode(
    public.digest(convert_to(havre.canonical_jsonb(material),'UTF8'),'sha256'),'hex'
  );
  IF NEW.content_hash<>expected THEN
    RAISE EXCEPTION 'episode suggestion canonical hash mismatch' USING ERRCODE='55000';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER guard_episode_suggestion_canonical_hash
BEFORE INSERT ON havre.episode_memory_suggestions
FOR EACH ROW EXECUTE FUNCTION havre.guard_episode_suggestion_canonical_hash();

-- Validate non-reconstructible 0036 owner evidence. Pre-correction episodes
-- and suggestions are immutable owner-review evidence, so 0037 never rewrites
-- them in place to look as if the owner reviewed a different summary. Because
-- 0036 was never an accepted daily-use checkpoint, an installation containing
-- those rows must stop for an explicit governed migration instead.
DO $$
DECLARE item record;
DECLARE material jsonb;
DECLARE expected text;
DECLARE source_privacy text;
BEGIN
  IF EXISTS (SELECT 1 FROM havre.conversation_episodes)
     OR EXISTS (SELECT 1 FROM havre.episode_memory_suggestions) THEN
    RAISE EXCEPTION 'pre-correction episode evidence requires explicit governed migration'
      USING ERRCODE='55000';
  END IF;
  FOR item IN
    SELECT revision.*,head.request_id,head.session_id,head.trace_id,
           head.user_event_id,head.assistant_event_id,head.context_pack_id,
           head.route_decision_id,head.inference_response_id
    FROM havre.response_feedback_revisions revision
    JOIN havre.response_feedback_heads head
      ON head.owner_id=revision.owner_id AND head.feedback_id=revision.feedback_id
  LOOP
    SELECT privacy_class INTO source_privacy FROM havre.events
      WHERE owner_id=item.owner_id AND event_id=item.assistant_event_id;
    material := jsonb_build_object(
      'schema_version',item.schema_version,'feedback_id',item.feedback_id,
      'revision',item.revision,'owner_id',item.owner_id,
      'request_id',item.request_id,'session_id',item.session_id,
      'trace_id',item.trace_id,'user_event_id',item.user_event_id,
      'assistant_event_id',item.assistant_event_id,
      'context_pack_id',item.context_pack_id,
      'route_decision_id',item.route_decision_id,
      'inference_response_id',item.inference_response_id,
      'provider_id',item.provider_id,'model_version_id',item.model_version_id,
      'adapter_version_id',item.adapter_version_id,
      'tokenizer_version_id',item.tokenizer_version_id,
      'serving_config_version',item.serving_config_version,
      'rating',item.rating,'reason_codes',to_jsonb(item.reason_codes),
      'reason_text',item.reason_text,'owner_revision_text',item.owner_revision_text,
      'privacy_class',item.privacy_class,'training_eligible',item.training_eligible
    );
    expected := 'sha256:' || encode(
      public.digest(convert_to(havre.canonical_jsonb(material),'UTF8'),'sha256'),'hex'
    );
    IF item.content_hash<>expected OR item.privacy_class<>source_privacy THEN
      RAISE EXCEPTION 'pre-correction feedback canonical evidence mismatch'
        USING ERRCODE='55000';
    END IF;
  END LOOP;

  FOR item IN SELECT * FROM havre.personalization_feedback_reviews LOOP
    material := jsonb_build_object(
      'schema_version',item.schema_version,'review_id',item.review_id,
      'owner_id',item.owner_id,'feedback_id',item.feedback_id,
      'feedback_revision',item.feedback_revision,'decision',item.decision,
      'issue_attributions',to_jsonb(item.issue_attributions),
      'review_notes',item.review_notes,'training_eligible',item.training_eligible,
      'authorization_ref',item.authorization_ref
    );
    expected := 'sha256:' || encode(
      public.digest(convert_to(havre.canonical_jsonb(material),'UTF8'),'sha256'),'hex'
    );
    IF item.content_hash<>expected OR item.training_eligible
       OR item.decision='approved_for_personalization_training' THEN
      RAISE EXCEPTION 'pre-correction feedback review is not admissible'
        USING ERRCODE='55000';
    END IF;
  END LOOP;

  FOR item IN SELECT * FROM havre.communication_preference_revisions LOOP
    material := jsonb_build_object(
      'schema_version',item.schema_version,'owner_id',item.owner_id,
      'revision',item.revision,'response_length',item.response_length,
      'reason',item.reason
    );
    expected := 'sha256:' || encode(
      public.digest(convert_to(havre.canonical_jsonb(material),'UTF8'),'sha256'),'hex'
    );
    IF item.content_hash<>expected THEN
      RAISE EXCEPTION 'pre-correction communication preference hash mismatch'
        USING ERRCODE='55000';
    END IF;
  END LOOP;

END;
$$;

CREATE OR REPLACE VIEW havre.daily_learning_integrity_violations AS
SELECT head.feedback_id AS provenance_edge_id,head.owner_id,
       'response_feedback'::text AS source_kind,head.assistant_event_id AS source_id,
       NULL::integer AS source_revision,'feedback_source_lineage_mismatch'::text AS violation_code
FROM havre.response_feedback_heads head
JOIN havre.interaction_requests request
  ON request.owner_id=head.owner_id AND request.request_id=head.request_id
JOIN havre.events user_event
  ON user_event.owner_id=head.owner_id AND user_event.event_id=head.user_event_id
JOIN havre.events assistant_event
  ON assistant_event.owner_id=head.owner_id AND assistant_event.event_id=head.assistant_event_id
JOIN havre.inference_attempts inference
  ON inference.owner_id=head.owner_id
 AND inference.inference_response_id=head.inference_response_id
JOIN havre.response_feedback_revisions revision
  ON revision.owner_id=head.owner_id AND revision.feedback_id=head.feedback_id
 AND revision.revision=head.current_revision
WHERE request.session_id<>head.session_id OR request.trace_id<>head.trace_id
   OR request.user_event_id<>head.user_event_id
   OR request.assistant_event_id<>head.assistant_event_id
   OR request.context_pack_id<>head.context_pack_id
   OR request.inference_response_id<>head.inference_response_id
   OR user_event.event_type<>'USER_MESSAGE'
   OR assistant_event.event_type<>'ASSISTANT_MESSAGE'
   OR user_event.session_id<>head.session_id OR assistant_event.session_id<>head.session_id
   OR inference.route_decision_id<>head.route_decision_id
   OR revision.privacy_class<>assistant_event.privacy_class
UNION ALL
SELECT member.episode_id,member.owner_id,'conversation_episode',member.event_id,
       member.ordinal,'episode_member_lineage_mismatch'
FROM havre.conversation_episode_members member
JOIN havre.conversation_episodes episode
  ON episode.owner_id=member.owner_id AND episode.episode_id=member.episode_id
JOIN havre.events event
  ON event.owner_id=member.owner_id AND event.event_id=member.event_id
WHERE event.content_hash<>member.event_content_hash
   OR event.event_type<>member.event_type OR event.session_id<>episode.session_id
UNION ALL
SELECT episode.episode_id,episode.owner_id,'conversation_episode',episode.episode_id,
       NULL::integer,'episode_member_count_mismatch'
FROM havre.conversation_episodes episode
LEFT JOIN havre.conversation_episode_members member
  ON member.owner_id=episode.owner_id AND member.episode_id=episode.episode_id
GROUP BY episode.owner_id,episode.episode_id,episode.message_count,episode.session_id
HAVING count(member.event_id)<>episode.message_count
    OR count(member.event_id)<>(
      SELECT count(*) FROM havre.events event
      WHERE event.owner_id=episode.owner_id AND event.session_id=episode.session_id
        AND event.event_type IN ('USER_MESSAGE','ASSISTANT_MESSAGE')
    )
UNION ALL
SELECT suggestion.suggestion_id,suggestion.owner_id,'episode_memory_suggestion',
       suggestion.episode_id,NULL::integer,'suggestion_policy_mismatch'
FROM havre.episode_memory_suggestions suggestion
JOIN havre.conversation_episodes episode
  ON episode.owner_id=suggestion.owner_id AND episode.episode_id=suggestion.episode_id
WHERE suggestion.content_text<>episode.summary_text
   OR suggestion.privacy_class<>episode.privacy_class
   OR suggestion.memory_eligible<>episode.memory_eligible
   OR suggestion.cloud_eligible<>episode.cloud_eligible
   OR suggestion.policy_version<>episode.policy_version
   OR suggestion.policy_revision_id<>episode.policy_revision_id
   OR suggestion.policy_decision_source<>episode.policy_decision_source
   OR suggestion.policy_authorization_ref IS DISTINCT FROM episode.policy_authorization_ref;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM havre.personalization_feedback_reviews
    WHERE training_eligible OR decision='approved_for_personalization_training'
  ) THEN
    RAISE EXCEPTION 'pre-correction training-eligible feedback cannot be retained'
      USING ERRCODE='55000';
  END IF;
  IF EXISTS (SELECT 1 FROM havre.daily_learning_integrity_violations) THEN
    RAISE EXCEPTION 'pre-correction daily learning provenance violation'
      USING ERRCODE='55000';
  END IF;
END;
$$;
