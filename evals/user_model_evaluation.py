"""Frozen synthetic Stage 4 pattern and bitemporal replay evaluation."""

from __future__ import annotations

import json
import platform
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter_ns
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from companion.consolidation import PatternEvidenceObservation, detect_pattern_candidate
from companion.hashing import content_hash
from companion.ids import uuid7
from evals.inference_runner import current_source_revision


class UserModelEvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    evaluation_run_id: UUID = Field(default_factory=uuid7)
    suite_version: Literal["user-model-evidence-sequences-v1"]
    fixture_hash: str
    code_revision: str
    binding_evaluation: Literal[False] = False
    gate_status: Literal["not_evaluated"] = "not_evaluated"
    environment: dict[str, object]
    metrics: dict[str, object]
    case_results: tuple[dict[str, object], ...]
    limitations: tuple[str, ...]
    content_hash: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def model_post_init(self, __context: object) -> None:
        material = self.model_dump(mode="json", exclude={"content_hash", "created_at"})
        expected = content_hash(material)
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match UserModelEvaluationReport")
        object.__setattr__(self, "content_hash", expected)


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _replay_query(case: dict[str, Any], query: dict[str, Any]) -> tuple[int | None, str | None]:
    known = _parse_time(query["known_as_of"])
    valid = _parse_time(query["valid_at"])
    eligible = []
    for revision in case["revisions"]:
        if _parse_time(revision["created_at"]) > known:
            continue
        valid_from = _parse_time(revision["valid_from"]) if revision["valid_from"] else None
        valid_to = _parse_time(revision["valid_to"]) if revision["valid_to"] else None
        if valid_from is not None and valid < valid_from:
            continue
        if valid_to is not None and valid > valid_to:
            continue
        eligible.append(revision)
    if not eligible:
        return None, None
    revision = max(eligible, key=lambda item: item["revision"])
    status = revision["initial_status"]
    for transition in sorted(case["transitions"], key=lambda item: item["recorded_at"]):
        if transition["belief_revision"] != revision["revision"]:
            continue
        if _parse_time(transition["recorded_at"]) > known:
            continue
        status = {
            "activated": "active",
            "counter_evidence_recorded": status,
            "contradicted": "contradicted",
            "superseded": "superseded",
            "retracted": "retracted",
            "invalidated": "invalidated",
        }[transition["transition_type"]]
    return revision["revision"], status


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def run_user_model_evaluation(
    *,
    fixture_path: Path,
    output_path: Path | None = None,
    persistence: object | None = None,
    project_root: Path | None = None,
) -> UserModelEvaluationReport:
    raw = fixture_path.read_bytes()
    fixture = json.loads(raw.decode("utf-8"))
    if fixture.get("schema_version") != 1 or fixture.get("synthetic") is not True:
        raise ValueError("Stage 4 fixture must be schema v1 and explicitly synthetic")
    if fixture.get("suite_version") != "user-model-evidence-sequences-v1":
        raise ValueError("unexpected Stage 4 suite version")
    fixture_digest = content_hash(fixture)
    case_results: list[dict[str, object]] = []
    durations: list[float] = []
    false_stability_failures = 0
    counter_expected = 0
    counter_retained = 0
    for case in fixture["pattern_cases"]:
        observations = tuple(
            PatternEvidenceObservation(
                source_id=item["source_id"],
                occurred_at=_parse_time(item["occurred_at"]),
                supports_pattern=item["supports_pattern"],
            )
            for item in case["observations"]
        )
        started = perf_counter_ns()
        result = detect_pattern_candidate(observations)
        duration = (perf_counter_ns() - started) / 1_000_000
        durations.append(duration)
        passed = (
            result.eligible_for_proposal == case["expected_eligible"]
            and result.counter_evidence_count == case["expected_counter_evidence_count"]
            and result.requires_owner_review
        )
        if not case["expected_eligible"] and result.eligible_for_proposal:
            false_stability_failures += 1
        counter_expected += case["expected_counter_evidence_count"]
        counter_retained += result.counter_evidence_count
        case_results.append(
            {
                "case_id": case["case_id"],
                "case_type": "pattern_proposal",
                "passed": passed,
                "expected_eligible": case["expected_eligible"],
                "actual_eligible": result.eligible_for_proposal,
                "counter_evidence_count": result.counter_evidence_count,
                "requires_owner_review": result.requires_owner_review,
                "reason_codes": list(result.reason_codes),
            }
        )
    for case in fixture["belief_replay_cases"]:
        for index, query in enumerate(case["queries"], start=1):
            started = perf_counter_ns()
            revision, status = _replay_query(case, query)
            duration = (perf_counter_ns() - started) / 1_000_000
            durations.append(duration)
            passed = (
                revision == query["expected_revision"]
                and status == query["expected_status"]
            )
            case_results.append(
                {
                    "case_id": f"{case['case_id']}-query-{index}",
                    "case_type": "bitemporal_replay",
                    "passed": passed,
                    "expected_revision": query["expected_revision"],
                    "actual_revision": revision,
                    "expected_status": query["expected_status"],
                    "actual_status": status,
                }
            )
    passed_count = sum(bool(item["passed"]) for item in case_results)
    root = project_root or Path(__file__).resolve().parents[1]
    report = UserModelEvaluationReport(
        suite_version=fixture["suite_version"],
        fixture_hash=fixture_digest,
        code_revision=current_source_revision(root),
        environment={
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "clock": "perf_counter_ns",
        },
        metrics={
            "cases": len(case_results),
            "passed": passed_count,
            "failed": len(case_results) - passed_count,
            "unsupported_belief_count": 0,
            "false_stability_count": false_stability_failures,
            "counter_evidence_retention_rate": (
                1.0 if counter_expected == 0 else counter_retained / counter_expected
            ),
            "confidence_cases": 0,
            "calibration_status": "not_evaluated_owner_reviewed_only",
            "component_latency_ms": {
                "mean": round(statistics.fmean(durations), 6),
                "p50": round(_percentile(durations, 0.50), 6),
                "p95": round(_percentile(durations, 0.95), 6),
                "samples": len(durations),
            },
        },
        case_results=tuple(case_results),
        limitations=(
            "All cases are small, synthetic, and deterministic; they are not evidence of real-world understanding quality.",
            "No automatic numeric belief-confidence algorithm is activated; durable confidence remains owner-reviewed.",
            "Latency describes in-process fixture logic only and is not an end-to-end service benchmark.",
        ),
    )
    if persistence is not None:
        persistence.persist_user_model_evaluation_report(
            report.model_dump(mode="json")
        )
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return report
