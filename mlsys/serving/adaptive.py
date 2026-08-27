"""Stage 6 adaptive rule router with hard eligibility filters and fallback."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from companion.policy import DataPolicy, PrivacyClass


@dataclass(frozen=True)
class EligibleProviderProfile:
    profile_id: str
    provider_id: str
    model_version_id: str
    execution_environment: Literal["local", "cloud"]
    strength: Literal["fast", "strong"]
    max_input_tokens: int
    approved_privacy_classes: frozenset[PrivacyClass]
    available: bool = True
    measured_latency_ms: float = 0.0
    measured_cost_units: float = 0.0
    measured_quality: float = 0.0


@dataclass(frozen=True)
class AdaptiveRouteDecision:
    router_version: str
    selected_profile_id: str
    eligible_profiles: tuple[str, ...]
    excluded_profiles: tuple[tuple[str, str], ...]
    fallback_profile_ids: tuple[str, ...]
    reason: str


class AdaptiveRouter:
    version = "adaptive-rule-router-v1"

    def decide(
        self,
        *,
        policy: DataPolicy,
        required_input_tokens: int,
        quality_requirement: Literal["routine", "strong"],
        profiles: tuple[EligibleProviderProfile, ...],
    ) -> AdaptiveRouteDecision:
        eligible: list[EligibleProviderProfile] = []
        excluded: list[tuple[str, str]] = []
        for profile in profiles:
            reason = None
            if not profile.available:
                reason = "unavailable"
            elif required_input_tokens > profile.max_input_tokens:
                reason = "insufficient_context_window"
            elif policy.privacy_class not in profile.approved_privacy_classes:
                reason = "privacy_class_not_approved"
            elif profile.execution_environment == "cloud" and not policy.cloud_eligible:
                reason = "cloud_forbidden_by_data_policy"
            if reason:
                excluded.append((profile.profile_id, reason))
            else:
                eligible.append(profile)
        if not eligible:
            raise ValueError("no provider profile satisfies hard privacy/capability filters")
        if quality_requirement == "strong":
            eligible.sort(key=lambda p: (-p.measured_quality, p.measured_latency_ms, p.profile_id))
            reason = "strongest_eligible_profile"
        else:
            eligible.sort(key=lambda p: (p.measured_latency_ms, p.measured_cost_units, -p.measured_quality, p.profile_id))
            reason = "fastest_eligible_profile_for_routine_work"
        return AdaptiveRouteDecision(
            router_version=self.version,
            selected_profile_id=eligible[0].profile_id,
            eligible_profiles=tuple(p.profile_id for p in eligible),
            excluded_profiles=tuple(excluded),
            fallback_profile_ids=tuple(p.profile_id for p in eligible[1:]),
            reason=reason,
        )
