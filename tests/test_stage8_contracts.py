from __future__ import annotations

import json
import unittest
import uuid
from pathlib import Path

from pydantic import ValidationError

from companion.evaluation import (
    REQUIRED_STAGE8_DOMAINS,
    EvaluationArtifact,
    EvaluationArtifactPolicy,
    HumanReviewDecision,
    EvidenceBundle,
    ReleaseComparison,
    Stage8OperationalEvidence,
    local_evaluation_policy,
)
from evals.unified_runner import compare_evidence_bundles, run_stage8_unified_evaluation
from scripts.export_contract_schemas import CONTRACTS


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Stage8ContractTests(unittest.TestCase):
    def _operational_evidence(self, owner_id):
        return Stage8OperationalEvidence(
            owner_id=owner_id,
            memory_lifecycle_outcomes={
                "ordinary-event-remains-event-only": "proposal_pending",
                "historical-validity-not-current": "excluded_stale_current",
                "archive-review-does-not-mutate-memory": "active_memory",
                "reconsolidation-rejection-does-not-mutate-memory": "active_memory",
            },
            erasure_regeneration_outcomes={
                "revoked-source-cannot-regenerate": "rejected_source_revoked",
                "eligible-synthetic-source-can-rebuild-manifest": "same_content_hash",
            },
            source_health_outcomes={
                "fresh-consented-observation": "eligible_observation_only",
                "stale-observation": "ineligible_stale",
                "revoked-observation": "ineligible_revoked",
                "missing-source-is-not-negative-evidence": "unknown_not_negative_evidence",
            },
            proactive_outcomes={
                "trace_complete": True,
                "proposal_decision_render_delivery_linked": True,
                "delivery_idempotent": True,
                "privacy_local_only": True,
                "missing_context_fails_closed": True,
                "owner_action_linked": True,
            },
            trace_ids=(trace_id := uuid.uuid4().hex,),
            trace_content_hashes={trace_id: "sha256:" + "1" * 64},
        )

    def test_unified_runner_covers_required_domains_and_never_promotes(self) -> None:
        owner_id = uuid.uuid4()
        bundle, artifacts, calibration = run_stage8_unified_evaluation(
            project_root=PROJECT_ROOT,
            owner_id=owner_id,
            candidate_release_id="stage8-contract-candidate-v1",
            operational_evidence=self._operational_evidence(owner_id),
        )
        self.assertEqual(bundle.automated_gate, "candidate_review")
        self.assertFalse(bundle.release_promotion_authorized)
        self.assertEqual(
            REQUIRED_STAGE8_DOMAINS,
            REQUIRED_STAGE8_DOMAINS & {suite.domain for suite in bundle.suite_results},
        )
        self.assertGreater(len(artifacts), len(bundle.suite_results))
        self.assertTrue(all(item.artifact_uri.startswith("inline://") for item in artifacts))
        self.assertTrue(all(not item.data_policy.cloud_eligible for item in artifacts))
        self.assertEqual(calibration.agreement_rate, 1.0)
        self.assertFalse(calibration.critical_clearance_authority)
        self.assertTrue(bundle.exceptions)

    def test_runner_fails_closed_without_postgres_operational_evidence(self) -> None:
        bundle, _, _ = run_stage8_unified_evaluation(
            project_root=PROJECT_ROOT, owner_id=uuid.uuid4(),
            candidate_release_id="missing-operational-evidence",
        )
        self.assertEqual(bundle.automated_gate, "rejected")
        self.assertTrue(bundle.critical_failures)
        self.assertEqual(bundle.trace_ids, ())

    def test_rejected_candidate_cannot_bypass_comparison_with_same_baseline_failure(self) -> None:
        owner_id = uuid.uuid4()
        candidate, _, _ = run_stage8_unified_evaluation(
            project_root=PROJECT_ROOT, owner_id=owner_id,
            candidate_release_id="candidate-without-operational-evidence",
        )
        baseline, _, _ = run_stage8_unified_evaluation(
            project_root=PROJECT_ROOT, owner_id=owner_id,
            candidate_release_id="baseline-without-operational-evidence",
        )
        comparison = compare_evidence_bundles(
            owner_id=owner_id, baseline=baseline, candidate=candidate,
            controlled_differences=(),
        )
        self.assertEqual(comparison.automated_recommendation, "reject")
        self.assertTrue(comparison.critical_regressions)

    def test_release_comparison_requires_every_version_difference_to_be_declared(self) -> None:
        owner_id = uuid.uuid4()
        evidence = self._operational_evidence(owner_id)
        baseline, _, _ = run_stage8_unified_evaluation(
            project_root=PROJECT_ROOT, owner_id=owner_id,
            candidate_release_id="version-baseline", operational_evidence=evidence,
        )
        payload = baseline.model_dump(mode="python")
        payload["evidence_bundle_id"] = uuid.uuid4()
        payload["candidate_release_id"] = "version-candidate"
        payload["versions"]["code_revision"] = "sha256:" + "9" * 64
        payload["content_hash"] = ""
        candidate = EvidenceBundle.model_validate(payload)
        comparison = compare_evidence_bundles(
            owner_id=owner_id, baseline=baseline, candidate=candidate,
            controlled_differences=(),
        )
        self.assertEqual(comparison.automated_recommendation, "inconclusive")
        self.assertEqual(comparison.observed_version_differences, ("versions.code_revision",))
        self.assertIn("versions.code_revision", comparison.uncontrolled_differences)

    def test_artifacts_cannot_enable_cloud_or_automatic_deletion(self) -> None:
        with self.assertRaises(ValidationError):
            EvaluationArtifact(
                owner_id=uuid.uuid4(), artifact_kind="suite_result",
                artifact_uri="https://example.invalid/report.json",
                artifact_content_hash="sha256:" + "1" * 64,
                media_type="application/json", data_policy=local_evaluation_policy(),
                access_policy=EvaluationArtifactPolicy(allowed_roles=("owner",)),
            )
        with self.assertRaises(ValidationError):
            EvaluationArtifactPolicy.model_validate({
                "allowed_roles": ["owner"], "automatic_deletion": True,
            })

    def test_critical_regression_cannot_receive_candidate_recommendation(self) -> None:
        base = {
            "owner_id": uuid.uuid4(),
            "baseline_bundle_id": uuid.uuid4(),
            "candidate_bundle_id": uuid.uuid4(),
            "controlled_differences": ("runner",),
            "uncontrolled_differences": (),
            "domain_deltas": {},
            "critical_regressions": ("privacy-bypass",),
            "automated_recommendation": "candidate_review",
        }
        with self.assertRaises(ValidationError):
            ReleaseComparison.model_validate(base)

    def test_blocking_human_review_cannot_accept_candidate_evidence(self) -> None:
        with self.assertRaises(ValidationError):
            HumanReviewDecision(
                owner_id=uuid.uuid4(), review_request_id=uuid.uuid4(),
                reviewer_role="technical_reviewer", reviewer_ref="reviewer:test",
                decision="accepted_for_candidate_evidence",
                rationale="Synthetic invalid acceptance",
                blocking_findings=("P1",),
            )

    def test_stage8_schemas_are_exported_and_match_contracts(self) -> None:
        names = (
            "evaluation-case-result-v1", "evaluation-suite-result-v1",
            "evaluation-version-set-v1", "evaluation-artifact-policy-v1",
            "evaluation-artifact-v1", "judge-calibration-report-v1",
            "release-comparison-v1", "human-review-request-v1",
            "human-review-decision-v1", "trace-exploration-v1",
            "artifact-retention-review-v1", "stage8-operational-evidence-v1",
            "evidence-bundle-v1",
        )
        self.assertTrue(set(names).issubset(CONTRACTS))
        root = PROJECT_ROOT / "contracts" / "schemas"
        for name in names:
            with self.subTest(name=name):
                committed = json.loads((root / f"{name}.json").read_text(encoding="utf-8"))
                self.assertEqual(committed, CONTRACTS[name].model_json_schema())
