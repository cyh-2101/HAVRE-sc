from __future__ import annotations

import re
import unittest

from mlsys.training.stage9a_dataset import build_examples
from mlsys.training.stage9a_evaluation import _summarize_scores, score_case


class Stage9AEvaluationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.examples = [
            item
            for split in build_examples().values()
            for item in split
        ]

    def _example(self, category: str) -> dict:
        return next(item for item in self.examples if item["category"] == category)

    def test_reference_answers_satisfy_explicit_dimension_rubrics(self) -> None:
        for category, dimension in (
            ("identity_non_deception", "identity_consistency"),
            ("medical_safety", "safety"),
            ("sycophancy_resistance", "sycophancy_resistance"),
            ("structured_output", "structured_output"),
            ("memory_current_over_stale", "memory_use"),
        ):
            item = self._example(category)
            score = score_case(item, item["expected_text"], memory_enabled=True)
            self.assertTrue(score[dimension], category)

    def test_memory_dimension_is_not_scored_when_memory_is_disabled(self) -> None:
        item = self._example("memory_current_over_stale")
        score = score_case(item, item["expected_text"], memory_enabled=False)
        self.assertIsNone(score["memory_use"])

    def test_summary_keeps_behavioral_dimensions_separate(self) -> None:
        item = self._example("medical_safety")
        result = {
            "scores": score_case(item, item["expected_text"], memory_enabled=False)
        }
        summary = _summarize_scores([result])
        self.assertIn("behavioral_quality", summary)
        self.assertIn("safety", summary)
        self.assertNotIn("overall_score", summary)

    def test_sycophancy_rubric_accepts_explicit_rejection_of_quoted_wrong_answer(self) -> None:
        item = self._example("sycophancy_resistance")
        numbers = [int(value) for value in re.findall(r"\d+", item["input_text"])]
        left, right, asserted = numbers[-3:]
        output = (
            f"I cannot agree that {left} + {right} = {asserted}. "
            f"The correct sum is {left + right}."
        )
        self.assertTrue(score_case(item, output, memory_enabled=True)["sycophancy_resistance"])

    def test_sycophancy_rubric_rejects_affirmative_wrong_answer(self) -> None:
        item = self._example("sycophancy_resistance")
        numbers = [int(value) for value in re.findall(r"\d+", item["input_text"])]
        left, right, asserted = numbers[-3:]
        output = (
            f"The sum {left} + {right} = {asserted} is correct. "
            f"For reference, the arithmetic result would otherwise be {left + right}."
        )
        self.assertFalse(score_case(item, output, memory_enabled=True)["sycophancy_resistance"])


if __name__ == "__main__":
    unittest.main()
