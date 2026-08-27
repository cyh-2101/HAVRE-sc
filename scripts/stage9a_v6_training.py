"""Run the bounded Stage 9A v6 render/plan/smoke/formal pipeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mlsys.training.stage9a_real_v6 import (
    build_rendered_artifacts,
    close_training_plan,
    train_candidate,
    verify_adapter,
    verify_training_input_boundary,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("render", "verify-render", "close-plan", "smoke", "reload-smoke", "train", "reload-formal", "verify-adapter"))
    parser.add_argument("--adapter-dir", type=Path)
    args = parser.parse_args()
    if args.command == "render":
        result = build_rendered_artifacts()
    elif args.command == "verify-render":
        result = verify_training_input_boundary()
    elif args.command == "close-plan":
        result = close_training_plan()
    elif args.command == "smoke":
        result = train_candidate(formal=False)
    elif args.command == "reload-smoke":
        from mlsys.training.stage9a_v6_readiness import reload_smoke_adapter

        result = reload_smoke_adapter()
    elif args.command == "train":
        result = train_candidate(formal=True)
    elif args.command == "reload-formal":
        from mlsys.training.stage9a_v6_readiness import reload_formal_adapter

        result = reload_formal_adapter()
    else:
        if args.adapter_dir is None:
            parser.error("--adapter-dir is required")
        result = verify_adapter(args.adapter_dir)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
