"""Content-free and synthetic benchmark for the Stage 12A Windows adapter.

This benchmark deliberately does not call ``WindowsForegroundProbe.sample``.
The native probe evidence binds the required Windows APIs only; all activity
summaries are produced from synthetic, explicitly labelled samples.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import json
import platform
from pathlib import Path
import statistics
import time

from apps.windows_agent.coarse_context import (
    CoarseWindowAggregator,
    LocalActivitySample,
    ProbeUnavailable,
    WindowsCoarseContextAdapter,
)
from apps.windows_agent.offline_queue import WindowsDPAPIProtector
from evals.inference_runner import current_source_revision


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _samples(
    categories: tuple[str, ...], *, idle: tuple[bool, ...] | None = None
) -> tuple[LocalActivitySample, ...]:
    start = datetime(2026, 8, 22, 0, 0, tzinfo=UTC)
    idle_values = idle or tuple(False for _ in categories)
    return tuple(
        LocalActivitySample(
            observed_at=start + timedelta(seconds=10 * index),
            category=category,
            idle=is_idle,
        )
        for index, (category, is_idle) in enumerate(
            zip(categories, idle_values, strict=True)
        )
    )


def run(*, iterations: int) -> dict[str, object]:
    if iterations < 100:
        raise ValueError("benchmark requires at least 100 synthetic iterations")
    aggregator = CoarseWindowAggregator(
        sample_interval_seconds=10, window_seconds=60
    )
    fixtures = (
        (
            "development_active",
            _samples(("development",) * 6),
            ("development", "active", 60, 0),
        ),
        (
            "idle_hides_category",
            _samples(("browser",) * 6, idle=(True,) * 6),
            ("unknown", "idle", 0, 60),
        ),
        (
            "deterministic_category_tie",
            _samples(
                ("development", "browser", "development", "browser", "system", "system")
            ),
            ("browser", "active", 60, 0),
        ),
    )
    fixture_results: list[dict[str, object]] = []
    fixture_passes = 0
    for name, samples, expected in fixtures:
        summary = aggregator.summarize(samples)
        observed = (
            summary.dominant_category,
            summary.activity_state,
            summary.active_seconds,
            summary.idle_seconds,
        )
        passed = observed == expected
        fixture_passes += int(passed)
        fixture_results.append(
            {
                "fixture": name,
                "expected": list(expected),
                "observed": list(observed),
                "passed": passed,
            }
        )

    unavailable_rejected = False
    try:
        aggregator.summarize(
            tuple(
                LocalActivitySample(
                    observed_at=datetime(2026, 8, 22, 0, 0, tzinfo=UTC)
                    + timedelta(seconds=10 * index),
                    category=None,
                    idle=None,
                    safe_error_category="foreground_unavailable",
                )
                for index in range(6)
            )
        )
    except ProbeUnavailable:
        unavailable_rejected = True

    benchmark_samples = _samples(("development",) * 6)
    latencies_ms: list[float] = []
    started = time.perf_counter()
    for _ in range(iterations):
        call_started = time.perf_counter()
        aggregator.summarize(benchmark_samples)
        latencies_ms.append((time.perf_counter() - call_started) * 1000)
    elapsed = time.perf_counter() - started

    content_free_probe = WindowsCoarseContextAdapter.content_free_probe_evidence()
    fixed_payload = b"HAVRE-stage12a-synthetic-dpapi-roundtrip-v1"
    dpapi = WindowsDPAPIProtector()
    protected = dpapi.protect(fixed_payload)
    dpapi_roundtrip = protected != fixed_payload and dpapi.unprotect(protected) == fixed_payload

    forbidden_fields = {
        "application_name",
        "browser_history",
        "clipboard",
        "document_content",
        "executable_name",
        "keystrokes",
        "microphone",
        "process_name",
        "screenshot",
        "url",
        "window_title",
    }
    serialized_fixture_keys = set(
        aggregator.summarize(benchmark_samples).model_dump(mode="json")
    )
    minimum_sufficient = not (serialized_fixture_keys & forbidden_fields)
    passed = all(
        (
            fixture_passes == len(fixtures),
            unavailable_rejected,
            content_free_probe["activity_sample_collected"] is False,
            content_free_probe["content_collected"] is False,
            content_free_probe["exact_process_identity_retained"] is False,
            dpapi_roundtrip,
            minimum_sufficient,
        )
    )
    report = {
        "schema_version": 1,
        "benchmark": "stage12a-windows-coarse-context-v1",
        "measured_at": datetime.now(UTC).isoformat(),
        "source_revision": current_source_revision(PROJECT_ROOT),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor(),
        },
        "workload": {
            "fixture_kind": "synthetic-minimized-activity-windows",
            "iterations": iterations,
            "real_owner_activity_collected": False,
            "network_used": False,
            "oa70_accessed": False,
        },
        "conformance": {
            "fixture_passes": fixture_passes,
            "fixture_total": len(fixtures),
            "fixtures": fixture_results,
            "unavailable_probe_rejected": unavailable_rejected,
            "minimum_sufficient_fields_only": minimum_sufficient,
            "serialized_field_names": sorted(serialized_fixture_keys),
        },
        "native_content_free_evidence": content_free_probe,
        "protected_state": {
            "provider": "Windows DPAPI current-user scope",
            "synthetic_roundtrip_passed": dpapi_roundtrip,
            "plaintext_bytes": len(fixed_payload),
            "protected_bytes": len(protected),
        },
        "diagnostic_latency": {
            "elapsed_ms": round(elapsed * 1000, 3),
            "median_per_summary_ms": round(statistics.median(latencies_ms), 6),
            "max_per_summary_ms": round(max(latencies_ms), 6),
        },
        "interpretation": (
            "Synthetic conformance, content-free Windows API binding, and DPAPI "
            "roundtrip evidence only. It does not measure owner benefit, production "
            "capacity, battery/energy impact, or authorize ambient collection."
        ),
        "passed": passed,
    }
    if not passed:
        raise RuntimeError("Stage 12A Windows benchmark did not pass")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=10_000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(iterations=args.iterations)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
