"""Build immutable Stage 9A compatibility, variance, and candidate registry evidence."""

from __future__ import annotations

import argparse
import json

from mlsys.training.stage9a_registry import (
    build_candidate_registry,
    build_training_input_boundary_evidence,
    build_variance_evidence,
    decide_optional_third_seed,
    run_compatibility_probes,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=(
            "compatibility", "third-seed-decision", "variance", "boundary", "registry"
        )
    )
    args = parser.parse_args()
    if args.command == "compatibility":
        result = run_compatibility_probes()
    elif args.command == "third-seed-decision":
        result = decide_optional_third_seed()
    elif args.command == "variance":
        result = build_variance_evidence()
    elif args.command == "boundary":
        result = build_training_input_boundary_evidence()
    else:
        result = build_candidate_registry()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
