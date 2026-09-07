"""Build a prompt-free, independently recomputable formal cloud cost ledger."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from evals.strong_cloud_brain_ceiling import PRICES
from mlsys.training.stage9a_provenance import PROJECT_ROOT
from mlsys.training.stage9a_real import read_hashed_json, write_hashed_json


REPORT_DIR = PROJECT_ROOT / "evals/reports/strong_cloud_brain_20260826"
PROGRESS_DIR = PROJECT_ROOT / "var/strong-cloud-brain"
SOURCES = (
    (
        "focused_non_thinking",
        PROGRESS_DIR / "focused-progress-v1.json",
        "deepseek_v4_pro_thinking_disabled",
        REPORT_DIR / "deepseek-v4-pro-disabled-v1.json",
    ),
    (
        "focused_thinking_high",
        PROGRESS_DIR / "focused-thinking-4096-progress-v1.json",
        "deepseek_v4_pro_thinking_enabled",
        REPORT_DIR / "deepseek-v4-pro-thinking-v1.json",
    ),
    (
        "broader_thinking_high",
        PROGRESS_DIR / "broader-thinking-4096-progress-v1.json",
        None,
        REPORT_DIR / "deepseek-v4-pro-thinking-broader-v3-final.json",
    ),
)


def _file_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def recompute_cost(row: dict[str, Any]) -> str:
    usage = row["usage"]
    hit = usage["prompt_cache_hit_tokens"]
    miss = usage["prompt_cache_miss_tokens"]
    prompt = usage["prompt_tokens"]
    output = usage["output_tokens"]
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in (hit, miss, prompt, output)):
        raise ValueError("formal cost ledger has invalid token usage")
    if hit + miss != prompt:
        raise ValueError("formal cost ledger cache usage is not exact")
    period = row["pricing_period"]
    if period not in PRICES:
        raise ValueError("formal cost ledger has an unknown pricing period")
    rates = PRICES[period]
    value = (
        Decimal(hit) * rates["cache_hit_input"]
        + Decimal(miss) * rates["cache_miss_input"]
        + Decimal(output) * rates["output"]
    ) / Decimal(1_000_000)
    return format(value.quantize(Decimal("0.000000000001")), "f")


def verify_cost_evidence(payload: dict[str, Any]) -> Decimal:
    total = Decimal(0)
    seen: set[tuple[str, str]] = set()
    for run in payload["runs"]:
        run_cost = Decimal(0)
        prompt = output = reasoning = 0
        for row in run["requests"]:
            key = (run["run_name"], row["case_id"])
            if key in seen:
                raise ValueError("duplicate formal cost ledger request")
            seen.add(key)
            expected = recompute_cost(row)
            if row["cost_usd"] != expected:
                raise ValueError("formal cost ledger request cost mismatch")
            run_cost += Decimal(expected)
            prompt += row["usage"]["prompt_tokens"]
            output += row["usage"]["output_tokens"]
            reasoning += row["usage"].get("reasoning_tokens") or 0
        if run["request_count"] != len(run["requests"]):
            raise ValueError("formal cost ledger request count mismatch")
        expected_summary = {
            "prompt_tokens": prompt,
            "output_tokens": output,
            "reasoning_tokens": reasoning,
            "cost_usd": format(run_cost.quantize(Decimal("0.000000000001")), "f"),
        }
        if run["summary"] != expected_summary:
            raise ValueError("formal cost ledger run summary mismatch")
        total += run_cost
    if payload["formal_total_cost_usd"] != format(
        total.quantize(Decimal("0.000000000001")), "f"
    ):
        raise ValueError("formal cost ledger total mismatch")
    return total


def build_cost_evidence(*, output_path: Path) -> dict[str, Any]:
    runs = []
    report_hashes: dict[str, str] = {}
    progress_hashes: dict[str, str] = {}
    for run_name, progress_path, arm_name, report_path in SOURCES:
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        report = read_hashed_json(report_path)
        source_rows = (
            progress["results"] if arm_name is None else progress["arms"][arm_name]["results"]
        )
        report_rows = (
            report["full_havre_pipeline"]["results"]
            if arm_name is None
            else report["arms"][0]["results"]
        )
        if [row["case_id"] for row in source_rows] != [row["case_id"] for row in report_rows]:
            raise ValueError(f"formal cost source membership mismatch for {run_name}")
        requests = []
        for row in source_rows:
            cost = row["cost"]
            request = {
                "case_id": row["case_id"],
                "pricing_period": cost["pricing_period"],
                "usage": {
                    key: row["usage"].get(key)
                    for key in (
                        "prompt_tokens",
                        "prompt_cache_hit_tokens",
                        "prompt_cache_miss_tokens",
                        "output_tokens",
                        "reasoning_tokens",
                    )
                },
                "cost_usd": cost["cost_usd"],
            }
            if request["cost_usd"] != recompute_cost(request):
                raise ValueError(f"source request cost mismatch for {run_name}")
            requests.append(request)
        prompt = sum(row["usage"]["prompt_tokens"] for row in requests)
        output = sum(row["usage"]["output_tokens"] for row in requests)
        reasoning = sum(row["usage"].get("reasoning_tokens") or 0 for row in requests)
        total = sum(Decimal(row["cost_usd"]) for row in requests)
        summary = {
            "prompt_tokens": prompt,
            "output_tokens": output,
            "reasoning_tokens": reasoning,
            "cost_usd": format(total.quantize(Decimal("0.000000000001")), "f"),
        }
        report_summary = (
            report["usage"] if arm_name is None else report["arms"][0]["summary"]
        )
        if (
            report_summary["prompt_tokens"] != prompt
            or report_summary["output_tokens"] != output
            or report_summary["reasoning_tokens"] != reasoning
            or report_summary["total_api_cost_usd"] != summary["cost_usd"]
        ):
            raise ValueError(f"formal report aggregate mismatch for {run_name}")
        runs.append(
            {
                "run_name": run_name,
                "request_count": len(requests),
                "summary": summary,
                "requests": requests,
            }
        )
        report_hashes[run_name] = report["content_hash"]
        progress_hashes[run_name] = _file_hash(progress_path)
    payload = {
        "schema_version": "strong-cloud-brain-formal-cost-evidence-v1",
        "privacy_class": "PUBLIC",
        "synthetic_only": True,
        "contains_prompts_or_outputs": False,
        "pricing_rates_usd_per_million_tokens": {
            period: {name: format(value, "f") for name, value in rates.items()}
            for period, rates in PRICES.items()
        },
        "source_report_hashes": report_hashes,
        "source_progress_file_hashes": progress_hashes,
        "runs": runs,
        "formal_total_cost_usd": format(
            sum(Decimal(run["summary"]["cost_usd"]) for run in runs).quantize(
                Decimal("0.000000000001")
            ),
            "f",
        ),
    }
    verify_cost_evidence(payload)
    return write_hashed_json(output_path, payload)
