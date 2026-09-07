from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from evals.strong_cloud_brain_decision import (
    BROADER_KEY,
    BROADER_PACKET,
    BROADER_REVIEW,
    FOCUSED_KEY,
    FOCUSED_PACKET,
    FOCUSED_REVIEW,
    _verify_broader_review,
    _verify_focused_review,
    build_decision_evidence,
)
from mlsys.training.stage9a_real import read_hashed_json


class StrongCloudBrainDecisionTests(unittest.TestCase):
    def test_decision_is_bound_to_blind_reviews_and_preserves_stop_boundary(self) -> None:
        with TemporaryDirectory() as directory:
            result = build_decision_evidence(output_path=Path(directory) / "decision.json")

        self.assertEqual(result["decision"], "C_both_model_capability_and_system_containment_matter")
        self.assertEqual(result["focused_attribution"]["cloud_thinking_delta_vs_best_local"], 6)
        self.assertFalse(result["broader_absolute_regression"]["strictly_attributable_to_model"])
        self.assertEqual(result["broader_absolute_regression"]["exact_prompt_matches"], 0)
        self.assertFalse(result["conclusion"]["training_performed"])
        self.assertEqual(result["conclusion"]["daily_use_candidate"], "candidate_9201")
        self.assertFalse(result["conclusion"]["candidate_status_changed"])
        self.assertFalse(result["conclusion"]["routing_or_serving_activated"])

    def test_review_case_metadata_must_match_blind_packets(self) -> None:
        focused_packet = read_hashed_json(FOCUSED_PACKET)
        focused_key = read_hashed_json(FOCUSED_KEY)
        focused_review = json.loads(FOCUSED_REVIEW.read_text(encoding="utf-8"))
        changed_focused = copy.deepcopy(focused_review)
        changed_focused["case_reviews"][0]["case_id"] = "substituted-case"
        with self.assertRaisesRegex(ValueError, "metadata"):
            _verify_focused_review(
                focused_packet,
                changed_focused,
                set(focused_key["mapping"].values()),
            )

        broader_packet = read_hashed_json(BROADER_PACKET)
        broader_key = read_hashed_json(BROADER_KEY)
        broader_review = json.loads(BROADER_REVIEW.read_text(encoding="utf-8"))
        changed_broader = copy.deepcopy(broader_review)
        changed_broader["case_reviews"][0]["prompt_exact"] = True
        with self.assertRaisesRegex(ValueError, "metadata"):
            _verify_broader_review(
                broader_packet,
                changed_broader,
                set(broader_key["mapping"].values()),
            )


if __name__ == "__main__":
    unittest.main()
