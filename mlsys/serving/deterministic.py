"""Deterministic local acceptance provider used to verify the permanent path."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from time import perf_counter_ns

from companion.context.builder import estimate_tokens
from companion.events import TextContentPart
from companion.ids import uuid7
from companion.policy import PrivacyClass
from mlsys.contracts import (
    InferenceRequest,
    InferenceResponse,
    InferenceStreamEvent,
    ProviderCapabilities,
    ProviderHealth,
    ProviderVersion,
    validate_inference_response_lineage,
)
from mlsys.contracts.inference import (
    InferenceTiming,
    ProviderReference,
    TokenUsage,
    VersionReferences,
)


class DeterministicLocalProvider:
    """A versioned local model adapter, intentionally simple and non-production."""

    provider_id = "deterministic-local"
    model_version_id = "deterministic-companion-v1"
    adapter_version_id = "deterministic-adapter-v1"
    provider_adapter_version_id = "deterministic-provider-adapter-v1"
    tokenizer_version_id = "utf8-bytes-div4-v1"
    serving_engine = "deterministic-python"
    serving_engine_version = "deterministic-python-v1"
    serving_config_version = "deterministic-serving-v1"
    output = (
        "I’m here with you. We can separate what you know from what you’re "
        "inferring, then choose the smallest useful next step that remains yours."
    )

    def __init__(
        self,
        *,
        active_adapter_version_id: str | None = None,
        active_adapter_artifact_hash: str | None = None,
    ) -> None:
        if (active_adapter_version_id is None) != (
            active_adapter_artifact_hash is None
        ):
            raise ValueError("active adapter version and hash must appear together")
        self.active_adapter_version_id = active_adapter_version_id
        self.active_adapter_artifact_hash = active_adapter_artifact_hash
        if active_adapter_version_id is not None:
            self.adapter_version_id = active_adapter_version_id

    async def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_id=self.provider_id,
            provider_class="local_test",
            execution_environment="local",
            available_model_version_ids=(self.model_version_id,),
            approved_privacy_classes=tuple(PrivacyClass),
            supports_streaming=True,
            max_context_tokens=32_768,
            max_output_tokens=4_096,
            observed_at=datetime.now(UTC),
            ttl_seconds=30,
        )

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            status="healthy",
            observed_at=datetime.now(UTC),
            latency_ms=0.0,
            loaded_model_version_ids=(self.model_version_id,),
        )

    async def version(self) -> ProviderVersion:
        return ProviderVersion(
            provider_id=self.provider_id,
            provider_class="local_test",
            execution_environment="local",
            provider_adapter_version_id=self.provider_adapter_version_id,
            serving_engine=self.serving_engine,
            serving_engine_version=self.serving_engine_version,
            serving_config_version=self.serving_config_version,
            model_version_id=self.model_version_id,
            tokenizer_version_id=self.tokenizer_version_id,
            active_adapter_version_id=self.active_adapter_version_id,
            active_adapter_artifact_hash=self.active_adapter_artifact_hash,
        )

    async def generate(self, request: InferenceRequest) -> InferenceResponse:
        started_ns = perf_counter_ns()
        prompt_tokens = sum(
            estimate_tokens(part.text)
            for message in request.messages
            for part in message.content_parts
        )
        output_tokens = estimate_tokens(self.output)
        total_ms = (perf_counter_ns() - started_ns) / 1_000_000
        response = InferenceResponse(
            inference_request_id=request.inference_request_id,
            request_id=request.request_id,
            trace_id=request.trace_id,
            output_parts=(TextContentPart(text=self.output),),
            finish_reason="stop",
            provider=ProviderReference(
                provider_id=self.provider_id,
                provider_request_id=str(uuid7()),
                provider_class="local_test",
            ),
            versions=VersionReferences(
                model_version_id=self.model_version_id,
                adapter_version_id=self.adapter_version_id,
                tokenizer_version_id=self.tokenizer_version_id,
                serving_config_version=self.serving_config_version,
                provider_adapter_version_id=self.provider_adapter_version_id,
                serving_engine=self.serving_engine,
                serving_engine_version=self.serving_engine_version,
            ),
            usage=TokenUsage(
                prompt_tokens=prompt_tokens,
                output_tokens=output_tokens,
                total_tokens=prompt_tokens + output_tokens,
                token_count_source="estimator",
            ),
            timing_ms=InferenceTiming(
                queue=0.0,
                time_to_first_token=round(total_ms, 3),
                generation=round(total_ms, 3),
                total=round(total_ms, 3),
            ),
        )
        return validate_inference_response_lineage(
            request=request,
            response=response,
            expected_provider_id=self.provider_id,
            expected_provider_class="local_test",
            expected_model_version_id=self.model_version_id,
            expected_provider_adapter_version_id=self.provider_adapter_version_id,
        )

    async def stream(
        self, request: InferenceRequest
    ) -> AsyncIterator[InferenceStreamEvent]:
        response = await self.generate(request)
        common = {
            "inference_response_id": response.inference_response_id,
            "inference_request_id": request.inference_request_id,
            "request_id": request.request_id,
            "trace_id": request.trace_id,
        }
        yield InferenceStreamEvent(
            event="response_started", sequence_number=0, **common
        )
        yield InferenceStreamEvent(
            event="output_delta",
            sequence_number=1,
            delta=TextContentPart(text=self.output),
            **common,
        )
        yield InferenceStreamEvent(
            event="response_completed",
            sequence_number=2,
            response=response,
            **common,
        )

    async def aclose(self) -> None:
        return None
