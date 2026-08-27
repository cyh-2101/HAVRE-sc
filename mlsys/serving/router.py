"""Eligibility-only router with one configured provider."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from companion.policy import DataPolicy
from mlsys.contracts import ProviderCapabilities, RouteDecision
from mlsys.serving.provider import ProviderPolicyError


class Stage1Router:
    """Compatibility name for the versioned single-provider eligibility router."""

    version = "single-provider-router-v2"

    def __init__(self, *, approved_cloud_provider_ids: frozenset[str] = frozenset()) -> None:
        self.approved_cloud_provider_ids = approved_cloud_provider_ids

    def decide(
        self,
        *,
        request_id,
        trace_id: str,
        policy: DataPolicy,
        capabilities: ProviderCapabilities,
        required_input_tokens: int | None = None,
        required_output_tokens: int | None = None,
        required_streaming: bool = False,
    ) -> RouteDecision:
        observed_at = capabilities.observed_at
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ProviderPolicyError("provider capabilities timestamp is not timezone-aware")
        if datetime.now(UTC) >= observed_at.astimezone(UTC) + timedelta(
            seconds=capabilities.ttl_seconds
        ):
            raise ProviderPolicyError("provider capabilities are stale")
        if not capabilities.available_model_version_ids:
            raise ProviderPolicyError("provider has no available model version")
        if required_streaming and not capabilities.supports_streaming:
            raise ProviderPolicyError("provider does not support required streaming")
        if required_input_tokens is not None:
            if required_input_tokens < 0:
                raise ProviderPolicyError("required input tokens cannot be negative")
            output_tokens = required_output_tokens or 0
            if required_input_tokens + output_tokens > capabilities.max_context_tokens:
                raise ProviderPolicyError(
                    "provider context window cannot satisfy the request"
                )
        if required_output_tokens is not None:
            if required_output_tokens <= 0:
                raise ProviderPolicyError("required output tokens must be positive")
            if required_output_tokens > capabilities.max_output_tokens:
                raise ProviderPolicyError(
                    "provider maximum output tokens cannot satisfy the request"
                )
        if policy.privacy_class not in capabilities.approved_privacy_classes:
            raise ProviderPolicyError(
                f"provider {capabilities.provider_id} is not approved for "
                f"{policy.privacy_class.value}"
            )
        if capabilities.execution_environment == "cloud":
            if not policy.cloud_eligible:
                raise ProviderPolicyError("effective DataPolicy forbids cloud execution")
            if capabilities.provider_id not in self.approved_cloud_provider_ids:
                raise ProviderPolicyError("cloud provider lacks explicit owner approval")
        return RouteDecision(
            request_id=request_id,
            trace_id=trace_id,
            selected_provider_id=capabilities.provider_id,
            selected_model_version_id=capabilities.available_model_version_ids[0],
            execution_environment=capabilities.execution_environment,
            effective_data_policy_revision_id=policy.policy_revision_id,
            eligible_candidates=(capabilities.provider_id,),
            reason="only_eligible_configured_provider",
        )
