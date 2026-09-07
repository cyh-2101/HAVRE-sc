"""Standalone exact pgvector retrieval and transparent Stage 2 ranking."""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from time import perf_counter_ns
from typing import Any

from companion.memory.embedding import DeterministicEmbeddingProvider
from companion.memory.lexical import overlap as lexical_overlap, tokens as lexical_tokens
from companion.persistence.postgres import PostgresRepository
from companion.policy import DataPolicy
from mlsys.retrieval.models import (
    CONTEXT_SAFE_ALGORITHM_VERSION,
    CONTEXT_SAFE_DUPLICATE_SIMILARITY_THRESHOLD,
    CONTEXT_SAFE_DUPLICATE_TOKEN_OVERLAP_THRESHOLD,
    CONTEXT_SAFE_MINIMUM_SEMANTIC_SIMILARITY,
    CONTEXT_SAFE_SELECTION_POLICY_VERSION,
    RetrievalCandidate,
    RetrievalExclusion,
    RetrievalRequest,
    RetrievalResult,
    RetrievalScoreComponents,
    RetrievalSelectionPolicy,
    RetrievalTiming,
    RetrievalVersions,
    HYBRID_ALGORITHM_VERSION,
    context_safety_profile,
)


class RetrievalService:
    index_version = "memory-exact-scan-v1"
    context_selection_policy_version = CONTEXT_SAFE_SELECTION_POLICY_VERSION
    legacy_selection_policy_version = "retrieval-selection-legacy-ungated-v1"
    minimum_semantic_similarity = CONTEXT_SAFE_MINIMUM_SEMANTIC_SIMILARITY
    duplicate_similarity_threshold = CONTEXT_SAFE_DUPLICATE_SIMILARITY_THRESHOLD
    duplicate_token_overlap_threshold = (
        CONTEXT_SAFE_DUPLICATE_TOKEN_OVERLAP_THRESHOLD
    )

    def __init__(
        self,
        *,
        repository: PostgresRepository,
        embedding_provider: DeterministicEmbeddingProvider,
    ) -> None:
        self.repository = repository
        self.embedding_provider = embedding_provider
        self.default_algorithm = (
            HYBRID_ALGORITHM_VERSION if getattr(embedding_provider, "semantic", False)
            else CONTEXT_SAFE_ALGORITHM_VERSION
        )
        profile = context_safety_profile(self.default_algorithm)
        (self.context_selection_policy_version, self.minimum_semantic_similarity,
         self.duplicate_similarity_threshold, self.duplicate_token_overlap_threshold) = profile

    def retrieve_empty(
        self, request: RetrievalRequest, *, persist: bool = True
    ) -> RetrievalResult:
        """Persist an explicit no-retrieval result for a governed manual rerun."""

        result = RetrievalResult(
            retrieval_request_id=request.retrieval_request_id,
            request_id=request.request_id,
            query_event_id=request.query.event_id,
            trace_id=request.trace_id,
            owner_id=request.owner_id,
            as_of=request.as_of,
            versions=RetrievalVersions(
                algorithm_version=request.algorithm_version,
                embedding_version_id=self.embedding_provider.version.embedding_version_id,
                index_version=self.index_version,
            ),
            selection_policy=RetrievalSelectionPolicy(
                policy_version=self.context_selection_policy_version,
                minimum_semantic_similarity=self.minimum_semantic_similarity,
                duplicate_similarity_threshold=self.duplicate_similarity_threshold,
                duplicate_token_overlap_threshold=self.duplicate_token_overlap_threshold,
            ),
            candidates=(),
            exclusions=(),
            timing_ms=RetrievalTiming(
                query_embedding=0,
                candidate_search=0,
                filtering=0,
                reranking=0,
                total=0,
            ),
        )
        if persist:
            self.repository.persist_retrieval_result(request=request, result=result)
        return result

    def retrieve(self, request: RetrievalRequest, *, persist: bool = True) -> RetrievalResult:
        started = perf_counter_ns()
        if request.algorithm_version == HYBRID_ALGORITHM_VERSION and self.default_algorithm != HYBRID_ALGORITHM_VERSION:
            raise ValueError("hybrid retrieval requires semantic embeddings")
        if self.default_algorithm == HYBRID_ALGORITHM_VERSION and request.algorithm_version != HYBRID_ALGORITHM_VERSION:
            raise ValueError("legacy retrieval requires its historical encoder")
        embedding_started = perf_counter_ns()
        use_vector = request.algorithm_version in {
            "retrieval-r1-vector-v1",
            "retrieval-r1-vector-gated-v2",
            HYBRID_ALGORITHM_VERSION,
        }
        query_vector = (
            self.embedding_provider.embed(request.query.text)
            if use_vector
            else (0.0,) * self.embedding_provider.dimension
        )
        query_embedding_ms = (perf_counter_ns() - embedding_started) / 1_000_000

        search_started = perf_counter_ns()
        rows = self.repository.search_memory_candidates(
            request=request,
            query_vector=self.embedding_provider.pgvector(query_vector),
            embedding_version_id=self.embedding_provider.version.embedding_version_id,
            use_vector_search=use_vector,
        )
        candidate_search_ms = (perf_counter_ns() - search_started) / 1_000_000

        rank_started = perf_counter_ns()
        ranked: list[tuple[float, dict[str, object], RetrievalScoreComponents]] = []
        for row in rows:
            age_seconds = max(0.0, (request.as_of - row["created_at"]).total_seconds())
            recency = math.exp(-age_seconds / (180 * 24 * 60 * 60))
            importance = float(row["importance"])
            semantic = max(-1.0, min(1.0, 1.0 - float(row["distance"])))
            if request.algorithm_version == "retrieval-r0-recency-v1":
                score = 0.7 * recency + 0.3 * importance
                components = RetrievalScoreComponents(
                    semantic=None,
                    recency=recency,
                    importance=importance,
                )
            elif request.algorithm_version == HYBRID_ALGORITHM_VERSION:
                lexical = lexical_overlap(request.query.text, row["content_text"])
                score = 0.70 * semantic + 0.15 * lexical + 0.10 * recency + 0.05 * importance
                components = RetrievalScoreComponents(
                    semantic=semantic, lexical=lexical, recency=recency, importance=importance,
                )
            else:
                score = 0.75 * semantic + 0.15 * recency + 0.10 * importance
                components = RetrievalScoreComponents(
                    semantic=semantic,
                    recency=recency,
                    importance=importance,
                )
            ranked.append((score, row, components))
        ranked.sort(
            key=lambda item: (
                -item[0],
                -item[1]["created_at"].timestamp(),
                str(item[1]["memory_id"]),
            )
        )
        reranking_ms = (perf_counter_ns() - rank_started) / 1_000_000

        filtering_started = perf_counter_ns()
        gated = context_safety_profile(request.algorithm_version) is not None
        exclusions: list[RetrievalExclusion] = []
        context_safe: list[
            tuple[float, dict[str, Any], RetrievalScoreComponents]
        ] = []
        if gated:
            for score, row, components in ranked:
                semantic = components.semantic
                if semantic is None or semantic < self.minimum_semantic_similarity or (
                    request.algorithm_version == HYBRID_ALGORITHM_VERSION
                    and semantic < 0.45 and (components.lexical or 0.0) < 0.25
                ):
                    exclusions.append(
                        RetrievalExclusion(
                            memory_id=row["memory_id"],
                            memory_revision=row["revision"],
                            reason_code="below_minimum_semantic_similarity",
                            semantic_similarity=(
                                None if semantic is None else round(semantic, 8)
                            ),
                        )
                    )
                    continue
                duplicate_of = self._duplicate_of(row=row, accepted=context_safe)
                if duplicate_of is not None:
                    exclusions.append(
                        RetrievalExclusion(
                            memory_id=row["memory_id"],
                            memory_revision=row["revision"],
                            reason_code="duplicate_suppressed",
                            semantic_similarity=round(semantic, 8),
                            duplicate_of_memory_id=duplicate_of,
                        )
                    )
                    continue
                context_safe.append((score, row, components))
            selected = context_safe[: request.top_k]
        else:
            selected = ranked[: request.top_k]
        filtering_ms = (perf_counter_ns() - filtering_started) / 1_000_000

        candidates = tuple(
            RetrievalCandidate(
                rank=index,
                memory_id=row["memory_id"],
                memory_revision=row["revision"],
                memory_class=row.get("memory_class", "episodic"),
                content_text=row["content_text"],
                score=round(score, 8),
                score_components=components,
                selection_reason_codes=self._selection_reasons(
                    request.algorithm_version
                ),
                context_eligible=gated,
                source_refs=tuple(row["source_refs"]),
                data_policy=DataPolicy(
                    policy_revision_id=row["policy_revision_id"],
                    privacy_class=row["privacy_class"],
                    memory_eligible=row["memory_eligible"],
                    training_eligible=row["training_eligible"],
                    cloud_eligible=row["cloud_eligible"],
                    policy_version=row["policy_version"],
                    decision_source=row["policy_decision_source"],
                    authorization_ref=row["policy_authorization_ref"],
                ),
                content_hash=row["content_hash"],
                created_at=row["created_at"],
            )
            for index, (score, row, components) in enumerate(selected, start=1)
        )
        total_ms = (perf_counter_ns() - started) / 1_000_000
        result = RetrievalResult(
            retrieval_request_id=request.retrieval_request_id,
            request_id=request.request_id,
            query_event_id=request.query.event_id,
            trace_id=request.trace_id,
            owner_id=request.owner_id,
            as_of=request.as_of,
            versions=RetrievalVersions(
                algorithm_version=request.algorithm_version,
                embedding_version_id=(
                    self.embedding_provider.version.embedding_version_id
                    if use_vector
                    else None
                ),
                index_version=self.index_version,
            ),
            selection_policy=RetrievalSelectionPolicy(
                policy_version=(
                    self.context_selection_policy_version
                    if gated
                    else self.legacy_selection_policy_version
                ),
                minimum_semantic_similarity=(
                    self.minimum_semantic_similarity if gated else None
                ),
                duplicate_similarity_threshold=(
                    self.duplicate_similarity_threshold if gated else None
                ),
                duplicate_token_overlap_threshold=(
                    self.duplicate_token_overlap_threshold if gated else None
                ),
            ),
            candidates=candidates,
            exclusions=tuple(exclusions),
            timing_ms=RetrievalTiming(
                query_embedding=round(query_embedding_ms, 3),
                candidate_search=round(candidate_search_ms, 3),
                filtering=round(filtering_ms, 3),
                reranking=round(reranking_ms, 3),
                total=round(total_ms, 3),
            ),
        )
        if persist:
            self.repository.persist_retrieval_result(request=request, result=result)
        return result

    def _duplicate_of(
        self,
        *,
        row: dict[str, Any],
        accepted: list[tuple[float, dict[str, Any], RetrievalScoreComponents]],
    ):
        tokenize = lexical_tokens if self.default_algorithm == HYBRID_ALGORITHM_VERSION else self._tokens
        candidate_tokens = tokenize(row["content_text"])
        candidate_vector = self.embedding_provider.embed(row["content_text"])
        for _, accepted_row, _ in accepted:
            if row["content_hash"] == accepted_row["content_hash"]:
                return accepted_row["memory_id"]
            overlap = self._overlap_coefficient(
                candidate_tokens,
                tokenize(accepted_row["content_text"]),
            )
            if overlap < self.duplicate_token_overlap_threshold:
                continue
            accepted_vector = self.embedding_provider.embed(
                accepted_row["content_text"]
            )
            similarity = sum(
                left * right
                for left, right in zip(candidate_vector, accepted_vector, strict=True)
            )
            if similarity >= self.duplicate_similarity_threshold:
                return accepted_row["memory_id"]
        return None

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return set(re.findall(r"[a-z0-9]+", text.casefold()))

    @staticmethod
    def _overlap_coefficient(left: set[str], right: set[str]) -> float:
        denominator = min(len(left), len(right))
        if denominator == 0:
            return 0.0
        return len(left.intersection(right)) / denominator

    @staticmethod
    def _selection_reasons(algorithm_version: str) -> tuple[str, ...]:
        if algorithm_version == HYBRID_ALGORITHM_VERSION:
            return ("local_semantic_similarity", "unicode_lexical_ranking", "minimum_relevance_passed", "duplicate_suppression_passed", "owner_policy_match")
        if algorithm_version == CONTEXT_SAFE_ALGORITHM_VERSION:
            return (
                "exact_vector_similarity",
                "minimum_relevance_passed",
                "duplicate_suppression_passed",
                "active_as_of",
                "owner_policy_match",
            )
        if algorithm_version == "retrieval-r1-vector-v1":
            return (
                "exact_vector_similarity",
                "legacy_not_context_eligible",
                "active_as_of",
                "owner_policy_match",
            )
        return (
            "recency_importance_baseline",
            "benchmark_only_not_context_eligible",
            "active_as_of",
            "owner_policy_match",
        )
