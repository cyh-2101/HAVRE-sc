"""Process-bound attestation for the pinned Stage 3 local model runtime.

This module is production serving infrastructure.  Benchmark code may consume
it, but Companion runtime construction must never depend on ``evals``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import psutil
from pydantic import BaseModel, ConfigDict, Field, model_validator

from companion.hashing import content_hash


SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"


class RuntimeAttestation(BaseModel):
    """Immutable, content-free proof of one active pinned serving process."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1, 2] = 1
    attestation_id: str = Field(min_length=1, max_length=300)
    runtime_state_hash: str = Field(pattern=SHA256_PATTERN)
    engine_manifest_hash: str = Field(pattern=SHA256_PATTERN)
    model_manifest_hash: str = Field(pattern=SHA256_PATTERN)
    server_executable_hash: str = Field(pattern=SHA256_PATTERN)
    server_executable_path_hash: str = Field(pattern=SHA256_PATTERN)
    process_executable_hash: str = Field(pattern=SHA256_PATTERN)
    model_artifact_hash: str = Field(pattern=SHA256_PATTERN)
    active_adapter_version_id: str | None = Field(default=None, min_length=1, max_length=500)
    active_adapter_artifact_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    active_adapter_path_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    model_path_hash: str = Field(pattern=SHA256_PATTERN)
    model_size_bytes: int = Field(gt=0)
    server_pid: int = Field(gt=0)
    process_started_at: datetime
    launch_arguments_hash: str = Field(pattern=SHA256_PATTERN)
    base_url: str = Field(min_length=1, max_length=500)
    serving_engine: str = Field(min_length=1, max_length=200)
    serving_engine_version: str = Field(min_length=1, max_length=300)
    serving_config_version: str = Field(min_length=1, max_length=300)
    model_version_id: str = Field(min_length=1, max_length=500)
    tokenizer_version_id: str = Field(min_length=1, max_length=500)
    loaded_model_alias: str = Field(min_length=1, max_length=300)
    loopback_only: Literal[True] = True
    request_logging_disabled: Literal[True] = True
    web_ui_disabled: Literal[True] = True
    attested_at: datetime
    attestation_hash: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_content_hash(self) -> "RuntimeAttestation":
        adapter_values = (
            self.active_adapter_version_id,
            self.active_adapter_artifact_hash,
            self.active_adapter_path_hash,
        )
        if any(value is not None for value in adapter_values) and not all(
            value is not None for value in adapter_values
        ):
            raise ValueError("runtime adapter attestation fields are atomic")
        excluded = {"attestation_hash"}
        if self.schema_version == 1:
            if any(
                value is not None
                for value in (
                    self.active_adapter_version_id,
                    self.active_adapter_artifact_hash,
                    self.active_adapter_path_hash,
                )
            ):
                raise ValueError("runtime attestation v1 cannot contain an adapter")
            excluded.update(
                {
                    "active_adapter_version_id",
                    "active_adapter_artifact_hash",
                    "active_adapter_path_hash",
                }
            )
        payload = self.model_dump(mode="json", exclude=excluded)
        if content_hash(payload) != self.attestation_hash:
            raise ValueError("runtime attestation content hash mismatch")
        parsed = urlsplit(self.base_url)
        if parsed.scheme != "http" or parsed.hostname not in {
            "127.0.0.1",
            "::1",
            "localhost",
        }:
            raise ValueError("runtime attestation base_url must be loopback HTTP")
        return self


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise ValueError(f"cannot read {label}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _runtime_child(runtime_root: Path, relative_path: object) -> Path:
    if not isinstance(relative_path, str) or not relative_path:
        raise ValueError("runtime state contains an invalid relative path")
    candidate = (runtime_root / relative_path).resolve()
    if candidate == runtime_root or runtime_root not in candidate.parents:
        raise ValueError("runtime state path escaped the Stage 3 runtime root")
    return candidate


def _expected_arguments(
    *, model: dict[str, Any], model_path: Path, adapter_path: Path | None = None
) -> list[str]:
    profile = model.get("serving_profile")
    if not isinstance(profile, dict):
        raise ValueError("model manifest serving profile is invalid")
    arguments = [
        "--model",
        str(model_path),
        "--alias",
        str(model["alias"]),
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
    if adapter_path is not None:
        arguments.extend(("--lora", str(adapter_path)))
    return arguments


def attest_active_runtime(
    *,
    runtime_root: Path,
    runtime_state_path: Path,
    runtime_pid_path: Path,
    model_manifest_path: Path,
    engine_manifest_path: Path,
    adapter_manifest_path: Path | None = None,
) -> RuntimeAttestation:
    """Perform the expensive verification once and bind it to the active PID."""

    runtime_root = runtime_root.resolve()
    state = read_json_object(runtime_state_path, label="Stage 3 runtime state")
    model = read_json_object(model_manifest_path, label="model manifest")
    engine = read_json_object(engine_manifest_path, label="serving-engine manifest")
    model_manifest_hash = file_sha256(model_manifest_path)
    engine_manifest_hash = file_sha256(engine_manifest_path)
    adapter_version_id = None
    adapter_artifact_hash = None
    adapter_path = None
    if adapter_manifest_path is not None:
        adapter = read_json_object(adapter_manifest_path, label="adapter manifest")
        adapter_manifest_hash = file_sha256(adapter_manifest_path)
        adapter_artifact = adapter.get("artifact")
        if (
            adapter.get("schema_version") != 1
            or adapter.get("artifact_kind") != "adapter"
            or adapter.get("immutable") is not True
            or adapter.get("lifecycle_status") != "approved"
            or adapter.get("base_model_manifest_id") != model.get("manifest_id")
            or not isinstance(adapter_artifact, dict)
            or state.get("adapter_manifest_id") != adapter.get("manifest_id")
            or state.get("adapter_manifest_sha256") != adapter_manifest_hash
        ):
            raise ValueError("runtime adapter manifest is invalid or unbound")
        adapter_path = _runtime_child(runtime_root, state.get("adapter_relative_path"))
        if (
            not adapter_path.is_file()
            or adapter_path.stat().st_size != adapter_artifact.get("size_bytes")
        ):
            raise ValueError("adapter artifact path or size does not match the manifest")
        adapter_artifact_hash = file_sha256(adapter_path)
        if adapter_artifact_hash != adapter_artifact.get("sha256"):
            raise ValueError("adapter artifact hash does not match the manifest")
        adapter_version_id = str(adapter["manifest_id"])
    elif any(str(key).startswith("adapter_") for key in state):
        raise ValueError("runtime state contains an unattested adapter")
    if (
        state.get("schema_version") != 1
        or state.get("model_manifest_id") != model.get("manifest_id")
        or state.get("engine_manifest_id") != engine.get("manifest_id")
        or state.get("model_manifest_sha256") != model_manifest_hash
        or state.get("engine_manifest_sha256") != engine_manifest_hash
    ):
        raise ValueError("runtime state does not match checked-in manifests")

    artifact = model.get("artifact")
    profile = model.get("serving_profile")
    upstream_model = model.get("upstream")
    upstream_engine = engine.get("upstream")
    api = engine.get("api")
    security = engine.get("security_defaults")
    if not all(
        isinstance(item, dict)
        for item in (artifact, profile, upstream_model, upstream_engine, api, security)
    ):
        raise ValueError("pinned manifests are incomplete")
    if (
        profile.get("host") != "127.0.0.1"
        or security.get("bind_host") != "127.0.0.1"
        or profile.get("request_logging") is not False
        or profile.get("web_ui") is not False
        or security.get("request_logging") is not False
        or security.get("web_ui") is not False
    ):
        raise ValueError("pinned runtime does not enforce the local privacy-safe profile")

    model_path = _runtime_child(runtime_root, state.get("model_relative_path"))
    server_path = _runtime_child(
        runtime_root, state.get("server_executable_relative_path")
    )
    if not model_path.is_file() or model_path.stat().st_size != artifact.get("size_bytes"):
        raise ValueError("model artifact path or size does not match the manifest")
    model_hash = file_sha256(model_path)
    if model_hash != artifact.get("sha256"):
        raise ValueError("model artifact hash does not match the manifest")
    if not server_path.is_file():
        raise ValueError("server executable is missing")
    server_hash = file_sha256(server_path)
    if server_hash != state.get("server_executable_sha256"):
        raise ValueError("server executable hash does not match runtime state")

    try:
        pid = int(runtime_pid_path.read_text(encoding="ascii").strip())
        process = psutil.Process(pid)
        process_path = Path(process.exe()).resolve()
        process_started_at = datetime.fromtimestamp(process.create_time(), tz=UTC)
        command_line = process.cmdline()
    except (OSError, ValueError, psutil.Error) as error:
        raise ValueError("verified Stage 3 serving process is not running") from error
    if process_path != server_path:
        raise ValueError("running PID is not the verified serving executable")
    process_hash = file_sha256(process_path)
    if process_hash != server_hash:
        raise ValueError("running process executable hash does not match the pinned server")
    if len(command_line) < 2:
        raise ValueError("running server command line is incomplete")
    actual_arguments = list(command_line[1:])
    if actual_arguments and not actual_arguments[0].startswith("--"):
        if Path(actual_arguments[0]).name.casefold() != server_path.name.casefold():
            raise ValueError("running command line does not launch the verified server")
        actual_arguments = actual_arguments[1:]
    expected_arguments = _expected_arguments(
        model=model,
        model_path=model_path,
        adapter_path=adapter_path,
    )
    if actual_arguments != expected_arguments:
        raise ValueError("running server arguments differ from the pinned launch profile")

    engine_tag = upstream_engine.get("release_tag")
    engine_commit = upstream_engine.get("commit")
    model_revision = upstream_model.get("revision")
    if not all(isinstance(value, str) and value for value in (
        engine_tag,
        engine_commit,
        model_revision,
    )):
        raise ValueError("pinned manifests require exact upstream revisions")
    base_url = api.get("base_url")
    if not isinstance(base_url, str):
        raise ValueError("serving-engine manifest base URL is invalid")
    tokenizer_version_id = (
        f"{upstream_model['repository']}@{model_revision}:embedded-gguf-tokenizer"
    )
    # Identity must remain stable for the lifetime of one process.  The proof is
    # rebuilt and rechecked as needed, but its immutable content is anchored to
    # the OS process creation time rather than wall-clock verification time.
    attested_at = process_started_at
    without_hash = {
        "schema_version": 2 if adapter_path is not None else 1,
        "attestation_id": (
            f"stage3-runtime:{pid}:"
            f"{int(process_started_at.timestamp() * 1_000_000)}"
        ),
        "runtime_state_hash": file_sha256(runtime_state_path),
        "engine_manifest_hash": engine_manifest_hash,
        "model_manifest_hash": model_manifest_hash,
        "server_executable_hash": server_hash,
        "server_executable_path_hash": content_hash(str(server_path)),
        "process_executable_hash": process_hash,
        "model_artifact_hash": model_hash,
        "model_path_hash": content_hash(str(model_path)),
        "model_size_bytes": model_path.stat().st_size,
        "server_pid": pid,
        "process_started_at": process_started_at.isoformat().replace("+00:00", "Z"),
        "launch_arguments_hash": content_hash(actual_arguments),
        "base_url": base_url,
        "serving_engine": "llama.cpp",
        "serving_engine_version": f"{engine_tag}@{engine_commit}",
        "serving_config_version": content_hash(profile),
        "model_version_id": str(model["manifest_id"]),
        "tokenizer_version_id": tokenizer_version_id,
        "loaded_model_alias": str(model["alias"]),
        "loopback_only": True,
        "request_logging_disabled": True,
        "web_ui_disabled": True,
        "attested_at": attested_at.isoformat().replace("+00:00", "Z"),
    }
    if adapter_path is not None:
        without_hash.update(
            {
                "active_adapter_version_id": adapter_version_id,
                "active_adapter_artifact_hash": adapter_artifact_hash,
                "active_adapter_path_hash": content_hash(str(adapter_path)),
            }
        )
    return RuntimeAttestation.model_validate(
        {**without_hash, "attestation_hash": content_hash(without_hash)}
    )


def write_runtime_attestation(
    attestation: RuntimeAttestation, path: Path
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(f".{path.name}.pending")
    pending.write_text(
        attestation.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    pending.replace(path)


def verify_attested_process_liveness(attestation: RuntimeAttestation) -> None:
    """Cheap per-check proof that the attested PID has not been replaced."""

    try:
        process = psutil.Process(attestation.server_pid)
        process_started_at = datetime.fromtimestamp(process.create_time(), tz=UTC)
        process_path = Path(process.exe()).resolve()
        command_line = process.cmdline()
    except (OSError, ValueError, psutil.Error) as error:
        raise ValueError("attested Stage 3 serving process is no longer running") from error
    if abs((process_started_at - attestation.process_started_at).total_seconds()) > 0.001:
        raise ValueError("attested Stage 3 PID has been reused")
    if content_hash(str(process_path)) != attestation.server_executable_path_hash:
        raise ValueError("attested Stage 3 process executable path changed")
    if file_sha256(process_path) != attestation.process_executable_hash:
        raise ValueError("attested Stage 3 process executable changed")
    if len(command_line) < 2:
        raise ValueError("attested Stage 3 process arguments are unavailable")
    actual_arguments = list(command_line[1:])
    if actual_arguments and not actual_arguments[0].startswith("--"):
        actual_arguments = actual_arguments[1:]
    if content_hash(actual_arguments) != attestation.launch_arguments_hash:
        raise ValueError("attested Stage 3 process arguments changed")
