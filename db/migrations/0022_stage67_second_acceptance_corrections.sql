-- Stage 6/7 second acceptance corrections: authoritative proactive preference
-- heads and source-serialized offline evidence admission.

CREATE TABLE havre.proactive_preference_heads (
    owner_id uuid PRIMARY KEY REFERENCES havre.owners(owner_id),
    preference_revision_id uuid NOT NULL,
    revision integer NOT NULL CHECK (revision > 0),
    updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (owner_id, preference_revision_id),
    UNIQUE (owner_id, revision),
    FOREIGN KEY (owner_id, preference_revision_id)
        REFERENCES havre.proactive_preference_revisions(owner_id, preference_revision_id)
);

INSERT INTO havre.proactive_preference_heads (
    owner_id, preference_revision_id, revision, updated_at
)
SELECT DISTINCT ON (owner_id)
       owner_id, preference_revision_id, revision, statement_timestamp()
FROM havre.proactive_preference_revisions
ORDER BY owner_id, revision DESC, preference_revision_id DESC;

CREATE OR REPLACE FUNCTION havre.guard_proactive_preference_head()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    stored_revision integer;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'proactive preference head cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    IF TG_OP = 'UPDATE' AND NEW.owner_id <> OLD.owner_id THEN
        RAISE EXCEPTION 'proactive preference head owner is immutable'
            USING ERRCODE = '55000';
    END IF;

    SELECT revision INTO stored_revision
    FROM havre.proactive_preference_revisions
    WHERE owner_id = NEW.owner_id
      AND preference_revision_id = NEW.preference_revision_id;
    IF NOT FOUND OR stored_revision <> NEW.revision THEN
        RAISE EXCEPTION 'proactive preference head must match an exact stored revision'
            USING ERRCODE = '55000';
    END IF;
    IF TG_OP = 'UPDATE' AND NEW.revision <= OLD.revision THEN
        RAISE EXCEPTION 'proactive preference head must advance monotonically'
            USING ERRCODE = '55000';
    END IF;
    NEW.updated_at := statement_timestamp();
    RETURN NEW;
END
$$;
CREATE TRIGGER proactive_preference_heads_guard
    BEFORE INSERT OR UPDATE OR DELETE ON havre.proactive_preference_heads
    FOR EACH ROW EXECUTE FUNCTION havre.guard_proactive_preference_head();

CREATE OR REPLACE FUNCTION havre.reject_revoked_offline_source()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(
        hashtextextended('offline-owner:' || NEW.owner_id::text, 0)
    );
    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'offline-source:' || NEW.owner_id::text || ':' || NEW.source_event_id::text,
            0
        )
    );
    IF EXISTS (
        SELECT 1 FROM havre.offline_source_revocations AS revoked
        WHERE revoked.owner_id = NEW.owner_id
          AND revoked.source_event_id = NEW.source_event_id
    ) THEN
        RAISE EXCEPTION 'revoked offline source cannot be reused'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END
$$;
