"""Provider-neutral inference, routing, usage, and timing contracts."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from companion.events import ContentPart
from companion.ids import uuid7
from companion.policy import DataPolicy, PrivacyClass


ProviderClass = Literal["local_test", "self_hosted", "cloud"]
ExecutionEnvironment = Literal["local", "cloud"]
InferenceFailureCode = Literal[
    "invalid_request",
    "unsupported_capability",
    "privacy_constraint_unsatisfied",
    "model_unavailable",
    "provider_rate_limited",
    "provider_timeout",
    "context_limit_exceeded",
    "content_blocked",
    "stream_interrupted",
    "provider_protocol_error",
    "internal_error",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProviderCapabilities(StrictModel):
    schema_version: Literal[1] = 1
    provider_id: str = Field(min_length=1, max_length=200)
    provider_class: ProviderClass
    execution_environment: ExecutionEnvironment
    available_model_version_ids: tuple[str, ...] = Field(min_length=1)
    approved_privacy_classes: tuple[PrivacyClass, ...] = Field(min_length=1)
    supports_streaming: bool
    max_context_tokens: int = Field(gt=0)
    max_output_tokens: int = Field(gt=0)
    observed_at: datetime
    ttl_seconds: int = Field(gt=0)


class ProviderVersion(StrictModel):
    """Exact, content-free provenance for one verified serving target."""

    schema_version: Literal[1] = 1
    provider_id: str = Field(min_length=1, max_length=200)
    provider_class: ProviderClass
    execution_environment: ExecutionEnvironment
    provider_adapter_version_id: str = Field(min_length=1, max_length=300)
    serving_engine: str = Field(min_length=1, max_length=200)
    serving_engine_version: str = Field(min_length=1, max_length=300)
    serving_config_version: str = Field(min_length=1, max_length=300)
    model_version_id: str = Field(min_length=1, max_length=500)
    tokenizer_version_id: str = Field(min_length=1, max_length=500)
    model_artifact_hash: str | None = Field(
        default=None, pattern=r"^sha256:[0-9a-f]{64}$"
    )
    active_adapter_version_id: str | None = Field(
        default=None, min_length=1, max_length=500
    )
    active_adapter_artifact_hash: str | None = Field(
        default=None, pattern=r"^sha256:[0-9a-f]{64}$"
    )
    runtime_attestation_id: str | None = Field(default=None, min_length=1, max_length=300)
    runtime_attestation_hash: str | None = Field(
        default=None, pattern=r"^sha256:[0-9a-f]{64}$"
    )
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_runtime_attestation(self) -> "ProviderVersion":
        if (self.active_adapter_version_id is None) != (
            self.active_adapter_artifact_hash is None
        ):
            raise ValueError("active adapter version and hash must appear together")
        if (self.runtime_attestation_id is None) != (
            self.runtime_attestation_hash is None
        ):
            raise ValueError("runtime attestation ID and hash must appear together")
        if self.provider_class == "self_hosted" and self.runtime_attestation_id is None:
            raise ValueError("self-hosted provider version requires runtime attestation")
        return self


class ProviderHealth(StrictModel):
    status: Literal["healthy", "degraded", "unavailable"]
    observed_at: datetime
    latency_ms: float = Field(ge=0)
    loaded_model_version_ids: tuple[str, ...]
    reasons: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_latency(self) -> "ProviderHealth":
        if not math.isfinite(self.latency_ms):
            raise ValueError("provider health latency must be finite")
        return self


class InferenceMessage(StrictModel):
    role: Literal["system", "user", "assistant"]
    content_parts: tuple[ContentPart, ...] = Field(min_length=1)
    source_refs: tuple[str, ...]


class GenerationSettings(StrictModel):
    max_output_tokens: int = Field(gt=0)
    temperature: float = Field(ge=0, le=2)
    top_p: float = Field(gt=0, le=1)
    seed: int | None = None
    stop: tuple[str, ...] = ()


class InferenceConstraints(StrictModel):
    stream: bool
    timeout_ms: int = Field(gt=0)
    effective_data_policy: DataPolicy
    allowed_execution_environments: tuple[ExecutionEnvironment, ...] = Field(
        min_length=1
    )


class InferenceRequest(StrictModel):
    schema_version: Literal[1] = 1
    inference_request_id: UUID = Field(default_factory=uuid7)
    request_id: UUID
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    purpose: Literal["companion_response"] = "companion_response"
    brain_role: Literal["personal"] = "personal"
    model_target_logical_profile: Literal["personal-balanced"] = "personal-balanced"
    messages: tuple[InferenceMessage, ...] = Field(min_length=1)
    context_pack_id: UUID
    response_format: Literal["text"] = "text"
    generation: GenerationSettings
    constraints: InferenceConstraints
    metadata: dict[str, str]


class ProviderReference(StrictModel):
    provider_id: str = Field(min_length=1, max_length=200)
    provider_request_id: str = Field(min_length=1, max_length=500)
    provider_class: ProviderClass


class VersionReferences(StrictModel):
    model_version_id: str = Field(min_length=1, max_length=500)
    adapter_version_id: str | None = Field(default=None, max_length=500)
    tokenizer_version_id: str = Field(min_length=1, max_length=500)
    serving_config_version: str = Field(min_length=1, max_length=500)
    provider_adapter_version_id: str | None = Field(
        default=None, min_length=1, max_length=500
    )
    serving_engine: str | None = Field(default=None, min_length=1, max_length=200)
    serving_engine_version: str | None = Field(
        default=None, min_length=1, max_length=300
    )
    model_artifact_hash: str | None = Field(
        default=None, pattern=r"^sha256:[0-9a-f]{64}$"
    )
    runtime_attestation_id: str | None = Field(default=None, min_length=1, max_length=300)
    runtime_attestation_hash: str | None = Field(
        default=None, pattern=r"^sha256:[0-9a-f]{64}$"
    )

    @model_validator(mode="after")
    def validate_runtime_attestation(self) -> "VersionReferences":
        if (self.runtime_attestation_id is None) != (
            self.runtime_attestation_hash is None
        ):
            raise ValueError("runtime attestation ID and hash must appear together")
        return self


class TokenUsage(StrictModel):
    prompt_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    token_count_source: Literal["provider", "estimator"]

    @model_validator(mode="after")
    def validate_total(self) -> "TokenUsage":
        if self.total_tokens != self.prompt_tokens + self.output_tokens:
            raise ValueError("total_tokens must equal prompt_tokens plus output_tokens")
        return self


class InferenceTiming(StrictModel):
    """Client-observed total is required; unavailable provider timings remain null."""

    queue: float | None = Field(default=None, ge=0)
    time_to_first_token: float | None = Field(default=None, ge=0)
    generation: float | None = Field(default=None, ge=0)
    total: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_finite_timings(self) -> "InferenceTiming":
        for name in ("queue", "time_to_first_token", "generation", "total"):
            value = getattr(self, name)
            if value is not None and not math.isfinite(value):
                raise ValueError(f"{name} timing must be finite when present")
        return self


class InferenceResponse(StrictModel):
    schema_version: Literal[1] = 1
    inference_response_id: UUID = Field(default_factory=uuid7)
    inference_request_id: UUID
    request_id: UUID
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    status: Literal["completed"] = "completed"
    output_parts: tuple[ContentPart, ...] = Field(min_length=1)
    finish_reason: Literal["stop", "length"]
    provider: ProviderReference
    versions: VersionReferences
    usage: TokenUsage
    timing_ms: InferenceTiming
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class InferenceFailure(StrictModel):
    """Safe terminal failure metadata; never contains prompts or raw provider bodies."""

    schema_version: Literal[1] = 1
    inference_request_id: UUID
    request_id: UUID
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    provider_id: str = Field(min_length=1, max_length=200)
    provider_class: ProviderClass
    code: InferenceFailureCode
    retryable: bool
    safe_message: str = Field(min_length=1, max_length=500)
    provider_status_code: int | None = Field(default=None, ge=100, le=599)
    provider_error_code: str | None = Field(default=None, min_length=1, max_length=200)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class InferenceStreamEvent(StrictModel):
    """Ordered, discriminated stream envelope with exactly one payload shape."""

    schema_version: Literal[1] = 1
    event: Literal[
        "response_started",
        "output_delta",
        "response_completed",
        "response_failed",
    ]
    sequence_number: int = Field(ge=0)
    inference_response_id: UUID
    inference_request_id: UUID
    request_id: UUID
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    delta: ContentPart | None = None
    response: InferenceResponse | None = None
    failure: InferenceFailure | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def __get_pydantic_json_schema__(
        cls, core_schema: Any, handler: Any
    ) -> dict[str, Any]:
        """Expose the runtime payload invariant to schema-only consumers."""

        schema = handler(core_schema)
        schema.setdefault("allOf", []).append(
            {
                "oneOf": [
                    {
                        "properties": {
                            "event": {"const": "response_started"},
                            "delta": {"type": "null"},
                            "response": {"type": "null"},
                            "failure": {"type": "null"},
                        }
                    },
                    {
                        "properties": {
                            "event": {"const": "output_delta"},
                            "delta": {"not": {"type": "null"}},
                            "response": {"type": "null"},
                            "failure": {"type": "null"},
                        },
                        "required": ["delta"],
                    },
                    {
                        "properties": {
                            "event": {"const": "response_completed"},
                            "delta": {"type": "null"},
                            "response": {"not": {"type": "null"}},
                            "failure": {"type": "null"},
                        },
                        "required": ["response"],
                    },
                    {
                        "properties": {
                            "event": {"const": "response_failed"},
                            "delta": {"type": "null"},
                            "response": {"type": "null"},
                            "failure": {"not": {"type": "null"}},
                        },
                        "required": ["failure"],
                    },
                ]
            }
        )
        return schema

    @model_validator(mode="after")
    def validate_event_payload(self) -> "InferenceStreamEvent":
        required_payload = {
            "response_started": (False, False, False),
            "output_delta": (True, False, False),
            "response_completed": (False, True, False),
            "response_failed": (False, False, True),
        }[self.event]
        actual_payload = (
            self.delta is not None,
            self.response is not None,
            self.failure is not None,
        )
        if actual_payload != required_payload:
            raise ValueError(f"{self.event} has an invalid stream payload shape")
        if self.response is not None:
            if (
                self.response.inference_response_id != self.inference_response_id
                or self.response.inference_request_id != self.inference_request_id
                or self.response.request_id != self.request_id
                or self.response.trace_id != self.trace_id
            ):
                raise ValueError("completed stream response lineage does not match envelope")
        if self.failure is not None:
            if (
                self.failure.inference_request_id != self.inference_request_id
                or self.failure.request_id != self.request_id
                or self.failure.trace_id != self.trace_id
            ):
                raise ValueError("failed stream lineage does not match envelope")
        return self


class InferenceResponseLineageError(ValueError):
    """A provider returned a response for a different request, route, or version."""


def validate_inference_response_lineage(
    *,
    request: InferenceRequest,
    response: InferenceResponse,
    expected_provider_id: str,
    expected_provider_class: ProviderClass,
    expected_model_version_id: str,
    expected_provider_adapter_version_id: str,
) -> InferenceResponse:
    """Independently bind normalized provider output to its exact routed input."""

    mismatches: list[str] = []
    if response.inference_request_id != request.inference_request_id:
        mismatches.append("inference_request_id")
    if response.request_id != request.request_id:
        mismatches.append("request_id")
    if response.trace_id != request.trace_id:
        mismatches.append("trace_id")
    if response.provider.provider_id != expected_provider_id:
        mismatches.append("provider_id")
    if response.provider.provider_class != expected_provider_class:
        mismatches.append("provider_class")
    if response.versions.model_version_id != expected_model_version_id:
        mismatches.append("model_version_id")
    if (
        response.versions.provider_adapter_version_id
        != expected_provider_adapter_version_id
    ):
        mismatches.append("provider_adapter_version_id")
    if response.versions.serving_engine is None:
        mismatches.append("serving_engine")
    if response.versions.serving_engine_version is None:
        mismatches.append("serving_engine_version")
    if expected_provider_class == "self_hosted" and (
        response.versions.runtime_attestation_id is None
        or response.versions.runtime_attestation_hash is None
    ):
        mismatches.append("runtime_attestation")
    if mismatches:
        raise InferenceResponseLineageError(
            "inference response lineage mismatch: " + ", ".join(mismatches)
        )
    return response


class RouteDecision(StrictModel):
    schema_version: Literal[1] = 1
    route_decision_id: UUID = Field(default_factory=uuid7)
    request_id: UUID
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    router_version: Literal[
        "stage1-single-provider-router-v1",
        "single-provider-router-v2",
    ] = "single-provider-router-v2"
    selected_provider_id: str = Field(min_length=1, max_length=200)
    selected_model_version_id: str = Field(min_length=1, max_length=500)
    execution_environment: ExecutionEnvironment
    effective_data_policy_revision_id: UUID
    eligible_candidates: tuple[str, ...] = Field(min_length=1)
    excluded_candidates: tuple[dict[str, str], ...] = ()
    reason: Literal[
        "only_eligible_stage1_provider",
        "only_eligible_configured_provider",
    ] = "only_eligible_configured_provider"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
