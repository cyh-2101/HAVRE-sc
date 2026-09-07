"""Provider-neutral admission of already source-qualified personal evidence.

This compiler does not invent facts, retrieve new sources, or authorize effects.
It chooses whole records under one budget and keeps the reason for each omission.
The same authority order is used for replies and delayed continuations.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import re

from companion.context.models import ContextSection
from companion.context.experience import OWNER_EXPERIENCE_VERSION, OWNER_EXPERIENCE_GUIDANCE, owner_experience_policy
from companion.policy import PrivacyClass
from companion.policy.models import PRIVACY_RESTRICTION_ORDER
from companion.memory.lexical import overlap


VERSION = "personal-context-compiler-v1"
HISTORY_TYPES = {"conversation_user_message", "conversation_assistant_message"}
CONCRETE_TYPES = {"episodic_memory", "goal", "current_state", "calendar_availability"}
ABSTRACT_TYPES = {"semantic_memory", "pattern_memory", "progress_memory", "user_belief"}
CONSTRAINT_TYPES = {
    "owner_response_instruction", "owner_wording_correction", "communication_preference",
}


def authority(section: ContextSection) -> int:
    """Fact authority is independent of a selector's numerical priority."""
    kind = section.section_type
    if kind in {"identity", "current_user_input", "current_time", "response_plan"}:
        return 0
    if kind in CONSTRAINT_TYPES or kind == "owner_fact_correction":
        return 1
    if kind in HISTORY_TYPES:
        return 2
    if kind in CONCRETE_TYPES:
        return 3
    if kind in ABSTRACT_TYPES:
        return 4
    if kind == "behavior_example":
        return 5
    raise ValueError(f"unsupported personal context kind: {kind}")


@dataclass(frozen=True)
class Compilation:
    sections: tuple[ContextSection, ...]
    exclusions: tuple[dict[str, str], ...]
    estimated_tokens: int


class PersonalContextCompiler:
    version = VERSION

    def compile(
        self,
        *,
        required: Sequence[ContextSection],
        candidates: Sequence[ContextSection],
        maximum_tokens: int,
        measure: Callable[[Sequence[ContextSection]], int],
        maximum_privacy_class: PrivacyClass,
        cloud_authorized: bool = False,
        query_text: str = "",
    ) -> Compilation:
        selected = list(required)
        for section in required:
            policy = section.data_policy
            fixed_owner_guidance = (section.section_id == OWNER_EXPERIENCE_VERSION
                and section.section_type == "owner_response_instruction"
                and policy == owner_experience_policy()
                and "\n".join(p.text for p in section.content_parts) == OWNER_EXPERIENCE_GUIDANCE)
            if not fixed_owner_guidance and PRIVACY_RESTRICTION_ORDER[policy.privacy_class] > PRIVACY_RESTRICTION_ORDER[maximum_privacy_class]:
                raise ValueError("required context is more restrictive than request")
            if cloud_authorized and (not policy.cloud_eligible or policy.privacy_class not in {PrivacyClass.PUBLIC, PrivacyClass.NORMAL}):
                raise ValueError("continuation context is not cloud authorized")
        if measure(selected) > maximum_tokens:
            raise ValueError("required personal context exceeds token budget")
        exclusions: list[dict[str, str]] = []
        admitted: list[ContextSection] = []
        identities: set[str] = {s.section_id for s in required}

        def exclude(section: ContextSection, reason: str) -> None:
            exclusions.append({"candidate_ref": section.source_refs[0], "reason_code": reason})

        for section in candidates:
            policy = section.data_policy
            if PRIVACY_RESTRICTION_ORDER[policy.privacy_class] > PRIVACY_RESTRICTION_ORDER[maximum_privacy_class]:
                exclude(section, "privacy_class_exceeds_request")
                continue
            if cloud_authorized and (not policy.cloud_eligible or policy.privacy_class not in {PrivacyClass.PUBLIC, PrivacyClass.NORMAL}):
                # Reusing a completed cloud pack must not silently hide changed
                # policy to continue on the cloud route.
                raise ValueError("continuation context is not cloud authorized")
            if section.section_id in identities:
                exclude(section, "duplicate_evidence_suppressed")
                continue
            identities.add(section.section_id)
            admitted.append(section)

        # Suppress repeated factual text across retrieval and personal selectors.
        # Never deduplicate raw turns: repeating a statement is itself experience.
        facts: dict[tuple[str, tuple[str, ...]], ContextSection] = {}
        unique: list[ContextSection] = []
        for section in sorted(admitted, key=lambda s: (authority(s), -s.priority)):
            if section.section_type in CONCRETE_TYPES | ABSTRACT_TYPES:
                text = "\n".join(p.text for p in section.content_parts)
                normalized = re.sub(r"[\s。.!！?？]+", "", text.casefold())
                # Identical words from different experiences are not the same
                # event. Deduplicate only an exact source-qualified derivative.
                event_refs = tuple(sorted(r for r in section.source_refs if r.startswith("event/")))
                key = (normalized, event_refs or tuple(sorted(section.source_refs)))
                if key in facts:
                    exclude(section, "duplicate_evidence_suppressed")
                    continue
                facts[key] = section
            unique.append(section)

        def add(group: Sequence[ContextSection], *, cap: int | None = None) -> bool:
            target = [*selected, *group]
            if measure(target) > (maximum_tokens if cap is None else min(cap, maximum_tokens)):
                return False
            selected.extend(group)
            return True

        for section in unique:
            if section.section_type == "owner_fact_correction" and not add((section,)):
                raise ValueError("required owner fact correction exceeds context budget")
        constraints = [s for s in unique if s.section_type in CONSTRAINT_TYPES]
        for section in constraints:
            if not add((section,)):
                exclude(section, "token_budget_exceeded")

        history = [s for s in candidates if s in unique and s.section_type in HISTORY_TYPES]
        concrete = [s for s in unique if s.section_type in CONCRETE_TYPES]
        remaining = maximum_tokens - measure(selected)
        concrete_cap = maximum_tokens if not history else measure(selected) + max(160, remaining // 3)
        deferred: list[ContextSection] = []
        for section in concrete:
            if not add((section,), cap=concrete_cap):
                deferred.append(section)

        # Preserve a request's owner/assistant evidence as a unit. A budget must
        # not retain an assistant guess while silently dropping its source turn.
        groups: dict[str, list[ContextSection]] = {}
        for section in history:
            key = next((r for r in section.source_refs if r.startswith("request/")), section.section_id)
            groups.setdefault(key, []).append(section)
        selected_history: set[str] = set()
        chronological_groups = list(groups.values())
        # Preserve the immediate exchange, then prioritize topic-bearing raw
        # experience over unrelated newer filler without changing fact authority.
        history_order = list(reversed(chronological_groups))
        if query_text and len(history_order) > 1:
            history_order = history_order[:1] + sorted(history_order[1:], key=lambda group: -max(
                (overlap(query_text, "\n".join(p.text for p in section.content_parts))
                 for section in group if section.section_type == "conversation_user_message"),
                default=0.0,
            ))
        for group in history_order:
            if add(group):
                selected_history.update(s.section_id for s in group)
            else:
                for section in group:
                    exclude(section, "token_budget_exceeded")
        for section in deferred:
            if not add((section,)):
                exclude(section, "memory_budget_reserved_for_recent_conversation" if history else "token_budget_exceeded")
        for section in unique:
            if section.section_type in ABSTRACT_TYPES | {"behavior_example"}:
                if not add((section,)):
                    exclude(section, "token_budget_exceeded")

        # Provider history must remain chronological even though admission works
        # newest first. Other sections retain the common authority order.
        non_history = [s for s in selected if s.section_type not in HISTORY_TYPES]
        ordered = tuple(sorted(non_history, key=lambda s: (authority(s), -s.priority))) + tuple(
            s for s in history if s.section_id in selected_history
        )
        return Compilation(ordered, tuple(exclusions), measure(ordered))
