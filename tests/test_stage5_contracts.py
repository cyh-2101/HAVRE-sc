from __future__ import annotations

import json
import unittest
import uuid
from pathlib import Path

from pydantic import ValidationError

from companion.identity import IdentityLoader
from companion.policy import DataPolicy, PrivacyClass
from companion.policy.intervention import (
    AvoidanceAssessment,
    CoercionAssessment,
    DangerAssessment,
    EnergyAssessment,
    GoalAlignment,
    GoalUrgency,
    InterventionBranch,
    InterventionContext,
    InterventionDecision,
    InterventionPolicy,
    SceneSignalType,
)
from evals.scene_evaluation import run_scene_policy_evaluation
from scripts.export_contract_schemas import CONTRACTS
from services.api.app import create_app


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Stage5InterventionPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.identity = IdentityLoader(PROJECT_ROOT / "identity").load()
        cls.policy = InterventionPolicy(
            constitution_version_id=cls.identity.constitution.version_id,
            identity_version_id=cls.identity.identity.version_id,
            values_version_id=cls.identity.values.version_id,
        )

    def _context(self, **overrides: object) -> InterventionContext:
        values: dict[str, object] = {
            "owner_id": uuid.uuid4(),
            "scene_session_id": uuid.uuid4(),
            "scene_revision": 2,
            "phase": "during",
            "situation_summary": "Synthetic situation",
            "planned_objective": "Complete the simulated conversation",
            "minimum_success": "Say the opening sentence",
            "signal_type": SceneSignalType.AVOIDANCE_URGE,
            "danger": DangerAssessment.LOW,
            "avoidance": AvoidanceAssessment.HIGH,
            "energy": EnergyAssessment.ADEQUATE,
            "coercion": CoercionAssessment.ABSENT,
            "goal_alignment": GoalAlignment.ACTIVE_MEANINGFUL,
            "goal_urgency": GoalUrgency.NORMAL,
            "input_event_id": uuid.uuid4(),
            "trace_id": uuid.uuid4().hex,
            "data_policy": DataPolicy.owner_default(
                PrivacyClass.LOCAL_ONLY, memory_eligible=False
            ),
        }
        values.update(overrides)
        return InterventionContext.model_validate(values)

    def test_safety_and_coercion_override_action_pressure(self) -> None:
        for override in (
            {"danger": DangerAssessment.PLAUSIBLE},
            {"coercion": CoercionAssessment.PRESENT},
            {"signal_type": SceneSignalType.NEED_HELP},
        ):
            with self.subTest(override=override):
                decision = self.policy.decide(self._context(**override))
                self.assertEqual(decision.branch, InterventionBranch.SAFETY_FIRST)
                self.assertFalse(decision.outreach_authorized)
                self.assertTrue(decision.simulation_only)

    def test_ambiguity_and_exhaustion_do_not_become_pressure(self) -> None:
        ambiguous = self.policy.decide(
            self._context(danger=DangerAssessment.UNCERTAIN)
        )
        exhausted = self.policy.decide(
            self._context(energy=EnergyAssessment.EXHAUSTED)
        )
        self.assertEqual(ambiguous.branch, InterventionBranch.CLARIFICATION)
        self.assertIsNotNone(ambiguous.clarification_question)
        self.assertEqual(exhausted.branch, InterventionBranch.RECOVERY)

    def test_during_guidance_is_low_bandwidth_and_hash_bound(self) -> None:
        decision = self.policy.decide(self._context())
        self.assertLessEqual(len(decision.guidance), 240)
        self.assertIn("preserve_user_choice", decision.required_constraints)
        payload = decision.model_dump(mode="json")
        payload["guidance"] = "tampered"
        with self.assertRaises(ValidationError):
            InterventionDecision.model_validate(payload)


class Stage5EvaluationContractTests(unittest.TestCase):
    def test_frozen_synthetic_policy_suite_separates_decision_and_wording(self) -> None:
        report = run_scene_policy_evaluation(
            fixture_path=PROJECT_ROOT / "evals" / "fixtures" / "scene_policy_cases_v1.json",
            identity=IdentityLoader(PROJECT_ROOT / "identity").load(),
            project_root=PROJECT_ROOT,
        )
        self.assertEqual(report.metrics["cases"], 10)
        self.assertEqual(report.metrics["decision_incorrect"], 0)
        self.assertEqual(report.metrics["wording_constraints_failed"], 0)
        self.assertEqual(report.metrics["outreach_authorized_count"], 0)
        self.assertFalse(report.binding_evaluation)
        self.assertEqual(report.gate_status, "not_evaluated")
        self.assertTrue(any("real-world benefit" in item for item in report.limitations))

    def test_stage5_schemas_and_routes_are_exported(self) -> None:
        expected_contracts = {
            "intervention-decision-v1",
            "scene-session-v1",
            "scene-record-v1",
            "scene-view-v1",
            "guidance-outcome-observation-v1",
            "scene-policy-evaluation-report-v1",
        }
        self.assertTrue(expected_contracts.issubset(CONTRACTS))
        paths = create_app().openapi()["paths"]
        for path in (
            "/v1/scenes",
            "/v1/scenes/{scene_session_id}",
            "/v1/scenes/{scene_session_id}/transition",
            "/v1/scenes/{scene_session_id}/signals",
            "/v1/scenes/{scene_session_id}/actions",
            "/v1/scenes/{scene_session_id}/outcomes",
            "/v1/scenes/{scene_session_id}/reflection",
        ):
            self.assertIn(path, paths)
        self.assertNotIn("/v1/proactive", paths)

    def test_committed_stage5_schemas_match_contracts(self) -> None:
        root = PROJECT_ROOT / "contracts" / "schemas"
        for name in (
            "intervention-decision-v1",
            "scene-session-v1",
            "scene-record-v1",
            "scene-view-v1",
            "guidance-outcome-observation-v1",
            "scene-policy-evaluation-report-v1",
        ):
            with self.subTest(name=name):
                committed = json.loads((root / f"{name}.json").read_text(encoding="utf-8"))
                self.assertEqual(committed, CONTRACTS[name].model_json_schema())
