"""Isolated runner for the pinned Stage 3 self-hosted inference benchmark.

The runner connects to an already-running loopback service.  It never starts,
stops, downloads, or mutates serving artifacts, and its reports contain only
reviewed synthetic workload content hashes and machine/system measurements.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
import hashlib
import json
import platform
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter_ns
from typing import Any, Protocol

import psutil

from companion.hashing import content_hash
from companion.ids import uuid7
from evals.inference_benchmark import (
    BenchmarkOutputExists,
    ResourceCollector,
    capture_environment_manifest,
    load_workload_manifest,
    run_inference_benchmark,
    write_report_pair,
)
from mlsys.contracts.inference_benchmark import (
    ArtifactDigest,
    InferenceBenchmarkSchedule,
    InferenceCompatibilityReport,
    InferenceEnvironmentManifest,
    InferenceSystemBenchmarkReport,
    InferenceSystemUnderTestManifest,
    InferenceWorkloadManifest,
    ResourceObservation,
    ResourceSnapshot,
    RuntimeVerification,
)
from mlsys.serving import (
    DeterministicLocalProvider,
    ModelProvider,
    OpenAICompatibleProvider,
    RuntimeAttestation,
    attest_active_runtime,
)
from services.api.settings import Settings
from mlsys.serving.openai_compatible import llama_context_tokens_per_slot


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = (PROJECT_ROOT / ".runtime" / "stage3").resolve()
RUNTIME_STATE_PATH = RUNTIME_ROOT / "runtime-state.json"
RUNTIME_PID_PATH = RUNTIME_ROOT / "run" / "llama-server.pid"
DEFAULT_WORKLOAD_PATH = PROJECT_ROOT / "evals" / "fixtures" / "inference_workload_v1.json"
APPROVED_WORKLOAD_CONTENT_HASH = (
    "sha256:46f5a39afe751ec7378a586e08c89f3304362b7cb06a8a301f90795f9a6c9712"
)
# Updated only alongside the reviewed base fixture and deterministic transform below.
APPROVED_CONTROLLED_WORKLOAD_CONTENT_HASH = (
    "sha256:26db3a3b8053d81564980406cda4c086eec4caafaa644d3b672b757dcfe5a49a"
)
DEFAULT_ENVIRONMENT_TEMPLATE_PATH = (
    PROJECT_ROOT
    / "mlsys"
    / "serving"
    / "manifests"
    / "stage3-environment-template-v1.json"
)
BENCHMARK_RUNNER_VERSION = "stage3-inference-runner-v1"


class InferenceBenchmarkPersistence(Protocol):
    def persist_inference_benchmark_reports(
        self,
        *,
        system_report: InferenceSystemBenchmarkReport,
        compatibility_report: InferenceCompatibilityReport,
        workload_manifest: InferenceWorkloadManifest,
    ) -> None: ...


@dataclass(frozen=True)
class _ResourceHandle:
    cpu_times: object
    gpu_sample_index: int


@dataclass(frozen=True)
class _GpuSample:
    observed_ns: int
    utilization_percent: float
    vram_used_bytes: float


class PsutilNvidiaResourceCollector:
    """Content-free host sampler with honest NVIDIA unavailability metadata."""

    def __init__(self, *, nvidia_smi: str | None = None) -> None:
        self._nvidia_smi = nvidia_smi or shutil.which("nvidia-smi")
        self._gpu_samples: list[_GpuSample] = []
        self._sampler_task: asyncio.Task[None] | None = None
        self._first_gpu_query: asyncio.Event | None = None
        self._gpu_query_failed = False

    async def begin_sample(self) -> object:
        if self._sampler_task is None and self._nvidia_smi is not None:
            self._first_gpu_query = asyncio.Event()
            self._sampler_task = asyncio.create_task(self._sample_gpu_loop())
        if self._first_gpu_query is not None:
            await self._first_gpu_query.wait()
        return _ResourceHandle(
            cpu_times=psutil.cpu_times(),
            gpu_sample_index=max(0, len(self._gpu_samples) - 1),
        )

    async def finish_sample(self, handle: object) -> ResourceSnapshot:
        if not isinstance(handle, _ResourceHandle):
            raise TypeError("resource collector handle has an invalid type")
        completed_ns = perf_counter_ns()
        cpu_after = psutil.cpu_times()
        cpu_percent = _cpu_busy_percent(handle.cpu_times, cpu_after)
        memory = psutil.virtual_memory()
        gpu_samples = [
            sample
            for sample in self._gpu_samples[handle.gpu_sample_index :]
            if sample.observed_ns <= completed_ns
        ]
        unavailable_reason = (
            "nvidia_smi_not_available"
            if self._nvidia_smi is None
            else "nvidia_smi_query_failed_or_no_nvidia_device"
            if self._gpu_query_failed
            else "no_nvidia_smi_sample_in_request_interval"
        )

        def measured(value: float, unit: str, source: str) -> ResourceObservation:
            return ResourceObservation(value=value, unit=unit, source=source)

        def missing(unit: str, reason: str = unavailable_reason) -> ResourceObservation:
            return ResourceObservation(
                unit=unit,
                unavailable_reason=reason,
            )

        if gpu_samples:
            gpu_utilization = measured(
                max(sample.utilization_percent for sample in gpu_samples),
                "percent",
                "nvidia-smi boundary/250ms sampled maximum",
            )
            vram_used = measured(
                gpu_samples[-1].vram_used_bytes,
                "bytes",
                "nvidia-smi latest boundary/interval sample",
            )
            vram_peak = measured(
                max(sample.vram_used_bytes for sample in gpu_samples),
                "bytes",
                "nvidia-smi boundary/250ms sampled maximum",
            )
        else:
            gpu_utilization = missing("percent")
            vram_used = missing("bytes")
            vram_peak = missing("bytes")
        return ResourceSnapshot(
            observed_at=datetime.now(UTC),
            cpu_percent=(
                measured(
                    cpu_percent,
                    "percent",
                    "psutil cumulative host CPU delta",
                )
                if cpu_percent is not None
                else missing("percent", "psutil_cpu_time_resolution_insufficient")
            ),
            ram_used_bytes=measured(
                float(memory.used),
                "bytes",
                "psutil virtual_memory used",
            ),
            gpu_utilization_percent=gpu_utilization,
            vram_used_bytes=vram_used,
            vram_peak_used_bytes=vram_peak,
        )

    async def aclose(self) -> None:
        if self._sampler_task is None:
            return
        self._sampler_task.cancel()
        with suppress(asyncio.CancelledError):
            await self._sampler_task
        self._sampler_task = None

    async def _sample_gpu_loop(self) -> None:
        while True:
            try:
                raw_sample = await asyncio.to_thread(self._query_nvidia_smi)
            except Exception:
                raw_sample = None
            if self._first_gpu_query is not None:
                self._first_gpu_query.set()
            if raw_sample is None:
                self._gpu_query_failed = True
            else:
                self._gpu_samples.append(
                    _GpuSample(
                        observed_ns=perf_counter_ns(),
                        utilization_percent=raw_sample[0],
                        vram_used_bytes=raw_sample[1],
                    )
                )
            await asyncio.sleep(0.25)

    def _query_nvidia_smi(self) -> tuple[float, float] | None:
        if self._nvidia_smi is None:
            return None
        try:
            completed = subprocess.run(
                [
                    self._nvidia_smi,
                    "--query-gpu=utilization.gpu,memory.used",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
                creationflags=(
                    subprocess.CREATE_NO_WINDOW
                    if platform.system() == "Windows"
                    else 0
                ),
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if completed.returncode != 0:
            return None
        rows: list[tuple[float, float]] = []
        for line in completed.stdout.splitlines():
            parts = [part.strip() for part in line.split(",")]
            if len(parts) != 2:
                return None
            try:
                rows.append((float(parts[0]), float(parts[1]) * 1024 * 1024))
            except ValueError:
                return None
        if not rows:
            return None
        return max(item[0] for item in rows), sum(item[1] for item in rows)


def _cpu_busy_percent(before: object, after: object) -> float | None:
    before_values = before._asdict()  # type: ignore[attr-defined]
    after_values = after._asdict()  # type: ignore[attr-defined]
    total_delta = sum(float(after_values[key]) - float(value) for key, value in before_values.items())
    idle_delta = sum(
        float(after_values.get(key, 0)) - float(before_values.get(key, 0))
        for key in ("idle", "iowait")
    )
    if total_delta <= 0:
        return None
    return min(100.0, max(0.0, 100 * (total_delta - idle_delta) / total_delta))


def _read_immutable_manifest(path: Path, *, artifact_kind: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"cannot load {artifact_kind} manifest at {path}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{artifact_kind} manifest must be an object")
    if (
        payload.get("schema_version") != 1
        or payload.get("artifact_kind") != artifact_kind
        or payload.get("immutable") is not True
    ):
        raise ValueError(f"{artifact_kind} manifest is not an immutable v1 manifest")
    return payload


def _file_sha256(path: Path) -> str:
    """Hash artifacts in bounded memory; model weights may be several GiB."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def build_live_benchmark_inputs(
    *,
    settings: Settings,
    code_revision: str,
    environment_template_path: Path = DEFAULT_ENVIRONMENT_TEMPLATE_PATH,
) -> tuple[
    OpenAICompatibleProvider,
    InferenceSystemUnderTestManifest,
    InferenceEnvironmentManifest,
]:
    """Map checked-in manifests and current machine facts to exact contracts."""

    if settings.provider_id != "self-hosted-openai-compatible":
        raise ValueError(
            "benchmark-inference requires HAVRE_PROVIDER_ID=self-hosted-openai-compatible"
        )
    if not code_revision.strip():
        raise ValueError("an exact code revision is required")
    if code_revision != current_source_revision(PROJECT_ROOT):
        raise ValueError(
            "benchmark code revision must match the current source snapshot"
        )
    model_path = settings.self_hosted_model_manifest.resolve()
    engine_path = settings.self_hosted_engine_manifest.resolve()
    template_path = environment_template_path.resolve()
    checked_in_manifest_root = (
        PROJECT_ROOT / "mlsys" / "serving" / "manifests"
    ).resolve()
    if any(
        path.parent != checked_in_manifest_root
        for path in (model_path, engine_path, template_path)
    ):
        raise ValueError("Stage 3 benchmark accepts only checked-in serving manifests")
    model = _read_immutable_manifest(model_path, artifact_kind="model")
    engine = _read_immutable_manifest(engine_path, artifact_kind="serving_engine")
    template = _read_immutable_manifest(
        template_path, artifact_kind="environment_manifest_template"
    )
    profile = model.get("serving_profile")
    model_artifact = model.get("artifact")
    model_upstream = model.get("upstream")
    engine_upstream = engine.get("upstream")
    engine_api = engine.get("api")
    license_value = model.get("license")
    engine_artifacts = engine.get("artifacts")
    if not all(
        isinstance(value, dict)
        for value in (
            profile,
            model_artifact,
            model_upstream,
            engine_upstream,
            engine_api,
            license_value,
        )
    ) or not isinstance(engine_artifacts, list):
        raise ValueError("pinned Stage 3 manifests are missing required objects")
    if any(
        not isinstance(artifact, dict)
        or not all(
            isinstance(artifact.get(field), str) and artifact[field]
            for field in ("role", "url", "sha256")
        )
        for artifact in engine_artifacts
    ):
        raise ValueError("serving engine artifacts require exact role, URI, and hash")
    template_system = template.get("system_under_test")
    if not isinstance(template_system, dict):
        raise ValueError("environment template lacks system_under_test")
    if (
        profile.get("serving_engine_manifest_id") != engine.get("manifest_id")
        or template_system.get("model_manifest_id") != model.get("manifest_id")
        or template_system.get("serving_engine_manifest_id")
        != engine.get("manifest_id")
    ):
        raise ValueError("model, engine, and environment manifests are not linked")
    if model.get("lifecycle_status") != "candidate":
        raise ValueError("Stage 3 model must remain a candidate")
    if profile.get("request_logging") is not False:
        raise ValueError("benchmark requires request logging to remain disabled")
    if int(profile.get("parallel_slots", 0)) < 2:
        raise ValueError("controlled concurrency 1/2 comparison requires two slots")
    if settings.self_hosted_base_url.rstrip("/") != str(engine_api["base_url"]):
        raise ValueError("configured base URL differs from the pinned engine manifest")
    runtime_verification, runtime_attestation = _verify_active_runtime(
        model=model,
        model_manifest_path=model_path,
        engine=engine,
        engine_manifest_path=engine_path,
    )

    model_hash = str(model_artifact["sha256"])
    model_revision = str(model_upstream["revision"])
    engine_tag = str(engine_upstream["release_tag"])
    engine_commit = str(engine_upstream["commit"])
    tokenizer_id = (
        f"{model_upstream['repository']}@{model_revision}:embedded-gguf-tokenizer"
    )
    serving_config_version = content_hash(profile)
    provider_adapter_version_id = "openai-compatible-provider-adapter-v1"
    system_manifest = InferenceSystemUnderTestManifest(
        manifest_id=f"stage3-system-{model['manifest_id']}-{engine_tag}",
        provider_id=settings.provider_id,
        provider_class="self_hosted",
        execution_environment="local",
        model_version_id=str(model["manifest_id"]),
        adapter_version_id=None,
        provider_adapter_version_id=provider_adapter_version_id,
        model_artifact_hash=model_hash,
        model_artifact_hash_unavailable_reason=None,
        tokenizer_version_id=tokenizer_id,
        serving_config_version=serving_config_version,
        serving_engine="llama.cpp",
        serving_engine_version=f"{engine_tag}@{engine_commit}",
        upstream_model_id=str(model_upstream["repository"]),
        upstream_revision=model_revision,
        architecture_family="Qwen3 dense decoder-only transformer",
        parameter_count=None,
        parameter_count_unavailable_reason=(
            "not declared in the pinned model artifact manifest"
        ),
        weights_format=str(model_artifact["weights_format"]),
        precision="quantized GGUF",
        quantization=str(model_artifact["quantization"]),
        context_limit=llama_context_tokens_per_slot(profile),
        max_output_tokens=min(4096, llama_context_tokens_per_slot(profile)),
        license_identifier=str(license_value["identifier"]),
        license_notes=f"Source repository: {license_value['source_repository']}",
        code_revision=code_revision,
        artifacts=(
            ArtifactDigest(
                artifact_kind="model_weights",
                artifact_uri=str(model_artifact["url"]),
                content_hash=model_hash,
            ),
            ArtifactDigest(
                artifact_kind="model_manifest",
                artifact_uri=f"repo:{model_path.relative_to(PROJECT_ROOT).as_posix()}",
                content_hash=_file_sha256(model_path),
            ),
            ArtifactDigest(
                artifact_kind="serving_engine_manifest",
                artifact_uri=f"repo:{engine_path.relative_to(PROJECT_ROOT).as_posix()}",
                content_hash=_file_sha256(engine_path),
            ),
            ArtifactDigest(
                artifact_kind="environment_template",
                artifact_uri=f"repo:{template_path.relative_to(PROJECT_ROOT).as_posix()}",
                content_hash=_file_sha256(template_path),
            ),
            *tuple(
                ArtifactDigest(
                    artifact_kind=f"serving_engine_{artifact['role']}",
                    artifact_uri=str(artifact["url"]),
                    content_hash=str(artifact["sha256"]),
                )
                for artifact in engine_artifacts
            ),
            ArtifactDigest(
                artifact_kind="provider_adapter_source",
                artifact_uri="repo:mlsys/serving/openai_compatible.py",
                content_hash=_file_sha256(
                    PROJECT_ROOT / "mlsys" / "serving" / "openai_compatible.py"
                ),
            ),
            ArtifactDigest(
                artifact_kind="benchmark_harness_source",
                artifact_uri="repo:evals/inference_benchmark.py",
                content_hash=_file_sha256(
                    PROJECT_ROOT / "evals" / "inference_benchmark.py"
                ),
            ),
            ArtifactDigest(
                artifact_kind="benchmark_runner_source",
                artifact_uri="repo:evals/inference_runner.py",
                content_hash=_file_sha256(Path(__file__).resolve()),
            ),
        ),
    )
    environment = capture_live_environment(
        template=template,
        template_path=template_path,
        model=model,
        engine=engine,
        runtime_verification=runtime_verification,
    )
    provider = OpenAICompatibleProvider(
        base_url=settings.self_hosted_base_url,
        transport_model_id=str(model["alias"]),
        model_version_id=str(model["manifest_id"]),
        tokenizer_version_id=tokenizer_id,
        serving_engine="llama.cpp",
        serving_engine_version=f"{engine_tag}@{engine_commit}",
        serving_config_version=serving_config_version,
        provider_id=settings.provider_id,
        provider_adapter_version_id=provider_adapter_version_id,
        model_artifact_hash=model_hash,
        api_key=settings.self_hosted_api_key,
        max_context_tokens=llama_context_tokens_per_slot(profile),
        max_output_tokens=min(4096, llama_context_tokens_per_slot(profile)),
        health_path=str(engine_api["health_path"]),
        version_path="/props",
        completions_path=str(engine_api["chat_completions_path"]),
        expected_build_substring=f"{engine_tag}-{engine_commit[:8]}",
        runtime_attestation=runtime_attestation,
    )
    return provider, system_manifest, environment


def build_stage1_compatibility_baseline(
    *, code_revision: str
) -> tuple[DeterministicLocalProvider, InferenceSystemUnderTestManifest]:
    """Describe the Stage 1 fixed-response provider as a non-production baseline."""

    provider = DeterministicLocalProvider()
    source_path = PROJECT_ROOT / "mlsys" / "serving" / "deterministic.py"
    manifest = InferenceSystemUnderTestManifest(
        manifest_id="stage1-deterministic-compatibility-baseline-v1",
        provider_id=provider.provider_id,
        provider_class="local_test",
        execution_environment="local",
        model_version_id=provider.model_version_id,
        adapter_version_id=provider.adapter_version_id,
        provider_adapter_version_id=provider.provider_adapter_version_id,
        model_artifact_hash=None,
        model_artifact_hash_unavailable_reason=(
            "fixed-response test double has no learned weight artifact"
        ),
        tokenizer_version_id=provider.tokenizer_version_id,
        serving_config_version=provider.serving_config_version,
        serving_engine=provider.serving_engine,
        serving_engine_version=provider.serving_engine_version,
        upstream_model_id="havre/deterministic-local-test-double",
        upstream_revision=code_revision,
        architecture_family="fixed-response-test-double",
        parameter_count=None,
        parameter_count_unavailable_reason=(
            "fixed-response test double has no learned parameters"
        ),
        weights_format="none",
        precision="not-applicable",
        quantization=None,
        context_limit=32_768,
        max_output_tokens=4_096,
        license_identifier="project-internal-test-fixture",
        license_notes="Non-production behavioral compatibility baseline only.",
        code_revision=code_revision,
        artifacts=(
            ArtifactDigest(
                artifact_kind="provider_source",
                artifact_uri="repo:mlsys/serving/deterministic.py",
                content_hash=_file_sha256(source_path),
            ),
        ),
    )
    return provider, manifest


def capture_live_environment(
    *,
    template: dict[str, Any],
    template_path: Path,
    model: dict[str, Any],
    engine: dict[str, Any],
    runtime_verification: RuntimeVerification,
) -> InferenceEnvironmentManifest:
    """Capture non-content machine facts without starting or probing inference."""

    memory = psutil.virtual_memory()
    disk = psutil.disk_usage(str(PROJECT_ROOT.anchor))
    nvidia = _nvidia_environment()
    hardware: dict[str, str | int | float | bool | None] = {
        "machine": platform.machine() or None,
        "processor": platform.processor() or None,
        "physical_cpu_count": psutil.cpu_count(logical=False),
        "logical_cpu_count": psutil.cpu_count(logical=True),
        "ram_total_bytes": int(memory.total),
        "ram_available_bytes_before_run": int(memory.available),
        "benchmark_volume_free_bytes_before_run": int(disk.free),
    }
    software: dict[str, str | int | float | bool | None] = {
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "operating_system": platform.system(),
        "operating_system_release": platform.release(),
        "operating_system_version": platform.version(),
        "psutil": psutil.__version__,
        "benchmark_runner": BENCHMARK_RUNNER_VERSION,
        "environment_template_hash": _file_sha256(template_path),
        "model_manifest_id": str(model["manifest_id"]),
        "serving_engine_manifest_id": str(engine["manifest_id"]),
    }
    serving = template.get("serving")
    power_mode, power_mode_source = _power_mode()
    return capture_environment_manifest(
        runtime_verification=runtime_verification,
        hardware=hardware,
        software=software,
        accelerator=nvidia,
        network_topology=(
            f"loopback {serving.get('base_url')}"
            if isinstance(serving, dict)
            else "loopback-local"
        ),
        power_mode=power_mode,
        measurement_sources={
            "host": "python-platform-and-psutil",
            "accelerator": (
                "nvidia-smi"
                if nvidia.get("status") == "measured"
                else str(nvidia.get("reason"))
            ),
            "environment_template": _file_sha256(template_path),
            "power_mode": power_mode_source,
        },
    )


def _resolve_runtime_child(relative_path: str) -> Path:
    path = (RUNTIME_ROOT / relative_path).resolve()
    if path == RUNTIME_ROOT or RUNTIME_ROOT not in path.parents:
        raise ValueError("runtime state path escaped .runtime/stage3")
    return path


def _verify_file(path: Path, *, expected_hash: str, expected_size: int | None = None) -> None:
    if not path.is_file():
        raise ValueError(f"verified runtime artifact is missing: {path}")
    if expected_size is not None and path.stat().st_size != expected_size:
        raise ValueError(f"runtime artifact size mismatch: {path}")
    if _file_sha256(path) != expected_hash:
        raise ValueError(f"runtime artifact hash mismatch: {path}")


def _verify_active_runtime(
    *,
    model: dict[str, Any],
    model_manifest_path: Path,
    engine: dict[str, Any],
    engine_manifest_path: Path,
) -> tuple[RuntimeVerification, RuntimeAttestation]:
    """Bind benchmark identity to the shared production serving attestation."""

    attestation = attest_active_runtime(
        runtime_root=RUNTIME_ROOT,
        runtime_state_path=RUNTIME_STATE_PATH,
        runtime_pid_path=RUNTIME_PID_PATH,
        model_manifest_path=model_manifest_path,
        engine_manifest_path=engine_manifest_path,
    )
    verification = RuntimeVerification(
        status="verified",
        runtime_state_hash=attestation.runtime_state_hash,
        server_executable_hash=attestation.server_executable_hash,
        model_artifact_hash=attestation.model_artifact_hash,
        server_pid=attestation.server_pid,
        process_executable_hash=attestation.process_executable_hash,
        launch_arguments_hash=attestation.launch_arguments_hash,
        launch_configuration_verified=True,
        request_logging_disabled=True,
        runtime_attestation_id=attestation.attestation_id,
        runtime_attestation_hash=attestation.attestation_hash,
        process_started_at=attestation.process_started_at,
        engine_manifest_hash=attestation.engine_manifest_hash,
        model_manifest_hash=attestation.model_manifest_hash,
        server_executable_path_hash=attestation.server_executable_path_hash,
        model_path_hash=attestation.model_path_hash,
        model_size_bytes=attestation.model_size_bytes,
        loaded_model_alias=attestation.loaded_model_alias,
    )
    return verification, attestation


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise ValueError(f"cannot read {label} at {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _power_mode() -> tuple[str | None, str]:
    if platform.system() != "Windows":
        return None, "power_mode_collection_not_implemented_for_this_platform"
    try:
        completed = subprocess.run(
            ["powercfg", "/getactivescheme"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None, "windows_powercfg_query_failed"
    match = re.search(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        completed.stdout,
    )
    if completed.returncode != 0 or match is None:
        return None, "windows_powercfg_query_failed"
    return f"windows-power-scheme:{match.group(0).lower()}", "windows-powercfg-guid"


def _nvidia_environment() -> dict[str, str | int | float | bool | None]:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return {"status": "unavailable", "reason": "nvidia_smi_not_available"}
    try:
        completed = subprocess.run(
            [
                executable,
                "--query-gpu=name,memory.total,driver_version",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            creationflags=(
                subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
            ),
        )
    except (OSError, subprocess.SubprocessError):
        return {"status": "unavailable", "reason": "nvidia_smi_query_failed"}
    if completed.returncode != 0:
        return {"status": "unavailable", "reason": "nvidia_smi_query_failed"}
    rows = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if not rows:
        return {"status": "unavailable", "reason": "nvidia_device_not_reported"}
    parsed = [[part.strip() for part in row.split(",")] for row in rows]
    if any(len(row) != 3 for row in parsed):
        return {"status": "unavailable", "reason": "nvidia_smi_output_invalid"}
    try:
        memory_bytes = sum(float(row[1]) * 1024 * 1024 for row in parsed)
    except ValueError:
        return {"status": "unavailable", "reason": "nvidia_smi_output_invalid"}
    return {
        "status": "measured",
        "gpu_count": len(parsed),
        "gpu_names": " | ".join(row[0] for row in parsed),
        "vram_total_bytes": memory_bytes,
        "driver_versions": " | ".join(sorted({row[2] for row in parsed})),
    }


def controlled_comparison_workload(
    workload: InferenceWorkloadManifest,
) -> InferenceWorkloadManifest:
    """Counterbalance the same concurrency 1/2 workload across two order blocks."""

    source = {schedule.concurrency: schedule for schedule in workload.schedules}
    serial = source.get(1)
    batch = source.get(2)
    if serial is None or batch is None:
        raise ValueError("workload must define concurrency 1 and 2 schedules")
    payload = workload.model_dump(mode="json", exclude={"content_hash"})
    common_warmup = max(
        serial.warmup_repetitions_per_case,
        batch.warmup_repetitions_per_case,
    )
    common_measured = max(
        serial.measured_repetitions_per_case,
        batch.measured_repetitions_per_case,
    )
    payload["schedules"] = [
        InferenceBenchmarkSchedule(
            schedule_id="controlled-order-a-concurrency-1-v1",
            concurrency=1,
            warmup_repetitions_per_case=common_warmup,
            measured_repetitions_per_case=common_measured,
        ).model_dump(mode="json"),
        InferenceBenchmarkSchedule(
            schedule_id="controlled-order-a-concurrency-2-v1",
            concurrency=2,
            warmup_repetitions_per_case=common_warmup,
            measured_repetitions_per_case=common_measured,
        ).model_dump(mode="json"),
        InferenceBenchmarkSchedule(
            schedule_id="controlled-order-b-concurrency-2-v1",
            concurrency=2,
            warmup_repetitions_per_case=common_warmup,
            measured_repetitions_per_case=common_measured,
        ).model_dump(mode="json"),
        InferenceBenchmarkSchedule(
            schedule_id="controlled-order-b-concurrency-1-v1",
            concurrency=1,
            warmup_repetitions_per_case=common_warmup,
            measured_repetitions_per_case=common_measured,
        ).model_dump(mode="json"),
    ]
    payload["description"] = (
        str(payload["description"])
        + " Controlled comparison varies only requested concurrency 1 versus 2 on one pinned server and counterbalances schedule order across two blocks."
    )
    return InferenceWorkloadManifest.model_validate(payload)


def validate_approved_controlled_workload(
    workload: InferenceWorkloadManifest,
) -> InferenceWorkloadManifest:
    """Revalidate the sole synthetic workload allowed in live report storage."""

    workload = InferenceWorkloadManifest.model_validate(
        workload.model_dump(mode="json")
    )
    if workload.content_hash != APPROVED_CONTROLLED_WORKLOAD_CONTENT_HASH:
        raise ValueError("only the approved controlled Stage 3 workload is allowed")
    return workload


async def run_live_inference_benchmark(
    *,
    settings: Settings,
    output_directory: Path,
    code_revision: str,
    workload_path: Path = DEFAULT_WORKLOAD_PATH,
    environment_template_path: Path = DEFAULT_ENVIRONMENT_TEMPLATE_PATH,
    baseline_provider: ModelProvider | None = None,
    baseline_manifest: InferenceSystemUnderTestManifest | None = None,
    persistence: InferenceBenchmarkPersistence | None = None,
    resource_collector: ResourceCollector | None = None,
    provider_factory: Callable[
        [],
        tuple[
            ModelProvider,
            InferenceSystemUnderTestManifest,
            InferenceEnvironmentManifest,
        ],
    ]
    | None = None,
) -> tuple[InferenceSystemBenchmarkReport, InferenceCompatibilityReport]:
    """Run against a live pinned server and publish immutable report files."""

    output_directory = output_directory.resolve()
    ignored_report_root = (PROJECT_ROOT / "var").resolve()
    if (
        output_directory == ignored_report_root
        or ignored_report_root not in output_directory.parents
    ):
        raise ValueError("benchmark output directory must be a child of ignored var/")
    if output_directory.exists():
        raise BenchmarkOutputExists(
            f"benchmark output directory already exists: {output_directory}"
        )
    if workload_path.resolve() != DEFAULT_WORKLOAD_PATH.resolve():
        raise ValueError(
            "Stage 3 live benchmark accepts only the checked-in reviewed workload"
        )
    approved_workload = load_workload_manifest(workload_path)
    if approved_workload.content_hash != APPROVED_WORKLOAD_CONTENT_HASH:
        raise ValueError("checked-in Stage 3 workload hash is not approved")
    workload = controlled_comparison_workload(approved_workload)
    workload = validate_approved_controlled_workload(workload)
    if provider_factory is None:
        provider, system_manifest, environment = build_live_benchmark_inputs(
            settings=settings,
            code_revision=code_revision,
            environment_template_path=environment_template_path,
        )
    else:
        provider, system_manifest, environment = provider_factory()
    owns_baseline = False
    if baseline_provider is None and baseline_manifest is None:
        baseline_provider, baseline_manifest = build_stage1_compatibility_baseline(
            code_revision=code_revision
        )
        owns_baseline = True
    try:
        systems, compatibility = await run_inference_benchmark(
            provider=provider,
            system_under_test=system_manifest,
            workload=workload,
            environment=environment,
            benchmark_code_revision=code_revision,
            baseline_provider=baseline_provider,
            baseline_manifest=baseline_manifest,
            resource_collector=(
                resource_collector or PsutilNvidiaResourceCollector()
            ),
        )
        output_directory.parent.mkdir(parents=True, exist_ok=True)
        pending_directory = (
            output_directory.parent
            / f".{output_directory.name}.pending-{uuid7()}"
        )
        pending_directory.mkdir(exist_ok=False)
        try:
            workload_path_out = pending_directory / "inference-workload.json"
            baseline_path_out = pending_directory / "inference-baseline-system.json"
            workload_path_out.write_text(
                workload.model_dump_json(indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            if baseline_manifest is None:
                raise RuntimeError("benchmark baseline manifest was not resolved")
            baseline_path_out.write_text(
                baseline_manifest.model_dump_json(indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            write_report_pair(
                system_report=systems,
                compatibility_report=compatibility,
                system_output_path=pending_directory / "inference-systems.json",
                compatibility_output_path=(
                    pending_directory / "inference-compatibility.json"
                ),
            )
            pending_directory.rename(output_directory)
        except Exception:
            if pending_directory.is_dir():
                shutil.rmtree(pending_directory)
            raise
        if persistence is not None:
            persistence.persist_inference_benchmark_reports(
                system_report=systems,
                compatibility_report=compatibility,
                workload_manifest=workload,
            )
        return systems, compatibility
    finally:
        try:
            await provider.aclose()
        finally:
            if owns_baseline and baseline_provider is not None:
                await baseline_provider.aclose()


def git_head_revision(
    project_root: Path = PROJECT_ROOT, *, require_clean: bool = True
) -> str:
    revision = ""
    completed = None
    for _attempt in range(3):
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            creationflags=(
                subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
            ),
        )
        revision = completed.stdout.strip()
        if completed.returncode == 0 and len(revision) == 40:
            break
    assert completed is not None
    if completed.returncode != 0 or len(revision) != 40:
        raise RuntimeError("cannot determine the exact benchmark code revision")
    if require_clean:
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=normal"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            creationflags=(
                subprocess.CREATE_NO_WINDOW
                if platform.system() == "Windows"
                else 0
            ),
        )
        if status.returncode != 0 or status.stdout.strip():
            raise RuntimeError(
                "benchmark source tree is not clean"
            )
    return revision


def source_snapshot_revision(project_root: Path = PROJECT_ROOT) -> str:
    """Hash the complete benchmark execution source, including new files.

    This is the exact, reproducible alternative to a commit ID when repository
    policy intentionally leaves an owner checkpoint uncommitted. Generated
    reports and narrative documentation are deliberately outside this closure:
    they do not execute, and including a report in the source hash of the next
    run would make identical back-to-back runs identify different systems.
    """

    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=project_root,
        capture_output=True,
        timeout=30,
        check=False,
        creationflags=(
            subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
        ),
    )
    if listed.returncode != 0:
        raise RuntimeError("cannot enumerate the benchmark source snapshot")
    source_roots = {
        "apps",
        "companion",
        "contracts",
        "db",
        "evals",
        "identity",
        "mlsys",
        "scripts",
        "services",
        "tests",
    }
    source_files = {".env.example", "pyproject.toml", "requirements.lock"}
    relative_paths = []
    for item in listed.stdout.split(b"\0"):
        if not item:
            continue
        relative = item.decode("utf-8").replace("\\", "/")
        parts = relative.split("/")
        if relative in source_files or (
            parts[0] in source_roots
            and not relative.startswith("evals/reports/")
        ):
            relative_paths.append(relative)
    relative_paths.sort()
    if not relative_paths:
        raise RuntimeError("benchmark source snapshot is empty")
    digest = hashlib.sha256(b"HAVRE-benchmark-execution-source-v2\0")
    for relative in relative_paths:
        encoded = relative.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        path = project_root / Path(relative)
        if not path.is_file():
            digest.update(b"\0missing\0")
            continue
        digest.update(b"\0file\0")
        digest.update(path.stat().st_size.to_bytes(8, "big"))
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def committed_source_snapshot_revision(
    project_root: Path,
    revision: str,
) -> str:
    """Hash the execution-source closure stored at an exact Git revision.

    This links a content-addressed source snapshot to committed bytes without
    substituting the commit ID for the snapshot hash. It reads canonical commit
    blobs directly, so the result is independent of checkout line-ending and
    clean-filter configuration. Narrative documentation and generated reports
    remain outside the execution-source closure exactly as they are in
    :func:`source_snapshot_revision`.
    """

    if len(revision) != 40 or any(
        character not in "0123456789abcdef" for character in revision
    ):
        raise ValueError("committed source revision must be an exact Git commit ID")
    listed = subprocess.run(
        ["git", "ls-tree", "-r", "-z", "--full-tree", revision],
        cwd=project_root,
        capture_output=True,
        timeout=30,
        check=False,
        creationflags=(
            subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
        ),
    )
    if listed.returncode != 0 or not listed.stdout:
        raise RuntimeError("cannot read the committed benchmark source snapshot")
    source_roots = {
        "apps",
        "companion",
        "contracts",
        "db",
        "evals",
        "identity",
        "mlsys",
        "scripts",
        "services",
        "tests",
    }
    source_files = {".env.example", "pyproject.toml", "requirements.lock"}
    relative_paths = []
    for raw_entry in listed.stdout.split(b"\0"):
        if not raw_entry:
            continue
        metadata, separator, raw_path = raw_entry.partition(b"\t")
        fields = metadata.split()
        if separator != b"\t" or len(fields) != 3 or fields[1] != b"blob":
            continue
        relative = raw_path.decode("utf-8").replace("\\", "/")
        parts = relative.split("/")
        if relative in source_files or (
            parts[0] in source_roots
            and not relative.startswith("evals/reports/")
        ):
            relative_paths.append(relative)
    relative_paths.sort()
    if not relative_paths:
        raise RuntimeError("committed benchmark source snapshot is empty")
    digest = hashlib.sha256(b"HAVRE-benchmark-execution-source-v2\0")
    for relative in relative_paths:
        committed = subprocess.run(
            ["git", "show", f"{revision}:{relative}"],
            cwd=project_root,
            capture_output=True,
            timeout=30,
            check=False,
            creationflags=(
                subprocess.CREATE_NO_WINDOW
                if platform.system() == "Windows"
                else 0
            ),
        )
        if committed.returncode != 0:
            raise RuntimeError("cannot read a committed source file")
        encoded = relative.encode("utf-8")
        payload = committed.stdout
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(b"\0file\0")
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return f"sha256:{digest.hexdigest()}"


def current_source_revision(project_root: Path = PROJECT_ROOT) -> str:
    """Use clean HEAD when possible, otherwise an exact working-tree hash."""

    try:
        return git_head_revision(project_root, require_clean=True)
    except RuntimeError:
        return source_snapshot_revision(project_root)
