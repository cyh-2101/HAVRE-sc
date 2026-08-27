"""Fail-closed validation for immutable Stage 10 deployment image references."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from companion.operations import ReleaseManifest
from services.api.source_provenance import (
    deployment_source_paths,
    deployment_source_snapshot_revision,
    git_head_revision,
)


IMAGE_REFERENCE = re.compile(
    r"^[^\s@]+@(?P<digest>sha256:[0-9a-f]{64})$"
)


def resolve_release_manifest_path(value: str, project_root: Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = project_root / "deploy" / path
    return path.resolve()


def verify_image_references(
    *,
    api_image: str,
    api_image_digest: str,
    postgres_image: str,
    caddy_image: str,
    operations_image: str,
) -> dict[str, str]:
    values = {
        "api": api_image,
        "postgres": postgres_image,
        "caddy": caddy_image,
        "operations": operations_image,
    }
    digests = {}
    for name, reference in values.items():
        match = IMAGE_REFERENCE.fullmatch(reference)
        if match is None:
            raise ValueError(f"{name} image must be an immutable digest reference")
        digests[name] = match.group("digest")
    if digests["api"] != api_image_digest:
        raise ValueError("API image reference and digest disagree")
    return {f"{name}_image": values[name] for name in sorted(values)}


def _tracked_paths_clean(project_root: Path, paths: tuple[str, ...]) -> bool:
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no", "--", *paths],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return status.returncode == 0 and not status.stdout.strip()


def verify_release_source_binding(
    *, release_manifest_path: Path, project_root: Path
) -> dict[str, str]:
    override_names = (
        "compose.override.yaml",
        "compose.override.yml",
        "docker-compose.override.yaml",
        "docker-compose.override.yml",
    )
    unexpected_overrides = [
        candidate
        for parent in (project_root, project_root / "deploy")
        for name in override_names
        for candidate in (parent / name,)
        if candidate.exists()
    ]
    if unexpected_overrides:
        raise ValueError("untracked or implicit Compose override is forbidden")
    manifest = ReleaseManifest.model_validate_json(
        release_manifest_path.read_text(encoding="utf-8")
    )
    revision = git_head_revision(project_root, require_clean=False)
    paths = deployment_source_paths(project_root, revision=revision)
    if not _tracked_paths_clean(project_root, paths):
        raise ValueError("host deployment source has tracked changes")
    observed = deployment_source_snapshot_revision(
        project_root, revision=revision, relative_paths=paths
    )
    component = next(
        (item for item in manifest.components if item.component == "companion_core"),
        None,
    )
    if manifest.source_revision != revision:
        raise ValueError("release source revision does not match host deployment source")
    if component is None or component.artifact_hash != observed:
        raise ValueError("host deployment source bytes do not match the release manifest")
    return {
        "release_manifest_hash": manifest.content_hash,
        "source_revision": revision,
        "deployment_source_snapshot": observed,
    }


def main() -> None:
    result = verify_image_references(
        api_image=os.environ.get("HAVRE_API_IMAGE", ""),
        api_image_digest=os.environ.get("HAVRE_API_IMAGE_DIGEST", ""),
        postgres_image=os.environ.get("HAVRE_POSTGRES_IMAGE", ""),
        caddy_image=os.environ.get("HAVRE_CADDY_IMAGE", ""),
        operations_image=os.environ.get("HAVRE_OPERATIONS_IMAGE", ""),
    )
    manifest_path = os.environ.get("HAVRE_RELEASE_MANIFEST_PATH")
    if not manifest_path:
        raise ValueError("HAVRE_RELEASE_MANIFEST_PATH is required")
    project_root = Path(__file__).resolve().parents[1]
    result.update(
        verify_release_source_binding(
            release_manifest_path=resolve_release_manifest_path(
                manifest_path, project_root
            ),
            project_root=project_root,
        )
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
