"""Synthetic, content-free conformance benchmark for Calendar availability."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import json
import platform
from pathlib import Path
import statistics
import time

from apps.calendar_agent.ics import IcsProtocolError, parse_ics_availability
from companion.life_context import CalendarAvailabilityWindow
from services.api.source_provenance import current_source_revision


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run(*, iterations: int) -> dict[str, object]:
    if iterations < 100:
        raise ValueError("benchmark requires at least 100 synthetic iterations")
    window_from = datetime(2026, 8, 22, tzinfo=UTC)
    window_to = window_from + timedelta(days=7)
    fixture = b"""BEGIN:VCALENDAR\r
VERSION:2.0\r
BEGIN:VEVENT\r
UID:must-not-cross\r
SUMMARY:must-not-cross\r
LOCATION:must-not-cross\r
DTSTART:20260822T010000Z\r
DTEND:20260822T020000Z\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:must-not-cross-free\r
TRANSP:TRANSPARENT\r
DTSTART:20260822T030000Z\r
DTEND:20260822T040000Z\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:must-not-cross-cancelled\r
STATUS:CANCELLED\r
DTSTART:20260822T050000Z\r
DTEND:20260822T060000Z\r
END:VEVENT\r
END:VCALENDAR\r
"""
    expected = CalendarAvailabilityWindow.model_validate({
        "schema_version": 1,
        "busy_intervals": [{
            "starts_at": (window_from + timedelta(hours=1)).isoformat(),
            "ends_at": (window_from + timedelta(hours=2)).isoformat(),
            "availability": "busy",
            "is_all_day": False,
        }],
    })
    observed, rows_seen = parse_ics_availability(
        fixture, window_from=window_from, window_to=window_to
    )
    provider_replacement = CalendarAvailabilityWindow.model_validate(
        observed.model_dump(mode="json")
    )
    forbidden = (
        "must-not-cross", "subject", "body", "location", "organizer", "attendees"
    )
    serialized = observed.model_dump_json().lower()
    forbidden_crossings = [field for field in forbidden if field in serialized]
    unsupported_rejected = False
    try:
        parse_ics_availability(
            fixture.replace(b"END:VEVENT", b"RRULE:FREQ=MONTHLY\r\nEND:VEVENT", 1),
            window_from=window_from,
            window_to=window_to,
        )
    except IcsProtocolError:
        unsupported_rejected = True

    latencies_ms: list[float] = []
    started = time.perf_counter()
    for _ in range(iterations):
        call_started = time.perf_counter()
        parse_ics_availability(fixture, window_from=window_from, window_to=window_to)
        latencies_ms.append((time.perf_counter() - call_started) * 1000)
    elapsed = time.perf_counter() - started
    passed = all((
        observed == expected,
        provider_replacement == expected,
        not forbidden_crossings,
        unsupported_rejected,
    ))
    report = {
        "schema_version": 1,
        "benchmark": "stage12a-calendar-availability-v1",
        "measured_at": datetime.now(UTC).isoformat(),
        "source_revision": current_source_revision(PROJECT_ROOT),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor(),
        },
        "workload": {
            "fixture_kind": "synthetic-owner-supplied-ics",
            "iterations": iterations,
            "provider_rows_per_iteration": rows_seen,
            "real_calendar_content_collected": False,
            "network_used": False,
            "oa70_accessed": False,
        },
        "conformance": {
            "busy_rows_retained": len(observed.busy_intervals),
            "free_or_cancelled_rows_discarded": 2,
            "unsupported_recurrence_rejected": unsupported_rejected,
            "provider_replacement_equivalent": provider_replacement == expected,
            "forbidden_content_crossings": forbidden_crossings,
            "canonical_payload_bytes": len(observed.model_dump_json().encode("utf-8")),
        },
        "diagnostic_latency": {
            "elapsed_ms": round(elapsed * 1000, 3),
            "median_per_projection_ms": round(statistics.median(latencies_ms), 6),
            "max_per_projection_ms": round(max(latencies_ms), 6),
        },
        "interpretation": (
            "Synthetic minimization and provider-replacement conformance only. "
            "It does not establish owner benefit, real ICS compatibility, "
            "calendar density, or permission for richer Calendar persistence."
        ),
        "passed": passed,
    }
    if not passed:
        raise RuntimeError("Stage 12A Calendar benchmark did not pass")
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
