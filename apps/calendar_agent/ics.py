"""Owner-local RFC 5545 availability provider for manual ICS imports.

The parser deliberately retains no provider content.  It supports the bounded
date/time and daily/weekly recurrence shapes used by course-calendar exports
and fails closed for unsupported recurrence rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from companion.life_context import CalendarAvailabilityWindow, CalendarBusyInterval


MAX_ICS_BYTES = 4 * 1024 * 1024
MAX_EVENTS = 4096
MAX_INTERVALS = 512
_WINDOWS_TZ = {
    "Central Standard Time": "America/Chicago",
    "Eastern Standard Time": "America/New_York",
    "Mountain Standard Time": "America/Denver",
    "Pacific Standard Time": "America/Los_Angeles",
    "UTC": "UTC",
}
_WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


class IcsProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class _Event:
    starts_at: datetime
    ends_at: datetime
    all_day: bool
    availability: str
    rrule: str | None
    exdates: tuple[datetime, ...]


def _unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw.startswith((" ", "\t")):
            if not lines:
                raise IcsProtocolError("ICS begins with a folded continuation")
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _property(line: str) -> tuple[str, dict[str, str], str]:
    if ":" not in line:
        raise IcsProtocolError("ICS property is missing a value separator")
    head, value = line.split(":", 1)
    pieces = head.split(";")
    name = pieces[0].upper()
    params: dict[str, str] = {}
    for piece in pieces[1:]:
        if "=" not in piece:
            raise IcsProtocolError("ICS property parameter is malformed")
        key, parameter_value = piece.split("=", 1)
        params[key.upper()] = parameter_value.strip('"')
    return name, params, value


def _zone(value: str | None, default_timezone: str | None) -> ZoneInfo:
    name = _WINDOWS_TZ.get(value or "", value or default_timezone)
    if not name:
        raise IcsProtocolError("floating ICS time requires an explicit timezone")
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as error:
        raise IcsProtocolError(f"unsupported ICS timezone: {value}") from error


def _datetime_value(
    value: str, params: dict[str, str], *, default_timezone: str | None
) -> tuple[datetime, bool]:
    if params.get("VALUE") == "DATE" or (len(value) == 8 and "T" not in value):
        try:
            parsed_date = datetime.strptime(value, "%Y%m%d").date()
        except ValueError as error:
            raise IcsProtocolError("invalid ICS date") from error
        return datetime.combine(parsed_date, time.min, _zone(params.get("TZID"), default_timezone)).astimezone(UTC), True
    formats = ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S%z", "%Y%m%dT%H%M%S", "%Y%m%dT%H%M")
    for format_string in formats:
        try:
            parsed = datetime.strptime(value, format_string)
        except ValueError:
            continue
        if value.endswith("Z"):
            parsed = parsed.replace(tzinfo=UTC)
        elif parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_zone(params.get("TZID"), default_timezone))
        return parsed.astimezone(UTC), False
    raise IcsProtocolError("invalid ICS date-time")


def _parse_rrule(value: str) -> dict[str, str]:
    rule: dict[str, str] = {}
    for item in value.split(";"):
        if "=" not in item:
            raise IcsProtocolError("malformed ICS recurrence rule")
        key, rule_value = item.split("=", 1)
        key = key.upper()
        if key in rule:
            raise IcsProtocolError("duplicate ICS recurrence key")
        rule[key] = rule_value.upper()
    allowed = {"FREQ", "INTERVAL", "COUNT", "UNTIL", "BYDAY", "WKST"}
    if set(rule) - allowed:
        raise IcsProtocolError("unsupported ICS recurrence key")
    if rule.get("FREQ") not in {"DAILY", "WEEKLY"}:
        raise IcsProtocolError("only daily or weekly ICS recurrence is supported")
    if rule.get("WKST", "MO") != "MO":
        raise IcsProtocolError("only Monday-based ICS recurrence weeks are supported")
    return rule


def _until(rule: dict[str, str], starts_at: datetime) -> datetime | None:
    raw = rule.get("UNTIL")
    if not raw:
        return None
    parsed, all_day = _datetime_value(
        raw,
        {"VALUE": "DATE"} if len(raw) == 8 else {},
        default_timezone=str(starts_at.tzinfo or "UTC"),
    )
    return parsed + (timedelta(days=1) if all_day else timedelta())


def _occurrences(event: _Event, window_from: datetime, window_to: datetime):
    if event.rrule is None:
        yield event.starts_at, event.ends_at
        return
    rule = _parse_rrule(event.rrule)
    try:
        interval = int(rule.get("INTERVAL", "1"))
        count = int(rule["COUNT"]) if "COUNT" in rule else None
    except ValueError as error:
        raise IcsProtocolError("ICS recurrence bounds are invalid") from error
    if interval < 1 or interval > 52 or (count is not None and (count < 1 or count > 4096)):
        raise IcsProtocolError("ICS recurrence bounds are invalid")
    until = _until(rule, event.starts_at)
    duration = event.ends_at - event.starts_at
    produced = 0
    cursor = event.starts_at
    hard_stop = min(window_to, until or window_to)
    if rule["FREQ"] == "DAILY":
        while cursor < hard_stop and (count is None or produced < count):
            yield cursor, cursor + duration
            produced += 1
            cursor += timedelta(days=interval)
        return
    bydays = rule.get("BYDAY")
    if bydays:
        day_tokens = bydays.split(",")
        if any(item not in _WEEKDAYS for item in day_tokens):
            raise IcsProtocolError("ICS recurrence weekday is invalid")
        weekdays = tuple(_WEEKDAYS[item] for item in day_tokens)
    else:
        weekdays = (event.starts_at.weekday(),)
    if len(set(weekdays)) != len(weekdays):
        raise IcsProtocolError("duplicate ICS recurrence weekday")
    week_start = event.starts_at - timedelta(days=event.starts_at.weekday())
    week = 0
    while True:
        any_in_range = False
        for weekday in sorted(weekdays):
            occurrence = week_start + timedelta(weeks=week * interval, days=weekday)
            occurrence = occurrence.replace(
                hour=event.starts_at.hour,
                minute=event.starts_at.minute,
                second=event.starts_at.second,
                microsecond=event.starts_at.microsecond,
            )
            if occurrence < event.starts_at:
                continue
            if occurrence >= hard_stop or (count is not None and produced >= count):
                continue
            any_in_range = True
            yield occurrence, occurrence + duration
            produced += 1
        if (count is not None and produced >= count) or week_start + timedelta(weeks=(week + 1) * interval) >= hard_stop:
            break
        week += 1
        if week > 4096:
            raise IcsProtocolError("ICS recurrence exceeded bounded expansion")


def parse_ics_availability(
    data: bytes,
    *,
    window_from: datetime,
    window_to: datetime,
    default_timezone: str | None = None,
) -> tuple[CalendarAvailabilityWindow, int]:
    if len(data) > MAX_ICS_BYTES:
        raise IcsProtocolError("ICS file exceeds the bounded size")
    if b"\x00" in data:
        raise IcsProtocolError("ICS file contains NUL bytes")
    try:
        lines = _unfold(data.decode("utf-8-sig"))
    except UnicodeDecodeError as error:
        raise IcsProtocolError("ICS file must be UTF-8") from error
    if "BEGIN:VCALENDAR" not in lines or "END:VCALENDAR" not in lines:
        raise IcsProtocolError("ICS calendar envelope is missing")
    blocks: list[list[tuple[str, dict[str, str], str]]] = []
    current: list[tuple[str, dict[str, str], str]] | None = None
    for line in lines:
        if line.upper() == "BEGIN:VEVENT":
            if current is not None:
                raise IcsProtocolError("nested ICS event")
            current = []
        elif line.upper() == "END:VEVENT":
            if current is None:
                raise IcsProtocolError("unmatched ICS event end")
            blocks.append(current)
            current = None
            if len(blocks) > MAX_EVENTS:
                raise IcsProtocolError("ICS event count exceeds the bound")
        elif current is not None:
            current.append(_property(line))
    if current is not None:
        raise IcsProtocolError("unterminated ICS event")

    intervals: list[CalendarBusyInterval] = []
    for properties in blocks:
        grouped: dict[str, list[tuple[dict[str, str], str]]] = {}
        for name, params, value in properties:
            grouped.setdefault(name, []).append((params, value))
        if grouped.get("STATUS", [({}, "")])[-1][1].upper() == "CANCELLED":
            continue
        if grouped.get("TRANSP", [({}, "OPAQUE")])[-1][1].upper() == "TRANSPARENT":
            continue
        if len(grouped.get("DTSTART", [])) != 1 or len(grouped.get("DTEND", [])) != 1:
            raise IcsProtocolError("ICS event requires one DTSTART and DTEND")
        starts_at, all_day = _datetime_value(*grouped["DTSTART"][0][::-1], default_timezone=default_timezone)
        ends_at, end_all_day = _datetime_value(*grouped["DTEND"][0][::-1], default_timezone=default_timezone)
        if ends_at <= starts_at or all_day != end_all_day:
            raise IcsProtocolError("ICS event duration is invalid")
        availability = "tentative" if grouped.get("STATUS", [({}, "")])[-1][1].upper() == "TENTATIVE" else "busy"
        microsoft_busy = grouped.get("X-MICROSOFT-CDO-BUSYSTATUS", [({}, "")])[-1][1].upper()
        availability = {"OOF": "out_of_office", "WORKINGELSEWHERE": "working_elsewhere", "TENTATIVE": "tentative"}.get(microsoft_busy, availability)
        exdates: list[datetime] = []
        for params, values in grouped.get("EXDATE", []):
            for value in values.split(","):
                exdates.append(_datetime_value(value, params, default_timezone=default_timezone)[0])
        rrules = grouped.get("RRULE", [])
        if len(rrules) > 1:
            raise IcsProtocolError("ICS event has multiple recurrence rules")
        event = _Event(starts_at, ends_at, all_day, availability, rrules[0][1] if rrules else None, tuple(exdates))
        for occurrence_start, occurrence_end in _occurrences(event, window_from, window_to):
            if occurrence_start in event.exdates:
                continue
            clipped_start = max(occurrence_start, window_from)
            clipped_end = min(occurrence_end, window_to)
            if clipped_end <= clipped_start:
                continue
            intervals.append(CalendarBusyInterval(
                starts_at=clipped_start,
                ends_at=clipped_end,
                availability=event.availability,
                is_all_day=event.all_day,
            ))
            if len(intervals) > MAX_INTERVALS:
                raise IcsProtocolError("ICS projection exceeds the interval bound")
    intervals = sorted(set(intervals), key=lambda item: (item.starts_at, item.ends_at, item.availability))
    return CalendarAvailabilityWindow(busy_intervals=tuple(intervals)), len(blocks)


class IcsCalendarProvider:
    def __init__(self, *, path: Path, default_timezone: str | None = None) -> None:
        self.path = path.resolve()
        self.default_timezone = default_timezone

    def read_all_calendar_availability(
        self,
        *,
        window_from: datetime,
        window_to: datetime,
        before_read: Callable[[], None] | None = None,
    ) -> tuple[CalendarAvailabilityWindow, int, int]:
        if window_from.utcoffset() is None or window_to.utcoffset() is None or window_to <= window_from:
            raise IcsProtocolError("ICS import window must be positive and timezone-aware")
        if self.path.suffix.casefold() != ".ics" or not self.path.is_file():
            raise IcsProtocolError("manual import requires one existing .ics file")
        if before_read is not None:
            before_read()
        with self.path.open("rb") as handle:
            before = self.path.stat()
            data = handle.read(MAX_ICS_BYTES + 1)
            after = self.path.stat()
        if (
            before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or after.st_size != len(data)
        ):
            raise IcsProtocolError("ICS file changed during import")
        value, rows = parse_ics_availability(
            data,
            window_from=window_from.astimezone(UTC),
            window_to=window_to.astimezone(UTC),
            default_timezone=self.default_timezone,
        )
        return value, rows, 1
