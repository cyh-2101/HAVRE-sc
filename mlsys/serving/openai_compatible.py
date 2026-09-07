"""Self-hosted OpenAI-compatible HTTP adapter behind HAVRE's provider port."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import math
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from time import perf_counter_ns
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import ValidationError

try:  # The runtime dependency is loaded lazily so contract-only tooling still works.
    import httpx as _httpx
except ModuleNotFoundError:  # pragma: no cover - exercised only before installation.
    _httpx = None

from companion.events import TextContentPart
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
from mlsys.serving.provider import ProviderInferenceError
from mlsys.serving.provider import ProviderVersionError
from mlsys.serving.runtime_attestation import (
    RuntimeAttestation,
    verify_attested_process_liveness,
)


def llama_context_tokens_per_slot(profile: dict[str, Any]) -> int:
    """Pinned llama --ctx-size is total KV capacity across --parallel slots."""
    total, slots = profile["context_tokens"], profile["parallel_slots"]
    if type(total) is not int or type(slots) is not int or slots < 1 or total < slots:
        raise ValueError("llama context and parallel slots must be positive integers")
    return total // slots


_SAFE_MESSAGES = {
    "invalid_request": "The self-hosted provider rejected the inference request.",
    "unsupported_capability": "The self-hosted provider does not support a required capability.",
    "privacy_constraint_unsatisfied": "The self-hosted provider is not eligible for this request.",
    "model_unavailable": "The configured self-hosted model is unavailable.",
    "provider_rate_limited": "The self-hosted provider is temporarily rate limited.",
    "provider_timeout": "The self-hosted provider exceeded its time limit.",
    "context_limit_exceeded": "The request exceeds the self-hosted model context limit.",
    "content_blocked": "The self-hosted provider did not return content for this request.",
    "stream_interrupted": "The self-hosted provider stream ended before completion.",
    "provider_protocol_error": "The self-hosted provider returned an invalid response.",
    "internal_error": "The self-hosted inference adapter could not complete the request.",
}


class OpenAICompatibleProvider:
    """Translate canonical HAVRE inference to a self-hosted OpenAI HTTP server."""

    provider_class = "self_hosted"
    execution_environment = "local"

    def __init__(
        self,
        *,
        base_url: str,
        transport_model_id: str,
        model_version_id: str,
        tokenizer_version_id: str,
        serving_engine: str,
        serving_engine_version: str,
        serving_config_version: str,
        provider_id: str = "self-hosted-openai-compatible",
        provider_adapter_version_id: str = "openai-compatible-provider-adapter-v1",
        adapter_version_id: str | None = None,
        adapter_artifact_hash: str | None = None,
        model_artifact_hash: str | None = None,
        expected_build_substring: str | None = None,
        api_key: str | None = None,
        max_context_tokens: int = 32_768,
        max_output_tokens: int = 4_096,
        approved_privacy_classes: tuple[PrivacyClass, ...] = tuple(PrivacyClass),
        capability_ttl_seconds: int = 30,
        health_path: str = "/health",
        version_path: str = "/version",
        models_path: str = "/v1/models",
        completions_path: str = "/v1/chat/completions",
        enable_thinking: bool = False,
        reasoning_effort: Literal["none", "low", "medium", "high"] | None = "none",
        runtime_attestation: RuntimeAttestation | None = None,
        client: Any | None = None,
        transport: Any | None = None,
    ) -> None:
        self.base_url = self._validate_base_url(base_url)
        self.provider_id = self._required(provider_id, "provider_id")
        self.transport_model_id = self._required(
            transport_model_id, "transport_model_id"
        )
        self.model_version_id = self._required(model_version_id, "model_version_id")
        self.tokenizer_version_id = self._required(
            tokenizer_version_id, "tokenizer_version_id"
        )
        self.serving_engine = self._required(serving_engine, "serving_engine")
        self.serving_engine_version = self._required(
            serving_engine_version, "serving_engine_version"
        )
        self.serving_config_version = self._required(
            serving_config_version, "serving_config_version"
        )
        self.provider_adapter_version_id = self._required(
            provider_adapter_version_id, "provider_adapter_version_id"
        )
        self.adapter_version_id = adapter_version_id
        if (adapter_version_id is None) != (adapter_artifact_hash is None):
            raise ValueError("active adapter version and hash must appear together")
        self.adapter_artifact_hash = adapter_artifact_hash
        self.model_artifact_hash = model_artifact_hash
        self.expected_build_substring = (
            self._required(expected_build_substring, "expected_build_substring")
            if expected_build_substring is not None
            else None
        )
        if not isinstance(enable_thinking, bool):
            raise ValueError("enable_thinking must be a boolean")
        if reasoning_effort not in {None, "none", "low", "medium", "high"}:
            raise ValueError("reasoning_effort is not supported")
        self.enable_thinking = enable_thinking
        self.reasoning_effort = reasoning_effort
        self.runtime_attestation = runtime_attestation
        self.max_context_tokens = max_context_tokens
        self.max_output_tokens = max_output_tokens
        self.approved_privacy_classes = approved_privacy_classes
        self.capability_ttl_seconds = capability_ttl_seconds
        self.health_path = self._validate_path(health_path)
        self.version_path = self._validate_path(version_path)
        self.models_path = self._validate_path(models_path)
        self.completions_path = self._validate_path(completions_path)
        if max_context_tokens <= 0 or max_output_tokens <= 0:
            raise ValueError("provider token limits must be positive")
        if capability_ttl_seconds <= 0:
            raise ValueError("capability_ttl_seconds must be positive")
        if not approved_privacy_classes:
            raise ValueError("approved_privacy_classes cannot be empty")
        if runtime_attestation is not None:
            self._validate_runtime_attestation(runtime_attestation)

        headers = {"Accept": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        if client is not None and transport is not None:
            raise ValueError("client and transport cannot both be provided")
        if _httpx is None:
            raise RuntimeError(
                "httpx is required to construct OpenAICompatibleProvider"
            )
        if client is None:
            self._client = _httpx.AsyncClient(
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
        return ProviderCapabilities(
            provider_id=self.provider_id,
            provider_class=self.provider_class,
            execution_environment=self.execution_environment,
            available_model_version_ids=(self.model_version_id,),
            approved_privacy_classes=self.approved_privacy_classes,
            supports_streaming=True,
            max_context_tokens=self.max_context_tokens,
            max_output_tokens=self.max_output_tokens,
            observed_at=datetime.now(UTC),
            ttl_seconds=self.capability_ttl_seconds,
        )

    async def version(self) -> ProviderVersion:
        await self._verify_version_endpoint()
        return self._provider_version()

    async def health(self) -> ProviderHealth:
        started_ns = perf_counter_ns()
        reasons: list[str] = []
        loaded: tuple[str, ...] = ()
        try:
            response = await self._client.get(
                self._url(self.health_path), timeout=5.0
            )
            if not 200 <= response.status_code < 300:
                reasons.append(f"health_http_{response.status_code}")
            else:
                await self._verify_version_endpoint()
                models_response = await self._client.get(
                    self._url(self.models_path), timeout=5.0
                )
                if not 200 <= models_response.status_code < 300:
                    reasons.append(f"models_http_{models_response.status_code}")
                else:
                    payload = self._json_object(models_response)
                    data = payload.get("data")
                    if not isinstance(data, list):
                        reasons.append("models_payload_invalid")
                    else:
                        model_ids = {
                            item.get("id")
                            for item in data
                            if isinstance(item, dict) and isinstance(item.get("id"), str)
                        }
                        if self.transport_model_id in model_ids:
                            loaded = (self.model_version_id,)
                        else:
                            reasons.append("configured_model_not_loaded")
        except asyncio.CancelledError:
            raise
        except Exception as error:
            reasons.append(self._health_exception_reason(error))
        latency_ms = (perf_counter_ns() - started_ns) / 1_000_000
        return ProviderHealth(
            status="healthy" if not reasons else "unavailable",
            observed_at=datetime.now(UTC),
            latency_ms=round(latency_ms, 3),
            loaded_model_version_ids=loaded,
            reasons=tuple(reasons),
        )

    async def generate(self, request: InferenceRequest) -> InferenceResponse:
        started_ns = perf_counter_ns()
        try:
            self._required_runtime_attestation()
            self._validate_request(request, expected_stream=False)
            response = await self._client.post(
                self._url(self.completions_path),
                json=self._request_payload(request, stream=False),
                headers=self._request_headers(request),
                timeout=request.constraints.timeout_ms / 1000,
            )
            self._reject_redirect(request, response)
            self._raise_for_status(request, response)
            payload = self._json_object(response)
            normalized = self._normalize_completion(
                request=request,
                payload=payload,
                total_ms=(perf_counter_ns() - started_ns) / 1_000_000,
            )
            return validate_inference_response_lineage(
                request=request,
                response=normalized,
                expected_provider_id=self.provider_id,
                expected_provider_class=self.provider_class,
                expected_model_version_id=self.model_version_id,
                expected_adapter_version_id=self.adapter_version_id,
                expected_provider_adapter_version_id=self.provider_adapter_version_id,
            )
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
        response_started_to_provider = False
        common = self._stream_common(request, response_id)
        # The canonical stream starts when the adapter accepts the request. This
        # keeps validation, connection, and HTTP failures inside one ordered
        # typed stream instead of emitting a terminal event at sequence zero.
        yield InferenceStreamEvent(
            event="response_started", sequence_number=sequence, **common
        )
        sequence += 1
        try:
            self._required_runtime_attestation()
            self._validate_request(request, expected_stream=True)
            async with self._client.stream(
                "POST",
                self._url(self.completions_path),
                json=self._request_payload(request, stream=True),
                headers=self._request_headers(request),
                timeout=request.constraints.timeout_ms / 1000,
            ) as response:
                self._reject_redirect(request, response)
                if response.status_code >= 400:
                    # A streaming Response has no readable JSON until its error
                    # body is consumed. Keep only the existing safe typed error.
                    await response.aread()
                self._raise_for_status(request, response)
                response_started_to_provider = True

                text_parts: list[str] = []
                provider_request_id: str | None = None
                finish_reason: str | None = None
                usage: TokenUsage | None = None
                provider_generation_ms: float | None = None
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
                    self._validate_transport_model(request, chunk.get("model"))
                    self._validate_system_fingerprint(
                        request, chunk.get("system_fingerprint")
                    )
                    if chunk.get("usage") is not None:
                        usage = self._parse_usage(request, chunk["usage"])
                    parsed_generation_ms = self._parse_provider_generation_ms(
                        request, chunk.get("timings")
                    )
                    if parsed_generation_ms is not None:
                        provider_generation_ms = parsed_generation_ms
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
                    raw_finish = choice.get("finish_reason")
                    if raw_finish is not None:
                        finish_reason = self._finish_reason(request, raw_finish)
                    delta = choice.get("delta")
                    if not isinstance(delta, dict):
                        raise ProviderInferenceError(
                            self._failure(request, "provider_protocol_error", False)
                        )
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
                if (
                    not text_parts
                    or provider_request_id is None
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
                        provider_id=self.provider_id,
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
                        generation=(
                            provider_generation_ms
                            if provider_generation_ms is not None
                            else round(
                                (ended_ns - first_text_ns) / 1_000_000, 3
                            )
                        ),
                        total=round((ended_ns - started_ns) / 1_000_000, 3),
                    ),
                )
                normalized = validate_inference_response_lineage(
                    request=request,
                    response=normalized,
                    expected_provider_id=self.provider_id,
                    expected_provider_class=self.provider_class,
                    expected_model_version_id=self.model_version_id,
                    expected_adapter_version_id=self.adapter_version_id,
                    expected_provider_adapter_version_id=(
                        self.provider_adapter_version_id
                    ),
                )
                completed_event = InferenceStreamEvent(
                    event="response_completed",
                    sequence_number=sequence,
                    response=normalized,
                    **common,
                )
                terminal_emitted = True
                yield completed_event
        except ProviderInferenceError as error:
            if terminal_emitted:
                return
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
                if response_started_to_provider and is_transport_error
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

    def _provider_version(self) -> ProviderVersion:
        attestation = self._required_runtime_attestation()
        return ProviderVersion(
            provider_id=self.provider_id,
            provider_class=self.provider_class,
            execution_environment=self.execution_environment,
            provider_adapter_version_id=self.provider_adapter_version_id,
            serving_engine=self.serving_engine,
            serving_engine_version=self.serving_engine_version,
            serving_config_version=self.serving_config_version,
            model_version_id=self.model_version_id,
            tokenizer_version_id=self.tokenizer_version_id,
            model_artifact_hash=self.model_artifact_hash,
            active_adapter_version_id=attestation.active_adapter_version_id,
            active_adapter_artifact_hash=attestation.active_adapter_artifact_hash,
            runtime_attestation_id=attestation.attestation_id,
            runtime_attestation_hash=attestation.attestation_hash,
        )

    def _version_references(self) -> VersionReferences:
        attestation = self._required_runtime_attestation()
        return VersionReferences(
            model_version_id=self.model_version_id,
            adapter_version_id=self.adapter_version_id,
            tokenizer_version_id=self.tokenizer_version_id,
            serving_config_version=self.serving_config_version,
            provider_adapter_version_id=self.provider_adapter_version_id,
            serving_engine=self.serving_engine,
            serving_engine_version=self.serving_engine_version,
            model_artifact_hash=self.model_artifact_hash,
            runtime_attestation_id=attestation.attestation_id,
            runtime_attestation_hash=attestation.attestation_hash,
        )

    async def _verify_version_endpoint(self) -> None:
        self._required_runtime_attestation()
        try:
            response = await self._client.get(
                self._url(self.version_path), timeout=5.0
            )
            if not 200 <= response.status_code < 300:
                raise ProviderVersionError(
                    code="model_unavailable",
                    retryable=True,
                    safe_message="The self-hosted provider version endpoint is temporarily unavailable.",
                )
            payload = self._json_object(response)
            build_info = payload.get("build_info")
            if build_info is not None:
                if not isinstance(build_info, str) or not build_info:
                    raise _ProviderProtocolError("provider build_info is invalid")
                expected_build = (
                    self.expected_build_substring or self.serving_engine_version
                )
                if expected_build not in build_info:
                    raise _ProviderProtocolError(
                        "provider serving engine version mismatch"
                    )
            else:
                reported_engine = payload.get("serving_engine")
                reported_version = payload.get(
                    "serving_engine_version", payload.get("version")
                )
                if (
                    reported_engine != self.serving_engine
                    or reported_version != self.serving_engine_version
                ):
                    raise _ProviderProtocolError(
                        "provider serving engine version mismatch"
                    )
            models_response = await self._client.get(
                self._url(self.models_path), timeout=5.0
            )
            if not 200 <= models_response.status_code < 300:
                raise ProviderVersionError(
                    code="model_unavailable",
                    retryable=True,
                    safe_message="The self-hosted provider model endpoint is temporarily unavailable.",
                )
            models_payload = self._json_object(models_response)
            data = models_payload.get("data")
            if not isinstance(data, list) or not any(
                isinstance(item, dict) and item.get("id") == self.transport_model_id
                for item in data
            ):
                raise _ProviderProtocolError("loaded provider model alias mismatch")
        except asyncio.CancelledError:
            raise
        except ProviderVersionError:
            raise
        except Exception as error:
            if _httpx is not None and isinstance(error, _httpx.RequestError):
                raise ProviderVersionError(
                    code="model_unavailable",
                    retryable=True,
                    safe_message="The self-hosted provider version check is temporarily unavailable.",
                ) from error
            raise ProviderVersionError(
                code="provider_protocol_error",
                retryable=False,
                safe_message="The active self-hosted runtime has a deterministic provider version mismatch.",
            ) from error

    def _required_runtime_attestation(self) -> RuntimeAttestation:
        if self.runtime_attestation is None:
            raise ProviderVersionError(
                code="provider_protocol_error",
                retryable=False,
                safe_message="The self-hosted runtime has no verified process attestation.",
            )
        try:
            self._validate_runtime_attestation(self.runtime_attestation)
            verify_attested_process_liveness(self.runtime_attestation)
        except Exception as error:
            raise ProviderVersionError(
                code="provider_protocol_error",
                retryable=False,
                safe_message="The active self-hosted runtime has a deterministic provider version mismatch.",
            ) from error
        return self.runtime_attestation

    def _validate_runtime_attestation(
        self, attestation: RuntimeAttestation
    ) -> None:
        expected = (
            self.base_url.rstrip("/"),
            self.serving_engine,
            self.serving_engine_version,
            self.serving_config_version,
            self.model_version_id,
            self.tokenizer_version_id,
            self.model_artifact_hash,
            self.transport_model_id,
        )
        actual = (
            attestation.base_url.rstrip("/"),
            attestation.serving_engine,
            attestation.serving_engine_version,
            attestation.serving_config_version,
            attestation.model_version_id,
            attestation.tokenizer_version_id,
            attestation.model_artifact_hash,
            attestation.loaded_model_alias,
        )
        if actual != expected:
            raise ValueError("runtime attestation does not match provider configuration")

    def _validate_request(
        self, request: InferenceRequest, *, expected_stream: bool
    ) -> None:
        if request.constraints.stream is not expected_stream:
            raise ProviderInferenceError(
                self._failure(request, "unsupported_capability", False)
            )
        if self.execution_environment not in (
            request.constraints.allowed_execution_environments
        ):
            raise ProviderInferenceError(
                self._failure(request, "privacy_constraint_unsatisfied", False)
            )
        if (
            request.constraints.effective_data_policy.privacy_class
            not in self.approved_privacy_classes
        ):
            raise ProviderInferenceError(
                self._failure(request, "privacy_constraint_unsatisfied", False)
            )
        if request.generation.max_output_tokens > self.max_output_tokens:
            raise ProviderInferenceError(
                self._failure(request, "unsupported_capability", False)
            )
        traceparent = request.metadata.get("traceparent")
        if traceparent is not None:
            parsed_traceparent = parse_traceparent(traceparent)
            if (
                parsed_traceparent is None
                or parsed_traceparent[0] != request.trace_id
            ):
                raise ProviderInferenceError(
                    self._failure(request, "invalid_request", False)
                )

    def _request_payload(
        self, request: InferenceRequest, *, stream: bool
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": self.transport_model_id,
            "messages": [
                {
                    "role": message.role,
                    "content": [
                        {"type": "text", "text": part.text}
                        for part in message.content_parts
                    ],
                }
                for message in request.messages
            ],
            "max_tokens": request.generation.max_output_tokens,
            "temperature": request.generation.temperature,
            "top_p": request.generation.top_p,
            "stream": stream,
            "chat_template_kwargs": {
                "enable_thinking": self.enable_thinking,
            },
        }
        if self.reasoning_effort is not None:
            payload["reasoning_effort"] = self.reasoning_effort
        if request.generation.seed is not None:
            payload["seed"] = request.generation.seed
        if request.generation.stop:
            payload["stop"] = list(request.generation.stop)
        if stream:
            payload["stream_options"] = {"include_usage": True}
        return payload

    def _request_headers(self, request: InferenceRequest) -> dict[str, str]:
        headers = {
            "Accept": "text/event-stream"
            if request.constraints.stream
            else "application/json",
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
        self._validate_transport_model(request, payload.get("model"))
        self._validate_system_fingerprint(
            request, payload.get("system_fingerprint")
        )
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
                self._failure(request, "provider_protocol_error", False)
            )
        finish_reason = self._finish_reason(request, choice.get("finish_reason"))
        usage = self._parse_usage(request, payload.get("usage"))
        return InferenceResponse(
            inference_request_id=request.inference_request_id,
            request_id=request.request_id,
            trace_id=request.trace_id,
            output_parts=(TextContentPart(text=output),),
            finish_reason=finish_reason,
            provider=ProviderReference(
                provider_id=self.provider_id,
                provider_request_id=provider_request_id,
                provider_class=self.provider_class,
            ),
            versions=self._version_references(),
            usage=usage,
            timing_ms=InferenceTiming(
                queue=None,
                time_to_first_token=None,
                generation=self._parse_provider_generation_ms(
                    request, payload.get("timings")
                ),
                total=round(total_ms, 3),
            ),
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
        try:
            return TokenUsage(
                prompt_tokens=values[0],
                output_tokens=values[1],
                total_tokens=values[2],
                token_count_source="provider",
            )
        except ValueError:
            raise ProviderInferenceError(
                self._failure(request, "provider_protocol_error", False)
            ) from None

    def _finish_reason(self, request: InferenceRequest, raw: object) -> str:
        if raw == "stop":
            return "stop"
        if raw == "length":
            return "length"
        if raw in {"content_filter", "content_blocked"}:
            raise ProviderInferenceError(
                self._failure(request, "content_blocked", False)
            )
        raise ProviderInferenceError(
            self._failure(request, "provider_protocol_error", False)
        )

    def _validate_transport_model(
        self, request: InferenceRequest, reported: object
    ) -> None:
        if reported != self.transport_model_id:
            raise ProviderInferenceError(
                self._failure(request, "model_unavailable", False)
            )

    def _validate_system_fingerprint(
        self, request: InferenceRequest, reported: object
    ) -> None:
        if self.expected_build_substring is None:
            return
        if (
            not isinstance(reported, str)
            or self.expected_build_substring not in reported
        ):
            raise ProviderInferenceError(
                self._failure(request, "model_unavailable", False)
            )

    def _parse_provider_generation_ms(
        self, request: InferenceRequest, raw: object
    ) -> float | None:
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise ProviderInferenceError(
                self._failure(request, "provider_protocol_error", False)
            )
        predicted_ms = raw.get("predicted_ms")
        if predicted_ms is None:
            return None
        if (
            isinstance(predicted_ms, bool)
            or not isinstance(predicted_ms, (int, float))
            or not math.isfinite(predicted_ms)
            or predicted_ms < 0
        ):
            raise ProviderInferenceError(
                self._failure(request, "provider_protocol_error", False)
            )
        return round(float(predicted_ms), 3)

    def _raise_for_status(self, request: InferenceRequest, response: Any) -> None:
        status_code = response.status_code
        if 200 <= status_code < 300:
            return
        if status_code == 429:
            code, retryable = "provider_rate_limited", True
        elif status_code in {408, 504}:
            code, retryable = "provider_timeout", True
        elif status_code == 413:
            code, retryable = "context_limit_exceeded", False
        elif status_code in {400, 422}:
            code, retryable = (
                ("context_limit_exceeded", False)
                if self._is_context_limit_error(response)
                else ("invalid_request", False)
            )
        elif status_code == 404:
            code, retryable = "model_unavailable", False
        elif status_code >= 500:
            code, retryable = "model_unavailable", True
        else:
            code, retryable = "provider_protocol_error", False
        raise ProviderInferenceError(
            self._failure(
                request,
                code,
                retryable,
                provider_status_code=status_code,
                provider_error_code=f"http_{status_code}",
            )
        )

    @staticmethod
    def _is_context_limit_error(response: Any) -> bool:
        """Allowlist a bounded llama/OpenAI error message without retaining its body."""

        try:
            payload = response.json()
        except Exception:
            return False
        if not isinstance(payload, dict):
            return False
        error = payload.get("error")
        if not isinstance(error, dict):
            return False
        raw_code = error.get("code")
        raw_type = error.get("type")
        message = error.get("message")
        if raw_code in {"context_length_exceeded", "context_window_exceeded"}:
            return True
        if raw_type in {"context_length_exceeded", "context_window_exceeded"}:
            return True
        if not isinstance(message, str) or len(message) > 2_000:
            return False
        normalized = message.casefold()
        markers = (
            "context size exceeded",
            "context length exceeded",
            "exceeds the available context size",
            "exceeds the context window",
            "prompt is too long",
            "too many tokens",
        )
        return any(marker in normalized for marker in markers)

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
        if _httpx is not None and isinstance(error, _httpx.ConnectError):
            return self._failure(request, "model_unavailable", True)
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
            provider_id=self.provider_id,
            provider_class=self.provider_class,
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

    def _stream_common(
        self, request: InferenceRequest, response_id
    ) -> dict[str, object]:
        return {
            "inference_response_id": response_id,
            "inference_request_id": request.inference_request_id,
            "request_id": request.request_id,
            "trace_id": request.trace_id,
        }

    def _json_object(self, response: Any) -> dict[str, object]:
        try:
            payload = response.json()
        except Exception:
            raise _ProviderProtocolError("provider returned malformed JSON") from None
        if not isinstance(payload, dict):
            raise _ProviderProtocolError("provider returned a non-object JSON payload")
        return payload

    def _health_exception_reason(self, error: Exception) -> str:
        if isinstance(error, ProviderVersionError):
            return (
                "version_mismatch"
                if error.code == "provider_protocol_error"
                else "health_unavailable"
            )
        if _httpx is not None and isinstance(error, _httpx.TimeoutException):
            return "health_timeout"
        if _httpx is not None and isinstance(error, _httpx.RequestError):
            return "health_transport_error"
        message = str(error)
        if "mismatch" in message:
            return "version_mismatch"
        if "malformed" in message or "non-object" in message:
            return "health_protocol_error"
        return "health_unavailable"

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    @staticmethod
    def _required(value: str, name: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{name} cannot be empty")
        return normalized

    @staticmethod
    def _validate_path(path: str) -> str:
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("provider endpoint paths must be absolute URL paths")
        parsed = urlsplit(path)
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("provider endpoint paths cannot contain a host/query/fragment")
        return path

    @staticmethod
    def _validate_base_url(base_url: str) -> str:
        parsed = urlsplit(base_url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("provider base URL must use HTTP or HTTPS with a host")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("provider base URL cannot contain credentials/query/fragment")
        if not OpenAICompatibleProvider._is_loopback(parsed.hostname):
            raise ValueError("Stage 3 self-hosted endpoints must be loopback-only")
        return base_url.strip().rstrip("/")

    @staticmethod
    def _is_loopback(host: str) -> bool:
        normalized = host.rstrip(".").lower()
        try:
            return ipaddress.ip_address(normalized).is_loopback
        except ValueError:
            return False


class _ProviderProtocolError(RuntimeError):
    """Internal marker for malformed provider payloads; message is never persisted."""
