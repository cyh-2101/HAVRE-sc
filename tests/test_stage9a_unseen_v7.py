from __future__ import annotations

import unittest
from collections import Counter

from mlsys.training.stage9a_dataset_v7 import _normalize, load_and_verify_dataset
from mlsys.training.stage9a_unseen_v7 import (
    COMPANION_DIMENSIONS,
    HARD_DIMENSIONS,
    load_and_verify_unseen,
    score_output,
)


class Stage9AUnseenV7Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest, cls.cases = load_and_verify_unseen()

    def test_membership_is_balanced_and_post_plan(self) -> None:
        self.assertEqual(len(self.cases), 80)
        self.assertEqual(Counter(case["axis"] for case in self.cases), {"companion_quality": 40, "hard_capability": 40})
        self.assertEqual(
            Counter(case["dimension"] for case in self.cases),
            Counter({name: 5 for name in (*COMPANION_DIMENSIONS, *HARD_DIMENSIONS)}),
        )
        self.assertTrue(all(case["critical_hard_capability"] == (case["axis"] == "hard_capability") for case in self.cases))
        self.assertTrue(all(case["training_eligible"] is False for case in self.cases))

    def test_unseen_has_no_exact_canonical_input_or_target_overlap(self) -> None:
        source = load_and_verify_dataset()
        rows = [row for split_rows in source.values() for row in split_rows]
        source_inputs = {_normalize(row["input_text"]) for row in rows}
        source_targets = {_normalize(row["expected_text"]) for row in rows}
        self.assertFalse(source_inputs & {_normalize(case["messages"][-1]["content"]) for case in self.cases})
        self.assertFalse(source_targets & {_normalize(case["expected_text"]) for case in self.cases})

    def test_exact_and_critical_scoring_fail_closed(self) -> None:
        exact = next(case for case in self.cases if case["case_id"] == "v7-unseen-066")
        self.assertTrue(score_output(exact, "126")["critical_hard_capability_pass"])
        self.assertFalse(score_output(exact, "126。")['critical_hard_capability_pass'])
        safety = next(case for case in self.cases if case["case_id"] == "v7-unseen-052")
        self.assertTrue(score_output(safety, safety["expected_text"])["critical_hard_capability_pass"])
        self.assertFalse(score_output(safety, "先观察一下。")['critical_hard_capability_pass'])

    def test_expected_targets_satisfy_deterministic_checks(self) -> None:
        failures = [
            case["case_id"]
            for case in self.cases
            if not score_output(case, case["expected_text"])["deterministic_pass"]
        ]
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
