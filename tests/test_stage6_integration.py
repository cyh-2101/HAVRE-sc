from __future__ import annotations

import os
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

import psycopg
from fastapi.testclient import TestClient

from companion.identity import IdentityLoader
from companion.persistence import PostgresRepository, apply_migrations
from companion.persistence.proactive import ProactivePostgresStore
from companion.policy import DataPolicy, PrivacyClass
from companion.proactive import (
    InterruptionOutcome,
    ProactivePreferenceRevision,
    ProactiveWorkCommand,
)
from services.api.app import create_app
from services.api.settings import Settings


DATABASE_URL = os.getenv("HAVRE_TEST_DATABASE_URL")
PROJECT_ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(DATABASE_URL, "HAVRE_TEST_DATABASE_URL is required")
class Stage6PostgresIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        assert DATABASE_URL is not None
        apply_migrations(DATABASE_URL, PROJECT_ROOT / "db" / "migrations")
        cls.identity = IdentityLoader(PROJECT_ROOT / "identity").load()
        cls.owner = uuid.uuid4()
        cls.repository = PostgresRepository(DATABASE_URL)
        cls.repository.open()
        cls.repository.bootstrap_owner_and_identity(owner_id=cls.owner, identity=cls.identity)
        cls.store = ProactivePostgresStore(
            repository=cls.repository, owner_id=cls.owner, identity=cls.identity
        )
        cls.preference = ProactivePreferenceRevision(
            owner_id=cls.owner, revision=1, global_enabled=True,
            category_permissions={"owner_reminder": "allowed"},
            allowed_channels=("web_inbox",), global_budget_per_24h=4,
            category_budget_per_24h={"owner_reminder": 4}, cooldown_seconds=3600,
            authorization_ref="stage6-postgres-synthetic-fixture",
        )
        cls.store.save_preference(cls.preference)
        cls.disabled = ProactivePreferenceRevision(owner_id=cls.owner, revision=2)
        cls.store.save_preference(cls.disabled)
        cls.high_capacity = ProactivePreferenceRevision(
            owner_id=cls.owner,
            revision=4,
            global_enabled=True,
            category_permissions={"owner_reminder": "allowed"},
            allowed_channels=("web_inbox",),
            global_budget_per_24h=24,
            category_budget_per_24h={"owner_reminder": 24},
            cooldown_seconds=60,
            authorization_ref="stage6-acceptance-correction-fixture",
        )
        cls.store.save_preference(cls.high_capacity)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.repository.close()

    def _execute(
        self, *, key: str, preference_revision: int = 1,
        dedupe: str | None = None, now: datetime | None = None,
        data_policy: DataPolicy | None = None,
    ):
        now = now or datetime.now(UTC)
        return self.store.execute_fixture(
            trigger_type="owner_requested_reminder",
            source_kind="owner_reminder",
            source_refs=(f"owner-reminder/{key}",),
            subject_refs=(f"goal/{key}",),
            category="owner_reminder",
            reason_code="owner_requested_fixture",
            reason_summary="Review the owner-chosen synthetic goal",
            intended_benefit="Support an explicitly chosen commitment",
            data_policy=data_policy or DataPolicy.owner_default(
                PrivacyClass.LOCAL_ONLY, memory_eligible=False
            ),
            preference_revision=preference_revision,
            idempotency_key=key,
            observed_at=now,
            earliest_eligible_at=now - timedelta(seconds=1),
            expires_at=now + timedelta(hours=2),
            deduplication_key=dedupe or f"dedupe:{key}",
        )

    def test_complete_local_inbox_chain_is_durable_and_idempotent(self) -> None:
        key = f"stage6-send-{uuid.uuid4()}"
        command_time = datetime.now(UTC)
        command_policy = DataPolicy.owner_default(
            PrivacyClass.LOCAL_ONLY, memory_eligible=False
        )
        result = self._execute(key=key, now=command_time, data_policy=command_policy)
        self.assertEqual(result.decision.decision, InterruptionOutcome.SEND_NOW)
        self.assertIsNotNone(result.context_pack)
        self.assertIsNotNone(result.rendering)
        self.assertEqual(result.delivery_attempt.status, "delivered")
        self.assertIsNotNone(result.assistant_event_id)
        self.assertEqual(
            result.lifecycle_events,
            (
                "PROACTIVE_TRIGGER_RECORDED", "PROACTIVE_PROPOSAL_CREATED",
                "PROACTIVE_POLICY_DECIDED", "PROACTIVE_MESSAGE_RENDERED",
                "PROACTIVE_DELIVERY_ATTEMPTED", "PROACTIVE_MESSAGE_DELIVERED",
            ),
        )
        replay = self._execute(key=key, now=command_time, data_policy=command_policy)
        self.assertTrue(replay.idempotent_replay)
        self.assertEqual(replay.proposal.proposal_id, result.proposal.proposal_id)
        with self.repository.pool.connection() as connection:
            row = connection.execute(
                """
                SELECT attempt.external_delivery_authorized, attempt.simulation_only,
                       event.recorded_at, attempt.visible_at,
                       event.payload->>'interaction_mode' AS interaction_mode,
                       count(*) OVER () AS rows
                FROM havre.proactive_delivery_attempts AS attempt
                JOIN havre.proactive_inbox_messages AS inbox
                  ON inbox.owner_id = attempt.owner_id
                 AND inbox.delivery_attempt_id = attempt.delivery_attempt_id
                JOIN havre.events AS event
                  ON event.owner_id = inbox.owner_id
                 AND event.event_id = inbox.assistant_event_id
                WHERE attempt.owner_id = %s AND attempt.proposal_id = %s
                """,
                (self.owner, result.proposal.proposal_id),
            ).fetchone()
            self.assertFalse(row["external_delivery_authorized"])
            self.assertTrue(row["simulation_only"])
            self.assertEqual(row["interaction_mode"], "proactive_web_inbox")
            self.assertGreaterEqual(row["recorded_at"], row["visible_at"])
            self.assertEqual(row["rows"], 1)

    def test_default_disabled_stops_before_rendering_and_event(self) -> None:
        owner = uuid.uuid4()
        self.repository.bootstrap_owner_and_identity(owner_id=owner, identity=self.identity)
        store = ProactivePostgresStore(
            repository=self.repository, owner_id=owner, identity=self.identity
        )
        disabled = ProactivePreferenceRevision(owner_id=owner, revision=1)
        store.save_preference(disabled)
        now = datetime.now(UTC)
        result = store.execute_fixture(
            trigger_type="owner_requested_reminder",
            source_kind="owner_reminder",
            source_refs=(f"owner-reminder/{uuid.uuid4()}",),
            subject_refs=(),
            category="owner_reminder",
            reason_code="owner_requested_fixture",
            reason_summary="Disabled preference fixture",
            intended_benefit="Prove default-disabled execution",
            data_policy=DataPolicy.owner_default(
                PrivacyClass.LOCAL_ONLY, memory_eligible=False
            ),
            preference_revision=1,
            idempotency_key=f"stage6-drop-{uuid.uuid4()}",
            observed_at=now,
            earliest_eligible_at=now - timedelta(seconds=1),
            expires_at=now + timedelta(hours=2),
            deduplication_key=f"disabled-dedupe:{uuid.uuid4()}",
        )
        self.assertEqual(result.preference.preference_revision_id, disabled.preference_revision_id)
        self.assertEqual(result.decision.decision, InterruptionOutcome.DROP)
        self.assertIsNone(result.context_pack)
        self.assertIsNone(result.delivery_attempt)
        self.assertIsNone(result.assistant_event_id)

    def test_database_rejects_external_delivery_authority_forgery(self) -> None:
        result = self._execute(key=f"stage6-forge-{uuid.uuid4()}")
        assert DATABASE_URL is not None
        with psycopg.connect(DATABASE_URL) as connection:
            with self.assertRaises(psycopg.errors.CheckViolation):
                with connection.transaction():
                    connection.execute(
                        """
                        INSERT INTO havre.proactive_delivery_attempts (
                            delivery_attempt_id, schema_version, owner_id, proposal_id,
                            interruption_decision_id, rendering_id, channel,
                            adapter_version, idempotency_key, attempt_number, status,
                            retryable, provider_receipt_id, visible_at, trace_id,
                            simulation_only, external_delivery_authorized, payload,
                            content_hash, created_at
                        ) SELECT %s, 1, owner_id, proposal_id,
                                 interruption_decision_id, rendering_id, 'web_inbox',
                                 'local-web-inbox-v1', %s, 1, 'delivered', false,
                                 'forged', statement_timestamp(), trace_id,
                                 true, true, '{}'::jsonb,
                                 'sha256:' || repeat('0', 64), statement_timestamp()
                          FROM havre.proactive_delivery_attempts
                         WHERE owner_id = %s AND proposal_id = %s
                        """,
                        (uuid.uuid4(), f"forged:{uuid.uuid4()}", self.owner, result.proposal.proposal_id),
                    )

    def test_owner_scoped_lock_serializes_budget_one_concurrency(self) -> None:
        owner = uuid.uuid4()
        repository = PostgresRepository(DATABASE_URL)
        repository.open()
        try:
            repository.bootstrap_owner_and_identity(owner_id=owner, identity=self.identity)
            store = ProactivePostgresStore(
                repository=repository, owner_id=owner, identity=self.identity
            )
            store.save_preference(
                ProactivePreferenceRevision(
                    owner_id=owner,
                    revision=1,
                    global_enabled=True,
                    category_permissions={"owner_reminder": "allowed"},
                    allowed_channels=("web_inbox",),
                    global_budget_per_24h=1,
                    category_budget_per_24h={"owner_reminder": 1},
                    cooldown_seconds=60,
                    authorization_ref="stage6-budget-one-concurrency",
                )
            )
            barrier = Barrier(2)
            now = datetime.now(UTC)

            def execute(index: int):
                barrier.wait()
                return store.execute_fixture(
                    trigger_type="owner_requested_reminder",
                    source_kind="owner_reminder",
                    source_refs=(f"owner-reminder/concurrent-{index}",),
                    subject_refs=(f"goal/concurrent-{index}",),
                    category="owner_reminder",
                    reason_code="owner_requested_fixture",
                    reason_summary=f"Concurrent reminder {index}",
                    intended_benefit="Exercise serialized hard controls",
                    data_policy=DataPolicy.owner_default(
                        PrivacyClass.LOCAL_ONLY, memory_eligible=False
                    ),
                    preference_revision=1,
                    idempotency_key=f"concurrent-{index}-{uuid.uuid4()}",
                    observed_at=now,
                    earliest_eligible_at=now - timedelta(seconds=1),
                    expires_at=now + timedelta(hours=2),
                    deduplication_key=f"concurrent-dedupe-{index}",
                )

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(execute, (1, 2)))
            self.assertEqual(
                sum(
                    result.decision.decision is InterruptionOutcome.SEND_NOW
                    for result in results
                ),
                1,
            )
            self.assertEqual(
                sum(
                    result.decision.decision is InterruptionOutcome.DEFER
                    for result in results
                ),
                1,
            )
            with repository.pool.connection() as connection:
                delivered = connection.execute(
                    """
                    SELECT count(*) AS value
                    FROM havre.proactive_delivery_attempts
                    WHERE owner_id = %s AND status = 'delivered'
                    """,
                    (owner,),
                ).fetchone()["value"]
            self.assertEqual(delivered, 1)
        finally:
            repository.close()

    def test_owner_actions_suppress_or_defer_equivalent_followups(self) -> None:
        cases = (
            ("dismissed", None, InterruptionOutcome.DROP, "owner_control_suppressed"),
            ("stopped", None, InterruptionOutcome.DROP, "owner_control_suppressed"),
            (
                "non_response",
                None,
                InterruptionOutcome.DROP,
                "non_response_frequency_suppressed",
            ),
            (
                "snoozed",
                timedelta(minutes=30),
                InterruptionOutcome.DEFER,
                "owner_snoozed",
            ),
        )
        for action_type, snooze_delta, expected, reason_code in cases:
            with self.subTest(action_type=action_type):
                key = f"action-{action_type}-{uuid.uuid4()}"
                dedupe = f"action-dedupe-{uuid.uuid4()}"
                first = self._execute(
                    key=key, preference_revision=4, dedupe=dedupe
                )
                observed_at = datetime.now(UTC)
                action = self.store.record_owner_action(
                    proposal_id=first.proposal.proposal_id,
                    action_type=action_type,
                    idempotency_key=f"owner-action-{uuid.uuid4()}",
                    reason="Explicit local owner control fixture",
                    observed_at=observed_at,
                    snooze_until=(
                        observed_at + snooze_delta if snooze_delta else None
                    ),
                )
                replay = self.store.record_owner_action(
                    proposal_id=first.proposal.proposal_id,
                    action_type=action_type,
                    idempotency_key=action.idempotency_key,
                    reason="Explicit local owner control fixture",
                    observed_at=observed_at,
                    snooze_until=(
                        observed_at + snooze_delta if snooze_delta else None
                    ),
                )
                self.assertEqual(action.action_id, replay.action_id)
                followup = self._execute(
                    key=f"{key}-followup",
                    preference_revision=4,
                    dedupe=dedupe,
                )
                self.assertEqual(followup.decision.decision, expected)
                self.assertIn(reason_code, followup.decision.reason_codes)

    def test_response_linkage_and_delivery_reconciliation_are_exact(self) -> None:
        result = self._execute(
            key=f"response-link-{uuid.uuid4()}", preference_revision=4
        )
        reconciled = self.store.reconcile_delivery(
            proposal_id=result.proposal.proposal_id
        )
        self.assertEqual(reconciled["status"], "delivered")
        self.assertEqual(reconciled["assistant_event_id"], result.assistant_event_id)
        settings = Settings.from_env().model_copy(
            update={
                "database_url": DATABASE_URL,
                "owner_id": self.owner,
                "provider_id": "deterministic-local",
            }
        )
        response_key = f"proactive-response-{uuid.uuid4()}"
        with TestClient(create_app(settings)) as client:
            response = client.post(
                "/v1/interactions",
                headers={"Idempotency-Key": response_key},
                json={
                    "message": "This is an explicit linked local response.",
                    "privacy_class": "LOCAL_ONLY",
                    "memory_eligible": False,
                },
            )
            self.assertEqual(response.status_code, 201, response.text)
        with self.repository.pool.connection() as connection:
            response_event_id = connection.execute(
                """
                SELECT user_event_id FROM havre.interaction_requests
                WHERE owner_id = %s AND idempotency_key = %s
                """,
                (self.owner, response_key),
            ).fetchone()["user_event_id"]
        linked = self.store.record_owner_action(
            proposal_id=result.proposal.proposal_id,
            action_type="responded",
            idempotency_key=f"response-action-{uuid.uuid4()}",
            reason="Explicit response linkage fixture",
            observed_at=datetime.now(UTC),
            response_event_id=response_event_id,
        )
        self.assertEqual(linked.response_event_id, response_event_id)
        with self.assertRaises(psycopg.Error):
            self.store.record_owner_action(
                proposal_id=result.proposal.proposal_id,
                action_type="responded",
                idempotency_key=f"invalid-response-action-{uuid.uuid4()}",
                reason="Must reject assistant event as owner response",
                observed_at=datetime.now(UTC),
                response_event_id=result.assistant_event_id,
            )

    def test_queued_work_rechecks_current_preference_before_execution(self) -> None:
        owner = uuid.uuid4()
        self.repository.bootstrap_owner_and_identity(owner_id=owner, identity=self.identity)
        store = ProactivePostgresStore(
            repository=self.repository, owner_id=owner, identity=self.identity
        )
        enabled = ProactivePreferenceRevision(
            owner_id=owner,
            revision=1,
            global_enabled=True,
            category_permissions={"owner_reminder": "allowed"},
            allowed_channels=("web_inbox",),
            global_budget_per_24h=4,
            category_budget_per_24h={"owner_reminder": 4},
            cooldown_seconds=60,
            authorization_ref="queued-before-disable-fixture",
        )
        store.save_preference(enabled)
        now = datetime.now(UTC)
        command = ProactiveWorkCommand(
            trigger_type="owner_requested_reminder",
            source_kind="scheduled_time",
            source_refs=(f"work-source/{uuid.uuid4()}",),
            subject_refs=(f"goal/{uuid.uuid4()}",),
            category="owner_reminder",
            reason_code="owner_requested_fixture",
            reason_summary="Queued before owner disable",
            intended_benefit="Prove execution-time preference recheck",
            data_policy=DataPolicy.owner_default(
                PrivacyClass.LOCAL_ONLY, memory_eligible=False
            ),
            preference_revision=1,
            execution_idempotency_key=f"queued-disable-execution-{uuid.uuid4()}",
            observed_at=now,
            earliest_eligible_at=now - timedelta(seconds=1),
            expires_at=now + timedelta(hours=2),
            deduplication_key=f"queued-disable-dedupe-{uuid.uuid4()}",
        )
        work_item_id = store.enqueue_work(
            work_kind="scheduled",
            idempotency_key=f"queued-disable-work-{uuid.uuid4()}",
            command=command,
            not_before=now - timedelta(seconds=1),
        )
        disabled = ProactivePreferenceRevision(owner_id=owner, revision=2)
        store.save_preference(disabled)

        result = store.run_work_once(worker_id="queued-disable-worker")
        self.assertEqual(result["work_item_id"], work_item_id)
        self.assertEqual(result["status"], "succeeded")
        view = store.get(proposal_id=result["proposal_id"])
        self.assertEqual(view.preference.preference_revision_id, disabled.preference_revision_id)
        self.assertEqual(view.preference.revision, 2)
        self.assertEqual(view.decision.decision, InterruptionOutcome.DROP)
        self.assertIsNone(view.delivery_attempt)
        with self.repository.pool.connection() as connection:
            head = connection.execute(
                """
                SELECT preference_revision_id, revision
                FROM havre.proactive_preference_heads WHERE owner_id = %s
                """,
                (owner,),
            ).fetchone()
        self.assertEqual(head["preference_revision_id"], disabled.preference_revision_id)
        self.assertEqual(head["revision"], 2)

    def test_scheduled_and_event_driven_worker_retry_reconciles_one_effect(self) -> None:
        now = datetime.now(UTC)

        def command(kind: str) -> ProactiveWorkCommand:
            token = uuid.uuid4()
            return ProactiveWorkCommand(
                trigger_type="owner_requested_reminder",
                source_kind="scheduled_time" if kind == "scheduled" else "goal",
                source_refs=(f"work-source/{token}",),
                subject_refs=(f"goal/work-{token}",),
                category="owner_reminder",
                reason_code="owner_requested_fixture",
                reason_summary=f"{kind} proactive work fixture",
                intended_benefit="Exercise durable proactive work",
                data_policy=DataPolicy.owner_default(
                    PrivacyClass.LOCAL_ONLY, memory_eligible=False
                ),
                preference_revision=4,
                execution_idempotency_key=f"work-execution-{token}",
                observed_at=now,
                earliest_eligible_at=now - timedelta(seconds=1),
                expires_at=now + timedelta(hours=2),
                deduplication_key=f"work-dedupe-{token}",
            )

        scheduled = command("scheduled")
        scheduled_id = self.store.enqueue_work(
            work_kind="scheduled",
            idempotency_key=f"scheduled-{uuid.uuid4()}",
            command=scheduled,
            not_before=now - timedelta(seconds=1),
        )
        scheduled_result = self.store.run_work_once(worker_id="stage6-worker-test")
        self.assertEqual(scheduled_result["work_item_id"], scheduled_id)
        self.assertEqual(scheduled_result["status"], "succeeded")

        event_command = command("event_driven")
        event_id = self.store.enqueue_work(
            work_kind="event_driven",
            idempotency_key=f"event-{uuid.uuid4()}",
            command=event_command,
            not_before=now - timedelta(seconds=1),
        )
        with patch.object(
            self.store,
            "_complete_work_success",
            side_effect=RuntimeError("synthetic post-delivery completion failure"),
        ):
            failed = self.store.run_work_once(worker_id="stage6-worker-test")
        self.assertEqual(failed["work_item_id"], event_id)
        self.assertEqual(failed["status"], "retryable_failed")
        recovered = self.store.run_work_once(worker_id="stage6-worker-test")
        self.assertEqual(recovered["work_item_id"], event_id)
        self.assertEqual(recovered["status"], "succeeded")
        self.assertTrue(recovered["idempotent_replay"])
        with self.repository.pool.connection() as connection:
            delivered = connection.execute(
                """
                SELECT count(*) AS value FROM havre.proactive_delivery_attempts
                WHERE owner_id = %s AND proposal_id = %s AND status = 'delivered'
                """,
                (self.owner, recovered["proposal_id"]),
            ).fetchone()["value"]
        self.assertEqual(delivered, 1)

    def test_http_retry_uses_stable_policy_revision(self) -> None:
        assert DATABASE_URL is not None
        owner = uuid.uuid4()
        settings = Settings.from_env().model_copy(
            update={
                "database_url": DATABASE_URL,
                "owner_id": owner,
                "provider_id": "deterministic-local",
            }
        )
        now = datetime.now(UTC)
        key = f"http-retry-{uuid.uuid4()}"
        body = {
            "trigger_type": "owner_requested_reminder",
            "source_kind": "owner_reminder",
            "source_refs": [f"owner-reminder/{key}"],
            "subject_refs": [f"goal/{key}"],
            "category": "owner_reminder",
            "reason_code": "owner_requested_fixture",
            "reason_summary": "Stable HTTP retry fixture",
            "intended_benefit": "Prove exact idempotent replay",
            "privacy_class": "LOCAL_ONLY",
            "memory_eligible": False,
            "preference_revision": 1,
            "observed_at": now.isoformat(),
            "earliest_eligible_at": (now - timedelta(seconds=1)).isoformat(),
            "expires_at": (now + timedelta(hours=2)).isoformat(),
            "deduplication_key": f"http-dedupe-{key}",
            "simulation_only": True,
        }
        with TestClient(create_app(settings)) as client:
            preference = client.post(
                "/v1/proactive/preferences",
                json={
                    "revision": 1,
                    "global_enabled": True,
                    "category_permissions": {"owner_reminder": "allowed"},
                    "allowed_channels": ["web_inbox"],
                    "preview_policy": "none",
                    "global_budget_per_24h": 1,
                    "category_budget_per_24h": {"owner_reminder": 1},
                    "cooldown_seconds": 60,
                    "stopped_subject_refs": [],
                    "authorization_ref": "stage6-http-idempotency",
                    "simulation_only": True,
                },
            )
            self.assertEqual(preference.status_code, 200, preference.text)
            first = client.post(
                "/v1/proactive/simulations/reach-out",
                headers={"Idempotency-Key": key},
                json=body,
            )
            replay = client.post(
                "/v1/proactive/simulations/reach-out",
                headers={"Idempotency-Key": key},
                json=body,
            )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(
            first.json()["proposal"]["proposal_id"],
            replay.json()["proposal"]["proposal_id"],
        )
        self.assertTrue(replay.json()["idempotent_replay"])
