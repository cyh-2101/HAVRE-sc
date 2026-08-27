"""PostgreSQL Stage 7 reflection workers and reproducible offline pipeline."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from companion.hashing import content_hash
from companion.ids import uuid7
from companion.offline.models import (
    ArtifactManifest,
    CanonicalDatasetSnapshot,
    DatasetRejection,
    MemoryLifecycleAction,
    MemoryLifecycleProposal,
    MemoryLifecycleReview,
    ReflectionProposal,
)
from companion.persistence.postgres import PostgresRepository
from companion.policy import DataPolicy, combine_policies


class Stage7PostgresStore:
    worker_version = "stage7-offline-worker-v1"

    def __init__(self, *, repository: PostgresRepository, owner_id: UUID) -> None:
        self.repository = repository
        self.owner_id = owner_id

    @staticmethod
    def _policy_columns(policy: DataPolicy) -> tuple[object, ...]:
        return (
            policy.privacy_class.value,
            policy.memory_eligible,
            policy.training_eligible,
            policy.cloud_eligible,
            policy.policy_version,
            policy.policy_revision_id,
            policy.decision_source,
            policy.authorization_ref,
        )

    def enqueue(
        self,
        *,
        job_type: str,
        window_start: datetime,
        window_end: datetime,
        idempotency_key: str,
    ) -> UUID:
        if window_start.utcoffset() is None or window_end.utcoffset() is None:
            raise ValueError("reflection windows must be timezone-aware")
        normalized_start = window_start.astimezone(UTC)
        normalized_end = window_end.astimezone(UTC)
        if normalized_end <= normalized_start:
            raise ValueError("reflection window_end must follow window_start")
        job_id = uuid7()
        with self.repository.pool.connection() as connection, connection.transaction():
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"stage7-enqueue:{self.owner_id}:{job_type}:{idempotency_key}",),
            )
            existing = connection.execute(
                """
                SELECT job_id, window_start, window_end
                FROM havre.stage7_jobs
                WHERE owner_id = %s AND job_type = %s AND idempotency_key = %s
                """,
                (self.owner_id, job_type, idempotency_key),
            ).fetchone()
            if existing is not None:
                if (
                    existing["window_start"] != normalized_start
                    or existing["window_end"] != normalized_end
                ):
                    raise ValueError(
                        "Stage 7 idempotency key was reused with a different window"
                    )
                return existing["job_id"]
            connection.execute(
                """
                INSERT INTO havre.stage7_jobs (
                    job_id, owner_id, job_type, idempotency_key,
                    window_start, window_end, status
                ) VALUES (%s, %s, %s, %s, %s, %s, 'pending')
                """,
                (
                    job_id, self.owner_id, job_type, idempotency_key,
                    normalized_start, normalized_end,
                ),
            )
            return job_id

    def run_once(self, *, worker_id: str = "stage7-local-worker") -> dict[str, object] | None:
        job = self._claim_job(worker_id=worker_id)
        if job is None:
            return None
        try:
            with self.repository.pool.connection() as connection, connection.transaction():
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (f"offline-owner:{self.owner_id}",),
                )
                return self._process_claimed_job(
                    connection, job=job, worker_id=worker_id
                )
        except Exception:
            status = self._record_claimed_failure(
                job_id=job["job_id"],
                worker_id=worker_id,
                error_code="worker_processing_error",
                retryable=True,
            )
            return {
                "job_id": job["job_id"],
                "job_type": job["job_type"],
                "status": status,
                "error_code": "worker_processing_error",
                "outreach_authorized": False,
                "delivery_called": False,
            }

    def _claim_job(self, *, worker_id: str):
        with self.repository.pool.connection() as connection, connection.transaction():
            return connection.execute(
                """
                WITH claimable AS (
                    SELECT job_id FROM havre.stage7_jobs
                    WHERE owner_id = %s
                      AND (
                        status IN ('pending', 'retryable_failed')
                        OR (status = 'leased' AND lease_expires_at < statement_timestamp())
                      )
                    ORDER BY created_at, job_id
                    FOR UPDATE SKIP LOCKED LIMIT 1
                )
                UPDATE havre.stage7_jobs AS job
                SET status = 'leased', lease_owner = %s,
                    lease_expires_at = statement_timestamp() + interval '5 minutes',
                    attempt_count = attempt_count + 1
                FROM claimable
                WHERE job.job_id = claimable.job_id
                RETURNING job.*
                """,
                (self.owner_id, worker_id),
            ).fetchone()

    def _process_claimed_job(self, connection, *, job, worker_id: str) -> dict[str, object]:
        events = connection.execute(
                """
                SELECT event.* FROM havre.events AS event
                WHERE event.owner_id = %s
                  AND event.recorded_at >= %s AND event.recorded_at < %s
                  AND NOT EXISTS (
                      SELECT 1 FROM havre.offline_source_revocations AS revoked
                      WHERE revoked.owner_id = event.owner_id
                        AND revoked.source_event_id = event.event_id
                  )
                ORDER BY event.recorded_at, event.event_id
                """,
                (self.owner_id, job["window_start"], job["window_end"]),
            ).fetchall()
        source_material = tuple(
            {
                "event_id": str(row["event_id"]),
                "content_hash": row["content_hash"],
                "recorded_at": row["recorded_at"].isoformat(),
            }
            for row in events
        )
        source_snapshot_hash = content_hash(source_material)
        reflection_id = None
        lifecycle_id = None
        if events:
            policies = [PostgresRepository._policy_from_row(row) for row in events]
            policy = combine_policies(policies)
            proposal_kind = (
                "progress_recognition"
                if job["job_type"] == "daily_reflection"
                else "pattern_check"
            )
            reflection = ReflectionProposal(
                owner_id=self.owner_id,
                job_id=job["job_id"],
                proposal_kind=proposal_kind,
                summary=(
                    f"Review {len(events)} source events in the selected offline window; "
                    "no conclusion or outreach is authorized."
                ),
                evidence_event_ids=tuple(row["event_id"] for row in events),
                source_snapshot_hash=source_snapshot_hash,
                data_policy=policy,
                trace_id=events[0]["trace_id"].strip(),
            )
            self._insert_reflection(connection, reflection)
            reflection_id = reflection.reflection_proposal_id
            action = (
                MemoryLifecycleAction.PROMOTE
                if job["job_type"] == "daily_reflection"
                else MemoryLifecycleAction.REGENERATE
            )
            lifecycle = MemoryLifecycleProposal(
                owner_id=self.owner_id,
                action=action,
                memory_class=(
                    "episodic"
                    if action is MemoryLifecycleAction.PROMOTE
                    else "semantic"
                ),
                source_event_ids=tuple(row["event_id"] for row in events),
                proposed_content_text=(
                    "Owner review is required before promoting this offline reflection."
                ),
                reason=(
                    "Deterministic offline worker created a candidate; ordinary events "
                    "remain experiences unless the owner reviews a later applicable path."
                ),
                data_policy=policy,
                trace_id=events[0]["trace_id"].strip(),
            )
            self._insert_lifecycle_proposal(connection, lifecycle)
            lifecycle_id = lifecycle.lifecycle_proposal_id
        completed = connection.execute(
            """
            UPDATE havre.stage7_jobs
            SET status = 'succeeded', lease_owner = NULL,
                lease_expires_at = NULL, completed_at = statement_timestamp(),
                last_error_code = NULL
            WHERE owner_id = %s AND job_id = %s AND status = 'leased'
              AND lease_owner = %s
            RETURNING job_id
            """,
            (self.owner_id, job["job_id"], worker_id),
        ).fetchone()
        if completed is None:
            raise RuntimeError("Stage 7 worker lost its lease before completion")
        return {
            "job_id": job["job_id"],
            "job_type": job["job_type"],
            "status": "succeeded",
            "source_event_count": len(events),
            "source_snapshot_hash": source_snapshot_hash,
            "reflection_proposal_id": reflection_id,
            "memory_lifecycle_proposal_id": lifecycle_id,
            "outreach_authorized": False,
            "delivery_called": False,
        }

    def _record_claimed_failure(
        self,
        *,
        job_id: UUID,
        worker_id: str,
        error_code: str,
        retryable: bool,
    ) -> str:
        with self.repository.pool.connection() as connection, connection.transaction():
            row = connection.execute(
                """
                SELECT attempt_count, max_attempts FROM havre.stage7_jobs
                WHERE owner_id = %s AND job_id = %s AND status = 'leased'
                  AND lease_owner = %s
                FOR UPDATE
                """,
                (self.owner_id, job_id, worker_id),
            ).fetchone()
            if row is None:
                raise RuntimeError("Stage 7 worker cannot record failure after lease loss")
            next_status = (
                "retryable_failed"
                if retryable and row["attempt_count"] < row["max_attempts"]
                else "terminal_failed"
            )
            connection.execute(
                """
                UPDATE havre.stage7_jobs
                SET status = %s, lease_owner = NULL, lease_expires_at = NULL,
                    last_error_code = %s,
                    completed_at = CASE WHEN %s = 'terminal_failed'
                                        THEN statement_timestamp() ELSE NULL END
                WHERE owner_id = %s AND job_id = %s
                """,
                (next_status, error_code, next_status, self.owner_id, job_id),
            )
            return next_status

    def _insert_reflection(self, connection, proposal: ReflectionProposal) -> None:
        policy = proposal.data_policy
        connection.execute(
            """
            INSERT INTO havre.reflection_proposals (
                reflection_proposal_id, schema_version, owner_id, job_id,
                proposal_kind, source_snapshot_hash, payload,
                outreach_authority, delivery_authority, simulation_only,
                privacy_class, memory_eligible, training_eligible, cloud_eligible,
                policy_version, policy_revision_id, policy_decision_source,
                policy_authorization_ref, trace_id, content_hash, created_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, false, false, true,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                proposal.reflection_proposal_id, proposal.schema_version,
                self.owner_id, proposal.job_id, proposal.proposal_kind,
                proposal.source_snapshot_hash, Jsonb(proposal.model_dump(mode="json")),
                *self._policy_columns(policy), proposal.trace_id,
                proposal.content_hash, proposal.created_at,
            ),
        )
        connection.cursor().executemany(
            """
            INSERT INTO havre.reflection_proposal_evidence (
                owner_id, reflection_proposal_id, source_event_id
            ) VALUES (%s, %s, %s)
            """,
            [
                (self.owner_id, proposal.reflection_proposal_id, event_id)
                for event_id in proposal.evidence_event_ids
            ],
        )

    def propose_memory_lifecycle(self, proposal: MemoryLifecycleProposal) -> None:
        if proposal.owner_id != self.owner_id:
            raise ValueError("memory lifecycle proposal owner mismatch")
        with self.repository.pool.connection() as connection, connection.transaction():
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"offline-owner:{self.owner_id}",),
            )
            self._insert_lifecycle_proposal(connection, proposal)

    def _insert_lifecycle_proposal(
        self, connection, proposal: MemoryLifecycleProposal
    ) -> None:
        policy = proposal.data_policy
        connection.execute(
            """
            INSERT INTO havre.memory_lifecycle_proposals (
                lifecycle_proposal_id, schema_version, owner_id, action,
                memory_class, target_memory_id, target_revision, payload,
                review_required, automatically_applied, privacy_class,
                memory_eligible, training_eligible, cloud_eligible,
                policy_version, policy_revision_id, policy_decision_source,
                policy_authorization_ref, trace_id, content_hash, created_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, true, false,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                proposal.lifecycle_proposal_id, proposal.schema_version,
                self.owner_id, proposal.action.value, proposal.memory_class,
                proposal.target_memory_id, proposal.target_revision,
                Jsonb(proposal.model_dump(mode="json")),
                *self._policy_columns(policy), proposal.trace_id,
                proposal.content_hash, proposal.created_at,
            ),
        )
        if proposal.source_event_ids:
            connection.cursor().executemany(
                """
                INSERT INTO havre.memory_lifecycle_proposal_evidence (
                    owner_id, lifecycle_proposal_id, source_event_id
                ) VALUES (%s, %s, %s)
                """,
                [
                    (self.owner_id, proposal.lifecycle_proposal_id, event_id)
                    for event_id in sorted(proposal.source_event_ids)
                ],
            )

    def review_memory_lifecycle(
        self,
        *,
        lifecycle_proposal_id: UUID,
        decision: str,
        reason: str,
    ) -> MemoryLifecycleReview:
        review = MemoryLifecycleReview(
            owner_id=self.owner_id,
            lifecycle_proposal_id=lifecycle_proposal_id,
            decision=decision,
            reason=reason,
        )
        with self.repository.pool.connection() as connection, connection.transaction():
            exists = connection.execute(
                """
                SELECT 1 FROM havre.memory_lifecycle_proposals
                WHERE owner_id = %s AND lifecycle_proposal_id = %s
                """,
                (self.owner_id, lifecycle_proposal_id),
            ).fetchone()
            if not exists:
                raise LookupError("memory lifecycle proposal not found")
            connection.execute(
                """
                INSERT INTO havre.memory_lifecycle_reviews (
                    review_id, schema_version, owner_id, lifecycle_proposal_id,
                    decision, payload, applied_artifact_ref, content_hash, reviewed_at
                ) VALUES (%s, %s, %s, %s, %s, %s, NULL, %s, %s)
                """,
                (
                    review.review_id, review.schema_version, self.owner_id,
                    lifecycle_proposal_id, review.decision,
                    Jsonb(review.model_dump(mode="json")), review.content_hash,
                    review.reviewed_at,
                ),
            )
        return review

    def build_canonical_dataset_snapshot(self) -> tuple[CanonicalDatasetSnapshot, ArtifactManifest]:
        with self.repository.pool.connection() as connection, connection.transaction():
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"offline-owner:{self.owner_id}",),
            )
            rows = connection.execute(
                """
                SELECT event.event_id, event.content_hash, event.training_eligible
                FROM havre.events AS event
                WHERE event.owner_id = %s
                  AND NOT EXISTS (
                      SELECT 1 FROM havre.offline_source_revocations AS revoked
                      WHERE revoked.owner_id = event.owner_id
                        AND revoked.source_event_id = event.event_id
                  )
                ORDER BY event_id
                """,
                (self.owner_id,),
            ).fetchall()
            if any(row["training_eligible"] for row in rows):
                raise RuntimeError(
                    "DataPolicy v1 forbids training eligibility; refusing an unexpected eligible source"
                )
            source_material = tuple(
                {"event_id": str(row["event_id"]), "content_hash": row["content_hash"]}
                for row in rows
            )
            source_snapshot_hash = content_hash(source_material)
            existing = connection.execute(
                """
                SELECT snapshot.payload AS snapshot_payload, manifest.payload AS manifest_payload
                FROM havre.canonical_dataset_snapshots AS snapshot
                JOIN havre.offline_artifact_manifests AS manifest
                  ON manifest.owner_id = snapshot.owner_id
                 AND manifest.dataset_snapshot_id = snapshot.dataset_snapshot_id
                WHERE snapshot.owner_id = %s AND snapshot.source_snapshot_hash = %s
                  AND snapshot.builder_version = 'canonical-dataset-builder-v1'
                """,
                (self.owner_id, source_snapshot_hash),
            ).fetchone()
            if existing:
                return (
                    CanonicalDatasetSnapshot.model_validate(existing["snapshot_payload"]),
                    ArtifactManifest.model_validate(existing["manifest_payload"]),
                )
            rejections = tuple(
                DatasetRejection(
                    source_ref=f"event/{row['event_id']}",
                    source_content_hash=row["content_hash"],
                    reason_code="training_not_eligible",
                )
                for row in rows
            )
            snapshot = CanonicalDatasetSnapshot(
                owner_id=self.owner_id,
                source_snapshot_hash=source_snapshot_hash,
                rejections=rejections,
            )
            manifest = ArtifactManifest(
                owner_id=self.owner_id,
                artifact_ref=f"dataset-snapshot/{snapshot.dataset_snapshot_id}",
                artifact_content_hash=snapshot.content_hash,
                source_snapshot_hash=source_snapshot_hash,
            )
            connection.execute(
                """
                INSERT INTO havre.canonical_dataset_snapshots (
                    dataset_snapshot_id, schema_version, owner_id,
                    source_snapshot_hash, builder_version, split_policy_version,
                    member_manifest_hash, payload, immutable, content_hash, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, true, %s, %s)
                """,
                (
                    snapshot.dataset_snapshot_id, snapshot.schema_version,
                    self.owner_id, snapshot.source_snapshot_hash,
                    snapshot.builder_version, snapshot.split_policy_version,
                    snapshot.member_manifest_hash,
                    Jsonb(snapshot.model_dump(mode="json")), snapshot.content_hash,
                    snapshot.created_at,
                ),
            )
            if rows:
                connection.cursor().executemany(
                    """
                    INSERT INTO havre.dataset_snapshot_sources (
                        owner_id, dataset_snapshot_id, source_event_id,
                        source_content_hash, rejection_reason
                    ) VALUES (%s, %s, %s, %s, 'training_not_eligible')
                    """,
                    [
                        (
                            self.owner_id, snapshot.dataset_snapshot_id,
                            row["event_id"], row["content_hash"],
                        )
                        for row in rows
                    ],
                )
            connection.execute(
                """
                INSERT INTO havre.offline_artifact_manifests (
                    artifact_manifest_id, schema_version, owner_id,
                    dataset_snapshot_id, payload, immutable, reproducible,
                    content_hash, created_at
                ) VALUES (%s, %s, %s, %s, %s, true, true, %s, %s)
                """,
                (
                    manifest.artifact_manifest_id, manifest.schema_version,
                    self.owner_id, snapshot.dataset_snapshot_id,
                    Jsonb(manifest.model_dump(mode="json")), manifest.content_hash,
                    manifest.created_at,
                ),
            )
            return snapshot, manifest

    def job_metrics(self) -> dict[str, int]:
        with self.repository.pool.connection() as connection:
            rows = connection.execute(
                """
                SELECT status, count(*) AS count FROM havre.stage7_jobs
                WHERE owner_id = %s GROUP BY status
                """,
                (self.owner_id,),
            ).fetchall()
            metrics = {row["status"]: row["count"] for row in rows}
            return {
                "pending": metrics.get("pending", 0),
                "leased": metrics.get("leased", 0),
                "succeeded": metrics.get("succeeded", 0),
                "retryable_failed": metrics.get("retryable_failed", 0),
                "terminal_failed": metrics.get("terminal_failed", 0),
            }

    def record_job_failure(
        self,
        *,
        job_id: UUID,
        error_code: str,
        retryable: bool,
    ) -> str:
        """Record a content-safe worker failure and enforce the retry ceiling."""

        if not error_code or len(error_code) > 120:
            raise ValueError("error_code must be a short typed code")
        with self.repository.pool.connection() as connection, connection.transaction():
            row = connection.execute(
                """
                SELECT * FROM havre.stage7_jobs
                WHERE owner_id = %s AND job_id = %s FOR UPDATE
                """,
                (self.owner_id, job_id),
            ).fetchone()
            if row is None:
                raise LookupError("Stage 7 job not found")
            if row["status"] in {"succeeded", "terminal_failed", "cancelled"}:
                raise ValueError("terminal Stage 7 job cannot record another failure")
            attempts = row["attempt_count"] + (0 if row["status"] == "leased" else 1)
            next_status = (
                "retryable_failed"
                if retryable and attempts < row["max_attempts"]
                else "terminal_failed"
            )
            connection.execute(
                """
                UPDATE havre.stage7_jobs
                SET status = %s, attempt_count = %s, lease_owner = NULL,
                    lease_expires_at = NULL, last_error_code = %s,
                    completed_at = CASE WHEN %s = 'terminal_failed'
                                        THEN statement_timestamp() ELSE NULL END
                WHERE owner_id = %s AND job_id = %s
                """,
                (
                    next_status, attempts, error_code, next_status,
                    self.owner_id, job_id,
                ),
            )
            return next_status
