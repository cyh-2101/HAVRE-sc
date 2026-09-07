"""Import an owner-reviewed course schedule into Goals and Proactive Core.

The source document remains owner-local. A private, gitignored plan supplies
the reviewed facts and exact reminder times; this script verifies the source
hash, creates one durable Goal per commitment, and schedules source-guarded
reminders through the owner-only API.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


COMMITMENT_AUTHORIZATION_REF = (
    "product-owner-decision:2026-09-03:course-commitment-field-projection-v1"
)
SOURCE_INTERACTION_IDEMPOTENCY_VERSION = "v4"


def _course_name(title: str) -> str:
    match = re.match(
        r"^(ECE\s+\d+|CS\s+\d+(?:\s*/\s*ECE\s+\d+)?|STAT\s+\d+)",
        title.strip(),
        flags=re.IGNORECASE,
    )
    return match.group(1).upper() if match else title.strip().split(" ", 1)[0]


def _natural_reminder_time(
    *, entry_id: str, due: datetime, offset_days: int
) -> datetime:
    day = due.date() - timedelta(days=offset_days)
    seed = f"{entry_id}|{due.isoformat()}|{offset_days}".encode("utf-8")
    jitter_minutes = int.from_bytes(hashlib.sha256(seed).digest()[:2], "big") % 91 - 45
    return datetime.combine(day, datetime.min.time(), tzinfo=due.tzinfo).replace(
        hour=18
    ) + timedelta(minutes=jitter_minutes)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _request(
    *,
    base_url: str,
    token: str,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> Any:
    headers = {"Authorization": f"Bearer {token}"}
    payload = None
    if body is not None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=payload,
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=300) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"HAVRE API {method} {path} failed with HTTP {error.code}: {detail}"
        ) from error


def _generated_text(title: str, policy: str, offset_days: int) -> tuple[str, str]:
    if policy == "exam":
        if offset_days == 7:
            return "start_window", f"离「{title}」还有一周。先确认范围和最薄弱的部分，今天从最小的一块开始。"
        if offset_days == 3:
            return "check_in", f"「{title}」还有三天。看一下复习进度，先补最不稳的地方。"
        return "encouragement", f"明天就是「{title}」。你已经走到这里了。今晚只做关键复习、早点休息，我相信你能稳稳去考。"
    if policy == "large":
        if offset_days == 7:
            return "start_window", f"离「{title}」还有一周。先看要求、拆第一步，今天不用做完，但要真正开始。"
        if offset_days == 3:
            return "check_in", f"「{title}」还有三天。看一下进度和卡点，需要的话现在调整。"
        return "encouragement", f"明天就是「{title}」。今晚收一收尾，别再无限加码；你能稳稳把它做完。"
    if offset_days == 3:
        return "start_window", f"「{title}」还有三天。现在看一眼剩余量，别让它偷偷变成最后一晚。"
    return "check_in", f"「{title}」明天到期。今晚把能确定的部分收好，别把最后一晚留给意外。"


def _catchup_text(title: str, policy: str) -> tuple[str, str]:
    if policy == "exam":
        return (
            "start_window",
            f"「{title}」已经进入考前提醒窗口。先确认范围和最薄弱的部分，今天从最小的一块开始。",
        )
    if policy == "large":
        return (
            "start_window",
            f"「{title}」已经进入提前准备窗口。先看要求、拆第一步，今天不用做完，但要真正开始。",
        )
    return (
        "start_window",
        f"「{title}」已经进入提醒窗口。现在看一眼剩余量，别让它偷偷变成最后一晚。",
    )


def _expand_reminders(plan: dict[str, Any], entry: dict[str, Any]) -> list[dict[str, str]]:
    explicit = entry.get("reminders")
    if explicit is not None:
        return list(explicit)
    policy = entry.get("reminder_policy", "none")
    if policy == "none":
        return []
    if policy not in {"regular", "large", "exam"}:
        raise ValueError(f"{entry['entry_id']} has an unsupported reminder_policy")
    due_values = entry.get("due_times")
    if not isinstance(due_values, list) or not due_values:
        raise ValueError(f"{entry['entry_id']} requires due_times")
    timezone = ZoneInfo(plan["timezone"])
    activation = datetime.fromisoformat(plan["activation_at"]).astimezone(timezone)
    offsets = (7, 3, 1) if policy in {"large", "exam"} else (3, 1)
    reminders: list[dict[str, str]] = []
    for due_value in due_values:
        due = datetime.fromisoformat(due_value).astimezone(timezone)
        generated: list[tuple[int, datetime]] = []
        for offset in offsets:
            day = due.date() - timedelta(days=offset)
            remind_at = _natural_reminder_time(
                entry_id=entry["entry_id"],due=due,offset_days=offset
            )
            generated.append((offset, remind_at))
        catchup_added = generated[0][1] < activation < due
        if catchup_added:
            catchup_kind, catchup_text = _catchup_text(entry["title"], policy)
            reminders.append({
                "kind": catchup_kind,
                "remind_at": activation.isoformat(),
                "expires_at": min(
                    activation.replace(hour=23, minute=0), due
                ).isoformat(),
                "text": catchup_text,
            })
        for offset, remind_at in generated:
            if (
                remind_at <= activation
                or (catchup_added and remind_at.date() == activation.date())
            ):
                continue
            kind, text = _generated_text(entry["title"], policy, offset)
            reminders.append({
                "kind": kind,
                "remind_at": remind_at.isoformat(),
                "expires_at": remind_at.replace(hour=23, minute=59).isoformat(),
                "text": text,
            })
    return reminders


def _validate_plan(plan: dict[str, Any], *, source_hash: str) -> list[dict[str, Any]]:
    if plan.get("schema_version") != 1:
        raise ValueError("course schedule plan schema_version must be 1")
    if plan.get("source_sha256") != source_hash:
        raise ValueError("course schedule plan does not match the source file hash")
    if plan.get("timezone") != "America/Chicago":
        raise ValueError("course schedule plan must use America/Chicago")
    decisions = plan.get("owner_decisions")
    if decisions != {"ece210_scope": "full_course", "ece494_credits": 3}:
        raise ValueError("course schedule plan lacks the exact owner course decisions")
    activation = datetime.fromisoformat(plan.get("activation_at", ""))
    if activation.utcoffset() is None:
        raise ValueError("course schedule plan activation_at must be timezone-aware")
    entries = plan.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError("course schedule plan must contain entries")
    seen: set[str] = set()
    for entry in entries:
        entry_id = entry.get("entry_id")
        if not isinstance(entry_id, str) or not entry_id or entry_id in seen:
            raise ValueError("every course entry needs a unique entry_id")
        seen.add(entry_id)
        if not isinstance(entry.get("title"), str) or not entry["title"].strip():
            raise ValueError(f"{entry_id} has no title")
        if not isinstance(entry.get("next_action"), str) or not entry["next_action"].strip():
            raise ValueError(f"{entry_id} has no next_action")
        reminders = _expand_reminders(plan, entry)
        entry["reminders"] = reminders
        for reminder in reminders:
            if reminder.get("kind") not in {
                "start_window",
                "check_in",
                "encouragement",
            }:
                raise ValueError(f"{entry_id} has an unsupported reminder kind")
            remind_at = datetime.fromisoformat(reminder["remind_at"])
            expires_at = datetime.fromisoformat(reminder["expires_at"])
            if remind_at.utcoffset() is None or expires_at.utcoffset() is None:
                raise ValueError(f"{entry_id} reminder times must be timezone-aware")
            if expires_at <= remind_at:
                raise ValueError(f"{entry_id} reminder expiration is invalid")
            local_time = remind_at.astimezone(ZoneInfo(plan["timezone"])).time()
            if not (datetime.min.time().replace(hour=10) <= local_time <=
                    datetime.min.time().replace(hour=21,minute=30)):
                raise ValueError(f"{entry_id} reminder is outside the natural window")
            text = reminder.get("text")
            if not isinstance(text, str) or not 1 <= len(text.strip()) <= 500:
                raise ValueError(f"{entry_id} reminder text is invalid")
    return entries


def _source_message(
    plan: dict[str, Any],
    entries: list[dict[str, Any]],
    *,
    batch_number: int = 1,
    batch_count: int = 1,
) -> str:
    lines = [
        "这是 Product Owner 明确授权的 owner-local 课程日程导入记录。",
        f"学期：{plan['term']}；时区：{plan['timezone']}；来源快照 sha256:{plan['source_sha256']}。",
        f"来源批次：{batch_number}/{batch_count}。各批次共同构成同一份快照。",
        "下列事项包含确定、暂定、条件适用和 TBA 状态；不要把暂定或 TBA 说成已确定。",
        "这些事实用于相关对话、Goal 和受治理的主动触达；不是课程作业内容，也不授权 AI 完成课程任务。",
    ]
    for entry in entries:
        qualifiers = []
        if entry.get("tentative"):
            qualifiers.append("暂定")
        if entry.get("conditional"):
            qualifiers.append("3-credit enrollment makes this 4-credit item not applicable")
        if entry.get("tba"):
            qualifiers.append("TBA")
        suffix = f"（{'、'.join(qualifiers)}）" if qualifiers else ""
        lines.append(f"- [{entry['entry_id']}] {entry['title']}{suffix}；{entry['next_action']}")
    return "\n".join(lines)


def import_schedule(args: argparse.Namespace) -> dict[str, Any]:
    source_path = Path(args.source).resolve(strict=True)
    plan_path = Path(args.plan).resolve(strict=True)
    token_path = Path(args.token_file).resolve(strict=True)
    source_hash = _sha256(source_path)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    entries = _validate_plan(plan, source_hash=source_hash)
    if not args.apply:
        return {
            "status": "dry_run",
            "source_sha256": source_hash,
            "entries": len(entries),
            "reminders": sum(len(entry.get("reminders", [])) for entry in entries),
        }

    token = token_path.read_text(encoding="utf-8").strip()
    if not token:
        raise ValueError("owner API token file is empty")
    _request(
        base_url=args.base_url,
        token=token,
        method="POST",
        path="/v1/commitments/course-field-authorization",
        body={
            "source_sha256": source_hash,
            "authorization_ref": COMMITMENT_AUTHORIZATION_REF,
        },
    )
    goals = _request(
        base_url=args.base_url,
        token=token,
        method="GET",
        path="/v1/goals?include_inactive=true",
    )
    if not isinstance(goals, list):
        raise RuntimeError("HAVRE goals endpoint returned an unexpected payload")

    marker_prefix = f"owner_course_schedule:{plan['term']}:"
    exact_prefix = f"{marker_prefix}{source_hash}:"
    existing_by_entry: dict[str, dict[str, Any]] = {}
    abandoned = 0
    for goal in goals:
        why = str(goal.get("why") or "")
        if not why.startswith(marker_prefix):
            continue
        if why.startswith(exact_prefix):
            entry_id = why.removeprefix(exact_prefix).split(";", 1)[0]
            current = existing_by_entry.get(entry_id)
            if current is None or int(goal.get("revision", 0)) > int(
                current.get("revision", 0)
            ):
                existing_by_entry[entry_id] = goal
            continue
        if goal.get("status") in {"active", "paused"}:
            _request(
                base_url=args.base_url,
                token=token,
                method="POST",
                path=f"/v1/goals/{goal['goal_id']}/update",
                body={
                    "expected_revision": goal["revision"],
                    "reason": "Superseded by a newly owner-authorized course schedule snapshot",
                    "status": "abandoned",
                },
            )
            abandoned += 1

    batch_size = 10
    batches = [
        entries[index : index + batch_size]
        for index in range(0, len(entries), batch_size)
    ]
    source_event_by_entry: dict[str, str] = {}
    source_events: list[str] = []
    source_routes: list[dict[str, str | None]] = []
    for batch_index, batch in enumerate(batches, start=1):
        missing_entries = [
            entry for entry in batch if entry["entry_id"] not in existing_by_entry
        ]
        if not missing_entries:
            continue
        source = _request(
            base_url=args.base_url,
            token=token,
            method="POST",
            path="/v1/interactions",
            body={
                "message": _source_message(
                    plan,
                    batch,
                    batch_number=batch_index,
                    batch_count=len(batches),
                ),
                "privacy_class": "LOCAL_ONLY",
                "memory_eligible": True,
                "language": "zh-CN",
            },
            idempotency_key=(
                "course-source-"
                f"{SOURCE_INTERACTION_IDEMPOTENCY_VERSION}-{source_hash}-"
                f"batch-{batch_index}"
            ),
        )
        source_event_id = source["user_event_id"]
        source_events.append(source_event_id)
        source_routes.append({
            "provider_id": source.get("provider_id"),
            "model_version_id": source.get("model_version_id"),
        })
        for entry in missing_entries:
            source_event_by_entry[entry["entry_id"]] = source_event_id

    now = datetime.now(UTC)
    created = 0
    reused = 0
    scheduled = 0
    expired = 0
    past_not_replayed = 0
    for entry in entries:
        entry_id = entry["entry_id"]
        goal = existing_by_entry.get(entry_id)
        goal_created = goal is None
        if goal is None:
            qualifiers = []
            if entry.get("tentative"):
                qualifiers.append("tentative")
            if entry.get("conditional"):
                qualifiers.append("conditional")
            if entry.get("tba"):
                qualifiers.append("tba")
            marker = f"{exact_prefix}{entry_id};status={','.join(qualifiers) or 'confirmed'}"
            goal = _request(
                base_url=args.base_url,
                token=token,
                method="POST",
                path="/v1/goals",
                body={
                    "track": "reality",
                    "title": entry["title"],
                    "why": marker,
                    "source_event_id": source_event_by_entry[entry_id],
                    "priority": entry.get("priority", "normal"),
                    "next_action": entry["next_action"],
                },
            )
            created += 1
        else:
            reused += 1
        not_applicable = bool(
            entry.get("conditional") and plan["owner_decisions"]["ece494_credits"] != 4
        )
        if not_applicable and goal.get("status") in {"active", "paused"}:
            goal = _request(
                base_url=args.base_url,
                token=token,
                method="POST",
                path=f"/v1/goals/{goal['goal_id']}/update",
                body={
                    "expected_revision": goal["revision"],
                    "reason": (
                        "Owner confirmed ECE 494 is 3-credit; the 4-credit-only "
                        "commitment is not applicable"
                    ),
                    "status": "abandoned",
                },
            )
        due_values = entry.get("due_times") or []
        deadline = due_values[0] if due_values else None
        _request(
            base_url=args.base_url,
            token=token,
            method="POST",
            path=f"/v1/goals/{goal['goal_id']}/commitment-projection",
            body={
                "source_sha256": source_hash,
                "entry_id": entry_id,
                "course_name": _course_name(entry["title"]),
                "task_name": entry["title"],
                "deadline_at": deadline,
            },
        )
        if not_applicable:
            continue
        if goal.get("status") != "active":
            continue
        for index, reminder in enumerate(entry.get("reminders", []), start=1):
            remind_at = datetime.fromisoformat(reminder["remind_at"]).astimezone(UTC)
            expires_at = datetime.fromisoformat(reminder["expires_at"]).astimezone(UTC)
            if expires_at <= now:
                expired += 1
                continue
            if not goal_created and remind_at <= now:
                past_not_replayed += 1
                continue
            _request(
                base_url=args.base_url,
                token=token,
                method="POST",
                path=f"/v1/goals/{goal['goal_id']}/reminders",
                body={
                    "reminder_kind": reminder["kind"],
                    "reminder_text": reminder["text"],
                    "remind_at": reminder["remind_at"],
                    "expires_at": reminder["expires_at"],
                    "supersede_existing_slot": True,
                },
                idempotency_key=(
                    f"course-v2-{source_hash[:16]}-{entry_id}-{index}-"
                    f"r{goal['revision']}"
                ),
            )
            scheduled += 1
    supersession = _request(
        base_url=args.base_url,
        token=token,
        method="POST",
        path="/v1/commitments/course-reminders/supersede-legacy",
        body={
            "source_sha256": source_hash,
            "replacement_generation": "v2",
        },
    )
    return {
        "status": "applied",
        "source_sha256": source_hash,
        "source_event_ids": source_events,
        "entries": len(entries),
        "goals_created": created,
        "goals_reused": reused,
        "old_goals_abandoned": abandoned,
        "reminders_scheduled_or_replayed": scheduled,
        "expired_reminders_skipped": expired,
        "past_reminders_not_replayed": past_not_replayed,
        "legacy_reminders_cancelled": supersession[
            "legacy_reminders_cancelled"
        ],
        "source_reply_routes": source_routes,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument(
        "--token-file",
        default=".runtime/desktop/secrets/owner-api-token.secret",
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(import_schedule(args), ensure_ascii=False, indent=2))
        return 0
    except Exception as error:  # CLI boundary prints one safe actionable error.
        print(f"course schedule import failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
