"""Controlled synthetic Stage 10 API load and failure-recovery benchmark."""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import psutil
from fastapi.testclient import TestClient

from companion.hashing import content_hash
from evals.inference_runner import current_source_revision
from mlsys.contracts import ProviderHealth
from services.api.app import create_app
from services.api.settings import Settings


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, int((len(ordered) - 1) * percentile))
    return round(ordered[index], 3)


def run(
    *,
    database_url: str,
    owner_id: UUID,
    requests: int,
    concurrency: int,
    working_root: Path,
) -> dict[str, object]:
    if requests < 8 or concurrency < 1 or concurrency > requests:
        raise ValueError("benchmark requires at least 8 requests and bounded concurrency")
    token = f"stage10-load-token-{uuid4()}"
    settings = Settings.from_env().model_copy(
        update={
            "database_url": database_url,
            "owner_id": owner_id,
            "provider_id": "deterministic-local",
            "owner_api_token": token,
            "erasure_ledger_path": working_root / "erasure-ledger.sqlite3",
            "owner_export_root": working_root / "exports",
        }
    )
    workload = {
        "schema_version": 1,
        "request_count": requests,
        "concurrency": concurrency,
        "privacy_class": "LOCAL_ONLY",
        "memory_eligible": False,
        "provider": "deterministic-local",
        "message_shape": "synthetic fixed-prefix plus sequence",
    }
    process = psutil.Process()
    cpu_before = process.cpu_times()
    rss_before = process.memory_info().rss
    started = time.perf_counter()
    latencies: list[float] = []
    status_codes: list[int] = []
    with TestClient(create_app(settings)) as client:
        headers = {"Authorization": f"Bearer {token}"}

        def execute(index: int) -> tuple[int, float]:
            call_started = time.perf_counter()
            response = client.post(
                "/v1/interactions",
                headers={
                    **headers,
                    "Idempotency-Key": f"stage10-load-{uuid4()}-{index}",
                },
                json={
                    "message": f"Synthetic reliability request {index}",
                    "privacy_class": "LOCAL_ONLY",
                    "memory_eligible": False,
                },
            )
            return response.status_code, (time.perf_counter() - call_started) * 1000

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            for status_code, latency in executor.map(execute, range(requests)):
                status_codes.append(status_code)
                latencies.append(latency)
        load_elapsed = time.perf_counter() - started
        metrics = client.get("/metrics", headers=headers)
        metrics_content_free = (
            metrics.status_code == 200
            and "Synthetic reliability request" not in metrics.text
            and "stage10-load-" not in metrics.text
        )
        wrong_token = client.get(
            "/metrics",
            headers={"Authorization": "Bearer definitely-wrong"},
        ).status_code
        original_health = client.app.state.runtime.service.provider.health

        async def unavailable_health() -> ProviderHealth:
            return ProviderHealth(
                status="unavailable",
                observed_at=datetime.now(UTC),
                latency_ms=0,
                loaded_model_version_ids=(),
                reasons=("controlled_failure_fixture",),
            )

        client.app.state.runtime.service.provider.health = unavailable_health
        provider_failure_status = client.get("/health/ready").status_code
        provider_failure_liveness = client.get("/health/live").status_code
        client.app.state.runtime.service.provider.health = original_health
        provider_recovery_status = client.get("/health/ready").status_code
        client.app.state.runtime.repository.close()
        database_failure_status = client.get("/health/ready").status_code
        database_failure_liveness = client.get("/health/live").status_code
    cpu_after = process.cpu_times()
    rss_after = process.memory_info().rss
    successes = status_codes.count(201)
    result = {
        "schema_version": 1,
        "benchmark": "stage10-controlled-reliability-v1",
        "measured_at": datetime.now(UTC).isoformat(),
        "source_revision": current_source_revision(PROJECT_ROOT),
        "migration_head": "0034_stage10_backup_fk_index.sql",
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor(),
        },
        "workload": workload,
        "workload_hash": content_hash(workload),
        "load": {
            "successful_requests": successes,
            "failed_requests": requests - successes,
            "elapsed_seconds": round(load_elapsed, 3),
            "throughput_requests_per_second": round(requests / load_elapsed, 3),
            "latency_ms": {
                "min": round(min(latencies), 3),
                "median": round(statistics.median(latencies), 3),
                "p95": _percentile(latencies, 0.95),
                "max": round(max(latencies), 3),
            },
            "process_user_cpu_seconds": round(cpu_after.user - cpu_before.user, 3),
            "process_system_cpu_seconds": round(cpu_after.system - cpu_before.system, 3),
            "rss_delta_bytes": rss_after - rss_before,
        },
        "failure_probes": {
            "wrong_bearer_rejected": wrong_token == 401,
            "provider_unavailable_ready_status": provider_failure_status,
            "provider_unavailable_liveness_status": provider_failure_liveness,
            "provider_recovery_ready_status": provider_recovery_status,
            "database_unavailable_ready_status": database_failure_status,
            "database_unavailable_liveness_status": database_failure_liveness,
            "metrics_content_free": metrics_content_free,
        },
    }
    expected = {
        "successful_requests": requests,
        "failed_requests": 0,
        "wrong_bearer_rejected": True,
        "provider_unavailable_ready_status": 503,
        "provider_unavailable_liveness_status": 200,
        "provider_recovery_ready_status": 200,
        "database_unavailable_ready_status": 503,
        "database_unavailable_liveness_status": 200,
        "metrics_content_free": True,
    }
    observed = {
        "successful_requests": result["load"]["successful_requests"],
        "failed_requests": result["load"]["failed_requests"],
        **result["failure_probes"],
    }
    result["passed"] = observed == expected
    if not result["passed"]:
        raise RuntimeError(f"controlled reliability benchmark failed: {observed}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url-file", type=Path, required=True)
    parser.add_argument("--owner-id", type=UUID, required=True)
    parser.add_argument("--requests", type=int, default=40)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--working-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    database_url = args.database_url_file.read_text(encoding="utf-8").strip()
    if not database_url:
        raise ValueError("database URL secret file is empty")
    report = run(
        database_url=database_url,
        owner_id=args.owner_id,
        requests=args.requests,
        concurrency=args.concurrency,
        working_root=args.working_root.resolve(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
