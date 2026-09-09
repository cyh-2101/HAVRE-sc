"""Explicit-only, source-bound high-effort chat Goal planning."""

from __future__ import annotations

import json
import re
from contextlib import nullcontext
from datetime import UTC, date, datetime, time, timedelta
import hashlib
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, model_validator

from companion.context import PersonalContextItem
from companion.context.response_plan import _SAY_MORE
from companion.events import EventEnvelope, TextContentPart
from companion.goals.models import GoalPriority, GoalTrack
from companion.goals.service import GoalService
from companion.hashing import content_hash
from companion.ids import uuid7
from companion.persistence.postgres import PostgresRepository
from companion.policy import DataPolicy, PrivacyClass
from mlsys.contracts import GenerationSettings, InferenceMessage, InferenceRequest
from mlsys.contracts.inference import InferenceConstraints
from mlsys.serving.codex_cli import bind_codex_cli_request


CHAT_GOAL_AUTHORIZATION_REF = (
    "product-owner/explicit-chat-goal-planning-2026-09-04"
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PlannedReminder(StrictModel):
    kind: Literal["start_window", "check_in", "encouragement"]
    text: str = Field(min_length=1, max_length=300)
    remind_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def validate_window(self) -> "PlannedReminder":
        if self.remind_at.utcoffset() is None or self.expires_at.utcoffset() is None:
            raise ValueError("planned reminder timestamps must be timezone-aware")
        if self.expires_at <= self.remind_at:
            raise ValueError("planned reminder expiration must follow reminder time")
        return self


class DailyReminderPlan(StrictModel):
    start_date: date
    end_date: date
    local_time: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    varying_daytime: bool = False

    @model_validator(mode="after")
    def bounded(self):
        if not 0 <= (self.end_date-self.start_date).days <= 30:
            raise ValueError("daily reminders must have a bounded period of at most 31 dates")
        if self.varying_daytime == (self.local_time is not None):
            raise ValueError("choose either an exact local time or owner-requested varied daytime")
        return self


class ChatGoalPlan(StrictModel):
    schema_version: Literal[1] = 1
    create_goal: bool
    source_quote: str | None = Field(default=None, max_length=500)
    track: GoalTrack | None = None
    title: str | None = Field(default=None, max_length=160)
    why: str | None = Field(default=None, max_length=700)
    priority: GoalPriority | None = None
    next_action: str | None = Field(default=None, max_length=500)
    review_at: datetime | None = None
    reminders: tuple[PlannedReminder, ...] = Field(default=(), max_length=3)
    daily_reminder: DailyReminderPlan | None = None

    @model_validator(mode="after")
    def validate_action(self) -> "ChatGoalPlan":
        required = (self.source_quote, self.track, self.title, self.why, self.priority)
        if self.create_goal and any(value is None for value in required):
            raise ValueError("created Goal requires quote, track, title, why, and priority")
        if not self.create_goal and any(value is not None for value in required):
            raise ValueError("no-action plan must omit Goal fields")
        if not self.create_goal and (
            self.next_action is not None or self.review_at is not None or self.reminders or self.daily_reminder
        ):
            raise ValueError("no-action plan cannot schedule Goal work")
        if self.daily_reminder is not None and self.reminders:
            raise ValueError("do not duplicate daily and one-off reminders")
        return self

    @classmethod
    def provider_schema(cls) -> dict:
        """Strict structured output uses nullable required fields, not omission."""
        schema = cls.model_json_schema()
        def strict(value):
            if isinstance(value, dict):
                if value.get("type") == "object":
                    value["required"] = list(value.get("properties", {}))
                    value["additionalProperties"] = False
                value.pop("default", None)
                for child in value.values():
                    strict(child)
            elif isinstance(value, list):
                for child in value:
                    strict(child)
        strict(schema)
        return schema

    @classmethod
    def parse_provider_text(cls, value: str) -> "ChatGoalPlan":
        text = value.strip()
        if text.startswith("```") or text.endswith("```"):
            raise ValueError("chat Goal planner returned a markdown fence")
        return cls.model_validate(json.loads(text))


class ExplicitChatGoalPlanner:
    version = "owner-directed-chat-goal-planner-v3-conversation"
    _explicit = re.compile(
        r"(?:记成|记录为|设成|设为|创建|建立|加(?:一个)?|生成)(?:.{0,8})目标"
        r"|我的目标是|帮我规划|给我规划|提醒我|帮我记得"
        r"|(?:我|以后我|从现在开始我)(?:打算|决定|准备).{2,}"
        r"|(?:我|以后我|从现在开始我)(?:想|希望|应该|要)[^。！？\n]*(?:目标|坚持|每周|每天|每月|习惯|计划|开始|做到|成为)"
        r"|\b(?:my goal|i (?:want|intend|plan|have decided) to|remind me|help me plan)\b",
        re.I,
    )

    def __init__(
        self, *, repository: PostgresRepository, owner_id: UUID, provider: Any,
        goal_service: GoalService, proactive_store: Any, owner_timezone: str,
        timeout_ms: int = 120_000,
    ) -> None:
        self.repository = repository
        self.owner_id = owner_id
        self.provider = provider
        self.goal_service = goal_service
        self.proactive_store = proactive_store
        self.owner_timezone = owner_timezone
        self.timeout_ms = timeout_ms

    @classmethod
    def explicitly_requests_action(cls, message: str) -> bool:
        if cls._explicit.search(message) is not None:
            return True
        # A substantial first-person reflection can articulate chosen directions
        # without command syntax or the word "goal". This only opens semantic
        # review; the source-quoted model plan must still choose action/no-action.
        # Short everyday wants/needs should not pay for an extra high-effort call.
        return len(message) >= 80 and re.search(
            r"我[^。！？\n]{0,18}(?:应该|需要|要尝试)", message
        ) is not None

    async def apply(
        self, *, user_event: EventEnvelope, message: str
    ) -> PersonalContextItem | None:
        if user_event.payload.reply_to_event_id is not None or _SAY_MORE.fullmatch(message):
            return None
        history = self._planning_history(user_event=user_event, message=message)
        if not self.explicitly_requests_action(message) and not history:
            return None
        if (
            user_event.data_policy.privacy_class
            not in {PrivacyClass.PUBLIC, PrivacyClass.NORMAL}
            or not user_event.data_policy.cloud_eligible
        ):
            return PersonalContextItem(
                owner_id=self.owner_id,
                section_id=f"chat-goal-private-{user_event.event_id}",
                section_type="owner_response_instruction",
                content_text=(
                    "This private/local message was not sent to the cloud Goal planner; "
                    "no Goal was created. Continue the owner's conversation naturally. "
                    "Only if they expected a saved action, explain that it was not saved. "
                    "Never claim a durable action occurred."
                ),
                priority=99,
                source_refs=(f"event/{user_event.event_id}",),
                data_policy=user_event.data_policy,
            )
        request = self._request(user_event=user_event, message=message, history=history)
        try:
            response = await self.provider.generate(request)
            plan = ChatGoalPlan.parse_provider_text(response.output_parts[0].text)
            owner_texts = [message, *("\n".join(p.text for p in e.payload.content_parts)
                for e in history if e.event_type.value == "USER_MESSAGE")]
            if plan.source_quote is not None and not any(plan.source_quote in text for text in owner_texts):
                raise ValueError("chat Goal source_quote was not copied from the owner")
            now = datetime.now(UTC)
            if plan.review_at is not None and (
                plan.review_at <= now or plan.review_at > now + timedelta(days=366)
            ):
                raise ValueError("chat Goal review_at is outside the allowed horizon")
            if any(
                item.remind_at <= now
                or item.remind_at > now + timedelta(days=366)
                for item in plan.reminders
            ):
                raise ValueError("chat Goal reminder is outside the allowed horizon")
            reminders = self._scheduled_reminders(plan, user_event=user_event, owner_texts=owner_texts)
            run_id, goal = self._commit_plan(
                user_event=user_event, message=message, request=request,
                response=response, plan=plan, reminders=reminders,
            )
            if not plan.create_goal:
                return PersonalContextItem(
                    owner_id=self.owner_id,
                    section_id=f"chat-goal-no-action-{run_id}",
                    section_type="owner_response_instruction",
                    content_text=(
                        "No durable action was taken. Do not say an action is saved or promise "
                        "future reminders. If an explicit request is incomplete, ask the one missing "
                        "detail, using the ongoing conversation. Otherwise continue naturally."
                    ),
                    priority=99,
                    source_refs=(*(f"event/{e.event_id}" for e in history), f"event/{user_event.event_id}", f"goal-plan/{run_id}"),
                    data_policy=user_event.data_policy,
                )
            assert goal is not None
            reminder_count = len(reminders)
            return PersonalContextItem(
                owner_id=self.owner_id,
                section_id=f"chat-goal-receipt-{run_id}",
                section_type="owner_response_instruction",
                content_text=(
                    "Durable action receipt: an explicit owner request created Goal "
                    f"'{goal.title}' and {reminder_count} reminder(s). "
                    + (f"First {reminders[0].remind_at.astimezone(ZoneInfo(self.owner_timezone)).isoformat()}, last {reminders[-1].remind_at.astimezone(ZoneInfo(self.owner_timezone)).isoformat()}; " if reminders else "")
                    + ("once per day at varied daytime hours (10:00-21:00 owner local time). " if plan.daily_reminder and plan.daily_reminder.varying_daytime else "")
                    + "You may naturally "
                    "confirm exactly that, but do not claim any additional Memory, plan, "
                    "or reminder was saved."
                ),
                priority=99,
                source_refs=(
                    *(f"event/{e.event_id}" for e in history),
                    f"event/{user_event.event_id}", f"goal/{goal.goal_id}@1",
                    f"goal-plan/{run_id}",
                ),
                data_policy=goal.data_policy,
            )
        except Exception as error:
            self._persist_failure(user_event=user_event, message=message, error=error)
            return PersonalContextItem(
                owner_id=self.owner_id,
                section_id=f"chat-goal-failed-{user_event.event_id}",
                section_type="owner_response_instruction",
                content_text=(
                    "The owner explicitly asked for a Goal or reminder, but the durable "
                    "write failed. Apologize briefly and do not claim anything was saved."
                ),
                priority=99,
                source_refs=(f"event/{user_event.event_id}",),
                data_policy=user_event.data_policy,
            )

    _time_followup = re.compile(r".{0,65}(?:每天|每日|一个月|一周|\d+天|\d{1,2}(?:点|:\d{2})|随机|随便|都行|daily|random).{0,30}", re.I)

    def _planning_history(self, *, user_event, message):
        if user_event.data_policy.privacy_class not in {PrivacyClass.PUBLIC,PrivacyClass.NORMAL} or not user_event.data_policy.cloud_eligible:
            return ()
        followup = self._time_followup.fullmatch(message)
        if not self.explicitly_requests_action(message) and followup is None:
            return ()
        with self.repository.pool.connection() as connection:
            rows = connection.execute(
                "SELECT event.* FROM havre.events event WHERE owner_id=%s AND session_id=%s "
                "AND recorded_at<%s AND recorded_at>=%s-interval '24 hours' "
                "AND event_type IN ('USER_MESSAGE','ASSISTANT_MESSAGE') ORDER BY recorded_at DESC,event_id DESC LIMIT 8",
                (self.owner_id,user_event.session_id,user_event.recorded_at,user_event.recorded_at),
            ).fetchall()
            # A privacy boundary or erasure breaks continuation; do not silently bridge across it.
            usable=[]
            for row in rows:
                if row["privacy_class"] not in {"NORMAL","PUBLIC"} or not row["cloud_eligible"]:
                    break
                revoked=connection.execute("SELECT 1 FROM havre.offline_source_revocations WHERE owner_id=%s AND source_event_id=%s",(self.owner_id,row["event_id"])).fetchone()
                if revoked: break
                if row["event_type"] == "USER_MESSAGE":
                    text = "\n".join(p.get("text", "") for p in row["payload"].get("content_parts", []))
                    if not self.explicitly_requests_action(text) and not self._time_followup.fullmatch(text):
                        break
                usable.append(row)
            user_rows=[row for row in usable if row["event_type"]=="USER_MESSAGE"]
            if not user_rows: return ()
            roots=[row for row in user_rows if self.explicitly_requests_action("\n".join(p.get("text","") for p in row["payload"].get("content_parts",[])))]
            if not roots: return ()
            # Do not repeat a prior committed request on a bare time/ack follow-up.
            if not self.explicitly_requests_action(message) and connection.execute(
                "SELECT 1 FROM havre.owner_chat_goal_actions WHERE owner_id=%s AND source_event_id=ANY(%s::uuid[])",
                (self.owner_id,[row["event_id"] for row in user_rows]),
            ).fetchone(): return ()
        events = tuple(self.repository.event_by_id(owner_id=self.owner_id,event_id=row["event_id"])
            for row in reversed(usable))
        return events if all(event is not None for event in events) else ()

    def _scheduled_reminders(self, plan, *, user_event, owner_texts):
        schedule=plan.daily_reminder
        if schedule is None: return plan.reminders
        owner_text="\n".join(owner_texts)
        if not re.search(r"每天|每日|daily|every day",owner_text,re.I):
            raise ValueError("daily schedule lacks owner intent")
        if schedule.varying_daytime and not re.search(r"随机|随便|都行|random|any time",owner_text,re.I):
            raise ValueError("varied times lack owner intent")
        zone=ZoneInfo(self.owner_timezone); now=datetime.now(UTC)
        if schedule.start_date < now.astimezone(zone).date() or schedule.end_date > now.astimezone(zone).date()+timedelta(days=366):
            raise ValueError("daily schedule is outside the allowed horizon")
        result=[]
        for offset in range((schedule.end_date-schedule.start_date).days+1):
            day=schedule.start_date+timedelta(days=offset)
            if schedule.varying_daytime:
                seed=f"{self.owner_id}:{user_event.event_id}:{day}".encode()
                minute=600+int.from_bytes(hashlib.sha256(seed).digest()[:4],"big")%661
                at=time(minute//60,minute%60)
            else:
                at=time.fromisoformat(schedule.local_time)
            instant=datetime.combine(day,at,tzinfo=zone)
            if instant<=now: continue
            result.append(PlannedReminder(kind="check_in",text=f"{plan.title}，今天想推进哪一点？",
                remind_at=instant,expires_at=instant+timedelta(hours=2)))
        if not result: raise ValueError("daily schedule has no future reminders")
        return tuple(result)

    def _request(
        self, *, user_event: EventEnvelope, message: str, history=()
    ) -> InferenceRequest:
        zone = ZoneInfo(self.owner_timezone)
        now = datetime.now(zone)
        policy = DataPolicy(
            privacy_class=user_event.data_policy.privacy_class,
            memory_eligible=False, training_eligible=False, cloud_eligible=True,
            decision_source="owner_explicit",
            authorization_ref=CHAT_GOAL_AUTHORIZATION_REF,
        )
        instructions = (
            "Return one strict JSON object for an explicit owner Goal/reminder request. "
            "Keys exactly: schema_version=1, create_goal, source_quote, track, title, "
            "why, priority, next_action, review_at, reminders, daily_reminder. Identify owner-directed "
            "intent semantically, not by requiring command words. A clear chosen personal "
            "direction or commitment can be a Goal without saying 'create a goal'. Ordinary "
            "conversation, hypothetical wishes, self-criticism, other people's objectives "
            "and 'don't save this' are no_action. Do not turn transient fatigue or sadness "
            "into self-improvement tasks. source_quote must be exact evidence of the "
            "owner's chosen objective, not just a topic. track is reality or inner_life; "
            "priority low/normal/high. ISO timestamps must include an offset. reminders "
            "has at most 3 objects with kind start_window/check_in/encouragement, text, "
            "remind_at, expires_at. Use create_goal=false and null Goal fields when an "
            "objective is ambiguous. An untimed Goal can have null review_at and no "
            "reminders; never invent a schedule or deadline. Reminders require the owner's "
            "request and a resolvable time. Do not create Memory or infer "
            "completion. Keep title human-readable and free of technical metadata. "
            "Read the bounded conversation to resolve follow-up answers such as a duration or time. "
            "Only OWNER messages establish intent; assistant promises are not saved actions. "
            "Do not create duplicate actions already confirmed by a receipt. source_quote must be "
            "copied from an owner message in this request. For an explicitly requested daily schedule "
            "with a resolved objective and end date (at most 31 dates), set daily_reminder to "
            "{start_date,end_date,local_time,varying_daytime} and reminders to []. local_time is HH:MM. "
            "Only if the owner asks for random/variable times use varying_daytime=true and local_time=null; "
            "Core chooses a stable varied time between 10:00 and 21:00. Otherwise daily_reminder=null. "
            "Missing objective or unresolved time requires no_action, never an invented reminder."
        )
        request = InferenceRequest(
            request_id=uuid7(), trace_id=user_event.trace_id,
            purpose="owner_chat_goal_plan", context_pack_id=uuid7(),
            messages=(
                InferenceMessage(
                    role="system", content_parts=(TextContentPart(text=instructions),),
                    source_refs=(f"authorization/{CHAT_GOAL_AUTHORIZATION_REF}",),
                ),
                InferenceMessage(
                    role="user",
                    content_parts=(TextContentPart(text=json.dumps({
                        "owner_local_time": now.isoformat(timespec="seconds"),
                        "owner_timezone": self.owner_timezone,
                        "message": message,
                        "conversation": [{"event_id":str(e.event_id),"role":("user" if e.event_type.value=="USER_MESSAGE" else "assistant"),
                            "content":"\n".join(p.text for p in e.payload.content_parts)} for e in history],
                    }, ensure_ascii=False, separators=(",", ":"))),),
                    source_refs=tuple(f"event/{e.event_id}" for e in (*history,user_event)),
                ),
            ),
            generation=GenerationSettings(
                max_output_tokens=1_500, temperature=0.1, top_p=0.95
            ),
            constraints=InferenceConstraints(
                stream=False, timeout_ms=self.timeout_ms,
                effective_data_policy=policy,
                allowed_execution_environments=("cloud",),
            ),
            metadata={
                "chat_goal_authorization_ref": CHAT_GOAL_AUTHORIZATION_REF,
                "chat_goal_source_manifest": json.dumps([{"event_id":str(e.event_id),"content_hash":e.content_hash} for e in (*history,user_event)],separators=(",",":")),
                "source_event_id": str(user_event.event_id),
                "explicit_intent_hash": content_hash({"message": message}),
                "codex_output_schema": json.dumps(ChatGoalPlan.provider_schema(), separators=(",", ":")),
            },
        )
        return bind_codex_cli_request(request, reasoning_effort="high")

    def _commit_plan(self, *, user_event, message, request, response, plan, reminders=None):
        # The model call has finished before taking locks. A receipt, Goal and all
        # queue entries either commit together or roll back together.
        with self.repository.pool.connection() as connection, connection.transaction():
            connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (f"offline-owner:{self.owner_id}",))
            for source in sorted(json.loads(request.metadata.get("chat_goal_source_manifest","[]")),key=lambda x:x["event_id"]):
                connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",(f"offline-source:{self.owner_id}:{source['event_id']}",))
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (f"proactive-owner:{self.owner_id}",),
            )
            run_id = self._persist_run(
                user_event=user_event, message=message, request=request,
                response=response, plan=plan, _connection=connection,
            )
            if not plan.create_goal:
                return run_id, None
            goal = self.repository.create_goal(
                owner_id=self.owner_id, track=plan.track, title=plan.title.strip(),
                why=plan.why.strip(), source_event_id=user_event.event_id,
                priority=plan.priority, next_action=plan.next_action,
                review_at=plan.review_at, _connection=connection,
            )
            connection.execute(
                """INSERT INTO havre.owner_chat_goal_actions
                   (owner_id,plan_run_id,source_event_id,goal_id,goal_revision)
                   VALUES (%s,%s,%s,%s,1)""",
                (self.owner_id, run_id, user_event.event_id, goal.goal_id),
            )
            for index, reminder in enumerate(plan.reminders if reminders is None else reminders):
                self.proactive_store.enqueue_goal_reminder(
                    goal_id=goal.goal_id, reminder_kind=reminder.kind,
                    reminder_text=reminder.text, remind_at=reminder.remind_at,
                    expires_at=reminder.expires_at,
                    idempotency_key=f"chat-goal:{run_id}:{index}", _connection=connection,
                )
            return run_id, goal

    def _persist_run(
        self, *, user_event: EventEnvelope, message: str,
        request: InferenceRequest, response: Any, plan: ChatGoalPlan,
        _connection=None,
    ) -> UUID:
        run_id = uuid7()
        with (nullcontext(_connection) if _connection is not None else self.repository.pool.connection()) as connection, connection.transaction():
            connection.execute(
                """INSERT INTO havre.owner_chat_goal_plan_runs
                   (plan_run_id,owner_id,source_event_id,source_event_content_hash,
                    explicit_intent_hash,status,inference_request_id,
                    request_binding_hash,provider_id,model_version_id,
                    provider_adapter_version_id,serving_config_version,
                    reasoning_effort,result,response_content_hash,authorization_ref,source_manifest)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'high',%s,%s,%s,%s)""",
                (
                    run_id, self.owner_id, user_event.event_id,
                    user_event.content_hash, content_hash({"message": message}),
                    "completed" if plan.create_goal else "no_action",
                    request.inference_request_id,
                    request.metadata["cloud_request_binding_hash"],
                    response.provider.provider_id,
                    response.versions.model_version_id,
                    response.versions.provider_adapter_version_id,
                    response.versions.serving_config_version,
                    Jsonb(plan.model_dump(mode="json")),
                    content_hash(response.output_parts[0].text),
                    CHAT_GOAL_AUTHORIZATION_REF,
                    Jsonb(json.loads(request.metadata.get("chat_goal_source_manifest","[]"))),
                ),
            )
            for source in json.loads(request.metadata.get("chat_goal_source_manifest","[]")):
                connection.execute("INSERT INTO havre.owner_chat_goal_plan_sources(owner_id,plan_run_id,event_id,event_content_hash) VALUES (%s,%s,%s,%s)",
                    (self.owner_id,run_id,source["event_id"],source["content_hash"]))
        return run_id

    def _persist_failure(
        self, *, user_event: EventEnvelope, message: str, error: Exception
    ) -> None:
        with self.repository.pool.connection() as connection, connection.transaction():
            connection.execute(
                """INSERT INTO havre.owner_chat_goal_plan_runs
                   (plan_run_id,owner_id,source_event_id,source_event_content_hash,
                    explicit_intent_hash,status,error_code,authorization_ref)
                   VALUES (%s,%s,%s,%s,%s,'failed',%s,%s)
                   ON CONFLICT (owner_id,source_event_id) DO NOTHING""",
                (
                    uuid7(), self.owner_id, user_event.event_id,
                    user_event.content_hash, content_hash({"message": message}),
                    type(error).__name__[:200], CHAT_GOAL_AUTHORIZATION_REF,
                ),
            )


__all__ = ["CHAT_GOAL_AUTHORIZATION_REF", "ChatGoalPlan", "ExplicitChatGoalPlanner"]


def committed_action_effects(repository, *, owner_id, event_id):
    with repository.pool.connection() as c:
        actions=c.execute("SELECT action.goal_id,action.plan_run_id FROM havre.owner_chat_goal_actions action "
            "JOIN havre.owner_chat_goal_plan_runs run ON run.owner_id=action.owner_id AND run.plan_run_id=action.plan_run_id "
            "WHERE action.owner_id=%s AND action.source_event_id=%s AND run.status='completed'",(owner_id,event_id)).fetchall()
        if not actions: return ()
        effects=["goal_created"]
        for action in actions:
            prefix=f"chat-goal:{action['plan_run_id']}:%"
            if c.execute("SELECT 1 FROM havre.proactive_work_items WHERE owner_id=%s AND idempotency_key LIKE %s "
                "AND status NOT IN ('cancelled','failed') LIMIT 1",(owner_id,prefix)).fetchone():
                effects.append("reminders_scheduled")
        return tuple(sorted(set(effects)))
