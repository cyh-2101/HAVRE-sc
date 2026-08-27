-- Prevent offline regeneration from reusing a source after derivative erasure.

CREATE TABLE havre.offline_source_revocations (
    owner_id uuid NOT NULL,
    source_event_id uuid NOT NULL,
    reason text NOT NULL CHECK (length(reason) BETWEEN 1 AND 500),
    revoked_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (owner_id, source_event_id),
    FOREIGN KEY (owner_id, source_event_id)
        REFERENCES havre.events(owner_id, event_id)
);
CREATE TRIGGER offline_source_revocations_immutable
    BEFORE UPDATE OR DELETE ON havre.offline_source_revocations
    FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation();

CREATE OR REPLACE VIEW havre.stage7_required_provenance_violations AS
SELECT proposal.reflection_proposal_id AS provenance_edge_id, proposal.owner_id,
       'reflection_proposal'::text AS source_kind,
       proposal.reflection_proposal_id AS source_id, NULL::integer AS source_revision,
       'reflection_proposal_evidence_mismatch'::text AS violation_code
FROM havre.reflection_proposals AS proposal
WHERE jsonb_array_length(proposal.payload->'evidence_event_ids') = 0
   OR jsonb_array_length(proposal.payload->'evidence_event_ids') <> (
       SELECT count(*) FROM havre.reflection_proposal_evidence AS evidence
       WHERE evidence.owner_id = proposal.owner_id
         AND evidence.reflection_proposal_id = proposal.reflection_proposal_id
   )
   OR EXISTS (
       SELECT 1 FROM havre.reflection_proposal_evidence AS evidence
       JOIN havre.offline_source_revocations AS revoked
         ON revoked.owner_id = evidence.owner_id
        AND revoked.source_event_id = evidence.source_event_id
       WHERE evidence.owner_id = proposal.owner_id
         AND evidence.reflection_proposal_id = proposal.reflection_proposal_id
   )
UNION ALL
SELECT proposal.lifecycle_proposal_id, proposal.owner_id,
       'memory_lifecycle_proposal', proposal.lifecycle_proposal_id, NULL::integer,
       'memory_lifecycle_proposal_evidence_mismatch'
FROM havre.memory_lifecycle_proposals AS proposal
WHERE jsonb_array_length(proposal.payload->'source_event_ids') <> (
       SELECT count(*) FROM havre.memory_lifecycle_proposal_evidence AS evidence
       WHERE evidence.owner_id = proposal.owner_id
         AND evidence.lifecycle_proposal_id = proposal.lifecycle_proposal_id
   )
   OR EXISTS (
       SELECT 1 FROM havre.memory_lifecycle_proposal_evidence AS evidence
       JOIN havre.offline_source_revocations AS revoked
         ON revoked.owner_id = evidence.owner_id
        AND revoked.source_event_id = evidence.source_event_id
       WHERE evidence.owner_id = proposal.owner_id
         AND evidence.lifecycle_proposal_id = proposal.lifecycle_proposal_id
   )
UNION ALL
SELECT snapshot.dataset_snapshot_id, snapshot.owner_id,
       'canonical_dataset_snapshot', snapshot.dataset_snapshot_id, NULL::integer,
       'training_policy_or_manifest_violation'
FROM havre.canonical_dataset_snapshots AS snapshot
WHERE jsonb_array_length(snapshot.payload->'members') <> 0
   OR jsonb_array_length(snapshot.payload->'rejections') <> (
       SELECT count(*) FROM havre.dataset_snapshot_sources AS source
       WHERE source.owner_id = snapshot.owner_id
         AND source.dataset_snapshot_id = snapshot.dataset_snapshot_id
   )
   OR EXISTS (
       SELECT 1 FROM havre.dataset_snapshot_sources AS source
       JOIN havre.events AS event
         ON event.owner_id = source.owner_id AND event.event_id = source.source_event_id
       LEFT JOIN havre.offline_source_revocations AS revoked
         ON revoked.owner_id = source.owner_id
        AND revoked.source_event_id = source.source_event_id
       WHERE source.owner_id = snapshot.owner_id
         AND source.dataset_snapshot_id = snapshot.dataset_snapshot_id
         AND (event.training_eligible <> false OR revoked.source_event_id IS NOT NULL)
   );
