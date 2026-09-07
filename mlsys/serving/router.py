"""Versioned hard-gate routers for configured inference providers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from companion.policy import DataPolicy, PrivacyClass
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
        self._validate_candidate(
            policy=policy,
            capabilities=capabilities,
            required_input_tokens=required_input_tokens,
            required_output_tokens=required_output_tokens,
            required_streaming=required_streaming,
        )
        return RouteDecision(
            request_id=request_id,
            trace_id=trace_id,
            router_version=self.version,
            selected_provider_id=capabilities.provider_id,
            selected_model_version_id=capabilities.available_model_version_ids[0],
            execution_environment=capabilities.execution_environment,
            effective_data_policy_revision_id=policy.policy_revision_id,
            eligible_candidates=(capabilities.provider_id,),
            reason="only_eligible_configured_provider",
        )

    def _validate_candidate(
        self,
        *,
        policy: DataPolicy,
        capabilities: ProviderCapabilities,
        required_input_tokens: int | None = None,
        required_output_tokens: int | None = None,
        required_streaming: bool = False,
    ) -> None:
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


class PrivacyClassRouter(Stage1Router):
    """Route ordinary cloud-safe turns to GPT and restricted turns to Local.

    This is a fixed privacy dispatch, not a quality or availability fallback.
    Exactly one provider is selected before its capabilities are queried. A
    failure on that provider is terminal for the interaction.
    """

    version = "privacy-class-router-v1"

    def __init__(
        self,
        *,
        cloud_provider_id: str,
        local_provider_id: str,
        approved_cloud_provider_ids: frozenset[str],
    ) -> None:
        if not cloud_provider_id or not local_provider_id:
            raise ValueError("privacy router provider IDs cannot be empty")
        if cloud_provider_id == local_provider_id:
            raise ValueError("privacy router requires distinct cloud and local providers")
        if cloud_provider_id not in approved_cloud_provider_ids:
            raise ValueError("privacy router cloud provider requires explicit approval")
        super().__init__(approved_cloud_provider_ids=approved_cloud_provider_ids)
        self.cloud_provider_id = cloud_provider_id
        self.local_provider_id = local_provider_id

    def select_provider_id(self, *, policy: DataPolicy) -> str:
        if (
            policy.privacy_class in {PrivacyClass.PUBLIC, PrivacyClass.NORMAL}
            and policy.cloud_eligible
        ):
            return self.cloud_provider_id
        return self.local_provider_id

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
        selected_provider_id = self.select_provider_id(policy=policy)
        if capabilities.provider_id != selected_provider_id:
            raise ProviderPolicyError(
                "provider capabilities do not match the privacy-selected route"
            )
        expected_environment = (
            "cloud"
            if selected_provider_id == self.cloud_provider_id
            else "local"
        )
        if capabilities.execution_environment != expected_environment:
            raise ProviderPolicyError(
                "provider execution environment does not match its privacy route slot"
            )
        self._validate_candidate(
            policy=policy,
            capabilities=capabilities,
            required_input_tokens=required_input_tokens,
            required_output_tokens=required_output_tokens,
            required_streaming=required_streaming,
        )
        other_provider_id = (
            self.local_provider_id
            if selected_provider_id == self.cloud_provider_id
            else self.cloud_provider_id
        )
        if selected_provider_id == self.cloud_provider_id:
            reason = "public_normal_cloud_default"
            excluded_reason = "fixed_privacy_route_prefers_cloud"
        elif policy.privacy_class in {PrivacyClass.PUBLIC, PrivacyClass.NORMAL}:
            reason = "cloud_ineligible_local_route"
            excluded_reason = "effective_policy_forbids_cloud"
        else:
            reason = "restricted_data_local_route"
            excluded_reason = "privacy_class_requires_local"
        return RouteDecision(
            request_id=request_id,
            trace_id=trace_id,
            router_version=self.version,
            selected_provider_id=capabilities.provider_id,
            selected_model_version_id=capabilities.available_model_version_ids[0],
            execution_environment=capabilities.execution_environment,
            effective_data_policy_revision_id=policy.policy_revision_id,
            eligible_candidates=(capabilities.provider_id,),
            excluded_candidates=(
                {
                    "provider_id": other_provider_id,
                    "reason_code": excluded_reason,
                },
            ),
            reason=reason,
        )
