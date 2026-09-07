"""Causal admission tests using synthetic evidence, never owner examples."""
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import unittest

from companion.context.builder import ContextBuilder, estimate_tokens
from companion.context.compiler import PersonalContextCompiler
from companion.context.models import ContextSection, ConversationHistoryItem, PersonalContextItem
from companion.events import EventEnvelope, TextContentPart, UserMessagePayload
from companion.identity import IdentityLoader
from companion.policy import DataPolicy, PrivacyClass

POLICY = DataPolicy.owner_default(PrivacyClass.NORMAL)


def section(kind, name, text, *, priority=80, request=None):
    return ContextSection(section_id=name, section_type=kind, priority=priority,
        content_parts=(TextContentPart(text=text),), estimated_tokens=estimate_tokens(text),
        source_refs=(f"event/{name}", *((f"request/{request}",) if request else ())),
        data_policy=POLICY, selection_reason="selected_active_personal_context")


class PersonalContextCompilerTests(unittest.TestCase):
    def compile(self, candidates, budget=100, query=""):
        return PersonalContextCompiler().compile(required=(), candidates=candidates,
            maximum_tokens=budget, measure=lambda values:sum(s.estimated_tokens for s in values),
            maximum_privacy_class=PrivacyClass.NORMAL, query_text=query)

    def test_abstract_belief_and_voice_cannot_displace_concrete_experience(self):
        concrete=section("episodic_memory","actual","Actual owner experience "*8,priority=30)
        belief=section("user_belief","belief","Abstract interpretation "*8,priority=99)
        example=section("behavior_example","voice","Optional illustrative voice "*8,priority=99)
        result=self.compile((example,belief,concrete),budget=concrete.estimated_tokens+3)
        self.assertEqual([s.section_id for s in result.sections],["actual"])
        self.assertEqual(len(result.exclusions),2)

    def test_budget_cannot_orphan_an_assistant_guess_from_owner_turn(self):
        owner=section("conversation_user_message","owner","Owner qualification "*12,request="pair")
        assistant=section("conversation_assistant_message","assistant","Assistant guess",request="pair")
        result=self.compile((owner,assistant),budget=assistant.estimated_tokens+2)
        self.assertEqual(result.sections,())
        self.assertEqual({x["candidate_ref"] for x in result.exclusions},{"event/owner","event/assistant"})

    def test_exact_duplicate_from_two_selectors_is_removed_with_reason(self):
        result=self.compile((section("episodic_memory","one","Specific shared experience."),
                             section("user_belief","two","Specific shared experience!").model_copy(update={"source_refs":("event/one",)})))
        self.assertEqual([s.section_id for s in result.sections],["one"])
        self.assertEqual(result.exclusions[0]["reason_code"],"duplicate_evidence_suppressed")

    def test_same_words_from_distinct_experiences_remain_distinct(self):
        result=self.compile((section("episodic_memory","one","We repaired the telescope."),
                             section("episodic_memory","two","We repaired the telescope.")))
        self.assertEqual(len(result.sections),2)

    def test_topic_bearing_old_raw_turn_survives_newer_unrelated_filler(self):
        old=section("conversation_user_message","old","松桥望远镜项目有了新的进展",request="old")
        filler=section("conversation_user_message","filler","烤土豆和西兰花 "*15,request="filler")
        recent=section("conversation_user_message","recent","我又想起以前的事",request="recent")
        result=self.compile((old,filler,recent),budget=old.estimated_tokens+recent.estimated_tokens,
                            query="松桥望远镜项目")
        self.assertEqual([s.section_id for s in result.sections],["old","recent"])

    def test_cloud_reuse_rejects_stricter_evidence_before_optional_budget(self):
        private=section("behavior_example","private","private").model_copy(update={"data_policy":DataPolicy.owner_default(PrivacyClass.LOCAL_ONLY)})
        with self.assertRaisesRegex(ValueError,"not cloud authorized"):
            PersonalContextCompiler().compile(required=(),candidates=(private,),maximum_tokens=1,
                measure=lambda values:sum(s.estimated_tokens for s in values),
                maximum_privacy_class=PrivacyClass.LOCAL_ONLY,cloud_authorized=True)

    def test_builder_gives_real_history_budget_before_optional_examples(self):
        owner,request,session=uuid4(),uuid4(),uuid4()
        event=EventEnvelope(event_type="USER_MESSAGE",owner_id=owner,request_id=request,session_id=session,
            trace_id=uuid4().hex,data_policy=POLICY,
            payload=UserMessagePayload(content_parts=(TextContentPart(text="How did our telescope work go?"),),channel="api"))
        history=ConversationHistoryItem(owner_id=owner,session_id=session,event_id=uuid4(),request_id=uuid4(),
            role="user",content_text="Our telescope mirror was successfully repaired yesterday.",
            recorded_at=event.recorded_at-timedelta(minutes=1),data_policy=POLICY)
        example=SimpleNamespace(case_id="synthetic",source_refs=("authorization/synthetic","example/synthetic"),
                                rendered_text=lambda:"Optional calibration wording "*100)
        bank=SimpleNamespace(owner_id=owner,data_policy=POLICY,runtime_selection_version="synthetic-test-v1",
                             select=lambda **kwargs:(example,))
        identity=IdentityLoader(Path("identity")).load()
        args=dict(request_id=request,trace_id=event.trace_id,owner_id=owner,identity=identity,user_event=event)
        base=ContextBuilder(max_input_tokens=5000,reserved_output_tokens=256).build(**args)
        builder=ContextBuilder(max_input_tokens=base.estimated_total_tokens+256+history.content_text.__len__()+100,
                               reserved_output_tokens=256,owner_example_bank=bank)
        result=builder.build(**args,conversation_history=(history,))
        self.assertIn("conversation_user_message",[s.section_type for s in result.sections])
        self.assertNotIn("behavior_example",[s.section_type for s in result.sections])
        self.assertLessEqual(result.estimated_total_tokens,result.token_budget.max_input_tokens-256)
        self.assertTrue(any(s.source_refs[0]==f"event/{history.event_id}" for s in result.sections))

    def test_builder_excludes_future_raw_context(self):
        owner,request,session=uuid4(),uuid4(),uuid4()
        event=EventEnvelope(event_type="USER_MESSAGE",owner_id=owner,request_id=request,session_id=session,
            trace_id=uuid4().hex,data_policy=POLICY,payload=UserMessagePayload(
                content_parts=(TextContentPart(text="Today"),),channel="api"))
        history=ConversationHistoryItem(owner_id=owner,session_id=session,event_id=uuid4(),request_id=uuid4(),
            role="user",content_text="Future event",recorded_at=event.recorded_at+timedelta(seconds=1),data_policy=POLICY)
        result=ContextBuilder(max_input_tokens=5000,reserved_output_tokens=256).build(request_id=request,
            trace_id=event.trace_id,owner_id=owner,identity=IdentityLoader(Path("identity")).load(),user_event=event,
            conversation_history=(history,))
        self.assertEqual(result.excluded_candidates[0]["reason_code"],"not_before_current_turn")

    def test_public_turn_keeps_already_authorized_owner_guidance(self):
        owner,request,session=uuid4(),uuid4(),uuid4()
        event=EventEnvelope(event_type="USER_MESSAGE",owner_id=owner,request_id=request,session_id=session,
            trace_id=uuid4().hex,data_policy=DataPolicy.owner_default(PrivacyClass.PUBLIC),
            payload=UserMessagePayload(content_parts=(TextContentPart(text="Hello"),),channel="api"))
        result=ContextBuilder(max_input_tokens=5000,reserved_output_tokens=256).build(request_id=request,
            trace_id=event.trace_id,owner_id=owner,identity=IdentityLoader(Path("identity")).load(),user_event=event)
        self.assertTrue(result.effective_data_policy.cloud_eligible)
        self.assertIn("owner_response_instruction",[s.section_type for s in result.sections])

    def test_owner_fact_correction_is_mandatory_before_old_source_and_voice(self):
        correction=section("owner_fact_correction","correction","Current owner fact correction "*20)
        with self.assertRaisesRegex(ValueError,"required owner fact correction"):
            self.compile((section("conversation_user_message","old","Old report"),correction),budget=20)
        result=self.compile((section("user_belief","belief","Older interpretation"),correction),budget=correction.estimated_tokens)
        self.assertEqual([item.section_id for item in result.sections],["correction"])
