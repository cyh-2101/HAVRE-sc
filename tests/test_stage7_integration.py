from __future__ import annotations

import os
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event

import psycopg
from unittest.mock import patch

from companion.events import EventEnvelope, EventType, TextContentPart, UserMessagePayload
from companion.hashing import content_hash
from companion.identity import IdentityLoader
from companion.ids import uuid7
from companion.offline.models import MemoryLifecycleAction, MemoryLifecycleProposal
from companion.persistence import PostgresRepository, Stage7PostgresStore, apply_migrations
from companion.policy import DataPolicy, PrivacyClass, combine_policies
from companion.tracing import TraceContext


DATABASE_URL = os.getenv("HAVRE_TEST_DATABASE_URL")
PROJECT_ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(DATABASE_URL, "HAVRE_TEST_DATABASE_URL is required")
class Stage7PostgresIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        assert DATABASE_URL is not None
        apply_migrations(DATABASE_URL, PROJECT_ROOT / "db" / "migrations")
        cls.owner = uuid.uuid4()
        cls.repository = PostgresRepository(DATABASE_URL)
        cls.repository.open()
        cls.repository.bootstrap_owner_and_identity(
            owner_id=cls.owner,
            identity=IdentityLoader(PROJECT_ROOT / "identity").load(),
        )
        cls.store = Stage7PostgresStore(repository=cls.repository, owner_id=cls.owner)
        cls.source_event_ids = (
            cls._insert_source_event("First ordinary experience"),
            cls._insert_source_event("Second ordinary experience"),
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.repository.close()

    @classmethod
    def _insert_source_event(cls, text: str):
        trace = TraceContext.from_traceparent(None)
        request_id = uuid7()
        session_id = uuid7()
        policy = DataPolicy.owner_default(PrivacyClass.LOCAL_ONLY, memory_eligible=True)
        event = EventEnvelope(
            event_type=EventType.USER_MESSAGE,
            owner_id=cls.owner,
            session_id=session_id,
            request_id=request_id,
            trace_id=trace.trace_id,
            data_policy=policy,
            payload=UserMessagePayload(
                content_parts=(TextContentPart(text=text),), channel="web"
            ),
        )
        with cls.repository.pool.connection() as connection, connection.transaction():
            connection.execute(
                "INSERT INTO havre.sessions (session_id, owner_id, channel) VALUES (%s, %s, 'web')",
                (session_id, cls.owner),
            )
            connection.execute(
                """
                INSERT INTO havre.traces (
                    trace_id, owner_id, root_request_id, trace_flags, started_at
                ) VALUES (%s, %s, %s, '01', %s)
                """,
                (trace.trace_id, cls.owner, request_id, datetime.now(UTC)),
            )
            connection.execute(
                """
                INSERT INTO havre.interaction_requests (
                    request_id, owner_id, session_id, trace_id, idempotency_key,
                    request_fingerprint, request_kind, status
                ) VALUES (%s, %s, %s, %s, %s, %s, 'interaction', 'processing')
                """,
                (
                    request_id, cls.owner, session_id, trace.trace_id,
                    f"stage7-source-{request_id}", content_hash({"text": text}),
                ),
            )
            PostgresRepository._insert_event(connection, event)
            connection.execute(
                """
                UPDATE havre.interaction_requests
                SET user_event_id = %s
                WHERE owner_id = %s AND request_id = %s
                """,
                (event.event_id, cls.owner, request_id),
            )
        return event.event_id

    def test_daily_reflection_creates_proposals_but_cannot_send(self) -> None:
        now = datetime.now(UTC)
        job_id = self.store.enqueue(
            job_type="daily_reflection",
            window_start=now - timedelta(days=1),
            window_end=now + timedelta(minutes=1),
            idempotency_key=f"daily-{uuid.uuid4()}",
        )
        result = self.store.run_once()
        self.assertEqual(result["job_id"], job_id)
        self.assertFalse(result["outreach_authorized"])
        self.assertFalse(result["delivery_called"])
        self.assertIsNotNone(result["reflection_proposal_id"])
        self.assertIsNotNone(result["memory_lifecycle_proposal_id"])
        with self.repository.pool.connection() as connection:
            reflection = connection.execute(
                "SELECT * FROM havre.reflection_proposals WHERE owner_id = %s AND job_id = %s",
                (self.owner, job_id),
            ).fetchone()
            self.assertFalse(reflection["outreach_authority"])
            self.assertFalse(reflection["delivery_authority"])
            lifecycle = connection.execute(
                """
                SELECT * FROM havre.memory_lifecycle_proposals
                WHERE owner_id = %s AND lifecycle_proposal_id = %s
                """,
                (self.owner, result["memory_lifecycle_proposal_id"]),
            ).fetchone()
            self.assertFalse(lifecycle["automatically_applied"])
            memory_count = connection.execute(
                "SELECT count(*) AS value FROM havre.memory_revisions WHERE owner_id = %s",
                (self.owner,),
            ).fetchone()["value"]
            self.assertEqual(memory_count, 0)
            proactive_count = connection.execute(
                "SELECT count(*) AS value FROM havre.interruption_decisions WHERE owner_id = %s",
                (self.owner,),
            ).fetchone()["value"]
            self.assertEqual(proactive_count, 0)

    def test_same_source_snapshot_rebuilds_same_empty_member_manifest(self) -> None:
        first, first_manifest = self.store.build_canonical_dataset_snapshot()
        second, second_manifest = self.store.build_canonical_dataset_snapshot()
        self.assertEqual(first.dataset_snapshot_id, second.dataset_snapshot_id)
        self.assertEqual(first.member_manifest_hash, second.member_manifest_hash)
        self.assertEqual(first.content_hash, second.content_hash)
        self.assertEqual(first_manifest.content_hash, second_manifest.content_hash)
        self.assertEqual(first.members, ())
        self.assertGreaterEqual(len(first.rejections), 2)
        self.assertTrue(
            all(item.reason_code == "training_not_eligible" for item in first.rejections)
        )

    def test_owner_review_is_append_only_and_does_not_apply_memory(self) -> None:
        now = datetime.now(UTC)
        self.store.enqueue(
            job_type="periodic_consolidation",
            window_start=now - timedelta(days=1),
            window_end=now + timedelta(minutes=1),
            idempotency_key=f"periodic-{uuid.uuid4()}",
        )
        result = self.store.run_once()
        review = self.store.review_memory_lifecycle(
            lifecycle_proposal_id=result["memory_lifecycle_proposal_id"],
            decision="accepted",
            reason="Accept proposal for later governed application only",
        )
        self.assertIsNone(review.applied_artifact_ref)
        with self.repository.pool.connection() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT count(*) AS value FROM havre.memory_revisions WHERE owner_id = %s",
                    (self.owner,),
                ).fetchone()["value"],
                0,
            )

    def test_database_rejects_reflection_outreach_forgery(self) -> None:
        assert DATABASE_URL is not None
        with psycopg.connect(DATABASE_URL) as connection:
            with self.assertRaises(psycopg.errors.CheckViolation):
                with connection.transaction():
                    connection.execute(
                        """
                        INSERT INTO havre.reflection_proposals (
                            reflection_proposal_id, schema_version, owner_id, job_id,
                            proposal_kind, source_snapshot_hash, payload,
                            outreach_authority, delivery_authority, simulation_only,
                            privacy_class, memory_eligible, training_eligible,
                            cloud_eligible, policy_version, policy_revision_id,
                            policy_decision_source, trace_id, content_hash, created_at
                        ) SELECT %s, 1, owner_id, job_id, 'follow_up',
                                 'sha256:' || repeat('0',64), '{}'::jsonb,
                                 true, false, true, 'LOCAL_ONLY', false, false,
                                 false, 'data-policy-v1', %s,
                                 'derived_conservative', repeat('1',32),
                                 'sha256:' || repeat('0',64), statement_timestamp()
                          FROM havre.stage7_jobs WHERE owner_id = %s LIMIT 1
                        """,
                        (uuid.uuid4(), uuid.uuid4(), self.owner),
                    )

    def test_worker_retry_ceiling_and_metrics_are_durable(self) -> None:
        now = datetime.now(UTC)
        job_id = self.store.enqueue(
            job_type="daily_reflection",
            window_start=now - timedelta(hours=1),
            window_end=now,
            idempotency_key=f"failure-{uuid.uuid4()}",
        )
        self.assertEqual(
            self.store.record_job_failure(
                job_id=job_id, error_code="synthetic_retry", retryable=True
            ),
            "retryable_failed",
        )
        self.assertEqual(
            self.store.record_job_failure(
                job_id=job_id, error_code="synthetic_retry", retryable=True
            ),
            "retryable_failed",
        )
        self.assertEqual(
            self.store.record_job_failure(
                job_id=job_id, error_code="synthetic_retry", retryable=True
            ),
            "terminal_failed",
        )
        metrics = self.store.job_metrics()
        self.assertGreaterEqual(metrics["terminal_failed"], 1)

    def test_real_worker_exception_commits_retry_state_then_recovers(self) -> None:
        now = datetime.now(UTC)
        job_id = self.store.enqueue(
            job_type="daily_reflection",
            window_start=now - timedelta(hours=1),
            window_end=now,
            idempotency_key=f"real-failure-{uuid.uuid4()}",
        )
        with patch.object(
            self.store,
            "_process_claimed_job",
            side_effect=RuntimeError("synthetic injected processing failure"),
        ):
            failed = self.store.run_once(worker_id="failure-injection-worker")
        self.assertEqual(failed["job_id"], job_id)
        self.assertEqual(failed["status"], "retryable_failed")
        with self.repository.pool.connection() as connection:
            row = connection.execute(
                """
                SELECT status, attempt_count, last_error_code
                FROM havre.stage7_jobs WHERE owner_id = %s AND job_id = %s
                """,
                (self.owner, job_id),
            ).fetchone()
            self.assertEqual(row["status"], "retryable_failed")
            self.assertEqual(row["attempt_count"], 1)
            self.assertEqual(row["last_error_code"], "worker_processing_error")
        recovered = self.store.run_once(worker_id="failure-injection-worker")
        self.assertEqual(recovered["job_id"], job_id)
        self.assertEqual(recovered["status"], "succeeded")

    def test_job_idempotency_key_is_bound_to_exact_window(self) -> None:
        now = datetime.now(UTC)
        key = f"window-binding-{uuid.uuid4()}"
        first = self.store.enqueue(
            job_type="daily_reflection",
            window_start=now - timedelta(hours=2),
            window_end=now,
            idempotency_key=key,
        )
        replay = self.store.enqueue(
            job_type="daily_reflection",
            window_start=now - timedelta(hours=2),
            window_end=now,
            idempotency_key=key,
        )
        self.assertEqual(first, replay)
        with self.assertRaisesRegex(ValueError, "different window"):
            self.store.enqueue(
                job_type="daily_reflection",
                window_start=now - timedelta(hours=3),
                window_end=now,
                idempotency_key=key,
            )
        processed = self.store.run_once(worker_id="window-binding-worker")
        self.assertEqual(processed["job_id"], first)

    def test_source_erasure_removes_offline_derivatives_and_prevents_resurrection(self) -> None:
        source_event_id = self.source_event_ids[0]
        result = self.repository.erase_source_event_derivatives(
            owner_id=self.owner, source_event_id=source_event_id
        )
        self.assertGreaterEqual(result["reflection_proposals"], 1)
        self.assertGreaterEqual(result["memory_lifecycle_proposals"], 1)
        self.assertGreaterEqual(result["dataset_snapshots"], 1)
        with self.repository.pool.connection() as connection:
            source_request = connection.execute(
                """SELECT status,error_code,completed_at,user_event_id,
                          assistant_event_id,failure_event_id
                   FROM havre.interaction_requests
                   WHERE owner_id=%s AND user_event_id=%s""",
                (self.owner, source_event_id),
            ).fetchone()
        self.assertEqual(source_request["status"], "failed")
        self.assertEqual(
            source_request["error_code"],
            "source_erasure_propagated",
        )
        self.assertIsNotNone(source_request["completed_at"])
        self.assertEqual(source_request["user_event_id"], source_event_id)
        self.assertIsNone(source_request["assistant_event_id"])
        self.assertIsNone(source_request["failure_event_id"])
        rebuilt, _ = self.store.build_canonical_dataset_snapshot()
        self.assertTrue(
            all(
                item.source_ref != f"event/{source_event_id}"
                for item in rebuilt.rejections
            )
        )
        now = datetime.now(UTC)
        job_id = self.store.enqueue(
            job_type="daily_reflection",
            window_start=now - timedelta(days=1),
            window_end=now + timedelta(minutes=1),
            idempotency_key=f"post-revocation-{uuid.uuid4()}",
        )
        rerun = self.store.run_once(worker_id="post-revocation-worker")
        self.assertEqual(rerun["job_id"], job_id)
        self.assertEqual(rerun["status"], "succeeded")
        with self.repository.pool.connection() as connection:
            with self.assertRaises(psycopg.Error):
                with connection.transaction():
                    connection.execute(
                        """
                        INSERT INTO havre.reflection_proposal_evidence (
                            owner_id, reflection_proposal_id, source_event_id
                        ) VALUES (%s, %s, %s)
                        """,
                        (
                            self.owner,
                            rerun["reflection_proposal_id"],
                            source_event_id,
                        ),
                    )
        with self.repository.pool.connection() as connection:
            self.assertEqual(
                connection.execute(
                    """
                    SELECT count(*) AS value FROM havre.dataset_snapshot_sources
                    WHERE owner_id = %s AND source_event_id = %s
                    """,
                    (self.owner, source_event_id),
                ).fetchone()["value"],
                0,
            )
            self.assertEqual(
                connection.execute(
                    """
                    SELECT count(*) AS value
                    FROM havre.reflection_proposal_evidence
                    WHERE owner_id = %s AND source_event_id = %s
                    """,
                    (self.owner, source_event_id),
                ).fetchone()["value"],
                0,
            )
            self.assertEqual(
                connection.execute(
                    """
                    SELECT count(*) AS value
                    FROM havre.memory_lifecycle_proposal_evidence
                    WHERE owner_id = %s AND source_event_id = %s
                    """,
                    (self.owner, source_event_id),
                ).fetchone()["value"],
                0,
            )
        self.assertEqual(self.repository.audit_provenance_integrity(), [])

    def test_evidence_admission_and_erasure_serialize_on_transaction_locks(self) -> None:
        source_event_id = self._insert_source_event(
            f"Concurrent lifecycle evidence {uuid.uuid4()}"
        )
        with self.repository.pool.connection() as connection:
            trace_id = connection.execute(
                "SELECT trace_id FROM havre.events WHERE owner_id = %s AND event_id = %s",
                (self.owner, source_event_id),
            ).fetchone()["trace_id"].strip()
        proposal = MemoryLifecycleProposal(
            owner_id=self.owner,
            action=MemoryLifecycleAction.PROMOTE,
            memory_class="episodic",
            source_event_ids=(source_event_id,),
            proposed_content_text="Concurrent proposal remains owner-review-only.",
            reason="Exercise database-serialized evidence admission and erasure.",
            data_policy=combine_policies((DataPolicy.owner_default(
                PrivacyClass.LOCAL_ONLY, memory_eligible=True
            ),)),
            trace_id=trace_id,
        )
        evidence_inserted = Event()
        allow_proposal_commit = Event()

        def insert_without_python_owner_lock() -> None:
            with self.repository.pool.connection() as connection, connection.transaction():
                self.store._insert_lifecycle_proposal(connection, proposal)
                evidence_inserted.set()
                if not allow_proposal_commit.wait(timeout=5):
                    raise RuntimeError("test did not release proposal transaction")

        with ThreadPoolExecutor(max_workers=2) as executor:
            proposal_future = executor.submit(insert_without_python_owner_lock)
            if not evidence_inserted.wait(timeout=5):
                proposal_future.result(timeout=1)
                self.fail("proposal evidence insert did not reach its transaction hold")
            erasure_future = executor.submit(
                self.repository.erase_source_event_derivatives,
                owner_id=self.owner,
                source_event_id=source_event_id,
            )
            waiting_on_transaction_lock = False
            deadline = time.monotonic() + 5
            try:
                while time.monotonic() < deadline:
                    with self.repository.pool.connection() as connection:
                        waiting_on_transaction_lock = connection.execute(
                            """
                            SELECT EXISTS (
                                SELECT 1 FROM pg_locks
                                WHERE locktype = 'advisory' AND NOT granted
                            ) AS value
                            """
                        ).fetchone()["value"]
                    if waiting_on_transaction_lock:
                        break
                    time.sleep(0.01)
                self.assertTrue(waiting_on_transaction_lock)
            finally:
                allow_proposal_commit.set()
            proposal_future.result(timeout=5)
            erased = erasure_future.result(timeout=5)

        self.assertGreaterEqual(erased["memory_lifecycle_proposals"], 1)
        with self.repository.pool.connection() as connection:
            counts = connection.execute(
                """
                SELECT
                    (SELECT count(*) FROM havre.offline_source_revocations
                     WHERE owner_id = %s AND source_event_id = %s) AS revocations,
                    (SELECT count(*) FROM havre.memory_lifecycle_proposal_evidence
                     WHERE owner_id = %s AND source_event_id = %s) AS evidence
                """,
                (
                    self.owner, source_event_id,
                    self.owner, source_event_id,
                ),
            ).fetchone()
        self.assertEqual(counts["revocations"], 1)
        self.assertEqual(counts["evidence"], 0)
        self.assertEqual(self.repository.audit_provenance_integrity(), [])
