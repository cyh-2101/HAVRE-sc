"""Immutable local candidate registry and variance evidence for Stage 9A."""

from __future__ import annotations

import json
import math
import os
import shutil
import statistics
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from companion.hashing import content_hash
from evals.inference_runner import current_source_revision
from mlsys.training.stage9a_dataset_v4 import (
    OWNER_ALIGNMENT_FILE_SHA256,
    OWNER_ALIGNMENT_PATH,
    SPLIT_COUNTS,
    dataset_bundle_hash,
    load_and_verify_dataset,
    load_and_verify_owner_alignment,
)
from mlsys.training.stage9a_provenance import (
    FORMAL_EXECUTION_SOURCE_SNAPSHOT,
    PROJECT_ROOT,
    STAGE9A_ROOT,
    assert_private_stage9a_path,
    load_model_manifest,
    require_archived_source_snapshot,
    require_committed_source_snapshot_archive,
)
from mlsys.training.stage9a_real import (
    DATASET_ROOT,
    EVIDENCE_ROOT,
    FORMAL_EVALUATION_IDS,
    FORMAL_RUN_IDS,
    RENDERED_ROOT,
    REQUIRED_FORMAL_SEEDS,
    RUNS_ROOT,
    OPTIONAL_THIRD_SEED,
    RESOURCE_EVIDENCE_VALIDATION_VERSION,
    TARGET_VRAM_MIB,
    TRAINING_IMPLEMENTATION_VERSION,
    _resource_evidence_is_within_stage9a_limits,
    completed_formal_runs as _completed_formal_runs,
    read_hashed_json,
    sha256_file,
    verify_adapter_binding,
    verify_training_input_boundary,
    write_hashed_json,
)


REGISTRY_ROOT = STAGE9A_ROOT / "registry"
REGISTRY_PATH = REGISTRY_ROOT / "candidate-registry-v4-resource-correction2.json"
SUPERSEDED_CANDIDATE_REGISTRY_HASH = (
    "sha256:359a04bd1be4309a08a0ed61c879d1cf3897c873342996d5decbc7468367fc0c"
)
REGISTRY_VERSION = "stage9a-local-candidate-registry-v4-resource-correction2"
REGISTRY_VALIDATION_SOURCE_COMMIT = "a28acc8a499e30b80688ceb130b7e20c027f09d1"
REGISTRY_VALIDATION_SOURCE_SNAPSHOT = (
    "sha256:915f29920d43b4b51185c48432b956e135bddbadc1950abd1de10dce1ee0a8bb"
)
REGISTRY_VALIDATION_SOURCE_FILE_COUNT = 316
REGISTRY_VALIDATION_SOURCE_BYTES = 5_452_083
COMPATIBILITY_EVIDENCE = (
    EVIDENCE_ROOT / "adapter-compatibility-probes-v4-resource-correction1.json"
)
VARIANCE_EVIDENCE = EVIDENCE_ROOT / "stage9a-v4-variance-resource-correction1.json"
TRAINING_INPUT_BOUNDARY_EVIDENCE = EVIDENCE_ROOT / "training-input-boundary-v4.json"
THIRD_SEED_DECISION_EVIDENCE = (
    EVIDENCE_ROOT / "third-seed-justification-v4-resource-correction1.json"
)
THIRD_SEED_DECISION_VERSION = "stage9a-v4-third-seed-material-variance-v2"
EXPECTED_EVALUATION_ARMS = (
    "base", "base_memory", "base_adapter", "base_memory_adapter",
)
EXPECTED_COMPATIBILITY_PROBES = {
    "wrong_exact_revision", "wrong_base_artifact",
    "incompatible_adapter_configuration", "incompatible_target_modules",
    "incompatible_structural_flag",
}
EXPECTED_COMPATIBILITY_FAILURE_MESSAGES = {
    "wrong_exact_revision": "adapter exact base revision binding mismatch",
    "wrong_base_artifact": "adapter base artifact hash binding mismatch",
    "incompatible_adapter_configuration": "adapter configuration is incompatible",
    "incompatible_target_modules": "target_modules do not match",
    "incompatible_structural_flag": "adapter configuration is incompatible",
}


def _formal_execution_source_snapshot() -> str:
    gate_c = read_hashed_json(
        EVIDENCE_ROOT / "gate-c-v4-remediated-selective-v1-resource-correction1.json"
    )
    source = gate_c.get("execution_source_snapshot")
    if not isinstance(source, str) or not source.startswith("sha256:"):
        raise ValueError("versioned formal Gate C lacks an execution-source snapshot")
    return source


def completed_formal_runs() -> list[dict[str, Any]]:
    """Read only the formal v4 lineage bound by this immutable registry."""
    return _completed_formal_runs(ignore_other_lineages=True)


def require_registry_validation_source() -> str:
    """Prove the registry snapshot is the exact committed source closure."""

    archive = require_committed_source_snapshot_archive(
        snapshot=REGISTRY_VALIDATION_SOURCE_SNAPSHOT,
        revision=REGISTRY_VALIDATION_SOURCE_COMMIT,
        expected_file_count=REGISTRY_VALIDATION_SOURCE_FILE_COUNT,
        expected_total_bytes=REGISTRY_VALIDATION_SOURCE_BYTES,
    )
    return str(archive["snapshot"])


def _validated_training_boundary() -> dict[str, Any]:
    historical = read_hashed_json(TRAINING_INPUT_BOUNDARY_EVIDENCE)
    current = verify_training_input_boundary()
    historical_projection = {
        key: value
        for key, value in current.items()
        if key not in {"content_hash", "selective_logit_contract"}
    }
    historical_projection["content_hash"] = content_hash(historical_projection)
    if historical != historical_projection:
        raise ValueError("historical training-input evidence differs from its exact projection")
    rendered = read_hashed_json(RENDERED_ROOT / "manifest.json")
    if (
        current.get("status") != "passed"
        or current.get("contains_user_data") is not False
        or current.get("all_members_training_eligible") is not True
        or current.get("source_kinds") != ["synthetic_fixture"]
        or current.get("holdout_rendered") is not False
        or current.get("dataset_bundle_hash") != dataset_bundle_hash(DATASET_ROOT)
        or current.get("rendered_manifest_hash") != rendered.get("content_hash")
        or current.get("selective_logit_contract", {}).get("batch_size") != 1
        or any(
            split.get("all_contiguous_supervised_suffix") is not True
            for split in current.get("selective_logit_contract", {})
            .get("splits", {}).values()
        )
    ):
        raise ValueError("training-input evidence violates the Stage 9A data boundary")
    return current


def _verify_sealed_evaluation_artifacts(
    evaluation: dict[str, Any], *, seed: int
) -> None:
    """Recompute the exact immutable synthetic-holdout projection and summaries."""
    from mlsys.training.stage9a_rubric_v4 import score_v4_case, summarize_v4_scores

    holdout = load_and_verify_dataset(DATASET_ROOT)["holdout"]
    expected = {item["example_id"]: item for item in holdout}
    if len(expected) != SPLIT_COUNTS["holdout"]:
        raise ValueError("sealed holdout does not have the expected unique membership")
    expected_root = (RUNS_ROOT / FORMAL_EVALUATION_IDS[seed]).resolve()
    arms = evaluation.get("arms", [])
    if [item.get("arm") for item in arms] != list(EXPECTED_EVALUATION_ARMS):
        raise ValueError("sealed evaluation does not contain the exact ordered four arms")
    for arm in arms:
        if (
            arm.get("formal_seed") != seed
            or arm.get("selected_adapter_manifest_hash")
            != evaluation.get("adapter_manifest_hash")
        ):
            raise ValueError("sealed evaluation arm is not bound to its seed/adapter")
        artifact = Path(str(arm.get("output_artifact", ""))).resolve()
        if artifact.parent != expected_root or not artifact.is_file():
            raise ValueError("sealed evaluation artifact escapes or is missing")
        if sha256_file(artifact) != arm.get("output_artifact_sha256"):
            raise ValueError("sealed evaluation artifact hash mismatch")
        rows = [
            json.loads(line)
            for line in artifact.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if len(rows) != SPLIT_COUNTS["holdout"]:
            raise ValueError("sealed evaluation arm does not contain 120 cases")
        seen: set[str] = set()
        expected_memory = arm.get("arm") in {"base_memory", "base_memory_adapter"}
        for row in rows:
            example_id = row.get("example_id")
            if example_id in seen or example_id not in expected:
                raise ValueError("sealed evaluation has duplicate or unknown holdout member")
            seen.add(example_id)
            material = dict(row)
            claimed = material.pop("content_hash", None)
            if claimed != content_hash(material):
                raise ValueError("sealed evaluation row content hash mismatch")
            if (
                row.get("source_content_hash") != expected[example_id]["content_hash"]
                or row.get("memory_enabled") is not expected_memory
                or row.get("evaluation_id") != evaluation.get("evaluation_id")
                or row.get("arm") != arm.get("arm")
                or row.get("formal_seed") != seed
                or row.get("selected_adapter_manifest_hash")
                != evaluation.get("adapter_manifest_hash")
            ):
                raise ValueError("sealed evaluation row is not an exact holdout/arm projection")
            expected_scores = score_v4_case(
                expected[example_id],
                row.get("text", ""),
                memory_enabled=expected_memory,
            )
            if row.get("scores") != expected_scores:
                raise ValueError("sealed evaluation scores are not canonical-text-derived")
        if seen != set(expected):
            raise ValueError("sealed evaluation omits holdout members")
        if arm.get("case_count") != len(rows):
            raise ValueError("sealed evaluation case count is not exact")
        if arm.get("behavioral_metrics") != summarize_v4_scores(rows):
            raise ValueError("sealed evaluation behavioral summary was not recomputed from rows")


def _load_exact_formal_run_evidence(
    seed: int,
    *,
    boundary: dict[str, Any] | None = None,
    verify_artifacts: bool = True,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    runs = {item["seed"]: item for item in completed_formal_runs()}
    if seed not in runs:
        raise RuntimeError(f"formal Seed {seed} is not complete")
    run = runs[seed]
    report = read_hashed_json(Path(run["report_path"]))
    adapter = verify_adapter_binding(Path(run["adapter_dir"]))
    evaluation = read_hashed_json(
        RUNS_ROOT / FORMAL_EVALUATION_IDS[seed] / "four-arm-evaluation.json"
    )
    selected_boundary = boundary or _validated_training_boundary()
    validate_run_evidence_bindings(
        seed=seed,
        report=report,
        adapter=adapter,
        evaluation=evaluation,
        boundary=selected_boundary,
        model_manifest=load_model_manifest(),
        expected_source_snapshot=_formal_execution_source_snapshot(),
    )
    if verify_artifacts:
        _verify_sealed_evaluation_artifacts(evaluation, seed=seed)
    return run, report, adapter, evaluation


def build_training_input_boundary_evidence() -> dict[str, Any]:
    """Persist the current exact source-to-rendered training projection proof."""
    if TRAINING_INPUT_BOUNDARY_EVIDENCE.exists():
        raise FileExistsError("immutable Stage 9A training-input evidence already exists")
    boundary = verify_training_input_boundary()
    material = dict(boundary)
    material.pop("content_hash")
    return write_hashed_json(TRAINING_INPUT_BOUNDARY_EVIDENCE, material)


def _expect_rejection(
    name: str,
    operation: Callable[[], object],
    expected_message: str,
) -> dict[str, Any]:
    try:
        operation()
    except Exception as error:
        if expected_message not in str(error):
            raise AssertionError(f"{name} rejected for the wrong reason: {error}") from error
        return {
            "probe": name,
            "status": "passed_rejected",
            "error_type": type(error).__name__,
            "error_message": str(error),
        }
    raise AssertionError(f"{name} did not fail closed")


def _link_or_copy(source: Path, target: Path) -> None:
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def run_compatibility_probes() -> dict[str, Any]:
    """Prove exact success plus wrong revision/artifact/config rejection."""
    if COMPATIBILITY_EVIDENCE.exists():
        raise FileExistsError("immutable Stage 9A compatibility evidence already exists")
    runs = completed_formal_runs()
    if len(runs) < 2:
        raise RuntimeError("compatibility probes require completed formal adapters")
    correct = []
    expected_source = current_source_revision(PROJECT_ROOT)
    for run in runs:
        adapter_dir = Path(run["adapter_dir"])
        manifest = verify_adapter_binding(adapter_dir)
        reload_report = read_hashed_json(adapter_dir.parent / "reload-report.json")
        if (
            reload_report.get("status") != "passed"
            or not reload_report.get("new_process_reload")
            or reload_report.get("finite_logits") is not True
            or reload_report.get("adapter_manifest_hash") != manifest["content_hash"]
            or reload_report.get("candidate_only") is not True
            or reload_report.get("promotion_authorized") is not False
            or reload_report.get("deployment_authorized") is not False
            or reload_report.get("contains_user_data") is not False
            or reload_report.get("execution_source_snapshot") != expected_source
            or manifest.get("execution_source_snapshot") != expected_source
            or not _resource_evidence_is_within_stage9a_limits(
                reload_report.get("resources", {}), peak_target_mib=TARGET_VRAM_MIB
            )
        ):
            raise RuntimeError("correct adapter lacks a passed new-process reload")
        correct.append({
            "seed": run["seed"],
            "adapter_manifest_hash": manifest["content_hash"],
            "reload_report_hash": reload_report["content_hash"],
            "finite_logits": reload_report["finite_logits"],
        })

    reference_dir = Path(runs[0]["adapter_dir"])
    reference = verify_adapter_binding(reference_dir)
    temp_parent = assert_private_stage9a_path(STAGE9A_ROOT / "tmp")
    temp_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="compatibility-probe-", dir=temp_parent) as directory:
        root = Path(directory)
        config_dir = root / "config-mismatch"
        config_dir.mkdir()
        _link_or_copy(
            reference_dir / reference["adapter_file"],
            config_dir / reference["adapter_file"],
        )
        config = json.loads((reference_dir / "adapter_config.json").read_text(encoding="utf-8"))
        config["r"] = int(config["r"]) + 1
        (config_dir / "adapter_config.json").write_text(
            json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        config_manifest = dict(reference)
        config_manifest.pop("content_hash")
        config_manifest["adapter_config_sha256"] = sha256_file(config_dir / "adapter_config.json")
        write_hashed_json(config_dir / "havre_adapter_manifest.json", config_manifest)

        target_dir = root / "target-modules-mismatch"
        target_dir.mkdir()
        _link_or_copy(
            reference_dir / reference["adapter_file"],
            target_dir / reference["adapter_file"],
        )
        target_config = json.loads(
            (reference_dir / "adapter_config.json").read_text(encoding="utf-8")
        )
        target_config["target_modules"] = ["q_proj"]
        (target_dir / "adapter_config.json").write_text(
            json.dumps(target_config, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        target_manifest = dict(reference)
        target_manifest.pop("content_hash")
        target_manifest["adapter_config_sha256"] = sha256_file(target_dir / "adapter_config.json")
        write_hashed_json(target_dir / "havre_adapter_manifest.json", target_manifest)

        flag_dir = root / "incompatible-flag"
        flag_dir.mkdir()
        _link_or_copy(
            reference_dir / reference["adapter_file"],
            flag_dir / reference["adapter_file"],
        )
        flag_config = json.loads(
            (reference_dir / "adapter_config.json").read_text(encoding="utf-8")
        )
        flag_config["use_dora"] = True
        (flag_dir / "adapter_config.json").write_text(
            json.dumps(flag_config, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        flag_manifest = dict(reference)
        flag_manifest.pop("content_hash")
        flag_manifest["adapter_config_sha256"] = sha256_file(flag_dir / "adapter_config.json")
        write_hashed_json(flag_dir / "havre_adapter_manifest.json", flag_manifest)

        provenance_dir = root / "provenance-mismatch"
        provenance_dir.mkdir()
        provenance_manifest = dict(reference)
        provenance_manifest.pop("content_hash")
        provenance_manifest["base_provenance_hash"] = "sha256:" + "0" * 64
        write_hashed_json(provenance_dir / "havre_adapter_manifest.json", provenance_manifest)

        rejections = [
            _expect_rejection(
                "wrong_exact_revision",
                lambda: verify_adapter_binding(reference_dir, expected_revision="0" * 40),
                "exact base revision binding mismatch",
            ),
            _expect_rejection(
                "wrong_base_artifact",
                lambda: verify_adapter_binding(provenance_dir),
                "base artifact hash binding mismatch",
            ),
            _expect_rejection(
                "incompatible_adapter_configuration",
                lambda: verify_adapter_binding(config_dir),
                "configuration is incompatible",
            ),
            _expect_rejection(
                "incompatible_target_modules",
                lambda: verify_adapter_binding(target_dir),
                "target_modules do not match",
            ),
            _expect_rejection(
                "incompatible_structural_flag",
                lambda: verify_adapter_binding(flag_dir),
                "configuration is incompatible",
            ),
        ]

    return write_hashed_json(COMPATIBILITY_EVIDENCE, {
        "schema_version": 1,
        "suite": "stage9a-exact-adapter-compatibility-v2",
        "status": "passed",
        "candidate_only": True,
        "promotion_authorized": False,
        "deployment_authorized": False,
        "contains_user_data": False,
        "correct_exact_bindings": correct,
        "fail_closed_probes": rejections,
        "temporary_probe_artifacts_removed": True,
        "execution_source_snapshot": expected_source,
        "completed_at": datetime.now(UTC).isoformat(),
    })


def require_compatibility_evidence() -> dict[str, Any]:
    """Validate exact reload and rejection closure for every formal adapter."""
    compatibility = read_hashed_json(COMPATIBILITY_EVIDENCE)
    runs = completed_formal_runs()
    expected_source = _formal_execution_source_snapshot()
    expected_rows = []
    for run in runs:
        adapter = verify_adapter_binding(Path(run["adapter_dir"]))
        reload_report = read_hashed_json(Path(run["adapter_dir"]).parent / "reload-report.json")
        if (
            reload_report.get("status") != "passed"
            or reload_report.get("new_process_reload") is not True
            or reload_report.get("finite_logits") is not True
            or reload_report.get("candidate_only") is not True
            or reload_report.get("promotion_authorized") is not False
            or reload_report.get("deployment_authorized") is not False
            or reload_report.get("contains_user_data") is not False
            or reload_report.get("execution_source_snapshot") != expected_source
            or adapter.get("execution_source_snapshot") != expected_source
            or reload_report.get("adapter_manifest_hash") != adapter["content_hash"]
            or not _resource_evidence_is_within_stage9a_limits(
                reload_report.get("resources", {}), peak_target_mib=TARGET_VRAM_MIB
            )
        ):
            raise ValueError("formal adapter reload evidence is incomplete or cross-bound")
        expected_rows.append({
            "seed": run["seed"],
            "adapter_manifest_hash": adapter["content_hash"],
            "reload_report_hash": reload_report["content_hash"],
            "finite_logits": True,
        })
    probes = compatibility.get("fail_closed_probes", [])
    probes_by_name = {item.get("probe"): item for item in probes}
    if (
        compatibility.get("suite") != "stage9a-exact-adapter-compatibility-v2"
        or compatibility.get("status") != "passed"
        or compatibility.get("candidate_only") is not True
        or compatibility.get("promotion_authorized") is not False
        or compatibility.get("deployment_authorized") is not False
        or compatibility.get("contains_user_data") is not False
        or compatibility.get("execution_source_snapshot") != expected_source
        or compatibility.get("temporary_probe_artifacts_removed") is not True
        or compatibility.get("correct_exact_bindings") != expected_rows
        or {item.get("probe") for item in probes} != EXPECTED_COMPATIBILITY_PROBES
        or len(probes) != len(EXPECTED_COMPATIBILITY_PROBES)
        or any(item.get("status") != "passed_rejected" for item in probes)
        or any(
            probes_by_name[name].get("error_type") != "ValueError"
            or EXPECTED_COMPATIBILITY_FAILURE_MESSAGES[name]
            not in str(probes_by_name[name].get("error_message", ""))
            for name in EXPECTED_COMPATIBILITY_PROBES
        )
    ):
        raise ValueError("compatibility evidence is forged, stale, or cross-bound")
    return compatibility


def _calculate_third_seed_decision(
    runs: dict[int, dict[str, Any]],
    training_reports: dict[int, dict[str, Any]],
    evaluations: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """Deterministically recompute the predeclared variance trigger."""

    first_loss = float(
        training_reports[REQUIRED_FORMAL_SEEDS[0]]["training_summary"][
            "final_validation_loss"
        ]
    )
    second_loss = float(
        training_reports[REQUIRED_FORMAL_SEEDS[1]]["training_summary"][
            "final_validation_loss"
        ]
    )
    if not all(math.isfinite(value) and value > 0 for value in (first_loss, second_loss)):
        raise RuntimeError("third-seed decision found invalid validation loss")
    validation_relative_gap = abs(first_loss - second_loss) / max(
        abs(first_loss), abs(second_loss), 1e-12
    )

    deterministic_gaps: list[dict[str, Any]] = []
    critical_names = {
        "exact",
        "safety_no_obvious_unsafe_instruction",
        "proactive_scope_is_rendering_only",
    }
    for arm_name in ("base_adapter", "base_memory_adapter"):
        by_seed = {}
        for seed, evaluation in evaluations.items():
            arm = next(item for item in evaluation["arms"] if item["arm"] == arm_name)
            by_seed[seed] = arm["behavioral_metrics"]["behavioral_rubric"][
                "deterministic_property_checks"
            ]
        names = set(by_seed[REQUIRED_FORMAL_SEEDS[0]]) | set(
            by_seed[REQUIRED_FORMAL_SEEDS[1]]
        )
        for name in sorted(names):
            left = by_seed[REQUIRED_FORMAL_SEEDS[0]].get(name)
            right = by_seed[REQUIRED_FORMAL_SEEDS[1]].get(name)
            if not left or not right or left.get("case_count") != right.get("case_count"):
                raise RuntimeError("third-seed deterministic metrics are not comparable")
            gap = abs(float(left["pass_rate"]) - float(right["pass_rate"]))
            deterministic_gaps.append({
                "arm": arm_name,
                "property": name,
                "case_count": left["case_count"],
                "absolute_pass_rate_gap": gap,
                "critical": name in critical_names,
            })

    maximum_critical_gap = max(
        (
            item["absolute_pass_rate_gap"]
            for item in deterministic_gaps
            if item["critical"]
        ),
        default=0.0,
    )
    material_training_variance = validation_relative_gap >= 0.10
    material_behavioral_variance = maximum_critical_gap >= 0.10
    variance_estimation_value = (
        material_training_variance or material_behavioral_variance
    )
    prior_gpu_seconds = sum(
        float(item["wall_time_seconds"]) for item in runs.values()
    )
    resources_sufficient = prior_gpu_seconds + 2 * 60 * 60 <= 6 * 60 * 60
    should_run = variance_estimation_value and resources_sufficient
    decision = (
        "run_optional_third_seed"
        if should_run
        else "do_not_run_optional_third_seed"
    )
    return {
        "decision": decision,
        "resources_sufficient": resources_sufficient,
        "variance_estimation_value": variance_estimation_value,
        "material_variance_rule": {
            "validation_loss_relative_gap_threshold": 0.10,
            "critical_deterministic_pass_rate_gap_threshold": 0.10,
            "reference_similarity_can_trigger_alone": False,
        },
        "validation_loss": {
            str(REQUIRED_FORMAL_SEEDS[0]): first_loss,
            str(REQUIRED_FORMAL_SEEDS[1]): second_loss,
            "relative_gap": validation_relative_gap,
        },
        "deterministic_property_gaps": deterministic_gaps,
        "maximum_critical_deterministic_gap": maximum_critical_gap,
        "material_training_variance": material_training_variance,
        "material_behavioral_variance": material_behavioral_variance,
        "formal_gpu_seconds_before_decision": prior_gpu_seconds,
        "required_seed_report_hashes": {
            str(seed): training_reports[seed]["content_hash"]
            for seed in REQUIRED_FORMAL_SEEDS
        },
        "required_evaluation_hashes": {
            str(seed): evaluations[seed]["content_hash"]
            for seed in REQUIRED_FORMAL_SEEDS
        },
        "required_adapter_manifest_hashes": {
            str(seed): runs[seed]["adapter_manifest_hash"]
            for seed in REQUIRED_FORMAL_SEEDS
        },
    }


def _first_two_exact_decision_inputs() -> tuple[
    dict[int, dict[str, Any]],
    dict[int, dict[str, Any]],
    dict[int, dict[str, Any]],
]:
    completed = {item["seed"]: item for item in completed_formal_runs()}
    if not all(seed in completed for seed in REQUIRED_FORMAL_SEEDS):
        raise RuntimeError("third-seed decision requires completed Seeds 9201 and 9202")
    if any(seed not in (*REQUIRED_FORMAL_SEEDS, OPTIONAL_THIRD_SEED) for seed in completed):
        raise RuntimeError("formal run set contains a seed outside the approved plan")
    boundary = _validated_training_boundary()
    runs: dict[int, dict[str, Any]] = {}
    reports: dict[int, dict[str, Any]] = {}
    evaluations: dict[int, dict[str, Any]] = {}
    for seed in REQUIRED_FORMAL_SEEDS:
        run, report, _, evaluation = _load_exact_formal_run_evidence(
            seed, boundary=boundary
        )
        runs[seed] = run
        reports[seed] = report
        evaluations[seed] = evaluation
    return runs, reports, evaluations


def decide_optional_third_seed() -> dict[str, Any]:
    """Apply the exact predeclared rule after both required sealed evaluations."""
    if THIRD_SEED_DECISION_EVIDENCE.exists():
        raise FileExistsError("immutable Stage 9A third-seed decision already exists")
    completed = completed_formal_runs()
    if [item["seed"] for item in completed] != list(REQUIRED_FORMAL_SEEDS):
        raise RuntimeError("third-seed decision requires exactly Seeds 9201 and 9202")
    runs, reports, evaluations = _first_two_exact_decision_inputs()
    calculation = _calculate_third_seed_decision(runs, reports, evaluations)
    return write_hashed_json(THIRD_SEED_DECISION_EVIDENCE, {
        "schema_version": 1,
        "decision_version": THIRD_SEED_DECISION_VERSION,
        "candidate_only": True,
        "promotion_authorized": False,
        "deployment_authorized": False,
        "contains_user_data": False,
        "owner_alignment_opened": False,
        "owner_alignment_used_for_seed_decision": False,
        "not_triggered_by_remaining_budget": True,
        "first_two_runs_and_evaluations_exactly_validated": True,
        **calculation,
        "execution_source_snapshot": current_source_revision(PROJECT_ROOT),
        "completed_at": datetime.now(UTC).isoformat(),
    })


def require_third_seed_decision() -> dict[str, Any]:
    """Reject forged or stale optional-seed decisions by exact recomputation."""
    decision = read_hashed_json(THIRD_SEED_DECISION_EVIDENCE)
    runs, reports, evaluations = _first_two_exact_decision_inputs()
    calculation = _calculate_third_seed_decision(runs, reports, evaluations)
    expected_source = _formal_execution_source_snapshot()
    required = {
        "schema_version": 1,
        "decision_version": THIRD_SEED_DECISION_VERSION,
        "candidate_only": True,
        "promotion_authorized": False,
        "deployment_authorized": False,
        "contains_user_data": False,
        "owner_alignment_opened": False,
        "owner_alignment_used_for_seed_decision": False,
        "not_triggered_by_remaining_budget": True,
        "first_two_runs_and_evaluations_exactly_validated": True,
        "execution_source_snapshot": expected_source,
        **calculation,
    }
    mismatches = {
        key: {"expected": value, "actual": decision.get(key)}
        for key, value in required.items()
        if decision.get(key) != value
    }
    if mismatches:
        raise ValueError(f"third-seed decision is forged, stale, or cross-bound: {mismatches}")
    return decision


def build_variance_evidence() -> dict[str, Any]:
    if VARIANCE_EVIDENCE.exists():
        raise FileExistsError("immutable Stage 9A variance evidence already exists")
    runs = completed_formal_runs()
    seeds = [item["seed"] for item in runs]
    approved_two = list(REQUIRED_FORMAL_SEEDS)
    approved_three = [*REQUIRED_FORMAL_SEEDS, OPTIONAL_THIRD_SEED]
    if seeds not in (approved_two, approved_three):
        raise RuntimeError("variance evidence requires the approved two or justified three seeds")
    third_seed_decision = require_third_seed_decision()
    if (
        third_seed_decision.get("owner_alignment_used_for_seed_decision") is not False
        or third_seed_decision.get("not_triggered_by_remaining_budget") is not True
        or (
            seeds == approved_two
            and third_seed_decision.get("decision")
            != "do_not_run_optional_third_seed"
        )
        or (
            seeds == approved_three
            and third_seed_decision.get("decision") != "run_optional_third_seed"
        )
    ):
        raise RuntimeError("formal seed set differs from the immutable third-seed decision")
    seed_rows = []
    memory_adapter_f1 = []
    boundary = _validated_training_boundary()
    for run in runs:
        seed = run["seed"]
        _, training, _, evaluation = _load_exact_formal_run_evidence(
            seed, boundary=boundary
        )
        arms = {item["arm"]: item for item in evaluation["arms"]}
        base_adapter = arms["base_adapter"]["behavioral_metrics"]
        memory_adapter = arms["base_memory_adapter"]["behavioral_metrics"]
        memory_adapter_diagnostic = memory_adapter["diagnostics"]["reference_token_f1"]["mean"]
        memory_adapter_f1.append(memory_adapter_diagnostic)
        seed_rows.append({
            "seed": seed,
            "training_report_hash": training["content_hash"],
            "adapter_manifest_hash": training["adapter_manifest_hash"],
            "final_validation_loss": training["training_summary"]["final_validation_loss"],
            "optimizer_steps": training["training_summary"]["optimizer_steps"],
            "wall_time_seconds": training["training_summary"]["wall_time_seconds"],
            "peak_vram_mib": training["training_summary"]["peak_vram_mib"],
            "evaluation_report_hash": evaluation["content_hash"],
            "base_adapter_diagnostic_reference_f1": (
                base_adapter["diagnostics"]["reference_token_f1"]["mean"]
            ),
            "base_memory_adapter_diagnostic_reference_f1": memory_adapter_diagnostic,
            "behavioral_review_status": memory_adapter["behavioral_rubric"]["review_status"],
        })
    mean = statistics.fmean(memory_adapter_f1)
    return write_hashed_json(VARIANCE_EVIDENCE, {
        "schema_version": 1,
        "suite": "stage9a-seed-variance-v4",
        "status": "completed_candidate_evidence",
        "candidate_only": True,
        "promotion_authorized": False,
        "deployment_authorized": False,
        "contains_user_data": False,
        "seed_count": len(seed_rows),
        "seeds": seed_rows,
        "formal_gpu_training_seconds": sum(row["wall_time_seconds"] for row in seed_rows),
        "base_memory_adapter_diagnostic_reference_f1": {
            "role": "diagnostic_only_not_primary_companion_quality",
            "mean": mean,
            "sample_standard_deviation": statistics.stdev(memory_adapter_f1),
            "minimum": min(memory_adapter_f1),
            "maximum": max(memory_adapter_f1),
            "range": max(memory_adapter_f1) - min(memory_adapter_f1),
        },
        "interpretation": (
            "The synthetic holdout shows seed-sensitive Base+Memory+Adapter wording and "
            "diagnostic reference-token F1. This is bounded variance evidence, while "
            "property-based behavioral review remains primary. It is not "
            "real-world utility or promotion evidence."
        ),
        "third_seed_executed": seeds == approved_three,
        "additional_seed_authorized": False,
        "third_seed_decision_hash": third_seed_decision["content_hash"],
        "execution_source_snapshot": current_source_revision(PROJECT_ROOT),
        "completed_at": datetime.now(UTC).isoformat(),
    })


def require_variance_evidence() -> dict[str, Any]:
    """Recompute exact seed/run/evaluation bindings in the variance record."""
    variance = read_hashed_json(VARIANCE_EVIDENCE)
    decision = require_third_seed_decision()
    runs = completed_formal_runs()
    seeds = [item["seed"] for item in runs]
    expected_seeds = (
        [*REQUIRED_FORMAL_SEEDS, OPTIONAL_THIRD_SEED]
        if decision["decision"] == "run_optional_third_seed"
        else list(REQUIRED_FORMAL_SEEDS)
    )
    if seeds != expected_seeds:
        raise ValueError("variance evidence formal seed set differs from the decision")
    boundary = _validated_training_boundary()
    expected_rows = []
    diagnostic_values = []
    for run in runs:
        seed = run["seed"]
        _, training, _, evaluation = _load_exact_formal_run_evidence(
            seed, boundary=boundary
        )
        arms = {item["arm"]: item for item in evaluation["arms"]}
        base_adapter = arms["base_adapter"]["behavioral_metrics"]
        memory_adapter = arms["base_memory_adapter"]["behavioral_metrics"]
        diagnostic = memory_adapter["diagnostics"]["reference_token_f1"]["mean"]
        diagnostic_values.append(diagnostic)
        expected_rows.append({
            "seed": seed,
            "training_report_hash": training["content_hash"],
            "adapter_manifest_hash": training["adapter_manifest_hash"],
            "final_validation_loss": training["training_summary"]["final_validation_loss"],
            "optimizer_steps": training["training_summary"]["optimizer_steps"],
            "wall_time_seconds": training["training_summary"]["wall_time_seconds"],
            "peak_vram_mib": training["training_summary"]["peak_vram_mib"],
            "evaluation_report_hash": evaluation["content_hash"],
            "base_adapter_diagnostic_reference_f1": (
                base_adapter["diagnostics"]["reference_token_f1"]["mean"]
            ),
            "base_memory_adapter_diagnostic_reference_f1": diagnostic,
            "behavioral_review_status": memory_adapter["behavioral_rubric"]["review_status"],
        })
    expected_diagnostic = {
        "role": "diagnostic_only_not_primary_companion_quality",
        "mean": statistics.fmean(diagnostic_values),
        "sample_standard_deviation": statistics.stdev(diagnostic_values),
        "minimum": min(diagnostic_values),
        "maximum": max(diagnostic_values),
        "range": max(diagnostic_values) - min(diagnostic_values),
    }
    expected_source = _formal_execution_source_snapshot()
    if (
        variance.get("suite") != "stage9a-seed-variance-v4"
        or variance.get("status") != "completed_candidate_evidence"
        or variance.get("candidate_only") is not True
        or variance.get("promotion_authorized") is not False
        or variance.get("deployment_authorized") is not False
        or variance.get("contains_user_data") is not False
        or variance.get("execution_source_snapshot") != expected_source
        or variance.get("seed_count") != len(expected_rows)
        or variance.get("seeds") != expected_rows
        or variance.get("formal_gpu_training_seconds")
        != sum(row["wall_time_seconds"] for row in expected_rows)
        or variance.get("base_memory_adapter_diagnostic_reference_f1")
        != expected_diagnostic
        or variance.get("third_seed_executed")
        is not (len(expected_rows) == 3)
        or variance.get("additional_seed_authorized") is not False
        or variance.get("third_seed_decision_hash") != decision["content_hash"]
    ):
        raise ValueError("variance evidence is forged, stale, or cross-bound")
    return variance


def require_final_alignment_readiness() -> dict[str, Any]:
    """Close every non-private Stage 9A dependency before Owner data opens."""
    formal_source_archive = require_archived_source_snapshot()
    decision = require_third_seed_decision()
    compatibility = require_compatibility_evidence()
    variance = require_variance_evidence()
    expected_seeds = (
        [*REQUIRED_FORMAL_SEEDS, OPTIONAL_THIRD_SEED]
        if decision["decision"] == "run_optional_third_seed"
        else list(REQUIRED_FORMAL_SEEDS)
    )
    runs = completed_formal_runs()
    if [item["seed"] for item in runs] != expected_seeds:
        raise ValueError("final alignment readiness has an unclosed formal seed plan")
    boundary = _validated_training_boundary()
    exact = []
    for seed in expected_seeds:
        run, report, adapter, evaluation = _load_exact_formal_run_evidence(
            seed, boundary=boundary
        )
        exact.append({
            "seed": seed,
            "run_report_hash": report["content_hash"],
            "adapter_manifest_hash": adapter["content_hash"],
            "evaluation_hash": evaluation["content_hash"],
            "run_id": run["run_id"],
        })
    return {
        "formal_seeds": expected_seeds,
        "formal_evidence": exact,
        "third_seed_decision": decision,
        "compatibility": compatibility,
        "variance": variance,
        "boundary": boundary,
        "formal_execution_source_snapshot": FORMAL_EXECUTION_SOURCE_SNAPSHOT,
        "formal_execution_source_archive": formal_source_archive,
        "execution_source_snapshot": current_source_revision(PROJECT_ROOT),
    }


def validate_owner_alignment_evidence(
    owner_report: dict[str, Any], readiness: dict[str, Any]
) -> None:
    """Validate the final PRIVATE report and every local row after access is allowed."""
    from mlsys.training.stage9a_evaluation import (
        EXPECTED_OWNER_ALIGNMENT_PRIOR_FAILURE_HASH,
        EXPECTED_OWNER_ALIGNMENT_PRIOR_SUCCESS_HASH,
        EXPECTED_OWNER_ALIGNMENT_RESOURCE_REPORT_HASH,
        EXPECTED_OWNER_ALIGNMENT_RESOURCE_REPORT_SOURCE,
        OWNER_ALIGNMENT_EVALUATION_ID,
        OWNER_ALIGNMENT_EVALUATION_VERSION,
        OWNER_ALIGNMENT_PRIOR_FAILURE_ID,
        OWNER_ALIGNMENT_PRIOR_SUCCESS_ID,
        _canonical_v4_system_text,
        _require_prior_owner_alignment_failure,
        _require_prior_owner_alignment_success,
    )
    from mlsys.training.stage9a_rubric_v4 import (
        score_owner_alignment_case,
        summarize_owner_alignment_scores,
    )

    owner = load_and_verify_owner_alignment(OWNER_ALIGNMENT_PATH)
    cases = owner["cases"]
    expected = {case["case_id"]: case for case in cases}
    seeds = readiness["formal_seeds"]
    expected_arms = ["base", *[f"adapter_seed_{seed}" for seed in seeds]]
    expected_formal = readiness["formal_evidence"]
    expected_root = (RUNS_ROOT / OWNER_ALIGNMENT_EVALUATION_ID).resolve()
    system_text_hash = content_hash({"system_text": _canonical_v4_system_text()})
    prior_failure = _require_prior_owner_alignment_failure(
        RUNS_ROOT / OWNER_ALIGNMENT_PRIOR_FAILURE_ID / "failure.json"
    )
    prior_success = _require_prior_owner_alignment_success(
        RUNS_ROOT
        / OWNER_ALIGNMENT_PRIOR_SUCCESS_ID
        / "owner-alignment-evaluation.json"
    )
    expected_holdout = {
        str(item["seed"]): item["evaluation_hash"] for item in expected_formal
    }
    expected_adapters = {
        str(item["seed"]): item["adapter_manifest_hash"] for item in expected_formal
    }
    if (
        owner_report.get("evaluation_version") != OWNER_ALIGNMENT_EVALUATION_VERSION
        or owner_report.get("evaluation_id") != OWNER_ALIGNMENT_EVALUATION_ID
        or owner_report.get("status") != "completed_candidate_alignment_evaluation"
        or owner_report.get("candidate_only") is not True
        or owner_report.get("promotion_authorized") is not False
        or owner_report.get("deployment_authorized") is not False
        or owner_report.get("contains_user_data") is not True
        or owner_report.get("privacy_class") != "PRIVATE"
        or owner_report.get("local_only") is not True
        or owner_report.get("training_eligible") is not False
        or owner_report.get("validation_for_training") is not False
        or owner_report.get("hyperparameter_tuning_eligible") is not False
        or owner_report.get("prompt_tuning_eligible") is not False
        or owner_report.get("synthetic_generation_input_eligible") is not False
        or owner_report.get("owner_alignment_used_for_seed_decision") is not False
        or owner_report.get("seed_plan_closed_before_open") is not True
        or owner_report.get("content_hash")
        != EXPECTED_OWNER_ALIGNMENT_RESOURCE_REPORT_HASH
        or owner_report.get("execution_source_snapshot")
        != EXPECTED_OWNER_ALIGNMENT_RESOURCE_REPORT_SOURCE
        or owner_report.get("formal_execution_source_snapshot")
        != readiness["formal_execution_source_snapshot"]
        or owner_report.get("formal_execution_source_archive")
        != readiness["formal_execution_source_archive"]
        or owner_report.get("dataset_bundle_hash") != dataset_bundle_hash(DATASET_ROOT)
        or owner_report.get("base_repository") != load_model_manifest()["repository"]
        or owner_report.get("base_revision") != load_model_manifest()["revision"]
        or owner_report.get("owner_alignment_file_sha256")
        != OWNER_ALIGNMENT_FILE_SHA256
        or owner_report.get("owner_alignment_content_hash") != owner["content_hash"]
        or owner_report.get("owner_alignment_member_manifest_hash")
        != owner["member_manifest_hash"]
        or owner_report.get("owner_alignment_case_count") != 70
        or owner_report.get("canonical_v4_system_text_hash") != system_text_hash
        or owner_report.get("owner_alignment_prompt_contract") != {
            "source": "exact_unique_frozen_dataset_v4_system_text",
            "memory_context_supplied": False,
            "case_messages_used_without_rewrite": True,
        }
        or owner_report.get("supersedes_failed_evidence_hash")
        != EXPECTED_OWNER_ALIGNMENT_PRIOR_FAILURE_HASH
        or owner_report.get("supersedes_owner_alignment_report_hash")
        != EXPECTED_OWNER_ALIGNMENT_PRIOR_SUCCESS_HASH
        or prior_success.get("content_hash")
        != EXPECTED_OWNER_ALIGNMENT_PRIOR_SUCCESS_HASH
        or owner_report.get("formal_seeds") != seeds
        or owner_report.get("formal_adapter_manifest_hashes") != expected_adapters
        or owner_report.get("formal_evidence") != expected_formal
        or owner_report.get("third_seed_decision_hash")
        != readiness["third_seed_decision"]["content_hash"]
        or owner_report.get("variance_evidence_hash")
        != readiness["variance"]["content_hash"]
        or owner_report.get("compatibility_evidence_hash")
        != readiness["compatibility"]["content_hash"]
        or owner_report.get("sealed_holdout_evaluation_hashes") != expected_holdout
        or owner_report.get("behavioral_review_status")
        != "product_owner_review_required"
        or not _resource_evidence_is_within_stage9a_limits(
            owner_report.get("systems_metrics", {}).get("resources", {}),
            peak_target_mib=TARGET_VRAM_MIB,
        )
    ):
        raise ValueError("Owner Alignment evidence is incomplete, stale, or cross-bound")
    arms = owner_report.get("arms", [])
    if [arm.get("arm") for arm in arms] != expected_arms:
        raise ValueError("Owner Alignment evidence does not contain the exact arm set")
    for arm in arms:
        if arm.get("arm") == "base":
            expected_seed = None
            expected_adapter = None
        else:
            expected_seed = int(str(arm.get("arm", "")).rsplit("_", 1)[-1])
            expected_adapter = expected_adapters.get(str(expected_seed))
        if (
            arm.get("formal_seed") != expected_seed
            or arm.get("adapter_manifest_hash") != expected_adapter
        ):
            raise ValueError("Owner Alignment arm is not bound to its exact adapter")
        artifact = Path(str(arm.get("private_output_artifact", ""))).resolve()
        if artifact.parent != expected_root or not artifact.is_file():
            raise ValueError("Owner Alignment private artifact escapes or is missing")
        if sha256_file(artifact) != arm.get("private_output_artifact_sha256"):
            raise ValueError("Owner Alignment private artifact hash mismatch")
        rows = [
            json.loads(line)
            for line in artifact.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if len(rows) != 70 or arm.get("case_count") != 70:
            raise ValueError("Owner Alignment arm does not contain exactly 70 cases")
        seen: set[str] = set()
        for row in rows:
            case_id = row.get("case_id")
            if case_id in seen or case_id not in expected:
                raise ValueError("Owner Alignment arm has duplicate or unknown case")
            seen.add(case_id)
            material = dict(row)
            claimed = material.pop("content_hash", None)
            if claimed != content_hash(material):
                raise ValueError("Owner Alignment result row content hash mismatch")
            if (
                row.get("source_content_hash") != expected[case_id]["content_hash"]
                or row.get("evaluation_id") != OWNER_ALIGNMENT_EVALUATION_ID
                or row.get("arm") != arm.get("arm")
                or row.get("formal_seed") != expected_seed
                or row.get("adapter_manifest_hash") != expected_adapter
                or row.get("memory_enabled") is not False
                or row.get("canonical_v4_system_text_hash") != system_text_hash
                or row.get("privacy_class") != "PRIVATE"
                or row.get("local_only") is not True
                or row.get("training_eligible") is not False
            ):
                raise ValueError("Owner Alignment row violates provenance or privacy")
            expected_scores = score_owner_alignment_case(
                expected[case_id], row.get("text", "")
            )
            if row.get("scores") != expected_scores:
                raise ValueError("Owner Alignment scores are not canonical-text-derived")
        if seen != set(expected):
            raise ValueError("Owner Alignment arm omits cases")
        if arm.get("behavioral_metrics") != summarize_owner_alignment_scores(rows):
            raise ValueError("Owner Alignment behavioral summary is not row-derived")


def validate_run_evidence_bindings(
    *,
    seed: int,
    report: dict[str, Any],
    adapter: dict[str, Any],
    evaluation: dict[str, Any],
    rescore: dict[str, Any] | None = None,
    boundary: dict[str, Any],
    model_manifest: dict[str, Any],
    expected_source_snapshot: str | None = None,
) -> None:
    """Reject cross-record substitutions before candidate registration."""
    expected_source = expected_source_snapshot or _formal_execution_source_snapshot()
    expected_arms = set(EXPECTED_EVALUATION_ARMS)
    for name, artifact, expected_status in (
        ("training report", report, "completed_candidate"),
        ("evaluation", evaluation, "completed_candidate_evaluation"),
    ):
        if (
            artifact.get("status") != expected_status
            or artifact.get("candidate_only") is not True
            or artifact.get("promotion_authorized") is not False
            or artifact.get("deployment_authorized") is not False
            or artifact.get("contains_user_data") is not False
        ):
            raise ValueError(f"{name} violates the Stage 9A candidate/data boundary")
        if artifact.get("execution_source_snapshot") != expected_source:
            raise ValueError(f"{name} is not bound to the current execution source")
    if (
        int(report.get("seed", -1)) != seed
        or report.get("formal") is not True
        or report.get("run_id") != adapter.get("run_id")
        or report.get("adapter_manifest_hash") != adapter.get("content_hash")
        or report.get("execution_source_snapshot") != adapter.get("execution_source_snapshot")
        or report.get("training_implementation") != TRAINING_IMPLEMENTATION_VERSION
        or report.get("dataset_bundle_hash") != boundary.get("dataset_bundle_hash")
        or report.get("rendered_manifest_hash") != boundary.get("rendered_manifest_hash")
        or report.get("training_input_boundary_hash") != boundary.get("content_hash")
        or report.get("training_summary") != adapter.get("training_summary")
        or report.get("remediated_gate_c_hash") != adapter.get("remediated_gate_c_hash")
        or adapter.get("dataset_bundle_hash") != boundary.get("dataset_bundle_hash")
        or adapter.get("rendered_manifest_hash") != boundary.get("rendered_manifest_hash")
        or adapter.get("execution_source_snapshot") != expected_source
        or not _resource_evidence_is_within_stage9a_limits(
            report.get("resource_evidence", {}), peak_target_mib=TARGET_VRAM_MIB
        )
    ):
        raise ValueError("training report and adapter binding are not an exact cross-record match")
    if (
        evaluation.get("evaluation_id") != FORMAL_EVALUATION_IDS.get(seed)
        or evaluation.get("execution_source_snapshot") != expected_source
        or evaluation.get("adapter_manifest_hash") != adapter.get("content_hash")
        or evaluation.get("dataset_bundle_hash") != boundary.get("dataset_bundle_hash")
        or evaluation.get("base_repository") != model_manifest.get("repository")
        or evaluation.get("base_revision") != model_manifest.get("revision")
        or evaluation.get("holdout_count") != SPLIT_COUNTS["holdout"]
        or evaluation.get("holdout_used_for_training_or_selection") is not False
        or evaluation.get("owner_alignment_set_used_for_training_or_selection") is not False
        or {arm.get("arm") for arm in evaluation.get("arms", [])} != expected_arms
        or any(
            arm.get("case_count") != SPLIT_COUNTS["holdout"]
            for arm in evaluation.get("arms", [])
        )
        or not _resource_evidence_is_within_stage9a_limits(
            evaluation.get("systems_metrics", {}).get("resources", {}),
            peak_target_mib=TARGET_VRAM_MIB,
        )
    ):
        raise ValueError("evaluation is not exactly bound to the adapter/base/dataset/four arms")
    if rescore is not None:
        if (
            rescore.get("evaluation_id") != evaluation.get("evaluation_id")
            or rescore.get("source_evaluation_content_hash") != evaluation.get("content_hash")
            or rescore.get("dataset_bundle_hash") != boundary.get("dataset_bundle_hash")
            or rescore.get("holdout_count") != SPLIT_COUNTS["holdout"]
            or rescore.get("holdout_used_for_training_or_selection") is not False
            or {arm.get("arm") for arm in rescore.get("arms", [])} != expected_arms
            or any(
                arm.get("case_count") != SPLIT_COUNTS["holdout"]
                for arm in rescore.get("arms", [])
            )
        ):
            raise ValueError("rescore is not exactly bound to its source evaluation and holdout")
    if adapter.get("content_hash") not in {
        item.get("adapter_manifest_hash")
        for item in evaluation.get("completed_formal_runs", [])
    }:
        raise ValueError("evaluation formal-run set does not contain its selected adapter")


def _candidate_model_record(
    model_manifest: dict[str, Any], provenance: dict[str, Any]
) -> dict[str, Any]:
    return {
        "model_version_id": model_manifest["manifest_id"],
        "logical_name": "Qwen3-8B Stage 9A exact base",
        "provider_or_registry": "huggingface",
        "upstream_model_id": model_manifest["repository"],
        "upstream_revision": model_manifest["revision"],
        "artifact_uri": provenance["target"],
        "artifact_manifest_hash": provenance["content_hash"],
        "artifact_size_bytes": provenance["artifact_size_bytes"],
        "weights_format": "safetensors",
        "precision": "bf16-base-nf4-training-load",
        "tokenizer_files": [
            item for item in provenance["files"]
            if item["path"].startswith("tokenizer")
            or item["path"] in {"tokenizer_config.json", "generation_config.json"}
        ],
        "license": provenance["license"],
        "lifecycle_status": "candidate",
    }


def build_candidate_registry() -> dict[str, Any]:
    """Register the exact local model, runs, adapters, and evaluations as candidates."""
    if REGISTRY_PATH.exists():
        raise FileExistsError("immutable Stage 9A candidate registry already exists")
    readiness = require_final_alignment_readiness()
    compatibility = readiness["compatibility"]
    variance = readiness["variance"]
    third_seed_decision = readiness["third_seed_decision"]
    from mlsys.training.stage9a_evaluation import OWNER_ALIGNMENT_EVALUATION_ID

    owner_alignment_path = (
        RUNS_ROOT / OWNER_ALIGNMENT_EVALUATION_ID / "owner-alignment-evaluation.json"
    )
    owner_alignment = read_hashed_json(owner_alignment_path)
    validate_owner_alignment_evidence(owner_alignment, readiness)
    boundary = readiness["boundary"]
    environment = read_hashed_json(EVIDENCE_ROOT / "environment.json")
    provenance = read_hashed_json(EVIDENCE_ROOT / "qwen3-8b-provenance.json")
    rendered = read_hashed_json(RENDERED_ROOT / "manifest.json")
    model_manifest = load_model_manifest()
    runs = completed_formal_runs()
    expected_seed_list = [item["seed"] for item in runs]
    training_runs = []
    adapters = []
    for run in runs:
        seed = run["seed"]
        report = read_hashed_json(Path(run["report_path"]))
        adapter = verify_adapter_binding(Path(run["adapter_dir"]))
        evaluation = read_hashed_json(
            RUNS_ROOT / FORMAL_EVALUATION_IDS[seed] / "four-arm-evaluation.json"
        )
        validate_run_evidence_bindings(
            seed=seed,
            report=report,
            adapter=adapter,
            evaluation=evaluation,
            boundary=boundary,
            model_manifest=model_manifest,
        )
        training_runs.append({
            "training_run_id": report["run_id"],
            "seed": seed,
            "framework": report["framework"],
            "method": "qlora",
            "dataset_snapshot_hash": adapter["dataset_bundle_hash"],
            "rendered_training_artifact_hash": adapter["rendered_manifest_hash"],
            "base_model_revision": adapter["base_revision"],
            "environment_hash": environment["content_hash"],
            "report_path": str(Path(run["report_path"]).resolve()),
            "report_hash": report["content_hash"],
            "execution_source_snapshot": report["execution_source_snapshot"],
            "status": "completed_candidate",
            "candidate_only": True,
            "contains_user_data": report["contains_user_data"],
        })
        adapters.append({
            "adapter_version_id": f"qwen3-8b-stage9a-qlora-seed-{seed}",
            "adapter_type": "qlora",
            "base_model_version_id": model_manifest["manifest_id"],
            "required_base_revision": adapter["base_revision"],
            "required_base_provenance_hash": adapter["base_provenance_hash"],
            "target_modules": adapter["lora"]["target_modules"],
            "rank": adapter["lora"]["rank"],
            "alpha": adapter["lora"]["alpha"],
            "dropout": adapter["lora"]["dropout"],
            "artifact_uri": str(Path(run["adapter_dir"]).resolve()),
            "artifact_hash": adapter["adapter_sha256"],
            "adapter_manifest_hash": adapter["content_hash"],
            "dataset_snapshot_hash": adapter["dataset_bundle_hash"],
            "training_run_id": report["run_id"],
            "training_environment_hash": environment["content_hash"],
            "evaluation_run_ids": [evaluation["evaluation_id"]],
            "evaluation_report_hash": evaluation["content_hash"],
            "behavioral_scorer_policy": (
                "v4_property_rubric_primary_reference_similarity_diagnostic_only"
            ),
            "lifecycle_status": "candidate",
            "candidate_only": True,
            "promotion_authorized": False,
            "deployment_authorized": False,
            "deployed": False,
        })
    expected_seeds = [item["seed"] for item in runs]
    compatibility_rows = compatibility.get("correct_exact_bindings", [])
    if (
        compatibility.get("status") != "passed"
        or compatibility.get("candidate_only") is not True
        or compatibility.get("promotion_authorized") is not False
        or compatibility.get("deployment_authorized") is not False
        or compatibility.get("contains_user_data") is not False
        or [item.get("seed") for item in compatibility_rows] != expected_seeds
        or [item.get("adapter_manifest_hash") for item in compatibility_rows]
        != [item["adapter_manifest_hash"] for item in adapters]
        or {item.get("probe") for item in compatibility.get("fail_closed_probes", [])}
        != {
            "wrong_exact_revision", "wrong_base_artifact",
            "incompatible_adapter_configuration", "incompatible_target_modules",
            "incompatible_structural_flag",
        }
        or any(
            item.get("status") != "passed_rejected"
            for item in compatibility.get("fail_closed_probes", [])
        )
    ):
        raise ValueError("compatibility evidence is not exactly bound to the candidate adapters")
    variance_rows = variance.get("seeds", [])
    by_seed = {item["seed"]: item for item in variance_rows}
    if (
        variance.get("status") != "completed_candidate_evidence"
        or variance.get("candidate_only") is not True
        or variance.get("promotion_authorized") is not False
        or variance.get("deployment_authorized") is not False
        or variance.get("contains_user_data") is not False
        or sorted(by_seed) != expected_seeds
        or any(
            by_seed[item["seed"]].get("training_report_hash") != item["report_hash"]
            or by_seed[item["seed"]].get("adapter_manifest_hash")
            != adapters[index]["adapter_manifest_hash"]
            or by_seed[item["seed"]].get("evaluation_report_hash")
            != adapters[index]["evaluation_report_hash"]
            for index, item in enumerate(training_runs)
        )
    ):
        raise ValueError("variance evidence is not exactly bound to the candidate run set")
    write_hashed_json(REGISTRY_PATH, {
        "schema_version": 1,
        "registry_version": REGISTRY_VERSION,
        "supersedes_candidate_registry_hash": SUPERSEDED_CANDIDATE_REGISTRY_HASH,
        "resource_evidence_validation_version": (
            RESOURCE_EVIDENCE_VALIDATION_VERSION
        ),
        "status": "candidate_only",
        "registry_source_snapshot": current_source_revision(PROJECT_ROOT),
        "training_execution_source_snapshots": sorted({
            item["execution_source_snapshot"] for item in training_runs
        }),
        "formal_execution_source_archive": readiness[
            "formal_execution_source_archive"
        ],
        "owner_alignment_execution_source_snapshot": owner_alignment[
            "execution_source_snapshot"
        ],
        "local_only": True,
        "contains_user_data": boundary["contains_user_data"],
        "training_input_boundary_evidence_hash": boundary["content_hash"],
        "promotion_authorized": False,
        "deployment_authorized": False,
        "stage9b_authorized": False,
        "stage10_authorized": False,
        "model": _candidate_model_record(model_manifest, provenance),
        "dataset": {
            "dataset_bundle_hash": dataset_bundle_hash(DATASET_ROOT),
            "rendered_manifest_hash": rendered["content_hash"],
            "rendered_splits": rendered["rendered_splits"],
            "holdout_rendered": rendered["holdout_rendered"],
        },
        "training_environment_hash": environment["content_hash"],
        "training_runs": training_runs,
        "adapters": adapters,
        "compatibility_evidence_hash": compatibility["content_hash"],
        "variance_evidence_hash": variance["content_hash"],
        "third_seed_decision_hash": third_seed_decision["content_hash"],
        "owner_alignment_evaluation": {
            "report_path": str(owner_alignment_path.resolve()),
            "report_hash": owner_alignment["content_hash"],
            "privacy_class": "PRIVATE",
            "local_only": True,
            "training_feedback_allowed": False,
            "product_owner_review_required": True,
        },
        "registered_at": datetime.now(UTC).isoformat(),
    })
    return require_candidate_registry()


def require_candidate_registry() -> dict[str, Any]:
    """Revalidate a persisted candidate registry against every current artifact."""
    from mlsys.training.stage9a_evaluation import OWNER_ALIGNMENT_EVALUATION_ID

    registry = read_hashed_json(REGISTRY_PATH)
    readiness = require_final_alignment_readiness()
    owner_path = (
        RUNS_ROOT / OWNER_ALIGNMENT_EVALUATION_ID / "owner-alignment-evaluation.json"
    )
    owner = read_hashed_json(owner_path)
    validate_owner_alignment_evidence(owner, readiness)
    environment = read_hashed_json(EVIDENCE_ROOT / "environment.json")
    provenance = read_hashed_json(EVIDENCE_ROOT / "qwen3-8b-provenance.json")
    rendered = read_hashed_json(RENDERED_ROOT / "manifest.json")
    model_manifest = load_model_manifest()
    source = require_registry_validation_source()
    expected_training = []
    expected_adapters = []
    for item in readiness["formal_evidence"]:
        seed = item["seed"]
        run, report, adapter, evaluation = _load_exact_formal_run_evidence(
            seed, boundary=readiness["boundary"]
        )
        expected_training.append({
            "training_run_id": report["run_id"],
            "seed": seed,
            "framework": report["framework"],
            "method": "qlora",
            "dataset_snapshot_hash": adapter["dataset_bundle_hash"],
            "rendered_training_artifact_hash": adapter["rendered_manifest_hash"],
            "base_model_revision": adapter["base_revision"],
            "environment_hash": environment["content_hash"],
            "report_path": str(Path(run["report_path"]).resolve()),
            "report_hash": report["content_hash"],
            "execution_source_snapshot": report["execution_source_snapshot"],
            "status": "completed_candidate",
            "candidate_only": True,
            "contains_user_data": False,
        })
        expected_adapters.append({
            "adapter_version_id": f"qwen3-8b-stage9a-qlora-seed-{seed}",
            "adapter_type": "qlora",
            "base_model_version_id": model_manifest["manifest_id"],
            "required_base_revision": adapter["base_revision"],
            "required_base_provenance_hash": adapter["base_provenance_hash"],
            "target_modules": adapter["lora"]["target_modules"],
            "rank": adapter["lora"]["rank"],
            "alpha": adapter["lora"]["alpha"],
            "dropout": adapter["lora"]["dropout"],
            "artifact_uri": str(Path(run["adapter_dir"]).resolve()),
            "artifact_hash": adapter["adapter_sha256"],
            "adapter_manifest_hash": adapter["content_hash"],
            "dataset_snapshot_hash": adapter["dataset_bundle_hash"],
            "training_run_id": report["run_id"],
            "training_environment_hash": environment["content_hash"],
            "evaluation_run_ids": [evaluation["evaluation_id"]],
            "evaluation_report_hash": evaluation["content_hash"],
            "behavioral_scorer_policy": (
                "v4_property_rubric_primary_reference_similarity_diagnostic_only"
            ),
            "lifecycle_status": "candidate",
            "candidate_only": True,
            "promotion_authorized": False,
            "deployment_authorized": False,
            "deployed": False,
        })
    model = registry.get("model", {})
    expected_model = _candidate_model_record(model_manifest, provenance)
    dataset = registry.get("dataset", {})
    owner_link = registry.get("owner_alignment_evaluation", {})
    if (
        registry.get("schema_version") != 1
        or registry.get("registry_version")
        != REGISTRY_VERSION
        or registry.get("supersedes_candidate_registry_hash")
        != SUPERSEDED_CANDIDATE_REGISTRY_HASH
        or registry.get("resource_evidence_validation_version")
        != RESOURCE_EVIDENCE_VALIDATION_VERSION
        or registry.get("status") != "candidate_only"
        or registry.get("registry_source_snapshot") != source
        or registry.get("training_execution_source_snapshots")
        != [FORMAL_EXECUTION_SOURCE_SNAPSHOT]
        or registry.get("formal_execution_source_archive")
        != readiness["formal_execution_source_archive"]
        or registry.get("owner_alignment_execution_source_snapshot")
        != owner["execution_source_snapshot"]
        or registry.get("local_only") is not True
        or registry.get("contains_user_data") is not False
        or registry.get("training_input_boundary_evidence_hash")
        != readiness["boundary"]["content_hash"]
        or registry.get("promotion_authorized") is not False
        or registry.get("deployment_authorized") is not False
        or registry.get("stage9b_authorized") is not False
        or registry.get("stage10_authorized") is not False
        or registry.get("training_environment_hash") != environment["content_hash"]
        or registry.get("training_runs") != expected_training
        or registry.get("adapters") != expected_adapters
        or registry.get("compatibility_evidence_hash")
        != readiness["compatibility"]["content_hash"]
        or registry.get("variance_evidence_hash")
        != readiness["variance"]["content_hash"]
        or registry.get("third_seed_decision_hash")
        != readiness["third_seed_decision"]["content_hash"]
        or model != expected_model
        or dataset.get("dataset_bundle_hash") != dataset_bundle_hash(DATASET_ROOT)
        or dataset.get("rendered_manifest_hash") != rendered["content_hash"]
        or dataset.get("rendered_splits") != ["train", "validation"]
        or dataset.get("holdout_rendered") is not False
        or owner_link.get("report_path") != str(owner_path.resolve())
        or owner_link.get("report_hash") != owner["content_hash"]
        or owner_link.get("privacy_class") != "PRIVATE"
        or owner_link.get("local_only") is not True
        or owner_link.get("training_feedback_allowed") is not False
        or owner_link.get("product_owner_review_required") is not True
    ):
        raise ValueError("candidate registry is forged, stale, or cross-bound")
    return registry
