"""Synthetic four-way policy and context/routing trade-off evidence."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

from companion.context.strategies import ControlledContextStrategy
from companion.hashing import content_hash
from companion.ids import uuid7
from companion.policy import DataPolicy, PrivacyClass
from companion.proactive import (
    InterruptionPolicy,
    ProactivePreferenceRevision,
    ProactiveProposal,
)
from mlsys.serving.adaptive import (
    AdaptiveRouter,
    EligibleProviderProfile,
)


class ProactiveEvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    evaluation_run_id: UUID = Field(default_factory=uuid7)
    suite_version: Literal["proactive-policy-simulation-v1"]
    fixture_hash: str
    metrics: dict[str, object]
    case_results: tuple[dict[str, object], ...]
    routing_tradeoff: dict[str, object]
    context_tradeoff: dict[str, object]
    binding_evaluation: Literal[False] = False
    gate_status: Literal["not_evaluated"] = "not_evaluated"
    limitations: tuple[str, ...]
    content_hash: str = ""

    def model_post_init(self, __context: object) -> None:
        expected = content_hash(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match ProactiveEvaluationReport")
        object.__setattr__(self, "content_hash", expected)


def run_proactive_evaluation(*, fixture_path: Path, identity) -> ProactiveEvaluationReport:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    if fixture.get("synthetic") is not True or fixture.get("schema_version") != 1:
        raise ValueError("proactive fixture must be explicitly synthetic schema v1")
    namespace = UUID("641ef27a-e1b9-4f1d-acb6-942ea7a2cbe2")
    owner_id = uuid5(namespace, "owner")
    now = datetime(2026, 8, 19, 12, tzinfo=UTC)
    policy = InterruptionPolicy(
        constitution_version_id=identity.constitution.version_id,
        identity_version_id=identity.identity.version_id,
    )
    results: list[dict[str, object]] = []
    for index, case in enumerate(fixture["cases"], start=1):
        budgets = bool(case["budgets"])
        cooldown = bool(case["cooldown"])
        preference = ProactivePreferenceRevision(
            owner_id=owner_id,
            revision=index,
            global_enabled=case["global_enabled"],
            category_permissions={"owner_reminder": case["category_permission"]},
            allowed_channels=("web_inbox",),
            global_budget_per_24h=1 if budgets else None,
            category_budget_per_24h={"owner_reminder": 1} if budgets else {},
            cooldown_seconds=3600 if cooldown else None,
            authorization_ref=("synthetic-evaluation" if case["global_enabled"] else None),
        )
        earliest = now + timedelta(hours=1) if case.get("not_yet") else now - timedelta(minutes=1)
        proposal = ProactiveProposal(
            owner_id=owner_id,
            category="owner_reminder",
            trigger_refs=(uuid5(namespace, f"trigger:{index}"),),
            reason_code="owner_requested_fixture",
            reason_summary="Synthetic reminder",
            intended_benefit="Evaluate policy",
            evidence_refs=(f"fixture/{index}",),
            data_policy=DataPolicy.owner_default(PrivacyClass.LOCAL_ONLY, memory_eligible=False),
            earliest_eligible_at=earliest,
            expires_at=now + timedelta(hours=4),
            deduplication_key=f"case:{index}",
            trace_id=uuid5(namespace, f"trace:{index}").hex,
            created_at=now,
        )
        decision = policy.decide(
            proposal=proposal,
            preference=preference,
            now=now,
            delivered_global_24h=int(case.get("delivered", 0)),
            delivered_category_24h=int(case.get("delivered", 0)),
            last_equivalent_delivery_at=None,
            duplicate_active=bool(case.get("duplicate", False)),
        )
        results.append(
            {
                "case_id": case["case_id"],
                "expected": case["expected"],
                "actual": decision.decision.value,
                "passed": decision.decision.value == case["expected"],
                "reason_codes": list(decision.reason_codes),
            }
        )

    local_policy = DataPolicy.owner_default(PrivacyClass.LOCAL_ONLY, memory_eligible=False)
    profiles = (
        EligibleProviderProfile(
            profile_id="local-fast", provider_id="local", model_version_id="small-v1",
            execution_environment="local", strength="fast", max_input_tokens=4096,
            approved_privacy_classes=frozenset(PrivacyClass), measured_latency_ms=24,
            measured_cost_units=1, measured_quality=0.91,
        ),
        EligibleProviderProfile(
            profile_id="local-strong", provider_id="local", model_version_id="strong-v1",
            execution_environment="local", strength="strong", max_input_tokens=8192,
            approved_privacy_classes=frozenset(PrivacyClass), measured_latency_ms=85,
            measured_cost_units=3, measured_quality=0.96,
        ),
        EligibleProviderProfile(
            profile_id="cloud-strong", provider_id="cloud", model_version_id="cloud-v1",
            execution_environment="cloud", strength="strong", max_input_tokens=16384,
            approved_privacy_classes=frozenset({PrivacyClass.PUBLIC, PrivacyClass.NORMAL}),
            measured_latency_ms=60, measured_cost_units=8, measured_quality=0.98,
        ),
    )
    router = AdaptiveRouter()
    routine = router.decide(
        policy=local_policy, required_input_tokens=2048,
        quality_requirement="routine", profiles=profiles,
    )
    strong = router.decide(
        policy=local_policy, required_input_tokens=2048,
        quality_requirement="strong", profiles=profiles,
    )
    candidates = tuple((f"evidence/{i}", "evidence text " * (i + 2), 10 - i) for i in range(5))
    raw = ControlledContextStrategy(mode="raw_top_k", top_k=5).build(
        identity_version=identity.identity.version_id,
        policy_version=policy.version,
        candidates=candidates,
    )
    compressed = ControlledContextStrategy(mode="compressed_top_k", top_k=3).build(
        identity_version=identity.identity.version_id,
        policy_version=policy.version,
        candidates=candidates,
    )
    return ProactiveEvaluationReport(
        suite_version=fixture["suite_version"],
        fixture_hash=content_hash(fixture),
        metrics={
            "cases": len(results),
            "passed": sum(bool(item["passed"]) for item in results),
            "failed": sum(not bool(item["passed"]) for item in results),
            "send_now_cases": sum(item["actual"] == "SEND_NOW" for item in results),
            "external_delivery_authorized": 0,
        },
        case_results=tuple(results),
        routing_tradeoff={
            "routine_selected": routine.selected_profile_id,
            "strong_selected": strong.selected_profile_id,
            "cloud_exclusion": dict(routine.excluded_profiles).get("cloud-strong"),
            "routine_latency_ms": 24,
            "strong_latency_ms": 85,
            "routine_quality": 0.91,
            "strong_quality": 0.96,
            "routine_cost_units": 1,
            "strong_cost_units": 3,
            "adoption": "routine-fast-with-strong-fallback",
        },
        context_tradeoff={
            "raw_tokens": raw.estimated_tokens,
            "compressed_tokens": compressed.estimated_tokens,
            "prefix_hash_equal": raw.prefix_hash == compressed.prefix_hash,
            "adoption": "compressed-top3-for-proactive-rendering",
        },
        limitations=(
            "All cases and provider measurements are deterministic synthetic fixtures.",
            "The report supports a Stage 6 routing/context decision, not production quality or cost claims.",
            "SEND_NOW reaches only the local simulated Web/inbox adapter.",
        ),
    )
