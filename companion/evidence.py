"""Typed evidence references shared by Stage 4 derived understanding."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EvidenceSourceKind(StrEnum):
    EVENT = "event"
    MEMORY_REVISION = "memory_revision"
    BELIEF_REVISION = "belief_revision"


class EvidenceRelation(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"


class EvidenceRef(BaseModel):
    """An exact, owner-qualified source reference.

    Owner identity is supplied by the containing command. PostgreSQL verifies
    that every referenced source belongs to that owner before accepting a
    derived record.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_kind: EvidenceSourceKind
    source_id: UUID
    source_revision: int | None = Field(default=None, gt=0)
    relation: EvidenceRelation
    weight: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_revision(self) -> "EvidenceRef":
        revisioned = self.source_kind in {
            EvidenceSourceKind.MEMORY_REVISION,
            EvidenceSourceKind.BELIEF_REVISION,
        }
        if revisioned != (self.source_revision is not None):
            raise ValueError(
                "memory and belief evidence require an exact revision; events do not"
            )
        return self

    @property
    def source_ref(self) -> str:
        if self.source_kind is EvidenceSourceKind.EVENT:
            return f"event/{self.source_id}"
        if self.source_kind is EvidenceSourceKind.MEMORY_REVISION:
            return f"memory/{self.source_id}@{self.source_revision}"
        return f"belief/{self.source_id}@{self.source_revision}"
