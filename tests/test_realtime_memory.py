from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, date, timedelta
from functools import partial
from unittest.mock import patch

import psycopg

from tests import test_diary_intelligence as diary_tests
from companion.application import InteractionCommand, InteractionService
from companion.context import ContextBuilder
from companion.events import EventEnvelope
from companion.memory.intelligence import RealtimeMemoryService
from companion.policy import PrivacyClass
from companion.product.diary_intelligence import DiaryIntelligenceService
from mlsys.serving import Stage1Router, DeterministicLocalProvider
from mlsys.serving.codex_cli import CodexCliProvider,CODEX_CLI_PROVIDER_ID,CODEX_OWNER_AUTOMATIC_AUTHORIZATION_REF,bind_codex_cli_request


class RealtimeMemoryTests(diary_tests.DiaryIntelligencePostgresTests):
    test_private_exclusion_auto_updates_and_source_erasure_close = None
    test_retryable_schedule_receipt_obeys_persisted_backoff = None

    async def _runner(self,args,stdin,cwd,environment,timeout):
        if stdin and 'HAVRE MEMORY-INTELLIGENCE' in stdin:
            self.memory_prompt=stdin
            if getattr(self,'fail_memory',False):
                raise RuntimeError('synthetic provider failure')
            if getattr(self,'erase_during_generation',None):
                self.repository.erase_source_event_derivatives(owner_id=self.owner,source_event_id=self.erase_during_generation)
            stdin=stdin.replace('HAVRE MEMORY-INTELLIGENCE','HAVRE DIARY-INTELLIGENCE')
        return await super()._runner(args,stdin,cwd,environment,timeout)

    async def asyncSetUp(self):
        await super().asyncSetUp()
        def provider(effort):
            return CodexCliProvider(executable=self.executable,enabled=True,
                explicit_authorization_ref=CODEX_OWNER_AUTOMATIC_AUTHORIZATION_REF,
                reasoning_effort=effort,process_runner=self._runner,
                environment={'PATH':'safe','CODEX_HOME':self.temporary.name})
        self.cloud=InteractionService(owner_id=self.owner,identity=self.identity,repository=self.repository,
            context_builder=ContextBuilder(max_input_tokens=8192,reserved_output_tokens=256),
            router=Stage1Router(approved_cloud_provider_ids=frozenset({CODEX_CLI_PROVIDER_ID})),
            provider=provider('medium'),retrieval_service=self.retrieval,
            request_binders={CODEX_CLI_PROVIDER_ID:partial(bind_codex_cli_request,reasoning_effort='medium')})
        self.diary=DiaryIntelligenceService(repository=self.repository,owner_id=self.owner,
            provider=provider('high'),embedding_provider=self.embedding)
        self.realtime=RealtimeMemoryService(understanding=self.diary,timezone_name='America/Chicago')

    async def say(self,when=None):
        command=InteractionCommand(message='我长期偏好先看结论，再看必要证据。',channel='web',idempotency_key=str(uuid.uuid4()))
        if when is None:
            return await self.cloud.interact(command)
        with patch('companion.application.service.EventEnvelope',side_effect=lambda **kw:EventEnvelope(**{**kw,'recorded_at':when})):
            return await self.cloud.interact(command)

    async def test_completed_chat_immediately_queues_and_high_effort_writes_no_diary(self):
        source=await self.say()
        with self.repository.pool.connection() as c:
            self.assertEqual(c.execute('select status from havre.realtime_memory_jobs where owner_id=%s',(self.owner,)).fetchone()['status'],'pending')
        result=await self.realtime.run_once()
        self.assertEqual(result['status'],'completed')
        self.assertIn('REALTIME MEMORY ONLY',self.memory_prompt)
        self.assertIsNone(await self.realtime.run_once())
        with self.repository.pool.connection() as c:
            row=c.execute('select run_kind,reasoning_effort,window_start_hour from havre.daily_diary_intelligence_runs where owner_id=%s',(self.owner,)).fetchone()
            self.assertEqual(dict(row),{'run_kind':'realtime_memory','reasoning_effort':'high','window_start_hour':5})
            self.assertEqual(c.execute('select count(*) n from havre.daily_diary_entry_heads where owner_id=%s',(self.owner,)).fetchone()['n'],0)
            self.assertEqual(c.execute('select count(*) n from havre.memory_heads where owner_id=%s',(self.owner,)).fetchone()['n'],1)
        self.repository.erase_source_event_derivatives(owner_id=self.owner,source_event_id=source.user_event_id)
        with self.repository.pool.connection() as c:
            for table in ('realtime_memory_jobs','memory_heads','daily_diary_intelligence_runs'):
                self.assertEqual(c.execute(f'select count(*) n from havre.{table} where owner_id=%s',(self.owner,)).fetchone()['n'],0)

    async def test_private_pair_cannot_queue_even_with_direct_sql(self):
        local=InteractionService(owner_id=self.owner,identity=self.identity,repository=self.repository,
            context_builder=ContextBuilder(max_input_tokens=8192,reserved_output_tokens=256),
            router=Stage1Router(),provider=DeterministicLocalProvider(),retrieval_service=self.retrieval)
        turn=await local.interact(InteractionCommand(message='private synthetic story',privacy_class=PrivacyClass.LOCAL_ONLY,idempotency_key=str(uuid.uuid4())))
        self.assertIsNone(await self.realtime.run_once())
        with self.assertRaisesRegex(psycopg.Error,'exact eligible completed GPT pair'):
            with self.repository.pool.connection() as c,c.transaction():
                c.execute('insert into havre.realtime_memory_jobs(owner_id,source_user_event_id,source_assistant_event_id,source_request_id) values(%s,%s,%s,%s)',
                    (self.owner,turn.user_event_id,turn.assistant_event_id,turn.request_id))

    async def test_other_owner_cannot_attach_the_source_pair(self):
        source=await self.say()
        other=uuid.uuid4()
        self.repository.bootstrap_owner_and_identity(owner_id=other,identity=self.identity)
        with self.assertRaisesRegex(psycopg.Error,'exact eligible completed GPT pair'):
            with self.repository.pool.connection() as c,c.transaction():
                c.execute('insert into havre.realtime_memory_jobs(owner_id,source_user_event_id,source_assistant_event_id,source_request_id) values(%s,%s,%s,%s)',
                    (other,source.user_event_id,source.assistant_event_id,source.request_id))

    async def test_concurrent_workers_do_not_duplicate_a_turn(self):
        import asyncio
        await self.say()
        results=await asyncio.gather(self.realtime.run_once(),self.realtime.run_once())
        self.assertEqual(sum(item is not None for item in results),1)

    async def test_failure_backs_off_without_local_fallback_or_duplicate_write(self):
        await self.say()
        self.fail_memory=True
        with self.assertRaises(Exception):
            await self.realtime.run_once()
        self.assertIsNone(await self.realtime.run_once())
        with self.repository.pool.connection() as c:
            row=c.execute('select status,available_at,attempt_count from havre.realtime_memory_jobs where owner_id=%s',(self.owner,)).fetchone()
            self.assertEqual(row['status'],'retryable_failed')
            self.assertEqual(row['attempt_count'],1)
            self.assertGreater(row['available_at'],datetime.now(UTC))
            self.assertEqual(c.execute('select count(*) n from havre.memory_heads where owner_id=%s',(self.owner,)).fetchone()['n'],0)

    async def test_erasure_while_gpt_runs_prevents_late_memory_resurrection(self):
        source=await self.say()
        self.erase_during_generation=source.user_event_id
        self.assertEqual((await self.realtime.run_once())['status'],'lease_lost')
        with self.repository.pool.connection() as c:
            self.assertEqual(c.execute('select count(*) n from havre.memory_heads where owner_id=%s',(self.owner,)).fetchone()['n'],0)

    async def test_diary_includes_next_morning_before_five_not_after(self):
        before=await self.say(datetime(2026,9,4,9,59,tzinfo=UTC))  # Chicago 04:59
        after=await self.say(datetime(2026,9,4,10,0,tzinfo=UTC))   # Chicago 05:00
        entries=self.diary._day_events(local_date=date(2026,9,3),timezone_name='America/Chicago')
        ids={item['event_id'] for item in entries}
        self.assertIn(before.user_event_id,ids)
        self.assertNotIn(after.user_event_id,ids)
        day=await self.diary.sync_day(local_date=date(2026,9,3),timezone_name='America/Chicago')
        self.assertEqual(day['summary_method'],'gpt-owner-five-am-diary-v6')
        self.assertIn(before.user_event_id,{item['event_id'] for item in day['sources']})
