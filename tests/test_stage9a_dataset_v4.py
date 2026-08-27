from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from mlsys.training.stage9a_dataset_v4 import (
    DATASET_ROOT,
    EXTERNAL_BUNDLE_HASH,
    OWNER_ALIGNMENT_PATH,
    SPLIT_COUNTS,
    audit_v4_data_boundaries,
    dataset_bundle_hash,
    load_and_verify_dataset,
    load_and_verify_owner_alignment,
)
from mlsys.training.stage9a_real import (
    V4_MEMORY_BLOCK_HEADER,
    _render_example,
    _v4_context_messages,
    write_hashed_json,
)
from mlsys.training.stage9a_rubric_v4 import (
    diagnostic_token_f1,
    score_v4_case,
    summarize_v4_scores,
)
from scripts.build_stage9a_dataset_v4_review import find_started_v4_runs


class _PrefixTokenizer:
    def apply_chat_template(
        self,
        messages,
        *,
        tokenize,
        add_generation_prompt,
        enable_thinking,
    ):
        del tokenize, enable_thinking
        prefix = [10 + index for index, _ in enumerate(messages)]
        if add_generation_prompt:
            return prefix + [99]
        if messages[-1]["role"] != "assistant":
            raise AssertionError("full rendering must end with the supervised assistant")
        return [10 + index for index, _ in enumerate(messages[:-1])] + [99, 201, 202]


class Stage9ADatasetV4Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.splits = load_and_verify_dataset(DATASET_ROOT)

    def test_exact_product_owner_bundle_and_split_boundaries(self) -> None:
        self.assertEqual(dataset_bundle_hash(DATASET_ROOT), EXTERNAL_BUNDLE_HASH)
        self.assertEqual(
            {split: len(items) for split, items in self.splits.items()},
            SPLIT_COUNTS,
        )
        self.assertTrue(all(item["training_eligible"] for item in self.splits["train"]))
        self.assertTrue(all(item["training_eligible"] for item in self.splits["validation"]))
        self.assertTrue(all(not item["training_eligible"] for item in self.splits["holdout"]))

    def test_canonical_byte_tamper_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "v4"
            shutil.copytree(DATASET_ROOT, target)
            path = target / "stage9a_train_v4.json"
            path.write_bytes(path.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "differs from Product Owner bytes"):
                load_and_verify_dataset(target)

    def test_owner_alignment_is_permanently_evaluation_only_and_physically_separate(self) -> None:
        owner = load_and_verify_owner_alignment(OWNER_ALIGNMENT_PATH)
        self.assertEqual(len(owner["cases"]), 70)
        for case in owner["cases"]:
            self.assertFalse(case["training_eligible"])
            self.assertFalse(case["validation_for_training"])
            self.assertFalse(case["hyperparameter_tuning_eligible"])
            self.assertFalse(case["prompt_tuning_eligible"])
            self.assertFalse(case["synthetic_generation_input_eligible"])
            self.assertTrue(case["evaluation_only"])
        audit = audit_v4_data_boundaries()
        self.assertEqual(audit["owner_alignment_exact_overlap"], {
            "input": 0, "target": 0, "conversation": 0,
        })
        self.assertTrue(audit["owner_alignment_path_is_outside_training_dataset"])

    def test_multiturn_history_is_context_and_only_final_target_is_supervised(self) -> None:
        item = next(
            value for value in self.splits["train"]
            if len(value["messages"]) >= 3
        )
        messages = _v4_context_messages(item, purpose="training", memory_enabled=True)
        self.assertEqual(messages[1:], item["messages"])
        self.assertGreater(sum(message["role"] == "assistant" for message in messages), 0)
        rendered = _render_example(_PrefixTokenizer(), item)
        self.assertTrue(all(value == -100 for value in rendered["labels"][:-2]))
        self.assertEqual(rendered["labels"][-2:], [201, 202])
        self.assertEqual(rendered["historical_assistant_message_count"], 1)

    def test_memory_is_selective_and_uses_approved_runtime_style_header(self) -> None:
        memory_item = next(item for item in self.splits["train"] if item["inject_memory_context"])
        plain_item = next(item for item in self.splits["train"] if not item["inject_memory_context"])
        injected = _v4_context_messages(
            memory_item, purpose="training", memory_enabled=True
        )[0]["content"]
        self.assertIn(V4_MEMORY_BLOCK_HEADER, injected)
        self.assertIn(memory_item["memory_context"], injected)
        disabled = _v4_context_messages(
            memory_item, purpose="training", memory_enabled=False
        )[0]["content"]
        self.assertNotIn(V4_MEMORY_BLOCK_HEADER, disabled)
        plain = _v4_context_messages(
            plain_item, purpose="training", memory_enabled=True
        )[0]["content"]
        self.assertNotIn(V4_MEMORY_BLOCK_HEADER, plain)

    def test_proactive_examples_are_authorized_wording_context_not_send_policy(self) -> None:
        item = next(
            value for value in self.splits["train"]
            if value["context_kind"] == "authorized_proactive_rendering"
        )
        messages = _v4_context_messages(item, purpose="training", memory_enabled=True)
        self.assertEqual(item["messages"], [])
        self.assertTrue(messages[-1]["content"].startswith("Authorized proactive ContextPack:"))

    def test_v4_scorer_keeps_reference_similarity_diagnostic_only(self) -> None:
        item = self.splits["holdout"][0]
        self.assertGreater(diagnostic_token_f1("我先陪你待会儿", "我陪你待会儿"), 0)
        score = score_v4_case(item, item["expected_text"], memory_enabled=True)
        self.assertEqual(
            score["diagnostics"]["reference_similarity_role"],
            "diagnostic_only_not_primary_companion_quality",
        )
        self.assertIsNone(score["overall_score"])
        summary = summarize_v4_scores([{"scores": score}])
        self.assertIn("behavioral_rubric", summary)
        self.assertIn("diagnostics", summary)
        self.assertIsNone(summary["overall_score"])

    def test_structured_output_uses_exact_checker(self) -> None:
        item = next(
            value for value in self.splits["holdout"]
            if value["category"] == "structured_output"
        )
        exact = json.dumps(item["exact_checker"]["expected"], ensure_ascii=False)
        self.assertTrue(
            score_v4_case(item, exact, memory_enabled=False)[
                "deterministic_property_checks"
            ]["exact"]
        )
        self.assertFalse(
            score_v4_case(item, '{"task":"wrong"}', memory_enabled=False)[
                "deterministic_property_checks"
            ]["exact"]
        )

    def test_review_gate_detects_failed_formal_seed_without_training_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runs = Path(directory) / "runs"
            failed = runs / "arbitrary-run-name" / "failure.json"
            write_hashed_json(failed, {
                "run_id": "arbitrary-run-name",
                "seed": 9201,
                "formal": True,
                "status": "failed",
            })
            started = find_started_v4_runs(runs)
            self.assertEqual(len(started), 1)
            self.assertEqual(started[0]["record"], "failure.json")
            self.assertEqual(started[0]["seed"], 9201)


if __name__ == "__main__":
    unittest.main()
