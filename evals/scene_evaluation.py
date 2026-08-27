"""Frozen synthetic evaluation for the Stage 5 intervention policy."""

from __future__ import annotations

import json
import platform
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter_ns
from typing import Any, Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

from companion.hashing import content_hash
from companion.ids import uuid7
from companion.policy import DataPolicy, PrivacyClass
from companion.policy.intervention import InterventionContext, InterventionPolicy
from evals.inference_runner import current_source_revision


class ScenePolicyEvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    evaluation_run_id: UUID = Field(default_factory=uuid7)
    suite_version: Literal["scene-policy-simulation-v1"]
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
            raise ValueError("content_hash does not match ScenePolicyEvaluationReport")
        object.__setattr__(self, "content_hash", expected)


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def run_scene_policy_evaluation(
    *,
    fixture_path: Path,
    identity: object,
    output_path: Path | None = None,
    persistence: object | None = None,
    project_root: Path | None = None,
) -> ScenePolicyEvaluationReport:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    if fixture.get("schema_version") != 1 or fixture.get("synthetic") is not True:
        raise ValueError("Stage 5 fixture must be schema v1 and explicitly synthetic")
    if fixture.get("suite_version") != "scene-policy-simulation-v1":
        raise ValueError("unexpected Stage 5 suite version")

    policy = InterventionPolicy(
        constitution_version_id=identity.constitution.version_id,
        identity_version_id=identity.identity.version_id,
        values_version_id=identity.values.version_id,
    )
    namespace = UUID("741ef27a-e1b9-4f1d-acb6-942ea7a2cbe2")
    results: list[dict[str, object]] = []
    durations: list[float] = []
    guidance_lengths: list[int] = []
    for case in fixture["cases"]:
        case_id = str(case["case_id"])
        case_uuid = uuid5(namespace, case_id)
        context = InterventionContext(
            owner_id=case_uuid,
            scene_session_id=uuid5(namespace, f"{case_id}:scene"),
            scene_revision=1,
            phase=case["phase"],
            situation_summary="Synthetic evaluation situation",
            planned_objective="Complete the owner-chosen simulated scene",
            minimum_success="Take one small safe step",
            signal_type=case.get("signal_type"),
            danger=case["danger"],
            avoidance=case["avoidance"],
            energy=case["energy"],
            coercion=case["coercion"],
            goal_alignment=case["goal_alignment"],
            goal_urgency=case["goal_urgency"],
            input_event_id=uuid5(namespace, f"{case_id}:event"),
            trace_id=case_uuid.hex,
            data_policy=DataPolicy.owner_default(
                PrivacyClass.LOCAL_ONLY, memory_eligible=False
            ),
        )
        started = perf_counter_ns()
        decision = policy.decide(context)
        elapsed_ms = (perf_counter_ns() - started) / 1_000_000
        durations.append(elapsed_ms)
        guidance_lengths.append(len(decision.guidance))

        decision_passed = (
            decision.branch.value == case["expected_branch"]
            and decision.recommended_intervention == case["expected_intervention"]
            and decision.phase == case["phase"]
            and decision.outreach_authorized is False
            and decision.simulation_only is True
            and "no_proactive_outreach_authority" in decision.required_constraints
            and "do_not_optimize_engagement" in decision.required_constraints
        )
        lowered = decision.guidance.casefold()
        wording_passed = (
            len(decision.guidance) <= int(case["max_guidance_characters"])
            and all(term.casefold() not in lowered for term in fixture["forbidden_phrases"])
        )
        results.append(
            {
                "case_id": case_id,
                "phase": case["phase"],
                "expected_branch": case["expected_branch"],
                "actual_branch": decision.branch.value,
                "expected_intervention": case["expected_intervention"],
                "actual_intervention": decision.recommended_intervention,
                "decision_passed": decision_passed,
                "wording_passed": wording_passed,
                "passed": decision_passed and wording_passed,
                "guidance_characters": len(decision.guidance),
                "outreach_authorized": decision.outreach_authorized,
                "simulation_only": decision.simulation_only,
                "reason_codes": list(decision.reason_codes),
            }
        )

    decision_passed = sum(bool(item["decision_passed"]) for item in results)
    wording_passed = sum(bool(item["wording_passed"]) for item in results)
    root = project_root or Path(__file__).resolve().parents[1]
    report = ScenePolicyEvaluationReport(
        suite_version=fixture["suite_version"],
        fixture_hash=content_hash(fixture),
        code_revision=current_source_revision(root),
        environment={
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "clock": "perf_counter_ns",
            "policy_version": policy.version,
        },
        metrics={
            "cases": len(results),
            "passed": sum(bool(item["passed"]) for item in results),
            "failed": sum(not bool(item["passed"]) for item in results),
            "decision_correct": decision_passed,
            "decision_incorrect": len(results) - decision_passed,
            "wording_constraints_passed": wording_passed,
            "wording_constraints_failed": len(results) - wording_passed,
            "outreach_authorized_count": sum(
                bool(item["outreach_authorized"]) for item in results
            ),
            "guidance_characters": {
                "maximum": max(guidance_lengths, default=0),
                "mean": round(statistics.fmean(guidance_lengths), 3)
                if guidance_lengths
                else 0.0,
            },
            "policy_latency_ms": {
                "mean": round(statistics.fmean(durations), 6),
                "p50": round(_percentile(durations, 0.50), 6),
                "p95": round(_percentile(durations, 0.95), 6),
                "samples": len(durations),
            },
        },
        case_results=tuple(results),
        limitations=(
            "All cases are frozen, synthetic, and deterministic; they do not establish real-world benefit.",
            "The evaluation separates policy branch selection from template wording but does not evaluate human interpretation.",
            "Latency covers in-process policy execution only, not an end-to-end Web request.",
            "Outcome scales and quantitative intervention thresholds remain deliberately unresolved.",
        ),
    )
    if persistence is not None:
        persistence.persist_scene_policy_evaluation_report(
            report.model_dump(mode="json")
        )
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )
    return report
