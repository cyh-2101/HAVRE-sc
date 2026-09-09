"""Stage 2 Context Builder: governed identity, retrieved memory, current input."""

from __future__ import annotations

from math import ceil, isfinite
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from companion.context.examples import OwnerExampleBank
from companion.context.compiler import PersonalContextCompiler
from companion.context.experience import (
    OWNER_EXPERIENCE_AUTHORIZATION_REF,
    OWNER_EXPERIENCE_GUIDANCE,
    OWNER_EXPERIENCE_VERSION,
    owner_experience_policy,
)

from companion.context.models import (
    ContextPack,
    ContextSection,
    ConversationHistoryItem,
    PersonalContextItem,
    TokenBudget,
)
from companion.context.presentation import (
    behavior_examples_overhead_text,
    memory_evidence_overhead_text,
    personal_context_overhead_text,
)
from companion.context.response_plan import ResponsePlan, render_response_plan
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
    context_safety_profile,
    HYBRID_ALGORITHM_VERSION,
    HYBRID_EMBEDDING_VERSION,
)


class ContextBudgetExceeded(ValueError):
    pass


class ContextRetrievalRejected(ValueError):
    pass


def estimate_tokens(text: str) -> int:
    return max(1, ceil(len(text.encode("utf-8")) / 4))


class ContextBuilder:
    version = "context-builder-v18"

    def __init__(
        self,
        *,
        max_input_tokens: int,
        reserved_output_tokens: int,
        owner_timezone: str | None = None,
        owner_example_bank: OwnerExampleBank | None = None,
    ) -> None:
        self.token_budget = TokenBudget(
            max_input_tokens=max_input_tokens,
            reserved_output_tokens=reserved_output_tokens,
        )
        self.owner_timezone = owner_timezone
        self.owner_example_bank = owner_example_bank
        self._owner_zone: ZoneInfo | None = None
        if owner_timezone is not None:
            try:
                self._owner_zone = ZoneInfo(owner_timezone)
            except ZoneInfoNotFoundError as error:
                raise ValueError(f"unknown owner timezone {owner_timezone!r}") from error

    def rebind_selected_sections(self, context_pack: ContextPack) -> ContextPack:
        """Apply this provider budget without reselecting or dropping context."""

        available = (
            self.token_budget.max_input_tokens
            - self.token_budget.reserved_output_tokens
        )
        if context_pack.estimated_total_tokens > available:
            raise ContextBudgetExceeded(
                "selected context needs "
                f"{context_pack.estimated_total_tokens} estimated tokens; "
                f"budget allows {available}"
            )
        rebound = context_pack.model_dump(mode="python")
        rebound.update(
            {
                "token_budget": self.token_budget,
                "content_hash": "",
            }
        )
        return ContextPack.model_validate(rebound)

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
        response_plan: ResponsePlan | None = None,
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
        if user_event.payload.input_origin == "continuation_button":
            from companion.context.continuation import CONTINUATION_INPUT_TEXT
            user_text = CONTINUATION_INPUT_TEXT
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
        experience_section = ContextSection(
            section_id=OWNER_EXPERIENCE_VERSION,
            section_type="owner_response_instruction",
            priority=100,
            content_parts=(TextContentPart(text=OWNER_EXPERIENCE_GUIDANCE),),
            estimated_tokens=estimate_tokens(OWNER_EXPERIENCE_GUIDANCE),
            source_refs=(f"authorization/{OWNER_EXPERIENCE_AUTHORIZATION_REF}",),
            data_policy=owner_experience_policy(),
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
        runtime_sections: tuple[ContextSection, ...] = ()
        if self._owner_zone is not None and self.owner_timezone is not None:
            local_received_at = user_event.recorded_at.astimezone(self._owner_zone)
            time_text = (
                "Authoritative owner-local time when this message was received: "
                f"{local_received_at.isoformat(timespec='seconds')} "
                f"({self.owner_timezone}, {local_received_at.tzname()}). "
                "Use it for relative time-of-day wording; do not claim it remains "
                "the current time after this turn."
                " History timestamps are past message times. After a long gap, "
                "do not assume an ambiguous completion refers to the last old "
                "meal or task; ask briefly when the reference is unclear."
            )
            runtime_sections = (
                ContextSection(
                    section_id=f"current-time-{user_event.event_id}",
                    section_type="current_time",
                    priority=100,
                    content_parts=(TextContentPart(text=time_text),),
                    estimated_tokens=estimate_tokens(time_text),
                    source_refs=(
                        f"event/{user_event.event_id}#recorded_at",
                        f"timezone/{self.owner_timezone}",
                    ),
                    data_policy=public_identity_policy,
                    selection_reason="required_runtime_context",
                ),
            )
        plan_sections: tuple[ContextSection, ...] = ()
        if response_plan is not None:
            if (
                response_plan.owner_id != owner_id
                or response_plan.request_id != request_id
                or response_plan.trace_id != trace_id
            ):
                raise ContextRetrievalRejected(
                    "ResponsePlan does not match the ContextPack owner/request/trace"
                )
            plan_text = response_plan.model_dump_json()
            plan_sections = (
                ContextSection(
                    section_id=f"response-plan-{response_plan.content_hash}",
                    section_type="response_plan",
                    priority=100,
                    content_parts=(TextContentPart(text=plan_text),),
                    estimated_tokens=estimate_tokens(render_response_plan(response_plan)),
                    source_refs=response_plan.source_refs,
                    data_policy=user_event.data_policy,
                    selection_reason="required_current_request",
                ),
            )
        required_sections = (identity_section, experience_section, *plan_sections, *runtime_sections, user_section)
        available = self.token_budget.max_input_tokens - self.token_budget.reserved_output_tokens

        def measure(sections):
            memory_labels = tuple(s.section_type.removesuffix("_memory") for s in sections
                                  if s.section_type in {"episodic_memory", "semantic_memory", "pattern_memory", "progress_memory"})
            personal_labels = tuple(s.section_type for s in sections if s.section_type in {
                "owner_response_instruction", "owner_wording_correction", "owner_fact_correction", "communication_preference",
                "goal", "user_belief", "current_state", "calendar_availability",
            })
            example_count = sum(s.section_type == "behavior_example" for s in sections)
            total = sum(s.estimated_tokens for s in sections)
            if personal_labels:
                total += estimate_tokens(personal_context_overhead_text(personal_labels)) + estimate_tokens("\n\n")
            if memory_labels:
                total += estimate_tokens(memory_evidence_overhead_text(memory_labels)) + estimate_tokens("\n\n")
            if example_count:
                total += estimate_tokens(behavior_examples_overhead_text(example_count)) + estimate_tokens("\n\n")
            return total

        if measure(required_sections) > available:
            raise ContextBudgetExceeded(f"required context needs {measure(required_sections)} estimated tokens; budget allows {available}")
        candidates = []
        for item in personal_context:
            if item.owner_id != owner_id:
                raise ContextRetrievalRejected("personal context owner does not match ContextPack owner")
            if PRIVACY_RESTRICTION_ORDER[item.data_policy.privacy_class] > PRIVACY_RESTRICTION_ORDER[user_event.data_policy.privacy_class]:
                raise ContextRetrievalRejected("personal context is more restrictive than the current request")
            candidates.append(ContextSection(
                section_id=item.section_id, section_type=item.section_type, priority=item.priority,
                content_parts=(TextContentPart(text=item.content_text),), estimated_tokens=estimate_tokens(item.content_text),
                source_refs=item.source_refs, data_policy=item.data_policy,
                selection_reason="selected_active_personal_context",
            ))
        if retrieval_result is not None:
            for candidate in retrieval_result.candidates:
                candidates.append(ContextSection(
                    section_id=f"memory-{candidate.memory_id}-{candidate.memory_revision}",
                    section_type=f"{candidate.memory_class}_memory",
                    priority=max(0, min(99, 50 + round(candidate.score * 20))),
                    content_parts=(TextContentPart(text=candidate.content_text),),
                    estimated_tokens=estimate_tokens(candidate.content_text),
                    source_refs=(f"memory/{candidate.memory_id}/revision/{candidate.memory_revision}", *candidate.source_refs),
                    data_policy=candidate.data_policy, selection_reason="retrieved_relevant",
                ))
        history_exclusions = []
        for item in conversation_history:
            if item.owner_id != owner_id:
                raise ContextRetrievalRejected("conversation history owner does not match current request")
            if item.event_id == user_event.event_id:
                raise ContextRetrievalRejected("current user Event cannot repeat in history")
            if item.recorded_at >= user_event.recorded_at:
                history_exclusions.append({"candidate_ref": f"event/{item.event_id}", "reason_code": "not_before_current_turn"})
                continue
            history_text = item.content_text
            if self._owner_zone is not None:
                local = item.recorded_at.astimezone(self._owner_zone)
                history_text = f"[Recorded {local.isoformat(timespec='minutes')}]\n{history_text}"
            candidates.append(ContextSection(
                section_id=f"conversation-event-{item.event_id}",
                section_type="conversation_user_message" if item.role == "user" else "conversation_assistant_message",
                priority=90, content_parts=(TextContentPart(text=history_text),),
                estimated_tokens=estimate_tokens(history_text),
                source_refs=(*item.source_refs, f"request/{item.request_id}"),
                data_policy=item.data_policy, selection_reason="selected_conversation_history",
            ))
        if self.owner_example_bank is not None:
            if self.owner_example_bank.owner_id != owner_id:
                raise ContextRetrievalRejected("owner example bank does not match ContextPack owner")
            for example in self.owner_example_bank.select(current_message=user_text, conversation_history=conversation_history):
                example_text = example.rendered_text()
                candidates.append(ContextSection(
                    section_id=f"behavior-example-{example.case_id}", section_type="behavior_example", priority=95,
                    content_parts=(TextContentPart(text=example_text),), estimated_tokens=estimate_tokens(example_text),
                    source_refs=(*example.source_refs, f"owner-example-selector/{self.owner_example_bank.runtime_selection_version}"),
                    data_policy=self.owner_example_bank.data_policy, selection_reason="selected_behavior_example",
                ))
        compiled = PersonalContextCompiler().compile(
            required=required_sections, candidates=candidates, maximum_tokens=available,
            measure=measure, maximum_privacy_class=user_event.data_policy.privacy_class,
            query_text=user_text,
        )
        sections = compiled.sections
        if user_event.payload.reply_to_event_id is not None:
            parent_ref = f"event/{user_event.payload.reply_to_event_id}"
            if not any(section.section_type == "conversation_assistant_message" and parent_ref in section.source_refs for section in sections):
                raise ContextBudgetExceeded("the exact continuation reply does not fit the selected context")
        excluded = [*history_exclusions, *compiled.exclusions]
        estimated_total = compiled.estimated_tokens
        non_identity_policies = [
            section.data_policy for section in sections
            if section.section_type != "identity"
        ]
        explicit_policy = user_event.data_policy
        if (
            explicit_policy.privacy_class is PrivacyClass.HIGHLY_PRIVATE
            and explicit_policy.cloud_eligible
            and explicit_policy.decision_source == "owner_explicit"
            and explicit_policy.authorization_ref
            and all(
                policy.cloud_eligible
                and (
                    policy.policy_revision_id == explicit_policy.policy_revision_id
                    or PRIVACY_RESTRICTION_ORDER[policy.privacy_class]
                    < PRIVACY_RESTRICTION_ORDER[PrivacyClass.HIGHLY_PRIVATE]
                )
                for policy in non_identity_policies
            )
        ):
            # One exact owner-authorized disclosure policy governs every
            # equally restrictive section. Less-restrictive sections must already
            # be independently cloud-eligible; fixed response/runtime guidance is
            # not personal evidence and must not erase the explicit authorization.
            effective_policy = explicit_policy
        else:
            effective_policy = combine_policies(
                [section.data_policy for section in sections]
            )
        return ContextPack(
            trace_id=trace_id,
            owner_id=owner_id,
            request_id=request_id,
            builder_version=self.version,
            constitution_version_id=identity.constitution.version_id,
            identity_version_id=identity.identity.version_id,
            values_version_id=identity.values.version_id,
            retrieval_result_id=(
                retrieval_result.retrieval_result_id if retrieval_result else None
            ),
            token_budget=self.token_budget,
            sections=sections,
            excluded_candidates=tuple(excluded),
            effective_data_policy=effective_policy,
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
        profile = context_safety_profile(retrieval_result.versions.algorithm_version)
        if (
            profile is None
            or (
                retrieval_result.versions.algorithm_version == HYBRID_ALGORITHM_VERSION
                and retrieval_result.versions.embedding_version_id != HYBRID_EMBEDDING_VERSION
            )
            or (
                retrieval_result.selection_policy.policy_version,
                retrieval_result.selection_policy.minimum_semantic_similarity,
                retrieval_result.selection_policy.duplicate_similarity_threshold,
                retrieval_result.selection_policy.duplicate_token_overlap_threshold,
            )
            != profile
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
        expected_ranks = list(range(1, len(retrieval_result.candidates) + 1))
        if [
            candidate.rank for candidate in retrieval_result.candidates
        ] != expected_ranks:
            raise ContextRetrievalRejected(
                "retrieval candidates do not have unique contiguous rank order"
            )
        if any(
            not isfinite(candidate.score)
            for candidate in retrieval_result.candidates
        ) or any(
            current.score < following.score
            for current, following in zip(
                retrieval_result.candidates,
                retrieval_result.candidates[1:],
                strict=False,
            )
        ):
            raise ContextRetrievalRejected(
                "retrieval candidates are not in finite descending score order"
            )
        for candidate in retrieval_result.candidates:
            if not candidate.context_eligible:
                raise ContextRetrievalRejected(
                    "retrieval result contains a candidate not approved for context"
                )
            semantic = candidate.score_components.semantic
            if retrieval_result.versions.algorithm_version == HYBRID_ALGORITHM_VERSION and (
                semantic is not None and semantic < 0.45
                and (candidate.score_components.lexical or 0.0) < 0.25
            ):
                raise ContextRetrievalRejected("weak semantic evidence lacks lexical support")
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
