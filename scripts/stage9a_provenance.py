"""Stage 9A model download/verification and environment evidence CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mlsys.training.stage9a_provenance import (
    MODEL_MANIFEST,
    STAGE9A_ROOT,
    collect_environment_manifest,
    download_model_artifact,
    verify_model_artifact,
)


MODEL_ROOT = STAGE9A_ROOT / "models" / "qwen3-8b-b968826d"
PROVENANCE_REPORT = STAGE9A_ROOT / "evidence" / "qwen3-8b-provenance.json"
ENVIRONMENT_REPORT = STAGE9A_ROOT / "evidence" / "environment.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("download", "verify", "environment"))
    parser.add_argument("--manifest", type=Path, default=MODEL_MANIFEST)
    args = parser.parse_args()
    if args.command == "download":
        report = download_model_artifact(MODEL_ROOT, PROVENANCE_REPORT, args.manifest)
    elif args.command == "verify":
        report = verify_model_artifact(MODEL_ROOT, args.manifest)
    else:
        report = collect_environment_manifest()
        ENVIRONMENT_REPORT.parent.mkdir(parents=True, exist_ok=True)
        ENVIRONMENT_REPORT.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
