"""Stage 1 event envelope and payload contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from companion.hashing import content_hash
from companion.goals.models import GoalProjectionMaterial
from companion.ids import uuid7
from companion.policy import DataPolicy, PrivacyClass
from companion.policy.response import ResponsePolicyDecision


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _normalized_utc(value: datetime, *, field_name: str) -> datetime:
    if value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


class TextContentPart(StrictModel):
    type: Literal["text"] = "text"
    text: str = Field(min_length=1, max_length=100_000)


ContentPart = Annotated[TextContentPart, Field(discriminator="type")]


class UserMessagePayload(StrictModel):
    content_parts: tuple[ContentPart, ...] = Field(min_length=1)
    channel: Literal["api", "cli", "web"]
    language: str | None = Field(default=None, max_length=35)
    reply_to_event_id: UUID | None = None
    client_created_at: datetime | None = None


class DeliveryRecord(StrictModel):
    channel: Literal["api", "cli", "web"]
    first_visible_at: datetime
    completed_at: datetime

    @field_validator("first_visible_at", "completed_at")
    @classmethod
    def normalize_delivery_times(cls, value: datetime, info) -> datetime:
        return _normalized_utc(value, field_name=info.field_name)


class AssistantMessagePayload(StrictModel):
    content_parts: tuple[ContentPart, ...] = Field(min_length=1)
    status: Literal["completed", "interrupted"]
    inference_response_id: UUID
    context_pack_id: UUID
    policy_decision_id: UUID | None = None
    response_policy_decision: ResponsePolicyDecision | None = None
    delivery: DeliveryRecord

    @model_validator(mode="after")
    def validate_response_policy_binding(self) -> "AssistantMessagePayload":
        if (self.policy_decision_id is None) != (self.response_policy_decision is None):
            raise ValueError("response policy ID and decision must be supplied together")
        if (
            self.response_policy_decision is not None
            and self.policy_decision_id != self.response_policy_decision.decision_id
        ):
            raise ValueError("response policy decision ID mismatch")
        return self


class ProactiveAssistantMessagePayload(StrictModel):
    """Message made visible only after a successful local Web/inbox attempt."""

    content_parts: tuple[ContentPart, ...] = Field(min_length=1)
    status: Literal["completed"] = "completed"
    interaction_mode: Literal["proactive_web_inbox"] = "proactive_web_inbox"
    proposal_id: UUID
    interruption_decision_id: UUID
    proactive_context_pack_id: UUID
    rendering_id: UUID
    delivery_attempt_id: UUID
    renderer_version: Literal[
        "proactive-template-v1", "proactive-natural-template-v2"
    ] = "proactive-natural-template-v2"
    delivery: DeliveryRecord
    simulation_only: Literal[True] = True
    external_delivery_authorized: Literal[False] = False


class SceneGuidancePayload(StrictModel):
    """Deterministic low-bandwidth guidance actually shown in the Web simulation."""

    content_parts: tuple[ContentPart, ...] = Field(min_length=1)
    status: Literal["completed"] = "completed"
    interaction_mode: Literal["scene_guidance"] = "scene_guidance"
    intervention_decision_id: UUID
    renderer_version: Literal["scene-guidance-template-v1"] = (
        "scene-guidance-template-v1"
    )
    delivery: DeliveryRecord


class SceneSessionLifecyclePayload(StrictModel):
    scene_session_id: UUID
    scene_revision: int = Field(gt=0)
    action: Literal[
        "planned", "started", "phase_changed", "paused", "resumed", "ended"
    ]
    phase: Literal["before", "during", "after", "closed"]
    status: Literal[
        "planned", "active", "paused", "completed", "abandoned", "cancelled"
    ]
    reason: str = Field(min_length=1, max_length=2_000)
    situation: dict[str, object] | None = None
    planned_goal: dict[str, object] | None = None
    anticipated_triggers: tuple[dict[str, object], ...] | None = None

    @model_validator(mode="after")
    def validate_planning_material(self) -> "SceneSessionLifecyclePayload":
        planning = self.action == "planned"
        supplied = all(
            value is not None
            for value in (
                self.situation,
                self.planned_goal,
                self.anticipated_triggers,
            )
        )
        if planning != supplied:
            raise ValueError("only planned events contain complete planning material")
        if self.action == "planned" and (
            self.scene_revision != 1
            or self.phase != "before"
            or self.status != "planned"
        ):
            raise ValueError("planned Scene event must create Before/planned revision 1")
        return self


class SceneSignalPayload(StrictModel):
    scene_session_id: UUID
    scene_record_id: UUID
    signal_type: Literal[
        "anxious", "avoidance_urge", "frozen", "unsure_next_step", "need_help"
    ]
    danger: Literal["low", "uncertain", "plausible", "immediate"]
    avoidance: Literal["low", "present", "high", "unknown"]
    energy: Literal["adequate", "low", "exhausted", "unknown"]
    coercion: Literal["absent", "uncertain", "present"]
    goal_alignment: Literal["active_meaningful", "unclear", "no_active_goal"]
    goal_urgency: Literal["low", "normal", "urgent", "unknown"]
    input_method: Literal["web_simulation"] = "web_simulation"
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def normalize_occurred_at(cls, value: datetime) -> datetime:
        return _normalized_utc(value, field_name="occurred_at")


class InterventionLifecyclePayload(StrictModel):
    scene_session_id: UUID
    intervention_decision_id: UUID
    scene_record_id: UUID
    input_record_id: UUID | None = None
    guidance_event_id: UUID
    branch: Literal[
        "safety_first", "clarification", "recovery", "minimum_action",
        "preparation", "reflection"
    ]
    policy_version: Literal["intervention-policy-sim-v1"] = (
        "intervention-policy-sim-v1"
    )
    outreach_authorized: Literal[False] = False
    simulation_only: Literal[True] = True


class SceneActionPayload(StrictModel):
    scene_session_id: UUID
    scene_record_id: UUID
    intervention_record_id: UUID
    action: str = Field(min_length=1, max_length=2_000)
    action_attempted: Literal["yes", "no", "unknown"]
    reporter: Literal["user"] = "user"
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def normalize_occurred_at(cls, value: datetime) -> datetime:
        return _normalized_utc(value, field_name="occurred_at")


class SceneOutcomePayload(StrictModel):
    scene_session_id: UUID
    scene_record_id: UUID
    action_record_id: UUID
    outcome: str = Field(min_length=1, max_length=4_000)
    reporter: Literal["user"] = "user"
    observation_scope: Literal["self_report"] = "self_report"
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def normalize_occurred_at(cls, value: datetime) -> datetime:
        return _normalized_utc(value, field_name="occurred_at")


class SceneReflectionPayload(StrictModel):
    scene_session_id: UUID
    scene_record_id: UUID
    outcome_record_id: UUID
    outcome_observation_id: UUID
    reflection: str = Field(min_length=1, max_length=4_000)
    next_adjustment: str | None = Field(default=None, max_length=2_000)


class MemoryLifecyclePayload(StrictModel):
    memory_id: UUID
    memory_revision: int = Field(gt=0)
    action: Literal["created", "revised", "retracted"]
    reason: str = Field(min_length=1, max_length=1000)
    candidate_id: UUID | None = None


class BeliefLifecyclePayload(StrictModel):
    belief_id: UUID
    belief_revision: int = Field(gt=0)
    action: Literal["created", "revised"]
    reason: str = Field(min_length=1, max_length=2000)
    previous_revision: int | None = Field(default=None, gt=0)


class BeliefTransitionPayload(StrictModel):
    belief_transition_id: UUID
    belief_id: UUID
    belief_revision: int = Field(gt=0)
    transition_type: Literal[
        "activated",
        "counter_evidence_recorded",
        "contradicted",
        "superseded",
        "retracted",
        "invalidated",
    ]
    reason: str = Field(min_length=1, max_length=2000)
    replacement_belief_id: UUID | None = None
    replacement_revision: int | None = Field(default=None, gt=0)


class CurrentStateLifecyclePayload(StrictModel):
    state_snapshot_id: UUID
    expires_at: datetime
    estimator_version: str = Field(min_length=1, max_length=200)


class ConsolidationLifecyclePayload(StrictModel):
    proposal_id: UUID
    action: Literal["proposed", "accepted", "accepted_with_correction", "rejected"]
    memory_class: Literal["semantic", "pattern", "progress"]
    reason: str = Field(min_length=1, max_length=2000)
    memory_id: UUID | None = None
    memory_revision: int | None = Field(default=None, gt=0)


class GoalLifecyclePayload(StrictModel):
    goal_id: UUID
    goal_revision: int = Field(gt=0)
    action: Literal["created", "updated", "completed"]
    track: Literal["reality", "inner_life"]
    title: str = Field(min_length=1, max_length=500)
    why: str = Field(min_length=1, max_length=2000)
    priority: Literal["low", "normal", "high"]
    status: Literal["active", "paused", "completed", "abandoned"]
    next_action: str | None = Field(default=None, max_length=2000)
    review_at: datetime | None = None
    reason: str = Field(min_length=1, max_length=2000)
    projection_content_hash: str | None = Field(
        default=None, pattern=r"^sha256:[0-9a-f]{64}$"
    )
    projection_canonical_json: str | None = None

    @model_validator(mode="after")
    def validate_projection_binding(self) -> "GoalLifecyclePayload":
        if (self.projection_content_hash is None) != (
            self.projection_canonical_json is None
        ):
            raise ValueError("Goal projection hash and material must appear together")
        if self.projection_canonical_json is None:
            # Historical events created before additive migration 0009 do not
            # carry this binding. New repository writes always supply it.
            return self
        try:
            material = GoalProjectionMaterial.model_validate_json(
                self.projection_canonical_json
            )
        except (ValueError, TypeError) as error:
            raise ValueError(
                "Goal projection material must satisfy the strict contract"
            ) from error
        if material.canonical_json() != self.projection_canonical_json:
            raise ValueError("Goal projection material must use canonical JSON")
        if material.projection_hash() != self.projection_content_hash:
            raise ValueError("Goal projection hash does not match its material")
        return self


class ProgressLifecyclePayload(StrictModel):
    progress_record_id: UUID
    goal_id: UUID
    goal_revision: int = Field(gt=0)
    direction: Literal["toward", "steady", "away", "unknown"]
    observed_at: datetime


class InteractionFailurePayload(StrictModel):
    """Content-free terminal failure evidence for an undelivered interaction."""

    status: Literal["failed"] = "failed"
    failure_stage: Literal[
        "context_build", "capability_check", "routing", "version_check", "inference"
    ] = "inference"
    inference_request_id: UUID | None = None
    context_pack_id: UUID | None = None
    route_decision_id: UUID | None = None
    failure_code: str = Field(min_length=1, max_length=100)
    retryable: bool
    safe_message: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_stage_lineage(self) -> "InteractionFailurePayload":
        if self.failure_stage == "context_build":
            if any(
                value is not None
                for value in (
                    self.context_pack_id,
                    self.inference_request_id,
                    self.route_decision_id,
                )
            ):
                raise ValueError(
                    "context-build failures cannot claim context, route, or inference lineage"
                )
            return self
        if self.context_pack_id is None:
            raise ValueError("post-context failure stages require a ContextPack identifier")
        routed = self.failure_stage in {"version_check", "inference"}
        has_inference = self.inference_request_id is not None
        has_route = self.route_decision_id is not None
        if (routed and not (has_inference and has_route)) or (
            not routed and (has_inference or has_route)
        ):
            raise ValueError(
                "routed failure stages require inference and route identifiers"
            )
        return self


class ContextConsentLifecyclePayload(StrictModel):
    consent_scope_id: UUID
    consent_scope_revision_id: UUID
    revision: int = Field(gt=0)
    action: Literal["activated", "revoked", "expired"]
    source_instance_id: UUID
    capability_revision_id: UUID
    consent_content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ContextSourceLifecyclePayload(StrictModel):
    source_instance_id: UUID
    state_revision_id: UUID
    revision: int = Field(gt=0)
    action: Literal["enabled", "disabled"]
    reason: Literal["registered", "owner_disabled", "lost_device", "key_rotated"]
    source_content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    state_content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ContextCapabilityLifecyclePayload(StrictModel):
    source_instance_id: UUID
    capability_revision_id: UUID
    state_revision_id: UUID
    revision: int = Field(gt=0)
    action: Literal["enabled", "disabled"]
    reason: Literal["registered", "owner_disabled", "source_disabled"]
    capability_content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    state_content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class LifeContextObservedPayload(StrictModel):
    observation_id: UUID
    source_instance_id: UUID
    capability_revision_id: UUID
    consent_scope_revision_id: UUID
    observation_kind: Literal[
        "device_activity_summary", "calendar_availability_window"
    ]
    observation_content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class EventType(StrEnum):
    USER_MESSAGE = "USER_MESSAGE"
    ASSISTANT_MESSAGE = "ASSISTANT_MESSAGE"
    INTERACTION_FAILED = "INTERACTION_FAILED"
    MEMORY_CREATED = "MEMORY_CREATED"
    MEMORY_REVISED = "MEMORY_REVISED"
    MEMORY_RETRACTED = "MEMORY_RETRACTED"
    CURRENT_STATE_ESTIMATED = "CURRENT_STATE_ESTIMATED"
    USER_BELIEF_CREATED = "USER_BELIEF_CREATED"
    USER_BELIEF_REVISED = "USER_BELIEF_REVISED"
    USER_BELIEF_TRANSITIONED = "USER_BELIEF_TRANSITIONED"
    CONSOLIDATION_PROPOSED = "CONSOLIDATION_PROPOSED"
    CONSOLIDATION_REVIEWED = "CONSOLIDATION_REVIEWED"
    GOAL_CREATED = "GOAL_CREATED"
    GOAL_UPDATED = "GOAL_UPDATED"
    GOAL_COMPLETED = "GOAL_COMPLETED"
    PROGRESS_RECORDED = "PROGRESS_RECORDED"
    SCENE_SESSION_PLANNED = "SCENE_SESSION_PLANNED"
    SCENE_SESSION_STARTED = "SCENE_SESSION_STARTED"
    SCENE_PHASE_CHANGED = "SCENE_PHASE_CHANGED"
    SCENE_SESSION_PAUSED = "SCENE_SESSION_PAUSED"
    SCENE_SESSION_ENDED = "SCENE_SESSION_ENDED"
    USER_SIGNAL = "USER_SIGNAL"
    INTERVENTION_DECIDED = "INTERVENTION_DECIDED"
    USER_ACTION_REPORTED = "USER_ACTION_REPORTED"
    OUTCOME_REPORTED = "OUTCOME_REPORTED"
    REFLECTION_CREATED = "REFLECTION_CREATED"
    CONTEXT_CONSENT_REVISED = "CONTEXT_CONSENT_REVISED"
    CONTEXT_SOURCE_STATE_REVISED = "CONTEXT_SOURCE_STATE_REVISED"
    CONTEXT_CAPABILITY_STATE_REVISED = "CONTEXT_CAPABILITY_STATE_REVISED"
    LIFE_CONTEXT_OBSERVED = "LIFE_CONTEXT_OBSERVED"


class EventEnvelope(StrictModel):
    schema_version: Literal[1] = 1
    event_id: UUID = Field(default_factory=uuid7)
    event_type: EventType
    event_version: Literal[1] = 1
    owner_id: UUID
    session_id: UUID
    scene_session_id: UUID | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    request_id: UUID
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    causation_event_id: UUID | None = None
    data_policy: DataPolicy
    payload: (
        UserMessagePayload
        | AssistantMessagePayload
        | SceneGuidancePayload
        | ProactiveAssistantMessagePayload
        | InteractionFailurePayload
        | MemoryLifecyclePayload
        | BeliefLifecyclePayload
        | BeliefTransitionPayload
        | CurrentStateLifecyclePayload
        | ConsolidationLifecyclePayload
        | GoalLifecyclePayload
        | ProgressLifecyclePayload
        | SceneSessionLifecyclePayload
        | SceneSignalPayload
        | InterventionLifecyclePayload
        | SceneActionPayload
        | SceneOutcomePayload
        | SceneReflectionPayload
        | ContextConsentLifecyclePayload
        | ContextSourceLifecyclePayload
        | ContextCapabilityLifecyclePayload
        | LifeContextObservedPayload
    )
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_hash: str = ""

    @model_validator(mode="after")
    def validate_payload_and_hash(self) -> "EventEnvelope":
        if isinstance(self.payload, UserMessagePayload):
            expected_type = EventType.USER_MESSAGE
        elif isinstance(
            self.payload,
            (AssistantMessagePayload, SceneGuidancePayload, ProactiveAssistantMessagePayload),
        ):
            expected_type = EventType.ASSISTANT_MESSAGE
        elif isinstance(self.payload, InteractionFailurePayload):
            expected_type = EventType.INTERACTION_FAILED
        elif isinstance(self.payload, MemoryLifecyclePayload):
            expected_type = {
                "created": EventType.MEMORY_CREATED,
                "revised": EventType.MEMORY_REVISED,
                "retracted": EventType.MEMORY_RETRACTED,
            }[self.payload.action]
        elif isinstance(self.payload, BeliefLifecyclePayload):
            expected_type = {
                "created": EventType.USER_BELIEF_CREATED,
                "revised": EventType.USER_BELIEF_REVISED,
            }[self.payload.action]
        elif isinstance(self.payload, BeliefTransitionPayload):
            expected_type = EventType.USER_BELIEF_TRANSITIONED
        elif isinstance(self.payload, CurrentStateLifecyclePayload):
            expected_type = EventType.CURRENT_STATE_ESTIMATED
        elif isinstance(self.payload, ConsolidationLifecyclePayload):
            expected_type = (
                EventType.CONSOLIDATION_PROPOSED
                if self.payload.action == "proposed"
                else EventType.CONSOLIDATION_REVIEWED
            )
        elif isinstance(self.payload, GoalLifecyclePayload):
            expected_type = {
                "created": EventType.GOAL_CREATED,
                "updated": EventType.GOAL_UPDATED,
                "completed": EventType.GOAL_COMPLETED,
            }[self.payload.action]
        elif isinstance(self.payload, ProgressLifecyclePayload):
            expected_type = EventType.PROGRESS_RECORDED
        elif isinstance(self.payload, SceneSessionLifecyclePayload):
            expected_type = {
                "planned": EventType.SCENE_SESSION_PLANNED,
                "started": EventType.SCENE_SESSION_STARTED,
                "phase_changed": EventType.SCENE_PHASE_CHANGED,
                "paused": EventType.SCENE_SESSION_PAUSED,
                "resumed": EventType.SCENE_SESSION_STARTED,
                "ended": EventType.SCENE_SESSION_ENDED,
            }[self.payload.action]
        elif isinstance(self.payload, SceneSignalPayload):
            expected_type = EventType.USER_SIGNAL
        elif isinstance(self.payload, InterventionLifecyclePayload):
            expected_type = EventType.INTERVENTION_DECIDED
        elif isinstance(self.payload, SceneActionPayload):
            expected_type = EventType.USER_ACTION_REPORTED
        elif isinstance(self.payload, SceneOutcomePayload):
            expected_type = EventType.OUTCOME_REPORTED
        elif isinstance(self.payload, ContextConsentLifecyclePayload):
            expected_type = EventType.CONTEXT_CONSENT_REVISED
        elif isinstance(self.payload, ContextSourceLifecyclePayload):
            expected_type = EventType.CONTEXT_SOURCE_STATE_REVISED
        elif isinstance(self.payload, ContextCapabilityLifecyclePayload):
            expected_type = EventType.CONTEXT_CAPABILITY_STATE_REVISED
        elif isinstance(self.payload, LifeContextObservedPayload):
            expected_type = EventType.LIFE_CONTEXT_OBSERVED
        else:
            expected_type = EventType.REFLECTION_CREATED
        if self.event_type is not expected_type:
            raise ValueError("event_type does not match payload")
        material = self.model_dump(mode="json", exclude={"recorded_at", "content_hash"})
        expected_hash = content_hash(material)
        if self.content_hash and self.content_hash != expected_hash:
            raise ValueError("content_hash does not match the event envelope")
        object.__setattr__(self, "content_hash", expected_hash)
        return self
