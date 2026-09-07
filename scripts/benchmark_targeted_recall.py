"""Read-only source regression on the existing constructed A/B stress database."""
from __future__ import annotations
import argparse,asyncio,json,subprocess
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID,uuid4
import psycopg
from psycopg.rows import dict_row
from companion.context import ContextBuilder,load_owner_example_bank
from companion.context.corrections import owner_fact_corrections
from companion.context.presentation import render_inference_messages
from companion.context.response_plan import ResponsePlanner
from companion.context.recall import recalled_history
from companion.context.source_resolution import VERSION
from companion.events import EventEnvelope,UserMessagePayload,TextContentPart
from companion.identity import IdentityLoader
from companion.memory.semantic import LocalSemanticEmbeddingProvider
from companion.persistence import PostgresRepository
from companion.policy import DataPolicy,PrivacyClass
from mlsys.retrieval.models import RetrievalRequest,RetrievalQuery,RetrievalFilters
from mlsys.retrieval.service import RetrievalService
from evals.context_ab_blind import canonical_hash,digest,write,read

ROOT=Path(__file__).resolve().parents[1]
DB='postgresql://postgres@127.0.0.1:55432/havre_context_ab_stress_20260906'
OWNER=UUID('00000000-0000-7000-8000-000000000001')
BASELINE='a1d8dc1'
EXTRA=(
 ('U01','前同事周宁又来找我了，你觉得我该怎么回？','Resolve former colleague scope; do not assume message content or transfer photography-club details.'),
 ('U02','机器人小车项目北星下一步该做什么来着？','Use the robot project: first adjust motors. Do not mix in organizing songs.'),
 ('U03','音乐播放列表项目北星下一步该做什么来着？','Use the music project: first organize songs. Do not mix in motor tuning.'),
 ('U04','赵青又来找我了，你觉得我该怎么回？','No source identifies this person or their message. Ask for context without pretending to know them.'),
)


def prepare(output: Path):
    if output.exists():raise ValueError('preserve earlier benchmark')
    fixture=read(ROOT/'evals/fixtures/context_recall_stress_v1.json')
    original=read(ROOT/'var/context-ab-20260906/case-review-v2/validated-input-run/stress-inputs.NORMAL.json')
    if original['fixture_sha256']!=digest(ROOT/'evals/fixtures/context_recall_stress_v1.json'):
        raise ValueError('original stress targets changed')
    with psycopg.connect(DB,options='-c default_transaction_read_only=on',row_factory=dict_row) as c:
        target=c.execute("SELECT current_database() db,inet_server_port() port,current_setting('transaction_read_only') ro").fetchone()
        if target!={'db':'havre_context_ab_stress_20260906','port':55432,'ro':'on'}:raise ValueError('wrong isolated read-only target')
        source_rows=c.execute("SELECT event_id,content_hash,payload FROM havre.events WHERE owner_id=%s AND event_type='USER_MESSAGE' ORDER BY recorded_at,event_id",(OWNER,)).fetchall()
    source_ids={}
    for source in fixture['sources']:
        matches=[r for r in source_rows if any(p.get('text','').endswith(source['text']) for p in r['payload'].get('content_parts',()))]
        if len(matches)!=1:raise ValueError('synthetic source missing or duplicated')
        source_ids[source['id']]=str(matches[0]['event_id'])
        if source.get('correction'):
            matches=[r for r in source_rows if any(p.get('text','')==source['correction'] for p in r['payload'].get('content_parts',()))]
            if len(matches)!=1:raise ValueError('correction missing')
            source_ids[source['id']+'-correction']=str(matches[0]['event_id'])
    old_source=subprocess.check_output(['git','show',BASELINE+':companion/context/recall.py'],cwd=ROOT).decode('utf-8')
    namespace={};exec(compile(old_source,'<frozen-baseline-recall>','exec'),namespace)
    repo=PostgresRepository(DB+'?options=-c%20default_transaction_read_only%3Don');repo.open()
    encoder=LocalSemanticEmbeddingProvider(ROOT/'var/models/memory-minilm-v1');repo.memory_encoder=encoder
    identity=IdentityLoader(ROOT/'identity').load()
    bank=load_owner_example_bank(ROOT/'.runtime/desktop/config/owner-example-bank-oa70-all70-v2.json',owner_id=OWNER)
    builder=ContextBuilder(max_input_tokens=16384,reserved_output_tokens=3072,owner_timezone='America/Chicago',owner_example_bank=bank)
    planner=ResponsePlanner(semantic_memory=True);retrieval=RetrievalService(repository=repo,embedding_provider=encoder)
    cases=[dict(c) for c in fixture['cases']]+[{'id':i,'query':q,'requirements':r,'category':'qualified_counterfactual'} for i,q,r in EXTRA]
    output_rows=[]
    try:
        for case in cases:
            old_case=next((r for r in original['cases'] if r['case_id']==case['id']),original['cases'][2])
            current=EventEnvelope(event_type='USER_MESSAGE',owner_id=OWNER,request_id=uuid4(),session_id=uuid4(),trace_id=uuid4().hex,
                recorded_at=datetime.fromisoformat(old_case['as_of']),data_policy=DataPolicy.owner_default(PrivacyClass.NORMAL),
                payload=UserMessagePayload(content_parts=(TextContentPart(text=case['query']),),channel='api'))
            recent=repo.select_conversation_history(owner_id=OWNER,session_id=current.session_id,exclude_event_id=current.event_id,
                maximum_privacy_class=PrivacyClass.NORMAL,as_of=current.recorded_at,include_cross_session_fallback=True,continuous_chat=False)
            personal=repo.select_personal_context(owner_id=OWNER,query_text=case['query'],maximum_privacy_class=PrivacyClass.NORMAL,as_of=current.recorded_at)
            row={'case_id':case['id'],'query':case['query'],'requirements':case['requirements'],'as_of':current.recorded_at.isoformat()}
            for arm,recall in [('baseline',namespace['recalled_history']),('targeted',recalled_history)]:
                history=recall(repo,owner_id=OWNER,query=case['query'],current_event=current,recent=recent,
                    explicit=planner.refers_to_prior_context(case['query']),timezone_name='America/Chicago')
                plan=planner.plan(request_id=current.request_id,trace_id=current.trace_id,owner_id=OWNER,message=case['query'],
                    source_refs=(f'event/{current.event_id}',),conversation_history=history,personal_context=personal)
                req=RetrievalRequest(request_id=current.request_id,trace_id=current.trace_id,owner_id=OWNER,
                    query=RetrievalQuery(text=plan.memory_query or case['query'],event_id=current.event_id),as_of=current.recorded_at,
                    filters=RetrievalFilters(allowed_privacy_classes=(PrivacyClass.PUBLIC,PrivacyClass.NORMAL)),algorithm_version=retrieval.default_algorithm)
                result=retrieval.retrieve(req,persist=False) if plan.memory_need!='none' else retrieval.retrieve_empty(req,persist=False)
                corrections=owner_fact_corrections(repo,owner_id=OWNER,current_event=current,history=history,retrieval_result=result)
                pack=builder.build(request_id=current.request_id,trace_id=current.trace_id,owner_id=OWNER,identity=identity,user_event=current,
                    conversation_history=history,personal_context=(*personal,*corrections),retrieval_result=result,response_plan=plan)
                messages=[{'role':m.role,'content':'\n'.join(p.text for p in m.content_parts),'source_refs':list(m.source_refs)} for m in render_inference_messages(pack)]
                refs={ref for m in messages for ref in m['source_refs']}
                row[arm]={'messages':messages,'input_hash':canonical_hash(messages),'admitted_sources':[name for name,event in source_ids.items() if 'event/'+event in refs],
                          'pack_hash':pack.content_hash,'estimated_tokens':pack.estimated_total_tokens}
            output_rows.append(row)
            print(json.dumps({'case':case['id'],'baseline_sources':row['baseline']['admitted_sources'],'targeted_sources':row['targeted']['admitted_sources']}),flush=True)
    finally:repo.close()
    result={'version':VERSION,'baseline_ref':subprocess.check_output(['git','rev-parse',BASELINE],cwd=ROOT).decode().strip(),
        'policy':{'privacy_class':'NORMAL','cloud_eligible':True,'training_eligible':False,'reason':'Constructed narratives with existing authorized runtime Identity/style bank'},
        'source_database':target,'source_event_hashes':{str(r['event_id']):r['content_hash'] for r in source_rows},
        'fixture_sha256':digest(ROOT/'evals/fixtures/context_recall_stress_v1.json'),'original_targets_unchanged':True,
        'code_sha256':{str(p.relative_to(ROOT)):digest(p) for p in [Path(__file__),ROOT/'companion/context/recall.py',ROOT/'companion/context/source_resolution.py']},
        'cases':output_rows,'limit':'Source regression is not a semantic answer scorer. No durable write, training or production restart.'}
    output.parent.mkdir(parents=True,exist_ok=True);write(output,result)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args();prepare(args.output)
