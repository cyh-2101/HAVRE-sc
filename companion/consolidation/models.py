"""Human-inspectable Stage 4 consolidation proposal contracts."""

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


class ConsolidationProposalStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    ACCEPTED_WITH_CORRECTION = "accepted_with_correction"
    REJECTED = "rejected"


class ConsolidationProposal(StrictModel):
    schema_version: Literal[1] = 1
    proposal_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    memory_class: Literal["semantic", "pattern", "progress"]
    content: dict[str, object]
    content_text: str = Field(min_length=1, max_length=100_000)
    confidence: Literal[0.5] = 0.5
    confidence_method: Literal["unreviewed-proposal-v1"] = "unreviewed-proposal-v1"
    importance: float = Field(default=0.5, ge=0, le=1)
    importance_policy_version: Literal["owner-review-required-v1"] = (
        "owner-review-required-v1"
    )
    detector_version: str = Field(min_length=1, max_length=200)
    evidence: tuple[EvidenceRef, ...] = Field(min_length=1)
    status: ConsolidationProposalStatus = ConsolidationProposalStatus.PENDING
    created_event_id: UUID
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    data_policy: DataPolicy
    content_hash: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_evidence_and_hash(self) -> "ConsolidationProposal":
        support = {item.source_ref for item in self.evidence if item.relation.value == "supports"}
        if not support:
            raise ValueError("a consolidation proposal requires supporting evidence")
        if self.memory_class in {"pattern", "progress"} and len(support) < 2:
            raise ValueError(
                "pattern and progress proposals require at least two distinct supporting sources"
            )
        material = self.model_dump(mode="json", exclude={"content_hash", "created_at", "status"})
        expected = content_hash(material)
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match ConsolidationProposal")
        object.__setattr__(self, "content_hash", expected)
        return self
