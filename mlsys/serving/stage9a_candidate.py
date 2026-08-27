"""Exact development-only binding for the sealed Stage 9A Seed 9201 runtime."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psutil

from companion.hashing import content_hash
from mlsys.serving.openai_compatible import OpenAICompatibleProvider
from mlsys.serving.runtime_attestation import (
    RuntimeAttestation,
    file_sha256,
    write_runtime_attestation,
)


PROVIDER_ID = "stage9a-candidate-local"
ADAPTER_VERSION_ID = "qwen3-8b-stage9a-qlora-seed-9201"
MODEL_ALIAS = "qwen3-8b-stage9a-seed-9201"
SERVER_VERSION_MARKER = "stage9a-candidate-runtime-v1"


def _binding(project_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    registry_path = (
        project_root
        / "var"
        / "stage9a"
        / "registry"
        / "candidate-registry-v4-resource-correction2.json"
    )
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError("sealed Stage 9A candidate registry is unavailable") from error
    if not isinstance(registry, dict):
        raise ValueError("sealed Stage 9A candidate registry must be an object")
    claimed_hash = registry.get("content_hash")
    material = {key: value for key, value in registry.items() if key != "content_hash"}
    if claimed_hash != content_hash(material):
        raise ValueError("sealed Stage 9A candidate registry hash is invalid")
    matches = [
        item
        for item in registry["adapters"]
        if item.get("adapter_version_id") == ADAPTER_VERSION_ID
    ]
    if len(matches) != 1:
        raise ValueError("Seed 9201 is not uniquely bound in the candidate registry")
    adapter = matches[0]
    if (
        registry.get("status") != "candidate_only"
        or registry.get("local_only") is not True
        or registry.get("promotion_authorized") is not False
        or registry.get("deployment_authorized") is not False
        or adapter.get("lifecycle_status") != "candidate"
        or adapter.get("candidate_only") is not True
        or adapter.get("promotion_authorized") is not False
        or adapter.get("deployment_authorized") is not False
        or adapter.get("deployed") is not False
    ):
        raise ValueError("Seed 9201 is not an unpromoted local development candidate")
    return registry, adapter


def _read_state(state_path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError("Stage 9A candidate runtime state is unavailable") from error
    if not isinstance(payload, dict):
        raise ValueError("Stage 9A candidate runtime state must be an object")
    return payload


def attest_stage9a_candidate_runtime(
    *, project_root: Path, base_url: str, write: bool = False
) -> RuntimeAttestation:
    project_root = project_root.resolve()
    runtime_root = project_root / ".runtime" / "stage9a-candidate"
    state_path = runtime_root / "runtime-state.json"
    attestation_path = runtime_root / "runtime-attestation.json"
    registry, adapter = _binding(project_root)
    state = _read_state(state_path)
    model = registry["model"]
    script_path = (project_root / "mlsys" / "serving" / "stage9a_candidate_server.py").resolve()
    adapter_root = Path(adapter["artifact_uri"]).resolve()
    adapter_file = adapter_root / "adapter_model.safetensors"
    model_root = Path(model["artifact_uri"]).resolve()
    expected_state = {
        "schema_version": 1,
        "provider_id": PROVIDER_ID,
        "candidate_only": True,
        "promotion_authorized": False,
        "deployment_authorized": False,
        "request_logging_disabled": True,
        "web_ui_disabled": True,
        "host": "127.0.0.1",
        "port": 8081,
        "server_script": str(script_path),
        "server_script_hash": file_sha256(script_path),
        "registry_hash": registry["content_hash"],
        "model_version_id": model["model_version_id"],
        "model_artifact_hash": model["artifact_manifest_hash"],
        "model_root": str(model_root),
        "model_size_bytes": model["artifact_size_bytes"],
        "base_revision": model["upstream_revision"],
        "adapter_version_id": ADAPTER_VERSION_ID,
        "adapter_artifact_hash": adapter["artifact_hash"],
        "adapter_root": str(adapter_root),
        "adapter_manifest_hash": adapter["adapter_manifest_hash"],
        "model_alias": MODEL_ALIAS,
        "serving_engine": "transformers-peft",
    }
    for name, expected in expected_state.items():
        if state.get(name) != expected:
            raise ValueError(f"Stage 9A candidate runtime state mismatch: {name}")
    if state.get("serving_config_version") is None or state.get("serving_engine_version") is None:
        raise ValueError("Stage 9A candidate runtime version fields are missing")
    if SERVER_VERSION_MARKER not in str(state["serving_engine_version"]):
        raise ValueError("Stage 9A candidate runtime engine version is invalid")
    expected_tokenizer = f"Qwen/Qwen3-8B@{model['upstream_revision']}:tokenizer"
    if state.get("tokenizer_version_id") != expected_tokenizer:
        raise ValueError("Stage 9A candidate tokenizer binding is invalid")
    if not adapter_file.is_file() or file_sha256(adapter_file) != adapter["artifact_hash"]:
        raise ValueError("Seed 9201 adapter artifact is missing or changed")
    if not model_root.is_dir():
        raise ValueError("exact Stage 9A base model directory is unavailable")
    if base_url.rstrip("/") != "http://127.0.0.1:8081":
        raise ValueError("Stage 9A candidate runtime must use loopback port 8081")

    try:
        pid = int(state["pid"])
        launcher_pid = int(state["launcher_pid"])
        process = psutil.Process(pid)
        launcher = psutil.Process(launcher_pid)
        process_path = Path(process.exe()).resolve()
        launcher_path = Path(launcher.exe()).resolve()
        process_started_at = datetime.fromtimestamp(process.create_time(), tz=UTC)
        command_line = process.cmdline()
        launcher_command_line = launcher.cmdline()
    except (KeyError, OSError, ValueError, psutil.Error) as error:
        raise ValueError("Stage 9A candidate process is not running") from error
    expected_python = (
        project_root / "var" / "stage9a" / "env-windows" / "Scripts" / "python.exe"
    ).resolve()
    if launcher_path != expected_python or file_sha256(launcher_path) != file_sha256(expected_python):
        raise ValueError("Stage 9A candidate process does not use the sealed environment")
    if process.parent() is None or process.parent().pid != launcher_pid:
        raise ValueError("Stage 9A candidate process is detached from the sealed launcher")
    if len(command_line) < 3 or command_line[1:3] != [
        "-m",
        "mlsys.serving.stage9a_candidate_server",
    ]:
        raise ValueError("Stage 9A candidate process does not execute the checked server")
    actual_arguments = list(command_line[1:])
    expected_arguments = [
        "-m",
        "mlsys.serving.stage9a_candidate_server",
        "--host",
        "127.0.0.1",
        "--port",
        "8081",
        "--adapter-version",
        ADAPTER_VERSION_ID,
        "--state-path",
        str(state_path.resolve()),
    ]
    if actual_arguments != expected_arguments:
        raise ValueError("Stage 9A candidate process arguments differ from the checked profile")
    if launcher_command_line[1:] != expected_arguments:
        raise ValueError("Stage 9A candidate launcher arguments differ from the checked profile")

    without_hash = {
        "schema_version": 2,
        "attestation_id": (
            f"stage9a-candidate-runtime:{pid}:"
            f"{int(process_started_at.timestamp() * 1_000_000)}"
        ),
        "runtime_state_hash": file_sha256(state_path),
        "engine_manifest_hash": file_sha256(script_path),
        "model_manifest_hash": model["artifact_manifest_hash"],
        "server_executable_hash": file_sha256(process_path),
        "server_executable_path_hash": content_hash(str(process_path)),
        "process_executable_hash": file_sha256(process_path),
        "model_artifact_hash": model["artifact_manifest_hash"],
        "active_adapter_version_id": ADAPTER_VERSION_ID,
        "active_adapter_artifact_hash": adapter["artifact_hash"],
        "active_adapter_path_hash": content_hash(str(adapter_file)),
        "model_path_hash": content_hash(str(model_root)),
        "model_size_bytes": int(model["artifact_size_bytes"]),
        "server_pid": pid,
        "process_started_at": process_started_at.isoformat().replace("+00:00", "Z"),
        # RuntimeAttestation liveness normalizes the first non-``--`` Python
        # launcher argument (``-m``) before hashing.  The exact full command is
        # already compared above; persist the same normalized material here.
        "launch_arguments_hash": content_hash(actual_arguments[1:]),
        "base_url": "http://127.0.0.1:8081",
        "serving_engine": "transformers-peft",
        "serving_engine_version": str(state["serving_engine_version"]),
        "serving_config_version": str(state["serving_config_version"]),
        "model_version_id": str(model["model_version_id"]),
        "tokenizer_version_id": expected_tokenizer,
        "loaded_model_alias": MODEL_ALIAS,
        "loopback_only": True,
        "request_logging_disabled": True,
        "web_ui_disabled": True,
        "attested_at": process_started_at.isoformat().replace("+00:00", "Z"),
    }
    attestation = RuntimeAttestation(
        **without_hash,
        attestation_hash=content_hash(without_hash),
    )
    if write:
        write_runtime_attestation(attestation, attestation_path)
    return attestation


def build_stage9a_candidate_provider(settings: Any) -> OpenAICompatibleProvider:
    if settings.deployment_environment != "development":
        raise ValueError("Seed 9201 candidate runtime is development-only")
    if settings.release_manifest_path is not None:
        raise ValueError("Seed 9201 candidate runtime cannot consume a release manifest")
    project_root = Path(__file__).resolve().parents[2]
    registry, adapter = _binding(project_root)
    if (
        settings.runtime_adapter_version != ADAPTER_VERSION_ID
        or settings.runtime_adapter_hash != adapter["artifact_hash"]
    ):
        raise ValueError("Seed 9201 runtime requires its exact candidate ID and hash")
    attestation = attest_stage9a_candidate_runtime(
        project_root=project_root,
        base_url=settings.self_hosted_base_url,
        write=True,
    )
    state = _read_state(project_root / ".runtime" / "stage9a-candidate" / "runtime-state.json")
    return OpenAICompatibleProvider(
        base_url="http://127.0.0.1:8081",
        transport_model_id=MODEL_ALIAS,
        model_version_id=registry["model"]["model_version_id"],
        tokenizer_version_id=str(state["tokenizer_version_id"]),
        serving_engine="transformers-peft",
        serving_engine_version=str(state["serving_engine_version"]),
        serving_config_version=str(state["serving_config_version"]),
        provider_id=PROVIDER_ID,
        provider_adapter_version_id="stage9a-candidate-openai-bridge-v1",
        adapter_version_id=ADAPTER_VERSION_ID,
        adapter_artifact_hash=adapter["artifact_hash"],
        model_artifact_hash=registry["model"]["artifact_manifest_hash"],
        expected_build_substring=SERVER_VERSION_MARKER,
        max_context_tokens=8_192,
        max_output_tokens=512,
        health_path="/health",
        version_path="/props",
        models_path="/v1/models",
        completions_path="/v1/chat/completions",
        enable_thinking=False,
        reasoning_effort=None,
        runtime_attestation=attestation,
    )
