from __future__ import annotations

import unittest

from mlsys.training.stage9a_evaluation_v6 import (
    _prompt_messages,
    build_blind_packet,
    summarize_results,
)


class Stage9AV6EvaluationTests(unittest.TestCase):
    def test_prompt_injects_only_supplied_memory_before_conversation(self) -> None:
        case = {
            "memory_context": ["用户说咖啡太苦。"],
            "messages": [{"role": "user", "content": "还记得吗？"}],
        }
        prompt = _prompt_messages(case, "SYSTEM")
        self.assertEqual(prompt[-1], case["messages"][-1])
        self.assertIn("Relevant synthetic memory", prompt[0]["content"])
        self.assertIn("- 用户说咖啡太苦。", prompt[0]["content"])

    def test_summary_keeps_dimensions_separate(self) -> None:
        row = {
            "category": "hard_capability",
            "scores": {
                "output_chars": 2,
                "within_max_chars": True,
                "ai_phrase_hits": [],
                "forbidden_phrase_hits": [],
                "must_include_any": None,
                "history_claim_check": None,
                "exact_checker": False,
                "critical_hard_capability": None,
            },
        }
        summary = summarize_results([row])
        self.assertNotIn("composite", summary)
        self.assertEqual(summary["overall"]["dimensions"]["exact_checker"]["pass_rate"], 0.0)
        self.assertIsNone(summary["overall"]["dimensions"]["must_include_any"]["pass_rate"])

    def test_blind_packet_hides_arm_names_from_options(self) -> None:
        cases = [{
            "case_id": "v6-unseen-001",
            "category": "casual_tiny",
            "subcategory": "small_mishap",
            "messages": [{"role": "user", "content": "咖啡洒了"}],
            "memory_context": [],
        }]
        arms = [
            {"arm_name": name, "results": [{"case_id": "v6-unseen-001", "output": name}]}
            for name in ("exact_base", "candidate_9201", "candidate_9202", "candidate_v6_9601")
        ]
        blind = build_blind_packet(arms, cases)
        self.assertEqual(set(blind["packet"]["arm_aliases"]), {"A", "B", "C", "D"})
        self.assertNotIn("alias_to_arm", blind["packet"])
        self.assertEqual(set(blind["key"]["alias_to_arm"].values()), {arm["arm_name"] for arm in arms})


if __name__ == "__main__":
    unittest.main()
