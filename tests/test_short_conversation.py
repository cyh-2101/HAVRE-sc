"""Control/provenance regressions, not semantic language-quality scores."""
from pathlib import Path
import unittest
from uuid import uuid4
from companion.context import ResponsePlanner, ResponsePlan, render_response_plan, parse_response_plan_json
from companion.context.experience import OWNER_EXPERIENCE_GUIDANCE, OWNER_EXPERIENCE_VERSION, owner_experience_policy
from companion.context.experience_v2 import OWNER_EXPERIENCE_GUIDANCE as V2_GUIDANCE


class ShortConversationTests(unittest.TestCase):
    def plan(self, text, **kwargs):
        return ResponsePlanner(**kwargs).plan(request_id=uuid4(), trace_id=uuid4().hex,
            owner_id=uuid4(), message=text, source_refs=("event/test",))

    def test_casual_sharing_does_not_demand_a_comment_for_every_clause(self):
        plan=self.plan("我今天去了新开的店。排了好久。买完又下雨了。到家鞋都湿透了。")
        self.assertEqual(plan.depth,"brief")
        self.assertNotEqual(plan.stance,"analytical")
        text=render_response_plan(plan)
        self.assertIn("they do not each require commentary",text)
        self.assertNotIn("Completeness outranks forced brevity",text)

    def test_long_sharing_is_not_automatically_an_analysis_request(self):
        plan=self.plan("今天在外面遇到好多事。"*60)
        self.assertEqual(plan.depth,"brief")

    def test_one_or_two_sentences_is_not_a_task_output_cap(self):
        for query in ("请详细解释电机控制原理", "请完整分析这个方案", "一步一步讲怎么实现", "Explain this in detail"):
            with self.subTest(query=query):
                plan=self.plan(query)
                self.assertEqual(plan.depth,"detailed")
                self.assertIn("tasks/detail requests still need complete answers",render_response_plan(plan))

    def test_code_and_multi_request_answer_remain_complete(self):
        code=self.plan("帮我写一个 Python 函数，返回排序后的输入列表")
        self.assertEqual(code.depth,"balanced")
        plan=self.plan("回答原因。另外比较方案。还有说明风险。然后给下一步。")
        self.assertEqual(plan.depth,"detailed")
        self.assertEqual(len(plan.must_address),4)

    def test_follow_on_imperatives_keep_their_request_meaning(self):
        plan=self.plan("先告诉我为什么体感差，再给我两个方案，最后给我一个明确建议")
        self.assertEqual(len(plan.must_address),3)
        self.assertTrue(all(item.kind != "context" for item in plan.must_address))
        self.assertEqual(plan.must_address[1].text,"给我两个方案")

    def test_detail_negation_is_not_an_expansion_request(self):
        self.assertEqual(self.plan("不要详细分析，我就是想吐槽").depth,"brief")

    def test_rejected_analysis_and_stopping_do_not_request_more_analysis(self):
        for query in ("我没让你分析啊，我就是随口说说", "先不用展开说了，我去忙"):
            with self.subTest(query=query):
                plan=self.plan(query)
                self.assertEqual(plan.mode,"talk")
                self.assertEqual(plan.depth,"brief")

    def test_say_more_survives_follow_on_segmentation(self):
        for query in ("再说点", "再说一点。", "Keep talking", "say more"):
            with self.subTest(query=query):
                plan=self.plan(query)
                self.assertEqual(plan.depth,"brief")
                self.assertEqual(len(plan.must_address),1)
                self.assertEqual(plan.must_address[0].text,query.strip())
                text=render_response_plan(plan)
                self.assertIn("one useful conversational step",text)
                self.assertIn("prior topic is absent or unclear",text)
                self.assertIn("do not invent one",text)

    def test_say_more_does_not_apply_to_incidental_words(self):
        plan=self.plan("帮我写一个名为 say more 的按钮，详细解释代码")
        self.assertEqual(plan.depth,"detailed")
        self.assertNotIn("one useful conversational step",render_response_plan(plan))

    def test_recall_correction_time_and_action_truth_are_not_length_exceptions_to_drop(self):
        recall=self.plan("还记得上次那个人吗",semantic_memory=True)
        self.assertEqual(recall.memory_need,"required")
        self.assertIn("ask one concise clarifying question",render_response_plan(recall))
        clock=self.plan("现在几点")
        self.assertTrue(clock.requires_current_time)
        self.assertIn("never infer the time of day",render_response_plan(clock))
        self.assertIn("corrections, urgent guidance or verified action results",render_response_plan(clock))

    def test_historical_plan_rendering_and_hash_are_not_rewritten(self):
        plan=self.plan("今天去看展了")
        payload=plan.model_dump(mode="json")
        payload.update(planner_version="response-planner-v5",content_hash="")
        old=ResponsePlan.model_validate(payload)
        loaded=parse_response_plan_json(old.model_dump_json())
        self.assertEqual(loaded.content_hash,old.content_hash)
        self.assertIn("Completeness outranks forced brevity",render_response_plan(loaded))
        self.assertNotIn("one short turn is complete",render_response_plan(loaded))

    def test_current_guidance_has_its_own_authority_and_no_training(self):
        self.assertEqual(OWNER_EXPERIENCE_VERSION,"owner-experience-first-v3-short-turns")
        self.assertNotIn("Do not squeeze an essay",V2_GUIDANCE)
        self.assertIn("Do not squeeze an essay",OWNER_EXPERIENCE_GUIDANCE)
        policy=owner_experience_policy()
        self.assertFalse(policy.training_eligible)
        self.assertFalse(policy.memory_eligible)
        self.assertIn("2026-09-06",policy.authorization_ref)
