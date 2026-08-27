"""Immutable Stage 7 offline-pipeline and memory-lifecycle contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from companion.hashing import content_hash
from companion.ids import uuid7
from companion.policy import DataPolicy


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MemoryLifecycleAction(StrEnum):
    PROMOTE = "promote"
    CONTRADICT = "contradict"
    SUPERSEDE = "supersede"
    RETRACT = "retract"
    ARCHIVE = "archive"
    RECONSOLIDATE = "reconsolidate"
    REGENERATE = "regenerate"


class ReflectionProposal(StrictModel):
    schema_version: Literal[1] = 1
    reflection_proposal_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    job_id: UUID
    proposal_kind: Literal[
        "pattern_check", "unresolved_contradiction", "progress_recognition", "follow_up"
    ]
    summary: str = Field(min_length=1, max_length=2000)
    evidence_event_ids: tuple[UUID, ...] = Field(min_length=1)
    source_snapshot_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    transform_version: Literal["deterministic-reflection-v1"] = (
        "deterministic-reflection-v1"
    )
    data_policy: DataPolicy
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    outreach_authority: Literal[False] = False
    delivery_authority: Literal[False] = False
    simulation_only: Literal[True] = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_hash: str = ""

    @field_validator("created_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def bind_hash(self) -> "ReflectionProposal":
        expected = content_hash(
            self.model_dump(mode="json", exclude={"content_hash", "created_at"})
        )
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match ReflectionProposal")
        object.__setattr__(self, "content_hash", expected)
        return self


class MemoryLifecycleProposal(StrictModel):
    schema_version: Literal[1] = 1
    lifecycle_proposal_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    action: MemoryLifecycleAction
    memory_class: Literal["episodic", "semantic", "pattern", "progress"]
    source_event_ids: tuple[UUID, ...] = ()
    source_memory_refs: tuple[str, ...] = ()
    target_memory_id: UUID | None = None
    target_revision: int | None = Field(default=None, gt=0)
    proposed_content_text: str | None = Field(default=None, min_length=1, max_length=100_000)
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    reason: str = Field(min_length=1, max_length=2000)
    transform_version: Literal["memory-lifecycle-proposal-v1"] = (
        "memory-lifecycle-proposal-v1"
    )
    data_policy: DataPolicy
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    review_required: Literal[True] = True
    automatically_applied: Literal[False] = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_hash: str = ""

    @field_validator("valid_from", "valid_to", "created_at")
    @classmethod
    def normalize_times(cls, value: datetime | None, info) -> datetime | None:
        if value is None:
            return None
        if value.utcoffset() is None:
            raise ValueError(f"{info.field_name} must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_and_hash(self) -> "MemoryLifecycleProposal":
        if not self.source_event_ids and not self.source_memory_refs:
            raise ValueError("memory lifecycle proposal requires exact source evidence")
        targeted = self.action in {
            MemoryLifecycleAction.CONTRADICT,
            MemoryLifecycleAction.SUPERSEDE,
            MemoryLifecycleAction.RETRACT,
            MemoryLifecycleAction.ARCHIVE,
            MemoryLifecycleAction.RECONSOLIDATE,
        }
        if targeted != (self.target_memory_id is not None and self.target_revision is not None):
            raise ValueError("targeted lifecycle actions require an exact memory revision")
        if self.valid_to is not None and self.valid_from is not None and self.valid_to < self.valid_from:
            raise ValueError("valid_to cannot precede valid_from")
        expected = content_hash(
            self.model_dump(mode="json", exclude={"content_hash", "created_at"})
        )
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match MemoryLifecycleProposal")
        object.__setattr__(self, "content_hash", expected)
        return self


class MemoryLifecycleReview(StrictModel):
    schema_version: Literal[1] = 1
    review_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    lifecycle_proposal_id: UUID
    decision: Literal["accepted", "rejected"]
    reason: str = Field(min_length=1, max_length=2000)
    reviewer: Literal["owner"] = "owner"
    applied_artifact_ref: None = None
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_hash: str = ""

    @model_validator(mode="after")
    def bind_hash(self) -> "MemoryLifecycleReview":
        expected = content_hash(
            self.model_dump(mode="json", exclude={"content_hash", "reviewed_at"})
        )
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match MemoryLifecycleReview")
        object.__setattr__(self, "content_hash", expected)
        return self


class DatasetRejection(StrictModel):
    source_ref: str
    source_content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    reason_code: Literal[
        "training_not_eligible", "source_erased", "duplicate", "quality_rejected", "holdout_conflict"
    ]


class CanonicalDatasetMember(StrictModel):
    member_id: str
    source_refs: tuple[str, ...] = Field(min_length=1)
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    split: Literal["train", "validation", "holdout"]
    explicit_training_authorization_ref: str = Field(min_length=1)


class CanonicalDatasetSnapshot(StrictModel):
    schema_version: Literal[1] = 1
    dataset_snapshot_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    source_snapshot_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    builder_version: Literal["canonical-dataset-builder-v1"] = (
        "canonical-dataset-builder-v1"
    )
    split_policy_version: Literal["source-grouped-holdout-v1"] = (
        "source-grouped-holdout-v1"
    )
    members: tuple[CanonicalDatasetMember, ...] = ()
    rejections: tuple[DatasetRejection, ...]
    member_manifest_hash: str = ""
    immutable: Literal[True] = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_hash: str = ""

    @model_validator(mode="after")
    def bind_hashes(self) -> "CanonicalDatasetSnapshot":
        ordered_members = tuple(sorted(
            (item.model_dump(mode="json") for item in self.members),
            key=lambda item: item["member_id"],
        ))
        manifest_hash = content_hash(ordered_members)
        if self.member_manifest_hash and self.member_manifest_hash != manifest_hash:
            raise ValueError("member manifest hash is not canonical")
        object.__setattr__(self, "member_manifest_hash", manifest_hash)
        material = self.model_dump(
            mode="json",
            exclude={"dataset_snapshot_id", "content_hash", "created_at"},
        )
        expected = content_hash(material)
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match dataset snapshot")
        object.__setattr__(self, "content_hash", expected)
        return self


class ArtifactManifest(StrictModel):
    schema_version: Literal[1] = 1
    artifact_manifest_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    artifact_kind: Literal["canonical_dataset_snapshot"] = "canonical_dataset_snapshot"
    artifact_ref: str
    artifact_content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    source_snapshot_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    builder_version: Literal["canonical-dataset-builder-v1"] = (
        "canonical-dataset-builder-v1"
    )
    reproducible: Literal[True] = True
    immutable: Literal[True] = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_hash: str = ""

    @model_validator(mode="after")
    def bind_hash(self) -> "ArtifactManifest":
        expected = content_hash(
            self.model_dump(
                mode="json",
                exclude={"artifact_manifest_id", "content_hash", "created_at"},
            )
        )
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match artifact manifest")
        object.__setattr__(self, "content_hash", expected)
        return self
