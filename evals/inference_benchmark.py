"""Stage 3 provider-neutral inference benchmark harness.

The harness measures the stream as seen by a HAVRE client.  It never stores
prompt or output text in the systems report, never guesses unavailable resource
metrics, and never turns the descriptive compatibility report into a release
gate.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import platform
import random
import statistics
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter_ns
from typing import Protocol, get_args

from companion.events import TextContentPart
from companion.hashing import content_hash
from companion.ids import new_trace_id, uuid7
from companion.policy import DataPolicy, PrivacyClass
from mlsys.contracts import GenerationSettings, InferenceMessage, InferenceRequest
from mlsys.contracts.inference import (
    ExecutionEnvironment,
    InferenceFailureCode,
    InferenceConstraints,
    InferenceResponse,
    InferenceStreamEvent,
)
from mlsys.contracts.inference_benchmark import (
    BenchmarkError,
    CompatibilityCaseResult,
    CompatibilityObservation,
    InferenceBenchmarkSample,
    InferenceCompatibilityReport,
    InferenceEnvironmentManifest,
    InferenceSystemBenchmarkReport,
    InferenceSystemUnderTestManifest,
    InferenceWorkloadCase,
    InferenceWorkloadManifest,
    MetricAggregate,
    ResourceObservation,
    ResourceSnapshot,
    RuntimeVerification,
    ScheduleSummary,
    validate_inference_benchmark_report_pair,
)
from mlsys.serving.provider import ModelProvider


BENCHMARK_ERROR_CODES = frozenset((*get_args(InferenceFailureCode), "version_mismatch"))


class BenchmarkManifestMismatch(ValueError):
    """The live provider does not match the immutable benchmark manifest."""


class BenchmarkOutputExists(FileExistsError):
    """A benchmark artifact path is immutable and already exists."""


class _StreamProtocolError(RuntimeError):
    pass


class ResourceCollector(Protocol):
    """Optional reliable collector, normally backed by a server metrics source."""

    async def begin_sample(self) -> object: ...

    async def finish_sample(self, handle: object) -> ResourceSnapshot: ...

    async def aclose(self) -> None: ...


class NullResourceCollector:
    """Honest default when no trustworthy process/GPU sampler is configured."""

    reason = "no_reliable_resource_collector_configured"

    async def begin_sample(self) -> object:
        return None

    async def finish_sample(self, handle: object) -> ResourceSnapshot:
        del handle
        return unavailable_resource_snapshot(self.reason)

    async def aclose(self) -> None:
        return None


@dataclass(frozen=True)
class _ExecutionResult:
    sample: InferenceBenchmarkSample
    output_text: str


def unavailable_resource_snapshot(reason: str) -> ResourceSnapshot:
    def missing(unit: str) -> ResourceObservation:
        return ResourceObservation(
            value=None,
            unit=unit,
            unavailable_reason=reason,
        )

    return ResourceSnapshot(
        observed_at=datetime.now(UTC),
        cpu_percent=missing("percent"),
        ram_used_bytes=missing("bytes"),
        gpu_utilization_percent=missing("percent"),
        vram_used_bytes=missing("bytes"),
        vram_peak_used_bytes=missing("bytes"),
    )


def capture_environment_manifest(
    *,
    runtime_verification: RuntimeVerification | None = None,
    software: dict[str, str | int | float | bool | None] | None = None,
    hardware: dict[str, str | int | float | bool | None] | None = None,
    accelerator: dict[str, str | int | float | bool | None] | None = None,
    measurement_sources: dict[str, str] | None = None,
    network_topology: str = "loopback-local",
    power_mode: str | None = None,
) -> InferenceEnvironmentManifest:
    """Capture only cheap, trustworthy facts; callers add accelerator facts."""

    base_hardware: dict[str, str | int | float | bool | None] = {
        "machine": platform.machine() or None,
        "processor": platform.processor() or None,
        "logical_cpu_count": os.cpu_count(),
    }
    base_hardware.update(hardware or {})
    base_software: dict[str, str | int | float | bool | None] = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "implementation": platform.python_implementation(),
    }
    base_software.update(software or {})
    return InferenceEnvironmentManifest(
        environment_manifest_id=f"environment-{uuid7()}",
        runtime_verification=runtime_verification
        or RuntimeVerification(
            status="unavailable",
            unavailable_reason="not_available_for_contract_only_run",
        ),
        hardware=base_hardware,
        software=base_software,
        accelerator=accelerator or {
            "status": "unavailable",
            "reason": "not_supplied_by_a_reliable_accelerator_source",
        },
        network_topology=network_topology,
        power_mode=power_mode,
        measurement_sources=measurement_sources or {
            "python_runtime": "python-platform-and-os",
            "accelerator": "unavailable",
        },
    )


def load_workload_manifest(path: Path) -> InferenceWorkloadManifest:
    return InferenceWorkloadManifest.model_validate_json(
        path.read_text(encoding="utf-8")
    )


def load_system_under_test_manifest(
    path: Path,
) -> InferenceSystemUnderTestManifest:
    return InferenceSystemUnderTestManifest.model_validate_json(
        path.read_text(encoding="utf-8")
    )


async def run_inference_benchmark(
    *,
    provider: ModelProvider,
    system_under_test: InferenceSystemUnderTestManifest,
    workload: InferenceWorkloadManifest,
    environment: InferenceEnvironmentManifest,
    benchmark_code_revision: str,
    baseline_provider: ModelProvider | None = None,
    baseline_manifest: InferenceSystemUnderTestManifest | None = None,
    resource_collector: ResourceCollector | None = None,
    system_output_path: Path | None = None,
    compatibility_output_path: Path | None = None,
) -> tuple[InferenceSystemBenchmarkReport, InferenceCompatibilityReport]:
    """Run streaming systems samples and a separate non-binding comparison."""

    if (baseline_provider is None) != (baseline_manifest is None):
        raise ValueError("baseline provider and manifest must be supplied together")
    if (system_output_path is None) != (compatibility_output_path is None):
        raise ValueError("both report output paths must be supplied together")

    await _validate_live_provider(provider, system_under_test)
    if baseline_provider is not None and baseline_manifest is not None:
        await _validate_live_provider(baseline_provider, baseline_manifest)

    collector = resource_collector or NullResourceCollector()
    benchmark_started_at = datetime.now(UTC)
    warmup_results: list[_ExecutionResult] = []
    measured_results: list[_ExecutionResult] = []
    schedule_summaries: list[ScheduleSummary] = []

    try:
        for schedule in workload.schedules:
            warmup_results.extend(
                await _run_schedule_attempts(
                    provider=provider,
                    system_under_test=system_under_test,
                    workload=workload,
                    schedule_id=schedule.schedule_id,
                    concurrency=schedule.concurrency,
                    repetitions=schedule.warmup_repetitions_per_case,
                    warmup=True,
                    resource_collector=collector,
                )
            )
            wall_started_ns = perf_counter_ns()
            scheduled_results = await _run_schedule_attempts(
                provider=provider,
                system_under_test=system_under_test,
                workload=workload,
                schedule_id=schedule.schedule_id,
                concurrency=schedule.concurrency,
                repetitions=schedule.measured_repetitions_per_case,
                warmup=False,
                resource_collector=collector,
            )
            wall_time_ms = (perf_counter_ns() - wall_started_ns) / 1_000_000
            measured_results.extend(scheduled_results)
            schedule_summaries.append(
                _summarize_schedule(
                    schedule_id=schedule.schedule_id,
                    concurrency=schedule.concurrency,
                    wall_time_ms=wall_time_ms,
                    samples=[item.sample for item in scheduled_results],
                )
            )
    finally:
        close_collector = getattr(collector, "aclose", None)
        if close_collector is not None:
            await close_collector()

    measured_samples = tuple(item.sample for item in measured_results)
    completed_count = sum(sample.status == "completed" for sample in measured_samples)
    status = (
        "completed"
        if completed_count == len(measured_samples)
        else "partial"
        if completed_count
        else "failed"
    )
    benchmark_completed_at = datetime.now(UTC)
    system_report = InferenceSystemBenchmarkReport(
        status=status,
        started_at=benchmark_started_at,
        completed_at=benchmark_completed_at,
        benchmark_code_revision=benchmark_code_revision,
        system_under_test=system_under_test,
        environment=environment,
        workload_manifest_id=workload.workload_manifest_id,
        workload_content_hash=workload.content_hash,
        measurement_methodology={
            "ttft_ms": "client monotonic clock from provider call to first nonempty typed output delta",
            "tpot_ms": "client first-to-last visible delta interval divided by output_tokens minus one; null when stream granularity is insufficient",
            "end_to_end_latency_ms": "client monotonic clock around the complete typed provider stream",
            "generation_interval_ms": "client monotonic clock from first nonempty output delta to terminal stream receipt",
            "attempted_requests_per_second": "per-sample service-rate equivalent (one divided by end-to-end seconds), distinct from schedule throughput",
            "schedule_throughput": "measured attempts or completed tokens divided by measured schedule wall time",
            "resources": "per-sample collector result, otherwise null with an explicit reason",
            "percentiles": "linear interpolation over sorted measured values (havre-percentile-linear-v1)",
        },
        warmup_samples=tuple(item.sample for item in warmup_results),
        measured_samples=measured_samples,
        schedule_summaries=tuple(schedule_summaries),
        limitations=(
            "Synthetic workloads measure this pinned system and environment only.",
            "Systems measurements do not establish helpfulness, safety, or production readiness.",
            "Resource values are null unless a named reliable collector supplied them.",
            "Host resource samples overlap at concurrency greater than one and are not per-request attribution.",
            "Counterbalanced schedule order reduces but cannot eliminate cache or thermal carryover.",
            "Small synthetic sample counts make interpolated p95 values descriptive, not tail-confidence claims.",
        ),
    )

    compatibility_started_at = datetime.now(UTC)
    baseline_by_case: dict[str, _ExecutionResult] = {}
    if baseline_provider is not None and baseline_manifest is not None:
        baseline_results = await _run_schedule_attempts(
            provider=baseline_provider,
            system_under_test=baseline_manifest,
            workload=workload,
            schedule_id="compatibility-baseline",
            concurrency=1,
            repetitions=1,
            warmup=False,
            resource_collector=NullResourceCollector(),
        )
        baseline_by_case = {
            result.sample.workload_case_id: result for result in baseline_results
        }

    candidate_results = await _run_schedule_attempts(
        provider=provider,
        system_under_test=system_under_test,
        workload=workload,
        schedule_id="compatibility-candidate",
        concurrency=1,
        repetitions=1,
        warmup=False,
        resource_collector=NullResourceCollector(),
    )
    candidate_by_case = {
        result.sample.workload_case_id: result for result in candidate_results
    }
    case_results = tuple(
        _compatibility_case(
            case=case,
            candidate=candidate_by_case[case.case_id],
            baseline=baseline_by_case.get(case.case_id),
        )
        for case in workload.cases
    )
    compatibility_report = InferenceCompatibilityReport(
        benchmark_run_id=system_report.benchmark_run_id,
        started_at=compatibility_started_at,
        completed_at=datetime.now(UTC),
        candidate_manifest_id=system_under_test.manifest_id,
        candidate_manifest_content_hash=system_under_test.content_hash,
        baseline_manifest_id=(
            None if baseline_manifest is None else baseline_manifest.manifest_id
        ),
        baseline_manifest_content_hash=(
            None if baseline_manifest is None else baseline_manifest.content_hash
        ),
        workload_manifest_id=workload.workload_manifest_id,
        workload_content_hash=workload.content_hash,
        candidate_samples=tuple(result.sample for result in candidate_results),
        baseline_samples=tuple(
            baseline_by_case[case.case_id].sample
            for case in workload.cases
            if case.case_id in baseline_by_case
        ),
        case_results=case_results,
        limitations=(
            "This report is descriptive and non-binding; it contains no release threshold.",
            "Synthetic protocol observations are not evidence of real-world benefit.",
            "Human-approved rubric anchors and critical safety gates remain unresolved.",
        ),
    )
    validate_inference_benchmark_report_pair(system_report, compatibility_report)

    if system_output_path is not None and compatibility_output_path is not None:
        write_report_pair(
            system_report=system_report,
            compatibility_report=compatibility_report,
            system_output_path=system_output_path,
            compatibility_output_path=compatibility_output_path,
        )
    return system_report, compatibility_report


async def _validate_live_provider(
    provider: ModelProvider,
    manifest: InferenceSystemUnderTestManifest,
) -> None:
    capabilities, health, version = await asyncio.gather(
        provider.capabilities(), provider.health(), provider.version()
    )
    problems: list[str] = []
    if capabilities.provider_id != manifest.provider_id:
        problems.append("provider_id")
    if capabilities.provider_class != manifest.provider_class:
        problems.append("provider_class")
    if capabilities.execution_environment != manifest.execution_environment:
        problems.append("execution_environment")
    if manifest.model_version_id not in capabilities.available_model_version_ids:
        problems.append("capabilities.model_version_id")
    if capabilities.max_context_tokens != manifest.context_limit:
        problems.append("capabilities.max_context_tokens")
    if capabilities.max_output_tokens != manifest.max_output_tokens:
        problems.append("capabilities.max_output_tokens")
    if not capabilities.supports_streaming:
        problems.append("streaming_capability")
    if health.status == "unavailable":
        problems.append("provider_health")
    if manifest.model_version_id not in health.loaded_model_version_ids:
        problems.append("health.loaded_model_version_id")
    exact_version_fields = {
        "version.provider_id": (version.provider_id, manifest.provider_id),
        "version.provider_class": (version.provider_class, manifest.provider_class),
        "version.execution_environment": (
            version.execution_environment,
            manifest.execution_environment,
        ),
        "version.model_version_id": (
            version.model_version_id,
            manifest.model_version_id,
        ),
        "version.model_artifact_hash": (
            version.model_artifact_hash,
            manifest.model_artifact_hash,
        ),
        "version.provider_adapter_version_id": (
            version.provider_adapter_version_id,
            manifest.provider_adapter_version_id,
        ),
        "version.tokenizer_version_id": (
            version.tokenizer_version_id,
            manifest.tokenizer_version_id,
        ),
        "version.serving_config_version": (
            version.serving_config_version,
            manifest.serving_config_version,
        ),
        "version.serving_engine": (
            version.serving_engine,
            manifest.serving_engine,
        ),
        "version.serving_engine_version": (
            version.serving_engine_version,
            manifest.serving_engine_version,
        ),
    }
    problems.extend(
        field
        for field, (observed, expected) in exact_version_fields.items()
        if observed != expected
    )
    if problems:
        raise BenchmarkManifestMismatch(
            "live provider does not match benchmark manifest: " + ", ".join(problems)
        )


def _revalidate_content_hashed(model):
    """Detect nested mutable-container edits before durable serialization."""

    return type(model).model_validate(model.model_dump(mode="json"))


async def _run_schedule_attempts(
    *,
    provider: ModelProvider,
    system_under_test: InferenceSystemUnderTestManifest,
    workload: InferenceWorkloadManifest,
    schedule_id: str,
    concurrency: int,
    repetitions: int,
    warmup: bool,
    resource_collector: ResourceCollector,
) -> list[_ExecutionResult]:
    if repetitions == 0:
        return []
    semaphore = asyncio.Semaphore(concurrency)

    async def run(case: InferenceWorkloadCase, attempt_index: int) -> _ExecutionResult:
        async with semaphore:
            return await _execute_stream_attempt(
                provider=provider,
                system_under_test=system_under_test,
                workload=workload,
                case=case,
                schedule_id=schedule_id,
                concurrency=concurrency,
                attempt_index=attempt_index,
                warmup=warmup,
                resource_collector=resource_collector,
            )

    attempts = [
        (case, repetition + 1)
        for repetition in range(repetitions)
        for case in workload.cases
    ]
    random.Random(
        f"{workload.random_seed}:{repetitions}:{'warmup' if warmup else 'measured'}"
    ).shuffle(attempts)
    tasks = [
        asyncio.create_task(run(case, attempt_index))
        for case, attempt_index in attempts
    ]
    return list(await asyncio.gather(*tasks))


async def _execute_stream_attempt(
    *,
    provider: ModelProvider,
    system_under_test: InferenceSystemUnderTestManifest,
    workload: InferenceWorkloadManifest,
    case: InferenceWorkloadCase,
    schedule_id: str,
    concurrency: int,
    attempt_index: int,
    warmup: bool,
    resource_collector: ResourceCollector,
) -> _ExecutionResult:
    trace_id = new_trace_id()
    request = _request_for_case(
        case=case,
        workload=workload,
        trace_id=trace_id,
        execution_environment=system_under_test.execution_environment,
    )
    first_visible_ns: int | None = None
    last_visible_ns: int | None = None
    stream_event_count = 0
    output_chunks: list[str] = []
    response: InferenceResponse | None = None
    failure: BenchmarkError | None = None
    stream_response_id = None
    terminal_seen = False
    resource_collection_failed = False
    try:
        resource_handle = await resource_collector.begin_sample()
    except Exception:
        resource_handle = None
        resource_collection_failed = True
    started_at = datetime.now(UTC)
    started_ns = perf_counter_ns()

    try:
        async with asyncio.timeout(workload.timeout_ms / 1000):
            async for event in provider.stream(request):
                _validate_stream_event(
                    event=event,
                    request=request,
                    expected_sequence_number=stream_event_count,
                    expected_response_id=stream_response_id,
                )
                if terminal_seen:
                    raise _StreamProtocolError("stream emitted an event after its terminal event")
                if stream_response_id is None:
                    stream_response_id = event.inference_response_id
                event_kind = _stream_event_kind(event)
                if stream_event_count == 0 and event_kind != "response_started":
                    raise _StreamProtocolError("stream did not begin with response_started")
                stream_event_count += 1
                if event_kind == "response_started":
                    if stream_event_count != 1:
                        raise _StreamProtocolError("stream emitted response_started more than once")
                    continue
                if event_kind == "output_delta":
                    text = _stream_delta_text(event)
                    if text:
                        now_ns = perf_counter_ns()
                        if first_visible_ns is None:
                            first_visible_ns = now_ns
                        last_visible_ns = now_ns
                        output_chunks.append(text)
                    continue
                if event_kind == "response_completed":
                    if response is not None or failure is not None:
                        raise _StreamProtocolError("stream emitted more than one terminal event")
                    response = _stream_completed_response(event)
                    terminal_seen = True
                    continue
                if event_kind == "response_failed":
                    if response is not None or failure is not None:
                        raise _StreamProtocolError("stream emitted more than one terminal event")
                    failure = _stream_failure(
                        event,
                        trace_id=trace_id,
                        system_under_test=system_under_test,
                    )
                    terminal_seen = True
                    continue
                raise _StreamProtocolError(f"unknown typed stream event {event_kind!r}")
    except TimeoutError:
        failure = BenchmarkError(
            code="provider_timeout",
            retryable=True,
            safe_message="provider stream exceeded the benchmark timeout",
            trace_id=trace_id,
        )
    except Exception as error:  # typed provider failures are normalized below
        failure = _benchmark_error_from_exception(error, trace_id=trace_id)

    completed_at = datetime.now(UTC)
    completed_ns = perf_counter_ns()
    try:
        if resource_collection_failed:
            raise RuntimeError("resource collector setup failed")
        resources = await resource_collector.finish_sample(resource_handle)
        if not isinstance(resources, ResourceSnapshot):
            raise TypeError("resource collector returned an untyped snapshot")
    except Exception:
        resources = unavailable_resource_snapshot("resource_collector_failed")

    output_text = "".join(output_chunks)
    if response is None and failure is None:
        failure = BenchmarkError(
            code="stream_interrupted",
            retryable=True,
            safe_message="provider stream ended without a terminal event",
            trace_id=trace_id,
        )
    if failure is not None:
        response = None
    if response is not None and failure is None:
        reconciliation_error = _reconcile_response(
            request=request,
            response=response,
            output_text=output_text,
            system_under_test=system_under_test,
        )
        if reconciliation_error is not None:
            failure = reconciliation_error
            response = None

    e2e_ms = (completed_ns - started_ns) / 1_000_000
    ttft_ms = (
        None if first_visible_ns is None else (first_visible_ns - started_ns) / 1_000_000
    )
    visible_token_interval_ms = (
        None
        if first_visible_ns is None or last_visible_ns is None
        else (last_visible_ns - first_visible_ns) / 1_000_000
    )
    generation_interval_ms = (
        None
        if first_visible_ns is None
        else (completed_ns - first_visible_ns) / 1_000_000
    )
    unavailable: dict[str, str] = {}
    if generation_interval_ms is None:
        unavailable["generation_interval_ms"] = "no_nonempty_output_delta"
    if visible_token_interval_ms is None:
        unavailable["visible_token_interval_ms"] = "no_nonempty_output_delta"
    tpot_ms: float | None = None
    output_tps: float | None = None
    if response is None:
        unavailable.update(
            {
                "ttft_ms": "request_failed_before_a_completed_response"
                if ttft_ms is None
                else "available_above",
                "tpot_ms": "request_failed",
                "output_tokens_per_second": "request_failed",
            }
        )
    else:
        if ttft_ms is None:
            unavailable["ttft_ms"] = "completed_stream_had_no_nonempty_output_delta"
        if response.usage.output_tokens < 2:
            unavailable["tpot_ms"] = "fewer_than_two_output_tokens"
        elif visible_token_interval_ms is None or visible_token_interval_ms <= 0:
            unavailable["tpot_ms"] = "no_positive_visible_generation_interval"
        else:
            tpot_ms = visible_token_interval_ms / (response.usage.output_tokens - 1)
        if generation_interval_ms is None or generation_interval_ms <= 0:
            unavailable["output_tokens_per_second"] = (
                "no_positive_terminal_generation_interval"
            )
        else:
            output_tps = response.usage.output_tokens / (
                generation_interval_ms / 1000
            )

    sample = InferenceBenchmarkSample(
        schedule_id=schedule_id,
        workload_case_id=case.case_id,
        workload_class=case.workload_class,
        warmup=warmup,
        attempt_index=attempt_index,
        concurrency=concurrency,
        inference_request_id=request.inference_request_id,
        inference_response_id=stream_response_id,
        trace_id=trace_id,
        status="failed" if failure is not None else "completed",
        started_at=started_at,
        completed_at=completed_at,
        ttft_ms=ttft_ms,
        tpot_ms=tpot_ms,
        end_to_end_latency_ms=e2e_ms,
        generation_interval_ms=generation_interval_ms,
        visible_token_interval_ms=visible_token_interval_ms,
        attempted_requests_per_second=(1000 / e2e_ms if e2e_ms > 0 else 0),
        output_tokens_per_second=output_tps,
        prompt_tokens=None if response is None else response.usage.prompt_tokens,
        output_tokens=None if response is None else response.usage.output_tokens,
        total_tokens=None if response is None else response.usage.total_tokens,
        token_count_source=(
            None if response is None else response.usage.token_count_source
        ),
        stream_event_count=stream_event_count,
        output_content_hash=(
            None if response is None else content_hash(output_text)
        ),
        system_manifest_content_hash=system_under_test.content_hash,
        provider_id=system_under_test.provider_id,
        provider_class=system_under_test.provider_class,
        execution_environment=system_under_test.execution_environment,
        provider_request_id=(
            None if response is None else response.provider.provider_request_id
        ),
        model_version_id=(
            None if response is None else response.versions.model_version_id
        ),
        adapter_version_id=(
            None if response is None else response.versions.adapter_version_id
        ),
        provider_adapter_version_id=(
            None
            if response is None
            else response.versions.provider_adapter_version_id
        ),
        tokenizer_version_id=(
            None if response is None else response.versions.tokenizer_version_id
        ),
        serving_config_version=(
            None if response is None else response.versions.serving_config_version
        ),
        serving_engine=(
            None if response is None else response.versions.serving_engine
        ),
        serving_engine_version=(
            None if response is None else response.versions.serving_engine_version
        ),
        model_artifact_hash=(
            None if response is None else response.versions.model_artifact_hash
        ),
        unavailable_measurements={
            key: value for key, value in unavailable.items() if value != "available_above"
        },
        resources=resources,
        error=failure,
    )
    return _ExecutionResult(sample=sample, output_text=output_text)


def _request_for_case(
    *,
    case: InferenceWorkloadCase,
    workload: InferenceWorkloadManifest,
    trace_id: str,
    execution_environment: ExecutionEnvironment,
) -> InferenceRequest:
    policy = DataPolicy.owner_default(
        PrivacyClass.NORMAL,
        memory_eligible=False,
    )
    return InferenceRequest(
        request_id=uuid7(),
        trace_id=trace_id,
        messages=tuple(
            InferenceMessage(
                role=message.role,
                content_parts=(TextContentPart(text=message.text),),
                source_refs=(
                    f"benchmark-workload/{workload.workload_manifest_id}/case/{case.case_id}",
                ),
            )
            for message in case.messages
        ),
        context_pack_id=uuid7(),
        generation=GenerationSettings(
            max_output_tokens=case.max_output_tokens,
            temperature=case.temperature,
            top_p=case.top_p,
            seed=case.seed,
            stop=case.stop,
        ),
        constraints=InferenceConstraints(
            stream=True,
            timeout_ms=workload.timeout_ms,
            effective_data_policy=policy,
            allowed_execution_environments=(execution_environment,),
        ),
        metadata={
            "benchmark_protocol_version": workload.protocol_version,
            "benchmark_workload_class": case.workload_class,
        },
    )


def _validate_stream_event(
    *,
    event: object,
    request: InferenceRequest,
    expected_sequence_number: int,
    expected_response_id: object,
) -> None:
    if not isinstance(event, InferenceStreamEvent):
        raise _StreamProtocolError("provider yielded an untyped stream event")
    if event.sequence_number != expected_sequence_number:
        raise _StreamProtocolError("stream sequence number was not contiguous")
    if (
        event.inference_request_id != request.inference_request_id
        or event.request_id != request.request_id
        or event.trace_id != request.trace_id
    ):
        raise _StreamProtocolError("stream event lineage did not match the request")
    if (
        expected_response_id is not None
        and event.inference_response_id != expected_response_id
    ):
        raise _StreamProtocolError("stream response ID changed during one response")


def _stream_event_kind(event: InferenceStreamEvent) -> str:
    value = getattr(event, "event_type", None)
    if value is None:
        value = getattr(event, "event", None)
    if hasattr(value, "value"):
        value = value.value
    if not isinstance(value, str):
        raise _StreamProtocolError("typed stream event has no event type")
    return value


def _stream_delta_text(event: InferenceStreamEvent) -> str:
    for field in ("text_delta", "delta", "text"):
        value = getattr(event, field, None)
        if isinstance(value, str):
            return value
        if hasattr(value, "text") and isinstance(value.text, str):
            return value.text
    raise _StreamProtocolError("output_delta event has no text delta")


def _stream_completed_response(event: InferenceStreamEvent) -> InferenceResponse:
    response = getattr(event, "response", None)
    if not isinstance(response, InferenceResponse):
        raise _StreamProtocolError(
            "response_completed event has no typed InferenceResponse"
        )
    return response


def _stream_failure(
    event: InferenceStreamEvent,
    *,
    trace_id: str,
    system_under_test: InferenceSystemUnderTestManifest,
) -> BenchmarkError:
    failure = getattr(event, "failure", None)
    if failure is None:
        failure = getattr(event, "error", None)
    if (
        getattr(failure, "provider_id", None) != system_under_test.provider_id
        or getattr(failure, "provider_class", None)
        != system_under_test.provider_class
    ):
        return BenchmarkError(
            code="provider_protocol_error",
            retryable=False,
            safe_message="typed failure provider did not match the system manifest",
            trace_id=trace_id,
        )
    return _benchmark_error_from_failure(failure, trace_id=trace_id)


def _benchmark_error_from_failure(failure: object, *, trace_id: str) -> BenchmarkError:
    code = getattr(failure, "code", None)
    if hasattr(code, "value"):
        code = code.value
    if code not in BENCHMARK_ERROR_CODES:
        code = "provider_protocol_error"
    safe_message = getattr(failure, "safe_message", None)
    if not isinstance(safe_message, str) or not safe_message:
        safe_message = "provider reported a typed stream failure"
    provider_status_code = getattr(failure, "provider_status_code", None)
    provider_error_code = getattr(failure, "provider_error_code", None)
    if not isinstance(provider_error_code, str) or not provider_error_code:
        provider_error_code = None
    return BenchmarkError(
        code=code,
        retryable=bool(getattr(failure, "retryable", False)),
        safe_message=safe_message,
        provider_status_code=(
            provider_status_code if isinstance(provider_status_code, int) else None
        ),
        provider_error_code=provider_error_code,
        trace_id=trace_id,
    )


def _benchmark_error_from_exception(error: Exception, *, trace_id: str) -> BenchmarkError:
    if isinstance(error, _StreamProtocolError):
        return BenchmarkError(
            code="provider_protocol_error",
            retryable=False,
            safe_message="provider stream violated the typed protocol",
            trace_id=trace_id,
        )
    code = getattr(error, "code", None)
    if hasattr(code, "value"):
        code = code.value
    if code not in BENCHMARK_ERROR_CODES:
        code = "internal_error"
    safe_message = getattr(error, "safe_message", None)
    if not isinstance(safe_message, str) or not safe_message:
        safe_message = "provider request failed"
    safe_message = safe_message[:500]
    provider_status_code = getattr(error, "provider_status_code", None)
    return BenchmarkError(
        code=code,
        retryable=bool(getattr(error, "retryable", False)),
        safe_message=safe_message,
        provider_status_code=(
            provider_status_code
            if isinstance(provider_status_code, int)
            and 100 <= provider_status_code <= 599
            else None
        ),
        trace_id=trace_id,
    )


def _reconcile_response(
    *,
    request: InferenceRequest,
    response: InferenceResponse,
    output_text: str,
    system_under_test: InferenceSystemUnderTestManifest,
) -> BenchmarkError | None:
    protocol_mismatch = (
        response.inference_request_id != request.inference_request_id
        or response.request_id != request.request_id
        or response.trace_id != request.trace_id
        or not output_text
        or "".join(part.text for part in response.output_parts) != output_text
    )
    if protocol_mismatch:
        return BenchmarkError(
            code="provider_protocol_error",
            retryable=False,
            safe_message="stream terminal response did not reconcile",
            trace_id=request.trace_id,
        )
    version_mismatch = (
        response.provider.provider_id != system_under_test.provider_id
        or response.provider.provider_class != system_under_test.provider_class
        or response.versions.model_version_id != system_under_test.model_version_id
        or response.versions.adapter_version_id != system_under_test.adapter_version_id
        or response.versions.tokenizer_version_id != system_under_test.tokenizer_version_id
        or response.versions.serving_config_version
        != system_under_test.serving_config_version
        or response.versions.provider_adapter_version_id
        != system_under_test.provider_adapter_version_id
        or response.versions.serving_engine != system_under_test.serving_engine
        or response.versions.serving_engine_version
        != system_under_test.serving_engine_version
        or response.versions.model_artifact_hash
        != system_under_test.model_artifact_hash
    )
    if version_mismatch:
        return BenchmarkError(
            code="version_mismatch",
            retryable=False,
            safe_message="provider response versions did not match the pinned manifest",
            trace_id=request.trace_id,
        )
    return None


def _percentile(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def _aggregate(metric: str, unit: str, values: Sequence[float]) -> MetricAggregate:
    if not values:
        return MetricAggregate(
            metric=metric,
            unit=unit,
            sample_count=0,
            unavailable_reason="no_completed_sample_exposed_this_measurement",
        )
    return MetricAggregate(
        metric=metric,
        unit=unit,
        sample_count=len(values),
        mean=statistics.fmean(values),
        p50=_percentile(values, 0.50),
        p95=_percentile(values, 0.95),
    )


def _summarize_schedule(
    *,
    schedule_id: str,
    concurrency: int,
    wall_time_ms: float,
    samples: list[InferenceBenchmarkSample],
) -> ScheduleSummary:
    completed = [sample for sample in samples if sample.status == "completed"]
    wall_seconds = wall_time_ms / 1000
    errors = Counter(
        sample.error.code
        for sample in samples
        if sample.error is not None
    )
    prompt_tokens = sum(sample.prompt_tokens or 0 for sample in completed)
    output_tokens = sum(sample.output_tokens or 0 for sample in completed)
    return ScheduleSummary(
        schedule_id=schedule_id,
        concurrency=concurrency,
        wall_time_ms=wall_time_ms,
        attempted_requests=len(samples),
        completed_requests=len(completed),
        error_rate=(
            (len(samples) - len(completed)) / len(samples) if samples else 0
        ),
        attempted_requests_per_second=(
            len(samples) / wall_seconds if wall_seconds > 0 else 0
        ),
        completed_requests_per_second=(
            len(completed) / wall_seconds if wall_seconds > 0 else 0
        ),
        input_tokens_per_second=(
            prompt_tokens / wall_seconds if completed and wall_seconds > 0 else None
        ),
        output_tokens_per_second=(
            output_tokens / wall_seconds if completed and wall_seconds > 0 else None
        ),
        total_tokens_per_second=(
            (prompt_tokens + output_tokens) / wall_seconds
            if completed and wall_seconds > 0
            else None
        ),
        errors_by_code=dict(sorted(errors.items())),
        metrics=(
            _aggregate(
                "end_to_end_latency_ms",
                "ms",
                [sample.end_to_end_latency_ms for sample in samples],
            ),
            _aggregate(
                "ttft_ms",
                "ms",
                [sample.ttft_ms for sample in completed if sample.ttft_ms is not None],
            ),
            _aggregate(
                "tpot_ms",
                "ms_per_output_token",
                [sample.tpot_ms for sample in completed if sample.tpot_ms is not None],
            ),
            _aggregate(
                "prompt_tokens",
                "tokens",
                [
                    float(sample.prompt_tokens)
                    for sample in completed
                    if sample.prompt_tokens is not None
                ],
            ),
            _aggregate(
                "output_tokens",
                "tokens",
                [
                    float(sample.output_tokens)
                    for sample in completed
                    if sample.output_tokens is not None
                ],
            ),
            _aggregate(
                "total_tokens",
                "tokens",
                [
                    float(sample.total_tokens)
                    for sample in completed
                    if sample.total_tokens is not None
                ],
            ),
            _aggregate(
                "per_sample_output_tokens_per_second",
                "tokens_per_second",
                [
                    sample.output_tokens_per_second
                    for sample in completed
                    if sample.output_tokens_per_second is not None
                ],
            ),
            _aggregate(
                "cpu_percent",
                "percent",
                [
                    sample.resources.cpu_percent.value
                    for sample in samples
                    if sample.resources.cpu_percent.value is not None
                ],
            ),
            _aggregate(
                "ram_used_bytes",
                "bytes",
                [
                    sample.resources.ram_used_bytes.value
                    for sample in samples
                    if sample.resources.ram_used_bytes.value is not None
                ],
            ),
            _aggregate(
                "gpu_utilization_percent",
                "percent",
                [
                    sample.resources.gpu_utilization_percent.value
                    for sample in samples
                    if sample.resources.gpu_utilization_percent.value is not None
                ],
            ),
            _aggregate(
                "vram_used_bytes",
                "bytes",
                [
                    sample.resources.vram_used_bytes.value
                    for sample in samples
                    if sample.resources.vram_used_bytes.value is not None
                ],
            ),
            _aggregate(
                "vram_peak_used_bytes",
                "bytes",
                [
                    sample.resources.vram_peak_used_bytes.value
                    for sample in samples
                    if sample.resources.vram_peak_used_bytes.value is not None
                ],
            ),
        ),
    )


def _compatibility_case(
    *,
    case: InferenceWorkloadCase,
    candidate: _ExecutionResult,
    baseline: _ExecutionResult | None,
) -> CompatibilityCaseResult:
    candidate_text = candidate.output_text
    baseline_text = None if baseline is None else baseline.output_text
    observations = [
        CompatibilityObservation(
            observation="nonempty_output",
            candidate_value=bool(candidate_text),
            baseline_value=None if baseline is None else bool(baseline_text),
            note="Descriptive protocol observation; not a quality gate.",
        ),
        CompatibilityObservation(
            observation="output_character_count",
            candidate_value=len(candidate_text),
            baseline_value=None if baseline_text is None else len(baseline_text),
            note="Length comparison has no preferred direction or threshold.",
        ),
        CompatibilityObservation(
            observation="output_token_count",
            candidate_value=candidate.sample.output_tokens,
            baseline_value=None if baseline is None else baseline.sample.output_tokens,
            note="Provider-reported or explicitly identified estimator token count.",
        ),
    ]
    if case.response_expectation == "json_object":
        observations.append(
            CompatibilityObservation(
                observation="json_object_parseable",
                candidate_value=_is_json_object(candidate_text),
                baseline_value=(
                    None if baseline_text is None else _is_json_object(baseline_text)
                ),
                note="Schema-free compatibility observation; no extraction feature is activated.",
            )
        )
    return CompatibilityCaseResult(
        workload_case_id=case.case_id,
        workload_class=case.workload_class,
        candidate_status=candidate.sample.status,
        baseline_status="not_run" if baseline is None else baseline.sample.status,
        candidate_output_content_hash=candidate.sample.output_content_hash,
        baseline_output_content_hash=(
            None if baseline is None else baseline.sample.output_content_hash
        ),
        observations=tuple(observations),
    )


def _is_json_object(value: str) -> bool:
    try:
        return isinstance(json.loads(value), dict)
    except (TypeError, json.JSONDecodeError):
        return False


def write_report_pair(
    *,
    system_report: InferenceSystemBenchmarkReport,
    compatibility_report: InferenceCompatibilityReport,
    system_output_path: Path,
    compatibility_output_path: Path,
) -> None:
    """Create two immutable artifacts; never overwrite an earlier run."""

    system_report = _revalidate_content_hashed(system_report)
    compatibility_report = _revalidate_content_hashed(compatibility_report)
    validate_inference_benchmark_report_pair(system_report, compatibility_report)
    paths = (system_output_path, compatibility_output_path)
    existing = [path for path in paths if path.exists()]
    if existing:
        raise BenchmarkOutputExists(
            "benchmark artifact already exists: "
            + ", ".join(str(path) for path in existing)
        )
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
    with system_output_path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(system_report.model_dump_json(indent=2))
        handle.write("\n")
    with compatibility_output_path.open(
        "x", encoding="utf-8", newline="\n"
    ) as handle:
        handle.write(compatibility_report.model_dump_json(indent=2))
        handle.write("\n")
