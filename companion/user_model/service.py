"""Owner-reviewed Stage 4 User Model application service."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from companion.evidence import EvidenceRef
from companion.persistence.postgres import PostgresRepository
from companion.user_model.models import BeliefTransitionType, BeliefType


class UserModelService:
    version = "user-model-service-v1"

    def __init__(self, *, repository: PostgresRepository) -> None:
        self.repository = repository

    def propose_belief(
        self,
        *,
        owner_id: UUID,
        belief_key: str,
        statement: str,
        belief_type: BeliefType,
        confidence: float,
        evidence: tuple[EvidenceRef, ...],
        reason: str,
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
    ):
        return self.repository.create_belief_revision(
            owner_id=owner_id,
            belief_key=belief_key,
            statement=statement,
            belief_type=belief_type,
            confidence=confidence,
            evidence=evidence,
            reason=reason,
            valid_from=valid_from,
            valid_to=valid_to,
        )

    def activate(
        self,
        *,
        owner_id: UUID,
        belief_id: UUID,
        revision: int,
        reason: str,
        occurred_at: datetime | None = None,
    ):
        return self.repository.transition_belief(
            owner_id=owner_id,
            belief_id=belief_id,
            revision=revision,
            transition_type=BeliefTransitionType.ACTIVATED,
            reason=reason,
            occurred_at=occurred_at,
        )

    def revise(
        self,
        *,
        owner_id: UUID,
        belief_id: UUID,
        expected_revision: int,
        statement: str,
        confidence: float,
        evidence: tuple[EvidenceRef, ...],
        reason: str,
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
    ):
        return self.repository.revise_belief(
            owner_id=owner_id,
            belief_id=belief_id,
            expected_revision=expected_revision,
            statement=statement,
            confidence=confidence,
            evidence=evidence,
            reason=reason,
            valid_from=valid_from,
            valid_to=valid_to,
        )

    def transition(
        self,
        *,
        owner_id: UUID,
        belief_id: UUID,
        revision: int,
        transition_type: BeliefTransitionType,
        reason: str,
        occurred_at: datetime | None = None,
        evidence: tuple[EvidenceRef, ...] = (),
    ):
        return self.repository.transition_belief(
            owner_id=owner_id,
            belief_id=belief_id,
            revision=revision,
            transition_type=transition_type,
            reason=reason,
            occurred_at=occurred_at,
            evidence=evidence,
        )

    def list_beliefs(
        self,
        *,
        owner_id: UUID,
        known_as_of: datetime | None = None,
        valid_at: datetime | None = None,
        include_inactive: bool = False,
    ):
        return self.repository.list_belief_snapshots(
            owner_id=owner_id,
            known_as_of=known_as_of,
            valid_at=valid_at,
            include_inactive=include_inactive,
        )
