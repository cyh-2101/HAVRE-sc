"""Stage 9 candidate-only local training and evaluation contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from companion.hashing import content_hash
from companion.ids import uuid7


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CanonicalTrainingExample(StrictModel):
    schema_version: Literal[1] = 1
    example_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,79}$")
    source_kind: Literal["synthetic_fixture", "public_fixture"]
    source_ref: str = Field(pattern=r"^fixture://stage9/[a-z0-9/_-]+$")
    license_id: Literal["CC0-1.0"] = "CC0-1.0"
    category: Literal["behavioral", "safety", "general_capability", "over_agreement"]
    input_text: str = Field(min_length=1, max_length=2000)
    expected_text: str = Field(min_length=1, max_length=2000)
    memory_hint: str | None = Field(default=None, max_length=500)
    split: Literal["train", "validation"]
    training_eligible: Literal[True] = True
    contains_user_data: Literal[False] = False
    privacy_class: Literal["PUBLIC"] = "PUBLIC"
    content_hash: str = ""

    @model_validator(mode="after")
    def bind_hash(self) -> "CanonicalTrainingExample":
        expected = content_hash(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match canonical training example")
        object.__setattr__(self, "content_hash", expected)
        return self


class TrainingDatasetSnapshot(StrictModel):
    schema_version: Literal[1] = 1
    dataset_snapshot_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    name: Literal["stage9-synthetic-public-training-v2"] = "stage9-synthetic-public-training-v2"
    semantic_version: Literal["2.0.0"] = "2.0.0"
    builder_version: Literal["stage9-canonical-fixture-builder-v2"] = (
        "stage9-canonical-fixture-builder-v2"
    )
    split_policy_version: Literal["fixed-train-validation-holdout-exclusion-v2"] = (
        "fixed-train-validation-holdout-exclusion-v2"
    )
    fixture_content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    examples: tuple[CanonicalTrainingExample, ...] = Field(min_length=4)
    member_manifest_hash: str = ""
    excluded_evaluation_holdout_ids: tuple[str, ...] = Field(min_length=1)
    excluded_evaluation_holdout_manifest_hash: str = Field(
        pattern=r"^sha256:[0-9a-f]{64}$"
    )
    user_event_source_count: Literal[0] = 0
    contains_user_data: Literal[False] = False
    local_only_build: Literal[True] = True
    immutable: Literal[True] = True
    known_limitations: tuple[str, ...] = (
        "Repository-authored synthetic/public fixtures do not establish personal model quality.",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_hash: str = ""

    @model_validator(mode="after")
    def validate_and_hash(self) -> "TrainingDatasetSnapshot":
        ids = [example.example_id for example in self.examples]
        if len(ids) != len(set(ids)):
            raise ValueError("canonical example IDs must be unique")
        if not {"train", "validation"}.issubset(
            {example.split for example in self.examples}
        ):
            raise ValueError("training snapshot requires train and validation members")
        if set(ids) & set(self.excluded_evaluation_holdout_ids):
            raise ValueError("evaluation holdout IDs must be excluded from training members")
        manifest = tuple(
            sorted(
                (
                    {
                        "example_id": example.example_id,
                        "content_hash": example.content_hash,
                        "split": example.split,
                        "source_ref": example.source_ref,
                    }
                    for example in self.examples
                ),
                key=lambda item: item["example_id"],
            )
        )
        manifest_hash = content_hash(manifest)
        if self.member_manifest_hash and self.member_manifest_hash != manifest_hash:
            raise ValueError("member manifest hash is not canonical")
        object.__setattr__(self, "member_manifest_hash", manifest_hash)
        expected = content_hash(
            self.model_dump(
                mode="json",
                exclude={"dataset_snapshot_id", "created_at", "content_hash"},
            )
        )
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match training dataset snapshot")
        object.__setattr__(self, "content_hash", expected)
        return self


class EvaluationHoldoutCase(StrictModel):
    schema_version: Literal[1] = 1
    example_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,79}$")
    source_kind: Literal["synthetic_fixture", "public_fixture"]
    source_ref: str = Field(pattern=r"^fixture://stage9/[a-z0-9/_-]+$")
    license_id: Literal["CC0-1.0"] = "CC0-1.0"
    category: Literal["behavioral", "safety", "general_capability", "over_agreement"]
    input_text: str = Field(min_length=1, max_length=2000)
    expected_text: str = Field(min_length=1, max_length=2000)
    memory_hint: str | None = Field(default=None, max_length=500)
    split: Literal["holdout"] = "holdout"
    training_eligible: Literal[False] = False
    evaluation_only: Literal[True] = True
    access_limited: Literal[True] = True
    contains_user_data: Literal[False] = False
    privacy_class: Literal["PUBLIC"] = "PUBLIC"
    content_hash: str = ""

    @model_validator(mode="after")
    def bind_hash(self) -> "EvaluationHoldoutCase":
        expected = content_hash(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match evaluation holdout case")
        object.__setattr__(self, "content_hash", expected)
        return self


class EvaluationHoldoutSuite(StrictModel):
    schema_version: Literal[1] = 1
    holdout_suite_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    dataset_snapshot_id: UUID
    fixture_content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    cases: tuple[EvaluationHoldoutCase, ...] = Field(min_length=1)
    member_manifest_hash: str = ""
    purpose: Literal["evaluation_holdout"] = "evaluation_holdout"
    training_eligible: Literal[False] = False
    access_limited: Literal[True] = True
    local_only: Literal[True] = True
    immutable: Literal[True] = True
    content_hash: str = ""

    @model_validator(mode="after")
    def validate_and_hash(self) -> "EvaluationHoldoutSuite":
        ids = [case.example_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("evaluation holdout case IDs must be unique")
        manifest = tuple(
            sorted(
                (
                    {
                        "example_id": case.example_id,
                        "content_hash": case.content_hash,
                        "source_ref": case.source_ref,
                    }
                    for case in self.cases
                ),
                key=lambda item: item["example_id"],
            )
        )
        manifest_hash = content_hash(manifest)
        if self.member_manifest_hash and self.member_manifest_hash != manifest_hash:
            raise ValueError("holdout member manifest hash is not canonical")
        object.__setattr__(self, "member_manifest_hash", manifest_hash)
        expected = content_hash(
            self.model_dump(mode="json", exclude={"holdout_suite_id", "content_hash"})
        )
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match evaluation holdout suite")
        object.__setattr__(self, "content_hash", expected)
        return self


class ModelVersion(StrictModel):
    schema_version: Literal[1] = 1
    model_version_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    logical_name: Literal["havre-stage9-toy-base"] = "havre-stage9-toy-base"
    upstream_model_id: Literal["local://havre/stage9-toy-matrix"] = (
        "local://havre/stage9-toy-matrix"
    )
    upstream_revision: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    artifact_uri: str = Field(pattern=r"^local-artifact://stage9/[a-z0-9/_-]+$")
    artifact_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    tokenizer_version: Literal["hashed-tokenizer-v1"] = "hashed-tokenizer-v1"
    architecture_family: Literal["synthetic-linear-dry-run"] = "synthetic-linear-dry-run"
    precision: Literal["fp32"] = "fp32"
    context_limit: Literal[128] = 128
    license_id: Literal["CC0-1.0"] = "CC0-1.0"
    lifecycle_status: Literal["candidate"] = "candidate"
    local_only: Literal[True] = True
    production_eligible: Literal[False] = False
    content_hash: str = ""

    @model_validator(mode="after")
    def bind_hash(self) -> "ModelVersion":
        expected = content_hash(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match model version")
        object.__setattr__(self, "content_hash", expected)
        return self


class RenderedTrainingExample(StrictModel):
    example_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,79}$")
    rendered_text: str = Field(min_length=1, max_length=5000)
    input_token_ids: tuple[int, ...] = Field(min_length=1)
    target_token_ids: tuple[int, ...] = Field(min_length=1)
    source_content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @field_validator("input_token_ids", "target_token_ids")
    @classmethod
    def validate_token_ids(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        if any(value < 0 or value >= 32 for value in values):
            raise ValueError("hashed-tokenizer-v1 token IDs must be in [0, 31]")
        return values


class RenderedTrainingArtifact(StrictModel):
    schema_version: Literal[1] = 1
    rendered_artifact_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    dataset_snapshot_id: UUID
    model_version_id: UUID
    renderer_version: Literal["stage9-renderer-v1"] = "stage9-renderer-v1"
    tokenizer_version: Literal["hashed-tokenizer-v1"] = "hashed-tokenizer-v1"
    examples: tuple[RenderedTrainingExample, ...] = Field(min_length=4)
    source_member_manifest_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    contains_user_data: Literal[False] = False
    local_only: Literal[True] = True
    immutable: Literal[True] = True
    content_hash: str = ""

    @model_validator(mode="after")
    def bind_hash(self) -> "RenderedTrainingArtifact":
        example_ids = [example.example_id for example in self.examples]
        if len(example_ids) != len(set(example_ids)):
            raise ValueError("rendered training example IDs must be unique")
        expected = content_hash(
            self.model_dump(mode="json", exclude={"rendered_artifact_id", "content_hash"})
        )
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match rendered training artifact")
        object.__setattr__(self, "content_hash", expected)
        return self


class GovernanceVersionSet(StrictModel):
    constitution_version: str = Field(min_length=1, max_length=240)
    constitution_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    identity_version: str = Field(min_length=1, max_length=240)
    identity_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    values_version: str = Field(min_length=1, max_length=240)
    values_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    intervention_policy_version: str = Field(min_length=1, max_length=240)
    intervention_policy_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class TrainingConfig(StrictModel):
    method: Literal["lora", "qlora"]
    framework: Literal["havre-local-matrix-dry-run-v1"] = "havre-local-matrix-dry-run-v1"
    rank: Literal[2] = 2
    alpha: Literal[4] = 4
    dropout: Literal[0.0] = 0.0
    learning_rate: Literal[0.05] = 0.05
    epochs: Literal[2] = 2
    seed: int = Field(ge=0, le=2**31 - 1)
    base_quantization_bits: Literal[4] | None = None
    dry_run: Literal[True] = True
    local_only: Literal[True] = True
    cloud_transfer: Literal[False] = False

    @model_validator(mode="after")
    def validate_method(self) -> "TrainingConfig":
        if (self.method == "qlora") != (self.base_quantization_bits == 4):
            raise ValueError("QLoRA requires exactly 4-bit base quantization")
        return self


class TrainingRun(StrictModel):
    schema_version: Literal[1] = 1
    training_run_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    dataset_snapshot_id: UUID
    model_version_id: UUID
    rendered_artifact_id: UUID
    config: TrainingConfig
    renderer_version: Literal["stage9-renderer-v1"] = "stage9-renderer-v1"
    tokenizer_version: Literal["hashed-tokenizer-v1"] = "hashed-tokenizer-v1"
    governance_versions: GovernanceVersionSet
    training_example_count: int = Field(gt=0)
    validation_example_count: int = Field(gt=0)
    initial_loss: float = Field(ge=0)
    final_loss: float = Field(ge=0)
    adapter_matrix_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    status: Literal["completed_dry_run"] = "completed_dry_run"
    candidate_only: Literal[True] = True
    governance_mutation_attempted: Literal[False] = False
    promotion_authorized: Literal[False] = False
    deployment_authorized: Literal[False] = False
    used_user_data: Literal[False] = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_hash: str = ""

    @model_validator(mode="after")
    def bind_hash(self) -> "TrainingRun":
        expected = content_hash(
            self.model_dump(mode="json", exclude={"created_at", "content_hash"})
        )
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match training run")
        object.__setattr__(self, "content_hash", expected)
        return self


class AdapterVersion(StrictModel):
    schema_version: Literal[1] = 1
    adapter_version_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    adapter_type: Literal["lora", "qlora"]
    base_model_version_id: UUID
    required_base_artifact_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    dataset_snapshot_id: UUID
    training_run_id: UUID
    target_modules: tuple[Literal["synthetic_output_projection"], ...] = (
        "synthetic_output_projection",
    )
    rank: Literal[2] = 2
    alpha: Literal[4] = 4
    dropout: Literal[0.0] = 0.0
    artifact_uri: str = Field(pattern=r"^local-artifact://stage9/adapters/[a-z0-9/_-]+$")
    artifact_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    lifecycle_status: Literal["candidate"] = "candidate"
    candidate_only: Literal[True] = True
    promotion_authorized: Literal[False] = False
    deployed: Literal[False] = False
    content_hash: str = ""

    @model_validator(mode="after")
    def bind_hash(self) -> "AdapterVersion":
        expected = content_hash(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match adapter version")
        object.__setattr__(self, "content_hash", expected)
        return self


class AdapterCompatibilityReport(StrictModel):
    schema_version: Literal[1] = 1
    compatibility_report_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    adapter_version_id: UUID
    model_version_id: UUID
    checked_base_artifact_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    tokenizer_version: str
    compatible: bool
    mismatch_codes: tuple[str, ...] = ()
    loader_version: Literal["candidate-adapter-loader-v1"] = "candidate-adapter-loader-v1"
    load_performed: Literal[False] = False
    content_hash: str = ""

    @model_validator(mode="after")
    def validate_and_hash(self) -> "AdapterCompatibilityReport":
        if self.compatible == bool(self.mismatch_codes):
            raise ValueError("compatible reports require zero mismatches")
        expected = content_hash(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match compatibility report")
        object.__setattr__(self, "content_hash", expected)
        return self


class FactorialArmResult(StrictModel):
    arm: Literal["base", "base_memory", "base_adapter", "base_memory_adapter"]
    case_count: int = Field(gt=0)
    synthetic_alignment_score: float = Field(ge=0, le=1)
    critical_safety_failures: Literal[0] = 0
    governance_mutations: Literal[0] = 0
    local_only_violations: Literal[0] = 0
    measured_latency_ms: float = Field(ge=0)
    peak_vram_bytes: Literal[0] = 0
    limitations: tuple[str, ...]


class FactorialEvaluationReport(StrictModel):
    schema_version: Literal[1] = 1
    evaluation_report_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    dataset_snapshot_id: UUID
    holdout_suite_id: UUID
    model_version_id: UUID
    adapter_version_id: UUID
    seeds: tuple[int, ...] = Field(min_length=2)
    arms: tuple[FactorialArmResult, ...] = Field(min_length=4, max_length=4)
    adapter_load_ms: float = Field(ge=0)
    adapter_switch_ms: float = Field(ge=0)
    general_capability_scope: Literal["synthetic_fixture_only"] = "synthetic_fixture_only"
    human_benefit_claimed: Literal[False] = False
    release_promotion_authorized: Literal[False] = False
    content_hash: str = ""

    @model_validator(mode="after")
    def validate_and_hash(self) -> "FactorialEvaluationReport":
        required = {"base", "base_memory", "base_adapter", "base_memory_adapter"}
        if {arm.arm for arm in self.arms} != required:
            raise ValueError("factorial report requires exactly four distinct arms")
        expected = content_hash(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match factorial report")
        object.__setattr__(self, "content_hash", expected)
        return self


class AdapterRejectionRecord(StrictModel):
    schema_version: Literal[1] = 1
    rejection_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    adapter_version_id: UUID
    evaluation_report_id: UUID
    reason_code: Literal["synthetic_dry_run_not_promotion_evidence"] = (
        "synthetic_dry_run_not_promotion_evidence"
    )
    active_adapter_before: None = None
    active_adapter_after: None = None
    persistent_identity_unchanged: Literal[True] = True
    persistent_history_unchanged: Literal[True] = True
    rollback_effect: Literal["no_activation_to_rollback"] = "no_activation_to_rollback"
    rejected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_hash: str = ""

    @model_validator(mode="after")
    def bind_hash(self) -> "AdapterRejectionRecord":
        expected = content_hash(
            self.model_dump(mode="json", exclude={"rejected_at", "content_hash"})
        )
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match adapter rejection")
        object.__setattr__(self, "content_hash", expected)
        return self
