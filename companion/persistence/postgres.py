"""PostgreSQL repository for the permanent Stage 1 slice."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import re
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from companion.context import ContextPack, ConversationHistoryItem, PersonalContextItem
from companion.events import (
    AssistantMessagePayload,
    BeliefLifecyclePayload,
    BeliefTransitionPayload,
    ConsolidationLifecyclePayload,
    CurrentStateLifecyclePayload,
    EventEnvelope,
    EventType,
    GoalLifecyclePayload,
    InteractionFailurePayload,
    MemoryLifecyclePayload,
    ProgressLifecyclePayload,
)
from companion.evidence import EvidenceRef, EvidenceRelation, EvidenceSourceKind
from companion.consolidation.models import ConsolidationProposal
from companion.goals.models import (
    GOAL_FIELD_UNSET,
    Goal,
    GoalFieldUnset,
    GoalPriority,
    GoalProgressRecord,
    GoalStatus,
    GoalTrack,
)
from companion.hashing import content_hash
from companion.identity import IdentityBundle
from companion.ids import uuid7
from companion.memory.models import MemoryCandidate, MemoryRevision, MemoryStatus
from companion.policy import DataPolicy, PrivacyClass, combine_policies
from companion.policy.response import validate_response_policy_delivery
from companion.policy.models import PRIVACY_RESTRICTION_ORDER
from companion.state.models import CurrentStateSnapshot
from companion.tracing import Span, TraceContext
from mlsys.contracts import InferenceRequest, InferenceResponse, RouteDecision
from mlsys.retrieval.models import RetrievalRequest, RetrievalResult
from companion.user_model.models import (
    BeliefInitialStatus,
    BeliefRevision,
    BeliefSnapshot,
    BeliefTransition,
    BeliefTransitionType,
    BeliefType,
)


@dataclass(frozen=True)
class Reservation:
    created: bool
    request: dict[str, Any]


class LeaseLostError(RuntimeError):
    """The worker no longer owns the exact lease generation it claimed."""


class PostgresRepository:
    _STAGE4_PROPOSAL_DETECTOR_VERSIONS = {
        "pattern": "pattern-proposal-distinct-days-v1",
        "progress": "progress-proposal-distinct-days-v1",
    }

    def __init__(self, database_url: str, *, min_size: int = 1, max_size: int = 4) -> None:
        self.pool = ConnectionPool(
            conninfo=database_url,
            min_size=min_size,
            max_size=max_size,
            open=False,
            kwargs={"row_factory": dict_row, "options": "-c timezone=UTC"},
        )

    def open(self) -> None:
        self.pool.open(wait=True)

    def close(self) -> None:
        self.pool.close()

    def database_version(self) -> str:
        with self.pool.connection() as connection:
            return connection.execute("SHOW server_version").fetchone()["server_version"]

    def extension_version(self, name: str) -> str | None:
        with self.pool.connection() as connection:
            row = connection.execute(
                "SELECT extversion FROM pg_extension WHERE extname = %s",
                (name,),
            ).fetchone()
            return row["extversion"] if row else None

    def bootstrap_owner_and_identity(
        self, *, owner_id: UUID, identity: IdentityBundle
    ) -> None:
        with self.pool.connection() as connection, connection.transaction():
            connection.execute(
                """
                INSERT INTO havre.owners (owner_id, display_name)
                VALUES (%s, 'Owner')
                ON CONFLICT (owner_id) DO NOTHING
                """,
                (owner_id,),
            )
            for artifact in (
                identity.constitution,
                identity.identity,
                identity.values,
            ):
                stored_artifact = connection.execute(
                    """
                    SELECT content_hash
                    FROM havre.identity_artifact_versions
                    WHERE owner_id = %s AND artifact_version_id = %s
                    """,
                    (owner_id, artifact.version_id),
                ).fetchone()
                if stored_artifact and stored_artifact["content_hash"] != artifact.content_hash:
                    raise ValueError(
                        f"identity version {artifact.version_id} changed content"
                    )
                existing = connection.execute(
                    """
                    SELECT approval_id, artifact_content_hash
                    FROM havre.approval_records
                    WHERE owner_id = %s AND artifact_kind = %s
                      AND artifact_version_id = %s
                    """,
                    (owner_id, artifact.artifact_kind, artifact.version_id),
                ).fetchone()
                if existing and existing["artifact_content_hash"] != artifact.content_hash:
                    raise ValueError(
                        f"approved artifact {artifact.version_id} changed content"
                    )
                approval_id = existing["approval_id"] if existing else uuid7()
                if not existing:
                    connection.execute(
                        """
                        INSERT INTO havre.approval_records (
                            approval_id, owner_id, artifact_kind,
                            artifact_version_id, artifact_content_hash,
                            decision, rationale, scope, approved_at
                        ) VALUES (%s, %s, %s, %s, %s, 'approved', %s, %s, %s)
                        """,
                        (
                            approval_id,
                            owner_id,
                            artifact.artifact_kind,
                            artifact.version_id,
                            artifact.content_hash,
                            "Stage 0.1 owner approval and Stage 1 activation",
                            "HAVRE Companion system",
                            artifact.approved_at,
                        ),
                    )
                connection.execute(
                    """
                    INSERT INTO havre.identity_artifact_versions (
                        artifact_version_id, owner_id, artifact_kind,
                        schema_version, content, content_hash, approval_id, source_files
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (owner_id, artifact_version_id) DO NOTHING
                    """,
                    (
                        artifact.version_id,
                        owner_id,
                        artifact.artifact_kind,
                        artifact.schema_version,
                        artifact.content,
                        artifact.content_hash,
                        approval_id,
                        Jsonb(list(artifact.source_files)),
                    ),
                )

            governance_artifacts = (
                (
                    "privacy_rules",
                    "data-policy-v1",
                    content_hash(
                        {
                            "public": "cloud_subject_to_provider_policy",
                            "normal": "cloud_default_subject_to_settings_and_provider_policy",
                            "private": "explicitly_approved_cloud_providers_only",
                            "highly_private": "no_cloud_without_explicit_owner_authorization",
                            "local_only": "owner_controlled_infrastructure_only",
                            "training_eligible_default": False,
                            "declassification_authority": "owner_only",
                            "redaction_requires_new_policy_and_provenance": True,
                        }
                    ),
                ),
                (
                    "governance",
                    identity.governance_version,
                    content_hash(
                        {
                            "material_changes_require_owner_approval": True,
                            "governance_version": identity.governance_version,
                        }
                    ),
                ),
            )
            for kind, version_id, artifact_hash in governance_artifacts:
                existing = connection.execute(
                    """
                    SELECT artifact_content_hash FROM havre.approval_records
                    WHERE owner_id = %s AND artifact_kind = %s
                      AND artifact_version_id = %s
                    """,
                    (owner_id, kind, version_id),
                ).fetchone()
                if existing and existing["artifact_content_hash"] != artifact_hash:
                    raise ValueError(
                        f"approved governance artifact {version_id} changed content"
                    )
                connection.execute(
                    """
                    INSERT INTO havre.approval_records (
                        approval_id, owner_id, artifact_kind, artifact_version_id,
                        artifact_content_hash, decision, rationale, scope, approved_at
                    ) VALUES (%s, %s, %s, %s, %s, 'approved', %s, %s, %s)
                    ON CONFLICT (owner_id, artifact_kind, artifact_version_id) DO NOTHING
                    """,
                    (
                        uuid7(),
                        owner_id,
                        kind,
                        version_id,
                        artifact_hash,
                        "Stage 1 owner decision",
                        "HAVRE Companion system",
                        identity.constitution.approved_at,
                    ),
                )

    def reserve_interaction(
        self,
        *,
        idempotency_key: str,
        request_fingerprint: str,
        user_event: EventEnvelope,
        trace: TraceContext,
        channel: str,
        trace_started_at: datetime,
    ) -> Reservation:
        with self.pool.connection() as connection, connection.transaction():
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"{user_event.owner_id}:{idempotency_key}",),
            )
            existing = connection.execute(
                """
                SELECT * FROM havre.interaction_requests
                WHERE owner_id = %s AND idempotency_key = %s
                """,
                (user_event.owner_id, idempotency_key),
            ).fetchone()
            if existing:
                return Reservation(created=False, request=existing)

            session = connection.execute(
                """
                INSERT INTO havre.sessions (session_id, owner_id, channel)
                VALUES (%s, %s, %s)
                ON CONFLICT (session_id) DO UPDATE
                    SET last_activity_at = clock_timestamp()
                    WHERE havre.sessions.owner_id=EXCLUDED.owner_id
                      AND havre.sessions.closed_at IS NULL
                RETURNING session_id
                """,
                (user_event.session_id, user_event.owner_id, channel),
            ).fetchone()
            if session is None:
                state = connection.execute(
                    "SELECT owner_id,closed_at FROM havre.sessions WHERE session_id=%s",
                    (user_event.session_id,),
                ).fetchone()
                if (
                    state is not None
                    and state["owner_id"] == user_event.owner_id
                    and state["closed_at"] is not None
                ):
                    raise ValueError("conversation is closed; start a new conversation")
                # A same UUID owned by somebody else deliberately continues to
                # the existing owner-qualified FK, preserving the durable
                # cross-owner rejection rather than disguising it as closure.
            connection.execute(
                """
                INSERT INTO havre.traces (
                    trace_id, owner_id, root_request_id,
                    incoming_parent_span_id, trace_flags, started_at
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    trace.trace_id,
                    user_event.owner_id,
                    user_event.request_id,
                    trace.parent_span_id,
                    trace.trace_flags,
                    trace_started_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO havre.interaction_requests (
                    request_id, owner_id, session_id, trace_id,
                    idempotency_key, request_fingerprint, status
                ) VALUES (%s, %s, %s, %s, %s, %s, 'processing')
                """,
                (
                    user_event.request_id,
                    user_event.owner_id,
                    user_event.session_id,
                    user_event.trace_id,
                    idempotency_key,
                    request_fingerprint,
                ),
            )
            self._insert_event(connection, user_event)
            # Daily Web chat consolidates the complete session at an explicit
            # episode boundary. Legacy API/CLI interactions retain the Stage 2
            # per-event job for compatibility, but the normal chat path never
            # interrupts the owner with one candidate per utterance.
            if user_event.data_policy.memory_eligible and channel != "web":
                connection.execute(
                    """
                    INSERT INTO havre.background_jobs (
                        job_id, owner_id, job_type, schema_version, payload,
                        idempotency_key, status, origin_trace_id,
                        source_event_id, source_request_id
                    ) VALUES (
                        %s, %s, 'episodic_memory_extract', 1, %s,
                        %s, 'pending', %s, %s, %s
                    ) ON CONFLICT (owner_id, job_type, idempotency_key) DO NOTHING
                    """,
                    (
                        uuid7(),
                        user_event.owner_id,
                        Jsonb(
                            {
                                "schema_version": 1,
                                "source_event_id": str(user_event.event_id),
                                "source_request_id": str(user_event.request_id),
                            }
                        ),
                        f"event:{user_event.event_id}:{'episodic-extractor-rule-v1'}",
                        user_event.trace_id,
                        user_event.event_id,
                        user_event.request_id,
                    ),
                )
            request = connection.execute(
                """
                UPDATE havre.interaction_requests
                SET user_event_id = %s
                WHERE request_id = %s AND owner_id = %s
                RETURNING *
                """,
                (user_event.event_id, user_event.request_id, user_event.owner_id),
            ).fetchone()
            return Reservation(created=True, request=request)

    def complete_interaction(
        self,
        *,
        owner_id: UUID,
        context_pack: ContextPack,
        route_decision: RouteDecision,
        inference_response: InferenceResponse,
        assistant_event: EventEnvelope,
        spans: list[Span],
    ) -> None:
        payload = assistant_event.payload
        if not isinstance(payload, AssistantMessagePayload):
            raise ValueError("completion requires an assistant message payload")
        decision = payload.response_policy_decision
        if decision is None:
            raise ValueError("completion requires a durable response policy decision")
        raw_parts = tuple(part.text for part in inference_response.output_parts)
        delivered_parts = tuple(part.text for part in payload.content_parts)
        if (
            assistant_event.owner_id != owner_id
            or assistant_event.request_id != context_pack.request_id
            or assistant_event.trace_id != context_pack.trace_id
            or payload.context_pack_id != context_pack.context_pack_id
            or payload.inference_response_id != inference_response.inference_response_id
        ):
            raise ValueError("response policy decision lineage or content hash mismatch")
        validate_response_policy_delivery(
            decision,
            request_id=context_pack.request_id,
            trace_id=context_pack.trace_id,
            context_pack_id=context_pack.context_pack_id,
            inference_response_id=inference_response.inference_response_id,
            raw_output_parts=raw_parts,
            delivered_output_parts=delivered_parts,
        )
        with self.pool.connection() as connection, connection.transaction():
            request = connection.execute(
                """
                SELECT status FROM havre.interaction_requests
                WHERE request_id = %s AND owner_id = %s FOR UPDATE
                """,
                (context_pack.request_id, owner_id),
            ).fetchone()
            if not request:
                raise LookupError("interaction request does not exist")
            if request["status"] == "completed":
                return
            if request["status"] != "processing":
                raise RuntimeError("interaction request is not processing")
            self._insert_context_pack(connection, context_pack)
            self._insert_route_decision(connection, route_decision, owner_id)
            connection.execute(
                """
                INSERT INTO havre.inference_attempts (
                    inference_attempt_id, inference_response_id,
                    inference_request_id, schema_version, owner_id, request_id,
                    trace_id, context_pack_id, route_decision_id, attempt_number,
                    status, finish_reason, provider_id, provider_request_id,
                    provider_class, model_version_id, adapter_version_id,
                    tokenizer_version_id, serving_config_version,
                    provider_adapter_version_id, serving_engine,
                    serving_engine_version, model_artifact_hash,
                    runtime_attestation_id, runtime_attestation_hash, usage, timing_ms,
                    output_content_hash, failure, created_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, 1,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, %s
                )
                """,
                (
                    inference_response.inference_request_id,
                    inference_response.inference_response_id,
                    inference_response.inference_request_id,
                    inference_response.schema_version, owner_id,
                    inference_response.request_id, inference_response.trace_id,
                    context_pack.context_pack_id, route_decision.route_decision_id,
                    inference_response.status, inference_response.finish_reason,
                    inference_response.provider.provider_id,
                    inference_response.provider.provider_request_id,
                    inference_response.provider.provider_class,
                    inference_response.versions.model_version_id,
                    inference_response.versions.adapter_version_id,
                    inference_response.versions.tokenizer_version_id,
                    inference_response.versions.serving_config_version,
                    inference_response.versions.provider_adapter_version_id,
                    inference_response.versions.serving_engine,
                    inference_response.versions.serving_engine_version,
                    inference_response.versions.model_artifact_hash,
                    inference_response.versions.runtime_attestation_id,
                    inference_response.versions.runtime_attestation_hash,
                    Jsonb(inference_response.usage.model_dump(mode="json")),
                    Jsonb(inference_response.timing_ms.model_dump(mode="json")),
                    content_hash(
                        [part.model_dump(mode="json") for part in inference_response.output_parts]
                    ),
                    inference_response.created_at,
                ),
            )
            self._insert_event(connection, assistant_event)
            self._insert_spans(connection, spans)
            connection.execute(
                """
                UPDATE havre.interaction_requests SET
                    status = 'completed', assistant_event_id = %s,
                    context_pack_id = %s, inference_attempt_id = %s,
                    inference_response_id = %s, completed_at = clock_timestamp()
                WHERE request_id = %s AND owner_id = %s
                """,
                (
                    assistant_event.event_id, context_pack.context_pack_id,
                    inference_response.inference_request_id,
                    inference_response.inference_response_id,
                    context_pack.request_id, owner_id,
                ),
            )

    @staticmethod
    def _insert_context_pack(connection, context_pack: ContextPack) -> None:
        policy = context_pack.effective_data_policy
        connection.execute(
            """
            INSERT INTO havre.context_packs (
                context_pack_id, schema_version, owner_id, request_id, trace_id,
                purpose, builder_version, constitution_version_id,
                identity_version_id, values_version_id, token_budget, sections,
                excluded_candidates, effective_privacy_class,
                effective_memory_eligible, effective_training_eligible,
                effective_cloud_eligible, effective_policy_version,
                effective_policy_revision_id, estimated_total_tokens,
                content_hash, created_at, retrieval_result_id
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                context_pack.context_pack_id, context_pack.schema_version,
                context_pack.owner_id, context_pack.request_id, context_pack.trace_id,
                context_pack.purpose, context_pack.builder_version,
                context_pack.constitution_version_id, context_pack.identity_version_id,
                context_pack.values_version_id,
                Jsonb(context_pack.token_budget.model_dump(mode="json")),
                Jsonb([section.model_dump(mode="json") for section in context_pack.sections]),
                Jsonb(list(context_pack.excluded_candidates)), policy.privacy_class.value,
                policy.memory_eligible, policy.training_eligible, policy.cloud_eligible,
                policy.policy_version, policy.policy_revision_id,
                context_pack.estimated_total_tokens, context_pack.content_hash,
                context_pack.created_at, context_pack.retrieval_result_id,
            ),
        )

    @staticmethod
    def _insert_route_decision(connection, route_decision: RouteDecision, owner_id: UUID) -> None:
        connection.execute(
            """
            INSERT INTO havre.route_decisions (
                route_decision_id, schema_version, owner_id, request_id,
                trace_id, router_version, selected_provider_id,
                selected_model_version_id, execution_environment,
                effective_policy_revision_id, eligible_candidates,
                excluded_candidates, reason, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                route_decision.route_decision_id, route_decision.schema_version,
                owner_id, route_decision.request_id, route_decision.trace_id,
                route_decision.router_version, route_decision.selected_provider_id,
                route_decision.selected_model_version_id,
                route_decision.execution_environment,
                route_decision.effective_data_policy_revision_id,
                Jsonb(list(route_decision.eligible_candidates)),
                Jsonb(list(route_decision.excluded_candidates)),
                route_decision.reason, route_decision.created_at,
            ),
        )

    def fail_inference_interaction(
        self,
        *,
        owner_id: UUID,
        context_pack: ContextPack,
        route_decision: RouteDecision,
        inference_request: InferenceRequest,
        inference_failure,
        provider_version,
        failure_event: EventEnvelope,
        spans: list[Span],
    ) -> None:
        """Atomically retain routed failure evidence without an assistant event."""

        from mlsys.contracts import InferenceFailure, ProviderVersion

        inference_failure = InferenceFailure.model_validate(
            inference_failure.model_dump(mode="json")
        )
        provider_version = ProviderVersion.model_validate(
            provider_version.model_dump(mode="json")
        )
        expected_lineage = (
            inference_request.inference_request_id,
            context_pack.request_id,
            context_pack.trace_id,
            route_decision.selected_provider_id,
            provider_version.provider_class,
        )
        actual_lineage = (
            inference_failure.inference_request_id,
            inference_failure.request_id,
            inference_failure.trace_id,
            inference_failure.provider_id,
            inference_failure.provider_class,
        )
        if actual_lineage != expected_lineage:
            raise ValueError("inference failure lineage does not match request and route")
        if (
            provider_version.provider_id != route_decision.selected_provider_id
            or provider_version.model_version_id
            != route_decision.selected_model_version_id
        ):
            raise ValueError("provider version lineage does not match route")
        if (
            inference_request.request_id != context_pack.request_id
            or inference_request.trace_id != context_pack.trace_id
            or inference_request.context_pack_id != context_pack.context_pack_id
            or route_decision.request_id != context_pack.request_id
            or route_decision.trace_id != context_pack.trace_id
        ):
            raise ValueError("inference request lineage does not match context and route")
        self._validate_failure_event(
            owner_id=owner_id,
            context_pack=context_pack,
            failure_event=failure_event,
            error_code=inference_failure.code,
            failure_stage="inference",
            route_decision=route_decision,
            inference_request_id=inference_request.inference_request_id,
            retryable=inference_failure.retryable,
            safe_message=inference_failure.safe_message,
        )

        with self.pool.connection() as connection, connection.transaction():
            request = connection.execute(
                """
                SELECT status FROM havre.interaction_requests
                WHERE request_id = %s AND owner_id = %s FOR UPDATE
                """,
                (context_pack.request_id, owner_id),
            ).fetchone()
            if not request:
                raise LookupError("interaction request does not exist")
            if request["status"] != "processing":
                return
            self._insert_context_pack(connection, context_pack)
            self._insert_route_decision(connection, route_decision, owner_id)
            connection.execute(
                """
                INSERT INTO havre.inference_attempts (
                    inference_attempt_id, inference_response_id,
                    inference_request_id, schema_version, owner_id, request_id,
                    trace_id, context_pack_id, route_decision_id, attempt_number,
                    status, finish_reason, provider_id, provider_request_id,
                    provider_class, model_version_id, adapter_version_id,
                    tokenizer_version_id, serving_config_version,
                    provider_adapter_version_id, serving_engine,
                    serving_engine_version, model_artifact_hash,
                    runtime_attestation_id, runtime_attestation_hash, usage, timing_ms,
                    output_content_hash, failure, created_at
                ) VALUES (
                    %s, NULL, %s, 1, %s, %s, %s, %s, %s, 1,
                    'failed', NULL, %s, NULL, %s, %s, NULL,
                    %s, %s, %s, %s, %s, %s, %s, %s, NULL, NULL, NULL, %s, %s
                )
                """,
                (
                    inference_failure.inference_request_id,
                    inference_failure.inference_request_id,
                    owner_id, inference_failure.request_id,
                    inference_failure.trace_id, context_pack.context_pack_id,
                    route_decision.route_decision_id, inference_failure.provider_id,
                    inference_failure.provider_class,
                    route_decision.selected_model_version_id,
                    provider_version.tokenizer_version_id,
                    provider_version.serving_config_version,
                    provider_version.provider_adapter_version_id,
                    provider_version.serving_engine,
                    provider_version.serving_engine_version,
                    provider_version.model_artifact_hash,
                    provider_version.runtime_attestation_id,
                    provider_version.runtime_attestation_hash,
                    Jsonb(inference_failure.model_dump(mode="json")),
                    inference_failure.created_at,
                ),
            )
            self._insert_event(connection, failure_event)
            self._insert_spans(connection, spans)
            connection.execute(
                """
                UPDATE havre.interaction_requests SET
                    status = 'failed', context_pack_id = %s,
                    inference_attempt_id = %s, failure_event_id = %s,
                    error_code = %s, completed_at = clock_timestamp()
                WHERE request_id = %s AND owner_id = %s AND status = 'processing'
                """,
                (
                    context_pack.context_pack_id,
                    inference_failure.inference_request_id,
                    failure_event.event_id,
                    inference_failure.code,
                    context_pack.request_id,
                    owner_id,
                ),
            )

    def register_runtime_attestation(self, attestation) -> None:
        """Register immutable process evidence before it can be referenced."""

        from mlsys.serving import RuntimeAttestation

        attestation = RuntimeAttestation.model_validate(
            attestation.model_dump(mode="json")
        )
        with self.pool.connection() as connection:
            connection.execute(
                """
                INSERT INTO havre.runtime_attestations (
                    runtime_attestation_id, schema_version, attestation_hash,
                    attestation, created_at
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (runtime_attestation_id) DO NOTHING
                """,
                (
                    attestation.attestation_id,
                    attestation.schema_version,
                    attestation.attestation_hash,
                    Jsonb(attestation.model_dump(mode="json")),
                    attestation.attested_at,
                ),
            )
            row = connection.execute(
                """
                SELECT attestation_hash FROM havre.runtime_attestations
                WHERE runtime_attestation_id = %s
                """,
                (attestation.attestation_id,),
            ).fetchone()
            if row is None or row["attestation_hash"] != attestation.attestation_hash:
                raise ValueError("runtime attestation ID already has different content")

    def fail_pre_inference_interaction(
        self,
        *,
        owner_id: UUID,
        context_pack: ContextPack,
        route_decision: RouteDecision,
        inference_request: InferenceRequest,
        failure_event: EventEnvelope,
        error_code: str,
        spans: list[Span],
    ) -> None:
        """Persist a typed routed failure without inventing provider version data."""

        inference_request = InferenceRequest.model_validate(
            inference_request.model_dump(mode="json")
        )
        if (
            inference_request.request_id != context_pack.request_id
            or inference_request.trace_id != context_pack.trace_id
            or inference_request.context_pack_id != context_pack.context_pack_id
            or route_decision.request_id != context_pack.request_id
            or route_decision.trace_id != context_pack.trace_id
        ):
            raise ValueError("pre-inference request lineage does not match context and route")
        self._validate_failure_event(
            owner_id=owner_id,
            context_pack=context_pack,
            failure_event=failure_event,
            error_code=error_code,
            failure_stage="version_check",
            route_decision=route_decision,
            inference_request_id=inference_request.inference_request_id,
        )

        with self.pool.connection() as connection, connection.transaction():
            request = connection.execute(
                """
                SELECT status FROM havre.interaction_requests
                WHERE request_id = %s AND owner_id = %s FOR UPDATE
                """,
                (context_pack.request_id, owner_id),
            ).fetchone()
            if not request:
                raise LookupError("interaction request does not exist")
            if request["status"] != "processing":
                return
            self._insert_context_pack(connection, context_pack)
            self._insert_route_decision(connection, route_decision, owner_id)
            self._insert_event(connection, failure_event)
            self._insert_spans(connection, spans)
            connection.execute(
                """
                UPDATE havre.interaction_requests SET
                    status = 'failed', context_pack_id = %s,
                    failure_event_id = %s, error_code = %s,
                    completed_at = clock_timestamp()
                WHERE request_id = %s AND owner_id = %s AND status = 'processing'
                """,
                (
                    context_pack.context_pack_id, failure_event.event_id,
                    error_code, context_pack.request_id, owner_id,
                ),
            )

    def fail_pre_route_interaction(
        self,
        *,
        owner_id: UUID,
        context_pack: ContextPack,
        failure_event: EventEnvelope,
        error_code: str,
        spans: list[Span],
    ) -> None:
        """Persist capability/routing failure evidence without fake route data."""

        payload = failure_event.payload
        if not isinstance(payload, InteractionFailurePayload) or payload.failure_stage not in {
            "capability_check", "routing"
        }:
            raise ValueError("pre-route failure event has an invalid stage or payload")
        self._validate_failure_event(
            owner_id=owner_id,
            context_pack=context_pack,
            failure_event=failure_event,
            error_code=error_code,
            failure_stage=payload.failure_stage,
        )

        with self.pool.connection() as connection, connection.transaction():
            request = connection.execute(
                """
                SELECT status FROM havre.interaction_requests
                WHERE request_id = %s AND owner_id = %s FOR UPDATE
                """,
                (context_pack.request_id, owner_id),
            ).fetchone()
            if not request:
                raise LookupError("interaction request does not exist")
            if request["status"] != "processing":
                return
            self._insert_context_pack(connection, context_pack)
            self._insert_event(connection, failure_event)
            self._insert_spans(connection, spans)
            connection.execute(
                """
                UPDATE havre.interaction_requests SET
                    status = 'failed', context_pack_id = %s,
                    failure_event_id = %s, error_code = %s,
                    completed_at = clock_timestamp()
                WHERE request_id = %s AND owner_id = %s AND status = 'processing'
                """,
                (
                    context_pack.context_pack_id,
                    failure_event.event_id,
                    error_code,
                    context_pack.request_id,
                    owner_id,
                ),
            )

    @staticmethod
    def _validate_failure_event(
        *,
        owner_id: UUID,
        context_pack: ContextPack,
        failure_event: EventEnvelope,
        error_code: str,
        failure_stage: str,
        route_decision: RouteDecision | None = None,
        inference_request_id: UUID | None = None,
        retryable: bool | None = None,
        safe_message: str | None = None,
    ) -> None:
        payload = failure_event.payload
        expected_route_id = (
            route_decision.route_decision_id if route_decision is not None else None
        )
        if not isinstance(payload, InteractionFailurePayload) or (
            failure_event.event_type != EventType.INTERACTION_FAILED
            or failure_event.owner_id != owner_id
            or failure_event.request_id != context_pack.request_id
            or failure_event.trace_id != context_pack.trace_id
            or payload.failure_stage != failure_stage
            or payload.inference_request_id != inference_request_id
            or payload.context_pack_id != context_pack.context_pack_id
            or payload.route_decision_id != expected_route_id
            or payload.failure_code != error_code
            or (retryable is not None and payload.retryable != retryable)
            or (safe_message is not None and payload.safe_message != safe_message)
        ):
            raise ValueError("failure event lineage does not match the failed request")
        if route_decision is not None and (
            route_decision.request_id != context_pack.request_id
            or route_decision.trace_id != context_pack.trace_id
        ):
            raise ValueError("failure route lineage does not match the context pack")

    def append_spans(self, spans: list[Span]) -> None:
        if not spans:
            return
        with self.pool.connection() as connection, connection.transaction():
            self._insert_spans(connection, spans)

    def mark_failed(self, request_id: UUID, owner_id: UUID, error_code: str) -> None:
        with self.pool.connection() as connection, connection.transaction():
            connection.execute(
                """
                UPDATE havre.interaction_requests
                SET status = 'failed', error_code = %s, completed_at = clock_timestamp()
                WHERE request_id = %s AND owner_id = %s AND status = 'processing'
                """,
                (error_code, request_id, owner_id),
            )

    def evidence(self, request_id: UUID, *, owner_id: UUID) -> dict[str, Any] | None:
        with self.pool.connection() as connection:
            request = connection.execute(
                """
                SELECT * FROM havre.interaction_requests
                WHERE request_id = %s AND owner_id = %s
                """,
                (request_id, owner_id),
            ).fetchone()
            if not request:
                return None
            events = connection.execute(
                """
                SELECT event_id, event_type, event_version, owner_id, session_id,
                       scene_session_id, request_id, trace_id, causation_event_id, privacy_class,
                       memory_eligible, training_eligible, cloud_eligible,
                       policy_version, policy_revision_id, policy_decision_source,
                       policy_authorization_ref, payload, content_hash, recorded_at
                FROM havre.events
                WHERE request_id = %s AND owner_id = %s
                ORDER BY recorded_at, event_id
                """,
                (request_id, owner_id),
            ).fetchall()
            context_pack = connection.execute(
                """
                SELECT * FROM havre.context_packs
                WHERE request_id = %s AND owner_id = %s
                """,
                (request_id, owner_id),
            ).fetchone()
            route = connection.execute(
                """
                SELECT * FROM havre.route_decisions
                WHERE request_id = %s AND owner_id = %s
                """,
                (request_id, owner_id),
            ).fetchone()
            inference = connection.execute(
                """
                SELECT attempt.* FROM havre.inference_attempts AS attempt
                JOIN havre.interaction_requests AS request
                  ON request.owner_id = attempt.owner_id
                 AND request.inference_attempt_id = attempt.inference_attempt_id
                WHERE request.request_id = %s AND request.owner_id = %s
                """,
                (request_id, owner_id),
            ).fetchone()
            spans = connection.execute(
                """
                SELECT span_id, trace_id, parent_span_id, name, kind, started_at,
                       ended_at, duration_ms, status, attributes
                FROM havre.spans WHERE trace_id = %s ORDER BY started_at
                """,
                (request["trace_id"],),
            ).fetchall()
            identity_versions = connection.execute(
                """
                SELECT artifact_kind, artifact_version_id, content_hash, approval_id
                FROM havre.identity_artifact_versions
                WHERE owner_id = %s ORDER BY artifact_kind
                """,
                (owner_id,),
            ).fetchall()
            retrieval_result = connection.execute(
                """
                SELECT * FROM havre.retrieval_results
                WHERE request_id = %s AND owner_id = %s
                """,
                (request_id, owner_id),
            ).fetchone()
            memory_job = connection.execute(
                """
                SELECT job_id, status, attempt_count, source_event_id,
                       origin_trace_id, last_error_code, created_at, completed_at
                FROM havre.background_jobs
                WHERE source_request_id = %s AND owner_id = %s
                """,
                (request_id, owner_id),
            ).fetchone()
            return {
                "request": request,
                "events": events,
                "context_pack": context_pack,
                "route_decision": route,
                "inference": inference,
                "spans": spans,
                "identity_versions": identity_versions,
                "retrieval_result": retrieval_result,
                "memory_job": memory_job,
            }

    def register_embedding_version(self, version) -> None:
        with self.pool.connection() as connection, connection.transaction():
            existing = connection.execute(
                """
                SELECT * FROM havre.embedding_versions
                WHERE embedding_version_id = %s
                """,
                (version.embedding_version_id,),
            ).fetchone()
            expected = {
                "provider_id": version.provider_id,
                "model_revision": version.model_revision,
                "dimension": version.dimension,
                "distance_metric": version.distance_metric,
                "normalization": version.normalization,
                "tokenizer_version": version.tokenizer_version,
                "implementation_hash": version.implementation_hash,
            }
            if existing:
                if any(existing[key] != value for key, value in expected.items()):
                    raise ValueError("embedding version identifier changed meaning")
                return
            connection.execute(
                """
                INSERT INTO havre.embedding_versions (
                    embedding_version_id, schema_version, provider_id,
                    model_revision, dimension, distance_metric, normalization,
                    tokenizer_version, implementation_hash, status
                ) VALUES (%s, 1, %s, %s, %s, %s, %s, %s, %s, 'active')
                """,
                (
                    version.embedding_version_id,
                    version.provider_id,
                    version.model_revision,
                    version.dimension,
                    version.distance_metric,
                    version.normalization,
                    version.tokenizer_version,
                    version.implementation_hash,
                ),
            )

    def claim_memory_job(
        self, *, worker_id: str, owner_id: UUID | None = None
    ) -> dict[str, Any] | None:
        with self.pool.connection() as connection, connection.transaction():
            return connection.execute(
                """
                WITH claimable AS (
                    SELECT job_id
                    FROM havre.background_jobs
                    WHERE job_type = 'episodic_memory_extract'
                      AND (%s::uuid IS NULL OR owner_id = %s)
                      AND available_at <= clock_timestamp()
                      AND (
                        status IN ('pending', 'retryable_failed')
                        OR (status = 'leased' AND lease_expires_at <= clock_timestamp())
                      )
                      AND attempt_count < max_attempts
                    ORDER BY available_at, created_at, job_id
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE havre.background_jobs AS job
                SET status = 'leased', lease_owner = %s,
                    lease_expires_at = clock_timestamp() + interval '30 seconds',
                    attempt_count = attempt_count + 1
                FROM claimable
                WHERE job.job_id = claimable.job_id
                RETURNING job.*
                """,
                (owner_id, owner_id, worker_id),
            ).fetchone()

    def event_by_id(self, *, owner_id: UUID, event_id: UUID) -> EventEnvelope | None:
        with self.pool.connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM havre.events
                WHERE owner_id = %s AND event_id = %s
                """,
                (owner_id, event_id),
            ).fetchone()
        if row is None:
            return None
        return EventEnvelope.model_validate(
            {
                "schema_version": row["schema_version"],
                "event_id": row["event_id"],
                "event_type": row["event_type"],
                "event_version": row["event_version"],
                "owner_id": row["owner_id"],
                "session_id": row["session_id"],
                "scene_session_id": row.get("scene_session_id"),
                "request_id": row["request_id"],
                "trace_id": row["trace_id"],
                "causation_event_id": row["causation_event_id"],
                "data_policy": self._policy_from_row(row),
                "payload": row["payload"],
                "recorded_at": row["recorded_at"],
                "content_hash": row["content_hash"],
            }
        )

    def complete_memory_job(
        self,
        *,
        job: dict[str, Any],
        candidate: MemoryCandidate,
        spans: list[Span],
    ) -> dict[str, Any]:
        with self.pool.connection() as connection, connection.transaction():
            current = connection.execute(
                """
                SELECT status, lease_owner, attempt_count,
                       lease_expires_at > clock_timestamp() AS lease_active
                FROM havre.background_jobs
                WHERE owner_id = %s AND job_id = %s FOR UPDATE
                """,
                (job["owner_id"], job["job_id"]),
            ).fetchone()
            if not current:
                raise LookupError("job does not exist")
            if current["status"] == "succeeded":
                if current["attempt_count"] != job["attempt_count"]:
                    raise LeaseLostError("job was completed by a newer lease generation")
                return connection.execute(
                    """
                    SELECT * FROM havre.memory_candidates
                    WHERE owner_id = %s AND job_id = %s
                    """,
                    (job["owner_id"], job["job_id"]),
                ).fetchone()
            if (
                current["status"] != "leased"
                or current["lease_owner"] != job["lease_owner"]
                or current["attempt_count"] != job["attempt_count"]
                or not current["lease_active"]
            ):
                raise LeaseLostError("worker lease is missing, expired, or superseded")

            policy = candidate.data_policy
            stored = connection.execute(
                """
                INSERT INTO havre.memory_candidates (
                    candidate_id, schema_version, owner_id, source_event_id,
                    source_request_id, job_id, memory_class, content, content_text,
                    content_hash, confidence, confidence_method, importance,
                    importance_policy_version, extractor_version, status,
                    privacy_class, memory_eligible, training_eligible, cloud_eligible,
                    policy_version, policy_revision_id, policy_decision_source,
                    policy_authorization_ref, trace_id, created_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                ) ON CONFLICT (owner_id, source_event_id, extractor_version)
                DO NOTHING
                RETURNING *
                """,
                (
                    candidate.candidate_id,
                    candidate.schema_version,
                    candidate.owner_id,
                    candidate.source_event_id,
                    candidate.source_request_id,
                    candidate.job_id,
                    candidate.memory_class,
                    Jsonb(candidate.content),
                    candidate.content_text,
                    candidate.content_hash,
                    candidate.confidence,
                    candidate.confidence_method,
                    candidate.importance,
                    candidate.importance_policy_version,
                    candidate.extractor_version,
                    candidate.status.value,
                    policy.privacy_class.value,
                    policy.memory_eligible,
                    policy.training_eligible,
                    policy.cloud_eligible,
                    policy.policy_version,
                    policy.policy_revision_id,
                    policy.decision_source,
                    policy.authorization_ref,
                    candidate.trace_id,
                    candidate.created_at,
                ),
            ).fetchone()
            if stored is None:
                stored = connection.execute(
                    """
                    SELECT * FROM havre.memory_candidates
                    WHERE owner_id = %s AND job_id = %s
                    """,
                    (job["owner_id"], job["job_id"]),
                ).fetchone()
            completed = connection.execute(
                """
                UPDATE havre.background_jobs
                SET status = 'succeeded', lease_owner = NULL,
                    lease_expires_at = NULL, completed_at = clock_timestamp()
                WHERE owner_id = %s AND job_id = %s
                  AND status = 'leased' AND lease_owner = %s
                  AND attempt_count = %s
                  AND lease_expires_at > clock_timestamp()
                """,
                (
                    job["owner_id"], job["job_id"], job["lease_owner"],
                    job["attempt_count"],
                ),
            )
            if completed.rowcount != 1:
                raise LeaseLostError("worker lease was lost before completion")
            self._insert_spans(connection, spans)
            return stored

    def fail_memory_job(
        self,
        *,
        job: dict[str, Any],
        error_code: str,
        spans: list[Span],
    ) -> None:
        with self.pool.connection() as connection, connection.transaction():
            failed = connection.execute(
                """
                UPDATE havre.background_jobs
                SET status = CASE WHEN attempt_count >= max_attempts
                                  THEN 'terminal_failed' ELSE 'retryable_failed' END,
                    available_at = clock_timestamp() + interval '1 second',
                    lease_owner = NULL, lease_expires_at = NULL,
                    last_error_code = %s,
                    completed_at = CASE WHEN attempt_count >= max_attempts
                                        THEN clock_timestamp() ELSE NULL END
                WHERE owner_id = %s AND job_id = %s AND status = 'leased'
                  AND lease_owner = %s AND attempt_count = %s
                  AND lease_expires_at > clock_timestamp()
                """,
                (
                    error_code, job["owner_id"], job["job_id"],
                    job["lease_owner"], job["attempt_count"],
                ),
            )
            if failed.rowcount != 1:
                raise LeaseLostError("worker lease was lost before failure submission")
            self._insert_spans(connection, spans)

    def list_memory_candidates(
        self, *, owner_id: UUID, status: str = "pending"
    ) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            return connection.execute(
                """
                SELECT * FROM havre.memory_candidates
                WHERE owner_id = %s AND status = %s
                ORDER BY created_at, candidate_id
                """,
                (owner_id, status),
            ).fetchall()

    def reject_memory_candidate(
        self, *, owner_id: UUID, candidate_id: UUID, reason: str
    ) -> dict[str, Any]:
        with self.pool.connection() as connection, connection.transaction():
            row = connection.execute(
                """
                UPDATE havre.memory_candidates
                SET status = 'rejected', reviewed_by = 'owner',
                    reviewed_at = clock_timestamp(), review_reason = %s
                WHERE owner_id = %s AND candidate_id = %s AND status = 'pending'
                RETURNING *
                """,
                (reason, owner_id, candidate_id),
            ).fetchone()
            if row is None:
                raise LookupError("pending memory candidate not found")
            return row

    def accept_memory_candidate(
        self,
        *,
        owner_id: UUID,
        candidate_id: UUID,
        reason: str,
        embedding_provider,
        importance: float | None = None,
    ) -> MemoryRevision:
        with self.pool.connection() as connection, connection.transaction():
            candidate = connection.execute(
                """
                SELECT candidate.*, event.session_id, event.request_id,
                       event.trace_id AS source_trace_id, event.recorded_at
                FROM havre.memory_candidates AS candidate
                JOIN havre.events AS event
                  ON event.owner_id = candidate.owner_id
                 AND event.event_id = candidate.source_event_id
                WHERE candidate.owner_id = %s AND candidate.candidate_id = %s
                FOR UPDATE OF candidate
                """,
                (owner_id, candidate_id),
            ).fetchone()
            if candidate is None:
                raise LookupError("memory candidate not found")
            if candidate["status"] == "accepted":
                row = connection.execute(
                    """
                    SELECT revision.* FROM havre.memory_revisions AS revision
                    WHERE owner_id = %s AND candidate_id = %s
                    """,
                    (owner_id, candidate_id),
                ).fetchone()
                return self._memory_from_row(row)
            if candidate["status"] != "pending":
                raise ValueError("only a pending candidate can be accepted")
            accepted_importance = (
                float(candidate["importance"])
                if importance is None
                else float(importance)
            )
            if not 0 <= accepted_importance <= 1:
                raise ValueError("importance must be between 0 and 1")
            importance_policy_version = (
                candidate["importance_policy_version"]
                if importance is None
                else "owner-review-importance-v1"
            )
            memory_id = uuid7()
            memory_policy = self._derived_policy_from_row(candidate)
            lifecycle_event = EventEnvelope(
                event_type=EventType.MEMORY_CREATED,
                owner_id=owner_id,
                session_id=candidate["session_id"],
                request_id=candidate["request_id"],
                trace_id=candidate["source_trace_id"],
                causation_event_id=candidate["source_event_id"],
                data_policy=memory_policy,
                payload=MemoryLifecyclePayload(
                    memory_id=memory_id,
                    memory_revision=1,
                    action="created",
                    reason=reason,
                    candidate_id=candidate_id,
                ),
            )
            self._insert_event(connection, lifecycle_event)
            revision = MemoryRevision(
                owner_id=owner_id,
                memory_id=memory_id,
                revision=1,
                content=candidate["content"],
                content_text=candidate["content_text"],
                confidence=float(candidate["confidence"]),
                confidence_method=candidate["confidence_method"],
                importance=accepted_importance,
                importance_policy_version=importance_policy_version,
                status=MemoryStatus.ACTIVE,
                source_occurred_at=candidate["recorded_at"],
                created_by="owner_review",
                transform_version=candidate["extractor_version"],
                candidate_id=candidate_id,
                created_event_id=lifecycle_event.event_id,
                trace_id=candidate["source_trace_id"],
                data_policy=memory_policy,
            )
            self._insert_memory_revision(connection, revision)
            connection.execute(
                """
                INSERT INTO havre.memory_heads (
                    owner_id, memory_id, current_revision, status
                ) VALUES (%s, %s, 1, 'active')
                """,
                (owner_id, memory_id),
            )
            self._insert_embedding(connection, revision, embedding_provider)
            self._insert_provenance(
                connection,
                owner_id=owner_id,
                source_kind="event",
                source_id=candidate["source_event_id"],
                source_revision=None,
                revision=revision,
                relation="derived_from",
                transform_name="episodic_extractor_owner_review",
                transform_version=candidate["extractor_version"],
                created_event_id=lifecycle_event.event_id,
            )
            connection.execute(
                """
                UPDATE havre.memory_candidates
                SET status = 'accepted', reviewed_by = 'owner',
                    reviewed_at = clock_timestamp(), review_reason = %s,
                    importance = %s, importance_policy_version = %s
                WHERE owner_id = %s AND candidate_id = %s
                """,
                (
                    reason, accepted_importance, importance_policy_version,
                    owner_id, candidate_id,
                ),
            )
            return revision

    def revise_memory(
        self,
        *,
        owner_id: UUID,
        memory_id: UUID,
        content_text: str,
        reason: str,
        embedding_provider,
    ) -> MemoryRevision:
        return self._transition_memory(
            owner_id=owner_id,
            memory_id=memory_id,
            content_text=content_text,
            reason=reason,
            status=MemoryStatus.ACTIVE,
            embedding_provider=embedding_provider,
        )

    def retract_memory(
        self, *, owner_id: UUID, memory_id: UUID, reason: str
    ) -> MemoryRevision:
        return self._transition_memory(
            owner_id=owner_id,
            memory_id=memory_id,
            content_text=None,
            reason=reason,
            status=MemoryStatus.RETRACTED,
            embedding_provider=None,
        )

    def _transition_memory(
        self,
        *,
        owner_id: UUID,
        memory_id: UUID,
        content_text: str | None,
        reason: str,
        status: MemoryStatus,
        embedding_provider,
    ) -> MemoryRevision:
        with self.pool.connection() as connection, connection.transaction():
            current = connection.execute(
                """
                SELECT revision.*, source_event.session_id, source_event.request_id,
                       source_event.event_id AS source_event_id
                FROM havre.memory_heads AS head
                JOIN havre.memory_revisions AS revision
                  ON revision.owner_id = head.owner_id
                 AND revision.memory_id = head.memory_id
                 AND revision.revision = head.current_revision
                JOIN havre.provenance_edges AS edge
                  ON edge.owner_id = revision.owner_id
                 AND edge.derived_kind = 'memory_revision'
                 AND edge.derived_id = revision.memory_id
                 AND edge.derived_revision = 1
                 AND edge.source_kind = 'event'
                 AND edge.relation = 'derived_from'
                JOIN havre.events AS source_event
                  ON source_event.owner_id = edge.owner_id
                 AND source_event.event_id = edge.source_id
                WHERE head.owner_id = %s AND head.memory_id = %s
                FOR UPDATE OF head
                """,
                (owner_id, memory_id),
            ).fetchone()
            if current is None:
                raise LookupError("memory not found")
            if current["status"] == "retracted":
                raise ValueError("a retracted memory cannot be changed")
            next_revision = current["revision"] + 1
            revision_policy = self._derived_policy_from_row(current)
            action = "retracted" if status is MemoryStatus.RETRACTED else "revised"
            event_type = (
                EventType.MEMORY_RETRACTED
                if status is MemoryStatus.RETRACTED
                else EventType.MEMORY_REVISED
            )
            lifecycle_event = EventEnvelope(
                event_type=event_type,
                owner_id=owner_id,
                session_id=current["session_id"],
                request_id=current["request_id"],
                trace_id=current["trace_id"],
                causation_event_id=current["created_event_id"],
                data_policy=revision_policy,
                payload=MemoryLifecyclePayload(
                    memory_id=memory_id,
                    memory_revision=next_revision,
                    action=action,
                    reason=reason,
                ),
            )
            self._insert_event(connection, lifecycle_event)
            revised_text = content_text if content_text is not None else current["content_text"]
            revised_content = dict(current["content"])
            revised_content["text"] = revised_text
            revision = MemoryRevision(
                owner_id=owner_id,
                memory_id=memory_id,
                revision=next_revision,
                memory_class=current["memory_class"],
                content=revised_content,
                content_text=revised_text,
                confidence=float(current["confidence"]),
                confidence_method="owner_correction" if content_text is not None else current["confidence_method"],
                importance=float(current["importance"]),
                importance_policy_version=current["importance_policy_version"],
                status=status,
                valid_from=current["valid_from"],
                valid_to=current["valid_to"],
                source_occurred_at=current["source_occurred_at"],
                created_by="owner",
                transform_version=self._transition_transform(status),
                supersedes_revision=current["revision"],
                created_event_id=lifecycle_event.event_id,
                trace_id=current["trace_id"],
                data_policy=revision_policy,
                created_at=max(
                    datetime.now(UTC),
                    current["created_at"] + timedelta(microseconds=1),
                ),
            )
            self._insert_memory_revision(connection, revision)
            connection.execute(
                """
                UPDATE havre.memory_heads
                SET current_revision = %s, status = %s,
                    updated_at = clock_timestamp()
                WHERE owner_id = %s AND memory_id = %s
                """,
                (next_revision, status.value, owner_id, memory_id),
            )
            if embedding_provider is not None:
                self._insert_embedding(connection, revision, embedding_provider)
            self._insert_provenance(
                connection,
                owner_id=owner_id,
                source_kind="memory_revision",
                source_id=memory_id,
                source_revision=current["revision"],
                revision=revision,
                relation="retracts" if status is MemoryStatus.RETRACTED else "corrects",
                transform_name="owner_memory_lifecycle",
                transform_version=revision.transform_version,
                created_event_id=lifecycle_event.event_id,
            )
            return revision

    def list_active_memories(self, *, owner_id: UUID) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            return connection.execute(
                """
                SELECT revision.*
                FROM havre.memory_heads AS head
                JOIN havre.memory_revisions AS revision
                  ON revision.owner_id = head.owner_id
                 AND revision.memory_id = head.memory_id
                 AND revision.revision = head.current_revision
                WHERE head.owner_id = %s AND head.status = 'active'
                ORDER BY revision.created_at, revision.memory_id
                """,
                (owner_id,),
            ).fetchall()

    def search_memory_candidates(
        self,
        *,
        request: RetrievalRequest,
        query_vector: str,
        embedding_version_id: str,
        use_vector_search: bool = True,
    ) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            return connection.execute(
                """
                SELECT revision.*,
                       CASE WHEN %s THEN embedding.embedding <=> %s::vector ELSE 0 END AS distance,
                       COALESCE(provenance.source_refs, ARRAY[]::text[]) AS source_refs
                FROM (
                    SELECT DISTINCT ON (history.owner_id, history.memory_id) history.*
                    FROM havre.memory_revisions AS history
                    WHERE history.owner_id = %s AND history.created_at <= %s
                    ORDER BY history.owner_id, history.memory_id, history.revision DESC
                ) AS revision
                JOIN havre.memory_embeddings AS embedding
                  ON embedding.owner_id = revision.owner_id
                 AND embedding.memory_id = revision.memory_id
                 AND embedding.memory_revision = revision.revision
                 AND embedding.embedding_version_id = %s
                LEFT JOIN LATERAL (
                    SELECT array_agg(
                        CASE edge.source_kind
                          WHEN 'event' THEN 'event/' || edge.source_id::text
                          ELSE 'memory/' || edge.source_id::text || '/revision/' || edge.source_revision::text
                        END ORDER BY edge.created_at
                    ) AS source_refs
                    FROM havre.provenance_edges AS edge
                    WHERE edge.owner_id = revision.owner_id
                      AND edge.derived_kind = 'memory_revision'
                      AND edge.derived_id = revision.memory_id
                      AND edge.derived_revision = revision.revision
                ) AS provenance ON true
                WHERE revision.owner_id = %s
                  AND revision.status = 'active'
                  AND revision.memory_class = ANY(%s)
                  AND revision.privacy_class = ANY(%s)
                  AND (%s::timestamptz IS NULL OR revision.source_occurred_at >= %s)
                  AND (%s::timestamptz IS NULL OR revision.source_occurred_at <= %s)
                ORDER BY CASE WHEN %s THEN embedding.embedding <=> %s::vector END,
                         revision.created_at DESC, revision.memory_id
                LIMIT %s
                """,
                (
                    use_vector_search,
                    query_vector,
                    request.owner_id,
                    request.as_of,
                    embedding_version_id,
                    request.owner_id,
                    list(request.filters.memory_classes),
                    [item.value for item in request.filters.allowed_privacy_classes],
                    request.filters.occurred_after,
                    request.filters.occurred_after,
                    request.filters.occurred_before,
                    request.filters.occurred_before,
                    use_vector_search,
                    query_vector,
                    request.candidate_k,
                ),
            ).fetchall()

    def persist_retrieval_result(
        self, *, request: RetrievalRequest, result: RetrievalResult
    ) -> None:
        with self.pool.connection() as connection, connection.transaction():
            connection.execute(
                """
                INSERT INTO havre.retrieval_results (
                    retrieval_result_id, retrieval_request_id, schema_version,
                    owner_id, request_id, query_event_id, trace_id, as_of,
                    request_snapshot, algorithm_version, embedding_version_id,
                    reranker_version_id, index_version, selection_policy_version,
                    minimum_semantic_similarity, duplicate_similarity_threshold,
                    duplicate_token_overlap_threshold, candidates, exclusions,
                    timing_ms, degraded_components, content_hash, created_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                ) ON CONFLICT (retrieval_request_id) DO NOTHING
                """,
                (
                    result.retrieval_result_id,
                    result.retrieval_request_id,
                    result.schema_version,
                    result.owner_id,
                    result.request_id,
                    result.query_event_id,
                    result.trace_id,
                    result.as_of,
                    Jsonb(request.model_dump(mode="json")),
                    result.versions.algorithm_version,
                    result.versions.embedding_version_id,
                    result.versions.reranker_version_id,
                    result.versions.index_version,
                    result.selection_policy.policy_version,
                    result.selection_policy.minimum_semantic_similarity,
                    result.selection_policy.duplicate_similarity_threshold,
                    result.selection_policy.duplicate_token_overlap_threshold,
                    Jsonb([item.model_dump(mode="json") for item in result.candidates]),
                    Jsonb([item.model_dump(mode="json") for item in result.exclusions]),
                    Jsonb(result.timing_ms.model_dump(mode="json")),
                    Jsonb(list(result.degraded_components)),
                    result.content_hash,
                    result.created_at,
                ),
            )

    def persist_benchmark_report(self, report: dict[str, Any]) -> None:
        with self.pool.connection() as connection, connection.transaction():
            connection.execute(
                """
                INSERT INTO havre.retrieval_benchmark_runs (
                    benchmark_run_id, schema_version, gold_set_version,
                    corpus_hash, algorithm_versions, embedding_version_id,
                    environment, metrics, case_results, content_hash, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    report["benchmark_run_id"], report["schema_version"],
                    report["gold_set_version"], report["corpus_hash"],
                    Jsonb(report["algorithm_versions"]), report["embedding_version_id"],
                    Jsonb(report["environment"]), Jsonb(report["metrics"]),
                    Jsonb(report["case_results"]), report["content_hash"],
                    report["created_at"],
                ),
            )

    def erase_source_event_derivatives(
        self, *, owner_id: UUID, source_event_id: UUID
    ) -> dict[str, int]:
        """Erase every stored copy derived from a source event.

        The raw source event deliberately remains so its independently governed
        deletion can be authorized separately. The transaction removes pending
        work as well as accepted memory and any later retrieval/prompt/answer
        artifact that copied or could have been influenced by that memory.
        """
        with self.pool.connection() as connection, connection.transaction():
            connection.execute("SET LOCAL havre.privileged_erasure = 'on'")
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"offline-owner:{owner_id}",),
            )
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"offline-source:{owner_id}:{source_event_id}",),
            )
            connection.execute(
                """
                INSERT INTO havre.offline_source_revocations (
                    owner_id, source_event_id, reason
                ) VALUES (%s, %s, 'derived_erasure_requested')
                ON CONFLICT (owner_id, source_event_id) DO NOTHING
                """,
                (owner_id, source_event_id),
            )
            context_observation_ids = [
                row["observation_id"]
                for row in connection.execute(
                    """
                    SELECT observation_id FROM havre.life_context_observations
                    WHERE owner_id=%s AND event_id=%s
                    """,
                    (owner_id, source_event_id),
                ).fetchall()
            ] if connection.execute(
                "SELECT to_regclass('havre.life_context_observations') IS NOT NULL AS present"
            ).fetchone()["present"] else []
            context_health_count = connection.execute(
                """
                DELETE FROM havre.context_source_health_records
                WHERE owner_id=%s AND (
                    causal_event_id=%s
                    OR last_successful_observation_id = ANY(%s::uuid[])
                )
                RETURNING 1
                """,
                (owner_id, source_event_id, context_observation_ids),
            ).rowcount if connection.execute(
                "SELECT to_regclass('havre.context_source_health_records') IS NOT NULL AS present"
            ).fetchone()["present"] else 0
            context_observation_count = connection.execute(
                """
                DELETE FROM havre.life_context_observations
                WHERE owner_id=%s AND observation_id = ANY(%s::uuid[])
                RETURNING 1
                """,
                (owner_id, context_observation_ids),
            ).rowcount if context_observation_ids else 0
            stage7_reflection_ids = [
                row["reflection_proposal_id"]
                for row in connection.execute(
                    """
                    SELECT reflection_proposal_id
                    FROM havre.reflection_proposal_evidence
                    WHERE owner_id = %s AND source_event_id = %s
                    """,
                    (owner_id, source_event_id),
                ).fetchall()
            ]
            stage7_lifecycle_ids = [
                row["lifecycle_proposal_id"]
                for row in connection.execute(
                    """
                    SELECT lifecycle_proposal_id
                    FROM havre.memory_lifecycle_proposal_evidence
                    WHERE owner_id = %s AND source_event_id = %s
                    """,
                    (owner_id, source_event_id),
                ).fetchall()
            ]
            stage7_snapshot_ids = [
                row["dataset_snapshot_id"]
                for row in connection.execute(
                    """
                    SELECT dataset_snapshot_id FROM havre.dataset_snapshot_sources
                    WHERE owner_id = %s AND source_event_id = %s
                    """,
                    (owner_id, source_event_id),
                ).fetchall()
            ]
            stage7_review_count = connection.execute(
                """
                DELETE FROM havre.memory_lifecycle_reviews
                WHERE owner_id = %s
                  AND lifecycle_proposal_id = ANY(%s::uuid[])
                RETURNING 1
                """,
                (owner_id, stage7_lifecycle_ids),
            ).rowcount
            connection.execute(
                """
                DELETE FROM havre.reflection_proposal_evidence
                WHERE owner_id = %s
                  AND reflection_proposal_id = ANY(%s::uuid[])
                """,
                (owner_id, stage7_reflection_ids),
            )
            stage7_reflection_count = connection.execute(
                """
                DELETE FROM havre.reflection_proposals
                WHERE owner_id = %s
                  AND reflection_proposal_id = ANY(%s::uuid[])
                RETURNING 1
                """,
                (owner_id, stage7_reflection_ids),
            ).rowcount
            connection.execute(
                """
                DELETE FROM havre.memory_lifecycle_proposal_evidence
                WHERE owner_id = %s
                  AND lifecycle_proposal_id = ANY(%s::uuid[])
                """,
                (owner_id, stage7_lifecycle_ids),
            )
            stage7_lifecycle_count = connection.execute(
                """
                DELETE FROM havre.memory_lifecycle_proposals
                WHERE owner_id = %s
                  AND lifecycle_proposal_id = ANY(%s::uuid[])
                RETURNING 1
                """,
                (owner_id, stage7_lifecycle_ids),
            ).rowcount
            stage7_manifest_count = connection.execute(
                """
                DELETE FROM havre.offline_artifact_manifests
                WHERE owner_id = %s
                  AND dataset_snapshot_id = ANY(%s::uuid[])
                RETURNING 1
                """,
                (owner_id, stage7_snapshot_ids),
            ).rowcount
            connection.execute(
                """
                DELETE FROM havre.dataset_snapshot_sources
                WHERE owner_id = %s
                  AND dataset_snapshot_id = ANY(%s::uuid[])
                """,
                (owner_id, stage7_snapshot_ids),
            )
            stage7_snapshot_count = connection.execute(
                """
                DELETE FROM havre.canonical_dataset_snapshots
                WHERE owner_id = %s
                  AND dataset_snapshot_id = ANY(%s::uuid[])
                RETURNING 1
                """,
                (owner_id, stage7_snapshot_ids),
            ).rowcount
            candidate_rows = connection.execute(
                """
                SELECT candidate_id
                FROM havre.memory_candidates
                WHERE owner_id = %s AND source_event_id = %s
                """,
                (owner_id, source_event_id),
            ).fetchall()
            candidate_ids = [row["candidate_id"] for row in candidate_rows]
            lineage_rows = connection.execute(
                """
                WITH RECURSIVE lineage(kind, id, revision) AS (
                    VALUES ('event'::text, %s::uuid, NULL::integer)
                    UNION
                    SELECT edge.derived_kind, edge.derived_id,
                           edge.derived_revision
                    FROM havre.provenance_edges AS edge
                    JOIN lineage AS source
                      ON edge.owner_id = %s
                     AND edge.source_kind = source.kind
                     AND edge.source_id = source.id
                     AND (
                         source.kind = 'event'
                         OR source.kind IN ('memory_revision', 'belief_revision')
                     )
                )
                SELECT kind, id, revision
                FROM lineage
                WHERE kind <> 'event'
                """,
                (source_event_id, owner_id),
            ).fetchall()
            lineage_by_kind: dict[str, set[UUID]] = {}
            for row in lineage_rows:
                lineage_by_kind.setdefault(row["kind"], set()).add(row["id"])
            scene_rows = connection.execute(
                """
                SELECT DISTINCT scene_session_id
                FROM havre.events
                WHERE owner_id = %s AND event_id = %s
                  AND scene_session_id IS NOT NULL
                """,
                (owner_id, source_event_id),
            ).fetchall()
            scene_ids = [row["scene_session_id"] for row in scene_rows]
            scene_decision_rows = connection.execute(
                """
                SELECT intervention_decision_id, decision_event_id, guidance_event_id
                FROM havre.intervention_decisions
                WHERE owner_id = %s AND scene_session_id = ANY(%s::uuid[])
                """,
                (owner_id, scene_ids),
            ).fetchall()
            scene_decision_ids = [
                row["intervention_decision_id"] for row in scene_decision_rows
            ]
            scene_outcome_rows = connection.execute(
                """
                SELECT outcome_observation_id
                FROM havre.guidance_outcome_observations
                WHERE owner_id = %s AND scene_session_id = ANY(%s::uuid[])
                """,
                (owner_id, scene_ids),
            ).fetchall()
            scene_outcome_ids = [
                row["outcome_observation_id"] for row in scene_outcome_rows
            ]
            memory_rows = connection.execute(
                """
                SELECT DISTINCT memory_id
                FROM (
                    SELECT derived_id AS memory_id
                    FROM havre.provenance_edges
                    WHERE owner_id = %s
                      AND source_kind = 'event' AND source_id = %s
                    UNION
                    SELECT memory_id
                    FROM havre.memory_revisions
                    WHERE owner_id = %s
                      AND candidate_id = ANY(%s::uuid[])
                    UNION
                    SELECT id AS memory_id
                    FROM unnest(%s::uuid[]) AS id
                ) AS source_memories
                """,
                (
                    owner_id,
                    source_event_id,
                    owner_id,
                    candidate_ids,
                    list(lineage_by_kind.get("memory_revision", set())),
                ),
            ).fetchall()
            memory_ids = [row["memory_id"] for row in memory_rows]
            belief_ids = list(lineage_by_kind.get("belief_revision", set()))
            proposal_ids = list(
                lineage_by_kind.get("consolidation_proposal", set())
            )
            state_snapshot_ids = list(
                lineage_by_kind.get("current_state_snapshot", set())
            )
            progress_record_ids = set(
                lineage_by_kind.get("goal_progress_record", set())
            )
            goal_rows = connection.execute(
                """
                SELECT goal_id, revision
                FROM havre.goals
                WHERE owner_id = %s
                  AND goal_id IN (
                      SELECT (event.payload->>'goal_id')::uuid
                      FROM havre.events AS event
                      WHERE event.owner_id = %s
                        AND event.event_type = 'GOAL_CREATED'
                        AND event.causation_event_id = %s
                  )
                """,
                (owner_id, owner_id, source_event_id),
            ).fetchall()
            goal_ids = [row["goal_id"] for row in goal_rows]
            progress_record_ids.update(
                row["progress_record_id"]
                for row in connection.execute(
                    """
                    SELECT progress_record_id
                    FROM havre.goal_progress_records
                    WHERE owner_id = %s AND goal_id = ANY(%s::uuid[])
                    """,
                    (owner_id, goal_ids),
                ).fetchall()
            )
            proposal_rows = connection.execute(
                """
                SELECT accepted_memory_id
                FROM havre.consolidation_proposals
                WHERE owner_id = %s AND proposal_id = ANY(%s::uuid[])
                  AND accepted_memory_id IS NOT NULL
                """,
                (owner_id, proposal_ids),
            ).fetchall()
            memory_ids = list(
                {
                    *memory_ids,
                    *(row["accepted_memory_id"] for row in proposal_rows),
                }
            )
            memory_id_strings = [str(memory_id) for memory_id in memory_ids]
            source_refs = [f"event/{source_event_id}"] + [
                f"memory/{memory_id}/revision/{row['revision']}"
                for memory_id in memory_ids
                for row in connection.execute(
                    """
                    SELECT revision FROM havre.memory_revisions
                    WHERE owner_id = %s AND memory_id = %s
                    """,
                    (owner_id, memory_id),
                ).fetchall()
            ]
            source_refs.extend(
                f"belief/{belief_id}@{row['revision']}"
                for belief_id in belief_ids
                for row in connection.execute(
                    """
                    SELECT revision FROM havre.user_belief_revisions
                    WHERE owner_id = %s AND belief_id = %s
                    """,
                    (owner_id, belief_id),
                ).fetchall()
            )
            source_refs.extend(
                f"current-state/{state_snapshot_id}"
                for state_snapshot_id in state_snapshot_ids
            )
            source_refs.extend(
                f"goal/{row['goal_id']}@{revision}"
                for row in goal_rows
                for revision in range(1, row["revision"] + 1)
            )
            retrieval_rows = connection.execute(
                """
                SELECT retrieval_result_id, request_id
                FROM havre.retrieval_results AS result
                WHERE owner_id = %s
                  AND (
                    query_event_id = %s
                    OR EXISTS (
                        SELECT 1
                        FROM jsonb_array_elements(result.candidates) AS candidate
                        WHERE candidate->>'memory_id' = ANY(%s::text[])
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM jsonb_array_elements(result.exclusions) AS exclusion
                        WHERE exclusion->>'memory_id' = ANY(%s::text[])
                           OR exclusion->>'duplicate_of_memory_id'
                              = ANY(%s::text[])
                    )
                  )
                """,
                (
                    owner_id, source_event_id, memory_id_strings,
                    memory_id_strings, memory_id_strings,
                ),
            ).fetchall()
            retrieval_result_ids = [
                row["retrieval_result_id"] for row in retrieval_rows
            ]
            request_ids = {row["request_id"] for row in retrieval_rows}

            context_rows = connection.execute(
                """
                SELECT context_pack_id, request_id
                FROM havre.context_packs AS pack
                WHERE owner_id = %s
                  AND (
                    retrieval_result_id = ANY(%s::uuid[])
                    OR EXISTS (
                        SELECT 1
                        FROM jsonb_array_elements(pack.sections) AS section
                        CROSS JOIN LATERAL jsonb_array_elements_text(
                            COALESCE(section->'source_refs', '[]'::jsonb)
                        ) AS source_ref
                        WHERE source_ref.value = ANY(%s::text[])
                    )
                  )
                """,
                (owner_id, retrieval_result_ids, source_refs),
            ).fetchall()
            request_ids.update(row["request_id"] for row in context_rows)
            source_request = connection.execute(
                """
                SELECT request_id FROM havre.events
                WHERE owner_id = %s AND event_id = %s
                """,
                (owner_id, source_event_id),
            ).fetchone()
            if source_request is not None:
                request_ids.add(source_request["request_id"])
            scene_request_rows = connection.execute(
                """
                SELECT DISTINCT request_id
                FROM havre.events
                WHERE owner_id = %s AND scene_session_id = ANY(%s::uuid[])
                """,
                (owner_id, scene_ids),
            ).fetchall()
            request_ids.update(row["request_id"] for row in scene_request_rows)
            request_id_list = list(request_ids)

            terminal_event_rows = connection.execute(
                """
                SELECT event_id, event_type FROM havre.events
                WHERE owner_id = %s AND request_id = ANY(%s::uuid[])
                  AND event_id <> %s
                  AND event_type IN (
                      'ASSISTANT_MESSAGE', 'INTERACTION_FAILED',
                      'INTERVENTION_DECIDED'
                  )
                """,
                (owner_id, request_id_list, source_event_id),
            ).fetchall()
            terminal_event_ids = [row["event_id"] for row in terminal_event_rows]
            # Feedback and episode summaries are derivatives of exact raw
            # interaction Events. Remove their complete provenance-bound
            # closure before terminal/source Event deletion; immutable-table
            # triggers admit this only under the privileged erasure flag.
            feedback_ids = [
                row["feedback_id"]
                for row in connection.execute(
                    """
                    SELECT feedback_id FROM havre.response_feedback_heads
                    WHERE owner_id=%s AND request_id = ANY(%s::uuid[])
                    """,
                    (owner_id, request_id_list),
                ).fetchall()
            ]
            connection.execute(
                """DELETE FROM havre.personalization_feedback_reviews
                   WHERE owner_id=%s AND feedback_id = ANY(%s::uuid[])""",
                (owner_id, feedback_ids),
            )
            connection.execute(
                """DELETE FROM havre.response_feedback_revisions
                   WHERE owner_id=%s AND feedback_id = ANY(%s::uuid[])""",
                (owner_id, feedback_ids),
            )
            connection.execute(
                """DELETE FROM havre.response_feedback_heads
                   WHERE owner_id=%s AND feedback_id = ANY(%s::uuid[])""",
                (owner_id, feedback_ids),
            )
            episode_ids = [
                row["episode_id"]
                for row in connection.execute(
                    """
                    SELECT DISTINCT episode_id
                    FROM havre.conversation_episode_members
                    WHERE owner_id=%s
                      AND event_id = ANY(%s::uuid[])
                    """,
                    (owner_id, [source_event_id, *terminal_event_ids]),
                ).fetchall()
            ]
            connection.execute(
                """DELETE FROM havre.episode_memory_suggestions
                   WHERE owner_id=%s AND episode_id = ANY(%s::uuid[])""",
                (owner_id, episode_ids),
            )
            connection.execute(
                """DELETE FROM havre.conversation_episode_members
                   WHERE owner_id=%s AND episode_id = ANY(%s::uuid[])""",
                (owner_id, episode_ids),
            )
            connection.execute(
                """UPDATE havre.sessions SET closed_episode_id=NULL
                   WHERE owner_id=%s AND closed_episode_id = ANY(%s::uuid[])""",
                (owner_id, episode_ids),
            )
            connection.execute(
                """DELETE FROM havre.conversation_episodes
                   WHERE owner_id=%s AND episode_id = ANY(%s::uuid[])""",
                (owner_id, episode_ids),
            )
            assistant_event_count_expected = sum(
                row["event_type"] == "ASSISTANT_MESSAGE" for row in terminal_event_rows
            )
            failure_event_count_expected = sum(
                row["event_type"] == "INTERACTION_FAILED" for row in terminal_event_rows
            )
            intervention_event_count_expected = sum(
                row["event_type"] == "INTERVENTION_DECIDED"
                for row in terminal_event_rows
            )
            requests_invalidated = connection.execute(
                """
                UPDATE havre.interaction_requests
                SET assistant_event_id = NULL, context_pack_id = NULL,
                    inference_attempt_id = NULL, inference_response_id = NULL,
                    failure_event_id = NULL, status = 'failed',
                    error_code = 'source_erasure_propagated'
                WHERE owner_id = %s AND request_id = ANY(%s::uuid[])
                RETURNING 1
                """,
                (owner_id, request_id_list),
            ).rowcount
            stage5_edge_count = connection.execute(
                """
                DELETE FROM havre.provenance_edges
                WHERE owner_id = %s AND (
                    (derived_kind = 'intervention_decision'
                     AND derived_id = ANY(%s::uuid[]))
                    OR (derived_kind = 'guidance_outcome_observation'
                        AND derived_id = ANY(%s::uuid[]))
                )
                RETURNING 1
                """,
                (owner_id, scene_decision_ids, scene_outcome_ids),
            ).rowcount
            scene_outcome_count = connection.execute(
                """
                DELETE FROM havre.guidance_outcome_observations
                WHERE owner_id = %s AND scene_session_id = ANY(%s::uuid[])
                RETURNING 1
                """,
                (owner_id, scene_ids),
            ).rowcount
            scene_decision_count = connection.execute(
                """
                DELETE FROM havre.intervention_decisions
                WHERE owner_id = %s AND scene_session_id = ANY(%s::uuid[])
                RETURNING 1
                """,
                (owner_id, scene_ids),
            ).rowcount
            scene_record_count = connection.execute(
                """
                DELETE FROM havre.scene_records
                WHERE owner_id = %s AND scene_session_id = ANY(%s::uuid[])
                RETURNING 1
                """,
                (owner_id, scene_ids),
            ).rowcount

            retained_scene_event_rows = connection.execute(
                """
                SELECT * FROM havre.events
                WHERE owner_id = %s
                  AND scene_session_id = ANY(%s::uuid[])
                  AND event_id <> ALL(%s::uuid[])
                ORDER BY recorded_at, event_id
                """,
                (owner_id, scene_ids, terminal_event_ids),
            ).fetchall()
            terminal_event_id_set = set(terminal_event_ids)
            for row in retained_scene_event_rows:
                detached_event = EventEnvelope.model_validate(
                    {
                        "schema_version": row["schema_version"],
                        "event_id": row["event_id"],
                        "event_type": row["event_type"],
                        "event_version": row["event_version"],
                        "owner_id": row["owner_id"],
                        "session_id": row["session_id"],
                        "request_id": row["request_id"],
                        "trace_id": row["trace_id"].strip(),
                        "causation_event_id": (
                            None
                            if row["causation_event_id"] in terminal_event_id_set
                            else row["causation_event_id"]
                        ),
                        "data_policy": self._policy_from_row(row),
                        "payload": row["payload"],
                        "recorded_at": row["recorded_at"],
                    }
                )
                connection.execute(
                    """
                    UPDATE havre.events
                    SET scene_session_id = NULL, causation_event_id = %s,
                        content_hash = %s
                    WHERE owner_id = %s AND event_id = %s
                    """,
                    (
                        detached_event.causation_event_id,
                        detached_event.content_hash,
                        owner_id,
                        detached_event.event_id,
                    ),
                )
            connection.execute(
                """
                UPDATE havre.events SET scene_session_id = NULL
                WHERE owner_id = %s
                  AND scene_session_id = ANY(%s::uuid[])
                  AND event_id = ANY(%s::uuid[])
                """,
                (owner_id, scene_ids, terminal_event_ids),
            )
            scene_session_count = connection.execute(
                """
                DELETE FROM havre.scene_sessions
                WHERE owner_id = %s AND scene_session_id = ANY(%s::uuid[])
                RETURNING 1
                """,
                (owner_id, scene_ids),
            ).rowcount
            terminal_event_count = connection.execute(
                """
                DELETE FROM havre.events
                WHERE owner_id = %s AND event_id = ANY(%s::uuid[])
                RETURNING 1
                """,
                (owner_id, terminal_event_ids),
            ).rowcount
            if terminal_event_count != len(terminal_event_ids):
                raise RuntimeError("terminal event erasure count mismatch")
            assistant_event_count = assistant_event_count_expected
            failure_event_count = failure_event_count_expected
            intervention_event_count = intervention_event_count_expected
            inference_count = connection.execute(
                """
                DELETE FROM havre.inference_attempts
                WHERE owner_id = %s AND request_id = ANY(%s::uuid[])
                RETURNING 1
                """,
                (owner_id, request_id_list),
            ).rowcount
            route_count = connection.execute(
                """
                DELETE FROM havre.route_decisions
                WHERE owner_id = %s AND request_id = ANY(%s::uuid[])
                RETURNING 1
                """,
                (owner_id, request_id_list),
            ).rowcount
            context_count = connection.execute(
                """
                DELETE FROM havre.context_packs
                WHERE owner_id = %s AND request_id = ANY(%s::uuid[])
                RETURNING 1
                """,
                (owner_id, request_id_list),
            ).rowcount
            retrieval_count = connection.execute(
                """
                DELETE FROM havre.retrieval_results
                WHERE owner_id = %s AND retrieval_result_id = ANY(%s::uuid[])
                RETURNING 1
                """,
                (owner_id, retrieval_result_ids),
            ).rowcount

            lifecycle_event_rows = connection.execute(
                """
                SELECT created_event_id AS event_id
                FROM havre.memory_revisions
                WHERE owner_id = %s AND memory_id = ANY(%s::uuid[])
                UNION
                SELECT created_event_id FROM havre.user_belief_revisions
                WHERE owner_id = %s AND belief_id = ANY(%s::uuid[])
                UNION
                SELECT causing_event_id FROM havre.belief_revision_transitions
                WHERE owner_id = %s AND belief_id = ANY(%s::uuid[])
                UNION
                SELECT created_event_id FROM havre.consolidation_proposals
                WHERE owner_id = %s AND proposal_id = ANY(%s::uuid[])
                UNION
                SELECT review_event_id FROM havre.consolidation_proposals
                WHERE owner_id = %s AND proposal_id = ANY(%s::uuid[])
                  AND review_event_id IS NOT NULL
                UNION
                SELECT created_event_id FROM havre.current_state_snapshots
                WHERE owner_id = %s AND state_snapshot_id = ANY(%s::uuid[])
                UNION
                SELECT created_event_id FROM havre.goal_progress_records
                WHERE owner_id = %s AND progress_record_id = ANY(%s::uuid[])
                UNION
                SELECT event_id FROM havre.events
                WHERE owner_id = %s
                  AND event_type IN ('GOAL_CREATED', 'GOAL_UPDATED', 'GOAL_COMPLETED')
                  AND (payload->>'goal_id')::uuid = ANY(%s::uuid[])
                """,
                (
                    owner_id,
                    memory_ids,
                    owner_id,
                    belief_ids,
                    owner_id,
                    belief_ids,
                    owner_id,
                    proposal_ids,
                    owner_id,
                    proposal_ids,
                    owner_id,
                    state_snapshot_ids,
                    owner_id,
                    list(progress_record_ids),
                    owner_id,
                    goal_ids,
                ),
            ).fetchall()
            lifecycle_event_ids = [row["event_id"] for row in lifecycle_event_rows]
            edge_count = stage5_edge_count + connection.execute(
                """
                DELETE FROM havre.provenance_edges
                WHERE owner_id = %s AND (
                    (source_kind = 'event' AND source_id = %s)
                    OR (source_kind = 'memory_revision' AND source_id = ANY(%s::uuid[]))
                    OR (source_kind = 'belief_revision' AND source_id = ANY(%s::uuid[]))
                    OR (derived_kind = 'memory_revision' AND derived_id = ANY(%s::uuid[]))
                    OR (derived_kind = 'belief_revision' AND derived_id = ANY(%s::uuid[]))
                    OR (derived_kind = 'consolidation_proposal' AND derived_id = ANY(%s::uuid[]))
                    OR (derived_kind = 'current_state_snapshot' AND derived_id = ANY(%s::uuid[]))
                    OR (derived_kind = 'goal_progress_record' AND derived_id = ANY(%s::uuid[]))
                )
                RETURNING 1
                """,
                (
                    owner_id,
                    source_event_id,
                    memory_ids,
                    belief_ids,
                    memory_ids,
                    belief_ids,
                    proposal_ids,
                    state_snapshot_ids,
                    list(progress_record_ids),
                ),
            ).rowcount
            progress_count = connection.execute(
                """
                DELETE FROM havre.goal_progress_records
                WHERE owner_id = %s AND progress_record_id = ANY(%s::uuid[])
                RETURNING 1
                """,
                (owner_id, list(progress_record_ids)),
            ).rowcount
            proposal_count = connection.execute(
                """
                DELETE FROM havre.consolidation_proposals
                WHERE owner_id = %s AND proposal_id = ANY(%s::uuid[])
                RETURNING 1
                """,
                (owner_id, proposal_ids),
            ).rowcount
            state_count = connection.execute(
                """
                DELETE FROM havre.current_state_snapshots
                WHERE owner_id = %s AND state_snapshot_id = ANY(%s::uuid[])
                RETURNING 1
                """,
                (owner_id, state_snapshot_ids),
            ).rowcount
            belief_transition_count = connection.execute(
                """
                DELETE FROM havre.belief_revision_transitions
                WHERE owner_id = %s AND belief_id = ANY(%s::uuid[])
                RETURNING 1
                """,
                (owner_id, belief_ids),
            ).rowcount
            connection.execute(
                """
                DELETE FROM havre.belief_heads
                WHERE owner_id = %s AND belief_id = ANY(%s::uuid[])
                """,
                (owner_id, belief_ids),
            )
            belief_count = connection.execute(
                """
                DELETE FROM havre.user_belief_revisions
                WHERE owner_id = %s AND belief_id = ANY(%s::uuid[])
                RETURNING 1
                """,
                (owner_id, belief_ids),
            ).rowcount
            goal_count = connection.execute(
                """
                DELETE FROM havre.goals
                WHERE owner_id = %s AND goal_id = ANY(%s::uuid[])
                RETURNING 1
                """,
                (owner_id, goal_ids),
            ).rowcount
            embedding_count = connection.execute(
                "DELETE FROM havre.memory_embeddings WHERE owner_id = %s AND memory_id = ANY(%s::uuid[]) RETURNING 1",
                (owner_id, memory_ids),
            ).rowcount
            connection.execute(
                "DELETE FROM havre.memory_heads WHERE owner_id = %s AND memory_id = ANY(%s::uuid[])",
                (owner_id, memory_ids),
            )
            memory_count = connection.execute(
                "DELETE FROM havre.memory_revisions WHERE owner_id = %s AND memory_id = ANY(%s::uuid[]) RETURNING 1",
                (owner_id, memory_ids),
            ).rowcount
            candidate_count = connection.execute(
                "DELETE FROM havre.memory_candidates WHERE owner_id = %s AND source_event_id = %s RETURNING 1",
                (owner_id, source_event_id),
            ).rowcount
            job_count = connection.execute(
                "DELETE FROM havre.background_jobs WHERE owner_id = %s AND source_event_id = %s RETURNING 1",
                (owner_id, source_event_id),
            ).rowcount
            lifecycle_event_count = connection.execute(
                """
                DELETE FROM havre.events
                WHERE owner_id = %s AND event_id = ANY(%s::uuid[])
                RETURNING 1
                """,
                (owner_id, lifecycle_event_ids),
            ).rowcount
            return {
                "requests_invalidated": requests_invalidated,
                "retrieval_results": retrieval_count,
                "context_packs": context_count,
                "inference_attempts": inference_count,
                "route_decisions": route_count,
                "assistant_events": assistant_event_count,
                "failure_events": failure_event_count,
                "intervention_events": intervention_event_count,
                "lifecycle_events": lifecycle_event_count,
                "memories": memory_count,
                "embeddings": embedding_count,
                "edges": edge_count,
                "candidates": candidate_count,
                "jobs": job_count,
                "belief_revisions": belief_count,
                "belief_transitions": belief_transition_count,
                "consolidation_proposals": proposal_count,
                "current_state_snapshots": state_count,
                "goal_progress_records": progress_count,
                "goals": goal_count,
                "scene_sessions": scene_session_count,
                "scene_records": scene_record_count,
                "intervention_decisions": scene_decision_count,
                "guidance_outcome_observations": scene_outcome_count,
                "reflection_proposals": stage7_reflection_count,
                "memory_lifecycle_proposals": stage7_lifecycle_count,
                "memory_lifecycle_reviews": stage7_review_count,
                "dataset_snapshots": stage7_snapshot_count,
                "offline_artifact_manifests": stage7_manifest_count,
                "life_context_observations": context_observation_count,
                "context_source_health_records": context_health_count,
            }

    def create_belief_revision(
        self,
        *,
        owner_id: UUID,
        belief_key: str,
        statement: str,
        belief_type: BeliefType,
        confidence: float,
        evidence: tuple[EvidenceRef, ...],
        reason: str,
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
    ) -> BeliefRevision:
        if not reason.strip():
            raise ValueError("belief proposal reason is required")
        with self.pool.connection() as connection, connection.transaction():
            rows = self._load_stage4_evidence(
                connection, owner_id=owner_id, evidence=evidence
            )
            policy = self._combine_stage4_evidence_policy(rows)
            anchor = rows[0]
            existing = connection.execute(
                """
                SELECT belief_id FROM havre.belief_heads
                WHERE owner_id = %s AND belief_key = %s
                """,
                (owner_id, belief_key),
            ).fetchone()
            if existing is not None:
                raise ValueError("belief_key already has a stable belief identity")
            belief_id = uuid7()
            lifecycle_event = EventEnvelope(
                event_type=EventType.USER_BELIEF_CREATED,
                owner_id=owner_id,
                session_id=anchor["session_id"],
                request_id=anchor["request_id"],
                trace_id=anchor["trace_id"],
                causation_event_id=anchor["anchor_event_id"],
                data_policy=policy,
                payload=BeliefLifecyclePayload(
                    belief_id=belief_id,
                    belief_revision=1,
                    action="created",
                    reason=reason,
                ),
            )
            self._insert_event(connection, lifecycle_event)
            occurred_from, occurred_to, learned_at = self._evidence_times(rows)
            revision = BeliefRevision(
                owner_id=owner_id,
                belief_id=belief_id,
                revision=1,
                belief_key=belief_key,
                statement=statement,
                belief_type=belief_type,
                confidence=confidence,
                initial_status=BeliefInitialStatus.CANDIDATE,
                evidence_occurred_from=occurred_from,
                evidence_occurred_to=occurred_to,
                learned_at=learned_at,
                valid_from=valid_from,
                valid_to=valid_to,
                created_event_id=lifecycle_event.event_id,
                trace_id=lifecycle_event.trace_id,
                data_policy=policy,
            )
            revision = self._insert_belief_revision(connection, revision)
            connection.execute(
                """
                INSERT INTO havre.belief_heads (
                    owner_id, belief_id, belief_key, current_revision, status
                ) VALUES (%s, %s, %s, 1, 'candidate')
                """,
                (owner_id, belief_id, belief_key),
            )
            self._insert_stage4_evidence_edges(
                connection,
                owner_id=owner_id,
                evidence=evidence,
                derived_kind="belief_revision",
                derived_id=belief_id,
                derived_revision=1,
                transform_name="owner_belief_proposal",
                transform_version="user-model-service-v1",
                created_event_id=lifecycle_event.event_id,
                trace_id=lifecycle_event.trace_id,
            )
            return revision

    def revise_belief(
        self,
        *,
        owner_id: UUID,
        belief_id: UUID,
        expected_revision: int,
        statement: str,
        confidence: float,
        evidence: tuple[EvidenceRef, ...],
        reason: str,
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
    ) -> dict[str, object]:
        if not reason.strip():
            raise ValueError("belief revision reason is required")
        with self.pool.connection() as connection, connection.transaction():
            current = connection.execute(
                """
                SELECT revision.*, head.status AS effective_status,
                       event.session_id, event.request_id,
                       event.event_id AS anchor_event_id
                FROM havre.belief_heads AS head
                JOIN havre.user_belief_revisions AS revision
                  ON revision.owner_id = head.owner_id
                 AND revision.belief_id = head.belief_id
                 AND revision.revision = head.current_revision
                JOIN havre.events AS event
                  ON event.owner_id = revision.owner_id
                 AND event.event_id = revision.created_event_id
                WHERE head.owner_id = %s AND head.belief_id = %s
                FOR UPDATE OF head
                """,
                (owner_id, belief_id),
            ).fetchone()
            if current is None:
                raise LookupError("belief not found")
            if current["revision"] != expected_revision:
                raise ValueError("belief revision precondition failed")
            if current["effective_status"] in {"retracted", "invalidated", "superseded"}:
                raise ValueError("terminal belief cannot be revised")
            rows = self._load_stage4_evidence(
                connection, owner_id=owner_id, evidence=evidence
            )
            prior_ref = EvidenceRef(
                source_kind=EvidenceSourceKind.BELIEF_REVISION,
                source_id=belief_id,
                source_revision=expected_revision,
                relation=EvidenceRelation.SUPPORTS,
            )
            prior_row = self._load_stage4_evidence(
                connection, owner_id=owner_id, evidence=(prior_ref,)
            )[0]
            policy = self._combine_stage4_evidence_policy([*rows, prior_row])
            anchor = rows[0]
            next_revision = expected_revision + 1
            lifecycle_event = EventEnvelope(
                event_type=EventType.USER_BELIEF_REVISED,
                owner_id=owner_id,
                session_id=anchor["session_id"],
                request_id=anchor["request_id"],
                trace_id=anchor["trace_id"],
                causation_event_id=current["created_event_id"],
                data_policy=policy,
                payload=BeliefLifecyclePayload(
                    belief_id=belief_id,
                    belief_revision=next_revision,
                    action="revised",
                    reason=reason,
                    previous_revision=expected_revision,
                ),
            )
            self._insert_event(connection, lifecycle_event)
            occurred_from, occurred_to, learned_at = self._evidence_times(rows)
            revision = BeliefRevision(
                owner_id=owner_id,
                belief_id=belief_id,
                revision=next_revision,
                belief_key=current["belief_key"],
                statement=statement,
                belief_type=current["belief_type"],
                confidence=confidence,
                initial_status=BeliefInitialStatus.ACTIVE,
                evidence_occurred_from=occurred_from,
                evidence_occurred_to=occurred_to,
                learned_at=learned_at,
                valid_from=valid_from,
                valid_to=valid_to,
                supersedes_revision=expected_revision,
                created_event_id=lifecycle_event.event_id,
                trace_id=lifecycle_event.trace_id,
                data_policy=policy,
            )
            revision = self._insert_belief_revision(connection, revision)
            self._insert_stage4_evidence_edges(
                connection,
                owner_id=owner_id,
                evidence=evidence,
                derived_kind="belief_revision",
                derived_id=belief_id,
                derived_revision=next_revision,
                transform_name="owner_belief_revision",
                transform_version="user-model-service-v1",
                created_event_id=lifecycle_event.event_id,
                trace_id=lifecycle_event.trace_id,
            )
            self._insert_stage4_provenance(
                connection,
                owner_id=owner_id,
                source_kind="belief_revision",
                source_id=belief_id,
                source_revision=expected_revision,
                derived_kind="belief_revision",
                derived_id=belief_id,
                derived_revision=next_revision,
                relation="supersedes",
                weight=None,
                transform_name="owner_belief_revision",
                transform_version="user-model-service-v1",
                created_event_id=lifecycle_event.event_id,
                trace_id=lifecycle_event.trace_id,
            )
            transition_event, transition = self._build_belief_transition(
                owner_id=owner_id,
                belief_id=belief_id,
                revision=expected_revision,
                transition_type=BeliefTransitionType.SUPERSEDED,
                reason=reason,
                occurred_at=lifecycle_event.recorded_at,
                policy=policy,
                anchor=current,
                replacement_belief_id=belief_id,
                replacement_revision=next_revision,
            )
            self._insert_event(connection, transition_event)
            transition = self._insert_belief_transition(connection, transition)
            connection.execute(
                """
                UPDATE havre.belief_heads
                SET current_revision = %s, status = 'active',
                    last_transition_id = %s,
                    updated_at = statement_timestamp()
                WHERE owner_id = %s AND belief_id = %s
                """,
                (
                    next_revision,
                    transition.belief_transition_id,
                    owner_id,
                    belief_id,
                ),
            )
            return {"revision": revision, "supersession": transition}

    def transition_belief(
        self,
        *,
        owner_id: UUID,
        belief_id: UUID,
        revision: int,
        transition_type: BeliefTransitionType,
        reason: str,
        occurred_at: datetime | None = None,
        evidence: tuple[EvidenceRef, ...] = (),
    ) -> BeliefTransition:
        if transition_type is BeliefTransitionType.SUPERSEDED:
            raise ValueError("supersession is created atomically by revise_belief")
        if not reason.strip():
            raise ValueError("belief transition reason is required")
        with self.pool.connection() as connection, connection.transaction():
            current = connection.execute(
                """
                SELECT revision.*, head.status AS effective_status,
                       event.session_id, event.request_id,
                       event.event_id AS anchor_event_id
                FROM havre.belief_heads AS head
                JOIN havre.user_belief_revisions AS revision
                  ON revision.owner_id = head.owner_id
                 AND revision.belief_id = head.belief_id
                 AND revision.revision = head.current_revision
                JOIN havre.events AS event
                  ON event.owner_id = revision.owner_id
                 AND event.event_id = revision.created_event_id
                WHERE head.owner_id = %s AND head.belief_id = %s
                FOR UPDATE OF head
                """,
                (owner_id, belief_id),
            ).fetchone()
            if current is None or current["revision"] != revision:
                raise LookupError("current belief revision not found")
            status = current["effective_status"]
            if status in {"retracted", "invalidated", "superseded"}:
                raise ValueError("terminal belief cannot transition again")
            if transition_type is BeliefTransitionType.ACTIVATED and status != "candidate":
                raise ValueError("only a candidate belief can be activated")
            counter_transition = transition_type in {
                BeliefTransitionType.COUNTER_EVIDENCE_RECORDED,
                BeliefTransitionType.CONTRADICTED,
            }
            if counter_transition != bool(evidence):
                raise ValueError("counter-evidence transitions require evidence; other transitions do not")
            if evidence and any(
                item.relation is not EvidenceRelation.CONTRADICTS for item in evidence
            ):
                raise ValueError("counter-evidence transitions accept only contradicting evidence")
            evidence_rows = (
                self._load_stage4_evidence(
                    connection,
                    owner_id=owner_id,
                    evidence=evidence,
                    require_support=False,
                )
                if evidence
                else []
            )
            policy = self._combine_stage4_evidence_policy(
                [
                    {
                        **current,
                        "policy": self._policy_from_row(current),
                        "learned_at": current["learned_at"],
                        "occurred_from": current["evidence_occurred_from"],
                        "occurred_to": current["evidence_occurred_to"],
                    },
                    *evidence_rows,
                ]
            )
            anchor = evidence_rows[0] if evidence_rows else current
            transition_event, transition = self._build_belief_transition(
                owner_id=owner_id,
                belief_id=belief_id,
                revision=revision,
                transition_type=transition_type,
                reason=reason,
                occurred_at=occurred_at or datetime.now(UTC),
                policy=policy,
                anchor=anchor,
            )
            self._insert_event(connection, transition_event)
            transition = self._insert_belief_transition(connection, transition)
            if evidence:
                self._insert_stage4_evidence_edges(
                    connection,
                    owner_id=owner_id,
                    evidence=evidence,
                    derived_kind="belief_revision",
                    derived_id=belief_id,
                    derived_revision=revision,
                    transform_name="owner_counter_evidence",
                    transform_version="user-model-service-v1",
                    created_event_id=transition_event.event_id,
                    trace_id=transition_event.trace_id,
                )
            next_status = {
                BeliefTransitionType.ACTIVATED: "active",
                BeliefTransitionType.COUNTER_EVIDENCE_RECORDED: status,
                BeliefTransitionType.CONTRADICTED: "contradicted",
                BeliefTransitionType.RETRACTED: "retracted",
                BeliefTransitionType.INVALIDATED: "invalidated",
            }[transition_type]
            connection.execute(
                """
                UPDATE havre.belief_heads
                SET status = %s, last_transition_id = %s,
                    updated_at = statement_timestamp()
                WHERE owner_id = %s AND belief_id = %s
                """,
                (
                    next_status,
                    transition.belief_transition_id,
                    owner_id,
                    belief_id,
                ),
            )
            return transition

    def list_belief_snapshots(
        self,
        *,
        owner_id: UUID,
        known_as_of: datetime | None = None,
        valid_at: datetime | None = None,
        include_inactive: bool = False,
    ) -> list[BeliefSnapshot]:
        with self.pool.connection() as connection:
            known = known_as_of
            if known is None:
                known = connection.execute(
                    "SELECT clock_timestamp() AS known_as_of"
                ).fetchone()["known_as_of"]
            revisions = connection.execute(
                """
                SELECT DISTINCT ON (belief_id) *
                FROM havre.user_belief_revisions
                WHERE owner_id = %s AND created_at <= %s
                  AND (%s::timestamptz IS NULL OR valid_from IS NULL OR valid_from <= %s)
                  AND (%s::timestamptz IS NULL OR valid_to IS NULL OR valid_to >= %s)
                ORDER BY belief_id, revision DESC
                """,
                (owner_id, known, valid_at, valid_at, valid_at, valid_at),
            ).fetchall()
            snapshots: list[BeliefSnapshot] = []
            for row in revisions:
                transition_rows = connection.execute(
                    """
                    SELECT * FROM havre.belief_revision_transitions
                    WHERE owner_id = %s AND belief_id = %s
                      AND belief_revision = %s AND recorded_at <= %s
                    ORDER BY recorded_at, belief_transition_id
                    """,
                    (owner_id, row["belief_id"], row["revision"], known),
                ).fetchall()
                status = row["initial_status"]
                for item in transition_rows:
                    status = {
                        "activated": "active",
                        "counter_evidence_recorded": status,
                        "contradicted": "contradicted",
                        "superseded": "superseded",
                        "retracted": "retracted",
                        "invalidated": "invalidated",
                    }[item["transition_type"]]
                if not include_inactive and status != "active":
                    continue
                edge_rows = connection.execute(
                    """
                    SELECT source_kind, source_id, source_revision, relation, weight
                    FROM havre.provenance_edges
                    WHERE owner_id = %s AND derived_kind = 'belief_revision'
                      AND derived_id = %s AND derived_revision = %s
                      AND relation IN ('supports', 'contradicts')
                    ORDER BY created_at, provenance_edge_id
                    """,
                    (owner_id, row["belief_id"], row["revision"]),
                ).fetchall()
                evidence_refs = tuple(
                    EvidenceRef(
                        source_kind=item["source_kind"],
                        source_id=item["source_id"],
                        source_revision=item["source_revision"],
                        relation=item["relation"],
                        weight=(float(item["weight"]) if item["weight"] is not None else None),
                    )
                    for item in edge_rows
                )
                snapshots.append(
                    BeliefSnapshot(
                        revision=self._belief_from_row(row),
                        effective_status=status,
                        supporting_evidence=tuple(
                            item for item in evidence_refs
                            if item.relation is EvidenceRelation.SUPPORTS
                        ),
                        counter_evidence=tuple(
                            item for item in evidence_refs
                            if item.relation is EvidenceRelation.CONTRADICTS
                        ),
                        transitions=tuple(
                            self._belief_transition_from_row(item)
                            for item in transition_rows
                        ),
                        known_as_of=known,
                        valid_at=valid_at,
                    )
                )
            snapshots.sort(
                key=lambda item: (
                    item.revision.belief_key,
                    str(item.revision.belief_id),
                )
            )
            return snapshots

    def create_consolidation_proposal(
        self,
        *,
        owner_id: UUID,
        memory_class: str,
        content_text: str,
        evidence: tuple[EvidenceRef, ...],
        detector_version: str,
        importance: float = 0.5,
    ) -> ConsolidationProposal:
        if memory_class not in {"semantic", "pattern", "progress"}:
            raise ValueError("Stage 4 consolidation class is invalid")
        supported_detector = self._STAGE4_PROPOSAL_DETECTOR_VERSIONS.get(
            memory_class
        )
        if supported_detector is not None and detector_version != supported_detector:
            raise ValueError(
                f"unsupported {memory_class} proposal detector version: "
                f"{detector_version}"
            )
        with self.pool.connection() as connection, connection.transaction():
            rows = self._load_stage4_evidence(
                connection, owner_id=owner_id, evidence=evidence
            )
            support_rows = [
                row for ref, row in zip(evidence, rows, strict=True)
                if ref.relation is EvidenceRelation.SUPPORTS
            ]
            if memory_class in {"pattern", "progress"}:
                distinct_sources = {
                    (ref.source_kind.value, ref.source_id, ref.source_revision)
                    for ref in evidence
                    if ref.relation is EvidenceRelation.SUPPORTS
                }
                if len(distinct_sources) < 2:
                    raise ValueError(
                        "pattern and progress proposals require two supporting sources"
                    )
                distinct_days = self._stage4_evidence_utc_dates(support_rows)
                if len(distinct_days) < 2:
                    raise ValueError(
                        "pattern and progress proposals require support on two "
                        "distinct UTC dates"
                    )
            policy = self._combine_stage4_evidence_policy(rows)
            anchor = rows[0]
            proposal_id = uuid7()
            lifecycle_event = EventEnvelope(
                event_type=EventType.CONSOLIDATION_PROPOSED,
                owner_id=owner_id,
                session_id=anchor["session_id"],
                request_id=anchor["request_id"],
                trace_id=anchor["trace_id"],
                causation_event_id=anchor["anchor_event_id"],
                data_policy=policy,
                payload=ConsolidationLifecyclePayload(
                    proposal_id=proposal_id,
                    action="proposed",
                    memory_class=memory_class,
                    reason="Evidence met the proposal-only detector contract",
                ),
            )
            self._insert_event(connection, lifecycle_event)
            proposal = ConsolidationProposal(
                proposal_id=proposal_id,
                owner_id=owner_id,
                memory_class=memory_class,
                content={
                    "schema_version": 1,
                    "kind": f"{memory_class}_memory_proposal",
                    "text": content_text,
                },
                content_text=content_text,
                importance=importance,
                detector_version=detector_version,
                evidence=evidence,
                created_event_id=lifecycle_event.event_id,
                trace_id=lifecycle_event.trace_id,
                data_policy=policy,
            )
            self._insert_consolidation_proposal(connection, proposal)
            self._insert_stage4_evidence_edges(
                connection,
                owner_id=owner_id,
                evidence=evidence,
                derived_kind="consolidation_proposal",
                derived_id=proposal_id,
                derived_revision=None,
                transform_name="stage4_consolidation_detector",
                transform_version=detector_version,
                created_event_id=lifecycle_event.event_id,
                trace_id=lifecycle_event.trace_id,
            )
            return proposal

    def list_consolidation_proposals(
        self, *, owner_id: UUID, status: str = "pending"
    ) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            return connection.execute(
                """
                SELECT * FROM havre.consolidation_proposals
                WHERE owner_id = %s AND status = %s
                ORDER BY created_at, proposal_id
                """,
                (owner_id, status),
            ).fetchall()

    def accept_consolidation_proposal(
        self,
        *,
        owner_id: UUID,
        proposal_id: UUID,
        reason: str,
        confidence: float,
        embedding_provider,
        importance: float | None = None,
        corrected_content_text: str | None = None,
    ) -> MemoryRevision:
        if not 0 <= confidence <= 1:
            raise ValueError("owner-reviewed confidence must be between 0 and 1")
        with self.pool.connection() as connection, connection.transaction():
            proposal = connection.execute(
                """
                SELECT proposal.*, event.session_id, event.request_id,
                       event.event_id AS anchor_event_id
                FROM havre.consolidation_proposals AS proposal
                JOIN havre.events AS event
                  ON event.owner_id = proposal.owner_id
                 AND event.event_id = proposal.created_event_id
                WHERE proposal.owner_id = %s AND proposal.proposal_id = %s
                FOR UPDATE OF proposal
                """,
                (owner_id, proposal_id),
            ).fetchone()
            if proposal is None:
                raise LookupError("consolidation proposal not found")
            if proposal["status"] in {"accepted", "accepted_with_correction"}:
                stored = connection.execute(
                    """
                    SELECT * FROM havre.memory_revisions
                    WHERE owner_id = %s AND memory_id = %s AND revision = %s
                    """,
                    (
                        owner_id,
                        proposal["accepted_memory_id"],
                        proposal["accepted_memory_revision"],
                    ),
                ).fetchone()
                return self._memory_from_row(stored)
            if proposal["status"] != "pending":
                raise ValueError("only a pending proposal can be accepted")
            accepted_importance = (
                float(proposal["importance"])
                if importance is None
                else float(importance)
            )
            if not 0 <= accepted_importance <= 1:
                raise ValueError("importance must be between 0 and 1")
            memory_id = uuid7()
            memory_policy = self._derived_policy_from_row(proposal)
            corrected = (
                corrected_content_text
                if corrected_content_text is not None
                else proposal["content_text"]
            )
            review_action = (
                "accepted_with_correction"
                if corrected_content_text is not None
                and corrected_content_text != proposal["content_text"]
                else "accepted"
            )
            review_event = EventEnvelope(
                event_type=EventType.CONSOLIDATION_REVIEWED,
                owner_id=owner_id,
                session_id=proposal["session_id"],
                request_id=proposal["request_id"],
                trace_id=proposal["trace_id"],
                causation_event_id=proposal["created_event_id"],
                data_policy=memory_policy,
                payload=ConsolidationLifecyclePayload(
                    proposal_id=proposal_id,
                    action=review_action,
                    memory_class=proposal["memory_class"],
                    reason=reason,
                    memory_id=memory_id,
                    memory_revision=1,
                ),
            )
            self._insert_event(connection, review_event)
            memory_event = EventEnvelope(
                event_type=EventType.MEMORY_CREATED,
                owner_id=owner_id,
                session_id=proposal["session_id"],
                request_id=proposal["request_id"],
                trace_id=proposal["trace_id"],
                causation_event_id=review_event.event_id,
                data_policy=memory_policy,
                payload=MemoryLifecyclePayload(
                    memory_id=memory_id,
                    memory_revision=1,
                    action="created",
                    reason=reason,
                ),
            )
            self._insert_event(connection, memory_event)
            content = dict(proposal["content"])
            content["text"] = corrected
            content["proposal_id"] = str(proposal_id)
            revision = MemoryRevision(
                owner_id=owner_id,
                memory_id=memory_id,
                revision=1,
                memory_class=proposal["memory_class"],
                content=content,
                content_text=corrected,
                confidence=confidence,
                confidence_method="owner-reviewed-v1",
                importance=accepted_importance,
                importance_policy_version="owner-review-importance-v1",
                status=MemoryStatus.ACTIVE,
                source_occurred_at=proposal["created_at"],
                created_by="owner_review",
                transform_version=proposal["detector_version"],
                created_event_id=memory_event.event_id,
                trace_id=proposal["trace_id"],
                data_policy=memory_policy,
            )
            self._insert_memory_revision(connection, revision)
            connection.execute(
                """
                INSERT INTO havre.memory_heads (
                    owner_id, memory_id, current_revision, status
                ) VALUES (%s, %s, 1, 'active')
                """,
                (owner_id, memory_id),
            )
            self._insert_embedding(connection, revision, embedding_provider)
            evidence = tuple(
                EvidenceRef.model_validate(item)
                for item in proposal["evidence_snapshot"]
            )
            self._insert_stage4_evidence_edges(
                connection,
                owner_id=owner_id,
                evidence=evidence,
                derived_kind="memory_revision",
                derived_id=memory_id,
                derived_revision=1,
                transform_name="owner_consolidation_acceptance",
                transform_version=proposal["detector_version"],
                created_event_id=memory_event.event_id,
                trace_id=memory_event.trace_id,
            )
            connection.execute(
                """
                UPDATE havre.consolidation_proposals
                SET status = %s, reviewed_by = 'owner',
                    reviewed_at = clock_timestamp(), review_reason = %s,
                    accepted_memory_id = %s, accepted_memory_revision = 1,
                    review_event_id = %s
                WHERE owner_id = %s AND proposal_id = %s
                """,
                (
                    review_action,
                    reason,
                    memory_id,
                    review_event.event_id,
                    owner_id,
                    proposal_id,
                ),
            )
            return revision

    def reject_consolidation_proposal(
        self, *, owner_id: UUID, proposal_id: UUID, reason: str
    ) -> dict[str, Any]:
        with self.pool.connection() as connection, connection.transaction():
            proposal = connection.execute(
                """
                SELECT proposal.*, event.session_id, event.request_id
                FROM havre.consolidation_proposals AS proposal
                JOIN havre.events AS event
                  ON event.owner_id = proposal.owner_id
                 AND event.event_id = proposal.created_event_id
                WHERE proposal.owner_id = %s AND proposal.proposal_id = %s
                FOR UPDATE OF proposal
                """,
                (owner_id, proposal_id),
            ).fetchone()
            if proposal is None:
                raise LookupError("consolidation proposal not found")
            if proposal["status"] != "pending":
                raise ValueError("only a pending proposal can be rejected")
            review_event = EventEnvelope(
                event_type=EventType.CONSOLIDATION_REVIEWED,
                owner_id=owner_id,
                session_id=proposal["session_id"],
                request_id=proposal["request_id"],
                trace_id=proposal["trace_id"],
                causation_event_id=proposal["created_event_id"],
                data_policy=self._derived_policy_from_row(proposal),
                payload=ConsolidationLifecyclePayload(
                    proposal_id=proposal_id,
                    action="rejected",
                    memory_class=proposal["memory_class"],
                    reason=reason,
                ),
            )
            self._insert_event(connection, review_event)
            return connection.execute(
                """
                UPDATE havre.consolidation_proposals
                SET status = 'rejected', reviewed_by = 'owner',
                    reviewed_at = clock_timestamp(), review_reason = %s,
                    review_event_id = %s
                WHERE owner_id = %s AND proposal_id = %s
                RETURNING *
                """,
                (reason, review_event.event_id, owner_id, proposal_id),
            ).fetchone()

    def create_current_state_snapshot(
        self,
        *,
        owner_id: UUID,
        summary: str,
        state: dict[str, object],
        uncertainty: float,
        estimated_at: datetime,
        expires_at: datetime,
        evidence: tuple[EvidenceRef, ...],
    ) -> CurrentStateSnapshot:
        with self.pool.connection() as connection, connection.transaction():
            rows = self._load_stage4_evidence(
                connection, owner_id=owner_id, evidence=evidence
            )
            policy = self._combine_stage4_evidence_policy(rows)
            anchor = rows[0]
            snapshot_id = uuid7()
            lifecycle_event = EventEnvelope(
                event_type=EventType.CURRENT_STATE_ESTIMATED,
                owner_id=owner_id,
                session_id=anchor["session_id"],
                request_id=anchor["request_id"],
                trace_id=anchor["trace_id"],
                causation_event_id=anchor["anchor_event_id"],
                data_policy=policy,
                payload=CurrentStateLifecyclePayload(
                    state_snapshot_id=snapshot_id,
                    expires_at=expires_at,
                    estimator_version="owner-reported-state-v1",
                ),
            )
            self._insert_event(connection, lifecycle_event)
            snapshot = CurrentStateSnapshot(
                state_snapshot_id=snapshot_id,
                owner_id=owner_id,
                summary=summary,
                state=state,
                uncertainty=uncertainty,
                estimated_at=estimated_at,
                expires_at=expires_at,
                evidence=evidence,
                created_event_id=lifecycle_event.event_id,
                trace_id=lifecycle_event.trace_id,
                data_policy=policy,
            )
            self._insert_current_state(connection, snapshot)
            self._insert_stage4_evidence_edges(
                connection,
                owner_id=owner_id,
                evidence=evidence,
                derived_kind="current_state_snapshot",
                derived_id=snapshot_id,
                derived_revision=None,
                transform_name="owner_current_state",
                transform_version=snapshot.estimator_version,
                created_event_id=lifecycle_event.event_id,
                trace_id=lifecycle_event.trace_id,
            )
            return snapshot

    def current_state(
        self, *, owner_id: UUID, as_of: datetime | None = None
    ) -> CurrentStateSnapshot | None:
        instant = as_of or datetime.now(UTC)
        with self.pool.connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM havre.current_state_snapshots
                WHERE owner_id = %s AND estimated_at <= %s AND expires_at > %s
                ORDER BY estimated_at DESC, created_at DESC, state_snapshot_id DESC
                LIMIT 1
                """,
                (owner_id, instant, instant),
            ).fetchone()
            return self._current_state_from_row(row) if row else None

    def create_goal(
        self,
        *,
        owner_id: UUID,
        track: GoalTrack,
        title: str,
        why: str,
        source_event_id: UUID,
        priority: GoalPriority = GoalPriority.NORMAL,
        next_action: str | None = None,
        review_at: datetime | None = None,
    ) -> Goal:
        source = EvidenceRef(
            source_kind=EvidenceSourceKind.EVENT,
            source_id=source_event_id,
            relation=EvidenceRelation.SUPPORTS,
        )
        with self.pool.connection() as connection, connection.transaction():
            row = self._load_stage4_evidence(
                connection, owner_id=owner_id, evidence=(source,)
            )[0]
            policy = self._combine_stage4_evidence_policy([row])
            goal_id = uuid7()
            lifecycle_event_id = uuid7()
            goal = Goal(
                goal_id=goal_id,
                owner_id=owner_id,
                track=track,
                title=title,
                why=why,
                priority=priority,
                status=GoalStatus.ACTIVE,
                next_action=next_action,
                review_at=review_at,
                revision=1,
                last_event_id=lifecycle_event_id,
                data_policy=policy,
            )
            projection_material = goal.projection_material()
            lifecycle_event = EventEnvelope(
                event_id=lifecycle_event_id,
                event_type=EventType.GOAL_CREATED,
                owner_id=owner_id,
                session_id=row["session_id"],
                request_id=row["request_id"],
                trace_id=row["trace_id"],
                causation_event_id=source_event_id,
                data_policy=policy,
                payload=GoalLifecyclePayload(
                    goal_id=goal_id,
                    goal_revision=1,
                    action="created",
                    track=track.value,
                    title=title,
                    why=why,
                    priority=priority.value,
                    status="active",
                    next_action=next_action,
                    review_at=review_at,
                    reason="Owner created goal",
                    projection_content_hash=goal.content_hash,
                    projection_canonical_json=projection_material.canonical_json(),
                ),
            )
            self._insert_event(connection, lifecycle_event)
            inserted = self._insert_goal(connection, goal)
            return goal.model_copy(update={
                "created_at": inserted["created_at"],
                "updated_at": inserted["updated_at"],
            })

    def update_goal(
        self,
        *,
        owner_id: UUID,
        goal_id: UUID,
        expected_revision: int,
        reason: str,
        title: str | None = None,
        why: str | None = None,
        priority: GoalPriority | None = None,
        status: GoalStatus | None = None,
        next_action: str | None | GoalFieldUnset = GOAL_FIELD_UNSET,
        review_at: datetime | None | GoalFieldUnset = GOAL_FIELD_UNSET,
    ) -> Goal:
        with self.pool.connection() as connection, connection.transaction():
            current = connection.execute(
                """
                SELECT goal.*, event.session_id, event.request_id, event.trace_id
                FROM havre.goals AS goal
                JOIN havre.events AS event
                  ON event.owner_id = goal.owner_id
                 AND event.event_id = goal.last_event_id
                WHERE goal.owner_id = %s AND goal.goal_id = %s
                FOR UPDATE OF goal
                """,
                (owner_id, goal_id),
            ).fetchone()
            if current is None:
                raise LookupError("goal not found")
            if current["revision"] != expected_revision:
                raise ValueError("goal revision precondition failed")
            if current["status"] in {"completed", "abandoned"}:
                raise ValueError("closed goal cannot be updated")
            next_status = status or GoalStatus(current["status"])
            next_goal = {
                "title": title if title is not None else current["title"],
                "why": why if why is not None else current["why"],
                "priority": priority or GoalPriority(current["priority"]),
                "status": next_status,
                "next_action": (
                    current["next_action"]
                    if isinstance(next_action, GoalFieldUnset)
                    else next_action
                ),
                "review_at": (
                    current["review_at"]
                    if isinstance(review_at, GoalFieldUnset)
                    else review_at
                ),
            }
            action = "completed" if next_status is GoalStatus.COMPLETED else "updated"
            event_type = (
                EventType.GOAL_COMPLETED
                if action == "completed"
                else EventType.GOAL_UPDATED
            )
            lifecycle_event_id = uuid7()
            goal = Goal(
                goal_id=goal_id,
                owner_id=owner_id,
                track=current["track"],
                title=next_goal["title"],
                why=next_goal["why"],
                priority=next_goal["priority"],
                status=next_status,
                next_action=next_goal["next_action"],
                review_at=next_goal["review_at"],
                revision=expected_revision + 1,
                last_event_id=lifecycle_event_id,
                data_policy=self._policy_from_row(current),
                created_at=current["created_at"],
            )
            projection_material = goal.projection_material()
            lifecycle_event = EventEnvelope(
                event_id=lifecycle_event_id,
                event_type=event_type,
                owner_id=owner_id,
                session_id=current["session_id"],
                request_id=current["request_id"],
                trace_id=current["trace_id"],
                causation_event_id=current["last_event_id"],
                data_policy=self._policy_from_row(current),
                payload=GoalLifecyclePayload(
                    goal_id=goal_id,
                    goal_revision=expected_revision + 1,
                    action=action,
                    track=current["track"],
                    title=next_goal["title"],
                    why=next_goal["why"],
                    priority=next_goal["priority"].value,
                    status=next_status.value,
                    next_action=next_goal["next_action"],
                    review_at=next_goal["review_at"],
                    reason=reason,
                    projection_content_hash=goal.content_hash,
                    projection_canonical_json=projection_material.canonical_json(),
                ),
            )
            self._insert_event(connection, lifecycle_event)
            updated = connection.execute(
                """
                UPDATE havre.goals
                SET title = %s, why = %s, priority = %s, status = %s,
                    next_action = %s, review_at = %s, revision = %s,
                    last_event_id = %s, content_hash = %s,
                    updated_at = statement_timestamp()
                WHERE owner_id = %s AND goal_id = %s AND revision = %s
                RETURNING updated_at
                """,
                (
                    goal.title,
                    goal.why,
                    goal.priority.value,
                    goal.status.value,
                    goal.next_action,
                    goal.review_at,
                    goal.revision,
                    goal.last_event_id,
                    goal.content_hash,
                    owner_id,
                    goal_id,
                    expected_revision,
                ),
            ).fetchone()
            if updated is None:
                raise ValueError("goal revision precondition failed")
            return goal.model_copy(update={"updated_at": updated["updated_at"]})

    def record_goal_progress(
        self,
        *,
        owner_id: UUID,
        goal_id: UUID,
        expected_goal_revision: int,
        direction: str,
        summary: str,
        observed_at: datetime,
        evidence: tuple[EvidenceRef, ...],
    ) -> GoalProgressRecord:
        with self.pool.connection() as connection, connection.transaction():
            goal = connection.execute(
                """
                SELECT * FROM havre.goals
                WHERE owner_id = %s AND goal_id = %s
                FOR SHARE
                """,
                (owner_id, goal_id),
            ).fetchone()
            if goal is None:
                raise LookupError("goal not found")
            if goal["revision"] != expected_goal_revision:
                raise ValueError("goal revision precondition failed")
            rows = self._load_stage4_evidence(
                connection, owner_id=owner_id, evidence=evidence
            )
            goal_policy_row = {"policy": self._policy_from_row(goal)}
            policy = self._combine_stage4_evidence_policy(
                [goal_policy_row, *rows]
            )
            anchor = rows[0]
            progress_id = uuid7()
            lifecycle_event = EventEnvelope(
                event_type=EventType.PROGRESS_RECORDED,
                owner_id=owner_id,
                session_id=anchor["session_id"],
                request_id=anchor["request_id"],
                trace_id=anchor["trace_id"],
                causation_event_id=anchor["anchor_event_id"],
                data_policy=policy,
                payload=ProgressLifecyclePayload(
                    progress_record_id=progress_id,
                    goal_id=goal_id,
                    goal_revision=expected_goal_revision,
                    direction=direction,
                    observed_at=observed_at,
                ),
            )
            self._insert_event(connection, lifecycle_event)
            progress = GoalProgressRecord(
                progress_record_id=progress_id,
                owner_id=owner_id,
                goal_id=goal_id,
                goal_revision=expected_goal_revision,
                direction=direction,
                summary=summary,
                observed_at=observed_at,
                evidence=evidence,
                created_event_id=lifecycle_event.event_id,
                trace_id=lifecycle_event.trace_id,
                data_policy=policy,
            )
            self._insert_goal_progress(connection, progress)
            self._insert_stage4_evidence_edges(
                connection,
                owner_id=owner_id,
                evidence=evidence,
                derived_kind="goal_progress_record",
                derived_id=progress_id,
                derived_revision=None,
                transform_name="owner_goal_progress",
                transform_version="goal-service-v1",
                created_event_id=lifecycle_event.event_id,
                trace_id=lifecycle_event.trace_id,
            )
            return progress

    def list_goals(
        self, *, owner_id: UUID, include_inactive: bool = False
    ) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            return connection.execute(
                """
                SELECT goal.*,
                       COALESCE(progress.records, '[]'::jsonb) AS progress_records
                FROM havre.goals AS goal
                LEFT JOIN LATERAL (
                    SELECT jsonb_agg(to_jsonb(item) ORDER BY item.observed_at, item.progress_record_id)
                        AS records
                    FROM havre.goal_progress_records AS item
                    WHERE item.owner_id = goal.owner_id AND item.goal_id = goal.goal_id
                ) AS progress ON true
                WHERE goal.owner_id = %s
                  AND (%s OR goal.status IN ('active', 'paused'))
                ORDER BY goal.track, goal.updated_at DESC, goal.goal_id
                """,
                (owner_id, include_inactive),
            ).fetchall()

    def persist_user_model_evaluation_report(self, report: dict[str, Any]) -> None:
        with self.pool.connection() as connection, connection.transaction():
            existing = connection.execute(
                """
                SELECT content_hash FROM havre.user_model_evaluation_runs
                WHERE evaluation_run_id = %s
                """,
                (report["evaluation_run_id"],),
            ).fetchone()
            if existing:
                if existing["content_hash"] != report["content_hash"]:
                    raise ValueError("evaluation run ID is bound to different content")
                return
            connection.execute(
                """
                INSERT INTO havre.user_model_evaluation_runs (
                    evaluation_run_id, schema_version, suite_version, fixture_hash,
                    code_revision, environment, metrics, case_results, limitations,
                    content_hash, created_at
                ) VALUES (%s, 1, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    report["evaluation_run_id"],
                    report["suite_version"],
                    report["fixture_hash"],
                    report["code_revision"],
                    Jsonb(report["environment"]),
                    Jsonb(report["metrics"]),
                    Jsonb(report["case_results"]),
                    Jsonb(report["limitations"]),
                    report["content_hash"],
                    report["created_at"],
                ),
            )

    def persist_scene_policy_evaluation_report(self, report: dict[str, Any]) -> None:
        with self.pool.connection() as connection, connection.transaction():
            existing = connection.execute(
                """
                SELECT content_hash FROM havre.scene_evaluation_runs
                WHERE evaluation_run_id = %s
                """,
                (report["evaluation_run_id"],),
            ).fetchone()
            if existing:
                if existing["content_hash"] != report["content_hash"]:
                    raise ValueError("evaluation run ID is bound to different content")
                return
            connection.execute(
                """
                INSERT INTO havre.scene_evaluation_runs (
                    evaluation_run_id, schema_version, suite_version, fixture_hash,
                    code_revision, binding_evaluation, gate_status, environment,
                    metrics, case_results, limitations, content_hash, created_at
                ) VALUES (%s, 1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    report["evaluation_run_id"],
                    report["suite_version"],
                    report["fixture_hash"],
                    report["code_revision"],
                    report["binding_evaluation"],
                    report["gate_status"],
                    Jsonb(report["environment"]),
                    Jsonb(report["metrics"]),
                    Jsonb(report["case_results"]),
                    Jsonb(report["limitations"]),
                    report["content_hash"],
                    report["created_at"],
                ),
            )

    def select_conversation_history(
        self,
        *,
        owner_id: UUID,
        session_id: UUID,
        exclude_event_id: UUID,
        maximum_privacy_class: PrivacyClass,
        limit: int = 24,
    ) -> tuple[ConversationHistoryItem, ...]:
        """Return recent raw message Events for one open conversation.

        The current Event is excluded explicitly. Selection is owner/session
        qualified, privacy-filtered before bytes leave PostgreSQL, and returned
        in exact durable order for ContextPack admission.
        """
        allowed = [
            value.value
            for value in PrivacyClass
            if PRIVACY_RESTRICTION_ORDER[value]
            <= PRIVACY_RESTRICTION_ORDER[maximum_privacy_class]
        ]
        with self.pool.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM (
                  SELECT event_id,owner_id,session_id,request_id,event_type,payload,
                         privacy_class,memory_eligible,training_eligible,
                         cloud_eligible,policy_version,policy_revision_id,
                         policy_decision_source,policy_authorization_ref,recorded_at
                  FROM havre.events
                  WHERE owner_id=%s AND session_id=%s AND event_id<>%s
                    AND event_type IN ('USER_MESSAGE','ASSISTANT_MESSAGE')
                    AND privacy_class = ANY(%s::text[])
                  ORDER BY recorded_at DESC,event_id DESC LIMIT %s
                ) recent
                ORDER BY recorded_at,event_id
                """,
                (owner_id,session_id,exclude_event_id,allowed,max(1,min(limit,100))),
            ).fetchall()
        result: list[ConversationHistoryItem] = []
        for row in rows:
            parts = row["payload"].get("content_parts", []) if row["payload"] else []
            text = "\n".join(
                str(part.get("text", ""))
                for part in parts
                if isinstance(part, dict) and part.get("type") == "text"
            ).strip()
            if not text:
                continue
            result.append(ConversationHistoryItem(
                owner_id=row["owner_id"],session_id=row["session_id"],
                event_id=row["event_id"],request_id=row["request_id"],
                role="user" if row["event_type"] == "USER_MESSAGE" else "assistant",
                content_text=text,recorded_at=row["recorded_at"],
                data_policy=self._policy_from_row(row),
            ))
        return tuple(result)

    def select_personal_context(
        self,
        *,
        owner_id: UUID,
        query_text: str,
        maximum_privacy_class: PrivacyClass,
        as_of: datetime | None = None,
    ) -> tuple[PersonalContextItem, ...]:
        """Select small, evidence-qualified Stage 4 context without a model.

        Beliefs and goals require meaningful lexical overlap. The latest
        non-expired Current State may be included without being promoted into a
        durable belief. The Context Builder independently rechecks owner and
        privacy before prompt admission.
        """

        instant = as_of or datetime.now(UTC)
        meaningful = {
            token
            for token in re.findall(r"[^\W_]+", query_text.casefold())
            if len(token) >= 3
        }
        items: list[PersonalContextItem] = []
        with self.pool.connection() as connection:
            preference = connection.execute(
                """
                SELECT revision, response_length
                FROM havre.communication_preference_revisions
                WHERE owner_id=%s ORDER BY revision DESC LIMIT 1
                """,
                (owner_id,),
            ).fetchone()
        if preference is not None:
            preference_policy = DataPolicy.owner_default(
                PrivacyClass.NORMAL, memory_eligible=False
            )
            if (
                PRIVACY_RESTRICTION_ORDER[preference_policy.privacy_class]
                <= PRIVACY_RESTRICTION_ORDER[maximum_privacy_class]
            ):
                instruction = {
                    "brief": "Prefer a concise, natural response unless the user asks for detail.",
                    "balanced": "Use a natural, proportionate response length.",
                    "detailed": "Give useful detail when it helps, without padding or repetition.",
                }[preference["response_length"]]
                items.append(
                    PersonalContextItem(
                        owner_id=owner_id,
                        section_id=f"communication-preference-{preference['revision']}",
                        section_type="communication_preference",
                        content_text=instruction,
                        priority=95,
                        source_refs=(
                            f"communication-preference/{preference['revision']}",
                        ),
                        data_policy=preference_policy,
                    )
                )
        with self.pool.connection() as connection:
            episodes = connection.execute(
                """
                SELECT * FROM havre.conversation_episodes
                WHERE owner_id=%s AND memory_eligible=true
                ORDER BY ended_at DESC LIMIT 20
                """,
                (owner_id,),
            ).fetchall()
        for episode in episodes:
            policy = self._policy_from_row(episode)
            if (
                PRIVACY_RESTRICTION_ORDER[policy.privacy_class]
                > PRIVACY_RESTRICTION_ORDER[maximum_privacy_class]
            ):
                continue
            summary = episode["summary_text"]
            summary_tokens = {
                token for token in re.findall(r"[^\W_]+", summary.casefold())
                if len(token) >= 3
            }
            recall_word = any(
                marker in query_text.casefold()
                for marker in ("remember", "recall", "记得", "之前", "那次")
            )
            if not recall_word and not meaningful.intersection(summary_tokens):
                continue
            items.append(
                PersonalContextItem(
                    owner_id=owner_id,
                    section_id=f"episode-summary-{episode['episode_id']}",
                    section_type="episodic_memory",
                    content_text=(
                        f"Past conversation episode ({episode['ended_at'].date()}): {summary}"
                    ),
                    priority=70,
                    source_refs=(
                        f"episode/{episode['episode_id']}",
                        f"session/{episode['session_id']}",
                    ),
                    data_policy=policy,
                )
            )
            if sum(item.section_type == "episodic_memory" for item in items) >= 3:
                break
        beliefs = self.list_belief_snapshots(
            owner_id=owner_id,
            known_as_of=instant,
            valid_at=instant,
            include_inactive=False,
        )
        for snapshot in beliefs:
            revision = snapshot.revision
            if (
                PRIVACY_RESTRICTION_ORDER[revision.data_policy.privacy_class]
                > PRIVACY_RESTRICTION_ORDER[maximum_privacy_class]
            ):
                continue
            tokens = {
                token
                for token in re.findall(r"[^\W_]+", revision.statement.casefold())
                if len(token) >= 3
            }
            if not meaningful.intersection(tokens):
                continue
            text = (
                f"Qualified belief (owner-reviewed confidence {revision.confidence:.2f}; "
                f"{len(snapshot.supporting_evidence)} supporting and "
                f"{len(snapshot.counter_evidence)} counter-evidence sources): "
                f"{revision.statement}"
            )
            items.append(
                PersonalContextItem(
                    owner_id=owner_id,
                    section_id=f"belief-{revision.belief_id}-{revision.revision}",
                    section_type="user_belief",
                    content_text=text,
                    priority=80,
                    source_refs=(
                        f"belief/{revision.belief_id}@{revision.revision}",
                        *(
                            item.source_ref
                            for item in (
                                *snapshot.supporting_evidence,
                                *snapshot.counter_evidence,
                            )
                        ),
                    ),
                    data_policy=revision.data_policy,
                )
            )
            if sum(item.section_type == "user_belief" for item in items) >= 3:
                break
        for goal in self.list_goals(owner_id=owner_id, include_inactive=False):
            policy = self._policy_from_row(goal)
            if (
                PRIVACY_RESTRICTION_ORDER[policy.privacy_class]
                > PRIVACY_RESTRICTION_ORDER[maximum_privacy_class]
            ):
                continue
            goal_text = " ".join(
                value
                for value in (goal["title"], goal["why"], goal["next_action"])
                if value
            )
            tokens = {
                token
                for token in re.findall(r"[^\W_]+", goal_text.casefold())
                if len(token) >= 3
            }
            if not meaningful.intersection(tokens):
                continue
            content = (
                f"Active {goal['track'].replace('_', ' ')} goal: {goal['title']}. "
                f"Why: {goal['why']}."
            )
            if goal["next_action"]:
                content += f" Next user-owned action: {goal['next_action']}."
            items.append(
                PersonalContextItem(
                    owner_id=owner_id,
                    section_id=f"goal-{goal['goal_id']}-{goal['revision']}",
                    section_type="goal",
                    content_text=content,
                    priority=85,
                    source_refs=(f"goal/{goal['goal_id']}@{goal['revision']}",),
                    data_policy=policy,
                )
            )
            if sum(item.section_type == "goal" for item in items) >= 3:
                break
        state = self.current_state(owner_id=owner_id, as_of=instant)
        if state is not None and (
            PRIVACY_RESTRICTION_ORDER[state.data_policy.privacy_class]
            <= PRIVACY_RESTRICTION_ORDER[maximum_privacy_class]
        ):
            items.append(
                PersonalContextItem(
                    owner_id=owner_id,
                    section_id=f"current-state-{state.state_snapshot_id}",
                    section_type="current_state",
                    content_text=(
                        f"Expiring Current State (uncertainty {state.uncertainty:.2f}; "
                        f"expires {state.expires_at.isoformat()}): {state.summary}"
                    ),
                    priority=75,
                    source_refs=(
                        f"current-state/{state.state_snapshot_id}",
                        *(item.source_ref for item in state.evidence),
                    ),
                    data_policy=state.data_policy,
                )
            )
        return tuple(items)

    def audit_provenance_integrity(self) -> list[dict[str, Any]]:
        """Return any source-side provenance violations for periodic auditing."""
        with self.pool.connection() as connection:
            stage5_exists = connection.execute(
                "SELECT to_regclass('havre.stage5_required_provenance_violations') "
                "IS NOT NULL AS present"
            ).fetchone()["present"]
            stage5_union = (
                " UNION ALL SELECT * FROM havre.stage5_required_provenance_violations"
                if stage5_exists
                else ""
            )
            stage6_exists = connection.execute(
                "SELECT to_regclass('havre.stage6_required_provenance_violations') "
                "IS NOT NULL AS present"
            ).fetchone()["present"]
            stage6_union = (
                " UNION ALL SELECT * FROM havre.stage6_required_provenance_violations"
                if stage6_exists
                else ""
            )
            stage7_exists = connection.execute(
                "SELECT to_regclass('havre.stage7_required_provenance_violations') "
                "IS NOT NULL AS present"
            ).fetchone()["present"]
            stage7_union = (
                " UNION ALL SELECT * FROM havre.stage7_required_provenance_violations"
                if stage7_exists
                else ""
            )
            stage8_exists = connection.execute(
                "SELECT to_regclass('havre.stage8_integrity_violations') "
                "IS NOT NULL AS present"
            ).fetchone()["present"]
            stage8_union = (
                " UNION ALL SELECT * FROM havre.stage8_integrity_violations"
                if stage8_exists
                else ""
            )
            stage12_exists = connection.execute(
                "SELECT to_regclass('havre.stage12_context_integrity_violations') "
                "IS NOT NULL AS present"
            ).fetchone()["present"]
            stage12_union = (
                " UNION ALL SELECT * FROM havre.stage12_context_integrity_violations"
                if stage12_exists
                else ""
            )
            daily_learning_exists = connection.execute(
                "SELECT to_regclass('havre.daily_learning_integrity_violations') "
                "IS NOT NULL AS present"
            ).fetchone()["present"]
            daily_learning_union = (
                " UNION ALL SELECT * FROM havre.daily_learning_integrity_violations"
                if daily_learning_exists
                else ""
            )
            return connection.execute(
                "SELECT * FROM havre.provenance_integrity_violations "
                "UNION ALL SELECT * FROM havre.stage4_required_provenance_violations"
                f"{stage5_union}{stage6_union}{stage7_union}{stage8_union}"
                f"{stage12_union}{daily_learning_union} "
                "ORDER BY owner_id, provenance_edge_id"
            ).fetchall()

    def persist_inference_benchmark_reports(
        self, *, system_report, compatibility_report, workload_manifest
    ) -> None:
        """Atomically store both immutable reports for one synthetic run."""

        from evals.inference_runner import validate_approved_controlled_workload
        from mlsys.contracts.inference_benchmark import (
            InferenceCompatibilityReport,
            InferenceSystemBenchmarkReport,
            InferenceWorkloadManifest,
            validate_inference_benchmark_report_pair,
        )

        system_report = InferenceSystemBenchmarkReport.model_validate(
            system_report.model_dump(mode="json")
        )
        compatibility_report = InferenceCompatibilityReport.model_validate(
            compatibility_report.model_dump(mode="json")
        )
        workload_manifest = validate_approved_controlled_workload(
            InferenceWorkloadManifest.model_validate(
                workload_manifest.model_dump(mode="json")
            )
        )
        validate_inference_benchmark_report_pair(system_report, compatibility_report)

        if compatibility_report.benchmark_run_id != system_report.benchmark_run_id:
            raise ValueError("benchmark report pair must share benchmark_run_id")
        if system_report.workload_content_hash != workload_manifest.content_hash:
            raise ValueError("systems report workload hash does not match manifest")
        if compatibility_report.workload_content_hash != workload_manifest.content_hash:
            raise ValueError("compatibility report workload hash does not match manifest")
        if (
            compatibility_report.candidate_manifest_id
            != system_report.system_under_test.manifest_id
            or compatibility_report.candidate_manifest_content_hash
            != system_report.system_under_test.content_hash
        ):
            raise ValueError(
                "compatibility report candidate does not match the systems report"
            )
        common = (
            system_report.benchmark_run_id,
            Jsonb(system_report.system_under_test.model_dump(mode="json")),
            Jsonb(workload_manifest.model_dump(mode="json")),
            Jsonb(system_report.environment.model_dump(mode="json")),
        )
        rows = (
            (
                "systems_performance",
                Jsonb(system_report.model_dump(mode="json")),
                system_report.content_hash,
                system_report.completed_at,
            ),
            (
                "behavior_compatibility",
                Jsonb(compatibility_report.model_dump(mode="json")),
                compatibility_report.content_hash,
                compatibility_report.completed_at,
            ),
        )
        with self.pool.connection() as connection, connection.transaction():
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (str(common[0]),),
            )
            existing_rows = connection.execute(
                """
                SELECT report_kind, content_hash
                FROM havre.inference_benchmark_runs
                WHERE benchmark_run_id = %s
                ORDER BY report_kind
                FOR UPDATE
                """,
                (common[0],),
            ).fetchall()
            if existing_rows:
                expected_hashes = {
                    report_kind: report_hash
                    for report_kind, _report, report_hash, _created_at in rows
                }
                existing_hashes = {
                    row["report_kind"]: row["content_hash"]
                    for row in existing_rows
                }
                if existing_hashes != expected_hashes:
                    raise ValueError(
                        "benchmark run is already bound to a partial or different report pair"
                    )
                return
            for report_kind, report, report_hash, created_at in rows:
                connection.execute(
                    """
                    INSERT INTO havre.inference_benchmark_runs (
                        benchmark_run_id, schema_version, report_kind,
                        system_manifest, workload_manifest, environment_manifest,
                        report, content_hash, created_at
                    ) VALUES (%s, 1, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        common[0], report_kind, common[1], common[2], common[3],
                        report, report_hash, created_at,
                    ),
                )

    @staticmethod
    def _load_stage4_evidence(
        connection,
        *,
        owner_id: UUID,
        evidence: tuple[EvidenceRef, ...],
        require_support: bool = True,
    ) -> list[dict[str, Any]]:
        if not evidence:
            raise ValueError("derived Stage 4 records require evidence")
        identities: set[tuple[str, UUID, int | None]] = set()
        rows: list[dict[str, Any]] = []
        for reference in evidence:
            identity = (
                reference.source_kind.value,
                reference.source_id,
                reference.source_revision,
            )
            if identity in identities:
                raise ValueError("an evidence source cannot be repeated or conflict with itself")
            identities.add(identity)
            if reference.source_kind is EvidenceSourceKind.EVENT:
                row = connection.execute(
                    """
                    SELECT event.event_id AS anchor_event_id,
                           event.session_id, event.request_id, event.trace_id,
                           event.recorded_at, event.payload,
                           event.privacy_class, event.memory_eligible,
                           event.training_eligible, event.cloud_eligible,
                           event.policy_version, event.policy_revision_id,
                           event.policy_decision_source,
                           event.policy_authorization_ref
                    FROM havre.events AS event
                    WHERE event.owner_id = %s AND event.event_id = %s
                    """,
                    (owner_id, reference.source_id),
                ).fetchone()
                if row is None:
                    raise LookupError("evidence event not found for owner")
                occurred = row["recorded_at"]
                client_created = row["payload"].get("client_created_at")
                if isinstance(client_created, str):
                    occurred = datetime.fromisoformat(
                        client_created.replace("Z", "+00:00")
                    )
                learned_at = row["recorded_at"]
                material = dict(row)
                material.update(
                    {
                        "occurred_from": occurred,
                        "occurred_to": occurred,
                        "learned_at": learned_at,
                        "policy": PostgresRepository._policy_from_row(row),
                    }
                )
            elif reference.source_kind is EvidenceSourceKind.MEMORY_REVISION:
                row = connection.execute(
                    """
                    SELECT memory.*, event.session_id, event.request_id,
                           event.event_id AS anchor_event_id
                    FROM havre.memory_revisions AS memory
                    JOIN havre.events AS event
                      ON event.owner_id = memory.owner_id
                     AND event.event_id = memory.created_event_id
                    WHERE memory.owner_id = %s AND memory.memory_id = %s
                      AND memory.revision = %s
                    """,
                    (owner_id, reference.source_id, reference.source_revision),
                ).fetchone()
                if row is None:
                    raise LookupError("evidence memory revision not found for owner")
                material = dict(row)
                material.update(
                    {
                        "anchor_event_id": row["created_event_id"],
                        "occurred_from": row["source_occurred_at"] or row["created_at"],
                        "occurred_to": row["source_occurred_at"] or row["created_at"],
                        "learned_at": row["created_at"],
                        "policy": PostgresRepository._policy_from_row(row),
                    }
                )
            else:
                row = connection.execute(
                    """
                    SELECT belief.*, event.session_id, event.request_id,
                           event.event_id AS anchor_event_id
                    FROM havre.user_belief_revisions AS belief
                    JOIN havre.events AS event
                      ON event.owner_id = belief.owner_id
                     AND event.event_id = belief.created_event_id
                    WHERE belief.owner_id = %s AND belief.belief_id = %s
                      AND belief.revision = %s
                    """,
                    (owner_id, reference.source_id, reference.source_revision),
                ).fetchone()
                if row is None:
                    raise LookupError("evidence belief revision not found for owner")
                material = dict(row)
                material.update(
                    {
                        "anchor_event_id": row["created_event_id"],
                        "occurred_from": row["evidence_occurred_from"],
                        "occurred_to": row["evidence_occurred_to"],
                        "learned_at": row["learned_at"],
                        "policy": PostgresRepository._policy_from_row(row),
                    }
                )
            if not material["policy"].memory_eligible:
                raise ValueError("evidence is not eligible for durable derived understanding")
            rows.append(material)
        if require_support and not any(
            item.relation is EvidenceRelation.SUPPORTS for item in evidence
        ):
            raise ValueError("derived Stage 4 records require supporting evidence")
        return rows

    @staticmethod
    def _combine_stage4_evidence_policy(rows: list[dict[str, Any]]) -> DataPolicy:
        policy = combine_policies(tuple(row["policy"] for row in rows))
        if not policy.memory_eligible:
            raise ValueError("all evidence must permit memory use")
        return policy

    @staticmethod
    def _stage4_evidence_utc_dates(rows: list[dict[str, Any]]) -> set[date]:
        dates: set[date] = set()
        for row in rows:
            occurred_at = row["occurred_from"]
            if (
                occurred_at is None
                or occurred_at.tzinfo is None
                or occurred_at.utcoffset() is None
            ):
                raise ValueError(
                    "pattern and progress proposal occurrence timestamps must "
                    "be timezone-aware"
                )
            dates.add(occurred_at.astimezone(UTC).date())
        return dates

    @staticmethod
    def _evidence_times(
        rows: list[dict[str, Any]],
    ) -> tuple[datetime | None, datetime | None, datetime]:
        starts = [row["occurred_from"] for row in rows if row["occurred_from"]]
        ends = [row["occurred_to"] for row in rows if row["occurred_to"]]
        learned = [row["learned_at"] for row in rows]
        return (
            min(starts) if starts else None,
            max(ends) if ends else None,
            max(learned),
        )

    @staticmethod
    def _insert_stage4_provenance(
        connection,
        *,
        owner_id: UUID,
        source_kind: str,
        source_id: UUID,
        source_revision: int | None,
        derived_kind: str,
        derived_id: UUID,
        derived_revision: int | None,
        relation: str,
        weight: float | None,
        transform_name: str,
        transform_version: str,
        created_event_id: UUID,
        trace_id: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO havre.provenance_edges (
                provenance_edge_id, schema_version, owner_id,
                source_kind, source_id, source_revision,
                derived_kind, derived_id, derived_revision, relation, weight,
                transform_name, transform_version, created_event_id, trace_id
            ) VALUES (%s, 1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                uuid7(),
                owner_id,
                source_kind,
                source_id,
                source_revision,
                derived_kind,
                derived_id,
                derived_revision,
                relation,
                weight,
                transform_name,
                transform_version,
                created_event_id,
                trace_id,
            ),
        )

    @staticmethod
    def _insert_stage4_evidence_edges(
        connection,
        *,
        owner_id: UUID,
        evidence: tuple[EvidenceRef, ...],
        derived_kind: str,
        derived_id: UUID,
        derived_revision: int | None,
        transform_name: str,
        transform_version: str,
        created_event_id: UUID,
        trace_id: str,
    ) -> None:
        for item in evidence:
            PostgresRepository._insert_stage4_provenance(
                connection,
                owner_id=owner_id,
                source_kind=item.source_kind.value,
                source_id=item.source_id,
                source_revision=item.source_revision,
                derived_kind=derived_kind,
                derived_id=derived_id,
                derived_revision=derived_revision,
                relation=item.relation.value,
                weight=item.weight,
                transform_name=transform_name,
                transform_version=transform_version,
                created_event_id=created_event_id,
                trace_id=trace_id,
            )

    @staticmethod
    def _insert_belief_revision(
        connection, revision: BeliefRevision
    ) -> BeliefRevision:
        policy = revision.data_policy
        row = connection.execute(
            """
            INSERT INTO havre.user_belief_revisions (
                owner_id, belief_id, revision, schema_version, belief_key,
                statement, belief_type, confidence, confidence_method,
                initial_status, evidence_occurred_from, evidence_occurred_to,
                learned_at, valid_from, valid_to, supersedes_revision,
                created_event_id, trace_id, privacy_class, memory_eligible,
                training_eligible, cloud_eligible, policy_version,
                policy_revision_id, policy_decision_source,
                policy_authorization_ref, content_hash, created_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                statement_timestamp()
            )
            RETURNING created_at
            """,
            (
                revision.owner_id,
                revision.belief_id,
                revision.revision,
                revision.schema_version,
                revision.belief_key,
                revision.statement,
                revision.belief_type.value,
                revision.confidence,
                revision.confidence_method,
                revision.initial_status.value,
                revision.evidence_occurred_from,
                revision.evidence_occurred_to,
                revision.learned_at,
                revision.valid_from,
                revision.valid_to,
                revision.supersedes_revision,
                revision.created_event_id,
                revision.trace_id,
                policy.privacy_class.value,
                policy.memory_eligible,
                policy.training_eligible,
                policy.cloud_eligible,
                policy.policy_version,
                policy.policy_revision_id,
                policy.decision_source,
                policy.authorization_ref,
                revision.content_hash,
            ),
        ).fetchone()
        assert row is not None
        return revision.model_copy(update={"created_at": row["created_at"]})

    @staticmethod
    def _build_belief_transition(
        *,
        owner_id: UUID,
        belief_id: UUID,
        revision: int,
        transition_type: BeliefTransitionType,
        reason: str,
        occurred_at: datetime,
        policy: DataPolicy,
        anchor: dict[str, Any],
        replacement_belief_id: UUID | None = None,
        replacement_revision: int | None = None,
    ) -> tuple[EventEnvelope, BeliefTransition]:
        transition_id = uuid7()
        event = EventEnvelope(
            event_type=EventType.USER_BELIEF_TRANSITIONED,
            owner_id=owner_id,
            session_id=anchor["session_id"],
            request_id=anchor["request_id"],
            trace_id=anchor["trace_id"],
            causation_event_id=anchor["anchor_event_id"],
            data_policy=policy,
            payload=BeliefTransitionPayload(
                belief_transition_id=transition_id,
                belief_id=belief_id,
                belief_revision=revision,
                transition_type=transition_type.value,
                reason=reason,
                replacement_belief_id=replacement_belief_id,
                replacement_revision=replacement_revision,
            ),
        )
        transition = BeliefTransition(
            belief_transition_id=transition_id,
            owner_id=owner_id,
            belief_id=belief_id,
            belief_revision=revision,
            transition_type=transition_type,
            occurred_at=occurred_at,
            recorded_at=event.recorded_at,
            reason=reason,
            causing_event_id=event.event_id,
            replacement_belief_id=replacement_belief_id,
            replacement_revision=replacement_revision,
        )
        return event, transition

    @staticmethod
    def _insert_belief_transition(
        connection, transition: BeliefTransition
    ) -> BeliefTransition:
        row = connection.execute(
            """
            INSERT INTO havre.belief_revision_transitions (
                belief_transition_id, schema_version, owner_id, belief_id,
                belief_revision, transition_type, occurred_at, recorded_at,
                reason, causing_event_id, replacement_belief_id,
                replacement_revision, content_hash
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, statement_timestamp(),
                %s, %s, %s, %s, %s
            )
            RETURNING recorded_at
            """,
            (
                transition.belief_transition_id,
                transition.schema_version,
                transition.owner_id,
                transition.belief_id,
                transition.belief_revision,
                transition.transition_type.value,
                transition.occurred_at,
                transition.reason,
                transition.causing_event_id,
                transition.replacement_belief_id,
                transition.replacement_revision,
                transition.content_hash,
            ),
        ).fetchone()
        assert row is not None
        return transition.model_copy(update={"recorded_at": row["recorded_at"]})

    @staticmethod
    def _belief_from_row(row: dict[str, Any]) -> BeliefRevision:
        return BeliefRevision(
            owner_id=row["owner_id"],
            belief_id=row["belief_id"],
            revision=row["revision"],
            belief_key=row["belief_key"],
            statement=row["statement"],
            belief_type=row["belief_type"],
            confidence=float(row["confidence"]),
            confidence_method=row["confidence_method"],
            initial_status=row["initial_status"],
            evidence_occurred_from=row["evidence_occurred_from"],
            evidence_occurred_to=row["evidence_occurred_to"],
            learned_at=row["learned_at"],
            valid_from=row["valid_from"],
            valid_to=row["valid_to"],
            supersedes_revision=row["supersedes_revision"],
            created_event_id=row["created_event_id"],
            trace_id=row["trace_id"],
            data_policy=PostgresRepository._policy_from_row(row),
            content_hash=row["content_hash"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _belief_transition_from_row(row: dict[str, Any]) -> BeliefTransition:
        return BeliefTransition(
            belief_transition_id=row["belief_transition_id"],
            owner_id=row["owner_id"],
            belief_id=row["belief_id"],
            belief_revision=row["belief_revision"],
            transition_type=row["transition_type"],
            occurred_at=row["occurred_at"],
            recorded_at=row["recorded_at"],
            reason=row["reason"],
            causing_event_id=row["causing_event_id"],
            replacement_belief_id=row["replacement_belief_id"],
            replacement_revision=row["replacement_revision"],
            content_hash=row["content_hash"],
        )

    @staticmethod
    def _insert_consolidation_proposal(
        connection, proposal: ConsolidationProposal
    ) -> None:
        policy = proposal.data_policy
        connection.execute(
            """
            INSERT INTO havre.consolidation_proposals (
                proposal_id, schema_version, owner_id, memory_class, content,
                content_text, content_hash, confidence, confidence_method,
                importance, importance_policy_version, detector_version,
                evidence_snapshot, status, created_event_id, trace_id,
                privacy_class, memory_eligible, training_eligible, cloud_eligible,
                policy_version, policy_revision_id, policy_decision_source,
                policy_authorization_ref, created_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                proposal.proposal_id,
                proposal.schema_version,
                proposal.owner_id,
                proposal.memory_class,
                Jsonb(proposal.content),
                proposal.content_text,
                proposal.content_hash,
                proposal.confidence,
                proposal.confidence_method,
                proposal.importance,
                proposal.importance_policy_version,
                proposal.detector_version,
                Jsonb([item.model_dump(mode="json") for item in proposal.evidence]),
                proposal.status.value,
                proposal.created_event_id,
                proposal.trace_id,
                policy.privacy_class.value,
                policy.memory_eligible,
                policy.training_eligible,
                policy.cloud_eligible,
                policy.policy_version,
                policy.policy_revision_id,
                policy.decision_source,
                policy.authorization_ref,
                proposal.created_at,
            ),
        )

    @staticmethod
    def _insert_current_state(connection, snapshot: CurrentStateSnapshot) -> None:
        policy = snapshot.data_policy
        connection.execute(
            """
            INSERT INTO havre.current_state_snapshots (
                state_snapshot_id, schema_version, owner_id, summary, state,
                uncertainty, estimated_at, expires_at, estimator_version,
                evidence_snapshot, created_event_id, trace_id, privacy_class,
                memory_eligible, training_eligible, cloud_eligible, policy_version,
                policy_revision_id, policy_decision_source,
                policy_authorization_ref, content_hash, created_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                snapshot.state_snapshot_id,
                snapshot.schema_version,
                snapshot.owner_id,
                snapshot.summary,
                Jsonb(snapshot.state),
                snapshot.uncertainty,
                snapshot.estimated_at,
                snapshot.expires_at,
                snapshot.estimator_version,
                Jsonb([item.model_dump(mode="json") for item in snapshot.evidence]),
                snapshot.created_event_id,
                snapshot.trace_id,
                policy.privacy_class.value,
                policy.memory_eligible,
                policy.training_eligible,
                policy.cloud_eligible,
                policy.policy_version,
                policy.policy_revision_id,
                policy.decision_source,
                policy.authorization_ref,
                snapshot.content_hash,
                snapshot.created_at,
            ),
        )

    @staticmethod
    def _current_state_from_row(row: dict[str, Any]) -> CurrentStateSnapshot:
        return CurrentStateSnapshot(
            state_snapshot_id=row["state_snapshot_id"],
            owner_id=row["owner_id"],
            summary=row["summary"],
            state=row["state"],
            uncertainty=float(row["uncertainty"]),
            estimated_at=row["estimated_at"],
            expires_at=row["expires_at"],
            estimator_version=row["estimator_version"],
            evidence=tuple(
                EvidenceRef.model_validate(item) for item in row["evidence_snapshot"]
            ),
            created_event_id=row["created_event_id"],
            trace_id=row["trace_id"],
            data_policy=PostgresRepository._policy_from_row(row),
            content_hash=row["content_hash"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _insert_goal(connection, goal: Goal) -> dict[str, datetime]:
        policy = goal.data_policy
        return connection.execute(
            """
            INSERT INTO havre.goals (
                goal_id, schema_version, owner_id, track, title, why, priority,
                status, next_action, review_at, revision, last_event_id,
                privacy_class, memory_eligible, training_eligible, cloud_eligible,
                policy_version, policy_revision_id, policy_decision_source,
                policy_authorization_ref, content_hash, created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            RETURNING created_at, updated_at
            """,
            (
                goal.goal_id,
                goal.schema_version,
                goal.owner_id,
                goal.track.value,
                goal.title,
                goal.why,
                goal.priority.value,
                goal.status.value,
                goal.next_action,
                goal.review_at,
                goal.revision,
                goal.last_event_id,
                policy.privacy_class.value,
                policy.memory_eligible,
                policy.training_eligible,
                policy.cloud_eligible,
                policy.policy_version,
                policy.policy_revision_id,
                policy.decision_source,
                policy.authorization_ref,
                goal.content_hash,
                goal.created_at,
                goal.updated_at,
            ),
        ).fetchone()

    @staticmethod
    def _insert_goal_progress(connection, progress: GoalProgressRecord) -> None:
        policy = progress.data_policy
        connection.execute(
            """
            INSERT INTO havre.goal_progress_records (
                progress_record_id, schema_version, owner_id, goal_id,
                goal_revision, direction, summary, observed_at, evidence_snapshot,
                created_event_id, trace_id, privacy_class, memory_eligible,
                training_eligible, cloud_eligible, policy_version,
                policy_revision_id, policy_decision_source,
                policy_authorization_ref, content_hash, created_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                progress.progress_record_id,
                progress.schema_version,
                progress.owner_id,
                progress.goal_id,
                progress.goal_revision,
                progress.direction,
                progress.summary,
                progress.observed_at,
                Jsonb([item.model_dump(mode="json") for item in progress.evidence]),
                progress.created_event_id,
                progress.trace_id,
                policy.privacy_class.value,
                policy.memory_eligible,
                policy.training_eligible,
                policy.cloud_eligible,
                policy.policy_version,
                policy.policy_revision_id,
                policy.decision_source,
                policy.authorization_ref,
                progress.content_hash,
                progress.created_at,
            ),
        )

    @staticmethod
    def _policy_from_row(row: dict[str, Any]) -> DataPolicy:
        return DataPolicy(
            policy_revision_id=row["policy_revision_id"],
            privacy_class=row["privacy_class"],
            memory_eligible=row["memory_eligible"],
            training_eligible=row["training_eligible"],
            cloud_eligible=row["cloud_eligible"],
            policy_version=row["policy_version"],
            decision_source=row["policy_decision_source"],
            authorization_ref=row["policy_authorization_ref"],
        )

    @staticmethod
    def _derived_policy_from_row(row: dict[str, Any]) -> DataPolicy:
        privacy_class = row["privacy_class"]
        return DataPolicy(
            privacy_class=privacy_class,
            memory_eligible=row["memory_eligible"],
            training_eligible=False,
            cloud_eligible=(
                row["cloud_eligible"]
                and str(privacy_class) in {"PUBLIC", "NORMAL", "PRIVATE"}
            ),
            policy_version=row["policy_version"],
            decision_source="derived_conservative",
        )

    @staticmethod
    def _memory_from_row(row: dict[str, Any]) -> MemoryRevision:
        return MemoryRevision(
            owner_id=row["owner_id"], memory_id=row["memory_id"],
            revision=row["revision"], memory_class=row["memory_class"], content=row["content"],
            content_text=row["content_text"], confidence=float(row["confidence"]),
            confidence_method=row["confidence_method"], importance=float(row["importance"]),
            importance_policy_version=row["importance_policy_version"], status=row["status"],
            valid_from=row["valid_from"], valid_to=row["valid_to"],
            source_occurred_at=row["source_occurred_at"], created_by=row["created_by"],
            transform_version=row["transform_version"], supersedes_revision=row["supersedes_revision"],
            candidate_id=row["candidate_id"], created_event_id=row["created_event_id"],
            trace_id=row["trace_id"], data_policy=PostgresRepository._policy_from_row(row),
            content_hash=row["content_hash"], created_at=row["created_at"],
        )

    @staticmethod
    def _transition_transform(status: MemoryStatus) -> str:
        return "owner-retraction-v1" if status is MemoryStatus.RETRACTED else "owner-correction-v1"

    @staticmethod
    def _insert_memory_revision(connection, revision: MemoryRevision) -> None:
        policy = revision.data_policy
        connection.execute(
            """
            INSERT INTO havre.memory_revisions (
                owner_id, memory_id, revision, schema_version, memory_class,
                content, content_text, content_hash, confidence, confidence_method,
                importance, importance_policy_version, status, valid_from, valid_to,
                source_occurred_at, created_at, created_by, transform_version,
                supersedes_revision, candidate_id, created_event_id, trace_id,
                privacy_class, memory_eligible, training_eligible, cloud_eligible,
                policy_version, policy_revision_id, policy_decision_source,
                policy_authorization_ref
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s
            )
            """,
            (
                revision.owner_id, revision.memory_id, revision.revision,
                revision.schema_version, revision.memory_class, Jsonb(revision.content),
                revision.content_text, revision.content_hash, revision.confidence,
                revision.confidence_method, revision.importance,
                revision.importance_policy_version, revision.status.value,
                revision.valid_from, revision.valid_to, revision.source_occurred_at,
                revision.created_at, revision.created_by, revision.transform_version,
                revision.supersedes_revision, revision.candidate_id,
                revision.created_event_id, revision.trace_id, policy.privacy_class.value,
                policy.memory_eligible, policy.training_eligible, policy.cloud_eligible,
                policy.policy_version, policy.policy_revision_id, policy.decision_source,
                policy.authorization_ref,
            ),
        )

    @staticmethod
    def _insert_embedding(connection, revision: MemoryRevision, provider) -> None:
        vector = provider.pgvector(provider.embed(revision.content_text))
        connection.execute(
            """
            INSERT INTO havre.memory_embeddings (
                owner_id, memory_id, memory_revision, embedding_version_id,
                chunk_index, embedding, content_hash
            ) VALUES (%s, %s, %s, %s, 0, %s::vector, %s)
            """,
            (
                revision.owner_id, revision.memory_id, revision.revision,
                provider.version.embedding_version_id, vector, revision.content_hash,
            ),
        )

    @staticmethod
    def _insert_provenance(
        connection,
        *,
        owner_id: UUID,
        source_kind: str,
        source_id: UUID,
        source_revision: int | None,
        revision: MemoryRevision,
        relation: str,
        transform_name: str,
        transform_version: str,
        created_event_id: UUID,
    ) -> None:
        connection.execute(
            """
            INSERT INTO havre.provenance_edges (
                provenance_edge_id, schema_version, owner_id, source_kind,
                source_id, source_revision, derived_kind, derived_id,
                derived_revision, relation, weight, transform_name,
                transform_version, created_event_id, trace_id
            ) VALUES (%s, 1, %s, %s, %s, %s, 'memory_revision', %s, %s,
                      %s, 1.0, %s, %s, %s, %s)
            """,
            (
                uuid7(), owner_id, source_kind, source_id, source_revision,
                revision.memory_id, revision.revision, relation, transform_name,
                transform_version, created_event_id, revision.trace_id,
            ),
        )

    @staticmethod
    def _insert_event(connection, event: EventEnvelope) -> None:
        policy = event.data_policy
        if event.scene_session_id is None:
            connection.execute(
                """
                INSERT INTO havre.events (
                    event_id, schema_version, event_type, event_version, owner_id,
                    session_id, request_id, trace_id, causation_event_id,
                    privacy_class, memory_eligible, training_eligible, cloud_eligible,
                    policy_version, policy_revision_id, policy_decision_source,
                    policy_authorization_ref, payload, content_hash, recorded_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    event.event_id,
                    event.schema_version,
                    event.event_type.value,
                    event.event_version,
                    event.owner_id,
                    event.session_id,
                    event.request_id,
                    event.trace_id,
                    event.causation_event_id,
                    policy.privacy_class.value,
                    policy.memory_eligible,
                    policy.training_eligible,
                    policy.cloud_eligible,
                    policy.policy_version,
                    policy.policy_revision_id,
                    policy.decision_source,
                    policy.authorization_ref,
                    Jsonb(event.payload.model_dump(mode="json")),
                    event.content_hash,
                    event.recorded_at,
                ),
            )
            return
        connection.execute(
            """
            INSERT INTO havre.events (
                event_id, schema_version, event_type, event_version, owner_id,
                session_id, scene_session_id, request_id, trace_id, causation_event_id,
                privacy_class, memory_eligible, training_eligible, cloud_eligible,
                policy_version, policy_revision_id, policy_decision_source,
                policy_authorization_ref, payload, content_hash, recorded_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                event.event_id,
                event.schema_version,
                event.event_type.value,
                event.event_version,
                event.owner_id,
                event.session_id,
                event.scene_session_id,
                event.request_id,
                event.trace_id,
                event.causation_event_id,
                policy.privacy_class.value,
                policy.memory_eligible,
                policy.training_eligible,
                policy.cloud_eligible,
                policy.policy_version,
                policy.policy_revision_id,
                policy.decision_source,
                policy.authorization_ref,
                Jsonb(event.payload.model_dump(mode="json")),
                event.content_hash,
                event.recorded_at,
            ),
        )

    @staticmethod
    def _insert_spans(connection, spans: list[Span]) -> None:
        for span in spans:
            connection.execute(
                """
                INSERT INTO havre.spans (
                    span_id, trace_id, parent_span_id, name, kind, started_at,
                    ended_at, duration_ms, status, attributes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (span_id) DO NOTHING
                """,
                (
                    span.span_id,
                    span.trace_id,
                    span.parent_span_id,
                    span.name,
                    span.kind,
                    span.started_at,
                    span.ended_at,
                    span.duration_ms,
                    span.status,
                    Jsonb(span.attributes),
                ),
            )
