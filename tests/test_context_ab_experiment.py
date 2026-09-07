"""Experimental integrity checks; no automatic conversational quality scorer."""
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

from evals.context_ab_blind import DIMENSIONS, canonical_hash, digest, make_blind_pair, validate_review, validate_spec, verify_frozen_pins
from evals.context_ab_replay import HistoricalRepository
from evals.context_ab_privacy import replace_entities
from evals.context_ab_results import lock_reviews, clustered_interval
from scripts.prepare_context_ab_cases import draft_tags, eligible


class ContextABIntegrityTests(unittest.TestCase):
    def test_missing_or_wrong_order_review_cannot_be_locked_for_unblinding(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'blind').mkdir();(root/'reviews').mkdir()
            answers={a:{'delivered':'hello'} for a in ('full','simple')}
            packet,_=make_blind_pair(self.fixture(),answers)
            (root/'blind/pair.NORMAL.json').write_text(json.dumps(packet))
            with self.assertRaisesRegex(ValueError,'all semantic reviews'):
                lock_reviews(root,['pair'])
            self.assertFalse((root/'review-lock.LOCAL_ONLY.json').exists())
            review=self.review();labels=[a['label'] for a in packet['outputs']]
            review['ratings']=dict(zip(labels,review['ratings'].values()));review['preference']=labels[0]
            for order in (0,1):
                path=root/f'reviews/pair-order-{order}.NORMAL.json'
                path.write_text(json.dumps({'packet_hash':canonical_hash(packet),'order':0,'semantic_review':review}))
            with self.assertRaisesRegex(ValueError,'exact packet/order'):
                lock_reviews(root,['pair'])
            self.assertFalse((root/'review-lock.LOCAL_ONLY.json').exists())
            path.write_text(json.dumps({'packet_hash':canonical_hash(packet),'order':1,'semantic_review':review}))
            lock_reviews(root,['pair'])
            review['reason']='A changed semantic judgment after the original review was locked.'
            path.write_text(json.dumps({'packet_hash':canonical_hash(packet),'order':1,'semantic_review':review}))
            with self.assertRaisesRegex(ValueError,'locked reviews changed'):
                lock_reviews(root,['pair'])

    def test_cluster_uncertainty_does_not_treat_adjacent_turns_as_independent(self):
        rows=[{'family':'one','full_share':1.} for _ in range(20)]
        rows.extend({'family':'two','full_share':0.} for _ in range(20))
        self.assertEqual(clustered_interval(rows,draws=1000),[0.,1.])

    def test_deidentification_preserves_clock_dates_and_english_word_interiors(self):
        mapping={'2026-09-05':'contact-alias','arc':'place-alias'}
        text='Authoritative time: 2026-09-05T14:18:41-05:00; search archive architecture. 我去arc，at arc.'
        result=replace_entities(text,mapping)
        self.assertIn('2026-09-05T14:18:41-05:00',result)
        self.assertIn('search archive architecture',result)
        self.assertIn('我去place-alias，at place-alias.',result)
        self.assertNotIn('contact-alias',result)

    def test_observation_time_does_not_masquerade_as_model_drift(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            frozen={'runner_sha256':'same','spec_sha256':'locked','judge_prompt_sha256':'locked',
                    'provider':{'model_version_id':'fixed-model','observed_at':'first-observation'}}
            (root/'frozen-run.LOCAL_ONLY.json').write_text(json.dumps(frozen))
            current={**frozen,'provider':{**frozen['provider'],'observed_at':'later-observation'}}
            verify_frozen_pins(root,current)
            current['provider']['model_version_id']='different-model'
            with self.assertRaisesRegex(ValueError,'configuration drift'):
                verify_frozen_pins(root,current)

    def test_metadata_repair_cannot_accept_unrecorded_code_or_target_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            frozen={'runner_sha256':'old','spec_sha256':'locked','judge_prompt_sha256':'locked',
                    'provider':{'model_version_id':'fixed-model','observed_at':'first'}}
            path=root/'frozen-run.LOCAL_ONLY.json';path.write_text(json.dumps(frozen))
            repair={'generation_manifest_sha256':digest(path),'from_runner_sha256':'old',
                    'to_runner_sha256':'exact-fix','unchanged_judge_prompt_sha256':'locked'}
            (root/'metadata-check-repair.LOCAL_ONLY.json').write_text(json.dumps(repair))
            current={**frozen,'runner_sha256':'exact-fix'}
            verify_frozen_pins(root,current)
            with self.assertRaisesRegex(ValueError,'unrecorded runner'):
                verify_frozen_pins(root,{**current,'runner_sha256':'another-edit'})
            with self.assertRaisesRegex(ValueError,'configuration drift'):
                verify_frozen_pins(root,{**current,'spec_sha256':'changed-target'})

    def fixture(self):
        return {'case_id':'synthetic','as_of':'2026-01-02T00:00:00+00:00','user_message':'Hello',
                'prior_evidence':[], 'full_messages':[{'role':'user','content':'Hello'}],
                'simple_messages':[{'role':'user','content':'Hello'}],
                'full_core_history':[],'simple_core_history':[],
                'requirements':'Respond naturally.','family':'greeting','stratum':'casual'}

    def spec(self, root, case):
        source={'policy':{'privacy_class':'NORMAL','cloud_eligible':True,'training_eligible':False},
                'source_packet_hash':'sealed','cases':[case]}
        path=root/'pseudonymized-evaluation-inputs.NORMAL.json'
        path.write_text(json.dumps(source),encoding='utf-8')
        return {'source_packet_hash':'sealed','source_payload_sha256':digest(path),'cases':[dict(case)],
                'schedule':[{'case_id':'synthetic','replicate':1,'order':['full','simple']}]}

    def test_changed_target_is_rejected_even_with_same_source_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);spec=self.spec(root,self.fixture())
            spec['cases'][0]['user_message']='A more favorable target'
            with self.assertRaisesRegex(ValueError,'changed target'):
                validate_spec(root,spec)

    def test_payload_replacement_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);spec=self.spec(root,self.fixture())
            (root/'pseudonymized-evaluation-inputs.NORMAL.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'payload changed'):
                validate_spec(root,spec)

    def test_private_derivative_cannot_be_relabeled_by_run_spec(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);spec=self.spec(root,self.fixture())
            path=root/'pseudonymized-evaluation-inputs.NORMAL.json'
            source=json.loads(path.read_text());source['policy']['privacy_class']='LOCAL_ONLY'
            path.write_text(json.dumps(source));spec['source_payload_sha256']=digest(path)
            with self.assertRaisesRegex(ValueError,'privacy rejected'):
                validate_spec(root,spec)

    def test_missing_primary_or_duplicate_slot_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);spec=self.spec(root,self.fixture())
            spec['schedule']*=2
            with self.assertRaisesRegex(ValueError,'duplicate generation'):
                validate_spec(root,spec)
            spec['schedule']=[]
            with self.assertRaisesRegex(ValueError,'incomplete primary'):
                validate_spec(root,spec)

    def test_blind_packet_drops_architecture_and_systems_metadata(self):
        case=self.fixture()
        answers={a:{'delivered':text,'seconds':900,'usage':{'prompt_tokens':987},'arm':a}
                 for a,text in [('full','The full moon looks lovely.'),('simple','Hello!')]}
        packet,key=make_blind_pair(case,answers,shuffle=lambda values:values.reverse())
        self.assertEqual(set(key.values()),{'full','simple'})
        self.assertEqual(packet['outputs'][0]['text'],'Hello!')
        self.assertEqual(packet['outputs'][1]['text'],'The full moon looks lovely.')
        self.assertEqual(set(packet),{'pair_id','current_message','pre_target_evidence','requirements','outputs','shared_authoritative_clock'})
        self.assertTrue(all(set(a)=={'label','text'} for a in packet['outputs']))
        # Real output wording is never redacted to hide an architecture leak.
        self.assertIn('full moon',packet['outputs'][1]['text'])

    def test_review_clock_is_target_time_even_when_history_claims_time_unknown(self):
        case=self.fixture();case['as_of']='2026-09-05T19:18:41+00:00'
        case['prior_evidence']=[{'role':'assistant','text':'I do not know the current time.'}]
        answers={a:{'delivered':'It is Saturday afternoon.'} for a in ('full','simple')}
        packet,_=make_blind_pair(case,answers)
        self.assertEqual(packet['shared_authoritative_clock']['target_received_at'],'2026-09-05T14:18:41-05:00')
        self.assertEqual(packet['shared_authoritative_clock']['weekday'],'Saturday')
        self.assertEqual(packet['current_message'],case['user_message'])
        self.assertEqual(packet['pre_target_evidence'],case['prior_evidence'])

    def test_labels_are_fresh_for_each_pair_and_position(self):
        answers={a:{'delivered':'same'} for a in ('full','simple')}
        first,_=make_blind_pair(self.fixture(),answers)
        second,_=make_blind_pair(self.fixture(),answers)
        self.assertTrue({a['label'] for a in first['outputs']}.isdisjoint(a['label'] for a in second['outputs']))
        self.assertNotEqual(canonical_hash(first),canonical_hash({**first,'outputs':list(reversed(first['outputs']))}))

    def review(self):
        return {'ratings':{label:{d:3 for d in DIMENSIONS} for label in ('x','y')},'preference':'y',
                'reason':'The second answer follows the current correction; the first repeats an unsupported premise.',
                'uncertainty':'medium','critical_failures':[]}

    def test_semantic_preference_is_not_replaced_by_score_arithmetic(self):
        review=self.review();review['ratings']['x']['naturalness']=5
        self.assertEqual(validate_review(review,['x','y'])['preference'],'y')

    def test_keyword_like_empty_review_is_rejected(self):
        review=self.review();review['reason']='keyword hit'
        with self.assertRaisesRegex(ValueError,'semantic reason'):
            validate_review(review,['x','y'])

    def test_wrong_labels_and_boolean_scores_are_rejected(self):
        review=self.review();review['preference']='full'
        with self.assertRaisesRegex(ValueError,'label mismatch'):
            validate_review(review,['x','y'])
        review=self.review();review['ratings']['x']['naturalness']=True
        with self.assertRaisesRegex(ValueError,'anchored rating'):
            validate_review(review,['x','y'])

    def test_source_policy_independently_excludes_one_time_disclosure(self):
        for privacy in ('PRIVATE','HIGHLY_PRIVATE','LOCAL_ONLY'):
            self.assertFalse(eligible({'privacy_class':privacy,'cloud_eligible':True}))
        self.assertFalse(eligible({'privacy_class':'NORMAL','cloud_eligible':False}))
        self.assertTrue(eligible({'privacy_class':'NORMAL','cloud_eligible':True}))

    def test_cross_day_hint_uses_owner_day_not_database_timezone(self):
        prior=[{'recorded_at':'2026-09-04T04:30:00+00:00'}]  # Sept 3, 23:30 Chicago
        current=datetime(2026,9,4,5,30,tzinfo=UTC)  # Sept 4, 00:30 Chicago
        self.assertIn('cross_day',draft_tags('hello',prior,current,()))
        same_day=datetime(2026,9,4,4,59,tzinfo=UTC)
        self.assertNotIn('cross_day',draft_tags('hello',prior,same_day,()))


@unittest.skipUnless(os.getenv('HAVRE_TEST_DATABASE_URL'),'dedicated PostgreSQL test database required')
class ContextABHistoricalSnapshotPostgresTests(unittest.IsolatedAsyncioTestCase):
    async def test_historical_correction_survives_a_later_head(self):
        from tests.test_personal_context_recall import PersonalContextRecallPostgresTests
        from companion.memory.service import MemoryWorker,MemoryService
        from companion.memory.extractor import DeterministicEpisodicExtractor
        from companion.context.corrections import owner_fact_revision_refs
        cls=PersonalContextRecallPostgresTests;cls.setUpClass()
        fixture=cls('runTest');await fixture.asyncSetUp()
        try:
            source=await fixture.turn('Synthetic telescope colleague was described as supervisor.')
            worker=MemoryWorker(repository=fixture.repository,extractor=DeterministicEpisodicExtractor(),owner_id=fixture.owner)
            candidate=worker.run_once()
            self.assertEqual(candidate['source_event_id'],source.user_event_id)
            service=MemoryService(repository=fixture.repository,embedding_provider=fixture.encoder)
            memory=service.accept_candidate(owner_id=fixture.owner,candidate_id=candidate['candidate_id'],reason='Synthetic test')
            memory_id=memory.memory_id if hasattr(memory,'memory_id') else memory['memory_id']
            service.correct(owner_id=fixture.owner,memory_id=memory_id,content_text='Synthetic former colleague, not supervisor.',reason='First correction')
            service.correct(owner_id=fixture.owner,memory_id=memory_id,content_text='Synthetic former project partner, not employee.',reason='Later correction')
            with psycopg.connect(os.environ['HAVRE_TEST_DATABASE_URL'],row_factory=dict_row,
                                 options='-c default_transaction_read_only=on') as c:
                times=c.execute('SELECT revision,created_at FROM havre.memory_revisions WHERE owner_id=%s AND memory_id=%s ORDER BY revision',
                                (fixture.owner,memory_id)).fetchall()
                repo=HistoricalRepository(c,fixture.encoder)
                for revision in (2,3):
                    instant=next(r['created_at'] for r in times if r['revision']==revision)
                    repo.pool.instant=instant
                    refs=owner_fact_revision_refs(repo,owner_id=fixture.owner,as_of=instant,
                        event_ids=[source.user_event_id],memory_ids=[])
                    self.assertEqual(refs,{f'memory/{memory_id}/revision/{revision}'})
        finally:
            fixture.doCleanups();cls.tearDownClass()

    async def test_completed_goal_is_reconstructed_as_active_before_completion(self):
        from tests.test_personal_context_recall import PersonalContextRecallPostgresTests
        from companion.goals.models import GoalTrack,GoalStatus
        cls=PersonalContextRecallPostgresTests;cls.setUpClass()
        fixture=cls('runTest')
        await fixture.asyncSetUp()
        try:
            source=await fixture.turn('Synthetic goal: finish the telescope report.')
            goal=fixture.repository.create_goal(owner_id=fixture.owner,track=GoalTrack.REALITY,
                title='Synthetic telescope report',why='Synthetic evaluation',source_event_id=source.user_event_id)
            old=fixture.repository.event_by_id(owner_id=fixture.owner,event_id=goal.last_event_id)
            done=fixture.repository.update_goal(owner_id=fixture.owner,goal_id=goal.goal_id,
                expected_revision=1,reason='Synthetic completed',status=GoalStatus.COMPLETED)
            latest=fixture.repository.event_by_id(owner_id=fixture.owner,event_id=done.last_event_id)
            with psycopg.connect(os.environ['HAVRE_TEST_DATABASE_URL'],row_factory=dict_row,
                                 options='-c default_transaction_read_only=on') as c:
                historical=HistoricalRepository(c,fixture.encoder)
                historical.pool.instant=old.recorded_at
                rows=historical.list_goals(owner_id=fixture.owner)
                self.assertEqual([(r['revision'],r['status']) for r in rows],[(1,'active')])
                self.assertEqual(rows[0]['last_event_id'],str(old.event_id))
                self.assertEqual(historical.list_goals(owner_id=uuid4()),[])
                historical.pool.instant=latest.recorded_at
                self.assertEqual(historical.list_goals(owner_id=fixture.owner),[])
                self.assertEqual(historical.list_goals(owner_id=fixture.owner,include_inactive=True)[0]['revision'],2)
                with self.assertRaises(psycopg.errors.ReadOnlySqlTransaction):
                    c.execute('CREATE TABLE havre.ab_forbidden_write (id integer)')
        finally:
            fixture.doCleanups();cls.tearDownClass()


if __name__=='__main__':
    unittest.main()
