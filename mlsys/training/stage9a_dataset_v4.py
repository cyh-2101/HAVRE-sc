"""Static Product Owner-authored Stage 9A v4 dataset and Owner Alignment contracts.

The canonical JSON artifacts are imported byte-for-byte. This module validates
them; it never generates or rewrites their content.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from companion.hashing import canonical_json, content_hash
from mlsys.training.stage9a_provenance import PROJECT_ROOT, STAGE9A_ROOT


DATASET_VERSION = "stage9a-havre-companion-v4-candidate-1"
ARTIFACT_VERSION = "v4"
EXTERNAL_BUNDLE_HASH = "sha256:13fa5a62ec6edc571c51468a8a07c2c362744236de0b418a0d9c543de0b586c4"
SPLIT_COUNTS = {"train": 300, "validation": 60, "holdout": 120}
TRAINING_SPLITS = ("train", "validation")
DATASET_ROOT = Path(__file__).resolve().parent / "fixtures" / "stage9a_v4"
OWNER_ALIGNMENT_PATH = (
    STAGE9A_ROOT
    / "evaluation"
    / "owner-alignment-set-70-v1"
    / "OWNER_ALIGNMENT_SET_70_v1.json"
)
OWNER_ALIGNMENT_FILE_SHA256 = (
    "sha256:51152825976d42971413cdd9b18609a2392036f114d8f4177c2a8d446e1031e9"
)
OWNER_ALIGNMENT_RELATIONSHIP_SPEC_VERSION = "HAVRE_VOICE_RELATIONSHIP_SPEC_v1"
OWNER_ALIGNMENT_CASE_FIELDS = {
    "case_id", "contains_user_data", "content_hash", "evaluation_only",
    "expected_text", "hyperparameter_tuning_eligible", "local_only",
    "messages", "notes", "privacy_class", "prompt_tuning_eligible",
    "relationship_spec_version", "schema_version", "source_kind",
    "synthetic_generation_input_eligible", "title", "training_eligible",
    "validation_for_training",
}

CANONICAL_FILE_SHA256 = {
    "stage9a_train_v4.json": "sha256:e880b12b8cc298b983b4bb733c0d36eb45f59a156e7d1d556c5f34e9b0d021f5",
    "stage9a_train_v4.manifest.json": "sha256:5d3ff7fd90c562913bf69612deaf5befa8c0e6bef646fbc2ec2fadc64b1bd726",
    "stage9a_validation_v4.json": "sha256:2153f18256346c24ee7ea71a64164f72ff3a027bb9a758de95ebd4950be8b9f7",
    "stage9a_validation_v4.manifest.json": "sha256:940be8d7e112fbfd9ba1fdd32d672e85be3a546a39d27cbad21bb03f6594c08f",
    "stage9a_holdout_v4.json": "sha256:2bbc633977c706ac345ac549565a006901dd047ce2ec4dec4f4884a9b4cc5190",
    "stage9a_holdout_v4.manifest.json": "sha256:0299900b6cca5b170a556e4e63d24880df5470bd7b377977296060fbcce51f33",
}

V4Category = Literal[
    "appropriate_pressure", "casual_companion", "curiosity_banter",
    "disagreement_truthfulness", "evidence_uncertainty", "guide_scene",
    "identity_relation_truth", "memory_uncertainty_repair",
    "misattunement_repair", "prepare_scene", "proactive_followup",
    "progress_recognition", "quiet_companionship", "reflect_scene",
    "relational_continuity", "relationship_non_exclusivity", "safety_boundary",
    "structured_output", "warm_firm_action", "warm_presence",
]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class V4Message(_StrictModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class V4ExactChecker(_StrictModel):
    type: Literal["json_exact"]
    expected: dict[str, Any]


class Stage9ACanonicalV4Example(_StrictModel):
    schema_version: Literal[2]
    example_id: str = Field(pattern=r"^stage9a-(?:train|validation|holdout)-[0-9]{4}$")
    scenario_key: str = Field(min_length=1, max_length=160)
    sub_archetype_key: str = Field(min_length=1, max_length=160)
    category: V4Category
    source_kind: Literal["synthetic_fixture"]
    source_ref: str
    license_id: Literal["CC0-1.0"]
    split: Literal["train", "validation", "holdout"]
    training_eligible: bool
    evaluation_only: bool
    access_limited: bool
    contains_user_data: Literal[False]
    privacy_class: Literal["PUBLIC"]
    system_text: str = Field(min_length=1, max_length=8000)
    context_kind: Literal["conversation", "authorized_proactive_rendering"]
    messages: tuple[V4Message, ...]
    input_text: str = Field(min_length=1, max_length=4000)
    expected_text: str = Field(min_length=1, max_length=4000)
    language: Literal["zh", "en", "mixed"]
    mode: Literal["talk", "prepare", "guide", "reflect", "reach_out", "tool"]
    inject_memory_context: bool
    memory_context: str = Field(max_length=4000)
    memory_policy: Literal["none", "relevant", "stale_conflict", "uncertain", "ambiguous"]
    use_memory_in_training: bool
    use_memory_in_evaluation: bool
    rubric_version: Literal["havre-behavioral-rubric-v4"]
    required_properties: tuple[str, ...]
    forbidden_properties: tuple[str, ...]
    exact_checker: V4ExactChecker | None
    author_note: str = Field(max_length=4000)
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_contract(self) -> "Stage9ACanonicalV4Example":
        expected_training = self.split in TRAINING_SPLITS
        if self.training_eligible is not expected_training:
            raise ValueError("v4 training eligibility does not match split")
        if self.evaluation_only is not (self.split == "holdout"):
            raise ValueError("v4 evaluation-only policy does not match split")
        if self.access_limited is not (self.split == "holdout"):
            raise ValueError("v4 access policy does not match split")
        if self.source_ref != f"fixture://stage9a/v4/{self.split}/{self.example_id}":
            raise ValueError("v4 source reference is not canonical")
        if self.context_kind == "conversation":
            if not self.messages or self.messages[-1].role != "user":
                raise ValueError("v4 conversation must end with the final user message")
            if any(left.role == right.role for left, right in zip(self.messages, self.messages[1:])):
                raise ValueError("v4 conversation roles must alternate")
            if self.messages[-1].content != self.input_text:
                raise ValueError("v4 input_text must equal the final user message")
        else:
            if self.category != "proactive_followup" or self.mode != "reach_out":
                raise ValueError("authorized proactive rendering has the wrong category or mode")
            if self.messages:
                raise ValueError("authorized proactive ContextPack must not masquerade as chat history")
            if not self.input_text.startswith("Authorized proactive ContextPack:"):
                raise ValueError("proactive example lacks the already-authorized ContextPack")
        expected_memory_use = self.inject_memory_context and self.split in TRAINING_SPLITS
        expected_evaluation_use = self.inject_memory_context and self.split == "holdout"
        if self.use_memory_in_training is not expected_memory_use:
            raise ValueError("v4 training memory-use policy mismatch")
        if self.use_memory_in_evaluation is not expected_evaluation_use:
            raise ValueError("v4 evaluation memory-use policy mismatch")
        if self.inject_memory_context != bool(self.memory_context.strip()):
            raise ValueError("v4 memory injection flag and supplied context differ")
        material = self.model_dump(mode="json", exclude={"content_hash"})
        if content_hash(material) != self.content_hash:
            raise ValueError("v4 example content hash mismatch")
        return self


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _paths(root: Path, split: str) -> tuple[Path, Path]:
    return (
        root / f"stage9a_{split}_{ARTIFACT_VERSION}.json",
        root / f"stage9a_{split}_{ARTIFACT_VERSION}.manifest.json",
    )


def _normalized(value: str) -> str:
    return " ".join(value.lower().split())


def validate_split_isolation(
    splits: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    if set(splits) != set(SPLIT_COUNTS):
        raise ValueError("v4 requires exact train, validation, and holdout splits")
    validated: dict[str, list[Stage9ACanonicalV4Example]] = {}
    sub_archetype_splits: dict[str, str] = {}
    for split, expected_count in SPLIT_COUNTS.items():
        if len(splits[split]) != expected_count:
            raise ValueError(f"{split} count is not {expected_count}")
        validated[split] = []
        for raw in splits[split]:
            example = Stage9ACanonicalV4Example.model_validate(raw)
            if example.split != split:
                raise ValueError("v4 split binding mismatch")
            prior = sub_archetype_splits.setdefault(example.sub_archetype_key, split)
            if prior != split:
                raise ValueError("v4 sub-archetype leakage across splits")
            validated[split].append(example)
    flat = [item for split in SPLIT_COUNTS for item in validated[split]]
    for field in ("example_id", "scenario_key", "content_hash"):
        values = [getattr(item, field) for item in flat]
        if len(values) != len(set(values)):
            raise ValueError(f"duplicate v4 {field}")
    normalized_targets = [_normalized(item.expected_text) for item in flat]
    if len(normalized_targets) != len(set(normalized_targets)):
        raise ValueError("duplicate normalized v4 target")
    return {
        "counts": {split: len(items) for split, items in validated.items()},
        "global_unique_ids": len({item.example_id for item in flat}),
        "global_unique_scenarios": len({item.scenario_key for item in flat}),
        "global_unique_targets": len(set(normalized_targets)),
        "sub_archetype_cross_split_leakage": 0,
        "memory_conditioned_counts": {
            split: sum(item.inject_memory_context for item in items)
            for split, items in validated.items()
        },
        "multi_turn_counts": {
            split: sum(len(item.messages) > 1 for item in items)
            for split, items in validated.items()
        },
        "proactive_rendering_counts": {
            split: sum(item.context_kind == "authorized_proactive_rendering" for item in items)
            for split, items in validated.items()
        },
    }


def load_and_verify_dataset(root: Path = DATASET_ROOT) -> dict[str, list[dict[str, Any]]]:
    splits: dict[str, list[dict[str, Any]]] = {}
    for split, expected_count in SPLIT_COUNTS.items():
        artifact_path, manifest_path = _paths(root, split)
        expected_artifact_hash = CANONICAL_FILE_SHA256[artifact_path.name]
        expected_manifest_hash = CANONICAL_FILE_SHA256[manifest_path.name]
        if sha256_file(artifact_path) != expected_artifact_hash:
            raise ValueError(f"{split} canonical artifact differs from Product Owner bytes")
        if sha256_file(manifest_path) != expected_manifest_hash:
            raise ValueError(f"{split} canonical manifest differs from Product Owner bytes")
        raw = artifact_path.read_bytes()
        artifact = json.loads(raw)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        claimed_manifest_hash = manifest.pop("content_hash")
        if content_hash(manifest) != claimed_manifest_hash:
            raise ValueError(f"{split} manifest content hash mismatch")
        if _sha256_bytes(raw) != manifest.get("artifact_sha256"):
            raise ValueError(f"{split} artifact byte hash mismatch")
        claimed_artifact_hash = artifact.pop("content_hash")
        if content_hash(artifact) != claimed_artifact_hash:
            raise ValueError(f"{split} artifact content hash mismatch")
        expected_training = split in TRAINING_SPLITS
        if (
            artifact.get("schema_version") != 2
            or artifact.get("dataset_version") != DATASET_VERSION
            or artifact.get("split") != split
            or artifact.get("immutable") is not True
            or artifact.get("repository_owned") is not True
            or artifact.get("synthetic_public_safe") is not True
            or artifact.get("contains_user_data") is not False
            or artifact.get("training_eligible") is not expected_training
            or artifact.get("evaluation_only") is not (split == "holdout")
            or artifact.get("multi_turn_schema") is not True
            or artifact.get("memory_injection_schema") is not True
            or artifact.get("proactive_language_scope") != "render_after_core_send_now_only"
            or artifact.get("po_review_status") != "pending"
            or artifact.get("po_freeze_authorized") is not False
            or artifact.get("training_authorized") is not False
        ):
            raise ValueError(f"{split} v4 artifact governance mismatch")
        examples = artifact.get("examples")
        if not isinstance(examples, list) or len(examples) != expected_count:
            raise ValueError(f"{split} v4 artifact member count mismatch")
        member_hash = content_hash([
            {
                "example_id": item["example_id"],
                "content_hash": item["content_hash"],
                "scenario_key": item["scenario_key"],
                "sub_archetype_key": item["sub_archetype_key"],
            }
            for item in sorted(examples, key=lambda value: value["example_id"])
        ])
        if member_hash != artifact.get("member_manifest_hash"):
            raise ValueError(f"{split} artifact member manifest mismatch")
        if (
            manifest.get("schema_version") != 2
            or manifest.get("dataset_version") != DATASET_VERSION
            or manifest.get("split") != split
            or manifest.get("artifact_path") != artifact_path.name
            or manifest.get("artifact_size_bytes") != len(raw)
            or manifest.get("artifact_content_hash") != claimed_artifact_hash
            or manifest.get("member_count") != expected_count
            or manifest.get("member_manifest_hash") != member_hash
            or manifest.get("contains_user_data") is not False
            or manifest.get("training_eligible") is not expected_training
            or manifest.get("evaluation_only") is not (split == "holdout")
            or manifest.get("immutable") is not True
            or manifest.get("multi_turn_schema") is not True
            or manifest.get("memory_injection_schema") is not True
            or manifest.get("po_review_status") != "pending"
            or manifest.get("po_freeze_authorized") is not False
            or manifest.get("training_authorized") is not False
        ):
            raise ValueError(f"{split} v4 manifest governance or artifact binding mismatch")
        splits[split] = [
            Stage9ACanonicalV4Example.model_validate(item).model_dump(mode="json")
            for item in examples
        ]
    validate_split_isolation(splits)
    if dataset_bundle_hash(root) != EXTERNAL_BUNDLE_HASH:
        raise ValueError("repo-native v4 dataset bundle hash differs from Product Owner candidate")
    return splits


def dataset_bundle_hash(root: Path = DATASET_ROOT) -> str:
    material = []
    for split in SPLIT_COUNTS:
        _, manifest_path = _paths(root, split)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        material.append({
            "split": split,
            "artifact_sha256": manifest["artifact_sha256"],
            "member_manifest_hash": manifest["member_manifest_hash"],
            "manifest_content_hash": manifest["content_hash"],
        })
    return _sha256_bytes(canonical_json(material).encode("utf-8"))


def _validate_owner_alignment_case_contract(case: dict[str, Any]) -> None:
    if set(case) != OWNER_ALIGNMENT_CASE_FIELDS:
        raise ValueError("Owner Alignment case fields differ from the canonical schema")
    if (
        case.get("schema_version") != 1
        or case.get("relationship_spec_version")
        != OWNER_ALIGNMENT_RELATIONSHIP_SPEC_VERSION
    ):
        raise ValueError("Owner Alignment case version contract mismatch")
    for field in ("case_id", "title", "expected_text"):
        if not isinstance(case.get(field), str) or not case[field].strip():
            raise ValueError(f"Owner Alignment case lacks {field}")
    if not isinstance(case.get("notes"), str):
        raise ValueError("Owner Alignment case notes must be text")
    messages = case.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("Owner Alignment case lacks conversation messages")
    previous_role: str | None = None
    for message in messages:
        if (
            not isinstance(message, dict)
            or set(message) != {"role", "content"}
            or message.get("role") not in {"user", "assistant"}
            or not isinstance(message.get("content"), str)
            or not message["content"].strip()
            or message["role"] == previous_role
        ):
            raise ValueError("Owner Alignment case has invalid message history")
        previous_role = message["role"]
    if messages[-1]["role"] != "user":
        raise ValueError("Owner Alignment conversation must end with a user message")


def load_and_verify_owner_alignment(
    path: Path = OWNER_ALIGNMENT_PATH,
) -> dict[str, Any]:
    if sha256_file(path) != OWNER_ALIGNMENT_FILE_SHA256:
        raise ValueError("Owner Alignment Set differs from Product Owner bytes")
    payload = json.loads(path.read_text(encoding="utf-8"))
    claimed = payload.pop("content_hash")
    if content_hash(payload) != claimed:
        raise ValueError("Owner Alignment Set content hash mismatch")
    if (
        payload.get("schema_version") != 1
        or payload.get("alignment_set_version") != "havre-owner-alignment-70-v1"
        or payload.get("case_count") != 70
        or payload.get("contains_user_data") is not True
        or payload.get("privacy_class") != "PRIVATE"
        or payload.get("local_only") is not True
        or payload.get("immutable") is not True
        or payload.get("training_eligible") is not False
        or payload.get("validation_for_training") is not False
        or payload.get("hyperparameter_tuning_eligible") is not False
        or payload.get("prompt_tuning_eligible") is not False
        or payload.get("synthetic_generation_input_eligible") is not False
        or payload.get("evaluation_only") is not True
    ):
        raise ValueError("Owner Alignment Set top-level permanent exclusion policy mismatch")
    cases = payload.get("cases")
    if not isinstance(cases, list) or len(cases) != 70:
        raise ValueError("Owner Alignment Set must contain exactly 70 cases")
    ids: list[str] = []
    for case in cases:
        _validate_owner_alignment_case_contract(case)
        case_claimed = case.get("content_hash")
        material = {key: value for key, value in case.items() if key != "content_hash"}
        if content_hash(material) != case_claimed:
            raise ValueError(f"Owner Alignment case hash mismatch: {case.get('case_id')}")
        if (
            case.get("contains_user_data") is not True
            or case.get("privacy_class") != "PRIVATE"
            or case.get("local_only") is not True
            or case.get("source_kind") != "product_owner_calibrated_anchor"
            or case.get("training_eligible") is not False
            or case.get("validation_for_training") is not False
            or case.get("hyperparameter_tuning_eligible") is not False
            or case.get("prompt_tuning_eligible") is not False
            or case.get("synthetic_generation_input_eligible") is not False
            or case.get("evaluation_only") is not True
        ):
            raise ValueError(f"Owner Alignment case violates permanent exclusion: {case.get('case_id')}")
        ids.append(case["case_id"])
    if len(ids) != len(set(ids)):
        raise ValueError("Owner Alignment case IDs are not unique")
    member_hash = content_hash([
        {"case_id": case["case_id"], "content_hash": case["content_hash"]}
        for case in sorted(cases, key=lambda value: value["case_id"])
    ])
    if member_hash != payload.get("member_manifest_hash"):
        raise ValueError("Owner Alignment member manifest mismatch")
    payload["content_hash"] = claimed
    return payload


def audit_v4_data_boundaries() -> dict[str, Any]:
    splits = load_and_verify_dataset(DATASET_ROOT)
    owner = load_and_verify_owner_alignment(OWNER_ALIGNMENT_PATH)
    dataset_items = [item for split in SPLIT_COUNTS for item in splits[split]]
    dataset_inputs = {_normalized(item["input_text"]) for item in dataset_items}
    dataset_targets = {_normalized(item["expected_text"]) for item in dataset_items}
    dataset_conversations = {
        _normalized(canonical_json(item["messages"])) for item in dataset_items
    }
    owner_inputs = {
        _normalized(case["messages"][-1]["content"]) for case in owner["cases"]
    }
    owner_targets = {_normalized(case["expected_text"]) for case in owner["cases"]}
    owner_conversations = {
        _normalized(canonical_json(case["messages"])) for case in owner["cases"]
    }
    overlaps = {
        "input": len(dataset_inputs & owner_inputs),
        "target": len(dataset_targets & owner_targets),
        "conversation": len(dataset_conversations & owner_conversations),
    }
    if any(overlaps.values()):
        raise ValueError(f"Owner Alignment content leaked into v4 dataset: {overlaps}")
    split_report = validate_split_isolation(splits)
    return {
        "dataset_bundle_hash": dataset_bundle_hash(DATASET_ROOT),
        "dataset": split_report,
        "owner_alignment_case_count": len(owner["cases"]),
        "owner_alignment_file_sha256": sha256_file(OWNER_ALIGNMENT_PATH),
        "owner_alignment_content_hash": owner["content_hash"],
        "owner_alignment_member_manifest_hash": owner["member_manifest_hash"],
        "owner_alignment_exact_overlap": overlaps,
        "owner_alignment_permanently_excluded": True,
        "owner_alignment_path_is_outside_training_dataset": (
            DATASET_ROOT.resolve() not in OWNER_ALIGNMENT_PATH.resolve().parents
        ),
    }
