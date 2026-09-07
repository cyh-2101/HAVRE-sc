-- Daily Companion product projection: revocable owner devices, Web Push
-- delivery evidence, one continuous timeline read cursor, and provenance-bound
-- daily diary entries. Canonical chat history remains havre.events.

CREATE TABLE havre.companion_devices (
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    device_id uuid NOT NULL,
    display_name text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 120),
    device_kind text NOT NULL CHECK (device_kind IN ('windows','iphone','browser','other')),
    session_token_hash text NOT NULL CHECK (session_token_hash ~ '^sha256:[0-9a-f]{64}$'),
    session_expires_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    revoked_at timestamptz NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (owner_id, device_id),
    UNIQUE (owner_id, session_token_hash),
    CHECK (session_expires_at > created_at),
    CHECK (revoked_at IS NULL OR revoked_at >= created_at)
);
CREATE INDEX companion_devices_owner_active_idx
  ON havre.companion_devices(owner_id, created_at DESC) WHERE revoked_at IS NULL;

CREATE TABLE havre.device_pairing_challenges (
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    pairing_id uuid NOT NULL,
    code_hash text NOT NULL CHECK (code_hash ~ '^sha256:[0-9a-f]{64}$'),
    expires_at timestamptz NOT NULL,
    consumed_at timestamptz NULL,
    consumed_device_id uuid NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (owner_id, pairing_id),
    FOREIGN KEY (owner_id, consumed_device_id)
      REFERENCES havre.companion_devices(owner_id, device_id),
    CHECK (expires_at > created_at),
    CHECK ((consumed_at IS NULL) = (consumed_device_id IS NULL))
);
CREATE INDEX device_pairing_challenges_expiry_idx
  ON havre.device_pairing_challenges(owner_id, expires_at DESC);
CREATE INDEX device_pairing_challenges_consumed_device_fk_idx
  ON havre.device_pairing_challenges(owner_id, consumed_device_id)
  WHERE consumed_device_id IS NOT NULL;

CREATE TABLE havre.device_read_cursors (
    owner_id uuid NOT NULL,
    device_id uuid NOT NULL,
    last_read_event_id uuid NOT NULL,
    last_read_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (owner_id, device_id),
    FOREIGN KEY (owner_id, device_id)
      REFERENCES havre.companion_devices(owner_id, device_id),
    FOREIGN KEY (owner_id, last_read_event_id)
      REFERENCES havre.events(owner_id, event_id)
);
CREATE INDEX device_read_cursors_event_fk_idx
  ON havre.device_read_cursors(owner_id, last_read_event_id);

CREATE TABLE havre.web_push_subscriptions (
    owner_id uuid NOT NULL,
    subscription_id uuid NOT NULL,
    device_id uuid NOT NULL,
    endpoint text NOT NULL CHECK (length(endpoint) BETWEEN 12 AND 4096),
    endpoint_hash text NOT NULL CHECK (endpoint_hash ~ '^sha256:[0-9a-f]{64}$'),
    p256dh text NOT NULL CHECK (length(p256dh) BETWEEN 16 AND 512),
    auth_secret text NOT NULL CHECK (length(auth_secret) BETWEEN 8 AND 256),
    preview_level text NOT NULL CHECK (preview_level IN ('private','detailed')),
    status text NOT NULL CHECK (status IN ('active','revoked','expired')),
    expires_at timestamptz NULL,
    last_success_at timestamptz NULL,
    last_failure_at timestamptz NULL,
    revoked_at timestamptz NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (owner_id, subscription_id),
    UNIQUE (owner_id, endpoint_hash),
    FOREIGN KEY (owner_id, device_id)
      REFERENCES havre.companion_devices(owner_id, device_id),
    CHECK ((status='revoked') = (revoked_at IS NOT NULL))
);
CREATE INDEX web_push_subscriptions_active_idx
  ON havre.web_push_subscriptions(owner_id, device_id, created_at DESC)
  WHERE status='active';

CREATE TABLE havre.web_push_delivery_attempts (
    owner_id uuid NOT NULL,
    web_push_attempt_id uuid NOT NULL,
    subscription_id uuid NOT NULL,
    assistant_event_id uuid NOT NULL,
    proactive_delivery_attempt_id uuid NULL,
    idempotency_key text NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 240),
    attempt_number integer NOT NULL CHECK (attempt_number > 0),
    status text NOT NULL CHECK (status IN ('delivered','failed','expired','revoked','skipped')),
    retryable boolean NOT NULL,
    preview_level text NOT NULL CHECK (preview_level IN ('private','detailed')),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload)='object'),
    payload_hash text NOT NULL CHECK (payload_hash ~ '^sha256:[0-9a-f]{64}$'),
    provider_receipt_id text NULL,
    failure_code text NULL,
    attempted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (owner_id, web_push_attempt_id),
    UNIQUE (owner_id, subscription_id, idempotency_key, attempt_number),
    FOREIGN KEY (owner_id, subscription_id)
      REFERENCES havre.web_push_subscriptions(owner_id, subscription_id),
    FOREIGN KEY (owner_id, assistant_event_id)
      REFERENCES havre.events(owner_id, event_id),
    FOREIGN KEY (owner_id, proactive_delivery_attempt_id)
      REFERENCES havre.proactive_delivery_attempts(owner_id, delivery_attempt_id),
    CHECK (status <> 'delivered' OR provider_receipt_id IS NOT NULL),
    CHECK (status = 'failed' OR failure_code IS NULL)
);
CREATE INDEX web_push_delivery_event_idx
  ON havre.web_push_delivery_attempts(owner_id, assistant_event_id, attempted_at DESC);
CREATE INDEX web_push_delivery_proactive_attempt_fk_idx
  ON havre.web_push_delivery_attempts(owner_id, proactive_delivery_attempt_id)
  WHERE proactive_delivery_attempt_id IS NOT NULL;

CREATE TABLE havre.daily_diary_entry_heads (
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    local_date date NOT NULL,
    timezone_name text NOT NULL CHECK (length(timezone_name) BETWEEN 1 AND 80),
    current_revision integer NOT NULL CHECK (current_revision > 0),
    status text NOT NULL CHECK (status IN ('current','invalidated')),
    finalized_at timestamptz NULL,
    invalidated_at timestamptz NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (owner_id, local_date, timezone_name),
    CHECK ((status='invalidated') = (invalidated_at IS NOT NULL))
);

CREATE TABLE havre.daily_diary_entry_revisions (
    owner_id uuid NOT NULL,
    local_date date NOT NULL,
    timezone_name text NOT NULL,
    revision integer NOT NULL CHECK (revision > 0),
    title text NOT NULL CHECK (length(title) BETWEEN 1 AND 160),
    summary_text text NOT NULL CHECK (length(summary_text) BETWEEN 1 AND 4000),
    preview_text text NOT NULL CHECK (length(preview_text) BETWEEN 1 AND 500),
    summary_method text NOT NULL CHECK (summary_method='evidence-extractive-diary-v1'),
    source_set_hash text NOT NULL CHECK (source_set_hash ~ '^sha256:[0-9a-f]{64}$'),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (owner_id, local_date, timezone_name, revision),
    FOREIGN KEY (owner_id, local_date, timezone_name)
      REFERENCES havre.daily_diary_entry_heads(owner_id, local_date, timezone_name)
);

CREATE TABLE havre.daily_diary_entry_sources (
    owner_id uuid NOT NULL,
    local_date date NOT NULL,
    timezone_name text NOT NULL,
    revision integer NOT NULL,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    event_id uuid NOT NULL,
    event_content_hash text NOT NULL CHECK (event_content_hash ~ '^sha256:[0-9a-f]{64}$'),
    PRIMARY KEY (owner_id, local_date, timezone_name, revision, ordinal),
    UNIQUE (owner_id, local_date, timezone_name, revision, event_id),
    FOREIGN KEY (owner_id, local_date, timezone_name, revision)
      REFERENCES havre.daily_diary_entry_revisions(owner_id, local_date, timezone_name, revision),
    FOREIGN KEY (owner_id, event_id)
      REFERENCES havre.events(owner_id, event_id) ON DELETE CASCADE
);
CREATE INDEX daily_diary_entry_sources_event_idx
  ON havre.daily_diary_entry_sources(owner_id, event_id);

CREATE FUNCTION havre.guard_daily_diary_source() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE source_event havre.events%ROWTYPE;
BEGIN
  SELECT * INTO STRICT source_event FROM havre.events
  WHERE owner_id=NEW.owner_id AND event_id=NEW.event_id;
  IF source_event.event_type NOT IN ('USER_MESSAGE','ASSISTANT_MESSAGE')
     OR source_event.content_hash<>NEW.event_content_hash
     OR (source_event.recorded_at AT TIME ZONE NEW.timezone_name)::date<>NEW.local_date THEN
    RAISE EXCEPTION 'daily diary source must match exact owner-local message Event'
      USING ERRCODE='55000';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER guard_daily_diary_source
BEFORE INSERT ON havre.daily_diary_entry_sources
FOR EACH ROW EXECUTE FUNCTION havre.guard_daily_diary_source();

CREATE TRIGGER daily_diary_entry_revisions_immutable
BEFORE UPDATE OR DELETE ON havre.daily_diary_entry_revisions
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();
CREATE TRIGGER daily_diary_entry_sources_immutable
BEFORE UPDATE OR DELETE ON havre.daily_diary_entry_sources
FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();

-- Re-enabling a previously disabled owner-approved Stage 12A source is a new
-- source-state revision, not a second calendar subsystem or source record.
ALTER TABLE havre.context_source_state_revisions
  DROP CONSTRAINT context_source_state_revisions_reason_check;
ALTER TABLE havre.context_source_state_revisions
  ADD CONSTRAINT context_source_state_revisions_reason_check CHECK (
    reason IN ('registered','owner_enabled','owner_disabled','lost_device','key_rotated')
  );
