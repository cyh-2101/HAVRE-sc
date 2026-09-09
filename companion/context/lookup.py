"""Bounded owner-requested reads through existing Context evidence contracts.

No database credentials or arbitrary SQL are exposed to a model. Routine chat
keeps its existing selectors; explicit record questions can request a snapshot.
"""
from datetime import date, timedelta
from zoneinfo import ZoneInfo
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict
from companion.context.models import PersonalContextItem
from companion.commitments.recognition import task_tokens
from companion.policy import PrivacyClass, combine_policies
from companion.policy.models import PRIVACY_RESTRICTION_ORDER


class PersonalLookupRequest(BaseModel):
    model_config=ConfigDict(frozen=True,extra="forbid")
    kind: Literal["diary","goals","user_model"]
    query: str
    local_date: date | None = None


def lookup_request(query, *, current_time, timezone_name):
    if re.search(r"(?:别|不要|不用|不想|不许).{0,10}(?:日记|目标|用户模型|记录)|don.t (?:read|look up|mention)", query, re.I):
        return None
    if re.search(r"日记|\bdiary\b",query,re.I):
        today=current_time.astimezone(ZoneInfo(timezone_name)).date()
        day=today-timedelta(days=1) if "昨天" in query else today if "今天" in query else None
        match=re.search(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})",query)
        if match:
            try: day=date(*(int(x) for x in match.groups()))
            except ValueError: return None
        return PersonalLookupRequest(kind="diary",query=query,local_date=day)
    if re.search(r"user\s*model|用户模型|你(?:觉得|认为)我是|你对我(?:的|有|了解)|为什么觉得我|依据.*(?:了解|判断)",query,re.I):
        return PersonalLookupRequest(kind="user_model",query=query)
    if re.search(r"goal|目标|任务|作业|报告|lab|report|quiz|考试",query,re.I) and re.search(r"查|哪些|什么|状态|完成|写完|做完|记录|提醒|还有|剩|结束|done|status|saved",query,re.I):
        return PersonalLookupRequest(kind="goals",query=query)
    return None


def requested_personal_context(repository, *, current_event, query, timezone_name):
    request=lookup_request(query,current_time=current_event.recorded_at,timezone_name=timezone_name)
    if request is None: return ()
    owner=current_event.owner_id; policy=current_event.data_policy; instant=current_event.recorded_at
    def allowed(p):
        return (PRIVACY_RESTRICTION_ORDER[p.privacy_class]<=PRIVACY_RESTRICTION_ORDER[policy.privacy_class]
            and (not policy.cloud_eligible or (p.cloud_eligible and p.privacy_class in {PrivacyClass.NORMAL,PrivacyClass.PUBLIC})))
    def item(kind,key,text,refs,p):
        return PersonalContextItem(owner_id=owner,section_id=f"requested-{request.kind}-{key}",section_type=kind,
            content_text=text,priority=96,source_refs=(f"event/{current_event.event_id}",*refs),data_policy=p)
    results=[]
    if request.kind=="goals":
        goals=[]
        with repository.pool.connection() as c:
            rows=c.execute("SELECT projection.* FROM havre.commitment_projections projection JOIN havre.goals goal "
                "ON goal.owner_id=projection.owner_id AND goal.goal_id=projection.goal_id AND goal.revision=projection.goal_revision "
                "AND goal.content_hash=projection.source_goal_content_hash WHERE projection.owner_id=%s",(owner,)).fetchall()
        for row in rows:
            p=repository._policy_from_row(row)
            if allowed(p):
                goals.append((row["task_name"],row["completion_state"],row["deadline_at"],
                    (f"goal/{row['goal_id']}@{row['goal_revision']}",f"commitment/{row['commitment_projection_id']}"),p))
        projected={ref for g in goals for ref in g[3] if ref.startswith("goal/")}
        for row in repository.list_goals(owner_id=owner,include_inactive=True):
            p=repository._policy_from_row(row);ref=f"goal/{row['goal_id']}@{row['revision']}"
            if allowed(p) and ref not in projected and row["updated_at"]<=instant:
                goals.append((row["title"],row["status"],row["review_at"],(ref,),p))
        tokens=task_tokens(query)
        def score(g):
            candidate=task_tokens(g[0])
            query_numbers={token for token in tokens if token[0].isdigit()}
            candidate_numbers={token for token in candidate if token[0].isdigit()}
            if query_numbers-candidate_numbers: return 0
            return len(tokens & candidate)
        ranked=sorted(goals,key=lambda g:(-score(g),str(g[2] or "9999"),g[0]))
        matched=[g for g in ranked if score(g)>0]
        if matched:
            ranked=matched
        elif re.search(r"[a-z]{2,}|\d+", re.sub(r"\b(?:goals?|tasks?|status|saved|done|what|which|my|are|is)\b", "", query, flags=re.I), re.I):
            ranked=[]  # A named course/project miss must not return unrelated tasks.
        for i,g in enumerate(ranked[:5]):
            results.append(item("goal",i,f"Current saved task: {g[0]}; status={g[1]}; deadline/review={g[2]}. "
                "This is a bounded lookup, not the whole task list. Owner corrections override stale recorded status; "
                "a statement of completion is not proof the database was updated.",g[3],g[4]))
    elif request.kind=="user_model":
        snapshots=repository.list_belief_snapshots(owner_id=owner,known_as_of=instant,valid_at=instant,include_inactive=False)
        snapshots=[s for s in snapshots if allowed(s.revision.data_policy)]
        snapshots.sort(key=lambda s:-len(task_tokens(query)&task_tokens(s.revision.statement)))
        for s in snapshots[:3]:
            r=s.revision;refs=(f"belief/{r.belief_id}@{r.revision}",*(e.source_ref for e in (*s.supporting_evidence,*s.counter_evidence)))
            results.append(item("user_belief",r.belief_id,"Revisable stored interpretation, not a fact or diagnosis: "+r.statement,refs,r.data_policy))
    else:
        with repository.pool.connection() as c:
            heads=c.execute("SELECT head.local_date,head.current_revision FROM havre.daily_diary_entry_heads head "
                "WHERE head.owner_id=%s AND head.timezone_name=%s AND head.status='current' "
                "AND (%s::date IS NULL OR head.local_date=%s) ORDER BY head.local_date DESC LIMIT 3",
                (owner,timezone_name,request.local_date,request.local_date)).fetchall()
            for head in heads:
                sources=c.execute("SELECT event.* FROM havre.daily_diary_entry_sources source JOIN havre.events event "
                    "ON event.owner_id=source.owner_id AND event.event_id=source.event_id AND event.content_hash=source.event_content_hash "
                    "WHERE source.owner_id=%s AND source.local_date=%s AND source.timezone_name=%s AND source.revision=%s",
                    (owner,head["local_date"],timezone_name,head["current_revision"])).fetchall()
                if not sources or any(not allowed(repository._policy_from_row(r)) or r["recorded_at"]>instant for r in sources): continue
                if c.execute("SELECT 1 FROM havre.offline_source_revocations WHERE owner_id=%s AND source_event_id=ANY(%s::uuid[])",(owner,[r["event_id"] for r in sources])).fetchone(): continue
                row=c.execute("SELECT title,summary_text FROM havre.daily_diary_entry_revisions WHERE owner_id=%s AND local_date=%s AND timezone_name=%s AND revision=%s AND created_at<=%s",
                    (owner,head["local_date"],timezone_name,head["current_revision"],instant)).fetchone()
                if row:
                    results.append(item("episodic_memory",f"{head['local_date']}@{head['current_revision']}",
                        f"Requested diary {head['local_date']} ({timezone_name}), derived first-person summary, not fresh fact: {row['title']}\n{row['summary_text']}",
                        tuple(f"event/{r['event_id']}" for r in sources),combine_policies(tuple(repository._policy_from_row(r) for r in sources))))
    if not results:
        results.append(item("owner_response_instruction","empty",f"The requested {request.kind} lookup returned no eligible evidence. "
            "Say what is unknown; absence here is not proof no record exists. Ask for a date or specific item only if useful.",(),policy))
    return tuple(results)
