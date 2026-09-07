"""Atomic PostgreSQL Stage 6 proactive lifecycle and local inbox delivery."""

from __future__ import annotations
from contextlib import nullcontext

import hashlib
from datetime import UTC, datetime, time, timedelta
from typing import Any, TYPE_CHECKING
from uuid import UUID
from zoneinfo import ZoneInfo

from psycopg.types.json import Jsonb
from pydantic_core import to_jsonable_python

from companion.context.strategies import ControlledContextStrategy
from companion.context.freshness import StalePersonalContextError, source_context_is_current
from companion.events import (
    DeliveryRecord,
    EventEnvelope,
    EventType,
    ProactiveAssistantMessagePayload,
    TextContentPart,
)
from companion.hashing import content_hash
from companion.ids import new_span_id, uuid7
from companion.identity import IdentityBundle
from companion.persistence.postgres import PostgresRepository
from companion.policy import DataPolicy
from companion.proactive.models import (
    DeliveryAttempt,
    InterruptionDecision,
    InterruptionOutcome,
    PreviewPolicy,
    ProactiveContextPack,
    ProactiveInboxItem,
    ProactiveLifecycleView,
    ProactiveOwnerAction,
    ProactivePreferenceRevision,
    ProactiveProposal,
    ProactiveSourceGuard,
    ProactiveWorkCommand,
    RenderedProactiveMessage,
    TriggerRecord,
)
from companion.proactive.policy import InterruptionPolicy
from companion.tracing import Span, TraceContext

if TYPE_CHECKING:
    from companion.commitments.service import CommitmentBroker


class ActiveConversationDeferral(RuntimeError):
    """A user arrival won the standalone-delivery race."""


class ProactivePostgresStore:
    service_version = "proactive-service-v1"

    def __init__(
        self,
        *,
        repository: PostgresRepository,
        owner_id: UUID,
        identity: IdentityBundle,
        commitment_broker: "CommitmentBroker | None" = None,
        relational_initiative_enabled: bool = False,
    ) -> None:
        self.repository = repository
        self.owner_id = owner_id
        self.identity = identity
        self.commitment_broker = commitment_broker
        self.relational_initiative_enabled = relational_initiative_enabled
        self.policy = InterruptionPolicy(
            constitution_version_id=identity.constitution.version_id,
            identity_version_id=identity.identity.version_id,
        )

    @staticmethod
    def _policy_columns(policy: DataPolicy) -> tuple[object, ...]:
        return (
            policy.privacy_class.value,
            policy.memory_eligible,
            policy.training_eligible,
            policy.cloud_eligible,
            policy.policy_version,
            policy.policy_revision_id,
            policy.decision_source,
            policy.authorization_ref,
        )

    def save_preference(self, preference: ProactivePreferenceRevision) -> None:
        if preference.owner_id != self.owner_id:
            raise ValueError("preference owner mismatch")
        with self.repository.pool.connection() as connection, connection.transaction():
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"proactive-owner:{self.owner_id}",),
            )
            head = connection.execute(
                """
                SELECT preference_revision_id, revision
                FROM havre.proactive_preference_heads
                WHERE owner_id = %s
                """,
                (self.owner_id,),
            ).fetchone()
            existing = connection.execute(
                """
                SELECT preference_revision_id, content_hash
                FROM havre.proactive_preference_revisions
                WHERE owner_id = %s AND revision = %s
                """,
                (self.owner_id, preference.revision),
            ).fetchone()
            if existing:
                if existing["content_hash"] != preference.content_hash:
                    raise ValueError("preference revision is immutable")
                return
            if head is not None and preference.revision <= head["revision"]:
                raise ValueError("preference revision must advance the current head")
            connection.execute(
                """
                INSERT INTO havre.proactive_preference_revisions (
                    preference_revision_id, schema_version, owner_id, revision,
                    payload, simulation_only, external_delivery_authorized,
                    content_hash, created_at
                ) VALUES (%s, %s, %s, %s, %s, true, false, %s, %s)
                """,
                (
                    preference.preference_revision_id,
                    preference.schema_version,
                    self.owner_id,
                    preference.revision,
                    Jsonb(preference.model_dump(mode="json")),
                    preference.content_hash,
                    preference.created_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO havre.proactive_preference_heads (
                    owner_id, preference_revision_id, revision
                ) VALUES (%s, %s, %s)
                ON CONFLICT (owner_id) DO UPDATE
                SET preference_revision_id = EXCLUDED.preference_revision_id,
                    revision = EXCLUDED.revision
                """,
                (
                    self.owner_id,
                    preference.preference_revision_id,
                    preference.revision,
                ),
            )

    def execute_fixture(
        self,
        *,
        trigger_type: str,
        source_kind: str,
        source_refs: tuple[str, ...],
        subject_refs: tuple[str, ...],
        category: str,
        reason_code: str,
        reason_summary: str,
        intended_benefit: str,
        data_policy: DataPolicy,
        preference_revision: int,
        idempotency_key: str,
        observed_at: datetime,
        earliest_eligible_at: datetime,
        expires_at: datetime,
        deduplication_key: str,
        trigger_source_version: str = "stage6-fixture-trigger-v1",
        traceparent: str | None = None,
        expected_arrival_epoch: int | None = None,
        work_item_id: UUID | None = None,
    ) -> ProactiveLifecycleView:
        trace = TraceContext.from_traceparent(traceparent)
        request_id = uuid7()
        session_id = uuid7()
        started_at = datetime.now(UTC)
        fingerprint = content_hash(
            {
                "service_version": self.service_version,
                "trigger_type": trigger_type,
                "source_kind": source_kind,
                "source_refs": source_refs,
                "subject_refs": subject_refs,
                "category": category,
                "reason_code": reason_code,
                "reason_summary": reason_summary,
                "intended_benefit": intended_benefit,
                "data_policy": data_policy.model_dump(mode="json"),
                "preference_revision": preference_revision,
                "trigger_source_version": trigger_source_version,
                "observed_at": observed_at.isoformat(),
                "earliest_eligible_at": earliest_eligible_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "deduplication_key": deduplication_key,
            }
        )
        with self.repository.pool.connection() as connection, connection.transaction():
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"proactive-owner:{self.owner_id}",),
            )
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"{self.owner_id}:{idempotency_key}",),
            )
            existing = connection.execute(
                """
                SELECT * FROM havre.interaction_requests
                WHERE owner_id = %s AND idempotency_key = %s
                """,
                (self.owner_id, idempotency_key),
            ).fetchone()
            if existing:
                if existing["request_fingerprint"] != fingerprint:
                    raise ValueError("idempotency key was reused with different proactive input")
                if existing["request_kind"] != "proactive_work":
                    raise ValueError("idempotency key belongs to another request kind")
                return self._view(connection, request_id=existing["request_id"], replay=True)

            preference_row = connection.execute(
                """
                SELECT revision.*
                FROM havre.proactive_preference_heads AS head
                JOIN havre.proactive_preference_revisions AS revision
                  ON revision.owner_id = head.owner_id
                 AND revision.preference_revision_id = head.preference_revision_id
                WHERE head.owner_id = %s
                """,
                (self.owner_id,),
            ).fetchone()
            if preference_row is None:
                raise LookupError("current proactive preference head not found")
            preference = ProactivePreferenceRevision.model_validate(preference_row["payload"])

            connection.execute(
                "INSERT INTO havre.sessions (session_id, owner_id, channel) VALUES (%s, %s, 'web')",
                (session_id, self.owner_id),
            )
            connection.execute(
                """
                INSERT INTO havre.traces (
                    trace_id, owner_id, root_request_id, incoming_parent_span_id,
                    trace_flags, started_at
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    trace.trace_id,
                    self.owner_id,
                    request_id,
                    trace.parent_span_id,
                    trace.trace_flags,
                    started_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO havre.interaction_requests (
                    request_id, owner_id, session_id, trace_id, idempotency_key,
                    request_fingerprint, request_kind, status
                ) VALUES (%s, %s, %s, %s, %s, %s, 'proactive_work', 'processing')
                """,
                (request_id, self.owner_id, session_id, trace.trace_id, idempotency_key, fingerprint),
            )

            trigger = TriggerRecord(
                owner_id=self.owner_id,
                trigger_type=trigger_type,
                source_kind=source_kind,
                source_refs=source_refs,
                subject_refs=subject_refs,
                observed_at=observed_at,
                source_version=trigger_source_version,
                data_policy=data_policy,
                trace_id=trace.trace_id,
            )
            self._insert_trigger(connection, request_id=request_id, trigger=trigger)
            self._lifecycle(
                connection,
                proposal_id=None,
                event_type="PROACTIVE_TRIGGER_RECORDED",
                artifact_kind="trigger",
                artifact_id=trigger.trigger_id,
                trace_id=trace.trace_id,
                payload={"source_kind": trigger.source_kind.value},
            )

            proposal = ProactiveProposal(
                owner_id=self.owner_id,
                category=category,
                trigger_refs=(trigger.trigger_id,),
                reason_code=reason_code,
                reason_summary=reason_summary,
                intended_benefit=intended_benefit,
                subject_refs=subject_refs,
                evidence_refs=source_refs,
                data_policy=data_policy,
                earliest_eligible_at=earliest_eligible_at,
                expires_at=expires_at,
                deduplication_key=deduplication_key,
                trace_id=trace.trace_id,
            )
            self._insert_proposal(connection, request_id=request_id, proposal=proposal)
            self._lifecycle(
                connection,
                proposal_id=proposal.proposal_id,
                event_type="PROACTIVE_PROPOSAL_CREATED",
                artifact_kind="proposal",
                artifact_id=proposal.proposal_id,
                trace_id=trace.trace_id,
                payload={"reason_code": proposal.reason_code},
            )

            now = datetime.now(UTC)
            (
                global_count,
                category_count,
                last_equivalent,
                duplicate,
                prior_response_result,
                snooze_until,
            ) = self._policy_state(
                connection,
                proposal=proposal,
                now=now,
            )
            decision = self.policy.decide(
                proposal=proposal,
                preference=preference,
                now=now,
                delivered_global_24h=global_count,
                delivered_category_24h=category_count,
                last_equivalent_delivery_at=last_equivalent,
                duplicate_active=duplicate,
                prior_response_result=prior_response_result,
                snooze_until=snooze_until,
            )
            self._insert_decision(connection, decision)
            lifecycle_type = {
                InterruptionOutcome.SEND_NOW: "PROACTIVE_POLICY_DECIDED",
                InterruptionOutcome.DEFER: "PROACTIVE_PROPOSAL_DEFERRED",
                InterruptionOutcome.DROP: "PROACTIVE_PROPOSAL_DROPPED",
                InterruptionOutcome.REQUEST_OWNER_CONFIRMATION: (
                    "PROACTIVE_OWNER_CONFIRMATION_REQUESTED"
                ),
            }[decision.decision]
            self._lifecycle(
                connection,
                proposal_id=proposal.proposal_id,
                event_type=lifecycle_type,
                artifact_kind="interruption_decision",
                artifact_id=decision.interruption_decision_id,
                trace_id=trace.trace_id,
                payload={"decision": decision.decision.value, "reason_codes": decision.reason_codes},
            )

            assistant_event_id = None
            if decision.decision is InterruptionOutcome.SEND_NOW:
                if expected_arrival_epoch is not None:
                    state = connection.execute(
                        """
                        SELECT state.arrival_epoch,
                               EXISTS(
                                 SELECT 1 FROM havre.interaction_activity_leases lease
                                 WHERE lease.owner_id=state.owner_id
                                   AND lease.ended_at IS NULL
                                   AND lease.expires_at>statement_timestamp()
                               ) AS active
                        FROM havre.owner_conversation_delivery_state state
                        WHERE state.owner_id=%s FOR UPDATE
                        """,
                        (self.owner_id,),
                    ).fetchone()
                    actual_epoch = 0 if state is None else state["arrival_epoch"]
                    active = False if state is None else state["active"]
                    if active or actual_epoch != expected_arrival_epoch:
                        raise ActiveConversationDeferral(
                            "standalone delivery lost the user-arrival race"
                        )
                context_pack, rendering, attempt, assistant_event_id = self._render_and_deliver(
                    connection,
                    request_id=request_id,
                    session_id=session_id,
                    trigger=trigger,
                    proposal=proposal,
                    preference=preference,
                    decision=decision,
                    work_item_id=work_item_id,
                )

            connection.execute(
                """
                UPDATE havre.interaction_requests
                SET status = 'completed', assistant_event_id = %s,
                    completed_at = statement_timestamp()
                WHERE owner_id = %s AND request_id = %s AND status = 'processing'
                """,
                (assistant_event_id, self.owner_id, request_id),
            )
            ended_at = datetime.now(UTC)
            PostgresRepository._insert_spans(
                connection,
                [
                    Span(
                        trace_id=trace.trace_id,
                        span_id=new_span_id(),
                        parent_span_id=trace.parent_span_id,
                        name="proactive.evaluate_and_deliver",
                        kind="server",
                        started_at=started_at,
                        ended_at=ended_at,
                        duration_ms=round((ended_at - started_at).total_seconds() * 1000, 3),
                        status="ok",
                        attributes={
                            "proactive_service_version": self.service_version,
                            "simulation_only": True,
                            "external_delivery_authorized": False,
                            "decision": decision.decision.value,
                        },
                    )
                ],
            )
            return self._view(connection, request_id=request_id, replay=False)

    def _policy_state(self, connection, *, proposal: ProactiveProposal, now: datetime):
        since = now - timedelta(hours=24)
        row = connection.execute(
            """
            SELECT count(*) AS global_count,
                   count(*) FILTER (WHERE proposal.category = %s) AS category_count,
                   max(attempt.visible_at) FILTER (
                       WHERE proposal.deduplication_key = %s
                   ) AS last_equivalent
            FROM havre.proactive_delivery_attempts AS attempt
            JOIN havre.proactive_proposals AS proposal
              ON proposal.owner_id = attempt.owner_id
             AND proposal.proposal_id = attempt.proposal_id
            WHERE attempt.owner_id = %s AND attempt.status = 'delivered'
              AND attempt.visible_at >= %s
            """,
            (proposal.category, proposal.deduplication_key, self.owner_id, since),
        ).fetchone()
        fused_count = connection.execute(
            """
            SELECT count(*) AS value
            FROM havre.commitment_reminder_deliveries
            WHERE owner_id=%s AND delivery_mode='conversation_fusion'
              AND delivered_at>=%s
            """,
            (self.owner_id,since),
        ).fetchone()["value"]
        duplicate = connection.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM havre.proactive_proposals AS existing
                JOIN havre.interruption_decisions AS decision
                  ON decision.owner_id = existing.owner_id
                 AND decision.proposal_id = existing.proposal_id
                WHERE existing.owner_id = %s
                  AND existing.deduplication_key = %s
                  AND existing.proposal_id <> %s
                  AND existing.expires_at > %s
                  AND decision.decision IN ('SEND_NOW', 'DEFER', 'REQUEST_OWNER_CONFIRMATION')
            ) AS value
            """,
            (self.owner_id, proposal.deduplication_key, proposal.proposal_id, now),
        ).fetchone()["value"]
        owner_action = connection.execute(
            """
            SELECT action_type, snooze_until
            FROM havre.proactive_owner_actions
            WHERE owner_id = %s
              AND (
                  deduplication_key = %s
                  OR (cardinality(%s::text[]) > 0 AND subject_refs && %s::text[])
              )
              AND (action_type <> 'snoozed' OR snooze_until > %s)
            ORDER BY (action_type = 'stopped') DESC,
                     observed_at DESC, action_id DESC
            LIMIT 1
            """,
            (
                self.owner_id,
                proposal.deduplication_key,
                list(proposal.subject_refs),
                list(proposal.subject_refs),
                now,
            ),
        ).fetchone()
        return (
            row["global_count"] + fused_count,
            row["category_count"] + (
                fused_count if proposal.category == "owner_reminder" else 0
            ),
            row["last_equivalent"],
            duplicate,
            owner_action["action_type"] if owner_action else "none",
            owner_action["snooze_until"] if owner_action else None,
        )

    @staticmethod
    def _render_text(proposal: ProactiveProposal) -> str:
        summary = proposal.reason_summary.strip()
        if proposal.reason_code in {
            "relationship_follow_up", "conversation_continuation"
        }:
            return summary[:300]
        if proposal.reason_code == "owner_goal_reminder":
            return summary[:500]
        if proposal.reason_code == "owner_requested_time_bound_reminder":
            return f"\u63d0\u9192\u4e00\u4e0b\uff1a{summary}"[:500]
        if proposal.reason_code == "goal_review_due":
            return f"{summary}\u3002\u8981\u4e0d\u8981\u73b0\u5728\u770b\u4e00\u773c\uff1f"[:500]
        if proposal.reason_code == "planned_scene_start_due":
            return (
                f"{summary}\u3002\u9700\u8981\u7684\u8bdd\uff0c"
                "\u6211\u4eec\u5c31\u4ece\u6700\u5c0f\u4e00\u6b65\u5f00\u59cb\u3002"
            )[:500]
        return (
            f"\u60f3\u8d77\u4f60\u4e4b\u524d\u4ea4\u4ee3\u7684\u8fd9\u4ef6\u4e8b\uff1a{summary}"
        )[:500]

    def _render_and_deliver(
        self, connection, *, request_id, session_id, trigger, proposal, preference,
        decision, work_item_id=None
    ):
        if proposal.category == "conversation_continuation":
            run_refs = [ref for ref in proposal.evidence_refs if ref.startswith("continuation-run/")]
            if len(run_refs) != 1:
                raise StalePersonalContextError("continuation source receipt is missing")
            run_id = UUID(run_refs[0].split("/", 1)[1])
            origin = connection.execute(
                """SELECT assistant.payload->>'context_pack_id' AS context_pack_id
                   FROM havre.owner_conversation_continuation_runs run
                   JOIN havre.events assistant ON assistant.owner_id=run.owner_id
                    AND assistant.event_id=run.source_assistant_event_id
                   WHERE run.owner_id=%s AND run.continuation_run_id=%s""",
                (self.owner_id, run_id),
            ).fetchone()
            if (origin is None or origin["context_pack_id"] is None
                or not source_context_is_current(
                    self.repository, owner_id=self.owner_id,
                    context_pack_id=UUID(origin["context_pack_id"]),
                    connection=connection, lock_current=True,
                )):
                raise StalePersonalContextError("continuation understanding was corrected or expired")
        strategy = ControlledContextStrategy(mode="compressed_top_k", top_k=3).build(
            identity_version=self.identity.identity.version_id,
            policy_version=decision.policy_version,
            candidates=tuple(
                (ref, ref, len(proposal.evidence_refs) - index)
                for index, ref in enumerate(proposal.evidence_refs)
            ),
        )
        context_pack = ProactiveContextPack(
            owner_id=self.owner_id,
            proposal_id=proposal.proposal_id,
            interruption_decision_id=decision.interruption_decision_id,
            strategy_version=strategy.strategy_version,
            prefix_sections=tuple(strategy.rendered_sections[:2]),
            evidence_sections=tuple(strategy.rendered_sections[2:]),
            effective_data_policy=proposal.data_policy,
            trace_id=proposal.trace_id,
        )
        connection.execute(
            """
            INSERT INTO havre.proactive_context_packs (
                proactive_context_pack_id, schema_version, owner_id, proposal_id,
                interruption_decision_id, payload, privacy_class,
                training_eligible, cloud_eligible, trace_id, content_hash
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, false, %s, %s, %s)
            """,
            (
                context_pack.proactive_context_pack_id,
                context_pack.schema_version,
                self.owner_id,
                proposal.proposal_id,
                decision.interruption_decision_id,
                Jsonb(context_pack.model_dump(mode="json")),
                proposal.data_policy.privacy_class.value,
                proposal.data_policy.cloud_eligible,
                proposal.trace_id,
                context_pack.content_hash,
            ),
        )
        text = self._render_text(proposal)
        preview = (
            "HAVRE has a private reminder in your local inbox."
            if preference.preview_policy is PreviewPolicy.GENERIC_PRIVATE
            else None
        )
        rendering = RenderedProactiveMessage(
            owner_id=self.owner_id,
            proposal_id=proposal.proposal_id,
            interruption_decision_id=decision.interruption_decision_id,
            proactive_context_pack_id=context_pack.proactive_context_pack_id,
            content_text=text,
            preview_policy=preference.preview_policy,
            preview_text=preview,
            data_policy=proposal.data_policy,
            trace_id=proposal.trace_id,
        )
        connection.execute(
            """
            INSERT INTO havre.rendered_proactive_messages (
                rendering_id, schema_version, owner_id, proposal_id,
                interruption_decision_id, proactive_context_pack_id,
                renderer_version, content_text, preview_policy, preview_text,
                payload, trace_id, simulation_only, content_hash
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, true, %s)
            """,
            (
                rendering.rendering_id, rendering.schema_version, self.owner_id,
                proposal.proposal_id, decision.interruption_decision_id,
                context_pack.proactive_context_pack_id, rendering.renderer_version,
                rendering.content_text, rendering.preview_policy.value,
                rendering.preview_text, Jsonb(rendering.model_dump(mode="json")),
                rendering.trace_id, rendering.content_hash,
            ),
        )
        self._lifecycle(
            connection, proposal_id=proposal.proposal_id,
            event_type="PROACTIVE_MESSAGE_RENDERED", artifact_kind="rendering",
            artifact_id=rendering.rendering_id, trace_id=proposal.trace_id,
            payload={"renderer_version": rendering.renderer_version},
        )

        visible_at = datetime.now(UTC)
        attempt = DeliveryAttempt(
            owner_id=self.owner_id,
            proposal_id=proposal.proposal_id,
            interruption_decision_id=decision.interruption_decision_id,
            rendering_id=rendering.rendering_id,
            idempotency_key=f"web-inbox:{proposal.proposal_id}",
            status="delivered",
            provider_receipt_id=f"local:{proposal.proposal_id}",
            visible_at=visible_at,
            trace_id=proposal.trace_id,
        )
        connection.execute(
            """
            INSERT INTO havre.proactive_delivery_attempts (
                delivery_attempt_id, schema_version, owner_id, proposal_id,
                interruption_decision_id, rendering_id, channel, adapter_version,
                idempotency_key, attempt_number, status, retryable,
                provider_receipt_id, failure_code, visible_at, trace_id,
                simulation_only, external_delivery_authorized, payload,
                content_hash, created_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, 'web_inbox', 'local-web-inbox-v1',
                %s, 1, %s, false, %s, %s, %s, %s, true, false, %s, %s, %s
            )
            """,
            (
                attempt.delivery_attempt_id, attempt.schema_version, self.owner_id,
                proposal.proposal_id, decision.interruption_decision_id,
                rendering.rendering_id, attempt.idempotency_key, attempt.status,
                attempt.provider_receipt_id, attempt.failure_code, attempt.visible_at,
                attempt.trace_id, Jsonb(attempt.model_dump(mode="json")),
                attempt.content_hash, attempt.created_at,
            ),
        )
        self._lifecycle(
            connection, proposal_id=proposal.proposal_id,
            event_type="PROACTIVE_DELIVERY_ATTEMPTED", artifact_kind="delivery_attempt",
            artifact_id=attempt.delivery_attempt_id, trace_id=proposal.trace_id,
            payload={"channel": "web_inbox", "status": "delivered"},
        )

        event = EventEnvelope(
            event_type=EventType.ASSISTANT_MESSAGE,
            owner_id=self.owner_id,
            session_id=session_id,
            request_id=request_id,
            trace_id=proposal.trace_id,
            data_policy=proposal.data_policy,
            payload=ProactiveAssistantMessagePayload(
                content_parts=(TextContentPart(text=rendering.content_text),),
                proposal_id=proposal.proposal_id,
                interruption_decision_id=decision.interruption_decision_id,
                proactive_context_pack_id=context_pack.proactive_context_pack_id,
                rendering_id=rendering.rendering_id,
                delivery_attempt_id=attempt.delivery_attempt_id,
                delivery=DeliveryRecord(
                    channel="web",
                    first_visible_at=visible_at,
                    completed_at=visible_at,
                ),
            ),
        )
        PostgresRepository._insert_event(connection, event)
        connection.execute(
            """
            INSERT INTO havre.proactive_inbox_messages (
                inbox_message_id, owner_id, proposal_id, delivery_attempt_id,
                rendering_id, assistant_event_id, content_text, visible_at,
                simulation_only
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, true)
            """,
            (
                uuid7(), self.owner_id, proposal.proposal_id,
                attempt.delivery_attempt_id, rendering.rendering_id,
                event.event_id, rendering.content_text, visible_at,
            ),
        )
        self._lifecycle(
            connection, proposal_id=proposal.proposal_id,
            event_type="PROACTIVE_MESSAGE_DELIVERED", artifact_kind="assistant_event",
            artifact_id=event.event_id, trace_id=proposal.trace_id,
            payload={"delivery_attempt_id": str(attempt.delivery_attempt_id)},
        )

        if proposal.reason_code == "owner_goal_reminder" and work_item_id is not None:
            guard_row = connection.execute(
                """SELECT command_payload FROM havre.proactive_work_items
                   WHERE owner_id=%s AND work_item_id=%s""",
                (self.owner_id, work_item_id),
            ).fetchone()
            guard = (
                guard_row["command_payload"].get("source_guard")
                if guard_row is not None else None
            )
            if guard is not None:
                projection = connection.execute(
                    """
                    SELECT * FROM havre.commitment_projections
                    WHERE owner_id=%s AND goal_id=%s AND goal_revision=%s
                    """,
                    (
                        self.owner_id,
                        UUID(guard["projection_id"]),
                        guard["projection_revision"],
                    ),
                ).fetchone()
                if projection is not None:
                    reminder_kind = proposal.deduplication_key.split(":",4)[3]
                    material = {
                        "owner_id": str(self.owner_id),
                        "work_item_id": str(work_item_id),
                        "goal_id": str(projection["goal_id"]),
                        "goal_revision": projection["goal_revision"],
                        "commitment_projection_id": str(
                            projection["commitment_projection_id"]
                        ),
                        "reminder_kind": reminder_kind,
                        "delivery_mode": "standalone_web_inbox",
                        "assistant_event_id": str(event.event_id),
                        "source_event_id": guard["source_event_id"],
                        "source_event_content_hash": guard[
                            "source_event_content_hash"
                        ],
                        "projection_content_hash": guard[
                            "projection_content_hash"
                        ],
                        "inclusion_text": projection["task_name"],
                        "delivered_at": visible_at.isoformat(),
                    }
                    connection.execute(
                        """
                        INSERT INTO havre.commitment_reminder_deliveries (
                          delivery_id,owner_id,work_item_id,claim_id,goal_id,
                          goal_revision,commitment_projection_id,reminder_kind,
                          delivery_mode,assistant_event_id,context_pack_id,
                          source_event_id,source_event_content_hash,
                          projection_content_hash,inclusion_text,content_hash,delivered_at
                        ) VALUES (%s,%s,%s,NULL,%s,%s,%s,%s,
                                  'standalone_web_inbox',%s,NULL,%s,%s,%s,%s,%s,%s)
                        """,
                        (
                            uuid7(),self.owner_id,work_item_id,projection["goal_id"],
                            projection["goal_revision"],
                            projection["commitment_projection_id"],reminder_kind,
                            event.event_id,UUID(guard["source_event_id"]),
                            guard["source_event_content_hash"],
                            guard["projection_content_hash"],projection["task_name"],
                            content_hash(material),visible_at,
                        ),
                    )
        return context_pack, rendering, attempt, event.event_id

    def relationship_cadence_state(
        self, *, now: datetime | None = None
    ) -> dict[str, object]:
        """Read-only candidate cadence; Goal reminders never count here."""
        instant = (now or datetime.now(UTC)).astimezone(UTC)
        with self.repository.pool.connection() as connection:
            row = connection.execute(
                """WITH latest_owner AS (
                       SELECT max(event.recorded_at) AS recorded_at
                       FROM havre.events event
                       JOIN havre.interaction_requests request
                         ON request.owner_id=event.owner_id
                        AND request.request_id=event.request_id
                       WHERE event.owner_id=%s AND event.event_type='USER_MESSAGE'
                         AND request.request_kind='interaction'
                     ), touches AS (
                       SELECT attempt.visible_at
                       FROM havre.proactive_delivery_attempts attempt
                       JOIN havre.proactive_proposals proposal
                         ON proposal.owner_id=attempt.owner_id
                        AND proposal.proposal_id=attempt.proposal_id
                       CROSS JOIN latest_owner
                       WHERE attempt.owner_id=%s AND attempt.status='delivered'
                         AND proposal.category='relationship_follow_up'
                         AND attempt.visible_at>COALESCE(
                           latest_owner.recorded_at,'-infinity'::timestamptz
                         )
                         AND attempt.visible_at<=%s
                     )
                     SELECT count(*) AS unanswered_count,
                            max(visible_at) AS last_touch_at
                     FROM touches""",
                (self.owner_id, self.owner_id, instant),
            ).fetchone()
            active = connection.execute(
                """SELECT count(*) AS value
                   FROM havre.proactive_work_items
                   WHERE owner_id=%s
                     AND command_payload->>'category'='relationship_follow_up'
                     AND status IN ('pending','retryable_failed','leased')
                     AND (command_payload->>'expires_at')::timestamptz>%s""",
                (self.owner_id, instant),
            ).fetchone()["value"]
        unanswered = int(row["unanswered_count"])
        last_touch = row["last_touch_at"]
        wait = (
            None if unanswered == 0
            else timedelta(hours=24) if unanswered == 1
            else timedelta(hours=72)
        )
        return {
            "unanswered_count": unanswered,
            "last_touch_at": last_touch,
            "next_eligible_at": (
                None if last_touch is None or wait is None else last_touch + wait
            ),
            "paused": unanswered >= 3,
            "active_pending_count": int(active),
        }

    def _insert_trigger(self, connection, *, request_id: UUID, trigger: TriggerRecord):
        policy = trigger.data_policy
        connection.execute(
            """
            INSERT INTO havre.proactive_triggers (
                trigger_id, schema_version, owner_id, request_id, trace_id,
                trigger_type, source_kind, source_refs, payload,
                privacy_class, memory_eligible, training_eligible, cloud_eligible,
                policy_version, policy_revision_id, policy_decision_source,
                policy_authorization_ref, simulation_only, content_hash,
                observed_at, recorded_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, true, %s, %s, %s
            )
            """,
            (
                trigger.trigger_id, trigger.schema_version, self.owner_id, request_id,
                trigger.trace_id, trigger.trigger_type, trigger.source_kind.value,
                Jsonb(list(trigger.source_refs)), Jsonb(trigger.model_dump(mode="json")),
                *self._policy_columns(policy), trigger.content_hash,
                trigger.observed_at, trigger.recorded_at,
            ),
        )

    def _insert_proposal(self, connection, *, request_id: UUID, proposal: ProactiveProposal):
        policy = proposal.data_policy
        connection.execute(
            """
            INSERT INTO havre.proactive_proposals (
                proposal_id, schema_version, owner_id, request_id, trace_id,
                category, primary_trigger_id, trigger_refs, deduplication_key,
                payload, privacy_class, memory_eligible, training_eligible,
                cloud_eligible, policy_version, policy_revision_id,
                policy_decision_source, policy_authorization_ref,
                earliest_eligible_at, expires_at, simulation_only,
                content_hash, created_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, true, %s, %s
            )
            """,
            (
                proposal.proposal_id, proposal.schema_version, self.owner_id,
                request_id, proposal.trace_id, proposal.category,
                proposal.trigger_refs[0], Jsonb([str(v) for v in proposal.trigger_refs]),
                proposal.deduplication_key, Jsonb(proposal.model_dump(mode="json")),
                *self._policy_columns(policy), proposal.earliest_eligible_at,
                proposal.expires_at, proposal.content_hash, proposal.created_at,
            ),
        )

    def _insert_decision(self, connection, decision: InterruptionDecision):
        connection.execute(
            """
            INSERT INTO havre.interruption_decisions (
                interruption_decision_id, schema_version, owner_id, proposal_id,
                preference_revision_id, decision, policy_version, payload,
                trace_id, defer_until, expires_at, simulation_only,
                external_delivery_authorized, content_hash, decided_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                      true, false, %s, %s)
            """,
            (
                decision.interruption_decision_id, decision.schema_version,
                self.owner_id, decision.proposal_id,
                decision.preference_revision_id, decision.decision.value,
                decision.policy_version, Jsonb(decision.model_dump(mode="json")),
                decision.trace_id, decision.defer_until, decision.expires_at,
                decision.content_hash, decision.decided_at,
            ),
        )

    def _lifecycle(
        self, connection, *, proposal_id, event_type, artifact_kind,
        artifact_id, trace_id, payload
    ):
        connection.execute(
            """
            INSERT INTO havre.proactive_lifecycle_events (
                lifecycle_event_id, owner_id, proposal_id, event_type,
                artifact_kind, artifact_id, trace_id, payload
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                uuid7(), self.owner_id, proposal_id, event_type, artifact_kind,
                artifact_id, trace_id, Jsonb(to_jsonable_python(payload)),
            ),
        )

    def record_owner_action(
        self,
        *,
        proposal_id: UUID,
        action_type: str,
        idempotency_key: str,
        reason: str,
        observed_at: datetime,
        response_event_id: UUID | None = None,
        snooze_until: datetime | None = None,
    ) -> ProactiveOwnerAction:
        with self.repository.pool.connection() as connection, connection.transaction():
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"proactive-owner:{self.owner_id}",),
            )
            existing = connection.execute(
                """
                SELECT payload FROM havre.proactive_owner_actions
                WHERE owner_id = %s AND idempotency_key = %s
                """,
                (self.owner_id, idempotency_key),
            ).fetchone()
            proposal_row = connection.execute(
                """
                SELECT payload, deduplication_key, trace_id
                FROM havre.proactive_proposals
                WHERE owner_id = %s AND proposal_id = %s
                """,
                (self.owner_id, proposal_id),
            ).fetchone()
            if proposal_row is None:
                raise LookupError("proactive proposal not found")
            proposal = ProactiveProposal.model_validate(proposal_row["payload"])
            inbox = connection.execute(
                """
                SELECT inbox_message_id FROM havre.proactive_inbox_messages
                WHERE owner_id = %s AND proposal_id = %s
                """,
                (self.owner_id, proposal_id),
            ).fetchone()
            action = ProactiveOwnerAction(
                owner_id=self.owner_id,
                proposal_id=proposal_id,
                idempotency_key=idempotency_key,
                action_type=action_type,
                inbox_message_id=(inbox["inbox_message_id"] if inbox else None),
                response_event_id=response_event_id,
                snooze_until=snooze_until,
                deduplication_key=proposal.deduplication_key,
                subject_refs=proposal.subject_refs,
                reason=reason,
                observed_at=observed_at,
                trace_id=proposal.trace_id,
            )
            if existing is not None:
                stored = ProactiveOwnerAction.model_validate(existing["payload"])
                requested = action.model_dump(
                    mode="json", exclude={"action_id", "content_hash"}
                )
                persisted = stored.model_dump(
                    mode="json", exclude={"action_id", "content_hash"}
                )
                if persisted != requested:
                    raise ValueError(
                        "proactive action idempotency key was reused with different input"
                    )
                return stored
            connection.execute(
                """
                INSERT INTO havre.proactive_owner_actions (
                    action_id, schema_version, owner_id, proposal_id,
                    idempotency_key, action_type, inbox_message_id,
                    response_event_id, snooze_until, deduplication_key,
                    subject_refs, reason, observed_at, trace_id,
                    simulation_only, payload, content_hash
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, true, %s, %s
                )
                """,
                (
                    action.action_id,
                    action.schema_version,
                    self.owner_id,
                    action.proposal_id,
                    action.idempotency_key,
                    action.action_type,
                    action.inbox_message_id,
                    action.response_event_id,
                    action.snooze_until,
                    action.deduplication_key,
                    list(action.subject_refs),
                    action.reason,
                    action.observed_at,
                    action.trace_id,
                    Jsonb(action.model_dump(mode="json")),
                    action.content_hash,
                ),
            )
            lifecycle_type = {
                "responded": "PROACTIVE_OWNER_RESPONDED",
                "dismissed": "PROACTIVE_OWNER_DISMISSED",
                "snoozed": "PROACTIVE_OWNER_SNOOZED",
                "non_response": "PROACTIVE_NON_RESPONSE_RECORDED",
                "stopped": "PROACTIVE_OWNER_STOPPED",
            }[action.action_type]
            self._lifecycle(
                connection,
                proposal_id=proposal_id,
                event_type=lifecycle_type,
                artifact_kind="owner_action",
                artifact_id=action.action_id,
                trace_id=action.trace_id,
                payload={"action_type": action.action_type},
            )
            return action

    def reconcile_delivery(self, *, proposal_id: UUID) -> dict[str, object]:
        with self.repository.pool.connection() as connection:
            row = connection.execute(
                """
                SELECT attempt.status, attempt.delivery_attempt_id,
                       attempt.provider_receipt_id, inbox.inbox_message_id,
                       inbox.assistant_event_id, event.event_type
                FROM havre.proactive_delivery_attempts AS attempt
                LEFT JOIN havre.proactive_inbox_messages AS inbox
                  ON inbox.owner_id = attempt.owner_id
                 AND inbox.delivery_attempt_id = attempt.delivery_attempt_id
                LEFT JOIN havre.events AS event
                  ON event.owner_id = inbox.owner_id
                 AND event.event_id = inbox.assistant_event_id
                WHERE attempt.owner_id = %s AND attempt.proposal_id = %s
                """,
                (self.owner_id, proposal_id),
            ).fetchone()
            if row is None:
                proposal = connection.execute(
                    """
                    SELECT 1 FROM havre.proactive_proposals
                    WHERE owner_id = %s AND proposal_id = %s
                    """,
                    (self.owner_id, proposal_id),
                ).fetchone()
                if proposal is None:
                    raise LookupError("proactive proposal not found")
                return {"proposal_id": proposal_id, "status": "not_delivered"}
            if (
                row["status"] == "delivered"
                and (
                    row["provider_receipt_id"] is None
                    or row["inbox_message_id"] is None
                    or row["assistant_event_id"] is None
                    or row["event_type"] != "ASSISTANT_MESSAGE"
                )
            ):
                raise RuntimeError("local delivery reconciliation found incomplete lineage")
            return {
                "proposal_id": proposal_id,
                "status": row["status"],
                "delivery_attempt_id": row["delivery_attempt_id"],
                "inbox_message_id": row["inbox_message_id"],
                "assistant_event_id": row["assistant_event_id"],
                "provider_receipt_id": row["provider_receipt_id"],
            }

    def list_pending_inbox(
        self, *, limit: int = 100
    ) -> tuple[ProactiveInboxItem, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("inbox limit must be between 1 and 100")
        with self.repository.pool.connection() as connection:
            rows = connection.execute(
                """
                SELECT inbox.inbox_message_id, inbox.proposal_id,
                       inbox.delivery_attempt_id, inbox.assistant_event_id,
                       inbox.visible_at,
                       rendering.preview_policy, rendering.preview_text,
                       proposal.privacy_class
                FROM havre.proactive_inbox_messages AS inbox
                JOIN havre.rendered_proactive_messages AS rendering
                  ON rendering.owner_id = inbox.owner_id
                 AND rendering.rendering_id = inbox.rendering_id
                JOIN havre.proactive_proposals AS proposal
                  ON proposal.owner_id = inbox.owner_id
                 AND proposal.proposal_id = inbox.proposal_id
                WHERE inbox.owner_id = %s
                  AND NOT EXISTS (
                    SELECT 1 FROM havre.proactive_owner_actions AS action
                    WHERE action.owner_id = inbox.owner_id
                      AND action.proposal_id = inbox.proposal_id
                  )
                ORDER BY inbox.visible_at, inbox.inbox_message_id
                LIMIT %s
                """,
                (self.owner_id, limit),
            ).fetchall()
        return tuple(
            ProactiveInboxItem(
                inbox_message_id=row["inbox_message_id"],
                proposal_id=row["proposal_id"],
                delivery_attempt_id=row["delivery_attempt_id"],
                assistant_event_id=row["assistant_event_id"],
                content_text=None,
                preview_policy=PreviewPolicy(row["preview_policy"]),
                preview_text=row["preview_text"],
                privacy_class=row["privacy_class"],
                visible_at=row["visible_at"],
            )
            for row in rows
        )

    def enqueue_work(
        self,
        *,
        work_kind: str,
        idempotency_key: str,
        command: ProactiveWorkCommand,
        not_before: datetime,
        supersede_reminder_slot: tuple[UUID, str, datetime] | None = None,
        _connection=None,
    ) -> UUID:
        if not_before.utcoffset() is None:
            raise ValueError("proactive work not_before must be timezone-aware")
        work_item_id = uuid7()
        fingerprint = content_hash(
            {"work_kind": work_kind, "command": command.model_dump(mode="json")}
        )
        with (nullcontext(_connection) if _connection is not None else self.repository.pool.connection()) as connection, connection.transaction():
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"proactive-work:{self.owner_id}:{work_kind}:{idempotency_key}",),
            )
            existing = connection.execute(
                """
                SELECT work_item_id, input_fingerprint
                FROM havre.proactive_work_items
                WHERE owner_id = %s AND work_kind = %s AND idempotency_key = %s
                """,
                (self.owner_id, work_kind, idempotency_key),
            ).fetchone()
            if existing is not None:
                if existing["input_fingerprint"] != fingerprint:
                    raise ValueError(
                        "proactive work idempotency key was reused with different input"
                    )
                return existing["work_item_id"]
            superseded_work_item_ids: list[UUID] = []
            if supersede_reminder_slot is not None:
                goal_id, reminder_kind, remind_at = supersede_reminder_slot
                superseded = connection.execute(
                    """
                    SELECT work_item_id,status
                    FROM havre.proactive_work_items
                    WHERE owner_id=%s AND work_kind='scheduled'
                      AND idempotency_key<>%s
                      AND command_payload->>'reason_code'='owner_goal_reminder'
                      AND command_payload#>>'{source_guard,projection_kind}'='goal'
                      AND command_payload#>>'{source_guard,projection_id}'=%s
                      AND split_part(command_payload->>'deduplication_key',':',4)=%s
                      AND (command_payload->>'earliest_eligible_at')::timestamptz=%s
                      AND status IN ('pending','retryable_failed','leased')
                    FOR UPDATE
                    """,
                    (
                        self.owner_id,
                        idempotency_key,
                        str(goal_id),
                        reminder_kind,
                        remind_at.astimezone(UTC),
                    ),
                ).fetchall()
                if any(row["status"] == "leased" for row in superseded):
                    raise ValueError(
                        "a reminder in the replacement slot is currently leased"
                    )
                superseded_work_item_ids = [
                    row["work_item_id"] for row in superseded
                ]
            connection.execute(
                """
                INSERT INTO havre.proactive_work_items (
                    work_item_id, owner_id, work_kind, idempotency_key,
                    input_fingerprint, command_payload, not_before, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending')
                """,
                (
                    work_item_id,
                    self.owner_id,
                    work_kind,
                    idempotency_key,
                    fingerprint,
                    Jsonb(command.model_dump(mode="json")),
                    not_before.astimezone(UTC),
                ),
            )
            if superseded_work_item_ids:
                connection.execute(
                    """
                    UPDATE havre.proactive_work_items
                    SET status='cancelled',
                        last_error_code='superseded_by_owner_schedule_update',
                        completed_at=statement_timestamp(),
                        lease_owner=NULL,lease_expires_at=NULL
                    WHERE owner_id=%s AND work_item_id=ANY(%s::uuid[])
                      AND status IN ('pending','retryable_failed')
                    """,
                    (self.owner_id, superseded_work_item_ids),
                )
            return work_item_id

    def enqueue_goal_reminder(
        self,
        *,
        goal_id: UUID,
        reminder_kind: str,
        reminder_text: str,
        remind_at: datetime,
        expires_at: datetime,
        idempotency_key: str,
        supersede_existing_slot: bool = False,
        _connection=None,
    ) -> dict[str, object]:
        """Schedule one owner-authored reminder against the exact current Goal.

        The caller supplies wording and time, but Core derives privacy,
        preference, provenance, deduplication, and the execution-time source
        guard from the current durable Goal projection.
        """
        if remind_at.utcoffset() is None or expires_at.utcoffset() is None:
            raise ValueError("goal reminder times must be timezone-aware")
        remind_at = remind_at.astimezone(UTC)
        expires_at = expires_at.astimezone(UTC)
        if expires_at <= remind_at:
            raise ValueError("goal reminder expiration must follow reminder time")
        if reminder_kind not in {"start_window", "check_in", "encouragement"}:
            raise ValueError("unsupported goal reminder kind")
        reminder_text = reminder_text.strip()
        if not reminder_text or len(reminder_text) > 500:
            raise ValueError("goal reminder text must contain 1 to 500 characters")
        with (nullcontext(_connection) if _connection is not None else self.repository.pool.connection()) as connection:
            row = connection.execute(
                """SELECT goal.*, event.content_hash AS source_event_content_hash,
                          event.recorded_at AS source_event_recorded_at,
                          head.revision AS preference_revision
                   FROM havre.goals AS goal
                   JOIN havre.events AS event
                     ON event.owner_id=goal.owner_id
                    AND event.event_id=goal.last_event_id
                   JOIN havre.proactive_preference_heads AS head
                     ON head.owner_id=goal.owner_id
                   WHERE goal.owner_id=%s AND goal.goal_id=%s""",
                (self.owner_id, goal_id),
            ).fetchone()
        if row is None:
            raise LookupError("current Goal or proactive preference not found")
        if row["status"] != "active":
            raise ValueError("only an active Goal may receive reminders")
        source_ref = f"goal:{goal_id}@{row['revision']}:{row['content_hash']}"
        command = ProactiveWorkCommand(
            trigger_type="owner_goal_reminder_due",
            source_kind="goal",
            source_refs=(source_ref,),
            subject_refs=(f"goal:{goal_id}",),
            category="owner_reminder",
            reason_code="owner_goal_reminder",
            reason_summary=reminder_text,
            intended_benefit=(
                "\u5728 owner \u4e3a\u5f53\u524d Goal \u9009\u62e9\u7684\u65f6\u95f4\u63d0\u4f9b\u4e00\u6b21\u6709\u7528\u4e14\u53ef\u53d6\u6d88\u7684\u63d0\u9192"
            ),
            data_policy=self.repository._policy_from_row(row),
            preference_revision=row["preference_revision"],
            execution_idempotency_key=f"owner-goal-reminder:{idempotency_key}",
            observed_at=row["source_event_recorded_at"],
            earliest_eligible_at=remind_at,
            expires_at=expires_at,
            deduplication_key=(
                f"goal-reminder:{goal_id}:{row['revision']}:"
                f"{reminder_kind}:{remind_at.isoformat()}"
            ),
            trigger_source_version="owner-goal-reminder-scheduler-v1",
            source_guard=ProactiveSourceGuard(
                source_event_id=row["last_event_id"],
                source_event_content_hash=row["source_event_content_hash"],
                projection_kind="goal",
                projection_id=goal_id,
                projection_revision=row["revision"],
                projection_content_hash=row["content_hash"],
            ),
        )
        work_item_id = self.enqueue_work(
            work_kind="scheduled",
            idempotency_key=idempotency_key,
            command=command,
            not_before=remind_at,
            supersede_reminder_slot=(goal_id, reminder_kind, remind_at)
            if supersede_existing_slot else None,
            _connection=_connection,
        )
        return {
            "work_item_id": work_item_id,
            "status": "pending",
            "goal_id": goal_id,
            "goal_revision": row["revision"],
            "reminder_kind": reminder_kind,
            "remind_at": remind_at,
            "expires_at": expires_at,
        }

    @staticmethod
    def _daily_goal_minute(*, owner_id: UUID, local_date) -> int:
        """Return one stable owner-local pseudo-random minute from 10:30 to 20:29."""
        material = f"{owner_id}:{local_date.isoformat()}:daily-goal-v2"
        value = int.from_bytes(
            hashlib.sha256(material.encode("utf-8")).digest()[:8], "big"
        )
        return 10 * 60 + 30 + value % (10 * 60)

    def enqueue_daily_goal_check_ins(
        self, *, timezone_name: str, now: datetime | None = None
    ) -> dict[str, object]:
        """Keep at most one supplemental Goal reminder ready per local day.

        A Goal becomes eligible only after the owner already authorized at least
        one reminder for it. Exact scheduled reminders remain independent; this
        filler selects at most one eligible Goal, preferring the nearest deadline.
        """
        instant = now or datetime.now(UTC)
        if instant.utcoffset() is None:
            raise ValueError("daily Goal scheduler time must be timezone-aware")
        zone = ZoneInfo(timezone_name)
        local_now = instant.astimezone(zone)
        today_minute = self._daily_goal_minute(
            owner_id=self.owner_id,
            local_date=local_now.date(),
        )
        today_slot = datetime.combine(
            local_now.date(),
            time(today_minute // 60, today_minute % 60),
            tzinfo=zone,
        )
        target_date = (
            local_now.date()
            if local_now <= today_slot
            else local_now.date() + timedelta(days=1)
        )
        minute = self._daily_goal_minute(
            owner_id=self.owner_id,
            local_date=target_date,
        )
        remind_local = datetime.combine(
            target_date, time(minute // 60, minute % 60), tzinfo=zone
        )
        with self.repository.pool.connection() as connection:
            goals = connection.execute(
                """SELECT goal.goal_id,goal.revision,goal.title,goal.review_at,
                          projection.deadline_at,
                          min((work.command_payload->>'earliest_eligible_at')::timestamptz)
                            AS reminder_start_at
                   FROM havre.goals goal
                   JOIN havre.proactive_work_items work
                     ON work.owner_id=goal.owner_id
                    AND work.command_payload->>'reason_code'='owner_goal_reminder'
                    AND work.command_payload#>>'{source_guard,projection_kind}'='goal'
                    AND work.command_payload#>>'{source_guard,projection_id}'=
                        goal.goal_id::text
                   LEFT JOIN havre.commitment_projections projection
                     ON projection.owner_id=goal.owner_id
                    AND projection.goal_id=goal.goal_id
                    AND projection.goal_revision=goal.revision
                   WHERE goal.owner_id=%s AND goal.status='active'
                   GROUP BY goal.goal_id,goal.revision,goal.title,goal.review_at,
                            projection.deadline_at
                   ORDER BY coalesce(projection.deadline_at,goal.review_at) NULLS LAST,
                            goal.goal_id""",
                (self.owner_id,),
            ).fetchall()
            daily_fill_exists = connection.execute(
                """SELECT EXISTS(
                       SELECT 1 FROM havre.proactive_work_items
                       WHERE owner_id=%s
                         AND idempotency_key LIKE %s
                         AND status IN (
                           'pending','retryable_failed','leased','succeeded'
                         )
                   ) AS value""",
                (self.owner_id, f"daily-goal-v2:%:{target_date.isoformat()}"),
            ).fetchone()["value"]
        scheduled: list[dict[str, object]] = []
        skipped_existing = 1 if daily_fill_exists else 0
        skipped_before_start = 0
        if daily_fill_exists:
            return {
                "eligible_goals": len(goals),
                "scheduled": 0,
                "scheduled_items": (),
                "skipped_existing": skipped_existing,
                "skipped_before_start": skipped_before_start,
            }
        for goal in goals:
            if target_date < goal["reminder_start_at"].astimezone(zone).date():
                skipped_before_start += 1
                continue
            with self.repository.pool.connection() as connection:
                slots = connection.execute(
                    """SELECT status,
                              (command_payload->>'earliest_eligible_at')::timestamptz
                                AS remind_at,
                              (command_payload#>>'{source_guard,projection_revision}')::int
                                AS goal_revision
                       FROM havre.proactive_work_items
                       WHERE owner_id=%s
                         AND command_payload->>'reason_code'='owner_goal_reminder'
                         AND command_payload#>>'{source_guard,projection_kind}'='goal'
                         AND command_payload#>>'{source_guard,projection_id}'=%s
                         AND status IN ('pending','retryable_failed','leased','succeeded')""",
                    (self.owner_id, str(goal["goal_id"])),
                ).fetchall()
            if any(
                slot["goal_revision"] == goal["revision"]
                and slot["remind_at"].astimezone(zone).date() == target_date
                for slot in slots
            ):
                skipped_existing += 1
                continue
            title = goal["title"].strip()
            reminder_text = (
                f"“{title[:420]}”还在进行中。今天记得给它留一点时间，"
                "做完也告诉我一声。"
            )
            scheduled.append(self.enqueue_goal_reminder(
                goal_id=goal["goal_id"],
                reminder_kind="check_in",
                reminder_text=reminder_text,
                remind_at=remind_local,
                expires_at=datetime.combine(
                    target_date, time(22, 0), tzinfo=zone
                ),
                idempotency_key=(
                    f"daily-goal-v2:{goal['goal_id']}:{goal['revision']}:"
                    f"{target_date.isoformat()}"
                ),
            ))
            break
        return {
            "eligible_goals": len(goals),
            "scheduled": len(scheduled),
            "scheduled_items": tuple(scheduled),
            "skipped_existing": skipped_existing,
            "skipped_before_start": skipped_before_start,
        }

    def enqueue_relationship_follow_up(
        self, *, run_id: UUID, source_event_id: UUID, source_kind: str,
        memory_ref: str | None, message: str, timezone_name: str,
        now: datetime | None = None,
    ) -> dict[str, object] | None:
        """Queue one evidence-bound relationship continuation for Core review.

        The model proposes wording only. The current owner preference and the
        normal Interruption Policy still decide whether anything is delivered.
        """
        if source_kind not in {"memory", "conversation"}:
            raise ValueError("relationship follow-up source must be Memory or conversation")
        message = message.strip()
        if not message or len(message) > 300:
            raise ValueError("relationship follow-up must contain 1 to 300 characters")
        instant = now or datetime.now(UTC)
        if instant.utcoffset() is None:
            raise ValueError("relationship follow-up time must be timezone-aware")
        zone = ZoneInfo(timezone_name)
        local_now = instant.astimezone(zone)
        eligible_local = datetime.combine(
            local_now.date(), time(11, 0), tzinfo=zone
        )
        if local_now >= eligible_local:
            eligible_local = local_now + timedelta(minutes=10)
        expires_local = datetime.combine(
            local_now.date(), time(21, 0), tzinfo=zone
        )
        if eligible_local >= expires_local:
            return None
        if self.relational_initiative_enabled:
            cadence = self.relationship_cadence_state(now=instant)
            if cadence["paused"] or cadence["active_pending_count"]:
                return None
            next_eligible_at = cadence["next_eligible_at"]
            if next_eligible_at is not None:
                cadence_local = next_eligible_at.astimezone(zone)
                eligible_local = max(eligible_local, cadence_local)
                if eligible_local.timetz().replace(tzinfo=None) < time(11, 0):
                    eligible_local = datetime.combine(
                        eligible_local.date(), time(11, 0), tzinfo=zone
                    )
                elif eligible_local.timetz().replace(tzinfo=None) >= time(21, 0):
                    eligible_local = datetime.combine(
                        eligible_local.date() + timedelta(days=1),
                        time(11, 0), tzinfo=zone,
                    )
                expires_local = datetime.combine(
                    eligible_local.date(), time(21, 0), tzinfo=zone
                )
                if eligible_local >= expires_local:
                    return None
        with self.repository.pool.connection() as connection:
            row = connection.execute(
                """SELECT event.*,head.revision AS preference_revision
                   FROM havre.events event
                   JOIN havre.proactive_preference_heads head
                     ON head.owner_id=event.owner_id
                   WHERE event.owner_id=%s AND event.event_id=%s
                     AND event.event_type='USER_MESSAGE'""",
                (self.owner_id, source_event_id),
            ).fetchone()
        if row is None:
            raise LookupError("relationship source Event or preference not found")
        source_refs = [f"event/{source_event_id}", f"diary-run/{run_id}"]
        if memory_ref is not None:
            source_refs.append(memory_ref)
        command = ProactiveWorkCommand(
            trigger_type="relationship_follow_up_due",
            source_kind=source_kind,
            source_refs=tuple(source_refs),
            subject_refs=(f"relationship:{source_event_id}",),
            category="relationship_follow_up",
            reason_code="relationship_follow_up",
            reason_summary=message,
            intended_benefit=(
                "自然延续 owner 真正在意的话题，以了解而非任务化的方式保持关系连续性"
            ),
            data_policy=self.repository._policy_from_row(row),
            preference_revision=row["preference_revision"],
            execution_idempotency_key=f"relationship-follow-up:{run_id}",
            observed_at=row["recorded_at"],
            earliest_eligible_at=eligible_local.astimezone(UTC),
            expires_at=expires_local.astimezone(UTC),
            deduplication_key=f"relationship-follow-up:{run_id}",
            trigger_source_version="experience-first-daily-review-v1",
            source_guard=ProactiveSourceGuard(
                source_event_id=source_event_id,
                source_event_content_hash=row["content_hash"],
            ),
        )
        work_item_id = self.enqueue_work(
            work_kind="scheduled",
            idempotency_key=f"relationship-follow-up:{run_id}",
            command=command,
            not_before=eligible_local.astimezone(UTC),
        )
        return {
            "work_item_id": work_item_id,
            "status": "pending",
            "source_event_id": source_event_id,
            "eligible_at": eligible_local.astimezone(UTC),
            "expires_at": expires_local.astimezone(UTC),
        }

    def enqueue_conversation_continuation(
        self, *, continuation_run_id: UUID, source_user_event_id: UUID,
        source_assistant_event_id: UUID, message: str, observed_at: datetime,
        expires_at: datetime, beat_index: int,
    ) -> UUID:
        """Create candidate work; callers are runtime-gated outside this store."""
        message = message.strip()
        if not 2 <= len(message) <= 300:
            raise ValueError("conversation continuation must contain 2 to 300 characters")
        if beat_index not in {1, 2}:
            raise ValueError("conversation continuation beat must be one or two")
        if observed_at.utcoffset() is None or expires_at.utcoffset() is None:
            raise ValueError("conversation continuation times must be timezone-aware")
        with self.repository.pool.connection() as connection:
            row = connection.execute(
                """SELECT user_event.*,assistant.content_hash AS assistant_content_hash,
                          head.revision AS preference_revision
                   FROM havre.events user_event
                   JOIN havre.events assistant
                     ON assistant.owner_id=user_event.owner_id
                    AND assistant.event_id=%s
                    AND assistant.event_type='ASSISTANT_MESSAGE'
                    AND assistant.causation_event_id=user_event.event_id
                   JOIN havre.proactive_preference_heads head
                     ON head.owner_id=user_event.owner_id
                   JOIN havre.owner_conversation_continuation_runs run
                     ON run.owner_id=user_event.owner_id
                    AND run.continuation_run_id=%s
                    AND run.source_user_event_id=user_event.event_id
                    AND run.source_assistant_event_id=assistant.event_id
                    AND run.beat_index=%s
                   WHERE user_event.owner_id=%s AND user_event.event_id=%s
                     AND user_event.event_type='USER_MESSAGE'""",
                (
                    source_assistant_event_id, continuation_run_id,
                    beat_index, self.owner_id, source_user_event_id,
                ),
            ).fetchone()
        if row is None:
            raise LookupError("continuation source turn or preference not found")
        now = datetime.now(UTC)
        if expires_at.astimezone(UTC) <= now:
            raise ValueError("conversation continuation already expired")
        command = ProactiveWorkCommand(
            trigger_type="conversation_continuation_due",
            source_kind="conversation",
            source_refs=(
                f"event/{source_user_event_id}",
                f"event/{source_assistant_event_id}",
                f"continuation-run/{continuation_run_id}",
            ),
            subject_refs=(f"relationship:{source_user_event_id}",),
            category="conversation_continuation",
            reason_code="conversation_continuation",
            reason_summary=message,
            intended_benefit=(
                "在正在发生的聊天里自然延续话题；第一段一分钟后，"
                "第二段仅在仍未回复时再等三十分钟"
            ),
            data_policy=self.repository._policy_from_row(row),
            preference_revision=row["preference_revision"],
            execution_idempotency_key=f"conversation-continuation:{continuation_run_id}",
            observed_at=observed_at.astimezone(UTC),
            earliest_eligible_at=now,
            expires_at=expires_at.astimezone(UTC),
            deduplication_key=f"conversation-continuation:{continuation_run_id}",
            trigger_source_version="conversation-continuation-v2",
            source_guard=ProactiveSourceGuard(
                source_event_id=source_user_event_id,
                source_event_content_hash=row["content_hash"],
            ),
        )
        return self.enqueue_work(
            work_kind="scheduled",
            idempotency_key=f"conversation-continuation:{continuation_run_id}",
            command=command,
            not_before=now,
        )

    def _source_guard_is_current(self, guard: ProactiveSourceGuard) -> bool:
        with self.repository.pool.connection() as connection:
            event = connection.execute(
                """SELECT content_hash FROM havre.events
                   WHERE owner_id=%s AND event_id=%s""",
                (self.owner_id, guard.source_event_id),
            ).fetchone()
            if event is None or event["content_hash"] != guard.source_event_content_hash:
                return False
            if guard.projection_kind == "none":
                return True
            if guard.projection_kind == "goal":
                projection = connection.execute(
                    """SELECT revision,content_hash,last_event_id,status
                       FROM havre.goals WHERE owner_id=%s AND goal_id=%s""",
                    (self.owner_id, guard.projection_id),
                ).fetchone()
                return bool(
                    projection is not None
                    and projection["revision"] == guard.projection_revision
                    and projection["content_hash"] == guard.projection_content_hash
                    and projection["last_event_id"] == guard.source_event_id
                    and projection["status"] == "active"
                )
            projection = connection.execute(
                """SELECT revision,content_hash,last_event_id,status,phase
                   FROM havre.scene_sessions
                   WHERE owner_id=%s AND scene_session_id=%s""",
                (self.owner_id, guard.projection_id),
            ).fetchone()
            return bool(
                projection is not None
                and projection["revision"] == guard.projection_revision
                and projection["content_hash"] == guard.projection_content_hash
                and projection["last_event_id"] == guard.source_event_id
                and projection["status"] == "planned"
                and projection["phase"] == "before"
            )

    def _relationship_conversation_is_current(
        self, command: ProactiveWorkCommand
    ) -> bool:
        if (
            command.category not in {
                "relationship_follow_up", "conversation_continuation"
            }
            or command.source_kind.value != "conversation"
        ):
            return True
        with self.repository.pool.connection() as connection:
            moved = connection.execute(
                """SELECT EXISTS(
                       SELECT 1 FROM havre.events event
                       JOIN havre.interaction_requests request
                         ON request.owner_id=event.owner_id
                        AND request.request_id=event.request_id
                       WHERE event.owner_id=%s AND event.event_type='USER_MESSAGE'
                         AND request.request_kind='interaction'
                         AND event.recorded_at>%s
                     ) AS value""",
                (self.owner_id, command.observed_at),
            ).fetchone()["value"]
        return not bool(moved)

    def _complete_work_cancelled(
        self, *, work_item_id: UUID, worker_id: str, error_code: str
    ) -> None:
        with self.repository.pool.connection() as connection, connection.transaction():
            updated = connection.execute(
                """UPDATE havre.proactive_work_items
                   SET status='cancelled',lease_owner=NULL,lease_expires_at=NULL,
                       last_error_code=%s,completed_at=statement_timestamp()
                   WHERE owner_id=%s AND work_item_id=%s
                     AND status='leased' AND lease_owner=%s
                   RETURNING work_item_id""",
                (error_code, self.owner_id, work_item_id, worker_id),
            ).fetchone()
            if updated is None:
                raise RuntimeError("proactive worker lost its lease before cancellation")

    def run_work_once(
        self, *, worker_id: str = "stage6-local-worker"
    ) -> dict[str, object] | None:
        with self.repository.pool.connection() as connection, connection.transaction():
            work = connection.execute(
                """
                WITH claimable AS (
                    SELECT work_item_id FROM havre.proactive_work_items
                    WHERE owner_id = %s AND not_before <= statement_timestamp()
                      AND (
                        status IN ('pending', 'retryable_failed')
                        OR (status = 'leased' AND lease_expires_at < statement_timestamp())
                      )
                    ORDER BY not_before, created_at, work_item_id
                    FOR UPDATE SKIP LOCKED LIMIT 1
                )
                UPDATE havre.proactive_work_items AS work
                SET status = 'leased', lease_owner = %s,
                    lease_expires_at = statement_timestamp() + interval '5 minutes',
                    attempt_count = attempt_count + 1
                FROM claimable
                WHERE work.work_item_id = claimable.work_item_id
                RETURNING work.*
                """,
                (self.owner_id, worker_id),
            ).fetchone()
        if work is None:
            return None
        try:
            command = ProactiveWorkCommand.model_validate(work["command_payload"])
            expected_arrival_epoch = None
            if self.commitment_broker is not None:
                expected_arrival_epoch = self.commitment_broker.standalone_epoch()
                if expected_arrival_epoch is None:
                    self._defer_work_for_conversation(
                        work_item_id=work["work_item_id"],
                        worker_id=worker_id,
                    )
                    return {
                        "work_item_id": work["work_item_id"],
                        "status": "deferred",
                        "error_code": "active_conversation",
                    }
            if command.source_guard is not None and not self._source_guard_is_current(
                command.source_guard
            ):
                self._complete_work_cancelled(
                    work_item_id=work["work_item_id"],
                    worker_id=worker_id,
                    error_code="proactive_source_no_longer_current",
                )
                return {
                    "work_item_id": work["work_item_id"],
                    "status": "cancelled",
                    "error_code": "proactive_source_no_longer_current",
                }
            if not self._relationship_conversation_is_current(command):
                self._complete_work_cancelled(
                    work_item_id=work["work_item_id"],
                    worker_id=worker_id,
                    error_code="relationship_conversation_moved",
                )
                return {
                    "work_item_id": work["work_item_id"],
                    "status": "cancelled",
                    "error_code": "relationship_conversation_moved",
                }
            result = self.execute_fixture(
                trigger_type=command.trigger_type,
                source_kind=command.source_kind.value,
                source_refs=command.source_refs,
                subject_refs=command.subject_refs,
                category=command.category,
                reason_code=command.reason_code,
                reason_summary=command.reason_summary,
                intended_benefit=command.intended_benefit,
                data_policy=command.data_policy,
                preference_revision=command.preference_revision,
                idempotency_key=command.execution_idempotency_key,
                observed_at=command.observed_at,
                earliest_eligible_at=command.earliest_eligible_at,
                expires_at=command.expires_at,
                deduplication_key=command.deduplication_key,
                trigger_source_version=command.trigger_source_version,
                traceparent=command.traceparent,
                expected_arrival_epoch=expected_arrival_epoch,
                work_item_id=work["work_item_id"],
            )
            self._complete_work_success(
                work_item_id=work["work_item_id"],
                worker_id=worker_id,
                request_id=result.request_id,
                proposal_id=result.proposal.proposal_id,
            )
            return {
                "work_item_id": work["work_item_id"],
                "status": "succeeded",
                "request_id": result.request_id,
                "proposal_id": result.proposal.proposal_id,
                "idempotent_replay": result.idempotent_replay,
            }
        except StalePersonalContextError:
            self._complete_work_cancelled(
                work_item_id=work["work_item_id"], worker_id=worker_id,
                error_code="personal_context_no_longer_current",
            )
            return {"work_item_id": work["work_item_id"], "status": "cancelled",
                    "error_code": "personal_context_no_longer_current"}
        except ActiveConversationDeferral:
            self._defer_work_for_conversation(
                work_item_id=work["work_item_id"],
                worker_id=worker_id,
            )
            return {
                "work_item_id": work["work_item_id"],
                "status": "deferred",
                "error_code": "user_arrival_suppressed_standalone",
            }
        except Exception:
            status = self._record_work_failure(
                work_item_id=work["work_item_id"],
                worker_id=worker_id,
                error_code="proactive_work_processing_error",
            )
            return {
                "work_item_id": work["work_item_id"],
                "status": status,
                "error_code": "proactive_work_processing_error",
            }

    def _defer_work_for_conversation(
        self, *, work_item_id: UUID, worker_id: str
    ) -> None:
        with self.repository.pool.connection() as connection, connection.transaction():
            updated = connection.execute(
                """
                UPDATE havre.proactive_work_items
                SET status='pending',lease_owner=NULL,lease_expires_at=NULL,
                    not_before=GREATEST(
                        not_before,statement_timestamp()+interval '2 minutes'
                    ),
                    last_error_code='active_conversation_deferred'
                WHERE owner_id=%s AND work_item_id=%s
                  AND status='leased' AND lease_owner=%s
                RETURNING work_item_id
                """,
                (self.owner_id,work_item_id,worker_id),
            ).fetchone()
            if updated is None:
                raise RuntimeError(
                    "proactive worker lost its lease before deferral"
                )

    def _complete_work_success(
        self,
        *,
        work_item_id: UUID,
        worker_id: str,
        request_id: UUID,
        proposal_id: UUID,
    ) -> None:
        with self.repository.pool.connection() as connection, connection.transaction():
            updated = connection.execute(
                """
                UPDATE havre.proactive_work_items
                SET status = 'succeeded', lease_owner = NULL,
                    lease_expires_at = NULL, request_id = %s, proposal_id = %s,
                    last_error_code = NULL, completed_at = statement_timestamp()
                WHERE owner_id = %s AND work_item_id = %s
                  AND status = 'leased' AND lease_owner = %s
                RETURNING work_item_id
                """,
                (
                    request_id,
                    proposal_id,
                    self.owner_id,
                    work_item_id,
                    worker_id,
                ),
            ).fetchone()
            if updated is None:
                raise RuntimeError("proactive worker lost its lease before completion")

    def _record_work_failure(
        self,
        *,
        work_item_id: UUID,
        worker_id: str,
        error_code: str,
    ) -> str:
        with self.repository.pool.connection() as connection, connection.transaction():
            row = connection.execute(
                """
                SELECT attempt_count, max_attempts
                FROM havre.proactive_work_items
                WHERE owner_id = %s AND work_item_id = %s
                  AND status = 'leased' AND lease_owner = %s
                FOR UPDATE
                """,
                (self.owner_id, work_item_id, worker_id),
            ).fetchone()
            if row is None:
                raise RuntimeError("proactive worker cannot record failure after lease loss")
            next_status = (
                "retryable_failed"
                if row["attempt_count"] < row["max_attempts"]
                else "terminal_failed"
            )
            connection.execute(
                """
                UPDATE havre.proactive_work_items
                SET status = %s, lease_owner = NULL, lease_expires_at = NULL,
                    last_error_code = %s,
                    completed_at = CASE WHEN %s = 'terminal_failed'
                                        THEN statement_timestamp() ELSE NULL END
                WHERE owner_id = %s AND work_item_id = %s
                """,
                (
                    next_status,
                    error_code,
                    next_status,
                    self.owner_id,
                    work_item_id,
                ),
            )
            return next_status

    def get(self, *, proposal_id: UUID) -> ProactiveLifecycleView:
        with self.repository.pool.connection() as connection:
            row = connection.execute(
                "SELECT request_id FROM havre.proactive_proposals WHERE owner_id = %s AND proposal_id = %s",
                (self.owner_id, proposal_id),
            ).fetchone()
            if row is None:
                raise LookupError("proactive proposal not found")
            return self._view(connection, request_id=row["request_id"], replay=False)

    def _view(self, connection, *, request_id: UUID, replay: bool) -> ProactiveLifecycleView:
        proposal_row = connection.execute(
            "SELECT * FROM havre.proactive_proposals WHERE owner_id = %s AND request_id = %s",
            (self.owner_id, request_id),
        ).fetchone()
        if proposal_row is None:
            raise RuntimeError("completed proactive request has no proposal")
        proposal = ProactiveProposal.model_validate(proposal_row["payload"])
        trigger_row = connection.execute(
            "SELECT payload FROM havre.proactive_triggers WHERE owner_id = %s AND trigger_id = %s",
            (self.owner_id, proposal.trigger_refs[0]),
        ).fetchone()
        decision_row = connection.execute(
            "SELECT * FROM havre.interruption_decisions WHERE owner_id = %s AND proposal_id = %s",
            (self.owner_id, proposal.proposal_id),
        ).fetchone()
        decision = InterruptionDecision.model_validate(decision_row["payload"])
        preference_row = connection.execute(
            "SELECT payload FROM havre.proactive_preference_revisions WHERE owner_id = %s AND preference_revision_id = %s",
            (self.owner_id, decision.preference_revision_id),
        ).fetchone()
        context_row = connection.execute(
            "SELECT payload FROM havre.proactive_context_packs WHERE owner_id = %s AND proposal_id = %s",
            (self.owner_id, proposal.proposal_id),
        ).fetchone()
        rendering_row = connection.execute(
            "SELECT payload FROM havre.rendered_proactive_messages WHERE owner_id = %s AND proposal_id = %s",
            (self.owner_id, proposal.proposal_id),
        ).fetchone()
        attempt_row = connection.execute(
            "SELECT payload FROM havre.proactive_delivery_attempts WHERE owner_id = %s AND proposal_id = %s",
            (self.owner_id, proposal.proposal_id),
        ).fetchone()
        inbox_row = connection.execute(
            "SELECT assistant_event_id FROM havre.proactive_inbox_messages WHERE owner_id = %s AND proposal_id = %s",
            (self.owner_id, proposal.proposal_id),
        ).fetchone()
        action_rows = connection.execute(
            """
            SELECT payload FROM havre.proactive_owner_actions
            WHERE owner_id = %s AND proposal_id = %s
            ORDER BY observed_at, action_id
            """,
            (self.owner_id, proposal.proposal_id),
        ).fetchall()
        lifecycle = connection.execute(
            """
            SELECT event_type FROM havre.proactive_lifecycle_events
            WHERE owner_id = %s AND (proposal_id = %s OR artifact_id = %s)
            ORDER BY recorded_at, lifecycle_event_id
            """,
            (self.owner_id, proposal.proposal_id, proposal.trigger_refs[0]),
        ).fetchall()
        return ProactiveLifecycleView(
            request_id=request_id,
            trace_id=proposal.trace_id,
            trigger=TriggerRecord.model_validate(trigger_row["payload"]),
            proposal=proposal,
            preference=ProactivePreferenceRevision.model_validate(preference_row["payload"]),
            decision=decision,
            context_pack=(ProactiveContextPack.model_validate(context_row["payload"]) if context_row else None),
            rendering=(RenderedProactiveMessage.model_validate(rendering_row["payload"]) if rendering_row else None),
            delivery_attempt=(DeliveryAttempt.model_validate(attempt_row["payload"]) if attempt_row else None),
            assistant_event_id=(inbox_row["assistant_event_id"] if inbox_row else None),
            owner_actions=tuple(
                ProactiveOwnerAction.model_validate(row["payload"])
                for row in action_rows
            ),
            lifecycle_events=tuple(row["event_type"] for row in lifecycle),
            idempotent_replay=replay,
        )
