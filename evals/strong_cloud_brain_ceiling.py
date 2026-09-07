"""Controlled PUBLIC-synthetic Strong Cloud Brain ceiling experiment."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

# This accepted experiment is immutable evidence. Runtime presentation can
# evolve independently; replay remains pinned to the exact local prompt bytes.
CONTEXT_PRESENTATION_VERSION = "context-presentation-v2-natural-memory-linking"
from companion.events import TextContentPart
from companion.hashing import content_hash
from companion.identity import IdentityLoader
from companion.policy import CoreResponsePolicy, DataPolicy, PrivacyClass
from evals.relevant_memory_use import (
    load_suite,
    prompt_messages,
    score_case,
    score_casual_case,
    summarize,
)
from mlsys.contracts import GenerationSettings, InferenceMessage, InferenceRequest
from mlsys.contracts.inference import InferenceConstraints
from mlsys.serving import DeepSeekCloudProvider, Stage1Router
from mlsys.serving.deepseek_cloud import (
    DEEPSEEK_MODEL_VERSION,
    DEEPSEEK_PROVIDER_ADAPTER_VERSION,
    DEEPSEEK_PROVIDER_ID,
    PUBLIC_SYNTHETIC_BOUNDARY,
    STRONG_CLOUD_BRAIN_AUTHORIZATION_REF,
    bind_cloud_experiment_request,
)
from mlsys.training.stage9a_provenance import PROJECT_ROOT
from mlsys.training.stage9a_real import read_hashed_json, write_hashed_json


EXPERIMENT_ID = "strong-cloud-brain-ceiling-deepseek-v4-pro-v1"
AUTHORIZATION_REF = STRONG_CLOUD_BRAIN_AUTHORIZATION_REF
OFFICIAL_PRICING_URL = "https://api-docs.deepseek.com/quick_start/pricing/"
OFFICIAL_THINKING_URL = "https://api-docs.deepseek.com/guides/thinking_mode/"
PRICING_VERIFIED_AT = "2026-08-26"
MAX_OUTPUT_TOKENS = 96
THINKING_MAX_OUTPUT_TOKENS = 4_096
TIMEOUT_MS = 120_000
MAX_ATTEMPTS = 2

FOCUSED_SUITE_PATH = (
    PROJECT_ROOT / "evals/fixtures/relevant_memory_use_unseen_v1.json"
)
DIAGNOSTIC_SUITE_PATH = (
    PROJECT_ROOT / "evals/fixtures/relevant_memory_use_v1.json"
)
LOCAL_FOCUSED_REPORT = (
    PROJECT_ROOT
    / "evals/reports/relevant_memory_20260826/post-plan-unseen-replay-v2-final.json"
)
LOCAL_9201_REPORT = (
    PROJECT_ROOT
    / "evals/reports/strong_cloud_brain_20260826/local-9201-unseen-v1.json"
)
LOCAL_DIAGNOSTIC_REPORTS = (
    PROJECT_ROOT
    / "evals/reports/relevant_memory_20260826/system-presentation-replay-v3-final.json",
    PROJECT_ROOT
    / "evals/reports/relevant_memory_20260826/memory-use-v1-diagnostic-replay-v2-final.json",
)

# USD per one million tokens, verified against the official page above. Peak is
# Mon-Fri 01:00-04:00 and 06:00-10:00 UTC; all other times are off-peak.
PRICES = {
    "off_peak": {
        "cache_hit_input": Decimal("0.022"),
        "cache_miss_input": Decimal("0.66"),
        "output": Decimal("1.98"),
    },
    "peak": {
        "cache_hit_input": Decimal("0.044"),
        "cache_miss_input": Decimal("1.32"),
        "output": Decimal("3.96"),
    },
}


def explicit_public_synthetic_policy() -> DataPolicy:
    return DataPolicy(
        privacy_class=PrivacyClass.PUBLIC,
        memory_eligible=False,
        training_eligible=False,
        cloud_eligible=True,
        decision_source="owner_explicit",
        authorization_ref=AUTHORIZATION_REF,
    )


def pricing_period(at: datetime) -> Literal["peak", "off_peak"]:
    value = at.astimezone(UTC)
    peak_hour = 1 <= value.hour < 4 or 6 <= value.hour < 10
    return "peak" if value.weekday() < 5 and peak_hour else "off_peak"


def usage_cost(usage: Any, *, at: datetime) -> dict[str, Any]:
    period = pricing_period(at)
    rates = PRICES[period]
    hit = usage.prompt_cache_hit_tokens
    miss = usage.prompt_cache_miss_tokens
    exact = hit is not None and miss is not None and hit + miss == usage.prompt_tokens
    if hit is None or miss is None:
        hit = 0
        miss = usage.prompt_tokens
    else:
        miss += usage.prompt_tokens - hit - miss
    cost = (
        Decimal(hit) * rates["cache_hit_input"]
        + Decimal(miss) * rates["cache_miss_input"]
        + Decimal(usage.output_tokens) * rates["output"]
    ) / Decimal(1_000_000)
    return {
        "pricing_period": period,
        "cost_usd": format(cost.quantize(Decimal("0.000000000001")), "f"),
        "cost_exact_from_provider_cache_usage": exact,
        "unclassified_prompt_tokens_billed_as_cache_miss": (
            usage.prompt_tokens - (usage.prompt_cache_hit_tokens or 0)
            - (usage.prompt_cache_miss_tokens or 0)
            if not exact
            else 0
        ),
    }


def preflight_cost_upper_bound(
    messages: list[dict[str, str]],
    *,
    at: datetime,
    max_output_tokens: int = MAX_OUTPUT_TOKENS,
) -> Decimal:
    # UTF-8 bytes plus fixed framing is a tokenizer-independent upper bound for
    # these text-only requests: one token cannot represent less than one byte.
    # Every estimated input token is priced as a cache miss.
    input_upper = sum(
        len(message["content"].encode("utf-8")) for message in messages
    ) + 1_024
    rates = PRICES[pricing_period(at)]
    return (
        Decimal(input_upper) * rates["cache_miss_input"]
        + Decimal(max_output_tokens) * rates["output"]
    ) / Decimal(1_000_000)


async def _decide_route_with_fresh_capabilities(
    *,
    provider: DeepSeekCloudProvider,
    router: Stage1Router,
    request: InferenceRequest,
    policy: DataPolicy,
    messages: list[dict[str, str]],
) -> Any:
    """Bind every route decision to a non-stale provider capability assertion."""
    capabilities = await provider.capabilities()
    return router.decide(
        request_id=request.request_id,
        trace_id=request.trace_id,
        policy=policy,
        capabilities=capabilities,
        required_input_tokens=sum(
            len(message["content"].encode("utf-8")) for message in messages
        ),
        required_output_tokens=request.generation.max_output_tokens,
        required_streaming=True,
    )


def _load_exact_suite(path: Path) -> tuple[dict[str, Any], str]:
    suite = load_suite(path)
    if (
        suite.get("privacy_class") != "SYNTHETIC"
        or suite.get("contains_user_data") is not False
        or suite.get("training_eligible") is not False
        or suite.get("validation_for_training") is not False
    ):
        raise ValueError("cloud evaluation fixture is not PUBLIC synthetic evidence")
    return suite, content_hash(suite)


def _all_cases(suite: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        *({"kind": "paired_memory", **case} for case in suite["cases"]),
        *({"kind": "multi_memory", **case} for case in suite["multi_memory_cases"]),
        *(
            {
                "kind": "casual_regression",
                **case,
                "memory_context": [],
                "variant": "casual",
            }
            for case in suite["casual_regression_cases"]
        ),
    ]


def _diagnostic_case() -> tuple[dict[str, Any], str]:
    suite, suite_hash = _load_exact_suite(DIAGNOSTIC_SUITE_PATH)
    matches = [
        case
        for case in suite["cases"]
        if case["case_id"] == "self-reflection-relevant"
    ]
    if len(matches) != 1:
        raise ValueError("owner diagnostic is not exact-bound to the sealed suite")
    return {"kind": "owner_diagnostic", **matches[0]}, suite_hash


def _prompt_hashes_from_report(path: Path) -> tuple[str, dict[str, str]]:
    report = read_hashed_json(path)
    hashes: dict[str, set[str]] = {}
    for arm in report["arms"]:
        if arm.get("presentation_version") != CONTEXT_PRESENTATION_VERSION:
            continue
        for row in arm["results"]:
            hashes.setdefault(row["case_id"], set()).add(row["prompt_hash"])
    if any(len(values) != 1 for values in hashes.values()):
        raise ValueError(f"local report has prompt drift: {path}")
    return report["content_hash"], {
        case_id: next(iter(values)) for case_id, values in hashes.items()
    }


def _verify_local_prompt_bindings(
    cases: list[dict[str, Any]],
    *,
    identity: str,
) -> dict[str, Any]:
    if not LOCAL_9201_REPORT.exists():
        raise FileNotFoundError("exact 9201 focused replay is required before cloud use")
    reports = (LOCAL_FOCUSED_REPORT, LOCAL_9201_REPORT)
    bindings = [_prompt_hashes_from_report(path) for path in reports]
    expected = {
        case["case_id"]: content_hash({
            "messages": prompt_messages(
                case,
                system_text=identity,
                presentation_version=CONTEXT_PRESENTATION_VERSION,
            )
        })
        for case in cases
    }
    for report_hash, observed in bindings:
        if observed != expected:
            raise ValueError("cloud prompts do not exactly match frozen local prompts")
    return {
        "report_hashes": [report_hash for report_hash, _ in bindings],
        "prompt_binding_hash": content_hash(expected),
    }


def _verify_diagnostic_prompt_binding(
    case: dict[str, Any], *, identity: str
) -> dict[str, Any]:
    expected = content_hash({
        "messages": prompt_messages(
            case,
            system_text=identity,
            presentation_version=CONTEXT_PRESENTATION_VERSION,
        )
    })
    report_hashes = []
    observed_count = 0
    for path in LOCAL_DIAGNOSTIC_REPORTS:
        report_hash, hashes = _prompt_hashes_from_report(path)
        report_hashes.append(report_hash)
        if case["case_id"] in hashes:
            observed_count += 1
            if hashes[case["case_id"]] != expected:
                raise ValueError("owner diagnostic prompt differs from local evidence")
    if observed_count != len(LOCAL_DIAGNOSTIC_REPORTS):
        raise ValueError("owner diagnostic is missing local prompt evidence")
    return {"report_hashes": report_hashes, "prompt_hash": expected}


def _request_for_case(
    case: dict[str, Any],
    *,
    arm_name: str,
    identity: str,
    fixture_hash: str,
    policy: DataPolicy,
    max_output_tokens: int = MAX_OUTPUT_TOKENS,
    thinking: Literal["enabled", "disabled"] = "disabled",
) -> tuple[InferenceRequest, list[dict[str, str]], str]:
    rendered = prompt_messages(
        case,
        system_text=identity,
        presentation_version=CONTEXT_PRESENTATION_VERSION,
    )
    prompt_hash = content_hash({"messages": rendered})
    stable = f"{EXPERIMENT_ID}/{arm_name}/{case['case_id']}"
    request_id = uuid5(NAMESPACE_URL, stable + "/request")
    trace_id = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:32]
    request = InferenceRequest(
        inference_request_id=uuid5(NAMESPACE_URL, stable + "/inference"),
        request_id=request_id,
        trace_id=trace_id,
        messages=tuple(
            InferenceMessage(
                role=message["role"],
                content_parts=(TextContentPart(text=message["content"]),),
                source_refs=(
                    f"eval-fixture/{fixture_hash}/{case['case_id']}",
                    f"context-presentation/{CONTEXT_PRESENTATION_VERSION}",
                ),
            )
            for message in rendered
        ),
        context_pack_id=uuid5(NAMESPACE_URL, stable + "/context-pack"),
        generation=GenerationSettings(
            max_output_tokens=max_output_tokens,
            temperature=0,
            top_p=1,
        ),
        constraints=InferenceConstraints(
            stream=True,
            timeout_ms=TIMEOUT_MS,
            effective_data_policy=policy,
            allowed_execution_environments=("cloud",),
        ),
        metadata={
            "context_presentation_version": CONTEXT_PRESENTATION_VERSION,
            "evaluation_data_boundary": PUBLIC_SYNTHETIC_BOUNDARY,
            "evaluation_fixture_hash": fixture_hash,
            "cloud_authorization_ref": AUTHORIZATION_REF,
        },
    )
    request = bind_cloud_experiment_request(
        request, thinking=thinking, reasoning_effort="high"
    )
    return request, rendered, prompt_hash


class CloudRunFailure(RuntimeError):
    def __init__(self, failure: Any) -> None:
        self.failure = failure
        super().__init__(failure.safe_message)


async def _stream_once(
    provider: DeepSeekCloudProvider, request: InferenceRequest
) -> Any:
    terminal = None
    async for event in provider.stream(request):
        if event.event in {"response_completed", "response_failed"}:
            terminal = event
    if terminal is None:
        raise RuntimeError("cloud provider emitted no terminal stream event")
    if terminal.event == "response_failed":
        raise CloudRunFailure(terminal.failure)
    return terminal.response


async def _execute_with_bounded_retry(
    provider: DeepSeekCloudProvider, request: InferenceRequest
) -> tuple[Any, int]:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return await _stream_once(provider, request), attempt
        except CloudRunFailure as error:
            if (
                error.failure.code != "provider_rate_limited"
                or attempt == MAX_ATTEMPTS
            ):
                raise
            await asyncio.sleep(1)
    raise RuntimeError("unreachable retry state")


def _core_result(
    *,
    request: InferenceRequest,
    response: Any,
    case: dict[str, Any],
) -> Any:
    return CoreResponsePolicy().apply(
        request_id=request.request_id,
        trace_id=request.trace_id,
        context_pack_id=request.context_pack_id,
        inference_response_id=response.inference_response_id,
        current_user_input=case["user_message"],
        raw_output_parts=tuple(part.text for part in response.output_parts),
        history_evidence=tuple(case.get("memory_context", ())),
        available_effects=(),
    )


def _score(case: dict[str, Any], output: str, suite: dict[str, Any]) -> dict[str, Any]:
    if case["kind"] == "casual_regression":
        return score_casual_case(
            case,
            output,
            global_forbidden_meta_phrases=suite["global_forbidden_meta_phrases"],
        )
    return score_case(
        case,
        output,
        global_forbidden_meta_phrases=suite["global_forbidden_meta_phrases"],
    )


def _write_progress(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _load_progress(
    path: Path,
    *,
    focused_fixture_hash: str,
    diagnostic_fixture_hash: str,
) -> dict[str, Any]:
    expected = {
        "experiment_id": EXPERIMENT_ID,
        "focused_fixture_hash": focused_fixture_hash,
        "diagnostic_fixture_hash": diagnostic_fixture_hash,
        "model_version_id": DEEPSEEK_MODEL_VERSION,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
    }
    mode_budgets = {
        "disabled": MAX_OUTPUT_TOKENS,
        "enabled": THINKING_MAX_OUTPUT_TOKENS,
    }
    if not path.exists():
        return {**expected, "max_output_tokens_by_mode": mode_budgets, "arms": {}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if any(payload.get(key) != value for key, value in expected.items()):
        raise ValueError("cloud evaluation progress binding mismatch")
    observed_mode_budgets = payload.get("max_output_tokens_by_mode")
    if observed_mode_budgets is None:
        # Additive migration for the first non-thinking-only progress snapshot.
        payload["max_output_tokens_by_mode"] = mode_budgets
    elif observed_mode_budgets != mode_budgets:
        raise ValueError("cloud evaluation progress mode budget binding mismatch")
    if not isinstance(payload.get("arms"), dict):
        raise ValueError("cloud evaluation progress has invalid arms")
    return payload


def _summarize_arm(rows: list[dict[str, Any]]) -> dict[str, Any]:
    focused = [row for row in rows if row["kind"] != "owner_diagnostic"]
    raw_rows = [{**row, "scores": row["raw_model_scores"]} for row in focused]
    pipeline_rows = [
        {**row, "scores": row["full_pipeline_scores"]} for row in focused
    ]
    prompt_tokens = sum(row["usage"]["prompt_tokens"] for row in rows)
    output_tokens = sum(row["usage"]["output_tokens"] for row in rows)
    reasoning_tokens = sum(
        row["usage"].get("reasoning_tokens") or 0 for row in rows
    )
    total_cost = sum(Decimal(row["cost"]["cost_usd"]) for row in rows)
    latencies = sorted(row["timing_ms"]["total"] for row in rows)
    ttfts = sorted(row["timing_ms"]["time_to_first_token"] for row in rows)

    def percentile(values: list[float], fraction: float) -> float:
        index = min(len(values) - 1, max(0, round((len(values) - 1) * fraction)))
        return round(values[index], 3)

    return {
        "raw_model": summarize(raw_rows),
        "full_havre_pipeline": summarize(pipeline_rows),
        "request_count": len(rows),
        "prompt_tokens": prompt_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "total_api_cost_usd": format(
            total_cost.quantize(Decimal("0.000000000001")), "f"
        ),
        "cost_exact_for_every_request": all(
            row["cost"]["cost_exact_from_provider_cache_usage"] for row in rows
        ),
        "latency_ms": {
            "p50": percentile(latencies, 0.5),
            "p95": percentile(latencies, 0.95),
        },
        "ttft_ms": {
            "definition": "first final-answer content token; reasoning_content is excluded",
            "p50": percentile(ttfts, 0.5),
            "p95": percentile(ttfts, 0.95),
        },
    }


async def run_focused_cloud_evaluation(
    *,
    output_path: Path,
    progress_path: Path,
    budget_usd: Decimal,
    modes: tuple[Literal["disabled", "enabled"], ...] = (
        "disabled",
        "enabled",
    ),
) -> dict[str, Any]:
    if output_path.exists():
        raise FileExistsError(f"immutable evaluation output exists: {output_path}")
    if budget_usd <= 0:
        raise ValueError("cloud experiment budget must be positive")
    if not modes or len(set(modes)) != len(modes):
        raise ValueError("cloud experiment modes must be unique and non-empty")

    focused_suite, focused_hash = _load_exact_suite(FOCUSED_SUITE_PATH)
    diagnostic, diagnostic_hash = _diagnostic_case()
    focused_cases = _all_cases(focused_suite)
    identity = IdentityLoader(PROJECT_ROOT / "identity").load().system_text()
    local_binding = _verify_local_prompt_bindings(
        focused_cases,
        identity=identity,
    )
    diagnostic_binding = _verify_diagnostic_prompt_binding(
        diagnostic,
        identity=identity,
    )
    progress = _load_progress(
        progress_path,
        focused_fixture_hash=focused_hash,
        diagnostic_fixture_hash=diagnostic_hash,
    )
    policy = explicit_public_synthetic_policy()
    router = Stage1Router(
        approved_cloud_provider_ids=frozenset({DEEPSEEK_PROVIDER_ID})
    )
    spent = sum(
        Decimal(row["cost"]["cost_usd"])
        for arm in progress["arms"].values()
        for row in arm["results"]
    )

    for mode in modes:
        arm_name = f"deepseek_v4_pro_thinking_{mode}"
        arm = progress["arms"].setdefault(
            arm_name,
            {
                "arm_name": arm_name,
                "thinking": mode,
                "reasoning_effort": "high" if mode == "enabled" else None,
                "results": [],
            },
        )
        if arm.get("thinking") != mode:
            raise ValueError("progress arm thinking-mode mismatch")
        completed = {row["case_id"] for row in arm["results"]}
        prepared = []
        for case in (*focused_cases, diagnostic):
            fixture_hash = (
                diagnostic_hash
                if case["kind"] == "owner_diagnostic"
                else focused_hash
            )
            request, messages, prompt_hash = _request_for_case(
                case,
                arm_name=arm_name,
                identity=identity,
                fixture_hash=fixture_hash,
                policy=policy,
                max_output_tokens=(
                    THINKING_MAX_OUTPUT_TOKENS
                    if mode == "enabled"
                    else MAX_OUTPUT_TOKENS
                ),
                thinking=mode,
            )
            prepared.append((case, request, messages, prompt_hash, fixture_hash))
        provider = DeepSeekCloudProvider(
            enabled=True,
            explicit_authorization_ref=AUTHORIZATION_REF,
            allowed_fixture_hashes=frozenset(
                fixture_hash for *_, fixture_hash in prepared
            ),
            allowed_request_hashes=frozenset(
                request.metadata["cloud_request_binding_hash"]
                for _, request, *_ in prepared
            ),
            thinking=mode,
            reasoning_effort="high",
        )
        try:
            version = await provider.version()
            if version.model_version_id != DEEPSEEK_MODEL_VERSION:
                raise ValueError("DeepSeek live model alias binding mismatch")
            for case, request, messages, prompt_hash, fixture_hash in prepared:
                if case["case_id"] in completed:
                    continue
                expected_prompt_hash = (
                    diagnostic_binding["prompt_hash"]
                    if case["kind"] == "owner_diagnostic"
                    else None
                )
                if expected_prompt_hash is not None and prompt_hash != expected_prompt_hash:
                    raise ValueError("owner diagnostic prompt binding changed")
                route = await _decide_route_with_fresh_capabilities(
                    provider=provider,
                    router=router,
                    request=request,
                    policy=policy,
                    messages=messages,
                )
                if (
                    route.selected_provider_id != DEEPSEEK_PROVIDER_ID
                    or route.execution_environment != "cloud"
                ):
                    raise ValueError("cloud route decision binding mismatch")
                started_at = datetime.now(UTC)
                upper = preflight_cost_upper_bound(
                    messages,
                    at=started_at,
                    max_output_tokens=request.generation.max_output_tokens,
                )
                if spent + upper > budget_usd:
                    raise RuntimeError("cloud experiment budget ceiling reached")
                response, attempts = await _execute_with_bounded_retry(
                    provider, request
                )
                raw_output = "\n".join(part.text for part in response.output_parts)
                core = _core_result(
                    request=request,
                    response=response,
                    case=case,
                )
                delivered = "\n".join(core.output_parts)
                cost = usage_cost(response.usage, at=started_at)
                spent += Decimal(cost["cost_usd"])
                row = {
                    "case_id": case["case_id"],
                    "kind": case["kind"],
                    "variant": case["variant"],
                    "pair_id": case.get("pair_id"),
                    "memory_context": case.get("memory_context", []),
                    "prompt_hash": prompt_hash,
                    "raw_model_output": raw_output,
                    "full_havre_pipeline_output": delivered,
                    "raw_model_scores": _score(
                        case, raw_output, focused_suite
                    ),
                    "full_pipeline_scores": _score(
                        case, delivered, focused_suite
                    ),
                    "core_action": core.decision.action,
                    "core_category": core.decision.category,
                    "core_reason_codes": list(core.decision.reason_codes),
                    "provider_request_id_hash": content_hash(
                        {"provider_request_id": response.provider.provider_request_id}
                    ),
                    "usage": response.usage.model_dump(mode="json"),
                    "timing_ms": response.timing_ms.model_dump(mode="json"),
                    "finish_reason": response.finish_reason,
                    "attempt_count": attempts,
                    "cost": cost,
                    "route": {
                        "router_version": route.router_version,
                        "reason": route.reason,
                        "effective_data_policy_revision_id": str(
                            route.effective_data_policy_revision_id
                        ),
                        "selected_provider_id": route.selected_provider_id,
                        "selected_model_version_id": route.selected_model_version_id,
                        "execution_environment": route.execution_environment,
                    },
                    "completed_at": datetime.now(UTC).isoformat(),
                }
                arm["results"].append(row)
                progress["updated_at"] = datetime.now(UTC).isoformat()
                _write_progress(progress_path, progress)
        finally:
            await provider.aclose()

    arms = []
    for mode in modes:
        arm_name = f"deepseek_v4_pro_thinking_{mode}"
        arm = progress["arms"][arm_name]
        expected_count = len(focused_cases) + 1
        if len(arm["results"]) != expected_count:
            raise ValueError("cloud evaluation arm is incomplete")
        arms.append({**arm, "summary": _summarize_arm(arm["results"])})

    output_path.parent.mkdir(parents=True, exist_ok=True)
    return write_hashed_json(
        output_path,
        {
            "schema_version": 1,
            "experiment_id": EXPERIMENT_ID,
            "status": "completed_evidence_only_evaluation",
            "provider_id": DEEPSEEK_PROVIDER_ID,
            "model_version_id": DEEPSEEK_MODEL_VERSION,
            "provider_adapter_version_id": DEEPSEEK_PROVIDER_ADAPTER_VERSION,
            "context_presentation_version": CONTEXT_PRESENTATION_VERSION,
            "focused_suite_id": focused_suite["suite_id"],
            "focused_fixture_hash": focused_hash,
            "diagnostic_fixture_hash": diagnostic_hash,
            "local_prompt_binding": local_binding,
            "diagnostic_prompt_binding": diagnostic_binding,
            "exact_same_provider_facing_prompt_as_local": True,
            "privacy_class": "PUBLIC",
            "synthetic_only": True,
            "contains_user_data": False,
            "owner_private_data_used": False,
            "daily_chat_used": False,
            "cloud_authorization_ref": AUTHORIZATION_REF,
            "cloud_route_default_enabled": False,
            "training_performed": False,
            "candidate_status_changed": False,
            "daily_use_binding_changed": False,
            "promotion_authorized": False,
            "deployment_authorized": False,
            "stage9b_started": False,
            "max_output_tokens_by_mode": {
                "disabled": MAX_OUTPUT_TOKENS,
                "enabled": THINKING_MAX_OUTPUT_TOKENS,
            },
            "timeout_ms": TIMEOUT_MS,
            "retry_policy": "one retry only for provider_rate_limited; no other retry",
            "budget_ceiling_usd": format(budget_usd, "f"),
            "pricing": {
                "verified_at": PRICING_VERIFIED_AT,
                "source_url": OFFICIAL_PRICING_URL,
                "thinking_source_url": OFFICIAL_THINKING_URL,
                "rates_usd_per_million_tokens": {
                    period: {key: format(value, "f") for key, value in rates.items()}
                    for period, rates in PRICES.items()
                },
            },
            "arms": arms,
            "manual_semantic_review_required": True,
            "raw_model_and_full_pipeline_reported_separately": True,
            "limitations": [
                "Deterministic surface scores are not semantic acceptance.",
                "The owner diagnostic is an existing sealed case and is reported separately from unseen totals.",
                "Provider chain-of-thought is neither retained nor treated as HAVRE evidence.",
                "Thinking mode uses a 4096-token total generation allowance because the provider counts hidden reasoning and visible final text against the same max_tokens field; non-thinking and local arms use 96. A separate 1024-token diagnostic run was incomplete and is not an evaluation arm.",
                "No result authorizes routing, serving, registration, promotion, deployment, or training.",
            ],
            "completed_at": datetime.now(UTC).isoformat(),
        },
    )
