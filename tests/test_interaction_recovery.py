from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import json
import os
import threading
from pathlib import Path
import unittest
from uuid import uuid4

import anyio

from companion.application import InteractionCommand, InteractionService
from companion.context import ContextBuilder
from companion.commitments.service import CommitmentBroker
from companion.identity import IdentityLoader
from companion.persistence import PostgresRepository, apply_migrations
from mlsys.serving import DeterministicLocalProvider, Stage1Router
from companion.application import InferenceTimeoutError
from services.api.interaction_tasks import InteractionTasks
from services.api.app import create_app
from services.api.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
DATABASE = os.getenv('HAVRE_TEST_DATABASE_URL')


class BlockingProvider(DeterministicLocalProvider):
    def __init__(self):
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def stream(self, request):
        self.entered.set()
        await self.release.wait()
        async for item in super().stream(request):
            yield item


@unittest.skipUnless(DATABASE, 'HAVRE_TEST_DATABASE_URL is required')
class InteractionRecoveryTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        apply_migrations(DATABASE, ROOT/'db/migrations')
        cls.repository = PostgresRepository(DATABASE)
        cls.repository.open()
        cls.identity = IdentityLoader(ROOT/'identity').load()

    @classmethod
    def tearDownClass(cls):
        cls.repository.close()

    async def asyncSetUp(self):
        self.owner = uuid4()
        self.repository.bootstrap_owner_and_identity(owner_id=self.owner, identity=self.identity)
        self.provider = BlockingProvider()
        self.broker = CommitmentBroker(repository=self.repository, owner_id=self.owner)
        self.service = InteractionService(owner_id=self.owner, identity=self.identity,
            repository=self.repository, context_builder=ContextBuilder(max_input_tokens=8192,reserved_output_tokens=256),
            router=Stage1Router(), provider=self.provider, commitment_broker=self.broker)
        self.command = InteractionCommand(message='Synthetic message for disconnect recovery.',channel='web',idempotency_key=str(uuid4()))

    def request_row(self):
        with self.repository.pool.connection() as c:
            return c.execute('select * from havre.interaction_requests where owner_id=%s and idempotency_key=%s',
                (self.owner,self.command.idempotency_key)).fetchone()

    async def test_level_cancellation_does_not_leave_processing(self):
        scopes=[]
        async def connection_scope():
            with anyio.CancelScope() as scope:
                scopes.append(scope)
                await self.service.interact(self.command)
        task=asyncio.create_task(connection_scope())
        await asyncio.wait_for(self.provider.entered.wait(),5)
        scopes[0].cancel()
        await asyncio.wait_for(task,5)
        self.assertEqual(self.request_row()['status'],'failed')

    async def test_cancellation_while_starting_chat_lease_drains_and_releases(self):
        entered, release = threading.Event(), threading.Event()
        original = self.broker.begin_interaction_activity
        captured = []
        def delayed_start(*, request_id):
            captured.append(request_id)
            entered.set()
            if not release.wait(5):
                raise RuntimeError('synthetic lease timeout')
            return original(request_id=request_id)
        self.broker.begin_interaction_activity = delayed_start
        task = asyncio.create_task(self.service.interact(self.command))
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait, 5))
            task.cancel()
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, 5)
            with self.repository.pool.connection() as c:
                lease = c.execute('select ended_at from havre.interaction_activity_leases where owner_id=%s and request_id=%s', (self.owner,captured[0])).fetchone()
            self.assertIsNotNone(lease['ended_at'])
            self.assertIsNone(self.request_row())
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)

    async def test_disconnected_viewer_does_not_cancel_owned_reply(self):
        manager = InteractionTasks()
        scopes = []
        async def viewer():
            with anyio.CancelScope() as scope:
                scopes.append(scope)
                await manager.run(self.service, self.command)
        task = asyncio.create_task(viewer())
        try:
            await asyncio.wait_for(self.provider.entered.wait(), 5)
            scopes[0].cancel()
            await asyncio.wait_for(task, 5)
            self.assertEqual(self.request_row()['status'], 'processing')
            owned = tuple(manager.tasks)
            self.assertEqual(len(owned), 1)
            self.provider.release.set()
            await asyncio.wait_for(asyncio.gather(*owned), 5)
            row = self.request_row()
            self.assertEqual(row['status'], 'completed')
            self.assertIsNotNone(row['assistant_event_id'])
            with self.repository.pool.connection() as c:
                count = c.execute("select count(*) as n from havre.events where owner_id=%s and request_id=%s and event_type='ASSISTANT_MESSAGE'", (self.owner, row['request_id'])).fetchone()['n']
            self.assertEqual(count, 1)
        finally:
            await manager.aclose()

    async def test_deadline_finishes_request_and_drains_task(self):
        manager = InteractionTasks(timeout_seconds=0.25)
        try:
            with self.assertRaises(InferenceTimeoutError):
                await asyncio.wait_for(manager.run(self.service, self.command), 5)
            self.assertEqual(self.request_row()['status'], 'failed')
            self.assertFalse(manager.tasks)
        finally:
            await manager.aclose()

    async def test_shutdown_finishes_request(self):
        manager = InteractionTasks()
        viewer = asyncio.create_task(manager.run(self.service, self.command))
        await asyncio.wait_for(self.provider.entered.wait(), 5)
        await asyncio.wait_for(manager.aclose(), 5)
        with self.assertRaises(asyncio.CancelledError):
            await viewer
        self.assertEqual(self.request_row()['status'], 'failed')
        self.assertFalse(manager.tasks)

    async def test_expiry_preserves_source_and_rejects_late_completion(self):
        task = asyncio.create_task(self.service.interact(self.command))
        await asyncio.wait_for(self.provider.entered.wait(), 5)
        before = self.request_row()
        cutoff = datetime.now(UTC) + timedelta(minutes=6)
        recover = self.repository.recover_expired_interactions
        try:
            self.assertEqual(recover(owner_id=uuid4(), cutoff=cutoff), [])
            self.assertEqual(recover(owner_id=self.owner, cutoff=datetime.now(UTC)-timedelta(minutes=6)), [])
            with self.repository.pool.connection() as c, c.transaction():
                c.execute('select request_id from havre.interaction_requests where owner_id=%s and request_id=%s for update', (self.owner, before['request_id']))
                self.assertEqual(recover(owner_id=self.owner, cutoff=cutoff), [])
            self.assertEqual(recover(owner_id=self.owner, cutoff=cutoff), [before['request_id']])
            self.assertEqual(recover(owner_id=self.owner, cutoff=cutoff), [])
            after = self.request_row()
            self.assertEqual(after['status'], 'failed')
            self.assertEqual(after['error_code'], 'interaction_expired')
            self.assertEqual(after['user_event_id'], before['user_event_id'])
            with self.repository.pool.connection() as c:
                events = c.execute('select * from havre.events where owner_id=%s and request_id=%s', (self.owner, before['request_id'])).fetchall()
                lease = c.execute('select ended_at from havre.interaction_activity_leases where owner_id=%s and request_id=%s', (self.owner, before['request_id'])).fetchone()
            self.assertIsNotNone(lease['ended_at'])
            source = next(e for e in events if e['event_type']=='USER_MESSAGE')
            failure = next(e for e in events if e['event_type']=='INTERACTION_FAILED')
            self.assertEqual(source['payload']['content_parts'][0]['text'], self.command.message)
            self.assertEqual(failure['causation_event_id'], source['event_id'])
            self.assertEqual(failure['trace_id'], source['trace_id'])
            for key in ('privacy_class', 'memory_eligible', 'cloud_eligible', 'training_eligible', 'policy_revision_id'):
                self.assertEqual(failure[key], source[key])
            self.provider.release.set()
            with self.assertRaises(RuntimeError):
                await asyncio.wait_for(task, 5)
            self.assertIsNone(self.request_row()['assistant_event_id'])
            self.assertEqual(self.request_row()['failure_event_id'], after['failure_event_id'])
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def test_expiry_never_changes_completed_request(self):
        self.provider.release.set()
        await self.service.interact(self.command)
        before = self.request_row()
        self.assertEqual(self.repository.recover_expired_interactions(owner_id=self.owner,
            cutoff=datetime.now(UTC)+timedelta(minutes=6)), [])
        self.assertEqual(self.request_row(), before)

    async def test_real_stream_endpoint_survives_asgi_disconnect(self):
        settings = Settings(database_url=DATABASE, owner_id=self.owner,
            identity_root=ROOT/'identity', provider_id='deterministic-local',
            self_hosted_base_url='http://127.0.0.1:1',
            self_hosted_model_manifest=ROOT/'README.md',
            self_hosted_engine_manifest=ROOT/'README.md', context_token_budget=8192,
            reserved_output_tokens=256, inference_timeout_ms=10000,
            require_owner_api_token=False, enable_erasure_ledger=False)
        app = create_app(settings)
        body_sent = False
        async def receive():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {'type':'http.request','body':json.dumps({'message':self.command.message}).encode(),'more_body':False}
            await self.provider.entered.wait()
            return {'type':'http.disconnect'}
        sent = []
        async def send(message):
            sent.append(message)
        scope = {'type':'http','asgi':{'version':'3.0','spec_version':'2.3'},
            'method':'POST','scheme':'http','path':'/v1/interactions/stream',
            'raw_path':b'/v1/interactions/stream','query_string':b'',
            'root_path':'','http_version':'1.1','server':('127.0.0.1',8765),
            'client':('127.0.0.1',54321),
            'headers':[(b'host',b'127.0.0.1:8765'),(b'content-type',b'application/json'),
                (b'idempotency-key',self.command.idempotency_key.encode())]}
        async with app.router.lifespan_context(app):
            app.state.runtime.service = self.service
            await asyncio.wait_for(app(scope, receive, send), 5)
            self.assertEqual(sent[0]['status'], 200)
            self.assertEqual(self.request_row()['status'], 'processing')
            owned = tuple(app.state.interaction_tasks.tasks)
            self.assertEqual(len(owned), 1)
            self.provider.release.set()
            await asyncio.wait_for(asyncio.gather(*owned), 5)
            self.assertEqual(self.request_row()['status'], 'completed')
