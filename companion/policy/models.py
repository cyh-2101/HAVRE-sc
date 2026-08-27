"""Provider-independent privacy and data-use policy contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from companion.ids import uuid7


class PrivacyClass(StrEnum):
    PUBLIC = "PUBLIC"
    NORMAL = "NORMAL"
    PRIVATE = "PRIVATE"
    HIGHLY_PRIVATE = "HIGHLY_PRIVATE"
    LOCAL_ONLY = "LOCAL_ONLY"


PRIVACY_RESTRICTION_ORDER = {
    PrivacyClass.PUBLIC: 0,
    PrivacyClass.NORMAL: 1,
    PrivacyClass.PRIVATE: 2,
    PrivacyClass.HIGHLY_PRIVATE: 3,
    PrivacyClass.LOCAL_ONLY: 4,
}


class DataPolicy(BaseModel):
    """A complete policy snapshot attached to each personal artifact.

    Stage 1 deliberately rejects training eligibility. Turning it on is a
    material governance change and cannot arrive as a request-level flag.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    policy_revision_id: UUID = Field(default_factory=uuid7)
    privacy_class: PrivacyClass
    memory_eligible: bool
    training_eligible: Literal[False] = False
    cloud_eligible: bool
    policy_version: Literal["data-policy-v1"] = "data-policy-v1"
    decision_source: Literal[
        "owner_default", "owner_explicit", "derived_conservative"
    ]
    authorization_ref: str | None = None

    @model_validator(mode="after")
    def enforce_hard_boundaries(self) -> "DataPolicy":
        if self.privacy_class is PrivacyClass.LOCAL_ONLY and self.cloud_eligible:
            raise ValueError("LOCAL_ONLY data can never be cloud eligible")
        if self.privacy_class is PrivacyClass.HIGHLY_PRIVATE and self.cloud_eligible:
            if self.decision_source != "owner_explicit" or not self.authorization_ref:
                raise ValueError(
                    "HIGHLY_PRIVATE cloud use requires explicit owner authorization"
                )
        return self

    @classmethod
    def owner_default(
        cls,
        privacy_class: PrivacyClass,
        *,
        memory_eligible: bool = True,
    ) -> "DataPolicy":
        return cls(
            privacy_class=privacy_class,
            memory_eligible=memory_eligible,
            cloud_eligible=privacy_class
            in {PrivacyClass.PUBLIC, PrivacyClass.NORMAL, PrivacyClass.PRIVATE},
            decision_source="owner_default",
        )


def combine_policies(policies: Sequence[DataPolicy]) -> DataPolicy:
    if not policies:
        raise ValueError("at least one policy is required")
    privacy = max(
        (policy.privacy_class for policy in policies),
        key=PRIVACY_RESTRICTION_ORDER.__getitem__,
    )
    return DataPolicy(
        privacy_class=privacy,
        memory_eligible=all(policy.memory_eligible for policy in policies),
        cloud_eligible=all(policy.cloud_eligible for policy in policies),
        decision_source="derived_conservative",
    )
