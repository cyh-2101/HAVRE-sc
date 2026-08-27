from __future__ import annotations

import os
import hashlib
import json
import unittest
import uuid
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from companion.application import InteractionCommand, InteractionService
from companion.consolidation.service import ConsolidationService
from companion.context import ContextBuilder
from companion.evidence import EvidenceRef, EvidenceRelation, EvidenceSourceKind
from companion.events import EventEnvelope, EventType, GoalLifecyclePayload
from companion.goals.models import Goal, GoalStatus, GoalTrack
from companion.goals.service import GoalService
from companion.hashing import canonical_json
from companion.identity import IdentityLoader
from companion.memory import DeterministicEmbeddingProvider
from companion.persistence import PostgresRepository, apply_migrations
from companion.policy import DataPolicy, PrivacyClass
from companion.state.service import CurrentStateService
from companion.user_model.models import BeliefTransitionType, BeliefType
from companion.user_model.service import UserModelService
from mlsys.retrieval.service import RetrievalService
from mlsys.serving import DeterministicLocalProvider, Stage1Router
from scripts.audit_stage4_fk_indexes import audit_stage4_fk_indexes


DATABASE_URL = os.getenv("HAVRE_TEST_DATABASE_URL")
PROJECT_ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(DATABASE_URL, "HAVRE_TEST_DATABASE_URL is required")
class Stage4PostgresIntegrationTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        assert DATABASE_URL is not None
        apply_migrations(DATABASE_URL, PROJECT_ROOT / "db" / "migrations")
        cls.owner_id = uuid.uuid4()
        cls.second_owner_id = uuid.uuid4()
        cls.identity = IdentityLoader(PROJECT_ROOT / "identity").load()
        cls.repository = PostgresRepository(DATABASE_URL)
        cls.repository.open()
        for owner in (cls.owner_id, cls.second_owner_id):
            cls.repository.bootstrap_owner_and_identity(owner_id=owner, identity=cls.identity)
        cls.embedding = DeterministicEmbeddingProvider()
        cls.repository.register_embedding_version(cls.embedding.version)
        cls.retrieval = RetrievalService(
            repository=cls.repository, embedding_provider=cls.embedding
        )
        cls.interactions = InteractionService(
            owner_id=cls.owner_id,
            identity=cls.identity,
            repository=cls.repository,
            context_builder=ContextBuilder(
                max_input_tokens=4096, reserved_output_tokens=256
            ),
            router=Stage1Router(),
            provider=DeterministicLocalProvider(),
            retrieval_service=cls.retrieval,
        )
        cls.second_interactions = InteractionService(
            owner_id=cls.second_owner_id,
            identity=cls.identity,
            repository=cls.repository,
            context_builder=ContextBuilder(
                max_input_tokens=4096, reserved_output_tokens=256
            ),
            router=Stage1Router(),
            provider=DeterministicLocalProvider(),
            retrieval_service=cls.retrieval,
        )
        cls.user_model = UserModelService(repository=cls.repository)
        cls.consolidation = ConsolidationService(
            repository=cls.repository, embedding_provider=cls.embedding
        )
        cls.state = CurrentStateService(repository=cls.repository)
        cls.goals = GoalService(repository=cls.repository)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.repository.close()

    async def _source(
        self,
        text: str,
        *,
        occurred_at: datetime | None = None,
        privacy_class: PrivacyClass = PrivacyClass.NORMAL,
    ):
        return await self.interactions.interact(InteractionCommand(
            message=text,
            privacy_class=privacy_class,
            memory_eligible=True,
            channel="api",
            client_created_at=occurred_at,
            idempotency_key=f"stage4-source-{uuid.uuid4()}",
        ))

    @staticmethod
    def _event_ref(event_id, relation=EvidenceRelation.SUPPORTS):
        return EvidenceRef(
            source_kind=EvidenceSourceKind.EVENT,
            source_id=event_id,
            relation=relation,
        )

    def _assert_projection_guard(
        self,
        sql: str,
        parameters: tuple[object, ...],
        message: str,
    ) -> None:
        with self.repository.pool.connection() as connection:
            with self.assertRaises(
                psycopg.errors.ObjectNotInPrerequisiteState
            ) as captured:
                connection.execute(sql, parameters)
            self.assertEqual(captured.exception.sqlstate, "55000")
            self.assertIn(message, captured.exception.diag.message_primary)
            connection.rollback()

    def _insert_goal_lifecycle_event(
        self,
        *,
        goal_id,
        payload_overrides: dict[str, object] | None = None,
        event_type: EventType = EventType.GOAL_UPDATED,
        causation_event_id=None,
        data_policy: DataPolicy | None = None,
    ) -> EventEnvelope:
        with self.repository.pool.connection() as connection, connection.transaction():
            current = connection.execute(
                """
                SELECT goal.*, event.session_id, event.request_id, event.trace_id
                FROM havre.goals AS goal
                JOIN havre.events AS event
                  ON event.owner_id = goal.owner_id
                 AND event.event_id = goal.last_event_id
                WHERE goal.owner_id = %s AND goal.goal_id = %s
                """,
                (self.owner_id, goal_id),
            ).fetchone()
            assert current is not None
            action = (
                "completed"
                if event_type is EventType.GOAL_COMPLETED
                else "updated"
            )
            payload_values: dict[str, object] = {
                "goal_id": goal_id,
                "goal_revision": current["revision"] + 1,
                "action": action,
                "track": current["track"],
                "title": current["title"],
                "why": current["why"],
                "priority": current["priority"],
                "status": "completed" if action == "completed" else current["status"],
                "next_action": current["next_action"],
                "review_at": current["review_at"],
                "reason": "Direct SQL projection-guard regression fixture",
            }
            payload_values.update(payload_overrides or {})
            event_id = uuid.uuid4()
            event_policy = data_policy or self.repository._policy_from_row(current)
            projection = Goal(
                goal_id=payload_values["goal_id"],
                owner_id=self.owner_id,
                track=payload_values["track"],
                title=payload_values["title"],
                why=payload_values["why"],
                priority=payload_values["priority"],
                status=payload_values["status"],
                next_action=payload_values["next_action"],
                review_at=payload_values["review_at"],
                revision=payload_values["goal_revision"],
                last_event_id=event_id,
                data_policy=event_policy,
                created_at=current["created_at"],
            )
            projection_material = projection.model_dump(
                mode="json", exclude={"content_hash", "created_at", "updated_at"}
            )
            payload_values.update(
                projection_content_hash=projection.content_hash,
                projection_canonical_json=canonical_json(projection_material),
            )
            lifecycle_event = EventEnvelope(
                event_id=event_id,
                event_type=event_type,
                owner_id=self.owner_id,
                session_id=current["session_id"],
                request_id=current["request_id"],
                trace_id=current["trace_id"],
                causation_event_id=(
                    current["last_event_id"]
                    if causation_event_id is None
                    else causation_event_id
                ),
                data_policy=event_policy,
                payload=GoalLifecyclePayload(**payload_values),
            )
            self.repository._insert_event(connection, lifecycle_event)
            return lifecycle_event

    def _insert_raw_goal_lifecycle_event(
        self,
        *,
        goal_id,
        projection_mutator=None,
        projection_serializer=None,
    ) -> dict[str, object]:
        """Insert an adversarial event without any Goal/Pydantic construction."""

        with self.repository.pool.connection() as connection, connection.transaction():
            current = connection.execute(
                """
                SELECT goal.*, event.session_id, event.request_id, event.trace_id
                FROM havre.goals AS goal
                JOIN havre.events AS event
                  ON event.owner_id = goal.owner_id
                 AND event.event_id = goal.last_event_id
                WHERE goal.owner_id = %s AND goal.goal_id = %s
                """,
                (self.owner_id, goal_id),
            ).fetchone()
            assert current is not None
            event_id = uuid.uuid4()
            review_at = current["review_at"]
            review_at_json = (
                None
                if review_at is None
                else review_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
            )
            policy = {
                "schema_version": 1,
                "policy_revision_id": str(current["policy_revision_id"]),
                "privacy_class": current["privacy_class"],
                "memory_eligible": current["memory_eligible"],
                "training_eligible": current["training_eligible"],
                "cloud_eligible": current["cloud_eligible"],
                "policy_version": current["policy_version"],
                "decision_source": current["policy_decision_source"],
                "authorization_ref": current["policy_authorization_ref"],
            }
            projection: dict[str, object] = {
                "schema_version": current["schema_version"],
                "goal_id": str(current["goal_id"]),
                "owner_id": str(current["owner_id"]),
                "track": current["track"],
                "title": current["title"],
                "why": current["why"],
                "priority": current["priority"],
                "status": current["status"],
                "next_action": current["next_action"],
                "review_at": review_at_json,
                "revision": current["revision"] + 1,
                "last_event_id": str(event_id),
                "data_policy": policy,
            }
            if projection_mutator is not None:
                projection_mutator(projection)
            projection_json = (
                canonical_json(projection)
                if projection_serializer is None
                else projection_serializer(projection)
            )
            projection_hash = "sha256:" + hashlib.sha256(
                projection_json.encode("utf-8")
            ).hexdigest()
            payload = {
                "goal_id": str(current["goal_id"]),
                "goal_revision": current["revision"] + 1,
                "action": "updated",
                "track": current["track"],
                "title": current["title"],
                "why": current["why"],
                "priority": current["priority"],
                "status": current["status"],
                "next_action": current["next_action"],
                "review_at": review_at_json,
                "reason": "Raw direct-SQL canonical projection attack fixture",
                "projection_content_hash": projection_hash,
                "projection_canonical_json": projection_json,
            }
            connection.execute(
                """
                INSERT INTO havre.events (
                    event_id, schema_version, event_type, event_version, owner_id,
                    session_id, request_id, trace_id, causation_event_id,
                    privacy_class, memory_eligible, training_eligible,
                    cloud_eligible, policy_version, policy_revision_id,
                    policy_decision_source, policy_authorization_ref, payload,
                    content_hash, recorded_at
                ) VALUES (
                    %s, 1, 'GOAL_UPDATED', 1, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    statement_timestamp()
                )
                """,
                (
                    event_id,
                    self.owner_id,
                    current["session_id"],
                    current["request_id"],
                    current["trace_id"],
                    current["last_event_id"],
                    current["privacy_class"],
                    current["memory_eligible"],
                    current["training_eligible"],
                    current["cloud_eligible"],
                    current["policy_version"],
                    current["policy_revision_id"],
                    current["policy_decision_source"],
                    current["policy_authorization_ref"],
                    Jsonb(payload),
                    "sha256:" + hashlib.sha256(
                        canonical_json(payload).encode("utf-8")
                    ).hexdigest(),
                ),
            )
            return {
                "event_id": event_id,
                "projection_hash": projection_hash,
                "projection_json": projection_json,
            }

    def _insert_raw_goal_created_event(
        self,
        *,
        source_event_id,
        include_projection: bool,
    ) -> dict[str, object]:
        """Insert a raw GOAL_CREATED event without Goal/Pydantic construction."""

        with self.repository.pool.connection() as connection, connection.transaction():
            source = connection.execute(
                """
                SELECT * FROM havre.events
                WHERE owner_id = %s AND event_id = %s
                """,
                (self.owner_id, source_event_id),
            ).fetchone()
            assert source is not None
            goal_id = uuid.uuid4()
            event_id = uuid.uuid4()
            title = "Raw Goal insert-guard fixture"
            why = "Exercise the durable initial projection boundary."
            policy = {
                "schema_version": 1,
                "policy_revision_id": str(source["policy_revision_id"]),
                "privacy_class": source["privacy_class"],
                "memory_eligible": source["memory_eligible"],
                "training_eligible": source["training_eligible"],
                "cloud_eligible": source["cloud_eligible"],
                "policy_version": source["policy_version"],
                "decision_source": source["policy_decision_source"],
                "authorization_ref": source["policy_authorization_ref"],
            }
            projection = {
                "schema_version": 1,
                "goal_id": str(goal_id),
                "owner_id": str(self.owner_id),
                "track": "reality",
                "title": title,
                "why": why,
                "priority": "normal",
                "status": "active",
                "next_action": None,
                "review_at": None,
                "revision": 1,
                "last_event_id": str(event_id),
                "data_policy": policy,
            }
            projection_json = canonical_json(projection)
            projection_hash = "sha256:" + hashlib.sha256(
                projection_json.encode("utf-8")
            ).hexdigest()
            payload: dict[str, object] = {
                "goal_id": str(goal_id),
                "goal_revision": 1,
                "action": "created",
                "track": "reality",
                "title": title,
                "why": why,
                "priority": "normal",
                "status": "active",
                "next_action": None,
                "review_at": None,
                "reason": "Raw direct-SQL Goal insert fixture",
            }
            if include_projection:
                payload.update(
                    projection_content_hash=projection_hash,
                    projection_canonical_json=projection_json,
                )
            connection.execute(
                """
                INSERT INTO havre.events (
                    event_id, schema_version, event_type, event_version, owner_id,
                    session_id, request_id, trace_id, causation_event_id,
                    privacy_class, memory_eligible, training_eligible,
                    cloud_eligible, policy_version, policy_revision_id,
                    policy_decision_source, policy_authorization_ref, payload,
                    content_hash, recorded_at
                ) VALUES (
                    %s, 1, 'GOAL_CREATED', 1, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    statement_timestamp()
                )
                """,
                (
                    event_id,
                    self.owner_id,
                    source["session_id"],
                    source["request_id"],
                    source["trace_id"],
                    source_event_id,
                    source["privacy_class"],
                    source["memory_eligible"],
                    source["training_eligible"],
                    source["cloud_eligible"],
                    source["policy_version"],
                    source["policy_revision_id"],
                    source["policy_decision_source"],
                    source["policy_authorization_ref"],
                    Jsonb(payload),
                    "sha256:" + hashlib.sha256(
                        canonical_json(payload).encode("utf-8")
                    ).hexdigest(),
                ),
            )
            return {
                "goal_id": goal_id,
                "event_id": event_id,
                "title": title,
                "why": why,
                "projection_hash": projection_hash,
            }

    def _insert_raw_stage4_event(
        self,
        *,
        source_event_id,
        event_type: str,
        payload: dict[str, object],
        data_policy: DataPolicy,
    ) -> dict[str, object]:
        """Insert a raw lifecycle event without an EventEnvelope."""

        with self.repository.pool.connection() as connection, connection.transaction():
            source = connection.execute(
                """
                SELECT * FROM havre.events
                WHERE owner_id = %s AND event_id = %s
                """,
                (self.owner_id, source_event_id),
            ).fetchone()
            assert source is not None
            event_id = uuid.uuid4()
            connection.execute(
                """
                INSERT INTO havre.events (
                    event_id, schema_version, event_type, event_version, owner_id,
                    session_id, request_id, trace_id, causation_event_id,
                    privacy_class, memory_eligible, training_eligible,
                    cloud_eligible, policy_version, policy_revision_id,
                    policy_decision_source, policy_authorization_ref, payload,
                    content_hash, recorded_at
                ) VALUES (
                    %s, 1, %s, 1, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, statement_timestamp()
                )
                """,
                (
                    event_id,
                    event_type,
                    self.owner_id,
                    source["session_id"],
                    source["request_id"],
                    source["trace_id"],
                    source_event_id,
                    data_policy.privacy_class.value,
                    data_policy.memory_eligible,
                    data_policy.training_eligible,
                    data_policy.cloud_eligible,
                    data_policy.policy_version,
                    data_policy.policy_revision_id,
                    data_policy.decision_source,
                    data_policy.authorization_ref,
                    Jsonb(payload),
                    "sha256:" + hashlib.sha256(
                        str(event_id).encode("utf-8")
                    ).hexdigest(),
                ),
            )
            return {
                "event_id": event_id,
                "trace_id": source["trace_id"],
                "recorded_at": source["recorded_at"],
            }

    async def test_belief_replay_counter_evidence_revision_and_owner_isolation(self) -> None:
        first = await self._source(
            "Before one unfamiliar group I anticipated rejection.",
            occurred_at=datetime(2026, 7, 1, tzinfo=UTC),
        )
        counter = await self._source(
            "At another unfamiliar group I felt curious and entered calmly.",
            occurred_at=datetime(2026, 7, 8, tzinfo=UTC),
        )
        later = await self._source(
            "Sometimes I anticipate rejection, but not in every unfamiliar group.",
            occurred_at=datetime(2026, 7, 15, tzinfo=UTC),
        )
        proposed = self.user_model.propose_belief(
            owner_id=self.owner_id,
            belief_key=f"social-anticipation-{uuid.uuid4()}",
            statement="The user may anticipate rejection before unfamiliar groups.",
            belief_type=BeliefType.PATTERN,
            confidence=0.45,
            evidence=(self._event_ref(first.user_event_id),),
            reason="Owner-reviewed qualified proposal",
            valid_from=datetime(2026, 7, 1, tzinfo=UTC),
        )
        self.user_model.activate(
            owner_id=self.owner_id,
            belief_id=proposed.belief_id,
            revision=1,
            reason="Owner accepted the qualified statement",
        )
        with self.repository.pool.connection() as connection:
            before_counter = connection.execute(
                "SELECT clock_timestamp() AS recorded_cutoff"
            ).fetchone()["recorded_cutoff"]
        self.user_model.transition(
            owner_id=self.owner_id,
            belief_id=proposed.belief_id,
            revision=1,
            transition_type=BeliefTransitionType.COUNTER_EVIDENCE_RECORDED,
            reason="Owner retained a counterexample",
            evidence=(self._event_ref(counter.user_event_id, EvidenceRelation.CONTRADICTS),),
        )
        revised = self.user_model.revise(
            owner_id=self.owner_id,
            belief_id=proposed.belief_id,
            expected_revision=1,
            statement="The user sometimes anticipates rejection before unfamiliar groups.",
            confidence=0.60,
            evidence=(
                self._event_ref(later.user_event_id),
                self._event_ref(counter.user_event_id, EvidenceRelation.CONTRADICTS),
            ),
            reason="Owner corrected an overgeneralization",
            valid_from=datetime(2026, 7, 1, tzinfo=UTC),
        )
        self.assertEqual(revised["revision"].revision, 2)
        historical = self.user_model.list_beliefs(
            owner_id=self.owner_id,
            known_as_of=before_counter,
            valid_at=datetime(2026, 7, 5, tzinfo=UTC),
        )
        historical_belief = next(
            item for item in historical
            if item.revision.belief_id == proposed.belief_id
        )
        self.assertEqual(historical_belief.revision.revision, 1)
        current = self.user_model.list_beliefs(
            owner_id=self.owner_id,
            valid_at=datetime(2026, 7, 20, tzinfo=UTC),
        )
        current_belief = next(
            item for item in current
            if item.revision.belief_id == proposed.belief_id
        )
        self.assertEqual(current_belief.revision.revision, 2)
        self.assertEqual(len(current_belief.counter_evidence), 1)
        with self.assertRaises((LookupError, ValueError)):
            self.user_model.propose_belief(
                owner_id=self.second_owner_id,
                belief_key=f"cross-owner-{uuid.uuid4()}",
                statement="Cross-owner evidence must fail.",
                belief_type=BeliefType.FACT,
                confidence=0.5,
                evidence=(self._event_ref(first.user_event_id),),
                reason="Must fail",
            )
        with self.repository.pool.connection() as connection:
            with self.assertRaises(psycopg.Error):
                connection.execute(
                    "UPDATE havre.user_belief_revisions SET statement='mutated' "
                    "WHERE owner_id=%s AND belief_id=%s AND revision=1",
                    (self.owner_id, proposed.belief_id),
                )

    async def test_pattern_proposal_owner_correction_and_retrieval(self) -> None:
        day_one = await self._source(
            "I practiced piano slowly and completed the difficult measure.",
            occurred_at=datetime(2026, 7, 2, tzinfo=UTC),
        )
        day_two = await self._source(
            "A week later, slow piano practice again helped me continue.",
            occurred_at=datetime(2026, 7, 9, tzinfo=UTC),
        )
        with self.assertRaises(ValueError):
            self.consolidation.propose(
                owner_id=self.owner_id,
                memory_class="pattern",
                content_text="One day proves a stable piano pattern.",
                evidence=(self._event_ref(day_one.user_event_id),),
                detector_version="pattern-proposal-distinct-days-v1",
            )
        proposal = self.consolidation.propose(
            owner_id=self.owner_id,
            memory_class="pattern",
            content_text="Slow piano practice always guarantees progress.",
            evidence=(
                self._event_ref(day_one.user_event_id),
                self._event_ref(day_two.user_event_id),
            ),
            detector_version="pattern-proposal-distinct-days-v1",
        )
        memory = self.consolidation.accept(
            owner_id=self.owner_id,
            proposal_id=proposal.proposal_id,
            reason="Owner accepted with qualified wording",
            confidence=0.65,
            corrected_content_text="Slow piano practice has helped on at least two observed occasions.",
        )
        self.assertEqual(memory.memory_class, "pattern")
        self.assertIn("at least two", memory.content_text)
        with self.repository.pool.connection() as connection:
            with self.assertRaises(psycopg.Error):
                connection.execute(
                    "UPDATE havre.consolidation_proposals SET content_text='mutated' "
                    "WHERE owner_id=%s AND proposal_id=%s",
                    (self.owner_id, proposal.proposal_id),
                )
        query = await self.interactions.interact(InteractionCommand(
            message="What has helped my slow piano practice?",
            privacy_class=PrivacyClass.NORMAL,
            memory_eligible=False,
            channel="api",
            idempotency_key=f"stage4-pattern-query-{uuid.uuid4()}",
        ))
        evidence = self.repository.evidence(query.request_id, owner_id=self.owner_id)
        memory_sections = [
            section for section in evidence["context_pack"]["sections"]
            if section["section_type"] == "pattern_memory"
        ]
        self.assertTrue(memory_sections)

    async def test_pattern_and_progress_admission_uses_distinct_utc_dates(self) -> None:
        same_day_one = await self._source(
            "First supporting observation on one UTC date.",
            occurred_at=datetime(2026, 7, 1, 8, tzinfo=UTC),
        )
        same_day_two = await self._source(
            "Second supporting observation on that same UTC date.",
            occurred_at=datetime(2026, 7, 1, 20, tzinfo=UTC),
        )
        same_day_evidence = (
            self._event_ref(same_day_one.user_event_id),
            self._event_ref(same_day_two.user_event_id),
        )
        for memory_class, version in (
            ("pattern", "pattern-proposal-distinct-days-v1"),
            ("progress", "progress-proposal-distinct-days-v1"),
        ):
            with self.assertRaisesRegex(ValueError, "distinct UTC dates"):
                self.consolidation.propose(
                    owner_id=self.owner_id,
                    memory_class=memory_class,
                    content_text=f"Same-day {memory_class} proposal must fail.",
                    evidence=same_day_evidence,
                    detector_version=version,
                )

        instant = datetime(2026, 7, 2, 0, 30, tzinfo=UTC)
        offset_instant = instant.astimezone(timezone(timedelta(hours=-4)))
        instant_one = await self._source(
            "First offset representation.", occurred_at=instant
        )
        instant_two = await self._source(
            "Second offset representation of the same instant.",
            occurred_at=offset_instant,
        )
        for memory_class, version in (
            ("pattern", "pattern-proposal-distinct-days-v1"),
            ("progress", "progress-proposal-distinct-days-v1"),
        ):
            with self.assertRaisesRegex(ValueError, "distinct UTC dates"):
                self.consolidation.propose(
                    owner_id=self.owner_id,
                    memory_class=memory_class,
                    content_text=(
                        "Different offsets cannot manufacture two UTC dates."
                    ),
                    evidence=(
                        self._event_ref(instant_one.user_event_id),
                        self._event_ref(instant_two.user_event_id),
                    ),
                    detector_version=version,
                )

        naive = await self._source(
            "Naive occurrence timestamp fixture.",
            occurred_at=datetime(2026, 7, 3, 12),
        )
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            self.consolidation.propose(
                owner_id=self.owner_id,
                memory_class="progress",
                content_text="Naive timestamps are never machine-local dates.",
                evidence=(
                    self._event_ref(naive.user_event_id),
                    self._event_ref(same_day_one.user_event_id),
                ),
                detector_version="progress-proposal-distinct-days-v1",
            )

        second_utc_day = await self._source(
            "Supporting observation on a genuine second UTC date.",
            occurred_at=datetime(2026, 7, 4, 8, tzinfo=UTC),
        )
        valid_evidence = (
            self._event_ref(same_day_one.user_event_id),
            self._event_ref(second_utc_day.user_event_id),
        )
        for memory_class, version in (
            ("pattern", "pattern-proposal-distinct-days-v1"),
            ("progress", "progress-proposal-distinct-days-v1"),
        ):
            proposal = self.consolidation.propose(
                owner_id=self.owner_id,
                memory_class=memory_class,
                content_text=f"Two-date {memory_class} proposal remains pending.",
                evidence=valid_evidence,
                detector_version=version,
            )
            self.assertEqual(proposal.status.value, "pending")
            with self.repository.pool.connection() as connection:
                persisted = connection.execute(
                    """
                    SELECT status, accepted_memory_id, review_event_id
                    FROM havre.consolidation_proposals
                    WHERE owner_id = %s AND proposal_id = %s
                    """,
                    (self.owner_id, proposal.proposal_id),
                ).fetchone()
            self.assertEqual(persisted["status"], "pending")
            self.assertIsNone(persisted["accepted_memory_id"])
            self.assertIsNone(persisted["review_event_id"])

        for memory_class in ("pattern", "progress"):
            with self.assertRaisesRegex(ValueError, "unsupported"):
                self.consolidation.propose(
                    owner_id=self.owner_id,
                    memory_class=memory_class,
                    content_text="Unknown detector versions fail visibly.",
                    evidence=valid_evidence,
                    detector_version="unsupported-detector-v999",
                )

    async def test_expiring_state_goals_progress_and_interaction_context(self) -> None:
        now = datetime.now(UTC)
        source = await self._source(
            "Today I am tired, and my user-chosen piano goal is ten calm minutes.",
            occurred_at=now,
        )
        source_ref = self._event_ref(source.user_event_id)
        snapshot = self.state.estimate(
            owner_id=self.owner_id,
            summary="Tired today; prefer a smaller piano step.",
            state={"energy": "low"},
            uncertainty=0.2,
            estimated_at=now,
            expires_at=now + timedelta(hours=2),
            evidence=(source_ref,),
        )
        self.assertEqual(
            self.state.current(owner_id=self.owner_id, as_of=now).state_snapshot_id,
            snapshot.state_snapshot_id,
        )
        self.assertIsNone(
            self.state.current(
                owner_id=self.owner_id, as_of=now + timedelta(hours=3)
            )
        )
        goal = self.goals.create(
            owner_id=self.owner_id,
            track=GoalTrack.REALITY,
            title="Practice piano calmly",
            why="Build consistency without turning one tired day into a trait.",
            source_event_id=source.user_event_id,
            next_action="Practice for ten calm minutes.",
        )
        goal = self.goals.update(
            owner_id=self.owner_id,
            goal_id=goal.goal_id,
            expected_revision=1,
            reason="Owner made the next action more specific",
            next_action="Practice one difficult measure for ten calm minutes.",
        )
        self.assertEqual(goal.revision, 2)
        progress = self.goals.record_progress(
            owner_id=self.owner_id,
            goal_id=goal.goal_id,
            expected_goal_revision=2,
            direction="toward",
            summary="Completed ten calm minutes.",
            observed_at=now + timedelta(minutes=20),
            evidence=(source_ref,),
        )
        listed = self.goals.list(owner_id=self.owner_id)
        self.assertEqual(listed[0]["progress_records"][0]["progress_record_id"], str(progress.progress_record_id))
        interaction = await self.interactions.interact(InteractionCommand(
            message="How should I approach piano practice today?",
            privacy_class=PrivacyClass.NORMAL,
            memory_eligible=False,
            channel="api",
            idempotency_key=f"stage4-context-{uuid.uuid4()}",
        ))
        durable = self.repository.evidence(interaction.request_id, owner_id=self.owner_id)
        section_types = {
            item["section_type"] for item in durable["context_pack"]["sections"]
        }
        self.assertIn("goal", section_types)
        self.assertIn("current_state", section_types)
        self.assertEqual(self.repository.audit_provenance_integrity(), [])

    async def test_goal_progress_combines_goal_and_evidence_policies(self) -> None:
        normal_evidence = await self._source(
            "A normal-policy observation used as goal evidence.",
            occurred_at=datetime(2026, 7, 5, tzinfo=UTC),
        )
        for goal_privacy in (PrivacyClass.PRIVATE, PrivacyClass.LOCAL_ONLY):
            goal_source = await self._source(
                f"Create a {goal_privacy.value} goal.",
                occurred_at=datetime(2026, 7, 4, tzinfo=UTC),
                privacy_class=goal_privacy,
            )
            goal = self.goals.create(
                owner_id=self.owner_id,
                track=GoalTrack.REALITY,
                title=f"Policy propagation {goal_privacy.value}",
                why="Verify conservative Goal policy propagation.",
                source_event_id=goal_source.user_event_id,
                next_action="Record one evidence-backed step.",
            )
            progress = self.goals.record_progress(
                owner_id=self.owner_id,
                goal_id=goal.goal_id,
                expected_goal_revision=1,
                direction="toward",
                summary="Recorded one step.",
                observed_at=datetime(2026, 7, 6, tzinfo=UTC),
                evidence=(self._event_ref(normal_evidence.user_event_id),),
            )
            self.assertEqual(progress.data_policy.privacy_class, goal_privacy)
            self.assertFalse(progress.data_policy.training_eligible)
            if goal_privacy is PrivacyClass.LOCAL_ONLY:
                self.assertFalse(progress.data_policy.cloud_eligible)
            with self.repository.pool.connection() as connection:
                event_policy = connection.execute(
                    """
                    SELECT privacy_class, training_eligible, cloud_eligible
                    FROM havre.events
                    WHERE owner_id = %s AND event_id = %s
                    """,
                    (self.owner_id, progress.created_event_id),
                ).fetchone()
            self.assertEqual(event_policy["privacy_class"], goal_privacy.value)
            self.assertFalse(event_policy["training_eligible"])
            if goal_privacy is PrivacyClass.LOCAL_ONLY:
                self.assertFalse(event_policy["cloud_eligible"])

    async def test_belief_head_direct_sql_requires_exact_transition(self) -> None:
        source = await self._source("Belief projection guard source.")
        candidate = self.user_model.propose_belief(
            owner_id=self.owner_id,
            belief_key=f"projection-guard-{uuid.uuid4()}",
            statement="This candidate exists for a database guard regression.",
            belief_type=BeliefType.FACT,
            confidence=0.5,
            evidence=(self._event_ref(source.user_event_id),),
            reason="Create a guarded candidate",
        )
        status_update = """
            UPDATE havre.belief_heads
            SET status = %s, updated_at = statement_timestamp()
            WHERE owner_id = %s AND belief_id = %s
        """
        self._assert_projection_guard(
            status_update,
            ("active", self.owner_id, candidate.belief_id),
            "belief head guard: update lacks a new explicit transition identity",
        )
        self.user_model.activate(
            owner_id=self.owner_id,
            belief_id=candidate.belief_id,
            revision=1,
            reason="Activate through the ordinary transition path",
        )
        self._assert_projection_guard(
            status_update,
            ("candidate", self.owner_id, candidate.belief_id),
            "belief head guard: update lacks a new explicit transition identity",
        )
        self._assert_projection_guard(
            """
            UPDATE havre.belief_heads
            SET current_revision = 3, status = 'active',
                updated_at = statement_timestamp()
            WHERE owner_id = %s AND belief_id = %s
            """,
            (self.owner_id, candidate.belief_id),
            "belief head guard: revision must advance exactly one",
        )

        contradictory = (
            self._event_ref(source.user_event_id, EvidenceRelation.CONTRADICTS),
        )
        first_counter = self.user_model.transition(
            owner_id=self.owner_id,
            belief_id=candidate.belief_id,
            revision=1,
            transition_type=BeliefTransitionType.COUNTER_EVIDENCE_RECORDED,
            reason="Consume the first explicit transition identity",
            evidence=contradictory,
        )
        self.user_model.transition(
            owner_id=self.owner_id,
            belief_id=candidate.belief_id,
            revision=1,
            transition_type=BeliefTransitionType.COUNTER_EVIDENCE_RECORDED,
            reason="Advance the head to a second transition identity",
            evidence=contradictory,
        )
        self._assert_projection_guard(
            """
            UPDATE havre.belief_heads
            SET status = 'active', last_transition_id = %s,
                updated_at = statement_timestamp()
            WHERE owner_id = %s AND belief_id = %s
            """,
            (
                first_counter.belief_transition_id,
                self.owner_id,
                candidate.belief_id,
            ),
            "belief head guard: transition identity was already consumed",
        )

    async def test_raw_belief_insert_requires_lifecycle_and_support(self) -> None:
        source = await self._source("Raw belief insertion guard source.")
        policy = DataPolicy(
            privacy_class=PrivacyClass.NORMAL,
            memory_eligible=True,
            cloud_eligible=True,
            decision_source="derived_conservative",
        )

        def raw_created_event(belief_id):
            return self._insert_raw_stage4_event(
                source_event_id=source.user_event_id,
                event_type="USER_BELIEF_CREATED",
                payload={
                    "belief_id": str(belief_id),
                    "belief_revision": 1,
                    "action": "created",
                    "reason": "Raw direct-SQL belief insertion fixture",
                    "previous_revision": None,
                },
                data_policy=policy,
            )

        insert_revision = """
            INSERT INTO havre.user_belief_revisions (
                owner_id, belief_id, revision, schema_version, belief_key,
                statement, belief_type, confidence, confidence_method,
                initial_status, evidence_occurred_from, evidence_occurred_to,
                learned_at, valid_from, valid_to, supersedes_revision,
                created_event_id, trace_id, privacy_class, memory_eligible,
                training_eligible, cloud_eligible, policy_version,
                policy_revision_id, policy_decision_source,
                policy_authorization_ref, content_hash, created_at
            ) VALUES (
                %s, %s, 1, 1, %s, %s, 'fact', 0.5, 'owner-reviewed-v1',
                %s, %s, %s, %s, NULL, NULL, NULL, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s,
                'sha256:' || repeat('0', 64), statement_timestamp()
            )
        """

        active_belief_id = uuid.uuid4()
        active_event = raw_created_event(active_belief_id)
        active_parameters = (
            self.owner_id,
            active_belief_id,
            f"raw-active-{uuid.uuid4()}",
            "A raw active belief must not bypass candidate review.",
            "active",
            active_event["recorded_at"],
            active_event["recorded_at"],
            active_event["recorded_at"],
            active_event["event_id"],
            active_event["trace_id"],
            policy.privacy_class.value,
            policy.memory_eligible,
            policy.training_eligible,
            policy.cloud_eligible,
            policy.policy_version,
            policy.policy_revision_id,
            policy.decision_source,
            policy.authorization_ref,
        )
        self._assert_projection_guard(
            insert_revision,
            active_parameters,
            "belief revision insert guard: revision 1 must be a candidate",
        )

        candidate_belief_id = uuid.uuid4()
        candidate_event = raw_created_event(candidate_belief_id)
        candidate_key = f"raw-candidate-{uuid.uuid4()}"
        candidate_parameters = (
            self.owner_id,
            candidate_belief_id,
            candidate_key,
            "A candidate without evidence must fail at the durable boundary.",
            "candidate",
            candidate_event["recorded_at"],
            candidate_event["recorded_at"],
            candidate_event["recorded_at"],
            candidate_event["event_id"],
            candidate_event["trace_id"],
            policy.privacy_class.value,
            policy.memory_eligible,
            policy.training_eligible,
            policy.cloud_eligible,
            policy.policy_version,
            policy.policy_revision_id,
            policy.decision_source,
            policy.authorization_ref,
        )
        with self.repository.pool.connection() as connection:
            connection.execute(insert_revision, candidate_parameters)
            connection.execute(
                """
                INSERT INTO havre.belief_heads (
                    owner_id, belief_id, belief_key, current_revision, status
                ) VALUES (%s, %s, %s, 1, 'candidate')
                """,
                (self.owner_id, candidate_belief_id, candidate_key),
            )
            violation = connection.execute(
                """
                SELECT violation_code
                FROM havre.stage4_required_provenance_violations
                WHERE owner_id = %s AND source_id = %s
                """,
                (self.owner_id, candidate_belief_id),
            ).fetchone()
            self.assertEqual(
                violation["violation_code"], "missing_required_belief_support"
            )
            with self.assertRaises(
                psycopg.errors.ObjectNotInPrerequisiteState
            ) as captured:
                connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
            self.assertIn(
                "belief revision requires at least one owner-qualified supporting",
                captured.exception.diag.message_primary,
            )
            connection.rollback()

    async def test_goal_progress_raw_insert_and_nullable_goal_updates(self) -> None:
        source = await self._source("Raw goal progress insertion guard source.")
        review_at = datetime.now(UTC) + timedelta(days=3)
        goal = self.goals.create(
            owner_id=self.owner_id,
            track=GoalTrack.REALITY,
            title="Keep nullable Goal updates exact",
            why="Omission must retain values while explicit null clears them.",
            source_event_id=source.user_event_id,
            next_action="Run one bounded check.",
            review_at=review_at,
        )
        retained = self.goals.update(
            owner_id=self.owner_id,
            goal_id=goal.goal_id,
            expected_revision=1,
            reason="Omit both nullable fields",
            title="Keep omitted nullable Goal fields",
        )
        self.assertEqual(retained.next_action, goal.next_action)
        self.assertEqual(retained.review_at, goal.review_at)
        cleared = self.goals.update(
            owner_id=self.owner_id,
            goal_id=goal.goal_id,
            expected_revision=2,
            reason="Explicitly clear both nullable fields",
            next_action=None,
            review_at=None,
        )
        self.assertIsNone(cleared.next_action)
        self.assertIsNone(cleared.review_at)

        weighted_progress = self.goals.record_progress(
            owner_id=self.owner_id,
            goal_id=goal.goal_id,
            expected_goal_revision=cleared.revision,
            direction="steady",
            summary="Weighted evidence and a non-UTC offset remain canonical.",
            observed_at=datetime.now(timezone(timedelta(hours=8))),
            evidence=(EvidenceRef(
                source_kind=EvidenceSourceKind.EVENT,
                source_id=source.user_event_id,
                relation=EvidenceRelation.SUPPORTS,
                weight=0.75,
            ),),
        )
        self.assertEqual(weighted_progress.observed_at.utcoffset(), timedelta(0))

        policy = DataPolicy(
            privacy_class=PrivacyClass.NORMAL,
            memory_eligible=True,
            cloud_eligible=True,
            decision_source="derived_conservative",
        )
        observed_at = datetime.now(UTC).replace(microsecond=123456)
        evidence = [{
            "source_kind": "event",
            "source_id": str(source.user_event_id),
            "source_revision": None,
            "relation": "supports",
            "weight": None,
        }]

        def progress_event(progress_id, goal_revision):
            return self._insert_raw_stage4_event(
                source_event_id=source.user_event_id,
                event_type="PROGRESS_RECORDED",
                payload={
                    "progress_record_id": str(progress_id),
                    "goal_id": str(goal.goal_id),
                    "goal_revision": goal_revision,
                    "direction": "toward",
                    "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
                },
                data_policy=policy,
            )

        insert_progress = """
            INSERT INTO havre.goal_progress_records (
                progress_record_id, schema_version, owner_id, goal_id,
                goal_revision, direction, summary, observed_at, evidence_snapshot,
                created_event_id, trace_id, privacy_class, memory_eligible,
                training_eligible, cloud_eligible, policy_version,
                policy_revision_id, policy_decision_source,
                policy_authorization_ref, content_hash, created_at
            ) VALUES (
                %s, 1, %s, %s, %s, 'toward', %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                statement_timestamp()
            )
        """

        wrong_revision_id = uuid.uuid4()
        wrong_revision_event = progress_event(wrong_revision_id, 999999)
        wrong_revision_parameters = (
            wrong_revision_id,
            self.owner_id,
            goal.goal_id,
            999999,
            "A nonexistent Goal revision must not be accepted.",
            observed_at,
            Jsonb(evidence),
            wrong_revision_event["event_id"],
            wrong_revision_event["trace_id"],
            policy.privacy_class.value,
            policy.memory_eligible,
            policy.training_eligible,
            policy.cloud_eligible,
            policy.policy_version,
            policy.policy_revision_id,
            policy.decision_source,
            policy.authorization_ref,
            "sha256:" + "0" * 64,
        )
        self._assert_projection_guard(
            insert_progress,
            wrong_revision_parameters,
            "goal progress insert guard: goal revision is not the current durable projection",
        )

        progress_id = uuid.uuid4()
        exact_event = progress_event(progress_id, cleared.revision)
        hash_material = {
            "schema_version": 1,
            "progress_record_id": str(progress_id),
            "owner_id": str(self.owner_id),
            "goal_id": str(goal.goal_id),
            "goal_revision": cleared.revision,
            "direction": "toward",
            "summary": "A valid raw record still requires matching provenance edges.",
            "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
            "evidence": evidence,
            "created_event_id": str(exact_event["event_id"]),
            "trace_id": exact_event["trace_id"],
            "data_policy": policy.model_dump(mode="json"),
        }
        exact_hash = "sha256:" + hashlib.sha256(
            canonical_json(hash_material).encode("utf-8")
        ).hexdigest()
        exact_parameters = (
            progress_id,
            self.owner_id,
            goal.goal_id,
            cleared.revision,
            hash_material["summary"],
            observed_at,
            Jsonb(evidence),
            exact_event["event_id"],
            exact_event["trace_id"],
            policy.privacy_class.value,
            policy.memory_eligible,
            policy.training_eligible,
            policy.cloud_eligible,
            policy.policy_version,
            policy.policy_revision_id,
            policy.decision_source,
            policy.authorization_ref,
            exact_hash,
        )
        forged_hash_parameters = (*exact_parameters[:-1], "sha256:" + "0" * 64)
        self._assert_projection_guard(
            insert_progress,
            forged_hash_parameters,
            "goal progress insert guard: content hash is not bound to the full record",
        )

        with self.repository.pool.connection() as connection:
            connection.execute(insert_progress, exact_parameters)
            violation = connection.execute(
                """
                SELECT violation_code
                FROM havre.stage4_required_provenance_violations
                WHERE owner_id = %s AND source_id = %s
                """,
                (self.owner_id, progress_id),
            ).fetchone()
            self.assertEqual(
                violation["violation_code"],
                "missing_or_mismatched_progress_provenance",
            )
            with self.assertRaises(
                psycopg.errors.ObjectNotInPrerequisiteState
            ) as captured:
                connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
            self.assertIn(
                "goal_progress_record requires exact owner-qualified snapshot provenance",
                captured.exception.diag.message_primary,
            )
            connection.rollback()

    async def test_goal_projection_direct_sql_requires_exact_event(self) -> None:
        source = await self._source(
            "Private goal projection guard source.",
            privacy_class=PrivacyClass.PRIVATE,
        )
        goal = self.goals.create(
            owner_id=self.owner_id,
            track=GoalTrack.REALITY,
            title="Guard the Goal projection",
            why="Direct SQL must not forge a Goal projection.",
            source_event_id=source.user_event_id,
            next_action="Run exact database regressions.",
        )
        base_update = """
            UPDATE havre.goals
            SET revision = %s, last_event_id = %s, content_hash = %s,
                updated_at = statement_timestamp()
            WHERE owner_id = %s AND goal_id = %s
        """
        self._assert_projection_guard(
            base_update,
            (
                2,
                source.user_event_id,
                "sha256:" + "0" * 64,
                self.owner_id,
                goal.goal_id,
            ),
            "goal projection guard: update lacks one exact immutable lifecycle event",
        )

        forged_payload = self._insert_goal_lifecycle_event(
            goal_id=goal.goal_id,
            payload_overrides={"goal_id": uuid.uuid4()},
        )
        self._assert_projection_guard(
            base_update,
            (
                2,
                forged_payload.event_id,
                forged_payload.payload.projection_content_hash,
                self.owner_id,
                goal.goal_id,
            ),
            "goal projection guard: update lacks one exact immutable lifecycle event",
        )

        skipped = self._insert_goal_lifecycle_event(
            goal_id=goal.goal_id,
            payload_overrides={"goal_revision": 3},
        )
        self._assert_projection_guard(
            base_update,
            (
                3,
                skipped.event_id,
                skipped.payload.projection_content_hash,
                self.owner_id,
                goal.goal_id,
            ),
            "goal projection guard: revision must advance exactly one",
        )

        status_event = self._insert_goal_lifecycle_event(goal_id=goal.goal_id)
        self._assert_projection_guard(
            """
            UPDATE havre.goals
            SET status = 'paused', revision = 2, last_event_id = %s,
                content_hash = %s, updated_at = statement_timestamp()
            WHERE owner_id = %s AND goal_id = %s
            """,
            (
                status_event.event_id,
                status_event.payload.projection_content_hash,
                self.owner_id,
                goal.goal_id,
            ),
            "goal projection guard: update lacks one exact immutable lifecycle event",
        )

        content_event = self._insert_goal_lifecycle_event(goal_id=goal.goal_id)
        self._assert_projection_guard(
            """
            UPDATE havre.goals
            SET title = 'Forged title', revision = 2, last_event_id = %s,
                content_hash = %s, updated_at = statement_timestamp()
            WHERE owner_id = %s AND goal_id = %s
            """,
            (
                content_event.event_id,
                content_event.payload.projection_content_hash,
                self.owner_id,
                goal.goal_id,
            ),
            "goal projection guard: update lacks one exact immutable lifecycle event",
        )

        wrong_causation = self._insert_goal_lifecycle_event(
            goal_id=goal.goal_id,
            causation_event_id=source.user_event_id,
        )
        self._assert_projection_guard(
            base_update,
            (
                2,
                wrong_causation.event_id,
                wrong_causation.payload.projection_content_hash,
                self.owner_id,
                goal.goal_id,
            ),
            "goal projection guard: update lacks one exact immutable lifecycle event",
        )

        normal_policy = DataPolicy.owner_default(PrivacyClass.NORMAL)
        weaker_event = self._insert_goal_lifecycle_event(
            goal_id=goal.goal_id,
            data_policy=normal_policy,
        )
        self._assert_projection_guard(
            """
            UPDATE havre.goals
                SET revision = 2, last_event_id = %s,
                    content_hash = %s, updated_at = statement_timestamp(),
                    privacy_class = %s, memory_eligible = %s,
                training_eligible = %s, cloud_eligible = %s,
                policy_version = %s, policy_revision_id = %s,
                policy_decision_source = %s, policy_authorization_ref = %s
            WHERE owner_id = %s AND goal_id = %s
            """,
            (
                weaker_event.event_id,
                weaker_event.payload.projection_content_hash,
                normal_policy.privacy_class.value,
                normal_policy.memory_eligible,
                normal_policy.training_eligible,
                normal_policy.cloud_eligible,
                normal_policy.policy_version,
                normal_policy.policy_revision_id,
                normal_policy.decision_source,
                normal_policy.authorization_ref,
                self.owner_id,
                goal.goal_id,
            ),
            "goal projection guard: DataPolicy cannot become less restrictive",
        )

        valid_event = self._insert_goal_lifecycle_event(goal_id=goal.goal_id)
        self._assert_projection_guard(
            base_update,
            (
                2,
                valid_event.event_id,
                "sha256:" + "f" * 64,
                self.owner_id,
                goal.goal_id,
            ),
            "goal projection guard: content hash is not bound to the full lifecycle projection",
        )

        future_event = self._insert_goal_lifecycle_event(goal_id=goal.goal_id)
        self._assert_projection_guard(
            """
            UPDATE havre.goals
            SET revision = 2, last_event_id = %s, content_hash = %s,
                updated_at = statement_timestamp() + interval '1 day'
            WHERE owner_id = %s AND goal_id = %s
            """,
            (
                future_event.event_id,
                future_event.payload.projection_content_hash,
                self.owner_id,
                goal.goal_id,
            ),
            "goal projection guard: updated_at must equal database statement time",
        )

        mismatched_content_event = self._insert_goal_lifecycle_event(goal_id=goal.goal_id)
        self._assert_projection_guard(
            """
            UPDATE havre.goals
            SET title = 'Hash/content mismatch', revision = 2,
                last_event_id = %s, content_hash = %s,
                updated_at = statement_timestamp()
            WHERE owner_id = %s AND goal_id = %s
            """,
            (
                mismatched_content_event.event_id,
                mismatched_content_event.payload.projection_content_hash,
                self.owner_id,
                goal.goal_id,
            ),
            "goal projection guard: update lacks one exact immutable lifecycle event",
        )

        completed = self.goals.update(
            owner_id=self.owner_id,
            goal_id=goal.goal_id,
            expected_revision=1,
            reason="Complete through the ordinary Goal lifecycle path",
            status=GoalStatus.COMPLETED,
        )
        self.assertEqual(completed.revision, 2)
        self.assertEqual(completed.status, GoalStatus.COMPLETED)
        with self.repository.pool.connection() as connection:
            completion_event = connection.execute(
                """
                SELECT event_type, causation_event_id, payload
                FROM havre.events
                WHERE owner_id = %s AND event_id = %s
                """,
                (self.owner_id, completed.last_event_id),
            ).fetchone()
        self.assertEqual(completion_event["event_type"], "GOAL_COMPLETED")
        self.assertEqual(completion_event["causation_event_id"], goal.last_event_id)
        self.assertEqual(completion_event["payload"]["status"], "completed")

    async def test_goal_projection_direct_sql_insert_requires_exact_created_event(self) -> None:
        source = await self._source("Goal insert guard source event.")
        raw_insert = """
            INSERT INTO havre.goals (
                goal_id, schema_version, owner_id, track, title, why, priority,
                status, next_action, review_at, revision, last_event_id,
                privacy_class, memory_eligible, training_eligible, cloud_eligible,
                policy_version, policy_revision_id, policy_decision_source,
                policy_authorization_ref, content_hash, created_at, updated_at
            )
            SELECT
                %s, 1, event.owner_id, 'reality', %s, %s, 'normal',
                'active', NULL, NULL, %s, %s,
                event.privacy_class, event.memory_eligible,
                event.training_eligible, event.cloud_eligible,
                event.policy_version, event.policy_revision_id,
                event.policy_decision_source, event.policy_authorization_ref,
                %s, statement_timestamp() + interval '30 days',
                statement_timestamp() + interval '30 days'
            FROM havre.events AS event
            WHERE event.owner_id = %s AND event.event_id = %s
        """

        self._assert_projection_guard(
            raw_insert,
            (
                uuid.uuid4(),
                "Forged Goal without lifecycle creation",
                "This reproduces the Product Owner raw SQL probe.",
                999,
                source.user_event_id,
                "sha256:" + "0" * 64,
                self.owner_id,
                source.user_event_id,
            ),
            "goal projection insert guard: initial projection must be active revision 1",
        )

        missing_projection = self._insert_raw_goal_created_event(
            source_event_id=source.user_event_id,
            include_projection=False,
        )
        self._assert_projection_guard(
            raw_insert,
            (
                missing_projection["goal_id"],
                missing_projection["title"],
                missing_projection["why"],
                1,
                missing_projection["event_id"],
                "sha256:" + "0" * 64,
                self.owner_id,
                missing_projection["event_id"],
            ),
            "goal projection insert guard: lifecycle projection material violates the exact contract",
        )

        forged_hash = self._insert_raw_goal_created_event(
            source_event_id=source.user_event_id,
            include_projection=True,
        )
        self._assert_projection_guard(
            raw_insert,
            (
                forged_hash["goal_id"],
                forged_hash["title"],
                forged_hash["why"],
                1,
                forged_hash["event_id"],
                "sha256:" + "0" * 64,
                self.owner_id,
                forged_hash["event_id"],
            ),
            "goal projection insert guard: content hash is not bound to the full lifecycle projection",
        )

        created = self.goals.create(
            owner_id=self.owner_id,
            track=GoalTrack.REALITY,
            title="Create through the guarded Goal path",
            why="The initial projection must be exact and event-backed.",
            source_event_id=source.user_event_id,
        )
        self.assertEqual(created.revision, 1)
        self.assertEqual(created.status, GoalStatus.ACTIVE)
        self.assertEqual(created.created_at, created.updated_at)
        with self.repository.pool.connection() as connection:
            durable = connection.execute(
                """
                SELECT goal.created_at, goal.updated_at, event.event_type,
                       event.causation_event_id, event.payload
                FROM havre.goals AS goal
                JOIN havre.events AS event
                  ON event.owner_id = goal.owner_id
                 AND event.event_id = goal.last_event_id
                WHERE goal.owner_id = %s AND goal.goal_id = %s
                """,
                (self.owner_id, created.goal_id),
            ).fetchone()
        self.assertEqual(durable["created_at"], durable["updated_at"])
        self.assertEqual(durable["event_type"], "GOAL_CREATED")
        self.assertEqual(durable["causation_event_id"], source.user_event_id)
        self.assertEqual(
            durable["payload"]["projection_content_hash"], created.content_hash
        )

    async def test_goal_projection_direct_sql_rejects_noncanonical_material(self) -> None:
        source = await self._source("Canonical Goal guard attack source.")
        goal = self.goals.create(
            owner_id=self.owner_id,
            track=GoalTrack.REALITY,
            title="Reject opaque Goal projection JSON",
            why="Only the exact typed canonical projection may advance the row.",
            source_event_id=source.user_event_id,
            next_action="Run raw SQL attacks.",
            review_at=datetime(2026, 9, 1, 12, 30, 0, 120000, tzinfo=UTC),
        )
        update = """
            UPDATE havre.goals
            SET revision = 2, last_event_id = %s, content_hash = %s,
                updated_at = statement_timestamp()
            WHERE owner_id = %s AND goal_id = %s
        """

        attacks = (
            self._insert_raw_goal_lifecycle_event(
                goal_id=goal.goal_id,
                projection_mutator=lambda material: material.update(
                    {"unexpected_top_level": "self-hashed"}
                ),
            ),
            self._insert_raw_goal_lifecycle_event(
                goal_id=goal.goal_id,
                projection_mutator=lambda material: material["data_policy"].update(
                    {"unexpected_policy_field": "self-hashed"}
                ),
            ),
            self._insert_raw_goal_lifecycle_event(
                goal_id=goal.goal_id,
                projection_serializer=lambda material: json.dumps(
                    material,
                    ensure_ascii=False,
                    sort_keys=False,
                    separators=(", ", ": "),
                ),
            ),
            self._insert_raw_goal_lifecycle_event(
                goal_id=goal.goal_id,
                projection_mutator=lambda material: material.pop("why"),
            ),
            self._insert_raw_goal_lifecycle_event(
                goal_id=goal.goal_id,
                projection_mutator=lambda material: material.update(
                    {"schema_version": 2}
                ),
            ),
        )
        for attack in attacks:
            with self.subTest(projection_json=attack["projection_json"]):
                self._assert_projection_guard(
                    update,
                    (
                        attack["event_id"],
                        attack["projection_hash"],
                        self.owner_id,
                        goal.goal_id,
                    ),
                    "goal projection guard",
                )

        updated = self.goals.update(
            owner_id=self.owner_id,
            goal_id=goal.goal_id,
            expected_revision=1,
            reason="Prove application and database canonical serialization agree",
            title='Canonical "雪" \\ newline\nprojection',
        )
        self.assertEqual(updated.revision, 2)
        self.assertEqual(updated.title, 'Canonical "雪" \\ newline\nprojection')

    async def test_stage4_provenance_foreign_keys_reject_cross_owner_endpoints(self) -> None:
        first_source = await self._source("Owner one observed a piano pattern.")
        second_source = await self.second_interactions.interact(InteractionCommand(
            message="Owner two observed a separate piano pattern.",
            privacy_class=PrivacyClass.NORMAL,
            memory_eligible=True,
            channel="api",
            idempotency_key=f"stage4-owner-two-{uuid.uuid4()}",
        ))
        first = self.user_model.propose_belief(
            owner_id=self.owner_id,
            belief_key=f"owner-one-{uuid.uuid4()}",
            statement="Owner one may benefit from slow piano practice.",
            belief_type=BeliefType.PATTERN,
            confidence=0.5,
            evidence=(self._event_ref(first_source.user_event_id),),
            reason="Owner one reviewed this belief",
        )
        second = self.user_model.propose_belief(
            owner_id=self.second_owner_id,
            belief_key=f"owner-two-{uuid.uuid4()}",
            statement="Owner two may benefit from deliberate piano practice.",
            belief_type=BeliefType.PATTERN,
            confidence=0.5,
            evidence=(self._event_ref(second_source.user_event_id),),
            reason="Owner two reviewed this belief",
        )
        insert = """
            INSERT INTO havre.provenance_edges (
                provenance_edge_id, schema_version, owner_id, source_kind,
                source_id, source_revision, derived_kind, derived_id,
                derived_revision, relation, transform_name, transform_version,
                created_event_id, trace_id
            ) VALUES (%s, 1, %s, 'belief_revision', %s, 1,
                      'belief_revision', %s, 1, 'supports', 'constraint-test',
                      'constraint-test-v1', %s, %s)
        """
        with self.repository.pool.connection() as connection:
            with self.assertRaises(psycopg.Error):
                connection.execute(
                    insert,
                    (
                        uuid.uuid4(), self.second_owner_id, first.belief_id,
                        second.belief_id, second.created_event_id, second.trace_id,
                    ),
                )

        with self.repository.pool.connection() as connection:
            with self.assertRaises(psycopg.Error):
                connection.execute(
                    insert,
                    (
                        uuid.uuid4(), self.owner_id, first.belief_id,
                        second.belief_id, first.created_event_id, first.trace_id,
                    ),
                )

    def test_stage4_fk_catalog_has_covering_indexes(self) -> None:
        assert DATABASE_URL is not None
        self.assertEqual(audit_stage4_fk_indexes(DATABASE_URL), [])

    async def test_source_erasure_closes_stage4_lineage_and_copied_context(self) -> None:
        first_day = await self._source(
            "Slow piano practice helped today, and I want to keep the goal small.",
            occurred_at=datetime(2026, 7, 3, tzinfo=UTC),
        )
        second_day = await self._source(
            "Slow piano practice helped again one week later.",
            occurred_at=datetime(2026, 7, 10, tzinfo=UTC),
        )
        first_ref = self._event_ref(first_day.user_event_id)
        belief = self.user_model.propose_belief(
            owner_id=self.owner_id,
            belief_key=f"erasure-piano-{uuid.uuid4()}",
            statement="Slow piano practice may help the user continue.",
            belief_type=BeliefType.PATTERN,
            confidence=0.55,
            evidence=(first_ref,),
            reason="Owner reviewed the qualified belief",
        )
        self.user_model.activate(
            owner_id=self.owner_id,
            belief_id=belief.belief_id,
            revision=1,
            reason="Owner activated the qualified belief",
        )
        state = self.state.estimate(
            owner_id=self.owner_id,
            summary="Prefer a small piano step today.",
            state={"piano_step": "small"},
            uncertainty=0.2,
            estimated_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            evidence=(first_ref,),
        )
        goal = self.goals.create(
            owner_id=self.owner_id,
            track=GoalTrack.REALITY,
            title="Practice piano slowly",
            why="Build steady practice.",
            source_event_id=first_day.user_event_id,
            next_action="Practice for five minutes.",
        )
        progress = self.goals.record_progress(
            owner_id=self.owner_id,
            goal_id=goal.goal_id,
            expected_goal_revision=1,
            direction="toward",
            summary="Completed five minutes.",
            observed_at=datetime.now(UTC),
            evidence=(first_ref,),
        )
        proposal = self.consolidation.propose(
            owner_id=self.owner_id,
            memory_class="pattern",
            content_text="Slow piano practice has helped on two observed days.",
            evidence=(first_ref, self._event_ref(second_day.user_event_id)),
            detector_version="pattern-proposal-distinct-days-v1",
        )
        memory = self.consolidation.accept(
            owner_id=self.owner_id,
            proposal_id=proposal.proposal_id,
            reason="Owner accepted the bounded pattern",
            confidence=0.6,
        )
        copied = await self.interactions.interact(InteractionCommand(
            message="What should I remember about slow piano practice today?",
            privacy_class=PrivacyClass.NORMAL,
            memory_eligible=False,
            channel="api",
            idempotency_key=f"stage4-erasure-context-{uuid.uuid4()}",
        ))

        counts = self.repository.erase_source_event_derivatives(
            owner_id=self.owner_id,
            source_event_id=first_day.user_event_id,
        )

        self.assertGreaterEqual(counts["belief_revisions"], 1)
        self.assertGreaterEqual(counts["belief_transitions"], 1)
        self.assertEqual(counts["consolidation_proposals"], 1)
        self.assertEqual(counts["current_state_snapshots"], 1)
        self.assertEqual(counts["goal_progress_records"], 1)
        self.assertEqual(counts["goals"], 1)
        self.assertGreaterEqual(counts["memories"], 1)
        with self.repository.pool.connection() as connection:
            raw_source = connection.execute(
                "SELECT 1 FROM havre.events WHERE owner_id=%s AND event_id=%s",
                (self.owner_id, first_day.user_event_id),
            ).fetchone()
            copied_request = connection.execute(
                "SELECT status, context_pack_id FROM havre.interaction_requests "
                "WHERE owner_id=%s AND request_id=%s",
                (self.owner_id, copied.request_id),
            ).fetchone()
            remaining = connection.execute(
                """
                SELECT
                    (SELECT count(*) FROM havre.user_belief_revisions
                     WHERE owner_id=%s AND belief_id=%s) AS beliefs,
                    (SELECT count(*) FROM havre.consolidation_proposals
                     WHERE owner_id=%s AND proposal_id=%s) AS proposals,
                    (SELECT count(*) FROM havre.current_state_snapshots
                     WHERE owner_id=%s AND state_snapshot_id=%s) AS states,
                    (SELECT count(*) FROM havre.goals
                     WHERE owner_id=%s AND goal_id=%s) AS goals,
                    (SELECT count(*) FROM havre.goal_progress_records
                     WHERE owner_id=%s AND progress_record_id=%s) AS progress,
                    (SELECT count(*) FROM havre.memory_revisions
                     WHERE owner_id=%s AND memory_id=%s) AS memories
                """,
                (
                    self.owner_id, belief.belief_id,
                    self.owner_id, proposal.proposal_id,
                    self.owner_id, state.state_snapshot_id,
                    self.owner_id, goal.goal_id,
                    self.owner_id, progress.progress_record_id,
                    self.owner_id, memory.memory_id,
                ),
            ).fetchone()
        self.assertIsNotNone(raw_source)
        self.assertEqual(copied_request["status"], "failed")
        self.assertIsNone(copied_request["context_pack_id"])
        self.assertEqual(set(remaining.values()), {0})
        self.assertEqual(self.repository.audit_provenance_integrity(), [])


if __name__ == "__main__":
    unittest.main()
