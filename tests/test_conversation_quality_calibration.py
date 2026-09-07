from __future__ import annotations

import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = PROJECT_ROOT / "evals" / "fixtures" / "conversation_quality_calibration_v1.json"


class ConversationQualityCalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.suite = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        cls.cases = cls.suite["cases"]

    def test_fixture_is_public_evaluation_only_and_not_training_data(self) -> None:
        self.assertEqual(self.suite["schema_version"], 1)
        self.assertEqual(self.suite["privacy_class"], "PUBLIC")
        self.assertFalse(self.suite["contains_user_data"])
        self.assertFalse(self.suite["training_eligible"])
        self.assertFalse(self.suite["validation_for_training"])

    def test_evidence_chain_separates_stack_layers(self) -> None:
        self.assertEqual(
            self.suite["evidence_chain"],
            [
                "input_turns",
                "retrieval_candidates",
                "memory_admission",
                "response_plan",
                "provider_messages",
                "raw_completion",
                "core_decision",
                "delivered_response",
                "review_provenance",
            ],
        )

    def test_cases_cover_modes_multi_request_correction_and_long_context(self) -> None:
        self.assertEqual(len({case["case_id"] for case in self.cases}), len(self.cases))
        self.assertTrue({"Talk", "Guide", "Prepare", "Reflect"}.issubset({case["mode"] for case in self.cases}))
        categories = {case["category"] for case in self.cases}
        self.assertTrue({"multi_request", "correction", "verbosity_fit", "long_context"}.issubset(categories))
        for case in self.cases:
            self.assertGreaterEqual(len(case["turns"]), 1)
            self.assertEqual(case["turns"][-1]["role"], "user")
            self.assertGreaterEqual(len(case["must_address"]), 2)
            self.assertGreaterEqual(len(case["case_hard_failures"]), 3)

    def test_memory_counterfactual_keeps_latest_user_message_identical(self) -> None:
        memory_cases = [case for case in self.cases if case["category"] == "memory_counterfactual"]
        self.assertEqual(
            {case["memory_variant"] for case in memory_cases},
            {"relevant", "irrelevant", "absent", "stale_conflicting", "partial"},
        )
        latest_messages = {case["turns"][-1]["content"] for case in memory_cases}
        self.assertEqual(len(latest_messages), 1)
        self.assertEqual(len(memory_cases), 5)

    def test_multi_request_has_four_explicit_obligations(self) -> None:
        case = next(case for case in self.cases if case["case_id"] == "multi-request-model-decision")
        self.assertEqual(len(case["must_address"]), 4)
        self.assertIn("私人助手的对话体感", case["turns"][-1]["content"])


if __name__ == "__main__":
    unittest.main()
