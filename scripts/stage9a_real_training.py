"""Execute the approved Stage 9A real-training gates and candidate runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mlsys.training.stage9a_evaluation import (
    evaluate_four_arms,
    evaluate_owner_alignment_final,
    rescore_existing_evaluation,
)
from mlsys.training.stage9a_real import (
    build_rendered_artifacts,
    _standard_lora_gpu_only_probe_worker,
    diagnose_gate_c_gradients,
    gate_a_cuda,
    gate_b_load,
    gate_c_training_step,
    gate_c_reentrant_remediation_probe,
    gate_c_selective_logits_remediation_probe,
    gate_c_nonreentrant_selective_remediation_probe,
    gate_c_bf16_autocast_selective_remediation_probe,
    gate_c_frozen_io_bf16_selective_remediation_probe,
    gate_c_frozen_io_bf16_autocast_remediation_probe,
    gate_c_frozen_io_bf16_autocast_cache_trim_remediation_probe,
    gate_c_remediated_training_step,
    _selective_probe_boundary_worker,
    reload_adapter,
    SMOKE_RUN_ID,
    standard_lora_gpu_only_probe,
    train_qlora,
    verify_adapter_binding,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=(
            "gate-a", "render", "gate-b", "gate-c", "diagnose-gate-c",
            "diagnose-gate-c-eager", "gate-c-reentrant-probe",
            "gate-c-selective-logits-probe", "selective-boundary-worker",
            "gate-c-nonreentrant-selective-probe",
            "gate-c-bf16-autocast-selective-probe",
            "gate-c-frozen-io-bf16-selective-probe",
            "gate-c-frozen-io-bf16-autocast-probe",
            "gate-c-frozen-io-bf16-autocast-cache-trim-probe",
            "gate-c-remediated",
            "gate-d-smoke",
            "reload-adapter", "standard-lora-probe", "standard-lora-worker",
            "train", "verify-adapter",
            "evaluate", "rescore",
            "evaluate-owner-alignment",
        ),
    )
    parser.add_argument("--seed", type=int)
    parser.add_argument("--run-id")
    parser.add_argument("--adapter-dir", type=Path)
    parser.add_argument("--evaluation-id")
    parser.add_argument("--epochs", type=int, default=2)
    args = parser.parse_args()
    if args.command == "gate-a":
        result = gate_a_cuda()
    elif args.command == "render":
        result = build_rendered_artifacts()
    elif args.command == "gate-b":
        result = gate_b_load()
    elif args.command == "gate-c":
        result = gate_c_training_step()
    elif args.command == "gate-c-reentrant-probe":
        result = gate_c_reentrant_remediation_probe()
    elif args.command == "gate-c-selective-logits-probe":
        result = gate_c_selective_logits_remediation_probe()
    elif args.command == "gate-c-nonreentrant-selective-probe":
        result = gate_c_nonreentrant_selective_remediation_probe()
    elif args.command == "gate-c-bf16-autocast-selective-probe":
        result = gate_c_bf16_autocast_selective_remediation_probe()
    elif args.command == "gate-c-frozen-io-bf16-selective-probe":
        result = gate_c_frozen_io_bf16_selective_remediation_probe()
    elif args.command == "gate-c-frozen-io-bf16-autocast-probe":
        result = gate_c_frozen_io_bf16_autocast_remediation_probe()
    elif args.command == "gate-c-frozen-io-bf16-autocast-cache-trim-probe":
        result = gate_c_frozen_io_bf16_autocast_cache_trim_remediation_probe()
    elif args.command == "gate-c-remediated":
        result = gate_c_remediated_training_step()
    elif args.command == "selective-boundary-worker":
        result = _selective_probe_boundary_worker()
    elif args.command == "diagnose-gate-c":
        result = diagnose_gate_c_gradients()
    elif args.command == "diagnose-gate-c-eager":
        result = diagnose_gate_c_gradients(
            attn_implementation="eager",
            diagnostic_attempt=2,
        )
    elif args.command == "gate-d-smoke":
        result = train_qlora(
            seed=args.seed or 9001,
            run_id=args.run_id or SMOKE_RUN_ID,
            epochs=1,
            max_optimizer_steps=8,
            formal=False,
        )
    elif args.command == "reload-adapter":
        if args.adapter_dir is None:
            parser.error("--adapter-dir is required")
        result = reload_adapter(args.adapter_dir)
    elif args.command == "standard-lora-probe":
        result = standard_lora_gpu_only_probe()
    elif args.command == "standard-lora-worker":
        result = _standard_lora_gpu_only_probe_worker()
    elif args.command == "train":
        if args.seed is None or args.run_id is None:
            parser.error("--seed and --run-id are required")
        result = train_qlora(
            seed=args.seed,
            run_id=args.run_id,
            epochs=args.epochs,
            max_optimizer_steps=None,
            formal=True,
        )
    elif args.command == "verify-adapter":
        if args.adapter_dir is None:
            parser.error("--adapter-dir is required")
        result = verify_adapter_binding(args.adapter_dir)
    elif args.command == "evaluate":
        if args.adapter_dir is None or args.evaluation_id is None:
            parser.error("--adapter-dir and --evaluation-id are required")
        result = evaluate_four_arms(args.adapter_dir, evaluation_id=args.evaluation_id)
    elif args.command == "evaluate-owner-alignment":
        result = evaluate_owner_alignment_final()
    else:
        if args.evaluation_id is None:
            parser.error("--evaluation-id is required")
        result = rescore_existing_evaluation(args.evaluation_id)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
