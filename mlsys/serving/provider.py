"""Provider port owned by the ML-system boundary."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from mlsys.contracts import (
    InferenceFailure,
    InferenceFailureCode,
    InferenceRequest,
    InferenceResponse,
    InferenceStreamEvent,
    ProviderCapabilities,
    ProviderHealth,
    ProviderVersion,
)


class ProviderPolicyError(RuntimeError):
    pass


class ProviderInferenceError(RuntimeError):
    """Exception wrapper that exposes only typed, persistence-safe failure data."""

    def __init__(self, failure: InferenceFailure) -> None:
        if not isinstance(failure, InferenceFailure):
            raise TypeError("ProviderInferenceError requires an InferenceFailure")
        self.failure = failure
        super().__init__(failure.safe_message)

    @property
    def code(self) -> InferenceFailureCode:
        return self.failure.code

    @property
    def retryable(self) -> bool:
        return self.failure.retryable

    @property
    def safe_message(self) -> str:
        return self.failure.safe_message

    @property
    def provider_status_code(self) -> int | None:
        return self.failure.provider_status_code

    @property
    def provider_error_code(self) -> str | None:
        return self.failure.provider_error_code

    @property
    def trace_id(self) -> str:
        return self.failure.trace_id


class ProviderVersionError(RuntimeError):
    """Typed, content-safe failure raised before an inference attempt starts."""

    def __init__(
        self,
        *,
        code: InferenceFailureCode,
        retryable: bool,
        safe_message: str,
    ) -> None:
        self.code = code
        self.retryable = retryable
        self.safe_message = safe_message
        super().__init__(safe_message)


class ModelProvider(Protocol):
    provider_id: str

    async def capabilities(self) -> ProviderCapabilities: ...

    async def health(self) -> ProviderHealth: ...

    async def version(self) -> ProviderVersion: ...

    async def generate(self, request: InferenceRequest) -> InferenceResponse: ...

    def stream(self, request: InferenceRequest) -> AsyncIterator[InferenceStreamEvent]: ...

    async def aclose(self) -> None: ...
