-- Additive Stage 15 foreign-key index correction. Migration 0054 has already
-- been exercised against PostgreSQL and remains immutable.

BEGIN;

CREATE INDEX goal_transition_evidence_lifecycle_fk_idx
  ON havre.goal_transition_evidence(owner_id,lifecycle_event_id);
CREATE INDEX goal_transition_evidence_source_fk_idx
  ON havre.goal_transition_evidence(owner_id,source_event_id);

CREATE INDEX commitment_projections_source_event_fk_idx
  ON havre.commitment_projections(owner_id,source_event_id);
CREATE INDEX commitment_projections_authorization_fk_idx
  ON havre.commitment_projections(owner_id,authorization_id);

CREATE INDEX proactive_fusion_claims_work_fk_idx
  ON havre.proactive_fusion_claims(owner_id,work_item_id);
CREATE INDEX proactive_fusion_claims_request_fk_idx
  ON havre.proactive_fusion_claims(owner_id,request_id);
CREATE INDEX proactive_fusion_claims_goal_fk_idx
  ON havre.proactive_fusion_claims(owner_id,goal_id);
CREATE INDEX proactive_fusion_claims_projection_fk_idx
  ON havre.proactive_fusion_claims(owner_id,commitment_projection_id);
CREATE INDEX proactive_fusion_claims_assistant_fk_idx
  ON havre.proactive_fusion_claims(owner_id,assistant_event_id)
  WHERE assistant_event_id IS NOT NULL;
CREATE INDEX proactive_fusion_claims_context_fk_idx
  ON havre.proactive_fusion_claims(owner_id,context_pack_id)
  WHERE context_pack_id IS NOT NULL;

CREATE INDEX commitment_deliveries_claim_fk_idx
  ON havre.commitment_reminder_deliveries(owner_id,claim_id)
  WHERE claim_id IS NOT NULL;
CREATE INDEX commitment_deliveries_goal_fk_idx
  ON havre.commitment_reminder_deliveries(owner_id,goal_id);
CREATE INDEX commitment_deliveries_projection_fk_idx
  ON havre.commitment_reminder_deliveries(owner_id,commitment_projection_id);
CREATE INDEX commitment_deliveries_assistant_fk_idx
  ON havre.commitment_reminder_deliveries(owner_id,assistant_event_id);
CREATE INDEX commitment_deliveries_context_fk_idx
  ON havre.commitment_reminder_deliveries(owner_id,context_pack_id)
  WHERE context_pack_id IS NOT NULL;
CREATE INDEX commitment_deliveries_source_fk_idx
  ON havre.commitment_reminder_deliveries(owner_id,source_event_id);

COMMIT;
