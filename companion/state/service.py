"""Stage 4 Current State service."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from companion.evidence import EvidenceRef
from companion.persistence.postgres import PostgresRepository


class CurrentStateService:
    version = "current-state-service-v1"

    def __init__(self, *, repository: PostgresRepository) -> None:
        self.repository = repository

    def estimate(
        self,
        *,
        owner_id: UUID,
        summary: str,
        state: dict[str, object],
        uncertainty: float,
        estimated_at: datetime,
        expires_at: datetime,
        evidence: tuple[EvidenceRef, ...],
    ):
        return self.repository.create_current_state_snapshot(
            owner_id=owner_id,
            summary=summary,
            state=state,
            uncertainty=uncertainty,
            estimated_at=estimated_at,
            expires_at=expires_at,
            evidence=evidence,
        )

    def current(self, *, owner_id: UUID, as_of: datetime | None = None):
        return self.repository.current_state(owner_id=owner_id, as_of=as_of)
