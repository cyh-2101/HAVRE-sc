-- Bind Stage 7 proposals to exact trace and memory-revision boundaries.

ALTER TABLE havre.reflection_proposals
    ADD CONSTRAINT reflection_proposals_owner_trace_fk
    FOREIGN KEY (owner_id, trace_id) REFERENCES havre.traces(owner_id, trace_id);
ALTER TABLE havre.memory_lifecycle_proposals
    ADD CONSTRAINT memory_lifecycle_proposals_owner_trace_fk
    FOREIGN KEY (owner_id, trace_id) REFERENCES havre.traces(owner_id, trace_id),
    ADD CONSTRAINT memory_lifecycle_proposals_target_revision_fk
    FOREIGN KEY (owner_id, target_memory_id, target_revision)
    REFERENCES havre.memory_revisions(owner_id, memory_id, revision);

CREATE INDEX reflection_proposals_owner_trace_idx
    ON havre.reflection_proposals(owner_id, trace_id);
CREATE INDEX memory_lifecycle_proposals_owner_trace_idx
    ON havre.memory_lifecycle_proposals(owner_id, trace_id);
CREATE INDEX memory_lifecycle_proposals_owner_target_idx
    ON havre.memory_lifecycle_proposals(owner_id, target_memory_id, target_revision)
    WHERE target_memory_id IS NOT NULL;

DROP VIEW havre.stage7_required_provenance_violations;
CREATE VIEW havre.stage7_required_provenance_violations AS
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
       SELECT 1 FROM jsonb_array_elements_text(
           proposal.payload->'evidence_event_ids'
       ) AS expected(event_id)
       WHERE NOT EXISTS (
           SELECT 1 FROM havre.reflection_proposal_evidence AS evidence
           WHERE evidence.owner_id = proposal.owner_id
             AND evidence.reflection_proposal_id = proposal.reflection_proposal_id
             AND evidence.source_event_id = expected.event_id::uuid
       )
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
       SELECT 1 FROM jsonb_array_elements_text(
           proposal.payload->'source_event_ids'
       ) AS expected(event_id)
       WHERE NOT EXISTS (
           SELECT 1 FROM havre.memory_lifecycle_proposal_evidence AS evidence
           WHERE evidence.owner_id = proposal.owner_id
             AND evidence.lifecycle_proposal_id = proposal.lifecycle_proposal_id
             AND evidence.source_event_id = expected.event_id::uuid
       )
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
       WHERE source.owner_id = snapshot.owner_id
         AND source.dataset_snapshot_id = snapshot.dataset_snapshot_id
         AND event.training_eligible <> false
   );
