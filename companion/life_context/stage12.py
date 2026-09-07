"""Stage 12 provider-neutral external context contracts.

These contracts retain only minimized canonical evidence. Provider-native or
device-native material is deliberately absent from every serializable model.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import hmac
import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from companion.hashing import canonical_json, content_hash
from companion.ids import uuid7
from companion.policy import DataPolicy, PrivacyClass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _utc(value: datetime, *, name: str) -> datetime:
    if value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


class SamplingPolicy(StrictModel):
    schema_version: Literal[1] = 1
    policy_version: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,95}$")
    mode: Literal["bounded_interval"] = "bounded_interval"
    sample_interval_seconds: int = Field(ge=10, le=300)
    summary_window_seconds: int = Field(ge=60, le=3600)
    idle_threshold_seconds: int = Field(ge=60, le=3600)
    fresh_for_seconds: int = Field(ge=60, le=3600)
    max_clock_skew_seconds: int = Field(ge=0, le=300)
    offline_buffer_seconds: int = Field(ge=0, le=86_400)

    @model_validator(mode="after")
    def validate_window(self) -> "SamplingPolicy":
        if self.summary_window_seconds % self.sample_interval_seconds:
            raise ValueError("summary window must be divisible by sample interval")
        return self


class CalendarImportPolicy(StrictModel):
    schema_version: Literal[1] = 1
    policy_version: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,95}$")
    mode: Literal["owner_initiated_import"] = "owner_initiated_import"
    max_coverage_seconds: int = Field(ge=86_400, le=17_280_000)
    freshness: Literal["through_coverage_end"] = "through_coverage_end"
    max_clock_skew_seconds: int = Field(ge=0, le=300)
    offline_buffer_seconds: int = Field(default=300, ge=0, le=300)


class RetentionPolicy(StrictModel):
    schema_version: Literal[1] = 1
    policy_version: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,95}$")
    source_native_retention_seconds: Literal[0] = 0
    normalized_draft_retention_seconds: int = Field(ge=0, le=86_400)
    canonical_retention_days: int = Field(ge=1, le=365)
    expiry_action: Literal["erase_with_provenance_closure"] = (
        "erase_with_provenance_closure"
    )


class ContextSourceDescriptor(StrictModel):
    schema_version: Literal[1] = 1
    source_instance_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    source_kind: Literal["windows", "calendar"]
    provider_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,95}$")
    device_binding_id: str = Field(pattern=r"^[a-z][a-z0-9_.:-]{2,127}$")
    adapter_version: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,127}$")
    source_version: str = Field(min_length=1, max_length=200)
    provider_tenant_binding: str | None = Field(
        default=None, pattern=r"^sha256:[0-9a-f]{64}$"
    )
    provider_account_binding: str | None = Field(
        default=None, pattern=r"^sha256:[0-9a-f]{64}$"
    )
    enrollment_status: Literal["enabled"] = "enabled"
    content_hash: str = ""

    @model_validator(mode="after")
    def bind_hash(self) -> "ContextSourceDescriptor":
        if self.source_kind == "calendar":
            if (
                self.provider_tenant_binding is None
                or self.provider_account_binding is None
            ):
                raise ValueError(
                    "calendar source requires exact tenant and account bindings"
                )
        elif (
            self.provider_tenant_binding is not None
            or self.provider_account_binding is not None
        ):
            raise ValueError("non-calendar source cannot carry provider account bindings")
        expected = content_hash(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match ContextSourceDescriptor")
        object.__setattr__(self, "content_hash", expected)
        return self


class ContextSourceCapability(StrictModel):
    schema_version: Literal[1] = 1
    capability_revision_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    source_instance_id: UUID
    capability_id: Literal[
        "windows.device_activity_summary.v1",
        "calendar.read_availability.v1",
    ]
    revision: Literal[1] = 1
    observation_kind: Literal[
        "device_activity_summary", "calendar_availability_window"
    ]
    observation_schema_version: Literal[1] = 1
    allowed_fields: tuple[str, ...]
    precision: Literal[
        "coarse_category_window", "availability_only_no_content"
    ] = "coarse_category_window"
    sampling_modes: tuple[
        Literal["bounded_interval", "owner_initiated_import"], ...
    ] = ("bounded_interval",)
    conformance_version: Literal[
        "windows-coarse-adapter-conformance-v1",
        "calendar-availability-adapter-conformance-v1",
    ] = "windows-coarse-adapter-conformance-v1"
    status: Literal["enabled"] = "enabled"
    content_hash: str = ""

    @model_validator(mode="after")
    def validate_fields_and_hash(self) -> "ContextSourceCapability":
        profiles = {
            "windows.device_activity_summary.v1": {
                "observation_kind": "device_activity_summary",
                "allowed_fields": (
                    "activity_state", "active_seconds", "dominant_category",
                    "idle_seconds", "sample_count", "window_seconds",
                ),
                "precision": "coarse_category_window",
                "sampling_modes": ("bounded_interval",),
                "conformance_version": "windows-coarse-adapter-conformance-v1",
            },
            "calendar.read_availability.v1": {
                "observation_kind": "calendar_availability_window",
                "allowed_fields": ("busy_intervals",),
                "precision": "availability_only_no_content",
                "sampling_modes": ("owner_initiated_import",),
                "conformance_version": "calendar-availability-adapter-conformance-v1",
            },
        }
        expected_profile = profiles[self.capability_id]
        for field_name, expected_value in expected_profile.items():
            if getattr(self, field_name) != expected_value:
                raise ValueError(
                    f"{self.capability_id} requires exact {field_name}"
                )
        expected = content_hash(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match ContextSourceCapability")
        object.__setattr__(self, "content_hash", expected)
        return self


class ContextSourceStateRevision(StrictModel):
    schema_version: Literal[1] = 1
    state_revision_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    source_instance_id: UUID
    revision: int = Field(gt=0)
    status: Literal["enabled", "disabled"]
    reason: Literal[
        "registered", "owner_enabled", "owner_disabled", "lost_device", "key_rotated"
    ]
    effective_at: datetime
    authorization_ref: str = Field(min_length=1, max_length=500)
    content_hash: str = ""

    @field_validator("effective_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _utc(value, name="effective_at")

    @model_validator(mode="after")
    def validate_state(self) -> "ContextSourceStateRevision":
        if self.revision == 1 and (
            self.status != "enabled" or self.reason != "registered"
        ):
            raise ValueError("the first source state must register an enabled source")
        if self.revision > 1 and self.status != "disabled":
            raise ValueError("a source cannot be re-enabled; enroll a new source")
        if self.revision > 1 and self.reason == "registered":
            raise ValueError("registered is valid only for the first source state")
        expected = content_hash(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match ContextSourceStateRevision")
        object.__setattr__(self, "content_hash", expected)
        return self


class ContextCapabilityStateRevision(StrictModel):
    schema_version: Literal[1] = 1
    state_revision_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    capability_revision_id: UUID
    revision: int = Field(gt=0)
    status: Literal["enabled", "disabled"]
    reason: Literal["registered", "owner_disabled", "source_disabled"]
    effective_at: datetime
    authorization_ref: str = Field(min_length=1, max_length=500)
    content_hash: str = ""

    @field_validator("effective_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _utc(value, name="effective_at")

    @model_validator(mode="after")
    def validate_state(self) -> "ContextCapabilityStateRevision":
        if self.revision == 1 and (
            self.status != "enabled" or self.reason != "registered"
        ):
            raise ValueError("the first capability state must be enabled registration")
        if self.revision > 1 and self.status != "disabled":
            raise ValueError("a capability cannot be re-enabled; register a new revision")
        if self.revision > 1 and self.reason == "registered":
            raise ValueError("registered is valid only for the first capability state")
        expected = content_hash(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match ContextCapabilityStateRevision")
        object.__setattr__(self, "content_hash", expected)
        return self


class ContextCollectionPermit(StrictModel):
    schema_version: Literal[1] = 1
    source: ContextSourceDescriptor
    source_state: ContextSourceStateRevision
    capability: ContextSourceCapability
    capability_state: ContextCapabilityStateRevision
    consent: "ConsentScopeRevision"
    issued_at: datetime
    valid_until: datetime
    content_hash: str = ""

    @field_validator("issued_at", "valid_until")
    @classmethod
    def normalize_time(cls, value: datetime, info) -> datetime:
        return _utc(value, name=info.field_name)

    @model_validator(mode="after")
    def validate_permit(self) -> "ContextCollectionPermit":
        if (
            self.source_state.source_instance_id != self.source.source_instance_id
            or self.capability.source_instance_id != self.source.source_instance_id
            or self.capability_state.capability_revision_id
                != self.capability.capability_revision_id
            or self.consent.source_instance_id != self.source.source_instance_id
            or self.consent.capability_revision_id
                != self.capability.capability_revision_id
            or self.source_state.status != "enabled"
            or self.capability_state.status != "enabled"
            or self.consent.status != "active"
        ):
            raise ValueError("collection permit requires one exact enabled consent chain")
        if not (
            self.consent.effective_at <= self.issued_at < self.valid_until
            <= self.consent.expires_at
        ):
            raise ValueError("collection permit validity exceeds consent")
        expected = content_hash(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match ContextCollectionPermit")
        object.__setattr__(self, "content_hash", expected)
        return self


class ContextCollectionPermitRequest(StrictModel):
    schema_version: Literal[1] = 1
    owner_id: UUID
    source_instance_id: UUID
    device_binding_id: str = Field(pattern=r"^[a-z][a-z0-9_.:-]{2,127}$")
    requested_at: datetime
    nonce: str = Field(pattern=r"^[0-9a-f]{32}$")
    signature: str = Field(default="", pattern=r"^(|hmac-sha256:[0-9a-f]{64})$")

    @field_validator("requested_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _utc(value, name="requested_at")

    def signing_material(self) -> str:
        return canonical_json(self.model_dump(mode="json", exclude={"signature"}))


def sign_collection_permit_request(
    request: ContextCollectionPermitRequest, *, secret: bytes
) -> ContextCollectionPermitRequest:
    if not secret:
        raise ValueError("device signing secret is required")
    digest = hmac.new(secret, request.signing_material().encode("utf-8"), hashlib.sha256)
    return request.model_copy(update={"signature": f"hmac-sha256:{digest.hexdigest()}"})


def verify_collection_permit_request_signature(
    request: ContextCollectionPermitRequest, *, secret: bytes
) -> bool:
    if not secret or not request.signature:
        return False
    expected = sign_collection_permit_request(
        request.model_copy(update={"signature": ""}), secret=secret
    ).signature
    return hmac.compare_digest(request.signature, expected)


class ConsentScopeRevision(StrictModel):
    schema_version: Literal[1] = 1
    consent_scope_revision_id: UUID = Field(default_factory=uuid7)
    consent_scope_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    source_instance_id: UUID
    capability_revision_id: UUID
    revision: int = Field(gt=0)
    status: Literal["active", "revoked", "expired"]
    purpose: Literal["companion_timing_context"] = "companion_timing_context"
    allowed_observation_kinds: tuple[
        Literal["device_activity_summary", "calendar_availability_window"], ...
    ] = ("device_activity_summary",)
    allowed_fields: tuple[str, ...]
    permitted_destinations: tuple[Literal["owner_core_local"], ...] = (
        "owner_core_local",
    )
    sampling_policy: SamplingPolicy | CalendarImportPolicy
    retention_policy: RetentionPolicy
    data_policy: DataPolicy
    effective_at: datetime
    expires_at: datetime
    authorization_ref: str = Field(min_length=1, max_length=500)
    content_hash: str = ""

    @field_validator("effective_at", "expires_at")
    @classmethod
    def normalize_time(cls, value: datetime, info) -> datetime:
        return _utc(value, name=info.field_name)

    @model_validator(mode="after")
    def validate_scope_and_hash(self) -> "ConsentScopeRevision":
        if self.expires_at <= self.effective_at:
            raise ValueError("consent expiry must follow its effective time")
        if self.data_policy.privacy_class is not PrivacyClass.LOCAL_ONLY:
            raise ValueError("external context must remain LOCAL_ONLY")
        if (
            self.data_policy.memory_eligible
            or self.data_policy.training_eligible
            or self.data_policy.cloud_eligible
        ):
            raise ValueError("external context cannot enable memory, training, or cloud")
        if self.data_policy.decision_source != "owner_explicit":
            raise ValueError("external context requires explicit owner policy")
        if self.data_policy.authorization_ref != self.authorization_ref:
            raise ValueError("DataPolicy authorization must match consent authorization")
        expected = content_hash(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match ConsentScopeRevision")
        object.__setattr__(self, "content_hash", expected)
        return self


ContextCollectionPermit.model_rebuild()


class WindowsContextActivationBundle(StrictModel):
    schema_version: Literal[1] = 1
    activation_id: UUID = Field(default_factory=uuid7)
    source: ContextSourceDescriptor
    capability: ContextSourceCapability
    consent: ConsentScopeRevision
    owner_activation_ref: str = Field(min_length=1, max_length=500)
    content_hash: str = ""

    @model_validator(mode="after")
    def validate_bundle(self) -> "WindowsContextActivationBundle":
        if (
            self.source.source_kind != "windows"
            or self.capability.source_instance_id != self.source.source_instance_id
            or self.consent.source_instance_id != self.source.source_instance_id
            or self.consent.capability_revision_id
                != self.capability.capability_revision_id
            or self.consent.status != "active"
            or self.owner_activation_ref != self.consent.authorization_ref
        ):
            raise ValueError("activation bundle must bind one exact active Windows scope")
        expected = content_hash(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match WindowsContextActivationBundle")
        object.__setattr__(self, "content_hash", expected)
        return self


class CalendarContextActivationBundle(StrictModel):
    schema_version: Literal[1] = 1
    activation_id: UUID = Field(default_factory=uuid7)
    source: ContextSourceDescriptor
    capability: ContextSourceCapability
    consent: ConsentScopeRevision
    owner_activation_ref: str = Field(min_length=1, max_length=500)
    source_access_mode: Literal["manual_owner_file"] = "manual_owner_file"
    content_hash: str = ""

    @model_validator(mode="after")
    def validate_bundle(self) -> "CalendarContextActivationBundle":
        if (
            self.source.source_kind != "calendar"
            or self.source.provider_id != "manual-ics"
            or self.source.adapter_version != "manual-ics-calendar-v1"
            or self.capability.capability_id != "calendar.read_availability.v1"
            or self.capability.source_instance_id != self.source.source_instance_id
            or self.consent.source_instance_id != self.source.source_instance_id
            or self.consent.capability_revision_id
                != self.capability.capability_revision_id
            or self.consent.allowed_observation_kinds
                != ("calendar_availability_window",)
            or self.consent.allowed_fields != ("busy_intervals",)
            or not isinstance(self.consent.sampling_policy, CalendarImportPolicy)
            or self.consent.status != "active"
            or self.owner_activation_ref != self.consent.authorization_ref
        ):
            raise ValueError("activation bundle must bind one exact Calendar scope")
        expected = content_hash(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match CalendarContextActivationBundle")
        object.__setattr__(self, "content_hash", expected)
        return self


class DeviceActivitySummary(StrictModel):
    schema_version: Literal[1] = 1
    dominant_category: Literal[
        "browser", "communication", "development", "game", "media",
        "office", "other", "system", "unknown",
    ]
    activity_state: Literal["active", "idle", "unknown"]
    active_seconds: int = Field(ge=0, le=3600)
    idle_seconds: int = Field(ge=0, le=3600)
    sample_count: int = Field(gt=0, le=360)
    window_seconds: int = Field(ge=60, le=3600)

    @model_validator(mode="after")
    def validate_duration(self) -> "DeviceActivitySummary":
        if self.active_seconds + self.idle_seconds > self.window_seconds:
            raise ValueError("activity durations exceed the summary window")
        return self


class CalendarBusyInterval(StrictModel):
    starts_at: datetime
    ends_at: datetime
    availability: Literal["busy", "tentative", "out_of_office", "working_elsewhere"]
    is_all_day: bool

    @field_validator("starts_at", "ends_at")
    @classmethod
    def normalize_time(cls, value: datetime, info) -> datetime:
        return _utc(value, name=info.field_name)

    @model_validator(mode="after")
    def validate_interval(self) -> "CalendarBusyInterval":
        if self.ends_at <= self.starts_at:
            raise ValueError("calendar busy interval must have positive duration")
        return self


class CalendarAvailabilityWindow(StrictModel):
    schema_version: Literal[1] = 1
    busy_intervals: tuple[CalendarBusyInterval, ...] = Field(max_length=512)

    @model_validator(mode="after")
    def validate_order(self) -> "CalendarAvailabilityWindow":
        ordered = tuple(
            sorted(
                self.busy_intervals,
                key=lambda item: (item.starts_at, item.ends_at, item.availability),
            )
        )
        if ordered != self.busy_intervals:
            raise ValueError("calendar busy intervals must be deterministically ordered")
        return self


class ContextObservationDraft(StrictModel):
    schema_version: Literal[1] = 1
    draft_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    source_instance_id: UUID
    device_binding_id: str = Field(pattern=r"^[a-z][a-z0-9_.:-]{2,127}$")
    capability_revision_id: UUID
    capability_id: Literal[
        "windows.device_activity_summary.v1", "calendar.read_availability.v1"
    ]
    observation_kind: Literal[
        "device_activity_summary", "calendar_availability_window"
    ]
    observation_schema_version: Literal[1] = 1
    value: DeviceActivitySummary | CalendarAvailabilityWindow
    occurred_from: datetime
    occurred_to: datetime
    source_observed_at: datetime
    consent_scope_revision_id: UUID
    sampling_policy_version: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,95}$")
    retention_policy_version: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,95}$")
    adapter_version: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,127}$")
    data_policy: DataPolicy
    idempotency_key: str = Field(min_length=1, max_length=200)
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    signature: str = Field(default="", pattern=r"^(|hmac-sha256:[0-9a-f]{64})$")

    @field_validator("occurred_from", "occurred_to", "source_observed_at")
    @classmethod
    def normalize_time(cls, value: datetime, info) -> datetime:
        return _utc(value, name=info.field_name)

    @model_validator(mode="after")
    def validate_window(self) -> "ContextObservationDraft":
        if self.occurred_to <= self.occurred_from:
            raise ValueError("observation window must have positive duration")
        if (
            self.observation_kind == "device_activity_summary"
            and self.source_observed_at < self.occurred_to
        ):
            raise ValueError("source observation time cannot precede coverage end")
        if (
            self.capability_id == "windows.device_activity_summary.v1"
            and not isinstance(self.value, DeviceActivitySummary)
        ) or (
            self.capability_id == "calendar.read_availability.v1"
            and not isinstance(self.value, CalendarAvailabilityWindow)
        ):
            raise ValueError("capability, observation kind, and value must match")
        expected_kind = {
            "windows.device_activity_summary.v1": "device_activity_summary",
            "calendar.read_availability.v1": "calendar_availability_window",
        }[self.capability_id]
        if self.observation_kind != expected_kind:
            raise ValueError("capability and observation kind must match")
        if self.data_policy.privacy_class is not PrivacyClass.LOCAL_ONLY:
            raise ValueError("external context draft must remain LOCAL_ONLY")
        return self

    def signing_material(self) -> str:
        return canonical_json(self.model_dump(mode="json", exclude={"signature"}))


def sign_observation_draft(
    draft: ContextObservationDraft, *, secret: bytes
) -> ContextObservationDraft:
    if not secret:
        raise ValueError("device signing secret is required")
    digest = hmac.new(secret, draft.signing_material().encode("utf-8"), hashlib.sha256)
    return draft.model_copy(update={"signature": f"hmac-sha256:{digest.hexdigest()}"})


def verify_observation_draft_signature(
    draft: ContextObservationDraft, *, secret: bytes
) -> bool:
    if not secret or not draft.signature:
        return False
    expected = sign_observation_draft(
        draft.model_copy(update={"signature": ""}), secret=secret
    ).signature
    return hmac.compare_digest(draft.signature, expected)


class ContextSourceHealthDraft(StrictModel):
    schema_version: Literal[1] = 1
    draft_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    source_instance_id: UUID
    device_binding_id: str = Field(pattern=r"^[a-z][a-z0-9_.:-]{2,127}$")
    capability_revision_id: UUID
    status: Literal["degraded", "stale", "offline", "permission_revoked", "unsupported"]
    checked_at: datetime
    safe_error_category: Literal[
        "foreground_unavailable",
        "idle_state_unavailable",
        "network_unavailable",
        "permission_revoked",
        "unsupported_platform",
    ]
    adapter_version: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,127}$")
    source_version: str = Field(min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=1, max_length=200)
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    signature: str = Field(default="", pattern=r"^(|hmac-sha256:[0-9a-f]{64})$")

    @field_validator("checked_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _utc(value, name="checked_at")

    def signing_material(self) -> str:
        return canonical_json(self.model_dump(mode="json", exclude={"signature"}))


def sign_health_draft(
    draft: ContextSourceHealthDraft, *, secret: bytes
) -> ContextSourceHealthDraft:
    if not secret:
        raise ValueError("device signing secret is required")
    digest = hmac.new(secret, draft.signing_material().encode("utf-8"), hashlib.sha256)
    return draft.model_copy(update={"signature": f"hmac-sha256:{digest.hexdigest()}"})


def verify_health_draft_signature(
    draft: ContextSourceHealthDraft, *, secret: bytes
) -> bool:
    if not secret or not draft.signature:
        return False
    expected = sign_health_draft(
        draft.model_copy(update={"signature": ""}), secret=secret
    ).signature
    return hmac.compare_digest(draft.signature, expected)


class LifeContextObservationV2(StrictModel):
    schema_version: Literal[2] = 2
    observation_id: UUID = Field(default_factory=uuid7)
    draft_id: UUID
    owner_id: UUID
    source_instance_id: UUID
    capability_revision_id: UUID
    capability_id: Literal[
        "windows.device_activity_summary.v1", "calendar.read_availability.v1"
    ]
    observation_kind: Literal[
        "device_activity_summary", "calendar_availability_window"
    ]
    observation_schema_version: Literal[1] = 1
    value: DeviceActivitySummary | CalendarAvailabilityWindow
    occurred_from: datetime
    occurred_to: datetime
    source_observed_at: datetime
    ingested_at: datetime
    fresh_until: datetime
    retention_expires_at: datetime
    consent_scope_revision_id: UUID
    sampling_policy_version: str
    retention_policy_version: str
    adapter_version: str
    data_policy: DataPolicy
    event_id: UUID
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    idempotency_key: str = Field(min_length=1, max_length=200)
    draft_content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    device_binding_id: str = Field(pattern=r"^[a-z][a-z0-9_.:-]{2,127}$")
    # The Calendar contract permits 512 minimized intervals. A valid semester
    # projection can therefore exceed 16 KiB even though it contains no event
    # content. Keep a hard bound sized to the contract's actual maximum.
    draft_signing_material: str = Field(min_length=2, max_length=262_144)
    device_signature: str = Field(pattern=r"^hmac-sha256:[0-9a-f]{64}$")
    measurement_quality: Literal[
        "coarse_local_aggregate", "owner_supplied_ics_projection"
    ] = "coarse_local_aggregate"
    clock_quality: Literal[
        "host_utc_clock", "ics_timezone_normalized"
    ] = "host_utc_clock"
    limitations: tuple[str, ...] = (
        "coarse category only",
        "no application identity or content retained",
        "not an interpretation of intent or productivity",
    )
    content_hash: str = ""

    @field_validator(
        "occurred_from", "occurred_to", "source_observed_at", "ingested_at",
        "fresh_until", "retention_expires_at"
    )
    @classmethod
    def normalize_time(cls, value: datetime, info) -> datetime:
        return _utc(value, name=info.field_name)

    @model_validator(mode="after")
    def bind_hash(self) -> "LifeContextObservationV2":
        if self.fresh_until <= self.source_observed_at:
            raise ValueError("freshness expiry must follow source observation")
        if self.retention_expires_at <= self.ingested_at:
            raise ValueError("canonical retention expiry must follow ingestion")
        try:
            signing_payload = json.loads(self.draft_signing_material)
        except json.JSONDecodeError as error:
            raise ValueError("draft signing material must be canonical JSON") from error
        if content_hash(signing_payload) != self.draft_content_hash:
            raise ValueError("draft signing material hash mismatch")
        expected_metadata = {
            "device_activity_summary": (
                "coarse_local_aggregate",
                "host_utc_clock",
                (
                    "coarse category only",
                    "no application identity or content retained",
                    "not an interpretation of intent or productivity",
                ),
            ),
            "calendar_availability_window": (
                "owner_supplied_ics_projection",
                "ics_timezone_normalized",
                (
                    "availability only; no subject, body, location, organizer, or attendees retained",
                    "owner-supplied snapshot can become outdated until manually replaced",
                    "missing calendar data is not negative evidence about the owner",
                ),
            ),
        }[self.observation_kind]
        if (
            self.measurement_quality,
            self.clock_quality,
            self.limitations,
        ) != expected_metadata:
            raise ValueError("observation measurement metadata must match its kind")
        expected = content_hash(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match LifeContextObservationV2")
        object.__setattr__(self, "content_hash", expected)
        return self


class ContextSourceHealthV2(StrictModel):
    schema_version: Literal[2] = 2
    health_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    source_instance_id: UUID
    capability_revision_id: UUID
    status: Literal[
        "unknown", "healthy", "degraded", "stale", "offline",
        "permission_revoked", "unsupported",
    ]
    checked_at: datetime
    last_successful_observation_id: UUID | None = None
    last_successful_observation_at: datetime | None = None
    coverage_from: datetime | None = None
    coverage_to: datetime | None = None
    safe_error_category: str | None = Field(default=None, max_length=100)
    adapter_version: str
    source_version: str
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    content_hash: str = ""

    @field_validator(
        "checked_at", "last_successful_observation_at", "coverage_from", "coverage_to"
    )
    @classmethod
    def normalize_time(cls, value: datetime | None, info) -> datetime | None:
        return None if value is None else _utc(value, name=info.field_name)

    @model_validator(mode="after")
    def bind_hash(self) -> "ContextSourceHealthV2":
        if (self.coverage_from is None) != (self.coverage_to is None):
            raise ValueError("coverage bounds must appear together")
        if self.coverage_from and self.coverage_to <= self.coverage_from:
            raise ValueError("health coverage must have positive duration")
        if self.status == "healthy" and (
            self.last_successful_observation_id is None
            or self.last_successful_observation_at is None
            or self.coverage_from is None
            or self.safe_error_category is not None
        ):
            raise ValueError("healthy source status requires exact successful coverage")
        if self.status != "healthy" and any(
            value is not None for value in (
                self.last_successful_observation_id,
                self.last_successful_observation_at,
                self.coverage_from,
                self.coverage_to,
            )
        ):
            raise ValueError("non-healthy source status cannot claim successful coverage")
        expected = content_hash(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match ContextSourceHealthV2")
        object.__setattr__(self, "content_hash", expected)
        return self


class ContextIngestResult(StrictModel):
    schema_version: Literal[1] = 1
    observation: LifeContextObservationV2
    idempotent_replay: bool


class ContextRetentionExpiryIntent(StrictModel):
    schema_version: Literal[1] = 1
    expiry_intent_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    source_event_id: UUID
    observation_id: UUID
    retention_policy_version: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,95}$")
    retention_expires_at: datetime
    planned_at: datetime
    content_hash: str = ""

    @field_validator("retention_expires_at", "planned_at")
    @classmethod
    def normalize_time(cls, value: datetime, info) -> datetime:
        return _utc(value, name=info.field_name)

    @model_validator(mode="after")
    def bind_hash(self) -> "ContextRetentionExpiryIntent":
        expected = content_hash(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match ContextRetentionExpiryIntent")
        object.__setattr__(self, "content_hash", expected)
        return self


class ContextRetentionExpiryReceipt(StrictModel):
    schema_version: Literal[1] = 1
    expiry_receipt_id: UUID = Field(default_factory=uuid7)
    expiry_intent_id: UUID
    owner_id: UUID
    source_event_id: UUID
    observation_id: UUID
    retention_policy_version: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,95}$")
    retention_expires_at: datetime
    erased_at: datetime
    directive_sequence: int = Field(gt=0)
    directive_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    absence_verified: Literal[True] = True
    content_hash: str = ""

    @field_validator("retention_expires_at", "erased_at")
    @classmethod
    def normalize_time(cls, value: datetime, info) -> datetime:
        return _utc(value, name=info.field_name)

    @model_validator(mode="after")
    def bind_hash(self) -> "ContextRetentionExpiryReceipt":
        expected = content_hash(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match ContextRetentionExpiryReceipt")
        object.__setattr__(self, "content_hash", expected)
        return self


class ContextRestoreQuarantine(StrictModel):
    """Fail-closed source quarantine created after every database restore."""

    schema_version: Literal[1] = 1
    quarantine_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    source_instance_id: UUID
    restore_id: str = Field(min_length=1, max_length=200)
    reason: Literal["backup_restore_requires_new_source_enrollment"] = (
        "backup_restore_requires_new_source_enrollment"
    )
    quarantined_at: datetime
    content_hash: str = ""

    @field_validator("quarantined_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _utc(value, name="quarantined_at")

    @model_validator(mode="after")
    def bind_hash(self) -> "ContextRestoreQuarantine":
        expected = content_hash(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match ContextRestoreQuarantine")
        object.__setattr__(self, "content_hash", expected)
        return self


class ContextSourceErasureTombstone(StrictModel):
    """Minimum content-free receipt preventing erased-source resurrection."""

    schema_version: Literal[1] = 1
    tombstone_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    source_instance_id: UUID
    registration_event_id: UUID
    erased_at: datetime
    directive_sequence: int = Field(gt=0)
    directive_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    absence_verified: Literal[True] = True
    content_hash: str = ""

    @field_validator("erased_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _utc(value, name="erased_at")

    @model_validator(mode="after")
    def bind_hash(self) -> "ContextSourceErasureTombstone":
        expected = content_hash(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match ContextSourceErasureTombstone")
        object.__setattr__(self, "content_hash", expected)
        return self


def classify_external_observation_eligibility(
    *,
    observation: LifeContextObservationV2 | None,
    health: ContextSourceHealthV2 | None,
    consent_status: Literal["active", "revoked", "expired", "missing"],
    as_of: datetime,
) -> str:
    """Classify use eligibility without turning absence into owner state."""

    instant = _utc(as_of, name="as_of")
    if consent_status != "active":
        return "ineligible_consent"
    if observation is None or health is None:
        return "unknown_not_negative_evidence"
    if health.status == "permission_revoked":
        return "ineligible_consent"
    if health.status != "healthy":
        return "unknown_not_negative_evidence"
    if health.last_successful_observation_id != observation.observation_id:
        return "unknown_not_negative_evidence"
    if (
        health.owner_id != observation.owner_id
        or health.source_instance_id != observation.source_instance_id
        or health.capability_revision_id != observation.capability_revision_id
    ):
        return "unknown_not_negative_evidence"
    if instant >= observation.retention_expires_at:
        return "ineligible_retention_expired"
    if instant >= observation.fresh_until:
        return "ineligible_stale"
    return "eligible_observation_only"
