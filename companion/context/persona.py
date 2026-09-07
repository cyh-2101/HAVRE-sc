"""Canonical identity for fields that propose HAVRE-authored outreach."""

from __future__ import annotations

from dataclasses import dataclass

from companion.context.experience import (
    OWNER_EXPERIENCE_AUTHORIZATION_REF,
    OWNER_EXPERIENCE_GUIDANCE,
    OWNER_EXPERIENCE_VERSION,
    owner_experience_policy,
)
from companion.identity import IdentityBundle
from companion.hashing import content_hash
from companion.policy import DataPolicy


FOLLOW_UP_PERSONA_VERSION = "follow-up-canonical-persona-v1"


@dataclass(frozen=True)
class FollowUpPersona:
    text: str
    source_refs: tuple[str, ...]
    data_policy: DataPolicy
    metadata: dict[str, str]


def follow_up_persona(identity: IdentityBundle) -> FollowUpPersona:
    """Scope the canonical voice to outreach, preserving first-person Diary.

    This adds no experience, example-bank content, retrieval, provider call,
    contact permission, or timing decision. The existing source/quality/Core
    gates still decide whether a proposed follow-up may be delivered.
    """
    artifacts = (identity.constitution, identity.identity, identity.values)
    return FollowUpPersona(
        text=(
            "Canonical HAVRE identity and authorized conversation guidance for "
            "follow_up_suggestion.message only. These are voice and judgment "
            "constraints, never facts about the owner. Diary title and diary_text "
            "must remain the owner's first-person account under the existing "
            "schema; do not narrate those fields as HAVRE. This guidance does not "
            "authorize a follow-up or alter its source, timing, or send gates.\n\n"
            + identity.system_text() + "\n\n" + OWNER_EXPERIENCE_GUIDANCE
        ),
        source_refs=tuple(
            f"{item.artifact_kind}/{item.version_id}@{item.content_hash}"
            for item in artifacts
        ) + (f"authorization/{OWNER_EXPERIENCE_AUTHORIZATION_REF}",),
        # The identity itself is PUBLIC, but the existing owner-authorized
        # experience-first guidance is NORMAL; callers combine this policy.
        data_policy=owner_experience_policy(),
        metadata={
            "follow_up_persona_version": FOLLOW_UP_PERSONA_VERSION,
            "follow_up_experience_version": OWNER_EXPERIENCE_VERSION,
            "follow_up_experience_hash": content_hash(OWNER_EXPERIENCE_GUIDANCE),
            **{f"follow_up_{item.artifact_kind}_version_id": item.version_id
               for item in artifacts},
            **{f"follow_up_{item.artifact_kind}_content_hash": item.content_hash
               for item in artifacts},
        },
    )
