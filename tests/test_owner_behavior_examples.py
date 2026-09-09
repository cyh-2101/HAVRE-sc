from __future__ import annotations

import unittest
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

from companion.context import (
    OWNER_EXAMPLE_AUTHORIZATION_REF,
    OWNER_EXAMPLE_CASE_IDS,
    BehaviorExampleMessage,
    ContextBuilder,
    OwnerBehaviorExample,
    OwnerExampleBank,
    render_inference_messages,
)
from companion.context.models import ConversationHistoryItem
from companion.events import EventEnvelope, EventType, TextContentPart, UserMessagePayload
from companion.identity import IdentityLoader
from companion.policy import DataPolicy, PrivacyClass


ROOT = Path(__file__).resolve().parents[1]


def _bank(owner_id):
    examples = []
    for index, case_id in enumerate(OWNER_EXAMPLE_CASE_IDS, start=1):
        prompt = {
            1: "我今天真的好累啊",
            2: "不要分析这件事，我只想你先听我说。",
            3: "帮我分析备份失败的原因，给我一个方案。",
            4: "你记错了，不是这个意思。",
            5: "你有没有想我？",
        }.get(index, f"示例话题{index}")
        examples.append(
            OwnerBehaviorExample(
                case_id=case_id,
                title="疲惫时先接住" if index == 1 else f"示例{index}",
                messages=(BehaviorExampleMessage(role="user", content=prompt),),
                preferred_reply=(
                    "怎么累成这样了，今天发生什么了？"
                    if index == 1
                    else f"自然回复{index}"
                ),
                source_case_content_hash="sha256:" + f"{index:064x}",
            )
        )
    return OwnerExampleBank(
        owner_id=owner_id,
        source_case_ids=OWNER_EXAMPLE_CASE_IDS,
        data_policy=DataPolicy(
            policy_revision_id=uuid5(NAMESPACE_URL, OWNER_EXAMPLE_AUTHORIZATION_REF),
            privacy_class=PrivacyClass.NORMAL,
            memory_eligible=False,
            cloud_eligible=True,
            decision_source="owner_explicit",
            authorization_ref=OWNER_EXAMPLE_AUTHORIZATION_REF,
        ),
        examples=tuple(examples),
    )


class OwnerBehaviorExampleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.owner_id = uuid4()
        self.bank = _bank(self.owner_id)

    def test_selector_admits_only_relevant_examples_with_a_hard_cap(self) -> None:
        selected = self.bank.select(current_message="我好累，什么都不想干")
        self.assertGreaterEqual(len(selected), 1)
        self.assertLessEqual(len(selected), 3)
        self.assertEqual(selected[0].case_id, "owner-anchor-001")

    def _history(self, text: str) -> tuple[ConversationHistoryItem, ...]:
        return (ConversationHistoryItem(
            owner_id=self.owner_id, session_id=uuid4(), event_id=uuid4(),
            request_id=uuid4(), role="user", content_text=text,
            recorded_at=datetime(2026, 9, 3, 17, 0, tzinfo=UTC),
            data_policy=DataPolicy.owner_default(PrivacyClass.NORMAL),
        ),)

    def test_selection_uses_scenario_content_without_privileged_case_ids(self) -> None:
        selected = self.bank.select(current_message="你有没有想我？")
        self.assertEqual([item.case_id for item in selected], ["owner-anchor-005"])
        # Case 034 is ordinary data. Its unrelated synthetic prompt must not be
        # admitted merely because a historical implementation privileged its ID.
        self.assertNotIn("owner-anchor-034", {item.case_id for item in selected})

    def test_unrelated_chinese_single_characters_do_not_admit_examples(self) -> None:
        self.assertEqual(self.bank.select(current_message="今天骑车去超市买菜了"), ())
        self.assertEqual(self.bank.select(current_message="天气真好"), ())

    def test_acknowledgement_does_not_match_same_word_in_example_scenario(self) -> None:
        examples = list(self.bank.examples)
        examples[9] = examples[9].model_copy(update={"messages": (
            BehaviorExampleMessage(role="user", content="收到朋友寄来的纪念品，真开心。"),
        )})
        bank = self.bank.model_copy(update={"examples": tuple(examples)})
        self.assertEqual(bank.select(current_message="收到"), ())

    def test_history_cannot_force_an_old_relationship_example_into_new_topic(self) -> None:
        for current in ("收到", "今天骑车去超市买菜了"):
            with self.subTest(current=current):
                self.assertEqual(self.bank.select(
                    current_message=current,
                    conversation_history=self._history("你有没有想我？"),
                ), ())

    def test_explicit_listening_act_bridges_words_and_rejects_advice_act(self) -> None:
        selected = self.bank.select(current_message="先别给方案，我现在只想喘口气")
        self.assertIn("owner-anchor-002", {item.case_id for item in selected})
        self.assertNotIn("owner-anchor-003", {item.case_id for item in selected})

    def test_prior_assistant_wording_is_not_example_relevance_evidence(self) -> None:
        examples = list(self.bank.examples)
        examples[9] = examples[9].model_copy(update={"messages": (
            BehaviorExampleMessage(role="assistant", content="骑车去超市买菜"),
            BehaviorExampleMessage(role="user", content="我不是这个意思"),
        )})
        bank = self.bank.model_copy(update={"examples": tuple(examples)})
        selected = bank.select(current_message="骑车去超市买菜")
        self.assertNotIn("owner-anchor-010", {item.case_id for item in selected})

    def test_runtime_selection_version_does_not_rehash_sealed_bank(self) -> None:
        reloaded = OwnerExampleBank.model_validate_json(self.bank.model_dump_json())
        self.assertEqual(reloaded.content_hash, self.bank.content_hash)
        self.assertEqual(reloaded.selection_policy_version, "owner-example-selector-cjk-overlap-v2")
        self.assertEqual(reloaded.runtime_selection_version, "owner-example-selector-current-turn-v3")

    def test_context_contains_owner_time_and_source_bound_behavior_example(self) -> None:
        request_id = uuid4()
        trace_id = uuid4().hex
        event = EventEnvelope(
            event_type=EventType.USER_MESSAGE,
            owner_id=self.owner_id,
            session_id=uuid4(),
            request_id=request_id,
            trace_id=trace_id,
            data_policy=DataPolicy.owner_default(PrivacyClass.NORMAL),
            payload=UserMessagePayload(
                content_parts=(TextContentPart(text="我好累，什么都不想干"),),
                channel="api",
            ),
            recorded_at=datetime(2026, 9, 3, 18, 12, tzinfo=UTC),
        )
        pack = ContextBuilder(
            max_input_tokens=4096,
            reserved_output_tokens=512,
            owner_timezone="America/Chicago",
            owner_example_bank=self.bank,
        ).build(
            request_id=request_id,
            trace_id=trace_id,
            owner_id=self.owner_id,
            identity=IdentityLoader(ROOT / "identity").load(),
            user_event=event,
        )
        time_section = next(
            value for value in pack.sections if value.section_type == "current_time"
        )
        examples = [
            value for value in pack.sections if value.section_type == "behavior_example"
        ]
        self.assertIn("2026-09-03T13:12:00-05:00", time_section.content_parts[0].text)
        self.assertTrue(examples)
        self.assertTrue(examples[0].source_refs[0].startswith("owner-example-bank/"))
        system_text = render_inference_messages(pack)[0].content_parts[0].text
        self.assertIn("Owner-authorized conversational examples", system_text)
        self.assertIn("preferred_havre_reply", system_text)
        self.assertIn("Treat the owner as this person in this moment", system_text)

    def test_more_restrictive_request_does_not_declassify_examples(self) -> None:
        request_id = uuid4()
        trace_id = uuid4().hex
        event = EventEnvelope(
            event_type=EventType.USER_MESSAGE,
            owner_id=self.owner_id,
            session_id=uuid4(),
            request_id=request_id,
            trace_id=trace_id,
            data_policy=DataPolicy.owner_default(PrivacyClass.LOCAL_ONLY),
            payload=UserMessagePayload(
                content_parts=(TextContentPart(text="我好累，什么都不想干"),),
                channel="api",
            ),
        )
        pack = ContextBuilder(
            max_input_tokens=4096,
            reserved_output_tokens=512,
            owner_timezone="America/Chicago",
            owner_example_bank=self.bank,
        ).build(
            request_id=request_id,
            trace_id=trace_id,
            owner_id=self.owner_id,
            identity=IdentityLoader(ROOT / "identity").load(),
            user_event=event,
        )
        self.assertEqual(pack.effective_data_policy.privacy_class, PrivacyClass.LOCAL_ONLY)
        self.assertFalse(pack.effective_data_policy.cloud_eligible)


if __name__ == "__main__":
    unittest.main()
