from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mlsys.training.stage9a_real_v7 import (
    EPOCHS,
    EXPECTED_COUNTS,
    LEARNING_RATE,
    MAX_SEQUENCE_LENGTH,
    train_candidate,
)


class Stage9ARealV7Tests(unittest.TestCase):
    def test_mild_candidate_strength_is_frozen(self) -> None:
        self.assertEqual(EPOCHS, 1)
        self.assertEqual(LEARNING_RATE, 1e-4)
        self.assertEqual(EXPECTED_COUNTS["train"], 568)
        self.assertEqual(MAX_SEQUENCE_LENGTH, 321)

    def test_formal_training_requires_smoke_readiness_first(self) -> None:
        with (
            patch("mlsys.training.stage9a_real_v7.load_training_plan", return_value={}),
            patch(
                "mlsys.training.stage9a_v7_readiness.require_smoke_readiness",
                side_effect=RuntimeError("missing v7 smoke reload"),
            ) as readiness,
            patch("mlsys.training.stage9a_real_v7.resource_snapshot") as resources,
        ):
            with self.assertRaisesRegex(RuntimeError, "missing v7 smoke reload"):
                train_candidate(formal=True)
        readiness.assert_called_once_with()
        resources.assert_not_called()

    def test_smoke_path_does_not_require_its_own_reload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch("mlsys.training.stage9a_real_v7.RUNS_ROOT", Path(directory)),
                patch("mlsys.training.stage9a_real_v7.assert_local_only_path"),
                patch("mlsys.training.stage9a_real_v7.load_training_plan", return_value={}),
                patch("mlsys.training.stage9a_real_v7.load_smoke_remediation", return_value={}),
                patch("mlsys.training.stage9a_real_v7.resource_snapshot", side_effect=RuntimeError("resource stop")),
                patch("mlsys.training.stage9a_v7_readiness.require_smoke_readiness") as readiness,
            ):
                with self.assertRaisesRegex(RuntimeError, "resource stop"):
                    train_candidate(formal=False)
        readiness.assert_not_called()


if __name__ == "__main__":
    unittest.main()
