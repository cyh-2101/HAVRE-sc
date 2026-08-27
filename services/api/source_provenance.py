"""Production-safe helpers for binding artifacts to exact Git source bytes."""

from __future__ import annotations

import hashlib
import platform
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOTS = {
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
SOURCE_FILES = {".env.example", "pyproject.toml", "requirements.lock"}
DEPLOYMENT_EXACT_FILES = {
    "pyproject.toml",
    "README.md",
    "deploy/Dockerfile",
    "deploy/Operations.Dockerfile",
    "deploy/Caddyfile",
    "deploy/bootstrap_roles.sql",
    "deploy/finalize_restore.sql",
    "deploy/compose.yaml",
    "deploy/compose.stage12a-windows.yaml",
    "deploy/runtime-requirements.lock",
    "apps/web/havre-chat.html",
    "scripts/build_stage10_image_context.py",
    "scripts/verify_stage10_deployment_config.py",
    "mlsys/__init__.py",
    "mlsys/py.typed",
}
DEPLOYMENT_PREFIXES = (
    "companion/",
    "db/migrations/",
    "identity/",
    "mlsys/contracts/",
    "mlsys/retrieval/",
    "mlsys/serving/",
    "services/",
)


def _creation_flags() -> int:
    return subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0


def git_head_revision(
    project_root: Path = PROJECT_ROOT, *, require_clean: bool = True
) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        creationflags=_creation_flags(),
    )
    revision = completed.stdout.strip()
    if completed.returncode != 0 or len(revision) != 40:
        raise RuntimeError("cannot determine the exact source revision")
    if require_clean:
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=normal"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            creationflags=_creation_flags(),
        )
        if status.returncode != 0 or status.stdout.strip():
            raise RuntimeError("source tree is not clean")
    return revision


def _is_source_path(relative: str) -> bool:
    parts = relative.split("/")
    return relative in SOURCE_FILES or (
        parts[0] in SOURCE_ROOTS and not relative.startswith("evals/reports/")
    )


def source_snapshot_revision(project_root: Path = PROJECT_ROOT) -> str:
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=project_root,
        capture_output=True,
        timeout=30,
        check=False,
        creationflags=_creation_flags(),
    )
    if listed.returncode != 0:
        raise RuntimeError("cannot enumerate the source snapshot")
    relative_paths = sorted(
        item.decode("utf-8").replace("\\", "/")
        for item in listed.stdout.split(b"\0")
        if item and _is_source_path(item.decode("utf-8").replace("\\", "/"))
    )
    if not relative_paths:
        raise RuntimeError("source snapshot is empty")
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


def current_source_revision(project_root: Path = PROJECT_ROOT) -> str:
    try:
        return git_head_revision(project_root, require_clean=True)
    except RuntimeError:
        return source_snapshot_revision(project_root)


def deployment_source_paths(
    project_root: Path = PROJECT_ROOT, *, revision: str | None = None
) -> tuple[str, ...]:
    revision = revision or git_head_revision(project_root, require_clean=False)
    listed = subprocess.run(
        ["git", "ls-tree", "-r", "-z", "--name-only", revision],
        cwd=project_root,
        capture_output=True,
        timeout=30,
        check=False,
        creationflags=_creation_flags(),
    )
    if listed.returncode != 0:
        raise RuntimeError("cannot enumerate the deployment source closure")
    return tuple(
        sorted(
            relative
            for item in listed.stdout.split(b"\0")
            if item
            for relative in (item.decode("utf-8").replace("\\", "/"),)
            if relative in DEPLOYMENT_EXACT_FILES
            or relative.startswith(DEPLOYMENT_PREFIXES)
        )
    )


def deployment_source_snapshot_revision(
    project_root: Path = PROJECT_ROOT,
    *,
    revision: str | None = None,
    relative_paths: tuple[str, ...] | None = None,
) -> str:
    revision = revision or git_head_revision(project_root, require_clean=False)
    paths = relative_paths or deployment_source_paths(project_root, revision=revision)
    if not paths:
        raise RuntimeError("deployment source closure is empty")
    digest = hashlib.sha256(b"HAVRE-deployment-source-v1\0")
    for relative in paths:
        completed = subprocess.run(
            ["git", "show", f"{revision}:{relative}"],
            cwd=project_root,
            capture_output=True,
            timeout=30,
            check=False,
            creationflags=_creation_flags(),
        )
        if completed.returncode != 0:
            raise RuntimeError(f"cannot read committed deployment source: {relative}")
        payload = completed.stdout
        encoded = relative.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return f"sha256:{digest.hexdigest()}"


def deployment_file_snapshot_revision(
    root: Path, *, relative_paths: tuple[str, ...]
) -> str:
    if not relative_paths:
        raise RuntimeError("deployment source closure is empty")
    digest = hashlib.sha256(b"HAVRE-deployment-source-v1\0")
    for relative in sorted(relative_paths):
        payload = (root / relative).read_bytes()
        encoded = relative.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return f"sha256:{digest.hexdigest()}"
