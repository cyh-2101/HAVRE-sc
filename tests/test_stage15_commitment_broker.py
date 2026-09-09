from __future__ import annotations

import json
import os
import unittest
import uuid
from unittest.mock import patch
from datetime import UTC, datetime, timedelta
from pathlib import Path

from companion.application import InteractionCommand, InteractionService
from companion.commitments.service import (
    COMMITMENT_AUTHORIZATION_REF,
    CommitmentBroker,
)
from companion.context import ContextBuilder
from companion.goals.models import GoalPriority, GoalStatus, GoalTrack
from companion.goals.service import GoalService
from companion.identity import IdentityLoader
from companion.persistence import PostgresRepository, apply_migrations
from companion.persistence.proactive import (
    ActiveConversationDeferral,
    ProactivePostgresStore,
)
from companion.policy import DataPolicy, PrivacyClass
from companion.proactive import (
    InterruptionOutcome,
    ProactivePreferenceRevision,
    ProactiveProposal,
)
from companion.proactive.policy import InterruptionPolicy
from mlsys.serving import DeterministicLocalProvider, Stage1Router
from scripts.import_owner_course_schedule import _expand_reminders


DATABASE_URL = os.getenv("HAVRE_TEST_DATABASE_URL")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHA256 = "a" * 64


class Stage15CommitmentPolicyTests(unittest.TestCase):
    def test_natural_reminders_are_deterministic_and_never_midnight(self) -> None:
        plan = {
            "timezone": "America/Chicago",
            "activation_at": "2026-09-03T10:00:00-05:00",
        }
        entry = {
            "entry_id": "ece210-lab-1",
            "title": "ECE 210 Lab 1",
            "reminder_policy": "large",
            "due_times": ["2026-09-24T17:00:00-05:00"],
        }
        first = _expand_reminders(plan, entry)
        self.assertEqual(first, _expand_reminders(plan, entry))
        self.assertEqual(len(first), 3)
        for reminder in first:
            local = datetime.fromisoformat(reminder["remind_at"])
            self.assertGreaterEqual((local.hour, local.minute), (10, 0))
            self.assertLessEqual((local.hour, local.minute), (21, 30))
            self.assertNotEqual((local.hour, local.minute), (0, 0))

    def test_no_normal_cap_but_hard_breaker_remains(self) -> None:
        owner_id = uuid.uuid4()
        identity = IdentityLoader(PROJECT_ROOT / "identity").load()
        policy = InterruptionPolicy(
            constitution_version_id=identity.constitution.version_id,
            identity_version_id=identity.identity.version_id,
        )
        now = datetime.now(UTC)
        preference = ProactivePreferenceRevision(
            owner_id=owner_id,
            revision=1,
            global_enabled=True,
            category_permissions={"owner_reminder": "allowed"},
            allowed_channels=("web_inbox",),
            authorization_ref="stage15-owner-authorized-no-normal-cap",
        )
        proposal = ProactiveProposal(
            owner_id=owner_id,
            category="owner_reminder",
            trigger_refs=(uuid.uuid4(),),
            reason_code="owner_goal_reminder",
            reason_summary="Review ECE 210 Lab 1",
            intended_benefit="Support an owner commitment",
            evidence_refs=("goal/test",),
            data_policy=DataPolicy.owner_default(
                PrivacyClass.LOCAL_ONLY, memory_eligible=False
            ),
            earliest_eligible_at=now - timedelta(minutes=1),
            expires_at=now + timedelta(hours=2),
            deduplication_key="stage15-hard-breaker",
            trace_id="a" * 32,
        )
        allowed = policy.decide(
            proposal=proposal,
            preference=preference,
            now=now,
            delivered_global_24h=23,
            delivered_category_24h=23,
            last_equivalent_delivery_at=None,
            duplicate_active=False,
        )
        self.assertEqual(allowed.decision, InterruptionOutcome.SEND_NOW)
        blocked = policy.decide(
            proposal=proposal,
            preference=preference,
            now=now,
            delivered_global_24h=24,
            delivered_category_24h=24,
            last_equivalent_delivery_at=None,
            duplicate_active=False,
        )
        self.assertEqual(blocked.decision, InterruptionOutcome.DEFER)
        self.assertIn("hard_anti_runaway_breaker", blocked.reason_codes)


@unittest.skipUnless(DATABASE_URL, "HAVRE_TEST_DATABASE_URL is required")
class Stage15CommitmentBrokerIntegrationTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        assert DATABASE_URL is not None
        apply_migrations(DATABASE_URL, PROJECT_ROOT / "db" / "migrations")
        cls.identity = IdentityLoader(PROJECT_ROOT / "identity").load()
        cls.repository = PostgresRepository(DATABASE_URL)
        cls.repository.open()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.repository.close()

    async def asyncSetUp(self) -> None:
        self.owner_id = uuid.uuid4()
        self.repository.bootstrap_owner_and_identity(
            owner_id=self.owner_id, identity=self.identity
        )
        self.goals = GoalService(repository=self.repository)
        self.broker = CommitmentBroker(
            repository=self.repository, owner_id=self.owner_id
        )
        self.store = ProactivePostgresStore(
            repository=self.repository,
            owner_id=self.owner_id,
            identity=self.identity,
            commitment_broker=self.broker,
        )
        self.store.save_preference(ProactivePreferenceRevision(
            owner_id=self.owner_id,
            revision=1,
            global_enabled=True,
            category_permissions={"owner_reminder": "allowed"},
            allowed_channels=("web_inbox",),
            authorization_ref="stage15-owner-authorized-no-normal-cap",
        ))
        self.source_interactions = self._interaction_service(
            output="Source accepted."
        )

    def _interaction_service(self, *, output: str, broker: bool = False):
        provider = DeterministicLocalProvider()
        provider.output = output
        return InteractionService(
            owner_id=self.owner_id,
            identity=self.identity,
            repository=self.repository,
            context_builder=ContextBuilder(
                max_input_tokens=4096, reserved_output_tokens=256
            ),
            router=Stage1Router(),
            provider=provider,
            commitment_broker=self.broker if broker else None,
        )

    async def _commitment(
        self,
        *,
        task_name: str,
        entry_id: str,
        deadline_at: datetime | None = None,
        course_schedule_marker: bool = False,
    ):
        source = await self.source_interactions.interact(InteractionCommand(
            message=f"Private schedule source for {entry_id}",
            privacy_class=PrivacyClass.LOCAL_ONLY,
            memory_eligible=True,
            channel="api",
            idempotency_key=f"stage15-source-{uuid.uuid4()}",
        ))
        goal = self.goals.create(
            owner_id=self.owner_id,
            track=GoalTrack.REALITY,
            title=task_name,
            why=(
                f"owner_course_schedule:Fall 2026:{SOURCE_SHA256}:"
                f"{entry_id};status=confirmed"
                if course_schedule_marker
                else f"Private source detail for {entry_id}"
            ),
            source_event_id=source.user_event_id,
            priority=GoalPriority.HIGH,
            next_action=f"Private next action for {entry_id}",
            review_at=deadline_at,
        )
        self.broker.record_field_authorization(
            source_sha256=SOURCE_SHA256,
            authorization_ref=COMMITMENT_AUTHORIZATION_REF,
        )
        projection = self.broker.project_goal(
            goal_id=goal.goal_id,
            source_sha256=SOURCE_SHA256,
            entry_id=entry_id,
            course_name="ECE 210",
            task_name=task_name,
            deadline_at=deadline_at,
        )
        return goal, projection

    def _due_reminder(self, *, goal_id, task_name: str):
        now = datetime.now(UTC)
        return self.store.enqueue_goal_reminder(
            goal_id=goal_id,
            reminder_kind="check_in",
            reminder_text=f"Remember {task_name}",
            remind_at=now - timedelta(seconds=2),
            expires_at=now + timedelta(hours=2),
            idempotency_key=f"stage15-reminder-{uuid.uuid4()}",
        )

    async def test_only_five_authorized_fields_enter_ordinary_chat_context(self) -> None:
        task_name = "ECE 210 Lab Privacy Boundary"
        await self._commitment(
            task_name=task_name,
            entry_id="ece210-privacy",
            deadline_at=datetime.now(UTC) + timedelta(days=2),
        )
        items = self.broker.select_context(
            query_text="帮我安排 ECE 210 作业",
            maximum_privacy_class=PrivacyClass.NORMAL,
        )
        self.assertEqual(len(items), 1)
        encoded = items[0].content_text.split(": ", 1)[1]
        fields = json.loads(encoded)
        self.assertEqual(set(fields), {
            "course_name", "task_name", "deadline",
            "completion_state", "reminder_history",
        })
        self.assertNotIn("Private source detail", items[0].content_text)
        self.assertNotIn("Private next action", items[0].content_text)
        self.assertEqual(items[0].data_policy.privacy_class, PrivacyClass.NORMAL)
        self.assertTrue(items[0].data_policy.cloud_eligible)
        self.assertEqual(
            items[0].data_policy.authorization_ref,
            COMMITMENT_AUTHORIZATION_REF,
        )

    async def test_projection_failure_rolls_back_goal_and_queue(self) -> None:
        goal, _ = await self._commitment(task_name="Lab Rollback", entry_id="rollback")
        reminder = self._due_reminder(goal_id=goal.goal_id, task_name="Lab Rollback")
        with patch("companion.persistence.commitment_projection.refresh_commitment_projection", side_effect=RuntimeError("projection unavailable")):
            with self.assertRaises(RuntimeError):
                self.goals.update(owner_id=self.owner_id, goal_id=goal.goal_id,
                                  expected_revision=1, reason="test rollback", status=GoalStatus.COMPLETED)
        with self.repository.pool.connection() as connection:
            current = connection.execute("SELECT status,revision FROM havre.goals WHERE owner_id=%s AND goal_id=%s", (self.owner_id, goal.goal_id)).fetchone()
            work = connection.execute("SELECT status FROM havre.proactive_work_items WHERE owner_id=%s AND work_item_id=%s", (self.owner_id, reminder["work_item_id"])).fetchone()
        self.assertEqual(dict(current), {"status": "active", "revision": 1})
        self.assertEqual(work["status"], "pending")

    async def test_written_report_with_time_suffix_updates_exact_task(self):
        from companion.context.lookup import requested_personal_context
        goal,_=await self._commitment(task_name="ECE 210 Lab 1 Report（9/8 11:59 PM）",entry_id="written-report")
        other,_=await self._commitment(task_name="ECE 210 Lab 2 Report（9/15 11:59 PM）",entry_id="other-report")
        reminder=self._due_reminder(goal_id=goal.goal_id,task_name="Lab 1 Report")
        service=self._interaction_service(output="这项完成了。",broker=True)
        result=await service.interact(InteractionCommand(message="昨天我把ece210 lab1report写完了",privacy_class=PrivacyClass.NORMAL,channel="web",idempotency_key=str(uuid.uuid4())))
        with self.repository.pool.connection() as c:
            states={row["goal_id"]:row["status"] for row in c.execute("SELECT goal_id,status FROM havre.goals WHERE owner_id=%s",(self.owner_id,)).fetchall()}
            self.assertEqual(states[goal.goal_id],"completed");self.assertEqual(states[other.goal_id],"active")
            self.assertEqual(c.execute("SELECT status FROM havre.proactive_work_items WHERE owner_id=%s AND work_item_id=%s",(self.owner_id,reminder["work_item_id"])).fetchone()["status"],"cancelled")
        event=self.repository.event_by_id(owner_id=self.owner_id,event_id=result.user_event_id)
        evidence=requested_personal_context(self.repository,current_event=event,query="ece210 lab1report现在状态是什么",timezone_name="UTC")
        self.assertTrue(any("status=completed" in item.content_text and "Lab 1 Report" in item.content_text for item in evidence))
        self.assertFalse(any("Private next action" in item.content_text for item in evidence))

    async def test_natural_composite_completion_is_safe_and_source_bound(self) -> None:
        goal, _ = await self._commitment(task_name="Lab 2.1 Demo + Quiz 1", entry_id="natural")
        service = self._interaction_service(output="Understood.", broker=True)
        for message in ("I have not completed ECE210 lab2.1", "ece210lab2.2demo+quiz1搞完了", "ece210lab2.1demo搞完了"):
            await service.interact(InteractionCommand(message=message, privacy_class=PrivacyClass.NORMAL, channel="web", idempotency_key=str(uuid.uuid4())))
            self.assertEqual(self.goals.list(owner_id=self.owner_id)[0]["status"], "active")
        result = await service.interact(InteractionCommand(message="ece210lab2.1demo+quiz搞完了", privacy_class=PrivacyClass.NORMAL, channel="web", idempotency_key=str(uuid.uuid4())))
        self.assertEqual(self.goals.list(owner_id=self.owner_id, include_inactive=True)[0]["status"], "completed")
        sections = self.repository.evidence(result.request_id, owner_id=self.owner_id)["context_pack"]["sections"]
        self.assertTrue(any(s["section_id"].startswith("completion-receipt-") for s in sections))

    async def test_urgent_goal_does_not_interrupt_unrelated_smalltalk(self) -> None:
        await self._commitment(task_name="ECE 210 Lab Calm", entry_id="calm", deadline_at=datetime.now(UTC)+timedelta(hours=1))
        self.assertEqual(self.broker.select_context(query_text="今天的面不太好吃", maximum_privacy_class=PrivacyClass.NORMAL), ())
        self.assertEqual(len(self.broker.select_context(query_text="今天有什么任务要做", maximum_privacy_class=PrivacyClass.NORMAL)), 1)

    async def test_clear_completion_updates_unique_goal_and_cancels_reminders(self) -> None:
        task_name = "ECE 210 Lab Completion Alpha"
        goal, _ = await self._commitment(
            task_name=task_name,
            entry_id="ece210-completion-alpha",
            deadline_at=datetime.now(UTC) + timedelta(hours=4),
        )
        reminder = self._due_reminder(goal_id=goal.goal_id, task_name=task_name)
        result = await self._interaction_service(
            output="Got it.", broker=True
        ).interact(InteractionCommand(
            message="I completed ECE 210 Lab Completion Alpha",
            privacy_class=PrivacyClass.NORMAL,
            memory_eligible=True,
            channel="web",
            idempotency_key=f"stage15-complete-{uuid.uuid4()}",
        ))
        with self.repository.pool.connection() as connection:
            current = connection.execute(
                "SELECT status,revision,last_event_id FROM havre.goals "
                "WHERE owner_id=%s AND goal_id=%s",
                (self.owner_id, goal.goal_id),
            ).fetchone()
            work = connection.execute(
                "SELECT status FROM havre.proactive_work_items "
                "WHERE owner_id=%s AND work_item_id=%s",
                (self.owner_id, reminder["work_item_id"]),
            ).fetchone()
            projection = connection.execute(
                "SELECT completion_state FROM havre.commitment_projections "
                "WHERE owner_id=%s AND goal_id=%s AND goal_revision=%s",
                (self.owner_id, goal.goal_id, current["revision"]),
            ).fetchone()
        self.assertEqual(current["status"], "completed")
        self.assertEqual(current["revision"], 2)
        with self.repository.pool.connection() as connection:
            evidence = connection.execute(
                "SELECT source_event_id,lifecycle_event_id FROM "
                "havre.goal_transition_evidence WHERE owner_id=%s AND goal_id=%s",
                (self.owner_id, goal.goal_id),
            ).fetchone()
        self.assertEqual(evidence["source_event_id"], result.user_event_id)
        self.assertEqual(evidence["lifecycle_event_id"], current["last_event_id"])
        self.assertEqual(work["status"], "cancelled")
        self.assertEqual(projection["completion_state"], "completed")

    async def test_explicit_slot_supersession_atomically_cancels_old_reminder(self) -> None:
        goal, _ = await self._commitment(
            task_name="ECE 210 Slot Replacement",
            entry_id="ece210-slot-replacement",
            deadline_at=datetime.now(UTC) + timedelta(hours=4),
        )
        remind_at = datetime.now(UTC) + timedelta(hours=1)
        expires_at = remind_at + timedelta(hours=2)
        old = self.store.enqueue_goal_reminder(
            goal_id=goal.goal_id,
            reminder_kind="check_in",
            reminder_text="Old wording",
            remind_at=remind_at,
            expires_at=expires_at,
            idempotency_key=f"stage15-slot-old-{uuid.uuid4()}",
        )
        new = self.store.enqueue_goal_reminder(
            goal_id=goal.goal_id,
            reminder_kind="check_in",
            reminder_text="Reviewed wording",
            remind_at=remind_at,
            expires_at=expires_at,
            idempotency_key=f"stage15-slot-new-{uuid.uuid4()}",
            supersede_existing_slot=True,
        )
        with self.repository.pool.connection() as connection:
            rows = connection.execute(
                "SELECT work_item_id,status,last_error_code "
                "FROM havre.proactive_work_items "
                "WHERE owner_id=%s AND work_item_id=ANY(%s::uuid[]) "
                "ORDER BY work_item_id",
                (self.owner_id, [old["work_item_id"], new["work_item_id"]]),
            ).fetchall()
        by_id = {row["work_item_id"]: row for row in rows}
        self.assertEqual(by_id[old["work_item_id"]]["status"], "cancelled")
        self.assertEqual(
            by_id[old["work_item_id"]]["last_error_code"],
            "superseded_by_owner_schedule_update",
        )
        self.assertEqual(by_id[new["work_item_id"]]["status"], "pending")

    async def test_authorized_source_supersedes_only_legacy_course_generation(self) -> None:
        goal, _ = await self._commitment(
            task_name="ECE 210 Legacy Generation",
            entry_id="ece210-legacy-generation",
            deadline_at=datetime.now(UTC) + timedelta(hours=4),
            course_schedule_marker=True,
        )
        remind_at = datetime.now(UTC) + timedelta(hours=1)
        expires_at = remind_at + timedelta(hours=2)
        legacy = self.store.enqueue_goal_reminder(
            goal_id=goal.goal_id,
            reminder_kind="check_in",
            reminder_text="Legacy reminder",
            remind_at=remind_at,
            expires_at=expires_at,
            idempotency_key=(
                f"course-{SOURCE_SHA256[:16]}-ece210-legacy-generation-1"
            ),
        )
        current = self.store.enqueue_goal_reminder(
            goal_id=goal.goal_id,
            reminder_kind="start_window",
            reminder_text="Current reminder",
            remind_at=remind_at + timedelta(minutes=10),
            expires_at=expires_at,
            idempotency_key=(
                f"course-v2-{SOURCE_SHA256[:16]}-ece210-legacy-generation-1-r1"
            ),
        )
        result = self.broker.supersede_legacy_course_reminders(
            source_sha256=SOURCE_SHA256,
            replacement_generation="v2",
        )
        replay = self.broker.supersede_legacy_course_reminders(
            source_sha256=SOURCE_SHA256,
            replacement_generation="v2",
        )
        with self.repository.pool.connection() as connection:
            rows = connection.execute(
                "SELECT work_item_id,status,last_error_code "
                "FROM havre.proactive_work_items "
                "WHERE owner_id=%s AND work_item_id=ANY(%s::uuid[])",
                (self.owner_id, [legacy["work_item_id"], current["work_item_id"]]),
            ).fetchall()
        by_id = {row["work_item_id"]: row for row in rows}
        self.assertEqual(result["legacy_reminders_cancelled"], 1)
        self.assertEqual(replay["legacy_reminders_cancelled"], 0)
        self.assertEqual(by_id[legacy["work_item_id"]]["status"], "cancelled")
        self.assertEqual(
            by_id[legacy["work_item_id"]]["last_error_code"],
            "superseded_by_owner_schedule_v2",
        )
        self.assertEqual(by_id[current["work_item_id"]]["status"], "pending")

    async def test_ambiguous_completion_only_requests_one_clarification(self) -> None:
        for suffix in ("Alpha", "Beta"):
            await self._commitment(
                task_name=f"ECE 210 Lab {suffix}",
                entry_id=f"ece210-ambiguous-{suffix.casefold()}",
                deadline_at=datetime.now(UTC) + timedelta(days=3),
            )
        result = await self._interaction_service(
            output="Which one?", broker=True
        ).interact(InteractionCommand(
            message="done",
            privacy_class=PrivacyClass.NORMAL,
            memory_eligible=True,
            channel="web",
            idempotency_key=f"stage15-ambiguous-{uuid.uuid4()}",
        ))
        with self.repository.pool.connection() as connection:
            statuses = connection.execute(
                "SELECT status FROM havre.goals WHERE owner_id=%s ORDER BY title",
                (self.owner_id,),
            ).fetchall()
            sections = connection.execute(
                "SELECT sections FROM havre.context_packs "
                "WHERE owner_id=%s AND context_pack_id=%s",
                (self.owner_id, result.context_pack_id),
            ).fetchone()["sections"]
        self.assertEqual([row["status"] for row in statuses], ["active", "active"])
        clarifications = [
            section for section in sections
            if str(section.get("section_id", "")).startswith("completion-clarification-")
        ]
        self.assertEqual(len(clarifications), 1)
        text = "\n".join(
            part["text"] for part in clarifications[0]["content_parts"]
        )
        self.assertIn("你说的是哪一项任务完成了", text)

    async def test_active_conversation_suppresses_standalone_delivery(self) -> None:
        task_name = "ECE 210 Lab Active Conversation"
        goal, _ = await self._commitment(
            task_name=task_name,
            entry_id="ece210-active-conversation",
            deadline_at=datetime.now(UTC) + timedelta(hours=2),
        )
        reminder = self._due_reminder(goal_id=goal.goal_id, task_name=task_name)
        request_id = uuid.uuid4()
        self.broker.begin_interaction_activity(request_id=request_id)
        try:
            result = self.store.run_work_once(worker_id="stage15-active-test")
        finally:
            self.broker.end_interaction_activity(request_id=request_id)
        self.assertEqual(result["status"], "deferred")
        self.assertEqual(result["error_code"], "active_conversation")
        with self.repository.pool.connection() as connection:
            work = connection.execute(
                "SELECT status,last_error_code FROM havre.proactive_work_items "
                "WHERE owner_id=%s AND work_item_id=%s",
                (self.owner_id, reminder["work_item_id"]),
            ).fetchone()
            delivered = connection.execute(
                "SELECT count(*) AS value FROM havre.commitment_reminder_deliveries "
                "WHERE owner_id=%s",
                (self.owner_id,),
            ).fetchone()["value"]
        self.assertEqual(work["status"], "pending")
        self.assertEqual(work["last_error_code"], "active_conversation_deferred")
        self.assertEqual(delivered, 0)

        fused = await self._interaction_service(
            output=f"顺带提醒：{task_name}。", broker=True
        ).interact(InteractionCommand(
            message="帮我安排今天的 ECE 210 作业",
            privacy_class=PrivacyClass.NORMAL,
            memory_eligible=True,
            channel="web",
            idempotency_key=f"stage15-after-race-{uuid.uuid4()}",
        ))
        with self.repository.pool.connection() as connection:
            delivery = connection.execute(
                "SELECT delivery_mode,assistant_event_id FROM "
                "havre.commitment_reminder_deliveries "
                "WHERE owner_id=%s AND work_item_id=%s",
                (self.owner_id, reminder["work_item_id"]),
            ).fetchone()
        self.assertEqual(delivery["delivery_mode"], "conversation_fusion")
        self.assertEqual(delivery["assistant_event_id"], fused.assistant_event_id)

    async def test_standalone_delivery_only_runs_without_active_conversation(self) -> None:
        task_name = "ECE 210 Lab Standalone"
        goal, _ = await self._commitment(
            task_name=task_name,
            entry_id="ece210-standalone",
            deadline_at=datetime.now(UTC) + timedelta(hours=2),
        )
        reminder = self._due_reminder(goal_id=goal.goal_id, task_name=task_name)
        result = self.store.run_work_once(worker_id="stage15-standalone-test")
        self.assertEqual(result["status"], "succeeded")
        with self.repository.pool.connection() as connection:
            rows = connection.execute(
                "SELECT delivery_mode,inclusion_text FROM "
                "havre.commitment_reminder_deliveries "
                "WHERE owner_id=%s AND work_item_id=%s",
                (self.owner_id, reminder["work_item_id"]),
            ).fetchall()
            inbox_count = connection.execute(
                "SELECT count(*) AS value FROM havre.proactive_inbox_messages "
                "WHERE owner_id=%s",
                (self.owner_id,),
            ).fetchone()["value"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["delivery_mode"], "standalone_web_inbox")
        self.assertEqual(rows[0]["inclusion_text"], task_name)
        self.assertEqual(inbox_count, 1)
        self.assertIsNone(self.store.run_work_once(worker_id="stage15-standalone-replay"))

    async def test_abandonment_atomically_cancels_goal_reminders(self) -> None:
        task_name = "CS 444 / ECE 494 4-credit Project Proposal"
        goal, _ = await self._commitment(
            task_name=task_name,
            entry_id="cs444-project-proposal-conditional",
            deadline_at=datetime.now(UTC) + timedelta(days=20),
        )
        reminder = self._due_reminder(goal_id=goal.goal_id, task_name=task_name)
        updated = self.goals.update(
            owner_id=self.owner_id,
            goal_id=goal.goal_id,
            expected_revision=goal.revision,
            reason="Owner confirmed ECE 494 is 3-credit",
            status=GoalStatus.ABANDONED,
        )
        self.assertEqual(updated.status.value, "abandoned")
        with self.repository.pool.connection() as connection:
            work = connection.execute(
                "SELECT status,last_error_code FROM havre.proactive_work_items "
                "WHERE owner_id=%s AND work_item_id=%s",
                (self.owner_id, reminder["work_item_id"]),
            ).fetchone()
        self.assertEqual(work["status"], "cancelled")
        self.assertEqual(work["last_error_code"], "goal_no_longer_active")

    async def test_user_arrival_epoch_wins_render_delivery_race(self) -> None:
        self.store.save_preference(ProactivePreferenceRevision(
            owner_id=self.owner_id,
            revision=2,
            global_enabled=True,
            category_permissions={"owner_reminder": "allowed"},
            allowed_channels=("web_inbox",),
            global_budget_per_24h=10,
            category_budget_per_24h={"owner_reminder": 10},
            authorization_ref="stage15-arrival-race-fixture",
        ))
        before = self.broker.standalone_epoch()
        self.assertEqual(before, 0)
        request_id = uuid.uuid4()
        self.broker.begin_interaction_activity(request_id=request_id)
        now = datetime.now(UTC)
        try:
            with self.assertRaises(ActiveConversationDeferral):
                self.store.execute_fixture(
                    trigger_type="owner_requested_reminder",
                    source_kind="owner_reminder",
                    source_refs=("owner-reminder/stage15-race",),
                    subject_refs=("goal/stage15-race",),
                    category="owner_reminder",
                    reason_code="owner_requested_fixture",
                    reason_summary="Race fixture",
                    intended_benefit="Prove the user arrival wins",
                    data_policy=DataPolicy.owner_default(
                        PrivacyClass.LOCAL_ONLY, memory_eligible=False
                    ),
                    preference_revision=2,
                    idempotency_key=f"stage15-race-{uuid.uuid4()}",
                    observed_at=now,
                    earliest_eligible_at=now - timedelta(seconds=1),
                    expires_at=now + timedelta(hours=1),
                    deduplication_key=f"stage15-race-dedupe-{uuid.uuid4()}",
                    expected_arrival_epoch=before,
                )
        finally:
            self.broker.end_interaction_activity(request_id=request_id)
        with self.repository.pool.connection() as connection:
            count = connection.execute(
                "SELECT count(*) AS value FROM havre.proactive_inbox_messages "
                "WHERE owner_id=%s",
                (self.owner_id,),
            ).fetchone()["value"]
        self.assertEqual(count, 0)

    async def test_fusion_delivered_only_after_actual_inclusion_and_deduped(self) -> None:
        task_name = "ECE 210 Lab Fusion Proof"
        goal, _ = await self._commitment(
            task_name=task_name,
            entry_id="ece210-fusion-proof",
            deadline_at=datetime.now(UTC) + timedelta(hours=2),
        )
        reminder = self._due_reminder(goal_id=goal.goal_id, task_name=task_name)
        omitted = await self._interaction_service(
            output="Here is a concise planning answer without a reminder.", broker=True
        ).interact(InteractionCommand(
            message="帮我安排今天的 ECE 210 作业",
            privacy_class=PrivacyClass.NORMAL,
            memory_eligible=True,
            channel="web",
            idempotency_key=f"stage15-fusion-omit-{uuid.uuid4()}",
        ))
        with self.repository.pool.connection() as connection:
            omitted_count = connection.execute(
                "SELECT count(*) AS value FROM havre.commitment_reminder_deliveries "
                "WHERE owner_id=%s AND work_item_id=%s",
                (self.owner_id, reminder["work_item_id"]),
            ).fetchone()["value"]
            omitted_claim = connection.execute(
                "SELECT status,reason FROM havre.proactive_fusion_claims "
                "WHERE owner_id=%s AND request_id=%s",
                (self.owner_id, omitted.request_id),
            ).fetchone()
        self.assertEqual(omitted_count, 0)
        self.assertEqual(omitted_claim["status"], "deferred")
        self.assertEqual(omitted_claim["reason"], "final_message_omitted_reminder")

        delivered = await self._interaction_service(
            output=f"今天先处理 {task_name}，再看剩余安排。", broker=True
        ).interact(InteractionCommand(
            message="再帮我安排一下今天的 ECE 210 作业",
            privacy_class=PrivacyClass.NORMAL,
            memory_eligible=True,
            channel="web",
            idempotency_key=f"stage15-fusion-deliver-{uuid.uuid4()}",
        ))
        await self._interaction_service(
            output="No duplicate reminder is needed.", broker=True
        ).interact(InteractionCommand(
            message="ECE 210 作业还有什么安排",
            privacy_class=PrivacyClass.NORMAL,
            memory_eligible=True,
            channel="web",
            idempotency_key=f"stage15-fusion-replay-{uuid.uuid4()}",
        ))
        with self.repository.pool.connection() as connection:
            rows = connection.execute(
                "SELECT delivery_mode,assistant_event_id,context_pack_id,inclusion_text "
                "FROM havre.commitment_reminder_deliveries "
                "WHERE owner_id=%s AND work_item_id=%s",
                (self.owner_id, reminder["work_item_id"]),
            ).fetchall()
            work = connection.execute(
                "SELECT status,request_id,proposal_id FROM havre.proactive_work_items "
                "WHERE owner_id=%s AND work_item_id=%s",
                (self.owner_id, reminder["work_item_id"]),
            ).fetchone()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["delivery_mode"], "conversation_fusion")
        self.assertEqual(rows[0]["assistant_event_id"], delivered.assistant_event_id)
        self.assertEqual(rows[0]["context_pack_id"], delivered.context_pack_id)
        self.assertEqual(rows[0]["inclusion_text"], task_name)
        self.assertEqual(work["status"], "succeeded")
        self.assertIsNone(work["request_id"])
        self.assertIsNone(work["proposal_id"])

    async def test_source_erasure_removes_goal_commitment_and_delivered_queue_closure(
        self,
    ) -> None:
        task_name = "ECE 210 Lab Erasure Closure"
        goal, projection = await self._commitment(
            task_name=task_name,
            entry_id="ece210-erasure-closure",
            deadline_at=datetime.now(UTC) + timedelta(hours=2),
        )
        reminder = self._due_reminder(goal_id=goal.goal_id, task_name=task_name)
        delivered = self.store.run_work_once(worker_id="stage15-erasure-test")
        self.assertEqual(delivered["status"], "succeeded")
        with self.repository.pool.connection() as connection:
            source_event_id = connection.execute(
                """
                SELECT causation_event_id
                FROM havre.events
                WHERE owner_id=%s AND event_type='GOAL_CREATED'
                  AND payload->>'goal_id'=%s
                """,
                (self.owner_id, str(goal.goal_id)),
            ).fetchone()["causation_event_id"]
            authorization_id = connection.execute(
                """
                SELECT authorization_id FROM havre.commitment_projections
                WHERE owner_id=%s AND commitment_projection_id=%s
                """,
                (self.owner_id, projection["commitment_projection_id"]),
            ).fetchone()["authorization_id"]

        erased = self.repository.erase_source_event_derivatives(
            owner_id=self.owner_id,
            source_event_id=source_event_id,
        )

        self.assertEqual(erased["goals"], 1)
        self.assertEqual(erased["commitment_projections"], 1)
        self.assertEqual(erased["commitment_reminder_deliveries"], 1)
        self.assertEqual(erased["proactive_work_items"], 1)
        self.assertEqual(erased["commitment_field_authorizations"], 1)
        with self.repository.pool.connection() as connection:
            raw_source_count = connection.execute(
                "SELECT count(*) AS value FROM havre.events "
                "WHERE owner_id=%s AND event_id=%s",
                (self.owner_id, source_event_id),
            ).fetchone()["value"]
            remaining = connection.execute(
                """
                SELECT
                  (SELECT count(*) FROM havre.goals
                   WHERE owner_id=%s AND goal_id=%s) AS goals,
                  (SELECT count(*) FROM havre.commitment_projections
                   WHERE owner_id=%s AND goal_id=%s) AS projections,
                  (SELECT count(*) FROM havre.commitment_reminder_deliveries
                   WHERE owner_id=%s AND work_item_id=%s) AS deliveries,
                  (SELECT count(*) FROM havre.proactive_work_items
                   WHERE owner_id=%s AND work_item_id=%s) AS work_items,
                  (SELECT count(*) FROM havre.commitment_field_authorizations
                   WHERE owner_id=%s AND authorization_id=%s) AS authorizations
                """,
                (
                    self.owner_id, goal.goal_id,
                    self.owner_id, goal.goal_id,
                    self.owner_id, reminder["work_item_id"],
                    self.owner_id, reminder["work_item_id"],
                    self.owner_id, authorization_id,
                ),
            ).fetchone()
        self.assertEqual(raw_source_count, 1)
        self.assertEqual(dict(remaining), {
            "goals": 0,
            "projections": 0,
            "deliveries": 0,
            "work_items": 0,
            "authorizations": 0,
        })
        self.assertEqual(self.repository.audit_provenance_integrity(), [])

    async def test_completion_source_erasure_removes_transition_affected_goal(
        self,
    ) -> None:
        task_name = "ECE 210 Lab Completion Erasure"
        goal, _ = await self._commitment(
            task_name=task_name,
            entry_id="ece210-completion-erasure",
            deadline_at=datetime.now(UTC) + timedelta(hours=3),
        )
        completed = await self._interaction_service(
            output="Completion recorded.", broker=True
        ).interact(InteractionCommand(
            message=f"I completed {task_name}",
            privacy_class=PrivacyClass.NORMAL,
            memory_eligible=True,
            channel="web",
            idempotency_key=f"stage15-completion-erasure-{uuid.uuid4()}",
        ))

        erased = self.repository.erase_source_event_derivatives(
            owner_id=self.owner_id,
            source_event_id=completed.user_event_id,
        )

        self.assertEqual(erased["goals"], 1)
        self.assertEqual(erased["goal_transition_evidence"], 1)
        self.assertEqual(erased["commitment_projections"], 2)
        with self.repository.pool.connection() as connection:
            raw_source_count = connection.execute(
                "SELECT count(*) AS value FROM havre.events "
                "WHERE owner_id=%s AND event_id=%s",
                (self.owner_id, completed.user_event_id),
            ).fetchone()["value"]
            goal_count = connection.execute(
                "SELECT count(*) AS value FROM havre.goals "
                "WHERE owner_id=%s AND goal_id=%s",
                (self.owner_id, goal.goal_id),
            ).fetchone()["value"]
            evidence_count = connection.execute(
                "SELECT count(*) AS value FROM havre.goal_transition_evidence "
                "WHERE owner_id=%s AND source_event_id=%s",
                (self.owner_id, completed.user_event_id),
            ).fetchone()["value"]
        self.assertEqual(raw_source_count, 1)
        self.assertEqual(goal_count, 0)
        self.assertEqual(evidence_count, 0)
        self.assertEqual(self.repository.audit_provenance_integrity(), [])


if __name__ == "__main__":
    unittest.main()
