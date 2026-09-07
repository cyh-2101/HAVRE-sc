"""Synthetic causal comparison against an explicit historical repository ref.

Runs no real cloud call: the durable interaction fixture uses an injected process
runner. Source text, owners and Events are synthetic. Output contains aggregates.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
from time import perf_counter
from types import SimpleNamespace
from urllib.parse import urlparse
from uuid import uuid4

from companion.context.builder import ContextBuilder
from companion.context.compiler import VERSION
from companion.context.models import ConversationHistoryItem, PersonalContextItem
from companion.context.recall import recalled_history
from companion.context.event_search import event_candidates
from companion.events import EventEnvelope, TextContentPart, UserMessagePayload
from companion.identity import IdentityLoader
from companion.policy import DataPolicy, PrivacyClass

ROOT=Path(__file__).resolve().parents[1]


def historical(ref,path):
    source=subprocess.check_output(["git","show",f"{ref}:{path}"],cwd=ROOT).decode("utf-8")
    namespace={"__name__":"historical_context_comparison"}
    exec(compile(source,f"{ref}:{path}","exec"),namespace)
    return namespace,hashlib.sha256(source.encode()).hexdigest()


def compiler_comparison(baseline):
    old,_=historical(baseline,"companion/context/builder.py")
    builders=(old["ContextBuilder"],ContextBuilder)
    identity=IdentityLoader(ROOT/"identity").load()
    policy=DataPolicy.owner_default(PrivacyClass.NORMAL)
    rows=[]
    for budget in range(300,901,50):
        owner,request,session=uuid4(),uuid4(),uuid4()
        event=EventEnvelope(event_type="USER_MESSAGE",owner_id=owner,request_id=request,session_id=session,
            trace_id=uuid4().hex,data_policy=policy,payload=UserMessagePayload(
                content_parts=(TextContentPart(text="How did our telescope project go?"),),channel="api"))
        history=ConversationHistoryItem(owner_id=owner,session_id=session,event_id=uuid4(),request_id=uuid4(),
            role="user",content_text="Our telescope was repaired together at the observatory. "*6,
            recorded_at=event.recorded_at-timedelta(minutes=1),data_policy=policy)
        examples=tuple(SimpleNamespace(case_id=f"synthetic-{i}",source_refs=("authorization/synthetic",f"example/{i}"),
            rendered_text=lambda:"Optional voice calibration wording. "*38) for i in range(3))
        bank=SimpleNamespace(owner_id=owner,data_policy=policy,runtime_selection_version="synthetic-benchmark",
            example_bank_version="synthetic",select=lambda **kwargs:examples)
        args=dict(request_id=request,trace_id=event.trace_id,owner_id=owner,identity=identity,user_event=event)
        base=ContextBuilder(max_input_tokens=5000,reserved_output_tokens=256).build(**args)
        arms=[]
        for builder in builders:
            pack=builder(max_input_tokens=base.estimated_total_tokens+256+budget,reserved_output_tokens=256,
                owner_example_bank=bank).build(**args,conversation_history=(history,))
            arms.append({"raw_experience_retained":any(s.source_refs[0]==f"event/{history.event_id}" for s in pack.sections),
                "voice_examples":sum(s.section_type=="behavior_example" for s in pack.sections),
                "tokens":pack.estimated_total_tokens,"within_budget":pack.estimated_total_tokens<=pack.token_budget.max_input_tokens-256})
        rows.append({"fixture":"voice_pressure","optional_budget":budget,"baseline":arms[0],"current":arms[1]})
    return rows


async def recall_comparison(baseline):
    from tests.test_personal_context_recall import PersonalContextRecallPostgresTests
    legacy,source_hash=historical(baseline,"companion/context/recall.py")
    cls=PersonalContextRecallPostgresTests;cls.setUpClass()
    fixture=cls("test_two_character_project_anchor_and_gin_expression_are_supported")
    await fixture.asyncSetUp()
    try:
        source=await fixture.turn("我和林舟完成了松桥望远镜项目，当时一起修好了镜片。")
        correction=await fixture.turn("刚才说错了，林舟是以前的同事，不是我的主管。")
        for i in range(140): await fixture.turn(f"合成午餐记录{i}，土豆和西兰花。")
        fixture.repository.memory_encoder=fixture.encoder
        query="还记得松桥望远镜项目修镜片的事情吗"
        rows=[]
        for days,label in ((0,"beyond_last_256_events"),(730,"two_year_source_age")):
            current=fixture.current(query,days=days)
            arms=[]
            for function in (legacy["recalled_history"],recalled_history):
                times=[];found=()
                for _ in range(3):
                    started=perf_counter()
                    found=function(fixture.repository,owner_id=fixture.owner,query=query,current_event=current,
                        recent=(),explicit=True,timezone_name="America/Chicago")
                    times.append((perf_counter()-started)*1000)
                ids={t.event_id for t in found}
                arms.append({"exact_owner_experience":source.user_event_id in ids,
                    "exact_assistant_pair":source.assistant_event_id in ids,
                    "nearby_owner_correction":correction.user_event_id in ids,
                    "returned_events":len(found),"median_ms":round(statistics.median(times),3)})
            rows.append({"fixture":label,"baseline":arms[0],"current":arms[1]})
        long_text=("Lunch included potatoes, carrots, and broccoli. "*200)+"我和许棠在枫港修好了旧收音机的天线。"
        long_source=await fixture.turn(long_text)
        ambiguity_a=await fixture.turn("林舟今天联系我，想再聊聊之前的项目。")
        ambiguity_b=await fixture.turn("顾岚今天也联系我，想再聊聊之前的项目。")
        probes=(
            ("long_event_tail", "还记得我和许棠在枫港修旧收音机天线的事情吗", (long_source.user_event_id,)),
            ("absent_experience", "还记得北极冰川科考队养企鹅的事情吗", ()),
            ("unresolved_person_reference", "那个人今天又联系我聊之前的项目了", (ambiguity_a.user_event_id,ambiguity_b.user_event_id)),
        )
        for label,probe,expected in probes:
            current=fixture.current(probe)
            arms=[]
            for function in (legacy["recalled_history"],recalled_history):
                started=perf_counter()
                found=function(fixture.repository,owner_id=fixture.owner,query=probe,current_event=current,
                    recent=(),explicit=True,timezone_name="America/Chicago")
                ids={item.event_id for item in found}
                arms.append({"source_candidates_retained":sum(e in ids for e in expected),
                    "expected_candidate_count":len(expected),"returned_events":len(found),
                    "exact_excerpt_visible":any("Exact excerpt from preserved Event" in item.content_text for item in found),
                    "single_run_ms":round((perf_counter()-started)*1000,3)})
            rows.append({"fixture":label,"baseline":arms[0],"current":arms[1],
                "interpretation":"Candidate visibility only; no person identity was resolved." if label=="unresolved_person_reference" else "Exact source admission; no generated-answer score."})
        current=fixture.current(query,days=730)
        # Exercise the strict-local candidate path on the same complete owner
        # corpus. This measures the owner-filtered scan path, not million-row scale.
        local_times=[]
        for _ in range(3):
            started=perf_counter()
            event_candidates(fixture.repository,owner_id=fixture.owner,
                allowed_privacy=[p.value for p in PrivacyClass],before=current.recorded_at,query=query,local_only=True)
            local_times.append((perf_counter()-started)*1000)
        with fixture.repository.pool.connection() as c:
            source_count=c.execute("SELECT count(*) n FROM havre.events WHERE owner_id=%s AND event_type IN ('USER_MESSAGE','ASSISTANT_MESSAGE')",(fixture.owner,)).fetchone()["n"]
        return {"baseline_source_sha256":source_hash,"owner_conversation_events":source_count,
                "cases":rows,"strict_local_candidate_median_ms":round(statistics.median(local_times),3)}
    finally:
        fixture.doCleanups();cls.tearDownClass()


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--baseline-ref",required=True)
    parser.add_argument("--output",type=Path,required=True);args=parser.parse_args()
    database=os.environ.get("HAVRE_TEST_DATABASE_URL","")
    name=urlparse(database).path.lstrip("/")
    if not name.startswith("havre_context_engine_test_"):
        raise SystemExit("use an explicit dedicated havre_context_engine_test_* database")
    baseline=subprocess.check_output(["git","rev-parse",args.baseline_ref],cwd=ROOT).decode().strip()
    report={"version":"personal-context-causal-benchmark-v1","privacy":"PUBLIC synthetic only",
        "evaluation_status":"Regression and causal development evidence, not an uncontaminated holdout",
        "baseline_ref":baseline,"compiler":VERSION,
        "limitations":["No generated-answer usefulness score; tests admission and exact source recall.",
            "No million-row scale claim; semantic-only lifelong paraphrase with no lexical anchor remains unsupported.",
            "Legacy builder and current builder use identical current presentation overhead in this causal scheduling comparison."],
        "compiler_cases":compiler_comparison(baseline),
        "recall":asyncio.run(recall_comparison(baseline))}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False))


if __name__=="__main__":main()
