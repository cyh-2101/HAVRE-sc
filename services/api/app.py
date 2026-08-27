"""FastAPI ingress for the active HAVRE Stage 10 slice."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
import asyncio
import json
import secrets
from typing import Annotated, Literal
from uuid import UUID, uuid5

from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from companion import __version__
from companion.evidence import EvidenceRef
from companion.ids import uuid7
from companion.mobile import MobileEnrollmentReceipt
from companion.life_context import (
    ContextIngestResult,
    ContextCollectionPermit,
    ContextCollectionPermitRequest,
    ContextObservationDraft,
    ContextSourceHealthDraft,
    ContextSourceHealthV2,
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
from companion.user_model.models import BeliefTransitionType, BeliefType
from mlsys.serving import ProviderInferenceError, ProviderVersionError
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


class ReviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    reason: str = Field(min_length=1, max_length=1000)


class AcceptReviewBody(ReviewBody):
    importance: float | None = Field(default=None, ge=0, le=1)


class CorrectMemoryBody(ReviewBody):
    content_text: str = Field(min_length=1, max_length=100_000)


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


def create_app(settings: Settings | None = None) -> FastAPI:
    # Stage 12 context is an explicit overlay. The Stage 10 baseline must remain
    # runnable with no enrolled device; its resolver then fails closed on every
    # context request instead of making the entire API fail at import/startup.
    resolved = settings or Settings.from_env(require_context_device=False)
    metrics = OperationalMetrics()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime = build_runtime(resolved)
        app.state.runtime = runtime
        try:
            yield
        finally:
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

    @app.middleware("http")
    async def owner_auth_and_metrics(request: Request, call_next):
        started = metrics.timer()
        protected = request.url.path.startswith("/v1/") or request.url.path == "/metrics"
        device_authenticated = request.url.path in {
            "/v1/context/collection-permit",
            "/v1/context/observations",
            "/v1/context/health",
        }
        desktop_bootstrap_request = request.url.path == "/v1/desktop/session"
        if (
            protected and not device_authenticated and not desktop_bootstrap_request
            and resolved.owner_api_token is not None
        ):
            authorization = request.headers.get("authorization", "")
            expected = f"Bearer {resolved.owner_api_token}"
            cookie = request.cookies.get("havre_owner_session", "")
            if not (
                secrets.compare_digest(authorization, expected)
                or secrets.compare_digest(cookie, resolved.owner_api_token)
            ):
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

    @app.post("/v1/desktop/session", include_in_schema=False)
    async def desktop_session(
        desktop_bootstrap: Annotated[
            str | None, Header(alias="X-HAVRE-Desktop-Bootstrap")
        ] = None,
    ) -> JSONResponse:
        if (
            resolved.deployment_environment != "development"
            or resolved.desktop_bootstrap_token is None
            or resolved.owner_api_token is None
            or desktop_bootstrap is None
            or not secrets.compare_digest(
                desktop_bootstrap, resolved.desktop_bootstrap_token
            )
        ):
            raise HTTPException(status_code=403, detail="desktop bootstrap rejected")
        response = JSONResponse({"status": "owner_session_ready"})
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
        provider_health = await runtime.service.provider.health()
        provider_version = await runtime.service.provider.version()
        if runtime.release_manifest is not None:
            require_provider_version_binding(
                components=runtime.release_manifest.components,
                provider_version=provider_version,
            )
        database = runtime.operations_store.readiness()
        preflight_ready = provider_health.status == "healthy"
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
            provider_version = await runtime.service.provider.version()
        except ProviderVersionError as error:
            raise HTTPException(
                status_code=(503 if error.retryable else 502),
                detail={
                    "code": error.code,
                    "retryable": error.retryable,
                    "message": error.safe_message,
                },
            ) from error
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
                result = await runtime.service.interact(
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
            except InferenceTimeoutError:
                yield json.dumps(
                    {"type": "error", "message": "HAVRE timed out before completing the response."},
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
        return jsonable_encoder(runtime.proactive_store.run_work_once())

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


app = create_app()
