"""One owner-initiated manual ICS import into HAVRE Core."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from apps.calendar_agent.calendar import CalendarAvailabilityAdapter
from apps.calendar_agent.ics import IcsCalendarProvider, IcsProtocolError
from apps.windows_agent.transport import (
    ContextTransportRejected,
    ContextTransportUnavailable,
    WindowsAgentTransport,
)
from companion.life_context import CalendarImportPolicy


class CalendarAgentRunner:
    def __init__(
        self,
        *,
        transport: WindowsAgentTransport,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.transport = transport
        self.clock = clock

    def import_ics(
        self,
        *,
        path: Path,
        window_from: datetime,
        window_to: datetime,
        default_timezone: str | None,
    ) -> dict[str, object]:
        try:
            permit = self.transport.request_permit()
        except ContextTransportRejected:
            return self._report("authorization_rejected")
        except ContextTransportUnavailable:
            return self._report("core_unavailable")
        if (
            permit.source.source_kind != "calendar"
            or permit.source.provider_id != "manual-ics"
            or not isinstance(permit.consent.sampling_policy, CalendarImportPolicy)
        ):
            return self._report("authorization_rejected")
        try:
            collection = CalendarAvailabilityAdapter(
                source=permit.source,
                capability=permit.capability,
                consent=permit.consent,
                signing_secret=self.transport.signing_secret,
                provider=IcsCalendarProvider(
                    path=path,
                    default_timezone=default_timezone,
                ),
                permit_resolver=self.transport.request_permit,
                clock=self.clock,
            ).collect(window_from=window_from, window_to=window_to)
            self.transport.submit_observation(collection.draft)
        except ContextTransportRejected:
            return self._report("authorization_rejected")
        except ContextTransportUnavailable:
            return self._report("core_unavailable")
        except PermissionError:
            return self._report("authorization_rejected")
        except IcsProtocolError:
            return self._report("ics_rejected")
        except OSError:
            return self._report("ics_unavailable")
        return {
            **self._report("observation_submitted"),
            "calendar_files_seen": collection.calendars_seen,
            "provider_rows_seen": collection.provider_rows_seen,
            "retained_busy_intervals": collection.retained_busy_intervals,
        }

    @staticmethod
    def _report(status: str) -> dict[str, object]:
        return {
            "schema_version": 1,
            "status": status,
            "content_included": False,
            "automatic_loop_enabled": False,
            "source_native_file_copied": False,
            "network_provider_used": False,
        }
