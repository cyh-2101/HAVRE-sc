"""Stage 4 temporal User Model contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from companion.evidence import EvidenceRef
from companion.hashing import content_hash
from companion.ids import uuid7
from companion.policy import DataPolicy


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BeliefType(StrEnum):
    FACT = "fact"
    PREFERENCE = "preference"
    VALUE = "value"
    STRENGTH = "strength"
    VULNERABILITY = "vulnerability"
    PATTERN = "pattern"
    UNCERTAINTY = "uncertainty"


class BeliefInitialStatus(StrEnum):
    CANDIDATE = "candidate"
    ACTIVE = "active"


class BeliefTransitionType(StrEnum):
    ACTIVATED = "activated"
    COUNTER_EVIDENCE_RECORDED = "counter_evidence_recorded"
    CONTRADICTED = "contradicted"
    SUPERSEDED = "superseded"
    RETRACTED = "retracted"
    INVALIDATED = "invalidated"


class BeliefRevision(StrictModel):
    schema_version: Literal[1] = 1
    owner_id: UUID
    belief_id: UUID = Field(default_factory=uuid7)
    revision: int = Field(gt=0)
    belief_key: str = Field(min_length=1, max_length=240)
    statement: str = Field(min_length=1, max_length=10_000)
    belief_type: BeliefType
    confidence: float = Field(ge=0, le=1)
    confidence_method: Literal["owner-reviewed-v1"] = "owner-reviewed-v1"
    initial_status: BeliefInitialStatus
    evidence_occurred_from: datetime | None = None
    evidence_occurred_to: datetime | None = None
    learned_at: datetime
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    supersedes_revision: int | None = Field(default=None, gt=0)
    created_event_id: UUID
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    data_policy: DataPolicy
    content_hash: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_temporal_contract(self) -> "BeliefRevision":
        if (self.revision == 1) != (self.supersedes_revision is None):
            raise ValueError("only revision 1 may omit supersedes_revision")
        if self.supersedes_revision is not None and self.supersedes_revision != self.revision - 1:
            raise ValueError("a belief revision must supersede the immediately prior revision")
        if (
            self.evidence_occurred_from is not None
            and self.evidence_occurred_to is not None
            and self.evidence_occurred_to < self.evidence_occurred_from
        ):
            raise ValueError("evidence occurrence range is inverted")
        if self.valid_from is not None and self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("belief valid-time range is inverted")
        material = self.model_dump(mode="json", exclude={"content_hash", "created_at"})
        expected = content_hash(material)
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match BeliefRevision")
        object.__setattr__(self, "content_hash", expected)
        return self


class BeliefTransition(StrictModel):
    schema_version: Literal[1] = 1
    belief_transition_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    belief_id: UUID
    belief_revision: int = Field(gt=0)
    transition_type: BeliefTransitionType
    occurred_at: datetime
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    reason: str = Field(min_length=1, max_length=2_000)
    causing_event_id: UUID
    replacement_belief_id: UUID | None = None
    replacement_revision: int | None = Field(default=None, gt=0)
    content_hash: str = ""

    @model_validator(mode="after")
    def validate_replacement(self) -> "BeliefTransition":
        if (self.replacement_belief_id is None) != (self.replacement_revision is None):
            raise ValueError("replacement belief ID and revision must appear together")
        if self.transition_type is BeliefTransitionType.SUPERSEDED and self.replacement_belief_id is None:
            raise ValueError("superseded transitions require a replacement revision")
        material = self.model_dump(mode="json", exclude={"content_hash", "recorded_at"})
        expected = content_hash(material)
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match BeliefTransition")
        object.__setattr__(self, "content_hash", expected)
        return self


class BeliefSnapshot(StrictModel):
    revision: BeliefRevision
    effective_status: Literal[
        "candidate",
        "active",
        "contradicted",
        "superseded",
        "retracted",
        "invalidated",
    ]
    supporting_evidence: tuple[EvidenceRef, ...]
    counter_evidence: tuple[EvidenceRef, ...]
    transitions: tuple[BeliefTransition, ...]
    known_as_of: datetime
    valid_at: datetime | None = None
