"""Source-separated owner-authorized GPT Diary intelligence."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from contextlib import nullcontext
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from companion.evidence import EvidenceRef, EvidenceRelation, EvidenceSourceKind
from companion.events import (
    BeliefLifecyclePayload, EventEnvelope, EventType, MemoryLifecyclePayload,
    TextContentPart,
)
from companion.context.persona import follow_up_persona
from companion.identity import IdentityBundle
from companion.hashing import content_hash
from companion.ids import uuid7
from companion.memory.models import MemoryRevision, MemoryStatus
from companion.persistence.postgres import PostgresRepository
from companion.policy import DataPolicy, PrivacyClass, combine_policies
from companion.user_model.models import (
    BeliefInitialStatus, BeliefRevision, BeliefTransitionType, BeliefType,
)
from mlsys.contracts import GenerationSettings, InferenceMessage, InferenceRequest
from mlsys.contracts.inference import InferenceConstraints
from mlsys.serving.codex_cli import CODEX_CLI_PROVIDER_ID, bind_codex_cli_request


DIARY_INTELLIGENCE_AUTHORIZATION_REF = (
    "product-owner/experience-first-daily-review-2026-09-04"
)
DIARY_INTELLIGENCE_METHOD = "gpt-owner-five-am-diary-v6"
DIARY_INTELLIGENCE_TRANSFORM = "gpt-owner-diary-intelligence-v2"
DIARY_INTELLIGENCE_PROMPT_VERSION = "gpt-owner-review-important-experiences-v2"
DIARY_FOLLOW_UP_PROMPT_VERSION = "gpt-owner-review-canonical-follow-up-v3"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class QualityFlag(StrEnum):
    TOO_VERBOSE = "too_verbose"
    TOO_GENERIC = "too_generic"
    UNNECESSARY_QUESTIONS = "unnecessary_questions"
    WEAK_MEMORY_USE = "weak_memory_use"
    FALSE_FAMILIARITY = "false_familiarity"
    MISSED_EMOTION = "missed_emotion"
    WEAK_ACTIONABILITY = "weak_actionability"
    PRIVACY_BOUNDARY_CONFUSION = "privacy_boundary_confusion"
    REPETITIVE_STRUCTURE = "repetitive_structure"
    OVERCONFIDENT_CLAIM = "overconfident_claim"


QUALITY_GUIDANCE: dict[str, str] = {
    "too_verbose": "Answer more concisely and remove repetition.",
    "too_generic": "Use supplied specifics instead of generic filler.",
    "unnecessary_questions": "Do not ask a follow-up when a grounded answer is possible.",
    "weak_memory_use": "Use admitted relevant Memory naturally; never force a callback.",
    "false_familiarity": "Do not imply shared history without admitted evidence.",
    "missed_emotion": "Acknowledge evident emotion briefly when relevant.",
    "weak_actionability": "Give a concrete next step when action is requested.",
    "privacy_boundary_confusion": "Keep private/local boundaries explicit and fail closed.",
    "repetitive_structure": "Vary structure naturally instead of repeating a template.",
    "overconfident_claim": "Calibrate claims to evidence and state uncertainty plainly.",
}


class DiaryMemoryUpdate(StrictModel):
    source_event_id: UUID
    source_quote: str = Field(min_length=2, max_length=500)
    statement: str = Field(min_length=3, max_length=500)
    confidence: float = Field(default=0.85, ge=0.6, le=0.95)
    importance: float = Field(default=0.65, ge=0, le=1)
    kind: Literal["stable_statement", "experience"] = "stable_statement"


class DiaryBeliefUpdate(StrictModel):
    source_event_id: UUID
    source_quote: str = Field(min_length=2, max_length=500)
    belief_key: str = Field(min_length=3, max_length=120)
    statement: str = Field(min_length=3, max_length=500)
    belief_type: BeliefType
    confidence: float = Field(default=0.8, ge=0.6, le=0.95)


class ImprovementCategory(StrEnum):
    CONVERSATION = "conversation"
    MEMORY = "memory"
    DIARY = "diary"
    PROACTIVE = "proactive"
    GOAL = "goal"
    PRIVACY = "privacy"
    EXPERIENCE = "experience"


class ImprovementSuggestion(StrictModel):
    category: ImprovementCategory
    observation: str = Field(min_length=3, max_length=500)
    recommendation: str = Field(min_length=3, max_length=700)
    reason: str = Field(min_length=3, max_length=500)
    risk: str = Field(min_length=2, max_length=300)
    evidence_event_ids: tuple[UUID, ...] = Field(min_length=1, max_length=5)


class FollowUpReason(StrEnum):
    CONTINUE_TOPIC = "continue_topic"
    CURIOSITY = "curiosity"
    NOTICE_PROGRESS = "notice_progress"


class FollowUpSuggestion(StrictModel):
    source_event_id: UUID
    source_quote: str = Field(min_length=2, max_length=500)
    memory_ref: str | None = Field(default=None, max_length=240)
    reason_kind: FollowUpReason
    message: str = Field(min_length=2, max_length=300)


class DiaryIntelligenceResult(StrictModel):
    schema_version: int = Field(default=2, ge=1, le=2)
    include_diary: bool
    title: str | None = Field(default=None, max_length=12)
    diary_text: str | None = Field(default=None, max_length=2_000)
    memory_updates: tuple[DiaryMemoryUpdate, ...] = Field(default=(), max_length=3)
    user_model_updates: tuple[DiaryBeliefUpdate, ...] = Field(default=(), max_length=3)
    quality_review: tuple[QualityFlag, ...] = Field(default=(), max_length=5)
    improvement_suggestions: tuple[ImprovementSuggestion, ...] = Field(
        default=(), max_length=5
    )
    follow_up_suggestion: FollowUpSuggestion | None = None

    @model_validator(mode="after")
    def validate_diary_shape(self) -> "DiaryIntelligenceResult":
        if self.include_diary:
            if self.title is None or self.diary_text is None:
                raise ValueError("included Diary requires title and diary_text")
            title, body = self.title.strip(), self.diary_text.strip()
            if not title or "\n" in title or re.search(r"[。.!！?？]$", title):
                raise ValueError("Diary title must be a short headline")
            if "我" not in body:
                raise ValueError("Diary body must use the owner's first-person voice")
            object.__setattr__(self, "title", title)
            object.__setattr__(self, "diary_text", body)
        elif self.title is not None or self.diary_text is not None:
            raise ValueError("excluded Diary must omit title and diary_text")
        return self

    @classmethod
    def parse_provider_text(cls, value: str, *, strict_understanding: bool = False) -> "DiaryIntelligenceResult":
        text = value.strip()
        if text.startswith("```") or text.endswith("```"):
            raise ValueError("Diary provider returned a markdown fence")
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("Diary result must be one JSON object")
        sanitized = dict(parsed)

        def validated_items(
            key: str, model: type[StrictModel], *,
            normalize: Any | None = None,
        ) -> list[dict[str, Any]] | Any:
            raw = sanitized.get(key, ())
            if not isinstance(raw, list):
                return raw
            accepted: list[dict[str, Any]] = []
            for item in raw:
                candidate = normalize(item) if normalize is not None else item
                try:
                    accepted.append(
                        model.model_validate(candidate).model_dump(mode="json")
                    )
                except ValidationError:
                    if strict_understanding and key in {"memory_updates", "user_model_updates"}:
                        # Never log the invalid quote itself, and do not mark a
                        # memory-only job complete after silently dropping it.
                        raise ValueError(f"invalid {key} item; retry required") from None
                    # Optional model-authored effects fail closed without
                    # discarding an otherwise valid owner Diary.
                    continue
            return accepted

        belief_aliases = {
            "communication_preference": BeliefType.PREFERENCE.value,
        }

        def normalize_belief(item: Any) -> Any:
            if not isinstance(item, dict):
                return item
            candidate = dict(item)
            belief_type = candidate.get("belief_type")
            if belief_type in belief_aliases:
                candidate["belief_type"] = belief_aliases[belief_type]
            return candidate

        improvement_values = {item.value for item in ImprovementCategory}

        def normalize_improvement(item: Any) -> Any:
            if not isinstance(item, dict):
                return item
            candidate = dict(item)
            if candidate.get("category") not in improvement_values:
                # `experience` is the explicit catch-all presentation bucket;
                # the suggestion still needs supplied Event evidence below.
                candidate["category"] = ImprovementCategory.EXPERIENCE.value
            return candidate

        sanitized["memory_updates"] = validated_items(
            "memory_updates", DiaryMemoryUpdate
        )
        sanitized["user_model_updates"] = validated_items(
            "user_model_updates", DiaryBeliefUpdate, normalize=normalize_belief
        )
        sanitized["improvement_suggestions"] = validated_items(
            "improvement_suggestions",
            ImprovementSuggestion,
            normalize=normalize_improvement,
        )

        quality = sanitized.get("quality_review", ())
        if isinstance(quality, list):
            allowed_quality = {item.value for item in QualityFlag}
            sanitized["quality_review"] = [
                item for item in quality if item in allowed_quality
            ]

        follow_up = sanitized.get("follow_up_suggestion")
        if follow_up is not None:
            reason_aliases = {
                "natural_continuation": FollowUpReason.CONTINUE_TOPIC.value,
                "emotional_continuation": FollowUpReason.CONTINUE_TOPIC.value,
                "recognition_of_progress": FollowUpReason.NOTICE_PROGRESS.value,
            }
            if isinstance(follow_up, dict):
                follow_up = dict(follow_up)
                reason = follow_up.get("reason_kind")
                if reason in reason_aliases:
                    follow_up["reason_kind"] = reason_aliases[reason]
            try:
                sanitized["follow_up_suggestion"] = (
                    FollowUpSuggestion.model_validate(follow_up).model_dump(
                        mode="json"
                    )
                )
            except ValidationError:
                sanitized["follow_up_suggestion"] = None

        return cls.model_validate(sanitized)


class DiaryIntelligenceService:
    _privacy_order = {
        "PUBLIC": 0, "NORMAL": 1, "PRIVATE": 2,
        "HIGHLY_PRIVATE": 3, "LOCAL_ONLY": 4,
    }
    def __init__(
        self, *, repository: PostgresRepository, owner_id: UUID, provider: Any,
        embedding_provider: Any, timeout_ms: int = 120_000,
        review_root: Path | None = None, proactive_store: Any | None = None,
        identity: IdentityBundle | None = None,
    ) -> None:
        self.repository = repository
        self.owner_id = owner_id
        self.provider = provider
        self.embedding_provider = embedding_provider
        self.timeout_ms = timeout_ms
        self.review_root = None if review_root is None else review_root.resolve()
        self.proactive_store = proactive_store
        self.identity = identity
        self._locks: dict[tuple[date, str], asyncio.Lock] = {}

    @staticmethod
    def _payload_text(payload: dict[str, Any] | None) -> str:
        if not payload:
            return ""
        return "\n".join(
            str(part.get("text", ""))
            for part in payload.get("content_parts", ())
            if isinstance(part, dict) and part.get("type", "text") == "text"
        ).strip()

    def _day_events(self, *, local_date: date, timezone_name: str) -> list[dict[str, Any]]:
        with self.repository.pool.connection() as connection:
            rows = connection.execute(
                """SELECT event.*,route.selected_provider_id,route.execution_environment
                   FROM havre.events event
                   JOIN havre.interaction_requests request
                     ON request.owner_id=event.owner_id AND request.request_id=event.request_id
                   LEFT JOIN havre.route_decisions route
                     ON route.owner_id=event.owner_id AND route.request_id=event.request_id
                   WHERE event.owner_id=%s
                     AND event.event_type IN ('USER_MESSAGE','ASSISTANT_MESSAGE')
                     AND COALESCE(event.payload->>'input_origin','owner_text') <> 'continuation_button'
                     AND request.request_kind='interaction' AND request.status='completed'
                     AND ((event.recorded_at AT TIME ZONE %s)-interval '5 hours')::date=%s
                   ORDER BY event.recorded_at,event.event_id""",
                (self.owner_id, timezone_name, local_date),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            cloud = (
                row["selected_provider_id"] == CODEX_CLI_PROVIDER_ID
                and row["execution_environment"] == "cloud"
                and row["privacy_class"] in {"PUBLIC", "NORMAL"}
                and row["cloud_eligible"]
            )
            result.append({
                **dict(row),
                "role": "user" if row["event_type"] == "USER_MESSAGE" else "assistant",
                "content": self._payload_text(row["payload"]),
                "disposition": "cloud_summary" if cloud else "private_reference",
            })
        return result

    def _prior_events(
        self, *, local_date: date, timezone_name: str, limit: int = 12
    ) -> list[dict[str, Any]]:
        with self.repository.pool.connection() as connection:
            rows = connection.execute(
                """SELECT event.*,route.selected_provider_id,
                          route.execution_environment
                   FROM havre.events event
                   JOIN havre.interaction_requests request
                     ON request.owner_id=event.owner_id
                    AND request.request_id=event.request_id
                   JOIN havre.route_decisions route
                     ON route.owner_id=event.owner_id
                    AND route.request_id=event.request_id
                   WHERE event.owner_id=%s
                     AND event.event_type IN ('USER_MESSAGE','ASSISTANT_MESSAGE')
                     AND COALESCE(event.payload->>'input_origin','owner_text') <> 'continuation_button'
                     AND request.request_kind='interaction'
                     AND request.status='completed'
                     AND route.selected_provider_id=%s
                     AND route.execution_environment='cloud'
                     AND event.privacy_class IN ('PUBLIC','NORMAL')
                     AND event.cloud_eligible
                     AND ((event.recorded_at AT TIME ZONE %s)-interval '5 hours')::date<%s
                     AND ((event.recorded_at AT TIME ZONE %s)-interval '5 hours')::date>=%s::date-7
                   ORDER BY event.recorded_at DESC,event.event_id DESC
                   LIMIT %s""",
                (
                    self.owner_id, CODEX_CLI_PROVIDER_ID, timezone_name,
                    local_date, timezone_name, local_date, max(1, min(limit, 24)),
                ),
            ).fetchall()
        return list(reversed([{
            **dict(row),
            "role": "user" if row["event_type"] == "USER_MESSAGE" else "assistant",
            "content": self._payload_text(row["payload"]),
            "disposition": "prior_context",
        } for row in rows if self._payload_text(row["payload"])]))

    def _review_memories(
        self, *, local_date: date, timezone_name: str, limit: int = 8,
        as_of: datetime | None = None,
    ) -> list[dict[str, Any]]:
        instant = as_of or datetime.now(UTC)
        with self.repository.pool.connection() as connection:
            rows = connection.execute(
                """SELECT revision.memory_id,revision.revision,
                          revision.content_text,revision.content_hash,
                          revision.importance,revision.created_at
                   FROM havre.memory_heads head
                   JOIN havre.memory_revisions revision
                     ON revision.owner_id=head.owner_id
                    AND revision.memory_id=head.memory_id
                    AND revision.revision=head.current_revision
                   WHERE head.owner_id=%s AND head.status='active'
                     AND revision.status='active'
                     AND revision.privacy_class IN ('PUBLIC','NORMAL')
                     AND revision.cloud_eligible
                     AND revision.created_at<=%s
                     AND (revision.valid_from IS NULL OR revision.valid_from<=%s)
                     AND (revision.valid_to IS NULL OR revision.valid_to>%s)
                     AND ((revision.created_at AT TIME ZONE %s)-interval '5 hours')::date<=%s
                   ORDER BY revision.importance DESC,revision.created_at DESC,
                            revision.memory_id DESC
                   LIMIT %s""",
                (
                    self.owner_id, instant, instant, instant, timezone_name, local_date,
                    max(1, min(limit, 12)),
                ),
            ).fetchall()
        return [dict(row) for row in rows]

    def _source_set_hash(
        self, events: list[dict[str, Any]], memories: list[dict[str, Any]],
        *, memory_only: bool = False,
    ) -> str:
        persona = follow_up_persona(self.identity) if not memory_only and self.identity is not None else None
        return content_hash({
            "window_version": "owner-local-five-to-five-v1",
            "prompt_version": DIARY_FOLLOW_UP_PROMPT_VERSION if persona else DIARY_INTELLIGENCE_PROMPT_VERSION,
            **({"follow_up_persona": persona.metadata} if persona else {}),
            "events": [{
                "event_id": str(item["event_id"]),
                "content_hash": item["content_hash"],
                "disposition": item["disposition"],
            } for item in events],
            "memories": [{
                "memory_id": str(item["memory_id"]),
                "revision": item["revision"],
                "content_hash": item["content_hash"],
            } for item in memories],
        })

    def _successful_run(self, *, local_date: date, timezone_name: str,
                        source_set_hash: str) -> dict[str, Any] | None:
        with self.repository.pool.connection() as connection:
            return connection.execute(
                """SELECT * FROM havre.daily_diary_intelligence_runs
                   WHERE owner_id=%s AND local_date=%s AND timezone_name=%s
                     AND source_set_hash=%s AND run_kind='daily_review'
                     AND status IN ('completed','private_only')
                   ORDER BY created_at DESC LIMIT 1""",
                (self.owner_id, local_date, timezone_name, source_set_hash),
            ).fetchone()

    def _run_policy(self, events: list[dict[str, Any]]) -> tuple[str, bool]:
        privacy = max(
            (str(item["privacy_class"]) for item in events),
            key=self._privacy_order.__getitem__,
        )
        cloud_eligible = all(
            item["disposition"] == "cloud_summary" and item["cloud_eligible"]
            for item in events
        )
        return privacy, cloud_eligible

    async def sync_day(self, *, local_date: date,
                       timezone_name: str) -> dict[str, Any] | None:
        lock = self._locks.setdefault((local_date, timezone_name), asyncio.Lock())
        async with lock:
            day_events = self._day_events(
                local_date=local_date, timezone_name=timezone_name
            )
            if not day_events:
                return None
            cloud = [item for item in day_events
                     if item["disposition"] == "cloud_summary" and item["content"]]
            prior_events = (
                self._prior_events(local_date=local_date, timezone_name=timezone_name)
                if cloud else []
            )
            review_memories = self._review_memories(
                local_date=local_date, timezone_name=timezone_name
            ) if cloud else []
            events = [*day_events, *prior_events]
            source_hash = self._source_set_hash(events, review_memories)
            successful = self._successful_run(
                local_date=local_date, timezone_name=timezone_name,
                source_set_hash=source_hash,
            )
            if successful is not None:
                self._materialize_review_file(
                    run_id=successful["run_id"], local_date=local_date,
                    source_set_hash=source_hash,
                    result=DiaryIntelligenceResult.model_validate(
                        successful["result"]
                    ),
                )
                replay_result = DiaryIntelligenceResult.model_validate(
                    successful["result"]
                )
                self._enqueue_follow_up(
                    run_id=successful["run_id"],
                    suggestion=replay_result.follow_up_suggestion,
                    review_memories=review_memories,
                    timezone_name=timezone_name,
                )
                return self.diary_day(
                    local_date=local_date, timezone_name=timezone_name
                )
            if not cloud:
                self._persist(
                    local_date=local_date, timezone_name=timezone_name,
                    source_set_hash=source_hash, events=day_events,
                    review_memories=[],
                    result=DiaryIntelligenceResult(include_diary=False),
                    request=None, response=None, status="private_only",
                )
                return self.diary_day(local_date=local_date, timezone_name=timezone_name)
            request = self._request(
                local_date=local_date, timezone_name=timezone_name,
                source_set_hash=source_hash, cloud_events=cloud,
                prior_events=prior_events, review_memories=review_memories,
                private_count=sum(
                    item["disposition"] == "private_reference" for item in day_events
                ),
            )
            try:
                response = await self.provider.generate(request)
                parsed = DiaryIntelligenceResult.parse_provider_text(
                    response.output_parts[0].text
                )
                memories, beliefs = self._validated_updates(parsed, cloud)
                improvements, follow_up = self._validated_review(
                    parsed, cloud_events=cloud, prior_events=prior_events,
                    review_memories=review_memories,
                )
                parsed = parsed.model_copy(update={
                    "memory_updates": memories, "user_model_updates": beliefs,
                    "improvement_suggestions": improvements,
                    "follow_up_suggestion": follow_up,
                })
                run_id = self._persist(
                    local_date=local_date, timezone_name=timezone_name,
                    source_set_hash=source_hash, events=events,
                    review_memories=review_memories, result=parsed,
                    request=request, response=response, status="completed",
                )
                self._materialize_review_file(
                    run_id=run_id, local_date=local_date,
                    source_set_hash=source_hash, result=parsed,
                )
                self._enqueue_follow_up(
                    run_id=run_id, suggestion=follow_up,
                    review_memories=review_memories,
                    timezone_name=timezone_name,
                )
            except Exception as error:
                self._persist_failure(local_date=local_date, timezone_name=timezone_name,
                                      source_set_hash=source_hash, events=events,
                                      error_code=type(error).__name__)
                raise
            return self.diary_day(local_date=local_date, timezone_name=timezone_name)

    def _request(self, *, local_date: date, timezone_name: str,
                 source_set_hash: str, cloud_events: list[dict[str, Any]],
                 private_count: int,
                 prior_events: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
                 review_memories: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
                 memory_only: bool = False,
                 ) -> InferenceRequest:
        privacy = (PrivacyClass.NORMAL if any(
            item["privacy_class"] == "NORMAL" for item in cloud_events
        ) else PrivacyClass.PUBLIC)
        policy = DataPolicy(
            privacy_class=privacy, memory_eligible=False, training_eligible=False,
            cloud_eligible=True, decision_source="owner_explicit",
            authorization_ref=DIARY_INTELLIGENCE_AUTHORIZATION_REF,
        )
        schema = (
            "Return JSON keys exactly: schema_version=2, include_diary, title, "
            "diary_text, memory_updates, user_model_updates, quality_review, "
            "improvement_suggestions, follow_up_suggestion. "
            "Ignore greetings, acknowledgements, status chatter, technical logs, "
            "and transactional流水. Set include_diary=false when nothing personally "
            "meaningful happened. Otherwise title is 4-12 Chinese characters and "
            "diary_text is a coherent factual diary in the owner's first-person 我 "
            "voice, not a chronological transcript. Each update list has at most 3 "
            "important autobiographical experiences or durable facts, preferences, "
            "values, strengths, vulnerabilities, or owner-reported repeated patterns. "
            "A deeply discussed meaningful experience belongs in episodic Memory "
            "even if it happened once and contains no 'I like' or 'remember this'. "
            "Prioritize one concise, faithful episode when a long personal story "
            "would otherwise be lost among small preferences. Preserve who, what, "
            "the owner's account of the impact, and which details remain uncertain; "
            "do not diagnose or infer the other person's intentions. Such an episode "
            "does not by itself justify a User Model personality trait. User Model "
            "updates require an explicit preference/value or supported pattern, "
            "and must stay revisable rather than label the owner permanently. "
            "Never infer durable understanding from a transient "
            "mood, one-off plan, technical task, or governance authorization. Every "
            "update requires source_event_id and source_quote copied exactly from "
            "one user message. Memory fields: kind ('experience' for a meaningful "
            "one-off autobiographical episode; otherwise 'stable_statement'), "
            "statement (3-500 characters), confidence 0.6-0.95, "
            "importance 0-1. User-model fields: belief_key, statement, belief_type, "
            "confidence. belief_type may only use: "
            + ",".join(item.value for item in BeliefType) + ". "
            "For BOTH update types, source_quote must be a contiguous exact "
            "excerpt of 2-500 characters, NOT the entire long message; statement "
            "must be 3-500 characters. Use only the fields specified above. "
            "quality_review may only use: "
            + ",".join(flag.value for flag in QualityFlag) + ". "
            "Use prior_messages and relevant_memories only to check continuity, "
            "honest history use, and possible product improvements; never import "
            "their facts into today's Diary. improvement_suggestions has at most "
            "5 items with category, observation, recommendation, reason, risk, "
            "and 1-5 supplied evidence_event_ids. category may only use: "
            + ",".join(item.value for item in ImprovementCategory) + ". "
            "Suggest only concrete changes "
            "that improve the owner's experience; do not auto-authorize code or "
            "policy changes. follow_up_suggestion is null unless one current-day "
            "user message supports a natural, non-urgent continuation, curiosity, "
            "or recognition of progress. It requires exact source_event_id and "
            "source_quote, optional supplied memory_ref, reason_kind, and a warm "
            "2-300 character message. reason_kind may only use: "
            + ",".join(item.value for item in FollowUpReason) + ". "
            "Never suggest follow-up after the owner said "
            "not to ask, not to push, or not to talk. Never manufacture dependence."
        )
        transcript = {
            "local_date": local_date.isoformat(), "timezone": timezone_name,
            "window": "05:00 on local_date inclusive to 05:00 next local date exclusive",
            "private_event_count_not_supplied": private_count,
            "messages": [{
                "source_event_id": str(item["event_id"]), "role": item["role"],
                "recorded_at": item["recorded_at"].isoformat(),
                "content": item["content"],
            } for item in cloud_events],
            "prior_messages": [{
                "source_event_id": str(item["event_id"]), "role": item["role"],
                "recorded_at": item["recorded_at"].isoformat(),
                "content": item["content"],
            } for item in prior_events],
            "relevant_memories": [{
                "memory_ref": f"memory/{item['memory_id']}@{item['revision']}",
                "content": item["content_text"],
            } for item in review_memories],
        }
        if memory_only:
            schema += (
                " This is REALTIME MEMORY ONLY, immediately after completed chat turns. "
                "Return include_diary=false, null title/diary_text, empty quality_review "
                "and improvement_suggestions, and null follow_up_suggestion. Only "
                "memory_updates and user_model_updates may be nonempty. Return both "
                "empty for greetings, acknowledgements, pure task chatter, or no new "
                "understanding. Do not restate already stored memories. Corrections "
                "take priority over assistant speculation. Retain meaningful personal "
                "experiences even without an explicit request to remember."
            )
        persona = follow_up_persona(self.identity) if not memory_only and self.identity is not None else None
        if persona is not None:
            schema += "\n\n" + persona.text
            policy = combine_policies((policy, persona.data_policy))
        request = InferenceRequest(
            request_id=uuid7(), trace_id=uuid7().hex,
            purpose="memory_intelligence" if memory_only else "diary_intelligence", context_pack_id=uuid7(),
            messages=(
                InferenceMessage(
                    role="system", content_parts=(TextContentPart(text=schema),),
                    source_refs=(f"authorization/{DIARY_INTELLIGENCE_AUTHORIZATION_REF}",) + (persona.source_refs if persona else ()),
                ),
                InferenceMessage(
                    role="user",
                    content_parts=(TextContentPart(text=json.dumps(
                        transcript, ensure_ascii=False, separators=(",", ":")
                    )),),
                    source_refs=(
                        tuple(f"event/{item['event_id']}" for item in cloud_events)
                        + tuple(f"event/{item['event_id']}" for item in prior_events)
                        + tuple(
                            f"memory/{item['memory_id']}@{item['revision']}"
                            for item in review_memories
                        )
                    ),
                ),
            ),
            generation=GenerationSettings(
                max_output_tokens=4_096, temperature=0.2, top_p=0.95
            ),
            constraints=InferenceConstraints(
                stream=False, timeout_ms=self.timeout_ms,
                effective_data_policy=policy,
                allowed_execution_environments=("cloud",),
            ),
            metadata={
                "diary_authorization_ref": DIARY_INTELLIGENCE_AUTHORIZATION_REF,
                "diary_source_set_hash": source_set_hash,
                "diary_local_date": local_date.isoformat(),
                "diary_timezone": timezone_name,
                "diary_prompt_version": DIARY_FOLLOW_UP_PROMPT_VERSION if persona else DIARY_INTELLIGENCE_PROMPT_VERSION,
                **(persona.metadata if persona else {}),
            },
        )
        return bind_codex_cli_request(request, reasoning_effort="high")

    @staticmethod
    def _durable(value: str) -> bool:
        compact = re.sub(r"\s+", "", value)
        transient = ("今天", "刚刚", "现在有点", "这次", "临时", "今晚", "明天要")
        durable = ("喜欢", "偏好", "习惯", "通常", "重视", "希望", "不喜欢", "长期", "擅长")
        return not any(marker in compact for marker in transient) or any(
            marker in compact for marker in durable
        )

    def _validated_updates(self, result: DiaryIntelligenceResult,
                           cloud_events: list[dict[str, Any]], *,
                           strict_sources: bool = False) -> tuple[
                               tuple[DiaryMemoryUpdate, ...],
                               tuple[DiaryBeliefUpdate, ...],
                           ]:
        sources = {item["event_id"]: item for item in cloud_events
                   if item["role"] == "user" and item["memory_eligible"]}
        if strict_sources and any(
            item.source_event_id not in sources or
            item.source_quote not in sources[item.source_event_id]["content"]
            for item in (*result.memory_updates, *result.user_model_updates)
        ):
            raise ValueError("understanding source quote does not match; retry required")
        memories = tuple(item for item in result.memory_updates
                         if item.source_event_id in sources
                         and item.source_quote in sources[item.source_event_id]["content"]
                         and (item.kind == "experience" or self._durable(item.statement)))
        beliefs = tuple(item for item in result.user_model_updates
                        if item.source_event_id in sources
                        and item.source_quote in sources[item.source_event_id]["content"]
                        and self._durable(item.statement))
        return memories, beliefs

    def _validated_review(
        self, result: DiaryIntelligenceResult, *,
        cloud_events: list[dict[str, Any]],
        prior_events: list[dict[str, Any]],
        review_memories: list[dict[str, Any]],
    ) -> tuple[tuple[ImprovementSuggestion, ...], FollowUpSuggestion | None]:
        supplied_events = {
            item["event_id"]: item for item in (*cloud_events, *prior_events)
        }
        improvements = tuple(
            item for item in result.improvement_suggestions
            if all(event_id in supplied_events for event_id in item.evidence_event_ids)
        )
        follow_up = result.follow_up_suggestion
        if follow_up is None:
            return improvements, None
        current_users = {
            item["event_id"]: item for item in cloud_events if item["role"] == "user"
        }
        source = current_users.get(follow_up.source_event_id)
        if source is None or follow_up.source_quote not in source["content"]:
            return improvements, None
        stop_markers = (
            "别催", "不要催", "别问", "不要问", "不想说", "别说了",
            "先别联系", "别联系", "stop asking", "don't ask", "do not ask",
        )
        if any(
            marker in item["content"].lower()
            for item in current_users.values() for marker in stop_markers
        ):
            return improvements, None
        dependency_markers = (
            "只有我", "只需要我", "比现实朋友", "离不开我", "不要去生活",
            "only need me", "better than your friends", "depend on me",
        )
        if any(marker in follow_up.message.lower() for marker in dependency_markers):
            return improvements, None
        if follow_up.memory_ref is not None:
            allowed_memory_refs = {
                f"memory/{item['memory_id']}@{item['revision']}"
                for item in review_memories
            }
            if follow_up.memory_ref not in allowed_memory_refs:
                return improvements, None
        return improvements, follow_up

    def _persist_failure(self, *, local_date: date, timezone_name: str,
                         source_set_hash: str, events: list[dict[str, Any]],
                         error_code: str) -> None:
        run_id = uuid7()
        privacy, cloud_eligible = self._run_policy(events)
        with self.repository.pool.connection() as connection, connection.transaction():
            connection.execute(
                """INSERT INTO havre.daily_diary_intelligence_runs
                   (run_id,owner_id,local_date,timezone_name,source_set_hash,status,
                    error_code,privacy_class,memory_eligible,training_eligible,
                    cloud_eligible,policy_version,policy_revision_id,
                    policy_decision_source,policy_authorization_ref,window_start_hour)
                   VALUES (%s,%s,%s,%s,%s,'failed',%s,%s,false,false,%s,
                           'data-policy-v1',%s,'derived_conservative',%s,5)""",
                (run_id, self.owner_id, local_date, timezone_name, source_set_hash,
                 error_code[:200], privacy, cloud_eligible, uuid7(),
                 DIARY_INTELLIGENCE_AUTHORIZATION_REF),
            )
            self._insert_run_sources(connection, run_id, events)

    def _persist(self, *, local_date: date, timezone_name: str,
                 source_set_hash: str, events: list[dict[str, Any]],
                 review_memories: list[dict[str, Any]],
                 result: DiaryIntelligenceResult, request: InferenceRequest | None,
                 response: Any | None, status: str,
                 run_kind: str = "daily_review", connection: Any | None = None) -> UUID:
        if run_kind not in {"daily_review", "realtime_memory"}:
            raise ValueError("unknown understanding run kind")
        if run_kind == "realtime_memory" and (result.include_diary or result.quality_review or result.improvement_suggestions or result.follow_up_suggestion):
            raise ValueError("real-time memory cannot write diary/review/outreach effects")
        run_id = uuid7()
        privacy, cloud_eligible = self._run_policy(events)
        with (self.repository.pool.connection() if connection is None else nullcontext(connection)) as connection, connection.transaction():
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (f"diary:{self.owner_id}:{local_date}:{timezone_name}",),
            )
            existing = connection.execute(
                """SELECT 1 FROM havre.daily_diary_intelligence_runs
                   WHERE owner_id=%s AND local_date=%s AND timezone_name=%s
                     AND source_set_hash=%s AND status IN ('completed','private_only')""",
                (self.owner_id, local_date, timezone_name, source_set_hash),
            ).fetchone()
            if existing is not None:
                row = connection.execute(
                    """SELECT run_id FROM havre.daily_diary_intelligence_runs
                       WHERE owner_id=%s AND local_date=%s AND timezone_name=%s
                         AND source_set_hash=%s
                         AND status IN ('completed','private_only')
                       ORDER BY created_at DESC LIMIT 1""",
                    (self.owner_id, local_date, timezone_name, source_set_hash),
                ).fetchone()
                assert row is not None
                return row["run_id"]
            result_json = Jsonb(result.model_dump(mode="json"))
            if status == "completed":
                assert request is not None and response is not None
                connection.execute(
                    """INSERT INTO havre.daily_diary_intelligence_runs
                       (run_id,owner_id,local_date,timezone_name,source_set_hash,status,
                        inference_request_id,request_binding_hash,provider_id,
                        model_version_id,provider_adapter_version_id,
                        serving_config_version,reasoning_effort,result,
                        response_content_hash,privacy_class,memory_eligible,
                        training_eligible,cloud_eligible,policy_version,
                        policy_revision_id,policy_decision_source,
                        policy_authorization_ref,run_kind,window_start_hour)
                       VALUES (%s,%s,%s,%s,%s,'completed',%s,%s,%s,%s,%s,%s,
                               'high',%s,%s,%s,false,false,%s,'data-policy-v1',
                               %s,'derived_conservative',%s,%s,5)""",
                    (run_id, self.owner_id, local_date, timezone_name, source_set_hash,
                     request.inference_request_id,
                     request.metadata["cloud_request_binding_hash"],
                     response.provider.provider_id,
                     response.versions.model_version_id,
                     response.versions.provider_adapter_version_id,
                     response.versions.serving_config_version, result_json,
                     content_hash(response.output_parts[0].text), privacy,
                     cloud_eligible,
                     request.constraints.effective_data_policy.policy_revision_id,
                     DIARY_INTELLIGENCE_AUTHORIZATION_REF,run_kind),
                )
            else:
                connection.execute(
                    """INSERT INTO havre.daily_diary_intelligence_runs
                       (run_id,owner_id,local_date,timezone_name,source_set_hash,status,
                        result,privacy_class,memory_eligible,training_eligible,
                        cloud_eligible,policy_version,policy_revision_id,
                        policy_decision_source,policy_authorization_ref,window_start_hour)
                       VALUES (%s,%s,%s,%s,%s,'private_only',%s,%s,false,false,%s,
                               'data-policy-v1',%s,'derived_conservative',%s,5)""",
                    (run_id, self.owner_id, local_date, timezone_name, source_set_hash,
                     result_json, privacy, cloud_eligible, uuid7(),
                     DIARY_INTELLIGENCE_AUTHORIZATION_REF),
                )
            self._insert_run_sources(connection, run_id, events)
            if status == "completed":
                self._insert_review_memories(connection, run_id, review_memories)
            if status == "completed":
                for update in result.memory_updates:
                    self._insert_memory_update(connection, run_id, update)
                for update in result.user_model_updates:
                    self._insert_belief_update(connection, run_id, update)
            if run_kind == "daily_review":
                self._insert_diary_revision(
                    connection, run_id, local_date, timezone_name,
                    source_set_hash, events, result,
                )
        return run_id

    def _insert_run_sources(self, connection: Any, run_id: UUID,
                            events: list[dict[str, Any]]) -> None:
        for ordinal, event in enumerate(events):
            connection.execute(
                """INSERT INTO havre.daily_diary_intelligence_sources
                   (owner_id,run_id,ordinal,event_id,event_content_hash,disposition)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (self.owner_id, run_id, ordinal, event["event_id"],
                 event["content_hash"], event["disposition"]),
            )

    def _insert_review_memories(
        self, connection: Any, run_id: UUID,
        memories: list[dict[str, Any]],
    ) -> None:
        for ordinal, memory in enumerate(memories):
            connection.execute(
                """INSERT INTO havre.daily_diary_review_memory_sources
                   (owner_id,run_id,ordinal,memory_id,memory_revision,
                    memory_content_hash)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (
                    self.owner_id, run_id, ordinal, memory["memory_id"],
                    memory["revision"], memory["content_hash"],
                ),
            )

    def _source_row(self, connection: Any, source_event_id: UUID) -> dict[str, Any]:
        row = connection.execute(
            """SELECT event.*,route.selected_provider_id,route.execution_environment
               FROM havre.events event JOIN havre.route_decisions route
                 ON route.owner_id=event.owner_id AND route.request_id=event.request_id
               WHERE event.owner_id=%s AND event.event_id=%s
                 AND event.event_type='USER_MESSAGE' FOR KEY SHARE OF event""",
            (self.owner_id, source_event_id),
        ).fetchone()
        if (row is None or row["selected_provider_id"] != CODEX_CLI_PROVIDER_ID
                or row["payload"].get("input_origin") == "continuation_button"
                or row["execution_environment"] != "cloud"
                or row["privacy_class"] not in {"PUBLIC", "NORMAL"}
                or not row["cloud_eligible"] or not row["memory_eligible"]):
            raise ValueError("automatic understanding requires eligible GPT source Event")
        return row

    def _delegated_policy(self, source: dict[str, Any]) -> DataPolicy:
        return self.repository._derived_policy_from_row(source).model_copy(update={
            "authorization_ref": DIARY_INTELLIGENCE_AUTHORIZATION_REF,
        })

    def _insert_memory_update(self, connection: Any, run_id: UUID,
                              update: DiaryMemoryUpdate) -> None:
        # Respect an existing statement and the owner's explicit rejection or
        # retraction across different source Events; do not silently resurrect it.
        normalized = re.sub(r"[\s。.!！?？]+", "", update.statement.casefold())
        if connection.execute(
            """SELECT 1 FROM (
                 SELECT r.content_text FROM havre.memory_heads h
                 JOIN havre.memory_revisions r ON r.owner_id=h.owner_id
                  AND r.memory_id=h.memory_id AND r.revision=h.current_revision
                 WHERE h.owner_id=%s
                 UNION ALL SELECT content_text FROM havre.memory_candidates
                 WHERE owner_id=%s AND status='rejected'
               ) existing WHERE regexp_replace(lower(content_text),
                    '[[:space:]。.!！?？]+','','g')=%s LIMIT 1""",
            (self.owner_id, self.owner_id, normalized),
        ).fetchone() is not None:
            return
        # The same old source must not undo a later explicit owner correction.
        # Scope this to exact source provenance: a fresh owner statement can
        # express a genuinely changed intention and is reviewed independently.
        # Stop automatic re-extraction of this older source after owner repair;
        # wording or quote changes cannot prove a different unaffected fact.
        if connection.execute(
            """SELECT 1 FROM havre.memory_revisions previous
               JOIN havre.provenance_edges source
                 ON source.owner_id=previous.owner_id
                AND source.derived_kind='memory_revision'
                AND source.derived_id=previous.memory_id
                AND source.derived_revision=previous.revision
                AND source.source_kind='event'
                AND source.source_id=%s
               JOIN havre.memory_revisions correction
                 ON correction.owner_id=previous.owner_id
                AND correction.memory_id=previous.memory_id
                AND correction.revision>previous.revision
                AND correction.created_by='owner'
               WHERE previous.owner_id=%s
               LIMIT 1""",
            (update.source_event_id, self.owner_id),
        ).fetchone() is not None:
            return
        statement_hash = content_hash({"statement": update.statement})
        duplicate = connection.execute(
            """SELECT 1 FROM havre.owner_delegated_gpt_memory_updates
               WHERE owner_id=%s AND source_event_id=%s AND statement_hash=%s""",
            (self.owner_id, update.source_event_id, statement_hash),
        ).fetchone()
        if duplicate is not None:
            return
        source = self._source_row(connection, update.source_event_id)
        policy = self._delegated_policy(source)
        memory_id = uuid7()
        lifecycle = EventEnvelope(
            event_type=EventType.MEMORY_CREATED, owner_id=self.owner_id,
            session_id=source["session_id"], request_id=source["request_id"],
            trace_id=source["trace_id"], causation_event_id=update.source_event_id,
            data_policy=policy,
            payload=MemoryLifecyclePayload(
                memory_id=memory_id, memory_revision=1, action="created",
                reason=DIARY_INTELLIGENCE_AUTHORIZATION_REF,
            ),
        )
        self.repository._insert_event(connection, lifecycle)
        revision = MemoryRevision(
            owner_id=self.owner_id, memory_id=memory_id, revision=1,
            content={"text": update.statement, "source_quote": update.source_quote,
                     "origin": "owner_delegated_gpt", "kind": update.kind},
            content_text=update.statement, confidence=update.confidence,
            confidence_method="gpt-grounded-owner-authorized-v1",
            importance=update.importance,
            importance_policy_version="owner-delegated-gpt-v1",
            status=MemoryStatus.ACTIVE, source_occurred_at=source["recorded_at"],
            created_by="owner_delegated_gpt",
            transform_version=DIARY_INTELLIGENCE_TRANSFORM,
            created_event_id=lifecycle.event_id, trace_id=source["trace_id"],
            data_policy=policy,
        )
        self.repository._insert_memory_revision(connection, revision)
        connection.execute(
            """INSERT INTO havre.memory_heads
               (owner_id,memory_id,current_revision,status)
               VALUES (%s,%s,1,'active')""",
            (self.owner_id, memory_id),
        )
        self.repository._insert_embedding(connection, revision, self.embedding_provider)
        self.repository._insert_provenance(
            connection, owner_id=self.owner_id, source_kind="event",
            source_id=update.source_event_id, source_revision=None,
            revision=revision, relation="derived_from",
            transform_name="owner_delegated_gpt_diary_memory",
            transform_version=DIARY_INTELLIGENCE_TRANSFORM,
            created_event_id=lifecycle.event_id,
        )
        connection.execute(
            """INSERT INTO havre.owner_delegated_gpt_memory_updates
               (owner_id,run_id,source_event_id,statement_hash,memory_id,
                memory_revision,authorization_ref)
               VALUES (%s,%s,%s,%s,%s,1,%s)""",
            (self.owner_id, run_id, update.source_event_id, statement_hash,
             memory_id, DIARY_INTELLIGENCE_AUTHORIZATION_REF),
        )

    def _insert_belief_update(self, connection: Any, run_id: UUID,
                              update: DiaryBeliefUpdate) -> None:
        statement_hash = content_hash({"statement": update.statement})
        duplicate = connection.execute(
            """SELECT 1 FROM havre.owner_delegated_gpt_belief_updates
               WHERE owner_id=%s AND source_event_id=%s AND statement_hash=%s""",
            (self.owner_id, update.source_event_id, statement_hash),
        ).fetchone()
        if duplicate is not None:
            return
        source = self._source_row(connection, update.source_event_id)
        belief_key = f"owner-delegated-gpt:{update.belief_key.strip()}"
        if connection.execute(
            "SELECT 1 FROM havre.belief_heads WHERE owner_id=%s AND belief_key=%s",
            (self.owner_id, belief_key),
        ).fetchone() is not None:
            return
        policy = self._delegated_policy(source)
        belief_id = uuid7()
        lifecycle = EventEnvelope(
            event_type=EventType.USER_BELIEF_CREATED, owner_id=self.owner_id,
            session_id=source["session_id"], request_id=source["request_id"],
            trace_id=source["trace_id"], causation_event_id=update.source_event_id,
            data_policy=policy,
            payload=BeliefLifecyclePayload(
                belief_id=belief_id, belief_revision=1, action="created",
                reason=DIARY_INTELLIGENCE_AUTHORIZATION_REF,
            ),
        )
        self.repository._insert_event(connection, lifecycle)
        revision = BeliefRevision(
            owner_id=self.owner_id, belief_id=belief_id, revision=1,
            belief_key=belief_key, statement=update.statement,
            belief_type=update.belief_type, confidence=update.confidence,
            confidence_method="owner-delegated-gpt-v1",
            initial_status=BeliefInitialStatus.CANDIDATE,
            evidence_occurred_from=source["recorded_at"],
            evidence_occurred_to=source["recorded_at"],
            learned_at=source["recorded_at"], created_event_id=lifecycle.event_id,
            trace_id=source["trace_id"], data_policy=policy,
        )
        revision = self.repository._insert_belief_revision(connection, revision)
        connection.execute(
            """INSERT INTO havre.belief_heads
               (owner_id,belief_id,belief_key,current_revision,status)
               VALUES (%s,%s,%s,1,'candidate')""",
            (self.owner_id, belief_id, belief_key),
        )
        evidence = (EvidenceRef(
            source_kind=EvidenceSourceKind.EVENT,
            source_id=update.source_event_id,
            relation=EvidenceRelation.SUPPORTS,
        ),)
        self.repository._insert_stage4_evidence_edges(
            connection, owner_id=self.owner_id, evidence=evidence,
            derived_kind="belief_revision", derived_id=belief_id,
            derived_revision=1,
            transform_name="owner_delegated_gpt_diary_belief",
            transform_version=DIARY_INTELLIGENCE_TRANSFORM,
            created_event_id=lifecycle.event_id, trace_id=source["trace_id"],
        )
        transition_event, transition = self.repository._build_belief_transition(
            owner_id=self.owner_id,
            belief_id=belief_id,
            revision=1,
            transition_type=BeliefTransitionType.ACTIVATED,
            reason=DIARY_INTELLIGENCE_AUTHORIZATION_REF,
            occurred_at=datetime.now(UTC),
            policy=policy,
            anchor={
                "session_id": source["session_id"],
                "request_id": source["request_id"],
                "trace_id": source["trace_id"],
                "anchor_event_id": lifecycle.event_id,
            },
        )
        self.repository._insert_event(connection, transition_event)
        transition = self.repository._insert_belief_transition(
            connection, transition
        )
        connection.execute(
            """UPDATE havre.belief_heads
               SET status='active',last_transition_id=%s,
                   updated_at=statement_timestamp()
               WHERE owner_id=%s AND belief_id=%s""",
            (transition.belief_transition_id, self.owner_id, belief_id),
        )
        connection.execute(
            """INSERT INTO havre.owner_delegated_gpt_belief_updates
               (owner_id,run_id,source_event_id,statement_hash,belief_id,
                belief_revision,authorization_ref)
               VALUES (%s,%s,%s,%s,%s,1,%s)""",
            (self.owner_id, run_id, update.source_event_id, statement_hash,
             belief_id, DIARY_INTELLIGENCE_AUTHORIZATION_REF),
        )

    def _materialize_review_file(
        self, *, run_id: UUID, local_date: date,
        source_set_hash: str, result: DiaryIntelligenceResult,
    ) -> str | None:
        if self.review_root is None:
            return None
        self.review_root.mkdir(parents=True, exist_ok=True)
        target = (
            self.review_root / f"{local_date.isoformat()}--{run_id}.md"
        ).resolve()
        if target.parent != self.review_root:
            raise ValueError("daily review path escaped its configured root")
        relative_path = target.relative_to(self.review_root).as_posix()
        with self.repository.pool.connection() as connection:
            existing = connection.execute(
                """SELECT relative_path,file_sha256
                   FROM havre.daily_improvement_review_files
                   WHERE owner_id=%s AND run_id=%s""",
                (self.owner_id, run_id),
            ).fetchone()
        lines = [
            f"# HAVRE 每日体验审查 · {local_date.isoformat()}",
            "",
            "> 这是给 owner 日后交给 Codex 的本地建议文件。它不会自动修改代码、Identity 或政策。",
            "",
            f"- Diary run: `{run_id}`",
            f"- Source set: `{source_set_hash}`",
            "- 聊天原文：未复制到本文件",
            "",
            "## 修改建议",
            "",
        ]
        if not result.improvement_suggestions:
            lines.append("本次没有发现足够具体、且有证据支持的修改建议。")
        for index, suggestion in enumerate(result.improvement_suggestions, 1):
            evidence = ", ".join(
                f"`event/{event_id}`" for event_id in suggestion.evidence_event_ids
            )
            lines.extend((
                f"### {index}. {suggestion.category.value}",
                "",
                f"- 观察：{suggestion.observation}",
                f"- 建议：{suggestion.recommendation}",
                f"- 理由：{suggestion.reason}",
                f"- 风险：{suggestion.risk}",
                f"- 证据：{evidence}",
                "",
            ))
        if result.quality_review:
            lines.extend(("## 当日质量信号", ""))
            lines.extend(
                f"- {flag.value}: {QUALITY_GUIDANCE[flag.value]}"
                for flag in result.quality_review
            )
            lines.append("")
        payload = "\n".join(lines).rstrip() + "\n"
        encoded = payload.encode("utf-8")
        file_sha256 = "sha256:" + hashlib.sha256(encoded).hexdigest()
        if existing is not None:
            if existing["relative_path"] != relative_path:
                raise ValueError("daily review path no longer matches its receipt")
            if not target.exists() or (
                "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest()
                != existing["file_sha256"]
            ):
                temporary = target.with_suffix(".tmp")
                temporary.write_bytes(encoded)
                temporary.replace(target)
            return relative_path
        temporary = target.with_suffix(".tmp")
        temporary.write_bytes(encoded)
        temporary.replace(target)
        try:
            with (
                self.repository.pool.connection() as connection,
                connection.transaction(),
            ):
                connection.execute(
                    """INSERT INTO havre.daily_improvement_review_files
                       (owner_id,run_id,relative_path,file_sha256,source_set_hash)
                       VALUES (%s,%s,%s,%s,%s)""",
                    (
                        self.owner_id, run_id, relative_path, file_sha256,
                        source_set_hash,
                    ),
                )
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return relative_path

    def _enqueue_follow_up(
        self, *, run_id: UUID, suggestion: FollowUpSuggestion | None,
        review_memories: list[dict[str, Any]], timezone_name: str,
    ) -> None:
        if suggestion is None or self.proactive_store is None:
            return
        memory_refs = {
            f"memory/{item['memory_id']}@{item['revision']}"
            for item in review_memories
        }
        source_kind = "memory" if suggestion.memory_ref in memory_refs else "conversation"
        self.proactive_store.enqueue_relationship_follow_up(
            run_id=run_id,
            source_event_id=suggestion.source_event_id,
            source_kind=source_kind,
            memory_ref=suggestion.memory_ref,
            message=suggestion.message,
            timezone_name=timezone_name,
        )

    async def run_scheduled_once(
        self, *, worker_id: str,
        now: datetime | None = None,
        timezone_name: str,
    ) -> dict[str, Any] | None:
        instant = now or datetime.now(UTC)
        if instant.utcoffset() is None:
            raise ValueError("daily scheduler time must be timezone-aware")
        zone = ZoneInfo(timezone_name)
        local_now = instant.astimezone(zone)
        if local_now.timetz().replace(tzinfo=None) < time(5, 0):
            return None
        local_date = local_now.date() - timedelta(days=1)
        scheduled_for = datetime.combine(
            local_now.date(), time(5, 0), tzinfo=zone
        ).astimezone(UTC)
        lease_until = instant.astimezone(UTC) + timedelta(minutes=10)
        with self.repository.pool.connection() as connection, connection.transaction():
            connection.execute(
                """INSERT INTO havre.daily_diary_schedule_receipts
                   (owner_id,local_date,timezone_name,scheduled_for,status)
                   VALUES (%s,%s,%s,%s,'pending')
                   ON CONFLICT (owner_id,local_date,timezone_name) DO NOTHING""",
                (self.owner_id, local_date, timezone_name, scheduled_for),
            )
            receipt = connection.execute(
                """SELECT * FROM havre.daily_diary_schedule_receipts
                   WHERE owner_id=%s AND local_date=%s AND timezone_name=%s
                   FOR UPDATE""",
                (self.owner_id, local_date, timezone_name),
            ).fetchone()
            assert receipt is not None
            if receipt["status"] in {"completed", "no_events"}:
                return {"status": receipt["status"], "local_date": local_date}
            if (
                receipt["status"] == "leased"
                and receipt["lease_expires_at"] > instant.astimezone(UTC)
            ):
                return None
            if receipt["status"] == "retryable_failed":
                retry_after = (
                    receipt["updated_at"]
                    + self._retry_backoff(receipt["attempt_count"])
                )
                if retry_after > instant.astimezone(UTC):
                    return None
            connection.execute(
                """UPDATE havre.daily_diary_schedule_receipts
                   SET status='leased',lease_owner=%s,lease_expires_at=%s,
                       attempt_count=attempt_count+1,error_code=NULL,
                       updated_at=statement_timestamp()
                   WHERE owner_id=%s AND local_date=%s AND timezone_name=%s""",
                (
                    worker_id[:200], lease_until, self.owner_id, local_date,
                    timezone_name,
                ),
            )
        try:
            entry = await self.sync_day(
                local_date=local_date, timezone_name=timezone_name
            )
            status = "no_events" if entry is None else "completed"
            run_id = None if entry is None else entry.get("intelligence_run_id")
            with self.repository.pool.connection() as connection, connection.transaction():
                connection.execute(
                    """UPDATE havre.daily_diary_schedule_receipts
                       SET status=%s,run_id=%s,lease_owner=NULL,
                           lease_expires_at=NULL,error_code=NULL,
                           updated_at=statement_timestamp()
                       WHERE owner_id=%s AND local_date=%s AND timezone_name=%s
                         AND status='leased' AND lease_owner=%s""",
                    (
                        status, run_id, self.owner_id, local_date,
                        timezone_name, worker_id[:200],
                    ),
                )
            return {"status": status, "local_date": local_date, "run_id": run_id}
        except Exception as error:
            with self.repository.pool.connection() as connection, connection.transaction():
                connection.execute(
                    """UPDATE havre.daily_diary_schedule_receipts
                       SET status='retryable_failed',lease_owner=NULL,
                           lease_expires_at=NULL,error_code=%s,
                           updated_at=statement_timestamp()
                       WHERE owner_id=%s AND local_date=%s AND timezone_name=%s
                         AND lease_owner=%s""",
                    (
                        type(error).__name__[:200], self.owner_id, local_date,
                        timezone_name, worker_id[:200],
                    ),
                )
            raise

    @staticmethod
    def _retry_backoff(attempt_count: int) -> timedelta:
        delays = (
            timedelta(minutes=1),
            timedelta(minutes=5),
            timedelta(minutes=15),
            timedelta(hours=1),
            timedelta(hours=6),
        )
        return delays[min(max(attempt_count - 1, 0), len(delays) - 1)]

    def _insert_diary_revision(self, connection: Any, run_id: UUID,
                               local_date: date, timezone_name: str,
                               source_set_hash: str, events: list[dict[str, Any]],
                               result: DiaryIntelligenceResult) -> None:
        private_count = sum(item["disposition"] == "private_reference"
                            for item in events)
        head = connection.execute(
            """SELECT * FROM havre.daily_diary_entry_heads
               WHERE owner_id=%s AND local_date=%s AND timezone_name=%s FOR UPDATE""",
            (self.owner_id, local_date, timezone_name),
        ).fetchone()
        now = datetime.now(UTC)
        if not result.include_diary and not private_count:
            if head is not None:
                connection.execute(
                    """UPDATE havre.daily_diary_entry_heads
                       SET status='invalidated',invalidated_at=%s,updated_at=%s
                       WHERE owner_id=%s AND local_date=%s AND timezone_name=%s""",
                    (now, now, self.owner_id, local_date, timezone_name),
                )
            return
        title = result.title if result.include_diary else "今天的私密对话"
        summary = result.diary_text if result.include_diary else (
            "今天有私密对话记录，内容保持本地且未由 GPT 总结。"
        )
        assert title is not None and summary is not None
        preview = summary[:120].rstrip() + ("…" if len(summary) > 120 else "")
        if head is None:
            revision_number = 1
            connection.execute(
                """INSERT INTO havre.daily_diary_entry_heads
                   (owner_id,local_date,timezone_name,current_revision,status,
                    created_at,updated_at) VALUES (%s,%s,%s,1,'current',%s,%s)""",
                (self.owner_id, local_date, timezone_name, now, now),
            )
        else:
            revision_number = head["current_revision"] + 1
        revision_hash = content_hash({
            "local_date": local_date.isoformat(), "timezone_name": timezone_name,
            "revision": revision_number, "title": title,
            "summary_text": summary, "preview_text": preview,
            "summary_method": DIARY_INTELLIGENCE_METHOD,
            "source_set_hash": source_set_hash,
            "intelligence_run_id": str(run_id),
        })
        connection.execute(
            """INSERT INTO havre.daily_diary_entry_revisions
               (owner_id,local_date,timezone_name,revision,title,summary_text,
                preview_text,summary_method,source_set_hash,content_hash,
                created_at,intelligence_run_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (self.owner_id, local_date, timezone_name, revision_number, title,
             summary, preview, DIARY_INTELLIGENCE_METHOD, source_set_hash,
             revision_hash, now, run_id),
        )
        cloud = [item for item in events if item["disposition"] == "cloud_summary"]
        for ordinal, event in enumerate(cloud):
            connection.execute(
                """INSERT INTO havre.daily_diary_entry_sources
                   (owner_id,local_date,timezone_name,revision,ordinal,event_id,
                    event_content_hash) VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (self.owner_id, local_date, timezone_name, revision_number,
                 ordinal, event["event_id"], event["content_hash"]),
            )
        local_today = connection.execute(
            "SELECT ((clock_timestamp() AT TIME ZONE %s)-interval '5 hours')::date AS value",
            (timezone_name,),
        ).fetchone()["value"]
        finalized_at = now if local_date < local_today else None
        connection.execute(
            """UPDATE havre.daily_diary_entry_heads
               SET current_revision=%s,status='current',invalidated_at=NULL,
                   finalized_at=COALESCE(finalized_at,%s),updated_at=%s
               WHERE owner_id=%s AND local_date=%s AND timezone_name=%s""",
            (revision_number, finalized_at, now, self.owner_id,
             local_date, timezone_name),
        )

    def list_diary(self, *, timezone_name: str,
                   limit: int = 60) -> tuple[dict[str, Any], ...]:
        with self.repository.pool.connection() as connection:
            rows = connection.execute(
                """SELECT head.local_date,head.timezone_name,head.current_revision,
                          head.finalized_at,revision.title,revision.preview_text,
                          revision.summary_method,revision.created_at,
                          (SELECT count(*) FROM havre.daily_diary_entry_sources source
                           WHERE source.owner_id=revision.owner_id
                             AND source.local_date=revision.local_date
                             AND source.timezone_name=revision.timezone_name
                             AND source.revision=revision.revision) AS source_count,
                          COALESCE((SELECT count(*)
                           FROM havre.daily_diary_intelligence_sources source
                           WHERE source.owner_id=revision.owner_id
                             AND source.run_id=revision.intelligence_run_id
                             AND source.disposition='private_reference'),0)
                           AS private_source_count
                   FROM havre.daily_diary_entry_heads head
                   JOIN havre.daily_diary_entry_revisions revision
                     ON revision.owner_id=head.owner_id
                    AND revision.local_date=head.local_date
                    AND revision.timezone_name=head.timezone_name
                    AND revision.revision=head.current_revision
                   WHERE head.owner_id=%s AND head.timezone_name=%s
                     AND head.status='current'
                   ORDER BY head.local_date DESC LIMIT %s""",
                (self.owner_id, timezone_name, max(1, min(limit, 180))),
            ).fetchall()
        return tuple({**dict(row), "month": row["local_date"].month} for row in rows)

    def diary_day(self, *, local_date: date,
                  timezone_name: str) -> dict[str, Any] | None:
        with self.repository.pool.connection() as connection:
            row = connection.execute(
                """SELECT head.local_date,head.timezone_name,head.current_revision,
                          head.finalized_at,revision.title,revision.summary_text,
                          revision.preview_text,revision.summary_method,
                          revision.created_at,revision.intelligence_run_id,
                          run.result
                   FROM havre.daily_diary_entry_heads head
                   JOIN havre.daily_diary_entry_revisions revision
                     ON revision.owner_id=head.owner_id
                    AND revision.local_date=head.local_date
                    AND revision.timezone_name=head.timezone_name
                    AND revision.revision=head.current_revision
                   LEFT JOIN havre.daily_diary_intelligence_runs run
                     ON run.owner_id=revision.owner_id
                    AND run.run_id=revision.intelligence_run_id
                   WHERE head.owner_id=%s AND head.local_date=%s
                     AND head.timezone_name=%s AND head.status='current'""",
                (self.owner_id, local_date, timezone_name),
            ).fetchone()
            if row is None:
                return None
            sources = connection.execute(
                """SELECT source.ordinal,source.event_id,source.event_content_hash,
                          event.recorded_at,event.event_type,event.payload
                   FROM havre.daily_diary_entry_sources source
                   JOIN havre.events event ON event.owner_id=source.owner_id
                    AND event.event_id=source.event_id
                   WHERE source.owner_id=%s AND source.local_date=%s
                     AND source.timezone_name=%s AND source.revision=%s
                   ORDER BY source.ordinal""",
                (self.owner_id, local_date, timezone_name, row["current_revision"]),
            ).fetchall()
            private_sources: tuple[Any, ...] | list[Any] = ()
            update_counts: dict[str, Any] = {"memory": 0, "user_model": 0}
            review_file: str | None = None
            if row["intelligence_run_id"] is not None:
                private_sources = connection.execute(
                    """SELECT source.ordinal,source.event_id,event.recorded_at,
                              event.event_type,event.payload,event.privacy_class
                       FROM havre.daily_diary_intelligence_sources source
                       JOIN havre.events event ON event.owner_id=source.owner_id
                        AND event.event_id=source.event_id
                       WHERE source.owner_id=%s AND source.run_id=%s
                         AND source.disposition='private_reference'
                       ORDER BY source.ordinal""",
                    (self.owner_id, row["intelligence_run_id"]),
                ).fetchall()
                update_counts = connection.execute(
                    """SELECT
                         (SELECT count(*) FROM havre.owner_delegated_gpt_memory_updates
                          WHERE owner_id=%s AND run_id=%s) AS memory,
                         (SELECT count(*) FROM havre.owner_delegated_gpt_belief_updates
                          WHERE owner_id=%s AND run_id=%s) AS user_model""",
                    (self.owner_id, row["intelligence_run_id"], self.owner_id,
                     row["intelligence_run_id"]),
                ).fetchone()
                review_row = connection.execute(
                    """SELECT relative_path
                       FROM havre.daily_improvement_review_files
                       WHERE owner_id=%s AND run_id=%s""",
                    (self.owner_id, row["intelligence_run_id"]),
                ).fetchone()
                review_file = (
                    None if review_row is None else review_row["relative_path"]
                )
        output = dict(row)
        run_result = row["result"] if isinstance(row["result"], dict) else {}
        output.pop("result", None)
        output["quality_review"] = tuple(run_result.get("quality_review", ()))
        output["automatic_updates"] = dict(update_counts)
        output["improvement_review_file"] = review_file
        output["sources"] = tuple({
            "ordinal": item["ordinal"], "event_id": item["event_id"],
            "event_content_hash": item["event_content_hash"],
            "recorded_at": item["recorded_at"],
            "role": "user" if item["event_type"] == "USER_MESSAGE" else "assistant",
            "content": self._payload_text(item["payload"]),
        } for item in sources)
        output["private_sources"] = tuple({
            "ordinal": item["ordinal"], "event_id": item["event_id"],
            "recorded_at": item["recorded_at"],
            "role": "user" if item["event_type"] == "USER_MESSAGE" else "assistant",
            "privacy_class": item["privacy_class"],
            "content": self._payload_text(item["payload"]),
        } for item in private_sources)
        return output


__all__ = [
    "DIARY_INTELLIGENCE_AUTHORIZATION_REF", "DIARY_INTELLIGENCE_METHOD",
    "DiaryIntelligenceResult", "DiaryIntelligenceService", "FollowUpSuggestion",
    "ImprovementSuggestion", "QualityFlag", "QUALITY_GUIDANCE",
]
