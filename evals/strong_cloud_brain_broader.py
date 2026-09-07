"""Conditional 80-case PUBLIC-synthetic Strong Cloud Brain regression."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from companion.context import CONTEXT_PRESENTATION_VERSION, render_memory_evidence
from companion.events import TextContentPart
from companion.hashing import content_hash
from companion.identity import IdentityLoader
from companion.policy import CoreResponsePolicy
from evals.strong_cloud_brain_ceiling import (
    AUTHORIZATION_REF,
    DEEPSEEK_MODEL_VERSION,
    DEEPSEEK_PROVIDER_ID,
    MAX_ATTEMPTS,
    OFFICIAL_PRICING_URL,
    PRICES,
    PRICING_VERIFIED_AT,
    PUBLIC_SYNTHETIC_BOUNDARY,
    TIMEOUT_MS,
    _decide_route_with_fresh_capabilities,
    _execute_with_bounded_retry,
    explicit_public_synthetic_policy,
    preflight_cost_upper_bound,
    usage_cost,
)
from mlsys.contracts import GenerationSettings, InferenceMessage, InferenceRequest
from mlsys.contracts.inference import InferenceConstraints
from mlsys.serving import DeepSeekCloudProvider, Stage1Router
from mlsys.serving.deepseek_cloud import (
    DEEPSEEK_PROVIDER_ADAPTER_VERSION,
    bind_cloud_experiment_request,
)
from mlsys.training.stage9a_core_responsibility import REPORT_PATH as LOCAL_CORE_REPORT
from mlsys.training.stage9a_core_responsibility import _summary
from mlsys.training.stage9a_dataset_v7 import DATASET_ROOT, load_and_verify_dataset
from mlsys.training.stage9a_evaluation_v7 import _prompt_messages as legacy_prompt_messages
from mlsys.training.stage9a_provenance import PROJECT_ROOT
from mlsys.training.stage9a_real import read_hashed_json, write_hashed_json
from mlsys.training.stage9a_unseen_v7 import (
    EVALUATION_SET_ID,
    load_and_verify_unseen,
    score_output,
)


EXPERIMENT_ID = "strong-cloud-brain-broader-deepseek-v4-pro-thinking-v1"
MAX_OUTPUT_TOKENS = 4_096


def current_prompt_messages(case: dict[str, Any], identity: str) -> list[dict[str, str]]:
    system = identity
    if case["memory_context"]:
        system = f"{system}\n\n" + render_memory_evidence(
            tuple(("episodic", value) for value in case["memory_context"])
        )
    return [
        {"role": "system", "content": system},
        *[dict(message) for message in case["messages"]],
    ]


def _request_for_case(
    case: dict[str, Any], *, identity: str, manifest_hash: str
) -> tuple[InferenceRequest, list[dict[str, str]], str]:
    messages = current_prompt_messages(case, identity)
    prompt_hash = content_hash(messages)
    stable = f"https://havre.local/{EXPERIMENT_ID}/{case['case_id']}"
    policy = explicit_public_synthetic_policy()
    request = InferenceRequest(
        inference_request_id=uuid5(NAMESPACE_URL, stable + "/inference"),
        request_id=uuid5(NAMESPACE_URL, stable + "/request"),
        trace_id=hashlib.sha256(stable.encode("utf-8")).hexdigest()[:32],
        messages=tuple(
            InferenceMessage(
                role=message["role"],
                content_parts=(TextContentPart(text=message["content"]),),
                source_refs=(
                    "identity/approved" if message["role"] == "system"
                    else f"evaluation/{case['case_id']}"
                ,),
            )
            for message in messages
        ),
        context_pack_id=uuid5(NAMESPACE_URL, stable + "/context-pack"),
        generation=GenerationSettings(
            max_output_tokens=MAX_OUTPUT_TOKENS,
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
            "evaluation_fixture_hash": manifest_hash,
            "cloud_authorization_ref": AUTHORIZATION_REF,
        },
    )
    request = bind_cloud_experiment_request(
        request, thinking="enabled", reasoning_effort="high"
    )
    return request, messages, prompt_hash


def _write_progress(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _load_progress(path: Path, *, manifest_hash: str) -> dict[str, Any]:
    expected = {
        "experiment_id": EXPERIMENT_ID,
        "evaluation_set_id": EVALUATION_SET_ID,
        "manifest_hash": manifest_hash,
        "model_version_id": DEEPSEEK_MODEL_VERSION,
        "thinking": "enabled",
        "reasoning_effort": "high",
        "max_output_tokens": MAX_OUTPUT_TOKENS,
    }
    if not path.exists():
        return {**expected, "results": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if any(payload.get(key) != value for key, value in expected.items()):
        raise ValueError("broader cloud progress binding mismatch")
    if not isinstance(payload.get("results"), list):
        raise ValueError("broader cloud progress has invalid results")
    return payload


def prompt_comparability(cases: list[dict[str, Any]], identity: str) -> dict[str, Any]:
    dataset = load_and_verify_dataset(DATASET_ROOT)
    frozen_system_values = {
        row["system_text"] for rows in dataset.values() for row in rows
    }
    if len(frozen_system_values) != 1:
        raise ValueError("frozen v7 broader system text is not canonical")
    frozen_system = frozen_system_values.pop()
    exact_ids = []
    identity_changed_ids = []
    memory_presentation_changed_ids = []
    for case in cases:
        current = current_prompt_messages(case, identity)
        frozen_local = legacy_prompt_messages(case, frozen_system)
        (exact_ids if current == frozen_local else identity_changed_ids).append(
            case["case_id"]
        )
        if case["memory_context"]:
            memory_presentation_changed_ids.append(case["case_id"])
    return {
        "exact_same_provider_facing_prompt_case_count": len(exact_ids),
        "same_case_messages_and_targets_count": len(cases),
        "identity_system_text_changed_case_count": len(identity_changed_ids),
        "current_memory_presentation_case_count": len(memory_presentation_changed_ids),
        "exact_same_case_ids": exact_ids,
        "identity_system_text_changed_case_ids": identity_changed_ids,
        "presentation_changed_case_ids": memory_presentation_changed_ids,
        "explanation": (
            "All cases retain the exact frozen conversation messages, Memory content, and targets. "
            "The frozen local report used the v7 dataset's canonical system text, while this cloud "
            "run uses the current approved Identity system text; therefore no provider-facing prompt "
            "is an exact cross-provider match. Memory-bearing cases additionally use the current "
            "context-presentation-v2-natural-memory-linking renderer."
        ),
    }


async def run_broader_cloud_evaluation(
    *, output_path: Path, progress_path: Path, budget_usd: Decimal
) -> dict[str, Any]:
    if output_path.exists():
        raise FileExistsError(f"immutable evaluation output exists: {output_path}")
    if budget_usd <= 0:
        raise ValueError("cloud experiment budget must be positive")
    manifest, cases = load_and_verify_unseen()
    if len(cases) != 80 or any(
        case["privacy_class"] != "SYNTHETIC"
        or case["contains_user_data"] is not False
        or case["training_eligible"] is not False
        for case in cases
    ):
        raise ValueError("broader suite is not the exact PUBLIC synthetic 80-case set")
    manifest_hash = manifest["content_hash"]
    local_report = read_hashed_json(LOCAL_CORE_REPORT)
    identity = IdentityLoader(PROJECT_ROOT / "identity").load().system_text()
    progress = _load_progress(progress_path, manifest_hash=manifest_hash)
    completed = {row["case_id"] for row in progress["results"]}
    spent = sum(Decimal(row["cost"]["cost_usd"]) for row in progress["results"])
    policy = explicit_public_synthetic_policy()
    router = Stage1Router(
        approved_cloud_provider_ids=frozenset({DEEPSEEK_PROVIDER_ID})
    )
    prepared = [
        (case, *_request_for_case(case, identity=identity, manifest_hash=manifest_hash))
        for case in cases
    ]
    provider = DeepSeekCloudProvider(
        enabled=True,
        explicit_authorization_ref=AUTHORIZATION_REF,
        allowed_fixture_hashes=frozenset({manifest_hash}),
        allowed_request_hashes=frozenset(
            request.metadata["cloud_request_binding_hash"]
            for _, request, *_ in prepared
        ),
        thinking="enabled",
        reasoning_effort="high",
    )
    try:
        version = await provider.version()
        if version.model_version_id != DEEPSEEK_MODEL_VERSION:
            raise ValueError("DeepSeek broader live model alias binding mismatch")
        for case, request, messages, prompt_hash in prepared:
            if case["case_id"] in completed:
                continue
            route = await _decide_route_with_fresh_capabilities(
                provider=provider,
                router=router,
                request=request,
                policy=policy,
                messages=messages,
            )
            started_at = datetime.now(UTC)
            upper = preflight_cost_upper_bound(
                messages,
                at=started_at,
                max_output_tokens=MAX_OUTPUT_TOKENS,
            )
            if spent + upper > budget_usd:
                raise RuntimeError("broader cloud experiment budget ceiling reached")
            response, attempts = await _execute_with_bounded_retry(provider, request)
            raw = "\n".join(part.text for part in response.output_parts)
            history = tuple(case["memory_context"]) + tuple(
                message["content"] for message in case["messages"][:-1]
            )
            core = CoreResponsePolicy().apply(
                request_id=request.request_id,
                trace_id=request.trace_id,
                context_pack_id=request.context_pack_id,
                inference_response_id=response.inference_response_id,
                current_user_input=case["messages"][-1]["content"],
                raw_output_parts=(raw,),
                history_evidence=history,
                available_effects=(),
            )
            delivered = "\n".join(core.output_parts)
            cost = usage_cost(response.usage, at=started_at)
            spent += Decimal(cost["cost_usd"])
            progress["results"].append(
                {
                    "case_id": case["case_id"],
                    "case_hash": case["content_hash"],
                    "axis": case["axis"],
                    "dimension": case["dimension"],
                    "subcategory": case["subcategory"],
                    "critical_hard_capability": case["critical_hard_capability"],
                    "prompt_hash": prompt_hash,
                    "raw_model_output": raw,
                    "raw_model_scores": score_output(case, raw),
                    "full_havre_pipeline_output": delivered,
                    "full_pipeline_scores": score_output(case, delivered),
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
                        "selected_provider_id": route.selected_provider_id,
                        "selected_model_version_id": route.selected_model_version_id,
                        "execution_environment": route.execution_environment,
                    },
                    "completed_at": datetime.now(UTC).isoformat(),
                }
            )
            progress["updated_at"] = datetime.now(UTC).isoformat()
            _write_progress(progress_path, progress)
    finally:
        await provider.aclose()

    if len(progress["results"]) != 80:
        raise ValueError("broader cloud evaluation is incomplete")
    raw_rows = [
        {
            **{key: row[key] for key in (
                "case_id", "axis", "dimension", "subcategory", "critical_hard_capability"
            )},
            "output": row["raw_model_output"],
            "scores": row["raw_model_scores"],
        }
        for row in progress["results"]
    ]
    pipeline_rows = [
        {
            **{key: row[key] for key in (
                "case_id", "axis", "dimension", "subcategory", "critical_hard_capability"
            )},
            "output": row["full_havre_pipeline_output"],
            "scores": row["full_pipeline_scores"],
        }
        for row in progress["results"]
    ]
    latencies = sorted(row["timing_ms"]["total"] for row in progress["results"])
    ttfts = sorted(row["timing_ms"]["time_to_first_token"] for row in progress["results"])

    def percentile(values: list[float], fraction: float) -> float:
        return round(values[round((len(values) - 1) * fraction)], 3)

    prompt_comparison = prompt_comparability(cases, identity)
    report = write_hashed_json(
        output_path,
        {
            "schema_version": "strong-cloud-brain-broader-v1",
            "experiment_id": EXPERIMENT_ID,
            "status": "completed_diagnostic_evaluation",
            "evaluation_set_id": EVALUATION_SET_ID,
            "case_count": 80,
            "unseen_manifest_hash": manifest_hash,
            "local_frozen_core_report_hash": local_report["content_hash"],
            "prompt_comparability_to_frozen_local_report": prompt_comparison,
            "context_presentation_version": CONTEXT_PRESENTATION_VERSION,
            "privacy_class": "PUBLIC",
            "synthetic_only": True,
            "contains_user_data": False,
            "owner_private_data_used": False,
            "daily_chat_used": False,
            "provider_id": DEEPSEEK_PROVIDER_ID,
            "model_version_id": DEEPSEEK_MODEL_VERSION,
            "provider_adapter_version_id": DEEPSEEK_PROVIDER_ADAPTER_VERSION,
            "thinking": "enabled",
            "reasoning_effort": "high",
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "raw_model": {"summary": _summary(raw_rows), "results": raw_rows},
            "full_havre_pipeline": {
                "summary": _summary(pipeline_rows),
                "core_action_counts": {
                    action: sum(row["core_action"] == action for row in progress["results"])
                    for action in ("pass_through", "replace")
                },
                "results": pipeline_rows,
            },
            "usage": {
                "prompt_tokens": sum(row["usage"]["prompt_tokens"] for row in progress["results"]),
                "output_tokens": sum(row["usage"]["output_tokens"] for row in progress["results"]),
                "reasoning_tokens": sum((row["usage"].get("reasoning_tokens") or 0) for row in progress["results"]),
                "total_api_cost_usd": format(spent.quantize(Decimal("0.000000000001")), "f"),
                "cost_exact_for_every_request": all(row["cost"]["cost_exact_from_provider_cache_usage"] for row in progress["results"]),
            },
            "latency_ms": {
                "p50": percentile(latencies, 0.5),
                "p95": percentile(latencies, 0.95),
            },
            "ttft_ms": {
                "definition": "first final-answer content token; reasoning_content is excluded",
                "p50": percentile(ttfts, 0.5),
                "p95": percentile(ttfts, 0.95),
            },
            "budget_ceiling_usd": format(budget_usd, "f"),
            "retry_policy": f"at most {MAX_ATTEMPTS} attempts; retry only provider_rate_limited",
            "pricing_source_url": OFFICIAL_PRICING_URL,
            "pricing_verified_at": PRICING_VERIFIED_AT,
            "rates_usd_per_million_tokens": {
                period: {key: format(value, "f") for key, value in rates.items()}
                for period, rates in PRICES.items()
            },
            "training_performed": False,
            "candidate_status_changed": False,
            "daily_use_binding_changed": False,
            "promotion_authorized": False,
            "deployment_authorized": False,
            "stage9b_started": False,
            "manual_semantic_review_required": True,
            "limitations": [
                "Deterministic scores are not a semantic naturalness review.",
                "Only the focused-suite winner was run on the conditional broader suite.",
                "The broader run is an absolute regression only, not a strict local-versus-cloud attribution: the frozen local report used the v7 dataset system text while cloud uses current Identity, so 0/80 provider-facing prompts are exact matches.",
                f"{prompt_comparison['current_memory_presentation_case_count']} Memory-bearing cases additionally use the current provider-facing Memory presentation rather than the frozen legacy presentation.",
                "Provider chain-of-thought is not retained.",
                "No result authorizes routing, serving, promotion, deployment, or training.",
            ],
            "completed_at": datetime.now(UTC).isoformat(),
        },
    )
    return report
