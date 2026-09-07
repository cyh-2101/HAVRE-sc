"""Replay the focused PUBLIC synthetic Memory-use suite on sealed candidates."""

from __future__ import annotations

import argparse
import gc
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from companion.context import CONTEXT_PRESENTATION_VERSION
from companion.hashing import content_hash
from companion.identity import IdentityLoader
from evals.inference_runner import current_source_revision
from evals.relevant_memory_use import (
    LEGACY_PRESENTATION_VERSION,
    load_suite,
    prompt_messages,
    score_case,
    score_casual_case,
    summarize,
)
from mlsys.training.stage9a_provenance import PROJECT_ROOT
from mlsys.training.stage9a_real import (
    MODEL_ROOT,
    _load_tokenizer,
    read_hashed_json,
    write_hashed_json,
)
from mlsys.training.stage9a_registry import REGISTRY_PATH


ARM_ADAPTERS = {
    "candidate_9201": (
        Path("var/stage9a/runs/formal-seed-9201-v4-resource-correction1/adapter")
    ),
    "candidate_9202": (
        Path("var/stage9a/runs/formal-seed-9202-v4-resource-correction1/adapter")
    ),
    "rejected_v7_9701": (
        Path(
            "var/stage9a/runs/"
            "formal-seed-9701-v7-capability-preserving-v1/adapter"
        )
    ),
    "memory_use_v1_9801": (
        Path("var/stage9a/runs/formal-memory-use-v1-seed-9801/adapter")
    ),
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="run-relevant-memory-evaluation")
    parser.add_argument(
        "--arms",
        nargs="+",
        choices=tuple(ARM_ADAPTERS),
        default=["candidate_9201", "candidate_9202"],
    )
    parser.add_argument(
        "--presentations",
        nargs="+",
        choices=(LEGACY_PRESENTATION_VERSION, CONTEXT_PRESENTATION_VERSION),
        default=[LEGACY_PRESENTATION_VERSION, CONTEXT_PRESENTATION_VERSION],
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--suite",
        type=Path,
        default=Path("evals/fixtures/relevant_memory_use_v1.json"),
    )
    return parser


def _generate(model, tokenizer, messages: list[dict[str, str]]) -> str:
    import torch

    input_ids = tokenizer.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        enable_thinking=False,
        return_tensors="pt",
    ).to("cuda:0")
    attention = torch.ones_like(input_ids)
    generated: list[int] = []
    cache = None
    with torch.inference_mode():
        for _ in range(96):
            if cache is None:
                output = model(
                    input_ids=input_ids,
                    attention_mask=attention,
                    use_cache=True,
                )
            else:
                output = model(
                    input_ids=input_ids[:, -1:],
                    attention_mask=attention,
                    past_key_values=cache,
                    use_cache=True,
                )
            token = int(output.logits[:, -1, :].argmax(dim=-1).item())
            if token == tokenizer.eos_token_id:
                break
            generated.append(token)
            cache = output.past_key_values
            input_ids = torch.cat(
                [input_ids, torch.tensor([[token]], device=input_ids.device)],
                dim=1,
            )
            attention = torch.cat(
                [attention, torch.ones((1, 1), device=attention.device, dtype=attention.dtype)],
                dim=1,
            )
    return tokenizer.decode(generated, skip_special_tokens=True).strip()


def run(
    *,
    arms: list[str],
    presentations: list[str],
    output: Path,
    suite_path: Path,
) -> dict[str, Any]:
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, BitsAndBytesConfig

    if output.exists():
        raise FileExistsError(f"immutable evaluation output already exists: {output}")
    suite = load_suite(suite_path)
    registry = read_hashed_json(REGISTRY_PATH)
    registered = {
        item["adapter_version_id"]: item for item in registry["adapters"]
    }
    identity = IdentityLoader(Path("identity")).load().system_text()
    tokenizer = _load_tokenizer()
    quantization = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    report_arms = []
    started = time.perf_counter()
    for arm_name in arms:
        adapter_path = (PROJECT_ROOT / ARM_ADAPTERS[arm_name]).resolve()
        if arm_name.startswith("candidate_"):
            seed = arm_name.removeprefix("candidate_")
            adapter = registered[f"qwen3-8b-stage9a-qlora-seed-{seed}"]
            adapter_manifest_hash = adapter["adapter_manifest_hash"]
        else:
            adapter = read_hashed_json(adapter_path / "havre_adapter_manifest.json")
            adapter_manifest_hash = adapter["content_hash"]
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
        model = PeftModel.from_pretrained(base, adapter_path, is_trainable=False)
        model.eval()
        for presentation in presentations:
            rows = []
            for case in suite["cases"]:
                messages = prompt_messages(
                    case,
                    system_text=identity,
                    presentation_version=presentation,
                )
                text = _generate(model, tokenizer, messages)
                rows.append(
                    {
                        "kind": "paired_memory",
                        "case_id": case["case_id"],
                        "pair_id": case["pair_id"],
                        "variant": case["variant"],
                        "memory_context": case["memory_context"],
                        "output": text,
                        "prompt_hash": content_hash({"messages": messages}),
                        "scores": score_case(
                            case,
                            text,
                            global_forbidden_meta_phrases=suite[
                                "global_forbidden_meta_phrases"
                            ],
                        ),
                    }
                )
            for case in suite["multi_memory_cases"]:
                messages = prompt_messages(
                    case,
                    system_text=identity,
                    presentation_version=presentation,
                )
                text = _generate(model, tokenizer, messages)
                rows.append(
                    {
                        "kind": "multi_memory",
                        "case_id": case["case_id"],
                        "variant": case["variant"],
                        "memory_context": case["memory_context"],
                        "output": text,
                        "prompt_hash": content_hash({"messages": messages}),
                        "scores": score_case(
                            case,
                            text,
                            global_forbidden_meta_phrases=suite[
                                "global_forbidden_meta_phrases"
                            ],
                        ),
                    }
                )
            for case in suite["casual_regression_cases"]:
                prompt_case = {
                    "user_message": case["user_message"],
                    "memory_context": [],
                }
                messages = prompt_messages(
                    prompt_case,
                    system_text=identity,
                    presentation_version=presentation,
                )
                text = _generate(model, tokenizer, messages)
                rows.append(
                    {
                        "kind": "casual_regression",
                        "case_id": case["case_id"],
                        "output": text,
                        "prompt_hash": content_hash({"messages": messages}),
                        "scores": score_casual_case(
                            case,
                            text,
                            global_forbidden_meta_phrases=suite[
                                "global_forbidden_meta_phrases"
                            ],
                        ),
                    }
                )
            report_arms.append(
                {
                    "arm_name": arm_name,
                    "presentation_version": presentation,
                    "adapter_manifest_hash": adapter_manifest_hash,
                    "candidate_status_unchanged": True,
                    "results": rows,
                    "summary": summarize(rows),
                }
            )
        del model, base
        gc.collect()
        torch.cuda.empty_cache()
    output.parent.mkdir(parents=True, exist_ok=True)
    return write_hashed_json(
        output,
        {
            "schema_version": 1,
            "evaluation_id": f"{suite['suite_id']}-candidate-replay-v1",
            "suite_id": suite["suite_id"],
            "suite_hash": content_hash(suite),
            "status": "completed_candidate_only_evaluation",
            "candidate_status_changed": False,
            "promotion_authorized": False,
            "deployment_authorized": False,
            "stage9b_started": False,
            "training_performed": False,
            "contains_user_data": False,
            "privacy_class": "SYNTHETIC",
            "training_eligible": False,
            "validation_for_training": False,
            "source_revision": current_source_revision(PROJECT_ROOT),
            "registry_hash": registry["content_hash"],
            "arms": report_arms,
            "manual_rubric": suite["manual_rubric"],
            "limitations": [
                "Deterministic checks are diagnostics, not a substitute for paired semantic review.",
                "This replay measures the sealed development candidates on PUBLIC synthetic cases only.",
                "No result promotes, deploys, registers, or changes the lifecycle of a candidate.",
            ],
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "completed_at": datetime.now(UTC).isoformat(),
        },
    )


def main() -> None:
    args = _parser().parse_args()
    report = run(
        arms=list(args.arms),
        presentations=list(args.presentations),
        output=args.output.resolve(),
        suite_path=args.suite.resolve(),
    )
    print(report["content_hash"])


if __name__ == "__main__":
    main()
