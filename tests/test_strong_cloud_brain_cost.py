from __future__ import annotations

import copy
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from evals.strong_cloud_brain_cost import build_cost_evidence, verify_cost_evidence


class StrongCloudBrainCostTests(unittest.TestCase):
    def test_formal_cost_is_independently_recomputed_from_every_request(self) -> None:
        with TemporaryDirectory() as directory:
            result = build_cost_evidence(output_path=Path(directory) / "cost.json")
        self.assertEqual(result["formal_total_cost_usd"], "0.240205504000")
        self.assertEqual(sum(run["request_count"] for run in result["runs"]), 146)
        self.assertFalse(result["contains_prompts_or_outputs"])

        changed = copy.deepcopy(result)
        changed["runs"][2]["requests"][0]["usage"]["prompt_cache_hit_tokens"] += 1
        with self.assertRaisesRegex(ValueError, "cache usage"):
            verify_cost_evidence(changed)


if __name__ == "__main__":
    unittest.main()
