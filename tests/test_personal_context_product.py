from __future__ import annotations

import os
from pathlib import Path
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from companion.application import InteractionCommand, InteractionService
from companion.context import ContextBuilder, render_inference_messages
from companion.context.models import ContextPack, ConversationHistoryItem
from companion.context.corrections import owner_fact_corrections
from companion.context.freshness import StalePersonalContextError, source_context_is_current
from companion.memory.models import MemoryRevision
from companion.events import EventEnvelope, TextContentPart, UserMessagePayload
from companion.policy import DataPolicy
from companion.persistence import apply_migrations
from companion.policy import PrivacyClass
from companion.product.sources import source_previews
from companion.product.strong import ManualStrongBrainService
from mlsys.serving import DeterministicLocalProvider, Stage1Router
from companion.user_model.models import BeliefType
from services.api.app import create_app
from services.api.runtime import build_runtime
from services.api.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
DATABASE_URL = os.getenv('HAVRE_TEST_DATABASE_URL')


@unittest.skipUnless(DATABASE_URL, 'HAVRE_TEST_DATABASE_URL is required')
class PersonalContextProductTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        apply_migrations(DATABASE_URL, ROOT/'db/migrations')
        self.owner = uuid4()
        self.settings = Settings(
            database_url=DATABASE_URL, owner_id=self.owner, identity_root=ROOT/'identity',
            provider_id='deterministic-local', self_hosted_base_url='http://127.0.0.1:1',
            self_hosted_model_manifest=ROOT/'README.md', self_hosted_engine_manifest=ROOT/'README.md',
            context_token_budget=8192, reserved_output_tokens=512, inference_timeout_ms=10000,
            require_owner_api_token=False, enable_erasure_ledger=False,
        )
        self.runtime = build_runtime(self.settings)
        self.addAsyncCleanup(self.runtime.aclose)
        self.turn = await self.runtime.service.interact(InteractionCommand(
            message='记住，我喜欢在公园练吉他。', channel='web',
            privacy_class=PrivacyClass.NORMAL, memory_eligible=True,
            idempotency_key=f'product-source-test:{uuid4()}',
        ))
        while self.runtime.memory_worker.run_once() is not None:
            pass
        candidate = self.runtime.memory_service.list_candidates(owner_id=self.owner)[0]
        self.memory = self.runtime.memory_service.accept_candidate(
            owner_id=self.owner, candidate_id=candidate['candidate_id'], reason='Synthetic owner review',
        )

    async def test_correction_chain_and_belief_resolve_exact_owner_source(self):
        for wording in ('我喜欢在树荫下练吉他。', '我喜欢安静的树荫下练吉他。'):
            self.memory = self.runtime.memory_service.correct(
                owner_id=self.owner, memory_id=self.memory.memory_id,
                content_text=wording, reason='Synthetic explicit correction',
            )
        belief = self.runtime.user_model_service.propose_from_confirmed_memory(
            owner_id=self.owner, memory_id=self.memory.memory_id,
            statement='我偏好安静的练琴环境。', belief_type=BeliefType.PREFERENCE,
            confidence=.7, reason='Synthetic owner proposal',
        )
        subjects = (
            ('memory_revision', self.memory.memory_id, 3),
            ('belief_revision', belief.belief_id, belief.revision),
        )
        previews = source_previews(self.runtime.repository, owner_id=self.owner, subjects=subjects)
        for subject in subjects:
            self.assertEqual(len(previews[subject]), 1)
            self.assertEqual(previews[subject][0]['source_ref'], f'event/{self.turn.user_event_id}')
            self.assertEqual(previews[subject][0]['content'], '记住，我喜欢在公园练吉他。')
        self.assertEqual(source_previews(self.runtime.repository, owner_id=uuid4(), subjects=subjects), {})
        self.assertEqual(source_previews(
            self.runtime.repository, owner_id=uuid4(),
            subjects=(('event', self.turn.user_event_id, None),),
        ), {})
        self.assertEqual(source_previews(
            self.runtime.repository, owner_id=self.owner,
            subjects=(('memory_revision', self.memory.memory_id, 99),),
        ), {})

    async def test_corrected_memory_product_response_keeps_original_source(self):
        self.runtime.memory_service.correct(
            owner_id=self.owner, memory_id=self.memory.memory_id,
            content_text='我喜欢在树荫下练吉他。', reason='Synthetic explicit correction',
        )
        with TestClient(create_app(self.settings)) as client:
            response = client.get('/v1/product/memory')
            self.assertEqual(response.status_code, 200)
            row = response.json()['memories'][0]
            self.assertEqual(row['revision'], 2)
            self.assertEqual(row['source_previews'][0]['source_ref'], f'event/{self.turn.user_event_id}')
            self.assertIn('公园', row['source_previews'][0]['content'])
            self.assertIn('树荫', row['content_text'])

    async def test_source_erasure_does_not_leave_product_preview(self):
        subject = ('memory_revision', self.memory.memory_id, self.memory.revision)
        self.runtime.repository.erase_source_event_derivatives(
            owner_id=self.owner, source_event_id=self.turn.user_event_id,
        )
        self.assertEqual(source_previews(self.runtime.repository, owner_id=self.owner, subjects=(subject,)), {})

    async def test_revocation_blocks_direct_event_preview_while_preserving_raw_event(self):
        subject = ('event', self.turn.user_event_id, None)
        before = source_previews(self.runtime.repository, owner_id=self.owner, subjects=(subject,))
        self.assertEqual(before[subject][0]['source_ref'], f'event/{self.turn.user_event_id}')
        self.runtime.repository.erase_source_event_derivatives(
            owner_id=self.owner, source_event_id=self.turn.user_event_id,
        )
        raw = self.runtime.repository.event_by_id(owner_id=self.owner, event_id=self.turn.user_event_id)
        self.assertIsNotNone(raw)
        self.assertEqual(raw.payload.content_parts[0].text, '记住，我喜欢在公园练吉他。')
        with self.runtime.repository.pool.connection() as connection:
            revoked = connection.execute(
                "SELECT EXISTS(SELECT 1 FROM havre.offline_source_revocations "
                "WHERE owner_id=%s AND source_event_id=%s) AS present",
                (self.owner, self.turn.user_event_id),
            ).fetchone()
        self.assertTrue(revoked['present'])
        self.assertEqual(source_previews(
            self.runtime.repository, owner_id=self.owner, subjects=(subject,),
        ), {})

    def _correction_probe(self, *, instant=None):
        source = self.runtime.repository.event_by_id(owner_id=self.owner, event_id=self.turn.user_event_id)
        history = (ConversationHistoryItem(
            owner_id=self.owner, session_id=source.session_id, event_id=source.event_id,
            request_id=source.request_id, role='user', content_text=source.payload.content_parts[0].text,
            recorded_at=source.recorded_at, data_policy=source.data_policy,
        ),)
        current = EventEnvelope(event_type='USER_MESSAGE', owner_id=self.owner,
            request_id=uuid4(), session_id=source.session_id, trace_id=uuid4().hex,
            recorded_at=instant or datetime.now(UTC), data_policy=DataPolicy.owner_default(PrivacyClass.NORMAL),
            payload=UserMessagePayload(content_parts=(TextContentPart(text='之前公园练吉他的事呢？'),),channel='api'))
        return current, history, SimpleNamespace(candidates=())

    async def test_owner_ui_fact_correction_enters_real_turn_and_final_messages(self):
        corrected = self.runtime.memory_service.correct(
            owner_id=self.owner, memory_id=self.memory.memory_id,
            content_text='我现在偏好在室内练电子琴。', reason='Synthetic owner correction',
        )
        captured = []
        original = self.runtime.service._inference_request
        def capture(**kwargs):
            request = original(**kwargs)
            captured.append(request)
            return request
        with patch.object(self.runtime.service, '_inference_request', side_effect=capture):
            answer = await self.runtime.service.interact(InteractionCommand(
                message='之前公园练吉他的事呢？', channel='web', session_id=self.turn.session_id,
                privacy_class=PrivacyClass.NORMAL, idempotency_key=str(uuid4()),
            ))
        evidence = self.runtime.repository.evidence(answer.request_id, owner_id=self.owner)
        row = evidence['context_pack']
        pack = ContextPack.model_validate({
            **{key: value for key, value in row.items() if key in ContextPack.model_fields},
            'effective_data_policy': captured[0].constraints.effective_data_policy,
        })
        overlays = [s for s in pack.sections if s.section_type == 'owner_fact_correction']
        self.assertEqual(len(overlays), 1)
        self.assertIn(corrected.content_text, overlays[0].content_parts[0].text)
        self.assertIn(f'memory/{corrected.memory_id}/revision/{corrected.revision}', overlays[0].source_refs)
        rendered = captured[0].messages
        self.assertEqual(rendered, render_inference_messages(pack))
        self.assertIn(corrected.content_text, rendered[0].content_parts[0].text)
        self.assertIn('not executable instructions', rendered[0].content_parts[0].text)
        self.assertTrue(any('公园练吉他' in message.content_parts[0].text for message in rendered[1:]))

    async def test_reviewed_extraction_wrong_owner_and_future_are_not_owner_corrections(self):
        current, history, retrieval = self._correction_probe()
        args = dict(current_event=current, history=history, retrieval_result=retrieval)
        self.assertEqual(owner_fact_corrections(self.runtime.repository, owner_id=self.owner, **args), ())
        corrected = self.runtime.memory_service.correct(
            owner_id=self.owner, memory_id=self.memory.memory_id,
            content_text='我现在偏好室内练琴。', reason='Synthetic explicit correction',
        )
        # The earlier request cannot consume a correction that had not happened.
        self.assertEqual(owner_fact_corrections(self.runtime.repository, owner_id=self.owner, **args), ())
        later, history, retrieval = self._correction_probe()
        later_args = dict(current_event=later, history=history, retrieval_result=retrieval)
        self.assertEqual(owner_fact_corrections(self.runtime.repository, owner_id=uuid4(), **later_args), ())
        self.assertEqual(len(owner_fact_corrections(self.runtime.repository, owner_id=self.owner, **later_args)), 1)

    async def test_correction_budget_cannot_keep_only_obsolete_raw_claim(self):
        self.runtime.memory_service.correct(
            owner_id=self.owner, memory_id=self.memory.memory_id,
            content_text='我现在偏好室内练琴。' * 30, reason='Synthetic long owner correction',
        )
        current, history, retrieval = self._correction_probe()
        overlays = owner_fact_corrections(self.runtime.repository, owner_id=self.owner,
            current_event=current, history=history, retrieval_result=retrieval)
        args = dict(request_id=current.request_id, trace_id=current.trace_id,
                    owner_id=self.owner, identity=self.runtime.service.identity, user_event=current)
        baseline = ContextBuilder(max_input_tokens=8192, reserved_output_tokens=256).build(**args)
        small = ContextBuilder(max_input_tokens=baseline.estimated_total_tokens + 256 + 50,
                               reserved_output_tokens=256)
        with self.assertRaises(ValueError):
            small.build(**args, conversation_history=history, personal_context=overlays)

    async def test_explicit_correction_valid_to_is_exclusive(self):
        end = datetime.now(UTC) + timedelta(days=1)
        factory = lambda **values: MemoryRevision(**{**values, 'valid_to': end})
        with patch('companion.persistence.postgres.MemoryRevision', side_effect=factory):
            self.runtime.memory_service.correct(owner_id=self.owner, memory_id=self.memory.memory_id,
                content_text='For this interval I prefer indoor music practice.', reason='Synthetic time-bound correction')
        for instant, expected in ((end - timedelta(microseconds=1), 1), (end, 0),
                                  (end + timedelta(microseconds=1), 0)):
            current, history, retrieval = self._correction_probe(instant=instant)
            overlays = owner_fact_corrections(self.runtime.repository, owner_id=self.owner,
                current_event=current, history=history, retrieval_result=retrieval)
            self.assertEqual(len(overlays), expected)

    async def test_retracted_understanding_remains_historical_in_actual_final_messages(self):
        before, _, _ = self._correction_probe()
        retracted = self.runtime.memory_service.retract(owner_id=self.owner, memory_id=self.memory.memory_id,
            reason='Synthetic owner withdrawal of the interpretation')
        captured = []
        original = self.runtime.service._inference_request
        def capture(**kwargs):
            request = original(**kwargs)
            captured.append(request)
            return request
        with patch.object(self.runtime.service, '_inference_request', side_effect=capture):
            answer = await self.runtime.service.interact(InteractionCommand(
                message='之前公园练吉他的事呢？', channel='web', session_id=self.turn.session_id,
                privacy_class=PrivacyClass.NORMAL, idempotency_key=str(uuid4())))
        row = self.runtime.repository.evidence(answer.request_id, owner_id=self.owner)['context_pack']
        overlays = [section for section in row['sections'] if section['section_type'] == 'owner_fact_correction']
        self.assertEqual(len(overlays), 1)
        restriction = overlays[0]
        self.assertEqual(restriction['section_id'], f'owner-fact-retraction-{retracted.memory_id}-{retracted.revision}')
        self.assertIn(f'memory/{retracted.memory_id}/revision/{retracted.revision}', restriction['source_refs'])
        system = captured[0].messages[0].content_parts[0].text
        self.assertIn('The owner retracted this derived understanding', system)
        self.assertIn('not a current owner fact or preference', system)
        self.assertIn('Retraction does not assert the opposite', system)
        self.assertIn(retracted.content_text, system)
        self.assertTrue(any('公园练吉他' in message.content_parts[0].text for message in captured[0].messages[1:]))
        self.assertTrue(source_context_is_current(self.runtime.repository, owner_id=self.owner,
            context_pack_id=answer.context_pack_id))
        self.assertEqual(self.runtime.memory_service.list_active(owner_id=self.owner), [])
        current, history, retrieval = self._correction_probe()
        self.assertEqual(owner_fact_corrections(self.runtime.repository, owner_id=self.owner,
            current_event=before, history=history, retrieval_result=retrieval), ())
        self.assertEqual(owner_fact_corrections(self.runtime.repository, owner_id=uuid4(),
            current_event=current, history=history, retrieval_result=retrieval), ())
        args = dict(request_id=current.request_id, trace_id=current.trace_id,
            owner_id=self.owner, identity=self.runtime.service.identity, user_event=current)
        baseline = ContextBuilder(max_input_tokens=8192, reserved_output_tokens=256).build(**args)
        small = ContextBuilder(max_input_tokens=baseline.estimated_total_tokens + 256 + 20,
            reserved_output_tokens=256)
        restrictions = owner_fact_corrections(self.runtime.repository, owner_id=self.owner,
            current_event=current, history=history, retrieval_result=retrieval)
        with self.assertRaises(ValueError):
            small.build(**args, conversation_history=history, personal_context=restrictions)

    def _manual_strong(self):
        interaction = InteractionService(owner_id=self.owner, identity=self.runtime.service.identity,
            repository=self.runtime.repository,
            context_builder=ContextBuilder(max_input_tokens=8192, reserved_output_tokens=512),
            router=Stage1Router(), provider=DeterministicLocalProvider(),
            retrieval_service=self.runtime.service.retrieval_service, manual_strong_only=True)
        return ManualStrongBrainService(owner_id=self.owner, repository=self.runtime.repository,
            interaction_service=interaction), interaction

    async def test_manual_snapshot_preserves_selected_correction_without_new_overlay_lookup(self):
        corrected = self.runtime.memory_service.correct(owner_id=self.owner, memory_id=self.memory.memory_id,
            content_text='我现在偏好在室内练电子琴。', reason='Synthetic owner correction')
        source = await self.runtime.service.interact(InteractionCommand(
            message='之前公园练吉他的事呢？', channel='web', session_id=self.turn.session_id,
            privacy_class=PrivacyClass.NORMAL, idempotency_key=str(uuid4())))
        strong, interaction = self._manual_strong()
        context = strong.prepare(source_assistant_event_id=source.assistant_event_id,
            idempotency_key=str(uuid4()))
        selected = [item for item in context.personal_context if item.section_type == 'owner_fact_correction']
        self.assertEqual(len(selected), 1)
        self.assertIn(corrected.content_text, selected[0].content_text)
        self.assertIn(f'memory/{corrected.memory_id}/revision/{corrected.revision}', selected[0].source_refs)
        captured = []
        original = interaction._inference_request
        class StopBeforeProvider(RuntimeError):
            pass
        def capture(**kwargs):
            captured.append(original(**kwargs))
            raise StopBeforeProvider('synthetic stop after final message compilation')
        with patch('companion.context.corrections.owner_fact_corrections',
                   side_effect=AssertionError('manual disclosure must not add a new overlay')) as lookup:
            with patch.object(interaction, '_inference_request', side_effect=capture):
                with self.assertRaises(StopBeforeProvider):
                    await interaction.interact(InteractionCommand(
                        message='请用 Strong Brain 重新想想上一条回复。', channel='web',
                        session_id=source.session_id, privacy_class=PrivacyClass.HIGHLY_PRIVATE,
                        memory_eligible=False, idempotency_key=str(uuid4())), manual_strong_context=context)
        lookup.assert_not_called()
        self.assertEqual(len(captured), 1)
        self.assertIn(corrected.content_text, captured[0].messages[0].content_parts[0].text)

    async def test_manual_prepared_raw_snapshot_rejects_later_correction_and_reprepare(self):
        strong, interaction = self._manual_strong()
        context = strong.prepare(source_assistant_event_id=self.turn.assistant_event_id,
            idempotency_key=str(uuid4()))
        corrected = self.runtime.memory_service.correct(owner_id=self.owner, memory_id=self.memory.memory_id,
            content_text='A later private correction outside the selected snapshot.', reason='Synthetic owner correction')
        with patch.object(interaction, '_inference_request') as inference:
            with self.assertRaisesRegex(StalePersonalContextError, 'no longer current'):
                await interaction.interact(InteractionCommand(
                    message='请用 Strong Brain 重新想想上一条回复。', channel='web',
                    session_id=self.turn.session_id, privacy_class=PrivacyClass.HIGHLY_PRIVATE,
                    memory_eligible=False, idempotency_key=str(uuid4())), manual_strong_context=context)
        inference.assert_not_called()
        with self.assertRaisesRegex(StalePersonalContextError, 'new reviewed reply'):
            strong.prepare(source_assistant_event_id=self.turn.assistant_event_id, idempotency_key=str(uuid4()))
        self.assertFalse(any(corrected.content_text in item.content_text for item in context.personal_context))

    async def test_manual_prepared_raw_snapshot_rejects_later_retraction(self):
        strong, interaction = self._manual_strong()
        context = strong.prepare(source_assistant_event_id=self.turn.assistant_event_id,
            idempotency_key=str(uuid4()))
        self.runtime.memory_service.retract(owner_id=self.owner, memory_id=self.memory.memory_id,
            reason='Synthetic owner withdrawal after preparing disclosure')
        with patch.object(interaction, '_inference_request') as inference:
            with self.assertRaises(StalePersonalContextError):
                await interaction.interact(InteractionCommand(
                    message='请用 Strong Brain 重新想想上一条回复。', channel='web',
                    session_id=self.turn.session_id, privacy_class=PrivacyClass.HIGHLY_PRIVATE,
                    memory_eligible=False, idempotency_key=str(uuid4())), manual_strong_context=context)
        inference.assert_not_called()

    async def test_manual_source_revocation_rejects_snapshot_preparation(self):
        strong, _ = self._manual_strong()
        self.runtime.repository.erase_source_event_derivatives(owner_id=self.owner,
            source_event_id=self.turn.user_event_id)
        with self.assertRaises((StalePersonalContextError, LookupError)):
            strong.prepare(source_assistant_event_id=self.turn.assistant_event_id, idempotency_key=str(uuid4()))

    async def test_manual_private_long_history_preserves_only_selected_exact_excerpt(self):
        for privacy in (PrivacyClass.PRIVATE, PrivacyClass.LOCAL_ONLY):
            with self.subTest(privacy=privacy):
                secret = f'UNSELECTED_SYNTHETIC_SECRET_{uuid4().hex}'
                narrative = 'A synthetic background observation. ' * 80 + secret
                source = await self.runtime.service.interact(InteractionCommand(
                    message=narrative, channel='web', privacy_class=privacy,
                    memory_eligible=False, idempotency_key=str(uuid4())))
                raw = self.runtime.repository.event_by_id(owner_id=self.owner, event_id=source.user_event_id)
                excerpt = ('[Exact excerpt from preserved Event, characters 0:35 of '
                           f'{len(narrative)}; omitted text is not visible here.]\n' + narrative[:35])
                history = (ConversationHistoryItem(owner_id=self.owner, session_id=source.session_id,
                    event_id=source.user_event_id, request_id=source.request_id, role='user',
                    content_text=excerpt, recorded_at=raw.recorded_at, data_policy=raw.data_policy),)
                # Isolate the already-selected excerpt boundary, while using
                # actual source persistence, compiler, disclosure, and messages.
                with patch.object(self.runtime.repository, 'select_conversation_history', return_value=history):
                    with patch('companion.context.recall.recalled_history', return_value=history):
                        selected = await self.runtime.service.interact(InteractionCommand(
                            message='Continue the selected observation.', channel='web',
                            privacy_class=privacy, session_id=source.session_id, memory_eligible=False,
                            idempotency_key=str(uuid4())))
                pack = self.runtime.repository.evidence(selected.request_id, owner_id=self.owner)['context_pack']
                old_source = next(section for section in pack['sections']
                    if section['section_type'] == 'conversation_user_message'
                    and f'event/{source.user_event_id}' in section['source_refs'])
                selected_text = old_source['content_parts'][0]['text']
                self.assertTrue(selected_text.endswith(excerpt))
                strong, interaction = self._manual_strong()
                context = strong.prepare(source_assistant_event_id=selected.assistant_event_id,
                    idempotency_key=str(uuid4()))
                disclosed = next(item for item in context.conversation_history if item.event_id == source.user_event_id)
                self.assertEqual(disclosed.content_text, selected_text)
                self.assertNotIn(secret, context.model_dump_json())
                captured = []
                original = interaction._inference_request
                class StopBeforeProvider(RuntimeError):
                    pass
                def capture(**kwargs):
                    captured.append(original(**kwargs))
                    raise StopBeforeProvider('synthetic stop after exact provider messages')
                with patch.object(interaction, '_inference_request', side_effect=capture):
                    with self.assertRaises(StopBeforeProvider):
                        await interaction.interact(InteractionCommand(
                            message='请用 Strong Brain 重新想想上一条回复。', channel='web',
                            session_id=selected.session_id, privacy_class=PrivacyClass.HIGHLY_PRIVATE,
                            memory_eligible=False, idempotency_key=str(uuid4())), manual_strong_context=context)
                self.assertEqual(len(captured), 1)
                rendered = '\n'.join(part.text for message in captured[0].messages for part in message.content_parts)
                self.assertIn(selected_text, rendered)
                self.assertNotIn(secret, rendered)
                preserved = self.runtime.repository.event_by_id(owner_id=self.owner, event_id=source.user_event_id)
                self.assertEqual(preserved.payload.content_parts[0].text, narrative)


if __name__ == '__main__':
    unittest.main()
