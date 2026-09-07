from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from functools import partial
from uuid import uuid4

import psycopg
from pydantic import ValidationError

from companion.application import InteractionCommand, InteractionService
from companion.context import ContextBuilder, ResponsePlanner
from companion.context.recall import recalled_history
from companion.events import EventEnvelope, TextContentPart, UserMessagePayload
from companion.identity import IdentityLoader
from companion.memory import DeterministicEmbeddingProvider, DeterministicEpisodicExtractor
from companion.memory.lexical import overlap
from companion.memory.semantic import LocalSemanticEmbeddingProvider
from companion.memory.service import MemoryService, MemoryWorker
from companion.persistence import PostgresRepository, apply_migrations
from companion.policy import DataPolicy, PrivacyClass
from mlsys.retrieval.models import RetrievalRequest, RetrievalQuery, RetrievalFilters
from mlsys.retrieval.service import RetrievalService
from mlsys.serving import DeterministicLocalProvider, Stage1Router
from mlsys.serving.codex_cli import (CodexCliProvider, CodexProcessResult,
    CODEX_CLI_PROVIDER_ID, CODEX_OWNER_AUTOMATIC_AUTHORIZATION_REF, bind_codex_cli_request)
from scripts.reindex_memories import reindex

ROOT = Path(__file__).resolve().parents[1]
DATABASE = os.getenv("HAVRE_TEST_DATABASE_URL")


class CapturingProvider(DeterministicLocalProvider):
    async def generate(self, request):
        self.last_request = request
        return await super().generate(request)


class SemanticMemoryUnitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.encoder = LocalSemanticEmbeddingProvider(ROOT / "var/models/memory-minilm-v1")

    def test_chinese_paraphrase_and_unrelated_query(self):
        v = self.encoder.embed_many(["我最近总是睡得很晚", "这几天又熬夜了", "午饭想买西兰花"])
        self.assertGreater(sum(a*b for a,b in zip(v[0],v[1])), .45)
        self.assertLess(sum(a*b for a,b in zip(v[0],v[2])), .20)
        self.assertGreater(overlap("面里有香菜", "我不喜欢吃香菜"), 0)

    def test_substantive_turn_uses_optional_memory_but_acknowledgement_does_not(self):
        planner = ResponsePlanner(semantic_memory=True)
        def plan(text):
            return planner.plan(request_id=uuid4(), trace_id=uuid4().hex, owner_id=uuid4(),
                message=text, source_refs=("event/synthetic",))
        self.assertEqual(plan("今天的面里有香菜").memory_need, "possible")
        self.assertEqual(plan("好呀").memory_need, "none")
        self.assertEqual(plan("你好呀").memory_need, "none")
        self.assertEqual(plan("还记得凌晨那件事吗").memory_need, "required")

    def test_missing_model_fails_without_network_fallback(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(FileNotFoundError):
                LocalSemanticEmbeddingProvider(Path(root))


@unittest.skipUnless(DATABASE, "HAVRE_TEST_DATABASE_URL is required")
class SemanticMemoryPostgresTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        apply_migrations(DATABASE, ROOT / "db/migrations")
        cls.repository = PostgresRepository(DATABASE)
        cls.repository.open()
        cls.identity = IdentityLoader(ROOT / "identity").load()
        cls.encoder = LocalSemanticEmbeddingProvider(ROOT / "var/models/memory-minilm-v1")

    @classmethod
    def tearDownClass(cls):
        cls.repository.close()

    async def asyncSetUp(self):
        self.owner = uuid4()
        self.repository.memory_encoder = None
        self.repository.bootstrap_owner_and_identity(owner_id=self.owner, identity=self.identity)
        self.legacy = DeterministicEmbeddingProvider()
        self.memory = MemoryService(repository=self.repository, embedding_provider=self.legacy)
        self.worker = MemoryWorker(repository=self.repository, extractor=DeterministicEpisodicExtractor(), owner_id=self.owner)
        self.retrieval = RetrievalService(repository=self.repository, embedding_provider=self.legacy)
        self.service = InteractionService(owner_id=self.owner, identity=self.identity, repository=self.repository,
            context_builder=ContextBuilder(max_input_tokens=12000,reserved_output_tokens=256,owner_timezone="America/Chicago"),
            router=Stage1Router(), provider=DeterministicLocalProvider(), retrieval_service=self.retrieval)

    async def memory_for(self, text, privacy=PrivacyClass.NORMAL):
        result = await self.service.interact(InteractionCommand(message=text,privacy_class=privacy,
            channel="api",idempotency_key=str(uuid4())))
        self.worker.run_once()
        candidate = next(c for c in self.memory.list_candidates(owner_id=self.owner) if c["source_event_id"]==result.user_event_id)
        revision = self.memory.accept_candidate(owner_id=self.owner,candidate_id=candidate["candidate_id"],reason="synthetic review")
        return result, revision

    async def test_reindex_preserves_old_vectors_and_recall_reaches_final_context(self):
        _, memory = await self.memory_for("我最近总是睡得很晚")
        self.assertEqual(reindex(self.repository,owner_id=self.owner,encoder=self.encoder),1)
        self.assertEqual(reindex(self.repository,owner_id=self.owner,encoder=self.encoder),0)
        self.repository.memory_encoder=self.encoder
        retrieval=RetrievalService(repository=self.repository,embedding_provider=self.encoder)
        provider=CapturingProvider()
        service=InteractionService(owner_id=self.owner,identity=self.identity,repository=self.repository,
            context_builder=ContextBuilder(max_input_tokens=12000,reserved_output_tokens=256,owner_timezone="America/Chicago"),
            router=Stage1Router(),provider=provider,retrieval_service=retrieval)
        result=await service.interact(InteractionCommand(message="这几天又熬夜了",memory_eligible=False,idempotency_key=str(uuid4())))
        evidence=self.repository.evidence(result.request_id,owner_id=self.owner)
        self.assertEqual(evidence["retrieval_result"]["algorithm_version"],"retrieval-r2-hybrid-v1")
        self.assertTrue(any(str(memory.memory_id) in s["section_id"] for s in evidence["context_pack"]["sections"]))
        self.assertIn("我最近总是睡得很晚",provider.last_request.model_dump_json())
        with self.repository.pool.connection() as c:
            dims=c.execute('select vector_dims(embedding) n from havre.memory_embeddings where owner_id=%s and memory_id=%s order by n',(self.owner,memory.memory_id)).fetchall()
        self.assertEqual([r["n"] for r in dims],[64,384])
        # Check the real SQL constraint, not a different FK/duplicate-key rejection.
        from psycopg import sql
        with self.repository.pool.connection() as c:
            columns=[r["column_name"] for r in c.execute("select column_name from information_schema.columns where table_schema='havre' and table_name='retrieval_results' order by ordinal_position").fetchall()]
        for field in ("minimum_semantic_similarity", "duplicate_similarity_threshold", "duplicate_token_overlap_threshold"):
            with self.assertRaises(psycopg.errors.CheckViolation) as error:
                with self.repository.pool.connection() as c,c.transaction():
                    c.execute(sql.SQL("insert into havre.retrieval_results ({}) select {} from havre.retrieval_results where owner_id=%s and request_id=%s").format(
                        sql.SQL(',').join(map(sql.Identifier,columns)),
                        sql.SQL(',').join(sql.SQL('NULL') if name==field else sql.Identifier(name) for name in columns)),(self.owner,result.request_id))
            self.assertEqual(error.exception.diag.constraint_name,"retrieval_results_hybrid_binding_check")

    async def test_dimension_and_exact_content_hash_are_database_guarded(self):
        _, memory=await self.memory_for("我喜欢在公园散步")
        self.repository.register_embedding_version(self.encoder.version)
        for vector,digest in ((self.legacy.pgvector(self.legacy.embed("bad dimension")),memory.content_hash),
                              (self.encoder.pgvector(self.encoder.embed("公园")),"sha256:"+"0"*64)):
            with self.assertRaises(psycopg.Error):
                with self.repository.pool.connection() as c,c.transaction():
                    c.execute('''insert into havre.memory_embeddings(owner_id,memory_id,memory_revision,
                        embedding_version_id,embedding,content_hash) values(%s,%s,%s,%s,%s::vector,%s)''',
                        (self.owner,memory.memory_id,memory.revision,self.encoder.version.embedding_version_id,vector,digest))

    async def test_private_memory_and_other_owner_do_not_enter_normal_retrieval(self):
        _, private=await self.memory_for("我喜欢在公园散步",PrivacyClass.LOCAL_ONLY)
        reindex(self.repository,owner_id=self.owner,encoder=self.encoder)
        current=await self.service.interact(InteractionCommand(message="还记得散步吗",memory_eligible=False,idempotency_key=str(uuid4())))
        request=RetrievalRequest(owner_id=self.owner,request_id=current.request_id,trace_id=current.trace_id,
            query=RetrievalQuery(text="我喜欢在公园散步",event_id=current.user_event_id),
            filters=RetrievalFilters(allowed_privacy_classes=(PrivacyClass.NORMAL,PrivacyClass.PUBLIC)),algorithm_version="retrieval-r2-hybrid-v1")
        result=RetrievalService(repository=self.repository,embedding_provider=self.encoder).retrieve(request,persist=False)
        self.assertEqual(result.candidates,())
        await self.memory_for("我喜欢在公园散步")
        reindex(self.repository,owner_id=self.owner,encoder=self.encoder)
        other=RetrievalService(repository=self.repository,embedding_provider=self.encoder).retrieve(
            request.model_copy(update={"owner_id":uuid4()}),persist=False)
        self.assertEqual(other.candidates,())

    async def test_source_erasure_removes_both_embedding_versions(self):
        source,memory=await self.memory_for("我习惯晚饭后去公园")
        reindex(self.repository,owner_id=self.owner,encoder=self.encoder)
        self.repository.erase_source_event_derivatives(owner_id=self.owner,source_event_id=source.user_event_id)
        with self.repository.pool.connection() as c:
            self.assertEqual(c.execute('select count(*) n from havre.memory_embeddings where owner_id=%s and memory_id=%s',(self.owner,memory.memory_id)).fetchone()["n"],0)

    async def test_private_narrative_is_only_a_local_review_candidate(self):
        self.repository.register_embedding_version(self.encoder.version)
        self.repository.memory_encoder=self.encoder
        service=InteractionService(owner_id=self.owner,identity=self.identity,repository=self.repository,
            context_builder=ContextBuilder(max_input_tokens=12000,reserved_output_tokens=256),
            router=Stage1Router(),provider=DeterministicLocalProvider(),
            retrieval_service=RetrievalService(repository=self.repository,embedding_provider=self.encoder))
        narrative=("高中时我和朋友参加过一次比赛，当时我很紧张。我记得后来我们一起完成了作品，"
                   "我现在讲这个经历是因为那段时光确实重要。")*4
        result=await service.interact(InteractionCommand(message=narrative,privacy_class=PrivacyClass.LOCAL_ONLY,
            channel="web",idempotency_key=str(uuid4())))
        self.worker.run_once()
        candidates=self.memory.list_candidates(owner_id=self.owner)
        self.assertEqual(len(candidates),1)
        self.assertEqual(candidates[0]['source_event_id'],result.user_event_id)
        self.assertEqual(candidates[0]['content']['kind'],'owner_proposed_experience')
        with self.repository.pool.connection() as c:
            self.assertEqual(c.execute('select count(*) n from havre.memory_heads where owner_id=%s',(self.owner,)).fetchone()['n'],0)
            self.assertEqual(c.execute('select count(*) n from havre.realtime_memory_jobs where owner_id=%s',(self.owner,)).fetchone()['n'],0)

    async def test_explicit_recall_finds_old_gpt_pair_but_excludes_local_and_future(self):
        async def runner(args,stdin,cwd,environment,timeout):
            if args[-1]=="--version": return CodexProcessResult(0,"codex-cli 0.152.0","")
            if args[1:]==("login","status"): return CodexProcessResult(0,"Logged in using ChatGPT","")
            return CodexProcessResult(0,"\n".join((
                json.dumps({"type":"thread.started","thread_id":"synthetic"}),
                json.dumps({"type":"item.completed","item":{"type":"agent_message","text":"Tell me more."}}),
                json.dumps({"type":"turn.completed","usage":{"input_tokens":100,"cached_input_tokens":0,"output_tokens":10,"reasoning_output_tokens":0}}))),"")
        with tempfile.TemporaryDirectory() as folder:
            executable=Path(folder)/"codex.exe";executable.touch()
            provider=CodexCliProvider(executable=executable,enabled=True,
                explicit_authorization_ref=CODEX_OWNER_AUTOMATIC_AUTHORIZATION_REF,
                reasoning_effort="medium",process_runner=runner,environment={"PATH":"safe","CODEX_HOME":folder})
            cloud=InteractionService(owner_id=self.owner,identity=self.identity,repository=self.repository,
                context_builder=ContextBuilder(max_input_tokens=12000,reserved_output_tokens=256),
                router=Stage1Router(approved_cloud_provider_ids=frozenset({CODEX_CLI_PROVIDER_ID})),
                provider=provider,retrieval_service=self.retrieval,
                request_binders={CODEX_CLI_PROVIDER_ID:partial(bind_codex_cli_request,reasoning_effort="medium")})
            old=await cloud.interact(InteractionCommand(message="我昨天帮朋友修好了电脑，我们聊得很开心",idempotency_key=str(uuid4())))
            secret=await self.service.interact(InteractionCommand(message="我帮朋友修电脑的私密细节",privacy_class=PrivacyClass.LOCAL_ONLY,idempotency_key=str(uuid4())))
            current=await cloud.interact(InteractionCommand(message="还记得我帮朋友修电脑的事情吗",idempotency_key=str(uuid4())))
            future=await cloud.interact(InteractionCommand(message="后来朋友又来修电脑",idempotency_key=str(uuid4())))
            self.repository.memory_encoder=self.encoder
            event=self.repository.event_by_id(owner_id=self.owner,event_id=current.user_event_id)
            result=recalled_history(self.repository,owner_id=self.owner,query="还记得我帮朋友修电脑的事情吗",
                current_event=event,recent=(),explicit=True,timezone_name="America/Chicago")
            ids={t.event_id for t in result}
            self.assertIn(old.user_event_id,ids);self.assertIn(old.assistant_event_id,ids)
            self.assertNotIn(secret.user_event_id,ids);self.assertNotIn(future.user_event_id,ids)
            self.assertEqual(recalled_history(self.repository,owner_id=self.owner,query="你好",current_event=event,
                recent=(),explicit=False,timezone_name="America/Chicago"),())

    async def test_nightly_duplicate_and_rejected_statement_is_not_resurrected(self):
        from companion.product.diary_intelligence import DiaryIntelligenceService, DiaryMemoryUpdate
        source,memory=await self.memory_for("我长期喜欢在公园散步")
        self.memory.retract(owner_id=self.owner,memory_id=memory.memory_id,reason="owner withdrawal")
        diary=DiaryIntelligenceService(repository=self.repository,owner_id=self.owner,provider=None,embedding_provider=self.encoder)
        update=DiaryMemoryUpdate(source_event_id=source.user_event_id,source_quote="我长期喜欢在公园散步",
            statement="我长期喜欢在公园散步。",confidence=.9,importance=.5)
        with self.repository.pool.connection() as c,c.transaction():
            diary._insert_memory_update(c,uuid4(),update)
            self.assertEqual(c.execute('select count(*) n from havre.memory_heads where owner_id=%s',(self.owner,)).fetchone()["n"],1)
