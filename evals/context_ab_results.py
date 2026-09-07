"""Join locked semantic judgments to their local key; descriptive inference only."""
from __future__ import annotations

import argparse
from collections import Counter,defaultdict
import json
from pathlib import Path
import random
import statistics

from evals.context_ab_blind import canonical_hash,read,DIMENSIONS,digest,write,validate_review


def quantile(values,fraction):
    values=sorted(values)
    if not values:return None
    index=(len(values)-1)*fraction
    lo=int(index);hi=min(len(values)-1,lo+1)
    return values[lo]+(values[hi]-values[lo])*(index-lo)


def clustered_interval(rows,*,seed=2026090602,draws=10000):
    families=defaultdict(list)
    for row in rows:families[row['family']].append(row['full_share'])
    groups=list(families.values());rng=random.Random(seed)
    if not groups:return None
    samples=[]
    for _ in range(draws):
        sample=[score for _ in groups for score in rng.choice(groups)]
        samples.append(statistics.mean(sample))
    return [quantile(samples,.025),quantile(samples,.975)]


def lock_reviews(directory, names):
    """Validate and seal all semantic evidence before the first key is opened."""
    required=[]
    for name in names:
        required.append(directory/'blind'/f'{name}.NORMAL.json')
        required.extend(directory/'reviews'/f'{name}-order-{order}.NORMAL.json' for order in (0,1))
    if any(not p.is_file() for p in required):raise ValueError('all semantic reviews must finish before unblinding')
    for name in names:
        packet=read(directory/'blind'/f'{name}.NORMAL.json')
        for order in (0,1):
            review=read(directory/'reviews'/f'{name}-order-{order}.NORMAL.json')
            if review['packet_hash']!=canonical_hash(packet) or review['order']!=order:
                raise ValueError('review not bound to exact packet/order')
            validate_review(review['semantic_review'],[a['label'] for a in packet['outputs']])
    locked={str(p.relative_to(directory)):digest(p) for p in required}
    lock_path=directory/'review-lock.LOCAL_ONLY.json'
    if lock_path.exists():
        if read(lock_path)!=locked:raise ValueError('locked reviews changed')
    else:write(lock_path,locked)


def summarize(directory):
    spec=read(directory/'run-spec.NORMAL.json')
    lock_reviews(directory,[f'pair-{i:03d}' for i in range(1,len(spec['schedule'])+1)])
    rows=[];metrics=defaultdict(list);dimensions={a:defaultdict(list) for a in ('full','simple')}
    for index,job in enumerate(spec['schedule'],1):
        name=f'pair-{index:03d}'
        case=next(c for c in spec['cases'] if c['case_id']==job['case_id'])
        packet=read(directory/'blind'/f'{name}.NORMAL.json')
        key=read(directory/'keys'/f'{name}.LOCAL_ONLY.json')
        if key['case_id']!=job['case_id'] or key['replicate']!=job['replicate']:raise ValueError('key points to wrong case')
        if key['packet_hash']!=canonical_hash(packet):raise ValueError('blinding key not bound to packet')
        reviews=[]
        for order in (0,1):
            review=read(directory/'reviews'/f'{name}-order-{order}.NORMAL.json')
            if review['packet_hash']!=canonical_hash(packet) or review['order']!=order:
                raise ValueError('review not bound to exact packet/order')
            reviews.append(review['semantic_review'])
        votes=[key['key'].get(r['preference'],r['preference']) for r in reviews]
        consensus=votes[0] if votes[0]==votes[1] else 'unresolved'
        full_share={'full':1.,'simple':0.,'tie':.5,'unresolved':.5,'unjudgeable':.5}[consensus]
        failures=[{**failure,'arm':key['key'][failure['label']],'order':order}
                  for order,review in enumerate(reviews) for failure in review['critical_failures']]
        row={'case_id':case['case_id'],'stratum':case['stratum'],'family':case['family'],
             'replicate':job['replicate'],'consensus':consensus,'full_share':full_share,
             'position_agreement':votes[0]==votes[1],'votes':votes,'critical_flags':failures}
        rows.append(row)
        for arm in ('full','simple'):
            generated=read(directory/'generated'/f'{name}-{arm}.NORMAL.json')
            anonymous=next(a for a in packet['outputs'] if key['key'][a['label']]==arm)
            if anonymous['text']!=generated['delivered']:raise ValueError('key does not match generated text')
            if generated['input_hash']!=canonical_hash(case[arm+'_messages']):raise ValueError('answer input changed')
            metrics[arm].append({'replicate':job['replicate'],'seconds':generated['seconds'],
                'input_tokens':generated['usage']['prompt_tokens'],'output_tokens':generated['usage']['output_tokens'],
                'total_tokens':generated['usage']['total_tokens'],
                'cache_hit_tokens':generated['usage'].get('prompt_cache_hit_tokens'),
                'core_action':generated['core_action']})
            if job['replicate']==1:
                label=next(k for k,v in key['key'].items() if v==arm)
                for dim in DIMENSIONS:
                    values=[r['ratings'][label][dim] for r in reviews if r['ratings'][label][dim] is not None]
                    if values:dimensions[arm][dim].append(statistics.mean(values))
    primary=[r for r in rows if r['replicate']==1]
    counts=Counter(r['consensus'] for r in primary)
    full=statistics.mean(r['full_share'] for r in primary)
    interval=clustered_interval(primary)
    agreement=statistics.mean(r['position_agreement'] for r in primary)
    unresolved=sum(r['consensus'] in {'unresolved','unjudgeable'} for r in primary)
    stratum={s:{'n':len(group),'consensus':dict(Counter(r['consensus'] for r in group)),
                'full_win_share_ties_half_unresolved_midpoint':statistics.mean(r['full_share'] for r in group)}
             for s in sorted({r['stratum'] for r in primary})
             if (group:=[r for r in primary if r['stratum']==s])}
    system={}
    for arm,values in metrics.items():
        primary_values=[r for r in values if r['replicate']==1]
        system[arm]={'generation_calls':len(values),'total_generation_tokens':sum(r['total_tokens'] for r in values),
            'primary_median_seconds':statistics.median(r['seconds'] for r in primary_values),
            'primary_p90_seconds':quantile([r['seconds'] for r in primary_values],.9),
            'primary_mean_input_tokens':statistics.mean(r['input_tokens'] for r in primary_values),
            'primary_mean_output_tokens':statistics.mean(r['output_tokens'] for r in primary_values),
            'primary_cache_hit_tokens':sum(r['cache_hit_tokens'] or 0 for r in primary_values),
            'core_actions':dict(Counter(r['core_action'] for r in values)),
            'usd_cost':None,'usd_reason':'Codex route returns no per-call billing; subscription use is not free or API-price-equivalent'}
    repeated=[]
    for row in rows:
        if row['replicate']==2:
            base=next(r for r in primary if r['case_id']==row['case_id'])
            repeated.append({'case_id':row['case_id'],'first':base['consensus'],'second':row['consensus'],
                             'same':base['consensus']==row['consensus']})
    flags=[f for r in primary for f in r['critical_flags']]
    # No automatic runtime decision. These flags remain unresolved until reviewed.
    candidate=('full' if full>=.65 and interval[0]>.5 else
               'simple' if 1-full>=.65 and interval[1]<.5 else None)
    if agreement<.8 or flags:candidate=None
    result={'schema_version':1,'primary_real_cases':len(primary),'dialogue_families':len({r['family'] for r in primary}),
        'stability_pairs':len(repeated),'consensus_counts':dict(counts),'position_agreement':agreement,
        'full_win_share_ties_half_unresolved_midpoint':full,'simple_win_share_ties_half_unresolved_midpoint':1-full,
        'full_dialogue_family_clustered_95_interval':interval,
        'full_unresolved_sensitivity':[full-unresolved/(2*len(primary)),full+unresolved/(2*len(primary))],
        'threshold_candidate_before_owner_calibration':candidate,'critical_flag_instances':len(flags),
        'dimension_means':{arm:{dim:{'mean':statistics.mean(v),'n':len(v)} for dim,v in values.items()}
                           for arm,values in dimensions.items()},
        'systems':system,'strata':stratum,'stability':repeated,'case_results':rows,
        'primary_paired_full_minus_simple_seconds':{
            'median':statistics.median(p['seconds']-q['seconds'] for p,q in zip(metrics['full'],metrics['simple']) if p['replicate']==1),
            'mean':statistics.mean(p['seconds']-q['seconds'] for p,q in zip(metrics['full'],metrics['simple']) if p['replicate']==1)},
        'limitations':['Model semantic judges are fallible and not calibrated with owner pairwise labels.',
            'Only twelve dialogue families; nominal case strata are not a representative population sample.',
            'Raw and Core outputs are preserved; a passed keyword/schema check is not a semantic quality score.',
            'No independent layer attribution, years of observed relationship use, or causal end-to-end latency claim.']}
    output=directory/'unblinded-results.LOCAL_ONLY.json'
    if output.exists():raise ValueError('preserve earlier analysis; do not overwrite')
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in {'case_results','stability','dimension_means','systems','strata','limitations'}},ensure_ascii=False))
    return result


def summarize_stress(directory):
    """Constructed cases stay separate from real-life primary inference."""
    data=read(directory/'stress-inputs.NORMAL.json')
    out=directory/'stress-run'
    frozen=read(out/'frozen-stress.LOCAL_ONLY.json')
    if digest(directory/'stress-inputs.NORMAL.json')!=frozen['input_sha256']:
        raise ValueError('stress input changed after generation')
    lock_reviews(out,[c['case_id'] for c in data['cases']])
    rows=[];usage=Counter()
    for case in data['cases']:
        name=case['case_id'];packet=read(out/'blind'/f'{name}.NORMAL.json')
        key=read(out/'keys'/f'{name}.LOCAL_ONLY.json')
        if key['case_id']!=name or key['packet_hash']!=canonical_hash(packet):
            raise ValueError('stress key not bound to case and packet')
        reviews=[read(out/'reviews'/f'{name}-order-{order}.NORMAL.json')['semantic_review'] for order in (0,1)]
        votes=[key['key'].get(r['preference'],r['preference']) for r in reviews]
        for arm in ('full','simple'):
            generated=read(out/'generated'/f'{name}-{arm}.NORMAL.json')
            anonymous=next(a for a in packet['outputs'] if key['key'][a['label']]==arm)
            if generated['input_hash']!=canonical_hash(case[arm+'_messages']) or anonymous['text']!=generated['delivered']:
                raise ValueError('stress key does not match exact generated input/output')
            usage[arm]+=generated['usage']['total_tokens']
        rows.append({'case_id':name,'votes':votes,'consensus':votes[0] if votes[0]==votes[1] else 'unresolved',
                     'position_agreement':votes[0]==votes[1],
                     'critical_flags':[{**f,'arm':key['key'][f['label']],'order':order}
                                       for order,r in enumerate(reviews) for f in r['critical_failures']]})
    result={'schema_version':1,'data_kind':'constructed_stress_not_real_owner_history',
            'cases':len(rows),'consensus_counts':dict(Counter(r['consensus'] for r in rows)),
            'position_agreement':statistics.mean(r['position_agreement'] for r in rows),
            'total_generation_tokens':dict(usage),'case_results':rows,
            'limit':'Curated synthetic Memory and simulated elapsed time do not prove automatic extraction or years of owner use.'}
    write(out/'unblinded-results.LOCAL_ONLY.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='case_results'}))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--stress',action='store_true')
    args=parser.parse_args()
    (summarize_stress if args.stress else summarize)(args.directory)
