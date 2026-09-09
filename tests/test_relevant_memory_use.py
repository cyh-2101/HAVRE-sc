from __future__ import annotations

import unittest
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from companion.context import (
    CONTEXT_PRESENTATION_VERSION,
    ContextBuilder,
    ContextPack,
    ContextSection,
    ConversationHistoryItem,
    TokenBudget,
    render_inference_messages,
)
from companion.events import EventEnvelope, TextContentPart, UserMessagePayload
from companion.context.experience_v1 import (
    OWNER_EXPERIENCE_AUTHORIZATION_REF,
    OWNER_EXPERIENCE_GUIDANCE,
    OWNER_EXPERIENCE_VERSION,
    owner_experience_policy,
)
from companion.identity import IdentityLoader
from companion.policy import DataPolicy, PrivacyClass
from evals.relevant_memory_use import (
    LEGACY_PRESENTATION_VERSION,
    load_suite,
    prompt_messages,
    score_case,
)
from mlsys.training.stage9a_memory_use_dataset_v1 import build_examples

UNSEEN_FIXTURE = Path("evals/fixtures/relevant_memory_use_unseen_v1.json")
SEALED_MEMORY_USE_PLAN_HASH = (
    "sha256:7873d3236f01a3ca422e246e18edc2bc601c7a8dd37052bb4b26cb07909f9ce7"
)
from mlsys.retrieval.models import (
    RetrievalCandidate,
    RetrievalResult,
    RetrievalScoreComponents,
    RetrievalSelectionPolicy,
    RetrievalTiming,
    RetrievalVersions,
)


def _section(
    section_id: str,
    section_type: str,
    text: str,
    source_ref: str,
) -> ContextSection:
    return ContextSection(
        section_id=section_id,
        section_type=section_type,
        priority=90,
        content_parts=(TextContentPart(text=text),),
        estimated_tokens=10,
        source_refs=(source_ref,),
        data_policy=DataPolicy.owner_default(PrivacyClass.NORMAL),
        selection_reason=(
            "required_by_policy"
            if section_type == "identity"
            else "required_current_request"
            if section_type == "current_user_input"
            else "selected_conversation_history"
            if section_type.startswith("conversation_")
            else "retrieved_relevant"
        ),
    )


class RelevantMemoryPresentationTests(unittest.TestCase):
    def test_renderer_uses_one_system_message_and_preserves_order_and_sources(self) -> None:
        owner_id = uuid.uuid4()
        request_id = uuid.uuid4()
        pack = ContextPack(
            trace_id=uuid.uuid4().hex,
            owner_id=owner_id,
            request_id=request_id,
            constitution_version_id="constitution-v1",
            identity_version_id="identity-v1",
            values_version_id="values-v1",
            token_budget=TokenBudget(max_input_tokens=4096, reserved_output_tokens=256),
            sections=(
                _section("identity", "identity", "Be HAVRE.", "identity/v1"),
                _section(
                    "history-user",
                    "conversation_user_message",
                    "Earlier turn",
                    "event/history-user",
                ),
                _section(
                    "history-assistant",
                    "conversation_assistant_message",
                    "Earlier reply",
                    "event/history-assistant",
                ),
                _section(
                    "memory-1",
                    "episodic_memory",
                    "The prior update damaged the save.",
                    "memory/1/revision/1",
                ),
                _section(
                    "memory-2",
                    "semantic_memory",
                    "The user likes sour candy.",
                    "memory/2/revision/1",
                ),
                _section(
                    "current",
                    "current_user_input",
                    "That game updated again.",
                    "event/current",
                ),
            ),
            effective_data_policy=DataPolicy.owner_default(PrivacyClass.NORMAL),
            estimated_total_tokens=60,
        )
        messages = render_inference_messages(pack)
        self.assertEqual([message.role for message in messages], ["system", "user", "assistant", "user"])
        system = messages[0].content_parts[0].text
        self.assertIn("selection is not a requirement to mention them", system)
        self.assertIn("current user message overrides", system)
        self.assertIn("candidate 1 (episodic)", system)
        self.assertIn("candidate 2 (semantic)", system)
        self.assertNotIn("Relevant shared history", messages[-1].content_parts[0].text)
        self.assertEqual(
            messages[0].source_refs,
            (
                "identity/v1",
                "memory/1/revision/1",
                "memory/2/revision/1",
            ),
        )
    def test_owner_response_instruction_is_separate_from_memory_evidence(self) -> None:
        owner_id = uuid.uuid4()
        instruction = ContextSection(
            section_id="owner-instruction",
            section_type="owner_wording_correction",
            priority=99,
            content_parts=(TextContentPart(text=(
                "The owner explicitly rejected wording or framing used in the "
                "immediately preceding assistant reply. Apply it silently."
            )),),
            estimated_tokens=20,
            source_refs=("event/current",),
            data_policy=DataPolicy.owner_default(PrivacyClass.NORMAL),
            selection_reason="selected_active_personal_context",
        )
        pack = ContextPack(
            trace_id=uuid.uuid4().hex,
            owner_id=owner_id,
            request_id=uuid.uuid4(),
            constitution_version_id="constitution-v1",
            identity_version_id="identity-v1",
            values_version_id="values-v1",
            token_budget=TokenBudget(max_input_tokens=4096, reserved_output_tokens=256),
            sections=(
                _section("identity", "identity", "Be HAVRE.", "identity/v1"),
                ContextSection(
                    section_id=OWNER_EXPERIENCE_VERSION,
                    section_type="owner_response_instruction",
                    priority=100,
                    content_parts=(TextContentPart(
                        text=OWNER_EXPERIENCE_GUIDANCE
                    ),),
                    estimated_tokens=300,
                    source_refs=(
                        f"authorization/{OWNER_EXPERIENCE_AUTHORIZATION_REF}",
                    ),
                    data_policy=owner_experience_policy(),
                    selection_reason="required_by_policy",
                ),
                instruction,
                _section(
                    "rejected-assistant",
                    "conversation_assistant_message",
                    "先别叫我直接替你把今天过掉。",
                    "event/rejected-assistant",
                ),
                _section(
                    "current",
                    "current_user_input",
                    "别再说‘替我把今天过掉’。",
                    "event/current",
                ),
            ),
            effective_data_policy=DataPolicy.owner_default(PrivacyClass.NORMAL),
            estimated_total_tokens=50,
        )
        messages = render_inference_messages(pack)
        system = messages[0].content_parts[0].text
        self.assertIn("Current owner response constraints", system)
        self.assertIn("Do not merely answer and stop", system)
        self.assertNotIn("Relevant shared history", system)
        provider_text = "\n".join(
            part.text for message in messages for part in message.content_parts
        )
        self.assertNotIn("替我把今天过掉", provider_text)
        self.assertNotIn("把今天过掉", provider_text)
        self.assertIn("event/current", messages[0].source_refs)
        assistant = next(message for message in messages if message.role == "assistant")
        self.assertIn("event/rejected-assistant", assistant.source_refs)

    def test_builder_accepts_owner_history_across_session_rotation(self) -> None:
        owner_id = uuid.uuid4()
        request_id = uuid.uuid4()
        trace_id = uuid.uuid4().hex
        current_session = uuid.uuid4()
        user_event = EventEnvelope(
            event_type="USER_MESSAGE",
            owner_id=owner_id,
            session_id=current_session,
            request_id=request_id,
            trace_id=trace_id,
            data_policy=DataPolicy.owner_default(PrivacyClass.NORMAL),
            payload=UserMessagePayload(
                content_parts=(TextContentPart(text="继续刚才那个"),),
                channel="web",
            ),
        )
        history = ConversationHistoryItem(
            owner_id=owner_id,
            session_id=uuid.uuid4(),
            event_id=uuid.uuid4(),
            request_id=uuid.uuid4(),
            role="user",
            content_text="跨设备上一轮",
            recorded_at=datetime.now(UTC) - timedelta(minutes=1),
            data_policy=DataPolicy.owner_default(PrivacyClass.NORMAL),
        )
        pack = ContextBuilder(max_input_tokens=4096, reserved_output_tokens=256).build(
            request_id=request_id,
            trace_id=trace_id,
            owner_id=owner_id,
            identity=IdentityLoader(Path("identity")).load(),
            user_event=user_event,
            conversation_history=(history,),
        )
        self.assertIn(
            "跨设备上一轮",
            [part.text for section in pack.sections for part in section.content_parts],
        )


    def test_no_memory_omits_memory_guidance(self) -> None:
        owner_id = uuid.uuid4()
        pack = ContextPack(
            trace_id=uuid.uuid4().hex,
            owner_id=owner_id,
            request_id=uuid.uuid4(),
            constitution_version_id="constitution-v1",
            identity_version_id="identity-v1",
            values_version_id="values-v1",
            token_budget=TokenBudget(max_input_tokens=4096, reserved_output_tokens=256),
            sections=(
                _section("identity", "identity", "Be HAVRE.", "identity/v1"),
                _section("current", "current_user_input", "Hi.", "event/current"),
            ),
            effective_data_policy=DataPolicy.owner_default(PrivacyClass.NORMAL),
            estimated_total_tokens=20,
        )
        messages = render_inference_messages(pack)
        self.assertEqual(len(messages), 2)
        self.assertNotIn("Relevant shared history", messages[0].content_parts[0].text)

    def test_gated_memory_is_budgeted_before_optional_old_history(self) -> None:
        owner_id = uuid.uuid4()
        request_id = uuid.uuid4()
        trace_id = uuid.uuid4().hex
        session_id = uuid.uuid4()
        user_event = EventEnvelope(
            event_type="USER_MESSAGE",
            owner_id=owner_id,
            session_id=session_id,
            request_id=request_id,
            trace_id=trace_id,
            data_policy=DataPolicy.owner_default(PrivacyClass.NORMAL),
            payload=UserMessagePayload(
                content_parts=(TextContentPart(text="That game updated again."),),
                channel="api",
            ),
        )
        identity = IdentityLoader(Path("identity")).load()
        base = ContextBuilder(max_input_tokens=4096, reserved_output_tokens=256).build(
            request_id=request_id,
            trace_id=trace_id,
            owner_id=owner_id,
            identity=identity,
            user_event=user_event,
        )
        memory_id = uuid.uuid4()
        memory_text = "save corruption " * 30
        retrieval = RetrievalResult(
            retrieval_request_id=uuid.uuid4(),
            request_id=request_id,
            query_event_id=user_event.event_id,
            trace_id=trace_id,
            owner_id=owner_id,
            as_of=datetime.now(UTC),
            versions=RetrievalVersions(
                algorithm_version="retrieval-r1-vector-gated-v2",
                embedding_version_id="embedding-deterministic-hash-v1",
                index_version="memory-exact-scan-v1",
            ),
            selection_policy=RetrievalSelectionPolicy(
                policy_version="retrieval-selection-context-safe-v1",
                minimum_semantic_similarity=0.35,
                duplicate_similarity_threshold=0.70,
                duplicate_token_overlap_threshold=0.65,
            ),
            candidates=(
                RetrievalCandidate(
                    rank=1,
                    memory_id=memory_id,
                    memory_revision=1,
                    content_text=memory_text,
                    score=0.8,
                    score_components=RetrievalScoreComponents(
                        semantic=0.8,
                        recency=1.0,
                        importance=0.5,
                    ),
                    selection_reason_codes=("exact_vector_similarity",),
                    context_eligible=True,
                    source_refs=("event/source",),
                    data_policy=DataPolicy.owner_default(PrivacyClass.NORMAL),
                    content_hash="sha256:" + "a" * 64,
                    created_at=datetime.now(UTC) - timedelta(days=2),
                ),
            ),
            timing_ms=RetrievalTiming(
                query_embedding=0,
                candidate_search=0,
                filtering=0,
                reranking=0,
                total=0,
            ),
        )
        history = ConversationHistoryItem(
            owner_id=owner_id,
            session_id=session_id,
            event_id=uuid.uuid4(),
            request_id=uuid.uuid4(),
            role="user",
            content_text="old turn " * 800,
            recorded_at=datetime.now(UTC) - timedelta(minutes=5),
            data_policy=DataPolicy.owner_default(PrivacyClass.NORMAL),
        )
        memory_tokens = max(1, len(memory_text.encode("utf-8")) // 4 + 1)
        constrained = ContextBuilder(
            max_input_tokens=base.estimated_total_tokens + 256 + memory_tokens + 1600,
            reserved_output_tokens=256,
        ).build(
            request_id=request_id,
            trace_id=trace_id,
            owner_id=owner_id,
            identity=identity,
            user_event=user_event,
            retrieval_result=retrieval,
            conversation_history=(history,),
        )
        types = [section.section_type for section in constrained.sections]
        self.assertIn("episodic_memory", types)
        self.assertNotIn("conversation_user_message", types)
        self.assertEqual(constrained.builder_version, "context-builder-v18")
        self.assertLessEqual(
            constrained.estimated_total_tokens,
            constrained.token_budget.max_input_tokens
            - constrained.token_budget.reserved_output_tokens,
        )
        self.assertTrue(
            any(
                item["candidate_ref"] == f"event/{history.event_id}"
                and item["reason_code"] == "token_budget_exceeded"
                for item in constrained.excluded_candidates
            )
        )

    def test_multiple_ranked_memories_cannot_crowd_out_recent_history(self) -> None:
        owner_id = uuid.uuid4()
        request_id = uuid.uuid4()
        trace_id = uuid.uuid4().hex
        session_id = uuid.uuid4()
        user_event = EventEnvelope(
            event_type="USER_MESSAGE",
            owner_id=owner_id,
            session_id=session_id,
            request_id=request_id,
            trace_id=trace_id,
            data_policy=DataPolicy.owner_default(PrivacyClass.NORMAL),
            payload=UserMessagePayload(
                content_parts=(TextContentPart(text="What should I do next?"),),
                channel="api",
            ),
        )
        candidates = tuple(
            RetrievalCandidate(
                rank=index,
                memory_id=uuid.uuid4(),
                memory_revision=1,
                content_text=(f"candidate {index} " * 80),
                score=0.9 - index * 0.05,
                score_components=RetrievalScoreComponents(
                    semantic=0.9 - index * 0.05,
                    recency=1.0,
                    importance=0.5,
                ),
                selection_reason_codes=("exact_vector_similarity",),
                context_eligible=True,
                source_refs=(f"event/source-{index}",),
                data_policy=DataPolicy.owner_default(PrivacyClass.NORMAL),
                content_hash="sha256:" + str(index) * 64,
                created_at=datetime.now(UTC) - timedelta(days=index),
            )
            for index in range(1, 6)
        )
        retrieval = RetrievalResult(
            retrieval_request_id=uuid.uuid4(),
            request_id=request_id,
            query_event_id=user_event.event_id,
            trace_id=trace_id,
            owner_id=owner_id,
            as_of=datetime.now(UTC),
            versions=RetrievalVersions(
                algorithm_version="retrieval-r1-vector-gated-v2",
                embedding_version_id="embedding-deterministic-hash-v1",
                index_version="memory-exact-scan-v1",
            ),
            selection_policy=RetrievalSelectionPolicy(
                policy_version="retrieval-selection-context-safe-v1",
                minimum_semantic_similarity=0.35,
                duplicate_similarity_threshold=0.70,
                duplicate_token_overlap_threshold=0.65,
            ),
            candidates=candidates,
            timing_ms=RetrievalTiming(
                query_embedding=0,
                candidate_search=0,
                filtering=0,
                reranking=0,
                total=0,
            ),
        )
        history = ConversationHistoryItem(
            owner_id=owner_id,
            session_id=session_id,
            event_id=uuid.uuid4(),
            request_id=uuid.uuid4(),
            role="assistant",
            content_text="Most recent reply must survive.",
            recorded_at=datetime.now(UTC) - timedelta(minutes=1),
            data_policy=DataPolicy.owner_default(PrivacyClass.NORMAL),
        )
        pack = ContextBuilder(
            max_input_tokens=2048,
            reserved_output_tokens=256,
        ).build(
            request_id=request_id,
            trace_id=trace_id,
            owner_id=owner_id,
            identity=IdentityLoader(Path("identity")).load(),
            user_event=user_event,
            retrieval_result=retrieval,
            conversation_history=(history,),
        )
        types = [section.section_type for section in pack.sections]
        self.assertIn("conversation_assistant_message", types)
        self.assertLess(types.count("episodic_memory"), 5)
        self.assertTrue(
            any(
                item["reason_code"]
                == "memory_budget_reserved_for_recent_conversation"
                for item in pack.excluded_candidates
            )
        )


class RelevantMemorySuiteTests(unittest.TestCase):
    def test_suite_has_exact_paired_counterfactuals(self) -> None:
        suite = load_suite()
        self.assertEqual(len(suite["cases"]), 15)
        self.assertEqual(len(suite["multi_memory_cases"]), 3)
        self.assertEqual(len(suite["casual_regression_cases"]), 5)

    def test_post_plan_unseen_suite_is_bound_and_counterfactual(self) -> None:
        suite = load_suite(UNSEEN_FIXTURE)
        self.assertEqual(suite["suite_id"], "relevant-memory-use-post-plan-unseen-v1")
        self.assertEqual(
            suite["authored_after_training_plan_hash"],
            SEALED_MEMORY_USE_PLAN_HASH,
        )
        self.assertEqual(len(suite["cases"]), 20)
        self.assertEqual(len(suite["multi_memory_cases"]), 4)
        self.assertEqual(len(suite["casual_regression_cases"]), 8)
        training = [item for rows in build_examples().values() for item in rows]
        training_inputs = {item["user_message"] for item in training}
        training_memories = {
            memory["text"]
            for item in training
            for memory in item["memories"]
        }
        unseen_cases = [
            *suite["cases"],
            *suite["multi_memory_cases"],
            *suite["casual_regression_cases"],
        ]
        self.assertTrue(training_inputs.isdisjoint(
            {item["user_message"] for item in unseen_cases}
        ))
        self.assertTrue(training_memories.isdisjoint({
            memory
            for item in [*suite["cases"], *suite["multi_memory_cases"]]
            for memory in item["memory_context"]
        }))

    def test_prompt_versions_reproduce_legacy_and_new_shapes(self) -> None:
        case = load_suite()["cases"][0]
        legacy = prompt_messages(
            case,
            system_text="identity",
            presentation_version=LEGACY_PRESENTATION_VERSION,
        )
        revised = prompt_messages(
            case,
            system_text="identity",
            presentation_version=CONTEXT_PRESENTATION_VERSION,
        )
        self.assertEqual([row["role"] for row in legacy], ["system", "system", "user"])
        self.assertEqual([row["role"] for row in revised], ["system", "user"])
        self.assertIn("selection is not a requirement", revised[0]["content"])
        self.assertIn("do not turn one event into a stable trait", revised[0]["content"])

    def test_scorer_separates_usefulness_from_keyword_only_naturalness(self) -> None:
        suite = load_suite()
        case = next(
            row for row in suite["cases"] if row["case_id"] == "self-reflection-relevant"
        )
        generic = score_case(
            case,
            "咋了？",
            global_forbidden_meta_phrases=suite["global_forbidden_meta_phrases"],
        )
        natural = score_case(
            case,
            "又是前几天那个“项目做了不少，但感觉自己没学进去”的感觉？",
            global_forbidden_meta_phrases=suite["global_forbidden_meta_phrases"],
        )
        meta = score_case(
            case,
            "根据我的记忆，你之前说项目做了不少但没学进去。",
            global_forbidden_meta_phrases=suite["global_forbidden_meta_phrases"],
        )
        self.assertTrue(generic["checks"]["naturalness_diagnostic"])
        self.assertFalse(generic["checks"]["ignored_relevant_history"])
        self.assertTrue(natural["deterministic_pass"])
        self.assertFalse(meta["checks"]["naturalness_diagnostic"])
        self.assertFalse(meta["checks"]["provenance_truth"])


if __name__ == "__main__":
    unittest.main()
