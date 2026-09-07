"""Typed results for the Stage 15A commitment broker."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CommitmentCompletionResolution(StrictModel):
    status: Literal["none", "completed", "ambiguous"]
    goal_id: UUID | None = None
    goal_revision: int | None = Field(default=None, gt=0)
    candidate_goal_ids: tuple[UUID, ...] = ()
    clarification_text: str | None = Field(default=None, max_length=500)


class CommitmentFusionClaim(StrictModel):
    claim_id: UUID
    work_item_id: UUID
    goal_id: UUID
    goal_revision: int = Field(gt=0)
    commitment_projection_id: UUID
    course_name: str = Field(min_length=1, max_length=160)
    task_name: str = Field(min_length=1, max_length=500)
    deadline_at: datetime | None = None
    reminder_kind: Literal["start_window", "check_in", "encouragement"]
    source_event_id: UUID
    source_event_content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    projection_content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
