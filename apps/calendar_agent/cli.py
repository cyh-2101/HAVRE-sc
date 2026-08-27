"""Owner-local, manual ICS import command."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from uuid import UUID

from apps.calendar_agent.runner import CalendarAgentRunner
from apps.windows_agent.offline_queue import read_dpapi_secret
from apps.windows_agent.transport import WindowsAgentTransport


def _aware_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must include a UTC offset")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="havre-calendar-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)
    import_ics = subparsers.add_parser("import-ics")
    import_ics.add_argument("--ics-file", type=Path, required=True)
    import_ics.add_argument("--window-from", type=_aware_datetime, required=True)
    import_ics.add_argument("--window-to", type=_aware_datetime, required=True)
    import_ics.add_argument("--default-timezone", default="America/Chicago")
    import_ics.add_argument("--core-url", required=True)
    import_ics.add_argument("--owner-id", type=UUID, required=True)
    import_ics.add_argument("--source-instance-id", type=UUID, required=True)
    import_ics.add_argument("--device-binding-id", required=True)
    import_ics.add_argument("--protected-device-secret-file", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command != "import-ics":
        raise AssertionError("unreachable")
    transport = WindowsAgentTransport(
        base_url=args.core_url,
        owner_id=args.owner_id,
        source_instance_id=args.source_instance_id,
        device_binding_id=args.device_binding_id,
        signing_secret=read_dpapi_secret(args.protected_device_secret_file),
    )
    try:
        report = CalendarAgentRunner(transport=transport).import_ics(
            path=args.ics_file,
            window_from=args.window_from,
            window_to=args.window_to,
            default_timezone=args.default_timezone,
        )
    finally:
        transport.close()
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "observation_submitted" else 2


if __name__ == "__main__":
    raise SystemExit(main())
