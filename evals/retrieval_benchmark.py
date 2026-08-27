"""Stage 2 frozen-corpus retrieval benchmark (R0 versus R1)."""

from __future__ import annotations

import json
import math
import os
import platform
import statistics
from datetime import UTC, datetime
from pathlib import Path

from companion.application import InteractionCommand
from companion.hashing import content_hash
from companion.ids import uuid7
from companion.policy import PrivacyClass
from companion.policy.models import PRIVACY_RESTRICTION_ORDER
from mlsys.retrieval import RetrievalFilters, RetrievalQuery, RetrievalRequest
from services.api.runtime import build_runtime


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = (len(ordered) - 1) * percentile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def _metrics(
    case_results: list[dict[str, object]], duplicate_groups: list[list[str]]
) -> dict[str, float]:
    recalls_5: list[float] = []
    recalls_10: list[float] = []
    reciprocals: list[float] = []
    wrong = stale = duplicates = should_not = total = 0
    latencies: list[float] = []
    provenance_complete = 0
    for case in case_results:
        ranked = case["ranked_keys"]
        essential = case["essential"]
        essential_set = set(essential)
        recalls_5.append(len(essential_set.intersection(ranked[:5])) / len(essential_set))
        recalls_10.append(len(essential_set.intersection(ranked[:10])) / len(essential_set))
        first = next((i for i, key in enumerate(ranked, start=1) if key in essential_set), None)
        reciprocals.append(0.0 if first is None else 1.0 / first)
        allowed = essential_set.union(case["helpful"])
        wrong += sum(1 for key in ranked if key not in allowed)
        should_not += sum(1 for key in ranked if key in set(case["should_not_surface"]))
        stale += case["stale_count"]
        duplicates += sum(
            max(0, len(set(group).intersection(ranked)) - 1)
            for group in duplicate_groups
        )
        total += len(ranked)
        latencies.append(case["latency_ms"])
        provenance_complete += int(case["provenance_complete"])
    denominator = max(1, total)
    return {
        "recall_at_5": statistics.fmean(recalls_5),
        "recall_at_10": statistics.fmean(recalls_10),
        "mrr": statistics.fmean(reciprocals),
        "wrong_memory_rate": wrong / denominator,
        "stale_memory_rate": stale / denominator,
        "duplicate_rate": duplicates / denominator,
        "should_not_surface_rate": should_not / denominator,
        "provenance_completeness": provenance_complete / len(case_results),
        "p50_latency_ms": _percentile(latencies, 0.5),
        "p95_latency_ms": _percentile(latencies, 0.95),
        "error_rate": 0.0,
    }


async def run_benchmark(*, settings, fixture_path: Path, output_path: Path) -> dict[str, object]:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    runtime = build_runtime(settings)
    corpus_ids: dict[str, object] = {}
    try:
        for item in fixture["corpus"]:
            result = await runtime.service.interact(InteractionCommand(
                message=item["text"],
                privacy_class=PrivacyClass(item["privacy_class"]),
                memory_eligible=True,
                channel="cli",
                idempotency_key=f"benchmark:{fixture['gold_set_version']}:{item['key']}",
            ))
            runtime.memory_worker.run_once()
            candidates = (
                runtime.memory_service.list_candidates(owner_id=settings.owner_id, status="pending")
                + runtime.memory_service.list_candidates(owner_id=settings.owner_id, status="accepted")
            )
            candidate = next(
                row for row in candidates if row["source_event_id"] == result.user_event_id
            )
            revision = runtime.memory_service.accept_candidate(
                owner_id=settings.owner_id,
                candidate_id=candidate["candidate_id"],
                reason=f"Gold corpus {fixture['gold_set_version']}",
                importance=float(item["importance"]),
            )
            corpus_ids[item["key"]] = revision.memory_id
            if item.get("lifecycle") == "correct_to_tuesday":
                active = runtime.memory_service.list_active(owner_id=settings.owner_id)
                current = next(row for row in active if row["memory_id"] == revision.memory_id)
                if current["content_text"] != "The piano lesson is on Tuesday afternoon.":
                    runtime.memory_service.correct(
                        owner_id=settings.owner_id,
                        memory_id=revision.memory_id,
                        content_text="The piano lesson is on Tuesday afternoon.",
                        reason="Gold-set correction",
                    )

        all_results: dict[str, list[dict[str, object]]] = {}
        for algorithm in (
            "retrieval-r0-recency-v1",
            "retrieval-r1-vector-v1",
            "retrieval-r1-vector-gated-v2",
        ):
            cases: list[dict[str, object]] = []
            for query in fixture["queries"]:
                interaction = await runtime.service.interact(InteractionCommand(
                    message=query["text"],
                    privacy_class=PrivacyClass(query["privacy_class"]),
                    memory_eligible=False,
                    channel="cli",
                    idempotency_key=f"benchmark-query:{fixture['gold_set_version']}:{algorithm}:{query['key']}",
                ))
                evidence = runtime.repository.evidence(
                    interaction.request_id, owner_id=settings.owner_id
                )
                query_event_id = next(
                    event["event_id"] for event in evidence["events"]
                    if event["event_type"] == "USER_MESSAGE"
                )
                privacy = PrivacyClass(query["privacy_class"])
                allowed = tuple(
                    item for item in PrivacyClass
                    if PRIVACY_RESTRICTION_ORDER[item] <= PRIVACY_RESTRICTION_ORDER[privacy]
                )
                result = runtime.retrieval_service.retrieve(
                    RetrievalRequest(
                        trace_id=interaction.trace_id,
                        owner_id=settings.owner_id,
                        request_id=interaction.request_id,
                        query=RetrievalQuery(text=query["text"], event_id=query_event_id),
                        filters=RetrievalFilters(allowed_privacy_classes=allowed),
                        candidate_k=100,
                        top_k=5,
                        algorithm_version=algorithm,
                    ),
                    persist=False,
                )
                reverse = {str(value): key for key, value in corpus_ids.items()}
                ranked_keys = [reverse[str(item.memory_id)] for item in result.candidates]
                exclusions = [
                    {
                        "key": reverse[str(item.memory_id)],
                        "reason_code": item.reason_code,
                        "semantic_similarity": item.semantic_similarity,
                        "duplicate_of_key": (
                            None
                            if item.duplicate_of_memory_id is None
                            else reverse[str(item.duplicate_of_memory_id)]
                        ),
                    }
                    for item in result.exclusions
                ]
                cases.append({
                    "case_key": query["key"],
                    "ranked_keys": ranked_keys,
                    "selection_policy": result.selection_policy.model_dump(mode="json"),
                    "exclusions": exclusions,
                    "essential": query["essential"],
                    "helpful": query["helpful"],
                    "should_not_surface": query["should_not_surface"],
                    "stale_count": sum(
                        1 for item in result.candidates
                        if item.memory_id == corpus_ids.get("old_lesson")
                        and item.memory_revision == 1
                    ),
                    "provenance_complete": all(item.source_refs for item in result.candidates),
                    "latency_ms": result.timing_ms.total,
                })
            all_results[algorithm] = cases

        metrics = {
            algorithm: _metrics(cases, fixture["duplicate_groups"])
            for algorithm, cases in all_results.items()
        }
        flat_case_results = [
            {"algorithm_version": algorithm, **case}
            for algorithm, cases in all_results.items()
            for case in cases
        ]
        report = {
            "schema_version": 1,
            "benchmark_run_id": str(uuid7()),
            "gold_set_version": fixture["gold_set_version"],
            "review_status": fixture["review_status"],
            "corpus_hash": content_hash(fixture["corpus"]),
            "algorithm_versions": list(all_results),
            "selection_policy_versions": {
                algorithm: cases[0]["selection_policy"]["policy_version"]
                for algorithm, cases in all_results.items()
            },
            "embedding_version_id": runtime.memory_service.embedding_provider.version.embedding_version_id,
            "index_version": runtime.retrieval_service.index_version,
            "environment": {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "postgres": runtime.repository.database_version(),
                "pgvector": runtime.repository.extension_version("vector"),
                "corpus_size": len(fixture["corpus"]),
                "query_count": len(fixture["queries"]),
            },
            "metrics": metrics,
            "case_results": flat_case_results,
            "created_at": datetime.now(UTC).isoformat(),
        }
        report["content_hash"] = content_hash(report)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        runtime.repository.persist_benchmark_report(report)
        return report
    finally:
        runtime.close()
