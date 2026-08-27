"""Freeze and verify the approved local-only Stage 9A v6 dataset."""

from __future__ import annotations

import argparse
import json

from mlsys.training.stage9a_dataset_v6 import (
    DATASET_ROOT,
    dataset_bundle_hash,
    freeze_dataset,
    load_and_verify_dataset,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("freeze", "verify"))
    args = parser.parse_args()
    if args.command == "freeze":
        result = freeze_dataset()
    else:
        splits = load_and_verify_dataset()
        result = {
            "dataset_root": str(DATASET_ROOT),
            "dataset_bundle_hash": dataset_bundle_hash(),
            "counts": {name: len(rows) for name, rows in splits.items()},
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
