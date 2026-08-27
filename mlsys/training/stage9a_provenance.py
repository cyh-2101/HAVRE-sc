"""Exact local model/environment provenance for Stage 9A real training."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from companion.hashing import content_hash


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STAGE9A_ROOT = PROJECT_ROOT / "var" / "stage9a"
MODEL_MANIFEST = Path(__file__).resolve().parent / "manifests" / "qwen3-8b-stage9a.json"
STORAGE_LIMIT_BYTES = 80 * 1024**3
FORMAL_EXECUTION_SOURCE_SNAPSHOT = (
    "sha256:943fa77aa164e4e8dff517dbcd5e3dbfe468da54edcf97a07cbb2fe114660a07"
)
FORMAL_EXECUTION_SOURCE_FILE_COUNT = 316
FORMAL_EXECUTION_SOURCE_BYTES = 5_443_265
ARCHIVED_SOURCE_INVENTORIES = {
    FORMAL_EXECUTION_SOURCE_SNAPSHOT: (
        FORMAL_EXECUTION_SOURCE_FILE_COUNT,
        FORMAL_EXECUTION_SOURCE_BYTES,
    ),
    "sha256:8fec80ebb772b5dcfab7211ca8904dfb04e106aedcb865f46bd22a5254f9298c": (
        316,
        5_414_005,
    ),
}


def directory_size(root: Path) -> int:
    if not root.exists():
        return 0
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def assert_private_stage9a_path(path: Path) -> Path:
    resolved_root = STAGE9A_ROOT.resolve()
    resolved = path.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ValueError(f"Stage 9A artifact path escapes private root: {resolved}")
    return resolved


def require_archived_source_snapshot(
    snapshot: str = FORMAL_EXECUTION_SOURCE_SNAPSHOT,
) -> dict[str, Any]:
    """Recompute the exact pre-correction Stage 9A execution-source closure.

    Formal Gate C/D, training, reload, holdout, compatibility, seed-decision,
    and variance evidence were executed before the versioned final Owner
    Alignment evaluator correction. Their exact 316-file source tree is kept
    under the private Stage 9A root so later registry code can validate those
    historical execution claims without pretending they ran under newer code.
    """

    if snapshot not in ARCHIVED_SOURCE_INVENTORIES:
        raise ValueError("unsupported archived Stage 9A execution-source snapshot")
    expected_file_count, expected_total_bytes = ARCHIVED_SOURCE_INVENTORIES[snapshot]
    digest_name = snapshot.removeprefix("sha256:")
    root = assert_private_stage9a_path(
        STAGE9A_ROOT / "source-snapshots" / digest_name / "tree"
    )
    if not root.is_dir():
        raise FileNotFoundError("archived Stage 9A execution-source tree is missing")
    relative_paths = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    )
    total_bytes = sum((root / relative).stat().st_size for relative in relative_paths)
    if (
        len(relative_paths) != expected_file_count
        or total_bytes != expected_total_bytes
    ):
        raise ValueError("archived Stage 9A execution-source inventory mismatch")
    digest = hashlib.sha256(b"HAVRE-benchmark-execution-source-v2\0")
    for relative in relative_paths:
        encoded = relative.encode("utf-8")
        path = root / relative
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(b"\0file\0")
        digest.update(path.stat().st_size.to_bytes(8, "big"))
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    actual = f"sha256:{digest.hexdigest()}"
    if actual != snapshot:
        raise ValueError("archived Stage 9A execution-source hash mismatch")
    return {
        "snapshot": actual,
        "tree": str(root),
        "file_count": len(relative_paths),
        "total_bytes": total_bytes,
    }


def require_committed_source_snapshot_archive(
    *,
    snapshot: str,
    revision: str,
    expected_file_count: int,
    expected_total_bytes: int,
) -> dict[str, Any]:
    """Verify exact archived worktree bytes and their committed Git blobs."""

    if not snapshot.startswith("sha256:") or len(snapshot) != 71:
        raise ValueError("committed source archive lacks an exact SHA-256 snapshot")
    if len(revision) != 40 or any(
        character not in "0123456789abcdef" for character in revision
    ):
        raise ValueError("committed source archive lacks an exact Git revision")
    root = assert_private_stage9a_path(
        STAGE9A_ROOT / "source-snapshots" / snapshot.removeprefix("sha256:") / "tree"
    )
    if not root.is_dir():
        raise FileNotFoundError("committed Stage 9A source archive is missing")
    relative_paths = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    )
    total_bytes = sum((root / relative).stat().st_size for relative in relative_paths)
    if (
        len(relative_paths) != expected_file_count
        or total_bytes != expected_total_bytes
    ):
        raise ValueError("committed Stage 9A source archive inventory mismatch")

    listed = subprocess.run(
        ["git", "ls-tree", "-r", "-z", "--full-tree", revision],
        cwd=PROJECT_ROOT,
        capture_output=True,
        timeout=30,
        check=False,
        creationflags=(
            subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
        ),
    )
    if listed.returncode != 0 or not listed.stdout:
        raise RuntimeError("cannot enumerate committed Stage 9A source")
    source_roots = {
        "apps", "companion", "contracts", "db", "evals", "identity",
        "mlsys", "scripts", "services", "tests",
    }
    source_files = {".env.example", "pyproject.toml", "requirements.lock"}
    committed_blobs: dict[str, str] = {}
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
            committed_blobs[relative] = fields[2].decode("ascii")
    if set(relative_paths) != set(committed_blobs):
        raise ValueError("committed Stage 9A source archive coverage mismatch")

    digest = hashlib.sha256(b"HAVRE-benchmark-execution-source-v2\0")
    normalized_line_ending_files = 0
    for relative in relative_paths:
        path = root / relative
        payload = path.read_bytes()
        committed = subprocess.run(
            ["git", "cat-file", "blob", committed_blobs[relative]],
            cwd=PROJECT_ROOT,
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
            raise RuntimeError(
                f"cannot read committed Stage 9A source blob: {relative}"
            )
        if payload == committed.stdout:
            pass
        elif payload.replace(b"\r\n", b"\n") == committed.stdout:
            normalized_line_ending_files += 1
        else:
            raise ValueError(
                f"archived Stage 9A source differs from committed blob: {relative}"
            )
        encoded = relative.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(b"\0file\0")
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    actual = f"sha256:{digest.hexdigest()}"
    if actual != snapshot:
        raise ValueError("committed Stage 9A source archive hash mismatch")
    return {
        "snapshot": actual,
        "revision": revision,
        "tree": str(root),
        "file_count": len(relative_paths),
        "total_bytes": total_bytes,
        "normalized_line_ending_files": normalized_line_ending_files,
    }


def _git_blob_oid(path: Path) -> str:
    size = path.stat().st_size
    digest = hashlib.sha1(usedforsecurity=False)
    digest.update(f"blob {size}\0".encode("ascii"))
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def load_model_manifest(path: Path = MODEL_MANIFEST) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest["repository"] != "Qwen/Qwen3-8B":
        raise ValueError("Stage 9A model repository is not approved")
    revision = manifest["revision"]
    if len(revision) != 40 or any(value not in "0123456789abcdef" for value in revision):
        raise ValueError("Stage 9A model revision is not an exact commit")
    files = manifest["files"]
    if len({item["path"] for item in files}) != len(files):
        raise ValueError("model manifest contains duplicate paths")
    if sum(item["size_bytes"] for item in files) != manifest["expected_total_size_bytes"]:
        raise ValueError("model manifest total size is not exact")
    shards = {
        item["path"] for item in files if item["path"].endswith(".safetensors")
    }
    if shards != {f"model-{index:05d}-of-00005.safetensors" for index in range(1, 6)}:
        raise ValueError("model manifest does not contain the exact five-shard set")
    if any("lfs_sha256" not in item for item in files if item["path"].endswith(".safetensors")):
        raise ValueError("safetensor shard lacks expected LFS SHA-256")
    return manifest


def _verify_file(path: Path, entry: dict[str, Any]) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.stat().st_size != entry["size_bytes"]:
        raise ValueError(f"size mismatch for {path.name}")
    actual_sha256 = _sha256(path)
    if "lfs_sha256" in entry and actual_sha256 != entry["lfs_sha256"]:
        raise ValueError(f"LFS SHA-256 mismatch for {path.name}")
    actual_git_oid = _git_blob_oid(path)
    if "git_oid" in entry and actual_git_oid != entry["git_oid"]:
        raise ValueError(f"Git blob OID mismatch for {path.name}")
    return {
        "path": entry["path"],
        "size_bytes": path.stat().st_size,
        "sha256": "sha256:" + actual_sha256,
        "git_blob_oid": actual_git_oid,
        "expected_lfs_sha256": (
            "sha256:" + entry["lfs_sha256"] if "lfs_sha256" in entry else None
        ),
    }


def verify_model_artifact(
    target: Path,
    manifest_path: Path = MODEL_MANIFEST,
) -> dict[str, Any]:
    target = assert_private_stage9a_path(target)
    manifest = load_model_manifest(manifest_path)
    verified = [_verify_file(target / entry["path"], entry) for entry in manifest["files"]]
    index = json.loads((target / "model.safetensors.index.json").read_text(encoding="utf-8"))
    referenced_shards = set(index["weight_map"].values())
    expected_shards = {
        item["path"] for item in manifest["files"] if item["path"].endswith(".safetensors")
    }
    if referenced_shards != expected_shards:
        raise ValueError("safetensor index does not reference the exact approved shard set")
    config = json.loads((target / "config.json").read_text(encoding="utf-8"))
    if config.get("model_type") != "qwen3" or config.get("architectures") != [
        "Qwen3ForCausalLM"
    ]:
        raise ValueError("downloaded config is not exact Qwen3ForCausalLM")
    license_text = (target / "LICENSE").read_text(encoding="utf-8")
    if "Apache License" not in license_text or "Version 2.0" not in license_text:
        raise ValueError("downloaded license is not Apache-2.0")
    report = {
        "schema_version": 1,
        "repository": manifest["repository"],
        "revision": manifest["revision"],
        "manifest_id": manifest["manifest_id"],
        "weights_format": manifest["weights_format"],
        "license": manifest["license"],
        "target": str(target),
        "artifact_size_bytes": sum(item["size_bytes"] for item in verified),
        "files": verified,
        "verified_at": datetime.now(UTC).isoformat(),
    }
    report["content_hash"] = content_hash(report)
    return report


def download_model_artifact(
    target: Path,
    report_path: Path,
    manifest_path: Path = MODEL_MANIFEST,
) -> dict[str, Any]:
    target = assert_private_stage9a_path(target)
    report_path = assert_private_stage9a_path(report_path)
    target.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = load_model_manifest(manifest_path)
    missing_bytes = sum(
        entry["size_bytes"]
        for entry in manifest["files"]
        if not (target / entry["path"]).exists()
    )
    if directory_size(STAGE9A_ROOT) + missing_bytes > STORAGE_LIMIT_BYTES:
        raise RuntimeError("model download would exceed the Stage 9A 80 GiB storage limit")

    def download_one(entry: dict[str, Any]) -> None:
        destination = target / entry["path"]
        if destination.exists():
            _verify_file(destination, entry)
            return
        partial = destination.with_suffix(destination.suffix + ".partial")
        url = (
            "https://huggingface.co/"
            + manifest["repository"]
            + "/resolve/"
            + manifest["revision"]
            + "/"
            + urllib.parse.quote(entry["path"], safe="/")
            + "?download=true"
        )
        for attempt in range(1, 6):
            existing = partial.stat().st_size if partial.exists() else 0
            if existing > entry["size_bytes"]:
                raise ValueError(f"oversized partial download for {entry['path']}")
            if existing == entry["size_bytes"]:
                break
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "HAVRE-Stage9A-Provenance/1",
                    **({"Range": f"bytes={existing}-"} if existing else {}),
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=600) as response:
                    if existing and response.status != 206:
                        raise RuntimeError(
                            f"server did not honor resume for {entry['path']}"
                        )
                    mode = "ab" if existing else "wb"
                    with partial.open(mode) as handle:
                        while chunk := response.read(1024 * 1024):
                            handle.write(chunk)
            except (TimeoutError, urllib.error.URLError, ConnectionError):
                if attempt == 5:
                    raise
        if partial.stat().st_size != entry["size_bytes"]:
            raise ValueError(f"incomplete download for {entry['path']}")
        partial.replace(destination)
        _verify_file(destination, entry)

    # Use one official-Hub stream at a time on the observed unstable route. All
    # retries resume the same canonical partial and never create per-run copies.
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="stage9a-model") as pool:
        list(pool.map(download_one, manifest["files"]))
    report = verify_model_artifact(target, manifest_path)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def collect_environment_manifest() -> dict[str, Any]:
    packages = {}
    for name in (
        "torch", "transformers", "peft", "accelerate", "bitsandbytes",
        "huggingface-hub", "safetensors", "psutil",
    ):
        packages[name] = importlib.metadata.version(name)
    freeze = subprocess.run(
        [sys.executable, "-m", "pip", "freeze", "--all"],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    ).stdout.splitlines()
    nvidia_smi = subprocess.run(
        [
            "nvidia-smi.exe",
            "--query-gpu=name,uuid,driver_version,memory.total,compute_cap",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    ).stdout.strip()
    manifest = {
        "schema_version": 1,
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "packages": packages,
        "dependency_lock": sorted(freeze),
        "nvidia_smi": nvidia_smi,
        "cache_paths": {
            name: os.environ.get(name)
            for name in (
                "PIP_CACHE_DIR", "HF_HOME", "HF_HUB_CACHE", "TRANSFORMERS_CACHE",
                "TORCH_HOME", "TMP", "TEMP",
            )
        },
        "stage9a_root": str(STAGE9A_ROOT.resolve()),
        "stage9a_bytes": directory_size(STAGE9A_ROOT),
        "captured_at": datetime.now(UTC).isoformat(),
    }
    if any(
        value is None or not Path(value).resolve().is_relative_to(STAGE9A_ROOT.resolve())
        for value in manifest["cache_paths"].values()
    ):
        raise ValueError("one or more training cache paths escape the Stage 9A private root")
    manifest["content_hash"] = content_hash(manifest)
    return manifest
