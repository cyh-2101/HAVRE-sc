"""Reproduced product failures; model doubles prove wiring, not naturalness."""
from datetime import UTC,datetime,timedelta
import json,os,unittest
from types import SimpleNamespace
from uuid import uuid4
from pathlib import Path
from companion.application import InteractionCommand,InteractionService
from companion.context import ContextBuilder,render_inference_messages
from companion.context.lookup import requested_personal_context,lookup_request
from companion.events import TextContentPart
from companion.goals.service import GoalService
from companion.goals.models import GoalTrack, GoalPriority
from companion.persistence.proactive import ProactivePostgresStore
from companion.policy import PrivacyClass,CoreResponsePolicy
from companion.proactive import ProactivePreferenceRevision
from companion.product.chat_goals import ChatGoalPlan,ExplicitChatGoalPlanner
from mlsys.serving import DeterministicLocalProvider,Stage1Router
from tests.test_chat_goal_planner import ChatGoalPlannerPostgresTests as Fixture


class PlanProvider:
    def __init__(self):self.requests=[];self.output=None
    async def generate(self,request):
        self.requests.append(request)
        data=json.loads(request.messages[-1].content_parts[0].text)
        plan=self.output or {"schema_version":1,"create_goal":False}
        if self.output is None and data["message"]=="随机时间吧":
            day=datetime.now(UTC).date()+timedelta(days=1)
            plan={"schema_version":1,"create_goal":True,"source_quote":"帮我创建一个目标：练琴", "track":"reality",
                "title":"每天练琴","why":"希望每天练琴","priority":"normal","daily_reminder":{
                    "start_date":str(day),"end_date":str(day+timedelta(days=29)),"local_time":None,"varying_daytime":True}}
        return SimpleNamespace(output_parts=(TextContentPart(text=json.dumps(plan,ensure_ascii=False)),),
            provider=SimpleNamespace(provider_id="openai-codex-chatgpt"),versions=SimpleNamespace(
                model_version_id="gpt-5.6-sol",provider_adapter_version_id="test-bound-planner",serving_config_version="test-high"))


# One exact-transcript action-claim regression is intentionally omitted from
# this public file. Its ID and reason are recorded in the verification runner;
# it is not replaced with invented data or counted as a passing public test.


@unittest.skipUnless(os.getenv("HAVRE_TEST_DATABASE_URL"),"requires dedicated PostgreSQL")
class ConversationRepairTests(unittest.IsolatedAsyncioTestCase):
    setUpClass=classmethod(Fixture.setUpClass.__func__)
    tearDownClass=classmethod(Fixture.tearDownClass.__func__)
    asyncSetUp=Fixture.asyncSetUp
    _cleanup=Fixture._cleanup

    def service(self,*,planner=False):
        provider=PlanProvider();store=ProactivePostgresStore(repository=self.repository,owner_id=self.owner,identity=self.identity)
        store.save_preference(ProactivePreferenceRevision(owner_id=self.owner,revision=1,global_enabled=True,
            category_permissions={"owner_reminder":"allowed"},allowed_channels=("web_inbox",),authorization_ref="test-explicit-reminders"))
        action=ExplicitChatGoalPlanner(repository=self.repository,owner_id=self.owner,provider=provider,
            goal_service=GoalService(repository=self.repository),proactive_store=store,owner_timezone="UTC")
        service=InteractionService(owner_id=self.owner,identity=self.identity,repository=self.repository,
            context_builder=ContextBuilder(max_input_tokens=8192,reserved_output_tokens=256,owner_timezone="UTC"),
            router=Stage1Router(),provider=DeterministicLocalProvider(),retrieval_service=self.retrieval,
            chat_goal_planner=action if planner else None)
        return service,provider

    async def talk(self,service,text,session,**kwargs):
        return await service.interact(InteractionCommand(message=text,session_id=session,channel="web",idempotency_key=str(uuid4()),**kwargs))

    async def test_multi_turn_schedule_has_sources_and_does_not_repeat(self):
        service,provider=self.service(planner=True);session=uuid4()
        first=await self.talk(service,"帮我创建一个目标：练琴，提醒我",session)
        await self.talk(service,"一个月之内。你需要每天提醒我",session)
        result=await self.talk(service,"随机时间吧",session)
        with self.repository.pool.connection() as c:
            goal=c.execute("SELECT goal_id FROM havre.goals WHERE owner_id=%s",(self.owner,)).fetchall()
            self.assertEqual(len(goal),1)
            work=c.execute("SELECT not_before FROM havre.proactive_work_items WHERE owner_id=%s ORDER BY not_before",(self.owner,)).fetchall()
            self.assertEqual(len(work),30)
            self.assertEqual(len({row["not_before"].date() for row in work}),30)
            self.assertTrue(all(10<=row["not_before"].astimezone(UTC).hour<=21 for row in work))
            sources=c.execute("SELECT event_id FROM havre.owner_chat_goal_plan_sources WHERE owner_id=%s",(self.owner,)).fetchall()
            self.assertIn(first.user_event_id,{row["event_id"] for row in sources})
        self.assertIn("练琴",provider.requests[-1].messages[-1].content_parts[0].text)
        before=len(provider.requests)
        await self.talk(service,"再说点",session,reply_to_event_id=result.assistant_event_id)
        self.assertEqual(len(provider.requests),before)
        self.repository.erase_source_event_derivatives(owner_id=self.owner,source_event_id=first.user_event_id)
        with self.repository.pool.connection() as c:
            self.assertEqual(c.execute("SELECT count(*) n FROM havre.goals WHERE owner_id=%s",(self.owner,)).fetchone()["n"],0)
            self.assertEqual(c.execute("SELECT count(*) n FROM havre.proactive_work_items WHERE owner_id=%s",(self.owner,)).fetchone()["n"],0)

    async def test_say_more_and_topic_change_do_not_resume_an_unfinished_action(self):
        service,provider=self.service(planner=True);session=uuid4()
        previous=await self.talk(service,"帮我创建一个目标：练琴，提醒我",session)
        count=len(provider.requests)
        await self.talk(service,"再说点",session,reply_to_event_id=previous.assistant_event_id)
        self.assertEqual(len(provider.requests),count)
        await self.talk(service,"今天看到一只猫",session)
        await self.talk(service,"随机时间吧",session)
        self.assertEqual(len(provider.requests),count)

    async def test_conversation_source_guards_reject_exact_forbidden_relationships(self):
        import psycopg
        from psycopg.types.json import Jsonb
        from companion.hashing import content_hash
        service,_=self.service();session=uuid4()
        source=await self.talk(service,"正常来源",session)
        private=await self.talk(service,"私有来源",session,privacy_class=PrivacyClass.LOCAL_ONLY)
        elsewhere=await self.talk(service,"其他会话",uuid4())
        current=await self.talk(service,"当前锚点",session)
        current_event=self.repository.event_by_id(owner_id=self.owner,event_id=current.user_event_id)
        def event(result):
            return self.repository.event_by_id(owner_id=self.owner,event_id=result.user_event_id)
        valid,restricted,other_session=event(source),event(private),event(elsewhere)
        async def probe(source_event,*,bad_hash=False,missing=False):
            source_hash="sha256:"+"0"*64 if bad_hash else source_event.content_hash
            manifest=Jsonb([{"event_id":str(source_event.event_id),"content_hash":source_hash}])
            with self.assertRaises(psycopg.Error) as rejected:
                with self.repository.pool.connection() as c,c.transaction():
                    c.execute("SET LOCAL ROLE havre_application")
                    run=uuid4()
                    c.execute("INSERT INTO havre.owner_chat_goal_plan_runs "
                        "(plan_run_id,owner_id,source_event_id,source_event_content_hash,explicit_intent_hash,status,error_code,authorization_ref,source_manifest) "
                        "VALUES (%s,%s,%s,%s,%s,'failed','source-guard-probe','product-owner/explicit-chat-goal-planning-2026-09-04',%s)",
                        (run,self.owner,current_event.event_id,current_event.content_hash,content_hash({"message":"当前锚点"}),manifest))
                    if not missing:
                        c.execute("INSERT INTO havre.owner_chat_goal_plan_sources(owner_id,plan_run_id,event_id,event_content_hash) VALUES (%s,%s,%s,%s)",
                            (self.owner,run,source_event.event_id,source_hash))
            self.assertEqual(rejected.exception.sqlstate,"55000",str(rejected.exception))
            self.assertIn("manifest is incomplete" if missing else "conversation source mismatch",str(rejected.exception))
        await probe(valid,bad_hash=True)
        await probe(restricted)
        await probe(other_session)
        await probe(valid,missing=True)
        owner=self.owner
        try:
            self.owner=uuid4()
            self.repository.bootstrap_owner_and_identity(owner_id=self.owner,identity=self.identity)
            foreign_service,_=self.service()
            foreign_result=await self.talk(foreign_service,"另一个 owner 的来源",uuid4())
            foreign_event=self.repository.event_by_id(owner_id=self.owner,event_id=foreign_result.user_event_id)
        finally:
            self.owner=owner
        await probe(foreign_event)
        self.repository.erase_source_event_derivatives(owner_id=self.owner,source_event_id=valid.event_id)
        await probe(valid)

    async def test_private_boundary_is_not_used_for_cloud_planning(self):
        service,provider=self.service(planner=True);session=uuid4()
        await self.talk(service,"帮我创建一个目标：秘密计划，提醒我",session,privacy_class=PrivacyClass.LOCAL_ONLY)
        await self.talk(service,"随机时间吧",session)
        self.assertEqual(provider.requests,[])

    async def test_continuation_binds_exact_reply_and_retries(self):
        service,_=self.service();session=uuid4()
        previous=await self.talk(service,"今天试了新餐馆",session)
        command=InteractionCommand(message="再说点",reply_to_event_id=previous.assistant_event_id,session_id=session,channel="web",idempotency_key=str(uuid4()))
        continued=await service.interact(command);replay=await service.interact(command)
        self.assertEqual(continued.assistant_event_id,replay.assistant_event_id)
        user=self.repository.event_by_id(owner_id=self.owner,event_id=continued.user_event_id)
        self.assertEqual(user.payload.reply_to_event_id,previous.assistant_event_id)
        with self.repository.pool.connection() as c:
            pack=c.execute("SELECT sections FROM havre.context_packs WHERE owner_id=%s AND request_id=%s",(self.owner,continued.request_id)).fetchone()
        sections=pack["sections"]
        parent=[s for s in sections if s["section_type"]=="conversation_assistant_message" and f"event/{previous.assistant_event_id}" in s["source_refs"]]
        self.assertEqual(len(parent),1)
        self.assertTrue(any(s["section_id"].startswith("reply-continuation-") for s in sections))
        with self.assertRaises(ValueError):
            await self.talk(service,"再说点",uuid4(),reply_to_event_id=previous.assistant_event_id)

    async def test_revoked_continuation_source_cannot_be_reintroduced(self):
        from companion.context.continuation import continuation_context
        service,_=self.service();session=uuid4()
        previous=await self.talk(service,"这个来源之后会撤回",session)
        parent=self.repository.event_by_id(owner_id=self.owner,event_id=previous.assistant_event_id)
        source=self.repository.event_by_id(owner_id=self.owner,event_id=previous.user_event_id)
        self.repository.erase_source_event_derivatives(owner_id=self.owner,source_event_id=source.event_id)
        with self.assertRaisesRegex(ValueError,"removed|revoked"):
            continuation_context(self.repository,parent=parent,current=source)

    async def test_continuation_inherits_private_parent(self):
        service,_=self.service();session=uuid4()
        previous=await self.talk(service,"仅本机的聊天",session,privacy_class=PrivacyClass.LOCAL_ONLY)
        result=await self.talk(service,"多说点",session,reply_to_event_id=previous.assistant_event_id)
        event=self.repository.event_by_id(owner_id=self.owner,event_id=result.user_event_id)
        self.assertEqual(event.data_policy.privacy_class,PrivacyClass.LOCAL_ONLY)
        self.assertFalse(event.data_policy.cloud_eligible)

    async def test_missing_lookup_is_honest_and_ordinary_chat_does_not_lookup(self):
        service,_=self.service();result=await self.talk(service,"昨天的日记记了什么",uuid4())
        event=self.repository.event_by_id(owner_id=self.owner,event_id=result.user_event_id)
        context=requested_personal_context(self.repository,current_event=event,query="昨天的日记记了什么",timezone_name="UTC")
        self.assertIn("no eligible evidence",context[0].content_text)
        for query in ("我刚看到一只猫","不要读取我的日记","别提用户模型了"):
            self.assertIsNone(lookup_request(query,current_time=event.recorded_at,timezone_name="UTC"))
        GoalService(repository=self.repository).create(owner_id=self.owner,track=GoalTrack.REALITY,title="完成 ECE 385 Lab 1",why="课程任务",source_event_id=event.event_id,priority=GoalPriority.NORMAL)
        fresh=await self.talk(service,"查看任务状态",uuid4())
        event=self.repository.event_by_id(owner_id=self.owner,event_id=fresh.user_event_id)
        found=requested_personal_context(self.repository,current_event=event,query="ECE 385 Lab 1 状态是什么",timezone_name="UTC")
        self.assertTrue(any("ECE 385" in item.content_text for item in found))
        missing=requested_personal_context(self.repository,current_event=event,query="CS 999 Lab 9 状态是什么",timezone_name="UTC")
        self.assertTrue(all("ECE 385" not in item.content_text for item in missing))

    async def test_diary_lookup_is_source_bound_and_private_diary_is_excluded(self):
        from companion.product.daily import DailyCompanionStore
        service,_=self.service();session=uuid4()
        source=await self.talk(service,"今天我去河边散步，遇见了一只橘猫。",session)
        product=DailyCompanionStore(repository=self.repository,owner_id=self.owner)
        entry=product.sync_diary_day(local_date=datetime.now(UTC).date(),timezone_name="UTC")
        self.assertIsNotNone(entry)
        ask=await self.talk(service,"今天的日记记了什么",session)
        event=self.repository.event_by_id(owner_id=self.owner,event_id=ask.user_event_id)
        context=requested_personal_context(self.repository,current_event=event,query="今天的日记",timezone_name="UTC")
        self.assertTrue(any(f"event/{source.user_event_id}" in item.source_refs for item in context))
        await self.talk(service,"今天我和秘密小组讨论了秘密行程。",session,privacy_class=PrivacyClass.LOCAL_ONLY)
        product.sync_diary_day(local_date=datetime.now(UTC).date(),timezone_name="UTC")
        new_ask=await self.talk(service,"今天的日记记了什么",session)
        current=self.repository.event_by_id(owner_id=self.owner,event_id=new_ask.user_event_id)
        limited=requested_personal_context(self.repository,current_event=current,query="今天的日记",timezone_name="UTC")
        self.assertFalse(any("秘密" in item.content_text for item in limited))

del Fixture
