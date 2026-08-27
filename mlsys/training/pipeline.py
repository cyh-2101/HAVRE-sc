"""Dependency-free local LoRA/QLoRA algorithmic dry-run over safe fixtures."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import random
import re
import time
from typing import Sequence
from uuid import UUID

from companion.hashing import content_hash
from mlsys.training.models import (
    AdapterCompatibilityReport,
    AdapterRejectionRecord,
    AdapterVersion,
    CanonicalTrainingExample,
    EvaluationHoldoutCase,
    EvaluationHoldoutSuite,
    FactorialArmResult,
    FactorialEvaluationReport,
    GovernanceVersionSet,
    ModelVersion,
    RenderedTrainingArtifact,
    RenderedTrainingExample,
    TrainingConfig,
    TrainingDatasetSnapshot,
    TrainingRun,
)


FEATURES = 32
OUTPUTS = 16


@dataclass(frozen=True)
class Stage9Experiment:
    snapshot: TrainingDatasetSnapshot
    holdout_suite: EvaluationHoldoutSuite
    model: ModelVersion
    rendered_artifact: RenderedTrainingArtifact
    training_runs: tuple[TrainingRun, ...]
    adapters: tuple[AdapterVersion, ...]
    compatibility_reports: tuple[AdapterCompatibilityReport, ...]
    evaluation: FactorialEvaluationReport
    rejection: AdapterRejectionRecord


def _fixture_bytes(path: Path, *, expected_fixture_id: str) -> bytes:
    raw = path.read_bytes()
    parsed = json.loads(raw)
    if parsed.get("fixture_id") != expected_fixture_id:
        raise ValueError("unexpected Stage 9 fixture identity")
    if parsed.get("license_id") != "CC0-1.0":
        raise ValueError("Stage 9 fixture must have an explicit public-domain license")
    return raw


def build_stage9_fixture_snapshot(
    *, owner_id: UUID, training_fixture_path: Path, holdout_fixture_path: Path
) -> TrainingDatasetSnapshot:
    return build_stage9_fixture_assets(
        owner_id=owner_id,
        training_fixture_path=training_fixture_path,
        holdout_fixture_path=holdout_fixture_path,
    )[0]


def build_stage9_fixture_assets(
    *, owner_id: UUID, training_fixture_path: Path, holdout_fixture_path: Path
) -> tuple[TrainingDatasetSnapshot, EvaluationHoldoutSuite]:
    training_raw = _fixture_bytes(
        training_fixture_path, expected_fixture_id="stage9-synthetic-public-training-v2"
    )
    holdout_raw = _fixture_bytes(
        holdout_fixture_path, expected_fixture_id="stage9-synthetic-public-holdout-v2"
    )
    training_payload = json.loads(training_raw)
    holdout_payload = json.loads(holdout_raw)
    training_fixture_hash = "sha256:" + hashlib.sha256(training_raw).hexdigest()
    holdout_fixture_hash = "sha256:" + hashlib.sha256(holdout_raw).hexdigest()
    training_examples = tuple(
        CanonicalTrainingExample.model_validate(item)
        for item in training_payload["examples"]
    )
    holdout_cases = tuple(
        EvaluationHoldoutCase.model_validate(
            {**item, "training_eligible": False, "evaluation_only": True, "access_limited": True}
        )
        for item in holdout_payload["examples"]
    )
    holdout_manifest = content_hash(
        tuple(
            sorted(
                (
                    {
                        "example_id": case.example_id,
                        "content_hash": case.content_hash,
                        "source_ref": case.source_ref,
                    }
                    for case in holdout_cases
                ),
                key=lambda item: item["example_id"],
            )
        )
    )
    snapshot = TrainingDatasetSnapshot(
        owner_id=owner_id,
        fixture_content_hash=training_fixture_hash,
        examples=training_examples,
        excluded_evaluation_holdout_ids=tuple(case.example_id for case in holdout_cases),
        excluded_evaluation_holdout_manifest_hash=holdout_manifest,
    )
    holdout_suite = EvaluationHoldoutSuite(
        owner_id=owner_id,
        dataset_snapshot_id=snapshot.dataset_snapshot_id,
        fixture_content_hash=holdout_fixture_hash,
        cases=holdout_cases,
    )
    if holdout_suite.member_manifest_hash != snapshot.excluded_evaluation_holdout_manifest_hash:
        raise ValueError("excluded holdout manifest is not bound to evaluation suite")
    return snapshot, holdout_suite


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[a-z0-9]+", text.lower()))[:128]


def _token_ids(text: str) -> tuple[int, ...]:
    return tuple(
        int.from_bytes(hashlib.sha256(token.encode()).digest()[:4], "big") % FEATURES
        for token in _tokens(text)
    )


def _vector(text: str, size: int) -> list[float]:
    result = [0.0] * size
    for token in _tokens(text):
        index = int.from_bytes(hashlib.sha256(token.encode()).digest()[:4], "big") % size
        result[index] += 1.0
    norm = math.sqrt(sum(value * value for value in result)) or 1.0
    return [value / norm for value in result]


def _matvec(matrix: Sequence[Sequence[float]], vector: Sequence[float]) -> list[float]:
    return [sum(weight * value for weight, value in zip(row, vector)) for row in matrix]


def _base_matrix(seed: int = 90817) -> list[list[float]]:
    rng = random.Random(seed)
    return [[rng.uniform(-0.08, 0.08) for _ in range(FEATURES)] for _ in range(OUTPUTS)]


def _quantize_4bit(matrix: Sequence[Sequence[float]]) -> list[list[float]]:
    flat = [abs(value) for row in matrix for value in row]
    scale = (max(flat) or 1.0) / 7.0
    return [[max(-8, min(7, round(value / scale))) * scale for value in row] for row in matrix]


def _adapter_delta(
    a: Sequence[Sequence[float]], b: Sequence[Sequence[float]], alpha: int, rank: int
) -> list[list[float]]:
    scale = alpha / rank
    return [
        [scale * sum(b[o][r] * a[r][f] for r in range(rank)) for f in range(FEATURES)]
        for o in range(OUTPUTS)
    ]


def _combined(
    base: Sequence[Sequence[float]], delta: Sequence[Sequence[float]] | None
) -> list[list[float]]:
    if delta is None:
        return [list(row) for row in base]
    return [[base[o][f] + delta[o][f] for f in range(FEATURES)] for o in range(OUTPUTS)]


def _loss(matrix: Sequence[Sequence[float]], examples: Sequence[CanonicalTrainingExample]) -> float:
    total = 0.0
    for example in examples:
        x = _vector(example.input_text, FEATURES)
        target = _vector(example.expected_text, OUTPUTS)
        predicted = _matvec(matrix, x)
        total += sum((predicted[i] - target[i]) ** 2 for i in range(OUTPUTS)) / OUTPUTS
    return total / len(examples)


def _train_adapter(
    *, base: list[list[float]], examples: Sequence[CanonicalTrainingExample], config: TrainingConfig
) -> tuple[list[list[float]], list[list[float]], float, float]:
    rng = random.Random(config.seed)
    a = [[rng.uniform(-0.02, 0.02) for _ in range(FEATURES)] for _ in range(config.rank)]
    b = [[0.0 for _ in range(config.rank)] for _ in range(OUTPUTS)]
    initial = _loss(base, examples)
    scale = config.alpha / config.rank
    for _ in range(config.epochs):
        for example in examples:
            x = _vector(example.input_text, FEATURES)
            target = _vector(example.expected_text, OUTPUTS)
            hidden = [sum(a[r][f] * x[f] for f in range(FEATURES)) for r in range(config.rank)]
            predicted = [
                sum(base[o][f] * x[f] for f in range(FEATURES))
                + scale * sum(b[o][r] * hidden[r] for r in range(config.rank))
                for o in range(OUTPUTS)
            ]
            error = [predicted[o] - target[o] for o in range(OUTPUTS)]
            old_b = [row[:] for row in b]
            for o in range(OUTPUTS):
                for r in range(config.rank):
                    b[o][r] -= config.learning_rate * error[o] * scale * hidden[r]
            for r in range(config.rank):
                upstream = sum(error[o] * old_b[o][r] for o in range(OUTPUTS)) * scale
                for f in range(FEATURES):
                    a[r][f] -= config.learning_rate * upstream * x[f]
    delta = _adapter_delta(a, b, config.alpha, config.rank)
    final = _loss(_combined(base, delta), examples)
    return a, b, initial, final


def check_adapter_compatibility(
    *, adapter: AdapterVersion, model: ModelVersion
) -> AdapterCompatibilityReport:
    mismatches: list[str] = []
    if adapter.base_model_version_id != model.model_version_id:
        mismatches.append("base_model_version_id")
    if adapter.required_base_artifact_hash != model.artifact_hash:
        mismatches.append("base_artifact_hash")
    return AdapterCompatibilityReport(
        owner_id=adapter.owner_id,
        adapter_version_id=adapter.adapter_version_id,
        model_version_id=model.model_version_id,
        checked_base_artifact_hash=model.artifact_hash,
        tokenizer_version=model.tokenizer_version,
        compatible=not mismatches,
        mismatch_codes=tuple(mismatches),
    )


def _alignment(
    matrix: Sequence[Sequence[float]],
    examples: Sequence[CanonicalTrainingExample | EvaluationHoldoutCase],
    memory: bool,
) -> float:
    scores: list[float] = []
    for example in examples:
        text = example.input_text
        if memory and example.memory_hint:
            text += " " + example.memory_hint
        predicted = _matvec(matrix, _vector(text, FEATURES))
        target = _vector(example.expected_text, OUTPUTS)
        dot = sum(predicted[i] * target[i] for i in range(OUTPUTS))
        denom = math.sqrt(sum(v * v for v in predicted)) or 1.0
        scores.append(max(0.0, min(1.0, dot / denom)))
    return sum(scores) / len(scores)


def run_stage9_synthetic_dry_run(
    *, owner_id: UUID, training_fixture_path: Path, holdout_fixture_path: Path,
    governance_versions: GovernanceVersionSet
) -> Stage9Experiment:
    snapshot, holdout_suite = build_stage9_fixture_assets(
        owner_id=owner_id,
        training_fixture_path=training_fixture_path,
        holdout_fixture_path=holdout_fixture_path,
    )
    base = _base_matrix()
    base_hash = content_hash(base)
    model = ModelVersion(
        owner_id=owner_id,
        upstream_revision=base_hash,
        artifact_uri="local-artifact://stage9/models/toy-base-v1",
        artifact_hash=base_hash,
    )
    rendered_artifact = RenderedTrainingArtifact(
        owner_id=owner_id,
        dataset_snapshot_id=snapshot.dataset_snapshot_id,
        model_version_id=model.model_version_id,
        source_member_manifest_hash=snapshot.member_manifest_hash,
        examples=tuple(
            RenderedTrainingExample(
                example_id=example.example_id,
                rendered_text=f"<user>{example.input_text}</user><assistant>{example.expected_text}</assistant>",
                input_token_ids=_token_ids(example.input_text),
                target_token_ids=_token_ids(example.expected_text),
                source_content_hash=example.content_hash,
            )
            for example in snapshot.examples
        ),
    )
    train = tuple(example for example in snapshot.examples if example.split == "train")
    validation = tuple(example for example in snapshot.examples if example.split == "validation")
    holdout = holdout_suite.cases
    runs: list[TrainingRun] = []
    adapters: list[AdapterVersion] = []
    deltas: dict[str, list[list[float]]] = {}
    for method, seed in (("lora", 1701), ("qlora", 1702)):
        config = TrainingConfig(
            method=method,
            seed=seed,
            base_quantization_bits=4 if method == "qlora" else None,
        )
        training_base = _quantize_4bit(base) if method == "qlora" else base
        a, b, initial, final = _train_adapter(base=training_base, examples=train, config=config)
        matrix_hash = content_hash({"a": a, "b": b, "method": method})
        run = TrainingRun(
            owner_id=owner_id,
            dataset_snapshot_id=snapshot.dataset_snapshot_id,
            model_version_id=model.model_version_id,
            rendered_artifact_id=rendered_artifact.rendered_artifact_id,
            config=config,
            governance_versions=governance_versions,
            training_example_count=len(train),
            validation_example_count=len(validation),
            initial_loss=initial,
            final_loss=final,
            adapter_matrix_hash=matrix_hash,
        )
        adapter = AdapterVersion(
            owner_id=owner_id,
            adapter_type=method,
            base_model_version_id=model.model_version_id,
            required_base_artifact_hash=model.artifact_hash,
            dataset_snapshot_id=snapshot.dataset_snapshot_id,
            training_run_id=run.training_run_id,
            artifact_uri=f"local-artifact://stage9/adapters/{method}-{run.training_run_id}",
            artifact_hash=matrix_hash,
        )
        runs.append(run)
        adapters.append(adapter)
        deltas[method] = _adapter_delta(a, b, config.alpha, config.rank)
    reports = tuple(check_adapter_compatibility(adapter=adapter, model=model) for adapter in adapters)
    selected = adapters[1]
    selected_delta = deltas[selected.adapter_type]
    quantized = _quantize_4bit(base)
    started = time.perf_counter()
    matrices = {
        "base": quantized,
        "base_memory": quantized,
        "base_adapter": _combined(quantized, selected_delta),
        "base_memory_adapter": _combined(quantized, selected_delta),
    }
    arms: list[FactorialArmResult] = []
    for name, matrix in matrices.items():
        arm_started = time.perf_counter()
        score = _alignment(matrix, holdout, "memory" in name)
        latency = (time.perf_counter() - arm_started) * 1000.0
        arms.append(
            FactorialArmResult(
                arm=name,
                case_count=len(holdout),
                synthetic_alignment_score=score,
                measured_latency_ms=latency,
                limitations=(
                    "Metric is a hashed-vector fixture alignment score, not human usefulness.",
                    "No transformer weights or personal data were used.",
                ),
            )
        )
    elapsed = (time.perf_counter() - started) * 1000.0
    evaluation = FactorialEvaluationReport(
        owner_id=owner_id,
        dataset_snapshot_id=snapshot.dataset_snapshot_id,
        holdout_suite_id=holdout_suite.holdout_suite_id,
        model_version_id=model.model_version_id,
        adapter_version_id=selected.adapter_version_id,
        seeds=tuple(run.config.seed for run in runs),
        arms=tuple(arms),
        adapter_load_ms=elapsed,
        adapter_switch_ms=elapsed,
    )
    rejection = AdapterRejectionRecord(
        owner_id=owner_id,
        adapter_version_id=selected.adapter_version_id,
        evaluation_report_id=evaluation.evaluation_report_id,
    )
    return Stage9Experiment(
        snapshot=snapshot,
        holdout_suite=holdout_suite,
        model=model,
        rendered_artifact=rendered_artifact,
        training_runs=tuple(runs),
        adapters=tuple(adapters),
        compatibility_reports=reports,
        evaluation=evaluation,
        rejection=rejection,
    )
