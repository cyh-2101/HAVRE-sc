"""Conservative pattern-candidate detection for frozen Stage 4 replay cases.

The detector decides only whether evidence is sufficient to create a proposal.
It never assigns a durable belief confidence and never activates a proposal.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PatternEvidenceObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: UUID
    occurred_at: datetime
    supports_pattern: bool


class PatternDetectionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    detector_version: Literal["pattern-proposal-distinct-days-v1"] = (
        "pattern-proposal-distinct-days-v1"
    )
    eligible_for_proposal: bool
    distinct_support_sources: int = Field(ge=0)
    distinct_support_days: int = Field(ge=0)
    counter_evidence_count: int = Field(ge=0)
    reason_codes: tuple[str, ...]
    requires_owner_review: Literal[True] = True


def detect_pattern_candidate(
    observations: tuple[PatternEvidenceObservation, ...],
) -> PatternDetectionResult:
    if any(
        item.occurred_at.tzinfo is None or item.occurred_at.utcoffset() is None
        for item in observations
    ):
        raise ValueError("pattern occurrence timestamps must be timezone-aware")
    supports = [item for item in observations if item.supports_pattern]
    counters = [item for item in observations if not item.supports_pattern]
    source_count = len({item.source_id for item in supports})
    days: set[date] = {
        item.occurred_at.astimezone(UTC).date() for item in supports
    }
    eligible = source_count >= 2 and len(days) >= 2
    reasons = []
    if source_count < 2:
        reasons.append("insufficient_distinct_support_sources")
    if len(days) < 2:
        reasons.append("insufficient_distinct_support_days")
    if counters:
        reasons.append("counter_evidence_present")
    if eligible:
        reasons.append("proposal_only_owner_review_required")
    return PatternDetectionResult(
        eligible_for_proposal=eligible,
        distinct_support_sources=source_count,
        distinct_support_days=len(days),
        counter_evidence_count=len(counters),
        reason_codes=tuple(reasons),
    )
