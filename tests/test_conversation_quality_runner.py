from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from companion.context import ResponsePlanner
from evals.conversation_quality import (
    build_candidate_messages,
    build_synthetic_retrieval_result,
    load_calibration_suite,
    seal_report,
    surface_diagnostics,
)
from scripts.run_conversation_candidate_calibration import _load_runtime_evidence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = PROJECT_ROOT / "evals" / "fixtures" / "conversation_quality_calibration_v1.json"


class ConversationQualityRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.suite = load_calibration_suite(FIXTURE_PATH)

    def test_loader_rejects_private_or_training_eligible_fixture(self) -> None:
        for field, value in (("privacy_class", "LOCAL_ONLY"), ("contains_user_data", True), ("training_eligible", True)):
            changed = copy.deepcopy(self.suite)
            changed[field] = value
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "suite.json"
                path.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
                with self.subTest(field=field), self.assertRaises(ValueError):
                    load_calibration_suite(path)

    def test_messages_preserve_turn_order_and_plan_without_fake_memory(self) -> None:
        case = next(case for case in self.suite["cases"] if case["case_id"] == "current-correction-wins")
        plan = ResponsePlanner().plan(
            request_id=uuid4(),
            trace_id=uuid4().hex,
            owner_id=uuid4(),
            message=case["turns"][-1]["content"],
            source_refs=("synthetic/test",),
        )
        messages = build_candidate_messages(identity_text="IDENTITY", response_plan=plan, case=case)
        self.assertEqual([message["role"] for message in messages[-3:]], ["user", "assistant", "user"])
        self.assertIn("Address every distinct request", messages[1]["content"])
        self.assertIn("No long-term Memory", messages[2]["content"])

    def test_memory_context_is_labeled_optional_and_current_first(self) -> None:
        case = next(case for case in self.suite["cases"] if case["case_id"] == "memory-project-stale")
        request_id = uuid4()
        trace_id = uuid4().hex
        owner_id = uuid4()
        retrieval = build_synthetic_retrieval_result(
            suite_id=self.suite["suite_id"],
            case=case,
            request_id=request_id,
            trace_id=trace_id,
            owner_id=owner_id,
        )
        plan = ResponsePlanner().plan(
            request_id=request_id,
            trace_id=trace_id,
            owner_id=owner_id,
            message=case["turns"][-1]["content"],
            source_refs=("synthetic/test",),
        )
        messages = build_candidate_messages(identity_text="IDENTITY", response_plan=plan, case=case)
        self.assertIsNotNone(retrieval)
        self.assertEqual(plan.memory_need, "possible")
        self.assertIn("Retrieved history is optional", messages[1]["content"])
        self.assertIn("prefer the current user message", messages[2]["content"])
        self.assertIn(case["memory_context"][0], messages[2]["content"])

    def test_frozen_case_modes_match_planner_output(self) -> None:
        owner_id = uuid4()
        planner = ResponsePlanner()
        for case in self.suite["cases"]:
            request_id = uuid4()
            trace_id = uuid4().hex
            retrieval = build_synthetic_retrieval_result(
                suite_id=self.suite["suite_id"],
                case=case,
                request_id=request_id,
                trace_id=trace_id,
                owner_id=owner_id,
            )
            plan = planner.plan(
                request_id=request_id,
                trace_id=trace_id,
                owner_id=owner_id,
                message=case["turns"][-1]["content"],
                source_refs=("synthetic/test",),
        )
            with self.subTest(case_id=case["case_id"]):
                self.assertEqual(plan.mode, case["mode"].lower())

    def test_surface_checks_are_explicitly_nonsemantic(self) -> None:
        flags = surface_diagnostics("根据记忆，你上次也这样。", finish_reason="length")
        self.assertTrue(flags["nonempty"])
        self.assertTrue(flags["mentions_memory_mechanism"])
        self.assertTrue(flags["possibly_length_truncated"])
        self.assertTrue(flags["semantic_review_required"])

    def test_report_hash_binds_all_material(self) -> None:
        report = seal_report({"schema_version": 1, "results": []})
        self.assertRegex(report["content_hash"], r"^sha256:[0-9a-f]{64}$")
        with self.assertRaises(ValueError):
            seal_report(report)

    def test_runtime_evidence_is_path_fenced_and_candidate_only(self) -> None:
        runtime_root = PROJECT_ROOT / ".runtime"
        runtime_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=runtime_root) as directory:
            state_path = Path(directory) / "state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "server_pid": 4242,
                        "alias": "candidate-alias",
                        "base_url": "http://127.0.0.1:8082",
                        "candidate_only": True,
                        "promotion_authorized": False,
                        "deployment_authorized": False,
                    }
                ),
                encoding="utf-8",
            )
            with patch("scripts.run_conversation_candidate_calibration.psutil.pid_exists", return_value=True):
                evidence = _load_runtime_evidence(
                    path=state_path,
                    base_url="http://127.0.0.1:8082",
                    model_alias="candidate-alias",
                )
            self.assertEqual(evidence["server_pid"], 4242)
            self.assertRegex(evidence["state_hash"], r"^sha256:[0-9a-f]{64}$")
            changed = json.loads(state_path.read_text(encoding="utf-8"))
            changed["promotion_authorized"] = True
            state_path.write_text(json.dumps(changed), encoding="utf-8")
            with patch("scripts.run_conversation_candidate_calibration.psutil.pid_exists", return_value=True):
                with self.assertRaises(ValueError):
                    _load_runtime_evidence(
                        path=state_path,
                        base_url="http://127.0.0.1:8082",
                        model_alias="candidate-alias",
                    )


if __name__ == "__main__":
    unittest.main()
