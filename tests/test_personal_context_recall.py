"""Indexed lifelong Event recall with exact synthetic GPT source receipts."""
from datetime import UTC, datetime, timedelta
from functools import partial
import json
import os
from pathlib import Path
import tempfile
from time import perf_counter
import unittest
from uuid import uuid4
from unittest.mock import patch

from companion.application import InteractionCommand, InteractionService
from companion.context import ContextBuilder
from companion.context.event_search import event_candidates, query_terms
from companion.context.recall import recalled_history
from companion.events import EventEnvelope, TextContentPart, UserMessagePayload
from companion.identity import IdentityLoader
from companion.memory import DeterministicEmbeddingProvider
from companion.memory.semantic import LocalSemanticEmbeddingProvider
from companion.persistence import PostgresRepository, apply_migrations
from companion.policy import DataPolicy, PrivacyClass
from mlsys.retrieval.service import RetrievalService
from mlsys.serving import Stage1Router, DeterministicLocalProvider
from mlsys.serving.codex_cli import (CodexCliProvider, CodexProcessResult,
    CODEX_CLI_PROVIDER_ID, CODEX_OWNER_AUTOMATIC_AUTHORIZATION_REF, bind_codex_cli_request)

ROOT=Path(__file__).resolve().parents[1]
DATABASE=os.getenv("HAVRE_TEST_DATABASE_URL")


async def synthetic_runner(args,stdin,cwd,environment,timeout):
    if args[-1]=="--version": return CodexProcessResult(0,"codex-cli 0.152.0","")
    if args[1:]==("login","status"): return CodexProcessResult(0,"Logged in using ChatGPT","")
    return CodexProcessResult(0,"\n".join((
        json.dumps({"type":"thread.started","thread_id":"synthetic"}),
        json.dumps({"type":"item.completed","item":{"type":"agent_message","text":"Tell me more."}}),
        json.dumps({"type":"turn.completed","usage":{"input_tokens":100,"cached_input_tokens":0,"output_tokens":10,"reasoning_output_tokens":0}}))),"")


@unittest.skipUnless(DATABASE,"HAVRE_TEST_DATABASE_URL is required")
class PersonalContextRecallPostgresTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        apply_migrations(DATABASE, ROOT/"db/migrations")
        cls.repository=PostgresRepository(DATABASE);cls.repository.open()
        cls.identity=IdentityLoader(ROOT/"identity").load()
        cls.encoder=LocalSemanticEmbeddingProvider(ROOT/"var/models/memory-minilm-v1")

    @classmethod
    def tearDownClass(cls): cls.repository.close()

    async def asyncSetUp(self):
        self.owner=uuid4();self.repository.memory_encoder=None
        self.repository.bootstrap_owner_and_identity(owner_id=self.owner,identity=self.identity)
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        executable=Path(self.folder.name)/"codex.exe";executable.touch()
        provider=CodexCliProvider(executable=executable,enabled=True,
            explicit_authorization_ref=CODEX_OWNER_AUTOMATIC_AUTHORIZATION_REF,
            reasoning_effort="medium",process_runner=synthetic_runner,
            environment={"PATH":"safe","CODEX_HOME":self.folder.name})
        self.service=InteractionService(owner_id=self.owner,identity=self.identity,repository=self.repository,
            context_builder=ContextBuilder(max_input_tokens=12000,reserved_output_tokens=256),
            router=Stage1Router(approved_cloud_provider_ids=frozenset({CODEX_CLI_PROVIDER_ID})),
            provider=provider,retrieval_service=RetrievalService(repository=self.repository,embedding_provider=DeterministicEmbeddingProvider()),
            request_binders={CODEX_CLI_PROVIDER_ID:partial(bind_codex_cli_request,reasoning_effort="medium")})

    async def turn(self,text):
        return await self.service.interact(InteractionCommand(message=text,idempotency_key=str(uuid4()),channel="api"))

    def current(self,query,days=0):
        return EventEnvelope(event_type="USER_MESSAGE",owner_id=self.owner,request_id=uuid4(),session_id=uuid4(),
            trace_id=uuid4().hex,recorded_at=datetime.now(UTC)+timedelta(days=days),
            data_policy=DataPolicy.owner_default(PrivacyClass.NORMAL),
            payload=UserMessagePayload(content_parts=(TextContentPart(text=query),),channel="api"))

    async def test_old_exact_experience_survives_more_than_256_recent_event_distractors(self):
        source=await self.turn("我去年和林舟完成了松桥望远镜项目，当时一起修好了镜片。")
        correction=await self.turn("刚才说错了，林舟是以前的同事，不是我的主管。")
        for index in range(135):
            await self.turn(f"午饭吃了土豆和西兰花，第{index}份合成记录。")
        query="还记得松桥望远镜项目修镜片的事情吗"
        current=self.current(query,days=366)
        self.repository.memory_encoder=self.encoder
        found=recalled_history(self.repository,owner_id=self.owner,query=query,current_event=current,
            recent=(),explicit=True,timezone_name="America/Chicago")
        ids={item.event_id for item in found}
        self.assertIn(source.user_event_id,ids);self.assertIn(source.assistant_event_id,ids)
        self.assertIn(correction.user_event_id,ids)
        self.assertLessEqual(len(found),12)
        # Same sources are outside both historical seven-day and last-256 limits.
        with self.repository.pool.connection() as c:
            historical=c.execute("SELECT count(*) n FROM havre.events WHERE owner_id=%s AND recorded_at>=%s",
                (self.owner,current.recorded_at-timedelta(days=7))).fetchone()["n"]
            rank=c.execute("SELECT count(*) n FROM havre.events WHERE owner_id=%s AND event_type IN ('USER_MESSAGE','ASSISTANT_MESSAGE') AND recorded_at>(SELECT recorded_at FROM havre.events WHERE owner_id=%s AND event_id=%s)",
                (self.owner,self.owner,source.user_event_id)).fetchone()["n"]
        self.assertEqual(historical,0);self.assertGreater(rank,256)
        actual=await self.turn(query)
        evidence=self.repository.evidence(actual.request_id,owner_id=self.owner)
        sections=evidence["context_pack"]["sections"]
        self.assertTrue(any(f"event/{source.user_event_id}" in item["source_refs"] for item in sections))
        self.assertTrue(any(ref.startswith("context-selector/personal-event-search-indexed-v1/")
                            for item in sections for ref in item["source_refs"]))
        # An independent owner's query cannot access any candidate.
        self.assertEqual(event_candidates(self.repository,owner_id=uuid4(),allowed_privacy=["PUBLIC","NORMAL"],
            before=current.recorded_at,query=query),[])
        self.repository.erase_source_event_derivatives(owner_id=self.owner,source_event_id=source.user_event_id)
        after=recalled_history(self.repository,owner_id=self.owner,query=query,current_event=current,
            recent=(),explicit=True,timezone_name="America/Chicago")
        self.assertNotIn(source.user_event_id,{item.event_id for item in after})
        self.assertNotIn(source.assistant_event_id,{item.event_id for item in after})

    async def test_two_character_project_anchor_and_gin_expression_are_supported(self):
        source=await self.turn("Li and I completed our AI project.")
        current=self.current("remember Li AI",days=730)
        found=event_candidates(self.repository,owner_id=self.owner,allowed_privacy=["PUBLIC","NORMAL"],
            before=current.recorded_at,query="remember Li AI")
        self.assertIn(source.user_event_id,{row["event_id"] for row in found})
        with self.repository.pool.connection() as c,c.transaction():
            terms=c.execute("SELECT havre.event_context_search_terms(%s::jsonb) AS terms",
                (json.dumps({"content_parts":[{"type":"text","text":"Li AI 松桥望远镜"}]}),)).fetchone()["terms"]
            self.assertIn("li",terms);self.assertIn("ai",terms);self.assertIn("松桥",terms)
            c.execute("SET LOCAL enable_seqscan=off")
            plan=c.execute("""EXPLAIN (FORMAT JSON) SELECT event_id FROM havre.events
                WHERE event_type='USER_MESSAGE' AND privacy_class IN ('PUBLIC','NORMAL')
                  AND cloud_eligible AND memory_eligible
                  AND havre.event_context_search_terms(payload) && %s::text[]""",(["ai"],)).fetchone()
        self.assertIn("events_personal_context_terms_gin_idx",json.dumps(plan))

    async def test_index_eligibility_rejects_private_future_and_memory_ineligible_sources(self):
        normal=await self.turn("Li AI source")
        event=self.repository.event_by_id(owner_id=self.owner,event_id=normal.user_event_id)
        self.assertEqual(event_candidates(self.repository,owner_id=self.owner,allowed_privacy=["PUBLIC","NORMAL"],
            before=event.recorded_at,query="Li AI"),[])
        # Independently require the owner privacy ceiling even for indexed PUBLIC/NORMAL rows.
        self.assertEqual(event_candidates(self.repository,owner_id=self.owner,allowed_privacy=["PUBLIC"],
            before=event.recorded_at+timedelta(days=1),query="Li AI"),[])

    async def test_local_only_lifetime_recall_never_enters_normal_cloud_request(self):
        local=InteractionService(owner_id=self.owner,identity=self.identity,repository=self.repository,
            context_builder=ContextBuilder(max_input_tokens=12000,reserved_output_tokens=256),
            router=Stage1Router(),provider=DeterministicLocalProvider(),
            retrieval_service=RetrievalService(repository=self.repository,embedding_provider=DeterministicEmbeddingProvider()))
        source=await local.interact(InteractionCommand(message="我和林舟完成了松桥望远镜项目的私下讨论。",
            privacy_class=PrivacyClass.LOCAL_ONLY,idempotency_key=str(uuid4())))
        query="还记得松桥望远镜项目吗"
        current=self.current(query,days=366).model_copy(update={"data_policy":DataPolicy.owner_default(PrivacyClass.LOCAL_ONLY)})
        self.repository.memory_encoder=self.encoder
        found=recalled_history(self.repository,owner_id=self.owner,query=query,current_event=current,
            recent=(),explicit=True,timezone_name="America/Chicago")
        self.assertIn(source.user_event_id,{t.event_id for t in found})
        self.assertTrue(all(t.data_policy.privacy_class is PrivacyClass.LOCAL_ONLY for t in found))
        normal=current.model_copy(update={"data_policy":DataPolicy.owner_default(PrivacyClass.NORMAL)})
        self.assertEqual(recalled_history(self.repository,owner_id=self.owner,query=query,current_event=normal,
            recent=(),explicit=True,timezone_name="America/Chicago"),())
        pack=ContextBuilder(max_input_tokens=12000,reserved_output_tokens=256).build(
            request_id=current.request_id,trace_id=current.trace_id,owner_id=self.owner,identity=self.identity,
            user_event=current,conversation_history=found)
        self.assertEqual(pack.effective_data_policy.privacy_class,PrivacyClass.LOCAL_ONLY)
        self.assertFalse(pack.effective_data_policy.cloud_eligible)

    async def test_long_event_tail_is_scored_and_returned_as_exact_source_excerpt(self):
        narrative=("Lunch included potatoes, carrots, and broccoli. "*200)+"我去年和林舟完成了松桥望远镜项目，当时一起修好了镜片。"
        source=await self.turn(narrative)
        query="还记得松桥望远镜项目修镜片的事情吗"
        self.repository.memory_encoder=self.encoder
        found=recalled_history(self.repository,owner_id=self.owner,query=query,current_event=self.current(query,730),
            recent=(),explicit=True,timezone_name="America/Chicago")
        recalled=next(t for t in found if t.event_id==source.user_event_id)
        self.assertIn("松桥望远镜",recalled.content_text)
        self.assertIn("Exact excerpt from preserved Event",recalled.content_text)
        self.assertTrue(any(ref.startswith("context-selector/personal-event-search-indexed-v1/") for ref in recalled.source_refs))
        self.assertLess(len(recalled.content_text),800)
        original=self.repository.event_by_id(owner_id=self.owner,event_id=source.user_event_id)
        self.assertEqual(original.payload.content_parts[0].text,narrative)

    async def test_private_default_cloud_flag_still_uses_only_the_local_recall_branch(self):
        local=InteractionService(owner_id=self.owner,identity=self.identity,repository=self.repository,
            context_builder=ContextBuilder(max_input_tokens=12000,reserved_output_tokens=256),
            router=Stage1Router(),provider=DeterministicLocalProvider(),
            retrieval_service=RetrievalService(repository=self.repository,embedding_provider=DeterministicEmbeddingProvider()))
        source=await local.interact(InteractionCommand(message="我和林舟修好了松桥望远镜项目的镜片。",
            privacy_class=PrivacyClass.PRIVATE,idempotency_key=str(uuid4())))
        query="还记得松桥望远镜项目修镜片吗"
        policy=DataPolicy.owner_default(PrivacyClass.PRIVATE)
        self.assertTrue(policy.cloud_eligible)
        current=self.current(query,730).model_copy(update={"data_policy":policy})
        self.repository.memory_encoder=self.encoder
        found=recalled_history(self.repository,owner_id=self.owner,query=query,current_event=current,
            recent=(),explicit=True,timezone_name="America/Chicago")
        self.assertIn(source.user_event_id,{item.event_id for item in found})
        normal=current.model_copy(update={"data_policy":DataPolicy.owner_default(PrivacyClass.NORMAL)})
        self.assertEqual(recalled_history(self.repository,owner_id=self.owner,query=query,current_event=normal,
            recent=(),explicit=True,timezone_name="America/Chicago"),())

    async def test_pronoun_reference_activates_recall_through_actual_interaction_service(self):
        await self.turn("林舟昨天联系我聊松桥望远镜项目。")
        self.repository.memory_encoder=self.encoder
        for query in ("他今天又找我了", "她刚刚又发消息了", "那件事后来怎么样了", "我又想起李老师说的话"):
            with patch("companion.context.recall.recalled_history", wraps=recalled_history) as recall:
                result=await self.turn(query)
            self.assertIsNotNone(result.assistant_event_id)
            self.assertTrue(recall.called)
            self.assertTrue(recall.call_args.kwargs["explicit"])
