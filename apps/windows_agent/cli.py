"""Local Windows agent diagnostic commands; no collection loop is enabled by default."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from uuid import UUID

from apps.windows_agent.coarse_context import WindowsCoarseContextAdapter
from apps.windows_agent.offline_queue import ProtectedOfflineQueue
from apps.windows_agent.offline_queue import read_dpapi_secret
from apps.windows_agent.runner import WindowsAgentRunner
from apps.windows_agent.transport import WindowsAgentTransport
from services.api.source_provenance import source_snapshot_revision


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description="HAVRE Windows coarse ContextSource")
    parser.add_argument(
        "command", choices=("capability-check", "queue-cleanup", "run-once")
    )
    parser.add_argument("--expected-source-snapshot")
    parser.add_argument("--queue-path", type=Path)
    args = parser.parse_args()
    observed_snapshot = source_snapshot_revision(PROJECT_ROOT)
    if (
        args.expected_source_snapshot is not None
        and args.expected_source_snapshot != observed_snapshot
    ):
        raise SystemExit("Windows agent source snapshot mismatch")
    if args.command == "capability-check":
        print(json.dumps(
            WindowsCoarseContextAdapter.content_free_probe_evidence(),
            sort_keys=True,
            separators=(",", ":"),
        ))
        return
    queue = ProtectedOfflineQueue(path=(
        args.queue_path
        or Path(os.getenv(
            "HAVRE_CONTEXT_QUEUE_PATH",
            str(Path.home() / ".havre" / "context-queue.dpapi"),
        ))
    ))
    if args.command == "queue-cleanup":
        print(json.dumps({
            "schema_version": 1,
            "expired_items_removed": queue.prune_expired(),
            "content_included": False,
            "source_snapshot": observed_snapshot,
        }, sort_keys=True, separators=(",", ":")))
        return
    if args.expected_source_snapshot is None:
        raise SystemExit("run-once requires --expected-source-snapshot")
    secret_path = os.getenv("HAVRE_CONTEXT_DEVICE_SECRET_DPAPI_FILE")
    if not secret_path:
        raise SystemExit("HAVRE_CONTEXT_DEVICE_SECRET_DPAPI_FILE is required")
    secret = read_dpapi_secret(Path(secret_path))
    transport = WindowsAgentTransport(
        base_url=os.environ["HAVRE_CONTEXT_CORE_BASE_URL"],
        owner_id=UUID(os.environ["HAVRE_OWNER_ID"]),
        source_instance_id=UUID(os.environ["HAVRE_CONTEXT_SOURCE_INSTANCE_ID"]),
        device_binding_id=os.environ["HAVRE_CONTEXT_DEVICE_BINDING_ID"],
        signing_secret=secret,
    )
    try:
        result = WindowsAgentRunner(
            transport=transport,
            queue=queue,
        ).run_once()
    finally:
        transport.close()
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
