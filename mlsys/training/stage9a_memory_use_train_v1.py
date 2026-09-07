"""One-candidate v7 continuation for natural relevant-Memory use.

The frozen rejected v7 adapter is read as an immutable parent.  This module
creates a new local candidate and never edits the candidate registry, serving
binding, release state, or either parent artifact.
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from companion.hashing import content_hash
from evals.inference_runner import current_source_revision
from mlsys.training.stage9a_memory_use_dataset_v1 import (
    DATASET_ID,
    DATASET_ROOT,
    dataset_bundle_hash,
    load_and_verify_dataset,
    prompt_messages,
    write_source_artifacts,
)
from mlsys.training.stage9a_provenance import PROJECT_ROOT, STAGE9A_ROOT, load_model_manifest
from mlsys.training.stage9a_real import (
    FRAMEWORK_VERSION,
    MODEL_ROOT,
    RESOURCE_EVIDENCE_VERSION,
    RUNS_ROOT,
    TARGET_VRAM_MIB,
    TRAINING_ATTENTION_IMPLEMENTATION,
    ResourceMonitor,
    TokenDataset,
    _collate,
    _evaluate_loss_selective,
    _load_tokenizer,
    _resource_evidence_is_within_stage9a_limits,
    _restore_frozen_base_io_bf16,
    _selective_training_step,
    _supervised_suffix_spec,
    assert_training_preflight,
    read_hashed_json,
    resource_snapshot,
    sha256_file,
    write_hashed_json,
)
from mlsys.training.stage9a_real_v7 import verify_adapter as verify_v7_adapter


PARENT_V7_ADAPTER = (
    RUNS_ROOT / "formal-seed-9701-v7-capability-preserving-v1" / "adapter"
)
DIAGNOSTIC_REPORT_PATH = (
    PROJECT_ROOT
    / "evals"
    / "reports"
    / "relevant_memory_20260826"
    / "system-presentation-replay-v2.json"
)
RENDERED_ROOT = STAGE9A_ROOT / "datasets" / f"{DATASET_ID}-rendered-qwen3-v1"
TRAINING_PLAN_PATH = (
    STAGE9A_ROOT / "evidence" / "stage9a-natural-relevant-memory-use-v1-plan.json"
)
RUN_ID = "formal-memory-use-v1-seed-9801"
OUTPUT_ROOT = RUNS_ROOT / RUN_ID
CANDIDATE_ID = "havre-stage9a-memory-use-v1-seed-9801"
FORMAL_SEED = 9801
EPOCHS = 1
LEARNING_RATE = 5e-5
MAX_SECONDS = 60 * 60
EXPECTED_TRAINABLE_PARAMETERS = 10_911_744
TRAINING_IMPLEMENTATION_VERSION = "qwen3-v7-continuation-memory-use-nf4-qlora-v1"
LOSS_PATH_VERSION = "qwen3-supervised-suffix-selective-logits-v1"


def _render_row(tokenizer, item: dict[str, Any]) -> dict[str, Any]:
    prompt = prompt_messages(item)
    full = [*prompt, {"role": "assistant", "content": item["chosen"]}]
    prompt_ids = tokenizer.apply_chat_template(
        prompt,
        tokenize=True,
        add_generation_prompt=True,
        enable_thinking=False,
    )
    full_ids = tokenizer.apply_chat_template(
        full,
        tokenize=True,
        add_generation_prompt=False,
        enable_thinking=False,
    )
    if full_ids[: len(prompt_ids)] != prompt_ids:
        raise ValueError("memory-use prompt is not an exact prefix of its target")
    labels = [-100] * len(prompt_ids) + full_ids[len(prompt_ids) :]
    suffix = _supervised_suffix_spec(labels)
    row = {
        "example_id": item["example_id"],
        "source_content_hash": item["content_hash"],
        "scenario_id": item["scenario_id"],
        "variant": item["variant"],
        "pair_role": item["pair_role"],
        "input_ids": full_ids,
        "labels": labels,
        "prompt_token_count": len(prompt_ids),
        "assistant_token_count": suffix["supervised_token_count"],
        "total_token_count": len(full_ids),
        "rejected_count": len(item["rejected"]),
        "contains_user_data": False,
    }
    row["content_hash"] = content_hash(row)
    return row


def build_artifacts() -> dict[str, Any]:
    if DATASET_ROOT.exists() or RENDERED_ROOT.exists():
        raise FileExistsError("immutable memory-use dataset or rendered root already exists")
    parent = verify_v7_adapter(PARENT_V7_ADAPTER)
    source_manifest = write_source_artifacts()
    source = load_and_verify_dataset()
    tokenizer = _load_tokenizer()
    rendered = {
        split: [_render_row(tokenizer, item) for item in source[split]]
        for split in ("train", "validation")
    }
    RENDERED_ROOT.mkdir(parents=True)
    split_reports: dict[str, Any] = {}
    for split, rows in rendered.items():
        path = RENDERED_ROOT / f"{split}.jsonl"
        path.write_text(
            "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        lengths = sorted(row["total_token_count"] for row in rows)
        split_reports[split] = {
            "count": len(rows),
            "artifact_sha256": sha256_file(path),
            "minimum_total_tokens": min(lengths),
            "maximum_total_tokens": max(lengths),
            "minimum_supervised_tokens": min(row["assistant_token_count"] for row in rows),
            "maximum_supervised_tokens": max(row["assistant_token_count"] for row in rows),
            "paired_counterfactual_count": sum(row["pair_role"] == "paired_counterfactual" for row in rows),
            "casual_regression_count": sum(row["pair_role"] == "casual_regression" for row in rows),
            "contains_user_data_count": sum(row["contains_user_data"] for row in rows),
        }
    return write_hashed_json(RENDERED_ROOT / "manifest.json", {
        "schema_version": 1,
        "dataset_id": DATASET_ID,
        "dataset_bundle_hash": dataset_bundle_hash(source),
        "source_manifest_hash": source_manifest["content_hash"],
        "renderer_version": "qwen3-production-context-presentation-chosen-only-v1",
        "parent_candidate_id": parent["candidate_id"],
        "parent_adapter_manifest_hash": parent["content_hash"],
        "parent_lifecycle_status_unchanged": True,
        "base_repository": load_model_manifest()["repository"],
        "base_revision": load_model_manifest()["revision"],
        "chosen_targets_optimized": True,
        "rejected_targets_optimized": False,
        "contains_user_data": False,
        "privacy_class": "PUBLIC",
        "oa70_rendered": False,
        "daily_chats_rendered": False,
        "candidate_only": True,
        "promotion_authorized": False,
        "deployment_authorized": False,
        "split_reports": split_reports,
    })


def _read_rendered() -> dict[str, list[dict[str, Any]]]:
    source = load_and_verify_dataset()
    manifest = read_hashed_json(RENDERED_ROOT / "manifest.json")
    parent = verify_v7_adapter(PARENT_V7_ADAPTER)
    if (
        manifest.get("dataset_bundle_hash") != dataset_bundle_hash(source)
        or manifest.get("parent_adapter_manifest_hash") != parent["content_hash"]
        or manifest.get("contains_user_data") is not False
        or manifest.get("oa70_rendered") is not False
        or manifest.get("daily_chats_rendered") is not False
        or manifest.get("promotion_authorized") is not False
        or manifest.get("deployment_authorized") is not False
    ):
        raise ValueError("memory-use rendered manifest boundary mismatch")
    tokenizer = _load_tokenizer()
    verified: dict[str, list[dict[str, Any]]] = {}
    for split in ("train", "validation"):
        path = RENDERED_ROOT / f"{split}.jsonl"
        if sha256_file(path) != manifest["split_reports"][split]["artifact_sha256"]:
            raise ValueError(f"memory-use rendered {split} hash mismatch")
        expected = {item["example_id"]: _render_row(tokenizer, item) for item in source[split]}
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            claimed = row.pop("content_hash", None)
            if claimed is None or content_hash(row) != claimed:
                raise ValueError(f"memory-use rendered row hash mismatch: {row.get('example_id')}")
            row["content_hash"] = claimed
            if row != expected.get(row["example_id"]):
                raise ValueError(f"memory-use rendered row drift: {row['example_id']}")
            rows.append(row)
        if len(rows) != manifest["split_reports"][split]["count"]:
            raise ValueError(f"memory-use rendered {split} count mismatch")
        verified[split] = rows
    return verified


def close_training_plan() -> dict[str, Any]:
    if TRAINING_PLAN_PATH.exists():
        raise FileExistsError(f"immutable memory-use plan exists: {TRAINING_PLAN_PATH}")
    rows = _read_rendered()
    parent = verify_v7_adapter(PARENT_V7_ADAPTER)
    diagnostic = read_hashed_json(DIAGNOSTIC_REPORT_PATH)
    if (
        diagnostic.get("training_performed") is not False
        or diagnostic.get("contains_user_data") is not False
        or diagnostic.get("candidate_status_changed") is not False
    ):
        raise ValueError("diagnostic replay is outside the authorized decision boundary")
    plan = {
        "schema_version": 1,
        "plan_id": "stage9a-natural-relevant-memory-use-v1-plan",
        "status": "closed_before_unseen_evaluation_authorship",
        "decision": "one narrow continuation from immutable rejected v7",
        "decision_reason": (
            "production-aligned presentation improved v7 but left relevant and multi-memory "
            "semantic failures, isolating model-owned connection/selectivity as the remaining bottleneck"
        ),
        "diagnostic_report_hash": diagnostic["content_hash"],
        "dataset_bundle_hash": dataset_bundle_hash(),
        "rendered_manifest_hash": read_hashed_json(RENDERED_ROOT / "manifest.json")["content_hash"],
        "parent_candidate_id": parent["candidate_id"],
        "parent_adapter_manifest_hash": parent["content_hash"],
        "parent_adapter_sha256": parent["adapter_sha256"],
        "parent_v7_status_unchanged": True,
        "fresh_base": False,
        "warm_start_from_v7": True,
        "warm_start_from_9201": False,
        "formal_seed": FORMAL_SEED,
        "formal_run_id": RUN_ID,
        "epochs": EPOCHS,
        "optimizer_steps": len(rows["train"]) * EPOCHS,
        "optimizer": {"name": "torch.optim.AdamW", "learning_rate": LEARNING_RATE, "weight_decay": 0.0},
        "batch_size": 1,
        "gradient_accumulation": 1,
        "maximum_sequence_length": max(row["total_token_count"] for split in rows.values() for row in split),
        "quantization": "NF4_double_quant_compute_bfloat16",
        "lora_continuation": {"rank": 4, "alpha": 8, "dropout": 0.05, "target_modules": "all-linear"},
        "objective_scope": "natural_relevant_memory_use_only",
        "paired_counterfactual_training": True,
        "chosen_supervision": True,
        "rejected_preference_evidence_optimized": False,
        "casual_naturalness_regression_included": True,
        "safety_exact_output_confidentiality_objectives_included": False,
        "contains_user_data": False,
        "privacy_class": "PUBLIC",
        "daily_chats_included": False,
        "oa70_included": False,
        "second_candidate_policy": "none",
        "unseen_evaluation_authored_at_plan_close": False,
        "candidate_only": True,
        "registration_authorized": False,
        "promotion_authorized": False,
        "deployment_authorized": False,
        "stage9b_authorized": False,
        "source_snapshot": current_source_revision(PROJECT_ROOT),
        "closed_at": datetime.now(UTC).isoformat(),
    }
    return write_hashed_json(TRAINING_PLAN_PATH, plan)


def load_training_plan() -> dict[str, Any]:
    plan = read_hashed_json(TRAINING_PLAN_PATH)
    rows = _read_rendered()
    parent = verify_v7_adapter(PARENT_V7_ADAPTER)
    if (
        plan.get("status") != "closed_before_unseen_evaluation_authorship"
        or plan.get("dataset_bundle_hash") != dataset_bundle_hash()
        or plan.get("rendered_manifest_hash") != read_hashed_json(RENDERED_ROOT / "manifest.json")["content_hash"]
        or plan.get("parent_adapter_manifest_hash") != parent["content_hash"]
        or plan.get("parent_v7_status_unchanged") is not True
        or plan.get("warm_start_from_v7") is not True
        or plan.get("optimizer_steps") != len(rows["train"]) * EPOCHS
        or plan.get("optimizer", {}).get("learning_rate") != LEARNING_RATE
        or plan.get("contains_user_data") is not False
        or plan.get("daily_chats_included") is not False
        or plan.get("registration_authorized") is not False
        or plan.get("promotion_authorized") is not False
        or plan.get("deployment_authorized") is not False
    ):
        raise ValueError("memory-use closed training plan binding mismatch")
    return plan


def _loader(rows: list[dict[str, Any]], tokenizer, *, shuffle: bool):
    import torch
    from torch.utils.data import DataLoader

    generator = torch.Generator()
    generator.manual_seed(FORMAL_SEED)
    items = [{"input_ids": row["input_ids"], "labels": row["labels"]} for row in rows]
    return DataLoader(
        TokenDataset(items),
        batch_size=1,
        shuffle=shuffle,
        generator=generator,
        collate_fn=lambda batch: _collate(batch, tokenizer.pad_token_id),
    )


def _load_parent_continuation():
    import torch
    from peft import PeftModel, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, BitsAndBytesConfig

    quantization = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    base = AutoModelForCausalLM.from_pretrained(
        MODEL_ROOT,
        local_files_only=True,
        trust_remote_code=False,
        quantization_config=quantization,
        device_map={"": 0},
        torch_dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
        attn_implementation=TRAINING_ATTENTION_IMPLEMENTATION,
    )
    base.config.use_cache = False
    base = prepare_model_for_kbit_training(
        base,
        use_gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
    )
    model = PeftModel.from_pretrained(base, PARENT_V7_ADAPTER, is_trainable=True)
    model._havre_frozen_io_dtype_evidence = _restore_frozen_base_io_bf16(model)
    trainable = sum(parameter.numel() for parameter in model.parameters() if parameter.requires_grad)
    if trainable != EXPECTED_TRAINABLE_PARAMETERS:
        raise RuntimeError(f"continuation trainable parameter count drifted: {trainable}")
    return model, trainable, quantization.to_dict()


def train_candidate() -> dict[str, Any]:
    import torch

    if OUTPUT_ROOT.exists():
        raise FileExistsError(f"immutable memory-use run exists: {OUTPUT_ROOT}")
    # Capture the environment baseline before any tokenizer or rendered-data
    # verification allocations, matching the meaning of the Stage 9A preflight.
    before = resource_snapshot()
    assert_training_preflight(before)
    plan = load_training_plan()
    rows = _read_rendered()
    tokenizer = _load_tokenizer()
    torch.manual_seed(FORMAL_SEED)
    torch.cuda.manual_seed_all(FORMAL_SEED)
    OUTPUT_ROOT.mkdir(parents=True)
    adapter_dir = OUTPUT_ROOT / "adapter"
    monitor = ResourceMonitor(interval_seconds=1.0).start()
    started = time.perf_counter()
    model = optimizer = None
    history: list[dict[str, Any]] = []
    failure: Exception | None = None
    initial_validation_loss = final_validation_loss = None
    quantization = None
    trainable = None
    try:
        torch.cuda.reset_peak_memory_stats()
        model, trainable, quantization = _load_parent_continuation()
        optimizer = torch.optim.AdamW(
            [parameter for parameter in model.parameters() if parameter.requires_grad],
            lr=LEARNING_RATE,
            weight_decay=0.0,
        )
        train_loader = _loader(rows["train"], tokenizer, shuffle=True)
        validation_loader = _loader(rows["validation"], tokenizer, shuffle=False)
        initial_validation_loss = _evaluate_loss_selective(model, validation_loader)
        step = 0
        for epoch in range(EPOCHS):
            model.train()
            for batch in train_loader:
                if time.perf_counter() - started > MAX_SECONDS:
                    raise TimeoutError("memory-use continuation exceeded one-hour budget")
                monitor.check()
                evidence: dict[str, Any] = {}
                loss, gradient_norm, selection = _selective_training_step(
                    model,
                    batch,
                    optimizer,
                    step_evidence=evidence,
                    use_bf16_autocast=True,
                    release_cuda_cache_before_optimizer=True,
                )
                if not evidence.get("all_gradient_tensors_finite") or not evidence.get("optimizer_state_materialized"):
                    raise RuntimeError("memory-use optimizer evidence is incomplete")
                step += 1
                history.append({
                    "optimizer_step": step,
                    "epoch": epoch + 1,
                    "loss": loss,
                    "gradient_norm": gradient_norm,
                    "selected_logit_count": selection["selected_logit_count"],
                    "elapsed_seconds": time.perf_counter() - started,
                })
        final_validation_loss = _evaluate_loss_selective(model, validation_loader)
        losses = [row["loss"] for row in history]
        if len(losses) != plan["optimizer_steps"] or any(not math.isfinite(value) or value <= 0 for value in losses):
            raise RuntimeError("memory-use loss history is incomplete or non-finite")
        torch.cuda.synchronize()
        monitor.samples.append(resource_snapshot())
        monitor.check()
        model.save_pretrained(adapter_dir, safe_serialization=True)
        tokenizer.save_pretrained(adapter_dir / "tokenizer")
    except Exception as error:
        failure = error
    finally:
        resources = monitor.stop()
    observed_peak = max(
        resources["maximum"]["vram_used_mib"],
        torch.cuda.max_memory_allocated() / 1024**2,
        torch.cuda.max_memory_reserved() / 1024**2,
    )
    if failure is None and (
        observed_peak > TARGET_VRAM_MIB
        or not _resource_evidence_is_within_stage9a_limits(resources, peak_target_mib=TARGET_VRAM_MIB)
    ):
        failure = RuntimeError("memory-use resource evidence is incomplete or outside Stage 9A limits")
    if failure is not None:
        write_hashed_json(OUTPUT_ROOT / "failure.json", {
            "schema_version": 1,
            "run_id": RUN_ID,
            "status": "failed",
            "failure": {"type": type(failure).__name__, "message": str(failure)},
            "parent_v7_status_unchanged": True,
            "candidate_only": True,
            "promotion_authorized": False,
            "deployment_authorized": False,
            "resource_evidence": resources,
        })
        del model, optimizer
        gc.collect()
        torch.cuda.empty_cache()
        raise failure
    parent = verify_v7_adapter(PARENT_V7_ADAPTER)
    summary = {
        "status": "completed_candidate",
        "epochs": EPOCHS,
        "optimizer_steps": len(history),
        "initial_validation_loss": initial_validation_loss,
        "final_validation_loss": final_validation_loss,
        "wall_time_seconds": time.perf_counter() - started,
        "peak_vram_mib": observed_peak,
        "minimum_available_ram_gib": resources["minimum"]["ram_available_gib"],
        "maximum_swap_used_mib": resources["maximum"]["swap_used_mib"],
    }
    manifest = write_hashed_json(adapter_dir / "havre_adapter_manifest.json", {
        "schema_version": 1,
        "candidate_id": CANDIDATE_ID,
        "run_id": RUN_ID,
        "seed": FORMAL_SEED,
        "formal": True,
        "candidate_only": True,
        "registered": False,
        "served": False,
        "promoted": False,
        "deployed": False,
        "promotion_authorized": False,
        "deployment_authorized": False,
        "contains_user_data": False,
        "privacy_class": "PUBLIC",
        "parent_candidate_id": parent["candidate_id"],
        "parent_adapter_manifest_hash": parent["content_hash"],
        "parent_adapter_sha256": parent["adapter_sha256"],
        "parent_v7_status_unchanged": True,
        "base_repository": load_model_manifest()["repository"],
        "base_revision": load_model_manifest()["revision"],
        "dataset_id": DATASET_ID,
        "dataset_bundle_hash": dataset_bundle_hash(),
        "rendered_manifest_hash": read_hashed_json(RENDERED_ROOT / "manifest.json")["content_hash"],
        "training_plan_hash": plan["content_hash"],
        "training_implementation": TRAINING_IMPLEMENTATION_VERSION,
        "framework": FRAMEWORK_VERSION,
        "adapter_file": "adapter_model.safetensors",
        "adapter_sha256": sha256_file(adapter_dir / "adapter_model.safetensors"),
        "adapter_config_sha256": sha256_file(adapter_dir / "adapter_config.json"),
        "training_summary": summary,
    })
    report = write_hashed_json(OUTPUT_ROOT / "training-report.json", {
        "schema_version": 1,
        "candidate_id": CANDIDATE_ID,
        "run_id": RUN_ID,
        "status": "completed_candidate",
        "candidate_only": True,
        "registered": False,
        "served": False,
        "promoted": False,
        "deployed": False,
        "promotion_authorized": False,
        "deployment_authorized": False,
        "parent_v7_status_unchanged": True,
        "contains_user_data": False,
        "dataset_bundle_hash": dataset_bundle_hash(),
        "rendered_manifest_hash": read_hashed_json(RENDERED_ROOT / "manifest.json")["content_hash"],
        "training_plan_hash": plan["content_hash"],
        "adapter_manifest_hash": manifest["content_hash"],
        "training_implementation": TRAINING_IMPLEMENTATION_VERSION,
        "loss_path_version": LOSS_PATH_VERSION,
        "framework": FRAMEWORK_VERSION,
        "quantization": quantization,
        "attention_implementation": TRAINING_ATTENTION_IMPLEMENTATION,
        "optimizer": "torch.optim.AdamW_no_paging",
        "learning_rate": LEARNING_RATE,
        "bf16_autocast": True,
        "trainable_parameters": trainable,
        "history": history,
        "training_summary": summary,
        "resource_evidence": resources,
        "completed_at": datetime.now(UTC).isoformat(),
    })
    del model, optimizer
    gc.collect()
    torch.cuda.empty_cache()
    return report


def verify_candidate() -> dict[str, Any]:
    manifest = read_hashed_json(OUTPUT_ROOT / "adapter" / "havre_adapter_manifest.json")
    plan = load_training_plan()
    parent = verify_v7_adapter(PARENT_V7_ADAPTER)
    if (
        manifest.get("candidate_id") != CANDIDATE_ID
        or manifest.get("parent_adapter_manifest_hash") != parent["content_hash"]
        or manifest.get("training_plan_hash") != plan["content_hash"]
        or manifest.get("dataset_bundle_hash") != dataset_bundle_hash()
        or manifest.get("registered") is not False
        or manifest.get("served") is not False
        or manifest.get("promoted") is not False
        or manifest.get("deployed") is not False
        or manifest.get("parent_v7_status_unchanged") is not True
        or manifest.get("adapter_sha256") != sha256_file(OUTPUT_ROOT / "adapter" / "adapter_model.safetensors")
        or manifest.get("adapter_config_sha256") != sha256_file(OUTPUT_ROOT / "adapter" / "adapter_config.json")
    ):
        raise ValueError("memory-use candidate binding mismatch")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(prog="stage9a-memory-use-v1")
    parser.add_argument("action", choices=("build", "close-plan", "train", "verify"))
    action = parser.parse_args().action
    result = {
        "build": build_artifacts,
        "close-plan": close_training_plan,
        "train": train_candidate,
        "verify": verify_candidate,
    }[action]()
    print(result["content_hash"])


if __name__ == "__main__":
    main()
