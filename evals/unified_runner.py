"""Stage 8 unified local evaluation runner and release comparison."""

from __future__ import annotations

import json
import platform
import sys
from pathlib import Path
from typing import Iterable
from uuid import UUID

from companion.evaluation import (
    EvidenceBundle,
    EvidenceDomain,
    EvaluationArtifact,
    EvaluationArtifactPolicy,
    EvaluationCaseResult,
    EvaluationSuiteResult,
    EvaluationVersionSet,
    HumanReviewDecision,
    JudgeCalibrationReport,
    ReleaseComparison,
    Stage8OperationalEvidence,
    local_evaluation_policy,
)
from companion.hashing import content_hash
from companion.identity import IdentityLoader
from evals.inference_runner import current_source_revision
from evals.proactive_evaluation import run_proactive_evaluation
from evals.scene_evaluation import run_scene_policy_evaluation
from mlsys.contracts.inference_benchmark import InferenceCompatibilityReport


RUNNER_VERSION = "unified-evaluation-runner-v1"


def _result(
    *, case_id: str, domain: EvidenceDomain, passed: bool | None,
    summary: str, critical: bool = False, metrics: dict[str, object] | None = None,
    limitations: tuple[str, ...] = (), artifact_refs: tuple[str, ...] = (),
) -> EvaluationCaseResult:
    return EvaluationCaseResult(
        case_id=case_id,
        domain=domain,
        status="inconclusive" if passed is None else ("passed" if passed else "failed"),
        critical=critical,
        summary=summary,
        metric_values=metrics or {},
        limitations=limitations,
        artifact_refs=artifact_refs,
    )


def _suite(
    *, suite_id: str, suite_version: str, domain: EvidenceDomain,
    fixture: object, cases: Iterable[EvaluationCaseResult], binding: bool = False,
    aggregate_metrics: dict[str, object] | None = None,
    limitations: tuple[str, ...] = (),
) -> EvaluationSuiteResult:
    return EvaluationSuiteResult(
        suite_id=suite_id,
        suite_version=suite_version,
        domain=domain,
        fixture_hash=content_hash(fixture),
        runner_version=RUNNER_VERSION,
        binding=binding,
        cases=tuple(cases),
        aggregate_metrics=aggregate_metrics or {},
        limitations=limitations,
    )


def _verify_report_hash(payload: dict[str, object]) -> bool:
    expected = payload.get("content_hash")
    material = {key: value for key, value in payload.items() if key != "content_hash"}
    return isinstance(expected, str) and expected == content_hash(material)


def run_stage8_unified_evaluation(
    *, project_root: Path, owner_id: UUID, candidate_release_id: str,
    output_path: Path | None = None,
    operational_evidence: Stage8OperationalEvidence | None = None,
) -> tuple[EvidenceBundle, tuple[EvaluationArtifact, ...], JudgeCalibrationReport]:
    if operational_evidence is not None and operational_evidence.owner_id != owner_id:
        raise ValueError("operational evidence owner mismatch")
    identity = IdentityLoader(project_root / "identity").load()
    unified_fixture = json.loads(
        (project_root / "evals" / "fixtures" / "stage8_unified_cases_v1.json")
        .read_text(encoding="utf-8")
    )
    if unified_fixture.get("synthetic") is not True or unified_fixture.get("schema_version") != 1:
        raise ValueError("Stage 8 unified fixture must be explicitly synthetic schema v1")

    scene = run_scene_policy_evaluation(
        fixture_path=project_root / "evals" / "fixtures" / "scene_policy_cases_v1.json",
        identity=identity,
        project_root=project_root,
    )
    proactive = run_proactive_evaluation(
        fixture_path=project_root / "evals" / "fixtures" / "proactive_policy_cases_v1.json",
        identity=identity,
    )
    retrieval_path = project_root / "var" / "benchmarks" / "stage2_retrieval_correction_final_repeat.json"
    retrieval = json.loads(retrieval_path.read_text(encoding="utf-8"))
    inference_path = (
        project_root / "var" / "benchmarks" / "stage3-correction-20260814-final-9a43713e"
        / "inference-compatibility.json"
    )
    inference_raw = json.loads(inference_path.read_text(encoding="utf-8"))
    inference = InferenceCompatibilityReport.model_validate(inference_raw)

    behavioral_cases = tuple(
        _result(
            case_id=str(item["case_id"]), domain=EvidenceDomain.BEHAVIORAL,
            passed=bool(item["passed"]),
            summary="Synthetic intervention branch and wording constraints",
            critical=not bool(item["decision_passed"]),
            metrics={
                "decision_passed": item["decision_passed"],
                "wording_passed": item["wording_passed"],
                "outreach_authorized": item["outreach_authorized"],
            },
        )
        for item in scene.case_results
    )
    behavioral = _suite(
        suite_id="behavioral-scene", suite_version=scene.suite_version,
        domain=EvidenceDomain.BEHAVIORAL,
        fixture={"fixture_hash": scene.fixture_hash}, cases=behavioral_cases,
        aggregate_metrics=scene.metrics, limitations=scene.limitations,
    )

    selected_retrieval = retrieval["metrics"]["retrieval-r1-vector-gated-v2"]
    retrieval_hash_ok = _verify_report_hash(retrieval)
    retrieval_case = _result(
        case_id="retrieval-r1-vector-gated-v2",
        domain=EvidenceDomain.RETRIEVAL,
        passed=(
            retrieval_hash_ok
            and selected_retrieval["provenance_completeness"] == 1.0
            and selected_retrieval["should_not_surface_rate"] == 0.0
            and selected_retrieval["error_rate"] == 0.0
        ),
        summary="Hash-verified frozen retrieval report with independent safety metrics",
        critical=not retrieval_hash_ok or selected_retrieval["should_not_surface_rate"] != 0.0,
        metrics=selected_retrieval,
        limitations=(
            "Wrong-memory rate remains 0.375 and is not a production semantic-quality pass.",
            "The Stage 2 corpus is small, synthetic, and manually reviewed.",
        ),
        artifact_refs=("local://var/benchmarks/stage2_retrieval_correction_final_repeat.json",),
    )
    retrieval_suite = _suite(
        suite_id="retrieval-gold", suite_version=str(retrieval["gold_set_version"]),
        domain=EvidenceDomain.RETRIEVAL, fixture={"corpus_hash": retrieval["corpus_hash"]},
        cases=(retrieval_case,), aggregate_metrics=selected_retrieval,
        limitations=retrieval_case.limitations,
    )

    context_data = proactive.context_tradeoff
    context_suite = _suite(
        suite_id="controlled-context", suite_version="controlled-context-strategy-v1",
        domain=EvidenceDomain.CONTEXT, fixture=context_data,
        cases=(_result(
            case_id="prefix-stability-and-budget", domain=EvidenceDomain.CONTEXT,
            passed=(bool(context_data["prefix_hash_equal"]) and int(context_data["compressed_tokens"]) < int(context_data["raw_tokens"])),
            summary="Controlled compression preserves governed prefix and reduces tokens",
            critical=not bool(context_data["prefix_hash_equal"]), metrics=context_data,
        ),), aggregate_metrics=context_data,
    )
    routing_data = proactive.routing_tradeoff
    routing_suite = _suite(
        suite_id="privacy-first-routing", suite_version="adaptive-router-v1",
        domain=EvidenceDomain.ROUTING, fixture=routing_data,
        cases=(_result(
            case_id="local-only-cloud-exclusion", domain=EvidenceDomain.ROUTING,
            passed=(routing_data["cloud_exclusion"] in {
                "cloud_forbidden_by_data_policy", "privacy_class_not_approved"
            }),
            summary="LOCAL_ONLY provider eligibility is enforced before ranking",
            critical=True, metrics=routing_data,
        ),), aggregate_metrics=routing_data,
    )

    inference_cases = tuple(
        _result(
            case_id=item.workload_case_id, domain=EvidenceDomain.INFERENCE,
            passed=None,
            summary="Candidate and baseline completed; behavioral quality remains non-binding",
            metrics={
                "candidate_status": item.candidate_status,
                "baseline_status": item.baseline_status,
            },
            limitations=("Stage 3 compatibility gate_status is not_evaluated.",),
            artifact_refs=(
                "local://var/benchmarks/stage3-correction-20260814-final-9a43713e/inference-compatibility.json",
            ),
        )
        for item in inference.case_results
    )
    inference_suite = _suite(
        suite_id="inference-compatibility", suite_version="stage3-source-bound-v1",
        domain=EvidenceDomain.INFERENCE,
        fixture={"workload_content_hash": inference.workload_content_hash},
        cases=inference_cases,
        limitations=tuple(inference.limitations),
    )

    proactive_cases = tuple(
        _result(
            case_id=str(item["case_id"]), domain=EvidenceDomain.PROACTIVE,
            passed=bool(item["passed"]),
            summary="Four-way interruption decision synthetic fixture",
            critical=(item["actual"] == "SEND_NOW" and item["expected"] != "SEND_NOW"),
            metrics={"expected": item["expected"], "actual": item["actual"]},
        )
        for item in proactive.case_results
    ) + tuple(
        _result(
            case_id=f"runtime-{case_id}", domain=EvidenceDomain.PROACTIVE,
            passed=(None if operational_evidence is None else passed),
            summary="PostgreSQL-backed local synthetic proactive lifecycle assertion",
            critical=True,
            metrics={"observed": passed} if operational_evidence is not None else {},
            limitations=("Operational PostgreSQL evidence was not supplied.",)
            if operational_evidence is None else (),
        )
        for case_id, passed in (
            operational_evidence.proactive_outcomes.items()
            if operational_evidence is not None else {
                "trace_complete": False,
                "proposal_decision_render_delivery_linked": False,
                "delivery_idempotent": False,
                "privacy_local_only": False,
                "missing_context_fails_closed": False,
            }.items()
        )
    )
    proactive_suite = _suite(
        suite_id="proactive-policy", suite_version=proactive.suite_version,
        domain=EvidenceDomain.PROACTIVE,
        fixture={"fixture_hash": proactive.fixture_hash}, cases=proactive_cases,
        aggregate_metrics=proactive.metrics,
        limitations=proactive.limitations + (
            "Usefulness remains explicitly inconclusive because synthetic fixtures have no truthful owner-benefit label.",
        ),
    )
    proactive_suite = proactive_suite.model_copy(update={
        "cases": proactive_suite.cases + (_result(
            case_id="usefulness-owner-benefit-label",
            domain=EvidenceDomain.PROACTIVE, passed=None,
            summary="Usefulness requires an explicit owner outcome label; non-response is not a negative label",
            critical=False,
            limitations=("No real owner-benefit outcome is authorized or available in Stage 8.",),
        ),),
        "content_hash": "",
    })
    proactive_suite = EvaluationSuiteResult.model_validate(
        proactive_suite.model_dump(mode="python")
    )

    memory_cases = []
    for case in unified_fixture["memory_lifecycle_cases"]:
        actual = (
            operational_evidence.memory_lifecycle_outcomes.get(case["case_id"])
            if operational_evidence is not None else None
        )
        memory_cases.append(_result(
            case_id=case["case_id"], domain=EvidenceDomain.MEMORY_LIFECYCLE,
            passed=None if actual is None else actual == case["expected"],
            summary="Observed Stage 7 PostgreSQL lifecycle remains proposal/review separated",
            critical=True, metrics={"expected": case["expected"], "actual": actual},
            limitations=("Operational PostgreSQL evidence was not supplied.",)
            if actual is None else (),
        ))
    memory_suite = _suite(
        suite_id="memory-lifecycle", suite_version=unified_fixture["suite_version"],
        domain=EvidenceDomain.MEMORY_LIFECYCLE,
        fixture=unified_fixture["memory_lifecycle_cases"], cases=memory_cases,
    )

    erasure_cases = []
    for case in unified_fixture["erasure_regeneration_cases"]:
        actual = (
            operational_evidence.erasure_regeneration_outcomes.get(case["case_id"])
            if operational_evidence is not None else None
        )
        erasure_cases.append(_result(
            case_id=case["case_id"], domain=EvidenceDomain.ERASURE_REGENERATION,
            passed=None if actual is None else actual == case["expected"],
            summary="Observed Stage 7 revocation and reproducible rebuild behavior",
            critical=True, metrics={"expected": case["expected"], "actual": actual},
            limitations=("Operational PostgreSQL evidence was not supplied.",)
            if actual is None else (),
        ))
    erasure_suite = _suite(
        suite_id="erasure-regeneration", suite_version=unified_fixture["suite_version"],
        domain=EvidenceDomain.ERASURE_REGENERATION,
        fixture=unified_fixture["erasure_regeneration_cases"], cases=erasure_cases,
    )

    source_health_cases = []
    for case in unified_fixture["source_health_cases"]:
        actual = (
            operational_evidence.source_health_outcomes.get(case["case_id"])
            if operational_evidence is not None else None
        )
        source_health_cases.append(_result(
            case_id=case["case_id"], domain=EvidenceDomain.SOURCE_HEALTH,
            passed=None if actual is None else actual == case["expected"],
            summary="Contract-evaluated source health/freshness/consent remains observation-only",
            critical=True, metrics={"expected": case["expected"], "actual": actual},
            limitations=("Operational contract evidence was not supplied.",)
            if actual is None else (),
        ))
    source_health_suite = _suite(
        suite_id="source-health", suite_version=unified_fixture["suite_version"],
        domain=EvidenceDomain.SOURCE_HEALTH,
        fixture=unified_fixture["source_health_cases"], cases=source_health_cases,
        limitations=("No external Context Source is activated or measured.",),
    )

    regression_suite = _suite(
        suite_id="stage8-regression-closure",
        suite_version="stage8-regression-closure-v1",
        domain=EvidenceDomain.REGRESSION,
        fixture={
            "operational_evidence_hash": (
                operational_evidence.content_hash if operational_evidence else None
            ),
            "fixture_hash": content_hash(unified_fixture),
        },
        cases=(
            _result(
                case_id="postgres-operational-evidence-required",
                domain=EvidenceDomain.REGRESSION,
                passed=operational_evidence is not None,
                summary="Unified evaluation cannot self-certify Stage 6/7 runtime behavior",
                critical=True,
            ),
            _result(
                case_id="operational-evidence-local-training-denied",
                domain=EvidenceDomain.REGRESSION,
                passed=(
                    operational_evidence is not None
                    and operational_evidence.privacy_class == "LOCAL_ONLY"
                    and not operational_evidence.training_eligible
                    and not operational_evidence.external_source_activated
                    and not operational_evidence.real_delivery_attempted
                ),
                summary="Operational evidence remains local, training-ineligible, synthetic, and no-delivery",
                critical=True,
            ),
        ),
    )

    suites = (
        behavioral, retrieval_suite, context_suite, routing_suite,
        inference_suite, proactive_suite, memory_suite, erasure_suite,
        source_health_suite, regression_suite,
    )
    calibration_fixture = unified_fixture["judge_calibration"]
    label_map = {
        "critical_failure": "fail", "nonbinding": "inconclusive",
        "passed": "pass", "missing_required_domain": "fail",
    }
    disagreements = tuple(
        case["case_id"] for case in calibration_fixture["cases"]
        if label_map.get(case["rule_signal"]) != case["human_label"]
    )
    calibration = JudgeCalibrationReport(
        owner_id=owner_id,
        calibration_set_id=calibration_fixture["calibration_set_id"],
        calibration_set_hash=content_hash(calibration_fixture["cases"]),
        judge_id=calibration_fixture["judge_id"],
        judge_version=calibration_fixture["judge_version"],
        judge_kind="deterministic_fixture",
        human_label_count=len(calibration_fixture["cases"]),
        agreement_count=len(calibration_fixture["cases"]) - len(disagreements),
        disagreement_case_ids=disagreements,
        agreement_rate=(len(calibration_fixture["cases"]) - len(disagreements)) / len(calibration_fixture["cases"]),
        limitations=(
            "This calibrates the deterministic gate workflow, not a model judge.",
            "Critical failures still require direct assertions and human adjudication.",
        ),
    )

    artifact_policy = EvaluationArtifactPolicy(
        allowed_roles=("owner", "technical_reviewer", "human_reviewer"),
        review_after_days=30,
    )
    artifacts = tuple(
        EvaluationArtifact(
            owner_id=owner_id, artifact_kind="suite_result",
            artifact_uri=f"inline://{suite.content_hash}",
            artifact_content_hash=suite.content_hash,
            media_type="application/json", data_policy=local_evaluation_policy(),
            access_policy=artifact_policy,
        )
        for suite in suites
    ) + (
        EvaluationArtifact(
            owner_id=owner_id, artifact_kind="systems_report",
            artifact_uri=f"inline://{operational_evidence.content_hash if operational_evidence else content_hash({'missing': 'operational_evidence'})}",
            artifact_content_hash=(operational_evidence.content_hash if operational_evidence else content_hash({"missing": "operational_evidence"})),
            media_type="application/json", data_policy=local_evaluation_policy(),
            access_policy=artifact_policy,
        ),
        EvaluationArtifact(
            owner_id=owner_id, artifact_kind="judge_calibration",
            artifact_uri=f"inline://{calibration.content_hash}",
            artifact_content_hash=calibration.content_hash,
            media_type="application/json", data_policy=local_evaluation_policy(),
            access_policy=artifact_policy,
        ),
    ) + tuple(
        EvaluationArtifact(
            owner_id=owner_id, artifact_kind="trace_export",
            artifact_uri=f"inline://trace/{trace_id}",
            artifact_content_hash=operational_evidence.trace_content_hashes[trace_id],
            media_type="application/json", data_policy=local_evaluation_policy(),
            access_policy=artifact_policy,
        )
        for trace_id in (operational_evidence.trace_ids if operational_evidence else ())
    )
    critical_failures = tuple(
        f"{suite.domain.value}:{case.case_id}"
        for suite in suites for case in suite.cases
        if case.critical and case.status != "passed"
    )
    errors = tuple(
        f"{suite.domain.value}:{case.case_id}"
        for suite in suites for case in suite.cases if case.status == "error"
    )
    gate = "rejected" if critical_failures else ("inconclusive" if errors else "candidate_review")
    exceptions = tuple(
        f"{suite.domain.value}:{case.case_id}:inconclusive"
        for suite in suites for case in suite.cases if case.status == "inconclusive"
    )
    versions = EvaluationVersionSet(
        code_revision=current_source_revision(project_root),
        environment_hash=content_hash({
            "python": sys.version.split()[0], "platform": platform.platform(),
            "runner": RUNNER_VERSION,
        }),
        component_versions={
            "scene_policy": "intervention-policy-sim-v1",
            "retrieval": "retrieval-r1-vector-gated-v2",
            "context": "controlled-context-strategy-v1",
            "router": "adaptive-router-v1",
            "proactive_policy": "interruption-policy-conservative-v1",
            "offline_pipeline": "stage7-offline-v1",
        },
        constitution_version_id=identity.constitution.version_id,
        identity_version_id=identity.identity.version_id,
        values_version_id=identity.values.version_id,
        policy_versions={
            "data_policy": "data-policy-v1",
            "artifact_access_retention": artifact_policy.policy_version,
        },
        judge_versions={calibration.judge_id: calibration.judge_version},
    )
    bundle = EvidenceBundle(
        owner_id=owner_id, candidate_release_id=candidate_release_id,
        versions=versions, suite_results=suites,
        artifact_ids=tuple(item.artifact_id for item in artifacts),
        trace_ids=operational_evidence.trace_ids if operational_evidence else (),
        judge_calibration_ids=(calibration.calibration_id,),
        exceptions=exceptions, critical_failures=critical_failures,
        automated_gate=gate,
    )
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(bundle.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return bundle, artifacts, calibration


def compare_evidence_bundles(
    *, owner_id: UUID, baseline: EvidenceBundle, candidate: EvidenceBundle,
    controlled_differences: tuple[str, ...], uncontrolled_differences: tuple[str, ...] = (),
) -> ReleaseComparison:
    if baseline.owner_id != owner_id or candidate.owner_id != owner_id:
        raise ValueError("release comparison owner mismatch")
    baseline_versions = baseline.versions.model_dump(mode="json")
    candidate_versions = candidate.versions.model_dump(mode="json")
    observed_version_differences = tuple(sorted(
        f"versions.{key}"
        for key in set(baseline_versions) | set(candidate_versions)
        if baseline_versions.get(key) != candidate_versions.get(key)
    ))
    undeclared_version_differences = tuple(
        item for item in observed_version_differences
        if item not in controlled_differences
    )
    effective_uncontrolled = tuple(sorted(set(
        uncontrolled_differences + undeclared_version_differences
    )))
    def counts(bundle: EvidenceBundle) -> dict[str, dict[str, int]]:
        result: dict[str, dict[str, int]] = {}
        for suite in bundle.suite_results:
            values = result.setdefault(suite.domain.value, {"passed": 0, "failed": 0, "inconclusive": 0, "error": 0})
            for case in suite.cases:
                values[case.status] += 1
        return result
    before, after = counts(baseline), counts(candidate)
    deltas = {
        domain: {status: after.get(domain, {}).get(status, 0) - before.get(domain, {}).get(status, 0)
                 for status in ("passed", "failed", "inconclusive", "error")}
        for domain in sorted(set(before) | set(after))
    }
    critical_regressions = tuple(sorted(candidate.critical_failures))
    noncritical = tuple(
        sorted(
            f"{domain}:failed_delta={values['failed']}"
            for domain, values in deltas.items() if values["failed"] > 0
        )
    )
    baseline_suites = {suite.domain: suite for suite in baseline.suite_results}
    candidate_suites = {suite.domain: suite for suite in candidate.suite_results}
    comparable = baseline_suites.keys() == candidate_suites.keys() and all(
        (
            baseline_suites[domain].suite_id,
            baseline_suites[domain].suite_version,
            baseline_suites[domain].fixture_hash,
            baseline_suites[domain].runner_version,
        ) == (
            candidate_suites[domain].suite_id,
            candidate_suites[domain].suite_version,
            candidate_suites[domain].fixture_hash,
            candidate_suites[domain].runner_version,
        )
        for domain in baseline_suites
    )
    recommendation = (
        "reject" if candidate.automated_gate == "rejected" or critical_regressions else
        "inconclusive" if baseline.automated_gate != "candidate_review"
        or candidate.automated_gate != "candidate_review"
        or effective_uncontrolled or not comparable else "candidate_review"
    )
    return ReleaseComparison(
        owner_id=owner_id, baseline_bundle_id=baseline.evidence_bundle_id,
        candidate_bundle_id=candidate.evidence_bundle_id,
        controlled_differences=controlled_differences,
        uncontrolled_differences=effective_uncontrolled,
        observed_version_differences=observed_version_differences,
        domain_deltas=deltas, critical_regressions=critical_regressions,
        noncritical_regressions=noncritical,
        automated_recommendation=recommendation,
    )


def finalize_stage8_evidence_bundle(
    *, owner_id: UUID, candidate: EvidenceBundle,
    candidate_artifacts: tuple[EvaluationArtifact, ...],
    comparison: ReleaseComparison, review_decision: HumanReviewDecision,
) -> tuple[EvidenceBundle, tuple[EvaluationArtifact, ...]]:
    """Create the immutable closure manifest after comparison and human review."""

    if candidate.owner_id != owner_id or comparison.owner_id != owner_id:
        raise ValueError("Stage 8 finalization owner mismatch")
    if comparison.candidate_bundle_id != candidate.evidence_bundle_id:
        raise ValueError("comparison must name the reviewed candidate bundle")
    if comparison.automated_recommendation != "candidate_review":
        raise ValueError("only a candidate-review comparison can be finalized")
    if review_decision.owner_id != owner_id:
        raise ValueError("review decision owner mismatch")
    if review_decision.decision != "accepted_for_candidate_evidence" or review_decision.blocking_findings:
        raise ValueError("Stage 8 finalization requires a blocker-free acceptance")
    if {item.artifact_id for item in candidate_artifacts} != set(candidate.artifact_ids):
        raise ValueError("candidate artifacts do not match candidate bundle")
    copied = tuple(
        EvaluationArtifact(
            owner_id=owner_id, artifact_kind=item.artifact_kind,
            artifact_uri=item.artifact_uri,
            artifact_content_hash=item.artifact_content_hash,
            media_type=item.media_type, data_policy=item.data_policy,
            access_policy=item.access_policy,
        )
        for item in candidate_artifacts
    )
    policy = candidate_artifacts[0].access_policy
    additions = (
        EvaluationArtifact(
            owner_id=owner_id, artifact_kind="release_comparison",
            artifact_uri=f"inline://{comparison.content_hash}",
            artifact_content_hash=comparison.content_hash,
            media_type="application/json", data_policy=local_evaluation_policy(),
            access_policy=policy,
        ),
        EvaluationArtifact(
            owner_id=owner_id, artifact_kind="human_review",
            artifact_uri=f"inline://{review_decision.content_hash}",
            artifact_content_hash=review_decision.content_hash,
            media_type="application/json", data_policy=local_evaluation_policy(),
            access_policy=policy,
        ),
        EvaluationArtifact(
            owner_id=owner_id, artifact_kind="evidence_bundle",
            artifact_uri=f"inline://{candidate.content_hash}",
            artifact_content_hash=candidate.content_hash,
            media_type="application/json", data_policy=local_evaluation_policy(),
            access_policy=policy,
        ),
    )
    artifacts = copied + additions
    final = EvidenceBundle(
        owner_id=owner_id, candidate_release_id=candidate.candidate_release_id,
        versions=candidate.versions, suite_results=candidate.suite_results,
        artifact_ids=tuple(item.artifact_id for item in artifacts),
        trace_ids=candidate.trace_ids,
        judge_calibration_ids=candidate.judge_calibration_ids,
        release_comparison_ids=(comparison.comparison_id,),
        human_review_decision_ids=(review_decision.review_decision_id,),
        exceptions=candidate.exceptions,
        critical_failures=candidate.critical_failures,
        automated_gate=candidate.automated_gate,
        explicit_decision="accepted_for_stage9_candidate_foundation",
    )
    return final, artifacts
