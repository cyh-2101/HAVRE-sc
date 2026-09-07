"""Build a blinded three-arm review packet for broader companion quality."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from mlsys.training.stage9a_core_responsibility import REPORT_PATH as LOCAL_CORE_REPORT
from mlsys.training.stage9a_real import read_hashed_json, write_hashed_json
from mlsys.training.stage9a_unseen_v7 import load_and_verify_unseen


ARMS = (
    "candidate_9201",
    "candidate_v7_9701",
    "deepseek_v4_pro_thinking_enabled",
)
BLINDING_VERSION = "strong-cloud-brain-broader-companion-blinding-v1"


def build_broader_review_evidence(
    *,
    cloud_report_path: Path,
    packet_path: Path,
    key_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    cloud = read_hashed_json(cloud_report_path)
    local = read_hashed_json(LOCAL_CORE_REPORT)
    _, cases = load_and_verify_unseen()
    companion_cases = [case for case in cases if case["axis"] == "companion_quality"]
    exact_prompt_ids = set(
        cloud["prompt_comparability_to_frozen_local_report"]["exact_same_case_ids"]
    )
    by_arm: dict[str, dict[str, str]] = {}
    for arm in local["arms"]:
        if arm["arm_name"] in ARMS:
            by_arm[arm["arm_name"]] = {
                row["case_id"]: row["output"]
                for row in arm["full_havre_pipeline"]["results"]
            }
    by_arm["deepseek_v4_pro_thinking_enabled"] = {
        row["case_id"]: row["output"]
        for row in cloud["full_havre_pipeline"]["results"]
    }
    if set(by_arm) != set(ARMS):
        raise ValueError("broader review arms are incomplete")
    expected_ids = {case["case_id"] for case in companion_cases}
    if any(set(rows) != {case["case_id"] for case in cases} for rows in by_arm.values()):
        raise ValueError("broader review source membership mismatch")

    ordered = sorted(
        ARMS,
        key=lambda name: hashlib.sha256(
            f"{BLINDING_VERSION}:{name}".encode("utf-8")
        ).hexdigest(),
    )
    labels = {name: f"arm_{index:02d}" for index, name in enumerate(ordered, 1)}
    packet = write_hashed_json(
        packet_path,
        {
            "schema_version": "strong-cloud-brain-broader-blind-review-v1",
            "blinding_version": BLINDING_VERSION,
            "cloud_report_hash": cloud["content_hash"],
            "local_report_hash": local["content_hash"],
            "case_count": len(companion_cases),
            "output_count": len(companion_cases) * len(ARMS),
            "arm_labels": [labels[name] for name in ordered],
            "review_dimensions": [
                "naturalness",
                "primary_dimension_quality",
                "truthfulness_and_provenance",
                "uncertainty",
                "agency",
            ],
            "strict_case_pass": "all applicable review dimensions pass",
            "cases": [
                {
                    "case_id": case["case_id"],
                    "dimension": case["dimension"],
                    "subcategory": case["subcategory"],
                    "expected_mode": case["expected_mode"],
                    "messages": case["messages"],
                    "memory_context": case["memory_context"],
                    "exact_same_provider_facing_prompt_across_local_and_cloud": (
                        case["case_id"] in exact_prompt_ids
                    ),
                    "outputs": [
                        {
                            "arm_label": labels[name],
                            "full_havre_pipeline_output": by_arm[name][case["case_id"]],
                        }
                        for name in ordered
                    ],
                }
                for case in companion_cases
            ],
        },
    )
    key = write_hashed_json(
        key_path,
        {
            "schema_version": "strong-cloud-brain-broader-blinding-key-v1",
            "blinding_version": BLINDING_VERSION,
            "packet_hash": packet["content_hash"],
            "mapping": labels,
        },
    )
    if expected_ids != {case["case_id"] for case in packet["cases"]}:
        raise ValueError("broader packet companion membership mismatch")
    return packet, key
