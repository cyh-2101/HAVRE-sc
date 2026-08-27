from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mlsys.training.stage9a_real_v6 import train_candidate


class Stage9ARealV6Tests(unittest.TestCase):
    def test_formal_training_requires_smoke_readiness_before_resource_or_model(self) -> None:
        with (
            patch("mlsys.training.stage9a_real_v6.load_training_plan", return_value={}),
            patch(
                "mlsys.training.stage9a_v6_readiness.require_smoke_readiness",
                side_effect=RuntimeError("missing smoke reload"),
            ) as readiness,
            patch("mlsys.training.stage9a_real_v6.resource_snapshot") as resources,
        ):
            with self.assertRaisesRegex(RuntimeError, "missing smoke reload"):
                train_candidate(formal=True)
        readiness.assert_called_once_with()
        resources.assert_not_called()

    def test_smoke_path_does_not_require_its_own_reload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch("mlsys.training.stage9a_real_v6.RUNS_ROOT", Path(directory)),
                patch("mlsys.training.stage9a_real_v6.assert_local_only_path"),
                patch("mlsys.training.stage9a_real_v6.load_training_plan", return_value={}),
                patch(
                    "mlsys.training.stage9a_real_v6.resource_snapshot",
                    side_effect=RuntimeError("resource stop"),
                ),
                patch("mlsys.training.stage9a_v6_readiness.require_smoke_readiness") as readiness,
            ):
                with self.assertRaisesRegex(RuntimeError, "resource stop"):
                    train_candidate(formal=False)
        readiness.assert_not_called()


if __name__ == "__main__":
    unittest.main()
