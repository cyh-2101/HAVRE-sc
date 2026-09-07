"""Transparent Stage 2 episodic candidate extraction."""

from __future__ import annotations

import re

from companion.events import EventEnvelope, UserMessagePayload
from companion.memory.models import MemoryCandidate
from companion.policy import DataPolicy


EPISODIC_EXTRACTOR_VERSION = "episodic-extractor-stable-or-experience-v3"

_TECHNICAL_OR_GOVERNANCE = re.compile(
    r"product\s+owner|owner[- ]local|sha256:|\badr-?\d+|\bstage\s*\d+|"
    r"source[- ]erasure|policy[_ -]?version|migration|provenance|"
    r"我(?:确认)?批准|我确认授权|明确授权|授权扩展|批准启动|"
    r"五字段投影|提醒队列|课程.{0,12}(?:goal|投影|队列|导入|转换)",
    re.I,
)
_SUPPORTED_OWNER_STATEMENT = re.compile(
    r"(?:请|帮我)?记住|"
    r"我(?:更|最)?(?:喜欢|不喜欢|偏好|习惯|希望|讨厌|常用)|"
    r"对我来说.{0,40}(?:重要|更好|舒服|有用)|"
    r"(?:以后|今后).{0,32}(?:回复|跟我说|叫我|提醒)|"
    r"我叫|我的名字(?:是|叫)|我住在|我在.{0,28}(?:上学|读书|工作)|"
    r"我是.{0,28}(?:学生|老师|工程师|开发者)|"
    r"我(?:一直|长期|最近一直)在|"
    r"remember\s+that|i\s+(?:really\s+)?(?:prefer|like|dislike)|"
    r"i\s+do\s+not\s+like|my\s+name\s+is|i\s+live\s+in|"
    r"i\s+(?:study|work)\s+(?:at|in|as)",
    re.I,
)


def _is_narrative(value: str) -> bool:
    return len(value) >= 160 and value.count("我") >= 3 and bool(
        re.search(r"那时候|后来|经历|高中|初中|小时候|过去|当时", value)
    )


def proposed_memory_text(value: str) -> str | None:
    """Return one conservative owner-authored candidate, never a hidden fact."""

    compact = re.sub(r"\s+", " ", value).strip()
    if not compact or _TECHNICAL_OR_GOVERNANCE.search(compact):
        return None
    # A local narrative is only a review candidate, never a durable personality
    # claim. Preserve the owner's words and leave judgment to owner review.
    if _is_narrative(compact):
        return compact[:2000]
    for sentence in re.split(r"(?<=[。！？!?])\s*|[\r\n]+", compact):
        candidate = sentence.strip(" \t\r\n。.!！?？")
        if candidate and _SUPPORTED_OWNER_STATEMENT.search(candidate):
            return candidate[:300]
    return None


def is_memory_candidate_worthy(value: str) -> bool:
    return proposed_memory_text(value) is not None


class DeterministicEpisodicExtractor:
    version = EPISODIC_EXTRACTOR_VERSION
    confidence_method = "source-message-direct-v1"
    importance_policy_version = "uniform-owner-review-v1"

    def extract(self, *, event: EventEnvelope, job_id) -> MemoryCandidate:
        if not isinstance(event.payload, UserMessagePayload):
            raise TypeError("episodic extraction requires USER_MESSAGE")
        if not event.data_policy.memory_eligible:
            raise ValueError("source event is not memory eligible")
        source_text = "\n".join(part.text for part in event.payload.content_parts).strip()
        text = (
            proposed_memory_text(source_text)
            if event.payload.channel == "web"
            else source_text
        )
        if text is None:
            raise ValueError("web message does not support a stable Memory proposal")
        derived_policy = DataPolicy(
            privacy_class=event.data_policy.privacy_class,
            memory_eligible=event.data_policy.memory_eligible,
            training_eligible=False,
            cloud_eligible=(
                event.data_policy.cloud_eligible
                and event.data_policy.privacy_class.value
                in {"PUBLIC", "NORMAL", "PRIVATE"}
            ),
            policy_version=event.data_policy.policy_version,
            decision_source="derived_conservative",
        )
        return MemoryCandidate(
            owner_id=event.owner_id,
            source_event_id=event.event_id,
            source_request_id=event.request_id,
            job_id=job_id,
            content={
                "schema_version": 1,
                "kind": (
                    ("owner_proposed_experience" if _is_narrative(source_text)
                     else "owner_proposed_stable_statement")
                    if event.payload.channel == "web"
                    else "user_reported_episode"
                ),
                "text": text,
                "language": event.payload.language,
            },
            content_text=text,
            confidence=0.9,
            confidence_method=self.confidence_method,
            importance=0.5,
            importance_policy_version=self.importance_policy_version,
            extractor_version=self.version,
            data_policy=derived_policy,
            trace_id=event.trace_id,
        )
