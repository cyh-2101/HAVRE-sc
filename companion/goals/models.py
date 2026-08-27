"""Reality and inner-life goal contracts for Stage 4."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from companion.evidence import EvidenceRef
from companion.hashing import content_hash
from companion.ids import uuid7
from companion.policy import DataPolicy, PrivacyClass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GoalTrack(StrEnum):
    REALITY = "reality"
    INNER_LIFE = "inner_life"


class GoalStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class GoalPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class GoalFieldUnset:
    """Sentinel that distinguishes an omitted nullable update from clear-to-null."""

    __slots__ = ()


GOAL_FIELD_UNSET = GoalFieldUnset()


class GoalProjectionDataPolicy(BaseModel):
    """Exact DataPolicy material included in a Goal projection digest."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1]
    policy_revision_id: UUID
    privacy_class: PrivacyClass
    memory_eligible: bool
    training_eligible: Literal[False]
    cloud_eligible: bool
    policy_version: Literal["data-policy-v1"]
    decision_source: Literal[
        "owner_default", "owner_explicit", "derived_conservative"
    ]
    authorization_ref: str | None

    @model_validator(mode="after")
    def enforce_hard_boundaries(self) -> "GoalProjectionDataPolicy":
        if self.privacy_class is PrivacyClass.LOCAL_ONLY and self.cloud_eligible:
            raise ValueError("LOCAL_ONLY data can never be cloud eligible")
        if self.privacy_class is PrivacyClass.HIGHLY_PRIVATE and self.cloud_eligible:
            if self.decision_source != "owner_explicit" or not self.authorization_ref:
                raise ValueError(
                    "HIGHLY_PRIVATE cloud use requires explicit owner authorization"
                )
        return self

    @classmethod
    def from_data_policy(cls, policy: DataPolicy) -> "GoalProjectionDataPolicy":
        return cls.model_validate(policy.model_dump())


class GoalProjectionMaterial(BaseModel):
    """The complete and only material admitted to a Goal content hash."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1]
    goal_id: UUID
    owner_id: UUID
    track: GoalTrack
    title: str = Field(min_length=1, max_length=500)
    why: str = Field(min_length=1, max_length=2_000)
    priority: GoalPriority
    status: GoalStatus
    next_action: str | None = Field(max_length=2_000)
    review_at: datetime | None
    revision: int = Field(gt=0)
    last_event_id: UUID
    data_policy: GoalProjectionDataPolicy

    @field_validator("review_at")
    @classmethod
    def normalize_review_at(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Goal projection review_at must be timezone-aware")
        return value.astimezone(UTC)

    def canonical_json(self) -> str:
        from companion.hashing import canonical_json

        return canonical_json(self.model_dump(mode="json"))

    def projection_hash(self) -> str:
        return content_hash(self.model_dump(mode="json"))


class Goal(StrictModel):
    schema_version: Literal[1] = 1
    goal_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    track: GoalTrack
    title: str = Field(min_length=1, max_length=500)
    why: str = Field(min_length=1, max_length=2_000)
    priority: GoalPriority = GoalPriority.NORMAL
    status: GoalStatus = GoalStatus.ACTIVE
    next_action: str | None = Field(default=None, max_length=2_000)
    review_at: datetime | None = None
    revision: int = Field(gt=0)
    last_event_id: UUID
    data_policy: DataPolicy
    content_hash: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def projection_material(self) -> GoalProjectionMaterial:
        return GoalProjectionMaterial(
            schema_version=self.schema_version,
            goal_id=self.goal_id,
            owner_id=self.owner_id,
            track=self.track,
            title=self.title,
            why=self.why,
            priority=self.priority,
            status=self.status,
            next_action=self.next_action,
            review_at=self.review_at,
            revision=self.revision,
            last_event_id=self.last_event_id,
            data_policy=GoalProjectionDataPolicy.from_data_policy(self.data_policy),
        )

    @model_validator(mode="after")
    def validate_hash(self) -> "Goal":
        expected = self.projection_material().projection_hash()
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match Goal")
        object.__setattr__(self, "content_hash", expected)
        return self


class GoalProgressRecord(StrictModel):
    schema_version: Literal[1] = 1
    progress_record_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    goal_id: UUID
    goal_revision: int = Field(gt=0)
    direction: Literal["toward", "steady", "away", "unknown"]
    summary: str = Field(min_length=1, max_length=2_000)
    observed_at: datetime
    evidence: tuple[EvidenceRef, ...] = Field(min_length=1)
    created_event_id: UUID
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    data_policy: DataPolicy
    content_hash: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("observed_at")
    @classmethod
    def normalize_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Goal progress observed_at must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_hash(self) -> "GoalProgressRecord":
        material = self.model_dump(mode="json", exclude={"content_hash", "created_at"})
        expected = content_hash(material)
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match GoalProgressRecord")
        object.__setattr__(self, "content_hash", expected)
        return self
