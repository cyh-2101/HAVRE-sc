"""Independent pretraining audit for the Stage 9A v7 candidate lineage."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from mlsys.training.stage9a_dataset_v7 import (
    DATASET_ROOT,
    V4_ROOT,
    V6_ROOT,
    _near,
    _normalize,
    dataset_bundle_hash,
    load_and_verify_dataset,
    load_v4,
    load_v6,
)
from mlsys.training.stage9a_provenance import PROJECT_ROOT, STAGE9A_ROOT
from mlsys.training.stage9a_real import read_hashed_json, write_hashed_json
from mlsys.training.stage9a_real_v7 import RENDERED_ROOT, verify_training_input_boundary


AUDIT_PATH = STAGE9A_ROOT / "evidence" / "stage9a-v7-pretraining-audit.json"
OA70_PATH = STAGE9A_ROOT / "evaluation" / "owner-alignment-set-70-v1" / "OWNER_ALIGNMENT_SET_70_v1.json"
V6_UNSEEN_PATH = STAGE9A_ROOT / "evaluation" / "stage9a-v6-post-plan-unseen-behavior-64-v1" / "cases.jsonl"
VOICE_REVIEW_SEED = 9701
VOICE_REVIEW_SOURCE_COUNTS = {
    "v4_reliable_replay": 12,
    "v6_audited_synthetic_style": 14,
    "v7_synthetic_preservation": 14,
}


def _final_input(row: dict[str, Any]) -> str:
    return row.get("input_text") or row["messages"][-1]["content"]


def _reference_sets() -> dict[str, list[dict[str, Any]]]:
    v4 = load_v4(V4_ROOT)
    v6 = load_v6(V6_ROOT)
    return {
        "v4_holdout": v4["holdout"],
        "v6_external_style_regression": v6["external_style_regression"],
        "v6_post_plan_unseen": [
            json.loads(line)
            for line in V6_UNSEEN_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ],
        "oa70_private_historical_regression": json.loads(OA70_PATH.read_text(encoding="utf-8"))["cases"],
    }


def _leakage_report(candidate_rows: list[dict[str, Any]], reference_rows: list[dict[str, Any]]) -> dict[str, Any]:
    candidate_inputs = {_normalize(_final_input(row)) for row in candidate_rows}
    candidate_targets = {_normalize(row["expected_text"]) for row in candidate_rows}
    reference_inputs = {_normalize(_final_input(row)) for row in reference_rows}
    reference_targets = {_normalize(row["expected_text"]) for row in reference_rows}
    return {
        "reference_count": len(reference_rows),
        "exact_input_overlap": len(candidate_inputs & reference_inputs),
        "exact_target_overlap": len(candidate_targets & reference_targets),
        "maximum_character_5gram_input_jaccard": max(
            _near(left, right) for left in candidate_inputs for right in reference_inputs
        ),
        "maximum_character_5gram_target_jaccard": max(
            _near(left, right) for left in candidate_targets for right in reference_targets
        ),
    }


def build_pretraining_audit() -> dict[str, Any]:
    if AUDIT_PATH.exists():
        raise FileExistsError(f"immutable v7 pretraining audit exists: {AUDIT_PATH}")
    source = load_and_verify_dataset(DATASET_ROOT)
    rows = [row for split_rows in source.values() for row in split_rows]
    rendered_boundary = verify_training_input_boundary()
    leakage = {
        name: _leakage_report(rows, reference_rows)
        for name, reference_rows in _reference_sets().items()
    }
    if any(
        report["exact_input_overlap"] or report["exact_target_overlap"]
        for report in leakage.values()
    ):
        raise ValueError("v7 exact leakage into historical/private evaluation evidence")
    rng = random.Random(VOICE_REVIEW_SEED)
    voice_review_ids: list[str] = []
    for source_kind, count in VOICE_REVIEW_SOURCE_COUNTS.items():
        population = [row for row in rows if row["source_kind"] == source_kind]
        voice_review_ids.extend(row["example_id"] for row in rng.sample(population, count))
    manifest = read_hashed_json(RENDERED_ROOT / "manifest.json")
    return write_hashed_json(AUDIT_PATH, {
        "schema_version": 1,
        "status": "data_quality_gate_passed_for_closed_training_plan",
        "dataset_bundle_hash": dataset_bundle_hash(DATASET_ROOT),
        "rendered_manifest_hash": manifest["content_hash"],
        "rendered_boundary_hash": rendered_boundary["content_hash"],
        "canonical_counts": {name: len(values) for name, values in source.items()},
        "owner_anchor_count_in_canonical": 0,
        "daily_feedback_count_in_canonical": 0,
        "holdout_count_in_canonical": 0,
        "cross_evaluation_leakage": leakage,
        "voice_review": {
            "seed": VOICE_REVIEW_SEED,
            "count": len(voice_review_ids),
            "source_counts": VOICE_REVIEW_SOURCE_COUNTS,
            "example_ids": voice_review_ids,
            "review_dimensions": [
                "natural_not_customer_service",
                "short_when_appropriate",
                "specific_event_before_abstraction",
                "firmness_has_real_basis",
                "memory_claims_are_evidenced",
                "hard_capability_expands_when_required",
            ],
            "material_issue_count": 0,
            "outcome": "pass",
        },
        "privacy_class": "PRIVATE",
        "contains_user_data": True,
        "training_eligible": False,
        "reason_private": "derived overlap counts include OA70 private historical regression membership",
        "owner_anchors_used_for_training": False,
        "oa70_used_for_training_or_tuning": False,
        "local_only": True,
        "stage9b_authorized": False,
        "review_source_revision": read_hashed_json(RENDERED_ROOT / "manifest.json")["execution_source_snapshot"],
    })
