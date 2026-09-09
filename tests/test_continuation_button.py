"""Button provenance, failure boundaries and projection; no model-quality scorer."""
from datetime import UTC, datetime
import os
import unittest
from uuid import uuid4

from companion.application import InteractionCommand
from companion.events import EventEnvelope, TextContentPart, UserMessagePayload
from companion.policy import DataPolicy, PrivacyClass
from companion.product.daily import DailyCompanionStore
from services.api.app import InteractionBody
from tests.test_chat_repair import ConversationRepairTests


class ButtonContractTests(unittest.TestCase):
    def test_legacy_payload_roundtrips_without_a_new_hash_field(self):
        event = EventEnvelope(event_type="USER_MESSAGE",owner_id=uuid4(),session_id=uuid4(),
            request_id=uuid4(),trace_id=uuid4().hex,data_policy=DataPolicy.owner_default(PrivacyClass.NORMAL),
            payload=UserMessagePayload(channel="web",content_parts=(TextContentPart(text="再说点"),)))
        raw = event.model_dump_json()
        self.assertNotIn("input_origin", raw)
        self.assertEqual(EventEnvelope.model_validate_json(raw).content_hash,event.content_hash)
        self.assertEqual(event.payload.input_origin,"owner_text")

    def test_control_requires_its_exact_parent_and_session(self):
        valid=dict(message="再说点",input_origin="continuation_button",session_id=uuid4(),reply_to_event_id=uuid4())
        for model in (InteractionCommand,InteractionBody):
            body={**valid,**({"idempotency_key":"test"} if model is InteractionCommand else {})}
            self.assertEqual(model(**body).input_origin,"continuation_button")
            for change in ({"message":"随便说点"},{"session_id":None},{"reply_to_event_id":None},{"input_origin":"unknown"}):
                with self.subTest(model=model.__name__,change=change),self.assertRaises(ValueError):
                    model(**{**body,**change})


@unittest.skipUnless(os.getenv("HAVRE_TEST_DATABASE_URL"),"requires dedicated PostgreSQL")
class ButtonPersistenceTests(unittest.IsolatedAsyncioTestCase):
    setUpClass=classmethod(ConversationRepairTests.setUpClass.__func__)
    tearDownClass=classmethod(ConversationRepairTests.tearDownClass.__func__)
    asyncSetUp=ConversationRepairTests.asyncSetUp
    _cleanup=ConversationRepairTests._cleanup
    service=ConversationRepairTests.service
    talk=ConversationRepairTests.talk

    async def test_control_survives_reload_without_becoming_a_diary_utterance(self):
        from companion.context.continuation import CONTINUATION_INPUT_TEXT
        service,planner=self.service(planner=True);session=uuid4()
        first=await self.talk(service,"今天看见了一只叼着树枝的狗。",session)
        command=InteractionCommand(message="再说点",session_id=session,channel="web",
            reply_to_event_id=first.assistant_event_id,input_origin="continuation_button",idempotency_key=str(uuid4()))
        count=len(planner.requests)
        result=await service.interact(command)
        self.assertEqual((await service.interact(command)).assistant_event_id,result.assistant_event_id)
        self.assertEqual(len(planner.requests),count)
        event=self.repository.event_by_id(owner_id=self.owner,event_id=result.user_event_id)
        self.assertEqual(event.payload.input_origin,"continuation_button")
        product=DailyCompanionStore(repository=self.repository,owner_id=self.owner)
        row=next(r for r in product.timeline()["items"] if r["event_id"]==result.user_event_id)
        self.assertEqual(row["input_origin"],"continuation_button")
        self.assertEqual(row["reply_to_event_id"],str(first.assistant_event_id))
        self.assertNotIn(result.user_event_id,{r["event_id"] for r in product._day_events(local_date=datetime.now(UTC).date(),timezone_name="UTC")})
        with self.repository.pool.connection() as c:
            sections=c.execute("SELECT sections FROM havre.context_packs WHERE owner_id=%s AND request_id=%s",(self.owner,result.request_id)).fetchone()["sections"]
            self.assertEqual(next(s for s in sections if s["section_type"]=="current_user_input")["content_parts"][0]["text"],CONTINUATION_INPUT_TEXT)
            self.assertEqual(c.execute("SELECT count(*) n FROM havre.background_jobs WHERE owner_id=%s AND source_event_id=%s",(self.owner,event.event_id)).fetchone()["n"],0)
        typed=command.model_copy(update={"input_origin":"owner_text"})
        self.assertNotEqual(service._request_fingerprint(command,None),service._request_fingerprint(typed,None))

    async def test_database_rejects_wrong_session_foreign_and_weakened_source(self):
        import psycopg
        from companion.tracing import TraceContext
        service,_=self.service();session=uuid4()
        normal=await self.talk(service,"普通上下文",session)
        private=await self.talk(service,"私密上下文",session,privacy_class=PrivacyClass.LOCAL_ONLY)
        def reserve(parent,*,target_session=session,policy_class=PrivacyClass.NORMAL):
            trace=TraceContext.from_traceparent(None)
            event=EventEnvelope(event_type="USER_MESSAGE",owner_id=self.owner,session_id=target_session,
                request_id=uuid4(),trace_id=trace.trace_id,data_policy=DataPolicy.owner_default(policy_class),
                payload=UserMessagePayload(channel="web",content_parts=(TextContentPart(text="再说点"),),
                    reply_to_event_id=parent,input_origin="continuation_button"))
            return self.repository.reserve_interaction(idempotency_key=str(uuid4()),request_fingerprint="sha256:"+"0"*64,
                user_event=event,trace=trace,channel="web",trace_started_at=datetime.now(UTC))
        for parent,kw,reason in ((normal.assistant_event_id,{"target_session":uuid4()},"owner/session"),
                                  (uuid4(),{},"owner/session"),(private.assistant_event_id,{},"weaken source policy")):
            with self.assertRaises(psycopg.Error) as rejected:
                reserve(parent,**kw)
            self.assertEqual(rejected.exception.sqlstate,"55000")
            self.assertIn(reason,str(rejected.exception))
        # Successful same-session private continuation proves the privacy fixture is valid.
        result=await self.talk(service,"再说点",session,reply_to_event_id=private.assistant_event_id,input_origin="continuation_button")
        event=self.repository.event_by_id(owner_id=self.owner,event_id=result.user_event_id)
        self.assertEqual(event.data_policy.privacy_class,PrivacyClass.LOCAL_ONLY)
        self.assertFalse(event.data_policy.cloud_eligible)
        original_owner=self.owner
        try:
            self.owner=uuid4();self.repository.bootstrap_owner_and_identity(owner_id=self.owner,identity=self.identity)
            foreign_service,_=self.service();foreign=await self.talk(foreign_service,"别人的对话",uuid4())
        finally:
            self.owner=original_owner
        with self.assertRaises(psycopg.Error) as rejected:
            reserve(foreign.assistant_event_id)
        self.assertEqual(rejected.exception.sqlstate,"55000")
        self.assertIn("owner/session",str(rejected.exception))


del ConversationRepairTests
