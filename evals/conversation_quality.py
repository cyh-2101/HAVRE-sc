"""PUBLIC synthetic conversation-quality calibration helpers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from companion.context import ResponsePlan, render_response_plan
from companion.hashing import content_hash
from companion.policy import DataPolicy, PrivacyClass
from mlsys.retrieval.models import (
    RetrievalCandidate,
    RetrievalResult,
    RetrievalScoreComponents,
    RetrievalSelectionPolicy,
    RetrievalTiming,
    RetrievalVersions,
)


REQUIRED_MEMORY_VARIANTS = {
    "relevant",
    "irrelevant",
    "absent",
    "stale_conflicting",
    "partial",
}
SYNTHETIC_RETRIEVAL_TIME = datetime(2026, 1, 1, tzinfo=UTC)


def load_calibration_suite(path: Path) -> dict[str, Any]:
    suite = json.loads(path.read_text(encoding="utf-8"))
    if suite.get("schema_version") != 1:
        raise ValueError("unsupported conversation calibration schema")
    if suite.get("privacy_class") != "PUBLIC" or suite.get("contains_user_data") is not False:
        raise ValueError("conversation candidate calibration accepts PUBLIC synthetic data only")
    if suite.get("training_eligible") is not False or suite.get("validation_for_training") is not False:
        raise ValueError("conversation calibration fixture must remain training-ineligible")
    cases = suite.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("conversation calibration suite has no cases")
    case_ids = [case.get("case_id") for case in cases]
    if any(not isinstance(case_id, str) or not case_id for case_id in case_ids):
        raise ValueError("every conversation calibration case needs a case_id")
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("conversation calibration case_id values must be unique")
    memory_cases = [case for case in cases if case.get("category") == "memory_counterfactual"]
    if {case.get("memory_variant") for case in memory_cases} != REQUIRED_MEMORY_VARIANTS:
        raise ValueError("conversation calibration memory counterfactual is incomplete")
    latest = {case["turns"][-1]["content"] for case in memory_cases}
    if len(latest) != 1:
        raise ValueError("memory counterfactual must keep the latest user message identical")
    return suite


def build_candidate_messages(
    *,
    identity_text: str,
    response_plan: ResponsePlan,
    case: dict[str, Any],
) -> list[dict[str, str]]:
    messages = [
        {"role": "system", "content": identity_text},
        {"role": "system", "content": render_response_plan(response_plan)},
    ]
    memory_context = case.get("memory_context") or []
    if memory_context:
        memory_lines = "\n".join(f"- {item}" for item in memory_context)
        messages.append(
            {
                "role": "system",
                "content": (
                    "Potential admitted historical context. Use it silently only when relevant, "
                    "prefer the current user message when it conflicts, and never invent details:\n"
                    f"{memory_lines}"
                ),
            }
        )
    else:
        messages.append(
            {
                "role": "system",
                "content": "No long-term Memory is admitted for this case. Do not imply prior familiarity.",
            }
        )
    for turn in case["turns"]:
        role = turn.get("role")
        content = turn.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str) or not content.strip():
            raise ValueError(f"invalid turn in calibration case {case.get('case_id')}")
        messages.append({"role": role, "content": content})
    return messages


def build_synthetic_retrieval_result(
    *,
    suite_id: str,
    case: dict[str, Any],
    request_id: UUID,
    trace_id: str,
    owner_id: UUID,
) -> RetrievalResult | None:
    """Represent injected PUBLIC Memory as isolated retrieval evidence.

    This does not simulate retrieval quality or durable ContextPack admission.
    Response Plan v2 is intentionally independent of retrieval output, so all
    counterfactual arms receive the same Turn Contract for the same current turn.
    """

    memory_context = case.get("memory_context") or []
    if not memory_context:
        return None
    policy = DataPolicy.owner_default(PrivacyClass.PUBLIC)
    candidates = tuple(
        RetrievalCandidate(
            rank=index,
            memory_id=uuid5(
                NAMESPACE_URL,
                f"{suite_id}/{case['case_id']}/memory/{index}",
            ),
            memory_revision=1,
            content_text=text,
            score=0.8 - ((index - 1) * 0.01),
            score_components=RetrievalScoreComponents(
                semantic=0.8 - ((index - 1) * 0.01),
                recency=1.0,
                importance=0.5,
            ),
            selection_reason_codes=("synthetic_calibration_context",),
            context_eligible=True,
            source_refs=(f"synthetic-case/{case['case_id']}/memory/{index}",),
            data_policy=policy,
            content_hash=content_hash({"text": text}),
            created_at=SYNTHETIC_RETRIEVAL_TIME,
        )
        for index, text in enumerate(memory_context, 1)
    )
    return RetrievalResult(
        retrieval_request_id=uuid5(
            NAMESPACE_URL,
            f"{suite_id}/{case['case_id']}/retrieval",
        ),
        request_id=request_id,
        query_event_id=uuid5(
            NAMESPACE_URL,
            f"{suite_id}/{case['case_id']}/query-event",
        ),
        trace_id=trace_id,
        owner_id=owner_id,
        as_of=SYNTHETIC_RETRIEVAL_TIME,
        versions=RetrievalVersions(
            algorithm_version="retrieval-r1-vector-gated-v2",
            embedding_version_id="synthetic-calibration-v1",
            index_version="synthetic-calibration-v1",
        ),
        selection_policy=RetrievalSelectionPolicy(
            policy_version="retrieval-selection-context-safe-v1",
            minimum_semantic_similarity=0.35,
            duplicate_similarity_threshold=0.70,
            duplicate_token_overlap_threshold=0.65,
        ),
        candidates=candidates,
        timing_ms=RetrievalTiming(
            query_embedding=0,
            candidate_search=0,
            filtering=0,
            reranking=0,
            total=0,
        ),
        created_at=SYNTHETIC_RETRIEVAL_TIME,
    )


def surface_diagnostics(text: str, *, finish_reason: str | None = None) -> dict[str, Any]:
    normalized = text.strip()
    meta_phrases = ("根据记忆", "记忆显示", "检索到的记忆", "系统提供的记忆")
    return {
        "nonempty": bool(normalized),
        "character_count": len(normalized),
        "mentions_memory_mechanism": any(phrase in normalized for phrase in meta_phrases),
        "finish_reason": finish_reason,
        "possibly_length_truncated": finish_reason == "length",
        "semantic_review_required": True,
    }


def seal_report(material: dict[str, Any]) -> dict[str, Any]:
    if "content_hash" in material:
        raise ValueError("unsealed report material must not contain content_hash")
    return {**material, "content_hash": content_hash(material)}
