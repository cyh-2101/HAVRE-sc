"""Immutable contracts for Stage 3 inference systems measurements.

The performance report deliberately contains no prompt or generated text.  A
separate, explicitly non-binding compatibility report records only descriptive
observations and content hashes so systems evidence cannot be mistaken for a
behavioral release decision.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from companion.hashing import content_hash
from companion.ids import uuid7


SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"
SOURCE_REVISION_PATTERN = r"^(?:[0-9a-f]{40}|sha256:[0-9a-f]{64})$"
UNSET_CONTENT_HASH = "sha256:" + "0" * 64
REQUIRED_STAGE3_WORKLOADS = frozenset(
    {"scene_short", "chat_standard", "reflection_long", "extraction_structured"}
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ContentHashedModel(StrictModel):
    """Frozen value object whose hash covers every identity-bearing field."""

    content_hash_excluded_fields: ClassVar[frozenset[str]] = frozenset(
        {"content_hash"}
    )
    content_hash: str = Field(default=UNSET_CONTENT_HASH, pattern=SHA256_PATTERN)

    def model_post_init(self, __context: object) -> None:
        expected = content_hash(
            self.model_dump(mode="json", exclude=self.content_hash_excluded_fields)
        )
        if "content_hash" in self.model_fields_set and self.content_hash != expected:
            raise ValueError(f"content_hash does not match {type(self).__name__}")
        object.__setattr__(self, "content_hash", expected)


class ArtifactDigest(StrictModel):
    artifact_kind: str = Field(min_length=1)
    artifact_uri: str = Field(min_length=1)
    content_hash: str = Field(pattern=SHA256_PATTERN)


class InferenceSystemUnderTestManifest(ContentHashedModel):
    """Exact, immutable identity of the provider/model/config being measured."""

    # The same pinned system can be materialized for more than one run. Its
    # observation timestamp is useful provenance, but is not part of the
    # provider/model/config identity.
    content_hash_excluded_fields: ClassVar[frozenset[str]] = frozenset(
        {"content_hash", "created_at"}
    )

    schema_version: Literal[1] = 1
    manifest_id: str = Field(min_length=1)
    provider_id: str = Field(min_length=1)
    provider_class: Literal["local_test", "self_hosted", "cloud"]
    execution_environment: Literal["local", "cloud"]
    model_version_id: str = Field(min_length=1)
    adapter_version_id: str | None = Field(default=None, min_length=1)
    provider_adapter_version_id: str = Field(min_length=1)
    model_artifact_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    model_artifact_hash_unavailable_reason: str | None = Field(
        default=None, min_length=1
    )
    tokenizer_version_id: str = Field(min_length=1)
    serving_config_version: str = Field(min_length=1)
    serving_engine: str = Field(min_length=1)
    serving_engine_version: str = Field(min_length=1)
    upstream_model_id: str = Field(min_length=1)
    upstream_revision: str = Field(min_length=1)
    architecture_family: str = Field(min_length=1)
    parameter_count: int | None = Field(default=None, gt=0)
    parameter_count_unavailable_reason: str | None = Field(default=None, min_length=1)
    weights_format: str = Field(min_length=1)
    precision: str = Field(min_length=1)
    quantization: str | None = Field(default=None, min_length=1)
    context_limit: int = Field(gt=0)
    max_output_tokens: int = Field(gt=0)
    license_identifier: str = Field(min_length=1)
    license_notes: str = Field(min_length=1)
    code_revision: str = Field(pattern=SOURCE_REVISION_PATTERN)
    artifacts: tuple[ArtifactDigest, ...] = Field(min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_artifact_kinds(self) -> "InferenceSystemUnderTestManifest":
        identities = [
            (artifact.artifact_kind, artifact.artifact_uri)
            for artifact in self.artifacts
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("system manifest artifact references must be unique")
        if (self.model_artifact_hash is None) == (
            self.model_artifact_hash_unavailable_reason is None
        ):
            raise ValueError(
                "model artifact hash needs either an exact value or an unavailable reason"
            )
        model_artifacts = [
            artifact
            for artifact in self.artifacts
            if artifact.artifact_kind == "model_weights"
        ]
        if self.model_artifact_hash is not None and not any(
            artifact.content_hash == self.model_artifact_hash
            for artifact in model_artifacts
        ):
            raise ValueError(
                "exact model artifact hash must appear in model_weights provenance"
            )
        if (self.parameter_count is None) == (
            self.parameter_count_unavailable_reason is None
        ):
            raise ValueError(
                "parameter count needs either an exact value or an unavailable reason"
            )
        if self.max_output_tokens > self.context_limit:
            raise ValueError("maximum output tokens cannot exceed context limit")
        return self


ManifestValue = str | int | float | bool | None


class RuntimeVerification(StrictModel):
    """Typed evidence that a benchmark was bound to one running binary/config."""

    status: Literal["verified", "unavailable"]
    unavailable_reason: str | None = Field(default=None, min_length=1)
    runtime_state_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    server_executable_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    model_artifact_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    server_pid: int | None = Field(default=None, gt=0)
    process_executable_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    launch_arguments_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    launch_configuration_verified: bool | None = None
    request_logging_disabled: bool | None = None
    runtime_attestation_id: str | None = Field(default=None, min_length=1)
    runtime_attestation_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    process_started_at: datetime | None = None
    engine_manifest_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    model_manifest_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    server_executable_path_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    model_path_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    model_size_bytes: int | None = Field(default=None, gt=0)
    loaded_model_alias: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_evidence(self) -> "RuntimeVerification":
        evidence = (
            self.runtime_state_hash,
            self.server_executable_hash,
            self.model_artifact_hash,
            self.server_pid,
            self.process_executable_hash,
            self.launch_arguments_hash,
            self.launch_configuration_verified,
            self.request_logging_disabled,
            self.runtime_attestation_id,
            self.runtime_attestation_hash,
            self.process_started_at,
            self.engine_manifest_hash,
            self.model_manifest_hash,
            self.server_executable_path_hash,
            self.model_path_hash,
            self.model_size_bytes,
            self.loaded_model_alias,
        )
        if self.status == "verified":
            if self.unavailable_reason is not None or any(item is None for item in evidence):
                raise ValueError("verified runtime requires complete attestation evidence")
            if not self.launch_configuration_verified or not self.request_logging_disabled:
                raise ValueError("verified runtime must attest the pinned privacy-safe launch")
        elif self.unavailable_reason is None or any(item is not None for item in evidence):
            raise ValueError("unavailable runtime requires only an explicit reason")
        return self


class InferenceEnvironmentManifest(ContentHashedModel):
    """Pinned benchmark host/runtime facts, captured before a run."""

    schema_version: Literal[1] = 1
    environment_manifest_id: str = Field(min_length=1)
    runtime_verification: RuntimeVerification
    hardware: dict[str, ManifestValue]
    software: dict[str, ManifestValue]
    accelerator: dict[str, ManifestValue]
    network_topology: str = Field(min_length=1)
    power_mode: str | None = None
    measurement_sources: dict[str, str]
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class InferenceWorkloadMessage(StrictModel):
    role: Literal["system", "user", "assistant"]
    text: str = Field(min_length=1)


class InferenceWorkloadCase(StrictModel):
    case_id: str = Field(min_length=1)
    workload_class: Literal[
        "scene_short",
        "chat_standard",
        "reflection_long",
        "extraction_structured",
    ]
    messages: tuple[InferenceWorkloadMessage, ...] = Field(min_length=1)
    max_output_tokens: int = Field(gt=0)
    temperature: float = Field(ge=0, le=2)
    top_p: float = Field(gt=0, le=1)
    seed: int | None = None
    stop: tuple[str, ...] = ()
    response_expectation: Literal["text", "json_object"] = "text"
    provenance_origin: Literal["synthetic"] = "synthetic"


class InferenceBenchmarkSchedule(StrictModel):
    schedule_id: str = Field(min_length=1)
    concurrency: int = Field(ge=1)
    warmup_repetitions_per_case: int = Field(ge=0)
    measured_repetitions_per_case: int = Field(ge=1)


class InferenceWorkloadManifest(ContentHashedModel):
    """Frozen workload and execution schedule; never a production quality gate."""

    schema_version: Literal[1] = 1
    workload_manifest_id: str = Field(min_length=1)
    protocol_version: Literal["inference-protocol-v1"] = "inference-protocol-v1"
    description: str = Field(min_length=1)
    review_status: Literal["synthetic_reviewed"] = "synthetic_reviewed"
    binding_evaluation: Literal[False] = False
    cache_mode: Literal["cold", "warm", "controlled_mixed"]
    timeout_ms: int = Field(gt=0)
    random_seed: int
    cases: tuple[InferenceWorkloadCase, ...] = Field(min_length=4)
    schedules: tuple[InferenceBenchmarkSchedule, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_stage3_coverage(self) -> "InferenceWorkloadManifest":
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("workload case IDs must be unique")
        schedule_ids = [schedule.schedule_id for schedule in self.schedules]
        if len(schedule_ids) != len(set(schedule_ids)):
            raise ValueError("benchmark schedule IDs must be unique")
        classes = {case.workload_class for case in self.cases}
        if not REQUIRED_STAGE3_WORKLOADS.issubset(classes):
            missing = sorted(REQUIRED_STAGE3_WORKLOADS - classes)
            raise ValueError(f"Stage 3 workload classes missing: {missing}")
        if not any(schedule.concurrency > 1 for schedule in self.schedules):
            raise ValueError("Stage 3 workload needs a batch/throughput schedule")
        return self


class ResourceObservation(StrictModel):
    """One resource metric with explicit evidence or explicit unavailability."""

    value: float | None = Field(default=None, ge=0)
    unit: str = Field(min_length=1)
    source: str | None = None
    unavailable_reason: str | None = None

    @model_validator(mode="after")
    def validate_evidence(self) -> "ResourceObservation":
        if self.value is None:
            if not self.unavailable_reason or self.source is not None:
                raise ValueError(
                    "an unavailable resource value needs a reason and no source"
                )
        elif not self.source or self.unavailable_reason is not None:
            raise ValueError(
                "a measured resource value needs a source and no unavailable reason"
            )
        return self


class ResourceSnapshot(StrictModel):
    observed_at: datetime
    cpu_percent: ResourceObservation
    ram_used_bytes: ResourceObservation
    gpu_utilization_percent: ResourceObservation
    vram_used_bytes: ResourceObservation
    vram_peak_used_bytes: ResourceObservation


class BenchmarkError(StrictModel):
    code: Literal[
        "invalid_request",
        "unsupported_capability",
        "privacy_constraint_unsatisfied",
        "model_unavailable",
        "provider_rate_limited",
        "provider_timeout",
        "context_limit_exceeded",
        "content_blocked",
        "stream_interrupted",
        "provider_protocol_error",
        "internal_error",
        "version_mismatch",
    ]
    retryable: bool
    safe_message: str = Field(min_length=1, max_length=500)
    provider_status_code: int | None = Field(default=None, ge=100, le=599)
    provider_error_code: str | None = Field(default=None, min_length=1, max_length=200)
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class InferenceBenchmarkSample(StrictModel):
    """Content-free raw measurement for one provider stream attempt."""

    schema_version: Literal[1] = 1
    sample_id: UUID = Field(default_factory=uuid7)
    schedule_id: str = Field(min_length=1)
    workload_case_id: str = Field(min_length=1)
    workload_class: Literal[
        "scene_short",
        "chat_standard",
        "reflection_long",
        "extraction_structured",
    ]
    warmup: bool
    attempt_index: int = Field(ge=1)
    concurrency: int = Field(ge=1)
    inference_request_id: UUID
    inference_response_id: UUID | None = None
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    status: Literal["completed", "failed"]
    started_at: datetime
    completed_at: datetime
    ttft_ms: float | None = Field(default=None, ge=0)
    tpot_ms: float | None = Field(default=None, ge=0)
    end_to_end_latency_ms: float = Field(ge=0)
    generation_interval_ms: float | None = Field(default=None, ge=0)
    visible_token_interval_ms: float | None = Field(default=None, ge=0)
    attempted_requests_per_second: float = Field(ge=0)
    output_tokens_per_second: float | None = Field(default=None, ge=0)
    prompt_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    token_count_source: Literal["provider", "estimator"] | None = None
    stream_event_count: int = Field(ge=0)
    output_content_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    system_manifest_content_hash: str = Field(pattern=SHA256_PATTERN)
    provider_id: str = Field(min_length=1)
    provider_class: Literal["local_test", "self_hosted", "cloud"]
    execution_environment: Literal["local", "cloud"]
    provider_request_id: str | None = Field(default=None, min_length=1)
    model_version_id: str | None = None
    adapter_version_id: str | None = None
    provider_adapter_version_id: str | None = None
    tokenizer_version_id: str | None = None
    serving_config_version: str | None = None
    serving_engine: str | None = None
    serving_engine_version: str | None = None
    model_artifact_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    unavailable_measurements: dict[str, str] = Field(default_factory=dict)
    resources: ResourceSnapshot
    error: BenchmarkError | None = None

    @model_validator(mode="after")
    def validate_terminal_state(self) -> "InferenceBenchmarkSample":
        if self.completed_at < self.started_at:
            raise ValueError("sample completion cannot precede its start")
        metric_fields = {
            "ttft_ms": self.ttft_ms,
            "tpot_ms": self.tpot_ms,
            "generation_interval_ms": self.generation_interval_ms,
            "visible_token_interval_ms": self.visible_token_interval_ms,
            "output_tokens_per_second": self.output_tokens_per_second,
        }
        for name, value in metric_fields.items():
            has_reason = name in self.unavailable_measurements
            if (value is None) != has_reason:
                raise ValueError(
                    f"{name} needs exactly one value or unavailable reason"
                )
        if self.status == "completed":
            if self.error is not None or self.inference_response_id is None:
                raise ValueError("completed sample needs a response and no error")
            if self.output_content_hash is None:
                raise ValueError("completed sample needs an output content hash")
            if None in (
                self.prompt_tokens,
                self.output_tokens,
                self.total_tokens,
                self.token_count_source,
                self.provider_request_id,
                self.model_version_id,
                self.provider_adapter_version_id,
                self.tokenizer_version_id,
                self.serving_config_version,
                self.serving_engine,
                self.serving_engine_version,
            ):
                raise ValueError("completed sample needs exact usage and versions")
            if self.total_tokens != self.prompt_tokens + self.output_tokens:
                raise ValueError("sample total tokens do not reconcile")
        else:
            if self.error is None:
                raise ValueError("failed sample needs a typed error")
            if any(
                value is not None
                for value in (
                    self.output_content_hash,
                    self.provider_request_id,
                    self.model_version_id,
                    self.adapter_version_id,
                    self.provider_adapter_version_id,
                    self.tokenizer_version_id,
                    self.serving_config_version,
                    self.serving_engine,
                    self.serving_engine_version,
                    self.model_artifact_hash,
                    self.prompt_tokens,
                    self.output_tokens,
                    self.total_tokens,
                    self.token_count_source,
                )
            ):
                raise ValueError("failed sample cannot claim completed output provenance")
        return self


def _sample_provenance_matches_manifest(
    sample: InferenceBenchmarkSample,
    manifest: InferenceSystemUnderTestManifest,
) -> bool:
    """Bind every completed sample to the exact measured provider artifact."""

    common_matches = (
        sample.system_manifest_content_hash == manifest.content_hash
        and sample.provider_id == manifest.provider_id
        and sample.provider_class == manifest.provider_class
        and sample.execution_environment == manifest.execution_environment
    )
    if not common_matches or sample.status != "completed":
        return common_matches
    return (
        sample.model_version_id == manifest.model_version_id
        and sample.adapter_version_id == manifest.adapter_version_id
        and sample.provider_adapter_version_id
        == manifest.provider_adapter_version_id
        and sample.tokenizer_version_id == manifest.tokenizer_version_id
        and sample.serving_config_version == manifest.serving_config_version
        and sample.serving_engine == manifest.serving_engine
        and sample.serving_engine_version == manifest.serving_engine_version
        and sample.model_artifact_hash == manifest.model_artifact_hash
    )


class MetricAggregate(StrictModel):
    metric: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    sample_count: int = Field(ge=0)
    mean: float | None = Field(default=None, ge=0)
    p50: float | None = Field(default=None, ge=0)
    p95: float | None = Field(default=None, ge=0)
    unavailable_reason: str | None = None

    @model_validator(mode="after")
    def validate_samples(self) -> "MetricAggregate":
        values = (self.mean, self.p50, self.p95)
        if self.sample_count == 0:
            if any(value is not None for value in values) or not self.unavailable_reason:
                raise ValueError("empty metric aggregates need an unavailability reason")
        elif any(value is None for value in values) or self.unavailable_reason is not None:
            raise ValueError("measured aggregates need mean, p50, and p95")
        return self


class ScheduleSummary(StrictModel):
    schedule_id: str = Field(min_length=1)
    concurrency: int = Field(ge=1)
    wall_time_ms: float = Field(ge=0)
    attempted_requests: int = Field(ge=0)
    completed_requests: int = Field(ge=0)
    error_rate: float = Field(ge=0, le=1)
    attempted_requests_per_second: float = Field(ge=0)
    completed_requests_per_second: float = Field(ge=0)
    input_tokens_per_second: float | None = Field(default=None, ge=0)
    output_tokens_per_second: float | None = Field(default=None, ge=0)
    total_tokens_per_second: float | None = Field(default=None, ge=0)
    errors_by_code: dict[str, int]
    metrics: tuple[MetricAggregate, ...]

    @model_validator(mode="after")
    def validate_counts(self) -> "ScheduleSummary":
        if self.completed_requests > self.attempted_requests:
            raise ValueError("completed requests cannot exceed attempted requests")
        failures = self.attempted_requests - self.completed_requests
        if sum(self.errors_by_code.values()) != failures:
            raise ValueError("typed error counts must reconcile with failed requests")
        expected_error_rate = (
            failures / self.attempted_requests if self.attempted_requests else 0
        )
        if abs(self.error_rate - expected_error_rate) > 1e-12:
            raise ValueError("error rate must reconcile with request counts")
        return self


class InferenceSystemBenchmarkReport(ContentHashedModel):
    """Systems-only report.  No behavioral verdict or content is allowed."""

    schema_version: Literal[1] = 1
    benchmark_run_id: UUID = Field(default_factory=uuid7)
    benchmark_type: Literal["inference"] = "inference"
    benchmark_name: Literal["personal-brain-serving-baseline"] = (
        "personal-brain-serving-baseline"
    )
    protocol_version: Literal["inference-protocol-v1"] = "inference-protocol-v1"
    benchmark_harness_version: Literal["stage3-inference-benchmark-v1"] = (
        "stage3-inference-benchmark-v1"
    )
    benchmark_code_revision: str = Field(pattern=SOURCE_REVISION_PATTERN)
    analysis_method_version: Literal["havre-percentile-linear-v1"] = (
        "havre-percentile-linear-v1"
    )
    status: Literal["completed", "partial", "failed"]
    started_at: datetime
    completed_at: datetime
    system_under_test: InferenceSystemUnderTestManifest
    environment: InferenceEnvironmentManifest
    workload_manifest_id: str = Field(min_length=1)
    workload_content_hash: str = Field(pattern=SHA256_PATTERN)
    measurement_methodology: dict[str, str] = Field(min_length=1)
    warmup_samples: tuple[InferenceBenchmarkSample, ...]
    measured_samples: tuple[InferenceBenchmarkSample, ...] = Field(min_length=1)
    schedule_summaries: tuple[ScheduleSummary, ...] = Field(min_length=1)
    limitations: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_measurement_groups(self) -> "InferenceSystemBenchmarkReport":
        if self.benchmark_code_revision != self.system_under_test.code_revision:
            raise ValueError(
                "benchmark code revision must match the system manifest"
            )
        if any(not sample.warmup for sample in self.warmup_samples):
            raise ValueError("warmup_samples may contain only warmup measurements")
        if any(sample.warmup for sample in self.measured_samples):
            raise ValueError("measured_samples may not contain warmup measurements")
        if self.completed_at < self.started_at:
            raise ValueError("benchmark completion cannot precede its start")
        completed = sum(
            sample.status == "completed" for sample in self.measured_samples
        )
        expected_status = (
            "completed"
            if completed == len(self.measured_samples)
            else "partial"
            if completed
            else "failed"
        )
        if self.status != expected_status:
            raise ValueError("benchmark status must match measured sample outcomes")
        summary_ids = [summary.schedule_id for summary in self.schedule_summaries]
        if len(summary_ids) != len(set(summary_ids)):
            raise ValueError("schedule summaries must be unique")
        measured_schedule_ids = {sample.schedule_id for sample in self.measured_samples}
        if set(summary_ids) != measured_schedule_ids:
            raise ValueError("schedule summaries must cover every measured schedule")
        if any(
            not _sample_provenance_matches_manifest(sample, self.system_under_test)
            for sample in (*self.warmup_samples, *self.measured_samples)
        ):
            raise ValueError(
                "sample provenance and exact versions must match the system manifest"
            )
        if self.system_under_test.provider_class == "self_hosted":
            if self.environment.runtime_verification.status != "verified":
                raise ValueError("self-hosted benchmark requires verified runtime evidence")
            if (
                self.environment.runtime_verification.model_artifact_hash
                != self.system_under_test.model_artifact_hash
            ):
                raise ValueError("runtime model hash must match the system manifest")
        return self


ObservationValue = str | int | float | bool | None


class CompatibilityObservation(StrictModel):
    observation: str = Field(min_length=1)
    candidate_value: ObservationValue
    baseline_value: ObservationValue = None
    note: str = Field(min_length=1)


class CompatibilityCaseResult(StrictModel):
    workload_case_id: str = Field(min_length=1)
    workload_class: Literal[
        "scene_short",
        "chat_standard",
        "reflection_long",
        "extraction_structured",
    ]
    candidate_status: Literal["completed", "failed"]
    baseline_status: Literal["completed", "failed", "not_run"]
    candidate_output_content_hash: str | None = Field(
        default=None, pattern=SHA256_PATTERN
    )
    baseline_output_content_hash: str | None = Field(
        default=None, pattern=SHA256_PATTERN
    )
    observations: tuple[CompatibilityObservation, ...]

    @model_validator(mode="after")
    def validate_output_references(self) -> "CompatibilityCaseResult":
        if (self.candidate_status == "completed") != (
            self.candidate_output_content_hash is not None
        ):
            raise ValueError("candidate status and output hash must agree")
        if self.baseline_status == "completed":
            if self.baseline_output_content_hash is None:
                raise ValueError("completed baseline needs an output hash")
        elif self.baseline_output_content_hash is not None:
            raise ValueError("non-completed baseline cannot claim an output hash")
        return self


class InferenceCompatibilityReport(ContentHashedModel):
    """Descriptive evidence only; never an implicit model release approval."""

    schema_version: Literal[1] = 1
    compatibility_run_id: UUID = Field(default_factory=uuid7)
    benchmark_run_id: UUID
    report_type: Literal["non_binding_behavioral_compatibility"] = (
        "non_binding_behavioral_compatibility"
    )
    binding_evaluation: Literal[False] = False
    gate_status: Literal["not_evaluated"] = "not_evaluated"
    started_at: datetime
    completed_at: datetime
    candidate_manifest_id: str = Field(min_length=1)
    candidate_manifest_content_hash: str = Field(pattern=SHA256_PATTERN)
    baseline_manifest_id: str | None = None
    baseline_manifest_content_hash: str | None = Field(
        default=None, pattern=SHA256_PATTERN
    )
    workload_manifest_id: str = Field(min_length=1)
    workload_content_hash: str = Field(pattern=SHA256_PATTERN)
    candidate_samples: tuple[InferenceBenchmarkSample, ...] = Field(min_length=4)
    baseline_samples: tuple[InferenceBenchmarkSample, ...]
    case_results: tuple[CompatibilityCaseResult, ...] = Field(min_length=4)
    limitations: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_baseline_reference(self) -> "InferenceCompatibilityReport":
        if (self.baseline_manifest_id is None) != (
            self.baseline_manifest_content_hash is None
        ):
            raise ValueError("baseline manifest ID and hash must be paired")
        if self.completed_at < self.started_at:
            raise ValueError("compatibility completion cannot precede its start")
        case_ids = [result.workload_case_id for result in self.case_results]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("compatibility case results must be unique")
        classes = {result.workload_class for result in self.case_results}
        if not REQUIRED_STAGE3_WORKLOADS.issubset(classes):
            raise ValueError("compatibility report must cover Stage 3 workload classes")
        candidate_by_case = {
            sample.workload_case_id: sample for sample in self.candidate_samples
        }
        baseline_by_case = {
            sample.workload_case_id: sample for sample in self.baseline_samples
        }
        if len(candidate_by_case) != len(self.candidate_samples):
            raise ValueError("compatibility candidate samples must be unique per case")
        if len(baseline_by_case) != len(self.baseline_samples):
            raise ValueError("compatibility baseline samples must be unique per case")
        if set(case_ids) != set(candidate_by_case):
            raise ValueError("candidate samples must cover compatibility cases exactly once")
        baseline_was_run = self.baseline_manifest_id is not None
        if baseline_was_run and set(case_ids) != set(baseline_by_case):
            raise ValueError("baseline samples must cover compatibility cases exactly once")
        if not baseline_was_run and self.baseline_samples:
            raise ValueError("baseline samples require a baseline manifest")
        if any(
            (result.baseline_status != "not_run") != baseline_was_run
            for result in self.case_results
        ):
            raise ValueError("baseline case status must match baseline manifest presence")
        if any(
            sample.warmup
            or sample.schedule_id != "compatibility-candidate"
            or sample.concurrency != 1
            or sample.attempt_index != 1
            or sample.system_manifest_content_hash
            != self.candidate_manifest_content_hash
            for sample in self.candidate_samples
        ):
            raise ValueError("candidate samples must bind to the declared compatibility run")
        if any(
            sample.warmup
            or sample.schedule_id != "compatibility-baseline"
            or sample.concurrency != 1
            or sample.attempt_index != 1
            or sample.system_manifest_content_hash
            != self.baseline_manifest_content_hash
            for sample in self.baseline_samples
        ):
            raise ValueError("baseline samples must bind to the declared compatibility run")
        for result in self.case_results:
            candidate = candidate_by_case[result.workload_case_id]
            if (
                result.workload_class != candidate.workload_class
                or result.candidate_status != candidate.status
                or result.candidate_output_content_hash
                != candidate.output_content_hash
            ):
                raise ValueError("candidate result must reconcile with its raw sample")
            baseline = baseline_by_case.get(result.workload_case_id)
            if baseline is not None and (
                result.workload_class != baseline.workload_class
                or result.baseline_status != baseline.status
                or result.baseline_output_content_hash
                != baseline.output_content_hash
            ):
                raise ValueError("baseline result must reconcile with its raw sample")
        return self


def validate_inference_benchmark_report_pair(
    system_report: InferenceSystemBenchmarkReport,
    compatibility_report: InferenceCompatibilityReport,
) -> None:
    """Validate facts that span the two separately immutable Stage 3 reports."""

    if compatibility_report.benchmark_run_id != system_report.benchmark_run_id:
        raise ValueError("benchmark report pair must share benchmark_run_id")
    if (
        compatibility_report.workload_manifest_id
        != system_report.workload_manifest_id
        or compatibility_report.workload_content_hash
        != system_report.workload_content_hash
    ):
        raise ValueError("benchmark report pair must share the exact workload")
    if (
        compatibility_report.candidate_manifest_id
        != system_report.system_under_test.manifest_id
        or compatibility_report.candidate_manifest_content_hash
        != system_report.system_under_test.content_hash
    ):
        raise ValueError(
            "compatibility candidate must match the systems report manifest"
        )
    if any(
        not _sample_provenance_matches_manifest(
            sample, system_report.system_under_test
        )
        for sample in compatibility_report.candidate_samples
    ):
        raise ValueError(
            "compatibility candidate samples must match the exact systems manifest"
        )
