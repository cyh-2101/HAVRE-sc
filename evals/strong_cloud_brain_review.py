"""Build integrity-bound identified and blinded Strong Cloud Brain review evidence."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from companion.policy import CoreResponsePolicy
from evals.strong_cloud_brain_ceiling import FOCUSED_SUITE_PATH, _all_cases, _load_exact_suite
from mlsys.training.stage9a_provenance import PROJECT_ROOT
from mlsys.training.stage9a_real import read_hashed_json, write_hashed_json


REPORT_DIR = PROJECT_ROOT / "evals/reports/strong_cloud_brain_20260826"
SOURCE_REPORTS = {
    "candidate_9201": REPORT_DIR / "local-9201-unseen-v1.json",
    "local_comparators": (
        PROJECT_ROOT
        / "evals/reports/relevant_memory_20260826/post-plan-unseen-replay-v2-final.json"
    ),
    "deepseek_v4_pro_thinking_disabled": REPORT_DIR / "deepseek-v4-pro-disabled-v1.json",
    "deepseek_v4_pro_thinking_enabled": REPORT_DIR / "deepseek-v4-pro-thinking-v1.json",
}
REQUIRED_ARMS = (
    "candidate_9201",
    "rejected_v7_9701",
    "memory_use_v1_9801",
    "deepseek_v4_pro_thinking_disabled",
    "deepseek_v4_pro_thinking_enabled",
)
BLINDING_VERSION = "strong-cloud-brain-focused-blinding-v1"


def _core_replay(*, arm_name: str, case: dict[str, Any], raw_output: str) -> dict[str, Any]:
    stable = f"https://havre.local/{BLINDING_VERSION}/{arm_name}/{case['case_id']}"
    result = CoreResponsePolicy().apply(
        request_id=uuid5(NAMESPACE_URL, stable + "/request"),
        trace_id=hashlib.sha256(stable.encode("utf-8")).hexdigest()[:32],
        context_pack_id=uuid5(NAMESPACE_URL, stable + "/context-pack"),
        inference_response_id=uuid5(NAMESPACE_URL, stable + "/response"),
        current_user_input=case["user_message"],
        raw_output_parts=(raw_output,),
        history_evidence=tuple(case.get("memory_context", ())),
        available_effects=(),
    )
    return {
        "output": "\n".join(result.output_parts),
        "action": result.decision.action,
        "category": result.decision.category,
        "reason_codes": list(result.decision.reason_codes),
    }


def _source_arms() -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    loaded = {name: read_hashed_json(path) for name, path in SOURCE_REPORTS.items()}
    rows: dict[str, list[dict[str, Any]]] = {}
    for arm in loaded["candidate_9201"]["arms"]:
        rows[arm["arm_name"]] = arm["results"]
    for arm in loaded["local_comparators"]["arms"]:
        if arm["arm_name"] in REQUIRED_ARMS:
            rows[arm["arm_name"]] = arm["results"]
    for source_name in (
        "deepseek_v4_pro_thinking_disabled",
        "deepseek_v4_pro_thinking_enabled",
    ):
        for arm in loaded[source_name]["arms"]:
            rows[arm["arm_name"]] = [
                row for row in arm["results"] if row["kind"] != "owner_diagnostic"
            ]
    if set(rows) != set(REQUIRED_ARMS):
        raise ValueError("focused comparison arms are incomplete or unexpected")
    return rows, {name: payload["content_hash"] for name, payload in loaded.items()}


def build_review_evidence(
    *,
    comparison_path: Path,
    blind_packet_path: Path,
    blinding_key_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    suite, suite_hash = _load_exact_suite(FOCUSED_SUITE_PATH)
    cases = _all_cases(suite)
    case_by_id = {case["case_id"]: case for case in cases}
    source_rows, source_hashes = _source_arms()
    expected_ids = [case["case_id"] for case in cases]

    identified_arms = []
    normalized_by_arm: dict[str, dict[str, dict[str, Any]]] = {}
    for arm_name in REQUIRED_ARMS:
        arm_rows = source_rows[arm_name]
        if [row["case_id"] for row in arm_rows] != expected_ids:
            raise ValueError(f"case order or membership mismatch for {arm_name}")
        normalized: dict[str, dict[str, Any]] = {}
        replacement_count = 0
        for source_row in arm_rows:
            case = case_by_id[source_row["case_id"]]
            raw_output = source_row.get("raw_model_output", source_row.get("output"))
            if not isinstance(raw_output, str) or not raw_output:
                raise ValueError(f"missing raw output for {arm_name}/{case['case_id']}")
            replay = _core_replay(arm_name=arm_name, case=case, raw_output=raw_output)
            if "full_havre_pipeline_output" in source_row:
                if source_row["full_havre_pipeline_output"] != replay["output"]:
                    raise ValueError(f"cloud Core replay mismatch for {arm_name}/{case['case_id']}")
                if source_row["core_action"] != replay["action"]:
                    raise ValueError(f"cloud Core action mismatch for {arm_name}/{case['case_id']}")
            replacement_count += replay["action"] == "replace"
            normalized[case["case_id"]] = {
                "case_id": case["case_id"],
                "prompt_hash": source_row["prompt_hash"],
                "raw_model_output": raw_output,
                "full_havre_pipeline_output": replay["output"],
                "core": {
                    "action": replay["action"],
                    "category": replay["category"],
                    "reason_codes": replay["reason_codes"],
                },
            }
        normalized_by_arm[arm_name] = normalized
        identified_arms.append(
            {
                "arm_name": arm_name,
                "case_count": len(normalized),
                "core_replacement_count": replacement_count,
                "results": list(normalized.values()),
            }
        )

    for case_id in expected_ids:
        prompt_hashes = {
            normalized_by_arm[arm][case_id]["prompt_hash"] for arm in REQUIRED_ARMS
        }
        if len(prompt_hashes) != 1:
            raise ValueError(f"provider-facing prompt mismatch for {case_id}")

    comparison = write_hashed_json(
        comparison_path,
        {
            "schema_version": "strong-cloud-brain-focused-comparison-v1",
            "suite_hash": suite_hash,
            "source_report_hashes": source_hashes,
            "arm_count": len(REQUIRED_ARMS),
            "case_count_per_arm": len(cases),
            "same_provider_facing_prompt_per_case": True,
            "core_policy_version": CoreResponsePolicy.version,
            "raw_model_and_full_pipeline_reported_separately": True,
            "arms": identified_arms,
            "created_at": datetime.now(UTC).isoformat(),
        },
    )

    ordered = sorted(
        REQUIRED_ARMS,
        key=lambda name: hashlib.sha256(
            f"{BLINDING_VERSION}:{name}".encode("utf-8")
        ).hexdigest(),
    )
    labels = {arm_name: f"arm_{index:02d}" for index, arm_name in enumerate(ordered, 1)}
    blinded_cases = []
    for case in cases:
        blinded_cases.append(
            {
                "case_id": case["case_id"],
                "kind": case["kind"],
                "pair_id": case.get("pair_id"),
                "variant": case.get("variant"),
                "user_message": case["user_message"],
                "memory_context": case.get("memory_context", []),
                "outputs": [
                    {
                        "arm_label": labels[arm_name],
                        "full_havre_pipeline_output": normalized_by_arm[arm_name][
                            case["case_id"]
                        ]["full_havre_pipeline_output"],
                    }
                    for arm_name in ordered
                ],
            }
        )
    blind_packet = write_hashed_json(
        blind_packet_path,
        {
            "schema_version": "strong-cloud-brain-focused-blind-review-v1",
            "blinding_version": BLINDING_VERSION,
            "suite_hash": suite_hash,
            "comparison_hash": comparison["content_hash"],
            "arm_labels": [labels[name] for name in ordered],
            "case_count": len(blinded_cases),
            "manual_rubric": suite["manual_rubric"],
            "review_instructions": {
                "score_each_output": True,
                "dimensions": list(suite["manual_rubric"]),
                "strict_case_pass": "all applicable dimensions pass",
                "do_not_use_keyword_hits_as_semantic_judgment": True,
            },
            "cases": blinded_cases,
        },
    )
    key = write_hashed_json(
        blinding_key_path,
        {
            "schema_version": "strong-cloud-brain-focused-blinding-key-v1",
            "blinding_version": BLINDING_VERSION,
            "blind_packet_hash": blind_packet["content_hash"],
            "mapping": labels,
        },
    )
    return comparison, blind_packet, key
