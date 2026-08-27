"""Exact-base Qwen3-8B rendering and bounded QLoRA training for v6.

This is a new candidate lineage.  It reuses the already-proven low-level v4
QLoRA mechanics while keeping v4 run IDs, artifacts, and registry immutable.
"""

from __future__ import annotations

import gc
import json
import math
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from companion.hashing import content_hash
from evals.inference_runner import current_source_revision
from mlsys.training.stage9a_dataset_v6 import (
    AUTHORIZATION_PATH,
    DATASET_ID,
    DATASET_ROOT,
    FROZEN_COUNTS,
    MEMORY_BLOCK_HEADER,
    TRAINING_SPLITS,
    assert_local_only_path,
    dataset_bundle_hash,
    load_and_verify_dataset,
    load_authorization,
)
from mlsys.training.stage9a_provenance import (
    PROJECT_ROOT,
    STAGE9A_ROOT,
    load_model_manifest,
    verify_model_artifact,
)
from mlsys.training.stage9a_real import (
    FRAMEWORK_VERSION,
    LORA_ALPHA,
    LORA_RANK,
    MODEL_ROOT,
    RESOURCE_EVIDENCE_VERSION,
    RUNS_ROOT,
    TARGET_VRAM_MIB,
    TRAINING_ATTENTION_IMPLEMENTATION,
    ResourceMonitor,
    TokenDataset,
    _collate,
    _evaluate_loss_selective,
    _load_qlora_model,
    _load_tokenizer,
    _render_example,
    _resource_evidence_is_within_stage9a_limits,
    _selective_training_step,
    _supervised_suffix_spec,
    assert_training_preflight,
    read_hashed_json,
    resource_snapshot,
    sha256_file,
    write_hashed_json,
)


RENDERED_ROOT = STAGE9A_ROOT / "datasets" / "stage9a-rendered-qwen3-b968826d-v6-style-first-v1"
TRAINING_PLAN_PATH = STAGE9A_ROOT / "evidence" / "stage9a-v6-style-first-training-plan.json"
RENDERER_VERSION = "qwen3-v6-style-first-multiturn-final-target-no-thinking-v1"
TRAINING_IMPLEMENTATION_VERSION = "qwen3-v6-nf4-qlora-selective-bf16-cache-trim-v1"
LOSS_PATH_VERSION = "qwen3-v6-supervised-suffix-selective-logits-v1"
SMOKE_SEED = 9600
FORMAL_SEED = 9601
SMOKE_RUN_ID = "gate-d-smoke-v6-style-first-v1"
FORMAL_RUN_ID = "formal-seed-9601-v6-style-first-v1"
EPOCHS = 2
SMOKE_STEPS = 8
MAX_SEED_SECONDS = 2 * 60 * 60
EXPECTED_TRAINABLE_PARAMETERS = 10_911_744


def _render_input(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "example_id": item["example_id"],
        "content_hash": item["content_hash"],
        "category": item["family"],
        "context_kind": "conversation",
        "messages": item["messages"],
        "input_text": item["input_text"],
        "expected_text": item["expected_text"],
        "system_text": item["system_text"],
        "inject_memory_context": item["inject_memory_context"],
        "memory_context": item["memory_context"],
        "use_memory_in_training": item["use_memory_in_training"],
    }


def _render_row(tokenizer, item: dict[str, Any]) -> dict[str, Any]:
    row = _render_example(tokenizer, _render_input(item))
    row.update({
        "canonical_content_hash": item["content_hash"],
        "source_kind": item["source_kind"],
        "privacy_class": item["privacy_class"],
        "contains_user_data": item["contains_user_data"],
    })
    row["content_hash"] = content_hash(row)
    return row


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def build_rendered_artifacts() -> dict[str, Any]:
    load_authorization(AUTHORIZATION_PATH)
    verify_model_artifact(MODEL_ROOT)
    assert_local_only_path(RENDERED_ROOT)
    if RENDERED_ROOT.exists():
        raise FileExistsError(f"immutable v6 rendered root already exists: {RENDERED_ROOT}")
    source = load_and_verify_dataset(DATASET_ROOT)
    tokenizer = _load_tokenizer()
    rendered: dict[str, list[dict[str, Any]]] = {}
    for split in ("train", "validation"):
        rendered[split] = [_render_row(tokenizer, item) for item in source[split]]
    maximum = max(row["total_token_count"] for rows in rendered.values() for row in rows)
    if maximum != 340:
        raise ValueError(f"v6 exact maximum token length drifted: {maximum}")
    RENDERED_ROOT.mkdir(parents=True)
    split_reports: dict[str, Any] = {}
    for split, rows in rendered.items():
        path = RENDERED_ROOT / f"{split}.jsonl"
        _write_jsonl(path, rows)
        lengths = sorted(row["total_token_count"] for row in rows)
        split_reports[split] = {
            "count": len(rows),
            "artifact_sha256": sha256_file(path),
            "maximum_total_tokens": max(lengths),
            "p95_total_tokens": lengths[int(0.95 * (len(lengths) - 1))],
            "minimum_supervised_tokens": min(row["assistant_token_count"] for row in rows),
            "maximum_supervised_tokens": max(row["assistant_token_count"] for row in rows),
            "memory_injected_count": sum(row["memory_injected"] for row in rows),
            "contains_user_data_count": sum(row["contains_user_data"] for row in rows),
        }
    model = load_model_manifest()
    manifest = {
        "schema_version": 1,
        "dataset_id": DATASET_ID,
        "dataset_bundle_hash": dataset_bundle_hash(DATASET_ROOT),
        "renderer_version": RENDERER_VERSION,
        "base_repository": model["repository"],
        "base_revision": model["revision"],
        "chosen_max_seq_length": maximum,
        "training_batch_size": 1,
        "rendered_splits": ["train", "validation"],
        "external_style_regression_rendered": False,
        "oa70_rendered": False,
        "memory_block_header": MEMORY_BLOCK_HEADER,
        "prompt_label_policy": "mask_complete_prompt_supervise_final_havre_suffix_only",
        "contains_user_data": True,
        "local_only": True,
        "candidate_only": True,
        "promotion_authorized": False,
        "deployment_authorized": False,
        "split_reports": split_reports,
        "execution_source_snapshot": current_source_revision(PROJECT_ROOT),
        "rendered_at": datetime.now(UTC).isoformat(),
    }
    return write_hashed_json(RENDERED_ROOT / "manifest.json", manifest)


def _verified_rendered(tokenizer=None) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    tokenizer = tokenizer or _load_tokenizer()
    source = load_and_verify_dataset(DATASET_ROOT)
    manifest = read_hashed_json(RENDERED_ROOT / "manifest.json")
    model = load_model_manifest()
    if (
        manifest.get("dataset_bundle_hash") != dataset_bundle_hash(DATASET_ROOT)
        or manifest.get("renderer_version") != RENDERER_VERSION
        or manifest.get("base_repository") != model["repository"]
        or manifest.get("base_revision") != model["revision"]
        or manifest.get("chosen_max_seq_length") != 340
        or manifest.get("rendered_splits") != ["train", "validation"]
        or manifest.get("external_style_regression_rendered") is not False
        or manifest.get("oa70_rendered") is not False
        or manifest.get("contains_user_data") is not True
        or manifest.get("local_only") is not True
    ):
        raise ValueError("v6 rendered manifest binding mismatch")
    verified: dict[str, list[dict[str, Any]]] = {}
    for split in ("train", "validation"):
        path = RENDERED_ROOT / f"{split}.jsonl"
        if sha256_file(path) != manifest["split_reports"][split]["artifact_sha256"]:
            raise ValueError(f"v6 rendered file hash mismatch: {split}")
        by_id = {item["example_id"]: item for item in source[split]}
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            claimed = row.pop("content_hash", None)
            if not isinstance(claimed, str) or content_hash(row) != claimed:
                raise ValueError(f"v6 rendered row hash mismatch: {row.get('example_id')}")
            example_id = row.get("example_id")
            if example_id in seen or example_id not in by_id:
                raise ValueError(f"v6 rendered membership mismatch: {example_id}")
            expected = _render_row(tokenizer, by_id[example_id])
            expected.pop("content_hash")
            if row != expected:
                raise ValueError(f"v6 rendered projection mismatch: {example_id}")
            _supervised_suffix_spec(row["labels"])
            seen.add(example_id)
            rows.append(row)
        if seen != set(by_id) or len(rows) != FROZEN_COUNTS[split]:
            raise ValueError(f"v6 rendered split is not an exact bijection: {split}")
        verified[split] = rows
    return manifest, verified


def verify_training_input_boundary(tokenizer=None) -> dict[str, Any]:
    manifest, rows = _verified_rendered(tokenizer)
    boundary = {
        "schema_version": 1,
        "dataset_bundle_hash": dataset_bundle_hash(DATASET_ROOT),
        "rendered_manifest_hash": manifest["content_hash"],
        "splits": {name: len(values) for name, values in rows.items()},
        "all_prompt_tokens_masked": all(
            all(value == -100 for value in row["labels"][: row["prompt_token_count"]])
            for values in rows.values() for row in values
        ),
        "all_supervised_labels_are_one_final_suffix": all(
            _supervised_suffix_spec(row["labels"])["supervised_label_start"] == row["prompt_token_count"]
            for values in rows.values() for row in values
        ),
        "contains_user_data": any(
            row["contains_user_data"] for values in rows.values() for row in values
        ),
        "normal_owner_anchor_count": sum(
            row["privacy_class"] == "NORMAL" for values in rows.values() for row in values
        ),
        "source_kinds": sorted({row["source_kind"] for values in rows.values() for row in values}),
        "local_only": True,
        "max_seq_length": manifest["chosen_max_seq_length"],
    }
    if (
        not boundary["all_prompt_tokens_masked"]
        or not boundary["all_supervised_labels_are_one_final_suffix"]
        or not boundary["contains_user_data"]
        or boundary["normal_owner_anchor_count"] != 69
        or boundary["source_kinds"] != ["owner_authored_anchor", "synthetic_external_candidate"]
    ):
        raise ValueError("v6 training input boundary violates the approved mixed-data scope")
    boundary["content_hash"] = content_hash(boundary)
    return boundary


def close_training_plan() -> dict[str, Any]:
    if TRAINING_PLAN_PATH.exists():
        raise FileExistsError(f"immutable v6 training plan already exists: {TRAINING_PLAN_PATH}")
    authorization = load_authorization()
    rendered = read_hashed_json(RENDERED_ROOT / "manifest.json")
    boundary = verify_training_input_boundary()
    plan = {
        "schema_version": 1,
        "plan_id": "stage9a-v6-style-first-fresh-base-plan-v1",
        "status": "closed_before_unseen_evaluation_authorship",
        "authorization_hash": authorization["content_hash"],
        "dataset_bundle_hash": dataset_bundle_hash(DATASET_ROOT),
        "rendered_manifest_hash": rendered["content_hash"],
        "training_input_boundary_hash": boundary["content_hash"],
        "base_repository": load_model_manifest()["repository"],
        "base_revision": load_model_manifest()["revision"],
        "fresh_base": True,
        "warm_start_9201": False,
        "warm_start_decision": "skip_old_style_confound_and_unnecessary_compute",
        "formal_seed": FORMAL_SEED,
        "formal_run_id": FORMAL_RUN_ID,
        "smoke_seed": SMOKE_SEED,
        "smoke_run_id": SMOKE_RUN_ID,
        "epochs": EPOCHS,
        "optimizer_steps": FROZEN_COUNTS["train"] * EPOCHS,
        "optimizer": {"name": "torch.optim.AdamW", "learning_rate": 2e-4, "weight_decay": 0.0},
        "batch_size": 1,
        "gradient_accumulation": 1,
        "max_seq_length": rendered["chosen_max_seq_length"],
        "quantization": "NF4_double_quant_compute_bfloat16",
        "lora": {"rank": LORA_RANK, "alpha": LORA_ALPHA, "dropout": 0.05, "target_modules": "all-linear"},
        "validation_role": "loss_stability_only_not_behavioral_selection",
        "candidate_only": True,
        "local_only": True,
        "promotion_authorized": False,
        "deployment_authorized": False,
        "stage9b_authorized": False,
        "unseen_evaluation_authored_at_plan_close": False,
        "closed_at": datetime.now(UTC).isoformat(),
    }
    return write_hashed_json(TRAINING_PLAN_PATH, plan)


def load_training_plan() -> dict[str, Any]:
    plan = read_hashed_json(TRAINING_PLAN_PATH)
    boundary = verify_training_input_boundary()
    if (
        plan.get("status") != "closed_before_unseen_evaluation_authorship"
        or plan.get("dataset_bundle_hash") != dataset_bundle_hash(DATASET_ROOT)
        or plan.get("rendered_manifest_hash") != read_hashed_json(RENDERED_ROOT / "manifest.json")["content_hash"]
        or plan.get("training_input_boundary_hash") != boundary["content_hash"]
        or plan.get("fresh_base") is not True
        or plan.get("warm_start_9201") is not False
        or plan.get("formal_seed") != FORMAL_SEED
        or plan.get("formal_run_id") != FORMAL_RUN_ID
        or plan.get("optimizer_steps") != FROZEN_COUNTS["train"] * EPOCHS
        or plan.get("promotion_authorized") is not False
        or plan.get("deployment_authorized") is not False
    ):
        raise ValueError("v6 closed training plan binding mismatch")
    return plan


@dataclass
class _LoadedRows:
    train: list[dict[str, Any]]
    validation: list[dict[str, Any]]


def _load_rows(tokenizer) -> _LoadedRows:
    _, rows = _verified_rendered(tokenizer)
    return _LoadedRows(
        train=[{"input_ids": row["input_ids"], "labels": row["labels"]} for row in rows["train"]],
        validation=[{"input_ids": row["input_ids"], "labels": row["labels"]} for row in rows["validation"]],
    )


def _loader(items: list[dict[str, Any]], tokenizer, *, seed: int, shuffle: bool):
    import torch
    from torch.utils.data import DataLoader

    generator = torch.Generator()
    generator.manual_seed(seed)
    return DataLoader(
        TokenDataset(items),
        batch_size=1,
        shuffle=shuffle,
        generator=generator,
        collate_fn=lambda batch: _collate(batch, tokenizer.pad_token_id),
    )


def _adapter_binding(
    *,
    adapter_dir: Path,
    run_id: str,
    seed: int,
    formal: bool,
    boundary: dict[str, Any],
    training_summary: dict[str, Any],
    execution_source_snapshot: str,
) -> dict[str, Any]:
    provenance = read_hashed_json(STAGE9A_ROOT / "evidence" / "qwen3-8b-provenance.json")
    model = load_model_manifest()
    return {
        "schema_version": 1,
        "candidate_id": "havre-stage9a-v6-style-first-seed-9601" if formal else "havre-stage9a-v6-style-first-smoke",
        "run_id": run_id,
        "seed": seed,
        "formal": formal,
        "candidate_only": True,
        "local_only": True,
        "promotion_authorized": False,
        "deployment_authorized": False,
        "contains_user_data": True,
        "privacy_class": "NORMAL",
        "base_repository": model["repository"],
        "base_revision": model["revision"],
        "base_provenance_hash": provenance["content_hash"],
        "dataset_id": DATASET_ID,
        "dataset_bundle_hash": dataset_bundle_hash(DATASET_ROOT),
        "rendered_manifest_hash": read_hashed_json(RENDERED_ROOT / "manifest.json")["content_hash"],
        "training_plan_hash": read_hashed_json(TRAINING_PLAN_PATH)["content_hash"],
        "training_input_boundary_hash": boundary["content_hash"],
        "execution_source_snapshot": execution_source_snapshot,
        "framework": FRAMEWORK_VERSION,
        "training_implementation": TRAINING_IMPLEMENTATION_VERSION,
        "resource_monitor_version": RESOURCE_EVIDENCE_VERSION,
        "adapter_file": "adapter_model.safetensors",
        "adapter_sha256": sha256_file(adapter_dir / "adapter_model.safetensors"),
        "adapter_config_sha256": sha256_file(adapter_dir / "adapter_config.json"),
        "training_summary": training_summary,
    }


def train_candidate(*, formal: bool) -> dict[str, Any]:
    import torch

    plan = load_training_plan()
    if formal:
        from mlsys.training.stage9a_v6_readiness import require_smoke_readiness

        require_smoke_readiness()
    seed = FORMAL_SEED if formal else SMOKE_SEED
    run_id = FORMAL_RUN_ID if formal else SMOKE_RUN_ID
    epochs = EPOCHS if formal else 1
    maximum_steps = None if formal else SMOKE_STEPS
    output_root = RUNS_ROOT / run_id
    assert_local_only_path(output_root)
    if output_root.exists():
        raise FileExistsError(f"immutable v6 run already exists: {output_root}")
    before = resource_snapshot()
    assert_training_preflight(before)
    tokenizer = _load_tokenizer()
    boundary = verify_training_input_boundary(tokenizer)
    rows = _load_rows(tokenizer)
    execution_source_snapshot = current_source_revision(PROJECT_ROOT)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    output_root.mkdir(parents=True)
    adapter_dir = output_root / "adapter"
    monitor = ResourceMonitor(interval_seconds=1.0).start()
    started = time.perf_counter()
    model = None
    optimizer = None
    history: list[dict[str, Any]] = []
    failure: Exception | None = None
    quantization = None
    trainable = None
    initial_validation_loss = None
    final_validation_loss = None
    try:
        torch.cuda.reset_peak_memory_stats()
        model, trainable, quantization = _load_qlora_model(
            attn_implementation=TRAINING_ATTENTION_IMPLEMENTATION,
            gradient_checkpointing_use_reentrant=False,
            restore_frozen_base_io_bf16=True,
        )
        if trainable != EXPECTED_TRAINABLE_PARAMETERS:
            raise RuntimeError(f"v6 trainable parameter count drifted: {trainable}")
        optimizer = torch.optim.AdamW(
            [parameter for parameter in model.parameters() if parameter.requires_grad],
            lr=2e-4,
            weight_decay=0.0,
        )
        train_loader = _loader(rows.train, tokenizer, seed=seed, shuffle=True)
        validation_loader = _loader(rows.validation, tokenizer, seed=seed, shuffle=False)
        initial_validation_loss = _evaluate_loss_selective(model, validation_loader)
        step = 0
        for epoch in range(epochs):
            model.train()
            for batch in train_loader:
                if time.perf_counter() - started > MAX_SEED_SECONDS:
                    raise TimeoutError("v6 candidate training exceeded the two-hour seed budget")
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
                    raise RuntimeError("v6 selective training evidence is incomplete")
                if max(torch.cuda.max_memory_allocated(), torch.cuda.max_memory_reserved()) / 1024**2 > TARGET_VRAM_MIB:
                    raise RuntimeError("v6 training peak VRAM exceeded 11 GiB")
                step += 1
                history.append({
                    "optimizer_step": step,
                    "epoch": epoch + 1,
                    "loss": loss,
                    "gradient_norm": gradient_norm,
                    "selected_logit_count": selection["selected_logit_count"],
                    "elapsed_seconds": time.perf_counter() - started,
                })
                if maximum_steps is not None and step >= maximum_steps:
                    break
            if maximum_steps is not None and step >= maximum_steps:
                break
        final_validation_loss = _evaluate_loss_selective(model, validation_loader)
        losses = [row["loss"] for row in history]
        expected_steps = FROZEN_COUNTS["train"] * EPOCHS if formal else SMOKE_STEPS
        if len(losses) != expected_steps or any(not math.isfinite(value) or value <= 0 for value in losses):
            raise RuntimeError("v6 loss history is incomplete or non-finite")
        torch.cuda.synchronize()
        monitor.samples.append(resource_snapshot())
        monitor.check()
        model.save_pretrained(adapter_dir, safe_serialization=True)
        tokenizer.save_pretrained(adapter_dir / "tokenizer")
        if not (adapter_dir / "adapter_model.safetensors").is_file():
            raise RuntimeError("v6 adapter safetensors was not saved")
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
        failure = RuntimeError("v6 resource evidence is incomplete or outside Stage 9A limits")
    if failure is not None:
        report = {
            "schema_version": 1,
            "run_id": run_id,
            "formal": formal,
            "status": "failed",
            "failure": {"type": type(failure).__name__, "message": str(failure)},
            "candidate_only": True,
            "local_only": True,
            "promotion_authorized": False,
            "deployment_authorized": False,
            "dataset_bundle_hash": dataset_bundle_hash(DATASET_ROOT),
            "training_plan_hash": plan["content_hash"],
            "resource_evidence": resources,
            "failed_at": datetime.now(UTC).isoformat(),
        }
        write_hashed_json(output_root / "failure.json", report)
        del model, optimizer
        gc.collect()
        torch.cuda.empty_cache()
        raise failure
    summary = {
        "status": "completed_candidate",
        "epochs_requested": epochs,
        "optimizer_steps": len(history),
        "initial_validation_loss": initial_validation_loss,
        "final_validation_loss": final_validation_loss,
        "wall_time_seconds": time.perf_counter() - started,
        "peak_vram_mib": observed_peak,
        "minimum_available_ram_gib": resources["minimum"]["ram_available_gib"],
        "maximum_swap_used_mib": resources["maximum"]["swap_used_mib"],
    }
    binding = _adapter_binding(
        adapter_dir=adapter_dir,
        run_id=run_id,
        seed=seed,
        formal=formal,
        boundary=boundary,
        training_summary=summary,
        execution_source_snapshot=execution_source_snapshot,
    )
    binding = write_hashed_json(adapter_dir / "havre_adapter_manifest.json", binding)
    report = {
        "schema_version": 1,
        "candidate_id": binding["candidate_id"],
        "run_id": run_id,
        "seed": seed,
        "formal": formal,
        "status": "completed_candidate",
        "candidate_only": True,
        "local_only": True,
        "promotion_authorized": False,
        "deployment_authorized": False,
        "contains_user_data": True,
        "dataset_bundle_hash": dataset_bundle_hash(DATASET_ROOT),
        "rendered_manifest_hash": read_hashed_json(RENDERED_ROOT / "manifest.json")["content_hash"],
        "training_plan_hash": plan["content_hash"],
        "training_input_boundary_hash": boundary["content_hash"],
        "execution_source_snapshot": execution_source_snapshot,
        "framework": FRAMEWORK_VERSION,
        "training_implementation": TRAINING_IMPLEMENTATION_VERSION,
        "loss_path_version": LOSS_PATH_VERSION,
        "quantization": quantization,
        "attention_implementation": TRAINING_ATTENTION_IMPLEMENTATION,
        "lora": {"rank": LORA_RANK, "alpha": LORA_ALPHA, "dropout": 0.05, "target_modules": "all-linear"},
        "optimizer": "torch.optim.AdamW_no_paging",
        "bf16_autocast": True,
        "trainable_parameters": trainable,
        "max_seq_length": 340,
        "history": history,
        "training_summary": summary,
        "resource_evidence": resources,
        "adapter_manifest_hash": binding["content_hash"],
        "completed_at": datetime.now(UTC).isoformat(),
    }
    written = write_hashed_json(output_root / "training-report.json", report)
    del model, optimizer
    gc.collect()
    torch.cuda.empty_cache()
    return written


def verify_adapter(adapter_dir: Path) -> dict[str, Any]:
    manifest = read_hashed_json(adapter_dir / "havre_adapter_manifest.json")
    model = load_model_manifest()
    if (
        manifest.get("base_repository") != model["repository"]
        or manifest.get("base_revision") != model["revision"]
        or manifest.get("dataset_bundle_hash") != dataset_bundle_hash(DATASET_ROOT)
        or manifest.get("rendered_manifest_hash") != read_hashed_json(RENDERED_ROOT / "manifest.json")["content_hash"]
        or manifest.get("training_plan_hash") != read_hashed_json(TRAINING_PLAN_PATH)["content_hash"]
        or manifest.get("contains_user_data") is not True
        or manifest.get("local_only") is not True
        or manifest.get("candidate_only") is not True
        or manifest.get("promotion_authorized") is not False
        or manifest.get("deployment_authorized") is not False
        or manifest.get("adapter_sha256") != sha256_file(adapter_dir / "adapter_model.safetensors")
        or manifest.get("adapter_config_sha256") != sha256_file(adapter_dir / "adapter_config.json")
    ):
        raise ValueError("v6 adapter binding mismatch")
    adapter_config = json.loads((adapter_dir / "adapter_config.json").read_text(encoding="utf-8"))
    expected_flags = {
        "peft_type": "LORA",
        "task_type": "CAUSAL_LM",
        "r": LORA_RANK,
        "lora_alpha": LORA_ALPHA,
        "lora_dropout": 0.05,
        "bias": "none",
        "use_dora": False,
        "use_rslora": False,
        "use_qalora": False,
        "lora_bias": False,
    }
    mismatches = {
        key: {"expected": expected, "actual": adapter_config.get(key)}
        for key, expected in expected_flags.items()
        if adapter_config.get(key) != expected
    }
    expected_targets = {
        "q_proj", "k_proj", "v_proj", "o_proj",
        "gate_proj", "up_proj", "down_proj",
    }
    if mismatches or set(adapter_config.get("target_modules", [])) != expected_targets:
        raise ValueError("v6 adapter configuration is incompatible")
    return manifest