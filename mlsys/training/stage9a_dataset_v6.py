"""Repo-native audit and local-only freeze for the Stage 9A v6 style candidate.

The external package is an authoring input, not a canonical dataset.  This
module deliberately keeps the mixed NORMAL/SYNTHETIC result under ``var`` and
records every exclusion instead of rewriting target voice.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from companion.hashing import content_hash
from mlsys.training.stage9a_dataset_v4 import (
    OWNER_ALIGNMENT_PATH,
    dataset_bundle_hash as v4_dataset_bundle_hash,
    load_and_verify_dataset as load_v4_dataset,
    load_and_verify_owner_alignment,
    sha256_file,
)
from mlsys.training.stage9a_provenance import PROJECT_ROOT, STAGE9A_ROOT


CANDIDATE_ID = "havre-stage9a-v6-style-first"
DATASET_ID = "stage9a-v6-style-first-canonical-v1"
DATASET_ROOT = STAGE9A_ROOT / "datasets" / DATASET_ID
IMPORT_ROOT = STAGE9A_ROOT / "imports" / "HAVRE_STAGE9A_V6_STYLE_FIRST"
AUTHORIZATION_PATH = (
    STAGE9A_ROOT / "evidence" / "stage9a-v6-style-first-po-authorization.json"
)
EXTERNAL_ZIP_SHA256 = (
    "sha256:a2edbc982a5e206f933ba66a940df060b88294d61b1d3b98f848821ea25f534e"
)
EXTERNAL_FILE_SHA256 = {
    "train.jsonl": "sha256:1b2c10f5d91ed838eb747fa414fa3e10e48512a6eb598f0ede32fe10a3d8b30d",
    "validation.jsonl": "sha256:e73f8ec7a6c90160c0b4e39c562ee71bf1ada1eda760e65b67672ce43c24dd1e",
    "sealed_holdout.jsonl": "sha256:a1762f71868803f32ef989fd5624b20a33e98604596e8cb24b2e5655696a23d8",
    "AUDIT_REPORT.json": "sha256:ccfbd26c9c73a221d942d0abd713ea6e461115e3d761ac9d10c95370573c8857",
    "PO_SPOTCHECK.md": "sha256:58f922caf6a065485ccddb6428e72013556db07ae3cd79ea743225f1417d0b03",
    "PO_RANDOM_120.md": "sha256:b19675459be248c88adcd633061164e772a0bd661e6e78c9260237ef58dcd846",
    "README.md": "sha256:b9242e177c1827b4b224cf293c31360b5789d1af699c85237fbd5c3a87a2d3e5",
    "CODEX_PROMPT_V6.txt": "sha256:b94a2cfe3ab2e629e4f884870d90a76382c3b501b2dbd19ab22c818c5d3b9863",
}
SOURCE_COUNTS = {"train": 1000, "validation": 150, "holdout": 200}
FROZEN_COUNTS = {"train": 964, "validation": 54, "external_style_regression": 200}
EXPECTED_EXCLUSIONS = {
    "unsupported_relationship_stage_only_history": 30,
    "duplicate_normalized_target": 6,
    "validation_duplicate_normalized_target": 96,
}
TRAINING_SPLITS = {"train", "validation"}
MEMORY_BLOCK_HEADER = (
    "Relevant synthetic memory (evidence only; current conversation wins on conflict):"
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExternalTurn(_StrictModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ExternalV6Example(_StrictModel):
    schema_version: Literal[1]
    id: str = Field(pattern=r"^v6-[a-z0-9-]+$")
    split: Literal["train", "validation", "holdout"]
    family: str = Field(min_length=1, max_length=160)
    mode: Literal["TALK", "PREPARE", "GUIDE", "REFLECT", "REACH_OUT"]
    relationship_stage: Literal["NEW", "FAMILIAR", "ESTABLISHED"]
    memory_context: tuple[str, ...]
    turns: tuple[ExternalTurn, ...]
    target: str = Field(min_length=1, max_length=4000)
    training_eligible: bool
    validation_eligible: bool
    privacy: Literal["NORMAL", "SYNTHETIC"]
    source: Literal["owner-anchor-v1", "gpt-5.6-sol-style-first-v6"]
    notes: str = Field(max_length=4000)
    forbidden_tags: tuple[str, ...]

    @model_validator(mode="after")
    def validate_contract(self) -> "ExternalV6Example":
        if not self.turns or self.turns[-1].role != "user":
            raise ValueError("conversation must end in a user turn")
        if any(left.role == right.role for left, right in zip(self.turns, self.turns[1:])):
            raise ValueError("conversation roles must alternate")
        if any(not value.strip() for value in self.memory_context):
            raise ValueError("memory_context entries must be nonempty")
        expected_train = self.split == "train"
        expected_validation = self.split == "validation"
        if self.training_eligible is not expected_train:
            raise ValueError("external training eligibility disagrees with split")
        if self.validation_eligible is not expected_validation:
            raise ValueError("external validation eligibility disagrees with split")
        if (self.source == "owner-anchor-v1") is not (self.privacy == "NORMAL"):
            raise ValueError("owner provenance and NORMAL privacy must agree")
        return self


class CanonicalV6Example(_StrictModel):
    schema_version: Literal[3]
    dataset_id: Literal[DATASET_ID]
    example_id: str = Field(pattern=r"^v6-[a-z0-9-]+$")
    split: Literal["train", "validation", "external_style_regression"]
    source_line: int = Field(ge=1)
    source_kind: Literal["owner_authored_anchor", "synthetic_external_candidate"]
    source_ref: str
    source_file_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    external_zip_sha256: Literal[EXTERNAL_ZIP_SHA256]
    privacy_class: Literal["NORMAL", "SYNTHETIC"]
    contains_user_data: bool
    local_only: Literal[True]
    optimizer_eligible: bool
    validation_eligible: bool
    evaluation_only: bool
    system_text: str = Field(min_length=1, max_length=8000)
    family: str = Field(min_length=1, max_length=160)
    mode: Literal["talk", "prepare", "guide", "reflect", "reach_out"]
    relationship_stage: Literal["new", "familiar", "established"]
    relationship_stage_is_runtime_history_evidence: Literal[False]
    messages: tuple[ExternalTurn, ...]
    input_text: str = Field(min_length=1, max_length=4000)
    expected_text: str = Field(min_length=1, max_length=4000)
    inject_memory_context: bool
    memory_context: str = Field(max_length=4000)
    use_memory_in_training: bool
    author_note: str = Field(max_length=4000)
    forbidden_tags: tuple[str, ...]
    style_regression_cluster_id: str | None
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_contract(self) -> "CanonicalV6Example":
        is_train = self.split == "train"
        is_validation = self.split == "validation"
        is_regression = self.split == "external_style_regression"
        if self.optimizer_eligible is not is_train:
            raise ValueError("optimizer eligibility disagrees with split")
        if self.validation_eligible is not is_validation:
            raise ValueError("validation eligibility disagrees with split")
        if self.evaluation_only is not is_regression:
            raise ValueError("evaluation-only boundary disagrees with split")
        if self.contains_user_data is not (self.privacy_class == "NORMAL"):
            raise ValueError("privacy and user-data marker disagree")
        if not self.messages or self.messages[-1].content != self.input_text:
            raise ValueError("input_text must bind the final user message")
        if self.messages[-1].role != "user":
            raise ValueError("canonical conversation must end in user")
        if self.inject_memory_context != bool(self.memory_context.strip()):
            raise ValueError("memory injection marker disagrees with context")
        expected_memory_use = self.inject_memory_context and self.split in TRAINING_SPLITS
        if self.use_memory_in_training is not expected_memory_use:
            raise ValueError("training memory-use marker disagrees with split")
        if is_regression != bool(self.style_regression_cluster_id):
            raise ValueError("style regression cluster boundary is incomplete")
        material = self.model_dump(mode="json", exclude={"content_hash"})
        if content_hash(material) != self.content_hash:
            raise ValueError("canonical example content hash mismatch")
        return self


class V6Authorization(_StrictModel):
    schema_version: Literal[1]
    candidate_id: Literal[CANDIDATE_ID]
    external_zip_sha256: Literal[EXTERNAL_ZIP_SHA256]
    decision: Literal["authorize_repo_native_audit_freeze_and_candidate_training"]
    approved_by: Literal["Product Owner"]
    owner_anchors_training_authorized: Literal[True]
    exact_qwen3_8b_fresh_base_authorized: Literal[True]
    private_daily_chat_bulk_training_authorized: Literal[False]
    stage9b_authorized: Literal[False]
    promotion_authorized: Literal[False]
    deployment_authorized: Literal[False]
    authorized_at: str
    scope_note: str
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_hash(self) -> "V6Authorization":
        material = self.model_dump(mode="json", exclude={"content_hash"})
        if content_hash(material) != self.content_hash:
            raise ValueError("authorization content hash mismatch")
        return self


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _load_jsonl(path: Path) -> list[ExternalV6Example]:
    rows: list[ExternalV6Example] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            raise ValueError(f"blank JSONL member at {path}:{line_number}")
        rows.append(ExternalV6Example.model_validate_json(line))
    return rows


def _verify_external_package(root: Path) -> dict[str, list[ExternalV6Example]]:
    if root.resolve() != IMPORT_ROOT.resolve():
        raise ValueError("formal v6 freeze only accepts the exact local import root")
    for name, expected in EXTERNAL_FILE_SHA256.items():
        path = root / name
        if not path.is_file() or _file_hash(path) != expected:
            raise ValueError(f"external candidate file hash mismatch: {name}")
    manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
    if manifest.get("candidate_id") != CANDIDATE_ID or manifest.get("counts") != SOURCE_COUNTS:
        raise ValueError("external manifest identity/count mismatch")
    for name, expected in EXTERNAL_FILE_SHA256.items():
        if name == "MANIFEST.json":
            continue
        claimed = manifest.get("hashes", {}).get(name)
        if claimed != expected.removeprefix("sha256:"):
            raise ValueError(f"external manifest hash claim mismatch: {name}")
    result = {
        "train": _load_jsonl(root / "train.jsonl"),
        "validation": _load_jsonl(root / "validation.jsonl"),
        "holdout": _load_jsonl(root / "sealed_holdout.jsonl"),
    }
    for split, rows in result.items():
        if len(rows) != SOURCE_COUNTS[split] or any(row.split != split for row in rows):
            raise ValueError(f"external split count/membership mismatch: {split}")
    ids = [row.id for rows in result.values() for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("external IDs are not globally unique")
    return result


def _system_text() -> tuple[str, str]:
    v4 = load_v4_dataset()
    values = {item["system_text"] for rows in v4.values() for item in rows}
    if len(values) != 1:
        raise ValueError("accepted v4 dataset does not have one stable system instruction")
    return next(iter(values)), v4_dataset_bundle_hash()


def _verify_owner_anchor_lineage(rows: Iterable[ExternalV6Example]) -> str:
    owner = load_and_verify_owner_alignment(OWNER_ALIGNMENT_PATH)
    cases = {case["case_id"]: case for case in owner["cases"]}
    anchors = [row for row in rows if row.source == "owner-anchor-v1"]
    expected_numbers = set(range(1, 71)) - {34}
    actual_numbers = {int(row.id.rsplit("-", 1)[1]) for row in anchors}
    if actual_numbers != expected_numbers or len(anchors) != 69:
        raise ValueError("v6 owner-anchor membership differs from approved 69-of-70 lineage")
    for row in anchors:
        number = int(row.id.rsplit("-", 1)[1])
        case = cases[f"owner-anchor-{number:03d}"]
        messages = [message.model_dump(mode="json") for message in row.turns]
        if messages != case["messages"] or row.target != case["expected_text"]:
            raise ValueError(f"owner anchor changed from OA70 lineage: {row.id}")
    return sha256_file(OWNER_ALIGNMENT_PATH)


def _deduplicate_training(
    rows: list[ExternalV6Example],
) -> tuple[list[tuple[int, ExternalV6Example]], list[dict[str, Any]]]:
    retained: list[tuple[int, ExternalV6Example]] = []
    exclusions: list[dict[str, Any]] = []
    candidates: list[tuple[int, ExternalV6Example]] = []
    for line, row in enumerate(rows, 1):
        if row.id.startswith("v6-relpair-") and row.id.endswith("-long"):
            exclusions.append({
                "example_id": row.id,
                "source_split": "train",
                "source_line": line,
                "reason": "unsupported_relationship_stage_only_history",
                "target_rewritten": False,
            })
        else:
            candidates.append((line, row))
    by_target: dict[str, list[tuple[int, ExternalV6Example]]] = defaultdict(list)
    for member in candidates:
        by_target[_normalize(member[1].target)].append(member)
    for group in by_target.values():
        owner = [member for member in group if member[1].source == "owner-anchor-v1"]
        keep = owner[0] if owner else group[0]
        retained.append(keep)
        for line, row in group:
            if row.id == keep[1].id:
                continue
            exclusions.append({
                "example_id": row.id,
                "source_split": "train",
                "source_line": line,
                "reason": "duplicate_normalized_target",
                "retained_example_id": keep[1].id,
                "target_rewritten": False,
            })
    retained.sort(key=lambda item: item[0])
    return retained, exclusions


def _deduplicate_validation(
    rows: list[ExternalV6Example],
) -> tuple[list[tuple[int, ExternalV6Example]], list[dict[str, Any]]]:
    seen: dict[str, str] = {}
    retained: list[tuple[int, ExternalV6Example]] = []
    exclusions: list[dict[str, Any]] = []
    for line, row in enumerate(rows, 1):
        normalized = _normalize(row.target)
        if normalized not in seen:
            seen[normalized] = row.id
            retained.append((line, row))
        else:
            exclusions.append({
                "example_id": row.id,
                "source_split": "validation",
                "source_line": line,
                "reason": "validation_duplicate_normalized_target",
                "retained_example_id": seen[normalized],
                "target_rewritten": False,
            })
    return retained, exclusions


def _memory_text(values: tuple[str, ...]) -> str:
    return "\n".join(f"- {value.strip()}" for value in values)


def _canonicalize(
    *,
    row: ExternalV6Example,
    source_line: int,
    split: Literal["train", "validation", "external_style_regression"],
    source_file: str,
    system_text: str,
) -> dict[str, Any]:
    memory = _memory_text(row.memory_context)
    cluster = None
    if split == "external_style_regression":
        cluster = "target-" + hashlib.sha256(_normalize(row.target).encode("utf-8")).hexdigest()[:16]
    material: dict[str, Any] = {
        "schema_version": 3,
        "dataset_id": DATASET_ID,
        "example_id": row.id,
        "split": split,
        "source_line": source_line,
        "source_kind": (
            "owner_authored_anchor"
            if row.source == "owner-anchor-v1"
            else "synthetic_external_candidate"
        ),
        "source_ref": f"external-candidate://{CANDIDATE_ID}/{source_file}#L{source_line}",
        "source_file_sha256": EXTERNAL_FILE_SHA256[source_file],
        "external_zip_sha256": EXTERNAL_ZIP_SHA256,
        "privacy_class": row.privacy,
        "contains_user_data": row.privacy == "NORMAL",
        "local_only": True,
        "optimizer_eligible": split == "train",
        "validation_eligible": split == "validation",
        "evaluation_only": split == "external_style_regression",
        "system_text": system_text,
        "family": row.family,
        "mode": row.mode.casefold(),
        "relationship_stage": row.relationship_stage.casefold(),
        "relationship_stage_is_runtime_history_evidence": False,
        "messages": [message.model_dump(mode="json") for message in row.turns],
        "input_text": row.turns[-1].content,
        "expected_text": row.target,
        "inject_memory_context": bool(memory),
        "memory_context": memory,
        "use_memory_in_training": bool(memory) and split in TRAINING_SPLITS,
        "author_note": row.notes,
        "forbidden_tags": list(row.forbidden_tags),
        "style_regression_cluster_id": cluster,
    }
    material["content_hash"] = content_hash(material)
    return CanonicalV6Example.model_validate(material).model_dump(mode="json")


def _cross_split_exact_check(splits: dict[str, list[dict[str, Any]]]) -> None:
    for left, right in (("train", "validation"), ("train", "external_style_regression"), ("validation", "external_style_regression")):
        for field in ("input_text", "expected_text"):
            a = {_normalize(row[field]) for row in splits[left]}
            b = {_normalize(row[field]) for row in splits[right]}
            if a & b:
                raise ValueError(f"cross-split normalized {field} overlap: {left}/{right}")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def load_authorization(path: Path = AUTHORIZATION_PATH) -> dict[str, Any]:
    return V6Authorization.model_validate_json(path.read_text(encoding="utf-8")).model_dump(mode="json")


def freeze_dataset(
    *,
    import_root: Path = IMPORT_ROOT,
    output_root: Path = DATASET_ROOT,
    authorization_path: Path = AUTHORIZATION_PATH,
) -> dict[str, Any]:
    """Audit and freeze the exact approved candidate into a new immutable root."""
    authorization = load_authorization(authorization_path)
    if output_root.exists():
        raise FileExistsError(f"immutable v6 dataset already exists: {output_root}")
    external = _verify_external_package(import_root)
    oa70_hash = _verify_owner_anchor_lineage(external["train"])
    system_text, parent_v4_hash = _system_text()
    train_members, train_exclusions = _deduplicate_training(external["train"])
    validation_members, validation_exclusions = _deduplicate_validation(external["validation"])
    holdout_members = list(enumerate(external["holdout"], 1))
    exclusions = train_exclusions + validation_exclusions
    reason_counts = Counter(item["reason"] for item in exclusions)
    if dict(reason_counts) != EXPECTED_EXCLUSIONS:
        raise ValueError(f"v6 exclusion boundary drifted: {dict(reason_counts)}")
    splits = {
        "train": [
            _canonicalize(row=row, source_line=line, split="train", source_file="train.jsonl", system_text=system_text)
            for line, row in train_members
        ],
        "validation": [
            _canonicalize(row=row, source_line=line, split="validation", source_file="validation.jsonl", system_text=system_text)
            for line, row in validation_members
        ],
        "external_style_regression": [
            _canonicalize(row=row, source_line=line, split="external_style_regression", source_file="sealed_holdout.jsonl", system_text=system_text)
            for line, row in holdout_members
        ],
    }
    counts = {name: len(rows) for name, rows in splits.items()}
    if counts != FROZEN_COUNTS:
        raise ValueError(f"v6 frozen counts drifted: {counts}")
    if sum(row["contains_user_data"] for row in splits["train"]) != 69:
        raise ValueError("all and only the 69 approved owner anchors must remain in train")
    if len({_normalize(row["expected_text"]) for row in splits["train"]}) != len(splits["train"]):
        raise ValueError("train targets are not unique after repair")
    if len({_normalize(row["expected_text"]) for row in splits["validation"]}) != len(splits["validation"]):
        raise ValueError("validation targets are not unique after repair")
    cluster_counts = Counter(row["style_regression_cluster_id"] for row in splits["external_style_regression"])
    if len(cluster_counts) != 20 or set(cluster_counts.values()) != {10}:
        raise ValueError("external holdout must be recorded as 20 clusters of 10, not 200 independent cases")
    _cross_split_exact_check(splits)

    output_root.mkdir(parents=True)
    for name, rows in splits.items():
        _write_jsonl(output_root / f"{name}.jsonl", rows)
    exclusions_payload = {
        "schema_version": 1,
        "dataset_id": DATASET_ID,
        "target_rewrites": 0,
        "reason_counts": dict(sorted(reason_counts.items())),
        "members": sorted(exclusions, key=lambda item: (item["source_split"], item["source_line"])),
    }
    exclusions_payload["content_hash"] = content_hash(exclusions_payload)
    _write_json(output_root / "exclusions.json", exclusions_payload)
    member_files = {
        f"{name}.jsonl": _file_hash(output_root / f"{name}.jsonl")
        for name in splits
    }
    member_files["exclusions.json"] = _file_hash(output_root / "exclusions.json")
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "dataset_id": DATASET_ID,
        "candidate_id": CANDIDATE_ID,
        "status": "finalized_local_candidate_training_input",
        "candidate_only": True,
        "promotion_authorized": False,
        "deployment_authorized": False,
        "stage9b_authorized": False,
        "contains_user_data": True,
        "local_only": True,
        "external_zip_sha256": EXTERNAL_ZIP_SHA256,
        "external_file_sha256": EXTERNAL_FILE_SHA256,
        "authorization_hash": authorization["content_hash"],
        "owner_alignment_v1_file_sha256": oa70_hash,
        "owner_alignment_v1_role": "historical_regression_and_training_lineage_not_blind_final",
        "parent_v4_dataset_bundle_hash": parent_v4_hash,
        "system_text_hash": content_hash({"system_text": system_text}),
        "counts": counts,
        "privacy_counts": {
            name: dict(sorted(Counter(row["privacy_class"] for row in rows).items()))
            for name, rows in splits.items()
        },
        "source_counts": {
            name: dict(sorted(Counter(row["source_kind"] for row in rows).items()))
            for name, rows in splits.items()
        },
        "mode_counts": {
            name: dict(sorted(Counter(row["mode"] for row in rows).items()))
            for name, rows in splits.items()
        },
        "memory_injected_counts": {
            name: sum(row["inject_memory_context"] for row in rows)
            for name, rows in splits.items()
        },
        "exclusion_counts": dict(sorted(reason_counts.items())),
        "target_rewrites": 0,
        "external_style_regression_effective_clusters": 20,
        "external_style_regression_cluster_weighting_required": True,
        "external_style_regression_is_unseen_final": False,
        "limitations": [
            "Validation is 54 unique TALK targets and cannot select mode-switching or hard-capability quality alone.",
            "External style regression has 200 rows but only 20 target clusters of size 10.",
            "A new post-plan unseen evaluation remains required before any promotion decision.",
            "Owner-authored NORMAL anchors make every derived adapter LOCAL_ONLY even though no private daily chat is included.",
        ],
        "member_files": member_files,
        "creator_code_revision": "working-tree-recorded-at-training-closure",
    }
    manifest["content_hash"] = content_hash(manifest)
    _write_json(output_root / "manifest.json", manifest)
    return manifest


def load_and_verify_dataset(root: Path = DATASET_ROOT) -> dict[str, list[dict[str, Any]]]:
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    claimed = manifest.pop("content_hash")
    if content_hash(manifest) != claimed:
        raise ValueError("v6 manifest content hash mismatch")
    manifest["content_hash"] = claimed
    if manifest.get("dataset_id") != DATASET_ID or manifest.get("counts") != FROZEN_COUNTS:
        raise ValueError("v6 manifest identity/count mismatch")
    load_authorization()
    splits: dict[str, list[dict[str, Any]]] = {}
    for split in FROZEN_COUNTS:
        path = root / f"{split}.jsonl"
        if _file_hash(path) != manifest["member_files"][path.name]:
            raise ValueError(f"v6 member file hash mismatch: {path.name}")
        rows = [
            CanonicalV6Example.model_validate_json(line).model_dump(mode="json")
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if len(rows) != FROZEN_COUNTS[split]:
            raise ValueError(f"v6 member count mismatch: {split}")
        splits[split] = rows
    _cross_split_exact_check(splits)
    return splits


def dataset_bundle_hash(root: Path = DATASET_ROOT) -> str:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    material = {
        "dataset_id": DATASET_ID,
        "manifest_sha256": _file_hash(root / "manifest.json"),
        "member_files": manifest["member_files"],
    }
    return content_hash(material)


def assert_local_only_path(path: Path) -> None:
    resolved = path.resolve()
    if STAGE9A_ROOT.resolve() not in resolved.parents:
        raise ValueError("mixed NORMAL v6 artifact must remain below local var/stage9a")
    try:
        resolved.relative_to(PROJECT_ROOT.resolve())
    except ValueError as error:
        raise ValueError("v6 artifact left the owner-controlled repository root") from error
