ALTER TABLE havre.interaction_requests
    ADD COLUMN request_fingerprint text;

UPDATE havre.interaction_requests
SET request_fingerprint = 'legacy:' || request_id::text
WHERE request_fingerprint IS NULL;

ALTER TABLE havre.interaction_requests
    ALTER COLUMN request_fingerprint SET NOT NULL,
    ADD CONSTRAINT interaction_requests_request_fingerprint_format_check
    CHECK (
        request_fingerprint ~ '^sha256:[0-9a-f]{64}$'
        OR request_fingerprint ~ '^legacy:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    );

-- Identity version names are stable inside an owner boundary, not globally.
ALTER TABLE havre.context_packs
    DROP CONSTRAINT context_packs_constitution_version_id_fkey,
    DROP CONSTRAINT context_packs_identity_version_id_fkey,
    DROP CONSTRAINT context_packs_values_version_id_fkey;

ALTER TABLE havre.identity_artifact_versions
    DROP CONSTRAINT identity_artifact_versions_approval_id_fkey,
    DROP CONSTRAINT identity_artifact_versions_pkey;

ALTER TABLE havre.approval_records
    ADD CONSTRAINT approval_records_owner_approval_key
    UNIQUE (owner_id, approval_id);

ALTER TABLE havre.identity_artifact_versions
    ADD CONSTRAINT identity_artifact_versions_pkey
        PRIMARY KEY (owner_id, artifact_version_id),
    ADD CONSTRAINT identity_artifact_versions_owner_approval_fk
        FOREIGN KEY (owner_id, approval_id)
        REFERENCES havre.approval_records(owner_id, approval_id);

-- Legacy Stage 1 databases may have owner-scoped approvals but only the first
-- owner's globally keyed identity row. Recreate the exact approved artifact for
-- each owner from matching version/kind/hash provenance before enforcing the new
-- owner-qualified Context Pack references.
INSERT INTO havre.identity_artifact_versions (
    artifact_version_id,
    owner_id,
    artifact_kind,
    schema_version,
    content,
    content_hash,
    approval_id,
    source_files,
    created_at
)
SELECT
    source_artifact.artifact_version_id,
    owner_approval.owner_id,
    source_artifact.artifact_kind,
    source_artifact.schema_version,
    source_artifact.content,
    source_artifact.content_hash,
    owner_approval.approval_id,
    source_artifact.source_files,
    owner_approval.created_at
FROM havre.approval_records AS owner_approval
JOIN havre.identity_artifact_versions AS source_artifact
  ON source_artifact.artifact_kind = owner_approval.artifact_kind
 AND source_artifact.artifact_version_id = owner_approval.artifact_version_id
 AND source_artifact.content_hash = owner_approval.artifact_content_hash
WHERE owner_approval.artifact_kind IN ('constitution', 'identity', 'values')
ON CONFLICT (owner_id, artifact_version_id) DO NOTHING;

DROP INDEX havre.identity_artifact_versions_owner_id_idx;
DROP INDEX havre.identity_artifact_versions_approval_id_idx;
CREATE INDEX identity_artifact_versions_owner_approval_id_idx
    ON havre.identity_artifact_versions(owner_id, approval_id);

-- Add owner-qualified candidate keys used by all personal-artifact references.
ALTER TABLE havre.traces
    ADD CONSTRAINT traces_owner_trace_key UNIQUE (owner_id, trace_id);
ALTER TABLE havre.interaction_requests
    ADD CONSTRAINT interaction_requests_owner_request_key UNIQUE (owner_id, request_id);
ALTER TABLE havre.events
    ADD CONSTRAINT events_owner_event_key UNIQUE (owner_id, event_id);
ALTER TABLE havre.context_packs
    ADD CONSTRAINT context_packs_owner_context_pack_key UNIQUE (owner_id, context_pack_id);
ALTER TABLE havre.route_decisions
    ADD CONSTRAINT route_decisions_owner_route_key UNIQUE (owner_id, route_decision_id);
ALTER TABLE havre.inference_attempts
    ADD CONSTRAINT inference_attempts_owner_response_key UNIQUE (owner_id, inference_response_id);

-- Replace globally keyed personal-artifact references with owner-qualified FKs.
ALTER TABLE havre.interaction_requests
    DROP CONSTRAINT interaction_requests_trace_id_fkey,
    DROP CONSTRAINT interaction_requests_user_event_fk,
    DROP CONSTRAINT interaction_requests_assistant_event_fk,
    DROP CONSTRAINT interaction_requests_context_pack_fk,
    DROP CONSTRAINT interaction_requests_inference_response_fk,
    ADD CONSTRAINT interaction_requests_owner_trace_fk
        FOREIGN KEY (owner_id, trace_id) REFERENCES havre.traces(owner_id, trace_id),
    ADD CONSTRAINT interaction_requests_owner_user_event_fk
        FOREIGN KEY (owner_id, user_event_id) REFERENCES havre.events(owner_id, event_id),
    ADD CONSTRAINT interaction_requests_owner_assistant_event_fk
        FOREIGN KEY (owner_id, assistant_event_id) REFERENCES havre.events(owner_id, event_id),
    ADD CONSTRAINT interaction_requests_owner_context_pack_fk
        FOREIGN KEY (owner_id, context_pack_id)
        REFERENCES havre.context_packs(owner_id, context_pack_id),
    ADD CONSTRAINT interaction_requests_owner_inference_response_fk
        FOREIGN KEY (owner_id, inference_response_id)
        REFERENCES havre.inference_attempts(owner_id, inference_response_id);

ALTER TABLE havre.events
    DROP CONSTRAINT events_request_id_fkey,
    DROP CONSTRAINT events_trace_id_fkey,
    DROP CONSTRAINT events_causation_event_id_fkey,
    ADD CONSTRAINT events_owner_request_fk
        FOREIGN KEY (owner_id, request_id)
        REFERENCES havre.interaction_requests(owner_id, request_id),
    ADD CONSTRAINT events_owner_trace_fk
        FOREIGN KEY (owner_id, trace_id) REFERENCES havre.traces(owner_id, trace_id),
    ADD CONSTRAINT events_owner_causation_event_fk
        FOREIGN KEY (owner_id, causation_event_id) REFERENCES havre.events(owner_id, event_id);

ALTER TABLE havre.context_packs
    DROP CONSTRAINT context_packs_request_id_fkey,
    DROP CONSTRAINT context_packs_trace_id_fkey,
    ADD CONSTRAINT context_packs_owner_request_fk
        FOREIGN KEY (owner_id, request_id)
        REFERENCES havre.interaction_requests(owner_id, request_id),
    ADD CONSTRAINT context_packs_owner_trace_fk
        FOREIGN KEY (owner_id, trace_id) REFERENCES havre.traces(owner_id, trace_id),
    ADD CONSTRAINT context_packs_owner_constitution_fk
        FOREIGN KEY (owner_id, constitution_version_id)
        REFERENCES havre.identity_artifact_versions(owner_id, artifact_version_id),
    ADD CONSTRAINT context_packs_owner_identity_fk
        FOREIGN KEY (owner_id, identity_version_id)
        REFERENCES havre.identity_artifact_versions(owner_id, artifact_version_id),
    ADD CONSTRAINT context_packs_owner_values_fk
        FOREIGN KEY (owner_id, values_version_id)
        REFERENCES havre.identity_artifact_versions(owner_id, artifact_version_id);

ALTER TABLE havre.route_decisions
    DROP CONSTRAINT route_decisions_request_id_fkey,
    DROP CONSTRAINT route_decisions_trace_id_fkey,
    ADD CONSTRAINT route_decisions_owner_request_fk
        FOREIGN KEY (owner_id, request_id)
        REFERENCES havre.interaction_requests(owner_id, request_id),
    ADD CONSTRAINT route_decisions_owner_trace_fk
        FOREIGN KEY (owner_id, trace_id) REFERENCES havre.traces(owner_id, trace_id);

ALTER TABLE havre.inference_attempts
    DROP CONSTRAINT inference_attempts_request_id_fkey,
    DROP CONSTRAINT inference_attempts_trace_id_fkey,
    DROP CONSTRAINT inference_attempts_context_pack_id_fkey,
    DROP CONSTRAINT inference_attempts_route_decision_id_fkey,
    ADD CONSTRAINT inference_attempts_owner_request_fk
        FOREIGN KEY (owner_id, request_id)
        REFERENCES havre.interaction_requests(owner_id, request_id),
    ADD CONSTRAINT inference_attempts_owner_trace_fk
        FOREIGN KEY (owner_id, trace_id) REFERENCES havre.traces(owner_id, trace_id),
    ADD CONSTRAINT inference_attempts_owner_context_pack_fk
        FOREIGN KEY (owner_id, context_pack_id)
        REFERENCES havre.context_packs(owner_id, context_pack_id),
    ADD CONSTRAINT inference_attempts_owner_route_fk
        FOREIGN KEY (owner_id, route_decision_id)
        REFERENCES havre.route_decisions(owner_id, route_decision_id);

-- Match indexes to the owner-qualified foreign-key access paths.
DROP INDEX havre.interaction_requests_trace_id_idx;
DROP INDEX havre.interaction_requests_user_event_id_idx;
DROP INDEX havre.interaction_requests_assistant_event_id_idx;
DROP INDEX havre.interaction_requests_context_pack_id_idx;
DROP INDEX havre.interaction_requests_inference_response_id_idx;
CREATE INDEX interaction_requests_owner_trace_id_idx
    ON havre.interaction_requests(owner_id, trace_id);
CREATE INDEX interaction_requests_owner_user_event_id_idx
    ON havre.interaction_requests(owner_id, user_event_id) WHERE user_event_id IS NOT NULL;
CREATE INDEX interaction_requests_owner_assistant_event_id_idx
    ON havre.interaction_requests(owner_id, assistant_event_id) WHERE assistant_event_id IS NOT NULL;
CREATE INDEX interaction_requests_owner_context_pack_id_idx
    ON havre.interaction_requests(owner_id, context_pack_id) WHERE context_pack_id IS NOT NULL;
CREATE INDEX interaction_requests_owner_inference_response_id_idx
    ON havre.interaction_requests(owner_id, inference_response_id)
    WHERE inference_response_id IS NOT NULL;

DROP INDEX havre.events_request_id_idx;
DROP INDEX havre.events_trace_id_idx;
DROP INDEX havre.events_causation_event_id_idx;
CREATE INDEX events_owner_request_id_idx ON havre.events(owner_id, request_id);
CREATE INDEX events_owner_trace_id_idx ON havre.events(owner_id, trace_id);
CREATE INDEX events_owner_causation_event_id_idx
    ON havre.events(owner_id, causation_event_id) WHERE causation_event_id IS NOT NULL;

DROP INDEX havre.context_packs_trace_id_idx;
DROP INDEX havre.context_packs_constitution_version_id_idx;
DROP INDEX havre.context_packs_identity_version_id_idx;
DROP INDEX havre.context_packs_values_version_id_idx;
CREATE INDEX context_packs_owner_trace_id_idx ON havre.context_packs(owner_id, trace_id);
CREATE INDEX context_packs_owner_constitution_version_id_idx
    ON havre.context_packs(owner_id, constitution_version_id);
CREATE INDEX context_packs_owner_identity_version_id_idx
    ON havre.context_packs(owner_id, identity_version_id);
CREATE INDEX context_packs_owner_values_version_id_idx
    ON havre.context_packs(owner_id, values_version_id);

DROP INDEX havre.route_decisions_trace_id_idx;
CREATE INDEX route_decisions_owner_trace_id_idx
    ON havre.route_decisions(owner_id, trace_id);

DROP INDEX havre.inference_attempts_trace_id_idx;
DROP INDEX havre.inference_attempts_context_pack_id_idx;
DROP INDEX havre.inference_attempts_route_decision_id_idx;
CREATE INDEX inference_attempts_owner_trace_id_idx
    ON havre.inference_attempts(owner_id, trace_id);
CREATE INDEX inference_attempts_owner_context_pack_id_idx
    ON havre.inference_attempts(owner_id, context_pack_id);
CREATE INDEX inference_attempts_owner_route_decision_id_idx
    ON havre.inference_attempts(owner_id, route_decision_id);
