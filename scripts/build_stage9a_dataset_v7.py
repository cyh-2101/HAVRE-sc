"""Build or verify the balanced Stage 9A v7 public/synthetic dataset."""

from __future__ import annotations

import argparse
import json

from mlsys.training.stage9a_dataset_v7 import (
    build_authorization,
    build_dataset,
    dataset_bundle_hash,
    load_and_verify_dataset,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("authorize", "build", "verify"))
    args = parser.parse_args()
    if args.command == "authorize":
        result = build_authorization()
    elif args.command == "build":
        result = build_dataset()
    else:
        rows = load_and_verify_dataset()
        result = {
            "bundle_hash": dataset_bundle_hash(),
            "splits": {name: len(values) for name, values in rows.items()},
        }
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))


if __name__ == "__main__":
    main()
