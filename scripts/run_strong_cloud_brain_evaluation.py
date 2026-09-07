"""Run the authorized PUBLIC-synthetic Strong Cloud Brain experiment."""

from __future__ import annotations

import argparse
import asyncio
from decimal import Decimal
from pathlib import Path

from evals.strong_cloud_brain_ceiling import run_focused_cloud_evaluation


def main() -> None:
    parser = argparse.ArgumentParser(prog="run-strong-cloud-brain-evaluation")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--progress",
        type=Path,
        default=Path("var/strong-cloud-brain/focused-progress-v1.json"),
    )
    parser.add_argument("--budget-usd", type=Decimal, default=Decimal("1.00"))
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=("disabled", "enabled"),
        default=("disabled", "enabled"),
    )
    args = parser.parse_args()
    report = asyncio.run(
        run_focused_cloud_evaluation(
            output_path=args.output.resolve(),
            progress_path=args.progress.resolve(),
            budget_usd=args.budget_usd,
            modes=tuple(args.modes),
        )
    )
    print(report["content_hash"])


if __name__ == "__main__":
    main()
