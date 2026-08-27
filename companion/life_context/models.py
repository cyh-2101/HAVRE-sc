"""Accepted ADR-0019 contracts without activating an external source."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from companion.hashing import content_hash
from companion.ids import uuid7
from companion.policy import DataPolicy


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SignalFreshness(StrictModel):
    observed_at: datetime
    valid_until: datetime
    clock_uncertainty_seconds: int = Field(ge=0, le=86_400)

    @field_validator("observed_at", "valid_until")
    @classmethod
    def normalize(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("freshness timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_window(self) -> "SignalFreshness":
        if self.valid_until <= self.observed_at:
            raise ValueError("freshness validity must follow observation")
        return self


class LifeContextObservation(StrictModel):
    schema_version: Literal[1] = 1
    observation_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    source_id: Literal["stage6-synthetic-manual"] = "stage6-synthetic-manual"
    capability: Literal["manual_coarse_context_fixture"] = (
        "manual_coarse_context_fixture"
    )
    observation_type: Literal["coarse_availability"] = "coarse_availability"
    value: Literal["available", "busy", "unknown"]
    coverage: Literal["point_observation"] = "point_observation"
    freshness: SignalFreshness
    consent_scope_ref: Literal["stage6-synthetic-fixture-only"] = (
        "stage6-synthetic-fixture-only"
    )
    adapter_version: Literal["synthetic-manual-adapter-v1"] = (
        "synthetic-manual-adapter-v1"
    )
    data_policy: DataPolicy
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    simulation_only: Literal[True] = True
    external_source_activated: Literal[False] = False
    content_hash: str = ""

    @model_validator(mode="after")
    def bind_hash(self) -> "LifeContextObservation":
        expected = content_hash(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match LifeContextObservation")
        object.__setattr__(self, "content_hash", expected)
        return self


class ContextSourceHealth(StrictModel):
    schema_version: Literal[1] = 1
    health_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    source_id: Literal["stage6-synthetic-manual"] = "stage6-synthetic-manual"
    status: Literal["available", "unavailable", "revoked"]
    coverage: Literal["synthetic_fixture_only"] = "synthetic_fixture_only"
    observed_at: datetime
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    simulation_only: Literal[True] = True
    external_source_activated: Literal[False] = False

    @field_validator("observed_at")
    @classmethod
    def normalize(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("health timestamp must be timezone-aware")
        return value.astimezone(UTC)


def classify_observation_eligibility(
    *, observation: LifeContextObservation | None,
    health: ContextSourceHealth | None, consent_active: bool, as_of: datetime,
) -> str:
    """Fail-closed eligibility classification for coarse local observations."""

    if as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    if not consent_active or (health is not None and health.status == "revoked"):
        return "ineligible_revoked"
    if observation is None or health is None:
        return "unknown_not_negative_evidence"
    if health.status != "available":
        return "unknown_not_negative_evidence"
    if observation.freshness.valid_until <= as_of.astimezone(UTC):
        return "ineligible_stale"
    return "eligible_observation_only"
