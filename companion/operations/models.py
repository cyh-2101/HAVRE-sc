"""Versioned Stage 10 operational contracts with explicit release gates."""

from __future__ import annotations

from datetime import UTC, datetime
import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from companion.hashing import content_hash
from companion.ids import uuid7


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _utc(value: datetime) -> datetime:
    if value.utcoffset() is None:
        raise ValueError("operational timestamps must be timezone-aware")
    return value.astimezone(UTC)


class ComponentReference(StrictModel):
    component: Literal[
        "companion_core", "database_schema", "provider", "foundation_model",
        "adapter", "tokenizer", "serving_engine", "deployment_image",
        "database_image", "proxy_image", "operations_image", "web", "worker",
    ]
    version: str = Field(min_length=1, max_length=240)
    artifact_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    lifecycle_status: Literal["approved", "candidate_fixture", "not_applicable"]
    replaceable: Literal[True] = True


class ComponentPromotionAuthorization(StrictModel):
    schema_version: Literal[1] = 1
    component: Literal[
        "provider", "foundation_model", "adapter", "tokenizer", "serving_engine"
    ]
    version: str = Field(min_length=1, max_length=240)
    artifact_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    decision: Literal["approved"] = "approved"
    actor: Literal["product_owner"] = "product_owner"
    rationale: str = Field(min_length=1, max_length=4000)
    decided_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_hash: str = ""

    @field_validator("decided_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def validate_and_hash(self) -> "ComponentPromotionAuthorization":
        expected = content_hash(
            self.model_dump(mode="json", exclude={"content_hash", "decided_at"})
        )
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match component authorization")
        object.__setattr__(self, "content_hash", expected)
        return self


class ReleaseManifest(StrictModel):
    schema_version: Literal[1] = 1
    release_manifest_id: UUID = Field(default_factory=uuid7)
    release_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,119}$")
    environment: Literal["development", "staging", "production"]
    release_scope: Literal[
        "infrastructure_only", "development_candidate_fixture", "production"
    ]
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    migration_head: str = Field(pattern=r"^[0-9]{4}_[a-z0-9_]+\.sql$")
    components: tuple[ComponentReference, ...] = Field(min_length=1)
    constitution_version_id: str = Field(min_length=1, max_length=240)
    identity_version_id: str = Field(min_length=1, max_length=240)
    values_version_id: str = Field(min_length=1, max_length=240)
    adapter_deployment_authorized: bool = False
    promotion_approval_ref: str | None = Field(default=None, max_length=500)
    rollback_release_manifest_hash: str | None = Field(
        default=None, pattern=r"^sha256:[0-9a-f]{64}$"
    )
    component_promotion_authorization_hashes: tuple[str, ...] = ()
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_hash: str = ""

    @field_validator("created_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def validate_gate_and_hash(self) -> "ReleaseManifest":
        kinds = [item.component for item in self.components]
        if len(kinds) != len(set(kinds)):
            raise ValueError("release component kinds must be unique")
        if len(self.component_promotion_authorization_hashes) != len(
            set(self.component_promotion_authorization_hashes)
        ) or any(
            not re.fullmatch(r"sha256:[0-9a-f]{64}", item)
            for item in self.component_promotion_authorization_hashes
        ):
            raise ValueError("component promotion authorization hashes are invalid")
        required_images = {
            "deployment_image", "database_image", "proxy_image", "operations_image"
        }
        if self.environment in {"staging", "production"} and not required_images.issubset(
            kinds
        ):
            raise ValueError("staging/production release requires every deployment image")
        adapter = next(
            (item for item in self.components if item.component == "adapter"), None
        )
        if self.release_scope == "production":
            if any(item.lifecycle_status != "approved" for item in self.components):
                raise ValueError(
                    "behavioral production release requires approved components"
                )
            if adapter is not None and not self.adapter_deployment_authorized:
                raise ValueError("production adapter requires explicit deployment authorization")
        if self.release_scope == "development_candidate_fixture":
            if self.environment == "production":
                raise ValueError("candidate fixture cannot be a production release")
            if adapter is None or adapter.lifecycle_status != "candidate_fixture":
                raise ValueError("candidate-fixture release requires a candidate adapter")
            if self.adapter_deployment_authorized or self.promotion_approval_ref:
                raise ValueError("candidate fixture cannot claim promotion or deployment")
        if adapter is not None and adapter.lifecycle_status == "candidate_fixture":
            if (
                self.environment == "production"
                or self.release_scope != "development_candidate_fixture"
            ):
                raise ValueError(
                    "candidate adapter is restricted to a nonproduction candidate fixture"
                )
            if self.adapter_deployment_authorized:
                raise ValueError("candidate adapter deployment is not authorized")
        if self.adapter_deployment_authorized:
            if (
                self.release_scope != "production"
                or self.environment != "production"
                or not self.promotion_approval_ref
                or adapter is None
                or adapter.lifecycle_status != "approved"
                or self.promotion_approval_ref
                not in self.component_promotion_authorization_hashes
            ):
                raise ValueError("adapter deployment requires an approved production gate")
        elif self.promotion_approval_ref is not None:
            raise ValueError("promotion approval cannot be detached from deployment authority")
        expected = content_hash(
            self.model_dump(mode="json", exclude={"content_hash", "created_at"})
        )
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match ReleaseManifest")
        object.__setattr__(self, "content_hash", expected)
        return self


class DeploymentHealthEvidence(StrictModel):
    schema_version: Literal[1] = 1
    release_manifest_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    environment: Literal["development", "staging", "production"]
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    runtime_image_digest: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    ready: Literal[True]
    checks: tuple[str, ...] = Field(min_length=1)
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("checked_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _utc(value)


class DeploymentRecord(StrictModel):
    schema_version: Literal[1] = 1
    deployment_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    release_manifest_id: UUID
    release_manifest_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    environment: Literal["development", "staging", "production"]
    action: Literal["deploy", "rollback"]
    status: Literal["planned", "applied", "failed"]
    previous_deployment_id: UUID | None = None
    health_evidence: DeploymentHealthEvidence | None = None
    failure_code: str | None = Field(default=None, max_length=120)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_hash: str = ""

    @field_validator("occurred_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def validate_and_hash(self) -> "DeploymentRecord":
        if self.action == "rollback" and self.previous_deployment_id is None:
            raise ValueError("rollback requires the deployment being rolled back")
        if self.status == "failed" and not self.failure_code:
            raise ValueError("failed deployment requires a safe failure code")
        if self.status != "failed" and self.failure_code is not None:
            raise ValueError("only failed deployments carry a failure code")
        if self.status == "applied" and self.health_evidence is None:
            raise ValueError("applied deployment requires health evidence")
        if self.status != "applied" and self.health_evidence is not None:
            raise ValueError("only applied deployments carry health evidence")
        if self.health_evidence is not None:
            if (
                self.health_evidence.release_manifest_hash
                != self.release_manifest_hash
                or self.health_evidence.environment != self.environment
            ):
                raise ValueError("health evidence is not bound to the deployment")
        expected = content_hash(
            self.model_dump(mode="json", exclude={"content_hash", "occurred_at"})
        )
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match DeploymentRecord")
        object.__setattr__(self, "content_hash", expected)
        return self


class ReleaseApprovalRecord(StrictModel):
    schema_version: Literal[1] = 1
    release_approval_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    release_manifest_id: UUID
    release_manifest_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    approval_scope: Literal[
        "infrastructure_production_release", "personalized_adapter_release"
    ]
    decision: Literal["approved", "rejected"]
    actor: Literal["product_owner"] = "product_owner"
    rationale: str = Field(min_length=1, max_length=4000)
    decided_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_hash: str = ""

    @field_validator("decided_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def validate_and_hash(self) -> "ReleaseApprovalRecord":
        expected = content_hash(
            self.model_dump(mode="json", exclude={"content_hash", "decided_at"})
        )
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match ReleaseApprovalRecord")
        object.__setattr__(self, "content_hash", expected)
        return self


class ErasureDirective(StrictModel):
    schema_version: Literal[1] = 1
    sequence: int = Field(gt=0)
    owner_id: UUID
    source_event_id: UUID
    scope: Literal[
        "raw_source_and_derived", "context_source_and_derived"
    ] = "raw_source_and_derived"
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    previous_content_hash: str | None = Field(
        default=None, pattern=r"^sha256:[0-9a-f]{64}$"
    )
    content_hash: str = ""

    @field_validator("requested_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def validate_and_hash(self) -> "ErasureDirective":
        if self.sequence == 1 and self.previous_content_hash is not None:
            raise ValueError("first erasure directive cannot have a predecessor")
        if self.sequence > 1 and self.previous_content_hash is None:
            raise ValueError("later erasure directive requires a predecessor hash")
        expected = content_hash(
            self.model_dump(mode="json", exclude={"content_hash"})
        )
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match ErasureDirective")
        object.__setattr__(self, "content_hash", expected)
        return self


class BackupManifest(StrictModel):
    schema_version: Literal[1] = 1
    backup_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    artifact_name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,240}$")
    artifact_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    artifact_size_bytes: int = Field(gt=0)
    source_database_name: str = Field(pattern=r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,62}$")
    migration_head: str = Field(pattern=r"^[0-9]{4}_[a-z0-9_]+\.sql$")
    release_manifest_id: UUID
    release_manifest_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    erasure_ledger_sequence: int = Field(ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime
    content_hash: str = ""

    @field_validator("created_at", "expires_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def validate_and_hash(self) -> "BackupManifest":
        if self.expires_at <= self.created_at:
            raise ValueError("backup expiry must be after creation")
        expected = content_hash(
            self.model_dump(mode="json", exclude={"content_hash", "created_at"})
        )
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match BackupManifest")
        object.__setattr__(self, "content_hash", expected)
        return self


class RestoreErasureReplay(StrictModel):
    schema_version: Literal[1] = 1
    replay_id: UUID
    owner_id: UUID
    backup_id: UUID
    restored_database_name: str = Field(
        pattern=r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,62}$"
    )
    ledger_sequence_from: int = Field(ge=0)
    ledger_sequence_through: int = Field(ge=0)
    directives_applied: int = Field(ge=0)
    absence_verified: Literal[True]
    provenance_violations: Literal[0]
    completed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_hash: str = ""

    @field_validator("completed_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def validate_and_hash(self) -> "RestoreErasureReplay":
        if self.ledger_sequence_through < self.ledger_sequence_from:
            raise ValueError("restore replay sequence range is inverted")
        expected = content_hash(
            self.model_dump(mode="json", exclude={"content_hash", "completed_at"})
        )
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match RestoreErasureReplay")
        object.__setattr__(self, "content_hash", expected)
        return self


class ExportArtifact(StrictModel):
    relative_path: str = Field(pattern=r"^[a-z0-9][a-z0-9._/-]{1,500}$")
    media_type: str = Field(min_length=1, max_length=120)
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    row_count: int = Field(ge=0)


class OwnerExportManifest(StrictModel):
    schema_version: Literal[1] = 1
    export_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    database_schema_migrations: tuple[str, ...] = Field(min_length=1)
    artifacts: tuple[ExportArtifact, ...] = Field(min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_hash: str = ""

    @field_validator("created_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def validate_and_hash(self) -> "OwnerExportManifest":
        paths = [item.relative_path for item in self.artifacts]
        if len(paths) != len(set(paths)):
            raise ValueError("owner export artifact paths must be unique")
        expected = content_hash(
            self.model_dump(mode="json", exclude={"content_hash", "created_at"})
        )
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match OwnerExportManifest")
        object.__setattr__(self, "content_hash", expected)
        return self
