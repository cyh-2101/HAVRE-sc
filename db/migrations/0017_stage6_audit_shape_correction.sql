-- Match the six-column provenance audit contract used by Stages 2-5.

DROP VIEW havre.stage6_required_provenance_violations;
CREATE VIEW havre.stage6_required_provenance_violations AS
SELECT proposal.proposal_id AS provenance_edge_id, proposal.owner_id,
       'proactive_proposal'::text AS source_kind,
       proposal.primary_trigger_id AS source_id,
       NULL::integer AS source_revision,
       'proactive_proposal_trigger_lineage'::text AS violation_code
FROM havre.proactive_proposals AS proposal
LEFT JOIN havre.proactive_triggers AS trigger
  ON trigger.owner_id = proposal.owner_id
 AND trigger.trigger_id = proposal.primary_trigger_id
WHERE trigger.trigger_id IS NULL
   OR trigger.request_id <> proposal.request_id
   OR trigger.trace_id <> proposal.trace_id
   OR NOT proposal.trigger_refs @> jsonb_build_array(proposal.primary_trigger_id::text)
UNION ALL
SELECT decision.interruption_decision_id, decision.owner_id,
       'interruption_decision', decision.proposal_id, NULL::integer,
       'interruption_decision_lineage'
FROM havre.interruption_decisions AS decision
JOIN havre.proactive_proposals AS proposal
  ON proposal.owner_id = decision.owner_id
 AND proposal.proposal_id = decision.proposal_id
JOIN havre.proactive_preference_revisions AS preference
  ON preference.owner_id = decision.owner_id
 AND preference.preference_revision_id = decision.preference_revision_id
WHERE decision.trace_id <> proposal.trace_id
   OR decision.payload->>'proposal_id' <> proposal.proposal_id::text
   OR decision.payload->>'preference_revision_id' <> preference.preference_revision_id::text
   OR decision.payload->>'decision' <> decision.decision
UNION ALL
SELECT attempt.delivery_attempt_id, attempt.owner_id,
       'proactive_delivery_attempt', attempt.proposal_id, NULL::integer,
       'proactive_delivery_chain'
FROM havre.proactive_delivery_attempts AS attempt
JOIN havre.interruption_decisions AS decision
  ON decision.owner_id = attempt.owner_id
 AND decision.interruption_decision_id = attempt.interruption_decision_id
JOIN havre.rendered_proactive_messages AS rendering
  ON rendering.owner_id = attempt.owner_id
 AND rendering.rendering_id = attempt.rendering_id
JOIN havre.proactive_context_packs AS context_pack
  ON context_pack.owner_id = rendering.owner_id
 AND context_pack.proactive_context_pack_id = rendering.proactive_context_pack_id
WHERE decision.decision <> 'SEND_NOW'
   OR attempt.proposal_id <> decision.proposal_id
   OR rendering.proposal_id <> decision.proposal_id
   OR context_pack.proposal_id <> decision.proposal_id
   OR attempt.trace_id <> decision.trace_id
   OR rendering.trace_id <> decision.trace_id
   OR context_pack.trace_id <> decision.trace_id
UNION ALL
SELECT inbox.inbox_message_id, inbox.owner_id,
       'proactive_inbox_message', inbox.proposal_id, NULL::integer,
       'proactive_assistant_event_lineage'
FROM havre.proactive_inbox_messages AS inbox
JOIN havre.proactive_delivery_attempts AS attempt
  ON attempt.owner_id = inbox.owner_id
 AND attempt.delivery_attempt_id = inbox.delivery_attempt_id
JOIN havre.events AS event
  ON event.owner_id = inbox.owner_id
 AND event.event_id = inbox.assistant_event_id
WHERE attempt.status <> 'delivered'
   OR event.event_type <> 'ASSISTANT_MESSAGE'
   OR event.recorded_at < inbox.visible_at
   OR event.payload->>'interaction_mode' <> 'proactive_web_inbox'
   OR event.payload->>'proposal_id' <> inbox.proposal_id::text
   OR event.payload->>'rendering_id' <> inbox.rendering_id::text
   OR event.payload->>'delivery_attempt_id' <> inbox.delivery_attempt_id::text;
