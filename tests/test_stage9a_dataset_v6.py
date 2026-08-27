from __future__ import annotations

import unittest

from mlsys.training.stage9a_dataset_v6 import (
    ExternalV6Example,
    _deduplicate_training,
    _deduplicate_validation,
)


def _row(
    example_id: str,
    *,
    target: str,
    split: str = "train",
    source: str = "gpt-5.6-sol-style-first-v6",
    privacy: str = "SYNTHETIC",
) -> ExternalV6Example:
    return ExternalV6Example.model_validate({
        "schema_version": 1,
        "id": example_id,
        "split": split,
        "family": "casual",
        "mode": "TALK",
        "relationship_stage": "FAMILIAR",
        "memory_context": [],
        "turns": [{"role": "user", "content": "今天咋样"}],
        "target": target,
        "training_eligible": split == "train",
        "validation_eligible": split == "validation",
        "privacy": privacy,
        "source": source,
        "notes": "fixture",
        "forbidden_tags": [],
    })


class Stage9AV6DatasetTests(unittest.TestCase):
    def test_relationship_stage_only_long_variant_is_excluded_without_rewrite(self) -> None:
        rows = [
            _row("v6-relpair-001-new", target="先说发生啥了。"),
            _row("v6-relpair-001-long", target="你又怎么了。"),
        ]
        retained, excluded = _deduplicate_training(rows)
        self.assertEqual([row.id for _, row in retained], ["v6-relpair-001-new"])
        self.assertEqual(excluded[0]["reason"], "unsupported_relationship_stage_only_history")
        self.assertFalse(excluded[0]["target_rewritten"])

    def test_duplicate_target_prefers_owner_anchor(self) -> None:
        rows = [
            _row("v6-gen-001", target="行。"),
            _row(
                "v6-anchor-001",
                target="行。",
                source="owner-anchor-v1",
                privacy="NORMAL",
            ),
        ]
        retained, excluded = _deduplicate_training(rows)
        self.assertEqual([row.id for _, row in retained], ["v6-anchor-001"])
        self.assertEqual(excluded[0]["retained_example_id"], "v6-anchor-001")

    def test_validation_target_dedup_is_stable(self) -> None:
        rows = [
            _row("v6-val-001", target="嗯。", split="validation"),
            _row("v6-val-002", target="  嗯。  ", split="validation"),
        ]
        retained, excluded = _deduplicate_validation(rows)
        self.assertEqual([row.id for _, row in retained], ["v6-val-001"])
        self.assertEqual(excluded[0]["retained_example_id"], "v6-val-001")


if __name__ == "__main__":
    unittest.main()
