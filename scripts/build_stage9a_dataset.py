"""Build the immutable Stage 9A repository-owned synthetic dataset artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mlsys.training.stage9a_dataset import (
    dataset_bundle_hash,
    load_and_verify_dataset,
    validate_split_isolation,
    write_dataset,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = PROJECT_ROOT / "mlsys" / "training" / "fixtures" / "stage9a_v2"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    paths = write_dataset(args.output_root)
    splits = load_and_verify_dataset(args.output_root)
    print(json.dumps({
        "root": str(args.output_root),
        "train": str(paths.train),
        "validation_artifact": str(paths.validation),
        "holdout": str(paths.holdout),
        "bundle_hash": dataset_bundle_hash(args.output_root),
        "isolation": validate_split_isolation(splits),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
