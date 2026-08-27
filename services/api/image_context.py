"""Verify that a deployment image was copied from an exact committed context."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def _snapshot(root: Path, paths: set[str]) -> str:
    digest = hashlib.sha256(b"HAVRE-deployment-source-v1\0")
    for relative in sorted(paths):
        payload = (root / relative).read_bytes()
        encoded = relative.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return f"sha256:{digest.hexdigest()}"


def verify_image_context(
    *,
    root: Path,
    manifest_path: Path,
    expected_revision: str,
    expected_snapshot: str,
) -> dict[str, object]:
    root = root.resolve()
    manifest_path = manifest_path.resolve()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        payload.get("schema_version") != 1
        or payload.get("source_revision") != expected_revision
        or payload.get("source_snapshot") != expected_snapshot
        or not re.fullmatch(r"[0-9a-f]{40}", expected_revision)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", expected_snapshot)
        or not isinstance(payload.get("files"), dict)
    ):
        raise ValueError("image build context provenance is invalid")
    expected_files = payload["files"]
    actual_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
        and path.resolve() != manifest_path
        and path.name != ".dockerignore"
    }
    if actual_files != set(expected_files):
        raise ValueError("image build context file membership mismatch")
    for relative_path, expected_hash in expected_files.items():
        path = (root / relative_path).resolve()
        if root not in path.parents or path.is_symlink():
            raise ValueError("image build context path is unsafe")
        if _sha256(path) != expected_hash:
            raise ValueError(f"image build context hash mismatch: {relative_path}")
    if _snapshot(root, actual_files) != expected_snapshot:
        raise ValueError("image build context source snapshot mismatch")
    return payload


def main() -> None:
    import os

    root = Path("/app")
    payload = verify_image_context(
        root=root,
        manifest_path=root / ".havre-build-context-manifest.json",
        expected_revision=os.environ.get("HAVRE_SOURCE_REVISION", ""),
        expected_snapshot=os.environ.get("HAVRE_SOURCE_SNAPSHOT", ""),
    )
    (root / ".havre-source-revision").write_text(
        str(payload["source_revision"]) + "\n", encoding="utf-8"
    )
    (root / ".havre-source-snapshot").write_text(
        str(payload["source_snapshot"]) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
