from __future__ import annotations

import json
import unittest
import uuid
import time
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError

from companion.context import ContextBuilder, ContextRetrievalRejected
from companion.events import EventEnvelope, EventType, TextContentPart, UserMessagePayload
from companion.identity import IdentityLoader
from companion.memory import DeterministicEmbeddingProvider, MemoryRevision, MemoryStatus
from companion.memory.extractor import is_memory_candidate_worthy, proposed_memory_text
from companion.policy import DataPolicy, PrivacyClass
from mlsys.retrieval import (
    RetrievalCandidate,
    RetrievalFilters,
    RetrievalQuery,
    RetrievalRequest,
    RetrievalResult,
    RetrievalScoreComponents,
    RetrievalSelectionPolicy,
    RetrievalTiming,
    RetrievalVersions,
)
from mlsys.retrieval.service import RetrievalService
from evals.retrieval_benchmark import run_benchmark


class EmbeddingContractTests(unittest.TestCase):
    def test_embedding_is_versioned_normalized_and_deterministic(self) -> None:
        provider = DeterministicEmbeddingProvider()
        first = provider.embed("I practice piano every Sunday.")
        second = provider.embed("I practice piano every Sunday.")
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)
        self.assertAlmostEqual(sum(value * value for value in first), 1.0, places=6)
        self.assertEqual(provider.version.distance_metric, "cosine")

    def test_memory_revision_timestamp_factory_runs_per_instance(self) -> None:
        fields = dict(
            owner_id=uuid.uuid4(), memory_id=uuid.uuid4(), revision=1,
            content={"text": "x"}, content_text="x", confidence=0.5,
            confidence_method="test", importance=0.5,
            importance_policy_version="test", status=MemoryStatus.ACTIVE,
            created_by="test", transform_version="test", created_event_id=uuid.uuid4(),
            trace_id=uuid.uuid4().hex,
            data_policy=DataPolicy.owner_default(PrivacyClass.NORMAL),
        )
        first = MemoryRevision(**fields)
        time.sleep(0.02)
        second = MemoryRevision(**fields)
        self.assertGreater(second.created_at, first.created_at)


class MemoryProposalContractTests(unittest.TestCase):
    def test_web_proposal_keeps_one_explicit_stable_owner_statement(self) -> None:
        value = "今天聊了很多。请记住我更喜欢简短直接的回复。以后不用每次都问我问题。"
        self.assertEqual(proposed_memory_text(value), "请记住我更喜欢简短直接的回复")
        self.assertTrue(is_memory_candidate_worthy("我喜欢先看到结论再看解释"))

    def test_web_proposal_rejects_governance_import_and_transient_chatter(self) -> None:
        rejected = (
            "我批准启动 owner-local worker 并应用 Stage 15 migration",
            "课程 Goal 导入完成，sha256:abcdef0123456789",
            "今天有点累",
            "你好呀",
        )
        for value in rejected:
            with self.subTest(value=value):
                self.assertIsNone(proposed_memory_text(value))
                self.assertFalse(is_memory_candidate_worthy(value))


class RetrievalContractTests(unittest.TestCase):
    def test_request_rejects_top_k_above_candidate_k(self) -> None:
        with self.assertRaises(ValidationError):
            RetrievalRequest(
                trace_id=uuid.uuid4().hex,
                owner_id=uuid.uuid4(),
                request_id=uuid.uuid4(),
                query=RetrievalQuery(text="query", event_id=uuid.uuid4()),
                filters=RetrievalFilters(
                    allowed_privacy_classes=(PrivacyClass.NORMAL,)
                ),
                candidate_k=2,
                top_k=3,
            )

    def test_context_builder_rejects_legacy_ungated_candidates(self) -> None:
        owner_id = uuid.uuid4()
        request_id = uuid.uuid4()
        trace_id = uuid.uuid4().hex
        event = EventEnvelope(
            event_type=EventType.USER_MESSAGE,
            owner_id=owner_id,
            session_id=uuid.uuid4(),
            request_id=request_id,
            trace_id=trace_id,
            data_policy=DataPolicy.owner_default(PrivacyClass.NORMAL),
            payload=UserMessagePayload(
                content_parts=(TextContentPart(text="Question"),), channel="api"
            ),
        )
        result = self._retrieval_result(
            owner_id=owner_id, request_id=request_id, trace_id=trace_id,
            event_id=event.event_id,
            candidate=self._candidate(context_eligible=False),
            gated=False,
        )
        with self.assertRaises(ContextRetrievalRejected):
            ContextBuilder(max_input_tokens=4096, reserved_output_tokens=256).build(
                request_id=request_id, trace_id=trace_id, owner_id=owner_id,
                identity=IdentityLoader(Path("identity")).load(), user_event=event,
                retrieval_result=result,
            )

    def test_retrieval_result_rejects_context_eligible_legacy_candidate(self) -> None:
        with self.assertRaises(ValidationError):
            self._retrieval_result(
                owner_id=uuid.uuid4(), request_id=uuid.uuid4(),
                trace_id=uuid.uuid4().hex, event_id=uuid.uuid4(),
                candidate=self._candidate(context_eligible=True), gated=False,
            )

    def test_context_builder_independently_rejects_spoofed_legacy_gate(self) -> None:
        owner_id = uuid.uuid4()
        request_id = uuid.uuid4()
        trace_id = uuid.uuid4().hex
        event = self._user_event(
            owner_id=owner_id, request_id=request_id, trace_id=trace_id
        )
        valid = self._retrieval_result(
            owner_id=owner_id, request_id=request_id, trace_id=trace_id,
            event_id=event.event_id,
            candidate=self._candidate(context_eligible=True), gated=True,
        )
        spoofed = valid.model_copy(update={
            "versions": RetrievalVersions(
                algorithm_version="retrieval-r1-vector-v1",
                embedding_version_id="embedding-deterministic-hash-v1",
                index_version="memory-exact-scan-v1",
            ),
            "selection_policy": RetrievalSelectionPolicy(
                policy_version="retrieval-selection-legacy-ungated-v1"
            ),
        })
        with self.assertRaises(ContextRetrievalRejected):
            ContextBuilder(max_input_tokens=4096, reserved_output_tokens=256).build(
                request_id=request_id, trace_id=trace_id, owner_id=owner_id,
                identity=IdentityLoader(Path("identity")).load(), user_event=event,
                retrieval_result=spoofed,
            )

    def test_context_builder_rejects_mismatched_retrieval_lineage(self) -> None:
        owner_id = uuid.uuid4()
        request_id = uuid.uuid4()
        trace_id = uuid.uuid4().hex
        event = self._user_event(
            owner_id=owner_id, request_id=request_id, trace_id=trace_id
        )
        result = self._retrieval_result(
            owner_id=owner_id, request_id=request_id, trace_id=trace_id,
            event_id=event.event_id,
            candidate=self._candidate(context_eligible=True), gated=True,
        )
        mismatches = (
            result.model_copy(update={"owner_id": uuid.uuid4()}),
            result.model_copy(update={"request_id": uuid.uuid4()}),
            result.model_copy(update={"trace_id": uuid.uuid4().hex}),
            result.model_copy(update={"query_event_id": uuid.uuid4()}),
        )
        builder = ContextBuilder(max_input_tokens=4096, reserved_output_tokens=256)
        for mismatch in mismatches:
            with self.subTest(mismatch=mismatch.retrieval_result_id):
                with self.assertRaises(ContextRetrievalRejected):
                    builder.build(
                        request_id=request_id, trace_id=trace_id, owner_id=owner_id,
                        identity=IdentityLoader(Path("identity")).load(),
                        user_event=event, retrieval_result=mismatch,
                    )

    def test_retrieval_result_rejects_unqualified_gated_candidates(self) -> None:
        for semantic in (None, 0.0, float("nan")):
            candidate = self._candidate(context_eligible=True)
            if semantic != 0.8:
                candidate = candidate.model_copy(update={
                    "score_components": candidate.score_components.model_copy(
                        update={"semantic": semantic}
                    )
                })
            with self.subTest(semantic=semantic):
                with self.assertRaises(ValidationError):
                    self._retrieval_result(
                        owner_id=uuid.uuid4(), request_id=uuid.uuid4(),
                        trace_id=uuid.uuid4().hex, event_id=uuid.uuid4(),
                        candidate=candidate,
                        gated=True,
                    )

    def test_context_builder_independently_rejects_unqualified_candidates(self) -> None:
        owner_id = uuid.uuid4()
        request_id = uuid.uuid4()
        trace_id = uuid.uuid4().hex
        event = self._user_event(
            owner_id=owner_id, request_id=request_id, trace_id=trace_id
        )
        valid = self._retrieval_result(
            owner_id=owner_id, request_id=request_id, trace_id=trace_id,
            event_id=event.event_id,
            candidate=self._candidate(context_eligible=True), gated=True,
        )
        builder = ContextBuilder(max_input_tokens=4096, reserved_output_tokens=256)
        for semantic in (None, 0.0, float("nan")):
            candidate = self._candidate(context_eligible=True)
            candidate = candidate.model_copy(update={
                "score_components": candidate.score_components.model_copy(
                    update={"semantic": semantic}
                )
            })
            unsafe = valid.model_copy(update={
                "candidates": (candidate,)
            })
            with self.subTest(semantic=semantic):
                with self.assertRaises(ContextRetrievalRejected):
                    builder.build(
                        request_id=request_id, trace_id=trace_id, owner_id=owner_id,
                        identity=IdentityLoader(Path("identity")).load(),
                        user_event=event, retrieval_result=unsafe,
                    )

    def test_context_gate_accepts_declared_minimum_similarity(self) -> None:
        owner_id = uuid.uuid4()
        request_id = uuid.uuid4()
        trace_id = uuid.uuid4().hex
        event = self._user_event(
            owner_id=owner_id, request_id=request_id, trace_id=trace_id
        )
        result = self._retrieval_result(
            owner_id=owner_id, request_id=request_id, trace_id=trace_id,
            event_id=event.event_id,
            candidate=self._candidate(context_eligible=True, semantic=0.35),
            gated=True,
        )
        pack = ContextBuilder(max_input_tokens=4096, reserved_output_tokens=256).build(
            request_id=request_id, trace_id=trace_id, owner_id=owner_id,
            identity=IdentityLoader(Path("identity")).load(), user_event=event,
            retrieval_result=result,
        )
        self.assertCountEqual(
            [section.section_type for section in pack.sections],
            [
                "identity", "owner_response_instruction",
                "episodic_memory", "current_user_input",
            ],
        )

    def test_retrieval_result_rejects_duplicate_candidate_content_hashes(self) -> None:
        duplicate_hash = "sha256:" + "e" * 64
        with self.assertRaises(ValidationError):
            self._retrieval_result(
                owner_id=uuid.uuid4(), request_id=uuid.uuid4(),
                trace_id=uuid.uuid4().hex, event_id=uuid.uuid4(),
                candidates=(
                    self._candidate(
                        context_eligible=True, content_hash=duplicate_hash
                    ),
                    self._candidate(
                        context_eligible=True, content_hash=duplicate_hash, rank=2
                    ),
                ),
                gated=True,
            )

    def test_context_builder_independently_rejects_duplicate_content(self) -> None:
        owner_id = uuid.uuid4()
        request_id = uuid.uuid4()
        trace_id = uuid.uuid4().hex
        event = self._user_event(
            owner_id=owner_id, request_id=request_id, trace_id=trace_id
        )
        valid = self._retrieval_result(
            owner_id=owner_id, request_id=request_id, trace_id=trace_id,
            event_id=event.event_id,
            candidate=self._candidate(context_eligible=True), gated=True,
        )
        duplicate_hash = "sha256:" + "f" * 64
        spoofed = valid.model_copy(update={
            "candidates": (
                self._candidate(
                    context_eligible=True, content_hash=duplicate_hash
                ),
                self._candidate(
                    context_eligible=True, content_hash=duplicate_hash, rank=2
                ),
            )
        })
        with self.assertRaises(ContextRetrievalRejected):
            ContextBuilder(max_input_tokens=4096, reserved_output_tokens=256).build(
                request_id=request_id, trace_id=trace_id, owner_id=owner_id,
                identity=IdentityLoader(Path("identity")).load(), user_event=event,
                retrieval_result=spoofed,
            )

    def test_context_safe_candidates_require_contiguous_descending_rank_order(self) -> None:
        owner_id = uuid.uuid4()
        request_id = uuid.uuid4()
        trace_id = uuid.uuid4().hex
        event = self._user_event(
            owner_id=owner_id, request_id=request_id, trace_id=trace_id
        )
        first = self._candidate(context_eligible=True, semantic=0.8)
        second = self._candidate(context_eligible=True, semantic=0.7).model_copy(
            update={
                "rank": 3,
                "score": 0.9,
                "memory_id": uuid.uuid4(),
                "content_hash": "sha256:" + "9" * 64,
            }
        )
        valid = self._retrieval_result(
            owner_id=owner_id,
            request_id=request_id,
            trace_id=trace_id,
            event_id=event.event_id,
            candidate=first,
            gated=True,
        )
        material = valid.model_dump(mode="python", exclude={"content_hash"})
        material["candidates"] = (first, second)
        with self.assertRaisesRegex(
            ValidationError, "unique contiguous rank order"
        ):
            RetrievalResult.model_validate(material)

        spoofed = valid.model_copy(update={"candidates": (first, second)})
        with self.assertRaisesRegex(
            ContextRetrievalRejected, "unique contiguous rank order"
        ):
            ContextBuilder(max_input_tokens=4096, reserved_output_tokens=256).build(
                request_id=request_id,
                trace_id=trace_id,
                owner_id=owner_id,
                identity=IdentityLoader(Path("identity")).load(),
                user_event=event,
                retrieval_result=spoofed,
            )

        descending = second.model_copy(update={"rank": 2})
        material["candidates"] = (first, descending)
        with self.assertRaisesRegex(
            ValidationError, "finite descending score order"
        ):
            RetrievalResult.model_validate(material)

        spoofed = valid.model_copy(update={"candidates": (first, descending)})
        with self.assertRaisesRegex(
            ContextRetrievalRejected, "finite descending score order"
        ):
            ContextBuilder(max_input_tokens=4096, reserved_output_tokens=256).build(
                request_id=request_id,
                trace_id=trace_id,
                owner_id=owner_id,
                identity=IdentityLoader(Path("identity")).load(),
                user_event=event,
                retrieval_result=spoofed,
            )

    def test_gated_retriever_returns_empty_when_nothing_is_relevant(self) -> None:
        service = RetrievalService(
            repository=self._FakeRepository([
                self._row("Unrelated stored preference", distance=0.9)
            ]),
            embedding_provider=DeterministicEmbeddingProvider(),
        )
        result = service.retrieve(self._request("totally different query"), persist=False)
        self.assertEqual(result.candidates, ())
        self.assertEqual(
            result.exclusions[0].reason_code,
            "below_minimum_semantic_similarity",
        )

    def test_gated_retriever_suppresses_duplicate_memory(self) -> None:
        same_text = "I repeat difficult piano measures using a slow metronome."
        service = RetrievalService(
            repository=self._FakeRepository([
                self._row(same_text, distance=0.1),
                self._row(same_text, distance=0.12),
            ]),
            embedding_provider=DeterministicEmbeddingProvider(),
        )
        result = service.retrieve(self._request("slow metronome piano"), persist=False)
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(len(result.exclusions), 1)
        self.assertEqual(result.exclusions[0].reason_code, "duplicate_suppressed")

    @staticmethod
    def _request(text: str) -> RetrievalRequest:
        return RetrievalRequest(
            trace_id=uuid.uuid4().hex,
            owner_id=uuid.uuid4(),
            request_id=uuid.uuid4(),
            query=RetrievalQuery(text=text, event_id=uuid.uuid4()),
            filters=RetrievalFilters(
                allowed_privacy_classes=(PrivacyClass.NORMAL,)
            ),
        )

    @staticmethod
    def _row(text: str, *, distance: float) -> dict[str, object]:
        return {
            "memory_id": uuid.uuid4(), "revision": 1, "content_text": text,
            "content_hash": "sha256:" + uuid.uuid4().hex * 2,
            "distance": distance, "importance": 0.5, "source_refs": ["event/source"],
            "policy_revision_id": uuid.uuid4(), "privacy_class": "NORMAL",
            "memory_eligible": True, "training_eligible": False,
            "cloud_eligible": True, "policy_version": "data-policy-v1",
            "policy_decision_source": "derived_conservative",
            "policy_authorization_ref": None, "created_at": datetime.now(UTC),
        }

    @staticmethod
    def _candidate(
        *,
        context_eligible: bool,
        semantic: float | None = 0.8,
        content_hash: str | None = None,
        rank: int = 1,
    ) -> RetrievalCandidate:
        return RetrievalCandidate(
            rank=rank, memory_id=uuid.uuid4(), memory_revision=1,
            content_text="Potential memory", score=0.8,
            score_components=RetrievalScoreComponents(
                semantic=semantic, recency=1.0, importance=0.5
            ),
            selection_reason_codes=("exact_vector_similarity",),
            context_eligible=context_eligible, source_refs=("event/source",),
            data_policy=DataPolicy.owner_default(PrivacyClass.NORMAL),
            content_hash=content_hash or "sha256:" + "d" * 64,
            created_at=datetime.now(UTC),
        )

    @staticmethod
    def _user_event(*, owner_id, request_id, trace_id) -> EventEnvelope:
        return EventEnvelope(
            event_type=EventType.USER_MESSAGE,
            owner_id=owner_id,
            session_id=uuid.uuid4(),
            request_id=request_id,
            trace_id=trace_id,
            data_policy=DataPolicy.owner_default(PrivacyClass.NORMAL),
            payload=UserMessagePayload(
                content_parts=(TextContentPart(text="Question"),), channel="api"
            ),
        )

    @staticmethod
    def _retrieval_result(
        *,
        owner_id,
        request_id,
        trace_id,
        event_id,
        candidate=None,
        candidates=None,
        gated: bool,
    ) -> RetrievalResult:
        selected_candidates = candidates if candidates is not None else (candidate,)
        return RetrievalResult(
            retrieval_request_id=uuid.uuid4(), request_id=request_id,
            query_event_id=event_id, trace_id=trace_id, owner_id=owner_id,
            as_of=datetime.now(UTC),
            versions=RetrievalVersions(
                algorithm_version=(
                    "retrieval-r1-vector-gated-v2" if gated
                    else "retrieval-r1-vector-v1"
                ),
                embedding_version_id="embedding-deterministic-hash-v1",
                index_version="memory-exact-scan-v1",
            ),
            selection_policy=RetrievalSelectionPolicy(
                policy_version=(
                    "retrieval-selection-context-safe-v1" if gated
                    else "retrieval-selection-legacy-ungated-v1"
                ),
                minimum_semantic_similarity=0.35 if gated else None,
                duplicate_similarity_threshold=0.70 if gated else None,
                duplicate_token_overlap_threshold=0.65 if gated else None,
            ),
            candidates=selected_candidates,
            timing_ms=RetrievalTiming(
                query_embedding=0, candidate_search=0, filtering=0,
                reranking=0, total=0,
            ),
        )

    class _FakeRepository:
        def __init__(self, rows):
            self.rows = rows

        def search_memory_candidates(self, **_kwargs):
            return self.rows

        def persist_retrieval_result(self, **_kwargs):
            raise AssertionError("persist=False should not write")

    def test_context_pack_records_memory_use_and_effective_privacy(self) -> None:
        owner_id = uuid.uuid4()
        request_id = uuid.uuid4()
        trace_id = uuid.uuid4().hex
        event = EventEnvelope(
            event_type=EventType.USER_MESSAGE,
            owner_id=owner_id,
            session_id=uuid.uuid4(),
            request_id=request_id,
            trace_id=trace_id,
            data_policy=DataPolicy.owner_default(PrivacyClass.PRIVATE),
            payload=UserMessagePayload(
                content_parts=(TextContentPart(text="What helps my piano practice?"),),
                channel="api",
            ),
        )
        memory_id = uuid.uuid4()
        result = RetrievalResult(
            retrieval_request_id=uuid.uuid4(),
            request_id=request_id,
            query_event_id=event.event_id,
            trace_id=trace_id,
            owner_id=owner_id,
            as_of=datetime.now(UTC),
            versions=RetrievalVersions(
                algorithm_version="retrieval-r1-vector-gated-v2",
                embedding_version_id="embedding-deterministic-hash-v1",
                index_version="memory-exact-scan-v1",
            ),
            selection_policy=RetrievalSelectionPolicy(
                policy_version="retrieval-selection-context-safe-v1",
                minimum_semantic_similarity=0.35,
                duplicate_similarity_threshold=0.70,
                duplicate_token_overlap_threshold=0.65,
            ),
            candidates=(
                RetrievalCandidate(
                    rank=1,
                    memory_id=memory_id,
                    memory_revision=1,
                    content_text="I practice piano every Sunday morning.",
                    score=0.8,
                    score_components=RetrievalScoreComponents(
                        semantic=0.8, recency=1.0, importance=0.5
                    ),
                    selection_reason_codes=("exact_vector_similarity",),
                    context_eligible=True,
                    source_refs=("event/source",),
                    data_policy=DataPolicy.owner_default(PrivacyClass.PRIVATE),
                    content_hash="sha256:" + "a" * 64,
                    created_at=datetime.now(UTC),
                ),
            ),
            timing_ms=RetrievalTiming(
                query_embedding=0.1,
                candidate_search=0.2,
                filtering=0,
                reranking=0.1,
                total=0.4,
            ),
        )
        identity = IdentityLoader(Path("identity")).load()
        pack = ContextBuilder(max_input_tokens=4096, reserved_output_tokens=256).build(
            request_id=request_id,
            trace_id=trace_id,
            owner_id=owner_id,
            identity=identity,
            user_event=event,
            retrieval_result=result,
        )
        self.assertEqual(pack.retrieval_result_id, result.retrieval_result_id)
        self.assertCountEqual(
            [section.section_type for section in pack.sections],
            [
                "identity", "owner_response_instruction",
                "episodic_memory", "current_user_input",
            ],
        )
        memory_section = next(
            section for section in pack.sections
            if section.section_type == "episodic_memory"
        )
        self.assertIn(f"memory/{memory_id}/revision/1", memory_section.source_refs)
        self.assertEqual(pack.effective_data_policy.privacy_class, PrivacyClass.PRIVATE)
        self.assertFalse(pack.effective_data_policy.training_eligible)

    def test_context_pack_excludes_memory_more_private_than_current_request(self) -> None:
        owner_id, request_id = uuid.uuid4(), uuid.uuid4()
        trace_id = uuid.uuid4().hex
        event = self._user_event(
            owner_id=owner_id, request_id=request_id, trace_id=trace_id
        )
        candidate = self._candidate(context_eligible=True).model_copy(update={
            "data_policy": DataPolicy.owner_default(PrivacyClass.PRIVATE)
        })
        result = self._retrieval_result(
            owner_id=owner_id, request_id=request_id, trace_id=trace_id,
            event_id=event.event_id, candidate=candidate, gated=True,
        )
        pack = ContextBuilder(max_input_tokens=4096, reserved_output_tokens=256).build(
            request_id=request_id, trace_id=trace_id, owner_id=owner_id,
            identity=IdentityLoader(Path("identity")).load(), user_event=event,
            retrieval_result=result,
        )
        self.assertFalse(any(section.section_type == "episodic_memory" for section in pack.sections))
        self.assertIn({
            "candidate_ref": f"memory/{candidate.memory_id}/revision/1",
            "reason_code": "privacy_class_exceeds_request",
        }, pack.excluded_candidates)
        self.assertEqual(pack.effective_data_policy.privacy_class, PrivacyClass.NORMAL)

    def test_context_budget_excludes_optional_memory_with_reason(self) -> None:
        owner_id = uuid.uuid4()
        request_id = uuid.uuid4()
        trace_id = uuid.uuid4().hex
        event = EventEnvelope(
            event_type=EventType.USER_MESSAGE,
            owner_id=owner_id,
            session_id=uuid.uuid4(),
            request_id=request_id,
            trace_id=trace_id,
            data_policy=DataPolicy.owner_default(PrivacyClass.NORMAL),
            payload=UserMessagePayload(
                content_parts=(TextContentPart(text="Short query"),), channel="api"
            ),
        )
        identity = IdentityLoader(Path("identity")).load()
        base = ContextBuilder(max_input_tokens=4096, reserved_output_tokens=256).build(
            request_id=request_id,
            trace_id=trace_id,
            owner_id=owner_id,
            identity=identity,
            user_event=event,
        )
        memory_id = uuid.uuid4()
        result = RetrievalResult(
            retrieval_request_id=uuid.uuid4(), request_id=request_id,
            query_event_id=event.event_id, trace_id=trace_id, owner_id=owner_id,
            as_of=datetime.now(UTC),
            versions=RetrievalVersions(algorithm_version="retrieval-r1-vector-gated-v2", embedding_version_id="embedding-deterministic-hash-v1", index_version="memory-exact-scan-v1"),
            selection_policy=RetrievalSelectionPolicy(
                policy_version="retrieval-selection-context-safe-v1",
                minimum_semantic_similarity=0.35,
                duplicate_similarity_threshold=0.70,
                duplicate_token_overlap_threshold=0.65,
            ),
            candidates=(RetrievalCandidate(
                rank=1, memory_id=memory_id, memory_revision=1,
                content_text="x" * 1000, score=0.5,
                score_components=RetrievalScoreComponents(semantic=0.5, recency=1, importance=0.5),
                selection_reason_codes=("exact_vector_similarity",), source_refs=("event/source",),
                context_eligible=True,
                data_policy=DataPolicy.owner_default(PrivacyClass.NORMAL),
                content_hash="sha256:" + "b" * 64, created_at=datetime.now(UTC),
            ),),
            timing_ms=RetrievalTiming(query_embedding=0, candidate_search=0, filtering=0, reranking=0, total=0),
        )
        constrained = ContextBuilder(
            max_input_tokens=base.estimated_total_tokens + 256 + 10,
            reserved_output_tokens=256,
        ).build(
            request_id=request_id, trace_id=trace_id, owner_id=owner_id,
            identity=identity, user_event=event, retrieval_result=result,
        )
        self.assertEqual(len(constrained.sections), 3)
        self.assertEqual(constrained.excluded_candidates[0]["reason_code"], "token_budget_exceeded")


class RetrievalBenchmarkCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_runner_awaits_runtime_cleanup_after_failure(self) -> None:
        class FailingService:
            async def interact(self, _command):
                raise RuntimeError("synthetic benchmark failure")

        class FakeRuntime:
            def __init__(self) -> None:
                self.service = FailingService()
                self.closed = False

            async def aclose(self) -> None:
                self.closed = True

        runtime = FakeRuntime()
        fixture = {
            "gold_set_version": "cleanup-regression-v1",
            "corpus": [
                {
                    "key": "fixture",
                    "text": "Synthetic cleanup fixture.",
                    "privacy_class": "PUBLIC",
                    "importance": 0.5,
                }
            ],
        }
        with TemporaryDirectory() as directory:
            root = Path(directory)
            fixture_path = root / "fixture.json"
            fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
            with patch(
                "evals.retrieval_benchmark.build_runtime",
                return_value=runtime,
            ):
                with self.assertRaisesRegex(RuntimeError, "synthetic benchmark failure"):
                    await run_benchmark(
                        settings=SimpleNamespace(owner_id=uuid.uuid4()),
                        fixture_path=fixture_path,
                        output_path=root / "report.json",
                    )
        self.assertTrue(runtime.closed)


if __name__ == "__main__":
    unittest.main()
