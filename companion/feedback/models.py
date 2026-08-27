"""Versioned contracts for owner response feedback.

Feedback is evidence about an interaction, not a Memory and not training consent.
The original assistant Event remains immutable; an owner rewrite is a proposed
alternative attached to that exact Event.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from companion.hashing import content_hash


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FeedbackRating(StrEnum):
    HELPFUL = "helpful"
    UNHELPFUL = "unhelpful"
    MIXED = "mixed"


class FeedbackReasonCode(StrEnum):
    TOO_AI = "too_ai"
    TOO_LONG = "too_long"
    NOT_WARM_ENOUGH = "not_warm_enough"
    NOT_FIRM_ENOUGH = "not_firm_enough"
    FABRICATED_MEMORY = "fabricated_memory"
    WRONG_USER_FACT = "wrong_user_fact"
    MISUNDERSTOOD_INTENT = "misunderstood_intent"
    WRONG_MODE = "wrong_mode"
    UNHELPFUL_ADVICE = "unhelpful_advice"
    NOT_HAVRE = "not_havre"
    OTHER = "other"


class FeedbackIssueAttribution(StrEnum):
    PERSONALITY_COMMUNICATION = "personality_communication"
    MEMORY_GROUNDING_TRUTHFULNESS = "memory_grounding_truthfulness"
    MEMORY_RETRIEVAL = "memory_retrieval"
    CORE_POLICY = "core_policy"
    MODE_SELECTION = "mode_selection"
    REASONING_UNDERSTANDING = "reasoning_understanding"
    OTHER_SYSTEM = "other_system"
    MIXED = "mixed"
    UNCLASSIFIED = "unclassified"


class FeedbackReviewDecision(StrEnum):
    RUNTIME_FIX = "runtime_fix"
    APPROVED_FOR_PERSONALIZATION_TRAINING = "approved_for_personalization_training"
    EVALUATION_ONLY = "evaluation_only"
    DEFERRED = "deferred"
    REJECTED = "rejected"


class PersonalizationFeedback(StrictModel):
    schema_version: Literal[1] = 1
    feedback_id: UUID
    revision: int = Field(gt=0)
    owner_id: UUID
    request_id: UUID
    session_id: UUID
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    user_event_id: UUID
    assistant_event_id: UUID
    context_pack_id: UUID
    route_decision_id: UUID
    inference_response_id: UUID
    provider_id: str
    model_version_id: str
    adapter_version_id: str | None = None
    tokenizer_version_id: str
    serving_config_version: str
    rating: FeedbackRating
    reason_codes: tuple[FeedbackReasonCode, ...] = ()
    reason_text: str | None = Field(default=None, max_length=2_000)
    owner_revision_text: str | None = Field(default=None, max_length=100_000)
    privacy_class: str
    training_eligible: Literal[False] = False
    status: Literal["saved", "reviewed"] = "saved"
    content_hash: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_hash(self) -> "PersonalizationFeedback":
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("feedback reason codes must be unique")
        material = self.model_dump(
            mode="json", exclude={"content_hash", "created_at", "status"}
        )
        expected = content_hash(material)
        if self.content_hash and self.content_hash != expected:
            raise ValueError("feedback content_hash mismatch")
        object.__setattr__(self, "content_hash", expected)
        return self


class PersonalizationFeedbackReview(StrictModel):
    schema_version: Literal[1] = 1
    review_id: UUID
    owner_id: UUID
    feedback_id: UUID
    feedback_revision: int = Field(gt=0)
    decision: FeedbackReviewDecision
    issue_attributions: tuple[FeedbackIssueAttribution, ...] = Field(min_length=1)
    review_notes: str | None = Field(default=None, max_length=4_000)
    training_eligible: bool = False
    authorization_ref: str | None = Field(default=None, max_length=500)
    content_hash: str = ""
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_review(self) -> "PersonalizationFeedbackReview":
        if len(set(self.issue_attributions)) != len(self.issue_attributions):
            raise ValueError("issue attributions must be unique")
        approved = (
            self.decision
            is FeedbackReviewDecision.APPROVED_FOR_PERSONALIZATION_TRAINING
        )
        if self.training_eligible != approved:
            raise ValueError("training eligibility must exactly match approval decision")
        if approved and not self.authorization_ref:
            raise ValueError("training approval requires an authorization reference")
        if not approved and self.authorization_ref is not None:
            raise ValueError("non-training review cannot carry training authorization")
        if approved and FeedbackIssueAttribution.UNCLASSIFIED in self.issue_attributions:
            raise ValueError("training approval requires a classified issue source")
        expected = content_hash(
            self.model_dump(mode="json", exclude={"content_hash", "reviewed_at"})
        )
        if self.content_hash and self.content_hash != expected:
            raise ValueError("feedback review content_hash mismatch")
        object.__setattr__(self, "content_hash", expected)
        return self


class CommunicationPreference(StrictModel):
    schema_version: Literal[1] = 1
    owner_id: UUID
    revision: int = Field(gt=0)
    response_length: Literal["brief", "balanced", "detailed"]
    reason: str = Field(min_length=1, max_length=1_000)
    content_hash: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_hash(self) -> "CommunicationPreference":
        expected = content_hash(
            self.model_dump(mode="json", exclude={"content_hash", "created_at"})
        )
        if self.content_hash and self.content_hash != expected:
            raise ValueError("communication preference content_hash mismatch")
        object.__setattr__(self, "content_hash", expected)
        return self


class ConversationEpisodeMember(StrictModel):
    ordinal: int = Field(ge=0)
    event_id: UUID
    event_content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    event_type: Literal["USER_MESSAGE", "ASSISTANT_MESSAGE"]


class ConversationEpisode(StrictModel):
    schema_version: Literal[1] = 1
    owner_id: UUID
    episode_id: UUID
    session_id: UUID
    status: Literal["closed"] = "closed"
    boundary_reason: Literal[
        "owner_started_new_conversation", "owner_closed", "idle_boundary"
    ]
    message_count: int = Field(gt=0)
    summary_text: str = Field(min_length=1, max_length=100_000)
    summary_method: Literal["extractive-episode-summary-v1"] = (
        "extractive-episode-summary-v1"
    )
    privacy_class: str
    memory_eligible: bool
    training_eligible: Literal[False] = False
    cloud_eligible: bool
    policy_version: Literal["data-policy-v1"] = "data-policy-v1"
    policy_revision_id: UUID
    policy_decision_source: Literal["derived_conservative"] = "derived_conservative"
    policy_authorization_ref: str | None = None
    content_hash: str
    started_at: datetime
    ended_at: datetime
    members: tuple[ConversationEpisodeMember, ...] = ()


class EpisodeMemorySuggestion(StrictModel):
    schema_version: Literal[1] = 1
    owner_id: UUID
    suggestion_id: UUID
    episode_id: UUID
    # v1 exposes only the implemented episode-summary projection. Future
    # semantic/preference/pattern extractors require their own reviewed
    # contracts rather than being advertised ahead of persistence support.
    memory_class: Literal["episodic"]
    content_text: str = Field(min_length=1, max_length=100_000)
    extractor_version: Literal["episode-suggestion-v1"] = "episode-suggestion-v1"
    status: Literal["pending", "accepted", "rejected"]
    review_reason: str | None = Field(default=None, max_length=2_000)
    privacy_class: str
    memory_eligible: bool
    training_eligible: Literal[False] = False
    cloud_eligible: bool
    policy_version: Literal["data-policy-v1"] = "data-policy-v1"
    policy_revision_id: UUID
    policy_decision_source: Literal["derived_conservative"] = "derived_conservative"
    policy_authorization_ref: str | None = None
    content_hash: str
    created_at: datetime
    reviewed_at: datetime | None = None
