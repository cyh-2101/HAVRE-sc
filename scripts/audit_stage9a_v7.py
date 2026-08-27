"""Freeze the Stage 9A v7 pretraining data/render audit."""

from __future__ import annotations

import json

from mlsys.training.stage9a_v7_audit import build_pretraining_audit


def main() -> None:
    print(json.dumps(build_pretraining_audit(), ensure_ascii=True, sort_keys=True))


if __name__ == "__main__":
    main()
