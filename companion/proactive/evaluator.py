"""Core-owned deterministic trigger evaluation over explicit durable evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo


from companion.events import (
    EventEnvelope,
    EventType,
    GoalLifecyclePayload,
    SceneSessionLifecyclePayload,
    UserMessagePayload,
)
from companion.hashing import content_hash
from companion.ids import uuid7
from companion.persistence.proactive import ProactivePostgresStore
from companion.proactive.models import ProactiveSourceGuard, ProactiveWorkCommand


EVALUATOR_VERSION = "proactive-trigger-evaluator-v1"
_CONTEXT_ONLY_TYPES = {
    "MEMORY_CREATED",
    "MEMORY_REVISED",
    "CURRENT_STATE_ESTIMATED",
    "LIFE_CONTEXT_OBSERVED",
    "USER_BELIEF_CREATED",
    "USER_BELIEF_REVISED",
    "USER_BELIEF_TRANSITIONED",
}
_RELEVANT_TYPES = _CONTEXT_ONLY_TYPES | {
    "USER_MESSAGE",
    "GOAL_CREATED",
    "GOAL_UPDATED",
    "SCENE_SESSION_PLANNED",
}
_ZH_NUMERALS = {
    "\u4e00": 1,
    "\u4e24": 2,
    "\u4e8c": 2,
    "\u4e09": 3,
    "\u56db": 4,
    "\u4e94": 5,
    "\u516d": 6,
    "\u4e03": 7,
    "\u516b": 8,
    "\u4e5d": 9,
    "\u5341": 10,
}
_REMINDER_MARKER = re.compile(
    r"(?:\u8bf7|\u9ebb\u70e6)?(?:\u8bb0\u5f97|\u5230\u65f6\u5019)?\u63d0\u9192\u6211|\bremind\s+me\b",
    re.IGNORECASE,
)
_RELATIVE_ZH = re.compile(
    r"(?P<number>\d{1,3}|[\u4e00\u4e8c\u4e24\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341]{1,3})\s*"
    r"(?P<unit>\u5206\u949f|\u5c0f\u65f6|\u5929)\s*(?:\u540e|\u4ee5\u540e)"
)
_RELATIVE_EN = re.compile(
    r"\bin\s+(?P<number>\d{1,3})\s+"
    r"(?P<unit>minutes?|hours?|days?)\b",
    re.IGNORECASE,
)
_ISO_DATE = re.compile(r"(?<!\d)(?P<year>20\d{2})[-/](?P<month>\d{1,2})[-/](?P<day>\d{1,2})(?!\d)")
_MONTH_DAY = re.compile(r"(?<!\d)(?P<month>\d{1,2})[\u6708/-](?P<day>\d{1,2})(?:\u65e5|\u53f7)?(?!\d)")
_ZH_TIME = re.compile(
    r"(?P<period>\u51cc\u6668|\u65e9\u4e0a|\u4e0a\u5348|\u4e2d\u5348|\u4e0b\u5348|\u508d\u665a|\u665a\u4e0a)?\s*"
    r"(?P<hour>\d{1,2})\s*(?:\u70b9|\u65f6|:|\uff1a)"
    r"(?:(?P<minute>\d{1,2})\s*\u5206?|(?P<half>\u534a))?"
)
_EN_TIME = re.compile(
    r"\b(?:at\s+)?(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*"
    r"(?P<period>am|pm)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ReminderIntent:
    due_at: datetime
    content: str


@dataclass(frozen=True)
class EvaluatedCandidate:
    candidate_kind: Literal["owner_reminder", "goal_review", "scene_start", "context_only"]
    disposition: Literal["enqueued", "ignored", "expired"]
    reason_code: str
    work_item_id: UUID | None = None


def _zh_integer(value: str) -> int:
    if value.isdigit():
        return int(value)
    if value in _ZH_NUMERALS:
        return _ZH_NUMERALS[value]
    if "\u5341" in value:
        left, right = value.split("\u5341", 1)
        tens = _ZH_NUMERALS.get(left, 1) if left else 1
        ones = _ZH_NUMERALS.get(right, 0) if right else 0
        return tens * 10 + ones
    raise ValueError("unsupported Chinese integer")


def _local_datetime(day: date, hour: int, minute: int, timezone: ZoneInfo) -> datetime:
    if hour > 23 or minute > 59:
        raise ValueError("invalid reminder time")
    return datetime.combine(day, time(hour, minute), tzinfo=timezone).astimezone(UTC)


def _clean_reminder_content(text: str, spans: list[tuple[int, int]]) -> str:
    pieces: list[str] = []
    cursor = 0
    for start, end in sorted(spans):
        if start > cursor:
            pieces.append(text[cursor:start])
        cursor = max(cursor, end)
    pieces.append(text[cursor:])
    cleaned = "".join(pieces)
    cleaned = re.sub(r"^[\s,\u3002\uff0c:\uff1a;\uff1b\u3001!\uff01?\uff1f-]+|[\s,\u3002\uff0c:\uff1a;\uff1b\u3001!\uff01?\uff1f-]+$", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned[:500]


def parse_explicit_reminder(
    text: str, *, observed_at: datetime, owner_timezone: str
) -> ReminderIntent | None:
    """Parse only explicit owner reminder commands; ordinary conversation is ignored."""
    marker = _REMINDER_MARKER.search(text)
    if marker is None:
        return None
    timezone = ZoneInfo(owner_timezone)
    local_observed = observed_at.astimezone(timezone)
    spans = [marker.span()]

    relative = _RELATIVE_ZH.search(text)
    if relative is not None:
        amount = _zh_integer(relative.group("number"))
        unit = relative.group("unit")
        delta = {
            "\u5206\u949f": timedelta(minutes=amount),
            "\u5c0f\u65f6": timedelta(hours=amount),
            "\u5929": timedelta(days=amount),
        }[unit]
        spans.append(relative.span())
        content = _clean_reminder_content(text, spans)
        return ReminderIntent(local_observed.astimezone(UTC) + delta, content) if content else None

    relative_en = _RELATIVE_EN.search(text)
    if relative_en is not None:
        amount = int(relative_en.group("number"))
        unit = relative_en.group("unit").lower()
        delta = (
            timedelta(minutes=amount)
            if unit.startswith("minute")
            else timedelta(hours=amount)
            if unit.startswith("hour")
            else timedelta(days=amount)
        )
        spans.append(relative_en.span())
        content = _clean_reminder_content(text, spans)
        return ReminderIntent(local_observed.astimezone(UTC) + delta, content) if content else None

    target_day = local_observed.date()
    day_match: re.Match[str] | None = None
    for token, offset in (("\u540e\u5929", 2), ("\u660e\u5929", 1), ("\u4eca\u5929", 0)):
        index = text.find(token)
        if index >= 0:
            target_day = local_observed.date() + timedelta(days=offset)
            spans.append((index, index + len(token)))
            break
    else:
        iso = _ISO_DATE.search(text)
        if iso is not None:
            day_match = iso
            target_day = date(int(iso.group("year")), int(iso.group("month")), int(iso.group("day")))
        else:
            month_day = _MONTH_DAY.search(text)
            if month_day is not None:
                day_match = month_day
                year = local_observed.year
                target_day = date(year, int(month_day.group("month")), int(month_day.group("day")))
                if target_day < local_observed.date():
                    target_day = date(year + 1, target_day.month, target_day.day)
        if day_match is not None:
            spans.append(day_match.span())

    time_match = _ZH_TIME.search(text)
    if time_match is not None:
        hour = int(time_match.group("hour"))
        minute = 30 if time_match.group("half") else int(time_match.group("minute") or 0)
        period = time_match.group("period")
        if period in {"\u4e0b\u5348", "\u508d\u665a", "\u665a\u4e0a"} and hour < 12:
            hour += 12
        elif period == "\u4e2d\u5348" and hour < 11:
            hour += 12
        elif period in {"\u51cc\u6668", "\u65e9\u4e0a", "\u4e0a\u5348"} and hour == 12:
            hour = 0
    else:
        time_match = _EN_TIME.search(text)
        if time_match is None:
            return None
        hour = int(time_match.group("hour"))
        minute = int(time_match.group("minute") or 0)
        if hour < 1 or hour > 12:
            return None
        if time_match.group("period").lower() == "pm" and hour < 12:
            hour += 12
        elif time_match.group("period").lower() == "am" and hour == 12:
            hour = 0
    spans.append(time_match.span())
    due_at = _local_datetime(target_day, hour, minute, timezone)
    if not any(token in text for token in ("\u4eca\u5929", "\u660e\u5929", "\u540e\u5929")) and day_match is None:
        if due_at <= observed_at.astimezone(UTC):
            due_at += timedelta(days=1)
    content = _clean_reminder_content(text, spans)
    return ReminderIntent(due_at, content) if content else None


class ProactiveTriggerEvaluator:
    """Evaluates exact source Events into idempotent, guarded Stage 6 work."""

    def __init__(
        self,
        *,
        store: ProactivePostgresStore,
        owner_timezone: str,
    ) -> None:
        self.store = store
        self.repository = store.repository
        self.owner_id = store.owner_id
        self.owner_timezone = owner_timezone

    def _current_preference_revision(self) -> int:
        with self.repository.pool.connection() as connection:
            row = connection.execute(
                """SELECT head.revision FROM havre.proactive_preference_heads head
                   WHERE head.owner_id=%s""",
                (self.owner_id,),
            ).fetchone()
        if row is None:
            raise LookupError("current proactive preference head not found")
        return int(row["revision"])

    def _candidate_for_event(self, event: EventEnvelope, *, now: datetime) -> tuple[EvaluatedCandidate, ProactiveWorkCommand | None, datetime | None]:
        source_ref = f"event:{event.event_id}:{event.content_hash}"
        guard = ProactiveSourceGuard(
            source_event_id=event.event_id,
            source_event_content_hash=event.content_hash,
        )
        due_at: datetime | None = None
        kind: Literal["owner_reminder", "goal_review", "scene_start", "context_only"]
        reason_code: str
        summary: str
        intended_benefit: str
        source_kind: str
        subject_refs: tuple[str, ...] = ()

        if event.event_type is EventType.USER_MESSAGE:
            payload = event.payload
            if not isinstance(payload, UserMessagePayload):
                raise ValueError("USER_MESSAGE payload mismatch")
            text = "\n".join(part.text for part in payload.content_parts)
            intent = parse_explicit_reminder(
                text, observed_at=event.recorded_at, owner_timezone=self.owner_timezone
            )
            if intent is None:
                return EvaluatedCandidate("owner_reminder", "ignored", "no_explicit_time_bound_reminder"), None, None
            kind, due_at = "owner_reminder", intent.due_at
            reason_code = "owner_requested_time_bound_reminder"
            summary = intent.content
            intended_benefit = "\u5728 owner \u660e\u786e\u9009\u62e9\u7684\u65f6\u95f4\u63d0\u9192\u8fd9\u4ef6\u4e8b"
            source_kind = "owner_reminder"
            subject_refs = (f"reminder:{event.event_id}",)
        elif event.event_type in {EventType.GOAL_CREATED, EventType.GOAL_UPDATED}:
            payload = event.payload
            if not isinstance(payload, GoalLifecyclePayload) or payload.review_at is None:
                return EvaluatedCandidate("goal_review", "ignored", "goal_has_no_review_time"), None, None
            with self.repository.pool.connection() as connection:
                row = connection.execute(
                    """SELECT * FROM havre.goals WHERE owner_id=%s AND goal_id=%s""",
                    (self.owner_id, payload.goal_id),
                ).fetchone()
            if (
                row is None
                or row["last_event_id"] != event.event_id
                or row["revision"] != payload.goal_revision
                or row["content_hash"] != payload.projection_content_hash
                or row["status"] != "active"
            ):
                return EvaluatedCandidate("goal_review", "ignored", "goal_projection_not_current_active"), None, None
            kind, due_at = "goal_review", payload.review_at.astimezone(UTC)
            reason_code = "goal_review_due"
            summary = f"\u4e4b\u524d\u5b9a\u7684\u300c{payload.title}\u300d\u5230\u590d\u76d8\u65f6\u95f4\u4e86"
            intended_benefit = "\u5728 owner \u4e3a\u5f53\u524d Goal \u9009\u62e9\u7684\u65f6\u95f4\u63d0\u4f9b\u4e00\u6b21\u590d\u76d8\u5165\u53e3"
            source_kind = "goal"
            subject_refs = (f"goal:{payload.goal_id}",)
            guard = ProactiveSourceGuard(
                source_event_id=event.event_id,
                source_event_content_hash=event.content_hash,
                projection_kind="goal",
                projection_id=payload.goal_id,
                projection_revision=payload.goal_revision,
                projection_content_hash=payload.projection_content_hash,
            )
        elif event.event_type is EventType.SCENE_SESSION_PLANNED:
            payload = event.payload
            if not isinstance(payload, SceneSessionLifecyclePayload):
                raise ValueError("SCENE_SESSION_PLANNED payload mismatch")
            with self.repository.pool.connection() as connection:
                row = connection.execute(
                    """SELECT * FROM havre.scene_sessions
                       WHERE owner_id=%s AND scene_session_id=%s""",
                    (self.owner_id, payload.scene_session_id),
                ).fetchone()
            if (
                row is None
                or row["last_event_id"] != event.event_id
                or row["revision"] != payload.scene_revision
                or row["status"] != "planned"
                or row["phase"] != "before"
                or row["planned_start_at"] is None
            ):
                return EvaluatedCandidate("scene_start", "ignored", "scene_not_current_planned_with_time"), None, None
            kind, due_at = "scene_start", row["planned_start_at"].astimezone(UTC)
            reason_code = "planned_scene_start_due"
            scene_label = str(row["planned_goal"].get("description") or row["scene_type"])
            summary = f"\u4e4b\u524d\u8ba1\u5212\u7684\u300c{scene_label}\u300d\u5230\u65f6\u95f4\u4e86"
            intended_benefit = "\u5728 owner \u660e\u786e\u8ba1\u5212\u7684 Scene \u5f00\u59cb\u65f6\u95f4\u63d0\u4f9b\u652f\u6301"
            source_kind = "scene_session"
            subject_refs = (f"scene:{payload.scene_session_id}",)
            guard = ProactiveSourceGuard(
                source_event_id=event.event_id,
                source_event_content_hash=event.content_hash,
                projection_kind="scene",
                projection_id=payload.scene_session_id,
                projection_revision=payload.scene_revision,
                projection_content_hash=row["content_hash"],
            )
        else:
            return EvaluatedCandidate("context_only", "ignored", "context_source_has_no_independent_trigger_authority"), None, None

        assert due_at is not None
        expires_at = due_at + (timedelta(hours=2) if kind == "scene_start" else timedelta(hours=6))
        if expires_at <= now:
            return EvaluatedCandidate(kind, "expired", "owner_chosen_time_window_expired"), None, None
        command = ProactiveWorkCommand(
            trigger_type={
                "owner_reminder": "owner_reminder_due",
                "goal_review": "goal_review_due",
                "scene_start": "planned_scene_start_due",
            }[kind],
            source_kind=source_kind,
            source_refs=(source_ref,),
            subject_refs=subject_refs,
            category="owner_reminder",
            reason_code=reason_code,
            reason_summary=summary,
            intended_benefit=intended_benefit,
            data_policy=event.data_policy,
            preference_revision=self._current_preference_revision(),
            execution_idempotency_key=f"auto-proactive:{EVALUATOR_VERSION}:{event.event_id}:{event.content_hash}",
            observed_at=event.recorded_at,
            earliest_eligible_at=due_at,
            expires_at=expires_at,
            deduplication_key=f"{kind}:{event.event_id}:{due_at.isoformat()}",
            trigger_source_version=EVALUATOR_VERSION,
            source_guard=guard,
        )
        return EvaluatedCandidate(kind, "enqueued", reason_code), command, max(now, due_at)

    def _record(self, event: EventEnvelope, candidate: EvaluatedCandidate) -> None:
        material = {
            "evaluator_version": EVALUATOR_VERSION,
            "source_event_id": str(event.event_id),
            "source_event_content_hash": event.content_hash,
            "candidate_kind": candidate.candidate_kind,
            "disposition": candidate.disposition,
            "reason_code": candidate.reason_code,
            "work_item_id": str(candidate.work_item_id) if candidate.work_item_id else None,
        }
        with self.repository.pool.connection() as connection, connection.transaction():
            connection.execute(
                """INSERT INTO havre.proactive_trigger_evaluations
                   (owner_id,evaluation_id,evaluator_version,source_event_id,
                    source_event_content_hash,source_event_type,candidate_kind,
                    disposition,reason_code,work_item_id,content_hash)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (owner_id,evaluator_version,source_event_id,
                                source_event_content_hash) DO NOTHING""",
                (
                    self.owner_id,
                    uuid7(),
                    EVALUATOR_VERSION,
                    event.event_id,
                    event.content_hash,
                    event.event_type.value,
                    candidate.candidate_kind,
                    candidate.disposition,
                    candidate.reason_code,
                    candidate.work_item_id,
                    content_hash(material),
                ),
            )

    def run_once(self, *, limit: int = 100) -> dict[str, int]:
        now = datetime.now(UTC)
        with self.repository.pool.connection() as connection:
            rows = connection.execute(
                """SELECT event.event_id FROM havre.events event
                   WHERE event.owner_id=%s AND event.event_type=ANY(%s)
                     AND NOT EXISTS (
                       SELECT 1 FROM havre.proactive_trigger_evaluations evaluation
                       WHERE evaluation.owner_id=event.owner_id
                         AND evaluation.evaluator_version=%s
                         AND evaluation.source_event_id=event.event_id
                         AND evaluation.source_event_content_hash=event.content_hash
                     )
                   ORDER BY event.recorded_at,event.event_id LIMIT %s""",
                (
                    self.owner_id,
                    list(_RELEVANT_TYPES),
                    EVALUATOR_VERSION,
                    max(1, min(limit, 500)),
                ),
            ).fetchall()
        counts = {"evaluated": 0, "enqueued": 0, "ignored": 0, "expired": 0}
        for row in rows:
            event = self.repository.event_by_id(
                owner_id=self.owner_id, event_id=row["event_id"]
            )
            if event is None:
                continue
            candidate, command, not_before = self._candidate_for_event(event, now=now)
            if command is not None and not_before is not None:
                work_item_id = self.store.enqueue_work(
                    work_kind="scheduled",
                    idempotency_key=command.execution_idempotency_key,
                    command=command,
                    not_before=not_before,
                )
                candidate = EvaluatedCandidate(
                    candidate.candidate_kind,
                    candidate.disposition,
                    candidate.reason_code,
                    work_item_id,
                )
            self._record(event, candidate)
            counts["evaluated"] += 1
            counts[candidate.disposition] += 1
        return counts
