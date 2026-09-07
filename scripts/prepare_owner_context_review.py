"""Local owner-only preference packets from immutable completed blind outputs."""
from __future__ import annotations
import argparse
from datetime import UTC, datetime
from html import escape
import json
from pathlib import Path
import random
from uuid import uuid4

from evals.context_ab_blind import canonical_hash, digest, read, write

QUESTIONS = {'like_havre': '哪个更像 HAVRE？', 'continue_chat': '哪个让你更想继续聊？'}
CHOICES = ('A', 'B', 'tie', 'cannot_judge')
POLICY = {'privacy_class': 'LOCAL_ONLY', 'cloud_eligible': False, 'training_eligible': False,
          'purpose': 'explicit owner product preference regression; no automatic training or product import'}


def prepare(run: Path, selected: list[int], output: Path):
    if output.exists(): raise ValueError('preserve existing owner packet')
    if len(selected) != len(set(selected)) or not 1 <= len(selected) <= 12:
        raise ValueError('select distinct bounded primary pairs')
    lock=read(run/'review-lock.LOCAL_ONLY.json')
    spec=read(run/'run-spec.NORMAL.json')
    packet={'schema_version':1,'review_id':uuid4().hex,'policy':POLICY,'questions':QUESTIONS,'cases':[]}
    keys=[]
    for number in selected:
        if number < 1 or number > len(spec['schedule']): raise ValueError('unknown pair')
        job=spec['schedule'][number-1]
        if job['replicate'] != 1: raise ValueError('generation repeats are not owner primary samples')
        name=f'pair-{number:03d}'
        relative=f'blind/{name}.NORMAL.json'
        if digest(run/relative) != lock.get(relative, lock.get(str(Path(relative)))): raise ValueError('blind packet changed after review lock')
        source=read(run/relative)
        old_key=read(run/'keys'/f'{name}.LOCAL_ONLY.json')
        if old_key['packet_hash'] != canonical_hash(source): raise ValueError('source key changed')
        if len(source['outputs']) != 2 or source['outputs'][0]['text']==source['outputs'][1]['text']:
            raise ValueError('owner review requires two distinct answers')
        answers=list(source['outputs']);random.SystemRandom().shuffle(answers)
        row={'case_id':f'choice-{len(keys)+1:02d}','current_message':source['current_message'],
             'clock':source['shared_authoritative_clock'],'prior_evidence':source['pre_target_evidence'],
             'answers':{label:answer['text'] for label,answer in zip(('A','B'),answers,strict=True)}}
        row['evidence_hash']=canonical_hash(row)
        packet['cases'].append(row)
        keys.append({'case_id':row['case_id'],'source_pair':name,'source_packet_hash':canonical_hash(source),
                     'source_case_id':job['case_id'],'labels':{label:answer['label'] for label,answer in zip(('A','B'),answers,strict=True)},
                     'original_key_hash':digest(run/'keys'/f'{name}.LOCAL_ONLY.json')})
    packet['packet_hash']=canonical_hash(packet)
    output.mkdir(parents=True)
    # Local permissions are set by the same owner-only preparation boundary.
    import os
    if os.name=='nt':
        import csv,subprocess
        sid=next(csv.reader(subprocess.check_output(['whoami','/user','/fo','csv','/nh'],text=True).strip().splitlines()))[1]
        subprocess.run(['icacls',str(output),'/inheritance:r','/grant:r',f'*{sid}:(OI)(CI)F'],check=True,capture_output=True)
    write(output/'owner-packet.LOCAL_ONLY.json',packet)
    write(output/'source-key.LOCAL_ONLY.json',{'packet_hash':packet['packet_hash'],'source_run':str(run.resolve()),'cases':keys})
    (output/'owner-review.LOCAL_ONLY.html').write_text(render(packet),encoding='utf-8')
    write(output/'manifest.LOCAL_ONLY.json',{'policy':POLICY,'packet_hash':packet['packet_hash'],
        'files':{p.name:digest(p) for p in output.iterdir() if p.is_file()},
        'owner_choices':'pending; no actual owner preferences have been recorded'})
    return packet


def validate_packet(packet):
    if packet['policy'] != POLICY or packet['questions'] != QUESTIONS:
        raise ValueError('owner review purpose or privacy changed')
    if packet['packet_hash'] != canonical_hash({k:v for k,v in packet.items() if k!='packet_hash'}):
        raise ValueError('owner packet changed')
    for case in packet['cases']:
        if case['evidence_hash'] != canonical_hash({k:v for k,v in case.items() if k!='evidence_hash'}):
            raise ValueError('owner evidence changed')


def record_choices(directory: Path, choices_path: Path, destination: Path):
    manifest=read(directory/'manifest.LOCAL_ONLY.json')
    for name,expected in manifest['files'].items():
        if digest(directory/name)!=expected: raise ValueError('sealed owner artifact changed')
    packet=read(directory/'owner-packet.LOCAL_ONLY.json');validate_packet(packet)
    choices=read(choices_path)
    if set(choices) != {'schema_version','packet_hash','choices'} or choices['schema_version']!=1:
        raise ValueError('invalid owner choice contract')
    if choices['packet_hash'] != packet['packet_hash']: raise ValueError('choices refer to another packet')
    expected={c['case_id'] for c in packet['cases']}
    rows=choices['choices']
    if not isinstance(rows,list) or len(rows)!=len(expected) or {r.get('case_id') for r in rows}!=expected:
        raise ValueError('every reviewed case must have exactly one owner response')
    for row in rows:
        if set(row)!={'case_id',*QUESTIONS} or any(row[q] not in CHOICES for q in QUESTIONS):
            raise ValueError('invalid owner choice')
    receipt={'schema_version':1,'policy':POLICY,'packet_hash':packet['packet_hash'],
             'source_file_sha256':digest(choices_path),'recorded_at':datetime.now(UTC).isoformat(),
             'kind':'owner_submitted_product_preference','choices':rows,
             'evidence':[{k:c[k] for k in ('case_id','evidence_hash','answers')} for c in packet['cases']],
             'limits':'Local submission, not authenticated identity proof or an automatic architecture/model decision.'}
    write(destination,receipt)
    return receipt


def render(packet):
    validate_packet(packet)
    parts=[]
    for i,case in enumerate(packet['cases'],1):
        evidence=''.join(f'<p><b>{"你" if row["role"]=="user" else "HAVRE"}</b> · {escape(str(row.get("at","")))}<br>{escape(row["text"])}</p>'
                         for row in case['prior_evidence'])
        answers=''.join(f'<article><h3>回复 {label}</h3><div class="reply">{escape(text)}</div></article>' for label,text in case['answers'].items())
        questions=''
        for key,title in QUESTIONS.items():
            inputs=''.join(f'<label><input type="radio" required name="{case["case_id"]}-{key}" value="{value}">{label}</label>'
                          for value,label in [('A','A'),('B','B'),('tie','差不多'),('cannot_judge','无法判断')])
            questions+=f'<fieldset><legend>{title}</legend>{inputs}</fieldset>'
        parts.append(f'<section><p class="number">{i:02d} / {len(packet["cases"]):02d}</p><p class="time">当时：{escape(case["clock"]["target_received_at"])}</p><div class="message">{escape(case["current_message"])}</div><details><summary>需要时查看当时之前的对话</summary>{evidence}</details><div class="answers">{answers}</div>{questions}</section>')
    export=json.dumps({'packet_hash':packet['packet_hash'],'ids':[c['case_id'] for c in packet['cases']]},ensure_ascii=True).replace('<','\\u003c')
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>HAVRE · 聊天感受</title><style>
*{box-sizing:border-box}body{margin:0;background:#f5f4ee;color:#243f3a;font:16px/1.7 system-ui,sans-serif}main{max-width:900px;margin:auto;padding:32px 18px 90px}h1{font-size:30px;letter-spacing:.04em}header p{color:#53665e}section{background:#fffefa;border:1px solid #dadfd5;border-radius:18px;padding:24px;margin:24px 0}.number{font:600 14px system-ui;color:#657c6b}.time{font-size:12px;color:#65756b}.message{white-space:pre-wrap;background:#edf2e9;padding:16px;border-radius:10px}details{margin:15px 0;color:#596961}details p{white-space:pre-wrap;font-size:14px}summary{cursor:pointer}.answers{display:grid;grid-template-columns:1fr 1fr;gap:22px}article{min-width:0}.reply{white-space:pre-wrap;overflow-wrap:anywhere}h3{font-size:15px}fieldset{border:0;border-top:1px solid #e2e6dd;padding:16px 0 0;margin:22px 0 0}legend{font-weight:600;padding:0 8px 0 0}label{display:inline-flex;align-items:center;gap:6px;margin:7px 15px 0 0;padding:8px 4px;cursor:pointer}input{width:18px;height:18px;accent-color:#42654d}button{background:#365d46;color:white;border:0;border-radius:10px;padding:14px 24px;font:600 16px system-ui;cursor:pointer}.footer{position:sticky;bottom:0;background:#f5f4eef5;padding:14px 0;display:flex;justify-content:space-between;align-items:center;gap:12px}.note{font-size:13px;color:#65756b}@media(max-width:620px){.answers{grid-template-columns:1fr}section{padding:18px}article+article{border-top:1px solid #e2e6dd}h1{font-size:26px}}
</style><main><header><p>HAVRE · 渡禾</p><h1>哪种回应，更让你想聊下去？</h1><p>每段只选两次。没有标准答案，也不用解释理由。拿不准时选「无法判断」。</p><p class="note">这是本机回顾页。选择不会上传；点击导出才保存文件。刷新页面会清空尚未导出的选择。</p></header><form id="review">'''+''.join(parts)+'''<div class="footer"><span id="progress">已选 0 项</span><button type="submit">导出我的选择</button></div></form><p class="note">导出的选择仅用于你对产品体验的回归依据，不自动作为训练数据。</p></main><script>
const packet='''+export+''';const form=document.querySelector('#review');
form.addEventListener('change',()=>{document.querySelector('#progress').textContent=`已选 ${document.querySelectorAll('input:checked').length} / ${packet.ids.length*2} 项`;});
form.addEventListener('submit',event=>{event.preventDefault();const data=new FormData(form);const result={schema_version:1,packet_hash:packet.packet_hash,choices:packet.ids.map(id=>({case_id:id,like_havre:data.get(`${id}-like_havre`),continue_chat:data.get(`${id}-continue_chat`)}))};const blob=new Blob([JSON.stringify(result,null,2)+'\\n'],{type:'application/json'});const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download='havre-owner-choices.LOCAL_ONLY.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
</script></html>'''


if __name__=='__main__':
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare');p.add_argument('--run',type=Path,required=True);p.add_argument('--pairs',required=True);p.add_argument('--output',type=Path,required=True)
    p=sub.add_parser('record');p.add_argument('--directory',type=Path,required=True);p.add_argument('--choices',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.command=='prepare':
        result=prepare(args.run,[int(x) for x in args.pairs.split(',')],args.output)
        print(json.dumps({'cases':len(result['cases']),'packet_hash':result['packet_hash'],'owner_choices':'pending'}))
    else:
        result=record_choices(args.directory,args.choices,args.output)
        print(json.dumps({'recorded_choices':len(result['choices']),'training_eligible':False}))
