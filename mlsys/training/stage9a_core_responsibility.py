"""Replay frozen Stage 9A v7 generations through the production Core gate.

This does not generate new model output and is never training/tuning evidence.
It separates raw-model behavior from the owner-visible delivery path using the
same 80 post-plan unseen cases and their exact frozen five-arm generations.
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from companion.hashing import content_hash
from companion.policy import CoreResponsePolicy
from evals.inference_runner import current_source_revision
from mlsys.training.stage9a_evaluation_v7 import OUTPUT_ROOT as RAW_OUTPUT_ROOT
from mlsys.training.stage9a_provenance import STAGE9A_ROOT
from mlsys.training.stage9a_real import read_hashed_json, write_hashed_json
from mlsys.training.stage9a_unseen_v7 import (
    EVALUATION_SET_ID,
    load_and_verify_unseen,
    score_output,
)


AUDIT_ID = "stage9a-v7-model-vs-core-responsibility-v3"
OUTPUT_ROOT = STAGE9A_ROOT / "evaluation" / AUDIT_ID
REPORT_PATH = OUTPUT_ROOT / "report.json"


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_axis: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_dimension: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_axis[row["axis"]].append(row)
        by_dimension[row["dimension"]].append(row)

    def summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
        critical = [row for row in items if row["critical_hard_capability"]]
        return {
            "case_count": len(items),
            "deterministic_pass_count": sum(
                bool(row["scores"]["deterministic_pass"]) for row in items
            ),
            "critical_case_count": len(critical),
            "critical_pass_count": sum(
                bool(row["scores"]["critical_hard_capability_pass"])
                for row in critical
            ),
            "mean_output_chars": (
                sum(row["scores"]["output_chars"] for row in items) / len(items)
                if items
                else 0.0
            ),
        }

    return {
        "by_axis": {key: summarize(value) for key, value in sorted(by_axis.items())},
        "by_dimension": {
            key: summarize(value) for key, value in sorted(by_dimension.items())
        },
        "no_cross_axis_composite": True,
    }


def run_core_responsibility_audit() -> dict[str, Any]:
    if OUTPUT_ROOT.exists():
        raise FileExistsError(f"immutable Core audit root exists: {OUTPUT_ROOT}")
    unseen_manifest, cases = load_and_verify_unseen()
    raw_report = read_hashed_json(RAW_OUTPUT_ROOT / "report.json")
    if (
        raw_report.get("evaluation_set_id") != EVALUATION_SET_ID
        or raw_report.get("arm_count") != 5
        or any(len(arm.get("results", ())) != 80 for arm in raw_report.get("arms", ()))
    ):
        raise ValueError("frozen five-arm report is not the exact v7 unseen evidence")

    cases_by_id = {case["case_id"]: case for case in cases}
    policy = CoreResponsePolicy()
    arms: list[dict[str, Any]] = []
    for arm in raw_report["arms"]:
        raw_rows: list[dict[str, Any]] = []
        pipeline_rows: list[dict[str, Any]] = []
        action_counts: Counter[str] = Counter()
        category_counts: Counter[str] = Counter()
        for raw in arm["results"]:
            case = cases_by_id[raw["case_id"]]
            history = tuple(case["memory_context"]) + tuple(
                message["content"] for message in case["messages"][:-1]
            )
            result = policy.apply(
                request_id=uuid5(NAMESPACE_URL, f"{AUDIT_ID}/{arm['arm_name']}/{case['case_id']}/request"),
                trace_id=hashlib.sha256(
                    f"{AUDIT_ID}/{arm['arm_name']}/{case['case_id']}".encode("utf-8")
                ).hexdigest()[:32],
                context_pack_id=uuid5(NAMESPACE_URL, f"{AUDIT_ID}/{arm['arm_name']}/{case['case_id']}/context"),
                inference_response_id=uuid5(NAMESPACE_URL, f"{AUDIT_ID}/{arm['arm_name']}/{case['case_id']}/response"),
                current_user_input=case["messages"][-1]["content"],
                raw_output_parts=(raw["output"],),
                history_evidence=history,
                available_effects=(),
            )
            delivered = "\n".join(result.output_parts)
            raw_row = {
                "case_id": case["case_id"],
                "axis": case["axis"],
                "dimension": case["dimension"],
                "subcategory": case["subcategory"],
                "critical_hard_capability": case["critical_hard_capability"],
                "output": raw["output"],
                "scores": score_output(case, raw["output"]),
            }
            pipeline_row = {
                **{key: raw_row[key] for key in (
                    "case_id", "axis", "dimension", "subcategory",
                    "critical_hard_capability",
                )},
                "output": delivered,
                "scores": score_output(case, delivered),
                "core_action": result.decision.action,
                "core_category": result.decision.category,
                "core_reason_codes": list(result.decision.reason_codes),
                "raw_output_content_hash": result.decision.raw_output_content_hash,
                "delivered_output_content_hash": result.decision.delivered_output_content_hash,
            }
            raw_rows.append(raw_row)
            pipeline_rows.append(pipeline_row)
            action_counts[result.decision.action] += 1
            category_counts[result.decision.category] += 1
        arms.append(
            {
                "arm_name": arm["arm_name"],
                "candidate_status_unchanged": True,
                "raw_model": {"summary": _summary(raw_rows), "results": raw_rows},
                "full_havre_pipeline": {
                    "summary": _summary(pipeline_rows),
                    "core_action_counts": dict(sorted(action_counts.items())),
                    "core_category_counts": dict(sorted(category_counts.items())),
                    "results": pipeline_rows,
                },
            }
        )

    OUTPUT_ROOT.mkdir(parents=True)
    return write_hashed_json(
        REPORT_PATH,
        {
            "schema_version": 1,
            "audit_id": AUDIT_ID,
            "status": "completed_system_responsibility_audit",
            "evaluation_set_id": EVALUATION_SET_ID,
            "case_count": 80,
            "arm_count": 5,
            "raw_five_arm_report_hash": raw_report["content_hash"],
            "unseen_manifest_hash": unseen_manifest["content_hash"],
            "core_policy_version": policy.version,
            "source_revision": current_source_revision(Path(__file__).resolve().parents[2]),
            "method": (
                "deterministic replay of the exact frozen raw generations through "
                "the production CoreResponsePolicy integrated before InteractionService delivery"
            ),
            "raw_model_and_pipeline_reported_separately": True,
            "no_model_generation_or_training": True,
            "no_prompt_change": True,
            "training_eligible": False,
            "validation_for_training": False,
            "hyperparameter_tuning_eligible": False,
            "candidate_status_changed": False,
            "stage9b_started": False,
            "private_daily_chat_used": False,
            "responsibility": {
                "memory_truth": {
                    "core": "evidence admission, source presence, current-over-stale ordering, and blocking unsupported history claims",
                    "model": "natural relevant callback, uncertainty wording, and evidence-faithful paraphrase",
                },
                "urgent_safety": {
                    "core": "recognized imminent-hazard minimum action and unsafe-action suppression",
                    "model": "natural supportive wording and noncritical elaboration after the minimum action",
                },
                "system_confidentiality": {
                    "core": "deny direct or transformed extraction of hidden instruction material",
                    "model": "natural public-boundary explanation only",
                },
                "exact_structured_output": {
                    "core": "canonical serialization for explicitly recognized deterministic response contracts",
                    "model": "content generation where a contract is semantic, open-ended, or unsupported",
                },
                "privacy_tool_boundary": {
                    "core": "authorization, capability receipts, effect execution, and no-effect-without-evidence truth",
                    "model": "natural explanation and clarification within the authorized capability envelope",
                },
            },
            "arms": arms,
            "limitations": [
                "This reuses frozen generations; it is not a fresh model inference run.",
                "The deterministic replay uses the exact unseen case history/memory fields and the production delivery policy, while database retrieval and provider routing are covered separately by integration tests.",
                "Pattern recognition is deliberately high precision and does not prove exhaustive semantic hazard or entailment detection.",
                "Deterministic marker scores remain diagnostic and are not Product Owner blind style review.",
            ],
            "completed_at": datetime.now(UTC).isoformat(),
        },
    )


def verify_core_responsibility_audit() -> dict[str, Any]:
    report = read_hashed_json(REPORT_PATH)
    unseen_manifest, cases = load_and_verify_unseen()
    raw_report = read_hashed_json(RAW_OUTPUT_ROOT / "report.json")
    if (
        report.get("audit_id") != AUDIT_ID
        or report.get("case_count") != len(cases)
        or len(cases) != 80
        or report.get("raw_five_arm_report_hash") != raw_report["content_hash"]
        or report.get("unseen_manifest_hash") != unseen_manifest["content_hash"]
        or report.get("candidate_status_changed") is not False
        or report.get("no_model_generation_or_training") is not True
    ):
        raise ValueError("Core responsibility audit binding mismatch")
    if any(
        len(arm["raw_model"]["results"]) != 80
        or len(arm["full_havre_pipeline"]["results"]) != 80
        for arm in report.get("arms", ())
    ):
        raise ValueError("Core responsibility audit case membership mismatch")
    return report
