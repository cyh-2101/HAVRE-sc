"""Versioned enrollment receipt for binding native private state to one owner."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MobileEnrollmentReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    owner_id: UUID
    core_binding_id: str = Field(pattern=r"^owner:[0-9a-f-]{36}$")
    constitution_version_id: str = Field(min_length=1, max_length=200)
    identity_version_id: str = Field(min_length=1, max_length=200)
    values_version_id: str = Field(min_length=1, max_length=200)
    governance_version: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def bind_owner(self) -> "MobileEnrollmentReceipt":
        if self.core_binding_id != f"owner:{self.owner_id}":
            raise ValueError("core_binding_id must bind the exact owner_id")
        return self
