"""Derive the bounded Strong Cloud Brain decision from integrity-bound evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from evals.strong_cloud_brain_cost import verify_cost_evidence
from mlsys.training.stage9a_provenance import PROJECT_ROOT
from mlsys.training.stage9a_real import read_hashed_json, write_hashed_json
from mlsys.training.stage9a_core_responsibility import REPORT_PATH as LOCAL_BROADER


REPORT_DIR = PROJECT_ROOT / "evals/reports/strong_cloud_brain_20260826"
FOCUSED_COMPARISON = REPORT_DIR / "focused-comparison-v1.json"
FOCUSED_KEY = REPORT_DIR / "focused-blinding-key-v1.json"
FOCUSED_PACKET = REPORT_DIR / "focused-blind-review-v1.json"
FOCUSED_REVIEW = REPORT_DIR / "focused-independent-semantic-review-v1.json"
LOCAL_9201 = REPORT_DIR / "local-9201-unseen-v1.json"
LOCAL_COMPARATORS = (
    PROJECT_ROOT
    / "evals/reports/relevant_memory_20260826/post-plan-unseen-replay-v2-final.json"
)
FOCUSED_CLOUD = {
    "deepseek_v4_pro_thinking_disabled": REPORT_DIR / "deepseek-v4-pro-disabled-v1.json",
    "deepseek_v4_pro_thinking_enabled": REPORT_DIR / "deepseek-v4-pro-thinking-v1.json",
}
BROADER_CLOUD = REPORT_DIR / "deepseek-v4-pro-thinking-broader-v3-final.json"
BROADER_PACKET = REPORT_DIR / "broader-companion-blind-review-v2-final.json"
BROADER_KEY = REPORT_DIR / "broader-companion-blinding-key-v2-final.json"
BROADER_REVIEW = REPORT_DIR / "broader-companion-independent-semantic-review-v2-final.json"
COST_EVIDENCE = REPORT_DIR / "formal-cost-evidence-v1.json"


def _file_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _load_review(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"review is not an object: {path}")
    return payload


def _identified_review(
    *, review: dict[str, Any], mapping: dict[str, str], label_field: str
) -> dict[str, dict[str, Any]]:
    by_label = {row[label_field]: row for row in review["arms"]}
    if set(by_label) != set(mapping.values()):
        raise ValueError("review labels do not match the blinding key")
    return {name: by_label[label] for name, label in mapping.items()}


def _verify_focused_review(
    packet: dict[str, Any], review: dict[str, Any], labels: set[str]
) -> None:
    dimensions = (
        "naturalness",
        "usefulness",
        "provenance_truth",
        "fabricated_familiarity",
        "forced_callback",
        "ignored_relevant_history",
        "current_message_precedence",
    )
    if (
        len(review["case_reviews"]) != 32
        or len(packet["cases"]) != 32
        or set(packet["arm_labels"]) != labels
    ):
        raise ValueError("focused review case membership mismatch")
    summaries: dict[str, dict[str, Any]] = {}
    for label in labels:
        summaries[label] = {
            "arm_label": label,
            "strict_pass_count": 0,
            "case_count": 32,
            "paired_strict_pass": 0,
            "paired_count": 20,
            "multi_memory_strict_pass": 0,
            "multi_memory_count": 4,
            "casual_strict_pass": 0,
            "casual_count": 8,
            "dimension_pass": {
                name: {"pass": 0, "applicable": 0} for name in dimensions
            },
            "critical_failures": {
                "provenance_truth": [],
                "fabricated_familiarity": [],
                "current_message_precedence": [],
            },
            "forced_callback_failures": [],
            "ignored_relevant_history_failures": [],
        }
    case_ids: set[str] = set()
    for packet_case, case in zip(packet["cases"], review["case_reviews"], strict=True):
        if any(
            packet_case.get(name) != case.get(name)
            for name in ("case_id", "kind", "variant")
        ):
            raise ValueError("focused review case metadata does not match blind packet")
        if {row["arm_label"] for row in packet_case["outputs"]} != labels:
            raise ValueError("focused blind packet arm membership mismatch")
        case_id = case["case_id"]
        if case_id in case_ids:
            raise ValueError("duplicate focused review case")
        case_ids.add(case_id)
        by_label = {row["arm_label"]: row for row in case["arm_reviews"]}
        if set(by_label) != labels:
            raise ValueError("focused review arm membership mismatch")
        for label, row in by_label.items():
            if set(row["dimensions"]) != set(dimensions):
                raise ValueError("focused review dimension membership mismatch")
            applicable = [value for value in row["dimensions"].values() if value is not None]
            if row["strict_case_pass"] != all(applicable):
                raise ValueError("focused strict score mismatch")
            summary = summaries[label]
            summary["strict_pass_count"] += bool(row["strict_case_pass"])
            kind = case["kind"]
            field = {
                "paired_memory": "paired_strict_pass",
                "multi_memory": "multi_memory_strict_pass",
                "casual_regression": "casual_strict_pass",
            }[kind]
            summary[field] += bool(row["strict_case_pass"])
            for name, value in row["dimensions"].items():
                if value is not None:
                    summary["dimension_pass"][name]["applicable"] += 1
                    summary["dimension_pass"][name]["pass"] += bool(value)
            for name in summary["critical_failures"]:
                if row["dimensions"][name] is False:
                    summary["critical_failures"][name].append(case_id)
            if row["dimensions"]["forced_callback"] is False:
                summary["forced_callback_failures"].append(case_id)
            if row["dimensions"]["ignored_relevant_history"] is False:
                summary["ignored_relevant_history_failures"].append(case_id)
    observed = {row["arm_label"]: row for row in review["arms"]}
    if observed != summaries:
        raise ValueError("focused review summary does not match per-case scores")


def _verify_broader_review(
    packet: dict[str, Any], review: dict[str, Any], labels: set[str]
) -> None:
    dimensions = tuple(review["review_dimension_order"])
    if (
        len(review["case_reviews"]) != 40
        or len(packet["cases"]) != 40
        or len(dimensions) != 5
        or set(packet["arm_labels"]) != labels
    ):
        raise ValueError("broader review membership mismatch")
    summaries: dict[str, dict[str, Any]] = {
        label: {
            "arm_label": label,
            "strict_pass": {"pass": 0, "applicable": 40},
            "dimension_pass": {
                name: {"pass": 0, "applicable": 0} for name in dimensions
            },
            "case_dimension_strict": {},
            "prompt_exact_subsets": {
                "true": {"pass": 0, "applicable": 0},
                "false": {"pass": 0, "applicable": 0},
            },
        }
        for label in labels
    }
    case_ids: set[str] = set()
    for packet_case, case in zip(packet["cases"], review["case_reviews"], strict=True):
        if (
            packet_case.get("case_id") != case.get("case_id")
            or packet_case.get("dimension") != case.get("dimension")
            or packet_case.get(
                "exact_same_provider_facing_prompt_across_local_and_cloud"
            )
            != case.get("prompt_exact")
        ):
            raise ValueError("broader review case metadata does not match blind packet")
        if {row["arm_label"] for row in packet_case["outputs"]} != labels:
            raise ValueError("broader blind packet arm membership mismatch")
        case_id = case["case_id"]
        if case_id in case_ids:
            raise ValueError("duplicate broader review case")
        case_ids.add(case_id)
        by_label = {row["arm_label"]: row for row in case["arm_reviews"]}
        if set(by_label) != labels:
            raise ValueError("broader review arm membership mismatch")
        subset = str(bool(case["prompt_exact"])).lower()
        category = case["dimension"]
        for label, row in by_label.items():
            if len(row["scores"]) != len(dimensions):
                raise ValueError("broader review dimension membership mismatch")
            applicable = [value for value in row["scores"] if value is not None]
            if row["strict_case_pass"] != all(applicable):
                raise ValueError("broader strict score mismatch")
            summary = summaries[label]
            summary["strict_pass"]["pass"] += bool(row["strict_case_pass"])
            summary["prompt_exact_subsets"][subset]["applicable"] += 1
            summary["prompt_exact_subsets"][subset]["pass"] += bool(row["strict_case_pass"])
            category_summary = summary["case_dimension_strict"].setdefault(
                category, {"pass": 0, "applicable": 0}
            )
            category_summary["applicable"] += 1
            category_summary["pass"] += bool(row["strict_case_pass"])
            for name, value in zip(dimensions, row["scores"], strict=True):
                if value is not None:
                    summary["dimension_pass"][name]["applicable"] += 1
                    summary["dimension_pass"][name]["pass"] += bool(value)
    observed = {row["arm_label"]: row for row in review["arms"]}
    if observed != summaries:
        raise ValueError("broader review summary does not match per-case scores")


def build_decision_evidence(*, output_path: Path) -> dict[str, Any]:
    focused_comparison = read_hashed_json(FOCUSED_COMPARISON)
    focused_key = read_hashed_json(FOCUSED_KEY)
    focused_packet = read_hashed_json(FOCUSED_PACKET)
    focused_review = _load_review(FOCUSED_REVIEW)
    focused_sources = {
        "candidate_9201": read_hashed_json(LOCAL_9201)["content_hash"],
        "local_comparators": read_hashed_json(LOCAL_COMPARATORS)["content_hash"],
        **{
            name: read_hashed_json(path)["content_hash"]
            for name, path in FOCUSED_CLOUD.items()
        },
    }
    if focused_comparison["source_report_hashes"] != focused_sources:
        raise ValueError("focused comparison source graph mismatch")
    if focused_packet["comparison_hash"] != focused_comparison["content_hash"]:
        raise ValueError("focused blind packet is not bound to the comparison")
    if focused_key["blind_packet_hash"] != focused_packet["content_hash"]:
        raise ValueError("focused blinding key is not bound to the final packet")
    if focused_review["blind_packet_hash"] != focused_packet["content_hash"]:
        raise ValueError("focused review is not bound to the final blind packet")
    focused = _identified_review(
        review=focused_review,
        mapping=focused_key["mapping"],
        label_field="arm_label",
    )
    _verify_focused_review(
        focused_packet, focused_review, set(focused_key["mapping"].values())
    )
    broader_cloud = read_hashed_json(BROADER_CLOUD)
    broader_packet = read_hashed_json(BROADER_PACKET)
    broader_key = read_hashed_json(BROADER_KEY)
    broader_review = _load_review(BROADER_REVIEW)
    local_broader = read_hashed_json(LOCAL_BROADER)
    if broader_packet["cloud_report_hash"] != broader_cloud["content_hash"]:
        raise ValueError("broader packet cloud source mismatch")
    if broader_packet["local_report_hash"] != local_broader["content_hash"]:
        raise ValueError("broader packet local source mismatch")
    if broader_key["packet_hash"] != broader_packet["content_hash"]:
        raise ValueError("broader blinding key is not bound to the final packet")
    if broader_review["blind_packet_hash"] != broader_packet["content_hash"]:
        raise ValueError("broader review is not bound to the final blind packet")
    broader = _identified_review(
        review=broader_review,
        mapping=broader_key["mapping"],
        label_field="arm_label",
    )
    _verify_broader_review(
        broader_packet, broader_review, set(broader_key["mapping"].values())
    )
    if broader_cloud["prompt_comparability_to_frozen_local_report"][
        "exact_same_provider_facing_prompt_case_count"
    ] != 0:
        raise ValueError("broader attribution boundary changed")

    cloud_metrics: dict[str, Any] = {}
    exact_formal_cost = Decimal(broader_cloud["usage"]["total_api_cost_usd"])
    focused_cloud_hashes: dict[str, str] = {}
    for arm_name, path in FOCUSED_CLOUD.items():
        report = read_hashed_json(path)
        arm = report["arms"][0]
        if arm["arm_name"] != arm_name:
            raise ValueError("focused cloud arm mismatch")
        focused_cloud_hashes[arm_name] = report["content_hash"]
        summary = arm["summary"]
        cloud_metrics[arm_name] = {
            "request_count": summary["request_count"],
            "prompt_tokens": summary["prompt_tokens"],
            "output_tokens": summary["output_tokens"],
            "reasoning_tokens": summary["reasoning_tokens"],
            "cost_usd": summary["total_api_cost_usd"],
            "latency_ms": summary["latency_ms"],
            "ttft_ms": summary["ttft_ms"],
        }
        exact_formal_cost += Decimal(summary["total_api_cost_usd"])
    if exact_formal_cost != Decimal("0.240205504000"):
        raise ValueError("formal completed-report cost ledger mismatch")
    cost_evidence = read_hashed_json(COST_EVIDENCE)
    if verify_cost_evidence(cost_evidence) != exact_formal_cost:
        raise ValueError("formal per-request cost evidence total mismatch")
    expected_cost_reports = {
        "focused_non_thinking": focused_cloud_hashes[
            "deepseek_v4_pro_thinking_disabled"
        ],
        "focused_thinking_high": focused_cloud_hashes[
            "deepseek_v4_pro_thinking_enabled"
        ],
        "broader_thinking_high": broader_cloud["content_hash"],
    }
    if cost_evidence["source_report_hashes"] != expected_cost_reports:
        raise ValueError("formal cost evidence report graph mismatch")

    focused_summary = {
        name: {
            "strict_pass": row["strict_pass_count"],
            "case_count": row["case_count"],
            "paired_strict_pass": row["paired_strict_pass"],
            "multi_memory_strict_pass": row["multi_memory_strict_pass"],
            "casual_strict_pass": row["casual_strict_pass"],
            "dimension_pass": row["dimension_pass"],
        }
        for name, row in focused.items()
    }
    cloud_thinking = focused_summary["deepseek_v4_pro_thinking_enabled"]
    best_local = max(
        focused_summary[name]["strict_pass"]
        for name in ("candidate_9201", "rejected_v7_9701", "memory_use_v1_9801")
    )
    if cloud_thinking["strict_pass"] - best_local < 5:
        raise ValueError("the checked-in broader-run trigger is no longer met")

    return write_hashed_json(
        output_path,
        {
            "schema_version": "strong-cloud-brain-decision-evidence-v1",
            "decision": "C_both_model_capability_and_system_containment_matter",
            "focused_attribution": {
                "same_provider_facing_prompt_per_case": True,
                "case_count": 32,
                "arms": focused_summary,
                "best_local_strict_pass": best_local,
                "cloud_thinking_strict_pass": cloud_thinking["strict_pass"],
                "cloud_thinking_delta_vs_best_local": cloud_thinking["strict_pass"] - best_local,
                "generation_budget_boundary": (
                    "Thinking used max_tokens=4096 because hidden reasoning and final answer share the provider limit; "
                    "local and non-thinking arms used 96. The gain is model-plus-inference-compute evidence."
                ),
            },
            "broader_absolute_regression": {
                "strictly_attributable_to_model": False,
                "exact_prompt_matches": 0,
                "case_count": 40,
                "arms": {
                    name: {
                        "strict_pass": row["strict_pass"],
                        "dimension_pass": row["dimension_pass"],
                        "case_dimension_strict": row["case_dimension_strict"],
                    }
                    for name, row in broader.items()
                },
                "boundary": broader_review["comparability_statement"],
            },
            "cloud_metrics": {
                "focused": cloud_metrics,
                "broader_thinking": {
                    "request_count": broader_cloud["case_count"],
                    **broader_cloud["usage"],
                    "latency_ms": broader_cloud["latency_ms"],
                    "ttft_ms": broader_cloud["ttft_ms"],
                },
            },
            "cost_ledger_usd": {
                "formal_completed_reports": "0.240205504000",
                "budget_ceiling": "1.00",
                "operator_log_not_independently_reproducible": {
                    "incomplete_1024_diagnostic_successful_rows": "0.025235584000",
                    "failed_token_budget_calls_conservative_upper_bound": "0.016938240000",
                    "note": "Not source-bound in repository evidence; excluded from the verified formal cost total and all quality results.",
                },
            },
            "conclusion": {
                "model_capability_is_major_memory_use_bottleneck": True,
                "context_and_core_remain_essential": True,
                "training_performed": False,
                "daily_use_candidate": "candidate_9201",
                "daily_use_reason": (
                    "9201 remains the unchanged authorized binding; cloud thinking has stronger focused Memory use "
                    "but worse casual naturalness/verbosity and one fabricated-familiarity failure."
                ),
                "candidate_status_changed": False,
                "routing_or_serving_activated": False,
                "promotion_or_deployment": False,
            },
            "source_hashes": {
                "focused_key": focused_key["content_hash"],
                "focused_packet": focused_packet["content_hash"],
                "focused_comparison": focused_comparison["content_hash"],
                "focused_independent_review_file": _file_hash(FOCUSED_REVIEW),
                "broader_cloud": broader_cloud["content_hash"],
                "broader_packet": broader_packet["content_hash"],
                "broader_key": broader_key["content_hash"],
                "broader_independent_review_file": _file_hash(BROADER_REVIEW),
                "formal_cost_evidence": cost_evidence["content_hash"],
            },
            "created_at": datetime.now(UTC).isoformat(),
        },
    )
