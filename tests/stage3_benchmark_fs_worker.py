"""Terminable subprocess worker for the Stage 3 var-backed filesystem test."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path
from uuid import UUID

from evals.inference_benchmark import (
    NullResourceCollector,
    capture_environment_manifest,
)
from evals.inference_runner import (
    APPROVED_CONTROLLED_WORKLOAD_CONTENT_HASH,
    run_live_inference_benchmark,
    validate_approved_controlled_workload,
)
from mlsys.contracts.inference_benchmark import (
    ArtifactDigest,
    InferenceSystemUnderTestManifest,
    InferenceWorkloadManifest,
)
from mlsys.serving import DeterministicLocalProvider
from services.api.settings import Settings


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VAR_ROOT = PROJECT_ROOT / "var"
OWNED_PREFIX = ".stage3-benchmark-fs-test-"


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(
        os.path.abspath(right)
    )


def _is_link_like(path: Path) -> bool:
    try:
        details = path.lstat()
    except FileNotFoundError:
        return False
    reparse = bool(
        getattr(details, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )
    return reparse or path.is_symlink() or (
        hasattr(path, "is_junction") and path.is_junction()
    )


def _entry_exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _prepare_var_root(var_root: Path, *, project_root: Path) -> bool:
    if not var_root.is_absolute():
        raise ValueError("Stage 3 var root must be absolute")
    if not _same_path(var_root.parent, project_root):
        raise ValueError("Stage 3 var root must be the direct project var/ child")
    if _is_link_like(var_root):
        raise ValueError("Stage 3 var root cannot be a link or junction")
    created = not var_root.exists()
    _progress("ensure_var_root", path=str(var_root), missing=created)
    var_root.mkdir(exist_ok=True)
    if not var_root.is_dir() or _is_link_like(var_root):
        raise ValueError("Stage 3 var root is not a real directory")
    return created


def _validate_var_root_for_cleanup(
    var_root: Path, *, project_root: Path
) -> bool:
    if not var_root.is_absolute():
        raise ValueError("Stage 3 var root must be absolute")
    if not _same_path(var_root.parent, project_root):
        raise ValueError("Stage 3 var root must be the direct project var/ child")
    if not _entry_exists(var_root):
        _progress("cleanup_var_root_missing_noop", path=str(var_root))
        return False
    if _is_link_like(var_root):
        raise ValueError("cleanup refuses a var root link, junction, or reparse point")
    if not var_root.is_dir():
        raise ValueError("cleanup requires var root to be a real directory")
    return True


def _owned_root(raw: str, *, var_root: Path = VAR_ROOT) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        raise ValueError("owned test path must be absolute")
    absolute = Path(os.path.abspath(path))
    if not _same_path(absolute.parent, var_root) or not absolute.name.startswith(
        OWNED_PREFIX
    ):
        raise ValueError("owned test path must be one exact Stage 3 child of var/")
    UUID(absolute.name.removeprefix(OWNED_PREFIX))
    return absolute


def _progress(phase: str, **details: object) -> None:
    print(json.dumps({"kind": "progress", "phase": phase, **details}), flush=True)


def _manifest() -> InferenceSystemUnderTestManifest:
    provider = DeterministicLocalProvider
    return InferenceSystemUnderTestManifest(
        manifest_id="deterministic-local-benchmark-v1",
        provider_id=provider.provider_id,
        provider_class="local_test",
        execution_environment="local",
        model_version_id=provider.model_version_id,
        adapter_version_id=provider.adapter_version_id,
        provider_adapter_version_id=provider.provider_adapter_version_id,
        model_artifact_hash=None,
        model_artifact_hash_unavailable_reason=(
            "deterministic test double has no learned weight artifact"
        ),
        tokenizer_version_id=provider.tokenizer_version_id,
        serving_config_version=provider.serving_config_version,
        serving_engine=provider.serving_engine,
        serving_engine_version=provider.serving_engine_version,
        upstream_model_id="havre/deterministic-fixture",
        upstream_revision="deterministic-fixture-v1",
        architecture_family="fixed-response-test-double",
        parameter_count=None,
        parameter_count_unavailable_reason=(
            "deterministic test double has no learned parameters"
        ),
        weights_format="none",
        precision="not-applicable",
        quantization=None,
        context_limit=32_768,
        max_output_tokens=4_096,
        license_identifier="project-internal-test-fixture",
        license_notes="Not a learned model or production model candidate.",
        code_revision="3" * 40,
        artifacts=(ArtifactDigest(
            artifact_kind="provider_source",
            artifact_uri="repo:mlsys/serving/deterministic.py",
            content_hash="sha256:" + "1" * 64,
        ),),
    )


class _RecordingPersistence:
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


async def _run(
    owned_root: Path,
    *,
    var_root: Path = VAR_ROOT,
    project_root: Path = PROJECT_ROOT,
    simulate_block_seconds: float = 0,
) -> dict[str, object]:
    var_root_created = _prepare_var_root(var_root, project_root=project_root)
    _progress("create_owned_var_child", path=str(owned_root))
    if simulate_block_seconds:
        time.sleep(simulate_block_seconds)
    owned_root.mkdir(exist_ok=False)
    output_directory = owned_root / "reports"
    persistence = _RecordingPersistence()

    def provider_factory():
        return (
            DeterministicLocalProvider(),
            _manifest(),
            capture_environment_manifest(),
        )

    _progress("run_live_inference_benchmark")
    systems, compatibility = await run_live_inference_benchmark(
        settings=Settings.from_env(require_owner_api_token=False),
        output_directory=output_directory,
        code_revision="3" * 40,
        provider_factory=provider_factory,
        persistence=persistence,
        resource_collector=NullResourceCollector(),
    )
    _progress("verify_atomic_publication")
    expected_files = (
        "inference-systems.json",
        "inference-compatibility.json",
        "inference-workload.json",
        "inference-baseline-system.json",
    )
    files_present = all((output_directory / name).is_file() for name in expected_files)
    pending_paths = tuple(owned_root.glob(".reports.pending-*"))
    persisted_workload = InferenceWorkloadManifest.model_validate_json(
        (output_directory / "inference-workload.json").read_text(encoding="utf-8")
    )
    return {
        "status": systems.status,
        "schedule_concurrency": [item.concurrency for item in systems.schedule_summaries],
        "baseline_manifest_id": compatibility.baseline_manifest_id,
        "files_present": files_present,
        "pending_path_count": len(pending_paths),
        "workload_hash_matches": (
            persisted_workload.content_hash == systems.workload_content_hash
        ),
        "persistence_called": (
            persistence.workload_content_hash
            == APPROVED_CONTROLLED_WORKLOAD_CONTENT_HASH
        ),
        "var_root_created": var_root_created,
    }


def _cleanup(
    owned_root: Path,
    *,
    var_root: Path = VAR_ROOT,
    project_root: Path = PROJECT_ROOT,
) -> bool:
    # Revalidate on every deletion attempt. Do not rely on a check performed
    # before the benchmark because Windows directory entries may be replaced.
    validated_owned_root = _owned_root(str(owned_root), var_root=var_root)
    if not _validate_var_root_for_cleanup(
        var_root, project_root=project_root
    ):
        return False
    if not _entry_exists(validated_owned_root):
        _progress("cleanup_owned_path_missing_noop", path=str(validated_owned_root))
        return False
    if _is_link_like(validated_owned_root):
        raise ValueError(
            "cleanup refuses an owned root link, junction, or reparse point"
        )
    if not validated_owned_root.is_dir():
        raise ValueError("cleanup requires owned root to be a real directory")
    # Repeat the parent check immediately before the only recursive deletion.
    if not _validate_var_root_for_cleanup(
        var_root, project_root=project_root
    ):
        return False
    _progress("cleanup_exact_owned_path", path=str(validated_owned_root))
    shutil.rmtree(validated_owned_root)
    return True


def _create_directory_link(link: Path, target: Path) -> None:
    if sys.platform == "win32":
        completed = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "could not create controlled junction: "
                f"stdout={completed.stdout!r}; stderr={completed.stderr!r}"
            )
    else:
        link.symlink_to(target, target_is_directory=True)


def _remove_directory_link(link: Path) -> None:
    if not _entry_exists(link):
        return
    if sys.platform == "win32":
        link.rmdir()
    else:
        link.unlink()


def _selftest_cleanup_boundaries(owned_root: Path) -> dict[str, object]:
    _prepare_var_root(VAR_ROOT, project_root=PROJECT_ROOT)
    _progress("create_owned_cleanup_boundary_container", path=str(owned_root))
    owned_root.mkdir(exist_ok=False)

    var_link_project = owned_root / "var-link-project"
    var_link_project.mkdir()
    var_link_target = owned_root / "var-link-target"
    var_link_target.mkdir()
    var_link_sentinel = var_link_target / "sentinel.txt"
    var_link_sentinel.write_text("preserve", encoding="utf-8")
    linked_var = var_link_project / "var"
    linked_owned = var_link_target / f"{OWNED_PREFIX}{UUID(int=2)}"
    linked_owned.mkdir()
    _create_directory_link(linked_var, var_link_target)

    var_link_rejected = False
    try:
        _cleanup(
            linked_var / linked_owned.name,
            var_root=linked_var,
            project_root=var_link_project,
        )
    except ValueError:
        var_link_rejected = True
    var_link_preserved = var_link_sentinel.is_file() and linked_owned.is_dir()

    owned_link_project = owned_root / "owned-link-project"
    owned_link_project.mkdir()
    real_var = owned_link_project / "var"
    real_var.mkdir()
    owned_link_target = owned_root / "owned-link-target"
    owned_link_target.mkdir()
    owned_link_sentinel = owned_link_target / "sentinel.txt"
    owned_link_sentinel.write_text("preserve", encoding="utf-8")
    linked_owned_root = real_var / f"{OWNED_PREFIX}{UUID(int=3)}"
    _create_directory_link(linked_owned_root, owned_link_target)

    owned_link_rejected = False
    try:
        _cleanup(
            linked_owned_root,
            var_root=real_var,
            project_root=owned_link_project,
        )
    except ValueError:
        owned_link_rejected = True
    owned_link_preserved = (
        owned_link_sentinel.is_file() and owned_link_target.is_dir()
    )

    missing_var_project = owned_root / "missing-var-project"
    missing_var_project.mkdir()
    missing_var = missing_var_project / "var"
    missing_owned = missing_var / f"{OWNED_PREFIX}{UUID(int=4)}"
    missing_cleanup_performed = _cleanup(
        missing_owned,
        var_root=missing_var,
        project_root=missing_var_project,
    )
    missing_var_remained_absent = not _entry_exists(missing_var)

    # Teardown the two controlled directory links without traversing them.
    _remove_directory_link(linked_var)
    _remove_directory_link(linked_owned_root)
    return {
        "var_link_rejected": var_link_rejected,
        "var_link_preserved": var_link_preserved,
        "owned_link_rejected": owned_link_rejected,
        "owned_link_preserved": owned_link_preserved,
        "missing_cleanup_performed": missing_cleanup_performed,
        "missing_var_remained_absent": missing_var_remained_absent,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "operation",
        choices=(
            "run",
            "cleanup",
            "selftest-missing-var",
            "selftest-cleanup-boundaries",
        ),
    )
    parser.add_argument("--owned-root", required=True)
    parser.add_argument("--simulate-block-seconds", type=float, default=0)
    args = parser.parse_args()
    owned_root = _owned_root(args.owned_root)
    if args.operation == "cleanup":
        performed = _cleanup(owned_root)
        print(json.dumps({
            "kind": "result",
            "cleanup_complete": True,
            "cleanup_performed": performed,
        }), flush=True)
        return 0

    result: dict[str, object] | None = None
    run_error: BaseException | None = None
    try:
        if args.operation == "selftest-cleanup-boundaries":
            result = _selftest_cleanup_boundaries(owned_root)
        elif args.operation == "selftest-missing-var":
            _prepare_var_root(VAR_ROOT, project_root=PROJECT_ROOT)
            _progress("create_owned_clean_checkout_container", path=str(owned_root))
            owned_root.mkdir(exist_ok=False)
            simulated_project_root = owned_root / "clean-checkout"
            simulated_project_root.mkdir(exist_ok=False)
            missing_var_root = simulated_project_root / "var"
            nested_owned_root = _owned_root(
                str(missing_var_root / f"{OWNED_PREFIX}{UUID(int=1)}"),
                var_root=missing_var_root,
            )
            result = asyncio.run(_run(
                nested_owned_root,
                var_root=missing_var_root,
                project_root=simulated_project_root,
            ))
            result["missing_parent_var_exercised"] = True
        else:
            result = asyncio.run(_run(
                owned_root,
                simulate_block_seconds=max(0, args.simulate_block_seconds),
            ))
    except BaseException as error:
        run_error = error
    finally:
        try:
            _cleanup(owned_root)
            if _entry_exists(owned_root):
                raise RuntimeError("exact owned path still exists after cleanup")
        except BaseException as cleanup_error:
            print(json.dumps({
                "kind": "error",
                "phase": "cleanup_exact_owned_path",
                "error_type": type(cleanup_error).__name__,
                "message": str(cleanup_error),
            }), flush=True)
            return 1
    if run_error is not None:
        print(json.dumps({
            "kind": "error",
            "phase": "worker_run",
            "error_type": type(run_error).__name__,
            "message": str(run_error),
        }), flush=True)
        return 1
    if result is not None:
        result["owned_path_removed"] = True
    print(json.dumps({"kind": "result", **(result or {})}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
