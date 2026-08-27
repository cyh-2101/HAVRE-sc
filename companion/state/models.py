"""Expiring Current State contract, separate from durable User Model beliefs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from companion.evidence import EvidenceRef
from companion.hashing import content_hash
from companion.ids import uuid7
from companion.policy import DataPolicy


class CurrentStateSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    state_snapshot_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    summary: str = Field(min_length=1, max_length=2_000)
    state: dict[str, object]
    uncertainty: float = Field(ge=0, le=1)
    estimated_at: datetime
    expires_at: datetime
    estimator_version: Literal["owner-reported-state-v1"] = "owner-reported-state-v1"
    evidence: tuple[EvidenceRef, ...] = Field(min_length=1)
    created_event_id: UUID
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    data_policy: DataPolicy
    content_hash: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_expiry_and_hash(self) -> "CurrentStateSnapshot":
        if self.expires_at <= self.estimated_at:
            raise ValueError("Current State must expire after it is estimated")
        material = self.model_dump(mode="json", exclude={"content_hash", "created_at"})
        expected = content_hash(material)
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match CurrentStateSnapshot")
        object.__setattr__(self, "content_hash", expected)
        return self
