"""Approved, model-independent identity artifacts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ApprovedTextArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    artifact_kind: Literal["constitution", "identity", "values"]
    version_id: str
    content: str
    content_hash: str
    approved_by: Literal["owner"]
    approved_at: datetime
    source_files: tuple[str, ...]


class IdentityBundle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    constitution: ApprovedTextArtifact
    identity: ApprovedTextArtifact
    values: ApprovedTextArtifact
    governance_version: Literal["governance-v1"] = "governance-v1"

    def system_text(self) -> str:
        return "\n\n".join(
            (
                self.constitution.content,
                self.identity.content,
                self.values.content,
            )
        )
