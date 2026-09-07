-- Historical daily revisions retain midnight attribution; v6 uses 05:00.
CREATE OR REPLACE FUNCTION havre.guard_daily_diary_source() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE source_event havre.events%ROWTYPE; method text; start_hour integer;
BEGIN
 SELECT * INTO STRICT source_event FROM havre.events WHERE owner_id=NEW.owner_id AND event_id=NEW.event_id;
 SELECT summary_method INTO STRICT method FROM havre.daily_diary_entry_revisions
  WHERE owner_id=NEW.owner_id AND local_date=NEW.local_date AND timezone_name=NEW.timezone_name AND revision=NEW.revision;
 start_hour:=CASE WHEN method='gpt-owner-five-am-diary-v6' THEN 5 ELSE 0 END;
 IF source_event.event_type NOT IN ('USER_MESSAGE','ASSISTANT_MESSAGE')
  OR source_event.content_hash<>NEW.event_content_hash
  OR ((source_event.recorded_at AT TIME ZONE NEW.timezone_name)-make_interval(hours=>start_hour))::date<>NEW.local_date THEN
  RAISE EXCEPTION 'daily diary source must match exact versioned owner-local window' USING ERRCODE='55000';
 END IF;
 RETURN NEW;
END $$;
