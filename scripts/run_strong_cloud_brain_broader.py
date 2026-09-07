"""Run the conditionally triggered PUBLIC-synthetic 80-case cloud regression."""

import argparse
import asyncio
from decimal import Decimal
from pathlib import Path

from evals.strong_cloud_brain_broader import run_broader_cloud_evaluation


def main() -> None:
    parser = argparse.ArgumentParser(prog="run-strong-cloud-brain-broader")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--progress", type=Path, required=True)
    parser.add_argument("--budget-usd", type=Decimal, default=Decimal("1.00"))
    args = parser.parse_args()
    report = asyncio.run(
        run_broader_cloud_evaluation(
            output_path=args.output.resolve(),
            progress_path=args.progress.resolve(),
            budget_usd=args.budget_usd,
        )
    )
    print(report["content_hash"])


if __name__ == "__main__":
    main()
