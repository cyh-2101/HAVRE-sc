"""Atomic PostgreSQL Stage 6 proactive lifecycle and local inbox delivery."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb
from pydantic_core import to_jsonable_python

from companion.context.strategies import ControlledContextStrategy
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
    ProactiveWorkCommand,
    RenderedProactiveMessage,
    TriggerRecord,
)
from companion.proactive.policy import InterruptionPolicy
from companion.tracing import Span, TraceContext


class ProactivePostgresStore:
    service_version = "proactive-service-v1"

    def __init__(
        self,
        *,
        repository: PostgresRepository,
        owner_id: UUID,
        identity: IdentityBundle,
    ) -> None:
        self.repository = repository
        self.owner_id = owner_id
        self.identity = identity
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
        traceparent: str | None = None,
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
                source_version="stage6-fixture-trigger-v1",
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
                context_pack, rendering, attempt, assistant_event_id = self._render_and_deliver(
                    connection,
                    request_id=request_id,
                    session_id=session_id,
                    trigger=trigger,
                    proposal=proposal,
                    preference=preference,
                    decision=decision,
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
            row["global_count"],
            row["category_count"],
            row["last_equivalent"],
            duplicate,
            owner_action["action_type"] if owner_action else "none",
            owner_action["snooze_until"] if owner_action else None,
        )

    def _render_and_deliver(
        self, connection, *, request_id, session_id, trigger, proposal, preference, decision
    ):
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
        text = f"Reminder: {proposal.reason_summary}"[:500]
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
        return context_pack, rendering, attempt, event.event_id

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
    ) -> UUID:
        if not_before.utcoffset() is None:
            raise ValueError("proactive work not_before must be timezone-aware")
        work_item_id = uuid7()
        fingerprint = content_hash(
            {"work_kind": work_kind, "command": command.model_dump(mode="json")}
        )
        with self.repository.pool.connection() as connection, connection.transaction():
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
            return work_item_id

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
                traceparent=command.traceparent,
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
