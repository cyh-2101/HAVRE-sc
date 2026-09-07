"""Permanent Stage 1 request-to-delivered-event orchestration."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Callable, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from companion.context import (
    CONTEXT_PRESENTATION_VERSION,
    ContextBudgetExceeded,
    ContextBuilder,
    ContextPack,
    ResponsePlan,
    ResponsePlanner,
    parse_response_plan_json,
    render_inference_messages,
    ConversationHistoryItem,
    PersonalContextItem,
)
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
from companion.application.lifecycle import settle_cancelled_task
from companion.persistence.postgres import PostgresRepository
from companion.policy import CoreResponsePolicy, DataPolicy, PrivacyClass
from companion.policy.models import PRIVACY_RESTRICTION_ORDER
from companion.tracing import TraceContext
from mlsys.contracts import (
    GenerationSettings,
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
    PrivacyClassRouter,
    Stage1Router,
)
from companion.commitments import CommitmentFusionClaim
from companion.commitments.service import CommitmentBroker, commitment_data_policy
from mlsys.retrieval.models import (
    RetrievalFilters,
    RetrievalQuery,
    RetrievalRequest,
)
from mlsys.retrieval.service import RetrievalService

if TYPE_CHECKING:
    from companion.product.chat_goals import ExplicitChatGoalPlanner


logger = logging.getLogger(__name__)


class InteractionInProgress(RuntimeError):
    pass


class InteractionPreviouslyFailed(RuntimeError):
    pass


class IdempotencyConflict(RuntimeError):
    pass


class InferenceTimeoutError(TimeoutError):
    pass


class ManualStrongContext(BaseModel):
    """Exact, pre-audited selected context for one owner-triggered cloud rerun."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    disclosure_id: UUID
    source_assistant_event_id: UUID
    data_policy: DataPolicy
    personal_context: tuple[PersonalContextItem, ...]
    conversation_history: tuple[ConversationHistoryItem, ...] = Field(min_length=2)
    selected_content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    def model_post_init(self, __context: object) -> None:
        from mlsys.serving.deepseek_cloud import OWNER_MANUAL_AUTHORIZATION_REF

        if (
            self.data_policy.privacy_class is not PrivacyClass.HIGHLY_PRIVATE
            or not self.data_policy.cloud_eligible
            or self.data_policy.memory_eligible
            or self.data_policy.decision_source != "owner_explicit"
            or self.data_policy.authorization_ref != OWNER_MANUAL_AUTHORIZATION_REF
        ):
            raise ValueError("manual Strong context requires the exact derived policy")



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
    version = "interaction-orchestrator-v9"

    def __init__(
        self,
        *,
        owner_id: UUID,
        identity: IdentityBundle,
        repository: PostgresRepository,
        context_builder: ContextBuilder,
        router: Stage1Router | PrivacyClassRouter,
        provider: ModelProvider,
        providers: Mapping[str, ModelProvider] | None = None,
        context_builders: Mapping[str, ContextBuilder] | None = None,
        retrieval_service: RetrievalService | None = None,
        response_policy: CoreResponsePolicy | None = None,
        ambient_context_selector: Callable[..., tuple] | None = None,
        response_planner: ResponsePlanner | None = None,
        request_binder: Callable[[InferenceRequest], InferenceRequest] | None = None,
        request_binders: Mapping[
            str, Callable[[InferenceRequest], InferenceRequest]
        ] | None = None,
        inference_timeout_ms: int = 20_000,
        manual_strong_only: bool = False,
        commitment_broker: CommitmentBroker | None = None,
        chat_goal_planner: "ExplicitChatGoalPlanner | None" = None,
        conversation_continuation_service: object | None = None,
    ) -> None:
        if inference_timeout_ms <= 0:
            raise ValueError("inference_timeout_ms must be positive")
        self.owner_id = owner_id
        self.identity = identity
        self.repository = repository
        self.context_builder = context_builder
        self.router = router
        self.provider = provider
        self.providers = dict(providers or {provider.provider_id: provider})
        if provider.provider_id not in self.providers:
            raise ValueError("primary provider is missing from the provider registry")
        if any(
            provider_id != configured.provider_id
            for provider_id, configured in self.providers.items()
        ):
            raise ValueError("provider registry keys must match provider IDs")
        self.context_builders = {
            provider_id: context_builder for provider_id in self.providers
        }
        if context_builders is not None:
            unknown_builders = set(context_builders) - set(self.providers)
            if unknown_builders:
                raise ValueError("context builder configured for an unknown provider")
            self.context_builders.update(context_builders)
        if isinstance(router, PrivacyClassRouter):
            required_provider_ids = {
                router.cloud_provider_id,
                router.local_provider_id,
            }
            if not required_provider_ids.issubset(self.providers):
                raise ValueError("privacy router providers are missing from the registry")
        self.response_policy = response_policy or CoreResponsePolicy()
        self.ambient_context_selector = ambient_context_selector
        self.response_planner = response_planner or ResponsePlanner(
            semantic_memory=getattr(repository, "memory_encoder", None) is not None
        )
        self.request_binder = request_binder
        self.request_binders = dict(request_binders or {})
        if request_binder is not None:
            if provider.provider_id in self.request_binders:
                raise ValueError("primary provider request binder is configured twice")
            self.request_binders[provider.provider_id] = request_binder
        if set(self.request_binders) - set(self.providers):
            raise ValueError("request binder configured for an unknown provider")
        self.manual_strong_only = manual_strong_only
        self.commitment_broker = commitment_broker
        self.chat_goal_planner = chat_goal_planner
        self.conversation_continuation_service = conversation_continuation_service
        if manual_strong_only and self.request_binders:
            raise ValueError("manual Strong path cannot use the default request binder")
        if retrieval_service is None:
            embedding_provider = DeterministicEmbeddingProvider()
            repository.register_embedding_version(embedding_provider.version)
            retrieval_service = RetrievalService(
                repository=repository,
                embedding_provider=embedding_provider,
            )
        self.retrieval_service = retrieval_service
        self.inference_timeout_ms = inference_timeout_ms

    def _provider_id_for_policy(self, policy: DataPolicy) -> str:
        if isinstance(self.router, PrivacyClassRouter):
            return self.router.select_provider_id(policy=policy)
        return self.provider.provider_id

    async def interact(
        self,
        command: InteractionCommand,
        *,
        manual_strong_context: ManualStrongContext | None = None,
    ) -> InteractionResult:
        # HTTP frameworks use level cancellation: every await in an enclosing
        # cancelled scope can fail again. Own the transactional work in a child
        # and cancel it once, then drain its existing reconciliation completely.
        task = asyncio.create_task(self._interact_owned(
            command, manual_strong_context=manual_strong_context,
        ))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            task.cancel()
            await settle_cancelled_task(task)
            raise

    async def _interact_owned(
        self,
        command: InteractionCommand,
        *,
        manual_strong_context: ManualStrongContext | None = None,
    ) -> InteractionResult:
        request_id = uuid7()
        broker = self.commitment_broker if manual_strong_context is None else None
        fusion_claims: tuple[CommitmentFusionClaim, ...] = ()
        try:
            if broker is not None:
                activity_task = asyncio.create_task(asyncio.to_thread(
                    broker.begin_interaction_activity,
                    request_id=request_id,
                ))
                try:
                    await asyncio.shield(activity_task)
                except asyncio.CancelledError:
                    await settle_cancelled_task(activity_task)
                    raise
            return await self._interact_active(
                command,
                request_id=request_id,
                manual_strong_context=manual_strong_context,
            )
        finally:
            if broker is not None:
                await asyncio.to_thread(
                    broker.release_claims,
                    request_id=request_id,
                    reason="interaction_ended_without_fused_delivery",
                )
                await asyncio.to_thread(
                    broker.end_interaction_activity,
                    request_id=request_id,
                )

    async def _interact_active(
        self,
        command: InteractionCommand,
        *,
        request_id: UUID,
        manual_strong_context: ManualStrongContext | None = None,
    ) -> InteractionResult:
        manual = manual_strong_context
        if self.manual_strong_only != (manual is not None):
            raise ValueError("Local and manual Strong interaction paths cannot be mixed")
        if manual is not None:
            if command.message != "请用 Strong Brain 重新想想上一条回复。":
                raise ValueError("manual Strong interaction requires the canonical action")
            if not self.repository.manual_cloud_context_prepared(
                owner_id=self.owner_id,
                disclosure_id=manual.disclosure_id,
                source_assistant_event_id=manual.source_assistant_event_id,
                policy_revision_id=manual.data_policy.policy_revision_id,
                selected_source_refs=tuple(
                    ref for item in (*manual.personal_context, *manual.conversation_history)
                    for ref in item.source_refs
                ),
                selected_content_hash=manual.selected_content_hash,
            ):
                raise ValueError("manual Strong context does not match its prepared permit")
            from companion.product.strong import assert_manual_context_current
            await asyncio.to_thread(assert_manual_context_current, self.repository,
                owner_id=self.owner_id, source_assistant_event_id=manual.source_assistant_event_id)
        request_fingerprint = self._request_fingerprint(command, manual)
        session_id = command.session_id or uuid7()
        trace = TraceContext.from_traceparent(command.traceparent)
        trace_started_at = datetime.now(UTC)
        policy = (
            manual.data_policy
            if manual is not None
            else DataPolicy.owner_default(
                command.privacy_class,
                memory_eligible=command.memory_eligible,
            )
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
        fusion_claims: tuple[CommitmentFusionClaim, ...] = ()
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
                    "privacy_class": policy.privacy_class.value,
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
                    completion_resolution = None
                    if self.commitment_broker is not None and manual is None:
                        completion_resolution = await asyncio.to_thread(
                            self.commitment_broker.resolve_completion,
                            user_event_id=user_event.event_id,
                            session_id=session_id,
                            message=command.message,
                        )
                    chat_goal_context = None
                    if self.chat_goal_planner is not None and manual is None:
                        chat_goal_context = await self.chat_goal_planner.apply(
                            user_event=user_event, message=command.message
                        )
                    with trace.span(
                        "user_model.select_context",
                        parent_span_id=root_span_id,
                        attributes={
                            "selector_version": "stage4-personal-context-selector-v1",
                        },
                    ):
                        if manual is not None:
                            personal_context = manual.personal_context
                            conversation_history = manual.conversation_history
                        else:
                            personal_context = await asyncio.to_thread(
                                self.repository.select_personal_context,
                                owner_id=self.owner_id,
                                query_text=command.message,
                                maximum_privacy_class=policy.privacy_class,
                                as_of=user_event.recorded_at,
                            )
                            commitment_context = ()
                            if self.commitment_broker is not None:
                                commitment_context = await asyncio.to_thread(
                                    self.commitment_broker.select_context,
                                    query_text=command.message,
                                    maximum_privacy_class=policy.privacy_class,
                                )
                            personal_context = (*personal_context, *commitment_context)
                            if chat_goal_context is not None:
                                personal_context = (*personal_context, chat_goal_context)
                            if completion_resolution is not None and completion_resolution.status == "completed":
                                personal_context = (*personal_context, PersonalContextItem(
                                    owner_id=self.owner_id,
                                    section_id=f"completion-receipt-{request_id}",
                                    section_type="owner_response_instruction",
                                    content_text=(
                                        "Committed action receipt: the uniquely identified task in this "
                                        "owner message is now completed; its pending reminders were "
                                        "cancelled atomically. Acknowledge naturally without inventing "
                                        "other saved actions or exposing internal identifiers."
                                    ),
                                    priority=99,
                                    source_refs=(
                                        f"event/{user_event.event_id}",
                                        f"goal/{completion_resolution.goal_id}@{completion_resolution.goal_revision}",
                                    ),
                                    data_policy=policy,
                                ))
                            if (
                                completion_resolution is not None
                                and completion_resolution.status == "ambiguous"
                                and completion_resolution.clarification_text
                            ):
                                clarification_policy = commitment_data_policy()
                                personal_context = (*personal_context, PersonalContextItem(
                                    owner_id=self.owner_id,
                                    section_id=f"completion-clarification-{request_id}",
                                    section_type="owner_response_instruction",
                                    content_text=(
                                        "Ask exactly this one minimal clarification and do not "
                                        "claim any Goal was updated: "
                                        + completion_resolution.clarification_text
                                    ),
                                    priority=99,
                                    source_refs=(f"event/{user_event.event_id}",),
                                    data_policy=clarification_policy,
                                ))
                            if self.commitment_broker is not None:
                                fusion_claims = await asyncio.to_thread(
                                    self.commitment_broker.claim_due_for_interaction,
                                    request_id=request_id,
                                    query_text=command.message,
                                )
                                personal_context = (
                                    *personal_context,
                                    *self.commitment_broker.fusion_context(fusion_claims),
                                )
                            if self.ambient_context_selector is not None:
                                ambient_context = await asyncio.to_thread(
                                    self.ambient_context_selector,
                                    query_text=command.message,
                                    maximum_privacy_class=policy.privacy_class,
                                )
                                personal_context = (*personal_context, *ambient_context)
                            conversation_history = await asyncio.to_thread(
                                self.repository.select_conversation_history,
                                owner_id=self.owner_id,
                                session_id=session_id,
                                exclude_event_id=user_event.event_id,
                                as_of=user_event.recorded_at,
                                maximum_privacy_class=policy.privacy_class,
                                include_cross_session_fallback=(
                                    self.response_planner.refers_to_prior_context(
                                        command.message
                                    )
                                ),
                                continuous_chat=command.channel == "web",
                            )
                            if getattr(self.repository, "memory_encoder", None) is not None:
                                from companion.context.recall import recalled_history
                                conversation_history = await asyncio.to_thread(
                                    recalled_history, self.repository,
                                    owner_id=self.owner_id, query=command.message,
                                    current_event=user_event, recent=conversation_history,
                                    explicit=self.response_planner.refers_to_prior_context(command.message),
                                    timezone_name=self.context_builder.owner_timezone or "America/Chicago",
                                )
                    planning_message = command.message
                    planning_source_refs = (f"event/{user_event.event_id}",)
                    if manual is not None:
                        source_user_turn = next(
                            (
                                item for item in reversed(conversation_history)
                                if item.role == "user"
                            ),
                            None,
                        )
                        if source_user_turn is not None:
                            planning_message = source_user_turn.content_text
                            planning_source_refs = source_user_turn.source_refs
                    with trace.span(
                        "response.plan",
                        parent_span_id=root_span_id,
                        attributes={"planner_version": self.response_planner.version},
                    ):
                        response_plan = self.response_planner.plan(
                            request_id=request_id,
                            trace_id=trace.trace_id,
                            owner_id=self.owner_id,
                            message=planning_message,
                            source_refs=planning_source_refs,
                            conversation_history=conversation_history,
                            personal_context=personal_context,
                        )
                    with trace.span(
                        "memory.retrieve",
                        parent_span_id=root_span_id,
                        attributes={
                            "algorithm_version": self.retrieval_service.default_algorithm,
                            "candidate_k": 100,
                            "top_k": 5,
                            "memory_need": response_plan.memory_need,
                            "retrieval_executed": (
                                manual is None and response_plan.memory_need != "none"
                            ),
                        },
                    ):
                        allowed_privacy = tuple(
                            item
                            for item in PrivacyClass
                            if PRIVACY_RESTRICTION_ORDER[item]
                            <= PRIVACY_RESTRICTION_ORDER[policy.privacy_class]
                        )
                        retrieval_method = (
                            self.retrieval_service.retrieve_empty
                            if manual is not None or response_plan.memory_need == "none"
                            else self.retrieval_service.retrieve
                        )
                        retrieval_result = await asyncio.to_thread(
                            retrieval_method,
                            RetrievalRequest(
                                algorithm_version=self.retrieval_service.default_algorithm,
                                trace_id=trace.trace_id,
                                owner_id=self.owner_id,
                                request_id=request_id,
                                query=RetrievalQuery(
                                    text=(response_plan.memory_query or command.message),
                                    language=command.language,
                                    event_id=user_event.event_id,
                                ),
                                filters=RetrievalFilters(
                                    allowed_privacy_classes=allowed_privacy
                                ),
                            ),
                        )
                    if manual is None:
                        # Manual Strong uses only its exact prepared disclosure;
                        # a later owner edit cannot authorize an additional source.
                        from companion.context.corrections import owner_fact_corrections
                        correction_context = await asyncio.to_thread(
                            owner_fact_corrections, self.repository,
                            owner_id=self.owner_id, current_event=user_event,
                            history=conversation_history, retrieval_result=retrieval_result,
                        )
                        personal_context = (*personal_context, *correction_context)
                    selected_provider_id = self._provider_id_for_policy(policy)
                    selected_provider = self.providers[selected_provider_id]
                    selected_context_builder = self.context_builders[
                        selected_provider_id
                    ]
                    with trace.span(
                        "context.build",
                        parent_span_id=root_span_id,
                        attributes={
                            "builder_version": selected_context_builder.version,
                            "initial_provider_id": selected_provider_id,
                            "constitution_version_id": self.identity.constitution.version_id,
                            "identity_version_id": self.identity.identity.version_id,
                            "values_version_id": self.identity.values.version_id,
                        },
                    ):
                        context_pack = selected_context_builder.build(
                            request_id=request_id,
                            trace_id=trace.trace_id,
                            owner_id=self.owner_id,
                            identity=self.identity,
                            user_event=user_event,
                            retrieval_result=retrieval_result,
                            personal_context=personal_context,
                            conversation_history=conversation_history,
                            response_plan=response_plan,
                        )
                        effective_provider_id = self._provider_id_for_policy(
                            context_pack.effective_data_policy
                        )
                        if effective_provider_id != selected_provider_id:
                            # The selected sections established the effective
                            # policy. Preserve them while applying the stricter
                            # provider budget so a restrictive item cannot be
                            # dropped and make routing oscillate back to cloud.
                            pre_route_context = context_pack
                            failure_stage = "routing"
                            selected_provider_id = effective_provider_id
                            selected_provider = self.providers[selected_provider_id]
                            selected_context_builder = self.context_builders[
                                selected_provider_id
                            ]
                            context_pack = (
                                selected_context_builder.rebind_selected_sections(
                                    context_pack
                                )
                            )
                            if (
                                self._provider_id_for_policy(
                                    context_pack.effective_data_policy
                                )
                                != selected_provider_id
                            ):
                                raise ProviderPolicyError(
                                    "effective privacy route did not converge"
                                )

                    pre_route_context = context_pack
                    failure_stage = "capability_check"
                    capabilities = await selected_provider.capabilities()
                    failure_stage = "routing"
                    with trace.span(
                        "inference.route",
                        parent_span_id=root_span_id,
                        attributes={
                            "router_version": self.router.version,
                            "candidate_count": len(self.providers),
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
                    if manual is not None:
                        from mlsys.serving.deepseek_cloud import (
                            OWNER_MANUAL_AUTHORIZATION_REF,
                            OWNER_MANUAL_BOUNDARY,
                        )

                        inference_request = inference_request.model_copy(
                            update={
                                "metadata": {
                                    **inference_request.metadata,
                                    "cloud_authorization_ref": (
                                        OWNER_MANUAL_AUTHORIZATION_REF
                                    ),
                                    "cloud_data_boundary": OWNER_MANUAL_BOUNDARY,
                                    "cloud_disclosure_id": str(manual.disclosure_id),
                                    "selected_content_hash": manual.selected_content_hash,
                                }
                            }
                        )
                    failure_stage = "version_check"
                    provider_version = await selected_provider.version()
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
                        if manual is not None:
                            from mlsys.serving.deepseek_cloud import (
                                bind_cloud_experiment_request,
                            )

                            inference_request = bind_cloud_experiment_request(
                                inference_request,
                                thinking="enabled",
                                reasoning_effort="high",
                            )
                            await asyncio.to_thread(assert_manual_context_current, self.repository,
                                owner_id=self.owner_id, source_assistant_event_id=manual.source_assistant_event_id)
                            await asyncio.to_thread(
                                self.repository.bind_manual_cloud_disclosure,
                                owner_id=self.owner_id,
                                disclosure_id=manual.disclosure_id,
                                inference_request=inference_request,
                            )
                        else:
                            request_binder = self.request_binders.get(
                                route.selected_provider_id
                            )
                            if request_binder is not None:
                                inference_request = request_binder(inference_request)
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
                                    provider=selected_provider,
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
                                inference_request=inference_request,
                                inference_response=inference_response,
                                provider_version=provider_version,
                                assistant_event=assistant_event,
                                spans=list(trace.spans),
                                fusion_claims=fusion_claims,
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
                    if (
                        manual is None
                        and self.conversation_continuation_service is not None
                        and isinstance(response_plan, ResponsePlan)
                    ):
                        try:
                            await asyncio.to_thread(
                                self.conversation_continuation_service.record_candidate,
                                user_event=user_event,
                                assistant_event=assistant_event,
                                response_plan=response_plan,
                                user_message=command.message,
                                assistant_message="\n".join(policy_result.output_parts),
                                selected_provider_id=route.selected_provider_id,
                                execution_environment=route.execution_environment,
                            )
                        except Exception as continuation_error:
                            logger.warning(
                                "continuation_candidate_record_failed request_id=%s "
                                "error_type=%s",
                                request_id,
                                type(continuation_error).__name__,
                            )
                    if manual is not None:
                        disclosure_task = asyncio.create_task(asyncio.to_thread(
                            self.repository.finish_manual_cloud_disclosure,
                            owner_id=self.owner_id,
                            disclosure_id=manual.disclosure_id,
                            result_assistant_event_id=assistant_event.event_id,
                        ))
                        try:
                            await asyncio.shield(disclosure_task)
                        except asyncio.CancelledError as error:
                            # A delivered assistant Event and its outbound disclosure
                            # must reach the same terminal truth before cancellation.
                            await disclosure_task
                            raise error
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
                            fusion_claims=fusion_claims,
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
                            fusion_claims=fusion_claims,
                        )
                elif pre_route_context is not None:
                    if isinstance(failure, ContextBudgetExceeded):
                        pre_route_code = "context_limit_exceeded"
                        pre_route_retryable = False
                        pre_route_message = (
                            "The selected local provider cannot fit the already "
                            "selected privacy-preserving context."
                        )
                    elif failure_stage == "capability_check":
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
                        fusion_claims=fusion_claims,
                    )
                elif isinstance(failure, ContextBudgetExceeded):
                    failure_event = EventEnvelope(
                        event_type=EventType.INTERACTION_FAILED,
                        owner_id=self.owner_id,
                        session_id=session_id,
                        request_id=request_id,
                        trace_id=trace.trace_id,
                        causation_event_id=user_event.event_id,
                        data_policy=policy,
                        payload=InteractionFailurePayload(
                            failure_stage="context_build",
                            context_pack_id=None,
                            failure_code="context_limit_exceeded",
                            retryable=False,
                            safe_message=(
                                "The selected provider cannot fit the required "
                                "conversation context."
                            ),
                        ),
                    )
                    await asyncio.to_thread(
                        self.repository.fail_pre_context_interaction,
                        owner_id=self.owner_id,
                        failure_event=failure_event,
                        error_code="context_limit_exceeded",
                        spans=list(trace.spans),
                        fusion_claims=fusion_claims,
                    )
                else:
                    # The USER_MESSAGE reservation is already durable, but no
                    # valid ContextPack exists yet.  Keep that terminal truth
                    # typed and content-free instead of leaving a bare failed
                    # request that cannot be reconciled to a failure Event.
                    pre_context_code = (
                        "interaction_cancelled"
                        if cancellation is not None
                        else "internal_error"
                    )
                    pre_context_retryable = cancellation is not None
                    pre_context_message = (
                        "The interaction ended before its conversation context "
                        "was built."
                        if cancellation is not None
                        else "The interaction failed before its conversation "
                        "context was built."
                    )
                    failure_event = EventEnvelope(
                        event_type=EventType.INTERACTION_FAILED,
                        owner_id=self.owner_id,
                        session_id=session_id,
                        request_id=request_id,
                        trace_id=trace.trace_id,
                        causation_event_id=user_event.event_id,
                        data_policy=policy,
                        payload=InteractionFailurePayload(
                            failure_stage="context_build",
                            context_pack_id=None,
                            failure_code=pre_context_code,
                            retryable=pre_context_retryable,
                            safe_message=pre_context_message,
                        ),
                    )
                    try:
                        await asyncio.to_thread(
                            self.repository.fail_pre_context_interaction,
                            owner_id=self.owner_id,
                            failure_event=failure_event,
                            error_code=pre_context_code,
                            spans=list(trace.spans),
                            fusion_claims=fusion_claims,
                        )
                    except Exception as reconciliation_error:
                        # A secondary persistence failure must not disguise the
                        # original application error or client cancellation.
                        logger.error(
                            "pre_context_failure_reconciliation_failed "
                            "request_id=%s error_type=%s",
                            request_id,
                            type(reconciliation_error).__name__,
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
        response_plan_sections = tuple(
            section
            for section in context_pack.sections
            if section.section_type == "response_plan"
        )
        response_plan = (
            None
            if not response_plan_sections
            else parse_response_plan_json(
                response_plan_sections[0].content_parts[0].text
            )
        )
        allowed_environments: tuple[Literal["local", "cloud"], ...] = (
            (route.execution_environment,)
        )
        return InferenceRequest(
            request_id=request_id,
            trace_id=trace.trace_id,
            messages=render_inference_messages(context_pack),
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
                "context_presentation_version": CONTEXT_PRESENTATION_VERSION,
                **(
                    {}
                    if response_plan is None
                    else {
                        "response_planner_version": response_plan.planner_version,
                        "response_plan_hash": response_plan.content_hash,
                        "response_plan_mode": response_plan.mode,
                        "response_plan_depth": response_plan.depth,
                        "response_plan_memory_need": response_plan.memory_need,
                    }
                ),
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
        provider: ModelProvider,
    ) -> InferenceResponse:
        expected_sequence = 0
        response_id: UUID | None = None
        pieces: list[str] = []
        terminal: InferenceStreamEvent | None = None
        saw_started = False
        async for event in provider.stream(request):
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
            expected_adapter_version_id=(
                provider_version.active_adapter_version_id
            ),
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
    def _request_fingerprint(
        command: InteractionCommand,
        manual_strong_context: ManualStrongContext | None = None,
    ) -> str:
        """Bind an idempotency key to every semantic ingress field.

        `traceparent` is transport correlation rather than request meaning and is
        intentionally excluded so a retry can arrive through a new parent span.
        An omitted session stays null in the fingerprint even though HAVRE creates
        a durable session ID for the first execution.
        """

        material = {
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
        if manual_strong_context is not None:
            material["manual_strong_disclosure_id"] = str(
                manual_strong_context.disclosure_id
            )
            material["manual_strong_selected_content_hash"] = (
                manual_strong_context.selected_content_hash
            )
        return content_hash(material)

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
