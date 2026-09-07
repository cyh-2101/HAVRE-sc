"""Evidence-linked Stage 4 goal application service."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from companion.evidence import EvidenceRef
from companion.goals.models import (
    GOAL_FIELD_UNSET,
    GoalFieldUnset,
    GoalPriority,
    GoalStatus,
    GoalTrack,
)
from companion.persistence.postgres import PostgresRepository


class GoalService:
    version = "goal-service-v1"

    def __init__(self, *, repository: PostgresRepository) -> None:
        self.repository = repository

    def create(
        self,
        *,
        owner_id: UUID,
        track: GoalTrack,
        title: str,
        why: str,
        source_event_id: UUID,
        priority: GoalPriority = GoalPriority.NORMAL,
        next_action: str | None = None,
        review_at: datetime | None = None,
    ):
        return self.repository.create_goal(
            owner_id=owner_id,
            track=track,
            title=title,
            why=why,
            source_event_id=source_event_id,
            priority=priority,
            next_action=next_action,
            review_at=review_at,
        )

    def update(
        self,
        *,
        owner_id: UUID,
        goal_id: UUID,
        expected_revision: int,
        reason: str,
        title: str | None = None,
        why: str | None = None,
        priority: GoalPriority | None = None,
        status: GoalStatus | None = None,
        next_action: str | None | GoalFieldUnset = GOAL_FIELD_UNSET,
        review_at: datetime | None | GoalFieldUnset = GOAL_FIELD_UNSET,
        source_event_id: UUID | None = None,
    ):
        return self.repository.update_goal(
            owner_id=owner_id,
            goal_id=goal_id,
            expected_revision=expected_revision,
            reason=reason,
            title=title,
            why=why,
            priority=priority,
            status=status,
            next_action=next_action,
            review_at=review_at,
            source_event_id=source_event_id,
        )

    def record_progress(
        self,
        *,
        owner_id: UUID,
        goal_id: UUID,
        expected_goal_revision: int,
        direction: str,
        summary: str,
        observed_at: datetime,
        evidence: tuple[EvidenceRef, ...],
    ):
        return self.repository.record_goal_progress(
            owner_id=owner_id,
            goal_id=goal_id,
            expected_goal_revision=expected_goal_revision,
            direction=direction,
            summary=summary,
            observed_at=observed_at,
            evidence=evidence,
        )

    def list(self, *, owner_id: UUID, include_inactive: bool = False):
        return self.repository.list_goals(
            owner_id=owner_id,
            include_inactive=include_inactive,
        )
