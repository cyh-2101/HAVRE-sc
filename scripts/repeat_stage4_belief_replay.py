"""Repeat the exact PostgreSQL belief replay regression in fresh processes."""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from companion.hashing import content_hash
from evals.inference_runner import current_source_revision


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXACT_TEST = (
    "tests.test_stage4_integration.Stage4PostgresIntegrationTests."
    "test_belief_replay_counter_evidence_revision_and_owner_isolation"
)


def run_repetitions(*, database_url: str, repetitions: int) -> dict[str, object]:
    if repetitions < 100:
        raise ValueError("belief replay stability requires at least 100 repetitions")
    results: list[dict[str, object]] = []
    started_at = datetime.now(UTC)
    for sequence in range(1, repetitions + 1):
        environment = os.environ.copy()
        environment["HAVRE_TEST_DATABASE_URL"] = database_url
        started = time.perf_counter()
        completed = subprocess.run(
            [sys.executable, "-m", "unittest", EXACT_TEST, "-v"],
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            creationflags=(
                subprocess.CREATE_NO_WINDOW
                if platform.system() == "Windows"
                else 0
            ),
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        result: dict[str, object] = {
            "sequence": sequence,
            "passed": completed.returncode == 0,
            "returncode": completed.returncode,
            "duration_ms": elapsed_ms,
        }
        if completed.returncode != 0:
            result["stdout"] = completed.stdout
            result["stderr"] = completed.stderr
        results.append(result)
        if completed.returncode != 0:
            break

    passed = sum(bool(item["passed"]) for item in results)
    report: dict[str, object] = {
        "schema_version": 1,
        "suite": "stage4-belief-replay-independent-process-v1",
        "exact_test": EXACT_TEST,
        "source_snapshot": current_source_revision(PROJECT_ROOT),
        "requested_repetitions": repetitions,
        "completed_repetitions": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "independent_processes": len(results),
        "database_name": database_url.rsplit("/", 1)[-1],
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "finished_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "results": results,
    }
    report["content_hash"] = content_hash(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=100)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    database_url = os.getenv("HAVRE_TEST_DATABASE_URL")
    if not database_url:
        raise RuntimeError("HAVRE_TEST_DATABASE_URL is required")
    report = run_repetitions(
        database_url=database_url, repetitions=arguments.repetitions
    )
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if arguments.output is not None:
        output = arguments.output.resolve()
        if PROJECT_ROOT not in output.parents:
            raise RuntimeError("output must stay inside the HAVRE repository")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
