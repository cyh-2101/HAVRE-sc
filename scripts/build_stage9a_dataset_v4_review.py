"""Build the repo-native Dataset v4 Product Owner freeze-review package."""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from companion.hashing import content_hash
from evals.inference_runner import current_source_revision
from mlsys.training.stage9a_dataset_v4 import (
    DATASET_ROOT,
    DATASET_VERSION,
    EXTERNAL_BUNDLE_HASH,
    OWNER_ALIGNMENT_PATH,
    audit_v4_data_boundaries,
    dataset_bundle_hash,
    load_and_verify_dataset,
)
from mlsys.training.stage9a_provenance import PROJECT_ROOT, STAGE9A_ROOT
from mlsys.training.stage9a_real import (
    EVIDENCE_ROOT,
    RENDERED_ROOT,
    RENDERER_VERSION,
    RUNS_ROOT,
    sha256_file,
    write_hashed_json,
    read_hashed_json,
)
from mlsys.training.stage9a_rubric_v4 import RUBRIC_VERSION, SCORER_VERSION


IMPORT_ROOT = STAGE9A_ROOT / "imports" / "HAVRE_STAGE9A_V4_CANDIDATE_1"
REPORT_ROOT = PROJECT_ROOT / "evals" / "reports" / "stage9a_dataset_v4_review_correction2"
REVIEW_MARKDOWN = REPORT_ROOT / "PRODUCT_OWNER_FREEZE_REVIEW.md"
REVIEW_MANIFEST = REPORT_ROOT / "review-manifest.json"
RENDERER_CHECK = REPORT_ROOT / "renderer-check.json"


def find_started_v4_runs(runs_root: Path) -> list[dict[str, object]]:
    """Treat successful and failed Gate D/formal records as started work."""
    started = []
    if not runs_root.exists():
        return started
    for run_dir in sorted(path for path in runs_root.iterdir() if path.is_dir()):
        for filename in ("training-report.json", "failure.json"):
            path = run_dir / filename
            if not path.exists():
                continue
            payload = read_hashed_json(path)
            if payload.get("run_id") == "gate-d-smoke-v4" or payload.get("seed") in {
                9201, 9202, 9203,
            }:
                started.append({
                    "run_directory": run_dir.name,
                    "record": filename,
                    "run_id": payload.get("run_id"),
                    "seed": payload.get("seed"),
                    "status": payload.get("status"),
                    "content_hash": payload["content_hash"],
                })
    return started


def _verify_import_package() -> dict[str, object]:
    manifest_path = IMPORT_ROOT / "PACKAGE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("dataset_bundle_hash") != EXTERNAL_BUNDLE_HASH:
        raise ValueError("import package binds the wrong dataset bundle")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("import package manifest has no file inventory")
    for name, expected in files.items():
        path = IMPORT_ROOT / name
        if not path.is_file():
            raise FileNotFoundError(path)
        if path.stat().st_size != expected["bytes"] or sha256_file(path) != expected["sha256"]:
            raise ValueError(f"import package file mismatch: {name}")
    return {
        "package_version": manifest["package_version"],
        "package_manifest_sha256": sha256_file(manifest_path),
        "verified_file_count": len(files),
        "po_authored_review_path": str((IMPORT_ROOT / "PO_REVIEW_v4.md").resolve()),
        "po_authored_review_sha256": files["PO_REVIEW_v4.md"]["sha256"],
    }


def build_review() -> dict[str, object]:
    if REVIEW_MANIFEST.exists() or REVIEW_MARKDOWN.exists():
        raise FileExistsError("immutable Dataset v4 review package already exists")
    if (EVIDENCE_ROOT / "dataset-v4-po-freeze-approval.json").exists():
        raise PermissionError("review package must be built before Product Owner freeze approval")
    if RENDERED_ROOT.exists():
        raise PermissionError("formal v4 rendered artifacts already exist")
    forbidden_runs = find_started_v4_runs(RUNS_ROOT)
    if forbidden_runs:
        raise PermissionError(f"v4 formal training paths already exist: {forbidden_runs}")

    package = _verify_import_package()
    splits = load_and_verify_dataset(DATASET_ROOT)
    audit = audit_v4_data_boundaries()
    renderer_check = read_hashed_json(RENDERER_CHECK)
    if (
        renderer_check.get("status") != "passed"
        or renderer_check.get("dataset_bundle_hash") != EXTERNAL_BUNDLE_HASH
        or renderer_check.get("formal_rendered_artifact_created") is not False
        or renderer_check.get("training_started") is not False
        or any(
            item.get("all_context_labels_masked") is not True
            or item.get("only_final_target_supervised") is not True
            for item in renderer_check.get("checks", [])
        )
    ):
        raise ValueError("bounded v4 exact-tokenizer renderer evidence is invalid")
    category_counts = {
        split: dict(sorted(Counter(item["category"] for item in items).items()))
        for split, items in splits.items()
    }
    manifest = {
        "schema_version": 1,
        "review_kind": "stage9a_dataset_v4_product_owner_freeze_gate",
        "status": "pending_product_owner_freeze",
        "decision": None,
        "dataset_version": DATASET_VERSION,
        "external_candidate_bundle_hash": EXTERNAL_BUNDLE_HASH,
        "repo_native_dataset_bundle_hash": dataset_bundle_hash(DATASET_ROOT),
        "repo_native_matches_external": dataset_bundle_hash(DATASET_ROOT) == EXTERNAL_BUNDLE_HASH,
        "canonical_dataset_root": str(DATASET_ROOT.resolve()),
        "counts": {split: len(items) for split, items in splits.items()},
        "category_counts": category_counts,
        "data_boundary_audit": audit,
        "import_package": package,
        "integration_contracts": {
            "renderer_version": RENDERER_VERSION,
            "supervision_policy": "final_havre_target_only",
            "freeze_approval_revalidated_by_every_rendered_consumer": True,
            "historical_assistant_context_label_masked": True,
            "selective_synthetic_memory": True,
            "proactive_scope": "wording_after_core_authorized_send_now_only",
            "rubric_version": RUBRIC_VERSION,
            "scorer_version": SCORER_VERSION,
            "reference_similarity_role": "diagnostic_only_not_primary_companion_quality",
            "renderer_check_content_hash": renderer_check["content_hash"],
            "renderer_check_sha256": sha256_file(RENDERER_CHECK),
        },
        "owner_alignment": {
            "path": str(OWNER_ALIGNMENT_PATH.resolve()),
            "permanently_evaluation_only": True,
            "training_eligible": False,
            "validation_for_training": False,
            "hyperparameter_tuning_eligible": False,
            "prompt_tuning_eligible": False,
            "synthetic_generation_input_eligible": False,
        },
        "gate": {
            "po_freeze_approval_present": False,
            "training_authorized": False,
            "formal_rendered_artifacts_present": False,
            "formal_seeds_started": False,
            "successful_and_failed_run_records_checked": True,
            "promotion_authorized": False,
            "deployment_authorized": False,
            "stage9b_authorized": False,
            "stage10_authorized": False,
        },
        "review_source_snapshot": current_source_revision(PROJECT_ROOT),
        "generated_at": datetime.now(UTC).isoformat(),
    }
    report = write_hashed_json(REVIEW_MANIFEST, manifest)
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    markdown = f"""# Stage 9A Dataset v4 Product Owner Freeze Review

Status: **PENDING PRODUCT OWNER FREEZE — TRAINING NOT AUTHORIZED**

- Dataset: `{DATASET_VERSION}`
- External candidate bundle: `{EXTERNAL_BUNDLE_HASH}`
- Repo-native bundle: `{report['repo_native_dataset_bundle_hash']}`
- Review manifest content hash: `{report['content_hash']}`
- Train / validation / sealed holdout: `{len(splits['train'])} / {len(splits['validation'])} / {len(splits['holdout'])}`
- Owner Alignment Set: 70 PRIVATE, local-only, permanently evaluation-only cases; excluded from every training and tuning input.
- Renderer: `{RENDERER_VERSION}`; full multi-turn context, historical assistant turns masked, final HAVRE target only supervised; every rendered consumer revalidates the exact Product Owner freeze approval.
- Memory: supplied synthetic memory only, selective by canonical flags, current conversation wins on conflict.
- Proactive: message wording only after governed Core has already authorized `SEND_NOW`.
- Evaluation: `{RUBRIC_VERSION}` property dimensions are primary; reference-token F1 is diagnostic only.

The complete Product Owner-authored review remains byte-preserved at:
`{package['po_authored_review_path']}`

Its SHA-256 is `{package['po_authored_review_sha256']}`.

## Product Owner decision

- [ ] ACCEPT exact v4 bundle for freeze and later formal rendering/training
- [ ] EDIT (requires a new externally authored immutable candidate)
- [ ] REJECT

Decision: __________

Product Owner: __________

Recorded at: __________

No approval file was created by this review builder. Seed 9201/9202 remain blocked until a separate exact-hash Product Owner freeze decision is recorded.
"""
    REVIEW_MARKDOWN.write_text(markdown, encoding="utf-8", newline="\n")
    return report


if __name__ == "__main__":
    print(json.dumps(build_review(), ensure_ascii=False, indent=2, sort_keys=True))
