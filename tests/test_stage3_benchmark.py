from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from pydantic import ValidationError

from companion.hashing import content_hash
from companion.ids import uuid7
from evals.inference_benchmark import (
    BenchmarkManifestMismatch,
    BenchmarkOutputExists,
    capture_environment_manifest,
    load_workload_manifest,
    NullResourceCollector,
    run_inference_benchmark,
    write_report_pair,
)
from evals.inference_runner import (
    APPROVED_CONTROLLED_WORKLOAD_CONTENT_HASH,
    DEFAULT_ENVIRONMENT_TEMPLATE_PATH,
    PsutilNvidiaResourceCollector,
    build_live_benchmark_inputs,
    committed_source_snapshot_revision,
    controlled_comparison_workload,
    current_source_revision,
    git_head_revision,
    run_live_inference_benchmark,
    source_snapshot_revision,
    validate_approved_controlled_workload,
)
from mlsys.contracts import InferenceFailure, InferenceStreamEvent
from mlsys.contracts.inference import InferenceRequest
from mlsys.contracts.inference_benchmark import (
    ArtifactDigest,
    InferenceCompatibilityReport,
    InferenceSystemBenchmarkReport,
    InferenceSystemUnderTestManifest,
    InferenceWorkloadManifest,
    RuntimeVerification,
)
from mlsys.serving import DeterministicLocalProvider, RuntimeAttestation
from scripts.export_contract_schemas import CONTRACTS
from services.api.cli import _parser
from services.api.settings import Settings


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKLOAD_PATH = PROJECT_ROOT / "evals" / "fixtures" / "inference_workload_v1.json"


def run_benchmark_fs_worker(
    *,
    owned_root: Path,
    timeout_seconds: float = 20,
    simulate_block_seconds: float = 0,
    operation: str = "run",
) -> dict[str, object]:
    command = [
        sys.executable,
        "-m",
        "tests.stage3_benchmark_fs_worker",
        operation,
        "--owned-root",
        str(owned_root),
    ]
    if simulate_block_seconds:
        command.extend(("--simulate-block-seconds", str(simulate_block_seconds)))
    process = subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as timeout_error:
        process.kill()
        stdout, stderr = process.communicate(timeout=5)
        cleanup_process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "tests.stage3_benchmark_fs_worker",
                "cleanup",
                "--owned-root",
                str(owned_root),
            ],
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            cleanup_stdout, cleanup_stderr = cleanup_process.communicate(timeout=10)
            cleanup_exit: int | str = cleanup_process.returncode
        except subprocess.TimeoutExpired:
            cleanup_process.kill()
            cleanup_stdout, cleanup_stderr = cleanup_process.communicate(timeout=5)
            cleanup_exit = "hard-timeout-after-10s"
        raise AssertionError(
            "Stage 3 var-backed benchmark filesystem worker exceeded the "
            f"{timeout_seconds}s hard timeout; owned_root={owned_root}; "
            f"worker_stdout={stdout!r}; worker_stderr={stderr!r}; "
            f"cleanup_exit={cleanup_exit}; cleanup_stdout={cleanup_stdout!r}; "
            f"cleanup_stderr={cleanup_stderr!r}"
        ) from timeout_error
    if process.returncode != 0:
        raise AssertionError(
            "Stage 3 var-backed benchmark filesystem worker failed; "
            f"owned_root={owned_root}; exit={process.returncode}; "
            f"stdout={stdout!r}; stderr={stderr!r}"
        )
    records = [json.loads(line) for line in stdout.splitlines() if line.strip()]
    return next(item for item in records if item.get("kind") == "result")


def benchmark_runtime_attestation() -> RuntimeAttestation:
    model = json.loads((
        PROJECT_ROOT / "mlsys" / "serving" / "manifests" / "qwen3-8b-q4-k-m.json"
    ).read_text(encoding="utf-8"))
    engine = json.loads((
        PROJECT_ROOT / "mlsys" / "serving" / "manifests" / "llama-cpp-b10405-win-cuda-12.4-x64.json"
    ).read_text(encoding="utf-8"))
    now = "2026-08-14T00:00:00Z"
    revision = model["upstream"]["revision"]
    payload = {
        "schema_version": 1,
        "attestation_id": "benchmark-runtime:4242:1",
        "runtime_state_hash": "sha256:" + "1" * 64,
        "engine_manifest_hash": "sha256:" + "2" * 64,
        "model_manifest_hash": "sha256:" + "3" * 64,
        "server_executable_hash": "sha256:" + "4" * 64,
        "server_executable_path_hash": "sha256:" + "5" * 64,
        "process_executable_hash": "sha256:" + "4" * 64,
        "model_artifact_hash": model["artifact"]["sha256"],
        "model_path_hash": "sha256:" + "6" * 64,
        "model_size_bytes": model["artifact"]["size_bytes"],
        "server_pid": 4242,
        "process_started_at": now,
        "launch_arguments_hash": "sha256:" + "7" * 64,
        "base_url": engine["api"]["base_url"],
        "serving_engine": "llama.cpp",
        "serving_engine_version": f"{engine['upstream']['release_tag']}@{engine['upstream']['commit']}",
        "serving_config_version": content_hash(model["serving_profile"]),
        "model_version_id": model["manifest_id"],
        "tokenizer_version_id": f"{model['upstream']['repository']}@{revision}:embedded-gguf-tokenizer",
        "loaded_model_alias": model["alias"],
        "loopback_only": True,
        "request_logging_disabled": True,
        "web_ui_disabled": True,
        "attested_at": now,
    }
    return RuntimeAttestation.model_validate({
        **payload, "attestation_hash": content_hash(payload)
    })


def deterministic_manifest(
    **overrides: object,
) -> InferenceSystemUnderTestManifest:
    values: dict[str, object] = {
        "manifest_id": "deterministic-local-benchmark-v1",
        "provider_id": DeterministicLocalProvider.provider_id,
        "provider_class": "local_test",
        "execution_environment": "local",
        "model_version_id": DeterministicLocalProvider.model_version_id,
        "adapter_version_id": DeterministicLocalProvider.adapter_version_id,
        "provider_adapter_version_id": (
            DeterministicLocalProvider.provider_adapter_version_id
        ),
        "model_artifact_hash": None,
        "model_artifact_hash_unavailable_reason": (
            "deterministic test double has no learned weight artifact"
        ),
        "tokenizer_version_id": DeterministicLocalProvider.tokenizer_version_id,
        "serving_config_version": (
            DeterministicLocalProvider.serving_config_version
        ),
        "serving_engine": DeterministicLocalProvider.serving_engine,
        "serving_engine_version": (
            DeterministicLocalProvider.serving_engine_version
        ),
        "upstream_model_id": "havre/deterministic-fixture",
        "upstream_revision": "deterministic-fixture-v1",
        "architecture_family": "fixed-response-test-double",
        "parameter_count": None,
        "parameter_count_unavailable_reason": (
            "deterministic test double has no learned parameters"
        ),
        "weights_format": "none",
        "precision": "not-applicable",
        "quantization": None,
        "context_limit": 32_768,
        "max_output_tokens": 4_096,
        "license_identifier": "project-internal-test-fixture",
        "license_notes": "Not a learned model or production model candidate.",
        "code_revision": "a" * 40,
        "artifacts": (
            ArtifactDigest(
                artifact_kind="provider_source",
                artifact_uri="repo:mlsys/serving/deterministic.py",
                content_hash="sha256:" + "1" * 64,
            ),
        ),
    }
    values.update(overrides)
    return InferenceSystemUnderTestManifest(**values)


def short_workload() -> InferenceWorkloadManifest:
    payload = load_workload_manifest(WORKLOAD_PATH).model_dump(
        mode="json", exclude={"content_hash"}
    )
    payload["schedules"] = [
        {
            "schedule_id": "throughput-test-v1",
            "concurrency": 2,
            "warmup_repetitions_per_case": 0,
            "measured_repetitions_per_case": 1,
        }
    ]
    return InferenceWorkloadManifest.model_validate(payload)


class InterruptedProvider(DeterministicLocalProvider):
    async def stream(
        self, request: InferenceRequest
    ) -> AsyncIterator[InferenceStreamEvent]:
        yield InferenceStreamEvent(
            event="response_started",
            sequence_number=0,
            inference_response_id=uuid7(),
            inference_request_id=request.inference_request_id,
            request_id=request.request_id,
            trace_id=request.trace_id,
        )


class PostTerminalProvider(DeterministicLocalProvider):
    async def stream(
        self, request: InferenceRequest
    ) -> AsyncIterator[InferenceStreamEvent]:
        response = await self.generate(request)
        common = {
            "inference_response_id": response.inference_response_id,
            "inference_request_id": request.inference_request_id,
            "request_id": request.request_id,
            "trace_id": request.trace_id,
        }
        yield InferenceStreamEvent(
            event="response_started", sequence_number=0, **common
        )
        yield InferenceStreamEvent(
            event="output_delta",
            sequence_number=1,
            delta=response.output_parts[0],
            **common,
        )
        yield InferenceStreamEvent(
            event="response_completed",
            sequence_number=2,
            response=response,
            **common,
        )
        yield InferenceStreamEvent(
            event="output_delta",
            sequence_number=3,
            delta=response.output_parts[0],
            **common,
        )


class FailedStreamProvider(DeterministicLocalProvider):
    failure_provider_id = DeterministicLocalProvider.provider_id

    async def stream(
        self, request: InferenceRequest
    ) -> AsyncIterator[InferenceStreamEvent]:
        response_id = uuid7()
        common = {
            "inference_response_id": response_id,
            "inference_request_id": request.inference_request_id,
            "request_id": request.request_id,
            "trace_id": request.trace_id,
        }
        yield InferenceStreamEvent(
            event="response_started", sequence_number=0, **common
        )
        yield InferenceStreamEvent(
            event="response_failed",
            sequence_number=1,
            failure=InferenceFailure(
                inference_request_id=request.inference_request_id,
                request_id=request.request_id,
                trace_id=request.trace_id,
                provider_id=self.failure_provider_id,
                provider_class="local_test",
                code="model_unavailable",
                retryable=True,
                safe_message="synthetic safe failure",
                provider_error_code="MODEL_LOADING",
            ),
            **common,
        )


class WrongProviderFailedStreamProvider(FailedStreamProvider):
    failure_provider_id = "wrong-provider"


class RecordingBenchmarkPersistence:
    def __init__(self) -> None:
        self.workload_content_hash: str | None = None

    def persist_inference_benchmark_reports(
        self, *, system_report, compatibility_report, workload_manifest
    ) -> None:
        approved = validate_approved_controlled_workload(workload_manifest)
        if system_report.workload_content_hash != approved.content_hash:
            raise AssertionError("systems report did not bind to persisted workload")
        if compatibility_report.workload_content_hash != approved.content_hash:
            raise AssertionError("compatibility report did not bind to persisted workload")
        self.workload_content_hash = approved.content_hash


class Stage3BenchmarkContractTests(unittest.TestCase):
    def test_reviewed_workload_is_content_hashed_and_covers_required_shapes(self) -> None:
        workload = load_workload_manifest(WORKLOAD_PATH)

        self.assertEqual(
            workload.content_hash,
            "sha256:46f5a39afe751ec7378a586e08c89f3304362b7cb06a8a301f90795f9a6c9712",
        )
        self.assertFalse(workload.binding_evaluation)
        self.assertEqual(
            {case.workload_class for case in workload.cases},
            {
                "scene_short",
                "chat_standard",
                "reflection_long",
                "extraction_structured",
            },
        )
        self.assertTrue(any(item.concurrency > 1 for item in workload.schedules))
        self.assertIn(
            "not an active Scene",
            workload.description
            + " "
            + " ".join(
                message.text for case in workload.cases for message in case.messages
            ),
        )
        reflection = next(
            case for case in workload.cases
            if case.workload_class == "reflection_long"
        )
        self.assertGreaterEqual(
            sum(len(message.text) for message in reflection.messages),
            7_500,
        )
        self.assertEqual(reflection.response_expectation, "json_object")

    def test_content_hash_rejects_tampered_workload(self) -> None:
        workload = load_workload_manifest(WORKLOAD_PATH)
        payload = workload.model_dump(mode="json")
        payload["description"] = "tampered"

        with self.assertRaises(ValidationError):
            InferenceWorkloadManifest.model_validate(payload)

    def test_system_manifest_rejects_duplicate_artifact_references(self) -> None:
        artifact = ArtifactDigest(
            artifact_kind="provider_source",
            artifact_uri="repo:first",
            content_hash="sha256:" + "1" * 64,
        )
        with self.assertRaises(ValidationError):
            deterministic_manifest(artifacts=(artifact, artifact.model_copy()))

    def test_system_manifest_identity_excludes_run_local_creation_time(self) -> None:
        first_time = datetime(2026, 8, 13, 11, 0, tzinfo=UTC)
        first = deterministic_manifest(created_at=first_time)
        second = deterministic_manifest(created_at=first_time + timedelta(minutes=5))

        self.assertNotEqual(first.created_at, second.created_at)
        self.assertEqual(first.manifest_id, second.manifest_id)
        self.assertEqual(first.content_hash, second.content_hash)

    def test_stage3_benchmark_contracts_are_schema_exported(self) -> None:
        self.assertEqual(
            {
                "inference-benchmark-report-v1",
                "inference-compatibility-report-v1",
                "inference-system-manifest-v1",
                "inference-workload-manifest-v1",
            }
            - set(CONTRACTS),
            set(),
        )

    def test_cli_exposes_isolated_inference_benchmark_outputs(self) -> None:
        args = _parser().parse_args(
            [
                "benchmark-inference",
                "--output-directory",
                "var/benchmarks/test-live-run",
            ]
        )
        self.assertEqual(args.command, "benchmark-inference")
        self.assertEqual(
            args.output_directory,
            Path("var/benchmarks/test-live-run"),
        )
        self.assertFalse(hasattr(args, "code_revision"))

    def test_controlled_comparison_changes_only_schedule_and_description(self) -> None:
        workload = load_workload_manifest(WORKLOAD_PATH)
        comparison = controlled_comparison_workload(workload)

        self.assertEqual(
            [item.concurrency for item in comparison.schedules], [1, 2, 2, 1]
        )
        self.assertEqual(
            {item.warmup_repetitions_per_case for item in comparison.schedules},
            {1},
        )
        self.assertEqual(
            {item.measured_repetitions_per_case for item in comparison.schedules},
            {2},
        )
        self.assertEqual(comparison.cases, workload.cases)
        self.assertEqual(comparison.timeout_ms, workload.timeout_ms)
        self.assertIn("varies only requested concurrency", comparison.description)
        self.assertNotEqual(comparison.content_hash, workload.content_hash)
        self.assertEqual(
            comparison.content_hash, APPROVED_CONTROLLED_WORKLOAD_CONTENT_HASH
        )
        self.assertEqual(validate_approved_controlled_workload(comparison), comparison)
        with self.assertRaises(ValueError):
            validate_approved_controlled_workload(workload)

    def test_checked_in_manifests_map_to_exact_live_contract(self) -> None:
        settings = Settings.from_env(require_owner_api_token=False).model_copy(
            update={
                "provider_id": "self-hosted-openai-compatible",
                "self_hosted_base_url": "http://127.0.0.1:8080",
                "self_hosted_model_manifest": (
                    PROJECT_ROOT
                    / "mlsys"
                    / "serving"
                    / "manifests"
                    / "qwen3-8b-q4-k-m.json"
                ),
                "self_hosted_engine_manifest": (
                    PROJECT_ROOT
                    / "mlsys"
                    / "serving"
                    / "manifests"
                    / "llama-cpp-b10405-win-cuda-12.4-x64.json"
                ),
            }
        )
        with patch(
            "evals.inference_runner._verify_active_runtime",
            return_value=(
                RuntimeVerification(
                    status="unavailable",
                    unavailable_reason="patched contract mapping test",
                ),
                benchmark_runtime_attestation(),
            ),
        ), patch("evals.inference_runner.current_source_revision", return_value="2" * 40):
            provider, manifest, environment = build_live_benchmark_inputs(
                settings=settings,
                code_revision="2" * 40,
                environment_template_path=DEFAULT_ENVIRONMENT_TEMPLATE_PATH,
            )

        self.assertEqual(provider.max_context_tokens, 4096)
        self.assertEqual(manifest.context_limit, provider.max_context_tokens)
        self.assertEqual(manifest.provider_id, "self-hosted-openai-compatible")
        self.assertEqual(
            manifest.model_artifact_hash,
            "sha256:d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785",
        )
        self.assertEqual(
            manifest.provider_adapter_version_id,
            provider.provider_adapter_version_id,
        )
        self.assertEqual(manifest.serving_engine, "llama.cpp")
        self.assertIn("psutil", environment.software)
        self.assertEqual(environment.runtime_verification.status, "unavailable")
        self.assertEqual(
            environment.network_topology,
            "loopback http://127.0.0.1:8080",
        )
        self.assertGreaterEqual(len(manifest.artifacts), 8)

    def test_resource_collector_reports_null_nvidia_with_reason(self) -> None:
        async def collect():
            collector = PsutilNvidiaResourceCollector(
                nvidia_smi="missing-nvidia-smi"
            )
            with patch("evals.inference_runner.subprocess.run", side_effect=OSError):
                handle = await collector.begin_sample()
                snapshot = await collector.finish_sample(handle)
                await collector.aclose()
                return snapshot

        snapshot = __import__("asyncio").run(collect())
        self.assertTrue(
            snapshot.cpu_percent.value is not None
            or snapshot.cpu_percent.unavailable_reason
            == "psutil_cpu_time_resolution_insufficient"
        )
        self.assertIsNotNone(snapshot.ram_used_bytes.value)
        self.assertIsNone(snapshot.gpu_utilization_percent.value)
        self.assertEqual(
            snapshot.gpu_utilization_percent.unavailable_reason,
            "nvidia_smi_query_failed_or_no_nvidia_device",
        )
        self.assertIsNone(snapshot.vram_peak_used_bytes.value)

    def test_git_revision_is_exact(self) -> None:
        self.assertRegex(
            git_head_revision(PROJECT_ROOT, require_clean=False),
            r"^[0-9a-f]{40}$",
        )

    def test_dirty_source_tree_has_an_exact_snapshot_revision(self) -> None:
        self.assertRegex(
            current_source_revision(PROJECT_ROOT),
            r"^(?:[0-9a-f]{40}|sha256:[0-9a-f]{64})$",
        )

    def test_source_snapshot_excludes_generated_reports_and_narrative_docs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            (root / "companion").mkdir()
            (root / "docs").mkdir()
            (root / "evals" / "reports").mkdir(parents=True)
            source = root / "companion" / "service.py"
            document = root / "docs" / "STATE.md"
            report = root / "evals" / "reports" / "run.json"
            source.write_text("version = 1\n", encoding="utf-8")
            document.write_text("draft\n", encoding="utf-8")
            report.write_text("{}\n", encoding="utf-8")
            listing = SimpleNamespace(
                returncode=0,
                stdout=(
                    b"companion/service.py\0docs/STATE.md\0"
                    b"evals/reports/run.json\0"
                ),
            )
            with patch("evals.inference_runner.subprocess.run", return_value=listing):
                first = source_snapshot_revision(root)
                document.write_text("published\n", encoding="utf-8")
                report.write_text('{"result":"new"}\n', encoding="utf-8")
                self.assertEqual(first, source_snapshot_revision(root))
                source.write_text("version = 2\n", encoding="utf-8")
                self.assertNotEqual(first, source_snapshot_revision(root))

    def test_committed_source_snapshot_uses_exact_archived_source_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            tree = SimpleNamespace(
                returncode=0,
                stdout=(
                    b"100644 blob " + b"a" * 40 + b"\tcompanion/service.py\0"
                    b"100644 blob " + b"b" * 40 + b"\tdocs/STATE.md\0"
                    b"100644 blob " + b"c" * 40 + b"\tevals/reports/run.json\0"
                ),
            )
            filtered = SimpleNamespace(returncode=0, stdout=b"version = 1\n")
            with (
                patch(
                    "evals.inference_runner.subprocess.run",
                    side_effect=(tree, filtered),
                ),
                patch(
                    "evals.inference_runner.platform.system",
                    return_value="Windows",
                ),
            ):
                committed = committed_source_snapshot_revision(root, "a" * 40)
            (root / "companion").mkdir()
            (root / "companion" / "service.py").write_bytes(b"version = 1\n")
            listing = SimpleNamespace(
                returncode=0,
                stdout=(
                    b"companion/service.py\0docs/STATE.md\0"
                    b"evals/reports/run.json\0"
                ),
            )
            with (
                patch("evals.inference_runner.subprocess.run", return_value=listing),
                patch(
                    "evals.inference_runner.platform.system",
                    return_value="Windows",
                ),
            ):
                working = source_snapshot_revision(root)
            self.assertEqual(committed, working)


class Stage3BenchmarkHarnessTests(unittest.IsolatedAsyncioTestCase):
    async def test_isolated_live_runner_writes_under_ignored_var_and_adds_baseline(self) -> None:
        owned_root = (
            PROJECT_ROOT / "var" / f".stage3-benchmark-fs-test-{uuid4()}"
        )
        result = run_benchmark_fs_worker(owned_root=owned_root)
        if result.get("cleanup_complete") is True:
            raise AssertionError("run worker returned cleanup-only evidence")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["schedule_concurrency"], [1, 2, 2, 1])
        self.assertEqual(result["baseline_manifest_id"], (
            "stage1-deterministic-compatibility-baseline-v1"
        ))
        self.assertIs(result["files_present"], True)
        self.assertEqual(result["pending_path_count"], 0)
        self.assertIs(result["workload_hash_matches"], True)
        self.assertIs(result["persistence_called"], True)
        self.assertIs(result["owned_path_removed"], True)

    async def test_var_filesystem_worker_timeout_is_bounded_and_diagnostic(self) -> None:
        owned_root = (
            PROJECT_ROOT / "var" / f".stage3-benchmark-fs-test-{uuid4()}"
        )
        with self.assertRaisesRegex(
            AssertionError,
            r"hard timeout; owned_root=.*cleanup_exit=0",
        ):
            run_benchmark_fs_worker(
                owned_root=owned_root,
                timeout_seconds=0.2,
                simulate_block_seconds=60,
            )

    async def test_var_filesystem_worker_creates_missing_parent_var(self) -> None:
        owned_root = (
            PROJECT_ROOT / "var" / f".stage3-benchmark-fs-test-{uuid4()}"
        )
        result = run_benchmark_fs_worker(
            owned_root=owned_root,
            operation="selftest-missing-var",
        )
        self.assertIs(result["missing_parent_var_exercised"], True)
        self.assertIs(result["var_root_created"], True)
        self.assertIs(result["files_present"], True)
        self.assertEqual(result["pending_path_count"], 0)
        self.assertIs(result["persistence_called"], True)
        self.assertIs(result["owned_path_removed"], True)

    async def test_var_filesystem_cleanup_rejects_every_nonowned_path(self) -> None:
        protected_path = PROJECT_ROOT / "do-not-delete"
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "tests.stage3_benchmark_fs_worker",
                "cleanup",
                "--owned-root",
                str(protected_path),
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "one exact Stage 3 child of var/",
            completed.stderr,
        )

    async def test_var_filesystem_cleanup_rejects_reparse_boundaries(self) -> None:
        owned_root = (
            PROJECT_ROOT / "var" / f".stage3-benchmark-fs-test-{uuid4()}"
        )
        result = run_benchmark_fs_worker(
            owned_root=owned_root,
            operation="selftest-cleanup-boundaries",
        )
        self.assertIs(result["var_link_rejected"], True)
        self.assertIs(result["var_link_preserved"], True)
        self.assertIs(result["owned_link_rejected"], True)
        self.assertIs(result["owned_link_preserved"], True)
        self.assertIs(result["missing_cleanup_performed"], False)
        self.assertIs(result["missing_var_remained_absent"], True)
        self.assertIs(result["owned_path_removed"], True)

    async def test_live_runner_rejects_unignored_output_before_provider_creation(self) -> None:
        called = False

        def provider_factory():
            nonlocal called
            called = True
            raise AssertionError("provider must not be created")

        with self.assertRaises(ValueError):
            await run_live_inference_benchmark(
                settings=Settings.from_env(require_owner_api_token=False),
                output_directory=PROJECT_ROOT / "reports-not-ignored",
                code_revision="4" * 40,
                provider_factory=provider_factory,
            )
        self.assertFalse(called)

    async def test_real_typed_stream_produces_separate_immutable_reports(self) -> None:
        workload = load_workload_manifest(WORKLOAD_PATH)
        manifest = deterministic_manifest()
        environment = capture_environment_manifest(
            software={"test_runtime": "deterministic-provider"},
            measurement_sources={
                "python_runtime": "python-platform-and-os",
                "accelerator": "unavailable",
            },
        )

        systems, compatibility = await run_inference_benchmark(
            provider=DeterministicLocalProvider(),
            system_under_test=manifest,
            workload=workload,
            environment=environment,
            benchmark_code_revision="a" * 40,
            baseline_provider=DeterministicLocalProvider(),
            baseline_manifest=manifest,
        )

        self.assertEqual(systems.status, "completed")
        self.assertEqual(len(systems.warmup_samples), 4)
        self.assertEqual(len(systems.measured_samples), 16)
        self.assertTrue(all(sample.stream_event_count == 3 for sample in systems.measured_samples))
        self.assertTrue(all(not sample.warmup for sample in systems.measured_samples))
        self.assertTrue(all(sample.error is None for sample in systems.measured_samples))
        self.assertEqual({item.error_rate for item in systems.schedule_summaries}, {0.0})
        self.assertTrue(
            all(
                sample.resources.gpu_utilization_percent.value is None
                and sample.resources.gpu_utilization_percent.unavailable_reason
                == "no_reliable_resource_collector_configured"
                for sample in systems.measured_samples
            )
        )
        self.assertTrue(
            all(
                sample.tpot_ms is None
                and sample.unavailable_measurements["tpot_ms"]
                == "no_positive_visible_generation_interval"
                for sample in systems.measured_samples
            )
        )
        resource_metric_names = {
            metric.metric
            for summary in systems.schedule_summaries
            for metric in summary.metrics
            if metric.metric in {
                "cpu_percent",
                "ram_used_bytes",
                "gpu_utilization_percent",
                "vram_used_bytes",
                "vram_peak_used_bytes",
            }
        }
        self.assertEqual(
            resource_metric_names,
            {
                "cpu_percent",
                "ram_used_bytes",
                "gpu_utilization_percent",
                "vram_used_bytes",
                "vram_peak_used_bytes",
            },
        )

        self.assertFalse(compatibility.binding_evaluation)
        self.assertEqual(compatibility.gate_status, "not_evaluated")
        self.assertEqual(len(compatibility.case_results), 4)
        self.assertEqual(
            compatibility.candidate_manifest_content_hash,
            manifest.content_hash,
        )
        self.assertTrue(
            all(
                result.candidate_output_content_hash
                == result.baseline_output_content_hash
                for result in compatibility.case_results
            )
        )

        systems_json = systems.model_dump_json()
        compatibility_json = compatibility.model_dump_json()
        self.assertNotIn("Synthetic note:", systems_json)
        self.assertNotIn("Synthetic note:", compatibility_json)
        self.assertNotIn(DeterministicLocalProvider.output, systems_json)
        self.assertNotIn(DeterministicLocalProvider.output, compatibility_json)
        self.assertEqual(
            InferenceSystemBenchmarkReport.model_validate_json(systems_json).content_hash,
            systems.content_hash,
        )
        self.assertEqual(
            InferenceCompatibilityReport.model_validate_json(
                compatibility_json
            ).content_hash,
            compatibility.content_hash,
        )
        tampered_systems = json.loads(systems_json)
        tampered_systems["limitations"][0] = "tampered but structurally valid"
        with self.assertRaises(ValidationError):
            InferenceSystemBenchmarkReport.model_validate(tampered_systems)
        contradictory_revision = systems.model_dump(
            mode="json", exclude={"content_hash"}
        )
        contradictory_revision["benchmark_code_revision"] = "b" * 40
        with self.assertRaises(ValidationError):
            InferenceSystemBenchmarkReport.model_validate(contradictory_revision)
        contradictory_system_sample = systems.model_dump(
            mode="json", exclude={"content_hash"}
        )
        contradictory_system_sample["measured_samples"][0][
            "model_version_id"
        ] = "wrong-model-version"
        with self.assertRaises(ValidationError):
            InferenceSystemBenchmarkReport.model_validate(contradictory_system_sample)
        contradictory_nullable_adapter = systems.model_dump(
            mode="json", exclude={"content_hash"}
        )
        contradictory_nullable_adapter["measured_samples"][0][
            "adapter_version_id"
        ] = None
        with self.assertRaises(ValidationError):
            InferenceSystemBenchmarkReport.model_validate(
                contradictory_nullable_adapter
            )
        contradictory_compatibility = compatibility.model_dump(
            mode="json", exclude={"content_hash"}
        )
        contradictory_compatibility["candidate_samples"][0]["schedule_id"] = (
            "unbound-schedule"
        )
        with self.assertRaises(ValidationError):
            InferenceCompatibilityReport.model_validate(contradictory_compatibility)
        contradictory_compatibility = compatibility.model_dump(
            mode="json", exclude={"content_hash"}
        )
        contradictory_compatibility["case_results"][0][
            "candidate_output_content_hash"
        ] = "sha256:" + "f" * 64
        with self.assertRaises(ValidationError):
            InferenceCompatibilityReport.model_validate(contradictory_compatibility)

        contradictory_candidate_payload = compatibility.model_dump(
            mode="json", exclude={"content_hash"}
        )
        contradictory_candidate_payload["candidate_samples"][0][
            "serving_engine_version"
        ] = "wrong-serving-engine-version"
        contradictory_candidate = InferenceCompatibilityReport.model_validate(
            contradictory_candidate_payload
        )
        with tempfile.TemporaryDirectory() as temp_directory:
            system_path = Path(temp_directory) / "systems.json"
            compatibility_path = Path(temp_directory) / "compatibility.json"
            with self.assertRaisesRegex(
                ValueError, "candidate samples must match the exact systems manifest"
            ):
                write_report_pair(
                    system_report=systems,
                    compatibility_report=contradictory_candidate,
                    system_output_path=system_path,
                    compatibility_output_path=compatibility_path,
                )
            self.assertFalse(system_path.exists())
            self.assertFalse(compatibility_path.exists())

        with tempfile.TemporaryDirectory() as temp_directory:
            system_path = Path(temp_directory) / "systems.json"
            compatibility_path = Path(temp_directory) / "compatibility.json"
            write_report_pair(
                system_report=systems,
                compatibility_report=compatibility,
                system_output_path=system_path,
                compatibility_output_path=compatibility_path,
            )
            self.assertTrue(system_path.is_file())
            self.assertTrue(compatibility_path.is_file())
            with self.assertRaises(BenchmarkOutputExists):
                write_report_pair(
                    system_report=systems,
                    compatibility_report=compatibility,
                    system_output_path=system_path,
                    compatibility_output_path=compatibility_path,
                )

        mutable_environment = systems.environment.hardware
        mutable_environment["tampered_after_hash"] = True
        with tempfile.TemporaryDirectory() as temp_directory:
            with self.assertRaises(ValidationError):
                write_report_pair(
                    system_report=systems,
                    compatibility_report=compatibility,
                    system_output_path=Path(temp_directory) / "systems.json",
                    compatibility_output_path=(
                        Path(temp_directory) / "compatibility.json"
                    ),
                )

    async def test_stream_without_terminal_event_is_a_measured_failure(self) -> None:
        systems, compatibility = await run_inference_benchmark(
            provider=InterruptedProvider(),
            system_under_test=deterministic_manifest(),
            workload=short_workload(),
            environment=capture_environment_manifest(),
            benchmark_code_revision="a" * 40,
        )

        self.assertEqual(systems.status, "failed")
        self.assertEqual(len(systems.measured_samples), 4)
        self.assertTrue(
            all(
                sample.status == "failed"
                and sample.error is not None
                and sample.error.code == "stream_interrupted"
                for sample in systems.measured_samples
            )
        )
        self.assertEqual(systems.schedule_summaries[0].error_rate, 1.0)
        self.assertTrue(
            all(result.candidate_status == "failed" for result in compatibility.case_results)
        )

    async def test_event_after_terminal_is_recorded_as_protocol_failure(self) -> None:
        systems, _ = await run_inference_benchmark(
            provider=PostTerminalProvider(),
            system_under_test=deterministic_manifest(),
            workload=short_workload(),
            environment=capture_environment_manifest(),
            benchmark_code_revision="a" * 40,
        )

        self.assertEqual(systems.status, "failed")
        self.assertTrue(
            all(
                sample.error is not None
                and sample.error.code == "provider_protocol_error"
                and sample.output_content_hash is None
                and sample.model_version_id is None
                for sample in systems.measured_samples
            )
        )

    async def test_typed_failure_retains_safe_provider_code(self) -> None:
        systems, _ = await run_inference_benchmark(
            provider=FailedStreamProvider(),
            system_under_test=deterministic_manifest(),
            workload=short_workload(),
            environment=capture_environment_manifest(),
            benchmark_code_revision="a" * 40,
        )

        self.assertTrue(
            all(
                sample.error is not None
                and sample.error.code == "model_unavailable"
                and sample.error.provider_error_code == "MODEL_LOADING"
                for sample in systems.measured_samples
            )
        )

    async def test_failure_from_wrong_provider_is_protocol_error(self) -> None:
        systems, _ = await run_inference_benchmark(
            provider=WrongProviderFailedStreamProvider(),
            system_under_test=deterministic_manifest(),
            workload=short_workload(),
            environment=capture_environment_manifest(),
            benchmark_code_revision="a" * 40,
        )

        self.assertTrue(
            all(
                sample.error is not None
                and sample.error.code == "provider_protocol_error"
                and sample.error.provider_error_code is None
                for sample in systems.measured_samples
            )
        )

    async def test_live_version_must_match_the_pinned_manifest(self) -> None:
        with self.assertRaises(BenchmarkManifestMismatch) as raised:
            await run_inference_benchmark(
                provider=DeterministicLocalProvider(),
                system_under_test=deterministic_manifest(
                    serving_engine_version="unexpected-engine-version"
                ),
                workload=short_workload(),
                environment=capture_environment_manifest(),
                benchmark_code_revision="a" * 40,
            )

        self.assertIn("version.serving_engine_version", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
