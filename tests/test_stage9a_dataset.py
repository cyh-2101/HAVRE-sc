from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from companion.hashing import content_hash
from mlsys.training.stage9a_dataset import (
    ARTIFACT_VERSION,
    SPLIT_COUNTS,
    build_examples,
    dataset_bundle_hash,
    load_and_verify_dataset,
    validate_split_isolation,
    write_dataset,
)


class Stage9ADatasetTests(unittest.TestCase):
    @staticmethod
    def _rehash(item: dict) -> None:
        material = {key: value for key, value in item.items() if key != "content_hash"}
        item["content_hash"] = content_hash(material)

    def test_exact_counts_and_global_isolation(self) -> None:
        splits = build_examples()
        report = validate_split_isolation(splits)
        self.assertEqual(report["counts"], SPLIT_COUNTS)
        self.assertEqual(report["global_unique_ids"], 384)
        self.assertEqual(report["global_unique_scenario_keys"], 384)
        self.assertEqual(report["global_unique_content_hashes"], 384)
        self.assertEqual(report["global_unique_normalized_targets"], 384)
        self.assertEqual(report["cross_split_exact_target_overlap_count"], 0)
        self.assertEqual(report["holdout_training_eligible_count"], 0)
        self.assertLess(report["maximum_cross_split_fivegram_jaccard"], 0.90)

    def test_artifacts_and_manifests_are_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            first = Path(first_dir)
            second = Path(second_dir)
            write_dataset(first)
            write_dataset(second)
            self.assertEqual(dataset_bundle_hash(first), dataset_bundle_hash(second))
            for split in SPLIT_COUNTS:
                self.assertEqual(
                    (first / f"stage9a_{split}_{ARTIFACT_VERSION}.json").read_bytes(),
                    (second / f"stage9a_{split}_{ARTIFACT_VERSION}.json").read_bytes(),
                )
                self.assertEqual(
                    (first / f"stage9a_{split}_{ARTIFACT_VERSION}.manifest.json").read_bytes(),
                    (second / f"stage9a_{split}_{ARTIFACT_VERSION}.manifest.json").read_bytes(),
                )

    def test_holdout_is_physical_and_training_ineligible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_dataset(root)
            splits = load_and_verify_dataset(root)
            self.assertTrue(all(not item["training_eligible"] for item in splits["holdout"]))
            self.assertTrue(all(item["evaluation_only"] for item in splits["holdout"]))
            self.assertTrue(all(item["access_limited"] for item in splits["holdout"]))
            self.assertTrue(all(item["training_eligible"] for item in splits["train"]))

    def test_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_dataset(root)
            path = root / f"stage9a_train_{ARTIFACT_VERSION}.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["examples"][0]["input_text"] = "tampered"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "byte hash mismatch"):
                load_and_verify_dataset(root)

    def test_training_members_fail_closed_on_unsafe_policy(self) -> None:
        mutations = (
            ("training_eligible", False, "not training eligible"),
            ("contains_user_data", True, "contains user data"),
            ("source_kind", "user_event", "not repository-owned synthetic data"),
            ("privacy_class", "LOCAL_ONLY", "not approved public-safe data"),
            ("split", "holdout", "split binding mismatch"),
        )
        for field, value, message in mutations:
            with self.subTest(field=field):
                splits = build_examples()
                splits["train"][0][field] = value
                self._rehash(splits["train"][0])
                with self.assertRaisesRegex(ValueError, message):
                    validate_split_isolation(splits)


if __name__ == "__main__":
    unittest.main()
