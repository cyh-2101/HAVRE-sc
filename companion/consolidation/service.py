"""Stage 4 proposal and owner-review service."""

from __future__ import annotations

from uuid import UUID

from companion.evidence import EvidenceRef
from companion.persistence.postgres import PostgresRepository


class ConsolidationService:
    version = "consolidation-service-v1"

    def __init__(self, *, repository: PostgresRepository, embedding_provider) -> None:
        self.repository = repository
        self.embedding_provider = embedding_provider

    def propose(
        self,
        *,
        owner_id: UUID,
        memory_class: str,
        content_text: str,
        evidence: tuple[EvidenceRef, ...],
        detector_version: str,
        importance: float = 0.5,
    ):
        return self.repository.create_consolidation_proposal(
            owner_id=owner_id,
            memory_class=memory_class,
            content_text=content_text,
            evidence=evidence,
            detector_version=detector_version,
            importance=importance,
        )

    def list_proposals(self, *, owner_id: UUID, status: str = "pending"):
        return self.repository.list_consolidation_proposals(
            owner_id=owner_id,
            status=status,
        )

    def accept(
        self,
        *,
        owner_id: UUID,
        proposal_id: UUID,
        reason: str,
        confidence: float,
        importance: float | None = None,
        corrected_content_text: str | None = None,
    ):
        return self.repository.accept_consolidation_proposal(
            owner_id=owner_id,
            proposal_id=proposal_id,
            reason=reason,
            confidence=confidence,
            importance=importance,
            corrected_content_text=corrected_content_text,
            embedding_provider=self.embedding_provider,
        )

    def reject(self, *, owner_id: UUID, proposal_id: UUID, reason: str):
        return self.repository.reject_consolidation_proposal(
            owner_id=owner_id,
            proposal_id=proposal_id,
            reason=reason,
        )
