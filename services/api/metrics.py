"""Content-free in-process operational metrics for Stage 10."""

from __future__ import annotations

import threading
import re
from collections import defaultdict
from time import perf_counter

import psutil


class OperationalMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests: dict[tuple[str, str, int], int] = defaultdict(int)
        self._duration_seconds: dict[tuple[str, str], float] = defaultdict(float)

    def timer(self) -> float:
        return perf_counter()

    def observe(
        self, *, method: str, route: str, status_code: int, started: float
    ) -> None:
        safe_method = method.upper()
        if safe_method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}:
            safe_method = "OTHER"
        safe_route = route
        if (
            not re.fullmatch(r"/[A-Za-z0-9_{}./-]{0,119}", safe_route)
            or "//" in safe_route
        ):
            safe_route = "/unmatched"
        with self._lock:
            self._requests[(safe_method, safe_route, status_code)] += 1
            self._duration_seconds[(safe_method, safe_route)] += max(
                0.0, perf_counter() - started
            )

    def render(self, *, readiness: dict[str, object]) -> str:
        lines = [
            "# HELP havre_http_requests_total Completed HTTP requests.",
            "# TYPE havre_http_requests_total counter",
        ]
        with self._lock:
            request_rows = sorted(self._requests.items())
            duration_rows = sorted(self._duration_seconds.items())
        for (method, route, status_code), count in request_rows:
            lines.append(
                'havre_http_requests_total{method="%s",route="%s",status="%s"} %s'
                % (method, route, status_code, count)
            )
        lines.extend(
            (
                "# HELP havre_http_request_duration_seconds_sum Total request duration.",
                "# TYPE havre_http_request_duration_seconds_sum counter",
            )
        )
        for (method, route), seconds in duration_rows:
            lines.append(
                'havre_http_request_duration_seconds_sum{method="%s",route="%s"} %.9f'
                % (method, route, seconds)
            )
        failed_jobs = readiness.get("failed_jobs", {})
        if isinstance(failed_jobs, dict):
            lines.extend(
                (
                    "# HELP havre_failed_jobs Current failed durable jobs.",
                    "# TYPE havre_failed_jobs gauge",
                )
            )
            for queue, count in sorted(failed_jobs.items()):
                lines.append(f'havre_failed_jobs{{queue="{queue}"}} {int(count)}')
        process = psutil.Process()
        lines.extend(
            (
                "# HELP havre_process_resident_memory_bytes Resident process memory.",
                "# TYPE havre_process_resident_memory_bytes gauge",
                f"havre_process_resident_memory_bytes {process.memory_info().rss}",
                "# HELP havre_process_cpu_percent Process CPU utilization sample.",
                "# TYPE havre_process_cpu_percent gauge",
                f"havre_process_cpu_percent {process.cpu_percent(interval=None):.3f}",
            )
        )
        return "\n".join(lines) + "\n"
