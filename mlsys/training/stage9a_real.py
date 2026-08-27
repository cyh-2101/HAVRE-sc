"""Local-only real Qwen3-8B QLoRA gates and bounded Stage 9A training."""

from __future__ import annotations

import gc
import csv
import hashlib
import json
import math
import os
import statistics
import subprocess
import sys
import threading
import time
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from companion.hashing import content_hash
from evals.inference_runner import current_source_revision
from mlsys.training.stage9a_dataset_v4 import (
    ARTIFACT_VERSION,
    DATASET_ROOT,
    DATASET_VERSION,
    EXTERNAL_BUNDLE_HASH,
    SPLIT_COUNTS,
    TRAINING_SPLITS,
    dataset_bundle_hash,
    load_and_verify_dataset,
)
from mlsys.training.stage9a_provenance import (
    FORMAL_EXECUTION_SOURCE_SNAPSHOT,
    MODEL_MANIFEST,
    PROJECT_ROOT,
    STAGE9A_ROOT,
    STORAGE_LIMIT_BYTES,
    directory_size,
    load_model_manifest,
    require_archived_source_snapshot,
    verify_model_artifact,
)


MODEL_ROOT = STAGE9A_ROOT / "models" / "qwen3-8b-b968826d"
RENDERED_ROOT = STAGE9A_ROOT / "datasets" / "stage9a-rendered-qwen3-b968826d-v4"
EVIDENCE_ROOT = STAGE9A_ROOT / "evidence"
RUNS_ROOT = STAGE9A_ROOT / "runs"
FRAMEWORK_VERSION = "transformers-peft-bitsandbytes-stage9a-v1"
RENDERER_VERSION = "qwen3-v4-multiturn-final-target-no-thinking-v1"
HARD_VRAM_MIB = int(11.5 * 1024)
TARGET_VRAM_MIB = 11 * 1024
MIN_AVAILABLE_RAM_GIB = 19.5
MAX_SWAP_GROWTH_MIB = 256
MAX_SHARED_GPU_GROWTH_MIB = 512
MAX_FORMAL_SEED_SECONDS = 2 * 60 * 60
MAX_FORMAL_GPU_SECONDS = 6 * 60 * 60
REQUIRED_FORMAL_SEEDS = (9201, 9202)
OPTIONAL_THIRD_SEED = 9203
RESOURCE_EVIDENCE_VERSION = "windows-typeperf-shared-gpu-fail-closed-v2"
RESOURCE_EVIDENCE_VALIDATION_VERSION = "raw-sample-aggregate-recompute-v1"
RESOURCE_CORRECTION_TAG = "resource-correction1"
SMOKE_RUN_ID = f"gate-d-smoke-v4-{RESOURCE_CORRECTION_TAG}"
FORMAL_RUN_IDS = {
    seed: f"formal-seed-{seed}-v4-{RESOURCE_CORRECTION_TAG}"
    for seed in (*REQUIRED_FORMAL_SEEDS, OPTIONAL_THIRD_SEED)
}
FORMAL_EVALUATION_IDS = {
    seed: f"evaluation-seed-{seed}-{RESOURCE_CORRECTION_TAG}"
    for seed in (*REQUIRED_FORMAL_SEEDS, OPTIONAL_THIRD_SEED)
}
SUPERSEDED_FORMAL_RUN_IDS = {
    seed: f"formal-seed-{seed}-v4" for seed in REQUIRED_FORMAL_SEEDS
}
SUPERSEDED_FORMAL_REPORT_HASHES = {
    9201: "sha256:fef0192f617ecd151a4a5059ee3b1e5a550a6ba85c5e9e42c1a9454cfdf66612",
    9202: "sha256:f3a412f8d4d08c5fa89d47c88938c5e56b3916ac082f1b502721e271086a013a",
}
GATE_A_EVIDENCE_NAME = f"gate-a-v4-{RESOURCE_CORRECTION_TAG}.json"
GATE_B_EVIDENCE_NAME = f"gate-b-v4-{RESOURCE_CORRECTION_TAG}.json"
GATE_C_EVIDENCE_NAME = "gate-c-v4.json"
REMEDIATED_GATE_C_EVIDENCE_NAME = (
    f"gate-c-v4-remediated-selective-v1-{RESOURCE_CORRECTION_TAG}.json"
)
REENTRANT_PROBE_EVIDENCE_NAME = "gate-c-v4-reentrant-remediation-probe-1.json"
SELECTIVE_LOGITS_PROBE_EVIDENCE_NAME = (
    "gate-c-v4-selective-logits-remediation-probe-1.json"
)
NONREENTRANT_SELECTIVE_PROBE_EVIDENCE_NAME = (
    "gate-c-v4-nonreentrant-selective-remediation-probe-1.json"
)
BF16_AUTOCAST_SELECTIVE_PROBE_EVIDENCE_NAME = (
    "gate-c-v4-bf16-autocast-selective-remediation-probe-1.json"
)
FROZEN_IO_BF16_SELECTIVE_PROBE_EVIDENCE_NAME = (
    "gate-c-v4-frozen-io-bf16-selective-remediation-probe-1.json"
)
FROZEN_IO_BF16_AUTOCAST_PROBE_EVIDENCE_NAME = (
    "gate-c-v4-frozen-io-bf16-autocast-selective-probe-1.json"
)
FROZEN_IO_BF16_AUTOCAST_CACHE_TRIM_PROBE_EVIDENCE_NAME = (
    "gate-c-v4-frozen-io-bf16-autocast-cache-trim-selective-probe-1.json"
)
SELECTIVE_LOGITS_LOSS_VERSION = "qwen3-v4-supervised-suffix-selective-logits-v1"
TRAINING_IMPLEMENTATION_VERSION = (
    "qwen3-v4-nf4-qlora-selective-bf16-cache-trim-v1"
)
APPROVED_RENDERED_MANIFEST_HASH = (
    "sha256:8bad6bd7042b3039f549ea5f8080f5e4f63ed83582aa91aa5aa15ec42e1c659a"
)
APPROVED_PRE_REMEDIATION_SOURCE_SNAPSHOT = (
    "sha256:858dc7cb8a7578801a4c033c772ac8628a39322366ae225431a6fd731bd223e4"
)
APPROVED_GATE_B_V4_HASH = (
    "sha256:3c2e33326ef08a8a9ad457b89c4c7001f56db357ca42e46a6bb12c4bcc2173c6"
)
SUPERSEDED_GATE_C_V4_HASH = (
    "sha256:7db2c43001aaa28b39f6c7447e8a2f0f2adc0a4b42b950c6015c82770093f14e"
)
SUPERSEDED_GATE_D_REPORT_HASH = (
    "sha256:9a7e3f431cfe5de286ee95ec5333b1e3ca2d661618cc0f919cd4f483897e21fd"
)
ORIGINAL_GATE_C_V4_FAILURE_HASH = (
    "sha256:f5f47861bd00cc68ae425420630a7cf452d1bb9d0948db33476d3eff64abe51e"
)
REENTRANT_PROBE_FAILURE_HASH = (
    "sha256:64546d12982547ea82f7407b1a4ee934ffe18bb6a9c89ca44c63a359979a341c"
)
SELECTIVE_LOGITS_PROBE_FAILURE_HASH = (
    "sha256:239eba42234e91b1851dbf27ce2b57ac03753ffa1b03a1712784b4b8252ad539"
)
NONREENTRANT_SELECTIVE_PROBE_FAILURE_HASH = (
    "sha256:7b172fb9e610155926f289064e73d6a66015765fd72bd1e6d9fca69b432c796e"
)
FROZEN_IO_BF16_PROBE_FAILURE_HASH = (
    "sha256:e2412cfe60e5cec811fa0a96fbccb2aa922116863c1c8e6a114b384a2159ba57"
)
FROZEN_IO_BF16_AUTOCAST_PROBE_FAILURE_HASH = (
    "sha256:fa40d2e7c763733363481c7f5c9f7c8e93c9d8a019feba6d4cab7100e39df987"
)
APPROVED_CACHE_TRIM_PROBE_HASH = (
    "sha256:09a5f932d80ea7f9d4a58ab6f7f52f839698a45159f9d220594d58d6b0dd80b2"
)
REENTRANT_PROBE_LONGEST_TOKENS = 321
SELECTIVE_PROBE_EXAMPLE_ID = "stage9a-train-0211"
SELECTIVE_PROBE_SUPERVISED_TOKENS = 34
TRAINING_ATTENTION_IMPLEMENTATION = "eager"
LORA_RANK = 4
LORA_ALPHA = 8


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def write_hashed_json(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    material = dict(payload)
    material["content_hash"] = content_hash(material)
    path.write_text(
        json.dumps(material, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return material


def read_hashed_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    claimed = payload.pop("content_hash")
    if content_hash(payload) != claimed:
        raise ValueError(f"content hash mismatch: {path}")
    payload["content_hash"] = claimed
    return payload


def require_passed_evidence(path: Path, *, expected_gate: str | None = None) -> dict[str, Any]:
    """Require immutable, hash-valid prerequisite evidence before a later gate."""
    payload = read_hashed_json(path)
    if payload.get("status") != "passed":
        raise RuntimeError(f"required Stage 9A evidence did not pass: {path}")
    if expected_gate is not None and payload.get("gate") != expected_gate:
        raise RuntimeError(f"Stage 9A evidence is for the wrong gate: {path}")
    return payload


def require_v4_gate_evidence(path: Path, *, expected_gate: str) -> dict[str, Any]:
    """Require a passed gate bound to the exact current v4 dataset and source."""
    payload = require_passed_evidence(path, expected_gate=expected_gate)
    evidence_dataset_version = payload.get(
        "dataset_version", payload.get("intended_dataset_version")
    )
    evidence_dataset_hash = payload.get(
        "dataset_bundle_hash", payload.get("intended_dataset_bundle_hash")
    )
    if (
        evidence_dataset_version != DATASET_VERSION
        or evidence_dataset_hash != dataset_bundle_hash(DATASET_ROOT)
        or payload.get("execution_source_snapshot")
        != current_source_revision(PROJECT_ROOT)
    ):
        raise RuntimeError(f"Stage 9A v4 evidence is stale or cross-bound: {path}")
    return payload


def require_remediated_gate_c() -> dict[str, Any]:
    """Require the exact source-bound Gate C that uses the reviewed v4 path."""
    path = EVIDENCE_ROOT / REMEDIATED_GATE_C_EVIDENCE_NAME
    payload = require_passed_evidence(path, expected_gate="C")
    archived_source = require_archived_source_snapshot(
        FORMAL_EXECUTION_SOURCE_SNAPSHOT
    )
    selection = payload.get("selected_supervision", {})
    suffix = payload.get("suffix_contract_summary", {})
    configuration = payload.get("unchanged_training_configuration", {})
    dtype_evidence = payload.get("frozen_base_io_dtype_evidence", {})
    resources = payload.get("resources", {})
    baseline = resources.get("baseline", {})
    maximum = resources.get("maximum", {})
    memory_stages = payload.get("torch_memory_stages", {})
    expected_configuration = {
        "attention_implementation": TRAINING_ATTENTION_IMPLEMENTATION,
        "base_repository": "Qwen/Qwen3-8B",
        "base_revision": "b968826d9c46dd6066d109eabc6255188de91218",
        "batch_size": 1,
        "bf16_autocast": True,
        "frozen_base_io_bf16_restored": True,
        "learning_rate": 2e-4,
        "lora_alpha": LORA_ALPHA,
        "lora_dropout": 0.05,
        "lora_rank": LORA_RANK,
        "lora_target_modules": "all-linear",
        "loss_reduction": "mean_over_supervised_target_tokens",
        "max_seq_length": 336,
        "optimizer": "torch.optim.AdamW_no_paging",
        "quantization": "nf4_double_quant_bf16_compute",
        "release_cuda_cache_before_optimizer": True,
        "weight_decay": 0.0,
    }
    resource_values = (
        payload.get("nvidia_smi_peak_vram_mib"),
        payload.get("torch_peak_allocated_mib"),
        payload.get("torch_peak_reserved_mib"),
        payload.get("shared_gpu_growth_mib"),
        payload.get("swap_growth_mib"),
        baseline.get("ram_available_gib"),
        maximum.get("vram_used_mib"),
    )
    if (
        payload.get("implementation_version") != TRAINING_IMPLEMENTATION_VERSION
        or payload.get("loss_path_version") != SELECTIVE_LOGITS_LOSS_VERSION
        or payload.get("prior_evidence_hash") != APPROVED_CACHE_TRIM_PROBE_HASH
        or payload.get("probe") != "stage9a-v4-remediated-formal-gate-c-v1"
        or payload.get("dataset_version") != DATASET_VERSION
        or payload.get("dataset_bundle_hash") != dataset_bundle_hash(DATASET_ROOT)
        or payload.get("rendered_manifest_hash") != APPROVED_RENDERED_MANIFEST_HASH
        or payload.get("rendered_max_seq_length") != 336
        or payload.get("execution_source_snapshot")
        != archived_source["snapshot"]
        or payload.get("gate_b_evidence_hash")
        != read_hashed_json(EVIDENCE_ROOT / GATE_B_EVIDENCE_NAME).get("content_hash")
        or payload.get("candidate_only") is not True
        or payload.get("formal_training") is not False
        or payload.get("gate_d_authorized") is not True
        or payload.get("promotion_authorized") is not False
        or payload.get("deployment_authorized") is not False
        or payload.get("cpu_offload") is not False
        or payload.get("disk_offload") is not False
        or payload.get("real_forward") is not True
        or payload.get("real_backward") is not True
        or payload.get("real_optimizer_step") is not True
        or not isinstance(payload.get("loss"), (int, float))
        or not math.isfinite(float(payload["loss"]))
        or float(payload["loss"]) <= 0
        or not isinstance(payload.get("gradient_norm"), (int, float))
        or not math.isfinite(float(payload["gradient_norm"]))
        or payload.get("all_gradient_tensors_finite") is not True
        or payload.get("gradient_tensor_count") != 504
        or payload.get("optimizer_state_materialized") is not True
        or payload.get("optimizer_state_entries") != 504
        or payload.get("optimizer_nonscalar_state_tensor_devices") != ["cuda:0"]
        or payload.get("model_parameter_devices") != {"cuda:0": 4728763392}
        or payload.get("trainable_parameters") != 10911744
        or payload.get("sample_id") != SELECTIVE_PROBE_EXAMPLE_ID
        or payload.get("sample_token_length") != REENTRANT_PROBE_LONGEST_TOKENS
        or payload.get("supervised_suffix_token_count")
        != SELECTIVE_PROBE_SUPERVISED_TOKENS
        or selection.get("sequence_length") != REENTRANT_PROBE_LONGEST_TOKENS
        or selection.get("supervised_label_start") != 287
        or selection.get("supervised_label_end_inclusive") != 320
        or selection.get("selected_logit_start") != 286
        or selection.get("selected_logit_end_inclusive") != 319
        or selection.get("selected_logit_count") != SELECTIVE_PROBE_SUPERVISED_TOKENS
        or selection.get("supervised_token_count") != SELECTIVE_PROBE_SUPERVISED_TOKENS
        or selection.get("bf16_autocast_enabled") is not True
        or selection.get("logits_dtype") != "torch.bfloat16"
        or suffix.get("train", {}).get("count") != SPLIT_COUNTS["train"]
        or suffix.get("validation", {}).get("count") != SPLIT_COUNTS["validation"]
        or suffix.get("train", {}).get("all_contiguous_supervised_suffix") is not True
        or suffix.get("validation", {}).get("all_contiguous_supervised_suffix") is not True
        or configuration != expected_configuration
        or dtype_evidence.get("base_manifest_torch_dtype") != "bfloat16"
        or dtype_evidence.get("total_saved_mib") != 2374.0
        or dtype_evidence.get("trainable_parameters_changed") is not False
        or any(not isinstance(value, (int, float)) for value in resource_values)
        or float(payload.get("nvidia_smi_peak_vram_mib", math.inf))
        > TARGET_VRAM_MIB
        or float(payload.get("torch_peak_allocated_mib", math.inf))
        > TARGET_VRAM_MIB
        or float(payload.get("torch_peak_reserved_mib", math.inf))
        > TARGET_VRAM_MIB
        or float(payload.get("shared_gpu_growth_mib", math.inf))
        > MAX_SHARED_GPU_GROWTH_MIB
        or float(payload.get("swap_growth_mib", math.inf)) > MAX_SWAP_GROWTH_MIB
        or resources.get("hard_failure") is not None
        or resources.get("resource_monitor_version") != RESOURCE_EVIDENCE_VERSION
        or not resources.get("samples")
        or any(
            sample.get("resource_monitor_version") != RESOURCE_EVIDENCE_VERSION
            for sample in resources.get("samples", [])
        )
        or float(baseline.get("ram_available_gib", -math.inf)) < MIN_AVAILABLE_RAM_GIB
        or float(maximum.get("vram_used_mib", math.inf))
        != float(payload.get("nvidia_smi_peak_vram_mib", -math.inf))
        or memory_stages.get("after_cache_release_before_optimizer", {}).get(
            "reserved_mib", math.inf
        )
        >= memory_stages.get("before_cache_release", {}).get(
            "reserved_mib", -math.inf
        )
        or payload.get("configuration_delta", {}).get(
            "supersedes_resource_evidence_hash"
        )
        != SUPERSEDED_GATE_C_V4_HASH
    ):
        raise RuntimeError("remediated Stage 9A Gate C is stale or cross-bound")
    return payload


def _require_current_adapter_training_binding(
    manifest: dict[str, Any],
) -> dict[str, Any]:
    gate_c = require_remediated_gate_c()
    if (
        manifest.get("training_implementation") != TRAINING_IMPLEMENTATION_VERSION
        or manifest.get("remediated_gate_c_hash") != gate_c["content_hash"]
        or manifest.get("execution_source_snapshot")
        != gate_c["execution_source_snapshot"]
    ):
        raise ValueError("adapter training source/Gate C binding mismatch")
    return gate_c


def require_dataset_freeze_approval() -> dict[str, Any]:
    """Fail closed until the Product Owner freezes this exact candidate dataset hash."""
    approval_path = EVIDENCE_ROOT / "dataset-v4-po-freeze-approval.json"
    if not approval_path.is_file():
        raise PermissionError("Dataset v4 lacks Product Owner freeze approval")
    approval = read_hashed_json(approval_path)
    if (
        approval.get("decision") != "ACCEPT"
        or approval.get("dataset_version") != DATASET_VERSION
        or approval.get("dataset_bundle_hash") != dataset_bundle_hash(DATASET_ROOT)
        or approval.get("dataset_bundle_hash") != EXTERNAL_BUNDLE_HASH
        or approval.get("training_authorized") is not True
        or approval.get("owner_alignment_permanently_excluded") is not True
        or approval.get("stage9a_only") is not True
        or approval.get("promotion_authorized") is not False
        or approval.get("deployment_authorized") is not False
    ):
        raise PermissionError("Dataset v4 Product Owner approval is absent or hash-mismatched")
    return approval


def _shared_gpu_mib() -> float:
    try:
        completed = subprocess.run(
            [
                "typeperf.exe",
                r"\GPU Adapter Memory(*)\Shared Usage",
                "-sc",
                "1",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("shared GPU counter collection timed out") from error
    if completed.returncode != 0:
        raise RuntimeError(
            "shared GPU counter collection failed: "
            f"exit={completed.returncode} stderr={completed.stderr[-500:]}"
        )
    for row in csv.reader(completed.stdout.splitlines()):
        if len(row) < 2 or row[0].startswith("(PDH-"):
            continue
        try:
            values = [float(value) for value in row[1:]]
        except ValueError:
            continue
        if values and all(math.isfinite(value) and value >= 0 for value in values):
            return sum(values) / 1024**2
    raise RuntimeError("shared GPU counter collection returned no valid sample")


def _nvidia_metrics() -> dict[str, float]:
    completed = subprocess.run(
        [
            "nvidia-smi.exe",
            "--query-gpu=memory.used,memory.free,utilization.gpu,temperature.gpu,power.draw",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    used, free, utilization, temperature, power = (
        float(value.strip()) for value in completed.stdout.strip().split(",")
    )
    return {
        "vram_used_mib": used,
        "vram_free_mib": free,
        "gpu_utilization_percent": utilization,
        "gpu_temperature_c": temperature,
        "gpu_power_w": power,
    }


def resource_snapshot() -> dict[str, Any]:
    import psutil

    virtual = psutil.virtual_memory()
    swap = psutil.swap_memory()
    return {
        "resource_monitor_version": RESOURCE_EVIDENCE_VERSION,
        **_nvidia_metrics(),
        "shared_gpu_mib": _shared_gpu_mib(),
        "ram_available_gib": virtual.available / 1024**3,
        "ram_used_gib": virtual.used / 1024**3,
        "swap_used_mib": swap.used / 1024**2,
        "stage9a_disk_gib": directory_size(STAGE9A_ROOT) / 1024**3,
        "recorded_at": datetime.now(UTC).isoformat(),
    }


def assert_training_preflight(snapshot: dict[str, Any]) -> None:
    if snapshot["ram_available_gib"] < MIN_AVAILABLE_RAM_GIB:
        raise RuntimeError(
            f"available RAM {snapshot['ram_available_gib']:.2f} GiB is below "
            f"the approved approximately-20 GiB gate"
        )
    if snapshot["swap_used_mib"] > 512:
        raise RuntimeError("pre-existing swap pressure is too high for Stage 9A")
    if snapshot["stage9a_disk_gib"] > 80:
        raise RuntimeError("Stage 9A private storage exceeds 80 GiB")


class ResourceMonitor:
    def __init__(self, *, interval_seconds: float = 5.0) -> None:
        self.interval_seconds = interval_seconds
        self.samples: list[dict[str, Any]] = []
        self.stop_event = threading.Event()
        self.hard_failure: str | None = None
        self.thread: threading.Thread | None = None
        self.baseline: dict[str, Any] | None = None

    def start(self) -> "ResourceMonitor":
        self.baseline = resource_snapshot()
        self.samples.append(self.baseline)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        return self

    def _run(self) -> None:
        assert self.baseline is not None
        while not self.stop_event.wait(self.interval_seconds):
            try:
                sample = resource_snapshot()
                self.samples.append(sample)
                if sample["vram_used_mib"] > HARD_VRAM_MIB:
                    self.hard_failure = "vram_above_11_5_gib"
                elif sample["swap_used_mib"] - self.baseline["swap_used_mib"] > MAX_SWAP_GROWTH_MIB:
                    self.hard_failure = "swap_growth_above_256_mib"
                elif sample["shared_gpu_mib"] - self.baseline["shared_gpu_mib"] > MAX_SHARED_GPU_GROWTH_MIB:
                    self.hard_failure = "shared_gpu_growth_above_512_mib"
                elif sample["stage9a_disk_gib"] * 1024**3 > STORAGE_LIMIT_BYTES:
                    self.hard_failure = "stage9a_storage_above_80_gib"
            except Exception as error:  # evidence collection failure is itself blocking
                self.hard_failure = f"resource_monitor_error:{type(error).__name__}:{error}"

    def check(self) -> None:
        if self.hard_failure:
            raise RuntimeError(self.hard_failure)

    def stop(self) -> dict[str, Any]:
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=20)
        if not self.samples:
            return {
                "resource_monitor_version": RESOURCE_EVIDENCE_VERSION,
                "samples": [],
                "hard_failure": self.hard_failure,
            }
        numeric = (
            "vram_used_mib", "shared_gpu_mib", "ram_available_gib", "ram_used_gib",
            "swap_used_mib", "stage9a_disk_gib", "gpu_utilization_percent",
            "gpu_temperature_c", "gpu_power_w",
        )
        return {
            "resource_monitor_version": RESOURCE_EVIDENCE_VERSION,
            "sample_count": len(self.samples),
            "hard_failure": self.hard_failure,
            "baseline": self.samples[0],
            "final": self.samples[-1],
            "minimum": {key: min(item[key] for item in self.samples) for key in numeric},
            "maximum": {key: max(item[key] for item in self.samples) for key in numeric},
            "samples": self.samples,
        }


def gate_a_cuda() -> dict[str, Any]:
    import torch

    if (EVIDENCE_ROOT / GATE_A_EVIDENCE_NAME).exists():
        raise FileExistsError("immutable versioned Gate A evidence already exists")
    started = time.perf_counter()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable")
    device = torch.device("cuda:0")
    capability = torch.cuda.get_device_capability(device)
    if capability != (12, 0):
        raise RuntimeError(f"expected sm_120, got {capability}")
    left = torch.randn((1024, 1024), device=device, dtype=torch.bfloat16, requires_grad=True)
    right = torch.randn((1024, 1024), device=device, dtype=torch.bfloat16)
    loss = (left @ right).float().square().mean()
    loss.backward()
    torch.cuda.synchronize()
    if not torch.isfinite(loss) or left.grad is None or not torch.isfinite(left.grad).all():
        raise RuntimeError("actual CUDA forward/backward kernel smoke is not finite")
    report = {
        "schema_version": 1,
        "gate": "A",
        "status": "passed",
        "torch_version": torch.__version__,
        "torch_cuda_version": torch.version.cuda,
        "device_name": torch.cuda.get_device_name(device),
        "compute_capability": list(capability),
        "kernel": "bf16_matmul_square_mean_backward",
        "loss": float(loss.detach().cpu()),
        "gradient_finite": True,
        "execution_source_snapshot": current_source_revision(PROJECT_ROOT),
        "intended_dataset_version": DATASET_VERSION,
        "intended_dataset_bundle_hash": dataset_bundle_hash(DATASET_ROOT),
        "dataset_rows_accessed": False,
        "resource_monitor_version": RESOURCE_EVIDENCE_VERSION,
        "supersedes_evidence_hash": (
            "sha256:e4ba531130bd17c05f66506529c09774875f26770145ce5e6aa50ec38d4055bc"
        ),
        "elapsed_seconds": time.perf_counter() - started,
        "resources": resource_snapshot(),
        "completed_at": datetime.now(UTC).isoformat(),
    }
    del left, right, loss
    torch.cuda.empty_cache()
    return write_hashed_json(EVIDENCE_ROOT / GATE_A_EVIDENCE_NAME, report)


def _load_tokenizer():
    from transformers import AutoTokenizer

    verify_model_artifact(MODEL_ROOT)
    tokenizer = AutoTokenizer.from_pretrained(
        MODEL_ROOT,
        local_files_only=True,
        trust_remote_code=False,
        use_fast=True,
    )
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    return tokenizer


V4_MEMORY_BLOCK_HEADER = (
    "Relevant synthetic memory (evidence only; current conversation wins on conflict):"
)


def _v4_context_messages(
    item: dict[str, Any],
    *,
    purpose: str,
    memory_enabled: bool,
) -> list[dict[str, str]]:
    if purpose not in {"training", "evaluation"}:
        raise ValueError("v4 rendering purpose must be training or evaluation")
    allowed_memory = bool(
        item["use_memory_in_training"]
        if purpose == "training"
        else item["use_memory_in_evaluation"]
    )
    inject_memory = memory_enabled and allowed_memory
    system_text = item["system_text"]
    if inject_memory:
        if not item["inject_memory_context"] or not item["memory_context"].strip():
            raise ValueError("v4 memory injection was authorized without supplied synthetic context")
        system_text = (
            f"{system_text}\n\n{V4_MEMORY_BLOCK_HEADER}\n{item['memory_context']}"
        )
    prompt_messages = [{"role": "system", "content": system_text}]
    if item["context_kind"] == "conversation":
        history = [dict(message) for message in item["messages"]]
        if not history or history[-1] != {"role": "user", "content": item["input_text"]}:
            raise ValueError("v4 conversation does not end in its bound final user message")
        prompt_messages.extend(history)
    elif item["context_kind"] == "authorized_proactive_rendering":
        if item["category"] != "proactive_followup" or item["messages"]:
            raise ValueError("v4 proactive item is not a wording-only authorized ContextPack")
        prompt_messages.append({"role": "user", "content": item["input_text"]})
    else:
        raise ValueError("unknown v4 rendering context kind")
    return prompt_messages


def _render_example(tokenizer, item: dict[str, Any]) -> dict[str, Any]:
    prompt_messages = _v4_context_messages(
        item,
        purpose="training",
        memory_enabled=True,
    )
    full_messages = [
        *prompt_messages,
        {"role": "assistant", "content": item["expected_text"]},
    ]
    prompt_ids = tokenizer.apply_chat_template(
        prompt_messages,
        tokenize=True,
        add_generation_prompt=True,
        enable_thinking=False,
    )
    full_ids = tokenizer.apply_chat_template(
        full_messages,
        tokenize=True,
        add_generation_prompt=False,
        enable_thinking=False,
    )
    if full_ids[:len(prompt_ids)] != prompt_ids:
        raise ValueError("Qwen3 prompt is not an exact prefix of the supervised rendering")
    labels = [-100] * len(prompt_ids) + full_ids[len(prompt_ids):]
    if not any(value != -100 for value in labels):
        raise ValueError("rendered example has no supervised assistant tokens")
    return {
        "example_id": item["example_id"],
        "source_content_hash": item["content_hash"],
        "category": item["category"],
        "context_kind": item["context_kind"],
        "context_message_count": len(prompt_messages) - 1,
        "historical_assistant_message_count": sum(
            message["role"] == "assistant" for message in prompt_messages[:-1]
        ),
        "memory_injected": bool(item["use_memory_in_training"]),
        "input_ids": full_ids,
        "labels": labels,
        "prompt_token_count": len(prompt_ids),
        "assistant_token_count": len(full_ids) - len(prompt_ids),
        "total_token_count": len(full_ids),
    }


def _percentile(values: list[int], percentile: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return float(ordered[lower])
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def build_rendered_artifacts() -> dict[str, Any]:
    require_dataset_freeze_approval()
    require_v4_gate_evidence(EVIDENCE_ROOT / GATE_A_EVIDENCE_NAME, expected_gate="A")
    tokenizer = _load_tokenizer()
    splits = load_and_verify_dataset(DATASET_ROOT)
    rendered: dict[str, list[dict[str, Any]]] = {
        split: [_render_example(tokenizer, item) for item in items]
        for split, items in splits.items()
        if split in TRAINING_SPLITS
    }
    decision_lengths = [
        item["total_token_count"]
        for split in ("train", "validation")
        for item in rendered[split]
    ]
    chosen = int(math.ceil(max(decision_lengths) / 16) * 16)
    chosen = max(64, min(chosen, 512))
    if RENDERED_ROOT.exists():
        raise FileExistsError(f"immutable rendered training artifact already exists: {RENDERED_ROOT}")
    RENDERED_ROOT.mkdir(parents=True)
    split_reports = {}
    for split, items in rendered.items():
        path = RENDERED_ROOT / f"{split}.jsonl"
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            for item in items:
                material = dict(item)
                material["content_hash"] = content_hash(material)
                handle.write(json.dumps(material, separators=(",", ":"), sort_keys=True) + "\n")
        lengths = [item["total_token_count"] for item in items]
        truncated = sum(value > chosen for value in lengths)
        padded_tokens = sum(max(0, chosen - min(value, chosen)) for value in lengths)
        untruncated_tokens = sum(lengths)
        selected_tokens = sum(min(value, chosen) for value in lengths)
        source_manifest = json.loads(
            (DATASET_ROOT / f"stage9a_{split}_{ARTIFACT_VERSION}.manifest.json").read_text(encoding="utf-8")
        )
        if {item["example_id"] for item in items} != {
            item["example_id"] for item in splits[split]
        }:
            raise ValueError(f"{split} rendered membership is not an exact source bijection")
        split_reports[split] = {
            "artifact": str(path),
            "artifact_sha256": sha256_file(path),
            "count": len(items),
            "source_member_manifest_hash": source_manifest["member_manifest_hash"],
            "minimum": min(lengths),
            "p50": _percentile(lengths, 0.50),
            "p90": _percentile(lengths, 0.90),
            "p95": _percentile(lengths, 0.95),
            "p99": _percentile(lengths, 0.99),
            "maximum": max(lengths),
            "truncation_count": truncated,
            "truncation_rate": truncated / len(lengths),
            "untruncated_token_count": untruncated_tokens,
            "selected_token_count": selected_tokens,
            "selected_token_retention": selected_tokens / untruncated_tokens,
            "dynamic_batch_padding_token_efficiency": 1.0,
            "hypothetical_fixed_length_padding_token_efficiency": (
                selected_tokens / (selected_tokens + padded_tokens)
            ),
        }
    report = {
        "schema_version": 1,
        "renderer_version": RENDERER_VERSION,
        "tokenizer_class": type(tokenizer).__name__,
        "tokenizer_length": len(tokenizer),
        "dataset_version": DATASET_VERSION,
        "dataset_bundle_hash": dataset_bundle_hash(DATASET_ROOT),
        "external_candidate_bundle_hash": EXTERNAL_BUNDLE_HASH,
        "execution_source_snapshot": current_source_revision(PROJECT_ROOT),
        "decision_basis": "train_and_validation_only_holdout_not_used",
        "supervision_policy": "final_havre_target_only",
        "historical_assistant_context_label_masked": True,
        "memory_injection_policy": "selective_synthetic_context_only",
        "memory_block_header": V4_MEMORY_BLOCK_HEADER,
        "owner_alignment_set_used": False,
        "proactive_scope": "wording_after_core_authorized_send_now_only",
        "rendered_splits": list(TRAINING_SPLITS),
        "holdout_rendered": False,
        "excluded_holdout_member_manifest_hash": json.loads(
            (DATASET_ROOT / f"stage9a_holdout_{ARTIFACT_VERSION}.manifest.json").read_text(encoding="utf-8")
        )["member_manifest_hash"],
        "chosen_max_seq_length": chosen,
        "training_batch_size": 1,
        "padding_policy": "dynamic_per_batch",
        "resource_impact": {
            "vram": "smallest_16_token_multiple_covering_train_validation_lengths_capped_at_512",
            "training_time": "proportional_to_selected_train_validation_tokens_no_holdout_input",
            "base_model_max_context_used_as_default": False,
        },
        "split_reports": split_reports,
        "created_at": datetime.now(UTC).isoformat(),
    }
    return write_hashed_json(RENDERED_ROOT / "manifest.json", report)


def _verify_training_input_boundary(tokenizer=None) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    """Prove that rendered train/validation are exact projections of safe source members."""
    require_dataset_freeze_approval()
    if tokenizer is None:
        tokenizer = _load_tokenizer()
    splits = load_and_verify_dataset(DATASET_ROOT)
    manifest = read_hashed_json(RENDERED_ROOT / "manifest.json")
    expected_bundle_hash = dataset_bundle_hash(DATASET_ROOT)
    holdout_manifest = read_hashed_json(
        DATASET_ROOT / f"stage9a_holdout_{ARTIFACT_VERSION}.manifest.json"
    )
    if (
        manifest.get("schema_version") != 1
        or manifest.get("content_hash") != APPROVED_RENDERED_MANIFEST_HASH
        or manifest.get("renderer_version") != RENDERER_VERSION
        or manifest.get("dataset_version") != DATASET_VERSION
        or manifest.get("dataset_bundle_hash") != expected_bundle_hash
        or manifest.get("external_candidate_bundle_hash") != EXTERNAL_BUNDLE_HASH
        # The immutable rendered artifact preserves the exact renderer source
        # snapshot that produced it; downstream training records its own source.
        or manifest.get("execution_source_snapshot")
        != APPROVED_PRE_REMEDIATION_SOURCE_SNAPSHOT
        or manifest.get("decision_basis") != "train_and_validation_only_holdout_not_used"
        or manifest.get("supervision_policy") != "final_havre_target_only"
        or manifest.get("historical_assistant_context_label_masked") is not True
        or manifest.get("memory_injection_policy") != "selective_synthetic_context_only"
        or manifest.get("memory_block_header") != V4_MEMORY_BLOCK_HEADER
        or manifest.get("owner_alignment_set_used") is not False
        or manifest.get("proactive_scope")
        != "wording_after_core_authorized_send_now_only"
        or manifest.get("rendered_splits") != list(TRAINING_SPLITS)
        or manifest.get("holdout_rendered") is not False
        or manifest.get("excluded_holdout_member_manifest_hash")
        != holdout_manifest["member_manifest_hash"]
        or set(manifest.get("split_reports", {})) != set(TRAINING_SPLITS)
    ):
        raise ValueError("rendered manifest violates the Stage 9A training boundary")
    chosen = manifest.get("chosen_max_seq_length")
    if not isinstance(chosen, int) or not 1 <= chosen <= 512:
        raise ValueError("rendered manifest has an invalid maximum sequence length")

    verified_items: dict[str, list[dict[str, Any]]] = {}
    for split in TRAINING_SPLITS:
        path = RENDERED_ROOT / f"{split}.jsonl"
        report = manifest["split_reports"][split]
        source_manifest = read_hashed_json(
            DATASET_ROOT / f"stage9a_{split}_{ARTIFACT_VERSION}.manifest.json"
        )
        if (
            Path(report.get("artifact", "")).resolve() != path.resolve()
            or report.get("artifact_sha256") != sha256_file(path)
            or report.get("source_member_manifest_hash")
            != source_manifest["member_manifest_hash"]
        ):
            raise ValueError(f"{split} rendered artifact binding mismatch")
        lines = path.read_text(encoding="utf-8").splitlines()
        if report.get("count") != len(lines) or len(lines) != len(splits[split]):
            raise ValueError(f"{split} rendered count mismatch")
        source_by_id = {item["example_id"]: item for item in splits[split]}
        seen: set[str] = set()
        verified: list[dict[str, Any]] = []
        for line in lines:
            item = json.loads(line)
            claimed = item.pop("content_hash", None)
            example_id = item.get("example_id")
            if not isinstance(claimed, str) or content_hash(item) != claimed:
                raise ValueError(f"rendered item hash mismatch: {example_id}")
            if example_id in seen:
                raise ValueError(f"duplicate rendered example_id: {example_id}")
            source = source_by_id.get(example_id)
            if source is None:
                raise ValueError(f"{split} rendered item is not a source member: {example_id}")
            expected = _render_example(tokenizer, source)
            if item != expected:
                raise ValueError(f"rendered item does not exactly match its source: {example_id}")
            _supervised_suffix_spec(item["labels"])
            seen.add(example_id)
            verified.append(item)
        if seen != set(source_by_id):
            raise ValueError(f"{split} rendered membership is not an exact source bijection")
        verified_items[split] = verified

    boundary = {
        "schema_version": 1,
        "status": "passed",
        "dataset_version": DATASET_VERSION,
        "dataset_bundle_hash": expected_bundle_hash,
        "external_candidate_bundle_hash": EXTERNAL_BUNDLE_HASH,
        "rendered_manifest_hash": manifest["content_hash"],
        "rendered_splits": list(TRAINING_SPLITS),
        "counts": {split: len(verified_items[split]) for split in TRAINING_SPLITS},
        "holdout_rendered": False,
        "owner_alignment_set_used": False,
        "supervision_policy": "final_havre_target_only",
        "contains_user_data": any(
            item["contains_user_data"]
            for split in TRAINING_SPLITS
            for item in splits[split]
        ),
        "all_members_training_eligible": all(
            item["training_eligible"]
            for split in TRAINING_SPLITS
            for item in splits[split]
        ),
        "source_kinds": sorted({
            item["source_kind"]
            for split in TRAINING_SPLITS
            for item in splits[split]
        }),
        "selective_logit_contract": {
            "loss_path_version": SELECTIVE_LOGITS_LOSS_VERSION,
            "batch_size": 1,
            "splits": _summarize_supervised_suffixes(verified_items),
        },
        "max_seq_length": chosen,
    }
    boundary["content_hash"] = content_hash(boundary)
    return boundary, verified_items


def verify_training_input_boundary(tokenizer=None) -> dict[str, Any]:
    """Return hash-bound evidence for the fail-closed file training boundary."""
    boundary, _ = _verify_training_input_boundary(tokenizer)
    return boundary


def _iter_rendered(split: str, max_seq_length: int, tokenizer=None) -> Iterator[dict[str, list[int]]]:
    if split not in TRAINING_SPLITS:
        raise ValueError("only train and validation may enter the training iterator")
    boundary, verified_items = _verify_training_input_boundary(tokenizer)
    if max_seq_length != boundary["max_seq_length"]:
        raise ValueError("training iterator maximum sequence length differs from the verified manifest")
    for item in verified_items[split]:
        yield {
            "input_ids": item["input_ids"][:max_seq_length],
            "labels": item["labels"][:max_seq_length],
        }


@dataclass
class TokenDataset:
    items: list[dict[str, list[int]]]

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, index: int) -> dict[str, list[int]]:
        return self.items[index]


def _collate(batch: list[dict[str, list[int]]], pad_token_id: int):
    import torch

    maximum = max(len(item["input_ids"]) for item in batch)
    input_ids, labels, attention = [], [], []
    for item in batch:
        padding = maximum - len(item["input_ids"])
        input_ids.append(item["input_ids"] + [pad_token_id] * padding)
        labels.append(item["labels"] + [-100] * padding)
        attention.append([1] * len(item["input_ids"]) + [0] * padding)
    return {
        "input_ids": torch.tensor(input_ids, dtype=torch.long),
        "labels": torch.tensor(labels, dtype=torch.long),
        "attention_mask": torch.tensor(attention, dtype=torch.long),
    }


def _supervised_suffix_spec(labels: list[int]) -> dict[str, int]:
    """Validate and describe one masked-prefix/contiguous-suffix label sequence."""
    if not labels or any(not isinstance(value, int) for value in labels):
        raise ValueError("selective-logit labels must be a non-empty integer sequence")
    supervised = [index for index, value in enumerate(labels) if value != -100]
    if not supervised:
        raise ValueError("selective-logit labels contain no supervised suffix")
    start = supervised[0]
    sequence_length = len(labels)
    if start <= 0:
        raise ValueError("selective-logit supervision requires a preceding causal position")
    if supervised != list(range(start, sequence_length)):
        raise ValueError("selective-logit labels are not one contiguous supervised suffix")
    if any(value < 0 for value in labels[start:]):
        raise ValueError("selective-logit supervised suffix contains an invalid token ID")
    count = sequence_length - start
    return {
        "sequence_length": sequence_length,
        "supervised_label_start": start,
        "supervised_label_end_inclusive": sequence_length - 1,
        "supervised_token_count": count,
        "selected_logit_start": start - 1,
        "selected_logit_end_inclusive": sequence_length - 2,
        "selected_logit_count": count,
    }


def _summarize_supervised_suffixes(
    verified_items: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    summaries: dict[str, Any] = {}
    for split in TRAINING_SPLITS:
        specs = [_supervised_suffix_spec(item["labels"]) for item in verified_items[split]]
        summaries[split] = {
            "count": len(specs),
            "all_contiguous_supervised_suffix": True,
            "minimum_supervised_tokens": min(item["supervised_token_count"] for item in specs),
            "maximum_supervised_tokens": max(item["supervised_token_count"] for item in specs),
        }
    return summaries


def _selective_supervision(batch):
    """Return exact causal positions and targets for the batch-size-1 v4 path."""
    import torch

    required = {"input_ids", "labels", "attention_mask"}
    if set(batch) != required:
        raise ValueError("selective-logit batch keys differ from the approved Stage 9A contract")
    input_ids = batch["input_ids"]
    labels = batch["labels"]
    attention_mask = batch["attention_mask"]
    if any(value.ndim != 2 for value in (input_ids, labels, attention_mask)):
        raise ValueError("selective-logit tensors must have batch and sequence dimensions")
    if input_ids.shape != labels.shape or labels.shape != attention_mask.shape:
        raise ValueError("selective-logit input, label, and attention shapes must match")
    if input_ids.shape[0] != 1:
        raise ValueError("selective-logit Stage 9A path supports batch size 1 only")
    if not bool(torch.all(attention_mask == 1)):
        raise ValueError("selective-logit Stage 9A path does not accept padded batch semantics")
    spec = _supervised_suffix_spec([int(value) for value in labels[0].detach().cpu().tolist()])
    positions = torch.arange(
        spec["selected_logit_start"],
        spec["selected_logit_end_inclusive"] + 1,
        device=input_ids.device,
        dtype=torch.long,
    )
    targets = labels[
        :, spec["supervised_label_start"] : spec["supervised_label_end_inclusive"] + 1
    ].contiguous()
    if positions.numel() != targets.numel() or targets.numel() != spec["supervised_token_count"]:
        raise ValueError("selective-logit causal position and target counts differ")
    if bool(torch.any(targets == -100)):
        raise ValueError("selective-logit targets unexpectedly contain an ignored label")
    return positions, targets, spec


def _selective_causal_lm_loss(model, batch):
    """Compute the unchanged causal objective without prefix vocabulary logits."""
    import torch.nn.functional as functional

    positions, targets, spec = _selective_supervision(batch)
    output = model(
        input_ids=batch["input_ids"],
        attention_mask=batch["attention_mask"],
        labels=None,
        logits_to_keep=positions,
    )
    logits = output.logits
    if logits.ndim != 3 or logits.shape[0] != 1:
        raise ValueError("selective-logit model output has unsupported batch semantics")
    if logits.shape[1] != spec["selected_logit_count"]:
        raise ValueError("selective-logit model output position count mismatch")
    if logits.shape[2] <= 0:
        raise ValueError("selective-logit model output has no vocabulary dimension")
    spec = dict(spec)
    spec["logits_dtype"] = str(logits.dtype)
    loss = functional.cross_entropy(
        logits.float().reshape(-1, logits.shape[-1]),
        targets.reshape(-1),
        reduction="mean",
    )
    return loss, spec


def _load_qlora_model(
    *,
    attn_implementation: str = TRAINING_ATTENTION_IMPLEMENTATION,
    gradient_checkpointing_use_reentrant: bool = False,
    restore_frozen_base_io_bf16: bool = False,
):
    import torch
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, BitsAndBytesConfig

    verify_model_artifact(MODEL_ROOT)
    quantization = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ROOT,
        local_files_only=True,
        trust_remote_code=False,
        quantization_config=quantization,
        device_map={"": 0},
        torch_dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
        attn_implementation=attn_implementation,
    )
    devices = {str(parameter.device) for parameter in model.parameters()}
    if not devices or any(not device.startswith("cuda") for device in devices):
        raise RuntimeError(f"QLoRA model contains disallowed non-CUDA parameters: {devices}")
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(
        model,
        use_gradient_checkpointing=True,
        gradient_checkpointing_kwargs={
            "use_reentrant": gradient_checkpointing_use_reentrant
        },
    )
    lora = LoraConfig(
        task_type="CAUSAL_LM",
        r=LORA_RANK,
        lora_alpha=LORA_ALPHA,
        lora_dropout=0.05,
        bias="none",
        target_modules="all-linear",
    )
    model = get_peft_model(model, lora)
    if restore_frozen_base_io_bf16:
        model._havre_frozen_io_dtype_evidence = _restore_frozen_base_io_bf16(model)
    trainable = sum(parameter.numel() for parameter in model.parameters() if parameter.requires_grad)
    if trainable <= 0:
        raise RuntimeError("QLoRA model has no trainable adapter parameters")
    return model, trainable, quantization.to_dict()


def _restore_frozen_base_io_bf16(model) -> dict[str, Any]:
    """Restore frozen embedding/LM-head weights to their manifest BF16 dtype."""
    import torch

    modules = {
        "input_embeddings": model.get_input_embeddings(),
        "output_embeddings": model.get_output_embeddings(),
    }
    records: list[dict[str, Any]] = []
    seen_pointers: set[int] = set()
    total_saved_bytes = 0
    for role, module in modules.items():
        weight = getattr(module, "weight", None)
        if weight is None:
            raise RuntimeError(f"{role} has no weight for BF16 restoration")
        if weight.requires_grad:
            raise RuntimeError(f"{role} is trainable and cannot use frozen-I/O restoration")
        pointer = weight.data_ptr()
        before_dtype = str(weight.dtype)
        if pointer in seen_pointers:
            records.append({
                "role": role,
                "tied_to_prior_weight": True,
                "elements": weight.numel(),
                "before_dtype": before_dtype,
                "after_dtype": str(weight.dtype),
            })
            continue
        seen_pointers.add(pointer)
        if weight.dtype != torch.float32:
            raise RuntimeError(
                f"{role} expected PEFT-prepared FP32 weight, found {weight.dtype}"
            )
        elements = weight.numel()
        weight.data = weight.data.to(dtype=torch.bfloat16)
        if weight.dtype != torch.bfloat16 or weight.requires_grad:
            raise RuntimeError(f"{role} BF16 restoration failed")
        saved_bytes = elements * (torch.float32.itemsize - torch.bfloat16.itemsize)
        total_saved_bytes += saved_bytes
        records.append({
            "role": role,
            "tied_to_prior_weight": False,
            "elements": elements,
            "before_dtype": before_dtype,
            "after_dtype": str(weight.dtype),
            "saved_bytes": saved_bytes,
        })
    return {
        "policy": "restore_only_frozen_base_io_weights_to_exact_manifest_bfloat16_dtype",
        "base_manifest_torch_dtype": "bfloat16",
        "weights": records,
        "total_saved_bytes": total_saved_bytes,
        "total_saved_mib": total_saved_bytes / 1024**2,
        "trainable_parameters_changed": False,
    }


def _model_devices(model) -> dict[str, int]:
    result: dict[str, int] = {}
    for parameter in model.parameters():
        key = str(parameter.device)
        result[key] = result.get(key, 0) + parameter.numel()
    return result


def gate_b_load() -> dict[str, Any]:
    import torch

    if (EVIDENCE_ROOT / GATE_B_EVIDENCE_NAME).exists():
        raise FileExistsError("immutable versioned Gate B evidence already exists")
    require_v4_gate_evidence(EVIDENCE_ROOT / GATE_A_EVIDENCE_NAME, expected_gate="A")
    before = resource_snapshot()
    assert_training_preflight(before)
    monitor = ResourceMonitor().start()
    started = time.perf_counter()
    model = None
    trainable = None
    quantization = None
    devices = None
    failure: Exception | None = None
    try:
        model, trainable, quantization = _load_qlora_model()
        torch.cuda.synchronize()
        monitor.check()
        devices = _model_devices(model)
        if any(not name.startswith("cuda") for name in devices):
            raise RuntimeError(f"Gate B found CPU/disk device placement: {devices}")
        status = "passed"
    except Exception as error:
        status = "failed"
        failure = error
    finally:
        resources = monitor.stop()
    if failure is None and not _resource_evidence_is_within_stage9a_limits(
        resources, peak_target_mib=TARGET_VRAM_MIB
    ):
        status = "failed"
        failure = RuntimeError("Gate B resource evidence is incomplete or outside limits")
    report = {
        "schema_version": 1,
        "gate": "B",
        "status": status,
        "quantization": quantization,
        "attention_implementation": TRAINING_ATTENTION_IMPLEMENTATION,
        "lora": {
            "rank": LORA_RANK,
            "alpha": LORA_ALPHA,
            "dropout": 0.05,
            "target_modules": "all-linear",
        },
        "trainable_parameters": trainable,
        "parameter_devices": devices,
        "cpu_offload": False,
        "disk_offload": False,
        "execution_source_snapshot": current_source_revision(PROJECT_ROOT),
        "intended_dataset_version": DATASET_VERSION,
        "intended_dataset_bundle_hash": dataset_bundle_hash(DATASET_ROOT),
        "dataset_rows_accessed": False,
        "resource_monitor_version": RESOURCE_EVIDENCE_VERSION,
        "supersedes_evidence_hash": APPROVED_GATE_B_V4_HASH,
        "elapsed_seconds": time.perf_counter() - started,
        "resources": resources,
        "completed_at": datetime.now(UTC).isoformat(),
    }
    if failure is not None:
        report["failure"] = {"type": type(failure).__name__, "message": str(failure)}
        write_hashed_json(EVIDENCE_ROOT / GATE_B_EVIDENCE_NAME, report)
        raise failure
    del model
    gc.collect()
    torch.cuda.empty_cache()
    return write_hashed_json(EVIDENCE_ROOT / GATE_B_EVIDENCE_NAME, report)


def _make_loader(split: str, tokenizer, max_seq_length: int, *, seed: int, shuffle: bool):
    import torch
    from torch.utils.data import DataLoader

    dataset = TokenDataset(list(_iter_rendered(split, max_seq_length, tokenizer)))
    generator = torch.Generator()
    generator.manual_seed(seed)
    return DataLoader(
        dataset,
        batch_size=1,
        shuffle=shuffle,
        generator=generator,
        collate_fn=lambda batch: _collate(batch, tokenizer.pad_token_id),
    )


def _training_step(
    model,
    batch,
    optimizer,
    *,
    gradient_accumulation: int = 1,
    progress: dict[str, bool] | None = None,
    step_evidence: dict[str, Any] | None = None,
) -> tuple[float, float]:
    import torch

    batch = {key: value.to("cuda:0", non_blocking=True) for key, value in batch.items()}
    output = model(**batch)
    if progress is not None:
        progress["forward"] = True
    loss = output.loss / gradient_accumulation
    if not torch.isfinite(loss):
        raise RuntimeError("non-finite training loss")
    loss.backward()
    if progress is not None:
        progress["backward"] = True
    gradient_norm = torch.nn.utils.clip_grad_norm_(
        [parameter for parameter in model.parameters() if parameter.requires_grad], 1.0
    )
    if not torch.isfinite(gradient_norm):
        raise RuntimeError("non-finite adapter gradient norm")
    if step_evidence is not None:
        gradients = [
            parameter.grad
            for parameter in model.parameters()
            if parameter.requires_grad and parameter.grad is not None
        ]
        step_evidence.update({
            "gradient_tensor_count": len(gradients),
            "all_gradient_tensors_finite": bool(gradients) and all(
                bool(torch.isfinite(gradient).all()) for gradient in gradients
            ),
        })
    optimizer.step()
    if progress is not None:
        progress["optimizer_step"] = True
    if step_evidence is not None:
        state_tensors = [
            value
            for state in optimizer.state.values()
            for value in state.values()
            if isinstance(value, torch.Tensor)
        ]
        nonscalar_state_tensors = [value for value in state_tensors if value.numel() > 1]
        step_evidence.update({
            "optimizer_state_entries": len(optimizer.state),
            "optimizer_state_tensor_count": len(state_tensors),
            "optimizer_state_tensor_devices": sorted({
                str(value.device) for value in state_tensors
            }),
            "optimizer_nonscalar_state_tensor_devices": sorted({
                str(value.device) for value in nonscalar_state_tensors
            }),
            "optimizer_state_materialized": len(optimizer.state) > 0,
        })
    optimizer.zero_grad(set_to_none=True)
    return float(loss.detach().cpu()) * gradient_accumulation, float(gradient_norm.detach().cpu())


def _selective_training_step(
    model,
    batch,
    optimizer,
    *,
    gradient_accumulation: int = 1,
    progress: dict[str, bool] | None = None,
    step_evidence: dict[str, Any] | None = None,
    use_bf16_autocast: bool = False,
    release_cuda_cache_before_optimizer: bool = False,
) -> tuple[float, float, dict[str, Any]]:
    """Run one optimizer step through the versioned suffix-selective loss path."""
    import torch

    if gradient_accumulation <= 0:
        raise ValueError("gradient accumulation must be positive")
    memory_stages: dict[str, dict[str, float]] = {}

    def record_memory(stage: str) -> None:
        if step_evidence is not None:
            memory_stages[stage] = {
                "allocated_mib": torch.cuda.memory_allocated() / 1024**2,
                "reserved_mib": torch.cuda.memory_reserved() / 1024**2,
            }

    batch = {key: value.to("cuda:0", non_blocking=True) for key, value in batch.items()}
    record_memory("batch_on_device")
    autocast_context = (
        torch.autocast(device_type="cuda", dtype=torch.bfloat16)
        if use_bf16_autocast
        else nullcontext()
    )
    with autocast_context:
        raw_loss, selection = _selective_causal_lm_loss(model, batch)
    selection["bf16_autocast_enabled"] = use_bf16_autocast
    record_memory("after_forward_loss")
    if progress is not None:
        progress["forward"] = True
    loss = raw_loss / gradient_accumulation
    if not torch.isfinite(loss):
        raise RuntimeError("non-finite selective-logit training loss")
    loss.backward()
    record_memory("after_backward")
    if progress is not None:
        progress["backward"] = True
    gradient_norm = torch.nn.utils.clip_grad_norm_(
        [parameter for parameter in model.parameters() if parameter.requires_grad], 1.0
    )
    if not torch.isfinite(gradient_norm):
        raise RuntimeError("non-finite selective-logit adapter gradient norm")
    record_memory("after_gradient_clip")
    if step_evidence is not None:
        gradients = [
            parameter.grad
            for parameter in model.parameters()
            if parameter.requires_grad and parameter.grad is not None
        ]
        step_evidence.update({
            "gradient_tensor_count": len(gradients),
            "all_gradient_tensors_finite": bool(gradients) and all(
                bool(torch.isfinite(gradient).all()) for gradient in gradients
            ),
        })
    if release_cuda_cache_before_optimizer:
        # Backward has released the transient activation graph, but the CUDA
        # caching allocator can retain those inactive blocks through the first
        # AdamW step. Releasing only unoccupied cache blocks changes neither
        # live tensors nor the supervised objective and gives optimizer state
        # an allocator-clean baseline.
        torch.cuda.synchronize()
        record_memory("before_cache_release")
        torch.cuda.empty_cache()
        record_memory("after_cache_release_before_optimizer")
    optimizer.step()
    record_memory("after_optimizer_step")
    if progress is not None:
        progress["optimizer_step"] = True
    if step_evidence is not None:
        state_tensors = [
            value
            for state in optimizer.state.values()
            for value in state.values()
            if isinstance(value, torch.Tensor)
        ]
        nonscalar_state_tensors = [value for value in state_tensors if value.numel() > 1]
        step_evidence.update({
            "optimizer_state_entries": len(optimizer.state),
            "optimizer_state_tensor_count": len(state_tensors),
            "optimizer_state_tensor_devices": sorted({
                str(value.device) for value in state_tensors
            }),
            "optimizer_nonscalar_state_tensor_devices": sorted({
                str(value.device) for value in nonscalar_state_tensors
            }),
            "optimizer_state_materialized": len(optimizer.state) > 0,
        })
    optimizer.zero_grad(set_to_none=True)
    record_memory("after_zero_grad")
    if step_evidence is not None:
        step_evidence["torch_memory_stages"] = memory_stages
    return (
        float(loss.detach().cpu()) * gradient_accumulation,
        float(gradient_norm.detach().cpu()),
        selection,
    )


def _select_longest_probe_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise ValueError("remediation probe has no verified training rows")
    longest = max(rows, key=lambda item: (item["total_token_count"], item["example_id"]))
    if longest["total_token_count"] != REENTRANT_PROBE_LONGEST_TOKENS:
        raise ValueError("remediation probe did not select the approved 321-token maximum")
    return longest


def _verify_reentrant_probe_input(tokenizer) -> tuple[dict[str, Any], dict[str, Any]]:
    """Bind the one-off probe to the frozen pre-remediation rendered artifact."""
    require_dataset_freeze_approval()
    manifest = read_hashed_json(RENDERED_ROOT / "manifest.json")
    if (
        manifest.get("content_hash") != APPROVED_RENDERED_MANIFEST_HASH
        or manifest.get("execution_source_snapshot")
        != APPROVED_PRE_REMEDIATION_SOURCE_SNAPSHOT
        or manifest.get("dataset_bundle_hash") != dataset_bundle_hash(DATASET_ROOT)
        or manifest.get("chosen_max_seq_length") != 336
        or manifest.get("rendered_splits") != list(TRAINING_SPLITS)
        or manifest.get("holdout_rendered") is not False
    ):
        raise ValueError("remediation probe rendered manifest binding mismatch")
    splits = load_and_verify_dataset(DATASET_ROOT)
    source_by_id = {item["example_id"]: item for item in splits["train"]}
    path = RENDERED_ROOT / "train.jsonl"
    if manifest["split_reports"]["train"].get("artifact_sha256") != sha256_file(path):
        raise ValueError("remediation probe train artifact hash mismatch")
    verified: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        claimed = row.pop("content_hash", None)
        example_id = row.get("example_id")
        if not isinstance(claimed, str) or content_hash(row) != claimed:
            raise ValueError(f"remediation probe row hash mismatch: {example_id}")
        if example_id in seen or example_id not in source_by_id:
            raise ValueError(f"remediation probe row membership mismatch: {example_id}")
        if row != _render_example(tokenizer, source_by_id[example_id]):
            raise ValueError(f"remediation probe row projection mismatch: {example_id}")
        seen.add(example_id)
        verified.append(row)
    if seen != set(source_by_id) or len(verified) != SPLIT_COUNTS["train"]:
        raise ValueError("remediation probe train membership is not an exact bijection")
    return manifest, _select_longest_probe_row(verified)


def _verify_selective_probe_input(
    tokenizer,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Verify both immutable training splits before the selective GPU probe."""
    require_dataset_freeze_approval()
    manifest = read_hashed_json(RENDERED_ROOT / "manifest.json")
    if (
        manifest.get("content_hash") != APPROVED_RENDERED_MANIFEST_HASH
        or manifest.get("execution_source_snapshot")
        != APPROVED_PRE_REMEDIATION_SOURCE_SNAPSHOT
        or manifest.get("dataset_bundle_hash") != dataset_bundle_hash(DATASET_ROOT)
        or manifest.get("chosen_max_seq_length") != 336
        or manifest.get("training_batch_size") != 1
        or manifest.get("rendered_splits") != list(TRAINING_SPLITS)
        or manifest.get("holdout_rendered") is not False
        or manifest.get("owner_alignment_set_used") is not False
    ):
        raise ValueError("selective-logit probe rendered manifest binding mismatch")
    splits = load_and_verify_dataset(DATASET_ROOT)
    verified_items: dict[str, list[dict[str, Any]]] = {}
    for split in TRAINING_SPLITS:
        source_by_id = {item["example_id"]: item for item in splits[split]}
        path = RENDERED_ROOT / f"{split}.jsonl"
        report = manifest["split_reports"][split]
        source_manifest = read_hashed_json(
            DATASET_ROOT / f"stage9a_{split}_{ARTIFACT_VERSION}.manifest.json"
        )
        if (
            report.get("artifact_sha256") != sha256_file(path)
            or report.get("source_member_manifest_hash")
            != source_manifest["member_manifest_hash"]
        ):
            raise ValueError(f"selective-logit probe {split} artifact binding mismatch")
        verified: list[dict[str, Any]] = []
        seen: set[str] = set()
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            claimed = row.pop("content_hash", None)
            example_id = row.get("example_id")
            if not isinstance(claimed, str) or content_hash(row) != claimed:
                raise ValueError(f"selective-logit probe row hash mismatch: {example_id}")
            if example_id in seen or example_id not in source_by_id:
                raise ValueError(f"selective-logit probe row membership mismatch: {example_id}")
            if row != _render_example(tokenizer, source_by_id[example_id]):
                raise ValueError(f"selective-logit probe row projection mismatch: {example_id}")
            _supervised_suffix_spec(row["labels"])
            seen.add(example_id)
            verified.append(row)
        if seen != set(source_by_id) or len(verified) != SPLIT_COUNTS[split]:
            raise ValueError(f"selective-logit probe {split} membership is not an exact bijection")
        verified_items[split] = verified
    longest = _select_longest_probe_row(verified_items["train"])
    longest_spec = _supervised_suffix_spec(longest["labels"])
    if (
        longest.get("example_id") != SELECTIVE_PROBE_EXAMPLE_ID
        or longest_spec["supervised_token_count"] != SELECTIVE_PROBE_SUPERVISED_TOKENS
    ):
        raise ValueError("selective-logit probe did not bind the approved longest sample")
    suffix_summary = _summarize_supervised_suffixes(verified_items)
    if (
        suffix_summary["train"]["count"] != SPLIT_COUNTS["train"]
        or suffix_summary["validation"]["count"] != SPLIT_COUNTS["validation"]
    ):
        raise ValueError("selective-logit suffix verification did not cover both training splits")
    return manifest, longest, suffix_summary


def _selective_probe_boundary_worker() -> dict[str, Any]:
    """Verify immutable inputs in a disposable process before model loading."""
    tokenizer = _load_tokenizer()
    manifest, probe_row, suffix_summary = _verify_selective_probe_input(tokenizer)
    return {
        "schema_version": 1,
        "execution_source_snapshot": current_source_revision(PROJECT_ROOT),
        "manifest": manifest,
        "probe_row": probe_row,
        "suffix_summary": suffix_summary,
        "pad_token_id": tokenizer.pad_token_id,
    }


def _load_selective_probe_boundary_in_subprocess(
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], int]:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.stage9a_real_training",
            "selective-boundary-worker",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"selective-logit boundary worker failed: {detail}")
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("selective-logit boundary worker returned no result")
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError as error:
        raise RuntimeError("selective-logit boundary worker returned invalid JSON") from error
    if (
        payload.get("schema_version") != 1
        or payload.get("execution_source_snapshot") != current_source_revision(PROJECT_ROOT)
        or payload.get("manifest", {}).get("content_hash") != APPROVED_RENDERED_MANIFEST_HASH
        or payload.get("probe_row", {}).get("example_id") != SELECTIVE_PROBE_EXAMPLE_ID
        or payload.get("probe_row", {}).get("total_token_count")
        != REENTRANT_PROBE_LONGEST_TOKENS
        or payload.get("probe_row", {}).get("assistant_token_count")
        != SELECTIVE_PROBE_SUPERVISED_TOKENS
        or not isinstance(payload.get("pad_token_id"), int)
    ):
        raise RuntimeError("selective-logit boundary worker result is incomplete or cross-bound")
    _supervised_suffix_spec(payload["probe_row"]["labels"])
    return (
        payload["manifest"],
        payload["probe_row"],
        payload["suffix_summary"],
        payload["pad_token_id"],
    )


def gate_c_reentrant_remediation_probe() -> dict[str, Any]:
    """Run the single PO-authorized longest-sample reentrant feasibility probe."""
    output_path = EVIDENCE_ROOT / REENTRANT_PROBE_EVIDENCE_NAME
    if output_path.exists():
        raise FileExistsError("immutable reentrant remediation probe evidence already exists")
    import torch

    original = read_hashed_json(EVIDENCE_ROOT / GATE_C_EVIDENCE_NAME)
    if (
        original.get("content_hash") != ORIGINAL_GATE_C_V4_FAILURE_HASH
        or original.get("status") != "failed"
        or original.get("failure", {}).get("message") != "vram_above_11_5_gib"
    ):
        raise RuntimeError("original Gate C failure evidence is missing or changed")
    gate_b = read_hashed_json(EVIDENCE_ROOT / GATE_B_EVIDENCE_NAME)
    if (
        gate_b.get("content_hash") != APPROVED_GATE_B_V4_HASH
        or gate_b.get("status") != "passed"
        or gate_b.get("execution_source_snapshot")
        != APPROVED_PRE_REMEDIATION_SOURCE_SNAPSHOT
        or gate_b.get("intended_dataset_bundle_hash") != dataset_bundle_hash(DATASET_ROOT)
        or gate_b.get("cpu_offload") is not False
        or gate_b.get("disk_offload") is not False
    ):
        raise RuntimeError("remediation probe Gate B evidence is missing or cross-bound")
    tokenizer = _load_tokenizer()
    manifest, probe_row = _verify_reentrant_probe_input(tokenizer)
    before = resource_snapshot()
    assert_training_preflight(before)
    monitor = ResourceMonitor().start()
    started = time.perf_counter()
    model = None
    optimizer = None
    trainable = None
    model_devices = None
    loss = None
    gradient_norm = None
    step_evidence: dict[str, Any] = {}
    progress = {"forward": False, "backward": False, "optimizer_step": False}
    failure: Exception | None = None
    torch_peak_allocated_mib = 0.0
    torch_peak_reserved_mib = 0.0
    try:
        model, trainable, _ = _load_qlora_model(
            gradient_checkpointing_use_reentrant=True,
        )
        model_devices = _model_devices(model)
        if any(not name.startswith("cuda") for name in model_devices):
            raise RuntimeError(f"remediation probe found non-GPU model placement: {model_devices}")
        optimizer = torch.optim.AdamW(
            [parameter for parameter in model.parameters() if parameter.requires_grad],
            lr=2e-4,
            weight_decay=0.0,
        )
        batch = _collate(
            [{"input_ids": probe_row["input_ids"], "labels": probe_row["labels"]}],
            tokenizer.pad_token_id,
        )
        torch.cuda.reset_peak_memory_stats()
        loss, gradient_norm = _training_step(
            model,
            batch,
            optimizer,
            progress=progress,
            step_evidence=step_evidence,
        )
        torch.cuda.synchronize()
        torch_peak_allocated_mib = torch.cuda.max_memory_allocated() / 1024**2
        torch_peak_reserved_mib = torch.cuda.max_memory_reserved() / 1024**2
        monitor.check()
    except Exception as error:
        failure = error
        if torch.cuda.is_available():
            torch_peak_allocated_mib = torch.cuda.max_memory_allocated() / 1024**2
            torch_peak_reserved_mib = torch.cuda.max_memory_reserved() / 1024**2
    finally:
        resources = monitor.stop()
    observed_peak_vram_mib = max(
        float(resources["maximum"]["vram_used_mib"]),
        torch_peak_allocated_mib,
        torch_peak_reserved_mib,
    )
    shared_growth_mib = (
        resources["maximum"]["shared_gpu_mib"] - resources["baseline"]["shared_gpu_mib"]
    )
    swap_growth_mib = (
        resources["maximum"]["swap_used_mib"] - resources["baseline"]["swap_used_mib"]
    )
    if failure is None and observed_peak_vram_mib > TARGET_VRAM_MIB:
        failure = RuntimeError("reentrant_probe_peak_vram_above_11_0_gib")
    if failure is None and shared_growth_mib > MAX_SHARED_GPU_GROWTH_MIB:
        failure = RuntimeError("reentrant_probe_shared_gpu_spill")
    if failure is None and swap_growth_mib > MAX_SWAP_GROWTH_MIB:
        failure = RuntimeError("reentrant_probe_material_swap_growth")
    if failure is None and (
        not step_evidence.get("optimizer_state_materialized")
        or not step_evidence.get("all_gradient_tensors_finite")
        or any(
            not device.startswith("cuda")
            for device in step_evidence.get("optimizer_nonscalar_state_tensor_devices", [])
        )
    ):
        failure = RuntimeError("reentrant_probe_step_evidence_incomplete_or_offloaded")
    status = "passed" if failure is None else "failed"
    report = {
        "schema_version": 1,
        "probe": "stage9a-v4-gate-c-reentrant-remediation-probe-1",
        "status": status,
        "candidate_only": True,
        "formal_training": False,
        "gate_d_authorized": False,
        "promotion_authorized": False,
        "deployment_authorized": False,
        "original_gate_c_failure_hash": original["content_hash"],
        "gate_b_evidence_hash": gate_b["content_hash"],
        "dataset_version": DATASET_VERSION,
        "dataset_bundle_hash": dataset_bundle_hash(DATASET_ROOT),
        "rendered_manifest_hash": manifest["content_hash"],
        "rendered_max_seq_length": manifest["chosen_max_seq_length"],
        "sample_id": probe_row["example_id"],
        "sample_token_length": probe_row["total_token_count"],
        "configuration_delta": {
            "only_change": "gradient_checkpointing_use_reentrant",
            "before": False,
            "probe": True,
        },
        "unchanged_training_configuration": {
            "base_repository": load_model_manifest()["repository"],
            "base_revision": load_model_manifest()["revision"],
            "quantization": "nf4_double_quant_bf16_compute",
            "attention_implementation": TRAINING_ATTENTION_IMPLEMENTATION,
            "lora_rank": LORA_RANK,
            "lora_alpha": LORA_ALPHA,
            "lora_dropout": 0.05,
            "lora_target_modules": "all-linear",
            "optimizer": "torch.optim.AdamW_no_paging",
            "learning_rate": 2e-4,
            "weight_decay": 0.0,
            "batch_size": 1,
        },
        "execution_source_snapshot": current_source_revision(PROJECT_ROOT),
        "model_parameter_devices": model_devices,
        "trainable_parameters": trainable,
        "real_forward": progress["forward"],
        "real_backward": progress["backward"],
        "real_optimizer_step": progress["optimizer_step"],
        "loss": loss,
        "gradient_norm": gradient_norm,
        **step_evidence,
        "target_peak_vram_mib": TARGET_VRAM_MIB,
        "observed_peak_vram_mib": observed_peak_vram_mib,
        "nvidia_smi_peak_vram_mib": resources["maximum"]["vram_used_mib"],
        "torch_peak_allocated_mib": torch_peak_allocated_mib,
        "torch_peak_reserved_mib": torch_peak_reserved_mib,
        "shared_gpu_growth_mib": shared_growth_mib,
        "swap_growth_mib": swap_growth_mib,
        "cpu_offload": False,
        "disk_offload": False,
        "resources": resources,
        "elapsed_seconds": time.perf_counter() - started,
        "completed_at": datetime.now(UTC).isoformat(),
    }
    if failure is not None:
        report["failure"] = {"type": type(failure).__name__, "message": str(failure)}
    written = write_hashed_json(output_path, report)
    del model, optimizer
    gc.collect()
    torch.cuda.empty_cache()
    if failure is not None:
        raise failure
    return written


def gate_c_selective_logits_remediation_probe() -> dict[str, Any]:
    """Run the one PO-authorized suffix-selective longest-sample GPU probe."""
    output_path = EVIDENCE_ROOT / SELECTIVE_LOGITS_PROBE_EVIDENCE_NAME
    if output_path.exists():
        raise FileExistsError("immutable selective-logits remediation probe evidence already exists")
    import torch

    original = read_hashed_json(EVIDENCE_ROOT / GATE_C_EVIDENCE_NAME)
    if (
        original.get("content_hash") != ORIGINAL_GATE_C_V4_FAILURE_HASH
        or original.get("status") != "failed"
        or original.get("failure", {}).get("message") != "vram_above_11_5_gib"
    ):
        raise RuntimeError("original Gate C failure evidence is missing or changed")
    reentrant = read_hashed_json(EVIDENCE_ROOT / REENTRANT_PROBE_EVIDENCE_NAME)
    if (
        reentrant.get("content_hash") != REENTRANT_PROBE_FAILURE_HASH
        or reentrant.get("status") != "failed"
        or reentrant.get("sample_id") != SELECTIVE_PROBE_EXAMPLE_ID
        or reentrant.get("sample_token_length") != REENTRANT_PROBE_LONGEST_TOKENS
        or reentrant.get("configuration_delta", {}).get("probe") is not True
        or reentrant.get("unchanged_training_configuration", {}).get(
            "attention_implementation"
        )
        != TRAINING_ATTENTION_IMPLEMENTATION
    ):
        raise RuntimeError("reentrant remediation evidence is missing or changed")
    gate_b = read_hashed_json(EVIDENCE_ROOT / GATE_B_EVIDENCE_NAME)
    if (
        gate_b.get("content_hash") != APPROVED_GATE_B_V4_HASH
        or gate_b.get("status") != "passed"
        or gate_b.get("execution_source_snapshot")
        != APPROVED_PRE_REMEDIATION_SOURCE_SNAPSHOT
        or gate_b.get("intended_dataset_bundle_hash") != dataset_bundle_hash(DATASET_ROOT)
        or gate_b.get("cpu_offload") is not False
        or gate_b.get("disk_offload") is not False
    ):
        raise RuntimeError("selective-logit probe Gate B evidence is missing or cross-bound")

    manifest, probe_row, suffix_summary, pad_token_id = (
        _load_selective_probe_boundary_in_subprocess()
    )
    before = resource_snapshot()
    assert_training_preflight(before)
    monitor = ResourceMonitor(interval_seconds=1.0).start()
    started = time.perf_counter()
    model = None
    optimizer = None
    trainable = None
    model_devices = None
    loss = None
    gradient_norm = None
    selection: dict[str, int] | None = None
    step_evidence: dict[str, Any] = {}
    progress = {"forward": False, "backward": False, "optimizer_step": False}
    failure: Exception | None = None
    torch_peak_allocated_mib = 0.0
    torch_peak_reserved_mib = 0.0
    try:
        model, trainable, _ = _load_qlora_model(
            attn_implementation=TRAINING_ATTENTION_IMPLEMENTATION,
            gradient_checkpointing_use_reentrant=True,
        )
        model_devices = _model_devices(model)
        if any(not name.startswith("cuda") for name in model_devices):
            raise RuntimeError(f"selective-logit probe found non-GPU model placement: {model_devices}")
        optimizer = torch.optim.AdamW(
            [parameter for parameter in model.parameters() if parameter.requires_grad],
            lr=2e-4,
            weight_decay=0.0,
        )
        batch = _collate(
            [{"input_ids": probe_row["input_ids"], "labels": probe_row["labels"]}],
            pad_token_id,
        )
        torch.cuda.reset_peak_memory_stats()
        loss, gradient_norm, selection = _selective_training_step(
            model,
            batch,
            optimizer,
            progress=progress,
            step_evidence=step_evidence,
        )
        torch.cuda.synchronize()
        torch_peak_allocated_mib = torch.cuda.max_memory_allocated() / 1024**2
        torch_peak_reserved_mib = torch.cuda.max_memory_reserved() / 1024**2
        monitor.samples.append(resource_snapshot())
        monitor.check()
    except Exception as error:
        failure = error
        if torch.cuda.is_available():
            torch_peak_allocated_mib = torch.cuda.max_memory_allocated() / 1024**2
            torch_peak_reserved_mib = torch.cuda.max_memory_reserved() / 1024**2
    finally:
        resources = monitor.stop()

    nvidia_peak_vram_mib = float(resources["maximum"]["vram_used_mib"])
    shared_growth_mib = max(
        0.0,
        resources["maximum"]["shared_gpu_mib"] - resources["baseline"]["shared_gpu_mib"],
    )
    swap_growth_mib = max(
        0.0,
        resources["maximum"]["swap_used_mib"] - resources["baseline"]["swap_used_mib"],
    )
    if failure is None and nvidia_peak_vram_mib > TARGET_VRAM_MIB:
        failure = RuntimeError("selective_logits_probe_peak_vram_above_11_0_gib")
    if failure is None and shared_growth_mib > MAX_SHARED_GPU_GROWTH_MIB:
        failure = RuntimeError("selective_logits_probe_shared_gpu_spill")
    if failure is None and swap_growth_mib > MAX_SWAP_GROWTH_MIB:
        failure = RuntimeError("selective_logits_probe_material_swap_growth")
    if failure is None and (
        selection is None
        or selection.get("selected_logit_start") != 286
        or selection.get("selected_logit_end_inclusive") != 319
        or selection.get("selected_logit_count") != SELECTIVE_PROBE_SUPERVISED_TOKENS
        or selection.get("supervised_label_start") != 287
        or selection.get("supervised_label_end_inclusive") != 320
    ):
        failure = RuntimeError("selective_logits_probe_position_contract_mismatch")
    if failure is None and (
        not step_evidence.get("optimizer_state_materialized")
        or not step_evidence.get("all_gradient_tensors_finite")
        or any(
            not device.startswith("cuda")
            for device in step_evidence.get("optimizer_nonscalar_state_tensor_devices", [])
        )
    ):
        failure = RuntimeError("selective_logits_probe_step_evidence_incomplete_or_offloaded")

    status = "passed" if failure is None else "failed"
    report = {
        "schema_version": 1,
        "probe": "stage9a-v4-selective-logits-remediation-probe-1",
        "loss_path_version": SELECTIVE_LOGITS_LOSS_VERSION,
        "status": status,
        "candidate_only": True,
        "formal_training": False,
        "gate_d_authorized": False,
        "promotion_authorized": False,
        "deployment_authorized": False,
        "original_gate_c_failure_hash": original["content_hash"],
        "reentrant_probe_failure_hash": reentrant["content_hash"],
        "gate_b_evidence_hash": gate_b["content_hash"],
        "dataset_version": DATASET_VERSION,
        "dataset_bundle_hash": dataset_bundle_hash(DATASET_ROOT),
        "rendered_manifest_hash": manifest["content_hash"],
        "rendered_max_seq_length": manifest["chosen_max_seq_length"],
        "sample_id": probe_row["example_id"],
        "sample_token_length": probe_row["total_token_count"],
        "supervised_suffix_token_count": probe_row["assistant_token_count"],
        "selected_supervision": selection,
        "suffix_contract_summary": suffix_summary,
        "configuration_delta": {
            "only_change": "masked_prefix_vocabulary_logits_omitted_with_exact_shifted_suffix_loss",
            "baseline_evidence_hash": reentrant["content_hash"],
            "before": {
                "gradient_checkpointing_use_reentrant": True,
                "loss_path": "qwen3_full_sequence_logits_and_transformers_causal_lm_loss",
            },
            "probe": {
                "gradient_checkpointing_use_reentrant": True,
                "loss_path": SELECTIVE_LOGITS_LOSS_VERSION,
            },
        },
        "unchanged_training_configuration": {
            "base_repository": load_model_manifest()["repository"],
            "base_revision": load_model_manifest()["revision"],
            "quantization": "nf4_double_quant_bf16_compute",
            "attention_implementation": TRAINING_ATTENTION_IMPLEMENTATION,
            "gradient_checkpointing_use_reentrant": True,
            "lora_rank": LORA_RANK,
            "lora_alpha": LORA_ALPHA,
            "lora_dropout": 0.05,
            "lora_target_modules": "all-linear",
            "optimizer": "torch.optim.AdamW_no_paging",
            "learning_rate": 2e-4,
            "weight_decay": 0.0,
            "batch_size": 1,
            "max_seq_length": 336,
            "loss_reduction": "mean_over_supervised_target_tokens",
        },
        "execution_source_snapshot": current_source_revision(PROJECT_ROOT),
        "model_parameter_devices": model_devices,
        "trainable_parameters": trainable,
        "real_forward": progress["forward"],
        "real_backward": progress["backward"],
        "real_optimizer_step": progress["optimizer_step"],
        "loss": loss,
        "gradient_norm": gradient_norm,
        **step_evidence,
        "target_peak_vram_mib": TARGET_VRAM_MIB,
        "observed_peak_vram_mib": nvidia_peak_vram_mib,
        "nvidia_smi_peak_vram_mib": nvidia_peak_vram_mib,
        "torch_peak_allocated_mib": torch_peak_allocated_mib,
        "torch_peak_reserved_mib": torch_peak_reserved_mib,
        "shared_gpu_growth_mib": shared_growth_mib,
        "swap_growth_mib": swap_growth_mib,
        "cpu_offload": False,
        "disk_offload": False,
        "resources": resources,
        "elapsed_seconds": time.perf_counter() - started,
        "completed_at": datetime.now(UTC).isoformat(),
    }
    if failure is not None:
        report["failure"] = {"type": type(failure).__name__, "message": str(failure)}
    written = write_hashed_json(output_path, report)
    del model, optimizer
    gc.collect()
    torch.cuda.empty_cache()
    if failure is not None:
        raise failure
    return written


def gate_c_nonreentrant_selective_remediation_probe(
    *,
    output_name: str = NONREENTRANT_SELECTIVE_PROBE_EVIDENCE_NAME,
    prior_evidence_name: str = SELECTIVE_LOGITS_PROBE_EVIDENCE_NAME,
    expected_prior_hash: str = SELECTIVE_LOGITS_PROBE_FAILURE_HASH,
    expected_prior_reentrant: bool = True,
    expected_prior_failure_message: str | None = "vram_above_11_5_gib",
    probe_id: str = "stage9a-v4-nonreentrant-selective-remediation-probe-1",
    use_bf16_autocast: bool = False,
    restore_frozen_base_io_bf16: bool = False,
    prior_already_restored_io: bool = False,
    release_cuda_cache_before_optimizer: bool = False,
    expected_prior_status: str = "failed",
    evidence_gate: str | None = None,
    configuration_delta_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Test selective loss with the original non-reentrant checkpoint engine."""
    output_path = EVIDENCE_ROOT / output_name
    if output_path.exists():
        raise FileExistsError(
            "immutable non-reentrant selective remediation probe evidence already exists"
        )
    import torch

    prior = read_hashed_json(EVIDENCE_ROOT / prior_evidence_name)
    prior_reentrant_matches = (
        prior.get("unchanged_training_configuration", {}).get(
            "gradient_checkpointing_use_reentrant"
        )
        is True
        if expected_prior_reentrant
        else (
            prior.get("configuration_delta", {}).get("probe") is False
            or prior.get("configuration_delta", {}).get(
                "gradient_checkpointing_use_reentrant_unchanged"
            )
            is False
        )
    )
    if (
        prior.get("content_hash") != expected_prior_hash
        or prior.get("status") != expected_prior_status
        or prior.get("loss_path_version") != SELECTIVE_LOGITS_LOSS_VERSION
        or prior.get("sample_id") != SELECTIVE_PROBE_EXAMPLE_ID
        or not prior_reentrant_matches
        or (
            expected_prior_failure_message is not None
            and prior.get("failure", {}).get("message")
            != expected_prior_failure_message
        )
    ):
        raise RuntimeError("selective-logits failure evidence is missing or changed")
    gate_b = read_hashed_json(EVIDENCE_ROOT / GATE_B_EVIDENCE_NAME)
    gate_b_hash_is_valid = (
        gate_b.get("content_hash") == APPROVED_GATE_B_V4_HASH
        if evidence_gate is None
        else gate_b.get("execution_source_snapshot")
        == current_source_revision(PROJECT_ROOT)
    )
    if (
        not gate_b_hash_is_valid
        or gate_b.get("status") != "passed"
        or gate_b.get("cpu_offload") is not False
        or gate_b.get("disk_offload") is not False
        or gate_b.get("resources", {}).get("resource_monitor_version")
        != RESOURCE_EVIDENCE_VERSION
    ):
        raise RuntimeError("non-reentrant selective probe Gate B evidence is invalid")
    manifest, probe_row, suffix_summary, pad_token_id = (
        _load_selective_probe_boundary_in_subprocess()
    )
    before = resource_snapshot()
    assert_training_preflight(before)
    monitor = ResourceMonitor(interval_seconds=1.0).start()
    started = time.perf_counter()
    model = None
    optimizer = None
    trainable = None
    model_devices = None
    loss = None
    gradient_norm = None
    selection: dict[str, int] | None = None
    step_evidence: dict[str, Any] = {}
    progress = {"forward": False, "backward": False, "optimizer_step": False}
    failure: Exception | None = None
    torch_peak_allocated_mib = 0.0
    torch_peak_reserved_mib = 0.0
    try:
        model, trainable, _ = _load_qlora_model(
            attn_implementation=TRAINING_ATTENTION_IMPLEMENTATION,
            gradient_checkpointing_use_reentrant=False,
            restore_frozen_base_io_bf16=restore_frozen_base_io_bf16,
        )
        model_devices = _model_devices(model)
        if any(not name.startswith("cuda") for name in model_devices):
            raise RuntimeError(
                f"non-reentrant selective probe found non-GPU model placement: {model_devices}"
            )
        optimizer = torch.optim.AdamW(
            [parameter for parameter in model.parameters() if parameter.requires_grad],
            lr=2e-4,
            weight_decay=0.0,
        )
        batch = _collate(
            [{"input_ids": probe_row["input_ids"], "labels": probe_row["labels"]}],
            pad_token_id,
        )
        torch.cuda.reset_peak_memory_stats()
        loss, gradient_norm, selection = _selective_training_step(
            model,
            batch,
            optimizer,
            progress=progress,
            step_evidence=step_evidence,
            use_bf16_autocast=use_bf16_autocast,
            release_cuda_cache_before_optimizer=release_cuda_cache_before_optimizer,
        )
        torch.cuda.synchronize()
        torch_peak_allocated_mib = torch.cuda.max_memory_allocated() / 1024**2
        torch_peak_reserved_mib = torch.cuda.max_memory_reserved() / 1024**2
        monitor.samples.append(resource_snapshot())
        monitor.check()
    except Exception as error:
        failure = error
        if torch.cuda.is_available():
            torch_peak_allocated_mib = torch.cuda.max_memory_allocated() / 1024**2
            torch_peak_reserved_mib = torch.cuda.max_memory_reserved() / 1024**2
    finally:
        resources = monitor.stop()
    nvidia_peak_vram_mib = float(resources["maximum"]["vram_used_mib"])
    shared_growth_mib = max(
        0.0,
        resources["maximum"]["shared_gpu_mib"] - resources["baseline"]["shared_gpu_mib"],
    )
    swap_growth_mib = max(
        0.0,
        resources["maximum"]["swap_used_mib"] - resources["baseline"]["swap_used_mib"],
    )
    if failure is None and nvidia_peak_vram_mib > TARGET_VRAM_MIB:
        failure = RuntimeError("nonreentrant_selective_peak_vram_above_11_0_gib")
    if failure is None and shared_growth_mib > MAX_SHARED_GPU_GROWTH_MIB:
        failure = RuntimeError("nonreentrant_selective_shared_gpu_spill")
    if failure is None and swap_growth_mib > MAX_SWAP_GROWTH_MIB:
        failure = RuntimeError("nonreentrant_selective_material_swap_growth")
    if failure is None and (
        selection is None
        or selection.get("selected_logit_start") != 286
        or selection.get("selected_logit_end_inclusive") != 319
        or selection.get("selected_logit_count") != SELECTIVE_PROBE_SUPERVISED_TOKENS
    ):
        failure = RuntimeError("nonreentrant_selective_position_contract_mismatch")
    if failure is None and (
        not step_evidence.get("optimizer_state_materialized")
        or not step_evidence.get("all_gradient_tensors_finite")
        or any(
            not device.startswith("cuda")
            for device in step_evidence.get("optimizer_nonscalar_state_tensor_devices", [])
        )
    ):
        failure = RuntimeError("nonreentrant_selective_step_evidence_incomplete_or_offloaded")
    report = {
        "schema_version": 1,
        "probe": probe_id,
        "gate": evidence_gate,
        "implementation_version": TRAINING_IMPLEMENTATION_VERSION,
        "loss_path_version": SELECTIVE_LOGITS_LOSS_VERSION,
        "status": "passed" if failure is None else "failed",
        "candidate_only": True,
        "formal_training": False,
        "gate_d_authorized": failure is None and evidence_gate == "C",
        "promotion_authorized": False,
        "deployment_authorized": False,
        "prior_evidence_hash": prior["content_hash"],
        "prior_probe_failure_hash": (
            prior["content_hash"] if expected_prior_status == "failed" else None
        ),
        "gate_b_evidence_hash": gate_b["content_hash"],
        "dataset_version": DATASET_VERSION,
        "dataset_bundle_hash": dataset_bundle_hash(DATASET_ROOT),
        "rendered_manifest_hash": manifest["content_hash"],
        "rendered_max_seq_length": manifest["chosen_max_seq_length"],
        "sample_id": probe_row["example_id"],
        "sample_token_length": probe_row["total_token_count"],
        "supervised_suffix_token_count": probe_row["assistant_token_count"],
        "selected_supervision": selection,
        "suffix_contract_summary": suffix_summary,
        "configuration_delta": configuration_delta_override or (
            {
                "only_change_from_prior_probe": (
                    "release_unoccupied_cuda_allocator_cache_between_"
                    "backward_and_optimizer"
                ),
                "baseline_evidence_hash": prior["content_hash"],
                "before": False,
                "probe": True,
                "gradient_checkpointing_use_reentrant_unchanged": False,
                "frozen_base_io_bf16_unchanged": True,
                "torch_bf16_autocast_unchanged": True,
                "selective_loss_unchanged": True,
            }
            if release_cuda_cache_before_optimizer
            else
            {
                "only_change_from_prior_probe": "frozen_base_io_runtime_dtype",
                "baseline_evidence_hash": prior["content_hash"],
                "before": "torch.float32_from_generic_peft_kbit_preparation",
                "probe": "torch.bfloat16_exact_base_manifest_dtype",
                "gradient_checkpointing_use_reentrant_unchanged": False,
                "selective_loss_unchanged": True,
            }
            if restore_frozen_base_io_bf16 and not prior_already_restored_io
            else {
                "only_change_from_prior_probe": "torch_bf16_autocast",
                "baseline_evidence_hash": prior["content_hash"],
                "before": False,
                "probe": True,
                "gradient_checkpointing_use_reentrant_unchanged": False,
                "frozen_base_io_bf16_unchanged": True,
                "selective_loss_unchanged": True,
            }
            if restore_frozen_base_io_bf16 and prior_already_restored_io
            else
            {
                "only_change_from_prior_probe": "torch_bf16_autocast",
                "baseline_evidence_hash": prior["content_hash"],
                "before": False,
                "probe": True,
                "gradient_checkpointing_use_reentrant_unchanged": False,
                "selective_loss_unchanged": True,
            }
            if use_bf16_autocast
            else {
                "only_change_from_prior_probe": "gradient_checkpointing_use_reentrant",
                "baseline_evidence_hash": prior["content_hash"],
                "before": True,
                "probe": False,
                "selective_loss_unchanged": True,
            }
        ),
        "unchanged_training_configuration": {
            "base_repository": load_model_manifest()["repository"],
            "base_revision": load_model_manifest()["revision"],
            "quantization": "nf4_double_quant_bf16_compute",
            "attention_implementation": TRAINING_ATTENTION_IMPLEMENTATION,
            "lora_rank": LORA_RANK,
            "lora_alpha": LORA_ALPHA,
            "lora_dropout": 0.05,
            "lora_target_modules": "all-linear",
            "optimizer": "torch.optim.AdamW_no_paging",
            "learning_rate": 2e-4,
            "weight_decay": 0.0,
            "batch_size": 1,
            "max_seq_length": 336,
            "loss_reduction": "mean_over_supervised_target_tokens",
            "bf16_autocast": use_bf16_autocast,
            "frozen_base_io_bf16_restored": restore_frozen_base_io_bf16,
            "release_cuda_cache_before_optimizer": (
                release_cuda_cache_before_optimizer
            ),
        },
        "frozen_base_io_dtype_evidence": (
            getattr(model, "_havre_frozen_io_dtype_evidence", None)
            if model is not None
            else None
        ),
        "execution_source_snapshot": current_source_revision(PROJECT_ROOT),
        "model_parameter_devices": model_devices,
        "trainable_parameters": trainable,
        "real_forward": progress["forward"],
        "real_backward": progress["backward"],
        "real_optimizer_step": progress["optimizer_step"],
        "loss": loss,
        "gradient_norm": gradient_norm,
        **step_evidence,
        "target_peak_vram_mib": TARGET_VRAM_MIB,
        "observed_peak_vram_mib": nvidia_peak_vram_mib,
        "nvidia_smi_peak_vram_mib": nvidia_peak_vram_mib,
        "torch_peak_allocated_mib": torch_peak_allocated_mib,
        "torch_peak_reserved_mib": torch_peak_reserved_mib,
        "shared_gpu_growth_mib": shared_growth_mib,
        "swap_growth_mib": swap_growth_mib,
        "cpu_offload": False,
        "disk_offload": False,
        "resources": resources,
        "elapsed_seconds": time.perf_counter() - started,
        "completed_at": datetime.now(UTC).isoformat(),
    }
    if failure is not None:
        report["failure"] = {"type": type(failure).__name__, "message": str(failure)}
    written = write_hashed_json(output_path, report)
    del model, optimizer
    gc.collect()
    torch.cuda.empty_cache()
    if failure is not None:
        raise failure
    return written


def gate_c_bf16_autocast_selective_remediation_probe() -> dict[str, Any]:
    """Test standard BF16 autocast with the verified selective objective."""
    return gate_c_nonreentrant_selective_remediation_probe(
        output_name=BF16_AUTOCAST_SELECTIVE_PROBE_EVIDENCE_NAME,
        prior_evidence_name=NONREENTRANT_SELECTIVE_PROBE_EVIDENCE_NAME,
        expected_prior_hash=NONREENTRANT_SELECTIVE_PROBE_FAILURE_HASH,
        expected_prior_reentrant=False,
        probe_id="stage9a-v4-bf16-autocast-selective-remediation-probe-1",
        use_bf16_autocast=True,
    )


def gate_c_frozen_io_bf16_selective_remediation_probe() -> dict[str, Any]:
    """Restore only frozen base I/O weights to the pinned base BF16 dtype."""
    return gate_c_nonreentrant_selective_remediation_probe(
        output_name=FROZEN_IO_BF16_SELECTIVE_PROBE_EVIDENCE_NAME,
        prior_evidence_name=NONREENTRANT_SELECTIVE_PROBE_EVIDENCE_NAME,
        expected_prior_hash=NONREENTRANT_SELECTIVE_PROBE_FAILURE_HASH,
        expected_prior_reentrant=False,
        probe_id="stage9a-v4-frozen-io-bf16-selective-remediation-probe-1",
        use_bf16_autocast=False,
        restore_frozen_base_io_bf16=True,
    )


def gate_c_frozen_io_bf16_autocast_remediation_probe() -> dict[str, Any]:
    """Combine exact BF16 base I/O restoration with BF16 compute autocast."""
    return gate_c_nonreentrant_selective_remediation_probe(
        output_name=FROZEN_IO_BF16_AUTOCAST_PROBE_EVIDENCE_NAME,
        prior_evidence_name=FROZEN_IO_BF16_SELECTIVE_PROBE_EVIDENCE_NAME,
        expected_prior_hash=FROZEN_IO_BF16_PROBE_FAILURE_HASH,
        expected_prior_reentrant=False,
        expected_prior_failure_message=(
            "expected mat1 and mat2 to have the same dtype, but got: "
            "float != struct c10::BFloat16"
        ),
        probe_id="stage9a-v4-frozen-io-bf16-autocast-selective-probe-1",
        use_bf16_autocast=True,
        restore_frozen_base_io_bf16=True,
        prior_already_restored_io=True,
    )


def gate_c_frozen_io_bf16_autocast_cache_trim_remediation_probe() -> dict[str, Any]:
    """Release only inactive allocator cache before the first AdamW step."""
    return gate_c_nonreentrant_selective_remediation_probe(
        output_name=FROZEN_IO_BF16_AUTOCAST_CACHE_TRIM_PROBE_EVIDENCE_NAME,
        prior_evidence_name=FROZEN_IO_BF16_AUTOCAST_PROBE_EVIDENCE_NAME,
        expected_prior_hash=FROZEN_IO_BF16_AUTOCAST_PROBE_FAILURE_HASH,
        expected_prior_reentrant=False,
        expected_prior_failure_message=(
            "nonreentrant_selective_peak_vram_above_11_0_gib"
        ),
        probe_id=(
            "stage9a-v4-frozen-io-bf16-autocast-cache-trim-"
            "selective-probe-1"
        ),
        use_bf16_autocast=True,
        restore_frozen_base_io_bf16=True,
        prior_already_restored_io=True,
        release_cuda_cache_before_optimizer=True,
    )


def gate_c_remediated_training_step() -> dict[str, Any]:
    """Re-run Gate C through the independently reviewed v4 training path."""
    return gate_c_nonreentrant_selective_remediation_probe(
        output_name=REMEDIATED_GATE_C_EVIDENCE_NAME,
        prior_evidence_name=FROZEN_IO_BF16_AUTOCAST_CACHE_TRIM_PROBE_EVIDENCE_NAME,
        expected_prior_hash=APPROVED_CACHE_TRIM_PROBE_HASH,
        expected_prior_reentrant=False,
        expected_prior_failure_message=None,
        expected_prior_status="passed",
        evidence_gate="C",
        configuration_delta_override={
            "change_from_reviewed_remediation": "none",
            "purpose": "formal_gate_c_execution_of_reviewed_implementation",
            "baseline_evidence_hash": APPROVED_CACHE_TRIM_PROBE_HASH,
            "supersedes_resource_evidence_hash": SUPERSEDED_GATE_C_V4_HASH,
            "resource_monitor_version": RESOURCE_EVIDENCE_VERSION,
            "objective_unchanged": True,
            "dataset_unchanged": True,
            "model_and_lora_unchanged": True,
            "optimizer_unchanged": True,
            "resource_thresholds_unchanged": True,
        },
        probe_id="stage9a-v4-remediated-formal-gate-c-v1",
        use_bf16_autocast=True,
        restore_frozen_base_io_bf16=True,
        prior_already_restored_io=True,
        release_cuda_cache_before_optimizer=True,
    )


def gate_c_training_step() -> dict[str, Any]:
    import torch

    if (EVIDENCE_ROOT / GATE_C_EVIDENCE_NAME).exists():
        raise FileExistsError("immutable original Gate C evidence already exists")
    require_dataset_freeze_approval()
    require_v4_gate_evidence(EVIDENCE_ROOT / GATE_B_EVIDENCE_NAME, expected_gate="B")
    manifest = read_hashed_json(RENDERED_ROOT / "manifest.json")
    max_seq_length = manifest["chosen_max_seq_length"]
    tokenizer = _load_tokenizer()
    before = resource_snapshot()
    assert_training_preflight(before)
    monitor = ResourceMonitor().start()
    started = time.perf_counter()
    model = None
    optimizer = None
    trainable = None
    loss = None
    gradient_norm = None
    optimizer_state_entries = 0
    progress = {"forward": False, "backward": False, "optimizer_step": False}
    failure: Exception | None = None
    try:
        model, trainable, _ = _load_qlora_model()
        torch.cuda.reset_peak_memory_stats()
        optimizer = torch.optim.AdamW(
            [parameter for parameter in model.parameters() if parameter.requires_grad],
            lr=2e-4,
            weight_decay=0.0,
        )
        loader = _make_loader("train", tokenizer, max_seq_length, seed=901, shuffle=False)
        loss, gradient_norm = _training_step(
            model,
            next(iter(loader)),
            optimizer,
            progress=progress,
        )
        torch.cuda.synchronize()
        monitor.check()
        optimizer_state_entries = len(optimizer.state)
        if optimizer_state_entries <= 0:
            raise RuntimeError("optimizer state was not materialized")
        status = "passed"
    except Exception as error:
        status = "failed"
        failure = error
    finally:
        resources = monitor.stop()
    report = {
        "schema_version": 1,
        "gate": "C",
        "status": status,
        "real_forward": progress["forward"],
        "real_backward": progress["backward"],
        "real_optimizer_step": progress["optimizer_step"],
        "attention_implementation": TRAINING_ATTENTION_IMPLEMENTATION,
        "lora": {
            "rank": LORA_RANK,
            "alpha": LORA_ALPHA,
            "dropout": 0.05,
            "target_modules": "all-linear",
        },
        "trainable_parameters": trainable,
        "gradient_norm": gradient_norm,
        "loss": loss,
        "optimizer": "torch.optim.AdamW_no_paging",
        "optimizer_state_entries": optimizer_state_entries,
        "max_seq_length": max_seq_length,
        "execution_source_snapshot": current_source_revision(PROJECT_ROOT),
        "dataset_version": DATASET_VERSION,
        "dataset_bundle_hash": dataset_bundle_hash(DATASET_ROOT),
        "rendered_manifest_hash": manifest["content_hash"],
        "elapsed_seconds": time.perf_counter() - started,
        "resources": resources,
        "torch_peak_allocated_mib": torch.cuda.max_memory_allocated() / 1024**2,
        "torch_peak_reserved_mib": torch.cuda.max_memory_reserved() / 1024**2,
        "completed_at": datetime.now(UTC).isoformat(),
    }
    if failure is not None:
        report["failure"] = {"type": type(failure).__name__, "message": str(failure)}
        write_hashed_json(EVIDENCE_ROOT / GATE_C_EVIDENCE_NAME, report)
        raise failure
    del model, optimizer
    gc.collect()
    torch.cuda.empty_cache()
    return write_hashed_json(EVIDENCE_ROOT / GATE_C_EVIDENCE_NAME, report)


def diagnose_gate_c_gradients(
    *,
    attn_implementation: str = "sdpa",
    diagnostic_attempt: int = 1,
) -> dict[str, Any]:
    """Inspect the failed real backward pass without applying an optimizer step."""
    import torch

    if attn_implementation not in {"sdpa", "eager"}:
        raise ValueError("unsupported diagnostic attention implementation")
    require_dataset_freeze_approval()
    report_path = EVIDENCE_ROOT / f"gate-c-v4-gradient-diagnostic-{diagnostic_attempt}.json"
    if report_path.exists():
        raise FileExistsError("Gate C gradient diagnostic is immutable and already exists")
    failed_gate = read_hashed_json(EVIDENCE_ROOT / GATE_C_EVIDENCE_NAME)
    if failed_gate.get("status") != "failed":
        raise RuntimeError("Gate C diagnostic requires preserved failed evidence")
    require_v4_gate_evidence(EVIDENCE_ROOT / GATE_B_EVIDENCE_NAME, expected_gate="B")
    manifest = read_hashed_json(RENDERED_ROOT / "manifest.json")
    tokenizer = _load_tokenizer()
    before = resource_snapshot()
    assert_training_preflight(before)
    monitor = ResourceMonitor().start()
    started = time.perf_counter()
    model = None
    report: dict[str, Any] = {
        "schema_version": 1,
        "diagnostic": "gate-c-gradient-finiteness",
        "attention_implementation": attn_implementation,
        "source_failed_gate_hash": failed_gate["content_hash"],
        "optimizer_step_performed": False,
    }
    try:
        model, trainable, quantization = _load_qlora_model(
            attn_implementation=attn_implementation
        )
        loader = _make_loader(
            "train", tokenizer, manifest["chosen_max_seq_length"], seed=901, shuffle=False
        )
        batch = {
            key: value.to("cuda:0", non_blocking=True)
            for key, value in next(iter(loader)).items()
        }
        output = model(**batch)
        loss = output.loss
        if not torch.isfinite(loss):
            raise RuntimeError("diagnostic forward loss is non-finite")
        loss.backward()
        torch.cuda.synchronize()
        bad_parameters = []
        gradient_parameter_count = 0
        finite_gradient_element_count = 0
        nonfinite_gradient_element_count = 0
        maximum_finite_absolute_gradient = 0.0
        dtype_counts: dict[str, int] = {}
        for name, parameter in model.named_parameters():
            if not parameter.requires_grad or parameter.grad is None:
                continue
            gradient_parameter_count += 1
            gradient = parameter.grad.detach()
            dtype_counts[str(gradient.dtype)] = dtype_counts.get(str(gradient.dtype), 0) + 1
            finite = torch.isfinite(gradient)
            finite_count = int(finite.sum().item())
            nonfinite_count = gradient.numel() - finite_count
            finite_gradient_element_count += finite_count
            nonfinite_gradient_element_count += nonfinite_count
            if finite_count:
                maximum_finite_absolute_gradient = max(
                    maximum_finite_absolute_gradient,
                    float(gradient[finite].abs().max().cpu()),
                )
            if nonfinite_count:
                bad_parameters.append({
                    "name": name,
                    "shape": list(gradient.shape),
                    "dtype": str(gradient.dtype),
                    "nonfinite_count": nonfinite_count,
                    "nan_count": int(torch.isnan(gradient).sum().item()),
                    "positive_inf_count": int(torch.isposinf(gradient).sum().item()),
                    "negative_inf_count": int(torch.isneginf(gradient).sum().item()),
                })
        monitor.check()
        report.update({
            "status": "diagnosed",
            "loss": float(loss.detach().cpu()),
            "logits_finite": bool(torch.isfinite(output.logits).all().item()),
            "trainable_parameters": trainable,
            "quantization": quantization,
            "gradient_parameter_count": gradient_parameter_count,
            "gradient_dtype_parameter_counts": dtype_counts,
            "finite_gradient_element_count": finite_gradient_element_count,
            "nonfinite_gradient_element_count": nonfinite_gradient_element_count,
            "maximum_finite_absolute_gradient": maximum_finite_absolute_gradient,
            "bad_parameters": bad_parameters,
        })
    except Exception as error:
        report.update({
            "status": "diagnostic_failed",
            "failure": {"type": type(error).__name__, "message": str(error)},
        })
        raise
    finally:
        report["elapsed_seconds"] = time.perf_counter() - started
        report["resources"] = monitor.stop()
        report["completed_at"] = datetime.now(UTC).isoformat()
        write_hashed_json(report_path, report)
        del model
        gc.collect()
        torch.cuda.empty_cache()
    return read_hashed_json(report_path)


def _evaluate_loss(model, loader, *, maximum_batches: int | None = None) -> float:
    import torch

    losses = []
    model.eval()
    with torch.no_grad():
        for index, batch in enumerate(loader):
            if maximum_batches is not None and index >= maximum_batches:
                break
            batch = {key: value.to("cuda:0", non_blocking=True) for key, value in batch.items()}
            loss = model(**batch).loss
            if not torch.isfinite(loss):
                raise RuntimeError("non-finite validation loss")
            losses.append(float(loss.detach().cpu()))
    model.train()
    return statistics.fmean(losses)


def _evaluate_loss_selective(
    model,
    loader,
    *,
    maximum_batches: int | None = None,
    evidence_rows: list[dict[str, Any]] | None = None,
) -> float:
    """Evaluate the identical shifted suffix objective without prefix logits."""
    import torch

    losses = []
    model.eval()
    with torch.no_grad():
        for index, batch in enumerate(loader):
            if maximum_batches is not None and index >= maximum_batches:
                break
            batch = {
                key: value.to("cuda:0", non_blocking=True)
                for key, value in batch.items()
            }
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                loss, selection = _selective_causal_lm_loss(model, batch)
            if (
                not torch.isfinite(loss)
                or selection.get("selected_logit_count")
                != selection.get("supervised_token_count")
            ):
                raise RuntimeError("invalid selective validation loss or supervision")
            losses.append(float(loss.detach().cpu()))
            if evidence_rows is not None:
                evidence_rows.append({
                    "validation_batch": index + 1,
                    "loss": losses[-1],
                    "selected_logit_count": selection["selected_logit_count"],
                    "supervised_token_count": selection["supervised_token_count"],
                })
            del loss, batch
            torch.cuda.empty_cache()
    model.train()
    if not losses:
        raise RuntimeError("selective validation produced no losses")
    return statistics.fmean(losses)


def _adapter_binding_material(
    *,
    run_id: str,
    seed: int,
    adapter_dir: Path,
    training: dict[str, Any],
    training_boundary: dict[str, Any],
    execution_source_snapshot: str,
    remediated_gate_c_hash: str,
) -> dict[str, Any]:
    model_provenance = read_hashed_json(EVIDENCE_ROOT / "qwen3-8b-provenance.json")
    rendered = read_hashed_json(RENDERED_ROOT / "manifest.json")
    adapter_file = adapter_dir / "adapter_model.safetensors"
    config_file = adapter_dir / "adapter_config.json"
    material = {
        "schema_version": 1,
        "run_id": run_id,
        "seed": seed,
        "candidate_only": True,
        "promotion_authorized": False,
        "deployment_authorized": False,
        "contains_user_data": training_boundary["contains_user_data"],
        "execution_source_snapshot": execution_source_snapshot,
        "base_repository": load_model_manifest()["repository"],
        "base_revision": load_model_manifest()["revision"],
        "base_provenance_hash": model_provenance["content_hash"],
        "dataset_version": DATASET_VERSION,
        "dataset_bundle_hash": dataset_bundle_hash(DATASET_ROOT),
        "rendered_manifest_hash": rendered["content_hash"],
        "training_input_boundary_hash": training_boundary["content_hash"],
        "remediated_gate_c_hash": remediated_gate_c_hash,
        "framework": FRAMEWORK_VERSION,
        "training_implementation": TRAINING_IMPLEMENTATION_VERSION,
        "resource_monitor_version": RESOURCE_EVIDENCE_VERSION,
        "supersedes_training_report_hash": (
            SUPERSEDED_FORMAL_REPORT_HASHES.get(seed) if seed in REQUIRED_FORMAL_SEEDS
            else None
        ),
        "attention_implementation": TRAINING_ATTENTION_IMPLEMENTATION,
        "lora": {
            "rank": LORA_RANK,
            "alpha": LORA_ALPHA,
            "dropout": 0.05,
            "target_modules": "all-linear",
        },
        "adapter_file": adapter_file.name,
        "adapter_sha256": sha256_file(adapter_file),
        "adapter_size_bytes": adapter_file.stat().st_size,
        "adapter_config_sha256": sha256_file(config_file),
        "training_summary": training,
    }
    return material


def _resource_evidence_is_within_stage9a_limits(
    resources: dict[str, Any], *, peak_target_mib: float
) -> bool:
    aggregate_fields = (
        "vram_used_mib",
        "shared_gpu_mib",
        "ram_available_gib",
        "ram_used_gib",
        "swap_used_mib",
        "stage9a_disk_gib",
        "gpu_utilization_percent",
        "gpu_temperature_c",
        "gpu_power_w",
    )
    sample_numeric_fields = (*aggregate_fields, "vram_free_mib")
    samples = resources.get("samples")
    if (
        resources.get("resource_monitor_version") != RESOURCE_EVIDENCE_VERSION
        or resources.get("hard_failure") is not None
        or not isinstance(samples, list)
        or not samples
        or type(resources.get("sample_count")) is not int
        or resources["sample_count"] != len(samples)
    ):
        return False

    for sample in samples:
        if (
            not isinstance(sample, dict)
            or sample.get("resource_monitor_version") != RESOURCE_EVIDENCE_VERSION
            or not isinstance(sample.get("recorded_at"), str)
            or not sample["recorded_at"]
        ):
            return False
        try:
            recorded_at = datetime.fromisoformat(sample["recorded_at"])
        except ValueError:
            return False
        if recorded_at.tzinfo is None:
            return False
        for field in sample_numeric_fields:
            value = sample.get(field)
            if (
                type(value) not in (int, float)
                or not math.isfinite(float(value))
                or float(value) < 0.0
            ):
                return False
        if float(sample["gpu_utilization_percent"]) > 100.0:
            return False

    baseline = resources.get("baseline")
    final = resources.get("final")
    minimum = resources.get("minimum")
    maximum = resources.get("maximum")
    if baseline != samples[0] or final != samples[-1]:
        return False
    if not isinstance(minimum, dict) or not isinstance(maximum, dict):
        return False
    expected_minimum = {
        field: min(sample[field] for sample in samples)
        for field in aggregate_fields
    }
    expected_maximum = {
        field: max(sample[field] for sample in samples)
        for field in aggregate_fields
    }
    if minimum != expected_minimum or maximum != expected_maximum:
        return False

    return (
        float(baseline["ram_available_gib"]) >= MIN_AVAILABLE_RAM_GIB
        and float(maximum["vram_used_mib"]) <= peak_target_mib
        and float(maximum["shared_gpu_mib"]) - float(baseline["shared_gpu_mib"])
        <= MAX_SHARED_GPU_GROWTH_MIB
        and float(maximum["swap_used_mib"]) - float(baseline["swap_used_mib"])
        <= MAX_SWAP_GROWTH_MIB
        and float(maximum["stage9a_disk_gib"]) <= 80.0
    )


def _validate_gate_d_readiness_records(
    *,
    smoke: dict[str, Any],
    reload_report: dict[str, Any],
    adapter: dict[str, Any],
    gate_c: dict[str, Any],
) -> None:
    summary = smoke.get("training_summary", {})
    history = smoke.get("history", [])
    finite_summary = (
        summary.get("initial_validation_loss"),
        summary.get("final_validation_loss"),
        summary.get("peak_vram_mib"),
        summary.get("nvidia_smi_peak_vram_mib"),
        summary.get("torch_peak_allocated_mib"),
        summary.get("torch_peak_reserved_mib"),
    )
    expected_lora = {
        "rank": LORA_RANK,
        "alpha": LORA_ALPHA,
        "dropout": 0.05,
        "target_modules": "all-linear",
    }
    if (
        smoke.get("run_id") != SMOKE_RUN_ID
        or smoke.get("gate") != "D"
        or smoke.get("seed") != 9001
        or smoke.get("formal") is not False
        or smoke.get("status") != "completed_candidate"
        or smoke.get("candidate_only") is not True
        or smoke.get("promotion_authorized") is not False
        or smoke.get("deployment_authorized") is not False
        or smoke.get("contains_user_data") is not False
        or smoke.get("execution_source_snapshot")
        != gate_c.get("execution_source_snapshot")
        or smoke.get("training_implementation") != TRAINING_IMPLEMENTATION_VERSION
        or smoke.get("resource_monitor_version") != RESOURCE_EVIDENCE_VERSION
        or smoke.get("supersedes_training_report_hash")
        != SUPERSEDED_GATE_D_REPORT_HASH
        or smoke.get("loss_path_version") != SELECTIVE_LOGITS_LOSS_VERSION
        or smoke.get("remediated_gate_c_hash") != gate_c.get("content_hash")
        or smoke.get("dataset_bundle_hash") != dataset_bundle_hash(DATASET_ROOT)
        or smoke.get("rendered_manifest_hash") != APPROVED_RENDERED_MANIFEST_HASH
        or smoke.get("attention_implementation") != TRAINING_ATTENTION_IMPLEMENTATION
        or smoke.get("lora") != expected_lora
        or smoke.get("optimizer") != "torch.optim.AdamW_no_paging"
        or smoke.get("bf16_autocast") is not True
        or smoke.get("frozen_base_io_bf16_restored") is not True
        or smoke.get("gradient_checkpointing_use_reentrant") is not False
        or smoke.get("release_cuda_cache_before_optimizer") is not True
        or smoke.get("trainable_parameters") != 10911744
        or smoke.get("max_seq_length") != 336
        or summary.get("epochs_requested") != 1
        or summary.get("optimizer_steps") != 8
        or len(history) != 8
        or [item.get("optimizer_step") for item in history] != list(range(1, 9))
        or any(
            not isinstance(item.get("loss"), (int, float))
            or not math.isfinite(float(item["loss"]))
            or float(item["loss"]) <= 0
            or not isinstance(item.get("gradient_norm"), (int, float))
            or not math.isfinite(float(item["gradient_norm"]))
            or not isinstance(item.get("selected_logit_count"), int)
            or int(item["selected_logit_count"]) <= 0
            for item in history
        )
        or any(not isinstance(value, (int, float)) for value in finite_summary)
        or any(not math.isfinite(float(value)) for value in finite_summary)
        or any(float(value) > TARGET_VRAM_MIB for value in finite_summary[2:])
        or not _resource_evidence_is_within_stage9a_limits(
            smoke.get("resource_evidence", {}), peak_target_mib=TARGET_VRAM_MIB
        )
        or adapter.get("content_hash") != smoke.get("adapter_manifest_hash")
        or adapter.get("run_id") != SMOKE_RUN_ID
        or adapter.get("seed") != 9001
        or adapter.get("execution_source_snapshot")
        != gate_c.get("execution_source_snapshot")
        or adapter.get("remediated_gate_c_hash") != gate_c.get("content_hash")
        or adapter.get("resource_monitor_version") != RESOURCE_EVIDENCE_VERSION
        or reload_report.get("gate") != "D-reload"
        or reload_report.get("status") != "passed"
        or reload_report.get("candidate_only") is not True
        or reload_report.get("promotion_authorized") is not False
        or reload_report.get("deployment_authorized") is not False
        or reload_report.get("contains_user_data") is not False
        or reload_report.get("execution_source_snapshot")
        != gate_c.get("execution_source_snapshot")
        or reload_report.get("training_implementation")
        != TRAINING_IMPLEMENTATION_VERSION
        or reload_report.get("adapter_manifest_hash") != adapter.get("content_hash")
        or reload_report.get("new_process_reload") is not True
        or reload_report.get("finite_logits") is not True
        or not isinstance(reload_report.get("adapter_load_seconds"), (int, float))
        or not math.isfinite(float(reload_report["adapter_load_seconds"]))
        or float(reload_report["adapter_load_seconds"]) < 0
        or not _resource_evidence_is_within_stage9a_limits(
            reload_report.get("resources", {}), peak_target_mib=TARGET_VRAM_MIB
        )
    ):
        raise RuntimeError("Gate D smoke/reload evidence is incomplete or cross-bound")


def require_gate_d_readiness() -> dict[str, Any]:
    gate_c = require_remediated_gate_c()
    smoke_path = RUNS_ROOT / SMOKE_RUN_ID / "training-report.json"
    reload_path = RUNS_ROOT / SMOKE_RUN_ID / "reload-report.json"
    smoke = read_hashed_json(smoke_path)
    reload_report = read_hashed_json(reload_path)
    adapter = verify_adapter_binding(RUNS_ROOT / SMOKE_RUN_ID / "adapter")
    _validate_gate_d_readiness_records(
        smoke=smoke,
        reload_report=reload_report,
        adapter=adapter,
        gate_c=gate_c,
    )
    return {
        "gate_c": gate_c,
        "smoke": smoke,
        "reload": reload_report,
        "adapter": adapter,
    }


def train_qlora(
    *,
    seed: int,
    run_id: str,
    epochs: int,
    max_optimizer_steps: int | None,
    formal: bool,
) -> dict[str, Any]:
    require_dataset_freeze_approval()
    remediated_gate_c = require_remediated_gate_c()
    if not formal and (
        seed != 9001
        or run_id != SMOKE_RUN_ID
        or epochs != 1
        or max_optimizer_steps != 8
    ):
        raise ValueError("Gate D uses the fixed seed-9001 eight-step smoke plan")
    if formal:
        readiness = require_gate_d_readiness()
        smoke_report = readiness["smoke"]
        if readiness["gate_c"]["content_hash"] != remediated_gate_c["content_hash"]:
            raise RuntimeError("Gate D and formal run use different Gate C evidence")
        if epochs != 2 or max_optimizer_steps is not None:
            raise ValueError("formal Stage 9A runs use the fixed two-epoch full-dataset plan")
        if seed not in (*REQUIRED_FORMAL_SEEDS, OPTIONAL_THIRD_SEED):
            raise ValueError(f"seed is outside the approved Stage 9A plan: {seed}")
        if run_id != FORMAL_RUN_IDS[seed]:
            raise ValueError("formal Stage 9A run id is not the versioned resource correction id")
        if seed == OPTIONAL_THIRD_SEED:
            # Local import avoids a module cycle; the registry validator
            # recomputes the decision from exact 9201/9202 evidence.
            from mlsys.training.stage9a_registry import require_third_seed_decision

            justification = require_third_seed_decision()
            if justification.get("decision") != "run_optional_third_seed":
                raise RuntimeError("optional third seed lacks approved experimental justification")
    import torch

    output_root = RUNS_ROOT / run_id
    if output_root.exists():
        raise FileExistsError(f"immutable Stage 9A run already exists: {output_root}")
    prior_formal_seconds = 0.0
    prior_formal_seeds: set[int] = set()
    if formal and RUNS_ROOT.exists():
        for report_path in RUNS_ROOT.glob("*/training-report.json"):
            prior = read_hashed_json(report_path)
            if prior.get("formal") and prior.get("status") == "completed_candidate":
                prior_formal_seconds += float(
                    prior["training_summary"]["wall_time_seconds"]
                )
                prior_seed = int(prior["seed"])
                if prior.get("run_id") not in SUPERSEDED_FORMAL_RUN_IDS.values():
                    prior_formal_seeds.add(prior_seed)
        if seed in prior_formal_seeds:
            raise ValueError(f"formal Stage 9A seed already exists: {seed}")
        if prior_formal_seconds >= MAX_FORMAL_GPU_SECONDS:
            raise TimeoutError("formal Stage 9A GPU training budget is exhausted")
    adapter_dir = output_root / "adapter"
    manifest = read_hashed_json(RENDERED_ROOT / "manifest.json")
    max_seq_length = manifest["chosen_max_seq_length"]
    tokenizer = _load_tokenizer()
    execution_source_snapshot = current_source_revision(PROJECT_ROOT)
    training_boundary = verify_training_input_boundary(tokenizer)
    if (
        training_boundary["contains_user_data"]
        or not training_boundary["all_members_training_eligible"]
        or training_boundary["source_kinds"] != ["synthetic_fixture"]
    ):
        raise RuntimeError("Stage 9A training inputs violate the approved data policy")
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    before = resource_snapshot()
    assert_training_preflight(before)
    output_root.mkdir(parents=True)
    monitor = ResourceMonitor(interval_seconds=1.0).start()
    started = time.perf_counter()
    history = []
    warning_codes: list[str] = []
    failure: Exception | None = None
    model = None
    optimizer = None
    try:
        torch.cuda.reset_peak_memory_stats()
        model, trainable, quantization = _load_qlora_model(
            attn_implementation=TRAINING_ATTENTION_IMPLEMENTATION,
            gradient_checkpointing_use_reentrant=False,
            restore_frozen_base_io_bf16=True,
        )
        optimizer = torch.optim.AdamW(
            [parameter for parameter in model.parameters() if parameter.requires_grad],
            lr=2e-4,
            weight_decay=0.0,
        )
        train_loader = _make_loader("train", tokenizer, max_seq_length, seed=seed, shuffle=True)
        validation_loader = _make_loader(
            "validation", tokenizer, max_seq_length, seed=seed, shuffle=False
        )
        initial_validation_rows: list[dict[str, Any]] = []
        initial_validation_loss = _evaluate_loss_selective(
            model, validation_loader, evidence_rows=initial_validation_rows
        )
        optimizer_steps = 0
        for epoch in range(epochs):
            model.train()
            for batch in train_loader:
                if formal and time.perf_counter() - started > MAX_FORMAL_SEED_SECONDS:
                    raise TimeoutError("formal seed exceeded two-hour limit")
                if formal and prior_formal_seconds + time.perf_counter() - started > MAX_FORMAL_GPU_SECONDS:
                    raise TimeoutError("formal Stage 9A GPU training exceeded six-hour total limit")
                monitor.check()
                step_evidence: dict[str, Any] = {}
                loss, gradient_norm, selection = _selective_training_step(
                    model,
                    batch,
                    optimizer,
                    step_evidence=step_evidence,
                    use_bf16_autocast=True,
                    release_cuda_cache_before_optimizer=True,
                )
                if (
                    not step_evidence.get("all_gradient_tensors_finite")
                    or not step_evidence.get("optimizer_state_materialized")
                ):
                    raise RuntimeError("selective training step evidence is incomplete")
                if max(
                    torch.cuda.max_memory_allocated() / 1024**2,
                    torch.cuda.max_memory_reserved() / 1024**2,
                ) > TARGET_VRAM_MIB:
                    raise RuntimeError("training_peak_vram_above_11_0_gib")
                optimizer_steps += 1
                history.append({
                    "optimizer_step": optimizer_steps,
                    "epoch": epoch + 1,
                    "loss": loss,
                    "gradient_norm": gradient_norm,
                    "selected_logit_count": selection["selected_logit_count"],
                    "elapsed_seconds": time.perf_counter() - started,
                    "torch_allocated_mib": torch.cuda.memory_allocated() / 1024**2,
                    "torch_reserved_mib": torch.cuda.memory_reserved() / 1024**2,
                })
                if max_optimizer_steps is not None and optimizer_steps >= max_optimizer_steps:
                    break
            if max_optimizer_steps is not None and optimizer_steps >= max_optimizer_steps:
                break
        final_validation_rows: list[dict[str, Any]] = []
        final_validation_loss = _evaluate_loss_selective(
            model, validation_loader, evidence_rows=final_validation_rows
        )
        observed_losses = [item["loss"] for item in history]
        if not observed_losses or any(not math.isfinite(value) or value <= 0 for value in observed_losses):
            raise RuntimeError("training loss history is empty, non-finite, or non-positive")
        if max(observed_losses) > max(100.0, observed_losses[0] * 4.0):
            raise RuntimeError("training loss behavior exceeded the bounded stability envelope")
        torch.cuda.synchronize()
        monitor.samples.append(resource_snapshot())
        monitor.check()
        pre_save_peak_mib = max(
            max(item["vram_used_mib"] for item in monitor.samples),
            torch.cuda.max_memory_allocated() / 1024**2,
            torch.cuda.max_memory_reserved() / 1024**2,
        )
        if pre_save_peak_mib > TARGET_VRAM_MIB:
            raise RuntimeError("training_peak_vram_above_11_0_gib")
        model.save_pretrained(adapter_dir, safe_serialization=True)
        tokenizer.save_pretrained(adapter_dir / "tokenizer")
        if not (adapter_dir / "adapter_model.safetensors").is_file():
            raise RuntimeError("real adapter.safetensors was not saved")
        status = "completed_candidate"
    except Exception as error:
        status = "failed"
        failure = error
    finally:
        resources = monitor.stop()
    torch_peak_allocated_mib = torch.cuda.max_memory_allocated() / 1024**2
    torch_peak_reserved_mib = torch.cuda.max_memory_reserved() / 1024**2
    observed_peak_vram_mib = max(
        resources["maximum"]["vram_used_mib"],
        torch_peak_allocated_mib,
        torch_peak_reserved_mib,
    )
    if failure is None and observed_peak_vram_mib > TARGET_VRAM_MIB:
        failure = RuntimeError("training_peak_vram_above_11_0_gib")

    def write_failure_evidence(error: Exception, *, failure_stage: str) -> None:
        write_hashed_json(output_root / "failure.json", {
            "schema_version": 1,
            "run_id": run_id,
            "seed": seed,
            "formal": formal,
            "status": "failed",
            "failure_stage": failure_stage,
            "failure": {"type": type(error).__name__, "message": str(error)},
            "candidate_only": True,
            "promotion_authorized": False,
            "deployment_authorized": False,
            "contains_user_data": False,
            "dataset_bundle_hash": dataset_bundle_hash(DATASET_ROOT),
            "rendered_manifest_hash": manifest["content_hash"],
            "execution_source_snapshot": execution_source_snapshot,
            "training_implementation": TRAINING_IMPLEMENTATION_VERSION,
            "remediated_gate_c_hash": remediated_gate_c["content_hash"],
            "resource_evidence": resources,
            "failed_at": datetime.now(UTC).isoformat(),
        })

    if failure is not None:
        status = "failed"
        write_failure_evidence(failure, failure_stage="model_or_training")
        del model, optimizer
        gc.collect()
        torch.cuda.empty_cache()
        raise failure
    try:
        training_summary = {
            "status": status,
            "epochs_requested": epochs,
            "optimizer_steps": optimizer_steps,
            "initial_validation_loss": initial_validation_loss,
            "final_validation_loss": final_validation_loss,
            "wall_time_seconds": time.perf_counter() - started,
            "peak_vram_mib": observed_peak_vram_mib,
            "nvidia_smi_peak_vram_mib": resources["maximum"]["vram_used_mib"],
            "torch_peak_allocated_mib": torch_peak_allocated_mib,
            "torch_peak_reserved_mib": torch_peak_reserved_mib,
            "minimum_available_ram_gib": resources["minimum"]["ram_available_gib"],
            "maximum_swap_used_mib": resources["maximum"]["swap_used_mib"],
        }
        binding = _adapter_binding_material(
            run_id=run_id,
            seed=seed,
            adapter_dir=adapter_dir,
            training=training_summary,
            training_boundary=training_boundary,
            execution_source_snapshot=execution_source_snapshot,
            remediated_gate_c_hash=remediated_gate_c["content_hash"],
        )
        binding = write_hashed_json(adapter_dir / "havre_adapter_manifest.json", binding)
        report = {
            "schema_version": 1,
            "gate": "D" if not formal else None,
            "run_id": run_id,
            "seed": seed,
            "formal": formal,
            "status": status,
            "candidate_only": True,
            "promotion_authorized": False,
            "deployment_authorized": False,
            "contains_user_data": training_boundary["contains_user_data"],
            "dataset_bundle_hash": dataset_bundle_hash(DATASET_ROOT),
            "rendered_manifest_hash": manifest["content_hash"],
            "execution_source_snapshot": execution_source_snapshot,
            "training_input_boundary_hash": training_boundary["content_hash"],
            "framework": FRAMEWORK_VERSION,
            "training_implementation": TRAINING_IMPLEMENTATION_VERSION,
            "resource_monitor_version": RESOURCE_EVIDENCE_VERSION,
            "supersedes_training_report_hash": (
                SUPERSEDED_FORMAL_REPORT_HASHES.get(seed)
                if formal and seed in REQUIRED_FORMAL_SEEDS
                else SUPERSEDED_GATE_D_REPORT_HASH if not formal else None
            ),
            "loss_path_version": SELECTIVE_LOGITS_LOSS_VERSION,
            "remediated_gate_c_hash": remediated_gate_c["content_hash"],
            "formal_seed_plan": list(REQUIRED_FORMAL_SEEDS),
            "optional_third_seed": OPTIONAL_THIRD_SEED,
            "quantization": quantization,
            "attention_implementation": TRAINING_ATTENTION_IMPLEMENTATION,
            "lora": {
                "rank": LORA_RANK,
                "alpha": LORA_ALPHA,
                "dropout": 0.05,
                "target_modules": "all-linear",
            },
            "optimizer": "torch.optim.AdamW_no_paging",
            "bf16_autocast": True,
            "frozen_base_io_bf16_restored": True,
            "gradient_checkpointing_use_reentrant": False,
            "release_cuda_cache_before_optimizer": True,
            "trainable_parameters": trainable,
            "max_seq_length": max_seq_length,
            "history": history,
            "validation_evidence": {
                "reduction": "arithmetic_mean_of_batch_size_1_losses",
                "initial": initial_validation_rows,
                "final": final_validation_rows,
            },
            "training_summary": training_summary,
            "resource_evidence": resources,
            "warning_codes": warning_codes,
            "adapter_manifest_hash": binding["content_hash"],
            "completed_at": datetime.now(UTC).isoformat(),
        }
        written = write_hashed_json(output_root / "training-report.json", report)
    except Exception as closure_error:
        write_failure_evidence(closure_error, failure_stage="artifact_closure")
        del model, optimizer
        gc.collect()
        torch.cuda.empty_cache()
        raise
    del model, optimizer
    gc.collect()
    torch.cuda.empty_cache()
    return written


def verify_adapter_binding(adapter_dir: Path, *, expected_revision: str | None = None) -> dict[str, Any]:
    manifest = read_hashed_json(adapter_dir / "havre_adapter_manifest.json")
    approved = load_model_manifest()
    required_revision = expected_revision or approved["revision"]
    if manifest["base_repository"] != approved["repository"]:
        raise ValueError("adapter repository binding mismatch")
    if manifest["base_revision"] != required_revision:
        raise ValueError("adapter exact base revision binding mismatch")
    provenance = read_hashed_json(EVIDENCE_ROOT / "qwen3-8b-provenance.json")
    if manifest["base_provenance_hash"] != provenance["content_hash"]:
        raise ValueError("adapter base artifact hash binding mismatch")
    if manifest["adapter_sha256"] != sha256_file(adapter_dir / manifest["adapter_file"]):
        raise ValueError("adapter artifact hash mismatch")
    if manifest["adapter_config_sha256"] != sha256_file(adapter_dir / "adapter_config.json"):
        raise ValueError("adapter configuration hash mismatch")
    adapter_config = json.loads((adapter_dir / "adapter_config.json").read_text(encoding="utf-8"))
    expected_config = {
        "peft_type": "LORA",
        "task_type": "CAUSAL_LM",
        "r": LORA_RANK,
        "lora_alpha": LORA_ALPHA,
        "lora_dropout": 0.05,
        "bias": "none",
        "modules_to_save": None,
        "use_dora": False,
        "use_rslora": False,
        "use_qalora": False,
        "layers_to_transform": None,
        "layer_replication": None,
        "trainable_token_indices": None,
        "exclude_modules": None,
        "lora_bias": False,
    }
    mismatches = {
        key: {"expected": expected, "actual": adapter_config.get(key)}
        for key, expected in expected_config.items()
        if adapter_config.get(key) != expected
    }
    if mismatches:
        raise ValueError(f"adapter configuration is incompatible: {mismatches}")
    expected_targets = {
        "q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"
    }
    actual_targets = adapter_config.get("target_modules")
    if not isinstance(actual_targets, list) or set(actual_targets) != expected_targets:
        raise ValueError(
            "adapter configuration is incompatible: target_modules do not match "
            "the approved Qwen3 all-linear projection set"
        )
    if manifest.get("contains_user_data") is not False:
        raise ValueError("adapter is not bound to a user-data-free training input")
    _require_current_adapter_training_binding(manifest)
    if manifest.get("dataset_bundle_hash") != dataset_bundle_hash(DATASET_ROOT):
        raise ValueError("adapter dataset binding differs from the current verified dataset")
    rendered = read_hashed_json(RENDERED_ROOT / "manifest.json")
    if manifest.get("rendered_manifest_hash") != rendered["content_hash"]:
        raise ValueError("adapter rendered-input binding differs from the current artifact")
    if not manifest["candidate_only"] or manifest["promotion_authorized"] or manifest["deployment_authorized"]:
        raise ValueError("adapter violates Stage 9A candidate-only boundary")
    return manifest


def _validate_formal_training_artifacts(
    report: dict[str, Any], binding: dict[str, Any]
) -> None:
    """Recompute the fixed formal-plan invariants from persisted training evidence."""
    seed = int(report.get("seed", -1))
    gate_c = require_remediated_gate_c()
    expected_source = gate_c["execution_source_snapshot"]
    gate_b = read_hashed_json(EVIDENCE_ROOT / GATE_B_EVIDENCE_NAME)
    summary = report.get("training_summary", {})
    history = report.get("history", [])
    expected_steps = SPLIT_COUNTS["train"] * 2
    expected_lora = {
        "rank": LORA_RANK,
        "alpha": LORA_ALPHA,
        "dropout": 0.05,
        "target_modules": "all-linear",
    }
    fixed_mismatch = (
        report.get("schema_version") != 1
        or report.get("gate") is not None
        or report.get("run_id") != FORMAL_RUN_IDS.get(seed)
        or report.get("formal") is not True
        or report.get("status") != "completed_candidate"
        or report.get("candidate_only") is not True
        or report.get("promotion_authorized") is not False
        or report.get("deployment_authorized") is not False
        or report.get("contains_user_data") is not False
        or report.get("dataset_bundle_hash") != dataset_bundle_hash(DATASET_ROOT)
        or report.get("rendered_manifest_hash") != APPROVED_RENDERED_MANIFEST_HASH
        or report.get("execution_source_snapshot") != expected_source
        or report.get("framework") != FRAMEWORK_VERSION
        or report.get("training_implementation") != TRAINING_IMPLEMENTATION_VERSION
        or report.get("resource_monitor_version") != RESOURCE_EVIDENCE_VERSION
        or report.get("supersedes_training_report_hash")
        != SUPERSEDED_FORMAL_REPORT_HASHES.get(seed)
        or report.get("loss_path_version") != SELECTIVE_LOGITS_LOSS_VERSION
        or report.get("remediated_gate_c_hash") != gate_c["content_hash"]
        or report.get("formal_seed_plan") != list(REQUIRED_FORMAL_SEEDS)
        or report.get("optional_third_seed") != OPTIONAL_THIRD_SEED
        or report.get("quantization") != gate_b.get("quantization")
        or report.get("attention_implementation") != TRAINING_ATTENTION_IMPLEMENTATION
        or report.get("lora") != expected_lora
        or report.get("optimizer") != "torch.optim.AdamW_no_paging"
        or report.get("bf16_autocast") is not True
        or report.get("frozen_base_io_bf16_restored") is not True
        or report.get("gradient_checkpointing_use_reentrant") is not False
        or report.get("release_cuda_cache_before_optimizer") is not True
        or report.get("trainable_parameters") != 10911744
        or report.get("max_seq_length") != 336
        or binding.get("run_id") != report.get("run_id")
        or int(binding.get("seed", -1)) != seed
        or binding.get("training_summary") != summary
        or binding.get("training_implementation") != TRAINING_IMPLEMENTATION_VERSION
        or binding.get("resource_monitor_version") != RESOURCE_EVIDENCE_VERSION
        or binding.get("supersedes_training_report_hash")
        != SUPERSEDED_FORMAL_REPORT_HASHES.get(seed)
        or binding.get("remediated_gate_c_hash") != gate_c["content_hash"]
        or binding.get("execution_source_snapshot") != expected_source
    )
    if fixed_mismatch:
        raise ValueError("formal training evidence differs from the fixed Stage 9A plan")
    numeric_summary = (
        summary.get("initial_validation_loss"),
        summary.get("final_validation_loss"),
        summary.get("wall_time_seconds"),
        summary.get("peak_vram_mib"),
        summary.get("nvidia_smi_peak_vram_mib"),
        summary.get("torch_peak_allocated_mib"),
        summary.get("torch_peak_reserved_mib"),
        summary.get("minimum_available_ram_gib"),
        summary.get("maximum_swap_used_mib"),
    )
    if (
        summary.get("status") != "completed_candidate"
        or summary.get("epochs_requested") != 2
        or summary.get("optimizer_steps") != expected_steps
        or len(history) != expected_steps
        or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in numeric_summary)
        or float(summary["initial_validation_loss"]) <= 0
        or float(summary["final_validation_loss"]) <= 0
        or not 0 < float(summary["wall_time_seconds"]) <= MAX_FORMAL_SEED_SECONDS
        or max(float(value) for value in numeric_summary[3:7]) > TARGET_VRAM_MIB
        or not _resource_evidence_is_within_stage9a_limits(
            report.get("resource_evidence", {}), peak_target_mib=TARGET_VRAM_MIB
        )
    ):
        raise ValueError("formal training summary is incomplete or outside fixed limits")
    resources = report["resource_evidence"]
    if (
        float(summary["nvidia_smi_peak_vram_mib"])
        != float(resources["maximum"]["vram_used_mib"])
        or float(summary["minimum_available_ram_gib"])
        != float(resources["minimum"]["ram_available_gib"])
        or float(summary["maximum_swap_used_mib"])
        != float(resources["maximum"]["swap_used_mib"])
        or float(summary["peak_vram_mib"])
        != max(
            float(summary["nvidia_smi_peak_vram_mib"]),
            float(summary["torch_peak_allocated_mib"]),
            float(summary["torch_peak_reserved_mib"]),
        )
    ):
        raise ValueError("formal training resource summary is not row-derived")
    validation = report.get("validation_evidence", {})
    if validation.get("reduction") != "arithmetic_mean_of_batch_size_1_losses":
        raise ValueError("formal validation reduction is not the fixed batch-size-1 mean")
    for phase, summary_key in (
        ("initial", "initial_validation_loss"),
        ("final", "final_validation_loss"),
    ):
        rows = validation.get(phase, [])
        if len(rows) != SPLIT_COUNTS["validation"]:
            raise ValueError("formal validation evidence lacks the full validation split")
        values = []
        for index, row in enumerate(rows, start=1):
            loss = row.get("loss")
            selected = row.get("selected_logit_count")
            if (
                row.get("validation_batch") != index
                or not isinstance(loss, (int, float))
                or not math.isfinite(loss)
                or float(loss) <= 0
                or not isinstance(selected, int)
                or not 1 <= selected <= 36
                or row.get("supervised_token_count") != selected
            ):
                raise ValueError("formal validation evidence contains an invalid row")
            values.append(float(loss))
        if statistics.fmean(values) != float(summary[summary_key]):
            raise ValueError("formal validation summary is not row-derived")
    previous_elapsed = -1.0
    for index, row in enumerate(history, start=1):
        expected_epoch = 1 if index <= SPLIT_COUNTS["train"] else 2
        numeric = (
            row.get("loss"), row.get("gradient_norm"), row.get("elapsed_seconds"),
            row.get("torch_allocated_mib"), row.get("torch_reserved_mib"),
        )
        if (
            row.get("optimizer_step") != index
            or row.get("epoch") != expected_epoch
            or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in numeric)
            or float(row["loss"]) <= 0
            or float(row["gradient_norm"]) < 0
            or not 1 <= int(row.get("selected_logit_count", 0)) <= 38
            or float(row["elapsed_seconds"]) < previous_elapsed
            or float(row["elapsed_seconds"]) > float(summary["wall_time_seconds"])
            or max(float(row["torch_allocated_mib"]), float(row["torch_reserved_mib"]))
            > TARGET_VRAM_MIB
        ):
            raise ValueError("formal training history is forged or inconsistent")
        previous_elapsed = float(row["elapsed_seconds"])


def completed_formal_runs(
    *, ignore_other_lineages: bool = False
) -> list[dict[str, Any]]:
    """Return internally consistent v4 formal candidate runs and adapters.

    Historical plan construction remains strict by default. Consumers of the
    sealed v4 registry may ignore later, separately governed Stage 9A lineages
    without treating their immutable evidence directories as v4 plan members.
    """
    completed: list[dict[str, Any]] = []
    if not RUNS_ROOT.exists():
        return completed
    known_v4_run_ids = {*FORMAL_RUN_IDS.values(), *SUPERSEDED_FORMAL_RUN_IDS.values()}
    for report_path in sorted(RUNS_ROOT.glob("*/training-report.json")):
        if ignore_other_lineages and report_path.parent.name not in known_v4_run_ids:
            continue
        report = read_hashed_json(report_path)
        if not report.get("formal") or report.get("status") != "completed_candidate":
            continue
        seed = int(report.get("seed", -1))
        if report.get("run_id") == SUPERSEDED_FORMAL_RUN_IDS.get(seed):
            if report.get("content_hash") != SUPERSEDED_FORMAL_REPORT_HASHES.get(seed):
                raise ValueError("superseded formal evidence changed before resource correction")
            continue
        if report.get("run_id") != FORMAL_RUN_IDS.get(seed):
            if ignore_other_lineages:
                continue
            raise ValueError(f"unrecognized formal Stage 9A run: {report_path}")
        if (
            not report.get("candidate_only")
            or report.get("promotion_authorized")
            or report.get("deployment_authorized")
            or report.get("contains_user_data")
            or report.get("training_implementation")
            != TRAINING_IMPLEMENTATION_VERSION
        ):
            raise ValueError(f"formal run violates Stage 9A boundary: {report_path}")
        adapter_dir = report_path.parent / "adapter"
        historical_binding = read_hashed_json(adapter_dir / "havre_adapter_manifest.json")
        if historical_binding.get("dataset_bundle_hash") != dataset_bundle_hash(DATASET_ROOT):
            continue
        binding = verify_adapter_binding(adapter_dir)
        if (
            binding["run_id"] != report["run_id"]
            or int(binding["seed"]) != int(report["seed"])
            or binding["training_summary"] != report["training_summary"]
            or binding["content_hash"] != report["adapter_manifest_hash"]
        ):
            raise ValueError(f"formal run report and adapter binding differ: {report_path}")
        _validate_formal_training_artifacts(report, binding)
        completed.append({
            "run_id": report["run_id"],
            "seed": seed,
            "adapter_dir": str(adapter_dir.resolve()),
            "report_path": str(report_path.resolve()),
            "report_hash": report["content_hash"],
            "adapter_manifest_hash": binding["content_hash"],
            "wall_time_seconds": report["training_summary"]["wall_time_seconds"],
        })
    seeds = [item["seed"] for item in completed]
    if len(seeds) != len(set(seeds)):
        raise ValueError("formal Stage 9A runs contain duplicate seeds")
    if sum(float(item["wall_time_seconds"]) for item in completed) > MAX_FORMAL_GPU_SECONDS:
        raise ValueError("formal Stage 9A runs exceed the six-hour GPU budget")
    return completed


def reload_adapter(adapter_dir: Path) -> dict[str, Any]:
    report_path = adapter_dir.parent / "reload-report.json"
    if report_path.exists():
        raise FileExistsError("immutable adapter reload evidence already exists")
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, BitsAndBytesConfig

    verify_model_artifact(MODEL_ROOT)
    binding = verify_adapter_binding(adapter_dir)
    before = resource_snapshot()
    assert_training_preflight(before)
    monitor = ResourceMonitor().start()
    started = time.perf_counter()
    adapter_load_seconds = None
    failure: Exception | None = None
    base = None
    model = None
    try:
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
            attn_implementation="sdpa",
        )
        load_started = time.perf_counter()
        model = PeftModel.from_pretrained(base, adapter_dir, is_trainable=False)
        adapter_load_seconds = time.perf_counter() - load_started
        tokenizer = _load_tokenizer()
        tokens = tokenizer("Return the word ready.", return_tensors="pt").to("cuda:0")
        with torch.no_grad():
            output = model(**tokens)
        torch.cuda.synchronize()
        monitor.check()
        if not torch.isfinite(output.logits).all():
            raise RuntimeError("reloaded adapter produced non-finite logits")
        status = "passed"
    except Exception as error:
        status = "failed"
        failure = error
    finally:
        resources = monitor.stop()
    if failure is None and not _resource_evidence_is_within_stage9a_limits(
        resources, peak_target_mib=TARGET_VRAM_MIB
    ):
        status = "failed"
        failure = RuntimeError("adapter reload exceeded Stage 9A resource limits")
    report = {
        "schema_version": 1,
        "gate": "D-reload",
        "status": status,
        "candidate_only": True,
        "promotion_authorized": False,
        "deployment_authorized": False,
        "contains_user_data": False,
        "execution_source_snapshot": current_source_revision(PROJECT_ROOT),
        "training_implementation": TRAINING_IMPLEMENTATION_VERSION,
        "adapter_manifest_hash": binding["content_hash"],
        "adapter_load_seconds": adapter_load_seconds,
        "new_process_reload": True,
        "finite_logits": True,
        "elapsed_seconds": time.perf_counter() - started,
        "resources": resources,
        "completed_at": datetime.now(UTC).isoformat(),
    }
    if failure is not None:
        report["finite_logits"] = False
        report["failure"] = {"type": type(failure).__name__, "message": str(failure)}
        write_hashed_json(report_path, report)
        del model, base
        gc.collect()
        torch.cuda.empty_cache()
        raise failure
    written = write_hashed_json(report_path, report)
    del model, base
    gc.collect()
    torch.cuda.empty_cache()
    return written


def _standard_lora_gpu_only_probe_worker() -> dict[str, Any]:
    import torch
    from transformers import AutoModelForCausalLM

    before = resource_snapshot()
    assert_training_preflight(before)
    monitor = ResourceMonitor().start()
    started = time.perf_counter()
    outcome = "unknown"
    error = None
    try:
        model = AutoModelForCausalLM.from_pretrained(
            MODEL_ROOT,
            local_files_only=True,
            trust_remote_code=False,
            torch_dtype=torch.bfloat16,
            device_map={"": 0},
            low_cpu_mem_usage=True,
            attn_implementation="sdpa",
        )
        torch.cuda.synchronize()
        monitor.check()
        devices = _model_devices(model)
        if any(not name.startswith("cuda") for name in devices):
            raise RuntimeError(f"standard LoRA probe attempted non-GPU placement: {devices}")
        outcome = "gpu_only_base_load_feasible"
    except torch.cuda.OutOfMemoryError as exception:
        outcome = "infeasible_gpu_oom"
        error = {"type": type(exception).__name__, "message": str(exception)}
        torch.cuda.empty_cache()
    except Exception as exception:
        outcome = "failed_other"
        error = {"type": type(exception).__name__, "message": str(exception)}
    resources = monitor.stop()
    report = {
        "schema_version": 1,
        "probe": "standard_lora_bf16_gpu_only_load",
        "outcome": outcome,
        "cpu_offload_allowed": False,
        "shared_memory_oversubscription_allowed": False,
        "swap_allowed": False,
        "elapsed_seconds": time.perf_counter() - started,
        "resources": resources,
        "error": error,
        "completed_at": datetime.now(UTC).isoformat(),
    }
    return report


def standard_lora_gpu_only_probe() -> dict[str, Any]:
    """Run the one allowed BF16 load probe in a killable 20-minute subprocess."""
    report_path = EVIDENCE_ROOT / "standard-lora-gpu-only-probe.json"
    if report_path.exists():
        raise FileExistsError("bounded standard LoRA feasibility probe may run only once")
    require_passed_evidence(EVIDENCE_ROOT / "gate-a.json", expected_gate="A")
    started = time.perf_counter()
    command = [
        sys.executable,
        "-m",
        "scripts.stage9a_real_training",
        "standard-lora-worker",
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            timeout=20 * 60,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode == 0:
            worker_report = json.loads(completed.stdout.strip().splitlines()[-1])
            outcome = worker_report["outcome"]
            error = worker_report.get("error")
        else:
            worker_report = None
            outcome = "failed_worker_process"
            error = {
                "type": "WorkerProcessError",
                "message": completed.stderr[-4000:],
                "returncode": completed.returncode,
            }
    except subprocess.TimeoutExpired as exception:
        worker_report = None
        outcome = "infeasible_timeout_20_minutes"
        error = {
            "type": type(exception).__name__,
            "message": "standard LoRA GPU-only probe reached the approved 20-minute limit",
        }
    report = {
        "schema_version": 1,
        "probe": "standard_lora_bf16_gpu_only_load_supervised",
        "outcome": outcome,
        "maximum_seconds": 20 * 60,
        "elapsed_seconds": time.perf_counter() - started,
        "worker_report": worker_report,
        "error": error,
        "cpu_offload_allowed": False,
        "shared_memory_oversubscription_allowed": False,
        "swap_allowed": False,
        "completed_at": datetime.now(UTC).isoformat(),
    }
    return write_hashed_json(report_path, report)
