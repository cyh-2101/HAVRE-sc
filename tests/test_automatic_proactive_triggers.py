from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
import unittest
import uuid
from types import SimpleNamespace

import psycopg

from companion.events import EventType
from companion.application import InteractionCommand, InteractionService
from companion.context import ContextBuilder
from companion.goals import GoalStatus, GoalTrack
from companion.goals.service import GoalService
from companion.persistence.scenes import ScenePostgresStore
from companion.policy.intervention import (
    AvoidanceAssessment,
    CoercionAssessment,
    DangerAssessment,
    EnergyAssessment,
    GoalAlignment,
    GoalUrgency,
)
from companion.scenes.models import SceneGoal, SceneSituation
from companion.identity import IdentityLoader
from companion.persistence import PostgresRepository, apply_migrations
from companion.persistence.proactive import ProactivePostgresStore
from companion.policy import PrivacyClass
from companion.proactive import ProactivePreferenceRevision
from companion.proactive.models import ProactiveProposal
from companion.proactive.evaluator import (
    EVALUATOR_VERSION,
    ProactiveTriggerEvaluator,
    parse_explicit_reminder,
)
from mlsys.serving import DeterministicLocalProvider, Stage1Router


DATABASE_URL = os.getenv("HAVRE_TEST_DATABASE_URL")
ROOT = Path(__file__).resolve().parents[1]


class ExplicitReminderParserTests(unittest.TestCase):
    def test_explicit_relative_and_calendar_reminders(self) -> None:
        observed = datetime(2026, 8, 27, 15, 0, tzinfo=UTC)
        relative = parse_explicit_reminder(
            "10\u5206\u949f\u540e\u63d0\u9192\u6211\u559d\u6c34",
            observed_at=observed,
            owner_timezone="America/Chicago",
        )
        self.assertIsNotNone(relative)
        assert relative is not None
        self.assertEqual(relative.content, "\u559d\u6c34")
        self.assertEqual(relative.due_at, observed + timedelta(minutes=10))

        calendar = parse_explicit_reminder(
            "\u660e\u5929\u4e0a\u53489\u70b9\u63d0\u9192\u6211\u4ea4\u4f5c\u4e1a",
            observed_at=observed,
            owner_timezone="America/Chicago",
        )
        self.assertIsNotNone(calendar)
        assert calendar is not None
        self.assertEqual(calendar.content, "\u4ea4\u4f5c\u4e1a")
        self.assertEqual(calendar.due_at, datetime(2026, 8, 28, 14, 0, tzinfo=UTC))

    def test_ordinary_conversation_never_becomes_a_reminder(self) -> None:
        observed = datetime.now(UTC)
        for text in (
            "\u6211\u611f\u89c9\u6211\u53c8\u5728\u81ea\u55e8\u4e86\u3002",
            "\u4f60\u8fd8\u8bb0\u5f97\u6211\u6628\u5929\u8bf4\u7684\u5417\uff1f",
            "\u6700\u8fd1\u6709\u70b9\u7d2f\u3002",
            "It has been a while.",
        ):
            with self.subTest(text=text):
                self.assertIsNone(
                    parse_explicit_reminder(
                        text,
                        observed_at=observed,
                        owner_timezone="America/Chicago",
                    )
                )


@unittest.skipUnless(DATABASE_URL, "HAVRE_TEST_DATABASE_URL is required")
class AutomaticProactiveTriggerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        assert DATABASE_URL is not None
        apply_migrations(DATABASE_URL, ROOT / "db" / "migrations")
        cls.identity = IdentityLoader(ROOT / "identity").load()
        cls.repository = PostgresRepository(DATABASE_URL)
        cls.repository.open()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.repository.close()

    def setUp(self) -> None:
        self.owner_id = uuid.uuid4()
        self.repository.bootstrap_owner_and_identity(
            owner_id=self.owner_id,
            identity=self.identity,
        )
        self.store = ProactivePostgresStore(
            repository=self.repository,
            owner_id=self.owner_id,
            identity=self.identity,
        )
        self.preference = ProactivePreferenceRevision(
            owner_id=self.owner_id,
            revision=1,
            global_enabled=True,
            category_permissions={"owner_reminder": "allowed"},
            allowed_channels=("web_inbox",),
            global_budget_per_24h=24,
            category_budget_per_24h={"owner_reminder": 24},
            cooldown_seconds=None,
            generic_push_for_local_only=True,
            authorization_ref="synthetic-automatic-proactive-test",
        )
        self.store.save_preference(self.preference)
        self.evaluator = ProactiveTriggerEvaluator(
            store=self.store,
            owner_timezone="America/Chicago",
        )
        self.service = InteractionService(
            owner_id=self.owner_id,
            identity=self.identity,
            repository=self.repository,
            context_builder=ContextBuilder(
                max_input_tokens=4096,
                reserved_output_tokens=256,
            ),
            router=Stage1Router(),
            provider=DeterministicLocalProvider(),
        )

    def _chat(self, message: str):
        return asyncio.run(
            self.service.interact(
                InteractionCommand(
                    message=message,
                    privacy_class=PrivacyClass.LOCAL_ONLY,
                    channel="web",
                    idempotency_key=f"auto-proactive-chat-{uuid.uuid4()}",
                )
            )
        )

    def test_explicit_reminder_evaluates_executes_once_and_erases_as_one_chain(self) -> None:
        interaction = self._chat(
            "0\u5206\u949f\u540e\u63d0\u9192\u6211\u559d\u6c34"
        )
        evaluation = self.evaluator.run_once()
        self.assertEqual(evaluation["enqueued"], 1)
        work = self.store.run_work_once(worker_id="automatic-proactive-test")
        self.assertIsNotNone(work)
        assert work is not None
        self.assertEqual(work["status"], "succeeded")
        self.assertEqual(self.evaluator.run_once()["evaluated"], 0)
        self.assertIsNone(self.store.run_work_once(worker_id="automatic-proactive-test"))

        with self.repository.pool.connection() as connection:
            row = connection.execute(
                """SELECT trigger.payload->>'source_version' AS source_version,
                          rendering.content_text,event.privacy_class,
                          evaluation.disposition,evaluation.reason_code
                   FROM havre.proactive_trigger_evaluations evaluation
                   JOIN havre.proactive_work_items work
                     ON work.owner_id=evaluation.owner_id
                    AND work.work_item_id=evaluation.work_item_id
                   JOIN havre.proactive_proposals proposal
                     ON proposal.owner_id=work.owner_id
                    AND proposal.proposal_id=work.proposal_id
                   JOIN havre.proactive_triggers trigger
                     ON trigger.owner_id=proposal.owner_id
                    AND trigger.trigger_id=proposal.primary_trigger_id
                   JOIN havre.rendered_proactive_messages rendering
                     ON rendering.owner_id=proposal.owner_id
                    AND rendering.proposal_id=proposal.proposal_id
                   JOIN havre.proactive_inbox_messages inbox
                     ON inbox.owner_id=proposal.owner_id
                    AND inbox.proposal_id=proposal.proposal_id
                   JOIN havre.events event
                     ON event.owner_id=inbox.owner_id
                    AND event.event_id=inbox.assistant_event_id
                   WHERE evaluation.owner_id=%s
                     AND evaluation.source_event_id=%s""",
                (self.owner_id, interaction.user_event_id),
            ).fetchone()
        self.assertEqual(row["source_version"], EVALUATOR_VERSION)
        self.assertEqual(
            row["content_text"],
            "\u63d0\u9192\u4e00\u4e0b\uff1a\u559d\u6c34",
        )
        self.assertEqual(row["privacy_class"], "LOCAL_ONLY")
        self.assertEqual(row["disposition"], "enqueued")
        self.assertEqual(
            row["reason_code"],
            "owner_requested_time_bound_reminder",
        )

        erased = self.repository.erase_source_event_derivatives(
            owner_id=self.owner_id,
            source_event_id=interaction.user_event_id,
        )
        self.assertEqual(erased["proactive_trigger_evaluations"], 1)
        self.assertEqual(erased["proactive_work_items"], 1)
        self.assertEqual(erased["proactive_proposals"], 1)
        self.assertEqual(erased["proactive_inbox_messages"], 1)
        with self.repository.pool.connection() as connection:
            remaining = connection.execute(
                """SELECT count(*) AS value
                   FROM havre.proactive_trigger_evaluations
                   WHERE owner_id=%s AND source_event_id=%s""",
                (self.owner_id, interaction.user_event_id),
            ).fetchone()["value"]
        self.assertEqual(remaining, 0)

    def test_non_reminder_is_recorded_as_ignored_without_work(self) -> None:
        interaction = self._chat(
            "\u4f60\u8fd8\u8bb0\u5f97\u6211\u6628\u5929\u8bf4\u7684\u5417\uff1f"
        )
        evaluation = self.evaluator.run_once()
        self.assertEqual(evaluation["ignored"], 1)
        self.assertEqual(evaluation["enqueued"], 0)
        self.assertIsNone(self.store.run_work_once(worker_id="automatic-proactive-test"))
        with self.repository.pool.connection() as connection:
            row = connection.execute(
                """SELECT disposition,reason_code,work_item_id
                   FROM havre.proactive_trigger_evaluations
                   WHERE owner_id=%s AND source_event_id=%s""",
                (self.owner_id, interaction.user_event_id),
            ).fetchone()
        self.assertEqual(row["disposition"], "ignored")
        self.assertEqual(row["reason_code"], "no_explicit_time_bound_reminder")
        self.assertIsNone(row["work_item_id"])

    def test_relationship_follow_up_is_source_guarded_and_separately_budgeted(self) -> None:
        source = self._chat("我最近终于开始慢慢适应新的节奏了。")
        revised = self.preference.model_copy(update={
            "preference_revision_id": uuid.uuid4(),
            "revision": 2,
            "category_permissions": {
                "owner_reminder": "allowed",
                "relationship_follow_up": "allowed",
            },
            "category_budget_per_24h": {
                "owner_reminder": 24,
                "relationship_follow_up": 1,
            },
            "created_at": datetime.now(UTC),
            "content_hash": "",
        })
        self.store.save_preference(ProactivePreferenceRevision.model_validate(
            revised.model_dump(mode="json")
        ))
        queued = self.store.enqueue_relationship_follow_up(
            run_id=uuid.uuid4(),
            source_event_id=source.user_event_id,
            source_kind="conversation",
            memory_ref=None,
            message="你说开始适应新的节奏了，我有点好奇：哪一刻让你最先感觉到变化？",
            timezone_name="America/Chicago",
            now=datetime.now(UTC).replace(hour=17, minute=0, second=0),
        )
        self.assertIsNotNone(queued)
        with self.repository.pool.connection() as connection:
            row = connection.execute(
                """SELECT command_payload
                   FROM havre.proactive_work_items
                   WHERE owner_id=%s AND work_item_id=%s""",
                (self.owner_id, queued["work_item_id"]),
            ).fetchone()
        command = row["command_payload"]
        self.assertEqual(command["source_kind"], "conversation")
        self.assertEqual(command["category"], "relationship_follow_up")
        self.assertEqual(command["reason_code"], "relationship_follow_up")
        self.assertEqual(
            command["source_guard"]["source_event_id"],
            str(source.user_event_id),
        )
        proposal = ProactiveProposal(
            owner_id=self.owner_id,
            category="relationship_follow_up",
            trigger_refs=(uuid.uuid4(),),
            reason_code="relationship_follow_up",
            reason_summary=command["reason_summary"],
            intended_benefit=command["intended_benefit"],
            evidence_refs=(f"event/{source.user_event_id}",),
            data_policy=self.repository.event_by_id(
                owner_id=self.owner_id, event_id=source.user_event_id
            ).data_policy,
            earliest_eligible_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            deduplication_key=f"relationship:{source.user_event_id}",
            trace_id=uuid.uuid4().hex,
        )
        self.assertEqual(
            self.store._render_text(proposal), command["reason_summary"]
        )
        erased = self.repository.erase_source_event_derivatives(
            owner_id=self.owner_id, source_event_id=source.user_event_id
        )
        self.assertEqual(erased["proactive_work_items"], 1)

    def test_goal_review_is_cancelled_when_goal_revision_is_no_longer_active(self) -> None:
        source = self._chat("Create a synthetic goal source event.")
        goal_service = GoalService(repository=self.repository)
        goal = goal_service.create(
            owner_id=self.owner_id,
            track=GoalTrack.REALITY,
            title="Review the synthetic milestone",
            why="Exercise the exact Goal projection guard",
            source_event_id=source.user_event_id,
            review_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        evaluation = self.evaluator.run_once()
        self.assertEqual(evaluation["enqueued"], 1)
        goal_service.update(
            owner_id=self.owner_id,
            goal_id=goal.goal_id,
            expected_revision=goal.revision,
            reason="Synthetic cancellation before proactive execution",
            status=GoalStatus.PAUSED,
        )
        work = self.store.run_work_once(worker_id="automatic-proactive-test")
        self.assertIsNotNone(work)
        assert work is not None
        self.assertEqual(work["status"], "cancelled")
        self.assertEqual(
            work["error_code"],
            "proactive_source_no_longer_current",
        )
        with self.repository.pool.connection() as connection:
            proposal_count = connection.execute(
                """SELECT count(*) AS value FROM havre.proactive_proposals
                   WHERE owner_id=%s""",
                (self.owner_id,),
            ).fetchone()["value"]
        self.assertEqual(proposal_count, 0)

    def test_multiple_owner_goal_reminders_use_current_projection_guard(self) -> None:
        source = self._chat("Store the exact owner course commitment source.")
        goal_service = GoalService(repository=self.repository)
        goal = goal_service.create(
            owner_id=self.owner_id,
            track=GoalTrack.REALITY,
            title="ECE 385 Lab deadline",
            why="Owner-authorized course schedule import",
            source_event_id=source.user_event_id,
        )
        due = datetime.now(UTC) - timedelta(seconds=1)
        first = self.store.enqueue_goal_reminder(
            goal_id=goal.goal_id,
            reminder_kind="start_window",
            reminder_text="ECE 385 Lab \u8fd8\u6709\u4e00\u5468\uff0c\u4eca\u5929\u5148\u628a\u7b2c\u4e00\u6b65\u5b9a\u4e0b\u6765\u3002",
            remind_at=due,
            expires_at=datetime.now(UTC) + timedelta(hours=2),
            idempotency_key=f"goal-reminder-{uuid.uuid4()}",
        )
        self.assertEqual(first["goal_revision"], 1)
        work = self.store.run_work_once(worker_id="automatic-proactive-test")
        self.assertIsNotNone(work)
        assert work is not None
        self.assertEqual(work["status"], "succeeded")
        with self.repository.pool.connection() as connection:
            rendered = connection.execute(
                """SELECT rendering.content_text
                   FROM havre.proactive_work_items work
                   JOIN havre.rendered_proactive_messages rendering
                     ON rendering.owner_id=work.owner_id
                    AND rendering.proposal_id=work.proposal_id
                   WHERE work.owner_id=%s AND work.work_item_id=%s""",
                (self.owner_id, first["work_item_id"]),
            ).fetchone()
        self.assertEqual(
            rendered["content_text"],
            "ECE 385 Lab \u8fd8\u6709\u4e00\u5468\uff0c\u4eca\u5929\u5148\u628a\u7b2c\u4e00\u6b65\u5b9a\u4e0b\u6765\u3002",
        )

        self.store.enqueue_goal_reminder(
            goal_id=goal.goal_id,
            reminder_kind="encouragement",
            reminder_text="\u660e\u5929\u5c31\u8981 demo \u4e86\uff0c\u4eca\u665a\u6536\u4e00\u6536\u5c3e\uff0c\u4f60\u80fd\u7a33\u7a33\u505a\u5b8c\u3002",
            remind_at=due,
            expires_at=datetime.now(UTC) + timedelta(hours=2),
            idempotency_key=f"goal-reminder-{uuid.uuid4()}",
        )
        goal_service.update(
            owner_id=self.owner_id,
            goal_id=goal.goal_id,
            expected_revision=goal.revision,
            reason="Owner completed or changed the imported commitment",
            status=GoalStatus.PAUSED,
        )
        cancelled = self.store.run_work_once(worker_id="automatic-proactive-test")
        self.assertIsNotNone(cancelled)
        assert cancelled is not None
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(
            cancelled["error_code"], "proactive_source_no_longer_current"
        )

    def test_planned_scene_is_cancelled_after_scene_starts(self) -> None:
        scene_store = ScenePostgresStore(
            repository=self.repository,
            owner_id=self.owner_id,
            identity=self.identity,
        )
        created = scene_store.create(
            scene_type="synthetic_focus_block",
            situation=SceneSituation(
                summary="Synthetic planned work",
                known_facts=("The owner chose this synthetic fixture",),
                uncertainty_notes=("No real-world outcome is assumed",),
            ),
            planned_goal=SceneGoal(
                objective="Start one synthetic step",
                minimum_success="Open the synthetic task",
            ),
            anticipated_triggers=(),
            danger=DangerAssessment.LOW,
            avoidance=AvoidanceAssessment.PRESENT,
            energy=EnergyAssessment.ADEQUATE,
            coercion=CoercionAssessment.ABSENT,
            goal_alignment=GoalAlignment.ACTIVE_MEANINGFUL,
            goal_urgency=GoalUrgency.NORMAL,
            privacy_class=PrivacyClass.LOCAL_ONLY,
            memory_eligible=False,
            planned_start_at=datetime.now(UTC) - timedelta(seconds=1),
            session_id=None,
            idempotency_key=f"automatic-scene-create-{uuid.uuid4()}",
            traceparent=None,
        )
        evaluation = self.evaluator.run_once()
        self.assertEqual(evaluation["enqueued"], 1)
        scene_store.transition(
            scene_session_id=created.scene.scene_session.scene_session_id,
            expected_revision=1,
            action="start",
            reason="Synthetic start before proactive execution",
            terminal_status=None,
            idempotency_key=f"automatic-scene-start-{uuid.uuid4()}",
            traceparent=None,
        )
        work = self.store.run_work_once(worker_id="automatic-proactive-test")
        self.assertIsNotNone(work)
        assert work is not None
        self.assertEqual(work["status"], "cancelled")
        self.assertEqual(
            work["error_code"],
            "proactive_source_no_longer_current",
        )

    def test_database_rejects_forged_evaluation_source_hash(self) -> None:
        interaction = self._chat("\u4eca\u5929\u968f\u4fbf\u804a\u804a")
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
            with self.repository.pool.connection() as connection, connection.transaction():
                connection.execute(
                    """INSERT INTO havre.proactive_trigger_evaluations
                       (owner_id,evaluation_id,evaluator_version,source_event_id,
                        source_event_content_hash,source_event_type,candidate_kind,
                        disposition,reason_code,work_item_id,content_hash)
                       VALUES (%s,%s,%s,%s,%s,'USER_MESSAGE','owner_reminder',
                               'ignored','forged_source_probe',NULL,%s)""",
                    (
                        self.owner_id,
                        uuid.uuid4(),
                        EVALUATOR_VERSION,
                        interaction.user_event_id,
                        "sha256:" + "0" * 64,
                        "sha256:" + "1" * 64,
                    ),
                )


    def test_context_sources_never_have_independent_trigger_authority(self) -> None:
        for event_type in (
            EventType.MEMORY_CREATED,
            EventType.MEMORY_REVISED,
            EventType.CURRENT_STATE_ESTIMATED,
            EventType.LIFE_CONTEXT_OBSERVED,
            EventType.USER_BELIEF_CREATED,
            EventType.USER_BELIEF_REVISED,
            EventType.USER_BELIEF_TRANSITIONED,
        ):
            with self.subTest(event_type=event_type.value):
                event = SimpleNamespace(
                    event_id=uuid.uuid4(),
                    event_type=event_type,
                    content_hash="sha256:" + "a" * 64,
                )
                candidate, command, not_before = self.evaluator._candidate_for_event(event, now=datetime.now(UTC))
                self.assertEqual((candidate.candidate_kind, candidate.disposition), ("context_only", "ignored"))
