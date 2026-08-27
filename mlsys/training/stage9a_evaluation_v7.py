"""Four-arm post-plan unseen evaluation for the Stage 9A v7 lineage."""

from __future__ import annotations

import gc
import json
import random
import statistics
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from companion.hashing import content_hash
from evals.inference_runner import current_source_revision
from mlsys.training.stage9a_dataset_v7 import DATASET_ROOT, MEMORY_BLOCK_HEADER, load_and_verify_dataset
from mlsys.training.stage9a_provenance import PROJECT_ROOT, STAGE9A_ROOT, load_model_manifest, verify_model_artifact
from mlsys.training.stage9a_real import (
    MODEL_ROOT,
    RESOURCE_EVIDENCE_VERSION,
    RUNS_ROOT,
    TARGET_VRAM_MIB,
    ResourceMonitor,
    _load_tokenizer,
    _resource_evidence_is_within_stage9a_limits,
    assert_training_preflight,
    read_hashed_json,
    resource_snapshot,
    write_hashed_json,
)
from mlsys.training.stage9a_real_v6 import FORMAL_RUN_ID as V6_FORMAL_RUN_ID, verify_adapter as verify_v6_adapter
from mlsys.training.stage9a_real_v7 import FORMAL_RUN_ID, TRAINING_PLAN_PATH, verify_adapter
from mlsys.training.stage9a_unseen_v7 import EVALUATION_SET_ID, SCORER_VERSION, load_and_verify_unseen, score_output
from mlsys.training.stage9a_v7_readiness import FORMAL_RELOAD_REPORT_PATH


EVALUATION_ID = "stage9a-v7-post-plan-five-arm-v1"
OUTPUT_ROOT = STAGE9A_ROOT / "evaluation" / EVALUATION_ID
HISTORICAL_ADAPTERS = {
    "candidate_9201": RUNS_ROOT / "formal-seed-9201-v4-resource-correction1" / "adapter",
    "candidate_9202": RUNS_ROOT / "formal-seed-9202-v4-resource-correction1" / "adapter",
}
REJECTED_V6_ADAPTER = RUNS_ROOT / V6_FORMAL_RUN_ID / "adapter"
V7_ADAPTER = RUNS_ROOT / FORMAL_RUN_ID / "adapter"


def _prompt_messages(case: dict[str, Any], system_text: str) -> list[dict[str, str]]:
    memory = case["memory_context"]
    if memory:
        system_text = f"{system_text}\n\n{MEMORY_BLOCK_HEADER}\n" + "\n".join(
            f"- {value.strip()}" for value in memory
        )
    return [{"role": "system", "content": system_text}, *[dict(value) for value in case["messages"]]]


def _greedy_generate(model, tokenizer, input_ids, *, max_new_tokens: int = 192) -> dict[str, Any]:
    import torch

    input_ids = input_ids.to("cuda:0")
    attention = torch.ones_like(input_ids)
    started = time.perf_counter()
    with torch.inference_mode():
        output = model(input_ids=input_ids, attention_mask=attention, use_cache=True)
        token = output.logits[:, -1, :].argmax(dim=-1, keepdim=True)
        torch.cuda.synchronize()
        ttft = time.perf_counter() - started
        generated = [int(token.item())]
        cache = output.past_key_values
        for _ in range(max_new_tokens - 1):
            if generated[-1] == tokenizer.eos_token_id:
                break
            attention = torch.cat(
                [attention, torch.ones((1, 1), device=attention.device, dtype=attention.dtype)],
                dim=1,
            )
            output = model(
                input_ids=token,
                attention_mask=attention,
                past_key_values=cache,
                use_cache=True,
            )
            cache = output.past_key_values
            token = output.logits[:, -1, :].argmax(dim=-1, keepdim=True)
            generated.append(int(token.item()))
        torch.cuda.synchronize()
    elapsed = time.perf_counter() - started
    if generated and generated[-1] == tokenizer.eos_token_id:
        generated.pop()
    return {
        "text": tokenizer.decode(generated, skip_special_tokens=True).strip(),
        "input_tokens": int(input_ids.shape[1]),
        "output_tokens": len(generated),
        "ttft_seconds": ttft,
        "latency_seconds": elapsed,
    }


def _rate(values: list[bool]) -> dict[str, Any]:
    return {
        "applicable_count": len(values),
        "pass_count": sum(values),
        "pass_rate": sum(values) / len(values) if values else None,
    }


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    def summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
        chars = [item["scores"]["output_chars"] for item in items]
        fields = (
            "within_max_chars",
            "unsupported_history_check",
            "exact_checker",
            "deterministic_pass",
            "critical_hard_capability_pass",
        )
        checks = {
            field: _rate([
                bool(item["scores"][field])
                for item in items
                if item["scores"][field] is not None
            ])
            for field in fields
        }
        required_group_values = [
            all(group["passed"] for group in item["scores"]["required_groups"])
            for item in items
            if item["scores"]["required_groups"]
        ]
        checks["required_groups"] = _rate(required_group_values)
        return {
            "case_count": len(items),
            "mean_output_chars": statistics.fmean(chars),
            "median_output_chars": statistics.median(chars),
            "ai_phrase_case_count": sum(bool(item["scores"]["ai_phrase_hits"]) for item in items),
            "ai_phrase_hit_count": sum(len(item["scores"]["ai_phrase_hits"]) for item in items),
            "forbidden_phrase_case_count": sum(bool(item["scores"]["forbidden_phrase_hits"]) for item in items),
            "checks": checks,
        }

    by_axis: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_dimension: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        by_axis[result["axis"]].append(result)
        by_dimension[result["dimension"]].append(result)
    return {
        "overall_diagnostic_only": summarize(results),
        "by_axis": {name: summarize(by_axis[name]) for name in sorted(by_axis)},
        "by_dimension": {name: summarize(by_dimension[name]) for name in sorted(by_dimension)},
        "no_cross_axis_composite": True,
    }

def _evaluate_arm(model, tokenizer, cases: list[dict[str, Any]], *, arm_name: str, system_text: str) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for case in cases:
        input_ids = tokenizer.apply_chat_template(
            _prompt_messages(case, system_text),
            tokenize=True,
            add_generation_prompt=True,
            enable_thinking=False,
            return_tensors="pt",
        )
        generated = _greedy_generate(model, tokenizer, input_ids)
        results.append({
            "case_id": case["case_id"],
            "case_hash": case["content_hash"],
            "axis": case["axis"],
            "dimension": case["dimension"],
            "subcategory": case["subcategory"],
            "expected_mode": case["expected_mode"],
            "critical_hard_capability": case["critical_hard_capability"],
            "output": generated["text"],
            "generation": {key: value for key, value in generated.items() if key != "text"},
            "scores": score_output(case, generated["text"]),
        })
    return {"arm_name": arm_name, "results": results, "summary": summarize_results(results)}

def build_blind_packet(arms: list[dict[str, Any]], cases: list[dict[str, Any]]) -> dict[str, Any]:
    arm_names = [arm["arm_name"] for arm in arms]
    aliases = ["A", "B", "C", "D", "E"]
    random.Random(970180).shuffle(aliases)
    mapping = dict(zip(aliases, arm_names))
    by_arm = {arm["arm_name"]: {row["case_id"]: row for row in arm["results"]} for arm in arms}
    items = []
    for case in cases:
        options = [
            {"alias": alias, "output": by_arm[arm_name][case["case_id"]]["output"]}
            for alias, arm_name in mapping.items()
        ]
        random.Random(int(case["case_id"].rsplit("-", 1)[1]) + 9701).shuffle(options)
        items.append({
            "case_id": case["case_id"],
            "axis": case["axis"],
            "dimension": case["dimension"],
            "subcategory": case["subcategory"],
            "messages": case["messages"],
            "memory_context": case["memory_context"],
            "options": options,
            "review_judgment": None,
            "review_notes": None,
        })
    public = {
        "schema_version": 1,
        "evaluation_id": EVALUATION_ID,
        "status": "awaiting_independent_and_product_owner_blinded_review",
        "case_count": len(items),
        "arm_aliases": aliases,
        "items": items,
        "training_eligible": False,
        "validation_for_training": False,
        "privacy_class": "PRIVATE",
        "contains_user_data": True,
        "reason_private": "includes outputs from immutable rejected v6 adapter trained with Owner anchors",
        "local_only": True,
    }
    key = {
        "schema_version": 1,
        "evaluation_id": EVALUATION_ID,
        "alias_to_arm": mapping,
        "packet_hash": content_hash(public),
        "local_only": True,
    }
    return {"packet": public, "key": key}


def build_preliminary_hard_gate(arms: list[dict[str, Any]]) -> dict[str, Any]:
    by_name = {arm["arm_name"]: arm for arm in arms}
    reference = by_name["candidate_9201"]
    candidate = by_name["candidate_v7_9701"]

    def dimension_counts(arm: dict[str, Any]) -> dict[str, dict[str, int]]:
        grouped: dict[str, list[bool]] = defaultdict(list)
        for row in arm["results"]:
            if row["axis"] == "hard_capability":
                grouped[row["dimension"]].append(bool(row["scores"]["critical_hard_capability_pass"]))
        return {
            name: {"pass": sum(values), "total": len(values)}
            for name, values in sorted(grouped.items())
        }

    reference_counts = dimension_counts(reference)
    candidate_counts = dimension_counts(candidate)
    regressions = [
        {
            "dimension": name,
            "reference_pass": reference_counts[name]["pass"],
            "candidate_pass": candidate_counts[name]["pass"],
        }
        for name in sorted(reference_counts)
        if candidate_counts[name]["pass"] < reference_counts[name]["pass"]
    ]
    return {
        "status": "preliminary_pass" if not regressions else "blocked_by_deterministic_regression",
        "reference_arm": "candidate_9201",
        "candidate_arm": "candidate_v7_9701",
        "reference_by_dimension": reference_counts,
        "candidate_by_dimension": candidate_counts,
        "dimension_regressions": regressions,
        "critical_policy": "no hard dimension may score below 9201; semantic independent review can only add blockers, not average them away",
        "not_a_companion_quality_decision": True,
    }

def run_evaluation() -> dict[str, Any]:
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, BitsAndBytesConfig

    if OUTPUT_ROOT.exists():
        raise FileExistsError(f"immutable v7 evaluation root already exists: {OUTPUT_ROOT}")
    plan = read_hashed_json(TRAINING_PLAN_PATH)
    reload = read_hashed_json(FORMAL_RELOAD_REPORT_PATH)
    v7 = verify_adapter(V7_ADAPTER)
    rejected_v6 = verify_v6_adapter(REJECTED_V6_ADAPTER)
    unseen_manifest, cases = load_and_verify_unseen()
    if (
        reload.get("status") != "completed_candidate_reload"
        or reload.get("formal") is not True
        or reload.get("adapter_manifest_hash") != v7["content_hash"]
        or reload.get("training_plan_hash") != plan["content_hash"]
        or unseen_manifest.get("used_for_training_or_hyperparameter_selection") is not False
    ):
        raise ValueError("v7 formal reload/unseen evaluation boundary mismatch")
    before = resource_snapshot()
    assert_training_preflight(before)
    verify_model_artifact(MODEL_ROOT)
    dataset = load_and_verify_dataset(DATASET_ROOT)
    system_values = {row["system_text"] for rows in dataset.values() for row in rows}
    if len(system_values) != 1:
        raise ValueError("v7 evaluation system text is not canonical")
    system_text = system_values.pop()
    tokenizer = _load_tokenizer()
    quantization = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    historical = {
        name: read_hashed_json(path / "havre_adapter_manifest.json")
        for name, path in HISTORICAL_ADAPTERS.items()
    }
    arms_spec = [
        ("exact_base", None, None),
        *[(name, HISTORICAL_ADAPTERS[name], historical[name]) for name in sorted(HISTORICAL_ADAPTERS)],
        ("rejected_v6_9601", REJECTED_V6_ADAPTER, rejected_v6),
        ("candidate_v7_9701", V7_ADAPTER, v7),
    ]
    monitor = ResourceMonitor(interval_seconds=1.0).start()
    started = time.perf_counter()
    arms: list[dict[str, Any]] = []
    failure: Exception | None = None

    def load_base():
        return AutoModelForCausalLM.from_pretrained(
            MODEL_ROOT,
            local_files_only=True,
            trust_remote_code=False,
            quantization_config=quantization,
            device_map={"": 0},
            torch_dtype=torch.bfloat16,
            low_cpu_mem_usage=True,
            attn_implementation="sdpa",
        )

    try:
        for arm_name, adapter_dir, manifest in arms_spec:
            base = load_base()
            model = base if adapter_dir is None else PeftModel.from_pretrained(base, adapter_dir, is_trainable=False)
            model.eval()
            arm = _evaluate_arm(model, tokenizer, cases, arm_name=arm_name, system_text=system_text)
            arm["adapter_manifest_hash"] = None if manifest is None else manifest["content_hash"]
            arms.append(arm)
            del model, base
            gc.collect()
            torch.cuda.empty_cache()
            monitor.check()
    except Exception as error:
        failure = error
    finally:
        resources = monitor.stop()
    if failure is None and not _resource_evidence_is_within_stage9a_limits(resources, peak_target_mib=TARGET_VRAM_MIB):
        failure = RuntimeError("v7 unseen evaluation resource evidence is outside limits")
    if failure is not None:
        raise failure
    hard_gate = build_preliminary_hard_gate(arms)
    OUTPUT_ROOT.mkdir(parents=True)
    blind = build_blind_packet(arms, cases)
    packet = write_hashed_json(OUTPUT_ROOT / "owner-blind-packet.json", blind["packet"])
    key = dict(blind["key"])
    key["packet_hash"] = packet["content_hash"]
    key = write_hashed_json(OUTPUT_ROOT / "owner-blind-key.json", key)
    model_manifest = load_model_manifest()
    report = {
        "schema_version": 1,
        "evaluation_id": EVALUATION_ID,
        "evaluation_set_id": EVALUATION_SET_ID,
        "status": "completed_candidate_evaluation_independent_and_owner_review_pending",
        "candidate_only": True,
        "promotion_authorized": False,
        "deployment_authorized": False,
        "local_only": True,
        "contains_user_data": True,
        "training_eligible": False,
        "validation_for_training": False,
        "hyperparameter_tuning_eligible": False,
        "used_for_training_or_hyperparameter_selection": False,
        "subjective_voice_requires_owner_review": True,
        "companion_and_hard_axes_reported_separately": True,
        "no_cross_axis_composite_score": True,
        "critical_hard_gate": hard_gate,
        "base_repository": model_manifest["repository"],
        "base_revision": model_manifest["revision"],
        "training_plan_hash": plan["content_hash"],
        "formal_reload_report_hash": reload["content_hash"],
        "unseen_manifest_hash": unseen_manifest["content_hash"],
        "generation": {"decoding": "greedy", "thinking": False, "max_new_tokens": 192},
        "arm_count": len(arms),
        "arms": arms,
        "owner_blind_packet_hash": packet["content_hash"],
        "owner_blind_key_hash": key["content_hash"],
        "resource_monitor_version": RESOURCE_EVIDENCE_VERSION,
        "resources": resources,
        "elapsed_seconds": time.perf_counter() - started,
        "execution_source_snapshot": current_source_revision(PROJECT_ROOT),
        "completed_at": datetime.now(UTC).isoformat(),
    }
    return write_hashed_json(OUTPUT_ROOT / "report.json", report)
