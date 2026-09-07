"""Parallel semantic review of frozen anonymous packets, never generation.

Scheduling only: the original judge prompt, payloads and configuration stay
fixed. Run after the sequential reviewer has stopped; preserve every prior
complete review and raw response. No architecture key is read by this module.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import UTC,datetime
import json
from pathlib import Path

from evals.context_ab_blind import (JUDGE_PROMPT,canonical_hash,digest,read,write,request,
                                  validate_review,recheck_sources,stable_provider_version)
from mlsys.serving.codex_cli import CodexCliProvider,CODEX_OWNER_AUTOMATIC_AUTHORIZATION_REF


async def run(directory,executable,concurrency):
    primary=read(directory/'frozen-run.LOCAL_ONLY.json')
    if canonical_hash(JUDGE_PROMPT)!=primary['judge_prompt_sha256']:
        raise ValueError('judge prompt changed from pre-generation protocol')
    if digest(executable)!=primary['executable_sha256']:
        raise ValueError('CLI changed')
    recheck_sources(directory)
    approval=read(directory/'owner-approval.LOCAL_ONLY.json')['packet_manifest_sha256']
    folders=[directory,directory/'stress-run']
    jobs=[]
    for folder in folders:
        packets=sorted((folder/'blind').glob('*.NORMAL.json'))
        expected=40 if folder==directory else 12
        if len(packets)!=expected:raise ValueError('all frozen anonymous packets must exist')
        for path in packets:
            packet=read(path)
            for order in (0,1):
                destination=folder/'reviews'/f'{path.name.removesuffix(".NORMAL.json")}-order-{order}.NORMAL.json'
                if destination.exists():
                    existing=read(destination)
                    if existing['packet_hash']!=canonical_hash(packet):raise ValueError('existing review changed packet')
                    validate_review(existing['semantic_review'],[o['label'] for o in packet['outputs']])
                    continue
                jobs.append((folder,path,packet,order,destination))
    pins={'driver_sha256':digest(Path(__file__)),'shared_runner_sha256':digest(Path(__file__).with_name('context_ab_blind.py')),
        'judge_prompt_sha256':canonical_hash(JUDGE_PROMPT),'provider':stable_provider_version(primary['provider']),
        'concurrency':concurrency,'scope':'Only missing semantic reviews; generation and existing reviews unchanged',
        'packets':{str(path.relative_to(directory)):digest(path) for folder in folders for path in (folder/'blind').glob('*.json')}}
    frozen=directory/'batch-review-execution.LOCAL_ONLY.json'
    if frozen.exists():
        if read(frozen)!=pins:raise ValueError('batch review execution drift')
    else:write(frozen,pins)
    semaphore=asyncio.Semaphore(concurrency)
    completed=0
    async def score(job):
        nonlocal completed
        folder,path,packet,order,destination=job
        async with semaphore:
            recheck_sources(directory)
            view={**packet,'outputs':packet['outputs'] if order==0 else list(reversed(packet['outputs']))}
            raw_path=destination.with_name(destination.name.replace('.NORMAL.json','-raw.NORMAL.json'))
            if raw_path.exists():
                saved=read(raw_path)
                if saved['input_hash']!=canonical_hash(view):raise ValueError('raw review input differs')
                raw=saved['raw']
            else:
                provider=CodexCliProvider(executable=executable,enabled=True,
                    explicit_authorization_ref=CODEX_OWNER_AUTOMATIC_AUTHORIZATION_REF,reasoning_effort='medium')
                try:
                    version=(await provider.version()).model_dump(mode='json')
                    if stable_provider_version(version)!=stable_provider_version(primary['provider']):
                        raise ValueError('review model/configuration drift')
                    req=request([{'role':'system','content':JUDGE_PROMPT},
                        {'role':'user','content':json.dumps(view,ensure_ascii=False)}],authorization_hash=approval)
                    response=await provider.generate(req)
                    if response.versions.model_version_id!=primary['provider']['model_version_id'] or response.versions.serving_config_version!=primary['provider']['serving_config_version']:
                        raise ValueError('review response version drift')
                    raw='\n'.join(p.text for p in response.output_parts).strip()
                    write(raw_path,{'raw':raw,'usage':response.usage.model_dump(mode='json'),
                        'versions':response.versions.model_dump(mode='json'),'input_hash':canonical_hash(view)})
                finally:
                    await provider.aclose()
            text=raw.split('\n',1)[1].rsplit('```',1)[0].strip() if raw.startswith('```') and raw.endswith('```') else raw
            review=validate_review(json.loads(text),[o['label'] for o in packet['outputs']])
            write(destination,{'packet_hash':canonical_hash(packet),'order':order,'semantic_review':review})
            completed+=1
            print(json.dumps({'semantic_reviews_completed_in_batch':completed,'remaining_batch_total':len(jobs)}),flush=True)
    results=await asyncio.gather(*(score(job) for job in jobs),return_exceptions=True)
    failures=[{'job':str(jobs[i][4].relative_to(directory)),'error_type':type(result).__name__}
              for i,result in enumerate(results) if isinstance(result,BaseException)]
    if failures:
        write(directory/f'batch-review-failures-{datetime.now(UTC).strftime("%H%M%S")}.LOCAL_ONLY.json',failures)
        raise RuntimeError(f'{len(failures)} semantic review jobs failed; preserve all evidence before resuming')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--executable',type=Path,required=True)
    parser.add_argument('--concurrency',type=int,choices=[1,2,3,4],default=4)
    args=parser.parse_args();asyncio.run(run(args.directory,args.executable,args.concurrency))
