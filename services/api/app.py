"""FastAPI ingress for the active HAVRE Stage 10 slice."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
import asyncio
import json
import logging
import re
import secrets
from zoneinfo import ZoneInfo
from typing import Annotated, Literal
from urllib.parse import parse_qs
from uuid import UUID, uuid5

import anyio
from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from companion import __version__
from companion.application.lifecycle import INTERACTION_DEADLINE_SECONDS, settle_cancelled_task
from services.api.interaction_tasks import InteractionTasks
from companion.evidence import EvidenceRef
from companion.ids import uuid7
from companion.mobile import MobileEnrollmentReceipt
from companion.memory.extractor import is_memory_candidate_worthy
from companion.life_context import (
    ContextIngestResult,
    ContextCollectionPermit,
    ContextCollectionPermitRequest,
    ContextObservationDraft,
    ContextSourceHealthDraft,
    ContextSourceHealthV2,
    ContextSourceStateRevision,
)
from companion.persistence import ContextIdempotencyConflict, ContextIngestRejected
from companion.goals.models import (
    GOAL_FIELD_UNSET,
    GoalPriority,
    GoalStatus,
    GoalTrack,
)
from companion.application import (
    IdempotencyConflict,
    InteractionCommand,
    InteractionInProgress,
    InferenceTimeoutError,
    InteractionPreviouslyFailed,
    InteractionResult,
)
from companion.commitments.service import COMMITMENT_AUTHORIZATION_REF
from companion.context import ContextBudgetExceeded
from companion.policy import DataPolicy, PrivacyClass
from companion.policy.intervention import (
    AvoidanceAssessment,
    CoercionAssessment,
    DangerAssessment,
    EnergyAssessment,
    GoalAlignment,
    GoalUrgency,
    SceneSignalType,
)
from companion.scenes.models import (
    AnticipatedTrigger,
    OutcomeHelpfulness,
    OutcomeTriState,
    SceneGoal,
    SceneSituation,
)
from companion.feedback import (
    FeedbackIssueAttribution,
    FeedbackRating,
    FeedbackReasonCode,
    FeedbackReviewDecision,
)
from companion.proactive import (
    PreviewPolicy,
    ProactivePreferenceRevision,
    ProactiveWorkCommand,
)
from companion.proactive.models import QuietHours
from companion.user_model.models import BeliefTransitionType, BeliefType
from mlsys.contracts import ProviderVersion
from mlsys.serving import (
    ProviderInferenceError,
    ProviderPolicyError,
    ProviderVersionError,
)
from services.api.runtime import Runtime, build_runtime
from services.api.settings import Settings
from services.api.metrics import OperationalMetrics
from services.api.release_binding import require_provider_version_binding


class InteractionBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    message: str = Field(min_length=1, max_length=100_000)
    privacy_class: PrivacyClass = PrivacyClass.NORMAL
    memory_eligible: bool = True
    session_id: UUID | None = None
    language: str | None = Field(default=None, max_length=35)
    client_created_at: datetime | None = None


CONTEXT_LIMIT_SAFE_MESSAGE = (
    "The selected reply route cannot fit the required conversation context."
)


class FeedbackBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    assistant_event_id: UUID
    rating: FeedbackRating
    reason_codes: tuple[FeedbackReasonCode, ...] = ()
    reason_text: str | None = Field(default=None, max_length=2_000)
    owner_revision_text: str | None = Field(default=None, max_length=100_000)
    expected_revision: int | None = Field(default=None, ge=0)


class FeedbackReviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    feedback_revision: int = Field(gt=0)
    decision: FeedbackReviewDecision
    issue_attributions: tuple[FeedbackIssueAttribution, ...] = Field(min_length=1)
    review_notes: str | None = Field(default=None, max_length=4_000)
    authorization_ref: str | None = Field(default=None, max_length=500)


class CommunicationPreferenceBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    response_length: Literal["brief", "balanced", "detailed"]
    reason: str = Field(min_length=1, max_length=1_000)


class EpisodeCloseBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    boundary_reason: Literal[
        "owner_started_new_conversation", "owner_closed", "idle_boundary"
    ] = "owner_closed"


class EpisodeSuggestionReviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    decision: Literal["accepted", "rejected"]
    reason: str = Field(min_length=1, max_length=2_000)


class PairingClaimBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    pairing_id: UUID
    code: str = Field(pattern=r"^\d{8}$")
    display_name: str = Field(min_length=1, max_length=120)
    device_kind: Literal["windows", "iphone", "browser", "other"]


class TimelineReadBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    event_id: UUID


class PushSubscriptionBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    endpoint: str = Field(min_length=12, max_length=4096)
    p256dh: str = Field(min_length=16, max_length=512)
    auth: str = Field(min_length=8, max_length=256)
    preview_level: Literal["private", "detailed"] = "private"
    expires_at: datetime | None = None


class RealDeviceValidationBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    delivery_locator: UUID
    device_id: UUID
    pwa_shell_version: str = Field(pattern=r"^havre-shell-v[0-9]+$")
    owner_confirmation_ref: str = Field(min_length=1, max_length=500)


class CalendarToggleBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    enabled: bool


class ReachOutSettingsBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    enabled: bool
    reminders_enabled: bool | None = None
    friendly_check_ins_enabled: bool | None = None
    cooldown_seconds: int | None = Field(default=None, ge=60, le=2_592_000)
    quiet_start: time | None = None
    quiet_end: time | None = None

    @property
    def quiet_hours_complete(self) -> bool:
        return self.quiet_start is not None and self.quiet_end is not None


class ReviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    reason: str = Field(min_length=1, max_length=1000)


class AcceptReviewBody(ReviewBody):
    importance: float | None = Field(default=None, ge=0, le=1)
    content_text: str | None = Field(default=None, min_length=1, max_length=100_000)


class CorrectMemoryBody(ReviewBody):
    content_text: str = Field(min_length=1, max_length=100_000)


class MemoryBeliefProposalBody(ReviewBody):
    statement: str = Field(min_length=1, max_length=10_000)
    belief_type: BeliefType
    confidence: float = Field(default=0.7, ge=0, le=1)


class BeliefProposalBody(ReviewBody):
    belief_key: str = Field(min_length=1, max_length=240)
    statement: str = Field(min_length=1, max_length=10_000)
    belief_type: BeliefType
    confidence: float = Field(ge=0, le=1)
    evidence: tuple[EvidenceRef, ...] = Field(min_length=1)
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class BeliefRevisionBody(ReviewBody):
    expected_revision: int = Field(gt=0)
    statement: str = Field(min_length=1, max_length=10_000)
    confidence: float = Field(ge=0, le=1)
    evidence: tuple[EvidenceRef, ...] = Field(min_length=1)
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class BeliefTransitionBody(ReviewBody):
    revision: int = Field(gt=0)
    transition_type: BeliefTransitionType
    occurred_at: datetime | None = None
    evidence: tuple[EvidenceRef, ...] = ()


class ConsolidationProposalBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    memory_class: str = Field(pattern=r"^(semantic|pattern|progress)$")
    content_text: str = Field(min_length=1, max_length=100_000)
    evidence: tuple[EvidenceRef, ...] = Field(min_length=1)
    detector_version: str = Field(min_length=1, max_length=200)
    importance: float = Field(default=0.5, ge=0, le=1)


class ConsolidationAcceptBody(ReviewBody):
    confidence: float = Field(ge=0, le=1)
    importance: float | None = Field(default=None, ge=0, le=1)
    corrected_content_text: str | None = Field(default=None, min_length=1, max_length=100_000)


class CurrentStateBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: str = Field(min_length=1, max_length=2_000)
    state: dict[str, object]
    uncertainty: float = Field(ge=0, le=1)
    estimated_at: datetime
    expires_at: datetime
    evidence: tuple[EvidenceRef, ...] = Field(min_length=1)


class GoalCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    track: GoalTrack
    title: str = Field(min_length=1, max_length=500)
    why: str = Field(min_length=1, max_length=2_000)
    source_event_id: UUID
    priority: GoalPriority = GoalPriority.NORMAL
    next_action: str | None = Field(default=None, max_length=2_000)
    review_at: datetime | None = None


class GoalUpdateBody(ReviewBody):
    expected_revision: int = Field(gt=0)
    title: str | None = Field(default=None, min_length=1, max_length=500)
    why: str | None = Field(default=None, min_length=1, max_length=2_000)
    priority: GoalPriority | None = None
    status: GoalStatus | None = None
    next_action: str | None = Field(default=None, max_length=2_000)
    review_at: datetime | None = None


class GoalProgressBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    expected_goal_revision: int = Field(gt=0)
    direction: str = Field(pattern=r"^(toward|steady|away|unknown)$")
    summary: str = Field(min_length=1, max_length=2_000)
    observed_at: datetime
    evidence: tuple[EvidenceRef, ...] = Field(min_length=1)


class GoalReminderBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    reminder_kind: Literal["start_window", "check_in", "encouragement"]
    reminder_text: str = Field(min_length=1, max_length=500)
    remind_at: datetime
    expires_at: datetime
    supersede_existing_slot: bool = False


class CommitmentAuthorizationBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    authorization_ref: Literal[
        "product-owner-decision:2026-09-03:course-commitment-field-projection-v1"
    ] = COMMITMENT_AUTHORIZATION_REF


class CommitmentProjectionBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    entry_id: str = Field(min_length=1,max_length=240)
    course_name: str = Field(min_length=1,max_length=160)
    task_name: str = Field(min_length=1,max_length=500)
    deadline_at: datetime | None = None


class CourseReminderSupersessionBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    replacement_generation: Literal["v2"] = "v2"


class SceneCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scene_type: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    situation: SceneSituation
    planned_goal: SceneGoal
    anticipated_triggers: tuple[AnticipatedTrigger, ...] = ()
    danger: DangerAssessment = DangerAssessment.UNCERTAIN
    avoidance: AvoidanceAssessment = AvoidanceAssessment.UNKNOWN
    energy: EnergyAssessment = EnergyAssessment.UNKNOWN
    coercion: CoercionAssessment = CoercionAssessment.UNCERTAIN
    goal_alignment: GoalAlignment = GoalAlignment.UNCLEAR
    goal_urgency: GoalUrgency = GoalUrgency.UNKNOWN
    privacy_class: PrivacyClass = PrivacyClass.PRIVATE
    memory_eligible: bool = True
    planned_start_at: datetime | None = None
    session_id: UUID | None = None


class SceneTransitionBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    expected_revision: int = Field(gt=0)
    action: Literal["start", "pause", "resume", "after", "close"]
    reason: str = Field(min_length=1, max_length=2_000)
    terminal_status: Literal["completed", "abandoned", "cancelled"] | None = None


class SceneSignalBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    expected_revision: int = Field(gt=0)
    signal_type: SceneSignalType
    danger: DangerAssessment
    avoidance: AvoidanceAssessment
    energy: EnergyAssessment
    coercion: CoercionAssessment
    goal_alignment: GoalAlignment
    goal_urgency: GoalUrgency
    privacy_class: PrivacyClass = PrivacyClass.PRIVATE
    memory_eligible: bool = False
    occurred_at: datetime
    uncertainty_note: str | None = Field(default=None, max_length=1_000)


class SceneActionBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    expected_revision: int = Field(gt=0)
    action: str = Field(min_length=1, max_length=2_000)
    action_attempted: OutcomeTriState
    occurred_at: datetime
    privacy_class: PrivacyClass = PrivacyClass.PRIVATE
    memory_eligible: bool = True
    uncertainty_note: str | None = Field(default=None, max_length=1_000)


class SceneOutcomeBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    expected_revision: int = Field(gt=0)
    outcome: str = Field(min_length=1, max_length=4_000)
    occurred_at: datetime
    privacy_class: PrivacyClass = PrivacyClass.PRIVATE
    memory_eligible: bool = True
    uncertainty_note: str | None = Field(default=None, max_length=1_000)


class SceneReflectionBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    expected_revision: int = Field(gt=0)
    reflection: str = Field(min_length=1, max_length=4_000)
    next_adjustment: str | None = Field(default=None, max_length=2_000)
    planned_scene_status: Literal[
        "completed", "partial", "abandoned", "cancelled", "unknown"
    ]
    helpfulness: OutcomeHelpfulness = OutcomeHelpfulness.NOT_ASKED
    too_passive: OutcomeTriState = OutcomeTriState.UNKNOWN
    too_forceful: OutcomeTriState = OutcomeTriState.UNKNOWN
    later_regret: Literal["yes", "no", "unsure", "not_asked"] = "not_asked"
    privacy_class: PrivacyClass = PrivacyClass.PRIVATE
    memory_eligible: bool = True
    consented: Literal[True]


class ProactivePreferenceBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    revision: int = Field(gt=0)
    global_enabled: bool = False
    category_permissions: dict[
        str, Literal["allowed", "denied", "confirmation_required"]
    ] = Field(default_factory=dict)
    allowed_channels: tuple[Literal["web_inbox"], ...] = ()
    preview_policy: PreviewPolicy = PreviewPolicy.NONE
    global_budget_per_24h: int | None = Field(default=None, gt=0, le=24)
    category_budget_per_24h: dict[str, int] = Field(default_factory=dict)
    cooldown_seconds: int | None = Field(default=None, ge=60, le=2_592_000)
    generic_push_for_local_only: bool = False
    stopped_subject_refs: tuple[str, ...] = ()
    authorization_ref: str | None = Field(default=None, max_length=500)
    simulation_only: Literal[True]


class ProactiveSimulationBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    trigger_type: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    source_kind: Literal[
        "scheduled_time", "goal", "scene_session", "owner_reminder",
        "belief_confirmation", "system_operational", "synthetic_life_context",
    ]
    source_refs: tuple[str, ...] = Field(min_length=1)
    subject_refs: tuple[str, ...] = ()
    category: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    reason_code: str = Field(pattern=r"^[a-z][a-z0-9_]{1,95}$")
    reason_summary: str = Field(min_length=1, max_length=1000)
    intended_benefit: str = Field(min_length=1, max_length=1000)
    privacy_class: PrivacyClass = PrivacyClass.LOCAL_ONLY
    memory_eligible: bool = False
    preference_revision: int = Field(gt=0)
    observed_at: datetime
    earliest_eligible_at: datetime
    expires_at: datetime
    deduplication_key: str = Field(min_length=1, max_length=240)
    simulation_only: Literal[True]


class ProactiveWorkBody(ProactiveSimulationBody):
    work_kind: Literal["scheduled", "event_driven"]
    not_before: datetime


class ProactiveOwnerActionBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action_type: Literal[
        "responded", "dismissed", "snoozed", "non_response", "stopped"
    ]
    reason: str = Field(min_length=1, max_length=1000)
    observed_at: datetime
    response_event_id: UUID | None = None
    snooze_until: datetime | None = None


class OfflineJobBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    job_type: Literal["daily_reflection", "periodic_consolidation"]
    window_start: datetime
    window_end: datetime


class MemoryLifecycleReviewBody(ReviewBody):
    decision: Literal["accepted", "rejected"]


def _reply_route_label(version: ProviderVersion) -> str:
    model_id = version.model_version_id
    normalized = model_id.lower()
    if version.provider_id == "openai-codex-chatgpt":
        return "GPT-5.6-sol"
    if "qwen3-8b" in normalized:
        if version.active_adapter_version_id is None:
            return "Qwen3-8B Base"
        return f"Qwen3-8B · {version.active_adapter_version_id}"
    return model_id


def _reply_routes_settings(
    *,
    provider_version: ProviderVersion,
    local_version: ProviderVersion | None,
) -> dict[str, object]:
    local_available = (
        local_version is not None
        and local_version.execution_environment == "local"
    )
    default_privacy_classes = (
        tuple(value.value for value in PrivacyClass)
        if provider_version.execution_environment == "local"
        else (PrivacyClass.PUBLIC.value, PrivacyClass.NORMAL.value)
    )
    local_route = None
    if local_available:
        assert local_version is not None
        local_route = {
            "available": True,
            "privacy_classes": (
                PrivacyClass.PRIVATE.value,
                PrivacyClass.HIGHLY_PRIVATE.value,
                PrivacyClass.LOCAL_ONLY.value,
            ),
            "provider_id": local_version.provider_id,
            "model_version_id": local_version.model_version_id,
            "execution_environment": local_version.execution_environment,
            "adapter_version_id": local_version.active_adapter_version_id,
            "label": _reply_route_label(local_version),
        }
    return {
        "default": {
            "available": True,
            "privacy_classes": default_privacy_classes,
            "provider_id": provider_version.provider_id,
            "model_version_id": provider_version.model_version_id,
            "execution_environment": provider_version.execution_environment,
            "adapter_version_id": provider_version.active_adapter_version_id,
            "label": _reply_route_label(provider_version),
        },
        "local_only_available": local_available,
        "local_only": local_route,
        "silent_cross_provider_fallback": False,
    }


def _course_task_type(task_name: str) -> str:
    """Return the friendly course grouping without exposing schedule internals."""
    return (
        "exam"
        if re.search(r"exam|midterm|final|quiz|考试|期中|期末|测验", task_name, re.I)
        else "assignment"
    )


def _stable_proactive_policy(
    *, owner_id: UUID, privacy_class: PrivacyClass, memory_eligible: bool
) -> DataPolicy:
    policy = DataPolicy.owner_default(
        privacy_class, memory_eligible=memory_eligible
    )
    semantic_key = (
        f"proactive-simulation:data-policy-v1:{privacy_class.value}:"
        f"memory={str(memory_eligible).lower()}:cloud={str(policy.cloud_eligible).lower()}"
    )
    return policy.model_copy(
        update={"policy_revision_id": uuid5(owner_id, semantic_key)}
    )


def create_app(settings: Settings) -> FastAPI:
    # Stage 12 context is an explicit overlay. The Stage 10 baseline must remain
    # runnable with no enrolled device; its resolver then fails closed on every
    # context request instead of making the entire API fail at import/startup.
    resolved = settings
    metrics = OperationalMetrics()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime = build_runtime(resolved)
        app.state.runtime = runtime
        app.state.interaction_tasks = InteractionTasks()
        async def recover_expired():
            while True:
                try:
                    sweep = asyncio.create_task(asyncio.to_thread(
                        runtime.repository.recover_expired_interactions,
                        owner_id=resolved.owner_id,
                        cutoff=datetime.now(UTC)-timedelta(seconds=INTERACTION_DEADLINE_SECONDS+30),
                    ))
                    try:
                        await asyncio.shield(sweep)
                    except asyncio.CancelledError:
                        await settle_cancelled_task(sweep)
                        raise
                except Exception:
                    logging.getLogger(__name__).exception('expired interaction recovery failed')
                await asyncio.sleep(15)
        recovery_task = asyncio.create_task(recover_expired())
        try:
            yield
        finally:
            recovery_task.cancel()
            with anyio.CancelScope(shield=True):
                await asyncio.gather(recovery_task,return_exceptions=True)
                await app.state.interaction_tasks.aclose()
                await runtime.aclose()

    app = FastAPI(
        title="HAVRE API",
        version=__version__,
        description=(
            "Permanent Stage 10 interaction, memory, User Model, goals, Scene, "
            "governed local proactive simulation, offline, and reliability slice."
        ),
        lifespan=lifespan,
    )

    def configured_providers(runtime: Runtime) -> dict[str, object]:
        registry = getattr(runtime.service, "providers", None)
        if isinstance(registry, dict) and registry:
            return registry
        primary = runtime.service.provider
        return {primary.provider_id: primary}

    @app.middleware("http")
    async def owner_auth_and_metrics(request: Request, call_next):
        started = metrics.timer()
        private_boundary_request = (
            request.url.path.startswith("/v1/")
            or request.url.path == "/metrics"
            or request.url.path in {"/", "/chat", "/diary", "/memory", "/settings"}
        )
        if resolved.web_push_enabled and private_boundary_request:
            runtime = getattr(request.app.state, "runtime", None)
            attested = (
                False
                if runtime is None
                else await asyncio.to_thread(
                    lambda: runtime.web_push_provider.available
                )
            )
            if not attested:
                response = JSONResponse(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    content={"detail": "private Tailscale Serve attestation is unavailable"},
                )
                response.headers["Cache-Control"] = "no-store"
                return response
        protected = request.url.path.startswith("/v1/") or request.url.path == "/metrics"
        device_authenticated = request.url.path in {
            "/v1/context/collection-permit",
            "/v1/context/observations",
            "/v1/context/health",
        }
        pairing_claim_request = request.url.path == "/v1/devices/pair/claim"
        desktop_bootstrap_request = request.url.path == "/v1/desktop/session"
        if (
            protected and not device_authenticated and not desktop_bootstrap_request
            and not pairing_claim_request
            and resolved.require_owner_api_token
        ):
            if resolved.owner_api_token is None:
                response = JSONResponse(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    content={"detail": "owner authentication is not configured"},
                )
                response.headers["Cache-Control"] = "no-store"
                return response
            authorization = request.headers.get("authorization", "")
            expected = f"Bearer {resolved.owner_api_token}"
            cookie = request.cookies.get("havre_owner_session", "")
            bearer_authenticated = secrets.compare_digest(authorization, expected)
            cookie_authenticated = secrets.compare_digest(
                cookie, resolved.owner_api_token
            )
            primary_authenticated = bearer_authenticated or cookie_authenticated
            if (
                cookie_authenticated
                and not bearer_authenticated
                and request.method in {"POST", "PUT", "PATCH", "DELETE"}
            ):
                origin = request.headers.get("origin")
                trusted_origins = {str(request.base_url).rstrip("/")}
                if resolved.public_base_url is not None:
                    trusted_origins.add(resolved.public_base_url.rstrip("/"))
                if origin not in trusted_origins:
                    response = JSONResponse(
                        status_code=status.HTTP_403_FORBIDDEN,
                        content={"detail": "trusted same-origin request required"},
                    )
                    response.headers["Cache-Control"] = "no-store"
                    return response
            request.state.device_id = None
            if not primary_authenticated:
                device_token = request.cookies.get("havre_device_session", "")
                if authorization.startswith("Bearer "):
                    device_token = authorization.removeprefix("Bearer ")
                runtime = getattr(request.app.state, "runtime", None)
                device_id = (
                    None
                    if runtime is None or not device_token
                    else runtime.daily_companion_store.authenticate_device(device_token)
                )
                if device_id is not None:
                    request.state.device_id = device_id
            if not primary_authenticated and request.state.device_id is None:
                response = JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "owner authentication required"},
                    headers={"WWW-Authenticate": "Bearer"},
                )
                metrics.observe(
                    method=request.method,
                    route="/unauthorized",
                    status_code=response.status_code,
                    started=started,
                )
                response.headers["Cache-Control"] = "no-store"
                return response
            if primary_authenticated:
                request.state.auth_kind = "owner_primary"
            else:
                request.state.auth_kind = "paired_device"
                path, method = request.url.path, request.method
                paired_allowed = (
                    (method == "GET" and (
                        path == "/v1/timeline"
                        or path.startswith("/v1/push/navigation/")
                        or path == "/v1/diary"
                        or path.startswith("/v1/diary/")
                        or path in {"/v1/product/memory", "/v1/product/settings", "/v1/pwa/config"}
                    ))
                    or (method == "POST" and (
                        path in {"/v1/timeline/read", "/v1/interactions/stream", "/v1/feedback", "/v1/push/subscriptions"}
                        or (path.startswith("/v1/push/subscriptions/") and path.endswith("/revoke"))
                        or (path.startswith("/v1/memory/candidates/") and (
                            path.endswith("/accept") or path.endswith("/reject")
                        ))
                        or (path.startswith("/v1/memories/") and (
                            path.endswith("/correct") or path.endswith("/retract")
                        ))
                        or (path.startswith("/v1/product/memory/")
                            and path.endswith("/user-model-proposal"))
                        or (path.startswith("/v1/user-model/beliefs/") and (
                            path.endswith("/revisions") or path.endswith("/transitions")
                        ))
                    ))
                )
                if not paired_allowed:
                    response = JSONResponse(
                        status_code=status.HTTP_403_FORBIDDEN,
                        content={"detail": "paired device is not authorized for this owner-primary operation"},
                    )
                    response.headers["Cache-Control"] = "no-store"
                    return response
        if (
            request.url.path.startswith("/v1/")
            and not request.url.path.startswith("/v1/privacy/")
            and resolved.deployment_environment in {"staging", "production"}
        ):
            runtime = getattr(request.app.state, "runtime", None)
            release = None if runtime is None else runtime.release_manifest
            active = bool(
                runtime is not None
                and release is not None
                and runtime.operations_store.release_activation_status(release)
            )
            behavior_scope_allowed = bool(
                release is not None
                and (
                    resolved.deployment_environment != "production"
                    or release.release_scope == "production"
                )
            )
            if not active or not behavior_scope_allowed:
                response = JSONResponse(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    content={
                        "detail": "behavior serving is inactive for this infrastructure release"
                    },
                )
                metrics.observe(
                    method=request.method,
                    route="/behavior-quarantined",
                    status_code=response.status_code,
                    started=started,
                )
                return response
        response = await call_next(request)
        if request.url.path.startswith("/v1/") or request.url.path in {"/", "/chat"}:
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
        route = request.scope.get("route")
        route_path = getattr(route, "path", "/unmatched")
        metrics.observe(
            method=request.method,
            route=route_path,
            status_code=response.status_code,
            started=started,
        )
        return response

    desktop_bootstrap_lock = asyncio.Lock()
    desktop_bootstrap_consumed = False

    @app.post("/v1/desktop/session", include_in_schema=False)
    async def desktop_session(
        request: Request,
        desktop_bootstrap: Annotated[
            str | None, Header(alias="X-HAVRE-Desktop-Bootstrap")
        ] = None,
    ):
        nonlocal desktop_bootstrap_consumed
        form_post = desktop_bootstrap is None
        if form_post:
            values = parse_qs((await request.body()).decode("utf-8"), strict_parsing=True)
            supplied = values.get("desktop_bootstrap", [None])
            desktop_bootstrap = supplied[0] if len(supplied) == 1 else None
        async with desktop_bootstrap_lock:
            if (
                desktop_bootstrap_consumed
                or resolved.deployment_environment != "development"
                or resolved.desktop_bootstrap_token is None
                or resolved.owner_api_token is None
                or desktop_bootstrap is None
                or not secrets.compare_digest(
                    desktop_bootstrap, resolved.desktop_bootstrap_token
                )
            ):
                raise HTTPException(status_code=403, detail="desktop bootstrap rejected")
            desktop_bootstrap_consumed = True
        response = (
            RedirectResponse(url="/chat", status_code=303)
            if form_post
            else JSONResponse({"status": "owner_session_ready"})
        )
        response.set_cookie(
            "havre_owner_session",
            resolved.owner_api_token,
            httponly=True,
            secure=False,
            samesite="strict",
            path="/",
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health/live")
    async def liveness() -> dict[str, object]:
        return {"status": "alive", "service": "havre-api", "stage": 10}

    async def _preflight(runtime: Runtime) -> dict[str, object]:
        providers = configured_providers(runtime)
        provider_ids = tuple(providers)
        health_values = await asyncio.gather(
            *(providers[provider_id].health() for provider_id in provider_ids)
        )
        version_values = await asyncio.gather(
            *(providers[provider_id].version() for provider_id in provider_ids)
        )
        provider_health_by_id = dict(zip(provider_ids, health_values, strict=True))
        provider_version_by_id = dict(zip(provider_ids, version_values, strict=True))
        primary_provider_id = runtime.service.provider.provider_id
        provider_health = provider_health_by_id[primary_provider_id]
        provider_version = provider_version_by_id[primary_provider_id]
        if runtime.release_manifest is not None:
            require_provider_version_binding(
                components=runtime.release_manifest.components,
                provider_version=provider_version,
            )
        database = runtime.operations_store.readiness()
        preflight_ready = all(
            health.status == "healthy"
            for health in provider_health_by_id.values()
        )
        release_active = bool(
            runtime.release_manifest is None
            or resolved.deployment_environment == "development"
            or runtime.operations_store.release_activation_status(
                runtime.release_manifest
            )
        )
        return {
            "status": "ready" if preflight_ready else "not_ready",
            "stage": 10,
            "database": database,
            "provider": provider_health.model_dump(mode="json"),
            "providers": {
                provider_id: {
                    "health": provider_health_by_id[provider_id].model_dump(mode="json"),
                    "version": provider_version_by_id[provider_id].model_dump(mode="json"),
                }
                for provider_id in provider_ids
            },
            "release_active": release_active,
        }

    @app.get("/health/preflight")
    async def preflight(request: Request):
        runtime: Runtime = request.app.state.runtime
        try:
            payload = await _preflight(runtime)
        except Exception:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"status": "not_ready", "stage": 10},
            )
        return JSONResponse(
            status_code=(
                status.HTTP_200_OK
                if payload["status"] == "ready"
                else status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            content=jsonable_encoder(payload),
        )

    async def _readiness(runtime: Runtime) -> dict[str, object]:
        # Infrastructure readiness must be observable before an operator can
        # append the exact applied deployment record. Behavioral routes remain
        # independently quarantined by release_activation_status above.
        return await _preflight(runtime)

    @app.get("/health/ready")
    async def readiness(request: Request):
        runtime: Runtime = request.app.state.runtime
        try:
            payload = await _readiness(runtime)
        except Exception:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"status": "not_ready", "stage": 10},
            )
        if payload["status"] != "ready":
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content=jsonable_encoder(payload),
            )
        return payload

    @app.get("/health")
    async def health(request: Request):
        runtime: Runtime = request.app.state.runtime
        try:
            payload = await _readiness(runtime)
        except Exception:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"status": "not_ready", "stage": 10},
            )
        return JSONResponse(
            status_code=(
                status.HTTP_200_OK
                if payload["status"] == "ready"
                else status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            content=jsonable_encoder(payload),
        )

    @app.get("/version")
    async def version(request: Request) -> dict[str, object]:
        runtime: Runtime = request.app.state.runtime
        try:
            providers = configured_providers(runtime)
            provider_ids = tuple(providers)
            provider_versions = await asyncio.gather(
                *(providers[provider_id].version() for provider_id in provider_ids)
            )
        except ProviderVersionError as error:
            raise HTTPException(
                status_code=(503 if error.retryable else 502),
                detail={
                    "code": error.code,
                    "retryable": error.retryable,
                    "message": error.safe_message,
                },
            ) from error
        versions_by_id = dict(zip(provider_ids, provider_versions, strict=True))
        provider_version = versions_by_id[runtime.service.provider.provider_id]
        return {
            "service": "havre-api",
            "service_version": __version__,
            "contract_schema_version": 1,
            "stage": 10,
            "deployment_environment": resolved.deployment_environment,
            "release": (
                None
                if runtime.release_manifest is None
                else {
                    "release_id": runtime.release_manifest.release_id,
                    "release_scope": runtime.release_manifest.release_scope,
                    "source_revision": runtime.release_manifest.source_revision,
                    "manifest_hash": runtime.release_manifest.content_hash,
                    "adapter_deployment_authorized": (
                        runtime.release_manifest.adapter_deployment_authorized
                    ),
                }
            ),
            "provider": provider_version.model_dump(mode="json"),
            "memory_retrieval": {
                "algorithm_version": runtime.retrieval_service.default_algorithm,
                "embedding_version_id": runtime.retrieval_service.embedding_provider.version.embedding_version_id,
                "execution_environment": "local",
                "realtime_generation_enabled": getattr(runtime,"realtime_memory_service",None) is not None,
                "diary_window": "05:00-to-05:00-owner-local",
            },
            "providers": {
                provider_id: version.model_dump(mode="json")
                for provider_id, version in versions_by_id.items()
            },
        }

    @app.get("/metrics", response_class=PlainTextResponse)
    async def operational_metrics(request: Request) -> PlainTextResponse:
        runtime: Runtime = request.app.state.runtime
        readiness = runtime.operations_store.readiness()
        return PlainTextResponse(
            metrics.render(readiness=readiness),
            media_type="text/plain; version=0.0.4",
        )

    @app.post("/v1/privacy/exports")
    async def create_owner_export(request: Request) -> dict[str, object]:
        runtime: Runtime = request.app.state.runtime
        operation_id = str(uuid7())
        destination = resolved.owner_export_root / operation_id
        manifest = runtime.operations_store.export_owner_data(
            destination,
            erasure_ledger=runtime.erasure_ledger,
        )
        runtime.operations_store.verify_owner_export(destination)
        return {
            "operation_id": operation_id,
            "export_id": str(manifest.export_id),
            "manifest_hash": manifest.content_hash,
            "artifact_count": len(manifest.artifacts),
            "created_at": manifest.created_at,
            "local_only": True,
        }

    @app.post("/v1/privacy/erasure/source-events/{source_event_id}")
    async def erase_source_event(
        source_event_id: UUID,
        request: Request,
        confirmation: Annotated[
            str, Header(alias="X-HAVRE-Erasure-Confirm")
        ],
    ) -> dict[str, object]:
        if confirmation != "raw_source_and_derived":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="exact erasure confirmation is required",
            )
        runtime: Runtime = request.app.state.runtime
        if not runtime.operations_store.erasure_available:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="privileged erasure service is not configured",
            )
        return runtime.operations_store.erase_source_event(
            source_event_id=source_event_id,
            ledger=runtime.erasure_ledger,
        )

    @app.post("/v1/privacy/erasure/context-sources/{source_instance_id}")
    async def erase_context_source(
        source_instance_id: UUID,
        request: Request,
        confirmation: Annotated[
            str, Header(alias="X-HAVRE-Erasure-Confirm")
        ],
    ) -> dict[str, object]:
        if confirmation != "context_source_and_derived":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="exact context-source erasure confirmation is required",
            )
        runtime: Runtime = request.app.state.runtime
        if not runtime.operations_store.erasure_available:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="privileged erasure service is not configured",
            )
        return runtime.operations_store.erase_context_source(
            source_instance_id=source_instance_id,
            ledger=runtime.erasure_ledger,
        )

    @app.post(
        "/v1/interactions",
        response_model=InteractionResult,
        status_code=status.HTTP_201_CREATED,
    )
    async def interact(
        body: InteractionBody,
        request: Request,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)],
        traceparent: Annotated[str | None, Header(alias="traceparent")] = None,
    ) -> InteractionResult:
        runtime: Runtime = request.app.state.runtime
        try:
            return await runtime.service.interact(
                InteractionCommand(
                    message=body.message,
                    privacy_class=body.privacy_class,
                    memory_eligible=body.memory_eligible,
                    session_id=body.session_id,
                    channel="api",
                    language=body.language,
                    client_created_at=body.client_created_at,
                    idempotency_key=idempotency_key,
                    traceparent=traceparent,
                )
            )
        except (IdempotencyConflict, InteractionInProgress, InteractionPreviouslyFailed) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ContextBudgetExceeded as error:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail={
                    "code": "context_limit_exceeded",
                    "retryable": False,
                    "message": CONTEXT_LIMIT_SAFE_MESSAGE,
                },
            ) from error
        except InferenceTimeoutError as error:
            raise HTTPException(status_code=504, detail=str(error)) from error
        except ProviderInferenceError as error:
            raise HTTPException(
                status_code=(503 if error.retryable else 502),
                detail={
                    "code": error.code,
                    "retryable": error.retryable,
                    "message": error.safe_message,
                },
            ) from error
        except (ProviderPolicyError, ProviderVersionError) as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @app.post("/v1/interactions/stream")
    async def interact_stream(
        body: InteractionBody,
        request: Request,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=1, max_length=200)
        ],
        traceparent: Annotated[str | None, Header(alias="traceparent")] = None,
    ) -> StreamingResponse:
        """Stream a durability-gated response as newline-delimited JSON.

        Provider streaming is consumed and validated inside Core. Text becomes
        client-visible only after the completed assistant Event is durable, so
        a disconnected browser cannot create ghost conversation history.
        """
        runtime: Runtime = request.app.state.runtime

        async def generate():
            yield json.dumps({"type": "status", "status": "thinking"}) + "\n"
            try:
                result = await request.app.state.interaction_tasks.run(runtime.service,
                    InteractionCommand(
                        message=body.message,
                        privacy_class=body.privacy_class,
                        memory_eligible=body.memory_eligible,
                        session_id=body.session_id,
                        channel="web",
                        language=body.language,
                        client_created_at=body.client_created_at,
                        idempotency_key=idempotency_key,
                        traceparent=traceparent,
                    )
                )
            except ProviderInferenceError as error:
                yield json.dumps(
                    {"type": "error", "message": error.safe_message},
                    ensure_ascii=False,
                ) + "\n"
                return
            except (ProviderPolicyError, ProviderVersionError):
                yield json.dumps(
                    {
                        "type": "error",
                        "message": "The selected reply route is unavailable and was not switched to another provider.",
                    },
                    ensure_ascii=False,
                ) + "\n"
                return
            except InferenceTimeoutError:
                yield json.dumps(
                    {"type": "error", "message": "HAVRE timed out before completing the response."},
                    ensure_ascii=False,
                ) + "\n"
                return
            except ContextBudgetExceeded:
                yield json.dumps(
                    {
                        "type": "error",
                        "code": "context_limit_exceeded",
                        "retryable": False,
                        "status_code": status.HTTP_413_CONTENT_TOO_LARGE,
                        "message": CONTEXT_LIMIT_SAFE_MESSAGE,
                    },
                    ensure_ascii=False,
                ) + "\n"
                return
            except (IdempotencyConflict, InteractionInProgress, InteractionPreviouslyFailed, ValueError):
                yield json.dumps(
                    {"type": "error", "message": "This conversation cannot accept that turn. Start a new conversation and try again."},
                    ensure_ascii=False,
                ) + "\n"
                return
            except Exception:
                yield json.dumps(
                    {"type": "error", "message": "HAVRE could not complete the response safely."},
                    ensure_ascii=False,
                ) + "\n"
                return
            content = result.content
            for offset in range(0, len(content), 24):
                yield json.dumps(
                    {"type": "delta", "text": content[offset:offset + 24]},
                    ensure_ascii=False,
                ) + "\n"
                await asyncio.sleep(0)
            metadata = jsonable_encoder(result)
            metadata.pop("content", None)
            yield json.dumps(
                {"type": "completed", "interaction": metadata},
                ensure_ascii=False,
            ) + "\n"

        return StreamingResponse(
            generate(),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @app.get("/v1/conversations")
    async def conversations(request: Request, limit: int = 50) -> object:
        runtime: Runtime = request.app.state.runtime
        return jsonable_encoder(
            runtime.feedback_service.list_conversations(limit=max(1, min(limit, 100)))
        )

    @app.get("/v1/timeline")
    async def continuous_timeline(
        request: Request,
        limit: int = 60,
        before_at: datetime | None = None,
        before_event_id: UUID | None = None,
        through_event_id: UUID | None = None,
    ) -> object:
        runtime: Runtime = request.app.state.runtime
        try:
            return jsonable_encoder(runtime.daily_companion_store.timeline(
                limit=limit,
                before_at=before_at,
                before_event_id=before_event_id,
                through_event_id=through_event_id,
            ))
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/v1/timeline/read")
    async def mark_timeline_read(body: TimelineReadBody, request: Request) -> object:
        runtime: Runtime = request.app.state.runtime
        device_id = getattr(request.state, "device_id", None)
        if device_id is None:
            raise HTTPException(status_code=409, detail="Pair this browser before syncing read state")
        try:
            return jsonable_encoder(runtime.daily_companion_store.mark_read(
                device_id=device_id, event_id=body.event_id
            ))
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.post("/v1/devices/pair")
    async def create_device_pairing(request: Request) -> object:
        runtime: Runtime = request.app.state.runtime
        return jsonable_encoder(runtime.daily_companion_store.create_pairing())

    @app.post("/v1/devices/pair/claim")
    async def claim_device_pairing(body: PairingClaimBody, request: Request) -> JSONResponse:
        runtime: Runtime = request.app.state.runtime
        try:
            result = runtime.daily_companion_store.claim_pairing(
                pairing_id=body.pairing_id,
                code=body.code,
                display_name=body.display_name,
                device_kind=body.device_kind,
                session_days=runtime.settings.device_session_days,
            )
        except ValueError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
        response = JSONResponse(jsonable_encoder({
            "device_id": result["device_id"],
            "session_expires_at": result["session_expires_at"],
        }))
        response.set_cookie(
            "havre_device_session",
            result["device_token"],
            httponly=True,
            secure=bool(runtime.settings.public_base_url and runtime.settings.public_base_url.startswith("https://")),
            samesite="strict",
            path="/",
            expires=result["session_expires_at"],
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/v1/devices")
    async def list_companion_devices(request: Request) -> object:
        runtime: Runtime = request.app.state.runtime
        return jsonable_encoder(runtime.daily_companion_store.list_devices())

    @app.post("/v1/devices/{device_id}/revoke")
    async def revoke_companion_device(device_id: UUID, request: Request) -> object:
        runtime: Runtime = request.app.state.runtime
        try:
            runtime.daily_companion_store.revoke_device(device_id=device_id)
            return {"device_id": str(device_id), "status": "revoked"}
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/v1/pwa/config")
    async def pwa_config(request: Request) -> object:
        runtime: Runtime = request.app.state.runtime
        worker = runtime.web_push_provider.worker_status()
        real_device_validated = runtime.web_push_provider.real_device_validated
        delivery_active = runtime.web_push_provider.delivery_active
        return {
            "web_push_available": runtime.web_push_provider.available,
            "web_push_worker_live": worker["live"],
            "web_push_runtime_ready": runtime.web_push_provider.runtime_ready,
            "web_push_delivery_active": delivery_active,
            "web_push_real_device_validated": real_device_validated,
            "web_push_pwa_shell_version": runtime.web_push_provider.pwa_shell_version,
            "web_push_delivery_reason": (
                "Governed Web Push is active on a validated private device path."
                if delivery_active else
                "The real-device path is validated; start the HAVRE backend to deliver notifications."
                if real_device_validated else
                "Governed Web Push is configured; real iPhone activation evidence is still required."
                if runtime.web_push_provider.available else
                "HTTPS, VAPID, and an explicit key version are required."
            ),
            "vapid_public_key": (
                runtime.settings.web_push_vapid_public_key
                if runtime.web_push_provider.available
                else None
            ),
            "owner_timezone": runtime.settings.owner_timezone,
        }

    @app.post("/v1/push/subscriptions")
    async def save_push_subscription(body: PushSubscriptionBody, request: Request) -> object:
        runtime: Runtime = request.app.state.runtime
        device_id = getattr(request.state, "device_id", None)
        if device_id is None:
            raise HTTPException(status_code=409, detail="Pair this browser before enabling notifications")
        try:
            runtime.web_push_provider.ensure_configuration()
            return jsonable_encoder(runtime.daily_companion_store.save_subscription(
                device_id=device_id,
                endpoint=body.endpoint,
                p256dh=body.p256dh,
                auth_secret=body.auth,
                preview_level=body.preview_level,
                vapid_key_version=runtime.settings.web_push_vapid_key_version or "",
                expires_at=body.expires_at,
            ))
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/v1/push/subscriptions/{subscription_id}/revoke")
    async def revoke_push_subscription(subscription_id: UUID, request: Request) -> object:
        runtime: Runtime = request.app.state.runtime
        device_id = getattr(request.state, "device_id", None)
        if device_id is None:
            raise HTTPException(status_code=409, detail="Paired device session required")
        try:
            runtime.daily_companion_store.revoke_subscription(
                device_id=device_id, subscription_id=subscription_id
            )
            return {"subscription_id": str(subscription_id), "status": "revoked"}
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.post("/v1/push/deliver/run-once")
    async def deliver_web_push(request: Request) -> object:
        runtime: Runtime = request.app.state.runtime
        return jsonable_encoder(runtime.web_push_provider.deliver_pending())

    @app.post("/v1/push/real-device-validations")
    async def record_real_device_validation(
        body: RealDeviceValidationBody, request: Request
    ) -> object:
        runtime: Runtime = request.app.state.runtime
        try:
            return jsonable_encoder(
                runtime.web_push_provider.record_real_device_validation(
                    delivery_locator=body.delivery_locator,
                    device_id=body.device_id,
                    pwa_shell_version=body.pwa_shell_version,
                    owner_confirmation_ref=body.owner_confirmation_ref,
                )
            )
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/v1/push/navigation/{delivery_locator}")
    async def resolve_push_navigation(delivery_locator: UUID, request: Request) -> object:
        runtime: Runtime = request.app.state.runtime
        try:
            event_id = runtime.web_push_provider.resolve_navigation(
                delivery_locator=delivery_locator,
                device_id=getattr(request.state, "device_id", None),
            )
            return {"event_id": str(event_id)}
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/v1/diary")
    async def list_diary(request: Request, limit: int = 60) -> object:
        runtime: Runtime = request.app.state.runtime
        if runtime.diary_intelligence_service is not None:
            return jsonable_encoder(runtime.diary_intelligence_service.list_diary(
                timezone_name=runtime.settings.owner_timezone, limit=limit
            ))
        return jsonable_encoder(runtime.daily_companion_store.list_diary(
            timezone_name=runtime.settings.owner_timezone, limit=limit
        ))

    @app.get("/v1/diary/{local_date}")
    async def get_diary_day(local_date: date, request: Request) -> object:
        runtime: Runtime = request.app.state.runtime
        entry = (
            runtime.diary_intelligence_service.diary_day(
                local_date=local_date, timezone_name=runtime.settings.owner_timezone
            )
            if runtime.diary_intelligence_service is not None
            else runtime.daily_companion_store.diary_day(
                local_date=local_date,
                timezone_name=runtime.settings.owner_timezone,
            )
        )
        if entry is None:
            raise HTTPException(status_code=404, detail="No conversation for this owner-local day")
        return jsonable_encoder(entry)

    @app.get("/v1/product/memory")
    async def product_memory(request: Request) -> object:
        runtime: Runtime = request.app.state.runtime
        from companion.product.sources import source_previews

        memories = runtime.memory_service.list_active(owner_id=runtime.settings.owner_id)
        beliefs = runtime.user_model_service.list_beliefs(
            owner_id=runtime.settings.owner_id, include_inactive=True
        )
        subjects = tuple(
            ("memory_revision", row["memory_id"], row["revision"]) for row in memories
        ) + tuple(
            ("belief_revision", snapshot.revision.belief_id, snapshot.revision.revision)
            for snapshot in beliefs
        )
        previews = source_previews(runtime.repository, owner_id=runtime.settings.owner_id, subjects=subjects)
        memory_rows = [
            {**dict(memory), "source_previews": previews.get(
                ("memory_revision", memory["memory_id"], memory["revision"]), ()
            )} for memory in memories
        ]
        belief_rows = [
            {**snapshot.model_dump(mode="python"), "source_previews": previews.get(
                ("belief_revision", snapshot.revision.belief_id, snapshot.revision.revision), ()
            )} for snapshot in beliefs
        ]
        all_candidates = runtime.memory_service.list_candidates(
            owner_id=runtime.settings.owner_id, status="pending"
        )
        with runtime.repository.pool.connection() as connection:
            delegated_sources = {
                row["source_event_id"]
                for row in connection.execute(
                    """SELECT DISTINCT source_event_id
                       FROM havre.owner_delegated_gpt_memory_updates
                       WHERE owner_id=%s""",
                    (runtime.settings.owner_id,),
                ).fetchall()
            }
        candidates = [
            candidate
            for candidate in all_candidates
            if is_memory_candidate_worthy(candidate["content_text"])
            and candidate["source_event_id"] not in delegated_sources
        ]
        candidate_previews = source_previews(
            runtime.repository, owner_id=runtime.settings.owner_id,
            subjects=tuple(("event", c["source_event_id"], None) for c in candidates),
        )
        candidate_rows = [
            {**dict(candidate), "source_previews": candidate_previews.get(
                ("event", candidate["source_event_id"], None), ()
            )} for candidate in candidates
        ]
        goals = runtime.goal_service.list(
            owner_id=runtime.settings.owner_id, include_inactive=True
        )
        with runtime.repository.pool.connection() as connection:
            course_rows = connection.execute(
                """SELECT projection.goal_id,projection.goal_revision,
                          projection.course_name,projection.task_name
                   FROM havre.commitment_projections projection
                   JOIN havre.goals goal ON goal.owner_id=projection.owner_id
                    AND goal.goal_id=projection.goal_id
                    AND goal.revision=projection.goal_revision
                   WHERE projection.owner_id=%s""",
                (runtime.settings.owner_id,),
            ).fetchall()
        courses = {row["goal_id"]: dict(row) for row in course_rows}
        goal_rows = []
        for goal in goals:
            item = dict(goal)
            course = courses.get(goal["goal_id"])
            item["display_category"] = "course" if course else "other"
            if course:
                item.update(course)
                item["task_type"] = _course_task_type(course["task_name"])
            goal_rows.append(item)
        with runtime.repository.pool.connection() as connection:
            memory_jobs = connection.execute(
                """SELECT count(*) FILTER (WHERE status IN ('pending','leased')) AS pending,
                          count(*) FILTER (WHERE status='retryable_failed') AS retrying,
                          max(updated_at) FILTER (WHERE status='completed') AS last_completed_at
                   FROM havre.realtime_memory_jobs WHERE owner_id=%s""",
                (runtime.settings.owner_id,),
            ).fetchone()
        return jsonable_encoder({
            "memories": memory_rows,
            "memory_candidates": candidate_rows,
            "beliefs": belief_rows,
            "goals": goal_rows,
            "understanding_status": {
                "realtime_jobs": dict(memory_jobs),
                "automatic_chat_context": True,
                "automatic_recent_owner_feedback": True,
                "automatic_memory_proposals": True,
                "automatic_user_model_beliefs": (
                    runtime.diary_intelligence_service is not None
                ),
                "automatic_pattern_acceptance": False,
                "automatic_current_state": False,
                "explanation": (
                    "聊天后，值得记住的经历和你明确说过的长期偏好会陆续整理到这里，不必等到凌晨。"
                    "私密聊天产生的新记忆仍需你确认；每天凌晨 5 点另外整理日记。"
                ),
                "suppressed_low_value_candidate_count": (
                    len(all_candidates) - len(candidates)
                ),
            },
            "current_state": runtime.current_state_service.current(
                owner_id=runtime.settings.owner_id
            ),
            "pattern_proposals": runtime.consolidation_service.list_proposals(
                owner_id=runtime.settings.owner_id, status="pending"
            ),
        })

    @app.get("/v1/product/settings")
    async def product_settings(request: Request) -> object:
        runtime: Runtime = request.app.state.runtime
        providers = configured_providers(runtime)
        provider_ids = tuple(providers)
        provider_versions = await asyncio.gather(
            *(providers[provider_id].version() for provider_id in provider_ids)
        )
        versions_by_id = dict(zip(provider_ids, provider_versions, strict=True))
        provider_version = versions_by_id[runtime.service.provider.provider_id]
        local_version = versions_by_id.get("self-hosted-openai-compatible")
        if (
            local_version is None
            and provider_version.execution_environment == "local"
        ):
            local_version = provider_version
        if (
            local_version is not None
            and local_version.execution_environment != "local"
        ):
            local_version = None
        dual_privacy_routing = (
            provider_version.execution_environment == "cloud"
            and local_version is not None
        )
        reply_routes = _reply_routes_settings(
            provider_version=provider_version,
            local_version=local_version,
        )
        owner_primary = getattr(request.state, "auth_kind", "owner_primary") != "paired_device"
        strong_runtime_active = bool(
            runtime.settings.manual_strong_brain_enabled
            and runtime.settings.deepseek_api_key
            and runtime.settings.deepseek_api_key.strip()
            and runtime.strong_brain_service is not None
        )
        strong_available_to_requester = owner_primary and strong_runtime_active
        worker = runtime.web_push_provider.worker_status()
        real_device_validated = runtime.web_push_provider.real_device_validated
        delivery_active = runtime.web_push_provider.delivery_active
        return jsonable_encoder({
            "auth_capabilities": {
                "owner_primary": owner_primary,
                "manage_devices": owner_primary,
                "mutate_memory": True,
                "review_understanding": True,
                "mutate_product_settings": owner_primary,
            },
            "owner_timezone": runtime.settings.owner_timezone,
            "calendar": runtime.daily_companion_store.calendar_status(),
            "web_push_available": runtime.web_push_provider.available,
            "web_push_worker_live": worker["live"],
            "web_push_runtime_ready": runtime.web_push_provider.runtime_ready,
            "web_push_delivery_active": delivery_active,
            "web_push_real_device_validated": real_device_validated,
            "web_push_pwa_shell_version": runtime.web_push_provider.pwa_shell_version,
            "web_push_delivery_reason": (
                "真实 iPhone 路径已验收，当前 governed Web Push worker 在线。"
                if delivery_active else
                "真实 iPhone 路径已验收；启动 HAVRE backend 后可投递。"
                if real_device_validated else
                "generic/private preview 已配置；真实 iPhone 激活证据仍未完成。"
                if runtime.web_push_provider.available else
                "尚未完成 HTTPS、VAPID 与 governed worker 配置。"
            ),
            "strong_brain": {
                "mode": (
                    "legacy_owner_manual"
                    if strong_runtime_active
                    else "disabled"
                ),
                "runtime_active": strong_runtime_active,
                "available_for_owner_data": strong_available_to_requester,
                "default": False,
                "user_facing": False,
                "reason": (
                    "历史 Strong Brain 端点已由 owner-primary 显式启用；它不出现在日常聊天中，也不会自动路由。"
                    if strong_available_to_requester
                    else "历史 Strong Brain 仅允许 owner-primary 显式启用；当前请求方不可用。"
                    if strong_runtime_active
                    else "Strong Brain 已退出日常产品；仅有 DeepSeek key 不会激活历史端点。"
                ),
            },
            "brain": {
                "mode": (
                    "automatic_chatgpt"
                    if provider_version.provider_id == "openai-codex-chatgpt"
                    else "local"
                ),
                "provider_id": provider_version.provider_id,
                "model_version_id": provider_version.model_version_id,
                "default": True,
                "reason": (
                    "普通且上下文允许云端时，消息默认由 GPT-5.6-sol 回复；HAVRE 合并上下文后若不适合云端则只走本机。两条路径都经过同一 Core 与 Event 流程。"
                    if provider_version.provider_id == "openai-codex-chatgpt"
                    else "当前使用本地回复引擎；没有自动向云端发送聊天内容。"
                ),
            },
            "reply_routes": reply_routes,
            "local_brain": {
                "available": local_version is not None,
                "provider_id": (
                    None if local_version is None else local_version.provider_id
                ),
                "model_version_ids": (
                    () if local_version is None else (local_version.model_version_id,)
                ),
                "adapter_version_id": (
                    None
                    if local_version is None
                    else local_version.active_adapter_version_id
                ),
                "binding": (
                    None
                    if local_version is None
                    else local_version.active_adapter_version_id
                    or local_version.model_version_id
                ),
                "default": (
                    not dual_privacy_routing
                    and local_version is not None
                    and local_version.execution_environment == "local"
                ),
                "privacy_route": dual_privacy_routing,
            },
            "reach_out": runtime.daily_companion_store.proactive_preference(),
            "relationship_initiative_active": (
                runtime.settings.relational_initiative_enabled
            ),
        })

    @app.post("/v1/product/reach-out")
    async def update_reach_out_settings(
        body: ReachOutSettingsBody, request: Request
    ) -> object:
        runtime: Runtime = request.app.state.runtime
        if (body.quiet_start is None) != (body.quiet_end is None):
            raise HTTPException(status_code=422, detail="quiet hours require both start and end")
        current_payload = runtime.daily_companion_store.proactive_preference()
        quiet_hours = (
            (
                QuietHours(
                    start_local=body.quiet_start,
                    end_local=body.quiet_end,
                    timezone_name=runtime.settings.owner_timezone,
                ),
            )
            if body.quiet_hours_complete
            else ()
        )
        if current_payload is None:
            reminders_enabled = (
                True if body.reminders_enabled is None else body.reminders_enabled
            )
            friendly_check_ins_enabled = (
                True
                if body.friendly_check_ins_enabled is None
                else body.friendly_check_ins_enabled
            )
            preference = ProactivePreferenceRevision(
                owner_id=runtime.settings.owner_id,
                revision=1,
                global_enabled=body.enabled,
                category_permissions={
                    "owner_reminder": (
                        "allowed" if reminders_enabled else "denied"
                    ),
                    "relationship_follow_up": (
                        "allowed" if friendly_check_ins_enabled else "denied"
                    ),
                    "conversation_continuation": (
                        "allowed" if friendly_check_ins_enabled else "denied"
                    ),
                },
                allowed_channels=("web_inbox",),
                quiet_hours=quiet_hours,
                global_budget_per_24h=5,
                category_budget_per_24h={
                    "owner_reminder": 4,
                    "relationship_follow_up": 1,
                    "conversation_continuation": 2,
                },
                cooldown_seconds=body.cooldown_seconds,
                authorization_ref="owner-daily-companion-reach-out-setting-v1",
            )
        else:
            current = ProactivePreferenceRevision.model_validate(current_payload)
            category_permissions = dict(current.category_permissions)
            if body.reminders_enabled is not None:
                category_permissions["owner_reminder"] = (
                    "allowed" if body.reminders_enabled else "denied"
                )
            if body.friendly_check_ins_enabled is not None:
                friendly_permission = (
                    "allowed" if body.friendly_check_ins_enabled else "denied"
                )
                category_permissions["relationship_follow_up"] = friendly_permission
                category_permissions["conversation_continuation"] = friendly_permission
            elif "conversation_continuation" not in category_permissions:
                category_permissions["conversation_continuation"] = (
                    category_permissions.get("relationship_follow_up", "denied")
                )
            category_budgets = dict(current.category_budget_per_24h)
            category_budgets["relationship_follow_up"] = 1
            category_budgets["conversation_continuation"] = 2
            preference = current.model_copy(update={
                "preference_revision_id": uuid7(),
                "revision": current.revision + 1,
                "global_enabled": body.enabled,
                "quiet_hours": quiet_hours,
                "cooldown_seconds": body.cooldown_seconds,
                "category_permissions": category_permissions,
                "category_budget_per_24h": category_budgets,
                "global_budget_per_24h": current.global_budget_per_24h or 5,
                "created_at": datetime.now(UTC),
                "content_hash": "",
            })
            preference = ProactivePreferenceRevision.model_validate(
                preference.model_dump(mode="json")
            )
        try:
            runtime.proactive_store.save_preference(preference)
        except (LookupError, ValueError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return jsonable_encoder(preference)

    @app.post("/v1/product/calendar")
    async def toggle_product_calendar(body: CalendarToggleBody, request: Request) -> object:
        runtime: Runtime = request.app.state.runtime
        with runtime.repository.pool.connection() as connection:
            row = connection.execute(
                """SELECT source.source_instance_id,state.revision,state.status,
                          consent.data_policy,consent.status AS consent_status,
                          consent.effective_at AS consent_effective_at,
                          consent.expires_at AS consent_expires_at,
                          consent.authorization_ref
                   FROM havre.context_sources source
                   JOIN LATERAL (
                     SELECT revision,status FROM havre.context_source_state_revisions value
                     WHERE value.owner_id=source.owner_id
                       AND value.source_instance_id=source.source_instance_id
                     ORDER BY revision DESC LIMIT 1
                   ) state ON true
                   JOIN LATERAL (
                     SELECT data_policy,status,effective_at,expires_at,authorization_ref
                     FROM havre.context_consent_scope_revisions value
                     WHERE value.owner_id=source.owner_id
                       AND value.source_instance_id=source.source_instance_id
                     ORDER BY revision DESC LIMIT 1
                   ) consent ON true
                   WHERE source.owner_id=%s AND source.source_kind='calendar'
                   ORDER BY source.created_at DESC LIMIT 1""",
                (runtime.settings.owner_id,),
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=409, detail="Import a calendar before enabling it")
        now = datetime.now(UTC)
        if body.enabled:
            if row["status"] == "enabled":
                return jsonable_encoder({"event_id": None, "calendar": runtime.daily_companion_store.calendar_status()})
            raise HTTPException(status_code=409, detail="Re-import the calendar to create a new governed source")
        if row["status"] == "disabled":
            return jsonable_encoder({"event_id": None, "calendar": runtime.daily_companion_store.calendar_status()})
        state = ContextSourceStateRevision(
            owner_id=runtime.settings.owner_id,
            source_instance_id=row["source_instance_id"],
            revision=row["revision"] + 1,
            status="disabled",
            reason="owner_disabled",
            effective_at=now,
            authorization_ref=row["authorization_ref"],
        )
        try:
            event_id = runtime.context_store.save_source_state(
                state, data_policy=DataPolicy.model_validate(row["data_policy"])
            )
        except (ContextIngestRejected, ValueError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return jsonable_encoder({"event_id": event_id, "calendar": runtime.daily_companion_store.calendar_status()})

    @app.post("/v1/brain/strong/rethink/{assistant_event_id}")
    async def strong_brain_rethink(
        assistant_event_id: UUID,
        request: Request,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=1, max_length=200)
        ],
    ) -> object:
        runtime: Runtime = request.app.state.runtime
        if (
            not runtime.settings.manual_strong_brain_enabled
            or not runtime.settings.deepseek_api_key
            or runtime.strong_brain_service is None
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "历史 Strong Brain 端点未显式启用；"
                    "本次没有向 DeepSeek 发送数据。"
                ),
            )
        try:
            result = await runtime.strong_brain_service.rethink(
                source_assistant_event_id=assistant_event_id,
                idempotency_key=idempotency_key,
            )
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except (ValueError, ProviderVersionError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ProviderInferenceError as error:
            if error.code == "content_blocked":
                detail = (
                    "Strong Brain 这次用完了思考额度，但没有生成最终回答。"
                    "这次没有写入聊天，可以重新试一次。"
                    if error.retryable
                    else "Strong Brain 这次没有返回可显示的最终回答；聊天没有被改动。"
                )
            else:
                detail = error.safe_message
            raise HTTPException(
                status_code=(503 if error.retryable else 502),
                detail=detail,
            ) from error
        return jsonable_encoder(result)

    @app.get("/v1/conversations/{session_id}")
    async def conversation(session_id: UUID, request: Request) -> object:
        runtime: Runtime = request.app.state.runtime
        return jsonable_encoder(
            runtime.feedback_service.conversation(session_id=session_id)
        )

    @app.post("/v1/conversations/{session_id}/close")
    async def close_conversation_episode(
        session_id: UUID, body: EpisodeCloseBody, request: Request
    ) -> object:
        runtime: Runtime = request.app.state.runtime
        try:
            return jsonable_encoder(runtime.feedback_service.close_episode(
                session_id=session_id, boundary_reason=body.boundary_reason
            ))
        except (LookupError, ValueError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/v1/memory/episodes")
    async def memory_episodes(request: Request, limit: int = 50) -> object:
        runtime: Runtime = request.app.state.runtime
        return jsonable_encoder(runtime.feedback_service.list_episodes(
            limit=max(1,min(limit,100))
        ))

    @app.get("/v1/memory/episode-suggestions")
    async def episode_suggestions(request: Request, status: str = "pending") -> object:
        runtime: Runtime = request.app.state.runtime
        return jsonable_encoder(
            runtime.feedback_service.list_episode_suggestions(status=status)
        )

    @app.post("/v1/memory/episode-suggestions/{suggestion_id}/review")
    async def review_episode_suggestion(
        suggestion_id: UUID,
        body: EpisodeSuggestionReviewBody,
        request: Request,
    ) -> object:
        runtime: Runtime = request.app.state.runtime
        try:
            return jsonable_encoder(runtime.feedback_service.review_episode_suggestion(
                suggestion_id=suggestion_id, decision=body.decision, reason=body.reason
            ))
        except (LookupError, ValueError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/v1/feedback", status_code=status.HTTP_201_CREATED)
    async def save_feedback(body: FeedbackBody, request: Request) -> object:
        runtime: Runtime = request.app.state.runtime
        try:
            return jsonable_encoder(runtime.feedback_service.save(
                assistant_event_id=body.assistant_event_id,
                rating=body.rating,
                reason_codes=body.reason_codes,
                reason_text=body.reason_text,
                owner_revision_text=body.owner_revision_text,
                expected_revision=body.expected_revision,
            ))
        except (LookupError, ValueError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/v1/personalization-feedback")
    async def personalization_feedback(request: Request, limit: int = 100) -> object:
        runtime: Runtime = request.app.state.runtime
        return jsonable_encoder(runtime.feedback_service.list(limit=max(1, min(limit, 250))))

    @app.post("/v1/personalization-feedback/{feedback_id}/review")
    async def review_personalization_feedback(
        feedback_id: UUID,
        body: FeedbackReviewBody,
        request: Request,
    ) -> object:
        if body.decision is FeedbackReviewDecision.APPROVED_FOR_PERSONALIZATION_TRAINING:
            raise HTTPException(
                status_code=409,
                detail="Stage 9B training authorization is not active",
            )
        runtime: Runtime = request.app.state.runtime
        try:
            return jsonable_encoder(runtime.feedback_service.review(
                feedback_id=feedback_id,
                feedback_revision=body.feedback_revision,
                decision=body.decision,
                issue_attributions=body.issue_attributions,
                review_notes=body.review_notes,
                authorization_ref=body.authorization_ref,
            ))
        except (LookupError, ValueError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/v1/preferences/communication")
    async def communication_preference(request: Request) -> object:
        runtime: Runtime = request.app.state.runtime
        return jsonable_encoder(runtime.feedback_service.current_preference())

    @app.post("/v1/preferences/communication")
    async def set_communication_preference(
        body: CommunicationPreferenceBody, request: Request
    ) -> object:
        runtime: Runtime = request.app.state.runtime
        return jsonable_encoder(runtime.feedback_service.set_preference(
            response_length=body.response_length,
            reason=body.reason,
        ))

    @app.get("/v1/interactions/{request_id}/evidence")
    async def evidence(request_id: UUID, request: Request) -> object:
        runtime: Runtime = request.app.state.runtime
        evidence_bundle = runtime.repository.evidence(
            request_id,
            owner_id=runtime.settings.owner_id,
        )
        if evidence_bundle is None:
            raise HTTPException(status_code=404, detail="interaction not found")
        return jsonable_encoder(evidence_bundle)

    @app.post("/v1/memory/jobs/run-once")
    async def run_memory_job(request: Request) -> object:
        runtime: Runtime = request.app.state.runtime
        return jsonable_encoder(runtime.memory_worker.run_once())

    @app.get("/v1/memory/candidates")
    async def memory_candidates(request: Request, status: str = "pending") -> object:
        runtime: Runtime = request.app.state.runtime
        return jsonable_encoder(
            runtime.memory_service.list_candidates(
                owner_id=runtime.settings.owner_id,
                status=status,
            )
        )

    @app.post("/v1/memory/candidates/{candidate_id}/accept")
    async def accept_memory_candidate(
        candidate_id: UUID, body: AcceptReviewBody, request: Request
    ) -> object:
        runtime: Runtime = request.app.state.runtime
        try:
            return jsonable_encoder(runtime.memory_service.accept_candidate(
                owner_id=runtime.settings.owner_id,
                candidate_id=candidate_id,
                reason=body.reason,
                importance=body.importance,
                content_text=body.content_text,
            ))
        except (LookupError, ValueError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/v1/memory/candidates/{candidate_id}/reject")
    async def reject_memory_candidate(
        candidate_id: UUID, body: ReviewBody, request: Request
    ) -> object:
        runtime: Runtime = request.app.state.runtime
        try:
            return jsonable_encoder(runtime.memory_service.reject_candidate(
                owner_id=runtime.settings.owner_id,
                candidate_id=candidate_id,
                reason=body.reason,
            ))
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/v1/memories")
    async def active_memories(request: Request) -> object:
        runtime: Runtime = request.app.state.runtime
        return jsonable_encoder(
            runtime.memory_service.list_active(owner_id=runtime.settings.owner_id)
        )

    @app.post("/v1/memories/{memory_id}/correct")
    async def correct_memory(
        memory_id: UUID, body: CorrectMemoryBody, request: Request
    ) -> object:
        runtime: Runtime = request.app.state.runtime
        try:
            return jsonable_encoder(runtime.memory_service.correct(
                owner_id=runtime.settings.owner_id,
                memory_id=memory_id,
                content_text=body.content_text,
                reason=body.reason,
            ))
        except (LookupError, ValueError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/v1/memories/{memory_id}/retract")
    async def retract_memory(
        memory_id: UUID, body: ReviewBody, request: Request
    ) -> object:
        runtime: Runtime = request.app.state.runtime
        try:
            return jsonable_encoder(runtime.memory_service.retract(
                owner_id=runtime.settings.owner_id,
                memory_id=memory_id,
                reason=body.reason,
            ))
        except (LookupError, ValueError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/v1/product/memory/{memory_id}/user-model-proposal")
    async def propose_user_model_from_memory(
        memory_id: UUID, body: MemoryBeliefProposalBody, request: Request
    ) -> object:
        runtime: Runtime = request.app.state.runtime
        try:
            return jsonable_encoder(
                runtime.user_model_service.propose_from_confirmed_memory(
                    owner_id=runtime.settings.owner_id,
                    memory_id=memory_id,
                    statement=body.statement,
                    belief_type=body.belief_type,
                    confidence=body.confidence,
                    reason=body.reason,
                )
            )
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/v1/user-model/beliefs")
    async def propose_belief(body: BeliefProposalBody, request: Request) -> object:
        runtime: Runtime = request.app.state.runtime
        try:
            return jsonable_encoder(runtime.user_model_service.propose_belief(
                owner_id=runtime.settings.owner_id,
                belief_key=body.belief_key,
                statement=body.statement,
                belief_type=body.belief_type,
                confidence=body.confidence,
                evidence=body.evidence,
                reason=body.reason,
                valid_from=body.valid_from,
                valid_to=body.valid_to,
            ))
        except (LookupError, ValueError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/v1/user-model/beliefs")
    async def list_beliefs(
        request: Request,
        known_as_of: datetime | None = None,
        valid_at: datetime | None = None,
        include_inactive: bool = False,
    ) -> object:
        runtime: Runtime = request.app.state.runtime
        return jsonable_encoder(runtime.user_model_service.list_beliefs(
            owner_id=runtime.settings.owner_id,
            known_as_of=known_as_of,
            valid_at=valid_at,
            include_inactive=include_inactive,
        ))

    @app.post("/v1/user-model/beliefs/{belief_id}/revisions")
    async def revise_belief(
        belief_id: UUID, body: BeliefRevisionBody, request: Request
    ) -> object:
        runtime: Runtime = request.app.state.runtime
        try:
            return jsonable_encoder(runtime.user_model_service.revise(
                owner_id=runtime.settings.owner_id,
                belief_id=belief_id,
                expected_revision=body.expected_revision,
                statement=body.statement,
                confidence=body.confidence,
                evidence=body.evidence,
                reason=body.reason,
                valid_from=body.valid_from,
                valid_to=body.valid_to,
            ))
        except (LookupError, ValueError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/v1/user-model/beliefs/{belief_id}/transitions")
    async def transition_belief(
        belief_id: UUID, body: BeliefTransitionBody, request: Request
    ) -> object:
        runtime: Runtime = request.app.state.runtime
        try:
            return jsonable_encoder(runtime.user_model_service.transition(
                owner_id=runtime.settings.owner_id,
                belief_id=belief_id,
                revision=body.revision,
                transition_type=body.transition_type,
                reason=body.reason,
                occurred_at=body.occurred_at,
                evidence=body.evidence,
            ))
        except (LookupError, ValueError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/v1/consolidation/proposals")
    async def create_consolidation_proposal(
        body: ConsolidationProposalBody, request: Request
    ) -> object:
        runtime: Runtime = request.app.state.runtime
        try:
            return jsonable_encoder(runtime.consolidation_service.propose(
                owner_id=runtime.settings.owner_id,
                memory_class=body.memory_class,
                content_text=body.content_text,
                evidence=body.evidence,
                detector_version=body.detector_version,
                importance=body.importance,
            ))
        except (LookupError, ValueError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/v1/consolidation/proposals")
    async def list_consolidation_proposals(
        request: Request, status: str = "pending"
    ) -> object:
        runtime: Runtime = request.app.state.runtime
        return jsonable_encoder(runtime.consolidation_service.list_proposals(
            owner_id=runtime.settings.owner_id,
            status=status,
        ))

    @app.post("/v1/consolidation/proposals/{proposal_id}/accept")
    async def accept_consolidation_proposal(
        proposal_id: UUID, body: ConsolidationAcceptBody, request: Request
    ) -> object:
        runtime: Runtime = request.app.state.runtime
        try:
            return jsonable_encoder(runtime.consolidation_service.accept(
                owner_id=runtime.settings.owner_id,
                proposal_id=proposal_id,
                reason=body.reason,
                confidence=body.confidence,
                importance=body.importance,
                corrected_content_text=body.corrected_content_text,
            ))
        except (LookupError, ValueError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/v1/consolidation/proposals/{proposal_id}/reject")
    async def reject_consolidation_proposal(
        proposal_id: UUID, body: ReviewBody, request: Request
    ) -> object:
        runtime: Runtime = request.app.state.runtime
        try:
            return jsonable_encoder(runtime.consolidation_service.reject(
                owner_id=runtime.settings.owner_id,
                proposal_id=proposal_id,
                reason=body.reason,
            ))
        except (LookupError, ValueError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/v1/current-state")
    async def estimate_current_state(body: CurrentStateBody, request: Request) -> object:
        runtime: Runtime = request.app.state.runtime
        try:
            return jsonable_encoder(runtime.current_state_service.estimate(
                owner_id=runtime.settings.owner_id,
                summary=body.summary,
                state=body.state,
                uncertainty=body.uncertainty,
                estimated_at=body.estimated_at,
                expires_at=body.expires_at,
                evidence=body.evidence,
            ))
        except (LookupError, ValueError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/v1/current-state")
    async def get_current_state(request: Request, as_of: datetime | None = None) -> object:
        runtime: Runtime = request.app.state.runtime
        return jsonable_encoder(runtime.current_state_service.current(
            owner_id=runtime.settings.owner_id,
            as_of=as_of,
        ))

    @app.post("/v1/goals")
    async def create_goal(body: GoalCreateBody, request: Request) -> object:
        runtime: Runtime = request.app.state.runtime
        try:
            return jsonable_encoder(runtime.goal_service.create(
                owner_id=runtime.settings.owner_id,
                track=body.track,
                title=body.title,
                why=body.why,
                source_event_id=body.source_event_id,
                priority=body.priority,
                next_action=body.next_action,
                review_at=body.review_at,
            ))
        except (LookupError, ValueError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/v1/goals")
    async def list_goals(request: Request, include_inactive: bool = False) -> object:
        runtime: Runtime = request.app.state.runtime
        return jsonable_encoder(runtime.goal_service.list(
            owner_id=runtime.settings.owner_id,
            include_inactive=include_inactive,
        ))

    @app.post("/v1/goals/{goal_id}/update")
    async def update_goal(
        goal_id: UUID, body: GoalUpdateBody, request: Request
    ) -> object:
        runtime: Runtime = request.app.state.runtime
        try:
            return jsonable_encoder(runtime.goal_service.update(
                owner_id=runtime.settings.owner_id,
                goal_id=goal_id,
                expected_revision=body.expected_revision,
                reason=body.reason,
                title=body.title,
                why=body.why,
                priority=body.priority,
                status=body.status,
                next_action=(
                    body.next_action
                    if "next_action" in body.model_fields_set
                    else GOAL_FIELD_UNSET
                ),
                review_at=(
                    body.review_at
                    if "review_at" in body.model_fields_set
                    else GOAL_FIELD_UNSET
                ),
            ))
        except (LookupError, ValueError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/v1/goals/{goal_id}/progress")
    async def record_goal_progress(
        goal_id: UUID, body: GoalProgressBody, request: Request
    ) -> object:
        runtime: Runtime = request.app.state.runtime
        try:
            return jsonable_encoder(runtime.goal_service.record_progress(
                owner_id=runtime.settings.owner_id,
                goal_id=goal_id,
                expected_goal_revision=body.expected_goal_revision,
                direction=body.direction,
                summary=body.summary,
                observed_at=body.observed_at,
                evidence=body.evidence,
            ))
        except (LookupError, ValueError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/v1/goals/{goal_id}/reminders")
    async def schedule_goal_reminder(
        goal_id: UUID,
        body: GoalReminderBody,
        request: Request,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=1, max_length=200)
        ],
    ) -> object:
        runtime: Runtime = request.app.state.runtime
        try:
            return jsonable_encoder(runtime.proactive_store.enqueue_goal_reminder(
                goal_id=goal_id,
                reminder_kind=body.reminder_kind,
                reminder_text=body.reminder_text,
                remind_at=body.remind_at,
                expires_at=body.expires_at,
                idempotency_key=idempotency_key,
                supersede_existing_slot=body.supersede_existing_slot,
            ))
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/v1/commitments/course-field-authorization")
    async def authorize_commitment_fields(
        body: CommitmentAuthorizationBody, request: Request
    ) -> object:
        runtime: Runtime = request.app.state.runtime
        try:
            return jsonable_encoder(
                runtime.commitment_broker.record_field_authorization(
                    source_sha256=body.source_sha256,
                    authorization_ref=body.authorization_ref,
                )
            )
        except ValueError as error:
            raise HTTPException(status_code=409,detail=str(error)) from error

    @app.post("/v1/commitments/course-reminders/supersede-legacy")
    async def supersede_legacy_course_reminders(
        body: CourseReminderSupersessionBody, request: Request
    ) -> object:
        runtime: Runtime = request.app.state.runtime
        try:
            return jsonable_encoder(
                runtime.commitment_broker.supersede_legacy_course_reminders(
                    source_sha256=body.source_sha256,
                    replacement_generation=body.replacement_generation,
                )
            )
        except LookupError as error:
            raise HTTPException(status_code=404,detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=409,detail=str(error)) from error

    @app.post("/v1/goals/{goal_id}/commitment-projection")
    async def project_commitment(
        goal_id: UUID, body: CommitmentProjectionBody, request: Request
    ) -> object:
        runtime: Runtime = request.app.state.runtime
        try:
            return jsonable_encoder(runtime.commitment_broker.project_goal(
                goal_id=goal_id,
                source_sha256=body.source_sha256,
                entry_id=body.entry_id,
                course_name=body.course_name,
                task_name=body.task_name,
                deadline_at=body.deadline_at,
            ))
        except LookupError as error:
            raise HTTPException(status_code=404,detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=409,detail=str(error)) from error

    @app.get("/scene-simulator", include_in_schema=False)
    async def scene_simulator() -> FileResponse:
        path = Path(__file__).resolve().parents[2] / "apps" / "web" / "scene-simulator.html"
        return FileResponse(path, media_type="text/html")

    @app.get("/", include_in_schema=False)
    @app.get("/chat", include_in_schema=False)
    async def havre_chat() -> FileResponse:
        path = Path(__file__).resolve().parents[2] / "apps" / "web" / "havre-chat.html"
        return FileResponse(
            path,
            media_type="text/html",
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )

    @app.get("/manifest.webmanifest", include_in_schema=False)
    async def pwa_manifest() -> FileResponse:
        path = Path(__file__).resolve().parents[2] / "apps" / "web" / "manifest.webmanifest"
        return FileResponse(
            path,
            media_type="application/manifest+json",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/service-worker.js", include_in_schema=False)
    async def pwa_service_worker() -> FileResponse:
        path = Path(__file__).resolve().parents[2] / "apps" / "web" / "service-worker.js"
        return FileResponse(
            path,
            media_type="text/javascript",
            headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
        )

    @app.get("/assets/{asset_name}", include_in_schema=False)
    async def pwa_asset(asset_name: str) -> FileResponse:
        allowed = {
            "havre-app.css": "text/css",
            "havre-app.js": "text/javascript",
            "havre-icon.svg": "image/svg+xml",
        }
        media_type = allowed.get(asset_name)
        if media_type is None:
            raise HTTPException(status_code=404, detail="asset not found")
        path = Path(__file__).resolve().parents[2] / "apps" / "web" / asset_name
        return FileResponse(
            path,
            media_type=media_type,
            headers={"Cache-Control": "no-cache"},
        )

    @app.post(
        "/v1/scenes",
        status_code=status.HTTP_201_CREATED,
    )
    async def create_scene(
        body: SceneCreateBody,
        request: Request,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=1, max_length=200)
        ],
        traceparent: Annotated[str | None, Header(alias="traceparent")] = None,
    ) -> object:
        runtime: Runtime = request.app.state.runtime
        try:
            result = runtime.scene_service.create(
                scene_type=body.scene_type,
                situation=body.situation,
                planned_goal=body.planned_goal,
                anticipated_triggers=body.anticipated_triggers,
                danger=body.danger,
                avoidance=body.avoidance,
                energy=body.energy,
                coercion=body.coercion,
                goal_alignment=body.goal_alignment,
                goal_urgency=body.goal_urgency,
                privacy_class=body.privacy_class,
                memory_eligible=body.memory_eligible,
                planned_start_at=body.planned_start_at,
                session_id=body.session_id,
                idempotency_key=idempotency_key,
                traceparent=traceparent,
            )
            return jsonable_encoder(result)
        except (LookupError, ValueError, RuntimeError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/v1/scenes/{scene_session_id}")
    async def get_scene(scene_session_id: UUID, request: Request) -> object:
        runtime: Runtime = request.app.state.runtime
        try:
            return jsonable_encoder(
                runtime.scene_service.get(scene_session_id=scene_session_id)
            )
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.post("/v1/scenes/{scene_session_id}/transition")
    async def transition_scene(
        scene_session_id: UUID,
        body: SceneTransitionBody,
        request: Request,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=1, max_length=200)
        ],
        traceparent: Annotated[str | None, Header(alias="traceparent")] = None,
    ) -> object:
        runtime: Runtime = request.app.state.runtime
        try:
            return jsonable_encoder(
                runtime.scene_service.transition(
                    scene_session_id=scene_session_id,
                    expected_revision=body.expected_revision,
                    action=body.action,
                    reason=body.reason,
                    terminal_status=body.terminal_status,
                    idempotency_key=idempotency_key,
                    traceparent=traceparent,
                )
            )
        except (LookupError, ValueError, RuntimeError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/v1/scenes/{scene_session_id}/signals")
    async def record_scene_signal(
        scene_session_id: UUID,
        body: SceneSignalBody,
        request: Request,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=1, max_length=200)
        ],
        traceparent: Annotated[str | None, Header(alias="traceparent")] = None,
    ) -> object:
        runtime: Runtime = request.app.state.runtime
        try:
            return jsonable_encoder(
                runtime.scene_service.signal(
                    scene_session_id=scene_session_id,
                    expected_revision=body.expected_revision,
                    signal_type=body.signal_type,
                    danger=body.danger,
                    avoidance=body.avoidance,
                    energy=body.energy,
                    coercion=body.coercion,
                    goal_alignment=body.goal_alignment,
                    goal_urgency=body.goal_urgency,
                    privacy_class=body.privacy_class,
                    memory_eligible=body.memory_eligible,
                    occurred_at=body.occurred_at,
                    uncertainty_note=body.uncertainty_note,
                    idempotency_key=idempotency_key,
                    traceparent=traceparent,
                )
            )
        except (LookupError, ValueError, RuntimeError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/v1/scenes/{scene_session_id}/actions")
    async def record_scene_action(
        scene_session_id: UUID,
        body: SceneActionBody,
        request: Request,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=1, max_length=200)
        ],
        traceparent: Annotated[str | None, Header(alias="traceparent")] = None,
    ) -> object:
        runtime: Runtime = request.app.state.runtime
        try:
            return jsonable_encoder(
                runtime.scene_service.record_action(
                    scene_session_id=scene_session_id,
                    expected_revision=body.expected_revision,
                    action_text=body.action,
                    action_attempted=body.action_attempted,
                    occurred_at=body.occurred_at,
                    privacy_class=body.privacy_class,
                    memory_eligible=body.memory_eligible,
                    uncertainty_note=body.uncertainty_note,
                    idempotency_key=idempotency_key,
                    traceparent=traceparent,
                )
            )
        except (LookupError, ValueError, RuntimeError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/v1/scenes/{scene_session_id}/outcomes")
    async def record_scene_outcome(
        scene_session_id: UUID,
        body: SceneOutcomeBody,
        request: Request,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=1, max_length=200)
        ],
        traceparent: Annotated[str | None, Header(alias="traceparent")] = None,
    ) -> object:
        runtime: Runtime = request.app.state.runtime
        try:
            return jsonable_encoder(
                runtime.scene_service.record_outcome(
                    scene_session_id=scene_session_id,
                    expected_revision=body.expected_revision,
                    outcome_text=body.outcome,
                    occurred_at=body.occurred_at,
                    privacy_class=body.privacy_class,
                    memory_eligible=body.memory_eligible,
                    uncertainty_note=body.uncertainty_note,
                    idempotency_key=idempotency_key,
                    traceparent=traceparent,
                )
            )
        except (LookupError, ValueError, RuntimeError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/v1/scenes/{scene_session_id}/reflection")
    async def record_scene_reflection(
        scene_session_id: UUID,
        body: SceneReflectionBody,
        request: Request,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=1, max_length=200)
        ],
        traceparent: Annotated[str | None, Header(alias="traceparent")] = None,
    ) -> object:
        runtime: Runtime = request.app.state.runtime
        try:
            return jsonable_encoder(
                runtime.scene_service.reflect(
                    scene_session_id=scene_session_id,
                    expected_revision=body.expected_revision,
                    reflection_text=body.reflection,
                    next_adjustment=body.next_adjustment,
                    planned_scene_status=body.planned_scene_status,
                    helpfulness=body.helpfulness,
                    too_passive=body.too_passive,
                    too_forceful=body.too_forceful,
                    later_regret=body.later_regret,
                    privacy_class=body.privacy_class,
                    memory_eligible=body.memory_eligible,
                    consented=body.consented,
                    idempotency_key=idempotency_key,
                    traceparent=traceparent,
                )
            )
        except (LookupError, ValueError, RuntimeError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/v1/proactive/preferences")
    async def save_proactive_preferences(
        body: ProactivePreferenceBody, request: Request
    ) -> object:
        runtime: Runtime = request.app.state.runtime
        preference = ProactivePreferenceRevision(
            owner_id=runtime.settings.owner_id,
            revision=body.revision,
            global_enabled=body.global_enabled,
            category_permissions=body.category_permissions,
            allowed_channels=body.allowed_channels,
            preview_policy=body.preview_policy,
            global_budget_per_24h=body.global_budget_per_24h,
            category_budget_per_24h=body.category_budget_per_24h,
            cooldown_seconds=body.cooldown_seconds,
            generic_push_for_local_only=body.generic_push_for_local_only,
            stopped_subject_refs=body.stopped_subject_refs,
            authorization_ref=body.authorization_ref,
        )
        try:
            runtime.proactive_store.save_preference(preference)
            return jsonable_encoder(preference)
        except (LookupError, ValueError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/v1/proactive/simulations/reach-out")
    async def simulate_proactive_reach_out(
        body: ProactiveSimulationBody,
        request: Request,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=1, max_length=200)
        ],
        traceparent: Annotated[str | None, Header(alias="traceparent")] = None,
    ) -> object:
        runtime: Runtime = request.app.state.runtime
        try:
            return jsonable_encoder(
                runtime.proactive_store.execute_fixture(
                    trigger_type=body.trigger_type,
                    source_kind=body.source_kind,
                    source_refs=body.source_refs,
                    subject_refs=body.subject_refs,
                    category=body.category,
                    reason_code=body.reason_code,
                    reason_summary=body.reason_summary,
                    intended_benefit=body.intended_benefit,
                    data_policy=_stable_proactive_policy(
                        owner_id=runtime.settings.owner_id,
                        privacy_class=body.privacy_class,
                        memory_eligible=body.memory_eligible,
                    ),
                    preference_revision=body.preference_revision,
                    idempotency_key=idempotency_key,
                    observed_at=body.observed_at,
                    earliest_eligible_at=body.earliest_eligible_at,
                    expires_at=body.expires_at,
                    deduplication_key=body.deduplication_key,
                    traceparent=traceparent,
                )
            )
        except (LookupError, ValueError, RuntimeError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/v1/proactive/proposals/{proposal_id}")
    async def get_proactive_proposal(proposal_id: UUID, request: Request) -> object:
        runtime: Runtime = request.app.state.runtime
        try:
            return jsonable_encoder(
                runtime.proactive_store.get(proposal_id=proposal_id)
            )
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.post("/v1/proactive/proposals/{proposal_id}/actions")
    async def record_proactive_owner_action(
        proposal_id: UUID,
        body: ProactiveOwnerActionBody,
        request: Request,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=1, max_length=200)
        ],
    ) -> object:
        runtime: Runtime = request.app.state.runtime
        try:
            return jsonable_encoder(
                runtime.proactive_store.record_owner_action(
                    proposal_id=proposal_id,
                    action_type=body.action_type,
                    idempotency_key=idempotency_key,
                    reason=body.reason,
                    observed_at=body.observed_at,
                    response_event_id=body.response_event_id,
                    snooze_until=body.snooze_until,
                )
            )
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except (ValueError, RuntimeError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/v1/proactive/proposals/{proposal_id}/delivery-reconciliation")
    async def reconcile_proactive_delivery(
        proposal_id: UUID, request: Request
    ) -> object:
        runtime: Runtime = request.app.state.runtime
        try:
            return jsonable_encoder(
                runtime.proactive_store.reconcile_delivery(proposal_id=proposal_id)
            )
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/v1/proactive/inbox")
    async def list_proactive_inbox(
        request: Request, limit: int = 100
    ) -> object:
        runtime: Runtime = request.app.state.runtime
        try:
            return jsonable_encoder(
                {
                    "schema_version": 1,
                    "items": runtime.proactive_store.list_pending_inbox(limit=limit),
                }
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/v1/mobile/enrollment")
    async def mobile_enrollment(request: Request) -> object:
        runtime: Runtime = request.app.state.runtime
        identity = runtime.service.identity
        return jsonable_encoder(MobileEnrollmentReceipt(
            owner_id=runtime.settings.owner_id,
            core_binding_id=f"owner:{runtime.settings.owner_id}",
            constitution_version_id=identity.constitution.version_id,
            identity_version_id=identity.identity.version_id,
            values_version_id=identity.values.version_id,
            governance_version=identity.governance_version,
        ))

    @app.post("/v1/context/observations", response_model=ContextIngestResult)
    async def ingest_context_observation(
        body: ContextObservationDraft, request: Request
    ) -> ContextIngestResult:
        runtime: Runtime = request.app.state.runtime
        try:
            return runtime.context_store.ingest(body)
        except ContextIdempotencyConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ContextIngestRejected as error:
            raise HTTPException(status_code=403, detail=str(error)) from error

    @app.post(
        "/v1/context/collection-permit", response_model=ContextCollectionPermit
    )
    async def issue_context_collection_permit(
        body: ContextCollectionPermitRequest, request: Request
    ) -> ContextCollectionPermit:
        runtime: Runtime = request.app.state.runtime
        try:
            return runtime.context_store.issue_collection_permit(body)
        except ContextIngestRejected as error:
            raise HTTPException(status_code=403, detail=str(error)) from error

    @app.post("/v1/context/health", response_model=ContextSourceHealthV2)
    async def ingest_context_health(
        body: ContextSourceHealthDraft, request: Request
    ) -> ContextSourceHealthV2:
        runtime: Runtime = request.app.state.runtime
        try:
            return runtime.context_store.ingest_health(body)
        except ContextIngestRejected as error:
            raise HTTPException(status_code=403, detail=str(error)) from error

    @app.post("/v1/proactive/work")
    async def enqueue_proactive_work(
        body: ProactiveWorkBody,
        request: Request,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=1, max_length=200)
        ],
        traceparent: Annotated[str | None, Header(alias="traceparent")] = None,
    ) -> object:
        runtime: Runtime = request.app.state.runtime
        command = ProactiveWorkCommand(
            trigger_type=body.trigger_type,
            source_kind=body.source_kind,
            source_refs=body.source_refs,
            subject_refs=body.subject_refs,
            category=body.category,
            reason_code=body.reason_code,
            reason_summary=body.reason_summary,
            intended_benefit=body.intended_benefit,
            data_policy=_stable_proactive_policy(
                owner_id=runtime.settings.owner_id,
                privacy_class=body.privacy_class,
                memory_eligible=body.memory_eligible,
            ),
            preference_revision=body.preference_revision,
            execution_idempotency_key=(
                f"proactive-work:{body.work_kind}:{idempotency_key}"
            ),
            observed_at=body.observed_at,
            earliest_eligible_at=body.earliest_eligible_at,
            expires_at=body.expires_at,
            deduplication_key=body.deduplication_key,
            traceparent=traceparent,
        )
        try:
            work_item_id = runtime.proactive_store.enqueue_work(
                work_kind=body.work_kind,
                idempotency_key=idempotency_key,
                command=command,
                not_before=body.not_before,
            )
            return {"work_item_id": str(work_item_id), "status": "pending"}
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/v1/proactive/work/run-once")
    async def run_proactive_work(request: Request) -> object:
        runtime: Runtime = request.app.state.runtime
        evaluation = runtime.proactive_evaluator.run_once()
        work = runtime.proactive_store.run_work_once()
        delivery = runtime.web_push_provider.deliver_pending()
        return jsonable_encoder({"evaluation": evaluation, "work": work, "web_push": delivery})

    @app.post("/v1/offline/jobs")
    async def enqueue_offline_job(
        body: OfflineJobBody,
        request: Request,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=1, max_length=200)
        ],
    ) -> object:
        runtime: Runtime = request.app.state.runtime
        try:
            job_id = runtime.offline_store.enqueue(
                job_type=body.job_type,
                window_start=body.window_start,
                window_end=body.window_end,
                idempotency_key=idempotency_key,
            )
            return {"job_id": str(job_id), "status": "pending"}
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/v1/offline/jobs/run-once")
    async def run_offline_job(request: Request) -> object:
        runtime: Runtime = request.app.state.runtime
        return jsonable_encoder(runtime.offline_store.run_once())

    @app.post("/v1/offline/datasets/rebuild")
    async def rebuild_offline_dataset(request: Request) -> object:
        runtime: Runtime = request.app.state.runtime
        snapshot, manifest = runtime.offline_store.build_canonical_dataset_snapshot()
        return jsonable_encoder({"snapshot": snapshot, "manifest": manifest})

    @app.post("/v1/offline/memory-lifecycle/{proposal_id}/review")
    async def review_offline_memory_lifecycle(
        proposal_id: UUID,
        body: MemoryLifecycleReviewBody,
        request: Request,
    ) -> object:
        runtime: Runtime = request.app.state.runtime
        try:
            return jsonable_encoder(
                runtime.offline_store.review_memory_lifecycle(
                    lifecycle_proposal_id=proposal_id,
                    decision=body.decision,
                    reason=body.reason,
                )
            )
        except (LookupError, ValueError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    return app
