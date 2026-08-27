"""Smoke reload and formal-readiness gate for the Stage 9A v7 candidate."""

from __future__ import annotations

import gc
import hashlib
import time
from datetime import UTC, datetime

from evals.inference_runner import current_source_revision
from mlsys.training.stage9a_dataset_v7 import DATASET_ROOT, load_and_verify_dataset
from mlsys.training.stage9a_provenance import PROJECT_ROOT, verify_model_artifact
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
from mlsys.training.stage9a_real_v7 import (  # noqa: E402
    FORMAL_RUN_ID,
    RENDERED_ROOT,
    SMOKE_RUN_ID,
    TRAINING_PLAN_PATH,
    load_smoke_remediation,
    load_training_plan,
    verify_adapter,
)
from mlsys.training.stage9a_unseen_v7 import load_and_verify_unseen


SMOKE_RELOAD_REPORT_PATH = RUNS_ROOT / SMOKE_RUN_ID / "reload-report.json"
FORMAL_RELOAD_REPORT_PATH = RUNS_ROOT / FORMAL_RUN_ID / "reload-report.json"
# Backward-compatible name for tests and evidence written before the formal run.
RELOAD_REPORT_PATH = SMOKE_RELOAD_REPORT_PATH


def _generate(model, tokenizer, input_ids, *, max_new_tokens: int = 12) -> str:
    import torch

    input_ids = input_ids.to("cuda:0")
    attention = torch.ones_like(input_ids)
    generated: list[int] = []
    with torch.inference_mode():
        output = model(input_ids=input_ids, attention_mask=attention, use_cache=True)
        token = output.logits[:, -1, :].argmax(dim=-1, keepdim=True)
        cache = output.past_key_values
        generated.append(int(token.item()))
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
    if generated and generated[-1] == tokenizer.eos_token_id:
        generated.pop()
    return tokenizer.decode(generated, skip_special_tokens=True).strip()


def _reload_adapter(*, run_id: str, formal: bool, report_path) -> dict:
    """Prove one immutable v7 adapter reloads over the exact local base."""
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, BitsAndBytesConfig

    plan = load_training_plan()
    if not formal:
        load_smoke_remediation()
    adapter_dir = RUNS_ROOT / run_id / "adapter"
    binding = verify_adapter(adapter_dir)
    if binding.get("formal") is not formal or binding.get("run_id") != run_id:
        raise ValueError("v7 reload received an adapter from the wrong run boundary")
    training = read_hashed_json(RUNS_ROOT / run_id / "training-report.json")
    if (
        training.get("status") != "completed_candidate"
        or training.get("formal") is not formal
        or training.get("adapter_manifest_hash") != binding["content_hash"]
    ):
        raise ValueError("v7 reload training/adapter binding mismatch")
    if report_path.exists():
        raise FileExistsError(f"immutable v7 reload evidence already exists: {report_path}")
    before = resource_snapshot()
    assert_training_preflight(before)
    verify_model_artifact(MODEL_ROOT)
    tokenizer = _load_tokenizer()
    source = load_and_verify_dataset(DATASET_ROOT)["train"][0]
    prompt = [
        {"role": "system", "content": source["system_text"]},
        {"role": "user", "content": "只回复：ready"},
    ]
    input_ids = tokenizer.apply_chat_template(
        prompt,
        tokenize=True,
        add_generation_prompt=True,
        enable_thinking=False,
        return_tensors="pt",
    )
    quantization = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    monitor = ResourceMonitor(interval_seconds=1.0).start()
    started = time.perf_counter()
    base = None
    adapted = None
    failure: Exception | None = None
    output = ""
    try:
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
        adapted = PeftModel.from_pretrained(base, adapter_dir, is_trainable=False)
        adapted.eval()
        output = _generate(adapted, tokenizer, input_ids)
        if not output:
            raise RuntimeError("v7 smoke adapter reload produced an empty output")
        torch.cuda.synchronize()
        monitor.samples.append(resource_snapshot())
        monitor.check()
    except Exception as error:
        failure = error
    finally:
        resources = monitor.stop()
    if failure is None and not _resource_evidence_is_within_stage9a_limits(
        resources, peak_target_mib=TARGET_VRAM_MIB
    ):
        failure = RuntimeError("v7 smoke reload resource evidence is outside limits")
    if failure is not None:
        del adapted, base
        gc.collect()
        torch.cuda.empty_cache()
        raise failure
    report = {
        "schema_version": 1,
        "status": "completed_candidate_reload",
        "run_id": run_id,
        "formal": formal,
        "formal_run_id_unlocked": FORMAL_RUN_ID if not formal else None,
        "candidate_only": True,
        "local_only": True,
        "promotion_authorized": False,
        "deployment_authorized": False,
        "contains_user_data": False,
        "adapter_manifest_hash": binding["content_hash"],
        "training_plan_hash": plan["content_hash"],
        "rendered_manifest_hash": read_hashed_json(RENDERED_ROOT / "manifest.json")["content_hash"],
        "execution_source_snapshot": current_source_revision(PROJECT_ROOT),
        "output_sha256": "sha256:" + hashlib.sha256(output.encode("utf-8")).hexdigest(),
        "output_nonempty": True,
        "resource_monitor_version": RESOURCE_EVIDENCE_VERSION,
        "resources": resources,
        "elapsed_seconds": time.perf_counter() - started,
        "completed_at": datetime.now(UTC).isoformat(),
    }
    written = write_hashed_json(report_path, report)
    del adapted, base
    gc.collect()
    torch.cuda.empty_cache()
    return written


def reload_smoke_adapter() -> dict:
    """Prove the eight-step smoke adapter reloads over the exact base."""
    return _reload_adapter(
        run_id=SMOKE_RUN_ID,
        formal=False,
        report_path=SMOKE_RELOAD_REPORT_PATH,
    )


def reload_formal_adapter() -> dict:
    """Prove the completed formal adapter independently reloads over the exact base."""
    return _reload_adapter(
        run_id=FORMAL_RUN_ID,
        formal=True,
        report_path=FORMAL_RELOAD_REPORT_PATH,
    )


def require_smoke_readiness() -> dict:
    """Fail closed unless smoke training, reload, and unseen separation close."""
    plan = load_training_plan()
    remediation = load_smoke_remediation()
    training = read_hashed_json(RUNS_ROOT / SMOKE_RUN_ID / "training-report.json")
    adapter = verify_adapter(RUNS_ROOT / SMOKE_RUN_ID / "adapter")
    reload = read_hashed_json(SMOKE_RELOAD_REPORT_PATH)
    unseen, _ = load_and_verify_unseen()
    if (
        training.get("run_id") != SMOKE_RUN_ID
        or training.get("formal") is not False
        or training.get("status") != "completed_candidate"
        or training.get("training_summary", {}).get("optimizer_steps") != 8
        or training.get("training_plan_hash") != plan["content_hash"]
        or adapter.get("content_hash") != training.get("adapter_manifest_hash")
        or reload.get("status") != "completed_candidate_reload"
        or reload.get("adapter_manifest_hash") != adapter["content_hash"]
        or reload.get("training_plan_hash") != plan["content_hash"]
        or unseen.get("authored_after_training_plan_hash") != plan["content_hash"]
        or unseen.get("used_for_training_or_hyperparameter_selection") is not False
        or not _resource_evidence_is_within_stage9a_limits(training.get("resource_evidence", {}), peak_target_mib=TARGET_VRAM_MIB)
        or not _resource_evidence_is_within_stage9a_limits(reload.get("resources", {}), peak_target_mib=TARGET_VRAM_MIB)
    ):
        raise ValueError("v7 smoke/reload/unseen formal-readiness binding mismatch")
    return {"remediation": remediation, "training": training, "adapter": adapter, "reload": reload, "unseen": unseen}
