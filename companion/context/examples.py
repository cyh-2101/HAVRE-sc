"""Owner-authorized, source-bound conversational behavior examples."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from companion.context.models import ConversationHistoryItem
from companion.hashing import content_hash
from companion.policy import DataPolicy, PrivacyClass


OWNER_EXAMPLE_AUTHORIZATION_REF = (
    "product-owner:2026-09-04:oa70-all70-runtime-examples"
)
OWNER_EXAMPLE_BANK_VERSION = "owner-example-bank-oa70-all70-v2"
OWNER_EXAMPLE_SELECTION_VERSION = "owner-example-selector-cjk-overlap-v2"
# Keep the sealed bank's derivation metadata unchanged; record the current
# algorithm separately in the admitted ContextPack.
OWNER_EXAMPLE_RUNTIME_SELECTION_VERSION = "owner-example-selector-current-turn-v3"
OWNER_EXAMPLE_SOURCE_SHA256 = (
    "sha256:51152825976d42971413cdd9b18609a2392036f114d8f4177c2a8d446e1031e9"
)
OWNER_EXAMPLE_CASE_IDS = tuple(
    f"owner-anchor-{index:03d}" for index in range(1, 71)
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BehaviorExampleMessage(StrictModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4_000)


class OwnerBehaviorExample(StrictModel):
    case_id: str = Field(pattern=r"^owner-anchor-[0-9]{3}$")
    title: str = Field(min_length=1, max_length=200)
    messages: tuple[BehaviorExampleMessage, ...] = Field(min_length=1, max_length=8)
    preferred_reply: str = Field(min_length=1, max_length=4_000)
    source_case_content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    def rendered_text(self) -> str:
        rows = [f'<example id="{self.case_id}" title="{self.title}">']
        rows.extend(f"  {message.role}: {message.content}" for message in self.messages)
        rows.append(f"  preferred_havre_reply: {self.preferred_reply}")
        rows.append("</example>")
        return "\n".join(rows)

    @property
    def source_refs(self) -> tuple[str, ...]:
        return (
            f"owner-example-bank/{OWNER_EXAMPLE_BANK_VERSION}",
            f"owner-alignment/{self.case_id}@{self.source_case_content_hash}",
        )


class OwnerExampleBank(StrictModel):
    schema_version: Literal[1] = 1
    example_bank_version: Literal[OWNER_EXAMPLE_BANK_VERSION] = (
        OWNER_EXAMPLE_BANK_VERSION
    )
    owner_id: UUID
    owner_authorization_ref: Literal[OWNER_EXAMPLE_AUTHORIZATION_REF] = (
        OWNER_EXAMPLE_AUTHORIZATION_REF
    )
    source_artifact_sha256: Literal[OWNER_EXAMPLE_SOURCE_SHA256] = (
        OWNER_EXAMPLE_SOURCE_SHA256
    )
    source_case_ids: tuple[str, ...] = Field(min_length=70, max_length=70)
    selection_policy_version: Literal[OWNER_EXAMPLE_SELECTION_VERSION] = (
        OWNER_EXAMPLE_SELECTION_VERSION
    )
    max_examples_per_turn: int = Field(default=3, ge=1, le=5)
    data_policy: DataPolicy
    examples: tuple[OwnerBehaviorExample, ...] = Field(min_length=70, max_length=70)
    content_hash: str = ""

    @model_validator(mode="after")
    def validate_authorized_derivation(self) -> "OwnerExampleBank":
        if self.source_case_ids != OWNER_EXAMPLE_CASE_IDS:
            raise ValueError("owner example bank must contain exact OA70 cases 1-70")
        if tuple(example.case_id for example in self.examples) != self.source_case_ids:
            raise ValueError("owner example bank order does not match source case IDs")
        if len(set(self.source_case_ids)) != len(self.source_case_ids):
            raise ValueError("owner example bank case IDs must be unique")
        policy = self.data_policy
        if (
            policy.privacy_class is not PrivacyClass.NORMAL
            or policy.memory_eligible
            or policy.training_eligible
            or not policy.cloud_eligible
            or policy.decision_source != "owner_explicit"
            or policy.authorization_ref != self.owner_authorization_ref
        ):
            raise ValueError("owner example bank requires exact owner-authorized policy")
        return self

    def model_post_init(self, __context: object) -> None:
        expected = content_hash(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match owner example bank")
        object.__setattr__(self, "content_hash", expected)

    def select(
        self,
        *,
        current_message: str,
        conversation_history: tuple[ConversationHistoryItem, ...] = (),
    ) -> tuple[OwnerBehaviorExample, ...]:
        if _ACKNOWLEDGEMENT.fullmatch(current_message.strip()):
            return ()
        recent_user_text = "\n".join(
            item.content_text
            for item in conversation_history[-6:]
            if item.role == "user"
        )
        # History can refine an already relevant example, but cannot make one
        # relevant to a new turn or turn an acknowledgement into another topic.
        query_features = _features(current_message)
        query_behavior = _behavior(current_message)
        history_features = _features(recent_user_text)
        example_texts = tuple(
            "\n".join(message.content for message in example.messages
                      if message.role == "user")
            for example in self.examples
        )
        example_features = tuple(_features(text) for text in example_texts)
        frequency = Counter(feature for features in example_features for feature in features)
        weights = {feature: math.log1p(len(self.examples) / count)
                   for feature, count in frequency.items()}
        scored: list[tuple[float, int, OwnerBehaviorExample]] = []
        for index, (example, text, features) in enumerate(
            zip(self.examples, example_texts, example_features)
        ):
            example_behavior = _behavior(text)
            if query_behavior and example_behavior and query_behavior != example_behavior:
                continue
            overlap = query_features & features
            # Single Chinese characters and generic conversation scaffolding do
            # not establish relevance. Shared explicit acts can bridge wording.
            behavior_match = bool(query_behavior and query_behavior == example_behavior)
            if not overlap and not behavior_match:
                continue
            lexical_score = sum(weights[feature] for feature in overlap)
            coverage = len(overlap) / max(1, min(len(query_features), len(features)))
            score = lexical_score * (0.5 + coverage) + (2.0 if behavior_match else 0.0)
            # Bounded tie-breaker after current-turn admission, never a trigger.
            score += min(0.25, len(history_features & features) * 0.025)
            scored.append((score, -index, example))
        scored.sort(reverse=True, key=lambda row: (row[0], row[1]))
        return tuple(row[2] for row in scored[: min(3, self.max_examples_per_turn)])

    @property
    def runtime_selection_version(self) -> str:
        return OWNER_EXAMPLE_RUNTIME_SELECTION_VERSION


_ASCII_WORD = re.compile(r"[a-z0-9]+", re.I)
_CJK_RUN = re.compile(r"[\u3400-\u9fff]+")
_CJK_STOP = frozenset("我你他她它的是了呢啊吧吗嘛有没不很也都就还又再这那现在哪什么怎么一个自己")
_GENERIC_FEATURES = frozenset({
    "今天", "现在", "最近", "然后", "感觉", "觉得", "真的", "说话", "事情",
    "the", "and", "you", "your", "me", "my", "is", "am", "are", "was",
    "were", "to", "of", "for", "in", "on", "it", "that", "this", "have",
    "has", "had", "do", "did", "can", "could", "would", "should", "today",
    "just", "really", "something", "about", "please", "not", "no",
})
_CJK_SCAFFOLDING = re.compile("|".join(
    re.escape(value) for value in sorted(_GENERIC_FEATURES)
    if _CJK_RUN.fullmatch(value)
))
_ACKNOWLEDGEMENT = re.compile(
    r"(?:ok|okay|好的?|好吧|行|嗯+|收到|知道了|明白了|谢谢|谢啦|thanks?|got it|sounds good)"
    r"[\s,.，。!！~～]*", re.I,
)
_LISTEN = re.compile(
    r"(?:不想|不要|别|先别)[^，,。！？!?\n]{0,8}(?:分析|建议|方案|办法)|"
    r"(?:只想|只要).{0,6}(?:听我|陪我)|"
    r"(?:don'?t|no).{0,8}(?:advice|analy[sz])|just listen", re.I,
)
_CORRECTION = re.compile(
    r"记错|弄错|理解错|误会我|不是这个意思|别再.{0,8}(?:说|叫)|"
    r"misremember|misunderstood me|that'?s not what i meant", re.I,
)
_GUIDANCE = re.compile(
    r"怎么办|该怎么|帮我.{0,8}(?:决定|选择|分析|计划)|给我.{0,6}(?:建议|方案)|"
    r"what should i|help me (?:decide|choose|plan)|give me advice", re.I,
)


def _behavior(text: str) -> str | None:
    """Only classify explicit acts; ordinary sharing has no invented intent."""
    for label, pattern in (("listen", _LISTEN), ("correct", _CORRECTION),
                           ("guide", _GUIDANCE)):
        if pattern.search(text):
            return label
    return None


def _features(text: str) -> frozenset[str]:
    normalized = _CJK_SCAFFOLDING.sub(" ", text.casefold())
    values = {word for word in _ASCII_WORD.findall(normalized) if len(word) >= 2}
    for run in _CJK_RUN.findall(normalized):
        values.update(run[index : index + 2] for index in range(len(run) - 1)
                      if not all(char in _CJK_STOP for char in run[index : index + 2]))
    return frozenset(values - _GENERIC_FEATURES)


def load_owner_example_bank(path: Path, *, owner_id: UUID) -> OwnerExampleBank:
    payload = json.loads(path.read_text(encoding="utf-8"))
    bank = OwnerExampleBank.model_validate(payload)
    if bank.owner_id != owner_id:
        raise ValueError("owner example bank belongs to a different owner")
    return bank
