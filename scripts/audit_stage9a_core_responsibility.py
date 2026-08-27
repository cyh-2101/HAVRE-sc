"""Build or verify the immutable Stage 9A model-vs-Core audit."""

from __future__ import annotations

import argparse

from mlsys.training.stage9a_core_responsibility import (
    run_core_responsibility_audit,
    verify_core_responsibility_audit,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    report = (
        verify_core_responsibility_audit()
        if args.verify
        else run_core_responsibility_audit()
    )
    print(report["content_hash"])


if __name__ == "__main__":
    main()
