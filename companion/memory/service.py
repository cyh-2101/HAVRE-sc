"""Stage 2 worker and owner-reviewed memory lifecycle services."""

from __future__ import annotations

from companion.events import EventEnvelope
from companion.ids import uuid7
from companion.memory.embedding import DeterministicEmbeddingProvider
from companion.memory.extractor import DeterministicEpisodicExtractor
from companion.persistence.postgres import PostgresRepository
from companion.tracing import TraceContext


class MemoryWorker:
    version = "memory-worker-v3"

    def __init__(
        self,
        *,
        repository: PostgresRepository,
        extractor: DeterministicEpisodicExtractor,
        owner_id=None,
        worker_id: str = "memory-worker-local-1",
    ) -> None:
        self.repository = repository
        self.extractor = extractor
        self.owner_id = owner_id
        self.worker_id = worker_id

    def run_once(self) -> dict[str, object] | None:
        job = self.repository.claim_memory_job(
            worker_id=self.worker_id,
            owner_id=self.owner_id,
        )
        if job is None:
            return None
        trace = TraceContext(
            trace_id=job["origin_trace_id"],
            parent_span_id=None,
        )
        try:
            with trace.span(
                "memory.extract_candidate",
                attributes={
                    "job_id": str(job["job_id"]),
                    "worker_version": self.version,
                    "extractor_version": self.extractor.version,
                },
            ):
                event = self.repository.event_by_id(
                    owner_id=job["owner_id"],
                    event_id=job["source_event_id"],
                )
                if event is None:
                    raise LookupError("source event was erased")
                candidate = self.extractor.extract(event=event, job_id=job["job_id"])
                stored = self.repository.complete_memory_job(
                    job=job,
                    candidate=candidate,
                    spans=list(trace.spans),
                )
            self.repository.append_spans(list(trace.spans))
            return stored
        except Exception as error:
            self.repository.fail_memory_job(
                job=job,
                error_code=type(error).__name__,
                spans=list(trace.spans),
            )
            raise


class MemoryService:
    version = "memory-service-v2"

    def __init__(
        self,
        *,
        repository: PostgresRepository,
        embedding_provider: DeterministicEmbeddingProvider,
    ) -> None:
        self.repository = repository
        self.embedding_provider = embedding_provider
        self.repository.register_embedding_version(embedding_provider.version)

    def list_candidates(self, *, owner_id, status: str = "pending"):
        return self.repository.list_memory_candidates(owner_id=owner_id, status=status)

    def accept_candidate(
        self, *, owner_id, candidate_id, reason: str, importance: float | None = None,
        content_text: str | None = None,
    ):
        return self.repository.accept_memory_candidate(
            owner_id=owner_id,
            candidate_id=candidate_id,
            reason=reason,
            embedding_provider=self.embedding_provider,
            importance=importance,
            content_text=content_text,
        )

    def reject_candidate(self, *, owner_id, candidate_id, reason: str):
        return self.repository.reject_memory_candidate(
            owner_id=owner_id,
            candidate_id=candidate_id,
            reason=reason,
        )

    def correct(self, *, owner_id, memory_id, content_text: str, reason: str):
        return self.repository.revise_memory(
            owner_id=owner_id,
            memory_id=memory_id,
            content_text=content_text,
            reason=reason,
            embedding_provider=self.embedding_provider,
        )

    def retract(self, *, owner_id, memory_id, reason: str):
        return self.repository.retract_memory(
            owner_id=owner_id,
            memory_id=memory_id,
            reason=reason,
        )

    def list_active(self, *, owner_id):
        return self.repository.list_active_memories(owner_id=owner_id)
