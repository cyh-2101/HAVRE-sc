"""Exact owner-source resolution and its unchanged admission/privacy boundaries."""
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import unittest
from uuid import uuid4

from companion.context.models import ConversationHistoryItem
from companion.context.presentation import render_inference_messages
from companion.context.recall import recalled_history
from companion.context.source_resolution import resolve_sources, reference_query, targeted_reference
from companion.policy import DataPolicy, PrivacyClass
from tests import test_personal_context_recall as recall_fixtures

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT/'evals/fixtures/context_recall_stress_v1.json').read_text('utf-8'))


class SourceResolutionTests(unittest.TestCase):
    def setUp(self):
        self.owner = uuid4(); self.session = uuid4(); self.now = datetime.now(UTC)

    def source(self, text, **overrides):
        data = dict(owner_id=self.owner, session_id=self.session, event_id=uuid4(), request_id=uuid4(),
                    role='user', content_text=text, recorded_at=self.now,
                    data_policy=DataPolicy.owner_default(PrivacyClass.NORMAL))
        return ConversationHistoryItem(**(data | overrides))

    def test_original_two_names_and_projects_are_alternatives(self):
        sources = [self.source(s['text']) for s in FIXTURE['sources']]
        for case_id in ('S03', 'S04'):
            query = next(c['query'] for c in FIXTURE['cases'] if c['id']==case_id)
            result = resolve_sources(query,sources,explicit=False)
            self.assertEqual(result.status,'ambiguous')
            self.assertEqual(len(result.event_ids),2)

    def test_new_names_are_not_fixture_specific(self):
        for name in ('陈岚','林溪','Morgan'):
            sources = [self.source('我的前同事叫'+name+'，一起做过测绘。'),
                       self.source('我的邻居也叫'+name+'，我们一起种过花。')]
            result = resolve_sources(name+'又来找我了，怎么回？',sources,explicit=False)
            self.assertEqual(result.status,'ambiguous')
            self.assertEqual(set(result.event_ids),{s.event_id for s in sources})

    def test_explicit_qualifier_does_not_use_negative_comparison_as_identity(self):
        first = self.source('我有个前同事叫陈岚，我们做过测绘。')
        second = self.source('我邻居也叫陈岚。这个陈岚不是前同事。')
        result = resolve_sources('前同事陈岚又来找我了，怎么回？',[first,second],explicit=False)
        self.assertEqual(result.status,'resolved')
        self.assertEqual(result.reason,'one_affirmative_descriptor_match_sources_retained')
        self.assertEqual(set(result.event_ids),{first.event_id,second.event_id})

    def test_contradictory_or_negative_query_never_selects_by_keyword(self):
        sources=[self.source('我的前同事叫陈岚。'),self.source('我的邻居也叫陈岚。')]
        for query in ('不是前同事的陈岚又来找我了。','前同事和邻居陈岚又来找我了。'):
            self.assertEqual(resolve_sources(query,sources,explicit=True).status,'ambiguous')

    def test_single_affirmative_owner_naming_source(self):
        source=self.source('青穹是我的无人机项目，下一步换螺旋桨。')
        result=resolve_sources('青穹下一步该做什么来着？',[source],explicit=False)
        self.assertEqual(result.status,'resolved');self.assertEqual(result.event_ids,(source.event_id,))

    def test_unknown_name_and_unsupported_declaration_abstain(self):
        known=self.source('我的同事叫陈岚。')
        self.assertEqual(resolve_sources('赵青又来找我了。',[known],explicit=False).status,'unknown')
        for text in ('假设我的同事叫赵青。','我的同事不叫赵青。','我的同事可能叫赵青。'):
            self.assertEqual(resolve_sources('赵青又来找我了。',[self.source(text)],explicit=False).event_ids,())

    def test_assistant_guess_never_establishes_owner_entity(self):
        guess=self.source('你的同事叫Morgan。',role='assistant')
        self.assertEqual(resolve_sources('Morgan contacted me again.',[guess],explicit=False).event_ids,())

    def test_latin_boundaries_and_cjk_prefix_collision(self):
        for name,query in [('Ann','Anna contacted me again.'),('arc','archive contacted me again.'),('北星','北星辰下一步该做什么来着？')]:
            source=self.source('我的项目叫'+name+'。')
            self.assertEqual(resolve_sources(query,[source],explicit=True).event_ids,())

    def test_english_owner_naming_and_two_alternatives(self):
        sources=[self.source('My coworker is named Morgan.'),self.source('My neighbor is also called Morgan.')]
        result=resolve_sources('Morgan contacted me again.',sources,explicit=False)
        self.assertEqual(result.status,'ambiguous');self.assertEqual(len(result.event_ids),2)

    def test_capacity_overflow_never_becomes_top_one(self):
        sources=[self.source(f'我的第{i}个项目也叫青穹。') for i in range(7)]
        result=resolve_sources('青穹下一步该做什么来着？',sources,explicit=False)
        self.assertEqual(result.status,'ambiguous');self.assertEqual(result.event_ids,())

    def test_ordinary_named_update_and_no_callback_remain_quiet(self):
        sources=[self.source('我的同事叫陈岚。')]
        for query in ('陈岚推荐的电影很好看。','陈岚又来找我了，不要提历史。','哈哈今天心情不错。'):
            result=resolve_sources(query,sources,explicit=False)
            self.assertEqual(result.status,'not_requested');self.assertEqual(result.event_ids,())

    def test_short_clarification_uses_only_recent_same_session_owner(self):
        previous=self.source('陈岚又来找我了。')
        current=self.source('邻居那个',recorded_at=self.now+timedelta(minutes=1))
        self.assertIn(previous.content_text,reference_query(current.content_text,(previous,),current))
        for change in ({'session_id':uuid4()},{'owner_id':uuid4()},{'recorded_at':self.now+timedelta(minutes=11)}):
            other=current.model_copy(update=change)
            self.assertEqual(reference_query(other.content_text,(previous,),other),other.content_text)
        self.assertEqual(reference_query('他怎么想', (previous,),current),'他怎么想')


@unittest.skipUnless(os.getenv('HAVRE_TEST_DATABASE_URL'),'dedicated PostgreSQL required')
class TargetedSourcePostgresTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls): recall_fixtures.PersonalContextRecallPostgresTests.setUpClass()

    @classmethod
    def tearDownClass(cls): recall_fixtures.PersonalContextRecallPostgresTests.tearDownClass()

    async def asyncSetUp(self):
        self.fixture=recall_fixtures.PersonalContextRecallPostgresTests('runTest')
        await self.fixture.asyncSetUp()
        self.repo=self.fixture.repository

    async def asyncTearDown(self): self.fixture.folder.cleanup()

    async def test_original_s03_s04_reach_real_context_and_provider_messages(self):
        sources={}
        for source in FIXTURE['sources'][1:5]:
            sources[source['id']]=await self.fixture.turn(source['text'])
        self.repo.memory_encoder=self.fixture.encoder
        for case_id,expected in [('S03',('name_work','name_club')),('S04',('project_robot','project_music'))]:
            query=next(c['query'] for c in FIXTURE['cases'] if c['id']==case_id)
            current=self.fixture.current(query,730)
            history=recalled_history(self.repo,owner_id=self.fixture.owner,query=query,current_event=current,
                recent=(),explicit=False,timezone_name='America/Chicago')
            self.assertTrue({sources[k].user_event_id for k in expected}<={h.event_id for h in history})
            other_ids={value.user_event_id for key,value in sources.items() if key not in expected}
            self.assertFalse(other_ids & {h.event_id for h in history})
            pack=self.fixture.service.context_builder.build(request_id=current.request_id,trace_id=current.trace_id,
                owner_id=self.fixture.owner,identity=self.fixture.identity,user_event=current,conversation_history=history)
            messages=render_inference_messages(pack)
            refs={ref for m in messages for ref in m.source_refs}
            self.assertTrue({f'event/{sources[k].user_event_id}' for k in expected}<=refs)
            self.assertTrue(any('targeted-source-resolution-v1/ambiguous' in ref for ref in refs))
            self.assertEqual(messages[-1].content_parts[0].text,query)
            # The production call site passes explicit=False for these targets.
            result=await self.fixture.turn(query)
            evidence=self.repo.evidence(result.request_id,owner_id=self.fixture.owner)
            self.assertTrue({f'event/{sources[k].user_event_id}' for k in expected}<={
                ref for section in evidence['context_pack']['sections'] for ref in section['source_refs']})

    async def test_named_source_outside_recent_256_and_unknown_remain_distinct(self):
        source=await self.fixture.turn('青穹是我的无人机项目，下一步换螺旋桨。')
        for i in range(130): await self.fixture.turn(f'Synthetic unrelated lunch {i}.')
        self.repo.memory_encoder=self.fixture.encoder
        query='青穹下一步该做什么来着？'
        history=recalled_history(self.repo,owner_id=self.fixture.owner,query=query,current_event=self.fixture.current(query,730),
            recent=(),explicit=False,timezone_name='America/Chicago')
        self.assertIn(source.user_event_id,{h.event_id for h in history})
        unknown='赤石下一步该做什么来着？'
        self.assertEqual(recalled_history(self.repo,owner_id=self.fixture.owner,query=unknown,
            current_event=self.fixture.current(unknown,730),recent=(),explicit=False,timezone_name='America/Chicago'),())

    async def test_foreign_owner_and_revoked_sources_cannot_resolve_names(self):
        source=await self.fixture.turn('我的同事叫陈岚。')
        self.repo.memory_encoder=self.fixture.encoder;query='陈岚又来找我了，怎么回？'
        current=self.fixture.current(query,730)
        self.assertEqual(recalled_history(self.repo,owner_id=uuid4(),query=query,current_event=current,
            recent=(),explicit=False,timezone_name='America/Chicago'),())
        self.repo.erase_source_event_derivatives(owner_id=self.fixture.owner,source_event_id=source.user_event_id)
        self.assertEqual(recalled_history(self.repo,owner_id=self.fixture.owner,query=query,current_event=current,
            recent=(),explicit=False,timezone_name='America/Chicago'),())

    async def test_exact_named_private_source_cannot_cross_to_normal_cloud(self):
        from companion.application import InteractionService,InteractionCommand
        from companion.context import ContextBuilder
        from companion.memory import DeterministicEmbeddingProvider
        from mlsys.retrieval.service import RetrievalService
        from mlsys.serving import Stage1Router,DeterministicLocalProvider
        local=InteractionService(owner_id=self.fixture.owner,identity=self.fixture.identity,repository=self.repo,
            context_builder=ContextBuilder(max_input_tokens=12000,reserved_output_tokens=256),
            router=Stage1Router(),provider=DeterministicLocalProvider(),
            retrieval_service=RetrievalService(repository=self.repo,embedding_provider=DeterministicEmbeddingProvider()))
        source=await local.interact(InteractionCommand(message='我的同事叫陈岚。',privacy_class=PrivacyClass.LOCAL_ONLY,idempotency_key=str(uuid4())))
        self.repo.memory_encoder=self.fixture.encoder;query='陈岚又来找我了，怎么回？'
        normal=self.fixture.current(query,730)
        self.assertEqual(recalled_history(self.repo,owner_id=self.fixture.owner,query=query,current_event=normal,
            recent=(),explicit=False,timezone_name='America/Chicago'),())
        current=normal.model_copy(update={'data_policy':DataPolicy.owner_default(PrivacyClass.LOCAL_ONLY)})
        found=recalled_history(self.repo,owner_id=self.fixture.owner,query=query,current_event=current,
            recent=(),explicit=False,timezone_name='America/Chicago')
        self.assertIn(source.user_event_id,{h.event_id for h in found})
        self.assertTrue(all(h.data_policy.privacy_class is PrivacyClass.LOCAL_ONLY for h in found))

    async def test_callback_opt_out_does_not_retrieve_even_when_explicit(self):
        await self.fixture.turn('我的同事叫陈岚。')
        self.repo.memory_encoder=self.fixture.encoder;query='陈岚又来找我了，但不要提历史。'
        self.assertEqual(recalled_history(self.repo,owner_id=self.fixture.owner,query=query,
            current_event=self.fixture.current(query,730),recent=(),explicit=True,timezone_name='America/Chicago'),())


if __name__=='__main__':unittest.main()
