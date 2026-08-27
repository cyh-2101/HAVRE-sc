"""Provider-neutral contracts for the governed Stage 6 proactive lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime, time
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from companion.hashing import content_hash
from companion.ids import uuid7
from companion.policy import DataPolicy


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _utc(value: datetime, *, name: str) -> datetime:
    if value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


class TriggerSourceKind(StrEnum):
    SCHEDULED_TIME = "scheduled_time"
    GOAL = "goal"
    SCENE_SESSION = "scene_session"
    OWNER_REMINDER = "owner_reminder"
    BELIEF_CONFIRMATION = "belief_confirmation"
    SYSTEM_OPERATIONAL = "system_operational"
    SYNTHETIC_LIFE_CONTEXT = "synthetic_life_context"


class InterruptionOutcome(StrEnum):
    SEND_NOW = "SEND_NOW"
    DEFER = "DEFER"
    DROP = "DROP"
    REQUEST_OWNER_CONFIRMATION = "REQUEST_OWNER_CONFIRMATION"


class PreviewPolicy(StrEnum):
    NONE = "none"
    GENERIC_PRIVATE = "generic_private"


class TriggerRecord(StrictModel):
    schema_version: Literal[1] = 1
    trigger_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    trigger_type: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    source_kind: TriggerSourceKind
    source_refs: tuple[str, ...] = Field(min_length=1)
    subject_refs: tuple[str, ...] = ()
    observed_at: datetime
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source_version: str = Field(min_length=1, max_length=200)
    data_policy: DataPolicy
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    status: Literal["recorded"] = "recorded"
    simulation_only: Literal[True] = True
    content_hash: str = ""

    @field_validator("observed_at", "recorded_at")
    @classmethod
    def normalize_times(cls, value: datetime, info) -> datetime:
        return _utc(value, name=info.field_name)

    @model_validator(mode="after")
    def bind_hash(self) -> "TriggerRecord":
        material = self.model_dump(mode="json", exclude={"content_hash", "recorded_at"})
        expected = content_hash(material)
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match TriggerRecord")
        object.__setattr__(self, "content_hash", expected)
        return self


class QuietHours(StrictModel):
    start_local: time
    end_local: time
    timezone_name: Literal["UTC"] = "UTC"


class ProactivePreferenceRevision(StrictModel):
    """Immutable owner-scoped controls; defaults fail closed."""

    schema_version: Literal[1] = 1
    preference_revision_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    revision: int = Field(gt=0)
    global_enabled: bool = False
    category_permissions: dict[
        str, Literal["allowed", "denied", "confirmation_required"]
    ] = Field(default_factory=dict)
    allowed_channels: tuple[Literal["web_inbox"], ...] = ()
    preview_policy: PreviewPolicy = PreviewPolicy.NONE
    quiet_hours: tuple[QuietHours, ...] = ()
    global_budget_per_24h: int | None = Field(default=None, gt=0, le=24)
    category_budget_per_24h: dict[str, int] = Field(default_factory=dict)
    cooldown_seconds: int | None = Field(default=None, ge=60, le=2_592_000)
    stopped_subject_refs: tuple[str, ...] = ()
    authorization_ref: str | None = Field(default=None, max_length=500)
    simulation_only: Literal[True] = True
    external_delivery_authorized: Literal[False] = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_hash: str = ""

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        return _utc(value, name="created_at")

    @model_validator(mode="after")
    def validate_and_hash(self) -> "ProactivePreferenceRevision":
        if self.global_enabled and not self.authorization_ref:
            raise ValueError("enabled proactive preferences require owner authorization")
        if any(value <= 0 or value > 24 for value in self.category_budget_per_24h.values()):
            raise ValueError("category budgets must be between 1 and 24")
        material = self.model_dump(mode="json", exclude={"content_hash", "created_at"})
        expected = content_hash(material)
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match preference revision")
        object.__setattr__(self, "content_hash", expected)
        return self


class ProactiveProposal(StrictModel):
    schema_version: Literal[1] = 1
    proposal_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    category: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    trigger_refs: tuple[UUID, ...] = Field(min_length=1)
    reason_code: str = Field(pattern=r"^[a-z][a-z0-9_]{1,95}$")
    reason_summary: str = Field(min_length=1, max_length=1000)
    intended_benefit: str = Field(min_length=1, max_length=1000)
    subject_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    data_policy: DataPolicy
    earliest_eligible_at: datetime
    expires_at: datetime
    deduplication_key: str = Field(min_length=1, max_length=240)
    candidate_channels: tuple[Literal["web_inbox"], ...] = ("web_inbox",)
    status: Literal["created"] = "created"
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    simulation_only: Literal[True] = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_hash: str = ""

    @field_validator("earliest_eligible_at", "expires_at", "created_at")
    @classmethod
    def normalize_times(cls, value: datetime, info) -> datetime:
        return _utc(value, name=info.field_name)

    @model_validator(mode="after")
    def validate_and_hash(self) -> "ProactiveProposal":
        if self.expires_at <= self.earliest_eligible_at:
            raise ValueError("proposal expiration must follow earliest eligibility")
        material = self.model_dump(mode="json", exclude={"content_hash", "created_at"})
        expected = content_hash(material)
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match proposal")
        object.__setattr__(self, "content_hash", expected)
        return self


class InterruptionInputs(StrictModel):
    global_permission: Literal["enabled", "disabled", "unresolved"]
    category_permission: Literal["allowed", "denied", "confirmation_required", "unresolved"]
    quiet_hours_result: Literal["inside", "outside", "unresolved"]
    global_budget_result: Literal["available", "exhausted", "unresolved"]
    category_budget_result: Literal["available", "exhausted", "unresolved"]
    cooldown_result: Literal["clear", "active", "unresolved"]
    deduplication_result: Literal["unique", "duplicate", "unresolved"]
    expiration_result: Literal["eligible", "not_yet", "expired"]
    channel_eligibility: Literal["eligible", "ineligible", "unresolved"]
    privacy_eligibility: Literal["eligible", "ineligible", "unresolved"]
    subject_stop_result: Literal["clear", "stopped"]
    prior_response_result: Literal[
        "none", "responded", "dismissed", "snoozed", "non_response", "stopped"
    ] = "none"


class InterruptionDecision(StrictModel):
    schema_version: Literal[1] = 1
    interruption_decision_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    proposal_id: UUID
    decision: InterruptionOutcome
    reason_codes: tuple[str, ...] = Field(min_length=1)
    human_explanation: str = Field(min_length=1, max_length=1000)
    policy_version: Literal["interruption-policy-conservative-v1"] = (
        "interruption-policy-conservative-v1"
    )
    preference_revision_id: UUID
    constitution_version_id: str
    identity_version_id: str
    inputs_snapshot: InterruptionInputs
    defer_until: datetime | None = None
    expires_at: datetime
    rendering_constraints: tuple[str, ...] = Field(min_length=1)
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    simulation_only: Literal[True] = True
    external_delivery_authorized: Literal[False] = False
    decided_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_hash: str = ""

    @field_validator("defer_until", "expires_at", "decided_at")
    @classmethod
    def normalize_times(cls, value: datetime | None, info) -> datetime | None:
        return None if value is None else _utc(value, name=info.field_name)

    @model_validator(mode="after")
    def validate_and_hash(self) -> "InterruptionDecision":
        if (self.decision is InterruptionOutcome.DEFER) != (self.defer_until is not None):
            raise ValueError("only DEFER decisions require defer_until")
        material = self.model_dump(mode="json", exclude={"content_hash", "decided_at"})
        expected = content_hash(material)
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match interruption decision")
        object.__setattr__(self, "content_hash", expected)
        return self


class ProactiveContextPack(StrictModel):
    schema_version: Literal[1] = 1
    proactive_context_pack_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    proposal_id: UUID
    interruption_decision_id: UUID
    purpose: Literal["authorized_proactive_rendering"] = "authorized_proactive_rendering"
    builder_version: Literal["proactive-context-builder-v1"] = "proactive-context-builder-v1"
    strategy_version: str = Field(min_length=1, max_length=200)
    prefix_sections: tuple[dict[str, object], ...] = Field(min_length=2)
    evidence_sections: tuple[dict[str, object], ...] = Field(min_length=1)
    prefix_stable: Literal[True] = True
    effective_data_policy: DataPolicy
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    content_hash: str = ""

    @model_validator(mode="after")
    def bind_hash(self) -> "ProactiveContextPack":
        expected = content_hash(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match proactive Context Pack")
        object.__setattr__(self, "content_hash", expected)
        return self


class RenderedProactiveMessage(StrictModel):
    schema_version: Literal[1] = 1
    rendering_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    proposal_id: UUID
    interruption_decision_id: UUID
    proactive_context_pack_id: UUID
    renderer_kind: Literal["deterministic_template"] = "deterministic_template"
    renderer_version: Literal["proactive-template-v1"] = "proactive-template-v1"
    content_text: str = Field(min_length=1, max_length=500)
    preview_policy: PreviewPolicy
    preview_text: str | None = Field(default=None, max_length=200)
    data_policy: DataPolicy
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    simulation_only: Literal[True] = True
    content_hash: str = ""

    @model_validator(mode="after")
    def validate_and_hash(self) -> "RenderedProactiveMessage":
        if self.preview_policy is PreviewPolicy.NONE and self.preview_text is not None:
            raise ValueError("no-preview policy cannot contain preview text")
        material = self.model_dump(mode="json", exclude={"content_hash"})
        expected = content_hash(material)
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match rendering")
        object.__setattr__(self, "content_hash", expected)
        return self


class DeliveryAttempt(StrictModel):
    schema_version: Literal[1] = 1
    delivery_attempt_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    proposal_id: UUID
    interruption_decision_id: UUID
    rendering_id: UUID
    channel: Literal["web_inbox"] = "web_inbox"
    adapter_version: Literal["local-web-inbox-v1"] = "local-web-inbox-v1"
    idempotency_key: str = Field(min_length=1, max_length=240)
    attempt_number: Literal[1] = 1
    status: Literal["delivered", "failed", "expired", "cancelled"]
    retryable: Literal[False] = False
    provider_receipt_id: str | None = Field(default=None, max_length=240)
    failure_code: str | None = Field(default=None, max_length=120)
    visible_at: datetime | None = None
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    simulation_only: Literal[True] = True
    external_delivery_authorized: Literal[False] = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_hash: str = ""

    @field_validator("visible_at", "created_at")
    @classmethod
    def normalize_times(cls, value: datetime | None, info) -> datetime | None:
        return None if value is None else _utc(value, name=info.field_name)

    @model_validator(mode="after")
    def validate_and_hash(self) -> "DeliveryAttempt":
        delivered = self.status == "delivered"
        if delivered != (self.visible_at is not None and self.provider_receipt_id is not None):
            raise ValueError("delivered attempts require visibility and a local receipt")
        if delivered and self.failure_code is not None:
            raise ValueError("delivered attempts cannot contain a failure")
        material = self.model_dump(mode="json", exclude={"content_hash", "created_at"})
        expected = content_hash(material)
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match delivery attempt")
        object.__setattr__(self, "content_hash", expected)
        return self


class ProactiveInboxItem(StrictModel):
    """Read projection for native clients; policy and delivery stay Core-owned."""

    schema_version: Literal[1] = 1
    inbox_message_id: UUID
    proposal_id: UUID
    delivery_attempt_id: UUID
    assistant_event_id: UUID
    content_text: str | None = Field(default=None, min_length=1, max_length=500)
    preview_policy: PreviewPolicy
    preview_text: str | None = Field(default=None, max_length=200)
    privacy_class: Literal["NORMAL", "PRIVATE", "HIGHLY_PRIVATE", "LOCAL_ONLY"]
    visible_at: datetime
    simulation_only: Literal[True] = True
    external_delivery_authorized: Literal[False] = False

    @field_validator("visible_at")
    @classmethod
    def normalize_visible_at(cls, value: datetime) -> datetime:
        return _utc(value, name="visible_at")


class ProactiveOwnerAction(StrictModel):
    schema_version: Literal[1] = 1
    action_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    proposal_id: UUID
    idempotency_key: str = Field(min_length=1, max_length=200)
    action_type: Literal[
        "responded", "dismissed", "snoozed", "non_response", "stopped"
    ]
    inbox_message_id: UUID | None = None
    response_event_id: UUID | None = None
    snooze_until: datetime | None = None
    deduplication_key: str = Field(min_length=1, max_length=240)
    subject_refs: tuple[str, ...] = ()
    reason: str = Field(min_length=1, max_length=1000)
    observed_at: datetime
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    simulation_only: Literal[True] = True
    content_hash: str = ""

    @field_validator("observed_at", "snooze_until")
    @classmethod
    def normalize_action_times(cls, value: datetime | None, info) -> datetime | None:
        return None if value is None else _utc(value, name=info.field_name)

    @model_validator(mode="after")
    def validate_and_hash(self) -> "ProactiveOwnerAction":
        if (self.action_type == "responded") != (self.response_event_id is not None):
            raise ValueError("only responded actions require a response event")
        if (self.action_type == "snoozed") != (self.snooze_until is not None):
            raise ValueError("only snoozed actions require snooze_until")
        if self.snooze_until is not None and self.snooze_until <= self.observed_at:
            raise ValueError("snooze_until must follow observed_at")
        material = self.model_dump(mode="json", exclude={"content_hash"})
        expected = content_hash(material)
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match proactive owner action")
        object.__setattr__(self, "content_hash", expected)
        return self


class ProactiveWorkCommand(StrictModel):
    schema_version: Literal[1] = 1
    trigger_type: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    source_kind: TriggerSourceKind
    source_refs: tuple[str, ...] = Field(min_length=1)
    subject_refs: tuple[str, ...] = ()
    category: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    reason_code: str = Field(pattern=r"^[a-z][a-z0-9_]{1,95}$")
    reason_summary: str = Field(min_length=1, max_length=1000)
    intended_benefit: str = Field(min_length=1, max_length=1000)
    data_policy: DataPolicy
    preference_revision: int = Field(gt=0)
    execution_idempotency_key: str = Field(min_length=1, max_length=200)
    observed_at: datetime
    earliest_eligible_at: datetime
    expires_at: datetime
    deduplication_key: str = Field(min_length=1, max_length=240)
    traceparent: str | None = None
    simulation_only: Literal[True] = True

    @field_validator("observed_at", "earliest_eligible_at", "expires_at")
    @classmethod
    def normalize_command_times(cls, value: datetime, info) -> datetime:
        return _utc(value, name=info.field_name)

    @model_validator(mode="after")
    def validate_window(self) -> "ProactiveWorkCommand":
        if self.expires_at <= self.earliest_eligible_at:
            raise ValueError("work command expiration must follow eligibility")
        return self


class ProactiveLifecycleView(StrictModel):
    request_id: UUID
    trace_id: str
    trigger: TriggerRecord
    proposal: ProactiveProposal
    preference: ProactivePreferenceRevision
    decision: InterruptionDecision
    context_pack: ProactiveContextPack | None = None
    rendering: RenderedProactiveMessage | None = None
    delivery_attempt: DeliveryAttempt | None = None
    assistant_event_id: UUID | None = None
    owner_actions: tuple[ProactiveOwnerAction, ...] = ()
    lifecycle_events: tuple[str, ...]
    idempotent_replay: bool = False
