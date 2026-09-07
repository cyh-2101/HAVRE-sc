"""Temporal, relevance and correction regressions on the real PostgreSQL path."""
from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from companion.application import InteractionCommand, InteractionService
from companion.context import ContextBuilder
from companion.feedback.service import FeedbackService
from companion.feedback.models import FeedbackRating
from companion.identity import IdentityLoader
from companion.memory.embedding import DeterministicEmbeddingProvider
from companion.memory.extractor import DeterministicEpisodicExtractor
from companion.memory.models import MemoryRevision
from companion.memory.service import MemoryService, MemoryWorker
from companion.persistence import PostgresRepository, apply_migrations
from companion.policy import PrivacyClass
from companion.product.diary_intelligence import DiaryIntelligenceService, DiaryMemoryUpdate
from mlsys.serving import DeterministicLocalProvider, Stage1Router

ROOT = Path(__file__).resolve().parents[1]
DATABASE = os.getenv("HAVRE_TEST_DATABASE_URL")


@unittest.skipUnless(DATABASE, "HAVRE_TEST_DATABASE_URL is required")
class PersonalContextPersistenceTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        apply_migrations(DATABASE, ROOT / "db/migrations")
        cls.repository = PostgresRepository(DATABASE)
        cls.repository.open()
        cls.identity = IdentityLoader(ROOT / "identity").load()

    @classmethod
    def tearDownClass(cls):
        cls.repository.close()

    async def asyncSetUp(self):
        self.owner = uuid4()
        self.repository.memory_encoder = None
        self.repository.bootstrap_owner_and_identity(owner_id=self.owner, identity=self.identity)
        self.embedding = DeterministicEmbeddingProvider()
        self.memory = MemoryService(repository=self.repository, embedding_provider=self.embedding)
        self.service = InteractionService(
            owner_id=self.owner, identity=self.identity, repository=self.repository,
            context_builder=ContextBuilder(max_input_tokens=8192, reserved_output_tokens=256),
            router=Stage1Router(), provider=DeterministicLocalProvider(),
        )
        self.feedback = FeedbackService(repository=self.repository, owner_id=self.owner)
        self.diary = DiaryIntelligenceService(repository=self.repository, owner_id=self.owner,
            provider=None, embedding_provider=self.embedding)

    async def say(self, message):
        return await self.service.interact(InteractionCommand(
            message=message, channel="api", privacy_class=PrivacyClass.NORMAL,
            idempotency_key=str(uuid4()),
        ))

    def select(self, query, as_of=None):
        return self.repository.select_personal_context(owner_id=self.owner,
            query_text=query, maximum_privacy_class=PrivacyClass.NORMAL, as_of=as_of)

    async def remembered(self, message, valid_from=None, valid_to=None):
        source = await self.say(message)
        MemoryWorker(repository=self.repository, extractor=DeterministicEpisodicExtractor(),
            owner_id=self.owner).run_once()
        candidate = next(c for c in self.memory.list_candidates(owner_id=self.owner)
                         if c["source_event_id"] == source.user_event_id)
        factory = lambda **values: MemoryRevision(**{**values, "valid_from": valid_from, "valid_to": valid_to})
        with patch("companion.persistence.postgres.MemoryRevision", side_effect=factory):
            memory = self.memory.accept_candidate(owner_id=self.owner,
                candidate_id=candidate["candidate_id"], reason="synthetic owner review")
        return source, memory

    async def test_future_instructions_feedback_preferences_and_episode_are_excluded(self):
        cutoff = datetime.now(UTC)
        source = await self.say("不要再说辛苦啦。今天我在图书馆研究火星。")
        self.feedback.set_preference(response_length="brief", reason="synthetic preference")
        self.feedback.save(assistant_event_id=source.assistant_event_id,
            rating=FeedbackRating.UNHELPFUL, reason_codes=(), reason_text="Please be specific.",
            expected_revision=0)
        self.feedback.close_episode(session_id=source.session_id,
            boundary_reason="owner_started_new_conversation")
        selected = self.select("remember 火星", as_of=cutoff)
        self.assertFalse(any(item.section_type in {"owner_wording_correction",
            "owner_response_instruction", "communication_preference", "episodic_memory"}
            for item in selected))

    async def test_old_wording_correction_expires_relative_to_requested_time(self):
        await self.say("不要再说辛苦啦。")
        self.assertTrue(any(item.section_type == "owner_wording_correction" for item in self.select("hello")))
        self.assertFalse(any(item.section_type == "owner_wording_correction"
            for item in self.select("hello", datetime.now(UTC) + timedelta(days=31))))

    async def test_explicit_recall_does_not_admit_unrelated_episode(self):
        source = await self.say("A microscope reveals a beautiful crystalline mineral.")
        self.feedback.close_episode(session_id=source.session_id,
            boundary_reason="owner_started_new_conversation")
        self.assertFalse(any(item.section_type == "episodic_memory"
            for item in self.select("remember swimming competition")))
        self.assertTrue(any(item.section_type == "episodic_memory"
            for item in self.select("remember crystalline mineral")))

    async def test_episode_rank_is_by_relevance_with_one_encoder_batch(self):
        episodes = []
        for topic in ("oldstrongtopic", "newmiddletopic", "newweaktopic", "newweakesttopic"):
            source = await self.say("I am studying " + topic + " for a presentation.")
            episodes.append(self.feedback.close_episode(session_id=source.session_id,
                boundary_reason="owner_started_new_conversation"))
        class CountingEncoder:
            calls = []
            def embed_many(self, texts):
                self.calls.append(tuple(texts))
                values = []
                for text in texts:
                    score = next((score for token, score in (
                        ("oldstrongtopic", .95), ("newmiddletopic", .75),
                        ("newweaktopic", .65), ("newweakesttopic", .50)) if token in text), 1.0)
                    values.append((score, (1.0 - score * score) ** .5))
                return values
        encoder = CountingEncoder()
        self.repository.memory_encoder = encoder
        selected = [item for item in self.select("presentation") if item.section_type == "episodic_memory"]
        self.assertEqual(len(encoder.calls), 1)
        self.assertEqual(encoder.calls[0].count("presentation"), 1)
        self.assertEqual(len(selected), 3)
        self.assertIn(str(episodes[0]["episode_id"]), selected[0].section_id)
        self.assertFalse(any(str(episodes[3]["episode_id"]) in item.section_id for item in selected))

    async def test_understanding_excludes_expired_and_not_yet_valid_memory(self):
        instant = datetime.now(UTC)
        _, expired = await self.remembered("我长期喜欢在公园散步", valid_to=instant-timedelta(days=1))
        _, future = await self.remembered("我长期喜欢在午后读书", valid_from=instant+timedelta(days=1))
        _, active = await self.remembered("我长期喜欢在周末游泳")
        rows = self.diary._review_memories(local_date=datetime.now(UTC).date(),
            timezone_name="UTC")
        ids = {row["memory_id"] for row in rows}
        self.assertNotIn(expired.memory_id, ids)
        self.assertNotIn(future.memory_id, ids)
        self.assertIn(active.memory_id, ids)

    async def test_same_old_source_cannot_recreate_owner_corrected_statement(self):
        source, memory = await self.remembered("我长期喜欢在公园散步")
        self.memory.correct(owner_id=self.owner, memory_id=memory.memory_id,
            content_text="我实际偏好室内运动。", reason="synthetic owner correction")
        update = DiaryMemoryUpdate(source_event_id=source.user_event_id,
            source_quote="我长期喜欢在公园散步", statement=memory.content_text)
        with self.repository.pool.connection() as connection, connection.transaction():
            with patch.object(self.diary, "_source_row", side_effect=AssertionError("replay escaped correction guard")):
                self.diary._insert_memory_update(connection, uuid4(), update)
                paraphrase = update.model_copy(update={
                    "source_quote": "喜欢在公园散步", "statement": "我偏好经常去公园散步"})
                self.diary._insert_memory_update(connection, uuid4(), paraphrase)
        self.assertEqual(len(self.memory.list_active(owner_id=self.owner)), 1)
        # A genuinely later statement reaches normal source validation. This
        # guard cannot silently turn one correction into a permanent belief ban.
        later = await self.say("我现在又想长期在公园散步了。")
        fresh = update.model_copy(update={"source_event_id": later.user_event_id})
        with self.repository.pool.connection() as connection, connection.transaction():
            with patch.object(self.diary, "_source_row", side_effect=LookupError("fresh source validation")):
                with self.assertRaisesRegex(LookupError, "fresh source validation"):
                    self.diary._insert_memory_update(connection, uuid4(), fresh)
