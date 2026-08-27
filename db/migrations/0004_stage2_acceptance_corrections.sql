-- Stage 2 acceptance corrections. This migration is intentionally additive:
-- 0003 may already be present in owner databases and must remain immutable.

-- Turn the polymorphic provenance source into owner-qualified foreign keys.
-- Generated columns retain the public source_kind/source_id contract while
-- allowing PostgreSQL to enforce the appropriate source relation.
ALTER TABLE havre.provenance_edges
    ADD COLUMN source_event_id uuid GENERATED ALWAYS AS (
        CASE WHEN source_kind = 'event' THEN source_id ELSE NULL END
    ) STORED,
    ADD COLUMN source_memory_id uuid GENERATED ALWAYS AS (
        CASE WHEN source_kind = 'memory_revision' THEN source_id ELSE NULL END
    ) STORED,
    ADD COLUMN source_memory_revision integer GENERATED ALWAYS AS (
        CASE WHEN source_kind = 'memory_revision' THEN source_revision ELSE NULL END
    ) STORED;

ALTER TABLE havre.provenance_edges
    ADD CONSTRAINT provenance_edges_owner_source_event_fk
        FOREIGN KEY (owner_id, source_event_id)
        REFERENCES havre.events(owner_id, event_id),
    ADD CONSTRAINT provenance_edges_owner_source_memory_fk
        FOREIGN KEY (owner_id, source_memory_id, source_memory_revision)
        REFERENCES havre.memory_revisions(owner_id, memory_id, revision);

CREATE INDEX provenance_edges_owner_source_event_fk_idx
    ON havre.provenance_edges(owner_id, source_event_id)
    WHERE source_event_id IS NOT NULL;
CREATE INDEX provenance_edges_owner_source_memory_fk_idx
    ON havre.provenance_edges(owner_id, source_memory_id, source_memory_revision)
    WHERE source_memory_id IS NOT NULL;

-- A queryable integrity surface supports scheduled audits and detects damage
-- caused by privileged/manual constraint bypasses. Under normal writes it is
-- empty because the foreign keys above reject invalid sources synchronously.
CREATE VIEW havre.provenance_integrity_violations AS
SELECT
    edge.provenance_edge_id,
    edge.owner_id,
    edge.source_kind,
    edge.source_id,
    edge.source_revision,
    CASE
        WHEN edge.source_kind = 'event' AND source_event.event_id IS NULL
            THEN 'missing_or_cross_owner_event_source'
        WHEN edge.source_kind = 'memory_revision' AND source_memory.memory_id IS NULL
            THEN 'missing_or_cross_owner_memory_source'
    END AS violation_code
FROM havre.provenance_edges AS edge
LEFT JOIN havre.events AS source_event
  ON edge.source_kind = 'event'
 AND source_event.owner_id = edge.owner_id
 AND source_event.event_id = edge.source_id
LEFT JOIN havre.memory_revisions AS source_memory
  ON edge.source_kind = 'memory_revision'
 AND source_memory.owner_id = edge.owner_id
 AND source_memory.memory_id = edge.source_id
 AND source_memory.revision = edge.source_revision
WHERE (edge.source_kind = 'event' AND source_event.event_id IS NULL)
   OR (edge.source_kind = 'memory_revision' AND source_memory.memory_id IS NULL);

-- Immutable records remain protected for ordinary code. The erasure service
-- uses a transaction-local flag so it does not disable triggers for concurrent
-- sessions while closing a privacy-deletion lineage.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'havre_privileged_erasure') THEN
        CREATE ROLE havre_privileged_erasure NOLOGIN;
    END IF;
END
$$;

GRANT havre_privileged_erasure TO CURRENT_USER;

CREATE OR REPLACE FUNCTION havre.reject_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF current_setting('havre.privileged_erasure', true) = 'on'
       AND pg_has_role(current_user, 'havre_privileged_erasure', 'MEMBER') THEN
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END IF;
    RAISE EXCEPTION '% is immutable; append a new record or use the privileged erasure path', TG_TABLE_NAME
        USING ERRCODE = '55000';
END;
$$;

CREATE FUNCTION havre.guard_memory_candidate_review() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF current_setting('havre.privileged_erasure', true) = 'on'
       AND pg_has_role(current_user, 'havre_privileged_erasure', 'MEMBER') THEN
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END IF;

    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'memory_candidates is immutable outside the privileged erasure path'
            USING ERRCODE = '55000';
    END IF;

    IF OLD.status <> 'pending' THEN
        RAISE EXCEPTION 'reviewed memory candidate % is immutable', OLD.candidate_id
            USING ERRCODE = '55000';
    END IF;
    IF NEW.status NOT IN ('accepted', 'rejected', 'duplicate')
       OR NEW.reviewed_by IS NULL
       OR NEW.reviewed_at IS NULL
       OR NEW.review_reason IS NULL THEN
        RAISE EXCEPTION 'candidate update must be a complete owner review transition'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.reviewed_by <> 'owner' THEN
        RAISE EXCEPTION 'only the owner may review a Stage 2 memory candidate'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.status <> 'accepted'
       AND (NEW.importance IS DISTINCT FROM OLD.importance
            OR NEW.importance_policy_version IS DISTINCT FROM OLD.importance_policy_version) THEN
        RAISE EXCEPTION 'importance may change only during owner acceptance'
            USING ERRCODE = '55000';
    END IF;
    IF (to_jsonb(NEW) - ARRAY[
            'status', 'reviewed_by', 'reviewed_at', 'review_reason',
            'importance', 'importance_policy_version'
        ]) IS DISTINCT FROM
       (to_jsonb(OLD) - ARRAY[
            'status', 'reviewed_by', 'reviewed_at', 'review_reason',
            'importance', 'importance_policy_version'
        ]) THEN
        RAISE EXCEPTION 'candidate content and provenance cannot change during review'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER memory_candidates_are_immutable_after_review
    ON havre.memory_candidates;
CREATE TRIGGER memory_candidates_are_immutable_after_review
BEFORE UPDATE OR DELETE ON havre.memory_candidates
FOR EACH ROW EXECUTE FUNCTION havre.guard_memory_candidate_review();

-- Persist the selection safety policy and exclusions beside every new result.
-- Existing rows are explicitly marked as legacy and remain inspectable.
ALTER TABLE havre.retrieval_results
    ADD COLUMN selection_policy_version text NOT NULL
        DEFAULT 'retrieval-selection-legacy-ungated-v1',
    ADD COLUMN minimum_semantic_similarity numeric(6,5) NULL
        CHECK (minimum_semantic_similarity BETWEEN -1 AND 1),
    ADD COLUMN duplicate_similarity_threshold numeric(6,5) NULL
        CHECK (duplicate_similarity_threshold BETWEEN -1 AND 1),
    ADD COLUMN duplicate_token_overlap_threshold numeric(6,5) NULL
        CHECK (duplicate_token_overlap_threshold BETWEEN 0 AND 1),
    ADD COLUMN exclusions jsonb NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(exclusions) = 'array');

ALTER TABLE havre.retrieval_results
    ADD CONSTRAINT retrieval_results_selection_policy_check CHECK (
        (
            selection_policy_version = 'retrieval-selection-legacy-ungated-v1'
            AND minimum_semantic_similarity IS NULL
            AND duplicate_similarity_threshold IS NULL
            AND duplicate_token_overlap_threshold IS NULL
        )
        OR (
            selection_policy_version = 'retrieval-selection-context-safe-v1'
            AND minimum_semantic_similarity IS NOT NULL
            AND duplicate_similarity_threshold IS NOT NULL
            AND duplicate_token_overlap_threshold IS NOT NULL
        )
    );

ALTER TABLE havre.retrieval_results
    ALTER COLUMN selection_policy_version DROP DEFAULT,
    ALTER COLUMN exclusions DROP DEFAULT;
