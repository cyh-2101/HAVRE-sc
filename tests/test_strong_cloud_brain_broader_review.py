from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from evals.strong_cloud_brain_broader_review import ARMS, build_broader_review_evidence
from mlsys.training.stage9a_provenance import PROJECT_ROOT


class StrongCloudBrainBroaderReviewTests(unittest.TestCase):
    def test_packet_is_complete_and_contains_no_arm_identity(self) -> None:
        cloud = (
            PROJECT_ROOT
            / "evals/reports/strong_cloud_brain_20260826/deepseek-v4-pro-thinking-broader-v3-final.json"
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            packet, key = build_broader_review_evidence(
                cloud_report_path=cloud,
                packet_path=root / "packet.json",
                key_path=root / "key.json",
            )
        self.assertEqual(packet["case_count"], 40)
        self.assertEqual(packet["output_count"], 120)
        self.assertEqual(set(key["mapping"]), set(ARMS))
        rendered = json.dumps(packet, ensure_ascii=False)
        for arm in ARMS:
            self.assertNotIn(arm, rendered)
        self.assertTrue(all(len(case["outputs"]) == 3 for case in packet["cases"]))


if __name__ == "__main__":
    unittest.main()
