-- A button tap is an auditable interaction request, not an owner-authored utterance.
-- Legacy payloads and their hashes are untouched.
ALTER TABLE havre.events ADD CONSTRAINT events_input_origin_shape CHECK (
    NOT (payload ? 'input_origin') OR COALESCE(
        event_type = 'USER_MESSAGE' AND (
            payload->>'input_origin' = 'owner_text' OR (
                payload->>'input_origin' = 'continuation_button'
                AND session_id IS NOT NULL
                AND jsonb_typeof(payload->'reply_to_event_id') = 'string'
                AND payload->'content_parts' = '[{"type":"text","text":"再说点"}]'::jsonb
            )
        ), false)
);

CREATE FUNCTION havre.guard_continuation_button_source() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE parent havre.events%ROWTYPE;
BEGIN
    IF NEW.payload->>'input_origin' IS DISTINCT FROM 'continuation_button' THEN
        RETURN NEW;
    END IF;
    SELECT event.* INTO parent FROM havre.events event
    JOIN havre.interaction_requests request
      ON request.owner_id=event.owner_id AND request.request_id=event.request_id
    WHERE event.owner_id=NEW.owner_id
      AND event.event_id::text=NEW.payload->>'reply_to_event_id'
      AND event.session_id=NEW.session_id AND event.event_type='ASSISTANT_MESSAGE'
      AND request.request_kind='interaction' AND request.status='completed'
      AND request.assistant_event_id=event.event_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'continuation button requires its owner/session completed reply' USING ERRCODE='55000';
    END IF;
    IF (NEW.cloud_eligible AND NOT parent.cloud_eligible)
       OR (NEW.memory_eligible AND NOT parent.memory_eligible)
       OR (NEW.training_eligible AND NOT parent.training_eligible)
       OR array_position(ARRAY['PUBLIC','NORMAL','PRIVATE','HIGHLY_PRIVATE','LOCAL_ONLY'], NEW.privacy_class::text)
          < array_position(ARRAY['PUBLIC','NORMAL','PRIVATE','HIGHLY_PRIVATE','LOCAL_ONLY'], parent.privacy_class::text) THEN
        RAISE EXCEPTION 'continuation button cannot weaken source policy' USING ERRCODE='55000';
    END IF;
    IF EXISTS (SELECT 1 FROM havre.offline_source_revocations revoked
        JOIN havre.events source ON source.owner_id=revoked.owner_id AND source.event_id=revoked.source_event_id
        WHERE source.owner_id=NEW.owner_id AND source.request_id=parent.request_id) THEN
        RAISE EXCEPTION 'continuation button source was revoked' USING ERRCODE='55000';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER events_continuation_button_source BEFORE INSERT ON havre.events
FOR EACH ROW EXECUTE FUNCTION havre.guard_continuation_button_source();
