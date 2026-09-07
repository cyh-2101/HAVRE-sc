"""Inspectable and reproducible Stage 1 Context Pack contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from companion.events import ContentPart
from companion.hashing import content_hash
from companion.ids import uuid7
from companion.policy import DataPolicy


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TokenBudget(StrictModel):
    max_input_tokens: int = Field(gt=0)
    reserved_output_tokens: int = Field(gt=0)
    estimator_id: Literal["utf8-bytes-div4-v1"] = "utf8-bytes-div4-v1"
    target_tokenizer_version_id: Literal["provider-neutral-estimator-v1"] = (
        "provider-neutral-estimator-v1"
    )


class ContextSection(StrictModel):
    section_id: str
    section_type: Literal[
        "identity",
        "response_plan",
        "episodic_memory",
        "semantic_memory",
        "pattern_memory",
        "progress_memory",
        "user_belief",
        "goal",
        "current_state",
        "communication_preference",
        "owner_response_instruction",
        "owner_wording_correction",
        "owner_fact_correction",
        "current_time",
        "behavior_example",
        "calendar_availability",
        "conversation_user_message",
        "conversation_assistant_message",
        "current_user_input",
    ]
    priority: int = Field(ge=0, le=100)
    content_parts: tuple[ContentPart, ...]
    estimated_tokens: int = Field(ge=0)
    source_refs: tuple[str, ...]
    data_policy: DataPolicy
    selection_reason: Literal[
        "required_by_policy",
        "retrieved_relevant",
        "selected_active_personal_context",
        "selected_conversation_history",
        "selected_behavior_example",
        "required_runtime_context",
        "required_current_request",
    ]
    truncation: None = None


class ContextPack(StrictModel):
    schema_version: Literal[1] = 1
    context_pack_id: UUID = Field(default_factory=uuid7)
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    owner_id: UUID
    request_id: UUID
    purpose: Literal["companion_response"] = "companion_response"
    builder_version: Literal[
        "context-builder-v3", "context-builder-v4", "context-builder-v5",
        "context-builder-v6",
        "context-builder-v7", "context-builder-v8", "context-builder-v9",
        "context-builder-v10",
        "context-builder-v11",
        "context-builder-v12",
        "context-builder-v13",
        "context-builder-v14",
        "context-builder-v15",
        "context-builder-v16",
        "context-builder-v17",
    ] = (
        "context-builder-v17"
    )
    constitution_version_id: str
    identity_version_id: str
    values_version_id: str
    policy_decision_id: None = None
    retrieval_result_id: UUID | None = None
    token_budget: TokenBudget
    sections: tuple[ContextSection, ...]
    excluded_candidates: tuple[dict[str, str], ...] = ()
    effective_data_policy: DataPolicy
    estimated_total_tokens: int = Field(ge=0)
    content_hash: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def model_post_init(self, __context: object) -> None:
        material = self.model_dump(mode="json", exclude={"content_hash", "created_at"})
        expected = content_hash(material)
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match Context Pack")
        object.__setattr__(self, "content_hash", expected)


class PersonalContextItem(StrictModel):
    owner_id: UUID
    section_id: str = Field(min_length=1, max_length=300)
    section_type: Literal[
        "user_belief", "goal", "current_state", "communication_preference",
        "owner_response_instruction", "episodic_memory", "semantic_memory",
        "owner_wording_correction",
        "owner_fact_correction",
        "pattern_memory", "progress_memory", "calendar_availability"
    ]
    content_text: str = Field(min_length=1, max_length=20_000)
    priority: int = Field(ge=0, le=99)
    source_refs: tuple[str, ...] = Field(min_length=1)
    data_policy: DataPolicy
    selector_version: Literal[
        "stage4-personal-context-selector-v1",
        "stage12a-calendar-context-selector-v1",
    ] = (
        "stage4-personal-context-selector-v1"
    )


class ConversationHistoryItem(StrictModel):
    owner_id: UUID
    session_id: UUID
    event_id: UUID
    request_id: UUID
    role: Literal["user", "assistant"]
    content_text: str = Field(min_length=1, max_length=100_000)
    recorded_at: datetime
    data_policy: DataPolicy
    selector_version: str | None = None

    @property
    def source_refs(self) -> tuple[str, ...]:
        return (f"event/{self.event_id}", *((f"context-selector/{self.selector_version}",) if self.selector_version else ()))
