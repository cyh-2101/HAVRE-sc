"""DeepSeek cloud adapter behind HAVRE's provider-neutral inference port.

The adapter is disabled unless a caller supplies an explicit Product Owner
authorization reference and opts in. It reads its credential only from
``DEEPSEEK_API_KEY`` and accepts only explicitly authorized PUBLIC synthetic
requests for the current ceiling experiment.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from time import perf_counter_ns
from typing import Any, Callable, Literal

from pydantic import ValidationError

try:  # Loaded lazily so contract-only tooling still works without httpx.
    import httpx as _httpx
except ModuleNotFoundError:  # pragma: no cover
    _httpx = None

from companion.events import TextContentPart
from companion.hashing import content_hash
from companion.ids import uuid7
from companion.policy import PrivacyClass
from companion.tracing import parse_traceparent
from mlsys.contracts import (
    InferenceFailure,
    InferenceFailureCode,
    InferenceRequest,
    InferenceResponse,
    InferenceResponseLineageError,
    InferenceStreamEvent,
    InferenceTiming,
    ProviderCapabilities,
    ProviderHealth,
    ProviderReference,
    ProviderVersion,
    TokenUsage,
    VersionReferences,
    validate_inference_response_lineage,
)
from mlsys.serving.provider import ProviderInferenceError, ProviderVersionError


DEEPSEEK_API_KEY_ENV = "DEEPSEEK_API_KEY"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL_ID = "deepseek-v4-pro"
DEEPSEEK_MANUAL_PROVIDER_ADAPTER_VERSION = "deepseek-cloud-provider-adapter-v3-owner-manual"
# The public API exposes a mutable model alias, not an independently verifiable
OWNER_MANUAL_BOUNDARY = "OWNER_MANUAL_SELECTED_CONTEXT_V1"
OWNER_MANUAL_AUTHORIZATION_REF = (
    "product-owner/manual-strong-brain-selected-context-2026-08-28"
)
# immutable revision. Do not manufacture stronger lineage than the provider
# supplies: the canonical version reference is therefore the verified alias.
DEEPSEEK_MODEL_VERSION = DEEPSEEK_MODEL_ID
DEEPSEEK_PROVIDER_ID = "deepseek-cloud"
DEEPSEEK_PROVIDER_ADAPTER_VERSION = "deepseek-cloud-provider-adapter-v2"
PUBLIC_SYNTHETIC_BOUNDARY = "PUBLIC_SYNTHETIC"
STRONG_CLOUD_BRAIN_AUTHORIZATION_REF = (
    "product-owner/strong-cloud-brain-ceiling-2026-08-26"
)
_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}")


def cloud_request_binding_hash(
    request: InferenceRequest,
    *,
    thinking: Literal["enabled", "disabled"],
    reasoning_effort: Literal["low", "high", "max"],
) -> str:
    """Hash the exact canonical request and provider generation mode.

    The binding field itself is excluded so callers can add the resulting hash
    to immutable request metadata without a recursive hash definition.
    """

    canonical = request.model_dump(mode="json")
    metadata = dict(canonical.get("metadata", {}))
    metadata.pop("cloud_request_binding_hash", None)
    canonical["metadata"] = metadata
    return content_hash(
        {
            "provider_id": DEEPSEEK_PROVIDER_ID,
            "model_alias": DEEPSEEK_MODEL_ID,
            "thinking": thinking,
            "reasoning_effort": reasoning_effort if thinking == "enabled" else None,
            "canonical_inference_request": canonical,
        }
    )


def bind_cloud_experiment_request(
    request: InferenceRequest,
    *,
    thinking: Literal["enabled", "disabled"],
    reasoning_effort: Literal["low", "high", "max"] = "high",
) -> InferenceRequest:
    binding = cloud_request_binding_hash(
        request, thinking=thinking, reasoning_effort=reasoning_effort
    )
    return request.model_copy(
        update={"metadata": {**request.metadata, "cloud_request_binding_hash": binding}}
    )

_SAFE_MESSAGES = {
    "invalid_request": "The cloud provider rejected the inference request.",
    "unsupported_capability": "The cloud provider does not support a required capability.",
    "privacy_constraint_unsatisfied": "The cloud provider is not eligible for this request.",
    "model_unavailable": "The configured cloud model is unavailable.",
    "provider_rate_limited": "The cloud provider is temporarily rate limited.",
    "provider_timeout": "The cloud provider exceeded its time limit.",
    "context_limit_exceeded": "The request exceeds the cloud model context limit.",
    "content_blocked": "The cloud provider did not return content for this request.",
    "stream_interrupted": "The cloud provider stream ended before completion.",
    "provider_protocol_error": "The cloud provider returned an invalid response.",
    "internal_error": "The cloud inference adapter could not complete the request.",
}


class DeepSeekCloudProvider:
    """Map canonical HAVRE requests to DeepSeek Chat Completions."""

    provider_id = DEEPSEEK_PROVIDER_ID
    provider_class = "cloud"
    execution_environment = "cloud"

    def __init__(
        self,
        *,
        enabled: bool = False,
        explicit_authorization_ref: str | None = None,
        allowed_fixture_hashes: frozenset[str] = frozenset(),
        allowed_request_hashes: frozenset[str] = frozenset(),
        thinking: Literal["enabled", "disabled"] = "disabled",
        mode: Literal["public_synthetic", "owner_manual"] = "public_synthetic",
        manual_permit_validator: Callable[[InferenceRequest], bool] | None = None,
        reasoning_effort: Literal["low", "high", "max"] = "high",
        model_id: str = DEEPSEEK_MODEL_ID,
        model_version_id: str = DEEPSEEK_MODEL_VERSION,
        max_context_tokens: int = 1_000_000,
        max_output_tokens: int = 384_000,
        capability_ttl_seconds: int = 30,
        client: Any | None = None,
        transport: Any | None = None,
    ) -> None:
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be a boolean")
        if thinking not in {"enabled", "disabled"}:
            raise ValueError("thinking must be enabled or disabled")
        if mode not in {"public_synthetic", "owner_manual"}:
            raise ValueError("unsupported DeepSeek governance mode")
        if reasoning_effort not in {"low", "high", "max"}:
            raise ValueError("unsupported DeepSeek reasoning effort")
        if model_id != DEEPSEEK_MODEL_ID:
            raise ValueError("unverified DeepSeek model ID")
        if model_version_id != DEEPSEEK_MODEL_VERSION:
            raise ValueError("unverified DeepSeek model version")
        if max_context_tokens <= 0 or max_output_tokens <= 0:
            raise ValueError("provider token limits must be positive")
        if capability_ttl_seconds <= 0:
            raise ValueError("capability_ttl_seconds must be positive")
        expected_authorization = (
            STRONG_CLOUD_BRAIN_AUTHORIZATION_REF
            if mode == "public_synthetic"
            else OWNER_MANUAL_AUTHORIZATION_REF
        )
        if enabled and explicit_authorization_ref != expected_authorization:
            if mode == "public_synthetic":
                raise ValueError(
                    "enabled cloud provider requires the exact experiment authorization"
                )
            raise ValueError(
                "enabled cloud provider requires the exact manual authorization"
            )
        if enabled and mode == "public_synthetic" and (
            not allowed_fixture_hashes or not allowed_request_hashes
        ):
            raise ValueError("enabled cloud provider requires a sealed experiment permit")
        if enabled and mode == "owner_manual" and manual_permit_validator is None:
            raise ValueError(
                "manual owner mode requires a durable permit validator"
            )
        if any(_SHA256_RE.fullmatch(value) is None for value in allowed_fixture_hashes):
            raise ValueError("experiment permit contains an invalid fixture hash")
        if any(_SHA256_RE.fullmatch(value) is None for value in allowed_request_hashes):
            raise ValueError("experiment permit contains an invalid request hash")
        if client is not None and transport is not None:
            raise ValueError("client and transport cannot both be provided")
        if _httpx is None:
            raise RuntimeError("httpx is required to construct DeepSeekCloudProvider")

        self.enabled = enabled
        self.explicit_authorization_ref = (
            explicit_authorization_ref.strip()
            if explicit_authorization_ref is not None
            else None
        )
        self.allowed_fixture_hashes = allowed_fixture_hashes
        self.allowed_request_hashes = allowed_request_hashes
        self.thinking = thinking
        self.reasoning_effort = reasoning_effort
        self.mode = mode
        self.manual_permit_validator = manual_permit_validator
        self.model_id = model_id
        self.model_version_id = model_version_id
        self.max_context_tokens = max_context_tokens
        self.max_output_tokens = max_output_tokens
        self.capability_ttl_seconds = capability_ttl_seconds

        if enabled:
            api_key = os.environ.get(DEEPSEEK_API_KEY_ENV)
            if api_key is None or not api_key.strip():
                raise ValueError(f"{DEEPSEEK_API_KEY_ENV} is required")
            headers = {
                "Accept": "application/json",
                "Authorization": f"Bearer {api_key.strip()}",
            }
        else:
            headers = {"Accept": "application/json"}

        if client is None:
            self._client = _httpx.AsyncClient(
                base_url=DEEPSEEK_BASE_URL,
                headers=headers,
                trust_env=False,
                follow_redirects=False,
                transport=transport,
            )
            self._owns_client = True
        else:
            self._client = client
            self._owns_client = False

    async def capabilities(self) -> ProviderCapabilities:
        self._require_enabled()
        return ProviderCapabilities(
            provider_id=DEEPSEEK_PROVIDER_ID,
            provider_class=self.provider_class,
            execution_environment=self.execution_environment,
            available_model_version_ids=(self.model_version_id,),
            approved_privacy_classes=(
                (PrivacyClass.PUBLIC,) if self.mode == "public_synthetic"
                else (PrivacyClass.HIGHLY_PRIVATE,)
            ),
            supports_streaming=True,
            max_context_tokens=self.max_context_tokens,
            max_output_tokens=self.max_output_tokens,
            observed_at=datetime.now(UTC),
            ttl_seconds=self.capability_ttl_seconds,
        )

    async def health(self) -> ProviderHealth:
        started_ns = perf_counter_ns()
        if not self.enabled:
            return ProviderHealth(
                status="unavailable",
                observed_at=datetime.now(UTC),
                latency_ms=0,
                loaded_model_version_ids=(),
                reasons=("cloud_provider_disabled",),
            )
        try:
            await self._verify_model_available()
            loaded = (self.model_version_id,)
            reasons: tuple[str, ...] = ()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            loaded = ()
            reasons = (self._health_exception_reason(error),)
        return ProviderHealth(
            status="healthy" if not reasons else "unavailable",
            observed_at=datetime.now(UTC),
            latency_ms=round((perf_counter_ns() - started_ns) / 1_000_000, 3),
            loaded_model_version_ids=loaded,
            reasons=reasons,
        )

    async def version(self) -> ProviderVersion:
        self._require_enabled()
        await self._verify_model_available()
        return ProviderVersion(
            provider_id=DEEPSEEK_PROVIDER_ID,
            provider_class=self.provider_class,
            execution_environment=self.execution_environment,
            provider_adapter_version_id=self._provider_adapter_version,
            serving_engine="deepseek-api",
            serving_engine_version="openai-chat-completions-2026-08-26",
            serving_config_version=self._serving_config_version,
            model_version_id=self.model_version_id,
            tokenizer_version_id="deepseek-api-managed-tokenizer-v1",
        )

    async def generate(self, request: InferenceRequest) -> InferenceResponse:
        started_ns = perf_counter_ns()
        try:
            self._validate_request(request, expected_stream=False)
            response = await self._client.post(
                "/chat/completions",
                json=self._request_payload(request, stream=False),
                headers=self._request_headers(request),
                timeout=request.constraints.timeout_ms / 1000,
            )
            self._reject_redirect(request, response)
            self._raise_for_status(request, response)
            normalized = self._normalize_completion(
                request=request,
                payload=self._json_object(response),
                total_ms=(perf_counter_ns() - started_ns) / 1_000_000,
            )
            return self._validate_lineage(request, normalized)
        except ProviderInferenceError:
            raise
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise ProviderInferenceError(
                self._failure_from_exception(request, error)
            ) from None

    async def stream(
        self, request: InferenceRequest
    ) -> AsyncIterator[InferenceStreamEvent]:
        response_id = uuid7()
        sequence = 0
        started_ns = perf_counter_ns()
        terminal_emitted = False
        provider_response_started = False
        common = self._stream_common(request, response_id)
        yield InferenceStreamEvent(
            event="response_started", sequence_number=sequence, **common
        )
        sequence += 1
        try:
            self._validate_request(request, expected_stream=True)
            async with self._client.stream(
                "POST",
                "/chat/completions",
                json=self._request_payload(request, stream=True),
                headers=self._request_headers(request),
                timeout=request.constraints.timeout_ms / 1000,
            ) as response:
                self._reject_redirect(request, response)
                self._raise_for_status(request, response)
                provider_response_started = True
                text_parts: list[str] = []
                provider_request_id: str | None = None
                finish_reason: str | None = None
                usage: TokenUsage | None = None
                first_text_ns: int | None = None
                saw_done = False
                async for data in self._iter_sse_data(response):
                    if data == "[DONE]":
                        saw_done = True
                        break
                    try:
                        chunk = json.loads(data)
                    except (TypeError, ValueError):
                        raise ProviderInferenceError(
                            self._failure(request, "provider_protocol_error", False)
                        ) from None
                    if not isinstance(chunk, dict):
                        raise ProviderInferenceError(
                            self._failure(request, "provider_protocol_error", False)
                        )
                    chunk_id = chunk.get("id")
                    if chunk_id is not None:
                        if not isinstance(chunk_id, str) or not chunk_id:
                            raise ProviderInferenceError(
                                self._failure(request, "provider_protocol_error", False)
                            )
                        if provider_request_id is None:
                            provider_request_id = chunk_id
                        elif provider_request_id != chunk_id:
                            raise ProviderInferenceError(
                                self._failure(request, "provider_protocol_error", False)
                            )
                    self._validate_model(request, chunk.get("model"))
                    if chunk.get("usage") is not None:
                        usage = self._parse_usage(request, chunk["usage"])
                    choices = chunk.get("choices")
                    if choices == [] and chunk.get("usage") is not None:
                        continue
                    if not isinstance(choices, list) or not choices:
                        raise ProviderInferenceError(
                            self._failure(request, "provider_protocol_error", False)
                        )
                    choice = choices[0]
                    if not isinstance(choice, dict):
                        raise ProviderInferenceError(
                            self._failure(request, "provider_protocol_error", False)
                        )
                    if choice.get("finish_reason") is not None:
                        finish_reason = self._finish_reason(
                            request, choice.get("finish_reason")
                        )
                    delta = choice.get("delta")
                    if not isinstance(delta, dict):
                        raise ProviderInferenceError(
                            self._failure(request, "provider_protocol_error", False)
                        )
                    # Never persist or emit provider chain-of-thought. Only final
                    # answer content crosses the canonical inference boundary.
                    text = delta.get("content")
                    if text is None or text == "":
                        continue
                    if not isinstance(text, str):
                        raise ProviderInferenceError(
                            self._failure(request, "provider_protocol_error", False)
                        )
                    if first_text_ns is None:
                        first_text_ns = perf_counter_ns()
                    text_parts.append(text)
                    yield InferenceStreamEvent(
                        event="output_delta",
                        sequence_number=sequence,
                        delta=TextContentPart(text=text),
                        **common,
                    )
                    sequence += 1

                if not saw_done:
                    raise ProviderInferenceError(
                        self._failure(request, "stream_interrupted", True)
                    )
                if not text_parts:
                    raise ProviderInferenceError(
                        self._failure(
                            request,
                            "content_blocked",
                            finish_reason == "length",
                            provider_error_code=(
                                "empty_final_content_output_limit"
                                if finish_reason == "length"
                                else "empty_final_content"
                            ),
                        )
                    )
                if (
                    provider_request_id is None
                    or finish_reason is None
                    or usage is None
                    or first_text_ns is None
                ):
                    raise ProviderInferenceError(
                        self._failure(request, "provider_protocol_error", False)
                    )
                ended_ns = perf_counter_ns()
                normalized = InferenceResponse(
                    inference_response_id=response_id,
                    inference_request_id=request.inference_request_id,
                    request_id=request.request_id,
                    trace_id=request.trace_id,
                    output_parts=(TextContentPart(text="".join(text_parts)),),
                    finish_reason=finish_reason,
                    provider=ProviderReference(
                        provider_id=DEEPSEEK_PROVIDER_ID,
                        provider_request_id=provider_request_id,
                        provider_class=self.provider_class,
                    ),
                    versions=self._version_references(),
                    usage=usage,
                    timing_ms=InferenceTiming(
                        queue=None,
                        time_to_first_token=round(
                            (first_text_ns - started_ns) / 1_000_000, 3
                        ),
                        generation=round(
                            (ended_ns - first_text_ns) / 1_000_000, 3
                        ),
                        total=round((ended_ns - started_ns) / 1_000_000, 3),
                    ),
                )
                normalized = self._validate_lineage(request, normalized)
                terminal_emitted = True
                yield InferenceStreamEvent(
                    event="response_completed",
                    sequence_number=sequence,
                    response=normalized,
                    **common,
                )
        except ProviderInferenceError as error:
            if not terminal_emitted:
                yield InferenceStreamEvent(
                    event="response_failed",
                    sequence_number=sequence,
                    failure=error.failure,
                    **self._stream_common(request, response_id),
                )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if terminal_emitted:
                return
            is_transport_error = (
                _httpx is not None and isinstance(error, _httpx.RequestError)
            )
            failure = (
                self._failure(request, "stream_interrupted", True)
                if provider_response_started and is_transport_error
                else self._failure_from_exception(request, error)
            )
            yield InferenceStreamEvent(
                event="response_failed",
                sequence_number=sequence,
                failure=failure,
                **self._stream_common(request, response_id),
            )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @property
    def _serving_config_version(self) -> str:
        return f"deepseek-v4-pro-{self.thinking}-{self.mode}-v3"

    @property
    def _provider_adapter_version(self) -> str:
        return (
            DEEPSEEK_PROVIDER_ADAPTER_VERSION
            if self.mode == "public_synthetic"
            else DEEPSEEK_MANUAL_PROVIDER_ADAPTER_VERSION
        )

    def _version_references(self) -> VersionReferences:
        return VersionReferences(
            model_version_id=self.model_version_id,
            adapter_version_id=None,
            tokenizer_version_id="deepseek-api-managed-tokenizer-v1",
            serving_config_version=self._serving_config_version,
            provider_adapter_version_id=self._provider_adapter_version,
            serving_engine="deepseek-api",
            serving_engine_version="openai-chat-completions-2026-08-26",
        )

    async def _verify_model_available(self) -> None:
        self._require_enabled()
        try:
            response = await self._client.get("/models", timeout=10.0)
            if not 200 <= response.status_code < 300:
                raise ProviderVersionError(
                    code="model_unavailable",
                    retryable=response.status_code >= 500,
                    safe_message="The DeepSeek model endpoint is unavailable.",
                )
            payload = self._json_object(response)
            data = payload.get("data")
            if not isinstance(data, list) or not any(
                isinstance(item, dict) and item.get("id") == self.model_id
                for item in data
            ):
                raise _ProviderProtocolError("configured model is not listed")
        except asyncio.CancelledError:
            raise
        except ProviderVersionError:
            raise
        except Exception as error:
            if _httpx is not None and isinstance(error, _httpx.RequestError):
                raise ProviderVersionError(
                    code="model_unavailable",
                    retryable=True,
                    safe_message="The DeepSeek model check is unavailable.",
                ) from None
            raise ProviderVersionError(
                code="provider_protocol_error",
                retryable=False,
                safe_message="The DeepSeek model endpoint returned an invalid response.",
            ) from None

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise ProviderVersionError(
                code="unsupported_capability",
                retryable=False,
                safe_message="The cloud provider is disabled.",
            )

    def _validate_request(
        self, request: InferenceRequest, *, expected_stream: bool
    ) -> None:
        try:
            self._require_enabled()
        except ProviderVersionError as error:
            raise ProviderInferenceError(
                self._failure(request, error.code, error.retryable)
            ) from None
        if request.constraints.stream is not expected_stream:
            raise ProviderInferenceError(
                self._failure(request, "unsupported_capability", False)
            )
        if "cloud" not in request.constraints.allowed_execution_environments:
            raise ProviderInferenceError(
                self._failure(request, "privacy_constraint_unsatisfied", False)
            )
        policy = request.constraints.effective_data_policy
        request_hash = request.metadata.get("cloud_request_binding_hash", "")
        expected_request_hash = cloud_request_binding_hash(
            request, thinking=self.thinking, reasoning_effort=self.reasoning_effort
        )
        common_valid = (
            policy.cloud_eligible
            and policy.decision_source == "owner_explicit"
            and policy.authorization_ref == self.explicit_authorization_ref
            and request.metadata.get("cloud_authorization_ref")
            == self.explicit_authorization_ref
            and isinstance(request_hash, str)
            and _SHA256_RE.fullmatch(request_hash) is not None
            and request_hash == expected_request_hash
        )
        if self.mode == "owner_manual":
            disclosure_id = request.metadata.get("cloud_disclosure_id", "")
            permit_valid = (
                self.manual_permit_validator(request)
                if self.manual_permit_validator is not None and common_valid
                else False
            )
            valid = (
                common_valid
                and policy.privacy_class is PrivacyClass.HIGHLY_PRIVATE
                and request.metadata.get("cloud_data_boundary")
                == OWNER_MANUAL_BOUNDARY
                and isinstance(disclosure_id, str)
                and re.fullmatch(
                    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
                    r"[0-9a-f]{4}-[0-9a-f]{12}",
                    disclosure_id,
                ) is not None
                and permit_valid
            )
        else:
            fixture_hash = request.metadata.get("evaluation_fixture_hash", "")
            valid = (
                common_valid
                and policy.privacy_class is PrivacyClass.PUBLIC
                and request.metadata.get("evaluation_data_boundary")
                == PUBLIC_SYNTHETIC_BOUNDARY
                and isinstance(fixture_hash, str)
                and _SHA256_RE.fullmatch(fixture_hash) is not None
                and fixture_hash in self.allowed_fixture_hashes
                and request_hash in self.allowed_request_hashes
            )
        if not valid:
            raise ProviderInferenceError(
                self._failure(request, "privacy_constraint_unsatisfied", False)
            )
        if request.generation.max_output_tokens > self.max_output_tokens:
            raise ProviderInferenceError(
                self._failure(request, "unsupported_capability", False)
            )
        traceparent = request.metadata.get("traceparent")
        if traceparent is not None:
            parsed = parse_traceparent(traceparent)
            if parsed is None or parsed[0] != request.trace_id:
                raise ProviderInferenceError(
                    self._failure(request, "invalid_request", False)
                )

    def _request_payload(
        self, request: InferenceRequest, *, stream: bool
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": self.model_id,
            "messages": [
                {
                    "role": message.role,
                    "content": "\n".join(part.text for part in message.content_parts),
                }
                for message in request.messages
            ],
            "max_tokens": request.generation.max_output_tokens,
            "stream": stream,
            "thinking": {"type": self.thinking},
            "user_id": (
                "havre-public-synthetic-eval" if self.mode == "public_synthetic"
                else "havre-owner-manual-inference"
            ),
        }
        if self.thinking == "enabled":
            payload["reasoning_effort"] = self.reasoning_effort
        else:
            payload["temperature"] = request.generation.temperature
            payload["top_p"] = request.generation.top_p
        if request.generation.stop:
            payload["stop"] = list(request.generation.stop)
        if stream:
            payload["stream_options"] = {"include_usage": True}
        return payload

    @staticmethod
    def _request_headers(request: InferenceRequest) -> dict[str, str]:
        headers = {
            "Accept": (
                "text/event-stream"
                if request.constraints.stream
                else "application/json"
            ),
            "X-HAVRE-Inference-Request-ID": str(request.inference_request_id),
        }
        traceparent = request.metadata.get("traceparent")
        if traceparent is not None:
            headers["traceparent"] = traceparent
        return headers

    def _normalize_completion(
        self,
        *,
        request: InferenceRequest,
        payload: dict[str, object],
        total_ms: float,
    ) -> InferenceResponse:
        provider_request_id = payload.get("id")
        if not isinstance(provider_request_id, str) or not provider_request_id:
            raise ProviderInferenceError(
                self._failure(request, "provider_protocol_error", False)
            )
        self._validate_model(request, payload.get("model"))
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ProviderInferenceError(
                self._failure(request, "provider_protocol_error", False)
            )
        choice = choices[0]
        message = choice.get("message")
        if not isinstance(message, dict):
            raise ProviderInferenceError(
                self._failure(request, "provider_protocol_error", False)
            )
        output = message.get("content")
        if not isinstance(output, str) or not output:
            raise ProviderInferenceError(
                self._failure(
                    request,
                    "content_blocked",
                    choice.get("finish_reason") == "length",
                    provider_error_code=(
                        "empty_final_content_output_limit"
                        if choice.get("finish_reason") == "length"
                        else "empty_final_content"
                    ),
                )
            )
        return InferenceResponse(
            inference_request_id=request.inference_request_id,
            request_id=request.request_id,
            trace_id=request.trace_id,
            output_parts=(TextContentPart(text=output),),
            finish_reason=self._finish_reason(request, choice.get("finish_reason")),
            provider=ProviderReference(
                provider_id=DEEPSEEK_PROVIDER_ID,
                provider_request_id=provider_request_id,
                provider_class=self.provider_class,
            ),
            versions=self._version_references(),
            usage=self._parse_usage(request, payload.get("usage")),
            timing_ms=InferenceTiming(total=round(total_ms, 3)),
        )

    def _parse_usage(self, request: InferenceRequest, raw: object) -> TokenUsage:
        if not isinstance(raw, dict):
            raise ProviderInferenceError(
                self._failure(request, "provider_protocol_error", False)
            )
        values = (
            raw.get("prompt_tokens"),
            raw.get("completion_tokens"),
            raw.get("total_tokens"),
        )
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise ProviderInferenceError(
                self._failure(request, "provider_protocol_error", False)
            )
        hit = raw.get("prompt_cache_hit_tokens")
        miss = raw.get("prompt_cache_miss_tokens")
        details = raw.get("completion_tokens_details")
        reasoning = details.get("reasoning_tokens") if isinstance(details, dict) else None
        if any(
            value is not None and (isinstance(value, bool) or not isinstance(value, int))
            for value in (hit, miss, reasoning)
        ):
            raise ProviderInferenceError(
                self._failure(request, "provider_protocol_error", False)
            )
        if (hit is None) != (miss is None):
            hit = miss = None
        try:
            return TokenUsage(
                prompt_tokens=values[0],
                output_tokens=values[1],
                total_tokens=values[2],
                token_count_source="provider",
                prompt_cache_hit_tokens=hit,
                prompt_cache_miss_tokens=miss,
                reasoning_tokens=reasoning,
            )
        except ValueError:
            raise ProviderInferenceError(
                self._failure(request, "provider_protocol_error", False)
            ) from None

    def _finish_reason(self, request: InferenceRequest, raw: object) -> str:
        if raw in {"stop", "length"}:
            return str(raw)
        if raw in {"content_filter", "content_blocked"}:
            raise ProviderInferenceError(
                self._failure(request, "content_blocked", False)
            )
        raise ProviderInferenceError(
            self._failure(request, "provider_protocol_error", False)
        )

    def _validate_model(self, request: InferenceRequest, reported: object) -> None:
        if reported != self.model_id:
            raise ProviderInferenceError(
                self._failure(request, "model_unavailable", False)
            )

    def _validate_lineage(
        self, request: InferenceRequest, response: InferenceResponse
    ) -> InferenceResponse:
        return validate_inference_response_lineage(
            request=request,
            response=response,
            expected_provider_id=DEEPSEEK_PROVIDER_ID,
            expected_provider_class="cloud",
            expected_model_version_id=self.model_version_id,
            expected_adapter_version_id=None,
            expected_provider_adapter_version_id=self._provider_adapter_version,
        )

    def _raise_for_status(self, request: InferenceRequest, response: Any) -> None:
        status = response.status_code
        if 200 <= status < 300:
            return
        if status == 429:
            code, retryable = "provider_rate_limited", True
        elif status in {408, 504}:
            code, retryable = "provider_timeout", True
        elif status == 413:
            code, retryable = "context_limit_exceeded", False
        elif status in {400, 422}:
            code, retryable = "invalid_request", False
        elif status == 404:
            code, retryable = "model_unavailable", False
        elif status == 402:
            code, retryable = "model_unavailable", False
        elif status >= 500:
            code, retryable = "model_unavailable", True
        else:
            code, retryable = "provider_protocol_error", False
        raise ProviderInferenceError(
            self._failure(
                request,
                code,
                retryable,
                provider_status_code=status,
                provider_error_code=f"http_{status}",
            )
        )

    def _reject_redirect(self, request: InferenceRequest, response: Any) -> None:
        if 300 <= response.status_code < 400:
            raise ProviderInferenceError(
                self._failure(
                    request,
                    "provider_protocol_error",
                    False,
                    provider_status_code=response.status_code,
                    provider_error_code="redirect_forbidden",
                )
            )

    def _failure_from_exception(
        self, request: InferenceRequest, error: Exception
    ) -> InferenceFailure:
        if isinstance(error, ProviderVersionError):
            return self._failure(request, error.code, error.retryable)
        if _httpx is not None and isinstance(error, _httpx.TimeoutException):
            return self._failure(request, "provider_timeout", True)
        if _httpx is not None and isinstance(error, _httpx.RequestError):
            return self._failure(request, "model_unavailable", True)
        if isinstance(
            error,
            (InferenceResponseLineageError, ValidationError, _ProviderProtocolError),
        ):
            return self._failure(request, "provider_protocol_error", False)
        return self._failure(request, "internal_error", False)

    def _failure(
        self,
        request: InferenceRequest,
        code: InferenceFailureCode,
        retryable: bool,
        *,
        provider_status_code: int | None = None,
        provider_error_code: str | None = None,
    ) -> InferenceFailure:
        return InferenceFailure(
            inference_request_id=request.inference_request_id,
            request_id=request.request_id,
            trace_id=request.trace_id,
            provider_id=DEEPSEEK_PROVIDER_ID,
            provider_class="cloud",
            code=code,
            retryable=retryable,
            safe_message=_SAFE_MESSAGES[code],
            provider_status_code=provider_status_code,
            provider_error_code=provider_error_code,
        )

    @staticmethod
    async def _iter_sse_data(response: Any) -> AsyncIterator[str]:
        data_lines: list[str] = []
        async for raw_line in response.aiter_lines():
            line = raw_line.rstrip("\r")
            if not line:
                if data_lines:
                    yield "\n".join(data_lines)
                    data_lines.clear()
                continue
            if line.startswith(":"):
                continue
            if line.startswith("data:"):
                value = line[5:]
                if value.startswith(" "):
                    value = value[1:]
                data_lines.append(value)
        if data_lines:
            yield "\n".join(data_lines)

    @staticmethod
    def _stream_common(request: InferenceRequest, response_id) -> dict[str, object]:
        return {
            "inference_response_id": response_id,
            "inference_request_id": request.inference_request_id,
            "request_id": request.request_id,
            "trace_id": request.trace_id,
        }

    @staticmethod
    def _json_object(response: Any) -> dict[str, object]:
        try:
            payload = response.json()
        except Exception:
            raise _ProviderProtocolError("malformed JSON") from None
        if not isinstance(payload, dict):
            raise _ProviderProtocolError("non-object JSON")
        return payload

    @staticmethod
    def _health_exception_reason(error: Exception) -> str:
        if isinstance(error, ProviderVersionError):
            return (
                "model_mismatch"
                if error.code == "provider_protocol_error"
                else "health_unavailable"
            )
        if _httpx is not None and isinstance(error, _httpx.TimeoutException):
            return "health_timeout"
        if _httpx is not None and isinstance(error, _httpx.RequestError):
            return "health_transport_error"
        return "health_unavailable"


class _ProviderProtocolError(RuntimeError):
    """Internal marker whose message is never persisted or exposed."""
