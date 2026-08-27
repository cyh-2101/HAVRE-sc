"""PostgreSQL persistence for the Stage 5 Scene vertical slice."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from psycopg.types.json import Jsonb
from pydantic_core import to_jsonable_python

from companion.evidence import EvidenceRef, EvidenceRelation, EvidenceSourceKind
from companion.events import (
    DeliveryRecord,
    EventEnvelope,
    EventType,
    InterventionLifecyclePayload,
    SceneActionPayload,
    SceneGuidancePayload,
    SceneOutcomePayload,
    SceneReflectionPayload,
    SceneSessionLifecyclePayload,
    SceneSignalPayload,
    TextContentPart,
)
from companion.hashing import content_hash
from companion.ids import new_span_id, uuid7
from companion.identity import IdentityBundle
from companion.persistence.postgres import PostgresRepository
from companion.policy import DataPolicy, PrivacyClass, combine_policies
from companion.policy.intervention import (
    AvoidanceAssessment,
    CoercionAssessment,
    DangerAssessment,
    EnergyAssessment,
    GoalAlignment,
    GoalUrgency,
    InterventionContext,
    InterventionDecision,
    InterventionPolicy,
    SceneSignalType,
)
from companion.scenes.models import (
    AnticipatedTrigger,
    GuidanceOutcomeObservation,
    OutcomeHelpfulness,
    OutcomeTriState,
    SceneCommandResult,
    SceneGoal,
    ScenePhase,
    SceneRecord,
    SceneRecordType,
    SceneSession,
    SceneSituation,
    SceneStatus,
    SceneView,
)
from companion.tracing import Span, TraceContext


@dataclass(frozen=True)
class _Ingress:
    request_id: UUID
    session_id: UUID
    trace: TraceContext
    trace_started_at: datetime
    idempotency_key: str
    request_fingerprint: str
    operation: str


class ScenePostgresStore:
    """Atomic Scene commands over the repository's owner-qualified connection pool."""

    service_version = "scene-service-v1"
    guidance_renderer_version = "scene-guidance-template-v1"

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
        self.intervention_policy = InterventionPolicy(
            constitution_version_id=identity.constitution.version_id,
            identity_version_id=identity.identity.version_id,
            values_version_id=identity.values.version_id,
        )

    def _ingress(
        self,
        *,
        operation: str,
        semantic_input: dict[str, object],
        idempotency_key: str,
        session_id: UUID,
        traceparent: str | None,
    ) -> _Ingress:
        trace = TraceContext.from_traceparent(traceparent)
        return _Ingress(
            request_id=uuid7(),
            session_id=session_id,
            trace=trace,
            trace_started_at=datetime.now(UTC),
            idempotency_key=idempotency_key,
            request_fingerprint=content_hash(
                {
                    "service_version": self.service_version,
                    "operation": operation,
                    "semantic_input": to_jsonable_python(semantic_input),
                }
            ),
            operation=operation,
        )

    def _reserve(self, connection, ingress: _Ingress) -> tuple[bool, dict[str, Any]]:
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"{self.owner_id}:{ingress.idempotency_key}",),
        )
        existing = connection.execute(
            """
            SELECT * FROM havre.interaction_requests
            WHERE owner_id = %s AND idempotency_key = %s
            """,
            (self.owner_id, ingress.idempotency_key),
        ).fetchone()
        if existing is not None:
            if existing["request_fingerprint"] != ingress.request_fingerprint:
                raise ValueError("idempotency key was already used for a different Scene command")
            if existing["request_kind"] != "scene_command":
                raise ValueError("idempotency key belongs to a non-Scene request")
            if existing["status"] == "processing":
                raise RuntimeError("Scene command is still processing")
            if existing["status"] == "failed":
                raise RuntimeError("Scene command previously failed")
            return False, existing

        connection.execute(
            """
            INSERT INTO havre.sessions (session_id, owner_id, channel)
            VALUES (%s, %s, 'web')
            ON CONFLICT (session_id) DO UPDATE
                SET last_activity_at = statement_timestamp()
            """,
            (ingress.session_id, self.owner_id),
        )
        connection.execute(
            """
            INSERT INTO havre.traces (
                trace_id, owner_id, root_request_id, incoming_parent_span_id,
                trace_flags, started_at
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                ingress.trace.trace_id,
                self.owner_id,
                ingress.request_id,
                ingress.trace.parent_span_id,
                ingress.trace.trace_flags,
                ingress.trace_started_at,
            ),
        )
        row = connection.execute(
            """
            INSERT INTO havre.interaction_requests (
                request_id, owner_id, session_id, trace_id, idempotency_key,
                request_fingerprint, request_kind, status
            ) VALUES (%s, %s, %s, %s, %s, %s, 'scene_command', 'processing')
            RETURNING *
            """,
            (
                ingress.request_id,
                self.owner_id,
                ingress.session_id,
                ingress.trace.trace_id,
                ingress.idempotency_key,
                ingress.request_fingerprint,
            ),
        ).fetchone()
        return True, row

    @staticmethod
    def _complete_request(
        connection,
        *,
        ingress: _Ingress,
        owner_id: UUID,
        request_id: UUID,
        user_event_id: UUID,
        assistant_event_id: UUID | None = None,
    ) -> None:
        connection.execute(
            """
            UPDATE havre.interaction_requests
            SET status = 'completed', user_event_id = %s, assistant_event_id = %s,
                completed_at = statement_timestamp()
            WHERE owner_id = %s AND request_id = %s AND status = 'processing'
            """,
            (user_event_id, assistant_event_id, owner_id, request_id),
        )
        ended_at = datetime.now(UTC)
        PostgresRepository._insert_spans(
            connection,
            [
                Span(
                    trace_id=ingress.trace.trace_id,
                    span_id=new_span_id(),
                    parent_span_id=ingress.trace.parent_span_id,
                    name=f"scene.{ingress.operation}",
                    kind="server",
                    started_at=ingress.trace_started_at,
                    ended_at=ended_at,
                    duration_ms=round(
                        (ended_at - ingress.trace_started_at).total_seconds() * 1000,
                        3,
                    ),
                    status="ok",
                    attributes={
                        "scene_service_version": ScenePostgresStore.service_version,
                        "outreach_authorized": False,
                    },
                )
            ],
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

    def _existing_scene_id(self, connection, request_id: UUID) -> UUID:
        row = connection.execute(
            """
            SELECT scene_session_id FROM havre.events
            WHERE owner_id = %s AND request_id = %s AND scene_session_id IS NOT NULL
            ORDER BY recorded_at LIMIT 1
            """,
            (self.owner_id, request_id),
        ).fetchone()
        if row is None:
            raise RuntimeError("completed Scene command has no Scene event")
        return row["scene_session_id"]

    def _result(
        self,
        connection,
        *,
        request_id: UUID,
        trace_id: str,
        scene_session_id: UUID,
        replay: bool,
    ) -> SceneCommandResult:
        decision_row = connection.execute(
            """
            SELECT decision.*
            FROM havre.intervention_decisions AS decision
            JOIN havre.events AS event
              ON event.owner_id = decision.owner_id
             AND event.event_id = decision.decision_event_id
            WHERE decision.owner_id = %s AND event.request_id = %s
            ORDER BY decision.created_at DESC LIMIT 1
            """,
            (self.owner_id, request_id),
        ).fetchone()
        observation_row = connection.execute(
            """
            SELECT observation.*
            FROM havre.guidance_outcome_observations AS observation
            JOIN havre.events AS event
              ON event.owner_id = observation.owner_id
             AND event.event_id = observation.created_event_id
            WHERE observation.owner_id = %s AND event.request_id = %s
            ORDER BY observation.created_at DESC LIMIT 1
            """,
            (self.owner_id, request_id),
        ).fetchone()
        decision = self._decision_from_row(decision_row) if decision_row else None
        observation = (
            self._observation_from_row(observation_row) if observation_row else None
        )
        return SceneCommandResult(
            request_id=request_id,
            trace_id=trace_id.strip(),
            scene=self._view(connection, scene_session_id=scene_session_id),
            decision=decision,
            guidance_event_id=(decision_row["guidance_event_id"] if decision_row else None),
            outcome_observation=observation,
            idempotent_replay=replay,
        )

    def get(self, *, scene_session_id: UUID) -> SceneView:
        with self.repository.pool.connection() as connection:
            return self._view(connection, scene_session_id=scene_session_id)

    def _view(self, connection, *, scene_session_id: UUID) -> SceneView:
        root = connection.execute(
            "SELECT * FROM havre.scene_sessions WHERE owner_id = %s AND scene_session_id = %s",
            (self.owner_id, scene_session_id),
        ).fetchone()
        if root is None:
            raise LookupError("Scene Session not found")
        records = connection.execute(
            """
            SELECT * FROM havre.scene_records
            WHERE owner_id = %s AND scene_session_id = %s
            ORDER BY sequence_number
            """,
            (self.owner_id, scene_session_id),
        ).fetchall()
        decisions = connection.execute(
            """
            SELECT * FROM havre.intervention_decisions
            WHERE owner_id = %s AND scene_session_id = %s
            ORDER BY created_at, intervention_decision_id
            """,
            (self.owner_id, scene_session_id),
        ).fetchall()
        observations = connection.execute(
            """
            SELECT * FROM havre.guidance_outcome_observations
            WHERE owner_id = %s AND scene_session_id = %s
            ORDER BY created_at, outcome_observation_id
            """,
            (self.owner_id, scene_session_id),
        ).fetchall()
        return SceneView(
            scene_session=self._scene_from_row(root),
            records=tuple(self._record_from_row(row) for row in records),
            intervention_decisions=tuple(
                self._decision_from_row(row) for row in decisions
            ),
            outcome_observations=tuple(
                self._observation_from_row(row) for row in observations
            ),
        )

    @staticmethod
    def _scene_from_row(row: dict[str, Any]) -> SceneSession:
        return SceneSession(
            scene_session_id=row["scene_session_id"],
            owner_id=row["owner_id"],
            opened_session_id=row["opened_session_id"],
            scene_type=row["scene_type"],
            situation=SceneSituation.model_validate(row["situation"]),
            planned_goal=SceneGoal.model_validate(row["planned_goal"]),
            anticipated_triggers=tuple(
                AnticipatedTrigger.model_validate(value)
                for value in row["anticipated_triggers"]
            ),
            phase=row["phase"],
            status=row["status"],
            planned_start_at=row["planned_start_at"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            revision=row["revision"],
            created_event_id=row["created_event_id"],
            last_event_id=row["last_event_id"],
            trace_id=row["trace_id"].strip(),
            data_policy=PostgresRepository._policy_from_row(row),
            content_hash=row["content_hash"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _record_from_row(row: dict[str, Any]) -> SceneRecord:
        return SceneRecord(
            scene_record_id=row["scene_record_id"],
            owner_id=row["owner_id"],
            scene_session_id=row["scene_session_id"],
            record_type=row["record_type"],
            phase=row["phase"],
            sequence_number=row["sequence_number"],
            occurred_at=row["occurred_at"],
            event_id=row["event_id"],
            assistant_event_id=row["assistant_event_id"],
            artifact_kind=row["artifact_kind"],
            artifact_id=row["artifact_id"],
            artifact_revision=row["artifact_revision"],
            causal_predecessor_id=row["causal_predecessor_id"],
            source=row["source"],
            uncertainty_note=row["uncertainty_note"],
            content=row["content"],
            trace_id=row["trace_id"].strip(),
            data_policy=PostgresRepository._policy_from_row(row),
            content_hash=row["content_hash"],
            recorded_at=row["recorded_at"],
        )

    @staticmethod
    def _decision_from_row(row: dict[str, Any]) -> InterventionDecision:
        policy_row = dict(row)
        policy_row["policy_version"] = row["data_policy_version"]
        return InterventionDecision(
            intervention_decision_id=row["intervention_decision_id"],
            owner_id=row["owner_id"],
            scene_session_id=row["scene_session_id"],
            scene_revision=row["scene_revision"],
            input_event_id=row["input_event_id"],
            input_record_id=row["input_record_id"],
            phase=row["phase"],
            policy_version=row["policy_version_id"],
            policy_release_status=row["policy_release_status"],
            constitution_version_id=row["constitution_version_id"],
            identity_version_id=row["identity_version_id"],
            values_version_id=row["values_version_id"],
            branch=row["branch"],
            recommended_intervention=row["recommended_intervention"],
            response_style=row["response_style"],
            guidance=row["guidance"],
            minimum_action=row["minimum_action"],
            clarification_question=row["clarification_question"],
            reason_codes=tuple(row["reason_codes"]),
            required_constraints=tuple(row["required_constraints"]),
            outreach_authorized=row["outreach_authorized"],
            simulation_only=row["simulation_only"],
            trace_id=row["trace_id"].strip(),
            data_policy=PostgresRepository._policy_from_row(policy_row),
            content_hash=row["content_hash"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _observation_from_row(row: dict[str, Any]) -> GuidanceOutcomeObservation:
        return GuidanceOutcomeObservation(
            outcome_observation_id=row["outcome_observation_id"],
            owner_id=row["owner_id"],
            scene_session_id=row["scene_session_id"],
            intervention_decision_id=row["intervention_decision_id"],
            guidance_event_id=row["guidance_event_id"],
            action_record_id=row["action_record_id"],
            outcome_record_id=row["outcome_record_id"],
            reflection_record_id=row["reflection_record_id"],
            observation_window_started_at=row["observation_window_started_at"],
            observation_window_ended_at=row["observation_window_ended_at"],
            reporter=row["reporter"],
            action_attempted=row["action_attempted"],
            planned_scene_status=row["planned_scene_status"],
            helpfulness=row["helpfulness"],
            too_passive=row["too_passive"],
            too_forceful=row["too_forceful"],
            later_regret=row["later_regret"],
            limitations=tuple(row["limitations"]),
            consented=row["consented"],
            evidence_snapshot=tuple(row["evidence_snapshot"]),
            created_event_id=row["created_event_id"],
            trace_id=row["trace_id"].strip(),
            data_policy=PostgresRepository._policy_from_row(row),
            content_hash=row["content_hash"],
            created_at=row["created_at"],
        )

    def _insert_scene(self, connection, scene: SceneSession) -> None:
        policy = scene.data_policy
        connection.execute(
            """
            INSERT INTO havre.scene_sessions (
                scene_session_id, schema_version, owner_id, opened_session_id,
                scene_type, situation, planned_goal, anticipated_triggers,
                phase, status, planned_start_at, started_at, ended_at, revision,
                created_event_id, last_event_id, trace_id, privacy_class,
                memory_eligible, training_eligible, cloud_eligible, policy_version,
                policy_revision_id, policy_decision_source,
                policy_authorization_ref, content_hash, created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                scene.scene_session_id,
                scene.schema_version,
                scene.owner_id,
                scene.opened_session_id,
                scene.scene_type,
                Jsonb(scene.situation.model_dump(mode="json")),
                Jsonb(scene.planned_goal.model_dump(mode="json")),
                Jsonb(
                    [value.model_dump(mode="json") for value in scene.anticipated_triggers]
                ),
                scene.phase.value,
                scene.status.value,
                scene.planned_start_at,
                scene.started_at,
                scene.ended_at,
                scene.revision,
                scene.created_event_id,
                scene.last_event_id,
                scene.trace_id,
                *self._policy_columns(policy),
                scene.content_hash,
                scene.created_at,
                scene.updated_at,
            ),
        )

    def _insert_record(self, connection, record: SceneRecord) -> None:
        policy = record.data_policy
        connection.execute(
            """
            INSERT INTO havre.scene_records (
                scene_record_id, schema_version, owner_id, scene_session_id,
                record_type, phase, sequence_number, occurred_at, recorded_at,
                event_id, assistant_event_id, artifact_kind, artifact_id,
                artifact_revision, causal_predecessor_id, source, uncertainty_note,
                content, trace_id, privacy_class, memory_eligible, training_eligible,
                cloud_eligible, policy_version, policy_revision_id,
                policy_decision_source, policy_authorization_ref, content_hash
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                record.scene_record_id,
                record.schema_version,
                record.owner_id,
                record.scene_session_id,
                record.record_type.value,
                record.phase,
                record.sequence_number,
                record.occurred_at,
                record.recorded_at,
                record.event_id,
                record.assistant_event_id,
                record.artifact_kind,
                record.artifact_id,
                record.artifact_revision,
                record.causal_predecessor_id,
                record.source,
                record.uncertainty_note,
                Jsonb(record.content),
                record.trace_id,
                *self._policy_columns(policy),
                record.content_hash,
            ),
        )

    def _insert_decision(
        self,
        connection,
        *,
        decision: InterventionDecision,
        decision_event_id: UUID,
        guidance_event_id: UUID,
        evidence: tuple[EvidenceRef, ...],
    ) -> None:
        policy = decision.data_policy
        connection.execute(
            """
            INSERT INTO havre.intervention_decisions (
                intervention_decision_id, schema_version, owner_id,
                scene_session_id, scene_revision, input_event_id, input_record_id,
                decision_event_id, guidance_event_id, phase, policy_version_id,
                policy_release_status, constitution_version_id, identity_version_id,
                values_version_id, branch, recommended_intervention,
                response_style, guidance, minimum_action, clarification_question,
                reason_codes, required_constraints, outreach_authorized,
                simulation_only, evidence_snapshot, trace_id, privacy_class,
                memory_eligible, training_eligible, cloud_eligible,
                data_policy_version, policy_revision_id, policy_decision_source,
                policy_authorization_ref, content_hash, created_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                decision.intervention_decision_id,
                decision.schema_version,
                decision.owner_id,
                decision.scene_session_id,
                decision.scene_revision,
                decision.input_event_id,
                decision.input_record_id,
                decision_event_id,
                guidance_event_id,
                decision.phase,
                decision.policy_version,
                decision.policy_release_status,
                decision.constitution_version_id,
                decision.identity_version_id,
                decision.values_version_id,
                decision.branch.value,
                decision.recommended_intervention,
                decision.response_style,
                decision.guidance,
                decision.minimum_action,
                decision.clarification_question,
                Jsonb(list(decision.reason_codes)),
                Jsonb(list(decision.required_constraints)),
                decision.outreach_authorized,
                decision.simulation_only,
                Jsonb([value.model_dump(mode="json") for value in evidence]),
                decision.trace_id,
                policy.privacy_class.value,
                policy.memory_eligible,
                policy.training_eligible,
                policy.cloud_eligible,
                policy.policy_version,
                policy.policy_revision_id,
                policy.decision_source,
                policy.authorization_ref,
                decision.content_hash,
                decision.created_at,
            ),
        )

    @staticmethod
    def _insert_evidence_edges(
        connection,
        *,
        owner_id: UUID,
        evidence: tuple[EvidenceRef, ...],
        derived_kind: str,
        derived_id: UUID,
        created_event_id: UUID,
        trace_id: str,
        transform_name: str,
        transform_version: str,
    ) -> None:
        for reference in evidence:
            connection.execute(
                """
                INSERT INTO havre.provenance_edges (
                    provenance_edge_id, schema_version, owner_id, source_kind,
                    source_id, source_revision, derived_kind, derived_id,
                    derived_revision, relation, weight, transform_name,
                    transform_version, created_event_id, trace_id
                ) VALUES (%s, 1, %s, %s, %s, %s, %s, %s, NULL,
                          %s, %s, %s, %s, %s, %s)
                """,
                (
                    uuid7(),
                    owner_id,
                    reference.source_kind.value,
                    reference.source_id,
                    reference.source_revision,
                    derived_kind,
                    derived_id,
                    reference.relation.value,
                    reference.weight,
                    transform_name,
                    transform_version,
                    created_event_id,
                    trace_id,
                ),
            )

    def _persist_intervention(
        self,
        connection,
        *,
        scene: SceneSession,
        ingress: _Ingress,
        input_event_id: UUID,
        input_record_id: UUID | None,
        signal_type: SceneSignalType | None,
        danger: DangerAssessment,
        avoidance: AvoidanceAssessment,
        energy: EnergyAssessment,
        coercion: CoercionAssessment,
        goal_alignment: GoalAlignment,
        goal_urgency: GoalUrgency,
        evidence: tuple[EvidenceRef, ...],
        policy: DataPolicy,
    ) -> tuple[InterventionDecision, UUID, SceneRecord]:
        decision_id = uuid7()
        record_id = uuid7()
        decision_event_id = uuid7()
        guidance_event_id = uuid7()
        now = datetime.now(UTC)
        decision = self.intervention_policy.decide(
            InterventionContext(
                owner_id=self.owner_id,
                scene_session_id=scene.scene_session_id,
                scene_revision=scene.revision,
                phase=scene.phase.value,
                situation_summary=scene.situation.summary,
                planned_objective=scene.planned_goal.objective,
                minimum_success=scene.planned_goal.minimum_success,
                signal_type=signal_type,
                danger=danger,
                avoidance=avoidance,
                energy=energy,
                coercion=coercion,
                goal_alignment=goal_alignment,
                goal_urgency=goal_urgency,
                input_event_id=input_event_id,
                input_record_id=input_record_id,
                trace_id=ingress.trace.trace_id,
                data_policy=policy,
            ),
            decision_id=decision_id,
            created_at=now,
        )
        decision_event = EventEnvelope(
            event_id=decision_event_id,
            event_type=EventType.INTERVENTION_DECIDED,
            owner_id=self.owner_id,
            session_id=ingress.session_id,
            scene_session_id=scene.scene_session_id,
            request_id=ingress.request_id,
            trace_id=ingress.trace.trace_id,
            causation_event_id=input_event_id,
            data_policy=policy,
            payload=InterventionLifecyclePayload(
                scene_session_id=scene.scene_session_id,
                intervention_decision_id=decision_id,
                scene_record_id=record_id,
                input_record_id=input_record_id,
                guidance_event_id=guidance_event_id,
                branch=decision.branch.value,
            ),
        )
        guidance_event = EventEnvelope(
            event_id=guidance_event_id,
            event_type=EventType.ASSISTANT_MESSAGE,
            owner_id=self.owner_id,
            session_id=ingress.session_id,
            scene_session_id=scene.scene_session_id,
            request_id=ingress.request_id,
            trace_id=ingress.trace.trace_id,
            causation_event_id=decision_event_id,
            data_policy=policy,
            payload=SceneGuidancePayload(
                content_parts=(TextContentPart(text=decision.guidance),),
                intervention_decision_id=decision_id,
                delivery=DeliveryRecord(
                    channel="web", first_visible_at=now, completed_at=now
                ),
            ),
        )
        PostgresRepository._insert_event(connection, decision_event)
        PostgresRepository._insert_event(connection, guidance_event)
        self._insert_decision(
            connection,
            decision=decision,
            decision_event_id=decision_event_id,
            guidance_event_id=guidance_event_id,
            evidence=evidence,
        )
        sequence = connection.execute(
            """
            SELECT COALESCE(max(sequence_number), 0) + 1 AS value
            FROM havre.scene_records
            WHERE owner_id = %s AND scene_session_id = %s
            """,
            (self.owner_id, scene.scene_session_id),
        ).fetchone()["value"]
        record = SceneRecord(
            scene_record_id=record_id,
            owner_id=self.owner_id,
            scene_session_id=scene.scene_session_id,
            record_type=SceneRecordType.INTERVENTION,
            phase=scene.phase.value,
            sequence_number=sequence,
            occurred_at=now,
            event_id=decision_event_id,
            assistant_event_id=guidance_event_id,
            artifact_kind="intervention_decision",
            artifact_id=decision_id,
            artifact_revision=1,
            causal_predecessor_id=input_record_id,
            source="intervention_policy",
            content={
                "branch": decision.branch.value,
                "recommended_intervention": decision.recommended_intervention,
                "guidance": decision.guidance,
                "minimum_action": decision.minimum_action,
                "reason_codes": list(decision.reason_codes),
                "outreach_authorized": False,
                "simulation_only": True,
            },
            trace_id=ingress.trace.trace_id,
            data_policy=policy,
            recorded_at=now,
        )
        self._insert_record(connection, record)
        self._insert_evidence_edges(
            connection,
            owner_id=self.owner_id,
            evidence=evidence,
            derived_kind="intervention_decision",
            derived_id=decision_id,
            created_event_id=decision_event_id,
            trace_id=ingress.trace.trace_id,
            transform_name="intervention_policy",
            transform_version=self.intervention_policy.version,
        )
        return decision, guidance_event_id, record

    def create(
        self,
        *,
        scene_type: str,
        situation: SceneSituation,
        planned_goal: SceneGoal,
        anticipated_triggers: tuple[AnticipatedTrigger, ...],
        danger: DangerAssessment,
        avoidance: AvoidanceAssessment,
        energy: EnergyAssessment,
        coercion: CoercionAssessment,
        goal_alignment: GoalAlignment,
        goal_urgency: GoalUrgency,
        privacy_class: PrivacyClass,
        memory_eligible: bool,
        planned_start_at: datetime | None,
        session_id: UUID | None,
        idempotency_key: str,
        traceparent: str | None,
    ) -> SceneCommandResult:
        actual_session_id = session_id or uuid7()
        semantic_input = {
            "scene_type": scene_type,
            "situation": situation.model_dump(mode="json"),
            "planned_goal": planned_goal.model_dump(mode="json"),
            "anticipated_triggers": [
                value.model_dump(mode="json") for value in anticipated_triggers
            ],
            "danger": danger.value,
            "avoidance": avoidance.value,
            "energy": energy.value,
            "coercion": coercion.value,
            "goal_alignment": goal_alignment.value,
            "goal_urgency": goal_urgency.value,
            "privacy_class": privacy_class.value,
            "memory_eligible": memory_eligible,
            "planned_start_at": planned_start_at,
            "session_id": session_id,
        }
        ingress = self._ingress(
            operation="create_scene",
            semantic_input=semantic_input,
            idempotency_key=idempotency_key,
            session_id=actual_session_id,
            traceparent=traceparent,
        )
        with self.repository.pool.connection() as connection, connection.transaction():
            created, request = self._reserve(connection, ingress)
            if not created:
                scene_id = self._existing_scene_id(connection, request["request_id"])
                return self._result(
                    connection,
                    request_id=request["request_id"],
                    trace_id=request["trace_id"],
                    scene_session_id=scene_id,
                    replay=True,
                )
            scene_id = uuid7()
            planned_event_id = uuid7()
            policy = DataPolicy.owner_default(
                privacy_class, memory_eligible=memory_eligible
            )
            planned_event = EventEnvelope(
                event_id=planned_event_id,
                event_type=EventType.SCENE_SESSION_PLANNED,
                owner_id=self.owner_id,
                session_id=actual_session_id,
                scene_session_id=scene_id,
                request_id=ingress.request_id,
                trace_id=ingress.trace.trace_id,
                data_policy=policy,
                payload=SceneSessionLifecyclePayload(
                    scene_session_id=scene_id,
                    scene_revision=1,
                    action="planned",
                    phase="before",
                    status="planned",
                    reason="Owner created a Web-simulated Scene Session",
                    situation=situation.model_dump(mode="json"),
                    planned_goal=planned_goal.model_dump(mode="json"),
                    anticipated_triggers=tuple(
                        value.model_dump(mode="json") for value in anticipated_triggers
                    ),
                ),
            )
            PostgresRepository._insert_event(connection, planned_event)
            scene = SceneSession(
                scene_session_id=scene_id,
                owner_id=self.owner_id,
                opened_session_id=actual_session_id,
                scene_type=scene_type,
                situation=situation,
                planned_goal=planned_goal,
                anticipated_triggers=anticipated_triggers,
                phase=ScenePhase.BEFORE,
                status=SceneStatus.PLANNED,
                planned_start_at=planned_start_at,
                revision=1,
                created_event_id=planned_event_id,
                last_event_id=planned_event_id,
                trace_id=ingress.trace.trace_id,
                data_policy=policy,
            )
            self._insert_scene(connection, scene)
            evidence = (
                EvidenceRef(
                    source_kind=EvidenceSourceKind.EVENT,
                    source_id=planned_event_id,
                    relation=EvidenceRelation.SUPPORTS,
                ),
            )
            decision_policy = combine_policies((policy,))
            decision, guidance_event_id, _ = self._persist_intervention(
                connection,
                scene=scene,
                ingress=ingress,
                input_event_id=planned_event_id,
                input_record_id=None,
                signal_type=None,
                danger=danger,
                avoidance=avoidance,
                energy=energy,
                coercion=coercion,
                goal_alignment=goal_alignment,
                goal_urgency=goal_urgency,
                evidence=evidence,
                policy=decision_policy,
            )
            self._complete_request(
                connection,
                ingress=ingress,
                owner_id=self.owner_id,
                request_id=ingress.request_id,
                user_event_id=planned_event_id,
                assistant_event_id=guidance_event_id,
            )
            return self._result(
                connection,
                request_id=ingress.request_id,
                trace_id=ingress.trace.trace_id,
                scene_session_id=scene_id,
                replay=False,
            )

    def transition(
        self,
        *,
        scene_session_id: UUID,
        expected_revision: int,
        action: Literal["start", "pause", "resume", "after", "close"],
        reason: str,
        terminal_status: Literal["completed", "abandoned", "cancelled"] | None,
        idempotency_key: str,
        traceparent: str | None,
    ) -> SceneCommandResult:
        initial = self.get(scene_session_id=scene_session_id).scene_session
        semantic_input = {
            "scene_session_id": scene_session_id,
            "expected_revision": expected_revision,
            "action": action,
            "reason": reason,
            "terminal_status": terminal_status,
        }
        ingress = self._ingress(
            operation="transition_scene",
            semantic_input=semantic_input,
            idempotency_key=idempotency_key,
            session_id=initial.opened_session_id,
            traceparent=traceparent,
        )
        with self.repository.pool.connection() as connection, connection.transaction():
            created, request = self._reserve(connection, ingress)
            if not created:
                return self._result(
                    connection,
                    request_id=request["request_id"],
                    trace_id=request["trace_id"],
                    scene_session_id=scene_session_id,
                    replay=True,
                )
            row = connection.execute(
                """
                SELECT * FROM havre.scene_sessions
                WHERE owner_id = %s AND scene_session_id = %s
                FOR UPDATE
                """,
                (self.owner_id, scene_session_id),
            ).fetchone()
            if row is None:
                raise LookupError("Scene Session not found")
            current = self._scene_from_row(row)
            if current.revision != expected_revision:
                raise ValueError("Scene revision precondition failed")
            database_now = connection.execute(
                "SELECT transaction_timestamp() AS value"
            ).fetchone()["value"]
            next_phase: ScenePhase
            next_status: SceneStatus
            event_type: EventType
            lifecycle_action: str
            started_at = current.started_at
            ended_at = None
            if action == "start":
                if current.phase is not ScenePhase.BEFORE or current.status is not SceneStatus.PLANNED:
                    raise ValueError("only a planned Before Scene may start")
                next_phase, next_status = ScenePhase.DURING, SceneStatus.ACTIVE
                event_type, lifecycle_action = EventType.SCENE_SESSION_STARTED, "started"
                started_at = database_now
            elif action == "pause":
                if current.phase is not ScenePhase.DURING or current.status is not SceneStatus.ACTIVE:
                    raise ValueError("only an active During Scene may pause")
                next_phase, next_status = ScenePhase.DURING, SceneStatus.PAUSED
                event_type, lifecycle_action = EventType.SCENE_SESSION_PAUSED, "paused"
            elif action == "resume":
                if current.phase is not ScenePhase.DURING or current.status is not SceneStatus.PAUSED:
                    raise ValueError("only a paused During Scene may resume")
                next_phase, next_status = ScenePhase.DURING, SceneStatus.ACTIVE
                event_type, lifecycle_action = EventType.SCENE_SESSION_STARTED, "resumed"
            elif action == "after":
                if current.phase is not ScenePhase.DURING or current.status is not SceneStatus.ACTIVE:
                    raise ValueError("only an active During Scene may enter After")
                next_phase, next_status = ScenePhase.AFTER, SceneStatus.ACTIVE
                event_type, lifecycle_action = EventType.SCENE_PHASE_CHANGED, "phase_changed"
            else:
                if terminal_status is None:
                    raise ValueError("closing a Scene requires an explicit terminal status")
                if not (
                    (current.phase is ScenePhase.AFTER and current.status is SceneStatus.ACTIVE)
                    or (
                        current.phase is ScenePhase.BEFORE
                        and current.status is SceneStatus.PLANNED
                        and terminal_status == "cancelled"
                    )
                ):
                    raise ValueError("Scene may close after After, or cancel while planned")
                next_phase, next_status = ScenePhase.CLOSED, SceneStatus(terminal_status)
                event_type, lifecycle_action = EventType.SCENE_SESSION_ENDED, "ended"
                ended_at = database_now

            event = EventEnvelope(
                event_type=event_type,
                owner_id=self.owner_id,
                session_id=current.opened_session_id,
                scene_session_id=scene_session_id,
                request_id=ingress.request_id,
                trace_id=ingress.trace.trace_id,
                causation_event_id=current.last_event_id,
                data_policy=current.data_policy,
                payload=SceneSessionLifecyclePayload(
                    scene_session_id=scene_session_id,
                    scene_revision=expected_revision + 1,
                    action=lifecycle_action,
                    phase=next_phase.value,
                    status=next_status.value,
                    reason=reason,
                ),
            )
            PostgresRepository._insert_event(connection, event)
            next_scene = SceneSession(
                scene_session_id=current.scene_session_id,
                owner_id=current.owner_id,
                opened_session_id=current.opened_session_id,
                scene_type=current.scene_type,
                situation=current.situation,
                planned_goal=current.planned_goal,
                anticipated_triggers=current.anticipated_triggers,
                phase=next_phase,
                status=next_status,
                planned_start_at=current.planned_start_at,
                started_at=started_at,
                ended_at=ended_at,
                revision=expected_revision + 1,
                created_event_id=current.created_event_id,
                last_event_id=event.event_id,
                trace_id=current.trace_id,
                data_policy=current.data_policy,
                created_at=current.created_at,
                updated_at=database_now,
            )
            connection.execute(
                """
                UPDATE havre.scene_sessions
                SET phase = %s, status = %s, started_at = %s, ended_at = %s,
                    revision = %s, last_event_id = %s, content_hash = %s,
                    updated_at = %s
                WHERE owner_id = %s AND scene_session_id = %s AND revision = %s
                """,
                (
                    next_scene.phase.value,
                    next_scene.status.value,
                    next_scene.started_at,
                    next_scene.ended_at,
                    next_scene.revision,
                    next_scene.last_event_id,
                    next_scene.content_hash,
                    next_scene.updated_at,
                    self.owner_id,
                    scene_session_id,
                    expected_revision,
                ),
            )
            guidance_event_id: UUID | None = None
            if action == "after":
                evidence = (
                    EvidenceRef(
                        source_kind=EvidenceSourceKind.EVENT,
                        source_id=current.created_event_id,
                        relation=EvidenceRelation.SUPPORTS,
                    ),
                    EvidenceRef(
                        source_kind=EvidenceSourceKind.EVENT,
                        source_id=event.event_id,
                        relation=EvidenceRelation.SUPPORTS,
                    ),
                )
                _, guidance_event_id, _ = self._persist_intervention(
                    connection,
                    scene=next_scene,
                    ingress=ingress,
                    input_event_id=event.event_id,
                    input_record_id=None,
                    signal_type=None,
                    danger=DangerAssessment.LOW,
                    avoidance=AvoidanceAssessment.UNKNOWN,
                    energy=EnergyAssessment.UNKNOWN,
                    coercion=CoercionAssessment.ABSENT,
                    goal_alignment=GoalAlignment.ACTIVE_MEANINGFUL,
                    goal_urgency=GoalUrgency.UNKNOWN,
                    evidence=evidence,
                    policy=combine_policies((current.data_policy,)),
                )
            self._complete_request(
                connection,
                ingress=ingress,
                owner_id=self.owner_id,
                request_id=ingress.request_id,
                user_event_id=event.event_id,
                assistant_event_id=guidance_event_id,
            )
            return self._result(
                connection,
                request_id=ingress.request_id,
                trace_id=ingress.trace.trace_id,
                scene_session_id=scene_session_id,
                replay=False,
            )

    def signal(
        self,
        *,
        scene_session_id: UUID,
        expected_revision: int,
        signal_type: SceneSignalType,
        danger: DangerAssessment,
        avoidance: AvoidanceAssessment,
        energy: EnergyAssessment,
        coercion: CoercionAssessment,
        goal_alignment: GoalAlignment,
        goal_urgency: GoalUrgency,
        privacy_class: PrivacyClass,
        memory_eligible: bool,
        occurred_at: datetime,
        uncertainty_note: str | None,
        idempotency_key: str,
        traceparent: str | None,
    ) -> SceneCommandResult:
        initial = self.get(scene_session_id=scene_session_id).scene_session
        semantic_input = {
            "scene_session_id": scene_session_id,
            "expected_revision": expected_revision,
            "signal_type": signal_type.value,
            "danger": danger.value,
            "avoidance": avoidance.value,
            "energy": energy.value,
            "coercion": coercion.value,
            "goal_alignment": goal_alignment.value,
            "goal_urgency": goal_urgency.value,
            "privacy_class": privacy_class.value,
            "memory_eligible": memory_eligible,
            "occurred_at": occurred_at,
            "uncertainty_note": uncertainty_note,
        }
        ingress = self._ingress(
            operation="scene_signal",
            semantic_input=semantic_input,
            idempotency_key=idempotency_key,
            session_id=initial.opened_session_id,
            traceparent=traceparent,
        )
        with self.repository.pool.connection() as connection, connection.transaction():
            created, request = self._reserve(connection, ingress)
            if not created:
                return self._result(
                    connection,
                    request_id=request["request_id"],
                    trace_id=request["trace_id"],
                    scene_session_id=scene_session_id,
                    replay=True,
                )
            row = connection.execute(
                """
                SELECT * FROM havre.scene_sessions
                WHERE owner_id = %s AND scene_session_id = %s FOR UPDATE
                """,
                (self.owner_id, scene_session_id),
            ).fetchone()
            if row is None:
                raise LookupError("Scene Session not found")
            scene = self._scene_from_row(row)
            if scene.revision != expected_revision:
                raise ValueError("Scene revision precondition failed")
            if scene.phase is not ScenePhase.DURING or scene.status is not SceneStatus.ACTIVE:
                raise ValueError("low-bandwidth signals require an active During Scene")
            signal_policy = DataPolicy.owner_default(
                privacy_class, memory_eligible=memory_eligible
            )
            signal_record_id = uuid7()
            signal_event = EventEnvelope(
                event_type=EventType.USER_SIGNAL,
                owner_id=self.owner_id,
                session_id=scene.opened_session_id,
                scene_session_id=scene_session_id,
                request_id=ingress.request_id,
                trace_id=ingress.trace.trace_id,
                causation_event_id=scene.last_event_id,
                data_policy=signal_policy,
                payload=SceneSignalPayload(
                    scene_session_id=scene_session_id,
                    scene_record_id=signal_record_id,
                    signal_type=signal_type.value,
                    danger=danger.value,
                    avoidance=avoidance.value,
                    energy=energy.value,
                    coercion=coercion.value,
                    goal_alignment=goal_alignment.value,
                    goal_urgency=goal_urgency.value,
                    occurred_at=occurred_at,
                ),
            )
            PostgresRepository._insert_event(connection, signal_event)
            sequence = connection.execute(
                """
                SELECT COALESCE(max(sequence_number), 0) + 1 AS value
                FROM havre.scene_records
                WHERE owner_id = %s AND scene_session_id = %s
                """,
                (self.owner_id, scene_session_id),
            ).fetchone()["value"]
            signal_record = SceneRecord(
                scene_record_id=signal_record_id,
                owner_id=self.owner_id,
                scene_session_id=scene_session_id,
                record_type=SceneRecordType.SIGNAL,
                phase="during",
                sequence_number=sequence,
                occurred_at=occurred_at,
                event_id=signal_event.event_id,
                source="web_simulation",
                uncertainty_note=uncertainty_note,
                content={
                    "signal_type": signal_type.value,
                    "danger": danger.value,
                    "avoidance": avoidance.value,
                    "energy": energy.value,
                    "coercion": coercion.value,
                    "goal_alignment": goal_alignment.value,
                    "goal_urgency": goal_urgency.value,
                    "input_method": "web_simulation",
                },
                trace_id=ingress.trace.trace_id,
                data_policy=signal_policy,
            )
            self._insert_record(connection, signal_record)
            root_ref = EvidenceRef(
                source_kind=EvidenceSourceKind.EVENT,
                source_id=scene.created_event_id,
                relation=EvidenceRelation.SUPPORTS,
            )
            signal_ref = EvidenceRef(
                source_kind=EvidenceSourceKind.EVENT,
                source_id=signal_event.event_id,
                relation=EvidenceRelation.SUPPORTS,
            )
            decision_policy = combine_policies((scene.data_policy, signal_policy))
            _, guidance_event_id, _ = self._persist_intervention(
                connection,
                scene=scene,
                ingress=ingress,
                input_event_id=signal_event.event_id,
                input_record_id=signal_record_id,
                signal_type=signal_type,
                danger=danger,
                avoidance=avoidance,
                energy=energy,
                coercion=coercion,
                goal_alignment=goal_alignment,
                goal_urgency=goal_urgency,
                evidence=(root_ref, signal_ref),
                policy=decision_policy,
            )
            self._complete_request(
                connection,
                ingress=ingress,
                owner_id=self.owner_id,
                request_id=ingress.request_id,
                user_event_id=signal_event.event_id,
                assistant_event_id=guidance_event_id,
            )
            return self._result(
                connection,
                request_id=ingress.request_id,
                trace_id=ingress.trace.trace_id,
                scene_session_id=scene_session_id,
                replay=False,
            )

    def record_action(
        self,
        *,
        scene_session_id: UUID,
        expected_revision: int,
        action_text: str,
        action_attempted: OutcomeTriState,
        occurred_at: datetime,
        privacy_class: PrivacyClass,
        memory_eligible: bool,
        uncertainty_note: str | None,
        idempotency_key: str,
        traceparent: str | None,
    ) -> SceneCommandResult:
        initial = self.get(scene_session_id=scene_session_id).scene_session
        semantic_input = {
            "scene_session_id": scene_session_id,
            "expected_revision": expected_revision,
            "action_text": action_text,
            "action_attempted": action_attempted.value,
            "occurred_at": occurred_at,
            "privacy_class": privacy_class.value,
            "memory_eligible": memory_eligible,
            "uncertainty_note": uncertainty_note,
        }
        ingress = self._ingress(
            operation="scene_action",
            semantic_input=semantic_input,
            idempotency_key=idempotency_key,
            session_id=initial.opened_session_id,
            traceparent=traceparent,
        )
        with self.repository.pool.connection() as connection, connection.transaction():
            created, request = self._reserve(connection, ingress)
            if not created:
                return self._result(
                    connection,
                    request_id=request["request_id"],
                    trace_id=request["trace_id"],
                    scene_session_id=scene_session_id,
                    replay=True,
                )
            row = connection.execute(
                """
                SELECT * FROM havre.scene_sessions
                WHERE owner_id = %s AND scene_session_id = %s FOR UPDATE
                """,
                (self.owner_id, scene_session_id),
            ).fetchone()
            if row is None:
                raise LookupError("Scene Session not found")
            scene = self._scene_from_row(row)
            if scene.revision != expected_revision:
                raise ValueError("Scene revision precondition failed")
            if scene.phase is not ScenePhase.DURING or scene.status is not SceneStatus.ACTIVE:
                raise ValueError("actions are captured during an active Scene")
            intervention = connection.execute(
                """
                SELECT * FROM havre.scene_records
                WHERE owner_id = %s AND scene_session_id = %s
                ORDER BY sequence_number DESC LIMIT 1
                """,
                (self.owner_id, scene_session_id),
            ).fetchone()
            if (
                intervention is None
                or intervention["record_type"] != "intervention"
                or intervention["phase"] != "during"
            ):
                raise ValueError(
                    "an action requires the latest Scene record to be a During intervention"
                )
            policy = DataPolicy.owner_default(
                privacy_class, memory_eligible=memory_eligible
            )
            record_id = uuid7()
            event = EventEnvelope(
                event_type=EventType.USER_ACTION_REPORTED,
                owner_id=self.owner_id,
                session_id=scene.opened_session_id,
                scene_session_id=scene_session_id,
                request_id=ingress.request_id,
                trace_id=ingress.trace.trace_id,
                causation_event_id=intervention["event_id"],
                data_policy=policy,
                payload=SceneActionPayload(
                    scene_session_id=scene_session_id,
                    scene_record_id=record_id,
                    intervention_record_id=intervention["scene_record_id"],
                    action=action_text,
                    action_attempted=action_attempted.value,
                    occurred_at=occurred_at,
                ),
            )
            PostgresRepository._insert_event(connection, event)
            sequence = intervention["sequence_number"] + 1
            record = SceneRecord(
                scene_record_id=record_id,
                owner_id=self.owner_id,
                scene_session_id=scene_session_id,
                record_type=SceneRecordType.ACTION,
                phase="during",
                sequence_number=sequence,
                occurred_at=occurred_at,
                event_id=event.event_id,
                causal_predecessor_id=intervention["scene_record_id"],
                source="owner_self_report",
                uncertainty_note=uncertainty_note,
                content={
                    "action": action_text,
                    "action_attempted": action_attempted.value,
                    "reporter": "user",
                },
                trace_id=ingress.trace.trace_id,
                data_policy=policy,
            )
            self._insert_record(connection, record)
            self._complete_request(
                connection,
                ingress=ingress,
                owner_id=self.owner_id,
                request_id=ingress.request_id,
                user_event_id=event.event_id,
            )
            return self._result(
                connection,
                request_id=ingress.request_id,
                trace_id=ingress.trace.trace_id,
                scene_session_id=scene_session_id,
                replay=False,
            )

    def record_outcome(
        self,
        *,
        scene_session_id: UUID,
        expected_revision: int,
        outcome_text: str,
        occurred_at: datetime,
        privacy_class: PrivacyClass,
        memory_eligible: bool,
        uncertainty_note: str | None,
        idempotency_key: str,
        traceparent: str | None,
    ) -> SceneCommandResult:
        initial = self.get(scene_session_id=scene_session_id).scene_session
        semantic_input = {
            "scene_session_id": scene_session_id,
            "expected_revision": expected_revision,
            "outcome_text": outcome_text,
            "occurred_at": occurred_at,
            "privacy_class": privacy_class.value,
            "memory_eligible": memory_eligible,
            "uncertainty_note": uncertainty_note,
        }
        ingress = self._ingress(
            operation="scene_outcome",
            semantic_input=semantic_input,
            idempotency_key=idempotency_key,
            session_id=initial.opened_session_id,
            traceparent=traceparent,
        )
        with self.repository.pool.connection() as connection, connection.transaction():
            created, request = self._reserve(connection, ingress)
            if not created:
                return self._result(
                    connection,
                    request_id=request["request_id"],
                    trace_id=request["trace_id"],
                    scene_session_id=scene_session_id,
                    replay=True,
                )
            row = connection.execute(
                """
                SELECT * FROM havre.scene_sessions
                WHERE owner_id = %s AND scene_session_id = %s FOR UPDATE
                """,
                (self.owner_id, scene_session_id),
            ).fetchone()
            if row is None:
                raise LookupError("Scene Session not found")
            scene = self._scene_from_row(row)
            if scene.revision != expected_revision:
                raise ValueError("Scene revision precondition failed")
            if scene.phase is not ScenePhase.AFTER or scene.status is not SceneStatus.ACTIVE:
                raise ValueError("outcomes are captured in an active After Scene")
            action = connection.execute(
                """
                SELECT * FROM havre.scene_records
                WHERE owner_id = %s AND scene_session_id = %s
                  AND record_type = 'action'
                ORDER BY sequence_number DESC LIMIT 1
                """,
                (self.owner_id, scene_session_id),
            ).fetchone()
            if action is None:
                raise ValueError("an outcome requires a preceding action report")
            policy = DataPolicy.owner_default(
                privacy_class, memory_eligible=memory_eligible
            )
            record_id = uuid7()
            event = EventEnvelope(
                event_type=EventType.OUTCOME_REPORTED,
                owner_id=self.owner_id,
                session_id=scene.opened_session_id,
                scene_session_id=scene_session_id,
                request_id=ingress.request_id,
                trace_id=ingress.trace.trace_id,
                causation_event_id=action["event_id"],
                data_policy=policy,
                payload=SceneOutcomePayload(
                    scene_session_id=scene_session_id,
                    scene_record_id=record_id,
                    action_record_id=action["scene_record_id"],
                    outcome=outcome_text,
                    occurred_at=occurred_at,
                ),
            )
            PostgresRepository._insert_event(connection, event)
            sequence = connection.execute(
                """
                SELECT COALESCE(max(sequence_number), 0) + 1 AS value
                FROM havre.scene_records
                WHERE owner_id = %s AND scene_session_id = %s
                """,
                (self.owner_id, scene_session_id),
            ).fetchone()["value"]
            record = SceneRecord(
                scene_record_id=record_id,
                owner_id=self.owner_id,
                scene_session_id=scene_session_id,
                record_type=SceneRecordType.OUTCOME,
                phase="after",
                sequence_number=sequence,
                occurred_at=occurred_at,
                event_id=event.event_id,
                causal_predecessor_id=action["scene_record_id"],
                source="owner_self_report",
                uncertainty_note=uncertainty_note,
                content={
                    "outcome": outcome_text,
                    "reporter": "user",
                    "observation_scope": "self_report",
                },
                trace_id=ingress.trace.trace_id,
                data_policy=policy,
            )
            self._insert_record(connection, record)
            self._complete_request(
                connection,
                ingress=ingress,
                owner_id=self.owner_id,
                request_id=ingress.request_id,
                user_event_id=event.event_id,
            )
            return self._result(
                connection,
                request_id=ingress.request_id,
                trace_id=ingress.trace.trace_id,
                scene_session_id=scene_session_id,
                replay=False,
            )

    def _insert_observation(
        self, connection, observation: GuidanceOutcomeObservation
    ) -> None:
        policy = observation.data_policy
        connection.execute(
            """
            INSERT INTO havre.guidance_outcome_observations (
                outcome_observation_id, schema_version, owner_id,
                scene_session_id, intervention_decision_id, guidance_event_id,
                action_record_id, outcome_record_id, reflection_record_id,
                observation_window_started_at, observation_window_ended_at,
                reporter, action_attempted, planned_scene_status, helpfulness,
                too_passive, too_forceful, later_regret, limitations, consented,
                evidence_snapshot, created_event_id, trace_id, privacy_class,
                memory_eligible, training_eligible, cloud_eligible, policy_version,
                policy_revision_id, policy_decision_source,
                policy_authorization_ref, content_hash, created_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s
            )
            """,
            (
                observation.outcome_observation_id,
                observation.schema_version,
                observation.owner_id,
                observation.scene_session_id,
                observation.intervention_decision_id,
                observation.guidance_event_id,
                observation.action_record_id,
                observation.outcome_record_id,
                observation.reflection_record_id,
                observation.observation_window_started_at,
                observation.observation_window_ended_at,
                observation.reporter,
                observation.action_attempted.value,
                observation.planned_scene_status,
                observation.helpfulness.value,
                observation.too_passive.value,
                observation.too_forceful.value,
                observation.later_regret,
                Jsonb(list(observation.limitations)),
                observation.consented,
                Jsonb(list(observation.evidence_snapshot)),
                observation.created_event_id,
                observation.trace_id,
                *self._policy_columns(policy),
                observation.content_hash,
                observation.created_at,
            ),
        )

    def reflect(
        self,
        *,
        scene_session_id: UUID,
        expected_revision: int,
        reflection_text: str,
        next_adjustment: str | None,
        planned_scene_status: Literal[
            "completed", "partial", "abandoned", "cancelled", "unknown"
        ],
        helpfulness: OutcomeHelpfulness,
        too_passive: OutcomeTriState,
        too_forceful: OutcomeTriState,
        later_regret: Literal["yes", "no", "unsure", "not_asked"],
        privacy_class: PrivacyClass,
        memory_eligible: bool,
        consented: Literal[True],
        idempotency_key: str,
        traceparent: str | None,
    ) -> SceneCommandResult:
        initial = self.get(scene_session_id=scene_session_id).scene_session
        semantic_input = {
            "scene_session_id": scene_session_id,
            "expected_revision": expected_revision,
            "reflection_text": reflection_text,
            "next_adjustment": next_adjustment,
            "planned_scene_status": planned_scene_status,
            "helpfulness": helpfulness.value,
            "too_passive": too_passive.value,
            "too_forceful": too_forceful.value,
            "later_regret": later_regret,
            "privacy_class": privacy_class.value,
            "memory_eligible": memory_eligible,
            "consented": consented,
        }
        ingress = self._ingress(
            operation="scene_reflection",
            semantic_input=semantic_input,
            idempotency_key=idempotency_key,
            session_id=initial.opened_session_id,
            traceparent=traceparent,
        )
        with self.repository.pool.connection() as connection, connection.transaction():
            created, request = self._reserve(connection, ingress)
            if not created:
                return self._result(
                    connection,
                    request_id=request["request_id"],
                    trace_id=request["trace_id"],
                    scene_session_id=scene_session_id,
                    replay=True,
                )
            row = connection.execute(
                """
                SELECT * FROM havre.scene_sessions
                WHERE owner_id = %s AND scene_session_id = %s FOR UPDATE
                """,
                (self.owner_id, scene_session_id),
            ).fetchone()
            if row is None:
                raise LookupError("Scene Session not found")
            scene = self._scene_from_row(row)
            if scene.revision != expected_revision:
                raise ValueError("Scene revision precondition failed")
            if scene.phase is not ScenePhase.AFTER or scene.status is not SceneStatus.ACTIVE:
                raise ValueError("reflection requires an active After Scene")
            outcome = connection.execute(
                """
                SELECT * FROM havre.scene_records
                WHERE owner_id = %s AND scene_session_id = %s
                  AND record_type = 'outcome'
                ORDER BY sequence_number DESC LIMIT 1
                """,
                (self.owner_id, scene_session_id),
            ).fetchone()
            if outcome is None:
                raise ValueError("reflection requires a preceding outcome")
            action = connection.execute(
                """
                SELECT * FROM havre.scene_records
                WHERE owner_id = %s AND scene_session_id = %s
                  AND scene_record_id = %s AND record_type = 'action'
                """,
                (self.owner_id, scene_session_id, outcome["causal_predecessor_id"]),
            ).fetchone()
            if action is None:
                raise ValueError("outcome does not link to an action")
            intervention = connection.execute(
                """
                SELECT record.*, decision.guidance_event_id, decision.created_at AS decision_created_at
                FROM havre.scene_records AS record
                JOIN havre.intervention_decisions AS decision
                  ON decision.owner_id = record.owner_id
                 AND decision.intervention_decision_id = record.artifact_id
                WHERE record.owner_id = %s AND record.scene_session_id = %s
                  AND record.scene_record_id = %s AND record.record_type = 'intervention'
                """,
                (self.owner_id, scene_session_id, action["causal_predecessor_id"]),
            ).fetchone()
            if intervention is None:
                raise ValueError("action does not link to an intervention")
            action_attempted = OutcomeTriState(action["content"]["action_attempted"])
            reflection_policy = DataPolicy.owner_default(
                privacy_class, memory_eligible=memory_eligible
            )
            observation_policy = combine_policies(
                (
                    PostgresRepository._policy_from_row(intervention),
                    PostgresRepository._policy_from_row(action),
                    PostgresRepository._policy_from_row(outcome),
                    reflection_policy,
                )
            )
            reflection_record_id = uuid7()
            observation_id = uuid7()
            reflection_event = EventEnvelope(
                event_type=EventType.REFLECTION_CREATED,
                owner_id=self.owner_id,
                session_id=scene.opened_session_id,
                scene_session_id=scene_session_id,
                request_id=ingress.request_id,
                trace_id=ingress.trace.trace_id,
                causation_event_id=outcome["event_id"],
                data_policy=reflection_policy,
                payload=SceneReflectionPayload(
                    scene_session_id=scene_session_id,
                    scene_record_id=reflection_record_id,
                    outcome_record_id=outcome["scene_record_id"],
                    outcome_observation_id=observation_id,
                    reflection=reflection_text,
                    next_adjustment=next_adjustment,
                ),
            )
            PostgresRepository._insert_event(connection, reflection_event)
            sequence = connection.execute(
                """
                SELECT COALESCE(max(sequence_number), 0) + 1 AS value
                FROM havre.scene_records
                WHERE owner_id = %s AND scene_session_id = %s
                """,
                (self.owner_id, scene_session_id),
            ).fetchone()["value"]
            reflection_record = SceneRecord(
                scene_record_id=reflection_record_id,
                owner_id=self.owner_id,
                scene_session_id=scene_session_id,
                record_type=SceneRecordType.REFLECTION,
                phase="after",
                sequence_number=sequence,
                occurred_at=reflection_event.recorded_at,
                event_id=reflection_event.event_id,
                causal_predecessor_id=outcome["scene_record_id"],
                source="owner_self_report",
                content={
                    "reflection": reflection_text,
                    "next_adjustment": next_adjustment,
                    "outcome_observation_id": str(observation_id),
                },
                trace_id=ingress.trace.trace_id,
                data_policy=reflection_policy,
            )
            self._insert_record(connection, reflection_record)
            evidence = tuple(
                EvidenceRef(
                    source_kind=EvidenceSourceKind.EVENT,
                    source_id=event_id,
                    relation=EvidenceRelation.SUPPORTS,
                )
                for event_id in (
                    action["event_id"],
                    outcome["event_id"],
                    reflection_event.event_id,
                )
            )
            evidence_snapshot = tuple(
                value.model_dump(mode="json") for value in evidence
            )
            observation = GuidanceOutcomeObservation(
                outcome_observation_id=observation_id,
                owner_id=self.owner_id,
                scene_session_id=scene_session_id,
                intervention_decision_id=intervention["artifact_id"],
                guidance_event_id=intervention["guidance_event_id"],
                action_record_id=action["scene_record_id"],
                outcome_record_id=outcome["scene_record_id"],
                reflection_record_id=reflection_record_id,
                observation_window_started_at=intervention["decision_created_at"],
                observation_window_ended_at=reflection_event.recorded_at,
                action_attempted=action_attempted,
                planned_scene_status=planned_scene_status,
                helpfulness=helpfulness,
                too_passive=too_passive,
                too_forceful=too_forceful,
                later_regret=later_regret,
                limitations=(
                    "Single consented self-report; association is not causal proof.",
                    "Unasked or missing observations remain unknown.",
                ),
                consented=consented,
                evidence_snapshot=evidence_snapshot,
                created_event_id=reflection_event.event_id,
                trace_id=ingress.trace.trace_id,
                data_policy=observation_policy,
            )
            self._insert_observation(connection, observation)
            self._insert_evidence_edges(
                connection,
                owner_id=self.owner_id,
                evidence=evidence,
                derived_kind="guidance_outcome_observation",
                derived_id=observation_id,
                created_event_id=reflection_event.event_id,
                trace_id=ingress.trace.trace_id,
                transform_name="consented_scene_outcome_capture",
                transform_version="guidance-outcome-observation-v1",
            )
            self._complete_request(
                connection,
                ingress=ingress,
                owner_id=self.owner_id,
                request_id=ingress.request_id,
                user_event_id=reflection_event.event_id,
            )
            return self._result(
                connection,
                request_id=ingress.request_id,
                trace_id=ingress.trace.trace_id,
                scene_session_id=scene_session_id,
                replay=False,
            )
