-- Stage 4 required-provenance and derived-record integrity correction.
--
-- This migration is intentionally additive. Migrations 0001-0011 are an
-- immutable historical snapshot and may already be installed. Stage 5 and
-- proactive runtime remain inactive.

CREATE FUNCTION havre.stage4_evidence_snapshot_is_exact(snapshot jsonb)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
STRICT
AS $$
    SELECT
        jsonb_typeof(snapshot) = 'array'
        AND jsonb_array_length(snapshot) > 0
        AND NOT EXISTS (
            SELECT 1
            FROM jsonb_array_elements(snapshot) AS evidence(item)
            WHERE jsonb_typeof(item) <> 'object'
               OR ARRAY(
                    SELECT key
                    FROM jsonb_object_keys(item) AS keys(key)
                    ORDER BY key
                  ) IS DISTINCT FROM ARRAY[
                    'relation', 'source_id', 'source_kind',
                    'source_revision', 'weight'
                  ]::text[]
               OR jsonb_typeof(item->'source_kind') <> 'string'
               OR item->>'source_kind' NOT IN (
                    'event', 'memory_revision', 'belief_revision'
                  )
               OR jsonb_typeof(item->'source_id') <> 'string'
               OR item->>'source_id' !~* (
                    '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-' ||
                    '[0-9a-f]{4}-[0-9a-f]{12}$'
                  )
               OR jsonb_typeof(item->'relation') <> 'string'
               OR item->>'relation' NOT IN ('supports', 'contradicts')
               OR (
                    item->>'source_kind' = 'event'
                    AND item->'source_revision' <> 'null'::jsonb
                  )
               OR (
                    item->>'source_kind' IN (
                        'memory_revision', 'belief_revision'
                    )
                    AND (
                        jsonb_typeof(item->'source_revision') <> 'number'
                        OR (item->'source_revision')::text !~ '^[1-9][0-9]*$'
                    )
                  )
               OR (
                    item->'weight' <> 'null'::jsonb
                    AND (
                        jsonb_typeof(item->'weight') <> 'number'
                        OR (item->>'weight')::numeric < 0
                        OR (item->>'weight')::numeric > 1
                    )
                  )
        )
        AND EXISTS (
            SELECT 1
            FROM jsonb_array_elements(snapshot) AS evidence(item)
            WHERE item->>'relation' = 'supports'
        )
        AND (
            SELECT count(*)
            FROM jsonb_array_elements(snapshot)
        ) = (
            SELECT count(*)
            FROM (
                SELECT DISTINCT
                    item->>'source_kind', item->>'source_id',
                    item->>'source_revision'
                FROM jsonb_array_elements(snapshot) AS evidence(item)
            ) AS identities
        )
$$;

CREATE FUNCTION havre.stage4_snapshot_provenance_matches(
    checked_owner_id uuid,
    checked_derived_kind text,
    checked_derived_id uuid,
    checked_snapshot jsonb
) RETURNS boolean
LANGUAGE sql
STABLE
STRICT
AS $$
    SELECT
        havre.stage4_evidence_snapshot_is_exact(checked_snapshot)
        AND NOT EXISTS (
            SELECT 1
            FROM jsonb_array_elements(checked_snapshot) AS evidence(item)
            WHERE NOT EXISTS (
                SELECT 1
                FROM havre.provenance_edges AS edge
                WHERE edge.owner_id = checked_owner_id
                  AND edge.derived_kind = checked_derived_kind
                  AND edge.derived_id = checked_derived_id
                  AND edge.derived_revision IS NULL
                  AND edge.source_kind = item->>'source_kind'
                  AND edge.source_id = (item->>'source_id')::uuid
                  AND edge.source_revision IS NOT DISTINCT FROM
                        (item->>'source_revision')::integer
                  AND edge.relation = item->>'relation'
                  AND edge.weight IS NOT DISTINCT FROM
                        (item->>'weight')::numeric
            )
        )
        AND (
            SELECT count(*)
            FROM havre.provenance_edges AS edge
            WHERE edge.owner_id = checked_owner_id
              AND edge.derived_kind = checked_derived_kind
              AND edge.derived_id = checked_derived_id
              AND edge.derived_revision IS NULL
              AND edge.relation IN ('supports', 'contradicts')
        ) = jsonb_array_length(checked_snapshot)
$$;

CREATE FUNCTION havre.canonical_stage4_timestamp(value timestamptz)
RETURNS text
LANGUAGE sql
IMMUTABLE
STRICT
AS $$
    SELECT to_json(
        to_char(value AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS') ||
        CASE
            WHEN to_char(value AT TIME ZONE 'UTC', 'US') = '000000' THEN ''
            ELSE '.' || to_char(value AT TIME ZONE 'UTC', 'US')
        END || 'Z'
    )::text
$$;

CREATE FUNCTION havre.canonical_goal_progress(
    progress_row havre.goal_progress_records
) RETURNS text
LANGUAGE plpgsql
STABLE
STRICT
AS $$
DECLARE
    evidence_canonical text;
BEGIN
    SELECT '[' || string_agg(
        '{"relation":' || to_json(item->>'relation')::text ||
        ',"source_id":' || to_json(item->>'source_id')::text ||
        ',"source_kind":' || to_json(item->>'source_kind')::text ||
        ',"source_revision":' || (item->'source_revision')::text ||
        ',"weight":' || (item->'weight')::text || '}',
        ',' ORDER BY ordinal
    ) || ']'
    INTO evidence_canonical
    FROM jsonb_array_elements(progress_row.evidence_snapshot)
         WITH ORDINALITY AS evidence(item, ordinal);

    RETURN
        '{"created_event_id":' ||
            to_json(progress_row.created_event_id::text)::text ||
        ',"data_policy":{' ||
        '"authorization_ref":' ||
            COALESCE(to_json(progress_row.policy_authorization_ref)::text, 'null') ||
        ',"cloud_eligible":' || progress_row.cloud_eligible::text ||
        ',"decision_source":' ||
            to_json(progress_row.policy_decision_source)::text ||
        ',"memory_eligible":' || progress_row.memory_eligible::text ||
        ',"policy_revision_id":' ||
            to_json(progress_row.policy_revision_id::text)::text ||
        ',"policy_version":' || to_json(progress_row.policy_version)::text ||
        ',"privacy_class":' || to_json(progress_row.privacy_class)::text ||
        ',"schema_version":1' ||
        ',"training_eligible":' || progress_row.training_eligible::text ||
        '},"direction":' || to_json(progress_row.direction)::text ||
        ',"evidence":' || evidence_canonical ||
        ',"goal_id":' || to_json(progress_row.goal_id::text)::text ||
        ',"goal_revision":' || progress_row.goal_revision::text ||
        ',"observed_at":' ||
            havre.canonical_stage4_timestamp(progress_row.observed_at) ||
        ',"owner_id":' || to_json(progress_row.owner_id::text)::text ||
        ',"progress_record_id":' ||
            to_json(progress_row.progress_record_id::text)::text ||
        ',"schema_version":' || progress_row.schema_version::text ||
        ',"summary":' || to_json(progress_row.summary)::text ||
        ',"trace_id":' || to_json(trim(progress_row.trace_id))::text ||
        '}' ;
END;
$$;

CREATE FUNCTION havre.guard_belief_revision_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    lifecycle_event record;
BEGIN
    IF NEW.revision = 1 THEN
        IF NEW.initial_status <> 'candidate'
           OR NEW.supersedes_revision IS NOT NULL THEN
            RAISE EXCEPTION
                'belief revision insert guard: revision 1 must be a candidate'
                USING ERRCODE = '55000';
        END IF;
    ELSE
        IF NEW.initial_status <> 'active'
           OR NEW.supersedes_revision <> NEW.revision - 1
           OR NOT EXISTS (
                SELECT 1
                FROM havre.user_belief_revisions AS previous
                WHERE previous.owner_id = NEW.owner_id
                  AND previous.belief_id = NEW.belief_id
                  AND previous.revision = NEW.revision - 1
                  AND previous.belief_key = NEW.belief_key
                  AND previous.belief_type = NEW.belief_type
           ) THEN
            RAISE EXCEPTION
                'belief revision insert guard: revision must exactly follow its prior identity'
                USING ERRCODE = '55000';
        END IF;
    END IF;

    BEGIN
        SELECT event.* INTO lifecycle_event
        FROM havre.events AS event
        WHERE event.owner_id = NEW.owner_id
          AND event.event_id = NEW.created_event_id
          AND event.event_type = CASE
                WHEN NEW.revision = 1 THEN 'USER_BELIEF_CREATED'
                ELSE 'USER_BELIEF_REVISED'
              END
          AND event.trace_id = NEW.trace_id
          AND event.payload->>'belief_id' = NEW.belief_id::text
          AND event.payload->>'belief_revision' = NEW.revision::text
          AND event.payload->>'action' = CASE
                WHEN NEW.revision = 1 THEN 'created' ELSE 'revised'
              END
          AND event.payload->>'previous_revision' IS NOT DISTINCT FROM
                CASE
                    WHEN NEW.revision = 1 THEN NULL
                    ELSE (NEW.revision - 1)::text
                END
          AND event.privacy_class = NEW.privacy_class
          AND event.memory_eligible = NEW.memory_eligible
          AND event.training_eligible = NEW.training_eligible
          AND event.cloud_eligible = NEW.cloud_eligible
          AND event.policy_version = NEW.policy_version
          AND event.policy_revision_id = NEW.policy_revision_id
          AND event.policy_decision_source = NEW.policy_decision_source
          AND event.policy_authorization_ref
                IS NOT DISTINCT FROM NEW.policy_authorization_ref
          AND (
                (
                    NEW.revision = 1
                    AND event.causation_event_id IS NOT NULL
                    AND EXISTS (
                        SELECT 1 FROM havre.events AS source_event
                        WHERE source_event.owner_id = NEW.owner_id
                          AND source_event.event_id = event.causation_event_id
                    )
                )
                OR (
                    NEW.revision > 1
                    AND event.causation_event_id = (
                        SELECT previous.created_event_id
                        FROM havre.user_belief_revisions AS previous
                        WHERE previous.owner_id = NEW.owner_id
                          AND previous.belief_id = NEW.belief_id
                          AND previous.revision = NEW.revision - 1
                    )
                )
          );
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION
            'belief revision insert guard: lifecycle event payload is invalid'
            USING ERRCODE = '55000';
    END;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'belief revision insert guard: insert lacks one exact immutable lifecycle event'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER user_belief_revisions_are_insert_guarded
BEFORE INSERT ON havre.user_belief_revisions
FOR EACH ROW EXECUTE FUNCTION havre.guard_belief_revision_insert();

CREATE FUNCTION havre.guard_belief_head_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.current_revision <> 1 OR NEW.status <> 'candidate'
       OR NOT EXISTS (
            SELECT 1
            FROM havre.user_belief_revisions AS revision
            WHERE revision.owner_id = NEW.owner_id
              AND revision.belief_id = NEW.belief_id
              AND revision.revision = 1
              AND revision.belief_key = NEW.belief_key
              AND revision.initial_status = 'candidate'
       ) THEN
        RAISE EXCEPTION
            'belief head insert guard: initial head must exactly project candidate revision 1'
            USING ERRCODE = '55000';
    END IF;
    NEW.updated_at := statement_timestamp();
    RETURN NEW;
END;
$$;

CREATE TRIGGER belief_heads_are_insert_guarded
BEFORE INSERT ON havre.belief_heads
FOR EACH ROW EXECUTE FUNCTION havre.guard_belief_head_insert();

CREATE FUNCTION havre.guard_goal_progress_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    expected_hash text;
BEGIN
    IF NOT havre.stage4_evidence_snapshot_is_exact(NEW.evidence_snapshot) THEN
        RAISE EXCEPTION
            'goal progress insert guard: evidence snapshot violates the exact contract'
            USING ERRCODE = '55000';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM havre.goals AS goal
        WHERE goal.owner_id = NEW.owner_id
          AND goal.goal_id = NEW.goal_id
          AND goal.revision = NEW.goal_revision
    ) THEN
        RAISE EXCEPTION
            'goal progress insert guard: goal revision is not the current durable projection'
            USING ERRCODE = '55000';
    END IF;

    BEGIN
        PERFORM 1
        FROM havre.events AS event
        WHERE event.owner_id = NEW.owner_id
          AND event.event_id = NEW.created_event_id
          AND event.event_type = 'PROGRESS_RECORDED'
          AND event.trace_id = NEW.trace_id
          AND event.causation_event_id IS NOT NULL
          AND EXISTS (
                SELECT 1 FROM havre.events AS source_event
                WHERE source_event.owner_id = NEW.owner_id
                  AND source_event.event_id = event.causation_event_id
          )
          AND event.payload->>'progress_record_id' =
                NEW.progress_record_id::text
          AND event.payload->>'goal_id' = NEW.goal_id::text
          AND event.payload->>'goal_revision' = NEW.goal_revision::text
          AND event.payload->>'direction' = NEW.direction
          AND (event.payload->>'observed_at')::timestamptz = NEW.observed_at
          AND event.privacy_class = NEW.privacy_class
          AND event.memory_eligible = NEW.memory_eligible
          AND event.training_eligible = NEW.training_eligible
          AND event.cloud_eligible = NEW.cloud_eligible
          AND event.policy_version = NEW.policy_version
          AND event.policy_revision_id = NEW.policy_revision_id
          AND event.policy_decision_source = NEW.policy_decision_source
          AND event.policy_authorization_ref
                IS NOT DISTINCT FROM NEW.policy_authorization_ref;
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION
            'goal progress insert guard: lifecycle event payload is invalid'
            USING ERRCODE = '55000';
    END;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'goal progress insert guard: insert lacks one exact immutable PROGRESS_RECORDED event'
            USING ERRCODE = '55000';
    END IF;

    NEW.created_at := statement_timestamp();
    expected_hash := 'sha256:' || encode(
        sha256(convert_to(havre.canonical_goal_progress(NEW), 'UTF8')), 'hex'
    );
    IF NEW.content_hash IS DISTINCT FROM expected_hash THEN
        RAISE EXCEPTION
            'goal progress insert guard: content hash is not bound to the full record'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER goal_progress_records_are_insert_guarded
BEFORE INSERT ON havre.goal_progress_records
FOR EACH ROW EXECUTE FUNCTION havre.guard_goal_progress_insert();

CREATE FUNCTION havre.require_belief_revision_support() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM havre.provenance_edges AS edge
        WHERE edge.owner_id = NEW.owner_id
          AND edge.derived_kind = 'belief_revision'
          AND edge.derived_id = NEW.belief_id
          AND edge.derived_revision = NEW.revision
          AND edge.relation = 'supports'
    ) THEN
        RAISE EXCEPTION
            'belief revision requires at least one owner-qualified supporting provenance edge'
            USING ERRCODE = '55000';
    END IF;
    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER user_belief_revisions_require_support
AFTER INSERT ON havre.user_belief_revisions
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION havre.require_belief_revision_support();

CREATE FUNCTION havre.require_stage4_snapshot_provenance() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    derived_kind text;
    derived_id uuid;
    snapshot jsonb;
BEGIN
    IF TG_TABLE_NAME = 'consolidation_proposals' THEN
        derived_kind := 'consolidation_proposal';
        derived_id := NEW.proposal_id;
    ELSIF TG_TABLE_NAME = 'current_state_snapshots' THEN
        derived_kind := 'current_state_snapshot';
        derived_id := NEW.state_snapshot_id;
    ELSIF TG_TABLE_NAME = 'goal_progress_records' THEN
        derived_kind := 'goal_progress_record';
        derived_id := NEW.progress_record_id;
    ELSE
        RAISE EXCEPTION 'unsupported Stage 4 required-provenance table';
    END IF;
    snapshot := to_jsonb(NEW)->'evidence_snapshot';

    IF NOT havre.stage4_snapshot_provenance_matches(
        NEW.owner_id, derived_kind, derived_id, snapshot
    ) THEN
        RAISE EXCEPTION
            '% requires exact owner-qualified snapshot provenance', derived_kind
            USING ERRCODE = '55000';
    END IF;
    IF TG_TABLE_NAME = 'consolidation_proposals'
       AND to_jsonb(NEW)->>'memory_class' IN ('pattern', 'progress')
       AND (
            SELECT count(DISTINCT (
                item->>'source_kind', item->>'source_id',
                item->>'source_revision'
            ))
            FROM jsonb_array_elements(snapshot) AS evidence(item)
            WHERE item->>'relation' = 'supports'
       ) < 2 THEN
        RAISE EXCEPTION
            'pattern and progress proposals require two supporting sources'
            USING ERRCODE = '55000';
    END IF;
    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER consolidation_proposals_require_provenance
AFTER INSERT ON havre.consolidation_proposals
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION havre.require_stage4_snapshot_provenance();

CREATE CONSTRAINT TRIGGER current_state_snapshots_require_provenance
AFTER INSERT ON havre.current_state_snapshots
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION havre.require_stage4_snapshot_provenance();

CREATE CONSTRAINT TRIGGER goal_progress_records_require_provenance
AFTER INSERT ON havre.goal_progress_records
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION havre.require_stage4_snapshot_provenance();

-- Fail an in-place upgrade closed if historical Stage 4 rows do not satisfy
-- the newly durable requirement. The owner must repair explicit provenance;
-- the migration never invents evidence.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM havre.user_belief_revisions AS revision
        WHERE NOT EXISTS (
            SELECT 1 FROM havre.provenance_edges AS edge
            WHERE edge.owner_id = revision.owner_id
              AND edge.derived_kind = 'belief_revision'
              AND edge.derived_id = revision.belief_id
              AND edge.derived_revision = revision.revision
              AND edge.relation = 'supports'
        )
    ) OR EXISTS (
        SELECT 1 FROM havre.consolidation_proposals AS proposal
        WHERE NOT havre.stage4_snapshot_provenance_matches(
            proposal.owner_id, 'consolidation_proposal', proposal.proposal_id,
            proposal.evidence_snapshot
        )
    ) OR EXISTS (
        SELECT 1 FROM havre.current_state_snapshots AS snapshot
        WHERE NOT havre.stage4_snapshot_provenance_matches(
            snapshot.owner_id, 'current_state_snapshot',
            snapshot.state_snapshot_id, snapshot.evidence_snapshot
        )
    ) OR EXISTS (
        SELECT 1 FROM havre.goal_progress_records AS progress
        WHERE NOT havre.stage4_snapshot_provenance_matches(
            progress.owner_id, 'goal_progress_record',
            progress.progress_record_id, progress.evidence_snapshot
        )
    ) THEN
        RAISE EXCEPTION
            'migration 0012 refuses Stage 4 rows with missing or mismatched required provenance';
    END IF;
END;
$$;

CREATE VIEW havre.stage4_required_provenance_violations AS
SELECT
    revision.belief_id AS provenance_edge_id,
    revision.owner_id,
    'required_provenance'::text AS source_kind,
    revision.belief_id AS source_id,
    revision.revision AS source_revision,
    'missing_required_belief_support'::text AS violation_code
FROM havre.user_belief_revisions AS revision
WHERE NOT EXISTS (
    SELECT 1 FROM havre.provenance_edges AS edge
    WHERE edge.owner_id = revision.owner_id
      AND edge.derived_kind = 'belief_revision'
      AND edge.derived_id = revision.belief_id
      AND edge.derived_revision = revision.revision
      AND edge.relation = 'supports'
)
UNION ALL
SELECT
    proposal.proposal_id, proposal.owner_id, 'required_provenance',
    proposal.proposal_id, NULL::integer,
    'missing_or_mismatched_proposal_provenance'
FROM havre.consolidation_proposals AS proposal
WHERE NOT havre.stage4_snapshot_provenance_matches(
    proposal.owner_id, 'consolidation_proposal', proposal.proposal_id,
    proposal.evidence_snapshot
)
UNION ALL
SELECT
    snapshot.state_snapshot_id, snapshot.owner_id, 'required_provenance',
    snapshot.state_snapshot_id, NULL::integer,
    'missing_or_mismatched_state_provenance'
FROM havre.current_state_snapshots AS snapshot
WHERE NOT havre.stage4_snapshot_provenance_matches(
    snapshot.owner_id, 'current_state_snapshot', snapshot.state_snapshot_id,
    snapshot.evidence_snapshot
)
UNION ALL
SELECT
    progress.progress_record_id, progress.owner_id, 'required_provenance',
    progress.progress_record_id, NULL::integer,
    'missing_or_mismatched_progress_provenance'
FROM havre.goal_progress_records AS progress
WHERE NOT havre.stage4_snapshot_provenance_matches(
    progress.owner_id, 'goal_progress_record', progress.progress_record_id,
    progress.evidence_snapshot
);
