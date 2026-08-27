"""Focused tests for the Stage 3 local-runtime attestation boundary.

These tests use only tiny temporary artifacts and a fake psutil process.  They
prove each relationship independently, without touching the installed Stage 3
runtime, a real model, or a real operating-system process.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mlsys.serving import (
    RuntimeAttestation,
    attest_active_runtime,
    verify_attested_process_liveness,
)


class _FakeProcess:
    def __init__(
        self,
        *,
        executable: Path,
        command_line: list[str],
        create_time: float = 1_700_000_000.0,
    ) -> None:
        self._executable = executable
        self._command_line = command_line
        self._create_time = create_time

    def exe(self) -> str:
        return str(self._executable)

    def cmdline(self) -> list[str]:
        return list(self._command_line)

    def create_time(self) -> float:
        return self._create_time


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


class Stage3RuntimeAttestationTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.runtime_root = self.root / ".runtime" / "stage3"
        self.runtime_state_path = self.runtime_root / "runtime-state.json"
        self.runtime_pid_path = self.runtime_root / "run" / "llama-server.pid"
        self.model_file = self.runtime_root / "models" / "model.gguf"
        self.server_file = self.runtime_root / "engine" / "llama-server.exe"
        self.model_manifest_path = self.root / "manifests" / "model.json"
        self.engine_manifest_path = self.root / "manifests" / "engine.json"

        for path in (
            self.runtime_pid_path,
            self.model_file,
            self.server_file,
            self.model_manifest_path,
            self.engine_manifest_path,
        ):
            path.parent.mkdir(parents=True, exist_ok=True)

        self.model_file.write_bytes(b"tiny-model-artifact-v1")
        self.server_file.write_bytes(b"tiny-server-binary-v1")
        self.model_manifest_path.write_text(
            '{"manifest_id":"model-test-v1"}\n', encoding="utf-8"
        )
        self.engine_manifest_path.write_text(
            '{"manifest_id":"engine-test-v1"}\n', encoding="utf-8"
        )
        self.runtime_pid_path.write_text("4242\n", encoding="ascii")

        self.model = {
            "manifest_id": "model-test-v1",
            "alias": "model-test",
            "upstream": {"repository": "test/model", "revision": "a" * 40},
            "artifact": {
                "sha256": _sha256(self.model_file),
                "size_bytes": self.model_file.stat().st_size,
            },
            "serving_profile": {
                "port": 8080,
                "context_tokens": 8192,
                "parallel_slots": 2,
                "gpu_layers_cli_value": 99,
                "host": "127.0.0.1",
                "request_logging": False,
                "web_ui": False,
            },
        }
        self.engine = {
            "manifest_id": "engine-test-v1",
            "upstream": {"release_tag": "b1", "commit": "b" * 40},
            "api": {"base_url": "http://127.0.0.1:8080"},
            "security_defaults": {
                "bind_host": "127.0.0.1",
                "request_logging": False,
                "web_ui": False,
            },
        }
        self.model_manifest_path.write_text(
            json.dumps(self.model, sort_keys=True) + "\n", encoding="utf-8"
        )
        self.engine_manifest_path.write_text(
            json.dumps(self.engine, sort_keys=True) + "\n", encoding="utf-8"
        )
        self.state = {
            "schema_version": 1,
            "engine_manifest_id": self.engine["manifest_id"],
            "engine_manifest_sha256": _sha256(self.engine_manifest_path),
            "model_manifest_id": self.model["manifest_id"],
            "model_manifest_sha256": _sha256(self.model_manifest_path),
            "server_executable_relative_path": str(
                self.server_file.relative_to(self.runtime_root)
            ),
            "server_executable_sha256": _sha256(self.server_file),
            "model_relative_path": str(self.model_file.relative_to(self.runtime_root)),
        }
        self._write_state()

    def _write_state(self) -> None:
        self.runtime_state_path.parent.mkdir(parents=True, exist_ok=True)
        self.runtime_state_path.write_text(
            json.dumps(self.state, sort_keys=True) + "\n", encoding="utf-8"
        )

    def _expected_arguments(self) -> list[str]:
        profile = self.model["serving_profile"]
        return [
            "--model",
            str(self.model_file),
            "--alias",
            str(self.model["alias"]),
            "--host",
            "127.0.0.1",
            "--port",
            str(profile["port"]),
            "--ctx-size",
            str(profile["context_tokens"]),
            "--parallel",
            str(profile["parallel_slots"]),
            "--n-gpu-layers",
            str(profile["gpu_layers_cli_value"]),
            "--flash-attn",
            "on",
            "--jinja",
            "--metrics",
            "--log-disable",
            "--no-webui",
        ]

    def _verify(self, *, arguments: list[str] | None = None) -> RuntimeAttestation:
        command_line = [str(self.server_file), *(arguments or self._expected_arguments())]
        process = _FakeProcess(
            executable=self.server_file,
            command_line=command_line,
        )
        with patch("mlsys.serving.runtime_attestation.psutil.Process", return_value=process):
            return attest_active_runtime(
                runtime_root=self.runtime_root,
                runtime_state_path=self.runtime_state_path,
                runtime_pid_path=self.runtime_pid_path,
                model_manifest_path=self.model_manifest_path,
                engine_manifest_path=self.engine_manifest_path,
            )

    def test_verified_runtime_returns_typed_complete_attestation(self) -> None:
        result = self._verify()

        self.assertIsInstance(result, RuntimeAttestation)
        self.assertEqual(result.server_pid, 4242)
        self.assertEqual(result.model_artifact_hash, _sha256(self.model_file))
        self.assertEqual(result.server_executable_hash, _sha256(self.server_file))
        self.assertEqual(result.process_executable_hash, _sha256(self.server_file))
        self.assertRegex(result.runtime_state_hash, r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(result.launch_arguments_hash, r"^sha256:[0-9a-f]{64}$")
        self.assertTrue(result.request_logging_disabled)
        self.assertTrue(result.web_ui_disabled)
        self.assertRegex(result.attestation_hash, r"^sha256:[0-9a-f]{64}$")

    def test_wrong_model_hash_is_rejected(self) -> None:
        original = self.model_file.read_bytes()
        self.model_file.write_bytes(bytes([original[0] ^ 1]) + original[1:])

        with self.assertRaisesRegex(ValueError, "model artifact hash"):
            self._verify()

    def test_wrong_server_hash_is_rejected(self) -> None:
        original = self.server_file.read_bytes()
        self.server_file.write_bytes(bytes([original[0] ^ 1]) + original[1:])

        with self.assertRaisesRegex(ValueError, "server executable hash"):
            self._verify()

    def test_stale_pid_is_rejected_without_opening_a_process(self) -> None:
        self.runtime_pid_path.write_text("not-a-pid\n", encoding="ascii")

        with patch(
            "mlsys.serving.runtime_attestation.psutil.Process",
            side_effect=AssertionError("invalid PID must fail before process lookup"),
        ) as process:
            with self.assertRaisesRegex(ValueError, "serving process is not running"):
                attest_active_runtime(
                    runtime_root=self.runtime_root,
                    runtime_state_path=self.runtime_state_path,
                    runtime_pid_path=self.runtime_pid_path,
                    model_manifest_path=self.model_manifest_path,
                    engine_manifest_path=self.engine_manifest_path,
                )
        process.assert_not_called()

    def test_wrong_pid_executable_is_rejected(self) -> None:
        other_executable = self.root / "other" / "llama-server.exe"
        other_executable.parent.mkdir(parents=True)
        other_executable.write_bytes(self.server_file.read_bytes())
        process = _FakeProcess(
            executable=other_executable,
            command_line=[str(other_executable), *self._expected_arguments()],
        )

        with patch("mlsys.serving.runtime_attestation.psutil.Process", return_value=process):
            with self.assertRaisesRegex(ValueError, "verified serving executable"):
                attest_active_runtime(
                    runtime_root=self.runtime_root,
                    runtime_state_path=self.runtime_state_path,
                    runtime_pid_path=self.runtime_pid_path,
                    model_manifest_path=self.model_manifest_path,
                    engine_manifest_path=self.engine_manifest_path,
                )

    def test_missing_duplicate_and_mismatched_launch_arguments_are_rejected(self) -> None:
        expected = self._expected_arguments()

        missing_metrics = list(expected)
        missing_metrics.remove("--metrics")
        duplicate_override = [*expected, "--parallel", "1"]
        wrong_gpu_layers = list(expected)
        wrong_gpu_layers[wrong_gpu_layers.index("--n-gpu-layers") + 1] = "0"
        wrong_flash_mode = list(expected)
        wrong_flash_mode[wrong_flash_mode.index("--flash-attn") + 1] = "off"
        wrong_context = list(expected)
        wrong_context[wrong_context.index("--ctx-size") + 1] = "4096"

        cases = {
            "missing_required_flag": missing_metrics,
            "duplicate_override": duplicate_override,
            "wrong_gpu_layers": wrong_gpu_layers,
            "wrong_flash_mode": wrong_flash_mode,
            "mismatched_context": wrong_context,
        }
        for name, arguments in cases.items():
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "arguments differ"):
                    self._verify(arguments=arguments)

    def test_runtime_relative_path_escape_is_rejected(self) -> None:
        self.state["model_relative_path"] = str(Path("..") / "escaped.gguf")
        self._write_state()

        with self.assertRaisesRegex(ValueError, "escaped the Stage 3 runtime root"):
            self._verify()

    def test_file_hashing_streams_without_path_read_bytes(self) -> None:
        artifact = self.root / "streamed-artifact.bin"
        artifact.write_bytes(b"stream-this-block" * 100_000)
        expected = _sha256(artifact)

        with patch.object(
            Path,
            "read_bytes",
            side_effect=AssertionError("artifact hashing must not buffer whole files"),
        ):
            from mlsys.serving.runtime_attestation import file_sha256

            self.assertEqual(file_sha256(artifact), expected)

    def test_pid_reuse_is_rejected_by_cheap_liveness_check(self) -> None:
        result = self._verify()
        reused = _FakeProcess(
            executable=self.server_file,
            command_line=[str(self.server_file), *self._expected_arguments()],
            create_time=1_700_000_001.0,
        )
        with patch(
            "mlsys.serving.runtime_attestation.psutil.Process",
            return_value=reused,
        ), self.assertRaisesRegex(ValueError, "PID has been reused"):
            verify_attested_process_liveness(result)

    def test_wrong_process_start_path_or_arguments_fail_liveness(self) -> None:
        result = self._verify()
        other = self.root / "other" / "llama-server.exe"
        other.parent.mkdir(parents=True)
        other.write_bytes(self.server_file.read_bytes())
        cases = (
            _FakeProcess(
                executable=other,
                command_line=[str(other), *self._expected_arguments()],
            ),
            _FakeProcess(
                executable=self.server_file,
                command_line=[str(self.server_file), *self._expected_arguments()[:-1]],
            ),
        )
        for process in cases:
            with self.subTest(executable=process.exe()), patch(
                "mlsys.serving.runtime_attestation.psutil.Process",
                return_value=process,
            ), self.assertRaises(ValueError):
                verify_attested_process_liveness(result)


if __name__ == "__main__":
    unittest.main()
