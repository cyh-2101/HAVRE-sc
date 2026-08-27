from __future__ import annotations

import os
import unittest
import uuid
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from fastapi.testclient import TestClient

from companion.events import (
    EventEnvelope,
    EventType,
    InterventionLifecyclePayload,
    SceneSessionLifecyclePayload,
    SceneSignalPayload,
)
from companion.identity import IdentityLoader
from companion.evidence import EvidenceRef, EvidenceRelation, EvidenceSourceKind
from companion.persistence import PostgresRepository, apply_migrations
from companion.persistence.scenes import ScenePostgresStore
from companion.policy import PrivacyClass, combine_policies
from companion.policy.intervention import (
    AvoidanceAssessment,
    CoercionAssessment,
    DangerAssessment,
    EnergyAssessment,
    GoalAlignment,
    GoalUrgency,
    InterventionBranch,
    SceneSignalType,
)
from companion.scenes.models import (
    OutcomeHelpfulness,
    OutcomeTriState,
    SceneGoal,
    ScenePhase,
    SceneRecord,
    SceneRecordType,
    SceneSituation,
    SceneStatus,
)
from evals.scene_evaluation import run_scene_policy_evaluation
from services.api.app import create_app
from services.api.settings import Settings
from scripts.audit_stage5_fk_indexes import audit_stage5_fk_indexes


DATABASE_URL = os.getenv("HAVRE_TEST_DATABASE_URL")
PROJECT_ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(DATABASE_URL, "HAVRE_TEST_DATABASE_URL is required")
class Stage5PostgresIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        assert DATABASE_URL is not None
        apply_migrations(DATABASE_URL, PROJECT_ROOT / "db" / "migrations")
        cls.identity = IdentityLoader(PROJECT_ROOT / "identity").load()
        cls.owner_id = uuid.uuid4()
        cls.second_owner_id = uuid.uuid4()
        cls.repository = PostgresRepository(DATABASE_URL)
        cls.repository.open()
        for owner_id in (cls.owner_id, cls.second_owner_id):
            cls.repository.bootstrap_owner_and_identity(
                owner_id=owner_id, identity=cls.identity
            )
        cls.store = ScenePostgresStore(
            repository=cls.repository,
            owner_id=cls.owner_id,
            identity=cls.identity,
        )
        cls.second_store = ScenePostgresStore(
            repository=cls.repository,
            owner_id=cls.second_owner_id,
            identity=cls.identity,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.repository.close()

    def _create(self, *, key: str | None = None):
        return self.store.create(
            scene_type="difficult_conversation",
            situation=SceneSituation(
                summary="Synthetic Web simulation",
                known_facts=("The user chose this scenario",),
                uncertainty_notes=("No real-world outcome is assumed",),
            ),
            planned_goal=SceneGoal(
                objective="State one boundary",
                minimum_success="Say the opening sentence",
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
            planned_start_at=None,
            session_id=None,
            idempotency_key=key or f"stage5-create-{uuid.uuid4()}",
            traceparent=None,
        )

    def test_full_before_during_after_chain_is_durable_and_auditable(self) -> None:
        created = self._create()
        scene_id = created.scene.scene_session.scene_session_id
        self.assertEqual(created.decision.branch, InterventionBranch.MINIMUM_ACTION)
        self.assertFalse(created.decision.outreach_authorized)
        self.assertEqual(created.scene.scene_session.phase, ScenePhase.BEFORE)

        started = self.store.transition(
            scene_session_id=scene_id,
            expected_revision=1,
            action="start",
            reason="Start synthetic Web simulation",
            terminal_status=None,
            idempotency_key=f"stage5-start-{uuid.uuid4()}",
            traceparent=None,
        )
        self.assertEqual(started.scene.scene_session.revision, 2)
        signalled = self.store.signal(
            scene_session_id=scene_id,
            expected_revision=2,
            signal_type=SceneSignalType.FROZEN,
            danger=DangerAssessment.LOW,
            avoidance=AvoidanceAssessment.HIGH,
            energy=EnergyAssessment.ADEQUATE,
            coercion=CoercionAssessment.ABSENT,
            goal_alignment=GoalAlignment.ACTIVE_MEANINGFUL,
            goal_urgency=GoalUrgency.NORMAL,
            privacy_class=PrivacyClass.LOCAL_ONLY,
            memory_eligible=False,
            occurred_at=datetime.now(UTC),
            uncertainty_note="Synthetic signal",
            idempotency_key=f"stage5-signal-{uuid.uuid4()}",
            traceparent=None,
        )
        self.assertEqual(signalled.decision.branch, InterventionBranch.MINIMUM_ACTION)
        action = self.store.record_action(
            scene_session_id=scene_id,
            expected_revision=2,
            action_text="Said the opening sentence",
            action_attempted=OutcomeTriState.YES,
            occurred_at=datetime.now(UTC),
            privacy_class=PrivacyClass.LOCAL_ONLY,
            memory_eligible=False,
            uncertainty_note=None,
            idempotency_key=f"stage5-action-{uuid.uuid4()}",
            traceparent=None,
        )
        self.assertIsNone(action.decision)
        after = self.store.transition(
            scene_session_id=scene_id,
            expected_revision=2,
            action="after",
            reason="Move simulated Scene to reflection",
            terminal_status=None,
            idempotency_key=f"stage5-after-{uuid.uuid4()}",
            traceparent=None,
        )
        self.assertEqual(after.decision.branch, InterventionBranch.REFLECTION)
        self.assertEqual(after.scene.scene_session.phase, ScenePhase.AFTER)
        self.store.record_outcome(
            scene_session_id=scene_id,
            expected_revision=3,
            outcome_text="The simulated listener paused and responded",
            occurred_at=datetime.now(UTC),
            privacy_class=PrivacyClass.LOCAL_ONLY,
            memory_eligible=False,
            uncertainty_note="Self-report in a synthetic flow",
            idempotency_key=f"stage5-outcome-{uuid.uuid4()}",
            traceparent=None,
        )
        reflected = self.store.reflect(
            scene_session_id=scene_id,
            expected_revision=3,
            reflection_text="The prediction was worse than the observed simulation",
            next_adjustment="Use the same opening next time",
            planned_scene_status="completed",
            helpfulness=OutcomeHelpfulness.HELPFUL,
            too_passive=OutcomeTriState.NO,
            too_forceful=OutcomeTriState.NO,
            later_regret="no",
            privacy_class=PrivacyClass.LOCAL_ONLY,
            memory_eligible=False,
            consented=True,
            idempotency_key=f"stage5-reflect-{uuid.uuid4()}",
            traceparent=None,
        )
        self.assertIsNotNone(reflected.outcome_observation)
        self.assertFalse(reflected.outcome_observation.data_policy.training_eligible)
        closed = self.store.transition(
            scene_session_id=scene_id,
            expected_revision=3,
            action="close",
            reason="Complete synthetic Web simulation",
            terminal_status="completed",
            idempotency_key=f"stage5-close-{uuid.uuid4()}",
            traceparent=None,
        )
        self.assertEqual(closed.scene.scene_session.phase, ScenePhase.CLOSED)
        self.assertEqual(closed.scene.scene_session.status, SceneStatus.COMPLETED)
        self.assertEqual(
            [record.record_type.value for record in closed.scene.records],
            [
                "intervention",
                "signal",
                "intervention",
                "action",
                "intervention",
                "outcome",
                "reflection",
            ],
        )
        self.assertEqual(len(closed.scene.intervention_decisions), 3)
        self.assertEqual(len(closed.scene.outcome_observations), 1)
        self.assertTrue(
            all(
                decision.outreach_authorized is False
                for decision in closed.scene.intervention_decisions
            )
        )
        with self.repository.pool.connection() as connection:
            trace_counts = connection.execute(
                """
                SELECT count(DISTINCT request.request_id) AS requests,
                       count(span.span_id) AS spans
                FROM havre.interaction_requests AS request
                JOIN havre.spans AS span ON span.trace_id = request.trace_id
                WHERE request.owner_id = %s AND request.request_kind = 'scene_command'
                  AND request.request_id IN (
                      SELECT event.request_id FROM havre.events AS event
                      WHERE event.owner_id = %s AND event.scene_session_id = %s
                  )
                """,
                (self.owner_id, self.owner_id, scene_id),
            ).fetchone()
        self.assertEqual(trace_counts["requests"], 8)
        self.assertEqual(trace_counts["spans"], 8)
        self.assertEqual(self.repository.audit_provenance_integrity(), [])

    def test_create_is_idempotent_and_conflicts_on_changed_input(self) -> None:
        key = f"stage5-idempotency-{uuid.uuid4()}"
        first = self._create(key=key)
        replay = self._create(key=key)
        self.assertEqual(
            first.scene.scene_session.scene_session_id,
            replay.scene.scene_session.scene_session_id,
        )
        self.assertTrue(replay.idempotent_replay)
        with self.assertRaisesRegex(ValueError, "different Scene command"):
            self.store.create(
                scene_type="different_scene",
                situation=SceneSituation(summary="Changed"),
                planned_goal=SceneGoal(objective="Changed", minimum_success="Changed"),
                anticipated_triggers=(),
                danger=DangerAssessment.LOW,
                avoidance=AvoidanceAssessment.LOW,
                energy=EnergyAssessment.ADEQUATE,
                coercion=CoercionAssessment.ABSENT,
                goal_alignment=GoalAlignment.ACTIVE_MEANINGFUL,
                goal_urgency=GoalUrgency.NORMAL,
                privacy_class=PrivacyClass.LOCAL_ONLY,
                memory_eligible=False,
                planned_start_at=None,
                session_id=None,
                idempotency_key=key,
                traceparent=None,
            )

    def test_during_action_requires_a_fresh_during_intervention(self) -> None:
        created = self._create()
        scene_id = created.scene.scene_session.scene_session_id
        self.store.transition(
            scene_session_id=scene_id,
            expected_revision=1,
            action="start",
            reason="Start without a signal",
            terminal_status=None,
            idempotency_key=f"stage5-start-without-signal-{uuid.uuid4()}",
            traceparent=None,
        )
        with self.assertRaisesRegex(ValueError, "During intervention"):
            self.store.record_action(
                scene_session_id=scene_id,
                expected_revision=2,
                action_text="Premature action",
                action_attempted=OutcomeTriState.UNKNOWN,
                occurred_at=datetime.now(UTC),
                privacy_class=PrivacyClass.LOCAL_ONLY,
                memory_eligible=False,
                uncertainty_note=None,
                idempotency_key=f"stage5-action-without-signal-{uuid.uuid4()}",
                traceparent=None,
            )

    def test_planned_scene_can_be_cancelled_without_fabricating_a_start(self) -> None:
        created = self._create()
        scene = created.scene.scene_session
        cancelled = self.store.transition(
            scene_session_id=scene.scene_session_id,
            expected_revision=1,
            action="close",
            reason="Owner cancelled before starting",
            terminal_status="cancelled",
            idempotency_key=f"stage5-cancel-planned-{uuid.uuid4()}",
            traceparent=None,
        )
        root = cancelled.scene.scene_session
        self.assertEqual(root.phase, ScenePhase.CLOSED)
        self.assertEqual(root.status, SceneStatus.CANCELLED)
        self.assertIsNone(root.started_at)
        self.assertIsNotNone(root.ended_at)

    def test_owner_isolation_immutability_and_outreach_constraints(self) -> None:
        created = self._create()
        scene_id = created.scene.scene_session.scene_session_id
        with self.assertRaises(LookupError):
            self.second_store.get(scene_session_id=scene_id)
        decision_id = created.decision.intervention_decision_id
        with self.repository.pool.connection() as connection:
            with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
                connection.execute(
                    "UPDATE havre.intervention_decisions SET guidance = 'tampered' "
                    "WHERE intervention_decision_id = %s",
                    (decision_id,),
                )
            connection.rollback()
            with self.assertRaises(psycopg.errors.CheckViolation):
                connection.execute("SET LOCAL session_replication_role = replica")
                connection.execute(
                    "UPDATE havre.intervention_decisions SET outreach_authorized = true "
                    "WHERE intervention_decision_id = %s",
                    (decision_id,),
                )
            connection.rollback()
            bypass_delivery_tables = connection.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'havre'
                  AND table_name IN ('outreach_deliveries', 'scene_outreach_deliveries')
                """
            ).fetchall()
            self.assertEqual(bypass_delivery_tables, [])

    def test_policy_evaluation_report_persists_immutably(self) -> None:
        report = run_scene_policy_evaluation(
            fixture_path=PROJECT_ROOT / "evals" / "fixtures" / "scene_policy_cases_v1.json",
            identity=self.identity,
            persistence=self.repository,
            project_root=PROJECT_ROOT,
        )
        with self.repository.pool.connection() as connection:
            row = connection.execute(
                "SELECT * FROM havre.scene_evaluation_runs WHERE evaluation_run_id = %s",
                (report.evaluation_run_id,),
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertFalse(row["binding_evaluation"])
            self.assertEqual(row["gate_status"], "not_evaluated")
            with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
                connection.execute(
                    "UPDATE havre.scene_evaluation_runs SET suite_version = 'tampered' "
                    "WHERE evaluation_run_id = %s",
                    (report.evaluation_run_id,),
                )
            connection.rollback()

    def test_stage5_foreign_keys_have_matching_indexes(self) -> None:
        assert DATABASE_URL is not None
        self.assertEqual(audit_stage5_fk_indexes(DATABASE_URL), [])

    def test_intervention_decision_cannot_commit_without_exact_provenance(self) -> None:
        created = self._create()
        scene = created.scene.scene_session
        ingress = self.store._ingress(
            operation="stage5_missing_provenance_probe",
            semantic_input={"scene_session_id": scene.scene_session_id},
            idempotency_key=f"stage5-missing-provenance-{uuid.uuid4()}",
            session_id=scene.opened_session_id,
            traceparent=None,
        )
        evidence = (
            EvidenceRef(
                source_kind=EvidenceSourceKind.EVENT,
                source_id=scene.created_event_id,
                relation=EvidenceRelation.SUPPORTS,
            ),
        )
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
            with self.repository.pool.connection() as connection, connection.transaction():
                reserved, _ = self.store._reserve(connection, ingress)
                self.assertTrue(reserved)
                decision, _, _ = self.store._persist_intervention(
                    connection,
                    scene=scene,
                    ingress=ingress,
                    input_event_id=scene.created_event_id,
                    input_record_id=None,
                    signal_type=None,
                    danger=DangerAssessment.LOW,
                    avoidance=AvoidanceAssessment.LOW,
                    energy=EnergyAssessment.ADEQUATE,
                    coercion=CoercionAssessment.ABSENT,
                    goal_alignment=GoalAlignment.ACTIVE_MEANINGFUL,
                    goal_urgency=GoalUrgency.NORMAL,
                    evidence=evidence,
                    policy=combine_policies((scene.data_policy,)),
                )
                connection.execute("SET LOCAL havre.privileged_erasure = 'on'")
                connection.execute(
                    "DELETE FROM havre.provenance_edges "
                    "WHERE owner_id = %s AND derived_kind = 'intervention_decision' "
                    "AND derived_id = %s",
                    (self.owner_id, decision.intervention_decision_id),
                )
        self.assertEqual(self.repository.audit_provenance_integrity(), [])

    def test_web_simulator_serves_and_calls_the_real_scene_api(self) -> None:
        assert DATABASE_URL is not None
        settings = Settings.from_env().model_copy(
            update={
                "database_url": DATABASE_URL,
                "owner_id": uuid.uuid4(),
                "provider_id": "deterministic-local",
            }
        )
        with TestClient(create_app(settings)) as client:
            page = client.get("/scene-simulator")
            self.assertEqual(page.status_code, 200)
            self.assertIn("cannot authorize outreach", page.text)
            self.assertIn("/v1/scenes", page.text)
            response = client.post(
                "/v1/scenes",
                headers={"Idempotency-Key": f"stage5-web-{uuid.uuid4()}"},
                json={
                    "scene_type": "difficult_conversation",
                    "situation": {"summary": "Synthetic browser flow"},
                    "planned_goal": {
                        "objective": "State one boundary",
                        "minimum_success": "Say the opening sentence",
                    },
                    "danger": "low",
                    "avoidance": "present",
                    "energy": "adequate",
                    "coercion": "absent",
                    "goal_alignment": "active_meaningful",
                    "goal_urgency": "normal",
                    "privacy_class": "LOCAL_ONLY",
                    "memory_eligible": False,
                },
            )
            self.assertEqual(response.status_code, 201, response.text)
            payload = response.json()
            self.assertEqual(payload["scene"]["scene_session"]["phase"], "before")
            self.assertFalse(payload["decision"]["outreach_authorized"])
            scene_id = payload["scene"]["scene_session"]["scene_session_id"]
            started = client.post(
                f"/v1/scenes/{scene_id}/transition",
                headers={"Idempotency-Key": f"stage5-web-start-{uuid.uuid4()}"},
                json={
                    "expected_revision": 1,
                    "action": "start",
                    "reason": "Start browser simulation",
                },
            )
            self.assertEqual(started.status_code, 200, started.text)
            fetched = client.get(f"/v1/scenes/{scene_id}")
            self.assertEqual(fetched.status_code, 200)
            self.assertEqual(fetched.json()["scene_session"]["phase"], "during")

    def test_scene_source_erasure_closes_stage5_derivatives_but_keeps_raw_source(self) -> None:
        created = self._create()
        scene = created.scene.scene_session
        counts = self.repository.erase_source_event_derivatives(
            owner_id=self.owner_id,
            source_event_id=scene.created_event_id,
        )
        self.assertEqual(counts["scene_sessions"], 1)
        self.assertEqual(counts["scene_records"], 1)
        self.assertEqual(counts["intervention_decisions"], 1)
        self.assertEqual(counts["intervention_events"], 1)
        self.assertEqual(counts["assistant_events"], 1)
        with self.assertRaises(LookupError):
            self.store.get(scene_session_id=scene.scene_session_id)
        with self.repository.pool.connection() as connection:
            source = connection.execute(
                "SELECT event_id, scene_session_id FROM havre.events "
                "WHERE owner_id = %s AND event_id = %s",
                (self.owner_id, scene.created_event_id),
            ).fetchone()
            self.assertIsNotNone(source)
            self.assertIsNone(source["scene_session_id"])
        self.assertEqual(self.repository.audit_provenance_integrity(), [])

    def test_full_scene_erasure_closes_cycles_and_rehashes_retained_events(self) -> None:
        created = self._create()
        scene_id = created.scene.scene_session.scene_session_id
        self.store.transition(
            scene_session_id=scene_id,
            expected_revision=1,
            action="start",
            reason="Start erasure regression Scene",
            terminal_status=None,
            idempotency_key=f"stage5-erasure-start-{uuid.uuid4()}",
            traceparent=None,
        )
        signalled = self.store.signal(
            scene_session_id=scene_id,
            expected_revision=2,
            signal_type=SceneSignalType.FROZEN,
            danger=DangerAssessment.LOW,
            avoidance=AvoidanceAssessment.HIGH,
            energy=EnergyAssessment.ADEQUATE,
            coercion=CoercionAssessment.ABSENT,
            goal_alignment=GoalAlignment.ACTIVE_MEANINGFUL,
            goal_urgency=GoalUrgency.NORMAL,
            privacy_class=PrivacyClass.LOCAL_ONLY,
            memory_eligible=False,
            occurred_at=datetime.now(UTC),
            uncertainty_note="Synthetic erasure signal",
            idempotency_key=f"stage5-erasure-signal-{uuid.uuid4()}",
            traceparent=None,
        )
        self.store.record_action(
            scene_session_id=scene_id,
            expected_revision=2,
            action_text="Synthetic erasure action",
            action_attempted=OutcomeTriState.YES,
            occurred_at=datetime.now(UTC),
            privacy_class=PrivacyClass.LOCAL_ONLY,
            memory_eligible=False,
            uncertainty_note=None,
            idempotency_key=f"stage5-erasure-action-{uuid.uuid4()}",
            traceparent=None,
        )
        self.store.transition(
            scene_session_id=scene_id,
            expected_revision=2,
            action="after",
            reason="Enter After for erasure regression",
            terminal_status=None,
            idempotency_key=f"stage5-erasure-after-{uuid.uuid4()}",
            traceparent=None,
        )
        self.store.record_outcome(
            scene_session_id=scene_id,
            expected_revision=3,
            outcome_text="Synthetic erasure outcome",
            occurred_at=datetime.now(UTC),
            privacy_class=PrivacyClass.LOCAL_ONLY,
            memory_eligible=False,
            uncertainty_note=None,
            idempotency_key=f"stage5-erasure-outcome-{uuid.uuid4()}",
            traceparent=None,
        )
        self.store.reflect(
            scene_session_id=scene_id,
            expected_revision=3,
            reflection_text="Synthetic erasure reflection",
            next_adjustment=None,
            planned_scene_status="completed",
            helpfulness=OutcomeHelpfulness.UNCERTAIN,
            too_passive=OutcomeTriState.UNKNOWN,
            too_forceful=OutcomeTriState.UNKNOWN,
            later_regret="not_asked",
            privacy_class=PrivacyClass.LOCAL_ONLY,
            memory_eligible=False,
            consented=True,
            idempotency_key=f"stage5-erasure-reflect-{uuid.uuid4()}",
            traceparent=None,
        )
        with self.repository.pool.connection() as connection:
            rows = connection.execute(
                "SELECT event_id, event_type FROM havre.events "
                "WHERE owner_id = %s AND scene_session_id = %s",
                (self.owner_id, scene_id),
            ).fetchall()
        terminal_ids = {
            row["event_id"]
            for row in rows
            if row["event_type"] in {"INTERVENTION_DECIDED", "ASSISTANT_MESSAGE"}
        }
        retained_ids = {row["event_id"] for row in rows} - terminal_ids
        counts = self.repository.erase_source_event_derivatives(
            owner_id=self.owner_id,
            source_event_id=created.scene.scene_session.created_event_id,
        )
        self.assertEqual(counts["scene_sessions"], 1)
        self.assertEqual(counts["scene_records"], 7)
        self.assertEqual(counts["intervention_decisions"], 3)
        self.assertEqual(counts["guidance_outcome_observations"], 1)
        self.assertEqual(counts["intervention_events"], 3)
        self.assertEqual(counts["assistant_events"], 3)
        for event_id in retained_ids:
            event = self.repository.event_by_id(
                owner_id=self.owner_id, event_id=event_id
            )
            self.assertIsNotNone(event)
            self.assertIsNone(event.scene_session_id)
            self.assertNotIn(event.causation_event_id, terminal_ids)
        for event_id in terminal_ids:
            self.assertIsNone(
                self.repository.event_by_id(
                    owner_id=self.owner_id, event_id=event_id
                )
            )
        self.assertEqual(self.repository.audit_provenance_integrity(), [])

    def test_database_rejects_during_signal_record_while_scene_is_before(self) -> None:
        created = self._create()
        scene = created.scene.scene_session
        ingress = self.store._ingress(
            operation="stage5_before_signal_probe",
            semantic_input={"scene_session_id": scene.scene_session_id},
            idempotency_key=f"stage5-before-signal-{uuid.uuid4()}",
            session_id=scene.opened_session_id,
            traceparent=None,
        )
        record_id = uuid.uuid4()
        occurred_at = datetime.now(UTC)
        event = EventEnvelope(
            event_type=EventType.USER_SIGNAL,
            owner_id=self.owner_id,
            session_id=scene.opened_session_id,
            scene_session_id=scene.scene_session_id,
            request_id=ingress.request_id,
            trace_id=ingress.trace.trace_id,
            causation_event_id=scene.last_event_id,
            data_policy=scene.data_policy,
            payload=SceneSignalPayload(
                scene_session_id=scene.scene_session_id,
                scene_record_id=record_id,
                signal_type="frozen",
                danger="low",
                avoidance="high",
                energy="adequate",
                coercion="absent",
                goal_alignment="active_meaningful",
                goal_urgency="normal",
                occurred_at=occurred_at,
            ),
        )
        record = SceneRecord(
            scene_record_id=record_id,
            owner_id=self.owner_id,
            scene_session_id=scene.scene_session_id,
            record_type=SceneRecordType.SIGNAL,
            phase="during",
            sequence_number=2,
            occurred_at=occurred_at,
            event_id=event.event_id,
            source="web_simulation",
            content={
                "signal_type": "frozen",
                "danger": "low",
                "avoidance": "high",
                "energy": "adequate",
                "coercion": "absent",
                "goal_alignment": "active_meaningful",
                "goal_urgency": "normal",
                "input_method": "web_simulation",
            },
            trace_id=ingress.trace.trace_id,
            data_policy=scene.data_policy,
        )
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
            with self.repository.pool.connection() as connection, connection.transaction():
                reserved, _ = self.store._reserve(connection, ingress)
                self.assertTrue(reserved)
                PostgresRepository._insert_event(connection, event)
                self.store._insert_record(connection, record)

    def test_database_rejects_caller_timed_scene_projection_with_stale_hash(self) -> None:
        created = self._create()
        scene = created.scene.scene_session
        ingress = self.store._ingress(
            operation="stage5_projection_tamper_probe",
            semantic_input={"scene_session_id": scene.scene_session_id},
            idempotency_key=f"stage5-projection-tamper-{uuid.uuid4()}",
            session_id=scene.opened_session_id,
            traceparent=None,
        )
        lifecycle_event = EventEnvelope(
            event_type=EventType.SCENE_SESSION_STARTED,
            owner_id=self.owner_id,
            session_id=scene.opened_session_id,
            scene_session_id=scene.scene_session_id,
            request_id=ingress.request_id,
            trace_id=ingress.trace.trace_id,
            causation_event_id=scene.last_event_id,
            data_policy=scene.data_policy,
            payload=SceneSessionLifecyclePayload(
                scene_session_id=scene.scene_session_id,
                scene_revision=2,
                action="started",
                phase="during",
                status="active",
                reason="Attempt a caller-timed projection",
            ),
        )
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
            with self.repository.pool.connection() as connection, connection.transaction():
                reserved, _ = self.store._reserve(connection, ingress)
                self.assertTrue(reserved)
                PostgresRepository._insert_event(connection, lifecycle_event)
                connection.execute(
                    """
                    UPDATE havre.scene_sessions
                    SET phase = 'during', status = 'active',
                        started_at = '2099-01-01T00:00:00Z'::timestamptz,
                        revision = 2, last_event_id = %s,
                        content_hash = %s,
                        updated_at = transaction_timestamp()
                    WHERE owner_id = %s AND scene_session_id = %s
                    """,
                    (
                        lifecycle_event.event_id,
                        scene.content_hash,
                        self.owner_id,
                        scene.scene_session_id,
                    ),
                )

    def test_database_rejects_mixed_decision_and_guidance_record(self) -> None:
        created = self._create()
        scene_id = created.scene.scene_session.scene_session_id
        self.store.transition(
            scene_session_id=scene_id,
            expected_revision=1,
            action="start",
            reason="Start mixed-reference regression Scene",
            terminal_status=None,
            idempotency_key=f"stage5-mixed-start-{uuid.uuid4()}",
            traceparent=None,
        )
        signalled = self.store.signal(
            scene_session_id=scene_id,
            expected_revision=2,
            signal_type=SceneSignalType.FROZEN,
            danger=DangerAssessment.LOW,
            avoidance=AvoidanceAssessment.HIGH,
            energy=EnergyAssessment.ADEQUATE,
            coercion=CoercionAssessment.ABSENT,
            goal_alignment=GoalAlignment.ACTIVE_MEANINGFUL,
            goal_urgency=GoalUrgency.NORMAL,
            privacy_class=PrivacyClass.LOCAL_ONLY,
            memory_eligible=False,
            occurred_at=datetime.now(UTC),
            uncertainty_note=None,
            idempotency_key=f"stage5-mixed-signal-{uuid.uuid4()}",
            traceparent=None,
        )
        scene = signalled.scene.scene_session
        signal_record = next(
            record
            for record in signalled.scene.records
            if record.record_type is SceneRecordType.SIGNAL
        )
        before_decision = created.decision
        during_decision = signalled.decision
        ingress = self.store._ingress(
            operation="stage5_mixed_reference_probe",
            semantic_input={"scene_session_id": scene_id},
            idempotency_key=f"stage5-mixed-reference-{uuid.uuid4()}",
            session_id=scene.opened_session_id,
            traceparent=None,
        )
        record_id = uuid.uuid4()
        forged_event = EventEnvelope(
            event_type=EventType.INTERVENTION_DECIDED,
            owner_id=self.owner_id,
            session_id=scene.opened_session_id,
            scene_session_id=scene_id,
            request_id=ingress.request_id,
            trace_id=ingress.trace.trace_id,
            causation_event_id=signal_record.event_id,
            data_policy=during_decision.data_policy,
            payload=InterventionLifecyclePayload(
                scene_session_id=scene_id,
                intervention_decision_id=before_decision.intervention_decision_id,
                scene_record_id=record_id,
                input_record_id=signal_record.scene_record_id,
                guidance_event_id=signalled.guidance_event_id,
                branch=before_decision.branch.value,
            ),
        )
        forged_record = SceneRecord(
            scene_record_id=record_id,
            owner_id=self.owner_id,
            scene_session_id=scene_id,
            record_type=SceneRecordType.INTERVENTION,
            phase="during",
            sequence_number=4,
            occurred_at=datetime.now(UTC),
            event_id=forged_event.event_id,
            assistant_event_id=signalled.guidance_event_id,
            artifact_kind="intervention_decision",
            artifact_id=before_decision.intervention_decision_id,
            artifact_revision=1,
            causal_predecessor_id=signal_record.scene_record_id,
            source="intervention_policy",
            content={
                "branch": before_decision.branch.value,
                "recommended_intervention": before_decision.recommended_intervention,
                "guidance": before_decision.guidance,
                "minimum_action": before_decision.minimum_action,
                "reason_codes": list(before_decision.reason_codes),
                "outreach_authorized": False,
                "simulation_only": True,
            },
            trace_id=ingress.trace.trace_id,
            data_policy=during_decision.data_policy,
        )
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
            with self.repository.pool.connection() as connection, connection.transaction():
                reserved, _ = self.store._reserve(connection, ingress)
                self.assertTrue(reserved)
                PostgresRepository._insert_event(connection, forged_event)
                self.store._insert_record(connection, forged_record)
