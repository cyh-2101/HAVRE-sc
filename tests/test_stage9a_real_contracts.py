from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from companion.hashing import content_hash
from evals.inference_runner import current_source_revision
from mlsys.training.stage9a_dataset_v4 import (
    DATASET_ROOT as V4_DATASET_ROOT,
    DATASET_VERSION,
    EXTERNAL_BUNDLE_HASH,
    OWNER_ALIGNMENT_CASE_FIELDS,
    _validate_owner_alignment_case_contract,
    dataset_bundle_hash,
    load_and_verify_dataset,
)
from mlsys.training.stage9a_real import (
    FORMAL_EVALUATION_IDS,
    FORMAL_RUN_IDS,
    GATE_A_EVIDENCE_NAME,
    GATE_B_EVIDENCE_NAME,
    REMEDIATED_GATE_C_EVIDENCE_NAME,
    RESOURCE_EVIDENCE_VERSION,
    SMOKE_RUN_ID,
    SUPERSEDED_FORMAL_REPORT_HASHES,
    SUPERSEDED_GATE_C_V4_HASH,
    SUPERSEDED_GATE_D_REPORT_HASH,
    _resource_evidence_is_within_stage9a_limits,
    _shared_gpu_mib,
    _iter_rendered,
    _require_current_adapter_training_binding,
    _validate_gate_d_readiness_records,
    _validate_formal_training_artifacts,
    _selective_causal_lm_loss,
    _selective_supervision,
    _restore_frozen_base_io_bf16,
    _select_longest_probe_row,
    _supervised_suffix_spec,
    build_rendered_artifacts,
    gate_c_reentrant_remediation_probe,
    gate_c_nonreentrant_selective_remediation_probe,
    gate_c_bf16_autocast_selective_remediation_probe,
    gate_c_frozen_io_bf16_selective_remediation_probe,
    gate_c_frozen_io_bf16_autocast_remediation_probe,
    gate_c_frozen_io_bf16_autocast_cache_trim_remediation_probe,
    gate_c_remediated_training_step,
    gate_c_selective_logits_remediation_probe,
    read_hashed_json,
    require_remediated_gate_c,
    reload_adapter,
    require_passed_evidence,
    sha256_file,
    standard_lora_gpu_only_probe,
    train_qlora,
    verify_adapter_binding,
    verify_training_input_boundary,
    write_hashed_json,
)
from mlsys.training.stage9a_registry import (
    REGISTRY_VALIDATION_SOURCE_COMMIT,
    REGISTRY_VALIDATION_SOURCE_SNAPSHOT,
    validate_owner_alignment_evidence,
    validate_run_evidence_bindings,
)
from mlsys.training.stage9a_registry import (
    _verify_sealed_evaluation_artifacts,
    decide_optional_third_seed,
    require_candidate_registry,
    require_compatibility_evidence,
    require_registry_validation_source,
    require_third_seed_decision,
)
from mlsys.training.stage9a_evaluation import (
    _owner_alignment_prompt_ids,
    _require_prior_owner_alignment_failure,
    _require_prior_owner_alignment_success,
    _score_owner_alignment_case,
    evaluate_owner_alignment_final,
)
from mlsys.training.stage9a_provenance import (
    FORMAL_EXECUTION_SOURCE_SNAPSHOT,
    PROJECT_ROOT,
    STAGE9A_ROOT,
    require_archived_source_snapshot,
    require_committed_source_snapshot_archive,
)
from mlsys.training.stage9a_rubric_v4 import score_v4_case, summarize_v4_scores


class _FakeQwenTokenizer:
    pad_token_id = 0

    def __len__(self) -> int:
        return 1024

    def apply_chat_template(
        self,
        messages,
        *,
        tokenize,
        add_generation_prompt,
        enable_thinking,
    ):
        del tokenize, enable_thinking
        prompt = [11, 12, 13, 99]
        if add_generation_prompt:
            return prompt
        return prompt + [21, 22, 23]


class Stage9ARealTrainingContractTests(unittest.TestCase):
    @staticmethod
    def _copy_v4_dataset(target: Path) -> None:
        shutil.copytree(V4_DATASET_ROOT, target)

    @staticmethod
    def _write_dataset_approval(evidence: Path, dataset: Path) -> None:
        write_hashed_json(evidence / "dataset-v4-po-freeze-approval.json", {
            "decision": "ACCEPT",
            "dataset_version": DATASET_VERSION,
            "dataset_bundle_hash": dataset_bundle_hash(dataset),
            "training_authorized": True,
            "owner_alignment_permanently_excluded": True,
            "stage9a_only": True,
            "promotion_authorized": False,
            "deployment_authorized": False,
        })

    @staticmethod
    def _valid_resource_evidence() -> dict[str, object]:
        baseline = {
            "resource_monitor_version": RESOURCE_EVIDENCE_VERSION,
            "recorded_at": "2026-08-21T12:00:00+08:00",
            "vram_used_mib": 0.0,
            "vram_free_mib": 11856.0,
            "shared_gpu_mib": 300.0,
            "ram_available_gib": 20.0,
            "ram_used_gib": 12.0,
            "swap_used_mib": 0.0,
            "stage9a_disk_gib": 30.0,
            "gpu_utilization_percent": 0.0,
            "gpu_temperature_c": 50.0,
            "gpu_power_w": 15.0,
        }
        final = {
            **baseline,
            "recorded_at": "2026-08-21T12:01:00+08:00",
            "vram_used_mib": 1000.0,
            "vram_free_mib": 10856.0,
            "shared_gpu_mib": 320.0,
            "ram_available_gib": 19.8,
            "ram_used_gib": 12.2,
            "gpu_utilization_percent": 70.0,
            "gpu_temperature_c": 65.0,
            "gpu_power_w": 100.0,
        }
        samples = [baseline, final]
        aggregate_fields = (
            "vram_used_mib", "shared_gpu_mib", "ram_available_gib",
            "ram_used_gib", "swap_used_mib", "stage9a_disk_gib",
            "gpu_utilization_percent", "gpu_temperature_c", "gpu_power_w",
        )
        return {
            "resource_monitor_version": RESOURCE_EVIDENCE_VERSION,
            "sample_count": len(samples),
            "hard_failure": None,
            "baseline": baseline,
            "final": final,
            "minimum": {
                field: min(sample[field] for sample in samples)
                for field in aggregate_fields
            },
            "maximum": {
                field: max(sample[field] for sample in samples)
                for field in aggregate_fields
            },
            "samples": samples,
        }

    def test_shared_gpu_counter_uses_typeperf_and_sums_all_adapters(self) -> None:
        output = (
            '"(PDH-CSV 4.0)","\\\\HOST\\GPU Adapter Memory(a)\\Shared Usage",'
            '"\\\\HOST\\GPU Adapter Memory(b)\\Shared Usage"\n'
            '"08/21/2026 08:52:09.845","314572800.000000","10485760.000000"\n'
        )
        with patch(
            "mlsys.training.stage9a_real.subprocess.run",
            return_value=SimpleNamespace(returncode=0, stdout=output, stderr=""),
        ) as run:
            self.assertEqual(_shared_gpu_mib(), 310.0)
        self.assertEqual(run.call_args.args[0][0], "typeperf.exe")
        self.assertIn(r"\GPU Adapter Memory(*)\Shared Usage", run.call_args.args[0])

    def test_shared_gpu_counter_timeout_fails_closed(self) -> None:
        with (
            patch(
                "mlsys.training.stage9a_real.subprocess.run",
                side_effect=subprocess.TimeoutExpired(["typeperf.exe"], timeout=15),
            ),
            self.assertRaisesRegex(RuntimeError, "counter collection timed out"),
        ):
            _shared_gpu_mib()

    def test_shared_gpu_counter_nonzero_exit_fails_closed(self) -> None:
        with (
            patch(
                "mlsys.training.stage9a_real.subprocess.run",
                return_value=SimpleNamespace(
                    returncode=1, stdout="", stderr="counter unavailable"
                ),
            ),
            self.assertRaisesRegex(RuntimeError, "collection failed"),
        ):
            _shared_gpu_mib()

    def test_shared_gpu_counter_empty_or_malformed_output_fails_closed(self) -> None:
        for output in ("", '"timestamp","not-a-number"\n'):
            with self.subTest(output=output), patch(
                "mlsys.training.stage9a_real.subprocess.run",
                return_value=SimpleNamespace(returncode=0, stdout=output, stderr=""),
            ), self.assertRaisesRegex(RuntimeError, "no valid sample"):
                _shared_gpu_mib()

    def test_shared_gpu_counter_nonfinite_or_negative_output_fails_closed(self) -> None:
        for value in ("NaN", "Infinity", "-1"):
            output = f'"timestamp","counter"\n"now","{value}"\n'
            with self.subTest(value=value), patch(
                "mlsys.training.stage9a_real.subprocess.run",
                return_value=SimpleNamespace(returncode=0, stdout=output, stderr=""),
            ), self.assertRaisesRegex(RuntimeError, "no valid sample"):
                _shared_gpu_mib()

    def test_shared_gpu_counter_missing_binary_fails_closed(self) -> None:
        with (
            patch(
                "mlsys.training.stage9a_real.subprocess.run",
                side_effect=FileNotFoundError("typeperf.exe"),
            ),
            self.assertRaises(FileNotFoundError),
        ):
            _shared_gpu_mib()

    def test_resource_evidence_recomputes_samples_and_rejects_forged_aggregates(
        self,
    ) -> None:
        def sample(**overrides: float) -> dict[str, object]:
            material: dict[str, object] = {
                "resource_monitor_version": RESOURCE_EVIDENCE_VERSION,
                "recorded_at": "2026-08-21T12:00:00+08:00",
                "vram_used_mib": 1000.0,
                "vram_free_mib": 10856.0,
                "shared_gpu_mib": 300.0,
                "ram_available_gib": 20.0,
                "ram_used_gib": 12.0,
                "swap_used_mib": 100.0,
                "stage9a_disk_gib": 25.0,
                "gpu_utilization_percent": 50.0,
                "gpu_temperature_c": 60.0,
                "gpu_power_w": 75.0,
            }
            material.update(overrides)
            return material

        safe = sample()
        forged = sample(
            vram_used_mib=12000.0,
            shared_gpu_mib=2000.0,
            swap_used_mib=1000.0,
            ram_available_gib=1.0,
            stage9a_disk_gib=100.0,
        )
        resources = {
            "resource_monitor_version": RESOURCE_EVIDENCE_VERSION,
            "sample_count": 2,
            "hard_failure": None,
            "baseline": safe,
            "final": safe,
            "minimum": {
                field: safe[field]
                for field in (
                    "vram_used_mib", "shared_gpu_mib", "ram_available_gib",
                    "ram_used_gib", "swap_used_mib", "stage9a_disk_gib",
                    "gpu_utilization_percent", "gpu_temperature_c", "gpu_power_w",
                )
            },
            "maximum": {
                field: safe[field]
                for field in (
                    "vram_used_mib", "shared_gpu_mib", "ram_available_gib",
                    "ram_used_gib", "swap_used_mib", "stage9a_disk_gib",
                    "gpu_utilization_percent", "gpu_temperature_c", "gpu_power_w",
                )
            },
            "samples": [safe, forged],
        }
        self.assertFalse(
            _resource_evidence_is_within_stage9a_limits(
                resources, peak_target_mib=11264.0
            )
        )

    @staticmethod
    def _valid_remediated_gate_c_payload(
        dataset: Path, snapshot: str
    ) -> dict[str, object]:
        return {
            "gate": "C",
            "probe": "stage9a-v4-remediated-formal-gate-c-v1",
            "status": "passed",
            "implementation_version": (
                "qwen3-v4-nf4-qlora-selective-bf16-cache-trim-v1"
            ),
            "loss_path_version": "qwen3-v4-supervised-suffix-selective-logits-v1",
            "prior_evidence_hash": (
                "sha256:09a5f932d80ea7f9d4a58ab6f7f52f839698a45159f9d220594d58d6b0dd80b2"
            ),
            "dataset_version": DATASET_VERSION,
            "dataset_bundle_hash": dataset_bundle_hash(dataset),
            "rendered_manifest_hash": (
                "sha256:8bad6bd7042b3039f549ea5f8080f5e4f63ed83582aa91aa5aa15ec42e1c659a"
            ),
            "gate_b_evidence_hash": "sha256:" + "6" * 64,
            "rendered_max_seq_length": 336,
            "execution_source_snapshot": snapshot,
            "candidate_only": True,
            "formal_training": False,
            "gate_d_authorized": True,
            "promotion_authorized": False,
            "deployment_authorized": False,
            "cpu_offload": False,
            "disk_offload": False,
            "real_forward": True,
            "real_backward": True,
            "real_optimizer_step": True,
            "loss": 6.0,
            "gradient_norm": 10.0,
            "all_gradient_tensors_finite": True,
            "gradient_tensor_count": 504,
            "optimizer_state_materialized": True,
            "optimizer_state_entries": 504,
            "optimizer_nonscalar_state_tensor_devices": ["cuda:0"],
            "model_parameter_devices": {"cuda:0": 4728763392},
            "trainable_parameters": 10911744,
            "sample_id": "stage9a-train-0211",
            "sample_token_length": 321,
            "supervised_suffix_token_count": 34,
            "selected_supervision": {
                "sequence_length": 321,
                "supervised_label_start": 287,
                "supervised_label_end_inclusive": 320,
                "selected_logit_start": 286,
                "selected_logit_end_inclusive": 319,
                "selected_logit_count": 34,
                "supervised_token_count": 34,
                "bf16_autocast_enabled": True,
                "logits_dtype": "torch.bfloat16",
            },
            "suffix_contract_summary": {
                "train": {"count": 300, "all_contiguous_supervised_suffix": True},
                "validation": {"count": 60, "all_contiguous_supervised_suffix": True},
            },
            "unchanged_training_configuration": {
                "attention_implementation": "eager",
                "base_repository": "Qwen/Qwen3-8B",
                "base_revision": "b968826d9c46dd6066d109eabc6255188de91218",
                "batch_size": 1,
                "bf16_autocast": True,
                "frozen_base_io_bf16_restored": True,
                "learning_rate": 2e-4,
                "lora_alpha": 8,
                "lora_dropout": 0.05,
                "lora_rank": 4,
                "lora_target_modules": "all-linear",
                "loss_reduction": "mean_over_supervised_target_tokens",
                "max_seq_length": 336,
                "optimizer": "torch.optim.AdamW_no_paging",
                "quantization": "nf4_double_quant_bf16_compute",
                "release_cuda_cache_before_optimizer": True,
                "weight_decay": 0.0,
            },
            "frozen_base_io_dtype_evidence": {
                "base_manifest_torch_dtype": "bfloat16",
                "total_saved_mib": 2374.0,
                "trainable_parameters_changed": False,
            },
            "nvidia_smi_peak_vram_mib": 8936.0,
            "torch_peak_allocated_mib": 10556.0,
            "torch_peak_reserved_mib": 10988.0,
            "shared_gpu_growth_mib": 0.0,
            "swap_growth_mib": 8.0,
            "resources": {
                "resource_monitor_version": RESOURCE_EVIDENCE_VERSION,
                "hard_failure": None,
                "samples": [{"resource_monitor_version": RESOURCE_EVIDENCE_VERSION}],
                "baseline": {"ram_available_gib": 20.5},
                "maximum": {"vram_used_mib": 8936.0},
            },
            "configuration_delta": {
                "supersedes_resource_evidence_hash": SUPERSEDED_GATE_C_V4_HASH,
            },
            "torch_memory_stages": {
                "before_cache_release": {"reserved_mib": 10988.0},
                "after_cache_release_before_optimizer": {"reserved_mib": 8614.0},
            },
        }

    @staticmethod
    def _write_v4_gate_a(evidence: Path, dataset: Path) -> None:
        write_hashed_json(evidence / GATE_A_EVIDENCE_NAME, {
            "gate": "A",
            "status": "passed",
            "execution_source_snapshot": current_source_revision(PROJECT_ROOT),
            "intended_dataset_version": DATASET_VERSION,
            "intended_dataset_bundle_hash": dataset_bundle_hash(dataset),
        })

    def test_hashed_json_detects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            write_hashed_json(path, {"candidate_only": True})
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["candidate_only"] = False
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "content hash mismatch"):
                read_hashed_json(path)

    def test_wrong_adapter_revision_fails_before_load(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            adapter = Path(directory)
            (adapter / "adapter_model.safetensors").write_bytes(b"adapter")
            (adapter / "adapter_config.json").write_text("{}", encoding="utf-8")
            manifest = {
                "schema_version": 1,
                "base_repository": "Qwen/Qwen3-8B",
                "base_revision": "b968826d9c46dd6066d109eabc6255188de91218",
                "base_provenance_hash": "sha256:" + "1" * 64,
                "adapter_file": "adapter_model.safetensors",
                "adapter_sha256": "sha256:" + "2" * 64,
                "adapter_config_sha256": "sha256:" + "3" * 64,
                "candidate_only": True,
                "promotion_authorized": False,
                "deployment_authorized": False,
            }
            write_hashed_json(adapter / "havre_adapter_manifest.json", manifest)
            with self.assertRaisesRegex(ValueError, "exact base revision"):
                verify_adapter_binding(
                    adapter,
                    expected_revision="0" * 40,
                )

    def test_failed_or_wrong_gate_evidence_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gate.json"
            write_hashed_json(path, {"gate": "B", "status": "failed"})
            with self.assertRaisesRegex(RuntimeError, "did not pass"):
                require_passed_evidence(path, expected_gate="B")
            write_hashed_json(path, {"gate": "A", "status": "passed"})
            with self.assertRaisesRegex(RuntimeError, "wrong gate"):
                require_passed_evidence(path, expected_gate="B")

    def test_reentrant_probe_selects_only_the_321_token_maximum(self) -> None:
        rows = [
            {"example_id": "short", "total_token_count": 263},
            {"example_id": "longest", "total_token_count": 321},
            {"example_id": "middle", "total_token_count": 300},
        ]
        self.assertEqual(_select_longest_probe_row(rows)["example_id"], "longest")
        with self.assertRaisesRegex(ValueError, "321-token maximum"):
            _select_longest_probe_row(rows[:1])

    def test_reentrant_probe_evidence_is_single_use_before_any_model_load(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory)
            (evidence / "gate-c-v4-reentrant-remediation-probe-1.json").write_text(
                "already exists", encoding="utf-8"
            )
            with (
                patch("mlsys.training.stage9a_real.EVIDENCE_ROOT", evidence),
                self.assertRaisesRegex(FileExistsError, "immutable reentrant"),
            ):
                gate_c_reentrant_remediation_probe()

    def test_selective_probe_evidence_is_single_use_before_any_model_load(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory)
            (evidence / "gate-c-v4-selective-logits-remediation-probe-1.json").write_text(
                "already exists", encoding="utf-8"
            )
            with (
                patch("mlsys.training.stage9a_real.EVIDENCE_ROOT", evidence),
                self.assertRaisesRegex(FileExistsError, "immutable selective-logits"),
            ):
                gate_c_selective_logits_remediation_probe()

    def test_nonreentrant_selective_probe_is_single_use_before_model_load(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory)
            (
                evidence / "gate-c-v4-nonreentrant-selective-remediation-probe-1.json"
            ).write_text("already exists", encoding="utf-8")
            with (
                patch("mlsys.training.stage9a_real.EVIDENCE_ROOT", evidence),
                self.assertRaisesRegex(FileExistsError, "immutable non-reentrant selective"),
            ):
                gate_c_nonreentrant_selective_remediation_probe()

    def test_bf16_autocast_selective_probe_is_single_use_before_model_load(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory)
            (
                evidence / "gate-c-v4-bf16-autocast-selective-remediation-probe-1.json"
            ).write_text("already exists", encoding="utf-8")
            with (
                patch("mlsys.training.stage9a_real.EVIDENCE_ROOT", evidence),
                self.assertRaisesRegex(FileExistsError, "immutable non-reentrant selective"),
            ):
                gate_c_bf16_autocast_selective_remediation_probe()

    def test_frozen_io_bf16_restoration_preserves_values_and_frozen_status(self) -> None:
        import torch

        class _FrozenIO(torch.nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.input = torch.nn.Embedding(8, 4, dtype=torch.float32)
                self.output = torch.nn.Linear(4, 8, bias=False, dtype=torch.float32)
                with torch.no_grad():
                    values = torch.arange(32, dtype=torch.bfloat16).reshape(8, 4)
                    self.input.weight.copy_(values.float())
                    self.output.weight.copy_((values / 8).float())
                self.input.weight.requires_grad = False
                self.output.weight.requires_grad = False

            def get_input_embeddings(self):
                return self.input

            def get_output_embeddings(self):
                return self.output

        model = _FrozenIO()
        input_before = model.input.weight.detach().clone()
        output_before = model.output.weight.detach().clone()
        evidence = _restore_frozen_base_io_bf16(model)
        self.assertEqual(model.input.weight.dtype, torch.bfloat16)
        self.assertEqual(model.output.weight.dtype, torch.bfloat16)
        self.assertFalse(model.input.weight.requires_grad)
        self.assertFalse(model.output.weight.requires_grad)
        torch.testing.assert_close(model.input.weight.float(), input_before, rtol=0, atol=0)
        torch.testing.assert_close(model.output.weight.float(), output_before, rtol=0, atol=0)
        self.assertEqual(evidence["total_saved_bytes"], 32 * 2 * 2)
        self.assertFalse(evidence["trainable_parameters_changed"])

    def test_frozen_io_bf16_probe_is_single_use_before_model_load(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory)
            (
                evidence / "gate-c-v4-frozen-io-bf16-selective-remediation-probe-1.json"
            ).write_text("already exists", encoding="utf-8")
            with (
                patch("mlsys.training.stage9a_real.EVIDENCE_ROOT", evidence),
                self.assertRaisesRegex(FileExistsError, "immutable non-reentrant selective"),
            ):
                gate_c_frozen_io_bf16_selective_remediation_probe()

    def test_frozen_io_bf16_autocast_probe_is_single_use_before_model_load(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory)
            (
                evidence / "gate-c-v4-frozen-io-bf16-autocast-selective-probe-1.json"
            ).write_text("already exists", encoding="utf-8")
            with (
                patch("mlsys.training.stage9a_real.EVIDENCE_ROOT", evidence),
                self.assertRaisesRegex(FileExistsError, "immutable non-reentrant selective"),
            ):
                gate_c_frozen_io_bf16_autocast_remediation_probe()

    def test_frozen_io_bf16_autocast_cache_trim_probe_is_single_use(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory)
            (
                evidence
                / "gate-c-v4-frozen-io-bf16-autocast-cache-trim-selective-probe-1.json"
            ).write_text("already exists", encoding="utf-8")
            with (
                patch("mlsys.training.stage9a_real.EVIDENCE_ROOT", evidence),
                self.assertRaisesRegex(FileExistsError, "immutable non-reentrant selective"),
            ):
                gate_c_frozen_io_bf16_autocast_cache_trim_remediation_probe()

    def test_frozen_io_bf16_autocast_cache_trim_probe_is_exactly_scoped(self) -> None:
        with patch(
            "mlsys.training.stage9a_real."
            "gate_c_nonreentrant_selective_remediation_probe",
            return_value={"status": "passed"},
        ) as delegate:
            result = gate_c_frozen_io_bf16_autocast_cache_trim_remediation_probe()
        self.assertEqual(result, {"status": "passed"})
        kwargs = delegate.call_args.kwargs
        self.assertTrue(kwargs["use_bf16_autocast"])
        self.assertTrue(kwargs["restore_frozen_base_io_bf16"])
        self.assertTrue(kwargs["prior_already_restored_io"])
        self.assertTrue(kwargs["release_cuda_cache_before_optimizer"])
        self.assertFalse(kwargs["expected_prior_reentrant"])
        self.assertEqual(
            kwargs["expected_prior_failure_message"],
            "nonreentrant_selective_peak_vram_above_11_0_gib",
        )

    def test_remediated_gate_c_executes_the_reviewed_path_unchanged(self) -> None:
        with patch(
            "mlsys.training.stage9a_real."
            "gate_c_nonreentrant_selective_remediation_probe",
            return_value={"gate": "C", "status": "passed"},
        ) as delegate:
            result = gate_c_remediated_training_step()
        self.assertEqual(result, {"gate": "C", "status": "passed"})
        kwargs = delegate.call_args.kwargs
        self.assertEqual(kwargs["evidence_gate"], "C")
        self.assertEqual(kwargs["expected_prior_status"], "passed")
        self.assertIsNone(kwargs["expected_prior_failure_message"])
        self.assertTrue(kwargs["use_bf16_autocast"])
        self.assertTrue(kwargs["restore_frozen_base_io_bf16"])
        self.assertTrue(kwargs["release_cuda_cache_before_optimizer"])
        self.assertTrue(
            kwargs["configuration_delta_override"]["objective_unchanged"]
        )

    def test_remediated_gate_c_requirement_is_exact_and_source_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "evidence"
            dataset = root / "dataset"
            self._copy_v4_dataset(dataset)
            snapshot = "sha256:" + "7" * 64
            valid = self._valid_remediated_gate_c_payload(dataset, snapshot)
            gate_b = write_hashed_json(
                evidence / GATE_B_EVIDENCE_NAME,
                {"gate": "B", "status": "passed"},
            )
            valid["gate_b_evidence_hash"] = gate_b["content_hash"]
            report = write_hashed_json(
                evidence / REMEDIATED_GATE_C_EVIDENCE_NAME, valid
            )
            with (
                patch("mlsys.training.stage9a_real.EVIDENCE_ROOT", evidence),
                patch("mlsys.training.stage9a_real.DATASET_ROOT", dataset),
                patch(
                    "mlsys.training.stage9a_real.require_archived_source_snapshot",
                    return_value={"snapshot": snapshot},
                ),
            ):
                self.assertEqual(
                    require_remediated_gate_c()["content_hash"],
                    report["content_hash"],
                )
            with (
                patch("mlsys.training.stage9a_real.EVIDENCE_ROOT", evidence),
                patch("mlsys.training.stage9a_real.DATASET_ROOT", dataset),
                patch(
                    "mlsys.training.stage9a_real.require_archived_source_snapshot",
                    return_value={"snapshot": "sha256:" + "8" * 64},
                ),
                self.assertRaisesRegex(RuntimeError, "stale or cross-bound"),
            ):
                require_remediated_gate_c()

            attacks = {
                "missing_real_backward": lambda item: item.pop("real_backward"),
                "gate_d_not_authorized": lambda item: item.__setitem__(
                    "gate_d_authorized", False
                ),
                "wrong_rendered_manifest": lambda item: item.__setitem__(
                    "rendered_manifest_hash", "sha256:" + "0" * 64
                ),
                "cache_trim_not_enabled": lambda item: item[
                    "unchanged_training_configuration"
                ].__setitem__("release_cuda_cache_before_optimizer", False),
                "nvidia_peak_above_target": lambda item: (
                    item.__setitem__("nvidia_smi_peak_vram_mib", 11265.0),
                    item["resources"]["maximum"].__setitem__(
                        "vram_used_mib", 11265.0
                    ),
                ),
            }
            for name, mutate in attacks.items():
                with self.subTest(name=name):
                    forged = deepcopy(valid)
                    mutate(forged)
                    write_hashed_json(
                        evidence / REMEDIATED_GATE_C_EVIDENCE_NAME,
                        forged,
                    )
                    with (
                        patch("mlsys.training.stage9a_real.EVIDENCE_ROOT", evidence),
                        patch("mlsys.training.stage9a_real.DATASET_ROOT", dataset),
                        patch(
                            "mlsys.training.stage9a_real.require_archived_source_snapshot",
                            return_value={"snapshot": snapshot},
                        ),
                        self.assertRaisesRegex(RuntimeError, "stale or cross-bound"),
                    ):
                        require_remediated_gate_c()

    def test_adapter_training_binding_rejects_source_drift(self) -> None:
        gate = {
            "content_hash": "sha256:" + "1" * 64,
            "execution_source_snapshot": "sha256:" + "2" * 64,
        }
        manifest = {
            "training_implementation": (
                "qwen3-v4-nf4-qlora-selective-bf16-cache-trim-v1"
            ),
            "remediated_gate_c_hash": gate["content_hash"],
            "execution_source_snapshot": gate["execution_source_snapshot"],
        }
        with patch(
            "mlsys.training.stage9a_real.require_remediated_gate_c",
            return_value=gate,
        ):
            self.assertEqual(
                _require_current_adapter_training_binding(manifest), gate
            )
            manifest["execution_source_snapshot"] = "sha256:" + "3" * 64
            with self.assertRaisesRegex(ValueError, "source/Gate C"):
                _require_current_adapter_training_binding(manifest)

    def test_gate_d_readiness_rejects_self_signed_or_truncated_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "dataset"
            self._copy_v4_dataset(dataset)
            source = "sha256:" + "1" * 64
            gate_hash = "sha256:" + "2" * 64
            adapter_hash = "sha256:" + "3" * 64

            def resources() -> dict[str, object]:
                return self._valid_resource_evidence()

            gate = {"content_hash": gate_hash, "execution_source_snapshot": source}
            adapter = {
                "content_hash": adapter_hash,
                "run_id": SMOKE_RUN_ID,
                "seed": 9001,
                "execution_source_snapshot": source,
                "remediated_gate_c_hash": gate_hash,
                "resource_monitor_version": RESOURCE_EVIDENCE_VERSION,
            }
            history = [
                {
                    "optimizer_step": index,
                    "loss": 5.0,
                    "gradient_norm": 1.0,
                    "selected_logit_count": 20,
                }
                for index in range(1, 9)
            ]
            smoke = {
                "run_id": SMOKE_RUN_ID,
                "gate": "D",
                "seed": 9001,
                "formal": False,
                "status": "completed_candidate",
                "candidate_only": True,
                "promotion_authorized": False,
                "deployment_authorized": False,
                "contains_user_data": False,
                "execution_source_snapshot": source,
                "training_implementation": (
                    "qwen3-v4-nf4-qlora-selective-bf16-cache-trim-v1"
                ),
                "resource_monitor_version": RESOURCE_EVIDENCE_VERSION,
                "supersedes_training_report_hash": SUPERSEDED_GATE_D_REPORT_HASH,
                "loss_path_version": (
                    "qwen3-v4-supervised-suffix-selective-logits-v1"
                ),
                "remediated_gate_c_hash": gate_hash,
                "dataset_bundle_hash": dataset_bundle_hash(dataset),
                "rendered_manifest_hash": (
                    "sha256:8bad6bd7042b3039f549ea5f8080f5e4f63ed83582aa91aa5aa15ec42e1c659a"
                ),
                "attention_implementation": "eager",
                "lora": {
                    "rank": 4,
                    "alpha": 8,
                    "dropout": 0.05,
                    "target_modules": "all-linear",
                },
                "optimizer": "torch.optim.AdamW_no_paging",
                "bf16_autocast": True,
                "frozen_base_io_bf16_restored": True,
                "gradient_checkpointing_use_reentrant": False,
                "release_cuda_cache_before_optimizer": True,
                "trainable_parameters": 10911744,
                "max_seq_length": 336,
                "history": history,
                "training_summary": {
                    "epochs_requested": 1,
                    "optimizer_steps": 8,
                    "initial_validation_loss": 6.0,
                    "final_validation_loss": 5.5,
                    "peak_vram_mib": 10988.0,
                    "nvidia_smi_peak_vram_mib": 9000.0,
                    "torch_peak_allocated_mib": 10556.0,
                    "torch_peak_reserved_mib": 10988.0,
                },
                "resource_evidence": resources(),
                "adapter_manifest_hash": adapter_hash,
            }
            reload_report = {
                "gate": "D-reload",
                "status": "passed",
                "candidate_only": True,
                "promotion_authorized": False,
                "deployment_authorized": False,
                "contains_user_data": False,
                "execution_source_snapshot": source,
                "training_implementation": (
                    "qwen3-v4-nf4-qlora-selective-bf16-cache-trim-v1"
                ),
                "adapter_manifest_hash": adapter_hash,
                "new_process_reload": True,
                "finite_logits": True,
                "adapter_load_seconds": 1.0,
                "resources": resources(),
            }
            with patch("mlsys.training.stage9a_real.DATASET_ROOT", dataset):
                _validate_gate_d_readiness_records(
                    smoke=smoke,
                    reload_report=reload_report,
                    adapter=adapter,
                    gate_c=gate,
                )
                attacks = {
                    "wrong_seed": ("smoke", "seed", 9002),
                    "missing_exact_epoch": (
                        "summary", "epochs_requested", None
                    ),
                    "reload_not_fresh": (
                        "reload", "new_process_reload", False
                    ),
                    "reload_nonfinite": ("reload", "finite_logits", False),
                    "reload_resource_failure": (
                        "reload_resources", "hard_failure", "vram"
                    ),
                }
                for name, (target, key, value) in attacks.items():
                    with self.subTest(name=name):
                        forged_smoke = deepcopy(smoke)
                        forged_reload = deepcopy(reload_report)
                        if target == "smoke":
                            forged_smoke[key] = value
                        elif target == "summary":
                            forged_smoke["training_summary"][key] = value
                        elif target == "reload":
                            forged_reload[key] = value
                        else:
                            forged_reload["resources"][key] = value
                        with self.assertRaisesRegex(
                            RuntimeError, "incomplete or cross-bound"
                        ):
                            _validate_gate_d_readiness_records(
                                smoke=forged_smoke,
                                reload_report=forged_reload,
                                adapter=adapter,
                                gate_c=gate,
                            )

    def test_reload_evidence_is_immutable_before_model_load(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            adapter = Path(directory) / "adapter"
            adapter.mkdir()
            (adapter.parent / "reload-report.json").write_text(
                "already exists", encoding="utf-8"
            )
            with self.assertRaisesRegex(FileExistsError, "immutable adapter reload"):
                reload_adapter(adapter)

    def test_preflight_failure_does_not_poison_immutable_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rendered = root / "rendered"
            rendered.mkdir()
            write_hashed_json(
                rendered / "manifest.json", {"chosen_max_seq_length": 336}
            )
            safe_boundary = {
                "contains_user_data": False,
                "all_members_training_eligible": True,
                "source_kinds": ["synthetic_fixture"],
            }
            with (
                patch("mlsys.training.stage9a_real.RUNS_ROOT", root / "runs"),
                patch("mlsys.training.stage9a_real.RENDERED_ROOT", rendered),
                patch("mlsys.training.stage9a_real.require_dataset_freeze_approval"),
                patch(
                    "mlsys.training.stage9a_real.require_remediated_gate_c",
                    return_value={"content_hash": "sha256:" + "4" * 64},
                ),
                patch(
                    "mlsys.training.stage9a_real._load_tokenizer",
                    return_value=_FakeQwenTokenizer(),
                ),
                patch(
                    "mlsys.training.stage9a_real.verify_training_input_boundary",
                    return_value=safe_boundary,
                ),
                patch(
                    "mlsys.training.stage9a_real.resource_snapshot",
                    return_value={"ram_available_gib": 10.0},
                ),
                self.assertRaisesRegex(RuntimeError, "available RAM"),
            ):
                train_qlora(
                    seed=9001,
                    run_id=SMOKE_RUN_ID,
                    epochs=1,
                    max_optimizer_steps=8,
                    formal=False,
                )
            self.assertFalse((root / "runs" / SMOKE_RUN_ID).exists())

    def test_formal_duplicate_seed_check_precedes_run_creation_and_monitor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runs = Path(directory) / "runs"
            smoke = runs / "gate-d-smoke-v4"
            smoke.mkdir(parents=True)
            snapshot = "sha256:" + "5" * 64
            gate_hash = "sha256:" + "6" * 64
            adapter_hash = "sha256:" + "7" * 64
            write_hashed_json(smoke / "training-report.json", {
                "run_id": "gate-d-smoke-v4",
                "gate": "D",
                "formal": False,
                "status": "completed_candidate",
                "candidate_only": True,
                "promotion_authorized": False,
                "deployment_authorized": False,
                "contains_user_data": False,
                "execution_source_snapshot": snapshot,
                "training_implementation": (
                    "qwen3-v4-nf4-qlora-selective-bf16-cache-trim-v1"
                ),
                "remediated_gate_c_hash": gate_hash,
                "adapter_manifest_hash": adapter_hash,
                "training_summary": {"optimizer_steps": 8},
            })
            write_hashed_json(smoke / "reload-report.json", {
                "gate": "D-reload",
                "status": "passed",
                "candidate_only": True,
                "promotion_authorized": False,
                "deployment_authorized": False,
                "contains_user_data": False,
                "execution_source_snapshot": snapshot,
                "training_implementation": (
                    "qwen3-v4-nf4-qlora-selective-bf16-cache-trim-v1"
                ),
                "adapter_manifest_hash": adapter_hash,
            })
            prior = runs / "current-seed-9201"
            prior.mkdir()
            write_hashed_json(prior / "training-report.json", {
                "run_id": "current-seed-9201",
                "formal": True,
                "status": "completed_candidate",
                "seed": 9201,
                "training_summary": {"wall_time_seconds": 1.0},
            })
            with (
                patch("mlsys.training.stage9a_real.RUNS_ROOT", runs),
                patch("mlsys.training.stage9a_real.require_dataset_freeze_approval"),
                patch(
                    "mlsys.training.stage9a_real.require_remediated_gate_c",
                    return_value={"content_hash": gate_hash},
                ),
                patch(
                    "mlsys.training.stage9a_real.require_gate_d_readiness",
                    return_value={
                        "gate_c": {"content_hash": gate_hash},
                        "smoke": {},
                    },
                ),
                patch(
                    "mlsys.training.stage9a_real.current_source_revision",
                    return_value=snapshot,
                ),
                self.assertRaisesRegex(ValueError, "seed already exists"),
            ):
                train_qlora(
                    seed=9201,
                    run_id=FORMAL_RUN_IDS[9201],
                    epochs=2,
                    max_optimizer_steps=None,
                    formal=True,
                )
            self.assertFalse((runs / FORMAL_RUN_IDS[9201]).exists())

    def test_third_seed_decision_does_not_use_owner_alignment_or_spare_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "evidence"
            formal_runs = []
            reports = {}
            evaluations = {}
            run_map = {}
            for seed in (9201, 9202):
                checks = {
                    "exact": {
                        "case_count": 12,
                        "pass_count": 12,
                        "pass_rate": 1.0,
                    }
                }
                arms = [
                    {
                        "arm": name,
                        "behavioral_metrics": {
                            "behavioral_rubric": {
                                "deterministic_property_checks": checks
                            }
                        },
                    }
                    for name in (
                        "base", "base_memory", "base_adapter", "base_memory_adapter"
                    )
                ]
                adapter_hash = "sha256:" + str(seed)[-1] * 64
                run = {
                    "seed": seed,
                    "adapter_manifest_hash": adapter_hash,
                    "wall_time_seconds": 100.0,
                }
                formal_runs.append(run)
                run_map[seed] = run
                reports[seed] = {
                    "content_hash": "sha256:" + str(seed)[-1] * 63 + "a",
                    "training_summary": {"final_validation_loss": 5.0},
                }
                evaluations[seed] = {
                    "content_hash": "sha256:" + str(seed)[-1] * 63 + "e",
                    "arms": arms,
                }
            with (
                patch(
                    "mlsys.training.stage9a_registry.THIRD_SEED_DECISION_EVIDENCE",
                    evidence / "third-seed-justification-v4.json",
                ),
                patch(
                    "mlsys.training.stage9a_registry.completed_formal_runs",
                    return_value=formal_runs,
                ),
                patch(
                    "mlsys.training.stage9a_registry.current_source_revision",
                    return_value="sha256:" + "9" * 64,
                ),
                patch(
                    "mlsys.training.stage9a_registry._first_two_exact_decision_inputs",
                    return_value=(run_map, reports, evaluations),
                ),
            ):
                decision = decide_optional_third_seed()
            self.assertEqual(
                decision["decision"], "do_not_run_optional_third_seed"
            )
            self.assertFalse(decision["owner_alignment_opened"])
            self.assertFalse(decision["owner_alignment_used_for_seed_decision"])
            self.assertTrue(decision["not_triggered_by_remaining_budget"])
            self.assertFalse(decision["variance_estimation_value"])

    def test_forged_minimal_third_seed_decision_fails_exact_recomputation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "third-seed-justification-v4.json"
            forged = write_hashed_json(path, {
                "decision": "run_optional_third_seed",
                "variance_estimation_value": True,
                "resources_sufficient": True,
            })
            with (
                patch(
                    "mlsys.training.stage9a_registry.THIRD_SEED_DECISION_EVIDENCE",
                    path,
                ),
                patch(
                    "mlsys.training.stage9a_registry._first_two_exact_decision_inputs",
                    return_value=({}, {}, {}),
                ),
                patch(
                    "mlsys.training.stage9a_registry._calculate_third_seed_decision",
                    return_value={"decision": "do_not_run_optional_third_seed"},
                ),
                patch(
                    "mlsys.training.stage9a_registry._formal_execution_source_snapshot",
                    return_value="sha256:" + "8" * 64,
                ),
                self.assertRaisesRegex(ValueError, "forged, stale, or cross-bound"),
            ):
                require_third_seed_decision()
            self.assertEqual(read_hashed_json(path)["content_hash"], forged["content_hash"])

    def test_self_signed_compatibility_probe_names_are_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "compatibility.json"
            names = (
                "wrong_exact_revision", "wrong_base_artifact",
                "incompatible_adapter_configuration", "incompatible_target_modules",
                "incompatible_structural_flag",
            )
            write_hashed_json(path, {
                "suite": "stage9a-exact-adapter-compatibility-v2",
                "status": "passed",
                "candidate_only": True,
                "promotion_authorized": False,
                "deployment_authorized": False,
                "contains_user_data": False,
                "execution_source_snapshot": "sha256:" + "1" * 64,
                "temporary_probe_artifacts_removed": True,
                "correct_exact_bindings": [],
                "fail_closed_probes": [
                    {"probe": name, "status": "passed_rejected"} for name in names
                ],
            })
            with (
                patch(
                    "mlsys.training.stage9a_registry.COMPATIBILITY_EVIDENCE", path
                ),
                patch(
                    "mlsys.training.stage9a_registry.completed_formal_runs",
                    return_value=[],
                ),
                patch(
                    "mlsys.training.stage9a_registry._formal_execution_source_snapshot",
                    return_value="sha256:" + "1" * 64,
                ),
                self.assertRaisesRegex(ValueError, "forged, stale, or cross-bound"),
            ):
                require_compatibility_evidence()

    def test_owner_alignment_cannot_open_before_seed_plan_closure(self) -> None:
        temp_parent = STAGE9A_ROOT / "tmp"
        temp_parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            dir=temp_parent, prefix="owner-alignment-order-contract-"
        ) as directory:
            with (
                patch("mlsys.training.stage9a_evaluation.RUNS_ROOT", Path(directory)),
                patch(
                    "mlsys.training.stage9a_registry.require_final_alignment_readiness",
                    side_effect=RuntimeError(
                        "Owner Alignment requires the closed formal seed plan"
                    ),
                ),
                patch(
                    "mlsys.training.stage9a_evaluation.load_and_verify_owner_alignment"
                ) as owner_loader,
                self.assertRaisesRegex(RuntimeError, "closed formal seed plan"),
            ):
                evaluate_owner_alignment_final()
            owner_loader.assert_not_called()

    def test_owner_alignment_prompt_and_score_use_case_only_at_final_eval(self) -> None:
        class _OwnerTokenizer:
            def apply_chat_template(self, messages, **kwargs):
                self.messages = messages
                self.kwargs = kwargs
                return [1, 2, 3]

        tokenizer = _OwnerTokenizer()
        case = {
            "messages": [{"role": "user", "content": "Hello"}],
            "expected_text": "Hi",
            "title": "Greeting",
            "notes": "Review warmth and naturalness.",
            "relationship_spec_version": "HAVRE_VOICE_RELATIONSHIP_SPEC_v1",
        }
        self.assertEqual(
            _owner_alignment_prompt_ids(tokenizer, case, system_text="System"),
            [1, 2, 3],
        )
        self.assertEqual(tokenizer.messages[-1]["content"], "Hello")
        scores = _score_owner_alignment_case(case, "Hi")
        self.assertIsNone(scores["overall_score"])
        self.assertEqual(
            scores["diagnostics"]["reference_similarity_role"],
            "diagnostic_only_not_primary_companion_quality",
        )
        self.assertEqual(
            scores["product_owner_review"]["status"],
            "product_owner_review_required",
        )
        self.assertNotIn("deterministic_property_checks", scores)
        with self.assertRaisesRegex(ValueError, "must not supply training-style memory"):
            _owner_alignment_prompt_ids(
                tokenizer,
                {**case, "inject_memory_context": True, "memory_context": "private"},
                system_text="System",
            )

    def test_owner_alignment_canonical_schema_fails_closed_before_evaluation(self) -> None:
        case = {
            "case_id": "owner-test-1",
            "contains_user_data": True,
            "content_hash": "sha256:" + "0" * 64,
            "evaluation_only": True,
            "expected_text": "Expected",
            "hyperparameter_tuning_eligible": False,
            "local_only": True,
            "messages": [{"role": "user", "content": "Hello"}],
            "notes": "Product Owner review.",
            "privacy_class": "PRIVATE",
            "prompt_tuning_eligible": False,
            "relationship_spec_version": "HAVRE_VOICE_RELATIONSHIP_SPEC_v1",
            "schema_version": 1,
            "source_kind": "product_owner_calibrated_anchor",
            "synthetic_generation_input_eligible": False,
            "title": "Greeting",
            "training_eligible": False,
            "validation_for_training": False,
        }
        self.assertEqual(set(case), OWNER_ALIGNMENT_CASE_FIELDS)
        _validate_owner_alignment_case_contract(case)
        with self.assertRaisesRegex(ValueError, "fields differ"):
            _validate_owner_alignment_case_contract({**case, "system_text": "forged"})
        with self.assertRaisesRegex(ValueError, "invalid message history"):
            _validate_owner_alignment_case_contract({
                **case,
                "messages": [
                    {"role": "user", "content": "one"},
                    {"role": "user", "content": "two"},
                ],
            })

    def test_owner_alignment_prior_failure_rejects_resigned_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "failure.json"
            original = write_hashed_json(path, {
                "status": "failed",
                "error": {
                    "type": "ValueError",
                    "message": "Owner Alignment case lacks system_text",
                },
            })
            with patch(
                "mlsys.training.stage9a_evaluation."
                "EXPECTED_OWNER_ALIGNMENT_PRIOR_FAILURE_HASH",
                original["content_hash"],
            ):
                self.assertEqual(
                    _require_prior_owner_alignment_failure(path)["content_hash"],
                    original["content_hash"],
                )
                write_hashed_json(path, {
                    "status": "failed",
                    "error": {
                        "type": "ValueError",
                        "message": "Owner Alignment case lacks system_text",
                    },
                    "resigned_tamper": True,
                })
                with self.assertRaisesRegex(ValueError, "exact prior failure"):
                    _require_prior_owner_alignment_failure(path)

    def test_owner_alignment_prior_success_rejects_resigned_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "owner-alignment-evaluation.json"
            original = write_hashed_json(path, {
                "evaluation_id": "owner-alignment-final-v4-correction1",
                "status": "completed_candidate_alignment_evaluation",
                "candidate_only": True,
                "promotion_authorized": False,
                "deployment_authorized": False,
            })
            with patch(
                "mlsys.training.stage9a_evaluation."
                "EXPECTED_OWNER_ALIGNMENT_PRIOR_SUCCESS_HASH",
                original["content_hash"],
            ):
                self.assertEqual(
                    _require_prior_owner_alignment_success(path)["content_hash"],
                    original["content_hash"],
                )
                write_hashed_json(path, {
                    "evaluation_id": "owner-alignment-final-v4-correction1",
                    "status": "completed_candidate_alignment_evaluation",
                    "candidate_only": True,
                    "promotion_authorized": False,
                    "deployment_authorized": False,
                    "resigned_tamper": True,
                })
                with self.assertRaisesRegex(ValueError, "exact prior report"):
                    _require_prior_owner_alignment_success(path)

    def test_owner_alignment_registry_consumption_rechecks_exact_prior_failure(self) -> None:
        with (
            patch(
                "mlsys.training.stage9a_registry.load_and_verify_owner_alignment",
                return_value={"cases": []},
            ),
            patch(
                "mlsys.training.stage9a_evaluation._canonical_v4_system_text",
                return_value="System",
            ),
            patch(
                "mlsys.training.stage9a_evaluation."
                "_require_prior_owner_alignment_failure",
                side_effect=ValueError("exact prior failure evidence"),
            ),
            self.assertRaisesRegex(ValueError, "exact prior failure"),
        ):
            validate_owner_alignment_evidence(
                {}, {"formal_seeds": [], "formal_evidence": []}
            )

    def test_formal_execution_source_archive_recomputes_exact_snapshot(self) -> None:
        archive = require_archived_source_snapshot()
        self.assertEqual(archive["snapshot"], FORMAL_EXECUTION_SOURCE_SNAPSHOT)
        self.assertEqual(archive["file_count"], 316)
        self.assertEqual(archive["total_bytes"], 5_443_265)

    def test_registry_snapshot_is_bound_to_exact_committed_source(self) -> None:
        self.assertRegex(REGISTRY_VALIDATION_SOURCE_COMMIT, r"^[0-9a-f]{40}$")
        self.assertEqual(
            require_registry_validation_source(),
            REGISTRY_VALIDATION_SOURCE_SNAPSHOT,
        )

    def test_registry_source_binding_does_not_use_ambient_clean_filters(self) -> None:
        original_run = subprocess.run

        def without_hash_object(*args, **kwargs):
            command = args[0]
            if command[:2] == ["git", "hash-object"]:
                self.fail("registry validation must not use ambient Git clean filters")
            return original_run(*args, **kwargs)

        with patch(
            "mlsys.training.stage9a_provenance.subprocess.run",
            side_effect=without_hash_object,
        ):
            self.assertEqual(
                require_registry_validation_source(),
                REGISTRY_VALIDATION_SOURCE_SNAPSHOT,
            )

    def test_committed_archive_normalizes_crlf_without_git_filters(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory) / "tree"
            path = root / "companion" / "service.py"
            path.parent.mkdir(parents=True)
            payload = b"version = 1\r\nnext = 2\n"
            path.write_bytes(payload)
            digest = hashlib.sha256(b"HAVRE-benchmark-execution-source-v2\0")
            relative = b"companion/service.py"
            digest.update(len(relative).to_bytes(8, "big"))
            digest.update(relative)
            digest.update(b"\0file\0")
            digest.update(len(payload).to_bytes(8, "big"))
            digest.update(payload)
            tree = SimpleNamespace(
                returncode=0,
                stdout=b"100644 blob " + b"a" * 40 + b"\tcompanion/service.py\0",
            )
            blob = SimpleNamespace(returncode=0, stdout=b"version = 1\nnext = 2\n")
            with (
                patch(
                    "mlsys.training.stage9a_provenance.assert_private_stage9a_path",
                    return_value=root,
                ),
                patch(
                    "mlsys.training.stage9a_provenance.subprocess.run",
                    side_effect=(tree, blob),
                ) as run,
                patch(
                    "mlsys.training.stage9a_provenance.platform.system",
                    return_value="Windows",
                ),
            ):
                archive = require_committed_source_snapshot_archive(
                    snapshot=f"sha256:{digest.hexdigest()}",
                    revision="b" * 40,
                    expected_file_count=1,
                    expected_total_bytes=len(payload),
                )
            self.assertEqual(archive["normalized_line_ending_files"], 1)
            self.assertEqual(
                run.call_args_list[1].args[0][:3], ["git", "cat-file", "blob"]
            )

    def test_committed_archive_rejects_payload_that_differs_from_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory) / "tree"
            path = root / "companion" / "service.py"
            path.parent.mkdir(parents=True)
            payload = b"tampered\r\n"
            path.write_bytes(payload)
            tree = SimpleNamespace(
                returncode=0,
                stdout=b"100644 blob " + b"a" * 40 + b"\tcompanion/service.py\0",
            )
            blob = SimpleNamespace(returncode=0, stdout=b"expected\n")
            with (
                patch(
                    "mlsys.training.stage9a_provenance.assert_private_stage9a_path",
                    return_value=root,
                ),
                patch(
                    "mlsys.training.stage9a_provenance.subprocess.run",
                    side_effect=(tree, blob),
                ),
                patch(
                    "mlsys.training.stage9a_provenance.platform.system",
                    return_value="Windows",
                ),
                self.assertRaisesRegex(ValueError, "differs from committed blob"),
            ):
                require_committed_source_snapshot_archive(
                    snapshot="sha256:" + "c" * 64,
                    revision="b" * 40,
                    expected_file_count=1,
                    expected_total_bytes=len(payload),
                )

    def test_selective_supervision_uses_exact_shifted_suffix_positions(self) -> None:
        import torch

        batch = {
            "input_ids": torch.tensor([[8, 7, 6, 3, 4, 5]], dtype=torch.long),
            "labels": torch.tensor([[-100, -100, -100, 3, 4, 5]], dtype=torch.long),
            "attention_mask": torch.ones((1, 6), dtype=torch.long),
        }
        positions, targets, spec = _selective_supervision(batch)
        self.assertEqual(positions.tolist(), [2, 3, 4])
        self.assertEqual(targets.tolist(), [[3, 4, 5]])
        self.assertEqual(spec["supervised_label_start"], 3)
        self.assertEqual(spec["selected_logit_start"], 2)
        self.assertEqual(spec["selected_logit_end_inclusive"], 4)

    def test_selective_supervision_fails_closed_on_non_suffix_or_batching(self) -> None:
        import torch

        with self.assertRaisesRegex(ValueError, "contiguous supervised suffix"):
            _supervised_suffix_spec([-100, 1, -100, 2])
        with self.assertRaisesRegex(ValueError, "preceding causal position"):
            _supervised_suffix_spec([1, 2])
        unsupported = {
            "input_ids": torch.ones((2, 4), dtype=torch.long),
            "labels": torch.tensor([[-100, -100, 1, 2], [-100, -100, 1, 2]]),
            "attention_mask": torch.ones((2, 4), dtype=torch.long),
        }
        with self.assertRaisesRegex(ValueError, "batch size 1 only"):
            _selective_supervision(unsupported)
        padded = {key: value[:1].clone() for key, value in unsupported.items()}
        padded["attention_mask"][0, -1] = 0
        with self.assertRaisesRegex(ValueError, "padded batch semantics"):
            _selective_supervision(padded)

    def test_full_and_selective_losses_targets_gradients_and_mean_are_equivalent(self) -> None:
        import torch
        import torch.nn.functional as functional

        class _ToyCausalLM(torch.nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.hidden = torch.nn.Parameter(
                    torch.tensor(
                        [[[0.1, -0.2, 0.3], [0.4, 0.5, -0.6], [-0.7, 0.8, 0.9],
                          [1.0, -1.1, 1.2], [1.3, 1.4, -1.5], [-1.6, 1.7, 1.8]]],
                        dtype=torch.float64,
                    )
                )
                self.lm_head = torch.nn.Linear(3, 7, bias=False, dtype=torch.float64)
                with torch.no_grad():
                    self.lm_head.weight.copy_(
                        torch.arange(21, dtype=torch.float64).reshape(7, 3) / 20.0
                    )

            def forward(
                self, *, input_ids, attention_mask, labels=None, logits_to_keep=0
            ):
                del input_ids, attention_mask, labels
                indices = (
                    slice(-logits_to_keep, None)
                    if isinstance(logits_to_keep, int)
                    else logits_to_keep
                )
                return SimpleNamespace(logits=self.lm_head(self.hidden[:, indices, :]))

        batch = {
            "input_ids": torch.tensor([[6, 5, 4, 3, 2, 1]], dtype=torch.long),
            "labels": torch.tensor([[-100, -100, -100, 3, 4, 5]], dtype=torch.long),
            "attention_mask": torch.ones((1, 6), dtype=torch.long),
        }
        full_model = _ToyCausalLM()
        selective_model = deepcopy(full_model)
        full_logits = full_model(**batch).logits.float()
        shifted = functional.pad(batch["labels"], (0, 1), value=-100)[:, 1:]
        full_loss = functional.cross_entropy(
            full_logits.reshape(-1, full_logits.shape[-1]),
            shifted.reshape(-1),
            ignore_index=-100,
            reduction="mean",
        )
        full_loss.backward()
        selective_loss, selection = _selective_causal_lm_loss(selective_model, batch)
        selective_loss.backward()

        positions, targets, _ = _selective_supervision(batch)
        self.assertEqual(positions.tolist(), [2, 3, 4])
        self.assertEqual(targets.tolist(), [[3, 4, 5]])
        self.assertEqual(selection["selected_logit_count"], targets.numel())
        torch.testing.assert_close(selective_loss, full_loss, rtol=1e-6, atol=1e-7)
        for full_parameter, selective_parameter in zip(
            full_model.parameters(), selective_model.parameters(), strict=True
        ):
            torch.testing.assert_close(
                selective_parameter.grad,
                full_parameter.grad,
                rtol=1e-6,
                atol=1e-7,
            )
        selected_logits = selective_model(
            input_ids=batch["input_ids"],
            attention_mask=batch["attention_mask"],
            logits_to_keep=positions,
        ).logits.float()
        per_token = functional.cross_entropy(
            selected_logits.reshape(-1, selected_logits.shape[-1]),
            targets.reshape(-1),
            reduction="none",
        )
        torch.testing.assert_close(selective_loss, per_token.mean(), rtol=1e-6, atol=1e-7)

    def test_adapter_configuration_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "evidence"
            adapter = root / "adapter"
            adapter.mkdir()
            (adapter / "adapter_model.safetensors").write_bytes(b"adapter")
            (adapter / "adapter_config.json").write_text(
                json.dumps({
                    "peft_type": "LORA",
                    "task_type": "CAUSAL_LM",
                    "r": 8,
                    "lora_alpha": 32,
                    "lora_dropout": 0.05,
                    "bias": "none",
                }),
                encoding="utf-8",
            )
            provenance = write_hashed_json(
                evidence / "qwen3-8b-provenance.json",
                {"repository": "Qwen/Qwen3-8B"},
            )
            write_hashed_json(adapter / "havre_adapter_manifest.json", {
                "schema_version": 1,
                "base_repository": "Qwen/Qwen3-8B",
                "base_revision": "b968826d9c46dd6066d109eabc6255188de91218",
                "base_provenance_hash": provenance["content_hash"],
                "adapter_file": "adapter_model.safetensors",
                "adapter_sha256": sha256_file(adapter / "adapter_model.safetensors"),
                "adapter_config_sha256": sha256_file(adapter / "adapter_config.json"),
                "candidate_only": True,
                "promotion_authorized": False,
                "deployment_authorized": False,
            })
            with (
                patch("mlsys.training.stage9a_real.EVIDENCE_ROOT", evidence),
                self.assertRaisesRegex(ValueError, "configuration is incompatible"),
            ):
                verify_adapter_binding(adapter)

    def test_adapter_target_modules_and_structural_flags_fail_closed(self) -> None:
        approved = {
            "peft_type": "LORA", "task_type": "CAUSAL_LM", "r": 4,
            "lora_alpha": 8, "lora_dropout": 0.05, "bias": "none",
            "modules_to_save": None, "use_dora": False, "use_rslora": False,
            "use_qalora": False, "layers_to_transform": None,
            "layer_replication": None, "trainable_token_indices": None,
            "exclude_modules": None, "lora_bias": False,
            "target_modules": [
                "q_proj", "k_proj", "v_proj", "o_proj",
                "gate_proj", "up_proj", "down_proj",
            ],
        }
        for field, value, expected in (
            ("target_modules", ["q_proj"], "target_modules do not match"),
            ("use_dora", True, "configuration is incompatible"),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                evidence = root / "evidence"
                adapter = root / "adapter"
                adapter.mkdir()
                (adapter / "adapter_model.safetensors").write_bytes(b"adapter")
                config = dict(approved)
                config[field] = value
                (adapter / "adapter_config.json").write_text(
                    json.dumps(config), encoding="utf-8"
                )
                provenance = write_hashed_json(
                    evidence / "qwen3-8b-provenance.json", {"repository": "Qwen/Qwen3-8B"}
                )
                write_hashed_json(adapter / "havre_adapter_manifest.json", {
                    "base_repository": "Qwen/Qwen3-8B",
                    "base_revision": "b968826d9c46dd6066d109eabc6255188de91218",
                    "base_provenance_hash": provenance["content_hash"],
                    "adapter_file": "adapter_model.safetensors",
                    "adapter_sha256": sha256_file(adapter / "adapter_model.safetensors"),
                    "adapter_config_sha256": sha256_file(adapter / "adapter_config.json"),
                    "candidate_only": True, "promotion_authorized": False,
                    "deployment_authorized": False,
                })
                with (
                    patch("mlsys.training.stage9a_real.EVIDENCE_ROOT", evidence),
                    self.assertRaisesRegex(ValueError, expected),
                ):
                    verify_adapter_binding(adapter)

    def test_rendered_training_boundary_physically_excludes_holdout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "evidence"
            rendered = root / "rendered"
            dataset = root / "dataset"
            self._copy_v4_dataset(dataset)
            self._write_v4_gate_a(evidence, dataset)
            self._write_dataset_approval(evidence, dataset)
            with (
                patch("mlsys.training.stage9a_real.EVIDENCE_ROOT", evidence),
                patch("mlsys.training.stage9a_real.DATASET_ROOT", dataset),
                patch("mlsys.training.stage9a_real.RENDERED_ROOT", rendered),
                patch("mlsys.training.stage9a_real._load_tokenizer", return_value=_FakeQwenTokenizer()),
            ):
                report = build_rendered_artifacts()
                with (
                    patch(
                        "mlsys.training.stage9a_real.APPROVED_RENDERED_MANIFEST_HASH",
                        report["content_hash"],
                    ),
                    patch(
                        "mlsys.training.stage9a_real.APPROVED_PRE_REMEDIATION_SOURCE_SNAPSHOT",
                        report["execution_source_snapshot"],
                    ),
                ):
                    boundary = verify_training_input_boundary(_FakeQwenTokenizer())
            self.assertEqual(report["rendered_splits"], ["train", "validation"])
            self.assertFalse(report["holdout_rendered"])
            self.assertTrue((rendered / "train.jsonl").is_file())
            self.assertTrue((rendered / "validation.jsonl").is_file())
            self.assertFalse((rendered / "holdout.jsonl").exists())
            self.assertEqual(
                boundary["selective_logit_contract"]["splits"]["train"]["count"], 300
            )
            self.assertEqual(
                boundary["selective_logit_contract"]["splits"]["validation"]["count"], 60
            )

    def test_legacy_gate_a_evidence_cannot_authorize_v4_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "evidence"
            dataset = root / "dataset"
            rendered = root / "rendered"
            self._copy_v4_dataset(dataset)
            self._write_dataset_approval(evidence, dataset)
            write_hashed_json(evidence / "gate-a.json", {"gate": "A", "status": "passed"})
            with (
                patch("mlsys.training.stage9a_real.EVIDENCE_ROOT", evidence),
                patch("mlsys.training.stage9a_real.DATASET_ROOT", dataset),
                patch("mlsys.training.stage9a_real.RENDERED_ROOT", rendered),
                self.assertRaises(FileNotFoundError),
            ):
                build_rendered_artifacts()
            self.assertFalse(rendered.exists())

    def test_renderer_fails_closed_without_exact_po_dataset_freeze(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "evidence"
            dataset = root / "dataset"
            rendered = root / "rendered"
            self._copy_v4_dataset(dataset)
            self._write_v4_gate_a(evidence, dataset)
            with (
                patch("mlsys.training.stage9a_real.EVIDENCE_ROOT", evidence),
                patch("mlsys.training.stage9a_real.DATASET_ROOT", dataset),
                patch("mlsys.training.stage9a_real.RENDERED_ROOT", rendered),
                patch("mlsys.training.stage9a_real._load_tokenizer", return_value=_FakeQwenTokenizer()),
                self.assertRaisesRegex(PermissionError, "lacks Product Owner freeze approval"),
            ):
                build_rendered_artifacts()
            write_hashed_json(evidence / "dataset-v4-po-freeze-approval.json", {
                "decision": "ACCEPT",
                "dataset_version": DATASET_VERSION,
                "dataset_bundle_hash": "sha256:" + "0" * 64,
                "training_authorized": True,
                "owner_alignment_permanently_excluded": True,
                "stage9a_only": True,
                "promotion_authorized": False,
                "deployment_authorized": False,
            })
            with (
                patch("mlsys.training.stage9a_real.EVIDENCE_ROOT", evidence),
                patch("mlsys.training.stage9a_real.DATASET_ROOT", dataset),
                self.assertRaisesRegex(PermissionError, "hash-mismatched"),
            ):
                build_rendered_artifacts()

    def test_holdout_cannot_enter_training_iterator(self) -> None:
        with self.assertRaisesRegex(ValueError, "only train and validation"):
            list(_iter_rendered("holdout", 128))

    def test_removed_freeze_approval_blocks_rendered_iterator_and_training_entry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "evidence"
            dataset = root / "dataset"
            rendered = root / "rendered"
            runs = root / "runs"
            self._copy_v4_dataset(dataset)
            self._write_v4_gate_a(evidence, dataset)
            self._write_dataset_approval(evidence, dataset)
            tokenizer = _FakeQwenTokenizer()
            with (
                patch("mlsys.training.stage9a_real.EVIDENCE_ROOT", evidence),
                patch("mlsys.training.stage9a_real.DATASET_ROOT", dataset),
                patch("mlsys.training.stage9a_real.RENDERED_ROOT", rendered),
                patch("mlsys.training.stage9a_real.RUNS_ROOT", runs),
                patch("mlsys.training.stage9a_real._load_tokenizer", return_value=tokenizer),
            ):
                manifest = build_rendered_artifacts()
                (evidence / "dataset-v4-po-freeze-approval.json").unlink()
                with self.assertRaisesRegex(PermissionError, "lacks Product Owner freeze"):
                    list(_iter_rendered("train", manifest["chosen_max_seq_length"], tokenizer))
                with self.assertRaisesRegex(PermissionError, "lacks Product Owner freeze"):
                    train_qlora(
                        seed=9201,
                        run_id="formal-seed-9201",
                        epochs=2,
                        max_optimizer_steps=None,
                        formal=True,
                    )
                self.assertFalse((runs / "formal-seed-9201").exists())

    def test_self_signed_forged_rendered_rows_cannot_enter_training(self) -> None:
        attacks = ("holdout_member", "duplicate_member", "token_payload")
        for attack in attacks:
            with self.subTest(attack=attack), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                evidence = root / "evidence"
                dataset = root / "dataset"
                rendered = root / "rendered"
                self._copy_v4_dataset(dataset)
                self._write_v4_gate_a(evidence, dataset)
                self._write_dataset_approval(evidence, dataset)
                tokenizer = _FakeQwenTokenizer()
                patches = (
                    patch("mlsys.training.stage9a_real.EVIDENCE_ROOT", evidence),
                    patch("mlsys.training.stage9a_real.DATASET_ROOT", dataset),
                    patch("mlsys.training.stage9a_real.RENDERED_ROOT", rendered),
                    patch("mlsys.training.stage9a_real._load_tokenizer", return_value=tokenizer),
                )
                with patches[0], patches[1], patches[2], patches[3]:
                    manifest = build_rendered_artifacts()
                    path = rendered / "train.jsonl"
                    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
                    if attack == "holdout_member":
                        holdout = load_and_verify_dataset(dataset)["holdout"][0]
                        rows[0]["example_id"] = holdout["example_id"]
                        rows[0]["source_content_hash"] = holdout["content_hash"]
                    elif attack == "duplicate_member":
                        rows = [dict(rows[0]) for _ in rows]
                    else:
                        rows[0]["input_ids"][0] += 1
                    for row in rows:
                        material = {key: value for key, value in row.items() if key != "content_hash"}
                        row["content_hash"] = content_hash(material)
                    path.write_text(
                        "".join(
                            json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n"
                            for row in rows
                        ),
                        encoding="utf-8",
                    )
                    manifest_material = dict(manifest)
                    manifest_material.pop("content_hash")
                    manifest_material["split_reports"]["train"]["artifact_sha256"] = sha256_file(path)
                    rewritten = write_hashed_json(
                        rendered / "manifest.json", manifest_material
                    )
                    expected = {
                        "holdout_member": "not a source member",
                        "duplicate_member": "duplicate rendered example_id",
                        "token_payload": "does not exactly match its source",
                    }[attack]
                    with (
                        patch(
                            "mlsys.training.stage9a_real.APPROVED_RENDERED_MANIFEST_HASH",
                            rewritten["content_hash"],
                        ),
                        patch(
                            "mlsys.training.stage9a_real.APPROVED_PRE_REMEDIATION_SOURCE_SNAPSHOT",
                            rewritten["execution_source_snapshot"],
                        ),
                        self.assertRaisesRegex(ValueError, expected),
                    ):
                        list(_iter_rendered("train", 144, tokenizer))

    def test_standard_lora_probe_is_supervised_by_twenty_minute_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory)
            write_hashed_json(evidence / "gate-a.json", {"gate": "A", "status": "passed"})
            timeout = subprocess.TimeoutExpired(["python"], timeout=1200)
            with (
                patch("mlsys.training.stage9a_real.EVIDENCE_ROOT", evidence),
                patch("mlsys.training.stage9a_real.subprocess.run", side_effect=timeout) as run,
            ):
                report = standard_lora_gpu_only_probe()
            self.assertEqual(run.call_args.kwargs["timeout"], 1200)
            self.assertEqual(report["outcome"], "infeasible_timeout_20_minutes")
            self.assertFalse(report["cpu_offload_allowed"])
            self.assertFalse(report["swap_allowed"])

    def test_sealed_evaluation_recomputes_scores_and_arm_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runs_root = Path(directory) / "runs"
            evaluation_root = runs_root / FORMAL_EVALUATION_IDS[9201]
            evaluation_root.mkdir(parents=True)
            adapter_hash = "sha256:" + "a" * 64
            holdout = load_and_verify_dataset(V4_DATASET_ROOT)["holdout"]
            arms = []
            rows_by_arm = {}
            for arm_name in (
                "base", "base_memory", "base_adapter", "base_memory_adapter"
            ):
                memory_enabled = arm_name in {"base_memory", "base_memory_adapter"}
                rows = []
                for item in holdout:
                    row = {
                        "example_id": item["example_id"],
                        "source_content_hash": item["content_hash"],
                        "category": item["category"],
                        "evaluation_id": FORMAL_EVALUATION_IDS[9201],
                        "arm": arm_name,
                        "formal_seed": 9201,
                        "selected_adapter_manifest_hash": adapter_hash,
                        "memory_enabled": memory_enabled,
                        "text": item["expected_text"],
                        "input_tokens": 10,
                        "output_tokens": 10,
                        "ttft_seconds": 0.1,
                        "latency_seconds": 0.2,
                    }
                    row["scores"] = score_v4_case(
                        item, row["text"], memory_enabled=memory_enabled
                    )
                    row["content_hash"] = content_hash(row)
                    rows.append(row)
                artifact = evaluation_root / f"{arm_name}.jsonl"
                artifact.write_text(
                    "".join(
                        json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
                        for row in rows
                    ),
                    encoding="utf-8",
                )
                rows_by_arm[arm_name] = rows
                arms.append({
                    "arm": arm_name,
                    "formal_seed": 9201,
                    "selected_adapter_manifest_hash": adapter_hash,
                    "memory_enabled": memory_enabled,
                    "case_count": 120,
                    "behavioral_metrics": summarize_v4_scores(rows),
                    "output_artifact": str(artifact),
                    "output_artifact_sha256": sha256_file(artifact),
                })
            evaluation = {
                "evaluation_id": FORMAL_EVALUATION_IDS[9201],
                "adapter_manifest_hash": adapter_hash,
                "arms": arms,
            }
            with (
                patch("mlsys.training.stage9a_registry.RUNS_ROOT", runs_root),
                patch("mlsys.training.stage9a_registry.DATASET_ROOT", V4_DATASET_ROOT),
            ):
                _verify_sealed_evaluation_artifacts(evaluation, seed=9201)
                attacked = rows_by_arm["base_adapter"]
                attacked[0]["scores"] = deepcopy(attacked[0]["scores"])
                checks = attacked[0]["scores"]["deterministic_property_checks"]
                checks["aiism_free"] = not checks["aiism_free"]
                material = dict(attacked[0])
                material.pop("content_hash")
                attacked[0]["content_hash"] = content_hash(material)
                artifact = evaluation_root / "base_adapter.jsonl"
                artifact.write_text(
                    "".join(
                        json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
                        for row in attacked
                    ),
                    encoding="utf-8",
                )
                arm = next(item for item in arms if item["arm"] == "base_adapter")
                arm["output_artifact_sha256"] = sha256_file(artifact)
                arm["behavioral_metrics"] = summarize_v4_scores(attacked)
                with self.assertRaisesRegex(ValueError, "canonical-text-derived"):
                    _verify_sealed_evaluation_artifacts(evaluation, seed=9201)

    def test_formal_validation_loss_must_be_row_derived(self) -> None:
        snapshot = "sha256:" + "1" * 64
        dataset_hash = "sha256:" + "2" * 64
        gate_hash = "sha256:" + "3" * 64
        quantization = {"load_in_4bit": True, "bnb_4bit_quant_type": "nf4"}
        resources = self._valid_resource_evidence()
        summary = {
            "status": "completed_candidate",
            "epochs_requested": 2,
            "optimizer_steps": 600,
            "initial_validation_loss": 2.0,
            "final_validation_loss": 2.0,
            "wall_time_seconds": 601.0,
            "peak_vram_mib": 1000.0,
            "nvidia_smi_peak_vram_mib": 1000.0,
            "torch_peak_allocated_mib": 900.0,
            "torch_peak_reserved_mib": 950.0,
            "minimum_available_ram_gib": 19.8,
            "maximum_swap_used_mib": 0.0,
        }
        history = [
            {
                "optimizer_step": index,
                "epoch": 1 if index <= 300 else 2,
                "loss": 2.0,
                "gradient_norm": 1.0,
                "selected_logit_count": 10,
                "elapsed_seconds": float(index),
                "torch_allocated_mib": 900.0,
                "torch_reserved_mib": 950.0,
            }
            for index in range(1, 601)
        ]
        validation_rows = [
            {
                "validation_batch": index,
                "loss": 2.0,
                "selected_logit_count": 10,
                "supervised_token_count": 10,
            }
            for index in range(1, 61)
        ]
        report = {
            "schema_version": 1,
            "gate": None,
            "run_id": FORMAL_RUN_IDS[9201],
            "seed": 9201,
            "formal": True,
            "status": "completed_candidate",
            "candidate_only": True,
            "promotion_authorized": False,
            "deployment_authorized": False,
            "contains_user_data": False,
            "dataset_bundle_hash": dataset_hash,
            "rendered_manifest_hash": (
                "sha256:8bad6bd7042b3039f549ea5f8080f5e4f63ed83582aa91aa5aa15ec42e1c659a"
            ),
            "execution_source_snapshot": snapshot,
            "framework": "transformers-peft-bitsandbytes-stage9a-v1",
            "training_implementation": (
                "qwen3-v4-nf4-qlora-selective-bf16-cache-trim-v1"
            ),
            "resource_monitor_version": RESOURCE_EVIDENCE_VERSION,
            "supersedes_training_report_hash": SUPERSEDED_FORMAL_REPORT_HASHES[9201],
            "loss_path_version": "qwen3-v4-supervised-suffix-selective-logits-v1",
            "remediated_gate_c_hash": gate_hash,
            "formal_seed_plan": [9201, 9202],
            "optional_third_seed": 9203,
            "quantization": quantization,
            "attention_implementation": "eager",
            "lora": {
                "rank": 4, "alpha": 8, "dropout": 0.05,
                "target_modules": "all-linear",
            },
            "optimizer": "torch.optim.AdamW_no_paging",
            "bf16_autocast": True,
            "frozen_base_io_bf16_restored": True,
            "gradient_checkpointing_use_reentrant": False,
            "release_cuda_cache_before_optimizer": True,
            "trainable_parameters": 10911744,
            "max_seq_length": 336,
            "history": history,
            "validation_evidence": {
                "reduction": "arithmetic_mean_of_batch_size_1_losses",
                "initial": deepcopy(validation_rows),
                "final": deepcopy(validation_rows),
            },
            "training_summary": summary,
            "resource_evidence": resources,
        }
        binding = {
            "run_id": report["run_id"],
            "seed": 9201,
            "training_summary": summary,
            "training_implementation": report["training_implementation"],
            "resource_monitor_version": RESOURCE_EVIDENCE_VERSION,
            "supersedes_training_report_hash": SUPERSEDED_FORMAL_REPORT_HASHES[9201],
            "remediated_gate_c_hash": gate_hash,
            "execution_source_snapshot": snapshot,
        }
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory)
            write_hashed_json(
                evidence / GATE_B_EVIDENCE_NAME, {"quantization": quantization}
            )
            with (
                patch("mlsys.training.stage9a_real.EVIDENCE_ROOT", evidence),
                patch(
                    "mlsys.training.stage9a_real.require_remediated_gate_c",
                    return_value={
                        "content_hash": gate_hash,
                        "execution_source_snapshot": snapshot,
                    },
                ),
                patch(
                    "mlsys.training.stage9a_real.dataset_bundle_hash",
                    return_value=dataset_hash,
                ),
            ):
                _validate_formal_training_artifacts(report, binding)
                summary["final_validation_loss"] = 1.0
                with self.assertRaisesRegex(ValueError, "not row-derived"):
                    _validate_formal_training_artifacts(report, binding)

    def test_forged_candidate_registry_fails_consumption_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "evidence"
            rendered = root / "rendered"
            runs = root / "runs"
            registry_path = root / "registry.json"
            rendered.mkdir()
            owner_path = (
                runs
                / "owner-alignment-final-v4-resource-correction2"
                / "owner-alignment-evaluation.json"
            )
            environment = write_hashed_json(evidence / "environment.json", {"name": "env"})
            provenance = write_hashed_json(
                evidence / "qwen3-8b-provenance.json", {
                    "target": "D:/models/exact-base",
                    "artifact_size_bytes": 123,
                    "files": [
                        {"path": "tokenizer.json", "sha256": "sha256:" + "a" * 64},
                        {"path": "model.safetensors", "sha256": "sha256:" + "b" * 64},
                    ],
                    "license": "Apache-2.0",
                }
            )
            rendered_manifest = write_hashed_json(rendered / "manifest.json", {
                "rendered_splits": ["train", "validation"],
                "holdout_rendered": False,
            })
            source = "sha256:" + "4" * 64
            owner = write_hashed_json(
                owner_path, {
                    "status": "completed_candidate_alignment_evaluation",
                    "execution_source_snapshot": source,
                }
            )
            dataset_hash = "sha256:" + "9" * 64
            readiness = {
                "formal_seeds": [],
                "formal_evidence": [],
                "third_seed_decision": {"content_hash": "sha256:" + "5" * 64},
                "compatibility": {"content_hash": "sha256:" + "6" * 64},
                "variance": {"content_hash": "sha256:" + "7" * 64},
                "boundary": {"content_hash": "sha256:" + "8" * 64},
                "formal_execution_source_snapshot": FORMAL_EXECUTION_SOURCE_SNAPSHOT,
                "formal_execution_source_archive": {
                    "snapshot": FORMAL_EXECUTION_SOURCE_SNAPSHOT,
                    "tree": "D:/archived-source",
                    "file_count": 316,
                    "total_bytes": 5_414_005,
                },
                "execution_source_snapshot": source,
            }
            write_hashed_json(registry_path, {
                "schema_version": 1,
                "registry_version": (
                    "stage9a-local-candidate-registry-v4-resource-correction2"
                ),
                "supersedes_candidate_registry_hash": (
                    "sha256:359a04bd1be4309a08a0ed61c879d1cf3897c873342996d5decbc7468367fc0c"
                ),
                "resource_evidence_validation_version": (
                    "raw-sample-aggregate-recompute-v1"
                ),
                "status": "candidate_only",
                "registry_source_snapshot": source,
                "training_execution_source_snapshots": [FORMAL_EXECUTION_SOURCE_SNAPSHOT],
                "formal_execution_source_archive": readiness[
                    "formal_execution_source_archive"
                ],
                "owner_alignment_execution_source_snapshot": source,
                "local_only": True,
                "contains_user_data": False,
                "training_input_boundary_evidence_hash": readiness["boundary"]["content_hash"],
                "promotion_authorized": False,
                "deployment_authorized": False,
                "stage9b_authorized": False,
                "stage10_authorized": False,
                "model": {
                    "model_version_id": "base",
                    "logical_name": "Qwen3-8B Stage 9A exact base",
                    "provider_or_registry": "huggingface",
                    "upstream_model_id": "Qwen/Qwen3-8B",
                    "upstream_revision": "revision",
                    "artifact_uri": "https://forged.invalid/model",
                    "artifact_manifest_hash": provenance["content_hash"],
                    "artifact_size_bytes": 123,
                    "weights_format": "safetensors",
                    "precision": "bf16-base-nf4-training-load",
                    "tokenizer_files": [provenance["files"][0]],
                    "license": "Apache-2.0",
                    "lifecycle_status": "candidate",
                },
                "dataset": {
                    "dataset_bundle_hash": dataset_hash,
                    "rendered_manifest_hash": rendered_manifest["content_hash"],
                    "rendered_splits": ["train", "validation"],
                    "holdout_rendered": False,
                },
                "training_environment_hash": environment["content_hash"],
                "training_runs": [],
                "adapters": [],
                "compatibility_evidence_hash": readiness["compatibility"]["content_hash"],
                "variance_evidence_hash": readiness["variance"]["content_hash"],
                "third_seed_decision_hash": readiness["third_seed_decision"]["content_hash"],
                "owner_alignment_evaluation": {
                    "report_path": str(owner_path.resolve()),
                    "report_hash": owner["content_hash"],
                    "privacy_class": "PRIVATE",
                    "local_only": True,
                    "training_feedback_allowed": False,
                    "product_owner_review_required": True,
                },
                "registered_at": "2026-08-21T00:00:00+00:00",
            })
            with (
                patch("mlsys.training.stage9a_registry.REGISTRY_PATH", registry_path),
                patch("mlsys.training.stage9a_registry.EVIDENCE_ROOT", evidence),
                patch("mlsys.training.stage9a_registry.RENDERED_ROOT", rendered),
                patch("mlsys.training.stage9a_registry.RUNS_ROOT", runs),
                patch(
                    "mlsys.training.stage9a_registry.require_final_alignment_readiness",
                    return_value=readiness,
                ),
                patch("mlsys.training.stage9a_registry.validate_owner_alignment_evidence"),
                patch(
                    "mlsys.training.stage9a_registry.require_registry_validation_source",
                    return_value=source,
                ),
                patch(
                    "mlsys.training.stage9a_registry.dataset_bundle_hash",
                    return_value=dataset_hash,
                ),
                patch(
                    "mlsys.training.stage9a_registry.load_model_manifest",
                    return_value={
                        "manifest_id": "base", "repository": "Qwen/Qwen3-8B",
                        "revision": "revision",
                    },
                ),
                self.assertRaisesRegex(ValueError, "forged, stale, or cross-bound"),
            ):
                require_candidate_registry()
            self.assertTrue(environment["content_hash"].startswith("sha256:"))
            self.assertTrue(provenance["content_hash"].startswith("sha256:"))

    def test_registry_rejects_cross_bound_evaluation_report(self) -> None:
        snapshot = "sha256:" + "1" * 64
        adapter_hash = "sha256:" + "2" * 64
        dataset_hash = "sha256:" + "3" * 64
        rendered_hash = "sha256:" + "4" * 64
        boundary_hash = "sha256:" + "6" * 64
        gate_hash = "sha256:" + "7" * 64
        resources = self._valid_resource_evidence()
        training_summary = {"final_validation_loss": 1.0}
        arms = [
            {"arm": name, "case_count": 120}
            for name in ("base", "base_memory", "base_adapter", "base_memory_adapter")
        ]
        report = {
            "status": "completed_candidate", "candidate_only": True,
            "promotion_authorized": False, "deployment_authorized": False,
            "contains_user_data": False, "execution_source_snapshot": snapshot,
            "seed": 9201, "run_id": "run-9201", "adapter_manifest_hash": adapter_hash,
            "formal": True,
            "training_implementation": (
                "qwen3-v4-nf4-qlora-selective-bf16-cache-trim-v1"
            ),
            "dataset_bundle_hash": dataset_hash,
            "rendered_manifest_hash": rendered_hash,
            "training_input_boundary_hash": boundary_hash,
            "training_summary": training_summary,
            "remediated_gate_c_hash": gate_hash,
            "resource_evidence": resources,
        }
        adapter = {
            "content_hash": adapter_hash, "run_id": "run-9201",
            "execution_source_snapshot": snapshot, "dataset_bundle_hash": dataset_hash,
            "rendered_manifest_hash": rendered_hash,
            "training_summary": training_summary,
            "remediated_gate_c_hash": gate_hash,
        }
        evaluation = {
            "status": "completed_candidate_evaluation", "candidate_only": True,
            "promotion_authorized": False, "deployment_authorized": False,
            "contains_user_data": False, "execution_source_snapshot": snapshot,
            "evaluation_id": FORMAL_EVALUATION_IDS[9201],
            "content_hash": "sha256:" + "5" * 64,
            "adapter_manifest_hash": adapter_hash, "dataset_bundle_hash": dataset_hash,
            "base_repository": "Qwen/Qwen3-8B", "base_revision": "revision",
            "holdout_count": 120, "holdout_used_for_training_or_selection": False,
            "owner_alignment_set_used_for_training_or_selection": False,
            "arms": arms, "completed_formal_runs": [{"adapter_manifest_hash": adapter_hash}],
            "systems_metrics": {"resources": resources},
        }
        rescore = {
            "status": "completed_candidate_rescore", "candidate_only": True,
            "promotion_authorized": False, "deployment_authorized": False,
            "contains_user_data": False, "execution_source_snapshot": snapshot,
            "evaluation_id": FORMAL_EVALUATION_IDS[9201],
            "source_evaluation_content_hash": evaluation["content_hash"],
            "dataset_bundle_hash": dataset_hash, "holdout_count": 120,
            "holdout_used_for_training_or_selection": False, "arms": arms,
        }
        arguments = {
            "seed": 9201, "report": report, "adapter": adapter,
            "evaluation": evaluation, "rescore": rescore,
            "boundary": {
                "content_hash": boundary_hash,
                "dataset_bundle_hash": dataset_hash,
                "rendered_manifest_hash": rendered_hash,
            },
            "model_manifest": {"repository": "Qwen/Qwen3-8B", "revision": "revision"},
            "expected_source_snapshot": snapshot,
        }
        validate_run_evidence_bindings(**arguments)
        evaluation["execution_source_snapshot"] = "sha256:" + "8" * 64
        with self.assertRaisesRegex(ValueError, "current execution source"):
            validate_run_evidence_bindings(**arguments)
        evaluation["execution_source_snapshot"] = snapshot
        rescore["source_evaluation_content_hash"] = "sha256:" + "9" * 64
        with self.assertRaisesRegex(ValueError, "source evaluation"):
            validate_run_evidence_bindings(**arguments)


if __name__ == "__main__":
    unittest.main()
