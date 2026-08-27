"""Build or verify the post-plan unseen v6 evaluation set."""

from __future__ import annotations

import argparse
import json

from mlsys.training.stage9a_unseen_v6 import build_unseen_holdout, load_and_verify_unseen


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build", "verify"))
    args = parser.parse_args()
    if args.command == "build":
        result = build_unseen_holdout()
    else:
        manifest, cases = load_and_verify_unseen()
        result = {"manifest_hash": manifest["content_hash"], "case_count": len(cases)}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
