"""Run a bounded in-memory v4 render check with the exact local Qwen tokenizer."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from evals.inference_runner import current_source_revision
from mlsys.training.stage9a_dataset_v4 import DATASET_ROOT, dataset_bundle_hash, load_and_verify_dataset
from mlsys.training.stage9a_provenance import PROJECT_ROOT
from mlsys.training.stage9a_real import (
    RENDERER_VERSION,
    _load_tokenizer,
    _render_example,
    _v4_context_messages,
    write_hashed_json,
)


OUTPUT = (
    PROJECT_ROOT
    / "evals"
    / "reports"
    / "stage9a_dataset_v4_review_correction2"
    / "renderer-check.json"
)


def verify() -> dict[str, object]:
    if OUTPUT.exists():
        raise FileExistsError("immutable v4 renderer check already exists")
    splits = load_and_verify_dataset(DATASET_ROOT)
    tokenizer = _load_tokenizer()
    cases = [
        next(item for item in splits["train"] if len(item["messages"]) >= 3),
        next(item for item in splits["train"] if item["use_memory_in_training"]),
        next(
            item for item in splits["train"]
            if item["context_kind"] == "authorized_proactive_rendering"
        ),
    ]
    checks = []
    for item in cases:
        rendered = _render_example(tokenizer, item)
        prompt_count = rendered["prompt_token_count"]
        if rendered["labels"][:prompt_count] != [-100] * prompt_count:
            raise ValueError("v4 prompt or historical context contains supervised labels")
        if not rendered["labels"][prompt_count:] or any(
            value == -100 for value in rendered["labels"][prompt_count:]
        ):
            raise ValueError("v4 final target supervision is incomplete")
        checks.append({
            "example_id": item["example_id"],
            "context_kind": rendered["context_kind"],
            "context_message_count": rendered["context_message_count"],
            "historical_assistant_message_count": rendered[
                "historical_assistant_message_count"
            ],
            "memory_injected": rendered["memory_injected"],
            "prompt_token_count": prompt_count,
            "assistant_token_count": rendered["assistant_token_count"],
            "all_context_labels_masked": True,
            "only_final_target_supervised": True,
        })
    holdout_memory = next(
        item for item in splits["holdout"] if item["use_memory_in_evaluation"]
    )
    holdout_messages = _v4_context_messages(
        holdout_memory,
        purpose="evaluation",
        memory_enabled=True,
    )
    return write_hashed_json(OUTPUT, {
        "schema_version": 1,
        "status": "passed",
        "check_kind": "bounded_in_memory_exact_tokenizer_no_formal_artifact",
        "dataset_bundle_hash": dataset_bundle_hash(DATASET_ROOT),
        "renderer_version": RENDERER_VERSION,
        "tokenizer_class": type(tokenizer).__name__,
        "checks": checks,
        "holdout_memory_example_id": holdout_memory["example_id"],
        "holdout_memory_context_injected": any(
            holdout_memory["memory_context"] in message["content"]
            for message in holdout_messages
        ),
        "formal_rendered_artifact_created": False,
        "training_started": False,
        "execution_source_snapshot": current_source_revision(PROJECT_ROOT),
        "completed_at": datetime.now(UTC).isoformat(),
    })


if __name__ == "__main__":
    print(json.dumps(verify(), ensure_ascii=False, indent=2, sort_keys=True))
