-- Owner response feedback and governed personalization evidence.
-- Original interaction Events remain immutable. Saved feedback is never
-- training-eligible; a separate exact owner review may authorize one revision.

CREATE FUNCTION havre.text_array_is_unique(values_to_check text[]) RETURNS boolean
LANGUAGE sql IMMUTABLE STRICT AS $$
  SELECT cardinality(values_to_check) = count(DISTINCT value)
  FROM unnest(values_to_check) AS value
$$;

CREATE TABLE havre.response_feedback_heads (
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    feedback_id uuid NOT NULL,
    request_id uuid NOT NULL,
    session_id uuid NOT NULL,
    trace_id char(32) NOT NULL,
    user_event_id uuid NOT NULL,
    assistant_event_id uuid NOT NULL,
    context_pack_id uuid NOT NULL,
    route_decision_id uuid NOT NULL,
    inference_response_id uuid NOT NULL,
    current_revision integer NOT NULL CHECK (current_revision > 0),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (owner_id, feedback_id),
    UNIQUE (owner_id, assistant_event_id),
    FOREIGN KEY (owner_id, request_id)
      REFERENCES havre.interaction_requests(owner_id, request_id),
    FOREIGN KEY (session_id, owner_id)
      REFERENCES havre.sessions(session_id, owner_id),
    FOREIGN KEY (owner_id, user_event_id)
      REFERENCES havre.events(owner_id, event_id),
    FOREIGN KEY (owner_id, assistant_event_id)
      REFERENCES havre.events(owner_id, event_id),
    FOREIGN KEY (owner_id, context_pack_id)
      REFERENCES havre.context_packs(owner_id, context_pack_id),
    FOREIGN KEY (owner_id, route_decision_id)
      REFERENCES havre.route_decisions(owner_id, route_decision_id),
    FOREIGN KEY (owner_id, inference_response_id)
      REFERENCES havre.inference_attempts(owner_id, inference_response_id),
    FOREIGN KEY (owner_id, request_id, trace_id)
      REFERENCES havre.interaction_requests(owner_id, request_id, trace_id),
    FOREIGN KEY (owner_id, request_id, trace_id, context_pack_id)
      REFERENCES havre.context_packs(owner_id, request_id, trace_id, context_pack_id),
    FOREIGN KEY (owner_id, request_id, trace_id, route_decision_id)
      REFERENCES havre.route_decisions(owner_id, request_id, trace_id, route_decision_id),
    FOREIGN KEY (owner_id, request_id, inference_response_id)
      REFERENCES havre.inference_attempts(owner_id, request_id, inference_response_id)
);
CREATE INDEX response_feedback_heads_owner_session_idx
    ON havre.response_feedback_heads(owner_id, session_id, updated_at DESC);

CREATE TABLE havre.response_feedback_revisions (
    owner_id uuid NOT NULL,
    feedback_id uuid NOT NULL,
    revision integer NOT NULL CHECK (revision > 0),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    rating text NOT NULL CHECK (rating IN ('helpful','unhelpful','mixed')),
    reason_codes text[] NOT NULL DEFAULT '{}',
    reason_text text NULL CHECK (reason_text IS NULL OR length(reason_text) <= 2000),
    owner_revision_text text NULL CHECK (
      owner_revision_text IS NULL OR length(owner_revision_text) BETWEEN 1 AND 100000
    ),
    provider_id text NOT NULL,
    model_version_id text NOT NULL,
    adapter_version_id text NULL,
    tokenizer_version_id text NOT NULL,
    serving_config_version text NOT NULL,
    privacy_class text NOT NULL CHECK (privacy_class IN (
      'PUBLIC','NORMAL','PRIVATE','HIGHLY_PRIVATE','LOCAL_ONLY'
    )),
    training_eligible boolean NOT NULL DEFAULT false CHECK (training_eligible=false),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (owner_id, feedback_id, revision),
    FOREIGN KEY (owner_id, feedback_id)
      REFERENCES havre.response_feedback_heads(owner_id, feedback_id),
    CHECK (reason_codes <@ ARRAY[
      'too_ai','too_long','not_warm_enough','not_firm_enough',
      'fabricated_memory','wrong_user_fact','misunderstood_intent','wrong_mode',
      'unhelpful_advice','not_havre','other'
    ]::text[]),
    CHECK (havre.text_array_is_unique(reason_codes))
);
CREATE INDEX response_feedback_revisions_owner_created_idx
    ON havre.response_feedback_revisions(owner_id, created_at DESC);

CREATE TABLE havre.personalization_feedback_reviews (
    owner_id uuid NOT NULL,
    review_id uuid NOT NULL,
    feedback_id uuid NOT NULL,
    feedback_revision integer NOT NULL CHECK (feedback_revision > 0),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version=1),
    decision text NOT NULL CHECK (decision IN (
      'runtime_fix','approved_for_personalization_training','evaluation_only',
      'deferred','rejected'
    )),
    issue_attributions text[] NOT NULL CHECK (cardinality(issue_attributions) > 0),
    review_notes text NULL CHECK (review_notes IS NULL OR length(review_notes) <= 4000),
    training_eligible boolean NOT NULL,
    authorization_ref text NULL CHECK (
      authorization_ref IS NULL OR length(authorization_ref) <= 500
    ),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    reviewed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (owner_id, review_id),
    UNIQUE (owner_id, feedback_id, feedback_revision),
    FOREIGN KEY (owner_id, feedback_id, feedback_revision)
      REFERENCES havre.response_feedback_revisions(owner_id, feedback_id, revision),
    CHECK (issue_attributions <@ ARRAY[
      'personality_communication','memory_grounding_truthfulness','memory_retrieval',
      'core_policy','mode_selection','reasoning_understanding','other_system',
      'mixed','unclassified'
    ]::text[]),
    CHECK (havre.text_array_is_unique(issue_attributions)),
    CHECK (
      (decision='approved_for_personalization_training'
       AND training_eligible=true AND authorization_ref IS NOT NULL
       AND NOT ('unclassified'=ANY(issue_attributions)))
      OR
      (decision<>'approved_for_personalization_training'
       AND training_eligible=false AND authorization_ref IS NULL)
    )
);

CREATE TABLE havre.communication_preference_revisions (
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    revision integer NOT NULL CHECK (revision > 0),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version=1),
    response_length text NOT NULL CHECK (response_length IN ('brief','balanced','detailed')),
    reason text NOT NULL CHECK (length(reason) BETWEEN 1 AND 1000),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (owner_id, revision)
);

CREATE TABLE havre.conversation_episodes (
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    episode_id uuid NOT NULL,
    session_id uuid NOT NULL,
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version=1),
    status text NOT NULL CHECK (status IN ('closed')),
    boundary_reason text NOT NULL CHECK (boundary_reason IN (
      'owner_started_new_conversation','owner_closed','idle_boundary'
    )),
    message_count integer NOT NULL CHECK (message_count > 0),
    summary_text text NOT NULL CHECK (length(summary_text) BETWEEN 1 AND 100000),
    summary_method text NOT NULL CHECK (summary_method='extractive-episode-summary-v1'),
    privacy_class text NOT NULL CHECK (privacy_class IN (
      'PUBLIC','NORMAL','PRIVATE','HIGHLY_PRIVATE','LOCAL_ONLY'
    )),
    memory_eligible boolean NOT NULL,
    training_eligible boolean NOT NULL DEFAULT false CHECK (training_eligible=false),
    cloud_eligible boolean NOT NULL,
    policy_version text NOT NULL CHECK (policy_version='data-policy-v1'),
    policy_revision_id uuid NOT NULL,
    policy_decision_source text NOT NULL CHECK (policy_decision_source IN (
      'owner_default','owner_explicit','derived_conservative'
    )),
    policy_authorization_ref text NULL,
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    started_at timestamptz NOT NULL,
    ended_at timestamptz NOT NULL CHECK (ended_at>=started_at),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (owner_id, episode_id),
    UNIQUE (owner_id, session_id),
    FOREIGN KEY (session_id, owner_id) REFERENCES havre.sessions(session_id, owner_id),
    CHECK (privacy_class<>'LOCAL_ONLY' OR cloud_eligible=false)
);
CREATE INDEX conversation_episodes_owner_ended_idx
  ON havre.conversation_episodes(owner_id, ended_at DESC);

CREATE TABLE havre.conversation_episode_members (
    owner_id uuid NOT NULL,
    episode_id uuid NOT NULL,
    ordinal integer NOT NULL CHECK (ordinal>=0),
    event_id uuid NOT NULL,
    event_content_hash text NOT NULL CHECK (event_content_hash ~ '^sha256:[0-9a-f]{64}$'),
    event_type text NOT NULL CHECK (event_type IN ('USER_MESSAGE','ASSISTANT_MESSAGE')),
    PRIMARY KEY (owner_id, episode_id, ordinal),
    UNIQUE (owner_id, episode_id, event_id),
    FOREIGN KEY (owner_id, episode_id)
      REFERENCES havre.conversation_episodes(owner_id, episode_id),
    FOREIGN KEY (owner_id, event_id) REFERENCES havre.events(owner_id, event_id)
);
CREATE INDEX conversation_episode_members_event_idx
  ON havre.conversation_episode_members(owner_id,event_id);

CREATE TABLE havre.episode_memory_suggestions (
    owner_id uuid NOT NULL,
    suggestion_id uuid NOT NULL,
    episode_id uuid NOT NULL,
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version=1),
    memory_class text NOT NULL CHECK (memory_class IN (
      'episodic','semantic','preference','pattern'
    )),
    content_text text NOT NULL CHECK (length(content_text) BETWEEN 1 AND 100000),
    extractor_version text NOT NULL CHECK (extractor_version='episode-suggestion-v1'),
    status text NOT NULL CHECK (status IN ('pending','accepted','rejected')),
    review_reason text NULL CHECK (review_reason IS NULL OR length(review_reason)<=2000),
    training_eligible boolean NOT NULL DEFAULT false CHECK (training_eligible=false),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    reviewed_at timestamptz NULL,
    PRIMARY KEY (owner_id,suggestion_id),
    UNIQUE (owner_id,episode_id,memory_class,content_hash),
    FOREIGN KEY (owner_id,episode_id)
      REFERENCES havre.conversation_episodes(owner_id,episode_id),
    CHECK ((status='pending' AND review_reason IS NULL AND reviewed_at IS NULL)
      OR (status IN ('accepted','rejected') AND review_reason IS NOT NULL
          AND reviewed_at IS NOT NULL))
);
CREATE INDEX episode_memory_suggestions_owner_status_idx
  ON havre.episode_memory_suggestions(owner_id,status,created_at DESC);

CREATE TRIGGER response_feedback_revisions_immutable
BEFORE UPDATE OR DELETE ON havre.response_feedback_revisions
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();
CREATE TRIGGER personalization_feedback_reviews_immutable
BEFORE UPDATE OR DELETE ON havre.personalization_feedback_reviews
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();
CREATE TRIGGER communication_preference_revisions_immutable
BEFORE UPDATE OR DELETE ON havre.communication_preference_revisions
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();
CREATE TRIGGER conversation_episodes_immutable
BEFORE UPDATE OR DELETE ON havre.conversation_episodes
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();
CREATE TRIGGER conversation_episode_members_immutable
BEFORE UPDATE OR DELETE ON havre.conversation_episode_members
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();
CREATE FUNCTION havre.guard_episode_suggestion_review() RETURNS trigger
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
     OR NEW.training_eligible<>OLD.training_eligible
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
CREATE TRIGGER episode_memory_suggestions_no_delete
BEFORE DELETE ON havre.episode_memory_suggestions
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();

CREATE FUNCTION havre.guard_response_feedback_revision() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  head havre.response_feedback_heads%ROWTYPE;
  attempt havre.inference_attempts%ROWTYPE;
BEGIN
  SELECT * INTO head FROM havre.response_feedback_heads
    WHERE owner_id=NEW.owner_id AND feedback_id=NEW.feedback_id FOR UPDATE;
  IF head IS NULL OR NEW.revision <> head.current_revision THEN
    RAISE EXCEPTION 'feedback revision must equal the exact locked head revision'
      USING ERRCODE='55000';
  END IF;
  SELECT * INTO attempt FROM havre.inference_attempts
    WHERE owner_id=head.owner_id
      AND inference_response_id=head.inference_response_id;
  IF attempt IS NULL OR NEW.provider_id<>attempt.provider_id
     OR NEW.model_version_id<>attempt.model_version_id
     OR NEW.adapter_version_id IS DISTINCT FROM attempt.adapter_version_id
     OR NEW.tokenizer_version_id<>attempt.tokenizer_version_id
     OR NEW.serving_config_version<>attempt.serving_config_version THEN
    RAISE EXCEPTION 'feedback model lineage does not match source inference'
      USING ERRCODE='55000';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER guard_response_feedback_revision
BEFORE INSERT ON havre.response_feedback_revisions
FOR EACH ROW EXECUTE FUNCTION havre.guard_response_feedback_revision();

CREATE FUNCTION havre.guard_response_feedback_head_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  request_row havre.interaction_requests%ROWTYPE;
  user_type text;
  assistant_type text;
  inference_route uuid;
BEGIN
  SELECT * INTO request_row FROM havre.interaction_requests
    WHERE owner_id=NEW.owner_id AND request_id=NEW.request_id;
  SELECT event_type INTO user_type FROM havre.events
    WHERE owner_id=NEW.owner_id AND event_id=NEW.user_event_id;
  SELECT event_type INTO assistant_type FROM havre.events
    WHERE owner_id=NEW.owner_id AND event_id=NEW.assistant_event_id;
  SELECT route_decision_id INTO inference_route FROM havre.inference_attempts
    WHERE owner_id=NEW.owner_id
      AND inference_response_id=NEW.inference_response_id;
  IF request_row IS NULL OR request_row.status<>'completed'
     OR request_row.session_id<>NEW.session_id OR request_row.trace_id<>NEW.trace_id
     OR request_row.user_event_id<>NEW.user_event_id
     OR request_row.assistant_event_id<>NEW.assistant_event_id
     OR request_row.context_pack_id<>NEW.context_pack_id
     OR request_row.inference_response_id<>NEW.inference_response_id
     OR user_type<>'USER_MESSAGE' OR assistant_type<>'ASSISTANT_MESSAGE'
     OR inference_route<>NEW.route_decision_id OR NEW.current_revision<>1 THEN
    RAISE EXCEPTION 'feedback head does not match exact completed interaction lineage'
      USING ERRCODE='55000';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER guard_response_feedback_head_insert
BEFORE INSERT ON havre.response_feedback_heads
FOR EACH ROW EXECUTE FUNCTION havre.guard_response_feedback_head_insert();

CREATE FUNCTION havre.guard_response_feedback_head_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.owner_id<>OLD.owner_id OR NEW.feedback_id<>OLD.feedback_id
     OR NEW.request_id<>OLD.request_id OR NEW.session_id<>OLD.session_id
     OR NEW.trace_id<>OLD.trace_id OR NEW.user_event_id<>OLD.user_event_id
     OR NEW.assistant_event_id<>OLD.assistant_event_id
     OR NEW.context_pack_id<>OLD.context_pack_id
     OR NEW.route_decision_id<>OLD.route_decision_id
     OR NEW.inference_response_id<>OLD.inference_response_id
     OR NEW.current_revision<>OLD.current_revision+1 THEN
    RAISE EXCEPTION 'feedback head may advance exactly one revision only'
      USING ERRCODE='55000';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER guard_response_feedback_head_update
BEFORE UPDATE ON havre.response_feedback_heads
FOR EACH ROW EXECUTE FUNCTION havre.guard_response_feedback_head_update();

CREATE FUNCTION havre.require_feedback_head_revision() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM havre.response_feedback_revisions revision
    WHERE revision.owner_id=NEW.owner_id
      AND revision.feedback_id=NEW.feedback_id
      AND revision.revision=NEW.current_revision
  ) THEN
    RAISE EXCEPTION 'feedback head requires its exact durable revision'
      USING ERRCODE='55000';
  END IF;
  RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER require_feedback_head_revision
AFTER INSERT OR UPDATE ON havre.response_feedback_heads
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION havre.require_feedback_head_revision();

CREATE FUNCTION havre.guard_feedback_review() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  revision_row havre.response_feedback_revisions%ROWTYPE;
  current_head integer;
BEGIN
  SELECT rev.* INTO revision_row
  FROM havre.response_feedback_revisions rev
  WHERE rev.owner_id=NEW.owner_id AND rev.feedback_id=NEW.feedback_id
    AND rev.revision=NEW.feedback_revision;
  SELECT current_revision INTO current_head FROM havre.response_feedback_heads
    WHERE owner_id=NEW.owner_id AND feedback_id=NEW.feedback_id;
  IF revision_row IS NULL OR current_head<>NEW.feedback_revision THEN
    RAISE EXCEPTION 'review must bind the current exact feedback revision'
      USING ERRCODE='55000';
  END IF;
  IF NEW.training_eligible AND revision_row.owner_revision_text IS NULL THEN
    RAISE EXCEPTION 'training approval requires an owner revision'
      USING ERRCODE='55000';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER guard_feedback_review
BEFORE INSERT ON havre.personalization_feedback_reviews
FOR EACH ROW EXECUTE FUNCTION havre.guard_feedback_review();

CREATE VIEW havre.daily_learning_integrity_violations AS
SELECT head.feedback_id AS provenance_edge_id,head.owner_id,
       'response_feedback'::text AS source_kind,head.assistant_event_id AS source_id,
       NULL::integer AS source_revision,'feedback_source_lineage_mismatch'::text AS violation_code
FROM havre.response_feedback_heads head
JOIN havre.interaction_requests request
  ON request.owner_id=head.owner_id AND request.request_id=head.request_id
JOIN havre.events user_event
  ON user_event.owner_id=head.owner_id AND user_event.event_id=head.user_event_id
JOIN havre.events assistant_event
  ON assistant_event.owner_id=head.owner_id
 AND assistant_event.event_id=head.assistant_event_id
JOIN havre.inference_attempts inference
  ON inference.owner_id=head.owner_id
 AND inference.inference_response_id=head.inference_response_id
WHERE request.session_id<>head.session_id OR request.trace_id<>head.trace_id
   OR request.user_event_id<>head.user_event_id
   OR request.assistant_event_id<>head.assistant_event_id
   OR request.context_pack_id<>head.context_pack_id
   OR request.inference_response_id<>head.inference_response_id
   OR user_event.event_type<>'USER_MESSAGE'
   OR assistant_event.event_type<>'ASSISTANT_MESSAGE'
   OR inference.route_decision_id<>head.route_decision_id
UNION ALL
SELECT member.episode_id,member.owner_id,'conversation_episode',member.event_id,
       member.ordinal,'episode_member_hash_mismatch'
FROM havre.conversation_episode_members member
JOIN havre.events event
  ON event.owner_id=member.owner_id AND event.event_id=member.event_id
WHERE event.content_hash<>member.event_content_hash
   OR event.event_type<>member.event_type
UNION ALL
SELECT episode.episode_id,episode.owner_id,'conversation_episode',episode.episode_id,
       NULL::integer,'episode_member_count_mismatch'
FROM havre.conversation_episodes episode
LEFT JOIN havre.conversation_episode_members member
  ON member.owner_id=episode.owner_id AND member.episode_id=episode.episode_id
GROUP BY episode.owner_id,episode.episode_id,episode.message_count
HAVING count(member.event_id)<>episode.message_count;

GRANT SELECT, INSERT, UPDATE ON havre.response_feedback_heads TO havre_application;
GRANT SELECT, INSERT ON havre.response_feedback_revisions TO havre_application;
GRANT SELECT, INSERT ON havre.personalization_feedback_reviews TO havre_application;
GRANT SELECT, INSERT ON havre.communication_preference_revisions TO havre_application;
GRANT SELECT, INSERT ON havre.conversation_episodes TO havre_application;
GRANT SELECT, INSERT ON havre.conversation_episode_members TO havre_application;
GRANT SELECT, INSERT, UPDATE ON havre.episode_memory_suggestions TO havre_application;
GRANT SELECT ON havre.daily_learning_integrity_violations TO havre_application;
