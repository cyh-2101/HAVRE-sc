from __future__ import annotations

import unittest

from companion.context.presentation import CONTEXT_PRESENTATION_VERSION
from mlsys.training.stage9a_memory_use_dataset_v1 import (
    TRAINING_CONTEXT_PRESENTATION_VERSION,
    VARIANTS,
    build_examples,
    dataset_bundle_hash,
    prompt_messages,
)


class Stage9AMemoryUseDatasetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = build_examples()

    def test_public_synthetic_boundary_and_exact_counts(self) -> None:
        self.assertEqual({key: len(value) for key, value in self.rows.items()}, {
            "train": 45,
            "validation": 20,
        })
        all_rows = [item for rows in self.rows.values() for item in rows]
        self.assertTrue(all(item["privacy_class"] == "PUBLIC" for item in all_rows))
        self.assertTrue(all(item["contains_user_data"] is False for item in all_rows))
        self.assertTrue(all(item["training_eligible"] is True for item in all_rows))
        self.assertTrue(dataset_bundle_hash(self.rows).startswith("sha256:"))

    def test_each_counterfactual_group_has_same_message_and_all_variants(self) -> None:
        paired = [
            item
            for rows in self.rows.values()
            for item in rows
            if item["pair_role"] == "paired_counterfactual"
        ]
        groups: dict[str, list[dict]] = {}
        for item in paired:
            groups.setdefault(item["scenario_id"], []).append(item)
        self.assertEqual(len(groups), 10)
        for items in groups.values():
            self.assertEqual({item["variant"] for item in items}, set(VARIANTS))
            self.assertEqual(len({item["user_message"] for item in items}), 1)

    def test_rejected_preferences_are_auditable_but_never_targets(self) -> None:
        for rows in self.rows.values():
            for item in rows:
                self.assertTrue(item["rejected"])
                self.assertNotIn(item["chosen"], item["rejected"])
                self.assertEqual(item["optimizer_eligible"], item["split"] == "train")

    def test_prompt_preserves_sealed_v1_memory_presentation(self) -> None:
        relevant = next(item for item in self.rows["train"] if item["variant"] == "relevant")
        messages = prompt_messages(relevant)
        self.assertEqual([item["role"] for item in messages], ["system", "user"])
        self.assertIn("Relevant shared history for this turn", messages[0]["content"])
        self.assertIn("Never announce that you are using memory", messages[0]["content"])
        self.assertEqual(
            TRAINING_CONTEXT_PRESENTATION_VERSION,
            "context-presentation-v1-natural-memory",
        )
        self.assertEqual(
            CONTEXT_PRESENTATION_VERSION,
            "context-presentation-v13-evidence-authority",
        )
        self.assertNotEqual(
            TRAINING_CONTEXT_PRESENTATION_VERSION,
            CONTEXT_PRESENTATION_VERSION,
        )

    def test_no_memory_and_casual_prompts_do_not_add_memory_guidance(self) -> None:
        for variant in ("no_memory", "casual"):
            item = next(
                row
                for rows in self.rows.values()
                for row in rows
                if row["variant"] == variant
            )
            self.assertNotIn("Relevant shared history for this turn", prompt_messages(item)[0]["content"])


if __name__ == "__main__":
    unittest.main()
