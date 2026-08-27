"""First-class Stage 5 Scene Session and outcome contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from companion.hashing import content_hash
from companion.ids import uuid7
from companion.policy import DataPolicy
from companion.policy.intervention import InterventionDecision


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _normalized_utc(value: datetime | None, *, field_name: str) -> datetime | None:
    if value is None:
        return None
    if value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


class ScenePhase(StrEnum):
    BEFORE = "before"
    DURING = "during"
    AFTER = "after"
    CLOSED = "closed"


class SceneStatus(StrEnum):
    PLANNED = "planned"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ABANDONED = "abandoned"
    CANCELLED = "cancelled"


class SceneRecordType(StrEnum):
    SIGNAL = "signal"
    INTERVENTION = "intervention"
    ACTION = "action"
    OUTCOME = "outcome"
    REFLECTION = "reflection"


class OutcomeTriState(StrEnum):
    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"


class OutcomeHelpfulness(StrEnum):
    HELPFUL = "helpful"
    NOT_HELPFUL = "not_helpful"
    UNCERTAIN = "uncertain"
    NOT_ASKED = "not_asked"


class SceneSituation(StrictModel):
    summary: str = Field(min_length=1, max_length=2_000)
    known_facts: tuple[str, ...] = ()
    uncertainty_notes: tuple[str, ...] = ()

    @field_validator("known_facts", "uncertainty_notes")
    @classmethod
    def validate_items(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() or len(value) > 500 for value in values):
            raise ValueError("situation items must contain 1 to 500 characters")
        return values


class SceneGoal(StrictModel):
    objective: str = Field(min_length=1, max_length=1_000)
    minimum_success: str = Field(min_length=1, max_length=1_000)
    owner_chosen: Literal[True] = True


class AnticipatedTrigger(StrictModel):
    label: str = Field(min_length=1, max_length=500)
    uncertainty_note: str | None = Field(default=None, max_length=500)


class SceneSession(StrictModel):
    schema_version: Literal[1] = 1
    scene_session_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    opened_session_id: UUID
    scene_type: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    situation: SceneSituation
    planned_goal: SceneGoal
    anticipated_triggers: tuple[AnticipatedTrigger, ...] = ()
    phase: ScenePhase
    status: SceneStatus
    planned_start_at: datetime | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    revision: int = Field(gt=0)
    created_event_id: UUID
    last_event_id: UUID
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    data_policy: DataPolicy
    content_hash: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("planned_start_at", "started_at", "ended_at")
    @classmethod
    def normalize_projection_times(
        cls, value: datetime | None, info
    ) -> datetime | None:
        return _normalized_utc(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_state_and_hash(self) -> "SceneSession":
        terminal = {
            SceneStatus.COMPLETED,
            SceneStatus.ABANDONED,
            SceneStatus.CANCELLED,
        }
        if (self.phase is ScenePhase.CLOSED) != (self.status in terminal):
            raise ValueError("closed phase and terminal status must appear together")
        if self.status is SceneStatus.PLANNED and self.phase is not ScenePhase.BEFORE:
            raise ValueError("planned Scene Sessions must remain in Before phase")
        if self.status is SceneStatus.PAUSED and self.phase is not ScenePhase.DURING:
            raise ValueError("only a During Scene may be paused")
        requires_start = self.phase in {ScenePhase.DURING, ScenePhase.AFTER} or (
            self.phase is ScenePhase.CLOSED
            and self.status is not SceneStatus.CANCELLED
        )
        if requires_start and self.started_at is None:
            raise ValueError("started or non-cancelled closed Scenes require started_at")
        if self.phase is ScenePhase.CLOSED:
            if self.ended_at is None:
                raise ValueError("closed Scenes require ended_at")
        elif self.ended_at is not None:
            raise ValueError("open Scenes cannot have ended_at")
        material = self.model_dump(
            mode="json", exclude={"content_hash", "created_at", "updated_at"}
        )
        expected = content_hash(material)
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match SceneSession")
        object.__setattr__(self, "content_hash", expected)
        return self


class SceneRecord(StrictModel):
    schema_version: Literal[1] = 1
    scene_record_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    scene_session_id: UUID
    record_type: SceneRecordType
    phase: Literal["before", "during", "after"]
    sequence_number: int = Field(gt=0)
    occurred_at: datetime
    event_id: UUID
    assistant_event_id: UUID | None = None
    artifact_kind: Literal["intervention_decision"] | None = None
    artifact_id: UUID | None = None
    artifact_revision: int | None = Field(default=None, gt=0)
    causal_predecessor_id: UUID | None = None
    source: Literal["owner_self_report", "web_simulation", "intervention_policy"]
    uncertainty_note: str | None = Field(default=None, max_length=1_000)
    content: dict[str, object]
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    data_policy: DataPolicy
    content_hash: str = ""
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("occurred_at")
    @classmethod
    def normalize_occurred_at(cls, value: datetime) -> datetime:
        normalized = _normalized_utc(value, field_name="occurred_at")
        assert normalized is not None
        return normalized

    @model_validator(mode="after")
    def validate_artifact_and_hash(self) -> "SceneRecord":
        is_intervention = self.record_type is SceneRecordType.INTERVENTION
        artifact_complete = (
            self.artifact_kind is not None
            and self.artifact_id is not None
            and self.artifact_revision is not None
            and self.assistant_event_id is not None
        )
        if is_intervention != artifact_complete:
            raise ValueError(
                "only intervention records require decision and guidance references"
            )
        material = self.model_dump(mode="json", exclude={"content_hash", "recorded_at"})
        expected = content_hash(material)
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match SceneRecord")
        object.__setattr__(self, "content_hash", expected)
        return self


class GuidanceOutcomeObservation(StrictModel):
    schema_version: Literal[1] = 1
    outcome_observation_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    scene_session_id: UUID
    intervention_decision_id: UUID
    guidance_event_id: UUID
    action_record_id: UUID
    outcome_record_id: UUID
    reflection_record_id: UUID
    observation_window_started_at: datetime
    observation_window_ended_at: datetime
    reporter: Literal["user_self_report"] = "user_self_report"
    action_attempted: OutcomeTriState
    planned_scene_status: Literal[
        "completed", "partial", "abandoned", "cancelled", "unknown"
    ]
    helpfulness: OutcomeHelpfulness = OutcomeHelpfulness.NOT_ASKED
    too_passive: OutcomeTriState = OutcomeTriState.UNKNOWN
    too_forceful: OutcomeTriState = OutcomeTriState.UNKNOWN
    later_regret: Literal["yes", "no", "unsure", "not_asked"] = "not_asked"
    limitations: tuple[str, ...] = Field(min_length=1)
    consented: Literal[True] = True
    evidence_snapshot: tuple[dict[str, object], ...] = Field(min_length=1)
    created_event_id: UUID
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    data_policy: DataPolicy
    content_hash: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("observation_window_started_at", "observation_window_ended_at")
    @classmethod
    def normalize_observation_times(cls, value: datetime, info) -> datetime:
        normalized = _normalized_utc(value, field_name=info.field_name)
        assert normalized is not None
        return normalized

    @model_validator(mode="after")
    def validate_window_and_hash(self) -> "GuidanceOutcomeObservation":
        if self.observation_window_ended_at < self.observation_window_started_at:
            raise ValueError("outcome observation window is inverted")
        material = self.model_dump(mode="json", exclude={"content_hash", "created_at"})
        expected = content_hash(material)
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match GuidanceOutcomeObservation")
        object.__setattr__(self, "content_hash", expected)
        return self


class SceneView(StrictModel):
    scene_session: SceneSession
    records: tuple[SceneRecord, ...]
    intervention_decisions: tuple[InterventionDecision, ...]
    outcome_observations: tuple[GuidanceOutcomeObservation, ...]


class SceneCommandResult(StrictModel):
    request_id: UUID
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    scene: SceneView
    decision: InterventionDecision | None = None
    guidance_event_id: UUID | None = None
    outcome_observation: GuidanceOutcomeObservation | None = None
    idempotent_replay: bool
