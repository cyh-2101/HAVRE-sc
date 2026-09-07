"""Provider-independent Stage 2 retrieval contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from companion.hashing import content_hash
from companion.ids import uuid7
from companion.policy import DataPolicy, PrivacyClass


CONTEXT_SAFE_ALGORITHM_VERSION = "retrieval-r1-vector-gated-v2"
CONTEXT_SAFE_SELECTION_POLICY_VERSION = "retrieval-selection-context-safe-v1"
CONTEXT_SAFE_MINIMUM_SEMANTIC_SIMILARITY = 0.35
CONTEXT_SAFE_DUPLICATE_SIMILARITY_THRESHOLD = 0.70
CONTEXT_SAFE_DUPLICATE_TOKEN_OVERLAP_THRESHOLD = 0.65

HYBRID_ALGORITHM_VERSION = "retrieval-r2-hybrid-v1"
HYBRID_SELECTION_POLICY_VERSION = "retrieval-selection-hybrid-v1"
HYBRID_EMBEDDING_VERSION = "embedding-minilm-multilingual-int8-v1"


def context_safety_profile(algorithm: str):
    if algorithm == CONTEXT_SAFE_ALGORITHM_VERSION:
        return (CONTEXT_SAFE_SELECTION_POLICY_VERSION, 0.35, 0.70, 0.65)
    if algorithm == HYBRID_ALGORITHM_VERSION:
        return (HYBRID_SELECTION_POLICY_VERSION, 0.20, 0.92, 0.80)
    return None


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RetrievalQuery(StrictModel):
    text: str = Field(min_length=1, max_length=100_000)
    language: str | None = Field(default=None, max_length=35)
    event_id: UUID


class RetrievalFilters(StrictModel):
    memory_classes: tuple[
        Literal["episodic", "semantic", "pattern", "progress"], ...
    ] = ("episodic", "semantic", "pattern", "progress")
    status: tuple[Literal["active"], ...] = ("active",)
    occurred_after: datetime | None = None
    occurred_before: datetime | None = None
    allowed_privacy_classes: tuple[PrivacyClass, ...]


class RetrievalRequest(StrictModel):
    schema_version: Literal[1] = 1
    retrieval_request_id: UUID = Field(default_factory=uuid7)
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    owner_id: UUID
    request_id: UUID
    query: RetrievalQuery
    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))
    filters: RetrievalFilters
    candidate_k: int = Field(default=100, ge=1, le=1000)
    top_k: int = Field(default=5, ge=1, le=100)
    algorithm_version: Literal[
        "retrieval-r0-recency-v1",
        "retrieval-r1-vector-v1",
        "retrieval-r1-vector-gated-v2",
        "retrieval-r2-hybrid-v1",
    ] = (
        "retrieval-r1-vector-gated-v2"
    )

    @model_validator(mode="after")
    def validate_k(self) -> "RetrievalRequest":
        if self.top_k > self.candidate_k:
            raise ValueError("top_k cannot exceed candidate_k")
        return self


class RetrievalScoreComponents(StrictModel):
    semantic: float | None = Field(default=None, ge=-1, le=1)
    lexical: float | None = Field(default=None, ge=0, le=1)
    recency: float = Field(ge=0, le=1)
    importance: float = Field(ge=0, le=1)
    goal_relevance: None = None
    scene_relevance: None = None
    reranker: None = None


class RetrievalCandidate(StrictModel):
    rank: int = Field(gt=0)
    memory_id: UUID
    memory_revision: int = Field(gt=0)
    memory_class: Literal["episodic", "semantic", "pattern", "progress"] = "episodic"
    content_text: str
    score: float
    score_components: RetrievalScoreComponents
    selection_reason_codes: tuple[str, ...]
    context_eligible: bool = False
    source_refs: tuple[str, ...]
    data_policy: DataPolicy
    content_hash: str
    created_at: datetime


class RetrievalVersions(StrictModel):
    algorithm_version: str
    embedding_version_id: str | None
    reranker_version_id: None = None
    index_version: str


class RetrievalSelectionPolicy(StrictModel):
    policy_version: Literal[
        "retrieval-selection-legacy-ungated-v1",
        "retrieval-selection-context-safe-v1",
        "retrieval-selection-hybrid-v1",
    ]
    minimum_semantic_similarity: float | None = Field(default=None, ge=-1, le=1)
    duplicate_similarity_threshold: float | None = Field(default=None, ge=-1, le=1)
    duplicate_token_overlap_threshold: float | None = Field(default=None, ge=0, le=1)


class RetrievalExclusion(StrictModel):
    memory_id: UUID
    memory_revision: int = Field(gt=0)
    reason_code: Literal[
        "below_minimum_semantic_similarity",
        "duplicate_suppressed",
    ]
    semantic_similarity: float | None = Field(default=None, ge=-1, le=1)
    duplicate_of_memory_id: UUID | None = None


class RetrievalTiming(StrictModel):
    query_embedding: float = Field(ge=0)
    candidate_search: float = Field(ge=0)
    filtering: float = Field(ge=0)
    reranking: float = Field(ge=0)
    total: float = Field(ge=0)


class RetrievalResult(StrictModel):
    schema_version: Literal[1] = 1
    retrieval_result_id: UUID = Field(default_factory=uuid7)
    retrieval_request_id: UUID
    request_id: UUID
    query_event_id: UUID
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    owner_id: UUID
    as_of: datetime
    versions: RetrievalVersions
    selection_policy: RetrievalSelectionPolicy
    candidates: tuple[RetrievalCandidate, ...]
    exclusions: tuple[RetrievalExclusion, ...] = ()
    timing_ms: RetrievalTiming
    degraded_components: tuple[str, ...] = ()
    content_hash: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_context_safety_gate(self) -> "RetrievalResult":
        profile = context_safety_profile(self.versions.algorithm_version)
        gated_algorithm = profile is not None
        gated_policy = self.selection_policy.policy_version != "retrieval-selection-legacy-ungated-v1"
        if self.versions.algorithm_version == HYBRID_ALGORITHM_VERSION and self.versions.embedding_version_id != HYBRID_EMBEDDING_VERSION:
            raise ValueError("hybrid retrieval requires the pinned semantic encoder")
        if gated_algorithm != gated_policy:
            raise ValueError(
                "context-safe algorithm and selection policy must be paired"
            )

        thresholds = (
            self.selection_policy.minimum_semantic_similarity,
            self.selection_policy.duplicate_similarity_threshold,
            self.selection_policy.duplicate_token_overlap_threshold,
        )
        if gated_algorithm:
            if (self.selection_policy.policy_version, *thresholds) != profile:
                raise ValueError(
                    "context-safe selection policy thresholds do not match its version"
                )
            minimum = self.selection_policy.minimum_semantic_similarity
            if minimum is None:
                raise ValueError(
                    "context-safe selection policy requires a minimum semantic "
                    "similarity"
                )
            expected_ranks = list(range(1, len(self.candidates) + 1))
            if [candidate.rank for candidate in self.candidates] != expected_ranks:
                raise ValueError(
                    "context-safe candidates must have unique contiguous rank order"
                )
            if any(
                not isfinite(candidate.score)
                for candidate in self.candidates
            ) or any(
                current.score < following.score
                for current, following in zip(
                    self.candidates, self.candidates[1:], strict=False
                )
            ):
                raise ValueError(
                    "context-safe candidates must be in finite descending score order"
                )
            content_hashes: set[str] = set()
            for candidate in self.candidates:
                if not candidate.context_eligible:
                    raise ValueError(
                        "every candidate selected by the context-safe algorithm must "
                        "be context eligible"
                    )
                semantic = candidate.score_components.semantic
                if self.versions.algorithm_version == HYBRID_ALGORITHM_VERSION and (
                    semantic is not None and semantic < 0.45
                    and (candidate.score_components.lexical or 0.0) < 0.25
                ):
                    raise ValueError("weak semantic evidence requires lexical support")
                if (
                    semantic is None
                    or not isfinite(semantic)
                    or semantic < minimum
                ):
                    raise ValueError(
                        "every context-safe candidate must meet the declared minimum "
                        "semantic similarity"
                    )
                if candidate.content_hash in content_hashes:
                    raise ValueError(
                        "context-safe candidates cannot repeat a content hash"
                    )
                content_hashes.add(candidate.content_hash)
        else:
            if any(threshold is not None for threshold in thresholds):
                raise ValueError("legacy selection policy cannot declare gated thresholds")
            if any(candidate.context_eligible for candidate in self.candidates):
                raise ValueError(
                    "legacy retrieval candidates cannot be context eligible"
                )
        return self

    def model_post_init(self, __context: object) -> None:
        expected = content_hash(
            self.model_dump(mode="json", exclude={"content_hash", "created_at"})
        )
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match RetrievalResult")
        object.__setattr__(self, "content_hash", expected)
