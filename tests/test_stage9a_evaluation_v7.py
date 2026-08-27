from __future__ import annotations

import unittest

from mlsys.training.stage9a_evaluation_v7 import (
    _prompt_messages,
    build_blind_packet,
    build_preliminary_hard_gate,
    summarize_results,
)


def _score(passed: bool, *, hard: bool) -> dict:
    return {
        "output_chars": 8,
        "within_max_chars": True,
        "required_groups": [{"alternatives": ["x"], "passed": passed}],
        "forbidden_phrase_hits": [],
        "ai_phrase_hits": [],
        "unsupported_history_check": None,
        "exact_checker": None,
        "deterministic_pass": passed,
        "critical_hard_capability_pass": passed if hard else None,
    }


class Stage9AEvaluationV7Tests(unittest.TestCase):
    def test_prompt_injects_only_supplied_memory_before_conversation(self) -> None:
        case = {"memory_context": ["用户明确说红色，不是蓝色。"], "messages": [{"role": "user", "content": "什么颜色？"}]}
        prompt = _prompt_messages(case, "SYSTEM")
        self.assertEqual(prompt[-1], case["messages"][-1])
        self.assertIn("Relevant synthetic memory", prompt[0]["content"])
        self.assertIn("红色", prompt[0]["content"])

    def test_summary_keeps_companion_and_hard_axes_separate(self) -> None:
        results = [
            {"axis": "companion_quality", "dimension": "natural_casual_tiny", "scores": _score(True, hard=False)},
            {"axis": "hard_capability", "dimension": "exact_output", "scores": _score(False, hard=True)},
        ]
        summary = summarize_results(results)
        self.assertTrue(summary["no_cross_axis_composite"])
        self.assertEqual(summary["by_axis"]["companion_quality"]["checks"]["deterministic_pass"]["pass_count"], 1)
        self.assertEqual(summary["by_axis"]["hard_capability"]["checks"]["critical_hard_capability_pass"]["pass_count"], 0)

    def test_blind_packet_has_five_aliases_and_no_public_mapping(self) -> None:
        case = {
            "case_id": "v7-unseen-001",
            "axis": "companion_quality",
            "dimension": "natural_casual_tiny",
            "subcategory": "fixture",
            "messages": [{"role": "user", "content": "hi"}],
            "memory_context": [],
        }
        names = ("exact_base", "candidate_9201", "candidate_9202", "rejected_v6_9601", "candidate_v7_9701")
        arms = [{"arm_name": name, "results": [{"case_id": case["case_id"], "output": name}]} for name in names]
        blind = build_blind_packet(arms, [case])
        self.assertEqual(set(blind["packet"]["arm_aliases"]), {"A", "B", "C", "D", "E"})
        self.assertNotIn("alias_to_arm", blind["packet"])
        self.assertEqual(set(blind["key"]["alias_to_arm"].values()), set(names))

    def test_hard_gate_blocks_any_dimension_regression_against_9201(self) -> None:
        def arm(name: str, exact_pass: bool, safety_pass: bool) -> dict:
            return {
                "arm_name": name,
                "results": [
                    {"axis": "hard_capability", "dimension": "exact_output", "scores": _score(exact_pass, hard=True)},
                    {"axis": "hard_capability", "dimension": "urgent_safety", "scores": _score(safety_pass, hard=True)},
                ],
            }
        arms = [arm("candidate_9201", True, True), arm("candidate_v7_9701", False, True)]
        gate = build_preliminary_hard_gate(arms)
        self.assertEqual(gate["status"], "blocked_by_deterministic_regression")
        self.assertEqual(gate["dimension_regressions"][0]["dimension"], "exact_output")


if __name__ == "__main__":
    unittest.main()
