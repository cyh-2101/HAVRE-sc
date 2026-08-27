"""Export an exact committed, privacy-minimized Stage 10 Docker context."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from services.api.source_provenance import (
    DEPLOYMENT_EXACT_FILES,
    DEPLOYMENT_PREFIXES,
    current_source_revision,
    deployment_file_snapshot_revision,
    git_head_revision,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
def _git(*arguments: str, text: bool = False):
    return subprocess.run(
        ["git", *arguments],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=text,
    ).stdout


def build_context(output: Path) -> dict[str, object]:
    output = output.resolve()
    if output.exists():
        raise FileExistsError("image context output must not already exist")
    revision = git_head_revision(PROJECT_ROOT)
    if current_source_revision(PROJECT_ROOT) != revision:
        raise ValueError("image context requires an exact clean committed source tree")
    paths = tuple(
        path
        for path in _git("ls-tree", "-r", "--name-only", revision, text=True).splitlines()
        if path in DEPLOYMENT_EXACT_FILES or path.startswith(DEPLOYMENT_PREFIXES)
    )
    output.mkdir(parents=True)
    hashes: dict[str, str] = {}
    for relative_path in paths:
        blob = _git("show", f"{revision}:{relative_path}")
        destination = output / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(blob)
        hashes[relative_path] = "sha256:" + hashlib.sha256(blob).hexdigest()
    manifest = {
        "schema_version": 1,
        "source_revision": revision,
        "source_snapshot": deployment_file_snapshot_revision(
            output, relative_paths=paths
        ),
        "files": hashes,
    }
    (output / ".havre-build-context-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    parents = sorted(
        {
            parent.as_posix() + "/"
            for path in paths
            for parent in Path(path).parents
            if parent.as_posix() != "."
        },
        key=lambda value: (value.count("/"), value),
    )
    exceptions = [*("!" + item for item in parents)]
    exceptions.extend("!" + item for item in paths)
    exceptions.append("!.havre-build-context-manifest.json")
    (output / ".dockerignore").write_text(
        "**\n" + "\n".join(exceptions) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_context(args.output), indent=2))


if __name__ == "__main__":
    main()
