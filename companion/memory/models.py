"""Stage 2 episodic-memory contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from companion.hashing import content_hash
from companion.ids import uuid7
from companion.policy import DataPolicy


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MemoryCandidateStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    RETRACTED = "retracted"


class MemoryCandidate(StrictModel):
    schema_version: Literal[1] = 1
    candidate_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    source_event_id: UUID
    source_request_id: UUID
    job_id: UUID
    memory_class: Literal["episodic"] = "episodic"
    content: dict[str, object]
    content_text: str = Field(min_length=1, max_length=100_000)
    confidence: float = Field(ge=0, le=1)
    confidence_method: str
    importance: float = Field(ge=0, le=1)
    importance_policy_version: str
    extractor_version: str
    data_policy: DataPolicy
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    status: MemoryCandidateStatus = MemoryCandidateStatus.PENDING
    content_hash: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def model_post_init(self, __context: object) -> None:
        expected = content_hash(
            self.model_dump(mode="json", exclude={"content_hash", "created_at"})
        )
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match MemoryCandidate")
        object.__setattr__(self, "content_hash", expected)


class MemoryRevision(StrictModel):
    schema_version: Literal[1] = 1
    owner_id: UUID
    memory_id: UUID
    revision: int = Field(gt=0)
    memory_class: Literal["episodic", "semantic", "pattern", "progress"] = "episodic"
    content: dict[str, object]
    content_text: str = Field(min_length=1, max_length=100_000)
    confidence: float = Field(ge=0, le=1)
    confidence_method: str
    importance: float = Field(ge=0, le=1)
    importance_policy_version: str
    status: MemoryStatus
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    source_occurred_at: datetime | None = None
    created_by: str
    transform_version: str
    supersedes_revision: int | None = None
    candidate_id: UUID | None = None
    created_event_id: UUID
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    data_policy: DataPolicy
    content_hash: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def model_post_init(self, __context: object) -> None:
        expected = content_hash(
            {
                "schema_version": self.schema_version,
                "owner_id": str(self.owner_id),
                "memory_id": str(self.memory_id),
                "revision": self.revision,
                "memory_class": self.memory_class,
                "content": self.content,
                "content_text": self.content_text,
                "confidence": self.confidence,
                "confidence_method": self.confidence_method,
                "importance": self.importance,
                "importance_policy_version": self.importance_policy_version,
                "status": self.status.value,
                "valid_from": self.valid_from.isoformat() if self.valid_from else None,
                "valid_to": self.valid_to.isoformat() if self.valid_to else None,
                "source_occurred_at": (
                    self.source_occurred_at.isoformat()
                    if self.source_occurred_at
                    else None
                ),
                "supersedes_revision": self.supersedes_revision,
            }
        )
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match MemoryRevision")
        object.__setattr__(self, "content_hash", expected)
