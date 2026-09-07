from __future__ import annotations

import os
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg

from companion.application import InteractionCommand, InteractionService
from companion.context import ContextBuilder
from companion.identity import IdentityLoader
from companion.memory import DeterministicEmbeddingProvider, DeterministicEpisodicExtractor
from companion.memory.service import MemoryService, MemoryWorker
from companion.persistence import LeaseLostError, PostgresRepository, apply_migrations
from companion.policy import PrivacyClass
from mlsys.retrieval import (
    RetrievalExclusion,
    RetrievalFilters,
    RetrievalQuery,
    RetrievalRequest,
    RetrievalResult,
    RetrievalSelectionPolicy,
    RetrievalTiming,
    RetrievalVersions,
)
from mlsys.retrieval.service import RetrievalService
from mlsys.serving import DeterministicLocalProvider, Stage1Router


DATABASE_URL = os.getenv("HAVRE_TEST_DATABASE_URL")
PROJECT_ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(DATABASE_URL, "HAVRE_TEST_DATABASE_URL is required")
class Stage2PostgresIntegrationTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        assert DATABASE_URL is not None
        apply_migrations(DATABASE_URL, PROJECT_ROOT / "db" / "migrations")
        cls.owner_id = uuid.uuid4()
        cls.second_owner_id = uuid.uuid4()
        cls.identity = IdentityLoader(PROJECT_ROOT / "identity").load()
        cls.repository = PostgresRepository(DATABASE_URL)
        cls.repository.open()
        for owner_id in (cls.owner_id, cls.second_owner_id):
            cls.repository.bootstrap_owner_and_identity(owner_id=owner_id, identity=cls.identity)
        cls.embedding = DeterministicEmbeddingProvider()
        cls.memory = MemoryService(repository=cls.repository, embedding_provider=cls.embedding)
        cls.retrieval = RetrievalService(repository=cls.repository, embedding_provider=cls.embedding)
        cls.worker = MemoryWorker(
            repository=cls.repository,
            extractor=DeterministicEpisodicExtractor(),
            owner_id=cls.owner_id,
        )
        cls.service = InteractionService(
            owner_id=cls.owner_id, identity=cls.identity, repository=cls.repository,
            context_builder=ContextBuilder(max_input_tokens=4096, reserved_output_tokens=256),
            router=Stage1Router(), provider=DeterministicLocalProvider(),
            retrieval_service=cls.retrieval,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.repository.close()

    async def _create_accepted_memory(
        self, text: str, *, privacy=PrivacyClass.NORMAL, importance: float | None = None
    ):
        result = await self.service.interact(InteractionCommand(
            message=text, privacy_class=privacy, channel="api",
            idempotency_key=f"stage2-source-{uuid.uuid4()}",
        ))
        job = self.worker.run_once()
        self.assertIsNotNone(job)
        pending = self.memory.list_candidates(owner_id=self.owner_id)
        candidate = next(item for item in pending if item["source_event_id"] == result.user_event_id)
        revision = self.memory.accept_candidate(
            owner_id=self.owner_id, candidate_id=candidate["candidate_id"],
            reason="Stage 2 integration review",
            importance=importance,
        )
        return result, candidate, revision

    def _isolated_owner_runtime(self):
        owner_id = uuid.uuid4()
        self.repository.bootstrap_owner_and_identity(
            owner_id=owner_id, identity=self.identity
        )
        retrieval = RetrievalService(
            repository=self.repository, embedding_provider=self.embedding
        )
        worker = MemoryWorker(
            repository=self.repository,
            extractor=DeterministicEpisodicExtractor(),
            owner_id=owner_id,
            worker_id=f"isolated-{owner_id}",
        )
        service = InteractionService(
            owner_id=owner_id, identity=self.identity, repository=self.repository,
            context_builder=ContextBuilder(
                max_input_tokens=4096, reserved_output_tokens=256
            ),
            router=Stage1Router(), provider=DeterministicLocalProvider(),
            retrieval_service=retrieval,
        )
        return owner_id, service, worker

    async def _create_isolated_accepted_memory(
        self, *, owner_id, service, worker, text: str
    ):
        source = await service.interact(InteractionCommand(
            message=text, memory_eligible=True, channel="api",
            idempotency_key=f"isolated-source-{uuid.uuid4()}",
        ))
        self.assertIsNotNone(worker.run_once())
        candidate = next(
            row for row in self.memory.list_candidates(
                owner_id=owner_id, status="pending"
            )
            if row["source_event_id"] == source.user_event_id
        )
        revision = self.memory.accept_candidate(
            owner_id=owner_id,
            candidate_id=candidate["candidate_id"],
            reason="Isolated deletion regression review",
        )
        return source, revision

    async def test_web_chat_proposes_only_stable_memory_and_accepts_owner_edit(self) -> None:
        owner_id, service, worker = self._isolated_owner_runtime()
        transient = await service.interact(InteractionCommand(
            message="今天有点累",
            memory_eligible=True,
            channel="web",
            idempotency_key=f"web-transient-{uuid.uuid4()}",
        ))
        stable = await service.interact(InteractionCommand(
            message="今天聊了很多。请记住我喜欢先看结论再看解释。",
            memory_eligible=True,
            channel="web",
            idempotency_key=f"web-stable-{uuid.uuid4()}",
        ))
        with self.repository.pool.connection() as connection:
            transient_jobs = connection.execute(
                "SELECT count(*) FROM havre.background_jobs WHERE owner_id=%s AND source_event_id=%s",
                (owner_id, transient.user_event_id),
            ).fetchone()["count"]
            stable_jobs = connection.execute(
                "SELECT count(*) FROM havre.background_jobs WHERE owner_id=%s AND source_event_id=%s",
                (owner_id, stable.user_event_id),
            ).fetchone()["count"]
        self.assertEqual(transient_jobs, 0)
        self.assertEqual(stable_jobs, 1)
        candidate = worker.run_once()
        self.assertEqual(candidate["source_event_id"], stable.user_event_id)
        self.assertEqual(candidate["content_text"], "请记住我喜欢先看结论再看解释")
        original_hash = candidate["content_hash"]
        revision = self.memory.accept_candidate(
            owner_id=owner_id,
            candidate_id=candidate["candidate_id"],
            reason="Owner edited and confirmed from the Memory review surface",
            content_text="我喜欢先看结论，再看必要的解释。",
        )
        self.assertEqual(revision.content_text, "我喜欢先看结论，再看必要的解释。")
        self.assertEqual(revision.confidence_method, "owner-correction-v1")
        self.assertEqual(revision.transform_version, "owner-accepted-correction-v1")
        accepted_candidate = next(
            item for item in self.memory.list_candidates(
                owner_id=owner_id,
                status="accepted",
            )
            if item["candidate_id"] == candidate["candidate_id"]
        )
        self.assertEqual(accepted_candidate["content_text"], candidate["content_text"])
        self.assertEqual(accepted_candidate["content_hash"], original_hash)

    async def test_rejected_web_memory_does_not_return_unchanged(self) -> None:
        owner_id, service, worker = self._isolated_owner_runtime()
        message = "请记住我不喜欢每条回复最后都带一个问题。"
        first = await service.interact(InteractionCommand(
            message=message,
            memory_eligible=True,
            channel="web",
            idempotency_key=f"web-reject-first-{uuid.uuid4()}",
        ))
        first_candidate = worker.run_once()
        self.assertEqual(first_candidate["source_event_id"], first.user_event_id)
        self.memory.reject_candidate(
            owner_id=owner_id,
            candidate_id=first_candidate["candidate_id"],
            reason="Owner does not want this Memory",
        )
        second = await service.interact(InteractionCommand(
            message=message,
            memory_eligible=True,
            channel="web",
            idempotency_key=f"web-reject-second-{uuid.uuid4()}",
        ))
        duplicate = worker.run_once()
        self.assertEqual(duplicate["source_event_id"], second.user_event_id)
        self.assertEqual(duplicate["status"], "duplicate")
        pending = self.memory.list_candidates(owner_id=owner_id, status="pending")
        self.assertFalse(any(item["source_event_id"] == second.user_event_id for item in pending))

    async def test_event_job_candidate_memory_and_embedding_are_durable_and_idempotent(self) -> None:
        result, candidate, revision = await self._create_accepted_memory(
            "I practice piano every Sunday morning before breakfast.",
            importance=0.73,
        )
        replay = self.memory.accept_candidate(
            owner_id=self.owner_id, candidate_id=candidate["candidate_id"],
            reason="idempotent replay",
        )
        self.assertEqual(revision.memory_id, replay.memory_id)
        with self.repository.pool.connection() as connection:
            job = connection.execute(
                "SELECT * FROM havre.background_jobs WHERE owner_id=%s AND source_event_id=%s",
                (self.owner_id, result.user_event_id),
            ).fetchone()
            embedding = connection.execute(
                "SELECT * FROM havre.memory_embeddings WHERE owner_id=%s AND memory_id=%s",
                (self.owner_id, revision.memory_id),
            ).fetchone()
            edge = connection.execute(
                "SELECT * FROM havre.provenance_edges WHERE owner_id=%s AND derived_id=%s",
                (self.owner_id, revision.memory_id),
            ).fetchone()
        self.assertEqual(job["status"], "succeeded")
        source_policy_id = self.repository.evidence(
            result.request_id, owner_id=self.owner_id
        )["events"][0]["policy_revision_id"]
        self.assertNotEqual(candidate["policy_revision_id"], source_policy_id)
        self.assertEqual(candidate["policy_decision_source"], "derived_conservative")
        self.assertFalse(candidate["training_eligible"])
        self.assertNotEqual(revision.data_policy.policy_revision_id, candidate["policy_revision_id"])
        self.assertEqual(revision.data_policy.decision_source, "derived_conservative")
        self.assertEqual(embedding["embedding_version_id"], self.embedding.version.embedding_version_id)
        self.assertEqual(edge["source_id"], result.user_event_id)
        self.assertFalse(embedding is None)
        self.assertAlmostEqual(revision.importance, 0.73)
        self.assertEqual(revision.importance_policy_version, "owner-review-importance-v1")

    async def test_new_interaction_retrieves_memory_and_context_pack_records_use(self) -> None:
        source, _, revision = await self._create_accepted_memory(
            "For piano practice I use a slow metronome and repeat the difficult measure."
        )
        query = await self.service.interact(InteractionCommand(
            message="What was my piano practice method from last time with the metronome?",
            privacy_class=PrivacyClass.NORMAL, channel="api",
            memory_eligible=False,
            idempotency_key=f"stage2-query-{uuid.uuid4()}",
        ))
        evidence = self.repository.evidence(query.request_id, owner_id=self.owner_id)
        self.assertEqual(evidence["retrieval_result"]["retrieval_result_id"], query.retrieval_result_id)
        self.assertEqual(
            evidence["retrieval_result"]["selection_policy_version"],
            "retrieval-selection-context-safe-v1",
        )
        ids = [item["memory_id"] for item in evidence["retrieval_result"]["candidates"]]
        self.assertIn(str(revision.memory_id), [str(item) for item in ids])
        memory_sections = [
            section for section in evidence["context_pack"]["sections"]
            if section["section_type"] == "episodic_memory"
        ]
        self.assertTrue(any(str(revision.memory_id) in section["section_id"] for section in memory_sections))
        self.assertIsNone(evidence["memory_job"])

    async def test_owner_privacy_and_as_of_filters(self) -> None:
        _, _, revision = await self._create_accepted_memory(
            "My private piano audition is next month.", privacy=PrivacyClass.PRIVATE
        )
        now = datetime.now(UTC)
        request = RetrievalRequest(
            trace_id=uuid.uuid4().hex, owner_id=self.owner_id,
            request_id=(await self.service.interact(InteractionCommand(
                message="piano audition", privacy_class=PrivacyClass.NORMAL,
                memory_eligible=False, channel="api", idempotency_key=f"filter-{uuid.uuid4()}"
            ))).request_id,
            query=RetrievalQuery(text="piano audition", event_id=uuid.uuid4()),
            filters=RetrievalFilters(allowed_privacy_classes=(PrivacyClass.PUBLIC, PrivacyClass.NORMAL)),
            as_of=now,
        )
        rows = self.repository.search_memory_candidates(
            request=request, query_vector=self.embedding.pgvector(self.embedding.embed("piano audition")),
            embedding_version_id=self.embedding.version.embedding_version_id,
        )
        self.assertNotIn(revision.memory_id, [row["memory_id"] for row in rows])
        other = request.model_copy(update={"owner_id": self.second_owner_id})
        other_rows = self.repository.search_memory_candidates(
            request=other, query_vector=self.embedding.pgvector(self.embedding.embed("piano audition")),
            embedding_version_id=self.embedding.version.embedding_version_id,
        )
        self.assertNotIn(revision.memory_id, [row["memory_id"] for row in other_rows])
        self.assertTrue(all(row["owner_id"] == self.second_owner_id for row in other_rows))

    async def test_active_memory_exposes_owner_scoped_provenance_refs(self) -> None:
        result, _, revision = await self._create_accepted_memory(
            "I finished the memory provenance review."
        )
        rows = self.memory.list_active(owner_id=self.owner_id)
        current = next(row for row in rows if row["memory_id"] == revision.memory_id)
        self.assertIn(f"event/{result.user_event_id}", current["source_refs"])


    async def test_correction_and_retraction_preserve_history_and_as_of_replay(self) -> None:
        _, _, first = await self._create_accepted_memory(
            "The piano lesson is on Thursday afternoon."
        )
        before_correction = first.created_at
        corrected = self.memory.correct(
            owner_id=self.owner_id, memory_id=first.memory_id,
            content_text="The piano lesson is on Tuesday afternoon.",
            reason="Owner corrected the weekday",
        )
        current = self.memory.list_active(owner_id=self.owner_id)
        self.assertEqual(corrected.revision, 2)
        self.assertGreater(corrected.created_at, before_correction)
        self.assertTrue(any(row["content_text"].endswith("Tuesday afternoon.") for row in current))
        with self.repository.pool.connection() as connection:
            revisions = connection.execute(
                "SELECT revision, content_text FROM havre.memory_revisions WHERE owner_id=%s AND memory_id=%s ORDER BY revision",
                (self.owner_id, first.memory_id),
            ).fetchall()
        self.assertEqual([row["revision"] for row in revisions], [1, 2])
        request_id = (await self.service.interact(InteractionCommand(
            message="lesson weekday", memory_eligible=False, channel="api",
            idempotency_key=f"asof-{uuid.uuid4()}",
        ))).request_id
        query_event = self.repository.evidence(request_id, owner_id=self.owner_id)["events"][0]["event_id"]
        past_request = RetrievalRequest(
            trace_id=uuid.uuid4().hex, owner_id=self.owner_id, request_id=request_id,
            query=RetrievalQuery(text="piano lesson Thursday", event_id=query_event),
            filters=RetrievalFilters(allowed_privacy_classes=tuple(PrivacyClass)),
            as_of=before_correction,
        )
        past = self.retrieval.retrieve(past_request, persist=False)
        past_match = next(item for item in past.candidates if item.memory_id == first.memory_id)
        self.assertEqual(past_match.memory_revision, 1)
        retracted = self.memory.retract(
            owner_id=self.owner_id, memory_id=first.memory_id, reason="No longer applicable"
        )
        self.assertEqual(retracted.status.value, "retracted")
        self.assertNotIn(first.memory_id, [row["memory_id"] for row in self.memory.list_active(owner_id=self.owner_id)])

    async def test_source_erasure_closure_removes_memory_embedding_and_provenance(self) -> None:
        source, _, revision = await self._create_accepted_memory(
            "Temporary episodic memory for erasure closure testing."
        )
        self.memory.correct(
            owner_id=self.owner_id,
            memory_id=revision.memory_id,
            content_text="Corrected temporary episodic memory for erasure testing.",
            reason="Exercise multi-revision deletion closure",
        )
        counts = self.repository.erase_source_event_derivatives(
            owner_id=self.owner_id, source_event_id=source.user_event_id
        )
        self.assertEqual(counts["memories"], 2)
        self.assertGreaterEqual(counts["embeddings"], 2)
        self.assertGreaterEqual(counts["edges"], 2)
        self.assertEqual(counts["lifecycle_events"], 2)
        with self.repository.pool.connection() as connection:
            remaining = connection.execute(
                "SELECT count(*) FROM havre.memory_revisions WHERE owner_id=%s AND memory_id=%s",
                (self.owner_id, revision.memory_id),
            ).fetchone()["count"]
            raw_source = connection.execute(
                "SELECT count(*) FROM havre.events WHERE owner_id=%s AND event_id=%s",
                (self.owner_id, source.user_event_id),
            ).fetchone()["count"]
        self.assertEqual(remaining, 0)
        self.assertEqual(raw_source, 1)

    async def test_source_erasure_runs_without_an_accepted_memory(self) -> None:
        pending_job = await self.service.interact(InteractionCommand(
            message="Pending job must be erased without producing a candidate.",
            memory_eligible=True, channel="api",
            idempotency_key=f"erase-pending-job-{uuid.uuid4()}",
        ))
        pending_counts = self.repository.erase_source_event_derivatives(
            owner_id=self.owner_id, source_event_id=pending_job.user_event_id
        )
        self.assertEqual(pending_counts["jobs"], 1)
        self.assertEqual(pending_counts["candidates"], 0)
        self.assertEqual(pending_counts["memories"], 0)

        rejected_source = await self.service.interact(InteractionCommand(
            message="Rejected candidate must also be erased without a memory.",
            memory_eligible=True, channel="api",
            idempotency_key=f"erase-rejected-{uuid.uuid4()}",
        ))
        self.worker.run_once()
        candidate = next(
            row for row in self.memory.list_candidates(
                owner_id=self.owner_id, status="pending"
            )
            if row["source_event_id"] == rejected_source.user_event_id
        )
        self.memory.reject_candidate(
            owner_id=self.owner_id,
            candidate_id=candidate["candidate_id"],
            reason="Acceptance correction test",
        )
        rejected_counts = self.repository.erase_source_event_derivatives(
            owner_id=self.owner_id, source_event_id=rejected_source.user_event_id
        )
        self.assertEqual(rejected_counts["jobs"], 1)
        self.assertEqual(rejected_counts["candidates"], 1)
        self.assertEqual(rejected_counts["memories"], 0)
        with self.repository.pool.connection() as connection:
            remaining = connection.execute(
                """
                SELECT
                  (SELECT count(*) FROM havre.background_jobs
                   WHERE owner_id=%s AND source_event_id IN (%s,%s)) AS jobs,
                  (SELECT count(*) FROM havre.memory_candidates
                   WHERE owner_id=%s AND source_event_id IN (%s,%s)) AS candidates
                """,
                (
                    self.owner_id, pending_job.user_event_id,
                    rejected_source.user_event_id, self.owner_id,
                    pending_job.user_event_id, rejected_source.user_event_id,
                ),
            ).fetchone()
        self.assertEqual(remaining, {"jobs": 0, "candidates": 0})

    async def test_source_erasure_removes_retrieval_context_inference_and_answer_copies(self) -> None:
        source, _, revision = await self._create_accepted_memory(
            "For cello practice I use a slow metronome on difficult measures."
        )
        query = await self.service.interact(InteractionCommand(
            message="What slow metronome method did I use last time for difficult cello measures?",
            memory_eligible=False, channel="api",
            idempotency_key=f"erase-copy-query-{uuid.uuid4()}",
        ))
        evidence = self.repository.evidence(query.request_id, owner_id=self.owner_id)
        self.assertTrue(any(
            item["memory_id"] == str(revision.memory_id)
            for item in evidence["retrieval_result"]["candidates"]
        ))
        counts = self.repository.erase_source_event_derivatives(
            owner_id=self.owner_id, source_event_id=source.user_event_id
        )
        self.assertGreaterEqual(counts["retrieval_results"], 2)
        self.assertGreaterEqual(counts["context_packs"], 2)
        self.assertGreaterEqual(counts["inference_attempts"], 2)
        self.assertGreaterEqual(counts["assistant_events"], 2)
        with self.repository.pool.connection() as connection:
            stored = connection.execute(
                """
                SELECT request_id, status, error_code, assistant_event_id,
                       context_pack_id, inference_response_id
                FROM havre.interaction_requests
                WHERE owner_id=%s AND request_id IN (%s,%s)
                ORDER BY request_id
                """,
                (self.owner_id, source.request_id, query.request_id),
            ).fetchall()
            retrievals = connection.execute(
                "SELECT count(*) FROM havre.retrieval_results WHERE owner_id=%s AND request_id IN (%s,%s)",
                (self.owner_id, source.request_id, query.request_id),
            ).fetchone()["count"]
        self.assertEqual(len(stored), 2)
        self.assertTrue(all(row["status"] == "failed" for row in stored))
        self.assertTrue(all(row["error_code"] == "source_erasure_propagated" for row in stored))
        self.assertTrue(all(row["assistant_event_id"] is None for row in stored))
        self.assertTrue(all(row["context_pack_id"] is None for row in stored))
        self.assertTrue(all(row["inference_response_id"] is None for row in stored))
        self.assertEqual(retrievals, 0)

    async def test_source_erasure_follows_below_relevance_exclusion(self) -> None:
        owner_id, service, worker = self._isolated_owner_runtime()
        source, revision = await self._create_isolated_accepted_memory(
            owner_id=owner_id, service=service, worker=worker,
            text=(
                "For sourdough bread I feed the starter at night and bake in the "
                "morning."
            ),
        )
        query = await service.interact(InteractionCommand(
            message="From our earlier conversations, which afternoon is my current piano lesson?",
            memory_eligible=False, channel="api",
            idempotency_key=f"excluded-low-{uuid.uuid4()}",
        ))
        evidence = self.repository.evidence(query.request_id, owner_id=owner_id)
        exclusion = next(
            item for item in evidence["retrieval_result"]["exclusions"]
            if item["memory_id"] == str(revision.memory_id)
        )
        self.assertEqual(
            exclusion["reason_code"], "below_minimum_semantic_similarity"
        )
        self.assertFalse(any(
            item["memory_id"] == str(revision.memory_id)
            for item in evidence["retrieval_result"]["candidates"]
        ))

        counts = self.repository.erase_source_event_derivatives(
            owner_id=owner_id, source_event_id=source.user_event_id
        )
        self.assertGreaterEqual(counts["retrieval_results"], 2)
        with self.repository.pool.connection() as connection:
            remaining = connection.execute(
                "SELECT count(*) FROM havre.retrieval_results "
                "WHERE owner_id=%s AND request_id=%s",
                (owner_id, query.request_id),
            ).fetchone()["count"]
        self.assertEqual(remaining, 0)

    async def test_source_erasure_follows_duplicate_exclusion(self) -> None:
        owner_id, service, worker = self._isolated_owner_runtime()
        _, accepted = await self._create_isolated_accepted_memory(
            owner_id=owner_id, service=service, worker=worker,
            text=(
                "For piano practice I use a slow metronome and repeat the difficult "
                "measure."
            ),
        )
        duplicate_source, duplicate = await self._create_isolated_accepted_memory(
            owner_id=owner_id, service=service, worker=worker,
            text="I repeat difficult piano measures while using a slow metronome.",
        )
        query = await service.interact(InteractionCommand(
            message="From our earlier conversations, what method helps my difficult piano practice with a metronome?",
            memory_eligible=False, channel="api",
            idempotency_key=f"excluded-duplicate-{uuid.uuid4()}",
        ))
        evidence = self.repository.evidence(query.request_id, owner_id=owner_id)
        exclusion = next(
            item for item in evidence["retrieval_result"]["exclusions"]
            if item["memory_id"] == str(duplicate.memory_id)
        )
        self.assertEqual(exclusion["reason_code"], "duplicate_suppressed")
        self.assertEqual(
            exclusion["duplicate_of_memory_id"], str(accepted.memory_id)
        )
        self.assertFalse(any(
            item["memory_id"] == str(duplicate.memory_id)
            for item in evidence["retrieval_result"]["candidates"]
        ))

        counts = self.repository.erase_source_event_derivatives(
            owner_id=owner_id, source_event_id=duplicate_source.user_event_id
        )
        self.assertGreaterEqual(counts["retrieval_results"], 2)
        with self.repository.pool.connection() as connection:
            remaining = connection.execute(
                "SELECT count(*) FROM havre.retrieval_results "
                "WHERE owner_id=%s AND request_id=%s",
                (owner_id, query.request_id),
            ).fetchone()["count"]
        self.assertEqual(remaining, 0)

    async def test_source_erasure_follows_duplicate_of_canonical_reference(self) -> None:
        owner_id, service, worker = self._isolated_owner_runtime()
        canonical_source, canonical = await self._create_isolated_accepted_memory(
            owner_id=owner_id, service=service, worker=worker,
            text="Canonical violin practice memory retained after deduplication.",
        )
        _, duplicate = await self._create_isolated_accepted_memory(
            owner_id=owner_id, service=service, worker=worker,
            text="Duplicate violin practice memory suppressed by retrieval.",
        )
        query = await service.interact(InteractionCommand(
            message="What is my violin practice memory?",
            memory_eligible=False, channel="api",
            idempotency_key=f"duplicate-of-diagnostic-{uuid.uuid4()}",
        ))
        evidence = self.repository.evidence(query.request_id, owner_id=owner_id)
        query_event_id = next(
            event["event_id"] for event in evidence["events"]
            if event["event_type"] == "USER_MESSAGE"
        )
        diagnostic_request = RetrievalRequest(
            trace_id=query.trace_id,
            owner_id=owner_id,
            request_id=query.request_id,
            query=RetrievalQuery(
                text="diagnostic duplicate-of snapshot",
                event_id=query_event_id,
            ),
            filters=RetrievalFilters(
                allowed_privacy_classes=(PrivacyClass.NORMAL,)
            ),
        )
        diagnostic_result = RetrievalResult(
            retrieval_request_id=diagnostic_request.retrieval_request_id,
            request_id=query.request_id,
            query_event_id=query_event_id,
            trace_id=query.trace_id,
            owner_id=owner_id,
            as_of=diagnostic_request.as_of,
            versions=RetrievalVersions(
                algorithm_version="retrieval-r1-vector-gated-v2",
                embedding_version_id=self.embedding.version.embedding_version_id,
                index_version=self.retrieval.index_version,
            ),
            selection_policy=RetrievalSelectionPolicy(
                policy_version="retrieval-selection-context-safe-v1",
                minimum_semantic_similarity=0.35,
                duplicate_similarity_threshold=0.70,
                duplicate_token_overlap_threshold=0.65,
            ),
            candidates=(),
            exclusions=(RetrievalExclusion(
                memory_id=duplicate.memory_id,
                memory_revision=duplicate.revision,
                reason_code="duplicate_suppressed",
                semantic_similarity=0.8,
                duplicate_of_memory_id=canonical.memory_id,
            ),),
            timing_ms=RetrievalTiming(
                query_embedding=0, candidate_search=0, filtering=0,
                reranking=0, total=0,
            ),
        )
        self.repository.persist_retrieval_result(
            request=diagnostic_request, result=diagnostic_result
        )
        with self.repository.pool.connection() as connection:
            diagnostic = connection.execute(
                "SELECT candidates, exclusions FROM havre.retrieval_results "
                "WHERE owner_id=%s AND retrieval_result_id=%s",
                (owner_id, diagnostic_result.retrieval_result_id),
            ).fetchone()
        self.assertFalse(any(
            item["memory_id"] == str(canonical.memory_id)
            for item in diagnostic["candidates"]
        ))
        self.assertFalse(any(
            item["memory_id"] == str(canonical.memory_id)
            for item in diagnostic["exclusions"]
        ))
        self.assertTrue(any(
            item["duplicate_of_memory_id"] == str(canonical.memory_id)
            for item in diagnostic["exclusions"]
        ))

        self.repository.erase_source_event_derivatives(
            owner_id=owner_id, source_event_id=canonical_source.user_event_id
        )
        with self.repository.pool.connection() as connection:
            remaining = connection.execute(
                "SELECT count(*) FROM havre.retrieval_results "
                "WHERE owner_id=%s AND retrieval_result_id=%s",
                (owner_id, diagnostic_result.retrieval_result_id),
            ).fetchone()["count"]
        self.assertEqual(remaining, 0)

    async def test_cross_owner_provenance_is_rejected(self) -> None:
        _, _, revision = await self._create_accepted_memory("Owner one memory.")
        second_service = InteractionService(
            owner_id=self.second_owner_id, identity=self.identity,
            repository=self.repository,
            context_builder=ContextBuilder(max_input_tokens=4096, reserved_output_tokens=256),
            router=Stage1Router(), provider=DeterministicLocalProvider(),
            retrieval_service=self.retrieval,
        )
        foreign_source = await second_service.interact(InteractionCommand(
            message="This event and memory belong only to owner two.", memory_eligible=True,
            channel="api", idempotency_key=f"foreign-source-{uuid.uuid4()}",
        ))
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            with self.repository.pool.connection() as connection, connection.transaction():
                connection.execute(
                    """
                    INSERT INTO havre.provenance_edges (
                      provenance_edge_id, schema_version, owner_id, source_kind,
                      source_id, source_revision, derived_kind, derived_id,
                      derived_revision, relation, transform_name, transform_version,
                      created_event_id, trace_id
                    ) VALUES (%s,1,%s,'event',%s,NULL,'memory_revision',%s,1,
                              'derived_from','bad','v1',%s,%s)
                    """,
                    (uuid.uuid4(), self.owner_id, foreign_source.user_event_id,
                     revision.memory_id, revision.created_event_id, revision.trace_id),
                )
        second_worker = MemoryWorker(
            repository=self.repository,
            extractor=DeterministicEpisodicExtractor(),
            owner_id=self.second_owner_id,
            worker_id="owner-two-worker",
        )
        second_worker.run_once()
        foreign_candidate = next(
            row for row in self.memory.list_candidates(
                owner_id=self.second_owner_id, status="pending"
            )
            if row["source_event_id"] == foreign_source.user_event_id
        )
        foreign_memory = self.memory.accept_candidate(
            owner_id=self.second_owner_id,
            candidate_id=foreign_candidate["candidate_id"],
            reason="Owner two review",
        )
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            with self.repository.pool.connection() as connection, connection.transaction():
                connection.execute(
                    """
                    INSERT INTO havre.provenance_edges (
                      provenance_edge_id, schema_version, owner_id, source_kind,
                      source_id, source_revision, derived_kind, derived_id,
                      derived_revision, relation, transform_name, transform_version,
                      created_event_id, trace_id
                    ) VALUES (%s,1,%s,'memory_revision',%s,1,'memory_revision',%s,1,
                              'corrects','bad','v1',%s,%s)
                    """,
                    (
                        uuid.uuid4(), self.owner_id, foreign_memory.memory_id,
                        revision.memory_id, revision.created_event_id,
                        revision.trace_id,
                    ),
                )
        self.assertEqual(self.repository.audit_provenance_integrity(), [])

    async def test_reviewed_candidate_is_immutable(self) -> None:
        _, candidate, _ = await self._create_accepted_memory(
            "Reviewed candidate content is immutable."
        )
        for statement in (
            "UPDATE havre.memory_candidates SET content_text='tampered' WHERE owner_id=%s AND candidate_id=%s",
            "UPDATE havre.memory_candidates SET content_hash=%s WHERE owner_id=%s AND candidate_id=%s",
            "UPDATE havre.memory_candidates SET status='rejected' WHERE owner_id=%s AND candidate_id=%s",
        ):
            with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
                with self.repository.pool.connection() as connection, connection.transaction():
                    parameters = (
                        ("sha256:" + "0" * 64, self.owner_id, candidate["candidate_id"])
                        if "content_hash" in statement
                        else (self.owner_id, candidate["candidate_id"])
                    )
                    connection.execute(statement, parameters)

    async def test_worker_lease_recovery_and_noneligible_event_has_no_job(self) -> None:
        no_memory = await self.service.interact(InteractionCommand(
            message="Do not remember this operational query.",
            memory_eligible=False,
            channel="api",
            idempotency_key=f"no-memory-{uuid.uuid4()}",
        ))
        self.assertIsNone(
            self.repository.evidence(no_memory.request_id, owner_id=self.owner_id)["memory_job"]
        )
        eligible = await self.service.interact(InteractionCommand(
            message="Lease recovery memory event.",
            memory_eligible=True,
            channel="api",
            idempotency_key=f"lease-recovery-{uuid.uuid4()}",
        ))
        claimed = self.repository.claim_memory_job(worker_id="crashed-worker", owner_id=self.owner_id)
        self.assertEqual(claimed["source_event_id"], eligible.user_event_id)
        with self.repository.pool.connection() as connection, connection.transaction():
            connection.execute(
                "UPDATE havre.background_jobs SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE job_id=%s",
                (claimed["job_id"],),
            )
        with self.assertRaises(LeaseLostError):
            self.repository.fail_memory_job(
                job=claimed, error_code="expired-worker", spans=[]
            )
        recovered = self.repository.claim_memory_job(worker_id="replacement-worker", owner_id=self.owner_id)
        self.assertEqual(recovered["job_id"], claimed["job_id"])
        self.assertEqual(recovered["attempt_count"], 2)
        source_event = self.repository.event_by_id(
            owner_id=self.owner_id, event_id=claimed["source_event_id"]
        )
        stale_candidate = DeterministicEpisodicExtractor().extract(
            event=source_event, job_id=claimed["job_id"]
        )
        with self.assertRaises(LeaseLostError):
            self.repository.complete_memory_job(
                job=claimed, candidate=stale_candidate, spans=[]
            )
        with self.assertRaises(LeaseLostError):
            self.repository.fail_memory_job(
                job=claimed, error_code="replaced-worker", spans=[]
            )
        current = self.repository.claim_memory_job(
            worker_id="third-worker", owner_id=self.owner_id
        )
        self.assertIsNone(current)
        recovered_event = self.repository.event_by_id(
            owner_id=self.owner_id, event_id=recovered["source_event_id"]
        )
        recovered_candidate = DeterministicEpisodicExtractor().extract(
            event=recovered_event, job_id=recovered["job_id"]
        )
        stored = self.repository.complete_memory_job(
            job=recovered, candidate=recovered_candidate, spans=[]
        )
        self.assertEqual(stored["job_id"], recovered["job_id"])


if __name__ == "__main__":
    unittest.main()
