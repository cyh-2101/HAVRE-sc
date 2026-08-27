"""Permanent Stage 1 request-to-delivered-event orchestration."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from companion.context import ContextBuilder, ContextPack
from companion.events import (
    AssistantMessagePayload,
    DeliveryRecord,
    EventEnvelope,
    EventType,
    InteractionFailurePayload,
    TextContentPart,
    UserMessagePayload,
)
from companion.identity import IdentityBundle
from companion.memory.embedding import DeterministicEmbeddingProvider
from companion.hashing import content_hash
from companion.ids import uuid7
from companion.persistence.postgres import PostgresRepository
from companion.policy import CoreResponsePolicy, DataPolicy, PrivacyClass
from companion.policy.models import PRIVACY_RESTRICTION_ORDER
from companion.tracing import TraceContext
from mlsys.contracts import (
    GenerationSettings,
    InferenceMessage,
    InferenceRequest,
    InferenceResponse,
    InferenceStreamEvent,
    RouteDecision,
    validate_inference_response_lineage,
)
from mlsys.contracts.inference import InferenceConstraints
from mlsys.serving import (
    ModelProvider,
    ProviderInferenceError,
    ProviderPolicyError,
    ProviderVersionError,
    Stage1Router,
)
from mlsys.retrieval.models import (
    RetrievalFilters,
    RetrievalQuery,
    RetrievalRequest,
)
from mlsys.retrieval.service import RetrievalService


logger = logging.getLogger(__name__)


class InteractionInProgress(RuntimeError):
    pass


class InteractionPreviouslyFailed(RuntimeError):
    pass


class IdempotencyConflict(RuntimeError):
    pass


class InferenceTimeoutError(TimeoutError):
    pass


class InteractionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    message: str = Field(min_length=1, max_length=100_000)
    privacy_class: PrivacyClass = PrivacyClass.NORMAL
    memory_eligible: bool = True
    session_id: UUID | None = None
    channel: Literal["api", "cli", "web"] = "api"
    language: str | None = Field(default=None, max_length=35)
    client_created_at: datetime | None = None
    idempotency_key: str = Field(min_length=1, max_length=200)
    traceparent: str | None = None


class InteractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: UUID
    trace_id: str
    traceparent: str
    session_id: UUID
    user_event_id: UUID
    assistant_event_id: UUID
    context_pack_id: UUID
    retrieval_result_id: UUID
    inference_response_id: UUID
    route_decision_id: UUID
    content: str
    provider_id: str
    provider_class: str
    model_version_id: str
    adapter_version_id: str | None
    provider_adapter_version_id: str
    serving_engine: str
    serving_engine_version: str
    model_artifact_hash: str | None
    runtime_attestation_id: str | None
    runtime_attestation_hash: str | None
    tokenizer_version_id: str
    serving_config_version: str
    prompt_tokens: int
    output_tokens: int
    total_tokens: int
    token_count_source: str
    inference_total_ms: float
    inference_ttft_ms: float | None
    inference_generation_ms: float | None
    estimated_context_tokens: int
    effective_privacy_class: PrivacyClass
    cloud_eligible: bool
    training_eligible: Literal[False]
    idempotent_replay: bool


class InteractionService:
    version = "interaction-orchestrator-v6"

    def __init__(
        self,
        *,
        owner_id: UUID,
        identity: IdentityBundle,
        repository: PostgresRepository,
        context_builder: ContextBuilder,
        router: Stage1Router,
        provider: ModelProvider,
        retrieval_service: RetrievalService | None = None,
        response_policy: CoreResponsePolicy | None = None,
        inference_timeout_ms: int = 20_000,
    ) -> None:
        if inference_timeout_ms <= 0:
            raise ValueError("inference_timeout_ms must be positive")
        self.owner_id = owner_id
        self.identity = identity
        self.repository = repository
        self.context_builder = context_builder
        self.router = router
        self.provider = provider
        self.response_policy = response_policy or CoreResponsePolicy()
        if retrieval_service is None:
            embedding_provider = DeterministicEmbeddingProvider()
            repository.register_embedding_version(embedding_provider.version)
            retrieval_service = RetrievalService(
                repository=repository,
                embedding_provider=embedding_provider,
            )
        self.retrieval_service = retrieval_service
        self.inference_timeout_ms = inference_timeout_ms

    async def interact(self, command: InteractionCommand) -> InteractionResult:
        request_id = uuid7()
        request_fingerprint = self._request_fingerprint(command)
        session_id = command.session_id or uuid7()
        trace = TraceContext.from_traceparent(command.traceparent)
        trace_started_at = datetime.now(UTC)
        policy = DataPolicy.owner_default(
            command.privacy_class,
            memory_eligible=command.memory_eligible,
        )
        user_event = EventEnvelope(
            event_type=EventType.USER_MESSAGE,
            owner_id=self.owner_id,
            session_id=session_id,
            request_id=request_id,
            trace_id=trace.trace_id,
            data_policy=policy,
            payload=UserMessagePayload(
                content_parts=(TextContentPart(text=command.message),),
                channel=command.channel,
                language=command.language,
                client_created_at=command.client_created_at,
            ),
        )
        created = False
        result: InteractionResult | None = None
        failure: Exception | None = None
        cancellation: asyncio.CancelledError | None = None
        completion_committed = False
        inference_started = False
        failure_context: (
            tuple[ContextPack, RouteDecision, InferenceRequest, object | None] | None
        ) = None
        pre_route_context: ContextPack | None = None
        failure_stage: Literal[
            "capability_check", "routing", "version_check", "inference"
        ] | None = None

        try:
            with trace.span(
                "interaction.request",
                kind="server",
                attributes={
                    "orchestrator_version": self.version,
                    "inference_timeout_ms": self.inference_timeout_ms,
                },
            ) as root_span_id:
                with trace.span(
                    "persistence.user_message",
                    parent_span_id=root_span_id,
                    attributes={
                        "request_id": str(request_id),
                        "privacy_class": policy.privacy_class.value,
                    },
                ):
                    reservation_task = asyncio.create_task(asyncio.to_thread(
                            self.repository.reserve_interaction,
                            idempotency_key=command.idempotency_key,
                            request_fingerprint=request_fingerprint,
                            user_event=user_event,
                            trace=trace,
                            channel=command.channel,
                            trace_started_at=trace_started_at,
                        ))
                    try:
                        reservation = await asyncio.shield(reservation_task)
                    except asyncio.CancelledError as error:
                        # `to_thread` cannot stop the PostgreSQL transaction.
                        # Wait for its durable outcome so outer cancellation
                        # reconciliation knows whether a request was created.
                        reservation = await reservation_task
                        created = reservation.created
                        raise error
                created = reservation.created
                if not created:
                    if reservation.request["request_fingerprint"] != request_fingerprint:
                        raise IdempotencyConflict(
                            "idempotency key was already used for a different request"
                        )
                    result = await self._result_for_existing(reservation.request)
                else:
                    with trace.span(
                        "memory.retrieve",
                        parent_span_id=root_span_id,
                        attributes={
                            "algorithm_version": "retrieval-r1-vector-gated-v2",
                            "candidate_k": 100,
                            "top_k": 5,
                        },
                    ):
                        allowed_privacy = tuple(
                            item
                            for item in PrivacyClass
                            if PRIVACY_RESTRICTION_ORDER[item]
                            <= PRIVACY_RESTRICTION_ORDER[policy.privacy_class]
                        )
                        retrieval_result = await asyncio.to_thread(
                            self.retrieval_service.retrieve,
                            RetrievalRequest(
                                trace_id=trace.trace_id,
                                owner_id=self.owner_id,
                                request_id=request_id,
                                query=RetrievalQuery(
                                    text=command.message,
                                    language=command.language,
                                    event_id=user_event.event_id,
                                ),
                                filters=RetrievalFilters(
                                    allowed_privacy_classes=allowed_privacy
                                ),
                            ),
                        )
                    with trace.span(
                        "user_model.select_context",
                        parent_span_id=root_span_id,
                        attributes={
                            "selector_version": "stage4-personal-context-selector-v1",
                        },
                    ):
                        personal_context = await asyncio.to_thread(
                            self.repository.select_personal_context,
                            owner_id=self.owner_id,
                            query_text=command.message,
                            maximum_privacy_class=policy.privacy_class,
                        )
                        conversation_history = await asyncio.to_thread(
                            self.repository.select_conversation_history,
                            owner_id=self.owner_id,
                            session_id=session_id,
                            exclude_event_id=user_event.event_id,
                            maximum_privacy_class=policy.privacy_class,
                        )
                    with trace.span(
                        "context.build",
                        parent_span_id=root_span_id,
                        attributes={
                            "builder_version": self.context_builder.version,
                            "constitution_version_id": self.identity.constitution.version_id,
                            "identity_version_id": self.identity.identity.version_id,
                            "values_version_id": self.identity.values.version_id,
                        },
                    ):
                        context_pack = self.context_builder.build(
                            request_id=request_id,
                            trace_id=trace.trace_id,
                            owner_id=self.owner_id,
                            identity=self.identity,
                            user_event=user_event,
                            retrieval_result=retrieval_result,
                            personal_context=personal_context,
                            conversation_history=conversation_history,
                        )

                    pre_route_context = context_pack
                    failure_stage = "capability_check"
                    capabilities = await self.provider.capabilities()
                    failure_stage = "routing"
                    with trace.span(
                        "inference.route",
                        parent_span_id=root_span_id,
                        attributes={
                            "router_version": self.router.version,
                            "candidate_count": 1,
                        },
                    ):
                        route = self.router.decide(
                            request_id=request_id,
                            trace_id=trace.trace_id,
                            policy=context_pack.effective_data_policy,
                            capabilities=capabilities,
                            required_input_tokens=(
                                context_pack.estimated_total_tokens
                            ),
                            required_output_tokens=(
                                context_pack.token_budget.reserved_output_tokens
                            ),
                            required_streaming=True,
                        )
                    inference_request = self._inference_request(
                        request_id=request_id,
                        trace=trace,
                        context_pack=context_pack,
                        route=route,
                    )
                    failure_context = (context_pack, route, inference_request, None)
                    failure_stage = "version_check"
                    provider_version = await self.provider.version()
                    self._validate_provider_version(
                        provider_version, capabilities, route
                    )
                    failure_context = (
                        context_pack, route, inference_request, provider_version
                    )
                    with trace.span(
                        "inference.generate",
                        kind="client",
                        parent_span_id=root_span_id,
                        attributes={
                            "provider_id": route.selected_provider_id,
                            "model_version_id": route.selected_model_version_id,
                            "execution_environment": route.execution_environment,
                        },
                    ) as inference_span_id:
                        inference_request = inference_request.model_copy(
                            update={
                                "metadata": {
                                    **inference_request.metadata,
                                    "traceparent": trace.traceparent(inference_span_id),
                                }
                            }
                        )
                        failure_context = (
                            context_pack, route, inference_request, provider_version
                        )
                        inference_started_at = datetime.now(UTC)
                        inference_started = True
                        failure_stage = "inference"
                        try:
                            inference_response = await asyncio.wait_for(
                                self._collect_stream(
                                    request=inference_request,
                                    route=route,
                                    provider_class=capabilities.provider_class,
                                    provider_version=provider_version,
                                ),
                                timeout=inference_request.constraints.timeout_ms / 1000,
                            )
                        except TimeoutError as error:
                            raise InferenceTimeoutError(
                                f"provider exceeded the enforced "
                                f"{inference_request.constraints.timeout_ms} ms timeout"
                            ) from error

                    with trace.span(
                        "policy.response",
                        parent_span_id=root_span_id,
                        attributes={"policy_version": self.response_policy.version},
                    ):
                        policy_result = self.response_policy.apply(
                            request_id=request_id,
                            trace_id=trace.trace_id,
                            context_pack_id=context_pack.context_pack_id,
                            inference_response_id=(
                                inference_response.inference_response_id
                            ),
                            current_user_input=command.message,
                            raw_output_parts=tuple(
                                part.text for part in inference_response.output_parts
                            ),
                            history_evidence=self._history_evidence(context_pack),
                            # Daily chat has no tool/effect receipts. A future
                            # tool runtime must pass explicit capabilities.
                            available_effects=(),
                        )
                    delivered_parts = tuple(
                        TextContentPart(text=value)
                        for value in policy_result.output_parts
                    )
                    delivery_time = datetime.now(UTC)
                    assistant_event = EventEnvelope(
                        event_type=EventType.ASSISTANT_MESSAGE,
                        owner_id=self.owner_id,
                        session_id=session_id,
                        request_id=request_id,
                        trace_id=trace.trace_id,
                        causation_event_id=user_event.event_id,
                        data_policy=context_pack.effective_data_policy,
                        payload=AssistantMessagePayload(
                            content_parts=delivered_parts,
                            status="completed",
                            inference_response_id=inference_response.inference_response_id,
                            context_pack_id=context_pack.context_pack_id,
                            policy_decision_id=policy_result.decision.decision_id,
                            response_policy_decision=policy_result.decision,
                            delivery=DeliveryRecord(
                                channel=command.channel,
                                # Stage 3 consumes provider streaming internally,
                                # but the API/CLI deliver only the completed
                                # InteractionResult. Do not claim client-visible
                                # streaming that has not happened.
                                first_visible_at=delivery_time,
                                completed_at=delivery_time,
                            ),
                        ),
                    )
                    with trace.span(
                        "persistence.delivered_response",
                        parent_span_id=root_span_id,
                        attributes={"request_id": str(request_id)},
                    ):
                        completion_task = asyncio.create_task(asyncio.to_thread(
                                self.repository.complete_interaction,
                                owner_id=self.owner_id,
                                context_pack=context_pack,
                                route_decision=route,
                                inference_response=inference_response,
                                assistant_event=assistant_event,
                                spans=list(trace.spans),
                            ))
                        try:
                            await asyncio.shield(completion_task)
                            completion_committed = True
                        except asyncio.CancelledError as error:
                            # The database commit may already be in progress.
                            # Resolve it before propagating disconnect. A
                            # completed response remains available in durable
                            # history; it must never race a contradictory fail.
                            await completion_task
                            completion_committed = True
                            raise error
                    result = self._result(
                        user_event=user_event,
                        assistant_event=assistant_event,
                        context_pack=context_pack,
                        route=route,
                        response=inference_response,
                        traceparent=trace.traceparent(root_span_id),
                        replay=False,
                    )
        except asyncio.CancelledError as error:
            # Client disconnect/task cancellation happens after the USER Event
            # may already be durable. Convert it to a normal internal failure
            # for reconciliation, then re-raise the original cancellation only
            # after the request is no longer stuck in `processing`.
            cancellation = error
            failure = RuntimeError("interaction cancelled before durable delivery")
        except Exception as error:
            failure = error

        if created:
            try:
                await asyncio.to_thread(self.repository.append_spans, list(trace.spans))
            except Exception as span_error:
                logger.warning(
                    "trace_span_reconciliation_failed request_id=%s error_type=%s",
                    request_id,
                    type(span_error).__name__,
                )
        if failure is not None:
            if cancellation is not None and completion_committed:
                raise cancellation
            if created:
                if failure_context is not None:
                    context_pack, route, inference_request, provider_version = failure_context
                    typed_failure = self._typed_failure(
                        failure,
                        inference_request=inference_request,
                        provider_id=route.selected_provider_id,
                        provider_class=(
                            capabilities.provider_class
                            if "capabilities" in locals()
                            else "local_test"
                        ),
                    )
                    if isinstance(failure, (ProviderInferenceError, ProviderVersionError)):
                        # A provider exception is trusted only after its lineage
                        # has been rebound or independently verified above.
                        failure = ProviderInferenceError(typed_failure)
                    failure_event = EventEnvelope(
                        event_type=EventType.INTERACTION_FAILED,
                        owner_id=self.owner_id,
                        session_id=session_id,
                        request_id=request_id,
                        trace_id=trace.trace_id,
                        causation_event_id=user_event.event_id,
                        data_policy=context_pack.effective_data_policy,
                        payload=InteractionFailurePayload(
                            failure_stage=(
                                "inference" if inference_started else "version_check"
                            ),
                            inference_request_id=inference_request.inference_request_id,
                            context_pack_id=context_pack.context_pack_id,
                            route_decision_id=route.route_decision_id,
                            failure_code=typed_failure.code,
                            retryable=typed_failure.retryable,
                            safe_message=typed_failure.safe_message,
                        ),
                    )
                    if provider_version is not None and inference_started:
                        await asyncio.to_thread(
                            self.repository.fail_inference_interaction,
                            owner_id=self.owner_id,
                            context_pack=context_pack,
                            route_decision=route,
                            inference_request=inference_request,
                            inference_failure=typed_failure,
                            provider_version=provider_version,
                            failure_event=failure_event,
                            spans=list(trace.spans),
                        )
                    else:
                        await asyncio.to_thread(
                            self.repository.fail_pre_inference_interaction,
                            owner_id=self.owner_id,
                            context_pack=context_pack,
                            route_decision=route,
                            inference_request=inference_request,
                            failure_event=failure_event,
                            error_code=typed_failure.code,
                            spans=list(trace.spans),
                        )
                elif pre_route_context is not None:
                    if failure_stage == "capability_check":
                        pre_route_code = "model_unavailable"
                        pre_route_retryable = True
                        pre_route_message = (
                            "The configured provider capabilities are unavailable."
                        )
                    else:
                        policy_error = str(failure) if isinstance(
                            failure, ProviderPolicyError
                        ) else ""
                        privacy_rejection = any(
                            marker in policy_error
                            for marker in (
                                "is not approved for",
                                "forbids cloud execution",
                                "cloud provider lacks explicit owner approval",
                            )
                        )
                        pre_route_code = (
                            "privacy_constraint_unsatisfied"
                            if privacy_rejection
                            else "unsupported_capability"
                        )
                        pre_route_retryable = False
                        pre_route_message = (
                            "No configured provider satisfies the request's privacy policy."
                            if privacy_rejection
                            else "No configured provider supports the required request capabilities."
                        )
                    failure_event = EventEnvelope(
                        event_type=EventType.INTERACTION_FAILED,
                        owner_id=self.owner_id,
                        session_id=session_id,
                        request_id=request_id,
                        trace_id=trace.trace_id,
                        causation_event_id=user_event.event_id,
                        data_policy=pre_route_context.effective_data_policy,
                        payload=InteractionFailurePayload(
                            failure_stage=(
                                failure_stage
                                if failure_stage in {"capability_check", "routing"}
                                else "capability_check"
                            ),
                            context_pack_id=pre_route_context.context_pack_id,
                            failure_code=pre_route_code,
                            retryable=pre_route_retryable,
                            safe_message=pre_route_message,
                        ),
                    )
                    await asyncio.to_thread(
                        self.repository.fail_pre_route_interaction,
                        owner_id=self.owner_id,
                        context_pack=pre_route_context,
                        failure_event=failure_event,
                        error_code=pre_route_code,
                        spans=list(trace.spans),
                    )
                else:
                    await asyncio.to_thread(
                        self.repository.mark_failed,
                        request_id,
                        self.owner_id,
                        type(failure).__name__,
                    )
            if cancellation is not None:
                raise cancellation
            raise failure
        if result is None:
            raise RuntimeError("interaction completed without a result")
        return result

    async def _result_for_existing(self, request: dict[str, object]) -> InteractionResult:
        status = request["status"]
        if status == "processing":
            raise InteractionInProgress("this idempotent request is still processing")
        if status == "failed":
            raise InteractionPreviouslyFailed(
                f"this idempotent request previously failed: {request['error_code']}"
            )
        evidence = await asyncio.to_thread(
            self.repository.evidence,
            request["request_id"],
            owner_id=self.owner_id,
        )
        if evidence is None:
            raise LookupError("completed request evidence was not found")
        return self._result_from_evidence(evidence)

    def _inference_request(
        self,
        *,
        request_id: UUID,
        trace: TraceContext,
        context_pack: ContextPack,
        route: RouteDecision,
    ) -> InferenceRequest:
        allowed_environments: tuple[Literal["local", "cloud"], ...] = (
            ("local", "cloud")
            if context_pack.effective_data_policy.cloud_eligible
            else ("local",)
        )
        return InferenceRequest(
            request_id=request_id,
            trace_id=trace.trace_id,
            messages=tuple(
                InferenceMessage(
                    role=(
                        "user"
                        if section.section_type in {
                            "current_user_input","conversation_user_message"
                        }
                        else "assistant"
                        if section.section_type == "conversation_assistant_message"
                        else "system"
                    ),
                    content_parts=section.content_parts,
                    source_refs=section.source_refs,
                )
                for section in context_pack.sections
            ),
            context_pack_id=context_pack.context_pack_id,
            generation=GenerationSettings(
                max_output_tokens=context_pack.token_budget.reserved_output_tokens,
                temperature=0.4,
                top_p=1.0,
            ),
            constraints=InferenceConstraints(
                stream=True,
                timeout_ms=self.inference_timeout_ms,
                effective_data_policy=context_pack.effective_data_policy,
                allowed_execution_environments=allowed_environments,
            ),
            metadata={
                "constitution_version_id": context_pack.constitution_version_id,
                "identity_version_id": context_pack.identity_version_id,
                "values_version_id": context_pack.values_version_id,
                "builder_version": context_pack.builder_version,
                "router_version": route.router_version,
            },
        )

    async def _collect_stream(
        self,
        *,
        request: InferenceRequest,
        route: RouteDecision,
        provider_class: str,
        provider_version,
    ) -> InferenceResponse:
        expected_sequence = 0
        response_id: UUID | None = None
        pieces: list[str] = []
        terminal: InferenceStreamEvent | None = None
        saw_started = False
        async for event in self.provider.stream(request):
            if terminal is not None:
                raise RuntimeError("provider emitted data after a terminal stream event")
            if event.sequence_number != expected_sequence:
                raise RuntimeError("provider stream sequence is not contiguous")
            expected_sequence += 1
            if (
                event.inference_request_id != request.inference_request_id
                or event.request_id != request.request_id
                or event.trace_id != request.trace_id
            ):
                raise RuntimeError("provider stream lineage mismatch")
            if response_id is None:
                response_id = event.inference_response_id
            elif response_id != event.inference_response_id:
                raise RuntimeError("provider changed inference_response_id mid-stream")
            if event.event == "response_started":
                if saw_started or event.sequence_number != 0:
                    raise RuntimeError("provider stream has an invalid start event")
                saw_started = True
            elif not saw_started:
                raise RuntimeError("provider stream did not begin with response_started")
            elif event.event == "output_delta":
                assert event.delta is not None
                pieces.append(event.delta.text)
            elif event.event in {"response_completed", "response_failed"}:
                terminal = event
        if terminal is None:
            raise RuntimeError("provider stream ended without a terminal event")
        if terminal.event == "response_failed":
            assert terminal.failure is not None
            if (
                terminal.failure.provider_id != route.selected_provider_id
                or terminal.failure.provider_class != provider_class
            ):
                raise RuntimeError("provider failure lineage mismatch")
            raise ProviderInferenceError(terminal.failure)
        assert terminal.response is not None
        response = validate_inference_response_lineage(
            request=request,
            response=terminal.response,
            expected_provider_id=route.selected_provider_id,
            expected_provider_class=provider_class,
            expected_model_version_id=route.selected_model_version_id,
            expected_provider_adapter_version_id=(
                provider_version.provider_adapter_version_id
            ),
        )
        if (
            response.versions.tokenizer_version_id
            != provider_version.tokenizer_version_id
            or response.versions.serving_config_version
            != provider_version.serving_config_version
            or response.versions.serving_engine != provider_version.serving_engine
            or response.versions.serving_engine_version
            != provider_version.serving_engine_version
            or response.versions.model_artifact_hash
            != provider_version.model_artifact_hash
            or response.versions.runtime_attestation_id
            != provider_version.runtime_attestation_id
            or response.versions.runtime_attestation_hash
            != provider_version.runtime_attestation_hash
        ):
            raise RuntimeError("provider response version provenance mismatch")
        if "".join(pieces) != "".join(part.text for part in response.output_parts):
            raise RuntimeError("provider stream deltas do not match terminal output")
        return response

    @staticmethod
    def _validate_provider_version(provider_version, capabilities, route) -> None:
        if (
            provider_version.provider_id != capabilities.provider_id
            or provider_version.provider_class != capabilities.provider_class
            or provider_version.execution_environment
            != capabilities.execution_environment
            or provider_version.model_version_id
            not in capabilities.available_model_version_ids
            or provider_version.model_version_id
            != route.selected_model_version_id
        ):
            raise ProviderVersionError(
                code="provider_protocol_error",
                retryable=False,
                safe_message="The provider version does not match the selected route.",
            )

    @staticmethod
    def _typed_failure(
        error: Exception,
        *,
        inference_request: InferenceRequest,
        provider_id: str,
        provider_class: str,
    ):
        from mlsys.contracts import InferenceFailure

        if isinstance(error, ProviderInferenceError):
            failure = error.failure
            if (
                failure.inference_request_id == inference_request.inference_request_id
                and failure.request_id == inference_request.request_id
                and failure.trace_id == inference_request.trace_id
                and failure.provider_id == provider_id
                and failure.provider_class == provider_class
            ):
                return failure
            return InferenceFailure(
                inference_request_id=inference_request.inference_request_id,
                request_id=inference_request.request_id,
                trace_id=inference_request.trace_id,
                provider_id=provider_id,
                provider_class=provider_class,
                code="provider_protocol_error",
                retryable=False,
                safe_message="The provider returned failure metadata for a different request or route.",
            )
        if isinstance(error, ProviderVersionError):
            return InferenceFailure(
                inference_request_id=inference_request.inference_request_id,
                request_id=inference_request.request_id,
                trace_id=inference_request.trace_id,
                provider_id=provider_id,
                provider_class=provider_class,
                code=error.code,
                retryable=error.retryable,
                safe_message=error.safe_message,
            )
        if isinstance(error, InferenceTimeoutError):
            code = "provider_timeout"
            retryable = True
            safe_message = "The provider exceeded the enforced inference timeout."
        else:
            code = "internal_error"
            retryable = False
            safe_message = "The inference attempt failed before a response was delivered."
        return InferenceFailure(
            inference_request_id=inference_request.inference_request_id,
            request_id=inference_request.request_id,
            trace_id=inference_request.trace_id,
            provider_id=provider_id,
            provider_class=provider_class,
            code=code,
            retryable=retryable,
            safe_message=safe_message,
        )

    @staticmethod
    def _request_fingerprint(command: InteractionCommand) -> str:
        """Bind an idempotency key to every semantic ingress field.

        `traceparent` is transport correlation rather than request meaning and is
        intentionally excluded so a retry can arrive through a new parent span.
        An omitted session stays null in the fingerprint even though HAVRE creates
        a durable session ID for the first execution.
        """

        return content_hash(
            {
                "schema_version": 1,
                "message": command.message,
                "privacy_class": command.privacy_class.value,
                "memory_eligible": command.memory_eligible,
                "session_id": str(command.session_id) if command.session_id else None,
                "channel": command.channel,
                "language": command.language,
                "client_created_at": (
                    command.client_created_at.isoformat()
                    if command.client_created_at
                    else None
                ),
            }
        )

    @staticmethod
    def _result(
        *,
        user_event: EventEnvelope,
        assistant_event: EventEnvelope,
        context_pack: ContextPack,
        route: RouteDecision,
        response: InferenceResponse,
        traceparent: str,
        replay: bool,
    ) -> InteractionResult:
        return InteractionResult(
            request_id=user_event.request_id,
            trace_id=user_event.trace_id,
            traceparent=traceparent,
            session_id=user_event.session_id,
            user_event_id=user_event.event_id,
            assistant_event_id=assistant_event.event_id,
            context_pack_id=context_pack.context_pack_id,
            retrieval_result_id=context_pack.retrieval_result_id,
            inference_response_id=response.inference_response_id,
            route_decision_id=route.route_decision_id,
            content="\n".join(
                part.text for part in assistant_event.payload.content_parts
            ),
            provider_id=response.provider.provider_id,
            provider_class=response.provider.provider_class,
            model_version_id=response.versions.model_version_id,
            adapter_version_id=response.versions.adapter_version_id,
            provider_adapter_version_id=(
                response.versions.provider_adapter_version_id or "legacy-unknown"
            ),
            serving_engine=response.versions.serving_engine or "legacy-unknown",
            serving_engine_version=(
                response.versions.serving_engine_version or "legacy-unknown"
            ),
            model_artifact_hash=response.versions.model_artifact_hash,
            runtime_attestation_id=response.versions.runtime_attestation_id,
            runtime_attestation_hash=response.versions.runtime_attestation_hash,
            tokenizer_version_id=response.versions.tokenizer_version_id,
            serving_config_version=response.versions.serving_config_version,
            prompt_tokens=response.usage.prompt_tokens,
            output_tokens=response.usage.output_tokens,
            total_tokens=response.usage.total_tokens,
            token_count_source=response.usage.token_count_source,
            inference_total_ms=response.timing_ms.total,
            inference_ttft_ms=response.timing_ms.time_to_first_token,
            inference_generation_ms=response.timing_ms.generation,
            estimated_context_tokens=context_pack.estimated_total_tokens,
            effective_privacy_class=context_pack.effective_data_policy.privacy_class,
            cloud_eligible=context_pack.effective_data_policy.cloud_eligible,
            training_eligible=context_pack.effective_data_policy.training_eligible,
            idempotent_replay=replay,
        )

    @staticmethod
    def _history_evidence(context_pack: ContextPack) -> tuple[str, ...]:
        evidence_types = {
            "episodic_memory",
            "semantic_memory",
            "pattern_memory",
            "progress_memory",
            "conversation_user_message",
            "conversation_assistant_message",
        }
        return tuple(
            part.text
            for section in context_pack.sections
            if section.section_type in evidence_types
            for part in section.content_parts
        )

    @staticmethod
    def _result_from_evidence(evidence: dict[str, object]) -> InteractionResult:
        request = evidence["request"]
        events = evidence["events"]
        context = evidence["context_pack"]
        route = evidence["route_decision"]
        inference = evidence["inference"]
        user_event = next(event for event in events if event["event_type"] == "USER_MESSAGE")
        assistant_event = next(
            event for event in events if event["event_type"] == "ASSISTANT_MESSAGE"
        )
        content = "\n".join(
            part["text"] for part in assistant_event["payload"]["content_parts"]
        )
        root_span = next(
            (span for span in evidence["spans"] if span["name"] == "interaction.request"),
            None,
        )
        root_span_id = root_span["span_id"] if root_span else "0" * 15 + "1"
        traceparent = f"00-{request['trace_id']}-{root_span_id}-01"
        return InteractionResult(
            request_id=request["request_id"],
            trace_id=request["trace_id"],
            traceparent=traceparent,
            session_id=request["session_id"],
            user_event_id=user_event["event_id"],
            assistant_event_id=assistant_event["event_id"],
            context_pack_id=context["context_pack_id"],
            retrieval_result_id=context["retrieval_result_id"],
            inference_response_id=inference["inference_response_id"],
            route_decision_id=route["route_decision_id"],
            content=content,
            provider_id=inference["provider_id"],
            provider_class=inference["provider_class"],
            model_version_id=inference["model_version_id"],
            adapter_version_id=inference["adapter_version_id"],
            provider_adapter_version_id=inference["provider_adapter_version_id"],
            serving_engine=inference["serving_engine"],
            serving_engine_version=inference["serving_engine_version"],
            model_artifact_hash=inference["model_artifact_hash"],
            runtime_attestation_id=inference.get("runtime_attestation_id"),
            runtime_attestation_hash=inference.get("runtime_attestation_hash"),
            tokenizer_version_id=inference["tokenizer_version_id"],
            serving_config_version=inference["serving_config_version"],
            prompt_tokens=inference["usage"]["prompt_tokens"],
            output_tokens=inference["usage"]["output_tokens"],
            total_tokens=inference["usage"]["total_tokens"],
            token_count_source=inference["usage"]["token_count_source"],
            inference_total_ms=inference["timing_ms"]["total"],
            inference_ttft_ms=inference["timing_ms"].get("time_to_first_token"),
            inference_generation_ms=inference["timing_ms"].get("generation"),
            estimated_context_tokens=context["estimated_total_tokens"],
            effective_privacy_class=context["effective_privacy_class"],
            cloud_eligible=context["effective_cloud_eligible"],
            training_eligible=context["effective_training_eligible"],
            idempotent_replay=True,
        )
