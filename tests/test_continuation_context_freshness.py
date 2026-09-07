"""A queued reply must stop using understanding changed through review UI."""
from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from types import SimpleNamespace
from psycopg.rows import dict_row
import psycopg
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

from tests import test_relationship_initiative as fixtures
from companion.application import InteractionCommand, InteractionService
from companion.context import ContextBuilder
from companion.context.models import ContextPack
from companion.context.freshness import source_context_is_current
from companion.evidence import EvidenceRef, EvidenceRelation, EvidenceSourceKind
from companion.memory.extractor import DeterministicEpisodicExtractor
from companion.memory.service import MemoryService, MemoryWorker
from companion.policy import PrivacyClass
from companion.user_model.service import UserModelService
from companion.user_model.models import BeliefType, BeliefTransitionType
from mlsys.serving import DeterministicLocalProvider, Stage1Router


@unittest.skipUnless(os.getenv("HAVRE_TEST_DATABASE_URL"), "HAVRE_TEST_DATABASE_URL is required")
class ContinuationContextFreshnessTests(unittest.IsolatedAsyncioTestCase):
    # Reuse infrastructure without inheriting/rerunning the original test cases.
    setUpClass = classmethod(fixtures.RelationshipInitiativeIntegrationTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.RelationshipInitiativeIntegrationTests.tearDownClass.__func__)
    asyncSetUp = fixtures.RelationshipInitiativeIntegrationTests.asyncSetUp
    _cleanup = fixtures.RelationshipInitiativeIntegrationTests._cleanup
    _cloud_runner = fixtures.RelationshipInitiativeIntegrationTests._cloud_runner
    _continuation_runner = fixtures.RelationshipInitiativeIntegrationTests._continuation_runner
    _turn = fixtures.RelationshipInitiativeIntegrationTests._turn
    _record = fixtures.RelationshipInitiativeIntegrationTests._record
    _lease_for_test = fixtures.RelationshipInitiativeIntegrationTests._lease_for_test

    async def _plan_with_understanding(self, kind="memory"):
        self.repository.memory_encoder = None
        local = InteractionService(owner_id=self.owner, identity=self.identity,
            repository=self.repository, context_builder=ContextBuilder(max_input_tokens=8192,
            reserved_output_tokens=256), router=Stage1Router(), provider=DeterministicLocalProvider())
        source = await local.interact(InteractionCommand(message="I prefer quiet parks for walking",
            channel="api", privacy_class=PrivacyClass.NORMAL, idempotency_key=str(uuid4())))
        memory_service = MemoryService(repository=self.repository,
            embedding_provider=self.retrieval.embedding_provider)
        MemoryWorker(repository=self.repository, extractor=DeterministicEpisodicExtractor(),
            owner_id=self.owner).run_once()
        candidate = next(item for item in memory_service.list_candidates(owner_id=self.owner)
                         if item["source_event_id"] == source.user_event_id)
        memory = memory_service.accept_candidate(owner_id=self.owner,
            candidate_id=candidate["candidate_id"], reason="synthetic owner review")
        belief = None
        if kind == "belief":
            service = UserModelService(repository=self.repository)
            belief = service.propose_from_confirmed_memory(owner_id=self.owner,
                memory_id=memory.memory_id, statement="I prefer quiet parks for walking",
                belief_type=BeliefType.PREFERENCE, confidence=.8, reason="synthetic owner review")
            service.activate(owner_id=self.owner, belief_id=belief.belief_id,
                revision=belief.revision, reason="synthetic acceptance")
        state = None
        if kind == "state":
            instant = datetime.now(UTC)
            state = self.repository.create_current_state_snapshot(owner_id=self.owner,
                summary="Considering a walk in a quiet park", state={"activity":"walk"}, uncertainty=.2,
                estimated_at=instant, expires_at=instant+timedelta(minutes=5),
                evidence=(EvidenceRef(source_kind=EvidenceSourceKind.EVENT,
                    source_id=source.user_event_id, relation=EvidenceRelation.SUPPORTS),))
        message = "We discussed that I prefer quiet parks for walking."
        turn = await self._turn(message)
        pack = self.repository.evidence(turn.request_id, owner_id=self.owner)["context_pack"]
        expected = {"memory":"episodic_memory", "belief":"user_belief", "state":"current_state"}[kind]
        self.assertTrue(any(section["section_type"] == expected for section in pack["sections"]))
        self.assertTrue(source_context_is_current(self.repository, owner_id=self.owner,
            context_pack_id=turn.context_pack_id))
        run_id = self._record(turn, message)
        leased = self._lease_for_test(run_id)
        with patch.object(self.continuation, "_claim", return_value=leased):
            planned = await self.continuation.run_once(worker_id="relationship-test")
        self.assertEqual(planned["status"], "completed")
        return memory_service, memory, belief, state, turn, planned

    def _assert_cancelled_without_visible_reply(self, planned):
        result = self.proactive.run_work_once(worker_id="freshness-delivery-test")
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["error_code"], "personal_context_no_longer_current")
        with self.repository.pool.connection() as connection:
            row = connection.execute("SELECT status,last_error_code FROM havre.proactive_work_items WHERE owner_id=%s AND work_item_id=%s",
                (self.owner, planned["work_item_id"])).fetchone()
            visible = connection.execute("SELECT count(*) n FROM havre.proactive_delivery_attempts WHERE owner_id=%s AND status='delivered'",
                (self.owner,)).fetchone()["n"]
        self.assertEqual(row["status"], "cancelled")
        self.assertEqual(visible, 0)

    async def test_memory_ui_correction_after_enqueue_cancels_delivery(self):
        service, memory, _, _, turn, planned = await self._plan_with_understanding()
        service.correct(owner_id=self.owner, memory_id=memory.memory_id,
            content_text="I prefer lively city streets now", reason="owner correction from Memory review")
        self.assertFalse(source_context_is_current(self.repository, owner_id=self.owner,
            context_pack_id=turn.context_pack_id))
        self._assert_cancelled_without_visible_reply(planned)
        fresh = await self._turn("Earlier I said I prefer lively city streets now.")
        current_pack = self.repository.evidence(fresh.request_id, owner_id=self.owner)["context_pack"]
        self.assertTrue(any(section["section_id"] == f"memory-{memory.memory_id}-2"
                            for section in current_pack["sections"]))
        self.assertTrue(source_context_is_current(self.repository, owner_id=self.owner,
            context_pack_id=fresh.context_pack_id))
        self.assertFalse(source_context_is_current(self.repository, owner_id=uuid4(),
            context_pack_id=fresh.context_pack_id))

    async def test_memory_ui_retraction_after_enqueue_cancels_delivery(self):
        service, memory, _, _, _, planned = await self._plan_with_understanding()
        service.retract(owner_id=self.owner, memory_id=memory.memory_id, reason="owner retraction from Memory review")
        self._assert_cancelled_without_visible_reply(planned)

    async def _plan_with_raw_source(self):
        message = "I prefer quiet parks for walking"
        turn = await self._turn(message)
        pack = self.repository.evidence(turn.request_id, owner_id=self.owner)["context_pack"]
        self.assertFalse(any(ref.startswith("memory/") for section in pack["sections"]
                             for ref in section["source_refs"]))
        run_id = self._record(turn, message)
        leased = self._lease_for_test(run_id)
        with patch.object(self.continuation, "_claim", return_value=leased):
            planned = await self.continuation.run_once(worker_id="relationship-test")
        self.assertEqual(planned["status"], "completed")
        service = MemoryService(repository=self.repository,
            embedding_provider=self.retrieval.embedding_provider)
        MemoryWorker(repository=self.repository, extractor=DeterministicEpisodicExtractor(),
            owner_id=self.owner).run_once()
        candidate = next(item for item in service.list_candidates(owner_id=self.owner)
                         if item["source_event_id"] == turn.user_event_id)
        memory = service.accept_candidate(owner_id=self.owner,
            candidate_id=candidate["candidate_id"], reason="synthetic owner review after enqueue")
        self.assertTrue(source_context_is_current(self.repository, owner_id=self.owner,
            context_pack_id=turn.context_pack_id))
        return service, memory, turn, planned

    async def test_raw_only_snapshot_rejects_owner_correction_created_after_enqueue(self):
        service, memory, turn, planned = await self._plan_with_raw_source()
        service.correct(owner_id=self.owner, memory_id=memory.memory_id,
            content_text="I prefer lively city streets now", reason="owner correction after enqueue")
        self.assertFalse(source_context_is_current(self.repository, owner_id=self.owner,
            context_pack_id=turn.context_pack_id))
        self._assert_cancelled_without_visible_reply(planned)

    async def test_raw_only_snapshot_rejects_owner_retraction_created_after_enqueue(self):
        service, memory, turn, planned = await self._plan_with_raw_source()
        service.retract(owner_id=self.owner, memory_id=memory.memory_id,
            reason="owner retraction after enqueue")
        self.assertFalse(source_context_is_current(self.repository, owner_id=self.owner,
            context_pack_id=turn.context_pack_id))
        self._assert_cancelled_without_visible_reply(planned)

    async def _turn_with_strong_wrapped_sections(self, message, *, session_id=None):
        # Compile and persist a real final pack with the same known wrapper that
        # Manual Strong applies to its selected personal-context identities.
        builder = self.cloud_service.context_builders[self.cloud_service.provider.provider_id]
        original = builder.build
        def wrapped(**kwargs):
            pack = original(**kwargs)
            sections = tuple(section.model_copy(update={
                "section_id": "strong-strong-" + section.section_id})
                if section.section_type in {"episodic_memory", "owner_fact_correction"}
                else section for section in pack.sections)
            return ContextPack(**{**pack.model_dump(), "sections": sections, "content_hash": ""})
        with patch.object(builder, "build", side_effect=wrapped):
            return await self.cloud_service.interact(InteractionCommand(
                message=message, session_id=session_id, privacy_class=PrivacyClass.NORMAL,
                memory_eligible=True, channel="web", idempotency_key=str(uuid4())))

    async def test_strong_wrapper_preserves_corrected_memory_ancestor_identity(self):
        service, memory, _, _, _, _ = await self._plan_with_understanding()
        service.correct(owner_id=self.owner, memory_id=memory.memory_id,
            content_text="I prefer lively city streets now", reason="synthetic correction")
        fresh = await self._turn_with_strong_wrapped_sections("Earlier I said I prefer lively city streets now.")
        pack = self.repository.evidence(fresh.request_id, owner_id=self.owner)["context_pack"]
        section = next(item for item in pack["sections"]
                       if item["section_id"] == f"strong-strong-memory-{memory.memory_id}-2")
        self.assertTrue(any(str(memory.memory_id) in ref and ref.endswith("1")
                            for ref in section["source_refs"]))
        self.assertTrue(source_context_is_current(self.repository, owner_id=self.owner,
            context_pack_id=fresh.context_pack_id))

    async def test_strong_wrapper_preserves_current_owner_retraction_constraint(self):
        service, memory, source, _ = await self._plan_with_raw_source()
        service.retract(owner_id=self.owner, memory_id=memory.memory_id, reason="synthetic withdrawal")
        fresh = await self._turn_with_strong_wrapped_sections("Earlier I said I prefer quiet parks for walking.",
            session_id=source.session_id)
        pack = self.repository.evidence(fresh.request_id, owner_id=self.owner)["context_pack"]
        self.assertTrue(any(item["section_id"] == f"strong-strong-owner-fact-retraction-{memory.memory_id}-2"
                            for item in pack["sections"]))
        self.assertTrue(source_context_is_current(self.repository, owner_id=self.owner,
            context_pack_id=fresh.context_pack_id))

    async def test_belief_rejection_after_enqueue_cancels_delivery(self):
        _, _, belief, _, _, planned = await self._plan_with_understanding("belief")
        UserModelService(repository=self.repository).transition(owner_id=self.owner,
            belief_id=belief.belief_id, revision=belief.revision,
            transition_type=BeliefTransitionType.INVALIDATED, reason="owner rejected this understanding")
        self._assert_cancelled_without_visible_reply(planned)

    async def test_current_state_expiry_after_enqueue_cancels_delivery(self):
        _, _, _, state, _, planned = await self._plan_with_understanding("state")
        with patch("companion.context.freshness.datetime") as clock:
            clock.now.return_value = state.expires_at + timedelta(seconds=1)
            self._assert_cancelled_without_visible_reply(planned)

    async def test_new_current_state_after_enqueue_cancels_delivery(self):
        _, _, _, state, _, planned = await self._plan_with_understanding("state")
        instant = datetime.now(UTC)
        self.repository.create_current_state_snapshot(owner_id=self.owner,
            summary="Already back at home", state={"activity":"home"}, uncertainty=.1,
            estimated_at=instant, expires_at=instant+timedelta(minutes=5), evidence=state.evidence)
        self._assert_cancelled_without_visible_reply(planned)

    async def test_direct_sql_state_insert_waits_for_final_delivery_state_lock(self):
        _, _, _, state, turn, _ = await self._plan_with_understanding("state")
        connected = threading.Event()
        backend = {}
        def direct_insert():
            with psycopg.connect(os.environ["HAVRE_TEST_DATABASE_URL"]) as writer:
                backend["pid"] = writer.execute("SELECT pg_backend_pid()").fetchone()[0]
                writer.execute("SET LOCAL lock_timeout='4s'")
                connected.set()
                try:
                    # A duplicate keeps this a non-mutating probe. Observe the
                    # exact ungranted advisory lock BEFORE its later PK error,
                    # so no other constraint can masquerade as the lock guard.
                    writer.execute("INSERT INTO havre.current_state_snapshots SELECT * FROM havre.current_state_snapshots WHERE owner_id=%s AND state_snapshot_id=%s",
                        (self.owner, state.state_snapshot_id))
                except psycopg.errors.UniqueViolation:
                    return "duplicate_after_lock"
            return "unexpected_insert"
        with ThreadPoolExecutor(max_workers=1) as executor:
            with self.repository.pool.connection() as delivery, delivery.transaction():
                self.assertTrue(source_context_is_current(self.repository, owner_id=self.owner,
                    context_pack_id=turn.context_pack_id, connection=delivery, lock_current=True))
                future = executor.submit(direct_insert)
                self.assertTrue(connected.wait(2))
                waiting = False
                deadline = time.monotonic()+2
                with self.repository.pool.connection() as observer:
                    while time.monotonic()<deadline:
                        waiting = observer.execute("SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid=%s AND locktype='advisory' AND NOT granted) value",
                            (backend["pid"],)).fetchone()["value"]
                        if waiting:
                            break
                        time.sleep(.01)
                self.assertTrue(waiting, "direct State INSERT did not wait on the delivery advisory lock")
                self.assertFalse(future.done())
            self.assertEqual(future.result(timeout=3), "duplicate_after_lock")

    async def test_state_committed_while_delivery_waits_is_seen_after_lock(self):
        _, _, _, state, turn, _ = await self._plan_with_understanding("state")
        connected = threading.Event()
        backend = {}
        def final_gate():
            with psycopg.connect(os.environ["HAVRE_TEST_DATABASE_URL"], row_factory=dict_row) as delivery:
                backend["pid"] = delivery.execute("SELECT pg_backend_pid() pid").fetchone()["pid"]
                delivery.execute("SET LOCAL lock_timeout='4s'")
                connected.set()
                return source_context_is_current(self.repository, owner_id=self.owner,
                    context_pack_id=turn.context_pack_id, connection=delivery, lock_current=True)
        from companion.context.freshness import lock_current_state_scope
        with ThreadPoolExecutor(max_workers=1) as executor:
            with self.repository.pool.connection() as writer, writer.transaction():
                lock_current_state_scope(writer, self.owner)
                future = executor.submit(final_gate)
                self.assertTrue(connected.wait(2))
                waiting = False
                deadline = time.monotonic()+2
                with self.repository.pool.connection() as observer:
                    while time.monotonic()<deadline:
                        waiting = observer.execute("SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid=%s AND locktype='advisory' AND NOT granted) value",
                            (backend["pid"],)).fetchone()["value"]
                        if waiting:
                            break
                        time.sleep(.01)
                self.assertTrue(waiting)
                # Publish a fully valid snapshot in the writer's open transaction,
                # after the delivery call already captured its initial clock.
                instant = datetime.now(UTC)
                with patch.object(self.repository, "pool", SimpleNamespace(connection=lambda: nullcontext(writer))):
                    self.repository.create_current_state_snapshot(owner_id=self.owner,
                        summary="Plans changed after the delayed answer began checking",
                        state={"activity":"home"}, uncertainty=.1, estimated_at=instant,
                        expires_at=instant+timedelta(minutes=5), evidence=state.evidence)
            self.assertFalse(future.result(timeout=3), "final delivery used the pre-wait clock and missed newly published State")
