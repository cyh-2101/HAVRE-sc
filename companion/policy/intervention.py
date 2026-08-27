"""Versioned, conservative Stage 5 intervention-policy contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from companion.hashing import content_hash
from companion.ids import uuid7
from companion.policy.models import DataPolicy


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SceneSignalType(StrEnum):
    ANXIOUS = "anxious"
    AVOIDANCE_URGE = "avoidance_urge"
    FROZEN = "frozen"
    UNSURE_NEXT_STEP = "unsure_next_step"
    NEED_HELP = "need_help"


class DangerAssessment(StrEnum):
    LOW = "low"
    UNCERTAIN = "uncertain"
    PLAUSIBLE = "plausible"
    IMMEDIATE = "immediate"


class AvoidanceAssessment(StrEnum):
    LOW = "low"
    PRESENT = "present"
    HIGH = "high"
    UNKNOWN = "unknown"


class EnergyAssessment(StrEnum):
    ADEQUATE = "adequate"
    LOW = "low"
    EXHAUSTED = "exhausted"
    UNKNOWN = "unknown"


class CoercionAssessment(StrEnum):
    ABSENT = "absent"
    UNCERTAIN = "uncertain"
    PRESENT = "present"


class GoalAlignment(StrEnum):
    ACTIVE_MEANINGFUL = "active_meaningful"
    UNCLEAR = "unclear"
    NO_ACTIVE_GOAL = "no_active_goal"


class GoalUrgency(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    URGENT = "urgent"
    UNKNOWN = "unknown"


class InterventionBranch(StrEnum):
    SAFETY_FIRST = "safety_first"
    CLARIFICATION = "clarification"
    RECOVERY = "recovery"
    MINIMUM_ACTION = "minimum_action"
    PREPARATION = "preparation"
    REFLECTION = "reflection"


class InterventionContext(StrictModel):
    """Categorical, user-visible inputs to policy; no hidden score is inferred."""

    schema_version: Literal[1] = 1
    owner_id: UUID
    scene_session_id: UUID
    scene_revision: int = Field(gt=0)
    phase: Literal["before", "during", "after"]
    situation_summary: str = Field(min_length=1, max_length=2_000)
    planned_objective: str = Field(min_length=1, max_length=1_000)
    minimum_success: str = Field(min_length=1, max_length=1_000)
    signal_type: SceneSignalType | None = None
    danger: DangerAssessment
    avoidance: AvoidanceAssessment
    energy: EnergyAssessment
    coercion: CoercionAssessment
    goal_alignment: GoalAlignment
    goal_urgency: GoalUrgency
    input_event_id: UUID
    input_record_id: UUID | None = None
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    data_policy: DataPolicy


class InterventionDecision(StrictModel):
    schema_version: Literal[1] = 1
    intervention_decision_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    scene_session_id: UUID
    scene_revision: int = Field(gt=0)
    input_event_id: UUID
    input_record_id: UUID | None = None
    phase: Literal["before", "during", "after"]
    policy_version: Literal["intervention-policy-sim-v1"] = (
        "intervention-policy-sim-v1"
    )
    policy_release_status: Literal["candidate_owner_acceptance"] = (
        "candidate_owner_acceptance"
    )
    constitution_version_id: str = Field(min_length=1, max_length=200)
    identity_version_id: str = Field(min_length=1, max_length=200)
    values_version_id: str = Field(min_length=1, max_length=200)
    branch: InterventionBranch
    recommended_intervention: Literal[
        "prioritize_safety_and_help",
        "clarify_before_pressure",
        "support_recovery_with_restart",
        "smallest_viable_action",
        "prepare_with_user_owned_plan",
        "reflect_without_self_judgment",
    ]
    response_style: Literal[
        "calm_direct", "warm_firm", "supportive_recovery", "curious_reflective"
    ]
    guidance: str = Field(min_length=1, max_length=500)
    minimum_action: str | None = Field(default=None, max_length=500)
    clarification_question: str | None = Field(default=None, max_length=500)
    reason_codes: tuple[str, ...] = Field(min_length=1)
    required_constraints: tuple[str, ...] = Field(min_length=1)
    outreach_authorized: Literal[False] = False
    simulation_only: Literal[True] = True
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    data_policy: DataPolicy
    content_hash: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_guidance_and_hash(self) -> "InterventionDecision":
        if self.phase == "during" and len(self.guidance) > 240:
            raise ValueError("During Scene guidance must stay low bandwidth")
        if self.branch is InterventionBranch.CLARIFICATION:
            if self.clarification_question is None:
                raise ValueError("clarification decisions require one question")
        elif self.clarification_question is not None:
            raise ValueError("only clarification decisions may ask a question")
        material = self.model_dump(mode="json", exclude={"content_hash", "created_at"})
        expected = content_hash(material)
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match InterventionDecision")
        object.__setattr__(self, "content_hash", expected)
        return self


class InterventionPolicy:
    """Inspectable rules implementing accepted Stage 5 simulation boundaries."""

    version = "intervention-policy-sim-v1"
    required_constraints = (
        "preserve_user_choice",
        "no_shame_or_coercion",
        "do_not_treat_feeling_as_fact",
        "do_not_optimize_engagement",
        "no_proactive_outreach_authority",
    )

    def __init__(
        self,
        *,
        constitution_version_id: str,
        identity_version_id: str,
        values_version_id: str,
    ) -> None:
        self.constitution_version_id = constitution_version_id
        self.identity_version_id = identity_version_id
        self.values_version_id = values_version_id

    def decide(
        self,
        context: InterventionContext,
        *,
        decision_id: UUID | None = None,
        created_at: datetime | None = None,
    ) -> InterventionDecision:
        shared = {
            "intervention_decision_id": decision_id or uuid7(),
            "owner_id": context.owner_id,
            "scene_session_id": context.scene_session_id,
            "scene_revision": context.scene_revision,
            "input_event_id": context.input_event_id,
            "input_record_id": context.input_record_id,
            "phase": context.phase,
            "constitution_version_id": self.constitution_version_id,
            "identity_version_id": self.identity_version_id,
            "values_version_id": self.values_version_id,
            "required_constraints": self.required_constraints,
            "trace_id": context.trace_id,
            "data_policy": context.data_policy,
            "created_at": created_at or datetime.now(UTC),
        }

        if (
            context.danger in {DangerAssessment.PLAUSIBLE, DangerAssessment.IMMEDIATE}
            or context.coercion is CoercionAssessment.PRESENT
            or context.signal_type is SceneSignalType.NEED_HELP
        ):
            return InterventionDecision(
                **shared,
                branch=InterventionBranch.SAFETY_FIRST,
                recommended_intervention="prioritize_safety_and_help",
                response_style="calm_direct",
                guidance=(
                    "Prioritize safety. Move toward a safer place and contact a trusted "
                    "person or local emergency services if needed."
                ),
                minimum_action="Move toward safety and ask a trusted person for help.",
                reason_codes=("danger_or_help_signal_overrides_action_pressure",),
            )

        if (
            context.danger is DangerAssessment.UNCERTAIN
            or context.coercion is CoercionAssessment.UNCERTAIN
        ):
            return InterventionDecision(
                **shared,
                branch=InterventionBranch.CLARIFICATION,
                recommended_intervention="clarify_before_pressure",
                response_style="calm_direct",
                guidance="Pause before pushing forward. First check whether you are physically safe.",
                clarification_question="Are you physically safe right now?",
                reason_codes=("unresolved_safety_defaults_to_clarification",),
            )

        if (
            context.energy is EnergyAssessment.EXHAUSTED
            and context.goal_urgency is not GoalUrgency.URGENT
        ):
            return InterventionDecision(
                **shared,
                branch=InterventionBranch.RECOVERY,
                recommended_intervention="support_recovery_with_restart",
                response_style="supportive_recovery",
                guidance="Recovery is the next step. Rest without guilt, then choose a clear restart point.",
                minimum_action="Choose one realistic time to reassess after rest.",
                reason_codes=("exhaustion_without_urgent_goal_prefers_recovery",),
            )

        if context.phase == "after":
            return InterventionDecision(
                **shared,
                branch=InterventionBranch.REFLECTION,
                recommended_intervention="reflect_without_self_judgment",
                response_style="curious_reflective",
                guidance="Compare the prediction with what happened, then choose one adjustment without self-judgment.",
                minimum_action="Name one observed outcome and one next adjustment.",
                reason_codes=("after_scene_prefers_evidence_and_adjustment",),
            )

        if (
            context.danger is DangerAssessment.LOW
            and context.coercion is CoercionAssessment.ABSENT
            and context.goal_alignment is GoalAlignment.ACTIVE_MEANINGFUL
            and (
                context.avoidance in {AvoidanceAssessment.PRESENT, AvoidanceAssessment.HIGH}
                or context.signal_type
                in {SceneSignalType.AVOIDANCE_URGE, SceneSignalType.FROZEN}
            )
        ):
            guidance = (
                "Ground first, then take only the smallest safe step. You still choose whether to continue."
                if context.signal_type is SceneSignalType.FROZEN
                else "The urge is real; it is not proof of danger. Take only the smallest safe next step."
            )
            return InterventionDecision(
                **shared,
                branch=InterventionBranch.MINIMUM_ACTION,
                recommended_intervention="smallest_viable_action",
                response_style="warm_firm",
                guidance=guidance,
                minimum_action=context.minimum_success,
                reason_codes=("low_danger_meaningful_goal_supports_minimum_action",),
            )

        if context.phase == "before" and context.goal_alignment is GoalAlignment.ACTIVE_MEANINGFUL:
            return InterventionDecision(
                **shared,
                branch=InterventionBranch.PREPARATION,
                recommended_intervention="prepare_with_user_owned_plan",
                response_style="warm_firm",
                guidance=(
                    f"Keep the plan user-owned: {context.planned_objective}. "
                    f"Minimum success is {context.minimum_success}."
                ),
                minimum_action=context.minimum_success,
                reason_codes=("before_scene_prepares_without_catastrophizing",),
            )

        return InterventionDecision(
            **shared,
            branch=InterventionBranch.CLARIFICATION,
            recommended_intervention="clarify_before_pressure",
            response_style="curious_reflective",
            guidance="Do not force an action from unclear evidence. Choose what needs clarifying first.",
            clarification_question="What is the smallest point you want help deciding?",
            reason_codes=("ambiguous_context_defaults_to_clarification",),
        )
