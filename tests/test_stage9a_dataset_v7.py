from __future__ import annotations

import unittest
from collections import Counter

from mlsys.training import stage9a_dataset_v7 as dataset


class Stage9ADatasetV7Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.v4 = dataset._v4_rows()
        reserved_inputs = {
            dataset._normalize(row["input_text"])
            for rows in cls.v4.values()
            for row in rows
        }
        reserved_targets = {
            dataset._normalize(row["expected_text"])
            for rows in cls.v4.values()
            for row in rows
        }
        cls.v6 = dataset._v6_style_rows(reserved_inputs, reserved_targets)
        cls.new = dataset._preservation_rows(reserved_inputs, reserved_targets)

    def test_balanced_source_membership_is_exact(self) -> None:
        self.assertEqual({name: len(rows) for name, rows in self.v4.items()}, {"train": 300, "validation": 60})
        self.assertEqual({name: len(rows) for name, rows in self.v6.items()}, {"train": 140, "validation": 28})
        self.assertEqual({name: len(rows) for name, rows in self.new.items()}, {"train": 128, "validation": 32})

    def test_generic_dataset_excludes_owner_and_private_material(self) -> None:
        rows = [
            row
            for source in (self.v4, self.v6, self.new)
            for split_rows in source.values()
            for row in split_rows
        ]
        self.assertTrue(all(row["privacy_class"] == "PUBLIC" for row in rows))
        self.assertTrue(all(row["contains_user_data"] is False for row in rows))
        self.assertTrue(all(row["training_eligible"] is True for row in rows))
        self.assertNotIn("owner_authored_anchor", {row["source_kind"] for row in rows})
        self.assertFalse(any("owner-anchor" in row["source_ref"] for row in rows))

    def test_v6_style_slice_preserves_explicit_quota_and_history_gate(self) -> None:
        train_counts = Counter(row["family"].removeprefix("natural_") for row in self.v6["train"])
        self.assertEqual(train_counts, Counter(dataset.STYLE_TRAIN_COUNTS))
        validation_counts = Counter(row["family"].removeprefix("natural_") for row in self.v6["validation"])
        self.assertEqual(validation_counts, Counter(dataset.STYLE_VALIDATION_COUNTS))
        self.assertTrue(all(dataset._history_evidence_safe(row) for rows in self.v6.values() for row in rows))
        unsupported = {
            "messages": [{"role": "user", "content": "这游戏挺好玩"}],
            "memory_context": "",
            "expected_text": "昨天你不是还说它无聊吗。",
        }
        self.assertFalse(dataset._history_evidence_safe(unsupported))

    def test_failure_taxonomy_is_eight_by_twenty_with_frozen_split(self) -> None:
        combined = [row for rows in self.new.values() for row in rows]
        self.assertEqual(Counter(row["family"] for row in combined), Counter({group: 20 for group in dataset.PRESERVATION_GROUPS}))
        self.assertEqual(Counter(row["family"] for row in self.new["train"]), Counter({group: 16 for group in dataset.PRESERVATION_GROUPS}))
        self.assertEqual(Counter(row["family"] for row in self.new["validation"]), Counter({group: 4 for group in dataset.PRESERVATION_GROUPS}))
        self.assertTrue(any(row["exact_checker"] is not None for row in combined if row["family"] == "exact_output"))
        self.assertTrue(any(row["memory_context"] for row in combined if row["family"] == "current_over_stale"))

    def test_assembled_rows_have_no_exact_cross_split_leakage(self) -> None:
        splits = {
            split: [*self.v4[split], *self.v6[split], *self.new[split]]
            for split in ("train", "validation")
        }
        train_inputs = {dataset._normalize(row["input_text"]) for row in splits["train"]}
        val_inputs = {dataset._normalize(row["input_text"]) for row in splits["validation"]}
        train_targets = {dataset._normalize(row["expected_text"]) for row in splits["train"]}
        val_targets = {dataset._normalize(row["expected_text"]) for row in splits["validation"]}
        self.assertFalse(train_inputs & val_inputs)
        self.assertFalse(train_targets & val_targets)


if __name__ == "__main__":
    unittest.main()
