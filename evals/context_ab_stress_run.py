"""Run the separately identified constructed stress comparison with pinned GPT."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import random
from time import perf_counter

from companion.policy import CoreResponsePolicy
from evals.context_ab_blind import (JUDGE_PROMPT,canonical_hash,digest,read,write,request,
                                   make_blind_pair,validate_review,recheck_sources,stable_provider_version)
from mlsys.serving.codex_cli import CodexCliProvider,CODEX_OWNER_AUTOMATIC_AUTHORIZATION_REF


async def run(directory,executable,phase):
    recheck_sources(directory)
    primary=read(directory/'frozen-run.LOCAL_ONLY.json')
    data=read(directory/'stress-inputs.NORMAL.json')
    if data['not_real_owner_history'] is not True or data['source_database']!='havre_context_ab_stress_20260906':
        raise ValueError('synthetic stress provenance required')
    out=directory/'stress-run';out.mkdir(exist_ok=True)
    provider=CodexCliProvider(executable=executable,enabled=True,
        explicit_authorization_ref=CODEX_OWNER_AUTOMATIC_AUTHORIZATION_REF,reasoning_effort='medium')
    try:
        version=(await provider.version()).model_dump(mode='json')
        if stable_provider_version(version)!=stable_provider_version(primary['provider']) or digest(executable)!=primary['executable_sha256']:
            raise ValueError('stress model/configuration differs from real comparison')
        pins={'input_sha256':digest(directory/'stress-inputs.NORMAL.json'),
              'fixture_sha256':data['fixture_sha256'],'provider':stable_provider_version(version),'executable_sha256':digest(executable),
              'driver_sha256':digest(Path(__file__)),'shared_runner_sha256':digest(Path(__file__).with_name('context_ab_blind.py')),
              'judge_prompt_sha256':canonical_hash(JUDGE_PROMPT),
              'authorization':'Owner requested constructed long-term recall stress; no real owner source narratives',
              'sampler_control':'provider-managed-not-transmitted','output_request_tokens':3072,'usd_cost':None}
        frozen=out/'frozen-stress.LOCAL_ONLY.json'
        if frozen.exists():
            if read(frozen)!=pins:raise ValueError('stress configuration drift')
        else:write(frozen,pins)
        for folder in ('generated','blind','keys','reviews'):(out/folder).mkdir(exist_ok=True)
        cases=list(data['cases']);random.Random(2026090603).shuffle(cases)
        approval_hash=read(directory/'owner-approval.LOCAL_ONLY.json')['packet_manifest_sha256']
        for index,case in enumerate(cases):
            name=case['case_id']
            if phase=='generate':
                answers={}
                for arm in (('full','simple') if index%2 else ('simple','full')):
                    result_path=out/'generated'/f'{name}-{arm}.NORMAL.json'
                    if result_path.exists():answers[arm]=read(result_path);continue
                    req=request(case[arm+'_messages'],authorization_hash=approval_hash)
                    started=perf_counter();response=await provider.generate(req);seconds=perf_counter()-started
                    if response.versions.model_version_id!=version['model_version_id'] or response.versions.serving_config_version!=version['serving_config_version']:
                        raise ValueError('response model/configuration drift')
                    raw='\n'.join(p.text for p in response.output_parts)
                    core=CoreResponsePolicy().apply(request_id=req.request_id,trace_id=req.trace_id,
                        context_pack_id=req.context_pack_id,inference_response_id=response.inference_response_id,
                        current_user_input=case['user_message'],raw_output_parts=(raw,),
                        history_evidence=tuple(case[arm+'_core_history']),available_effects=())
                    result={'input_hash':canonical_hash(case[arm+'_messages']),'raw':raw,
                        'delivered':'\n'.join(core.output_parts),'core_action':core.decision.action,
                        'seconds':seconds,'usage':response.usage.model_dump(mode='json'),
                        'versions':response.versions.model_dump(mode='json'),'usd_cost':None,
                        'data_kind':'constructed_stress_not_real_owner_history'}
                    write(result_path,result);answers[arm]=result
                if not (out/'blind'/f'{name}.NORMAL.json').exists():
                    packet,key=make_blind_pair(case,answers)
                    write(out/'keys'/f'{name}.LOCAL_ONLY.json',{'case_id':name,'key':key,'packet_hash':canonical_hash(packet)})
                    write(out/'blind'/f'{name}.NORMAL.json',packet)
                print(json.dumps({'stress_generation_pairs':index+1,'total':len(cases)}),flush=True)
            else:
                packet=read(out/'blind'/f'{name}.NORMAL.json')
                for order in (0,1):
                    path=out/'reviews'/f'{name}-order-{order}.NORMAL.json'
                    if path.exists():continue
                    view={**packet,'outputs':packet['outputs'] if order==0 else list(reversed(packet['outputs']))}
                    req=request([{'role':'system','content':JUDGE_PROMPT},
                        {'role':'user','content':json.dumps(view,ensure_ascii=False)}],authorization_hash=approval_hash)
                    response=await provider.generate(req)
                    raw='\n'.join(p.text for p in response.output_parts).strip()
                    write(out/'reviews'/f'{name}-order-{order}-raw.NORMAL.json',{'raw':raw,
                        'usage':response.usage.model_dump(mode='json'),'versions':response.versions.model_dump(mode='json'),
                        'input_hash':canonical_hash(view)})
                    parsed_text=raw.split('\n',1)[1].rsplit('```',1)[0].strip() if raw.startswith('```') and raw.endswith('```') else raw
                    review=validate_review(json.loads(parsed_text),[a['label'] for a in packet['outputs']])
                    write(path,{'packet_hash':canonical_hash(packet),'order':order,'semantic_review':review})
                    print(json.dumps({'stress_semantic_pair':index+1,'total':len(cases),'order':order}),flush=True)
    finally:
        await provider.aclose()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--executable',type=Path,required=True)
    parser.add_argument('--phase',choices=['generate','judge'],required=True)
    args=parser.parse_args();asyncio.run(run(args.directory,args.executable,args.phase))
