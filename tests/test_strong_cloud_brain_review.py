from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from evals.strong_cloud_brain_review import REQUIRED_ARMS, build_review_evidence


class StrongCloudBrainReviewTests(unittest.TestCase):
    def test_review_packet_is_complete_blinded_and_core_replayed(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            comparison, packet, key = build_review_evidence(
                comparison_path=root / "comparison.json",
                blind_packet_path=root / "packet.json",
                blinding_key_path=root / "key.json",
            )

        self.assertEqual(comparison["arm_count"], 5)
        self.assertEqual(comparison["case_count_per_arm"], 32)
        self.assertTrue(comparison["same_provider_facing_prompt_per_case"])
        self.assertEqual(packet["case_count"], 32)
        self.assertEqual(len(packet["arm_labels"]), 5)
        self.assertEqual(set(key["mapping"]), set(REQUIRED_ARMS))
        rendered_packet = json.dumps(packet, ensure_ascii=False)
        for arm_name in REQUIRED_ARMS:
            self.assertNotIn(arm_name, rendered_packet)
        self.assertTrue(
            all(len(case["outputs"]) == 5 for case in packet["cases"])
        )
        self.assertTrue(
            all(
                arm["core_replacement_count"] >= 0
                and len(arm["results"]) == 32
                for arm in comparison["arms"]
            )
        )


if __name__ == "__main__":
    unittest.main()
