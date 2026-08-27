from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mlsys.training.stage9a_review_v7 import (
    EXPECTED_PLAN_HASH,
    EXPECTED_REPORT_HASH,
    EXPECTED_UNSEEN_HASH,
    build_review,
)


def _report() -> dict:
    return {
        "content_hash": EXPECTED_REPORT_HASH,
        "unseen_manifest_hash": EXPECTED_UNSEEN_HASH,
        "training_plan_hash": EXPECTED_PLAN_HASH,
        "arms": [{"arm_name": "candidate_v7_9701", "results": [{} for _ in range(80)]}],
    }


class Stage9AReviewV7Tests(unittest.TestCase):
    @patch("mlsys.training.stage9a_review_v7.datetime")
    def test_review_blocks_ui_and_keeps_axes_separate(self, clock) -> None:
        clock.now.return_value.isoformat.return_value = "2026-08-25T00:00:00+00:00"
        review = build_review(_report())
        self.assertEqual(review["status"], "rejected_tradeoff_not_pareto_improvement")
        self.assertEqual(review["companion_quality"]["decision"], "not_clearly_more_natural_than_9201")
        self.assertEqual(review["hard_capability"]["decision"], "blocked_by_absolute_critical_failures")
        self.assertFalse(review["disposition"]["daily_use_development_eligible"])
        self.assertFalse(review["training_eligible"])

    def test_wrong_report_binding_is_rejected(self) -> None:
        report = copy.deepcopy(_report())
        report["content_hash"] = "sha256:wrong"
        with self.assertRaisesRegex(ValueError, "exact frozen"):
            build_review(report)

    @patch("mlsys.training.stage9a_registry._completed_formal_runs")
    def test_sealed_registry_ignores_later_governed_lineages(self, discover) -> None:
        from mlsys.training.stage9a_registry import completed_formal_runs

        discover.return_value = []
        self.assertEqual(completed_formal_runs(), [])
        discover.assert_called_once_with(ignore_other_lineages=True)

    def test_v4_discovery_does_not_open_later_lineage_reports(self) -> None:
        from mlsys.training.stage9a_real import completed_formal_runs

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "formal-seed-9701-v7-capability-preserving-v1" / "training-report.json"
            report.parent.mkdir()
            report.write_text("not-json", encoding="utf-8")
            with patch("mlsys.training.stage9a_real.RUNS_ROOT", root):
                self.assertEqual(completed_formal_runs(ignore_other_lineages=True), [])


if __name__ == "__main__":
    unittest.main()
