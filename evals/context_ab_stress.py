"""Construct controlled recall stress inputs using actual local/PG selectors.

Requires an explicitly named disposable stress database. All source narratives
are checked-in synthetic text. Existing owner style calibration stays NORMAL and
local artifacts are never public or ingested into the product database.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import UTC,datetime,timedelta
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import psycopg

from companion.context import ContextBuilder,load_owner_example_bank
from companion.context.corrections import owner_fact_corrections
from companion.context.event_search import query_terms
from companion.context.presentation import render_inference_messages
from companion.context.recall import recalled_history
from companion.context.response_plan import ResponsePlanner
from companion.memory.service import MemoryWorker,MemoryService
from companion.memory.extractor import DeterministicEpisodicExtractor
from companion.policy import PrivacyClass
from mlsys.retrieval.models import RetrievalRequest,RetrievalQuery,RetrievalFilters
from mlsys.retrieval.service import RetrievalService

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/'evals/fixtures/context_recall_stress_v1.json'
SHARED={'owner_response_instruction','owner_wording_correction','owner_fact_correction','communication_preference'}


async def prepare(output):
    url=os.environ['HAVRE_TEST_DATABASE_URL']
    parsed=urlparse(url)
    if parsed.hostname!='127.0.0.1' or parsed.port!=55432 or parsed.path!='/havre_context_ab_stress_20260906':
        raise ValueError('exact dedicated stress database required')
    with psycopg.connect(url) as c:
        if c.execute('SELECT current_database(),inet_server_port()').fetchone()!=('havre_context_ab_stress_20260906',55432):
            raise ValueError('wrong test target')
        if c.execute("SELECT to_regclass('havre.events')").fetchone()[0] is not None:
            if c.execute('SELECT count(*) FROM havre.events').fetchone()[0]:
                raise ValueError('stress preparation requires an empty dedicated database')
    if output.exists():raise ValueError('do not overwrite stress inputs')
    from tests.test_personal_context_recall import PersonalContextRecallPostgresTests
    cls=PersonalContextRecallPostgresTests;cls.setUpClass()
    fixture=cls('runTest');await fixture.asyncSetUp()
    data=json.loads(FIXTURE.read_text('utf-8'))
    bank=load_owner_example_bank(ROOT/'.runtime/desktop/config/owner-example-bank-oa70-all70-v2.json',
                               owner_id=__import__('uuid').UUID('00000000-0000-7000-8000-000000000001'))
    # Same logical HAVRE owner for the authorized style bank, in a fresh isolated
    # database containing only this script's fictional source text.
    fixture.owner=bank.owner_id;fixture.service.owner_id=bank.owner_id
    fixture.repository.bootstrap_owner_and_identity(owner_id=fixture.owner,identity=fixture.identity)
    worker=MemoryWorker(repository=fixture.repository,extractor=DeterministicEpisodicExtractor(),owner_id=fixture.owner)
    memories=MemoryService(repository=fixture.repository,embedding_provider=fixture.encoder)
    fixture.repository.register_embedding_version(fixture.service.retrieval_service.embedding_provider.version)
    memory_ids={};sources=[]
    try:
        for source in data['sources']:
            text=('Synthetic lunch note: potatoes and broccoli. '*source.get('prefix_repeat',0))+source['text']
            turn=await fixture.turn(text)
            candidate=worker.run_once()
            if candidate['source_event_id']!=turn.user_event_id:
                raise ValueError('synthetic candidate must reference its exact source turn')
            memory=memories.accept_candidate(owner_id=fixture.owner,candidate_id=candidate['candidate_id'],
                reason='Constructed evaluation fixture; no real owner fact',content_text=source['text'])
            memory_ids[source['id']]=memory.memory_id if hasattr(memory,'memory_id') else memory['memory_id']
            sources.append({'id':source['id'],'event_id':str(turn.user_event_id),'text':text})
        for i in range(140):
            await fixture.turn(f'Synthetic unrelated lunch distractor {i}: potatoes and broccoli.')
        for source in data['sources']:
            if source.get('correction'):
                turn=await fixture.turn(source['correction'])
                memories.correct(owner_id=fixture.owner,memory_id=memory_ids[source['id']],
                    content_text=source['correction'],reason='Explicit synthetic owner correction')
                sources.append({'id':source['id']+'-correction','event_id':str(turn.user_event_id),'text':source['correction']})
        for i in range(data['distractor_turns_between_sources_and_query']):
            await fixture.turn(f'Synthetic unrelated lunch follow-up {i}: carrots and rice.')
        fixture.repository.memory_encoder=fixture.encoder
        retrieval=RetrievalService(repository=fixture.repository,embedding_provider=fixture.encoder)
        planner=ResponsePlanner(semantic_memory=True)
        builders={'full':ContextBuilder(max_input_tokens=16384,reserved_output_tokens=3072,
            owner_timezone='America/Chicago',owner_example_bank=bank),
            'simple':ContextBuilder(max_input_tokens=16384,reserved_output_tokens=3072,owner_timezone='America/Chicago')}
        rows=[]
        for case in data['cases']:
            current=fixture.current(case['query'],days=data['source_age_days'])
            recent=fixture.repository.select_conversation_history(owner_id=fixture.owner,session_id=current.session_id,
                exclude_event_id=current.event_id,maximum_privacy_class=PrivacyClass.NORMAL,as_of=current.recorded_at,
                include_cross_session_fallback=True,continuous_chat=False)
            personal=fixture.repository.select_personal_context(owner_id=fixture.owner,query_text=case['query'],
                maximum_privacy_class=PrivacyClass.NORMAL,as_of=current.recorded_at)
            histories={arm:recalled_history(fixture.repository,owner_id=fixture.owner,query=case['query'],
                current_event=current,recent=recent,timezone_name='America/Chicago',
                explicit=planner.refers_to_prior_context(case['query']) if arm=='full'
                         else bool(query_terms(case['query'])) or planner.refers_to_prior_context(case['query']))
                for arm in builders}
            plan=planner.plan(request_id=current.request_id,trace_id=current.trace_id,owner_id=fixture.owner,
                message=case['query'],source_refs=(f'event/{current.event_id}',),conversation_history=histories['full'],personal_context=personal)
            req=RetrievalRequest(request_id=current.request_id,trace_id=current.trace_id,owner_id=fixture.owner,
                query=RetrievalQuery(text=plan.memory_query or case['query'],event_id=current.event_id),
                as_of=current.recorded_at,filters=RetrievalFilters(allowed_privacy_classes=(PrivacyClass.PUBLIC,PrivacyClass.NORMAL)),
                algorithm_version=retrieval.default_algorithm)
            result=retrieval.retrieve(req,persist=False) if plan.memory_need!='none' else retrieval.retrieve_empty(req,persist=False)
            row={'case_id':case['id'],'stratum':case['category'],'family':case['id'],'requirements':case['requirements'],
                'data_kind':'constructed_stress','user_message':case['query'],'as_of':current.recorded_at.isoformat(),
                'prior_evidence':[{'role':'user','at':'730 or more simulated days before the target','text':s['text']}
                                  for s in sources]}
            for arm,builder in builders.items():
                correction=owner_fact_corrections(fixture.repository,owner_id=fixture.owner,current_event=current,
                    history=histories[arm],retrieval_result=result if arm=='full' else retrieval.retrieve_empty(req,persist=False))
                pack=builder.build(request_id=current.request_id,trace_id=current.trace_id,owner_id=fixture.owner,
                    identity=fixture.identity,user_event=current,conversation_history=histories[arm],
                    personal_context=(*personal,*correction) if arm=='full' else tuple(p for p in (*personal,*correction) if p.section_type in SHARED),
                    retrieval_result=result if arm=='full' else None,response_plan=plan if arm=='full' else None)
                row[arm+'_messages']=[{'role':m.role,'content':'\n'.join(p.text for p in m.content_parts),
                                      'source_refs':[f'evidence/{i}' for i,_ in enumerate(m.source_refs)]}
                                     for m in render_inference_messages(pack)]
                row[arm+'_core_history']=[p.text for s in pack.sections if s.section_type in {
                    'episodic_memory','semantic_memory','pattern_memory','progress_memory',
                    'conversation_user_message','conversation_assistant_message'} for p in s.content_parts]
                row[arm+'_admitted_source_ids']=[s['id'] for s in sources
                    if any('event/'+s['event_id'] in section.source_refs for section in pack.sections)]
                row[arm+'_section_types']=[s.section_type for s in pack.sections]
                row[arm+'_pack_hash']=pack.content_hash
            rows.append(row)
        document={'schema_version':1,'fixture_sha256':hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
            'policy':{'privacy_class':'NORMAL','cloud_eligible':True,'training_eligible':False,
                      'reason':'PUBLIC synthetic narratives plus existing owner-authorized NORMAL style calibration'},
            'source_database':'havre_context_ab_stress_20260906','not_real_owner_history':True,
            'old_source_age_days':730,'noise_turns':280,'cases':rows,
            'limitations':['Time is simulated; no two-year deployment or capacity claim.',
                'Memory facts are curated fixture admissions, not proof of automatic long-term extraction quality.',
                'Synthetic cases are separate from real case preferences and cannot decide a production architecture.']}
        output.write_text(json.dumps(document,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'stress_cases':len(rows),'noise_turns':280,'real_data':False,'output_sha256':hashlib.sha256(output.read_bytes()).hexdigest()}))
    finally:
        fixture.doCleanups();cls.tearDownClass()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    asyncio.run(prepare(parser.parse_args().output))
