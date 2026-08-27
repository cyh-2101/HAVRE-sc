"""Stage 2 Context Builder: governed identity, retrieved memory, current input."""

from __future__ import annotations

from math import ceil, isfinite
from uuid import UUID

from companion.context.models import (
    ContextPack,
    ContextSection,
    ConversationHistoryItem,
    PersonalContextItem,
    TokenBudget,
)
from companion.events import EventEnvelope, TextContentPart, UserMessagePayload
from companion.identity import IdentityBundle
from companion.policy import DataPolicy, PrivacyClass, combine_policies
from companion.policy.models import PRIVACY_RESTRICTION_ORDER
from mlsys.retrieval.models import (
    CONTEXT_SAFE_ALGORITHM_VERSION,
    CONTEXT_SAFE_DUPLICATE_SIMILARITY_THRESHOLD,
    CONTEXT_SAFE_DUPLICATE_TOKEN_OVERLAP_THRESHOLD,
    CONTEXT_SAFE_MINIMUM_SEMANTIC_SIMILARITY,
    CONTEXT_SAFE_SELECTION_POLICY_VERSION,
    RetrievalResult,
)


class ContextBudgetExceeded(ValueError):
    pass


class ContextRetrievalRejected(ValueError):
    pass


def estimate_tokens(text: str) -> int:
    return max(1, ceil(len(text.encode("utf-8")) / 4))


class ContextBuilder:
    version = "context-builder-v8"

    def __init__(self, *, max_input_tokens: int, reserved_output_tokens: int) -> None:
        self.token_budget = TokenBudget(
            max_input_tokens=max_input_tokens,
            reserved_output_tokens=reserved_output_tokens,
        )

    def build(
        self,
        *,
        request_id: UUID,
        trace_id: str,
        owner_id: UUID,
        identity: IdentityBundle,
        user_event: EventEnvelope,
        retrieval_result: RetrievalResult | None = None,
        personal_context: tuple[PersonalContextItem, ...] = (),
        conversation_history: tuple[ConversationHistoryItem, ...] = (),
    ) -> ContextPack:
        if not isinstance(user_event.payload, UserMessagePayload):
            raise TypeError("ContextBuilder requires a USER_MESSAGE event")
        if (
            user_event.owner_id != owner_id
            or user_event.request_id != request_id
            or user_event.trace_id != trace_id
        ):
            raise ContextRetrievalRejected(
                "current USER_MESSAGE does not match the ContextPack owner/request/trace"
            )
        if retrieval_result is not None:
            self._validate_retrieval_result(
                retrieval_result=retrieval_result,
                owner_id=owner_id,
                request_id=request_id,
                trace_id=trace_id,
                user_event=user_event,
            )
        identity_text = identity.system_text()
        user_text = "\n".join(part.text for part in user_event.payload.content_parts)
        public_identity_policy = DataPolicy.owner_default(
            PrivacyClass.PUBLIC, memory_eligible=False
        )
        identity_section = ContextSection(
                section_id="identity",
                section_type="identity",
                priority=100,
                content_parts=(TextContentPart(text=identity_text),),
                estimated_tokens=estimate_tokens(identity_text),
                source_refs=(
                    f"constitution/{identity.constitution.version_id}",
                    f"identity/{identity.identity.version_id}",
                    f"values/{identity.values.version_id}",
                ),
                data_policy=public_identity_policy,
                selection_reason="required_by_policy",
        )
        user_section = ContextSection(
            section_id="current-user-input",
            section_type="current_user_input",
            priority=100,
            content_parts=(TextContentPart(text=user_text),),
            estimated_tokens=estimate_tokens(user_text),
            source_refs=(f"event/{user_event.event_id}",),
            data_policy=user_event.data_policy,
            selection_reason="required_current_request",
        )
        required_tokens = identity_section.estimated_tokens + user_section.estimated_tokens
        available = (
            self.token_budget.max_input_tokens
            - self.token_budget.reserved_output_tokens
        )
        if required_tokens > available:
            raise ContextBudgetExceeded(
                f"required context needs {required_tokens} estimated tokens; "
                f"budget allows {available}"
            )
        personal_sections: list[ContextSection] = []
        excluded: list[dict[str, str]] = []
        remaining = available - required_tokens
        ordered_personal = sorted(
            personal_context,
            key=lambda value: (-value.priority, value.section_id),
        )

        def add_personal(item: PersonalContextItem) -> None:
            nonlocal remaining
            if item.owner_id != owner_id:
                raise ContextRetrievalRejected(
                    "personal context owner does not match ContextPack owner"
                )
            if (
                PRIVACY_RESTRICTION_ORDER[item.data_policy.privacy_class]
                > PRIVACY_RESTRICTION_ORDER[user_event.data_policy.privacy_class]
            ):
                raise ContextRetrievalRejected(
                    "personal context is more restrictive than the current request"
                )
            item_tokens = estimate_tokens(item.content_text)
            if item_tokens > remaining:
                excluded.append(
                    {
                        "candidate_ref": item.source_refs[0],
                        "reason_code": "token_budget_exceeded",
                    }
                )
                return
            personal_sections.append(
                ContextSection(
                    section_id=item.section_id,
                    section_type=item.section_type,
                    priority=item.priority,
                    content_parts=(TextContentPart(text=item.content_text),),
                    estimated_tokens=item_tokens,
                    source_refs=item.source_refs,
                    data_policy=item.data_policy,
                    selection_reason="selected_active_personal_context",
                )
            )
            remaining -= item_tokens

        for item in (value for value in ordered_personal if value.priority >= 90):
            add_personal(item)

        selected_history: list[ConversationHistoryItem] = []
        for item in reversed(conversation_history):
            if item.owner_id != owner_id or item.session_id != user_event.session_id:
                raise ContextRetrievalRejected(
                    "conversation history owner/session does not match current request"
                )
            if item.event_id == user_event.event_id:
                raise ContextRetrievalRejected("current user Event cannot repeat in history")
            if (
                PRIVACY_RESTRICTION_ORDER[item.data_policy.privacy_class]
                > PRIVACY_RESTRICTION_ORDER[user_event.data_policy.privacy_class]
            ):
                excluded.append({
                    "candidate_ref":f"event/{item.event_id}",
                    "reason_code":"privacy_class_exceeds_request",
                })
                continue
            item_tokens = estimate_tokens(item.content_text)
            if item_tokens > remaining:
                excluded.append({
                    "candidate_ref":f"event/{item.event_id}",
                    "reason_code":"token_budget_exceeded",
                })
                continue
            selected_history.append(item)
            remaining -= item_tokens
        selected_history.reverse()
        history_sections = [
            ContextSection(
                section_id=f"conversation-event-{item.event_id}",
                section_type=(
                    "conversation_user_message"
                    if item.role == "user"
                    else "conversation_assistant_message"
                ),
                priority=90,
                content_parts=(TextContentPart(text=item.content_text),),
                estimated_tokens=estimate_tokens(item.content_text),
                source_refs=(f"event/{item.event_id}",f"request/{item.request_id}"),
                data_policy=item.data_policy,
                selection_reason="selected_conversation_history",
            )
            for item in selected_history
        ]

        for item in (value for value in ordered_personal if value.priority < 90):
            add_personal(item)
        memory_sections: list[ContextSection] = []
        if retrieval_result is not None:
            for candidate in retrieval_result.candidates:
                if not candidate.context_eligible:
                    excluded.append(
                        {
                            "candidate_ref": (
                                f"memory/{candidate.memory_id}/revision/"
                                f"{candidate.memory_revision}"
                            ),
                            "reason_code": "retrieval_safety_gate_not_passed",
                        }
                    )
                    continue
                candidate_tokens = estimate_tokens(candidate.content_text)
                if candidate_tokens > remaining:
                    excluded.append(
                        {
                            "candidate_ref": (
                                f"memory/{candidate.memory_id}/revision/"
                                f"{candidate.memory_revision}"
                            ),
                            "reason_code": "token_budget_exceeded",
                        }
                    )
                    continue
                memory_sections.append(
                    ContextSection(
                        section_id=f"memory-{candidate.memory_id}-{candidate.memory_revision}",
                        section_type=f"{candidate.memory_class}_memory",
                        priority=max(0, min(99, 50 + round(candidate.score * 20))),
                        content_parts=(TextContentPart(text=candidate.content_text),),
                        estimated_tokens=candidate_tokens,
                        source_refs=(
                            f"memory/{candidate.memory_id}/revision/{candidate.memory_revision}",
                            *candidate.source_refs,
                        ),
                        data_policy=candidate.data_policy,
                        selection_reason="retrieved_relevant",
                    )
                )
                remaining -= candidate_tokens
        sections = (
            identity_section,
            *personal_sections,
            *memory_sections,
            *history_sections,
            user_section,
        )
        estimated_total = sum(section.estimated_tokens for section in sections)
        return ContextPack(
            trace_id=trace_id,
            owner_id=owner_id,
            request_id=request_id,
            constitution_version_id=identity.constitution.version_id,
            identity_version_id=identity.identity.version_id,
            values_version_id=identity.values.version_id,
            retrieval_result_id=(
                retrieval_result.retrieval_result_id if retrieval_result else None
            ),
            token_budget=self.token_budget,
            sections=sections,
            excluded_candidates=tuple(excluded),
            effective_data_policy=combine_policies(
                [section.data_policy for section in sections]
            ),
            estimated_total_tokens=estimated_total,
        )

    @staticmethod
    def _validate_retrieval_result(
        *,
        retrieval_result: RetrievalResult,
        owner_id: UUID,
        request_id: UUID,
        trace_id: str,
        user_event: EventEnvelope,
    ) -> None:
        if retrieval_result.owner_id != owner_id:
            raise ContextRetrievalRejected("retrieval owner does not match ContextPack owner")
        if retrieval_result.request_id != request_id:
            raise ContextRetrievalRejected(
                "retrieval request does not match ContextPack request"
            )
        if retrieval_result.trace_id != trace_id:
            raise ContextRetrievalRejected("retrieval trace does not match ContextPack trace")
        if retrieval_result.query_event_id != user_event.event_id:
            raise ContextRetrievalRejected(
                "retrieval query event does not match the current USER_MESSAGE"
            )
        if (
            retrieval_result.versions.algorithm_version
            != CONTEXT_SAFE_ALGORITHM_VERSION
            or retrieval_result.selection_policy.policy_version
            != CONTEXT_SAFE_SELECTION_POLICY_VERSION
            or (
                retrieval_result.selection_policy.minimum_semantic_similarity,
                retrieval_result.selection_policy.duplicate_similarity_threshold,
                retrieval_result.selection_policy.duplicate_token_overlap_threshold,
            )
            != (
                CONTEXT_SAFE_MINIMUM_SEMANTIC_SIMILARITY,
                CONTEXT_SAFE_DUPLICATE_SIMILARITY_THRESHOLD,
                CONTEXT_SAFE_DUPLICATE_TOKEN_OVERLAP_THRESHOLD,
            )
        ):
            raise ContextRetrievalRejected(
                "retrieval result did not pass the approved context-safety gate"
            )
        minimum = retrieval_result.selection_policy.minimum_semantic_similarity
        if minimum is None:
            raise ContextRetrievalRejected(
                "retrieval result has no minimum semantic similarity"
            )
        content_hashes: set[str] = set()
        for candidate in retrieval_result.candidates:
            if not candidate.context_eligible:
                raise ContextRetrievalRejected(
                    "retrieval result contains a candidate not approved for context"
                )
            semantic = candidate.score_components.semantic
            if (
                semantic is None
                or not isfinite(semantic)
                or semantic < minimum
            ):
                raise ContextRetrievalRejected(
                    "retrieval candidate does not meet the declared minimum semantic "
                    "similarity"
                )
            if candidate.content_hash in content_hashes:
                raise ContextRetrievalRejected(
                    "retrieval result repeats candidate content"
                )
            content_hashes.add(candidate.content_hash)
