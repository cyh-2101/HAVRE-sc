"""PostgreSQL persistence for Stage 8 local evaluation operations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from psycopg.types.json import Jsonb

from companion.evaluation import (
    ArtifactRetentionReview,
    EvidenceBundle,
    EvaluationArtifact,
    HumanReviewDecision,
    HumanReviewRequest,
    JudgeCalibrationReport,
    ReleaseComparison,
    Stage8OperationalEvidence,
    TraceEdge,
    TraceExploration,
    TraceNode,
)
from companion.hashing import content_hash
from companion.ids import uuid7


class Stage8PostgresStore:
    def __init__(self, *, repository, owner_id: UUID) -> None:
        self.repository = repository
        self.owner_id = owner_id

    def persist_bundle(
        self,
        *,
        bundle: EvidenceBundle,
        artifacts: tuple[EvaluationArtifact, ...] = (),
        calibrations: tuple[JudgeCalibrationReport, ...] = (),
        operational_evidence: Stage8OperationalEvidence | None = None,
    ) -> None:
        bundle = EvidenceBundle.model_validate(bundle.model_dump(mode="python"))
        artifacts = tuple(
            EvaluationArtifact.model_validate(item.model_dump(mode="python"))
            for item in artifacts
        )
        calibrations = tuple(
            JudgeCalibrationReport.model_validate(item.model_dump(mode="python"))
            for item in calibrations
        )
        if bundle.owner_id != self.owner_id:
            raise ValueError("evidence bundle owner mismatch")
        if {artifact.artifact_id for artifact in artifacts} != set(bundle.artifact_ids):
            raise ValueError("bundle artifact IDs must exactly match supplied artifacts")
        if {item.calibration_id for item in calibrations} != set(bundle.judge_calibration_ids):
            raise ValueError("bundle calibration IDs must exactly match supplied calibrations")
        with self.repository.pool.connection() as connection, connection.transaction():
            for calibration in calibrations:
                if calibration.owner_id != self.owner_id:
                    raise ValueError("judge calibration owner mismatch")
                inserted = connection.execute(
                    """
                    INSERT INTO havre.judge_calibration_runs (
                        calibration_id, schema_version, owner_id, calibration_set_id,
                        calibration_set_hash, judge_id, judge_version, judge_kind,
                        human_label_count, agreement_count, critical_clearance_authority,
                        payload, content_hash, created_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,false,%s,%s,%s)
                    ON CONFLICT (calibration_id) DO NOTHING
                    RETURNING calibration_id
                    """,
                    (
                        calibration.calibration_id, calibration.schema_version,
                        self.owner_id, calibration.calibration_set_id,
                        calibration.calibration_set_hash, calibration.judge_id,
                        calibration.judge_version, calibration.judge_kind,
                        calibration.human_label_count, calibration.agreement_count,
                        Jsonb(calibration.model_dump(mode="json")),
                        calibration.content_hash, calibration.created_at,
                    ),
                ).fetchone()
                if inserted is None:
                    self._assert_existing_hash(
                        connection, "judge_calibration_runs", "calibration_id",
                        calibration.calibration_id, calibration.content_hash,
                    )
            self.validate_operational_evidence(
                operational_evidence,
                _connection=connection, _bundle=bundle, _artifacts=artifacts,
            )

    def validate_operational_evidence(
        self, evidence: Stage8OperationalEvidence | None, *,
        _connection=None, _bundle: EvidenceBundle | None = None,
        _artifacts: tuple[EvaluationArtifact, ...] = (),
    ) -> None:
        """Recompute every caller-supplied Stage 6/7 outcome before persistence."""

        if evidence is None:
            if _bundle is None or _bundle.automated_gate == "candidate_review":
                raise ValueError("candidate-review bundles require database-recomputed operational evidence")
            self._persist_bundle_body(_connection, _bundle, _artifacts)
            return
        if evidence.owner_id != self.owner_id:
            raise ValueError("operational evidence owner mismatch")
        explorations = tuple(self.explore_trace(trace_id) for trace_id in evidence.trace_ids)
        actual_trace_hashes = {item.trace_id: item.content_hash for item in explorations}
        if evidence.trace_content_hashes != actual_trace_hashes:
            raise ValueError("operational evidence trace hashes do not match database exploration")
        covered_sources = {
            source for item in explorations
            for source in set(item.registered_source_kinds) - set(item.missing_source_kinds)
        }
        registered_sources = set(explorations[0].registered_source_kinds)
        trace_ids = list(evidence.trace_ids)
        with self.repository.pool.connection() as connection:
            full_chain = connection.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM havre.proactive_proposals AS proposal
                    JOIN havre.interruption_decisions AS decision
                      ON decision.owner_id=proposal.owner_id
                     AND decision.proposal_id=proposal.proposal_id
                    JOIN havre.proactive_context_packs AS context_pack
                      ON context_pack.owner_id=proposal.owner_id
                     AND context_pack.proposal_id=proposal.proposal_id
                    JOIN havre.rendered_proactive_messages AS rendering
                      ON rendering.owner_id=proposal.owner_id
                     AND rendering.proposal_id=proposal.proposal_id
                    JOIN havre.proactive_delivery_attempts AS delivery
                      ON delivery.owner_id=proposal.owner_id
                     AND delivery.proposal_id=proposal.proposal_id
                    WHERE proposal.owner_id=%s AND proposal.trace_id=ANY(%s::char(32)[])
                      AND decision.decision='SEND_NOW'
                      AND delivery.simulation_only
                      AND NOT delivery.external_delivery_authorized
                ) AS value
                """,
                (self.owner_id, trace_ids),
            ).fetchone()["value"]
            delivery_idempotent = connection.execute(
                """
                SELECT EXISTS (
                    SELECT proposal_id FROM havre.proactive_delivery_attempts
                    WHERE owner_id=%s AND trace_id=ANY(%s::char(32)[])
                    GROUP BY proposal_id HAVING count(*)=1
                ) AS value
                """,
                (self.owner_id, trace_ids),
            ).fetchone()["value"]
            privacy_local = connection.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM havre.proactive_context_packs AS context_pack
                    JOIN havre.proactive_delivery_attempts AS delivery
                      ON delivery.owner_id=context_pack.owner_id
                     AND delivery.proposal_id=context_pack.proposal_id
                    WHERE context_pack.owner_id=%s
                      AND context_pack.trace_id=ANY(%s::char(32)[])
                      AND context_pack.privacy_class='LOCAL_ONLY'
                      AND NOT context_pack.cloud_eligible
                      AND NOT context_pack.training_eligible
                      AND NOT delivery.external_delivery_authorized
                ) AS value
                """,
                (self.owner_id, trace_ids),
            ).fetchone()["value"]
            missing_context_closed = connection.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM havre.interruption_decisions AS decision
                    WHERE decision.owner_id=%s
                      AND decision.trace_id=ANY(%s::char(32)[])
                      AND decision.decision<>'SEND_NOW'
                      AND NOT EXISTS (
                          SELECT 1 FROM havre.proactive_context_packs AS context_pack
                          WHERE context_pack.owner_id=decision.owner_id
                            AND context_pack.proposal_id=decision.proposal_id
                      )
                      AND NOT EXISTS (
                          SELECT 1 FROM havre.proactive_delivery_attempts AS delivery
                          WHERE delivery.owner_id=decision.owner_id
                            AND delivery.proposal_id=decision.proposal_id
                      )
                ) AS value
                """,
                (self.owner_id, trace_ids),
            ).fetchone()["value"]
            owner_action_linked = connection.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM havre.proactive_owner_actions
                    WHERE owner_id=%s AND trace_id=ANY(%s::char(32)[])
                ) AS value
                """,
                (self.owner_id, trace_ids),
            ).fetchone()["value"]
            promote_pending = connection.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM havre.memory_lifecycle_proposals
                    WHERE owner_id=%s AND trace_id=ANY(%s::char(32)[])
                      AND action='promote' AND review_required AND NOT automatically_applied
                ) AS value
                """,
                (self.owner_id, trace_ids),
            ).fetchone()["value"]
            stale_excluded = connection.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM havre.memory_lifecycle_proposals AS proposal
                    WHERE proposal.owner_id=%s
                      AND proposal.trace_id=ANY(%s::char(32)[])
                      AND (proposal.payload->>'valid_to')::timestamptz < statement_timestamp()
                      AND NOT proposal.automatically_applied
                ) AS value
                """,
                (self.owner_id, trace_ids),
            ).fetchone()["value"]
            archive_safe = connection.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM havre.memory_lifecycle_proposals AS proposal
                    JOIN havre.memory_lifecycle_reviews AS review
                      ON review.owner_id=proposal.owner_id
                     AND review.lifecycle_proposal_id=proposal.lifecycle_proposal_id
                    JOIN havre.memory_revisions AS memory
                      ON memory.owner_id=proposal.owner_id
                     AND memory.memory_id=proposal.target_memory_id
                     AND memory.revision=proposal.target_revision
                    WHERE proposal.owner_id=%s AND proposal.action='archive'
                      AND review.applied_artifact_ref IS NULL AND memory.status='active'
                ) AS value
                """,
                (self.owner_id,),
            ).fetchone()["value"]
            reconsolidation_safe = connection.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM havre.memory_lifecycle_proposals AS proposal
                    JOIN havre.memory_lifecycle_reviews AS review
                      ON review.owner_id=proposal.owner_id
                     AND review.lifecycle_proposal_id=proposal.lifecycle_proposal_id
                    JOIN havre.memory_revisions AS memory
                      ON memory.owner_id=proposal.owner_id
                     AND memory.memory_id=proposal.target_memory_id
                     AND memory.revision=proposal.target_revision
                    WHERE proposal.owner_id=%s AND proposal.action='reconsolidate'
                      AND review.decision='rejected'
                      AND review.applied_artifact_ref IS NULL AND memory.status='active'
                ) AS value
                """,
                (self.owner_id,),
            ).fetchone()["value"]
            revoked_closed = connection.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM havre.offline_source_revocations AS revoked
                    WHERE revoked.owner_id=%s
                      AND NOT EXISTS (SELECT 1 FROM havre.reflection_proposal_evidence e
                          WHERE e.owner_id=revoked.owner_id AND e.source_event_id=revoked.source_event_id)
                      AND NOT EXISTS (SELECT 1 FROM havre.memory_lifecycle_proposal_evidence e
                          WHERE e.owner_id=revoked.owner_id AND e.source_event_id=revoked.source_event_id)
                      AND NOT EXISTS (SELECT 1 FROM havre.dataset_snapshot_sources e
                          WHERE e.owner_id=revoked.owner_id AND e.source_event_id=revoked.source_event_id)
                ) AS value
                """,
                (self.owner_id,),
            ).fetchone()["value"]
        from companion.persistence.offline import Stage7PostgresStore
        stage7 = Stage7PostgresStore(repository=self.repository, owner_id=self.owner_id)
        first_snapshot, first_manifest = stage7.build_canonical_dataset_snapshot()
        repeated_snapshot, repeated_manifest = stage7.build_canonical_dataset_snapshot()
        actual_memory = {
            "ordinary-event-remains-event-only": "proposal_pending" if promote_pending else "missing",
            "historical-validity-not-current": "excluded_stale_current" if stale_excluded else "unexpected_current_memory",
            "archive-review-does-not-mutate-memory": "active_memory" if archive_safe else "mutated",
            "reconsolidation-rejection-does-not-mutate-memory": "active_memory" if reconsolidation_safe else "mutated",
        }
        actual_erasure = {
            "revoked-source-cannot-regenerate": "rejected_source_revoked" if revoked_closed else "regenerated",
            "eligible-synthetic-source-can-rebuild-manifest": "same_content_hash"
            if first_snapshot.content_hash == repeated_snapshot.content_hash
            and first_manifest.content_hash == repeated_manifest.content_hash else "hash_changed",
        }
        actual_proactive = {
            "trace_complete": covered_sources == registered_sources,
            "proposal_decision_render_delivery_linked": bool(full_chain),
            "delivery_idempotent": bool(delivery_idempotent),
            "privacy_local_only": bool(privacy_local),
            "missing_context_fails_closed": bool(missing_context_closed),
            "owner_action_linked": bool(owner_action_linked),
        }
        expected_source_health = {
            "fresh-consented-observation": "eligible_observation_only",
            "stale-observation": "ineligible_stale",
            "revoked-observation": "ineligible_revoked",
            "missing-source-is-not-negative-evidence": "unknown_not_negative_evidence",
        }
        if evidence.memory_lifecycle_outcomes != actual_memory:
            raise ValueError("operational memory lifecycle outcomes do not match database")
        if evidence.erasure_regeneration_outcomes != actual_erasure:
            raise ValueError("operational erasure outcomes do not match database")
        if evidence.proactive_outcomes != actual_proactive:
            raise ValueError(
                "operational proactive outcomes do not match database: "
                f"expected={evidence.proactive_outcomes!r} actual={actual_proactive!r}"
            )
        if evidence.source_health_outcomes != expected_source_health:
            raise ValueError("operational source-health outcomes do not match contracts")
        if _bundle is None:
            return
        self._persist_bundle_body(_connection, _bundle, _artifacts)

    def _persist_bundle_body(
        self, connection, bundle: EvidenceBundle,
        artifacts: tuple[EvaluationArtifact, ...],
    ) -> None:
        for suite in bundle.suite_results:
            statuses = {case.status for case in suite.cases}
            run_status = (
                "error" if "error" in statuses else
                "failed" if "failed" in statuses else
                "inconclusive" if "inconclusive" in statuses else "passed"
            )
            inserted = connection.execute(
                """
                INSERT INTO havre.evaluation_runs (
                    evaluation_run_id, schema_version, owner_id, suite_id,
                    suite_version, domain, fixture_hash, runner_version,
                    binding_evaluation, status, payload, content_hash, created_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (evaluation_run_id) DO NOTHING
                RETURNING evaluation_run_id
                """,
                (
                    suite.suite_result_id, suite.schema_version, self.owner_id,
                    suite.suite_id, suite.suite_version, suite.domain.value,
                    suite.fixture_hash, suite.runner_version, suite.binding,
                    run_status, Jsonb(suite.model_dump(mode="json")),
                    suite.content_hash, bundle.created_at,
                ),
            ).fetchone()
            if inserted is None:
                self._assert_existing_hash(
                    connection, "evaluation_runs", "evaluation_run_id",
                    suite.suite_result_id, suite.content_hash,
                )
            for case in suite.cases:
                inserted = connection.execute(
                    """
                    INSERT INTO havre.evaluation_case_results (
                        case_result_id, schema_version, owner_id, evaluation_run_id,
                        case_id, domain, status, critical, payload, content_hash
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (case_result_id) DO NOTHING
                    RETURNING case_result_id
                    """,
                    (
                        case.case_result_id, case.schema_version, self.owner_id,
                        suite.suite_result_id, case.case_id, case.domain.value,
                        case.status, case.critical,
                        Jsonb(case.model_dump(mode="json")), case.content_hash,
                    ),
                ).fetchone()
                if inserted is None:
                    self._assert_existing_hash(
                        connection, "evaluation_case_results", "case_result_id",
                        case.case_result_id, case.content_hash,
                    )
        connection.execute(
            """
            INSERT INTO havre.evidence_bundles (
                evidence_bundle_id, schema_version, owner_id, candidate_release_id,
                runner_version, automated_gate, explicit_decision, decision_scope,
                release_promotion_authorized, critical_failure_count,
                payload, content_hash, created_at
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,false,%s,%s,%s,%s)
            """,
            (
                bundle.evidence_bundle_id, bundle.schema_version, self.owner_id,
                bundle.candidate_release_id, bundle.runner_version,
                bundle.automated_gate, bundle.explicit_decision, bundle.decision_scope,
                len(bundle.critical_failures),
                Jsonb(bundle.model_dump(mode="json")), bundle.content_hash,
                bundle.created_at,
            ),
        )
        for suite in bundle.suite_results:
            connection.execute(
                """
                INSERT INTO havre.evidence_bundle_runs (
                    owner_id, evidence_bundle_id, evaluation_run_id
                ) VALUES (%s,%s,%s)
                """,
                (self.owner_id, bundle.evidence_bundle_id, suite.suite_result_id),
            )
        for calibration_id in bundle.judge_calibration_ids:
            connection.execute(
                """
                INSERT INTO havre.evidence_bundle_calibrations (
                    owner_id, evidence_bundle_id, calibration_id
                ) VALUES (%s,%s,%s)
                """,
                (self.owner_id, bundle.evidence_bundle_id, calibration_id),
            )
        for trace_id in bundle.trace_ids:
            connection.execute(
                """
                INSERT INTO havre.evidence_bundle_traces (
                    owner_id, evidence_bundle_id, trace_id
                ) VALUES (%s,%s,%s)
                """,
                (self.owner_id, bundle.evidence_bundle_id, trace_id),
            )
        for comparison_id in bundle.release_comparison_ids:
            connection.execute(
                """
                INSERT INTO havre.evidence_bundle_release_comparisons (
                    owner_id, evidence_bundle_id, comparison_id
                ) VALUES (%s,%s,%s)
                """,
                (self.owner_id, bundle.evidence_bundle_id, comparison_id),
            )
        for decision_id in bundle.human_review_decision_ids:
            connection.execute(
                """
                INSERT INTO havre.evidence_bundle_review_decisions (
                    owner_id, evidence_bundle_id, review_decision_id
                ) VALUES (%s,%s,%s)
                """,
                (self.owner_id, bundle.evidence_bundle_id, decision_id),
            )
        for artifact in artifacts:
            if artifact.owner_id != self.owner_id:
                raise ValueError("evaluation artifact owner mismatch")
            retention_id = self._ensure_retention_policy(connection, artifact)
            connection.execute(
                """
                INSERT INTO havre.evaluation_artifacts (
                    artifact_id, schema_version, owner_id, evidence_bundle_id,
                    retention_policy_id, artifact_kind, artifact_uri,
                    artifact_content_hash, media_type, privacy_class,
                    memory_eligible, training_eligible, cloud_eligible,
                    external_transfer_allowed, payload, content_hash, created_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'LOCAL_ONLY',
                          false,false,false,false,%s,%s,%s)
                """,
                (
                    artifact.artifact_id, artifact.schema_version, self.owner_id,
                    bundle.evidence_bundle_id, retention_id, artifact.artifact_kind,
                    artifact.artifact_uri, artifact.artifact_content_hash,
                    artifact.media_type, Jsonb(artifact.model_dump(mode="json")),
                    artifact.content_hash, artifact.created_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO havre.evaluation_artifact_access_grants (
                    access_grant_id, owner_id, artifact_id, actor_ref,
                    role, purpose, granted_by, expires_at
                ) VALUES (%s,%s,%s,%s,'owner','stage8_evidence_review','owner',%s)
                """,
                (
                    uuid7(), self.owner_id, artifact.artifact_id,
                    f"owner:{self.owner_id}",
                    artifact.created_at + timedelta(
                        days=artifact.access_policy.review_after_days
                    ),
                ),
            )

    def _assert_existing_hash(
        self, connection, table: str, id_column: str, identifier: UUID, expected_hash: str
    ) -> None:
        allowed = {
            ("judge_calibration_runs", "calibration_id"),
            ("evaluation_runs", "evaluation_run_id"),
            ("evaluation_case_results", "case_result_id"),
        }
        if (table, id_column) not in allowed:
            raise ValueError("unsupported immutable evaluation identity check")
        row = connection.execute(
            f"SELECT owner_id, content_hash FROM havre.{table} WHERE {id_column} = %s",
            (identifier,),
        ).fetchone()
        if row is None or row["owner_id"] != self.owner_id or row["content_hash"] != expected_hash:
            raise ValueError(f"{table} identity conflicts with durable owner/content")

    def grant_artifact_access(
        self, *, artifact_id: UUID, actor_ref: str, role: str, purpose: str
    ) -> None:
        if role not in {"technical_reviewer", "human_reviewer"}:
            raise ValueError("delegated artifact grants require a reviewer role")
        if not actor_ref or len(actor_ref) > 240 or not purpose or len(purpose) > 500:
            raise ValueError("artifact grant actor and purpose must be present and bounded")
        with self.repository.pool.connection() as connection, connection.transaction():
            allowed = connection.execute(
                """
                SELECT GREATEST(
                           artifact.created_at + make_interval(days => policy.review_after_days),
                           COALESCE(max(review.retain_until), '-infinity'::timestamptz)
                       ) AS access_until
                FROM havre.evaluation_artifacts AS artifact
                JOIN havre.evaluation_retention_policies AS policy
                  ON policy.owner_id = artifact.owner_id
                 AND policy.retention_policy_id = artifact.retention_policy_id
                LEFT JOIN havre.evaluation_retention_reviews AS review
                  ON review.owner_id = artifact.owner_id
                 AND review.artifact_id = artifact.artifact_id
                WHERE artifact.owner_id = %s AND artifact.artifact_id = %s
                  AND %s = ANY(policy.allowed_roles)
                GROUP BY artifact.created_at, policy.review_after_days
                """,
                (self.owner_id, artifact_id, role),
            ).fetchone()
            if allowed is None or allowed["access_until"] <= datetime.now(UTC):
                raise PermissionError("artifact policy does not allow the reviewer role")
            connection.execute(
                """
                    INSERT INTO havre.evaluation_artifact_access_grants (
                        access_grant_id, owner_id, artifact_id, actor_ref,
                        role, purpose, granted_by, expires_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,'owner',%s)
                """,
                (
                    uuid7(), self.owner_id, artifact_id, actor_ref, role, purpose,
                    allowed["access_until"],
                ),
            )

    def review_artifact_retention(self, review: ArtifactRetentionReview) -> None:
        if review.owner_id != self.owner_id:
            raise ValueError("retention review owner mismatch")
        with self.repository.pool.connection() as connection, connection.transaction():
            artifact = connection.execute(
                """
                SELECT 1 FROM havre.evaluation_artifacts
                WHERE owner_id = %s AND artifact_id = %s
                """,
                (self.owner_id, review.artifact_id),
            ).fetchone()
            if artifact is None:
                raise LookupError("evaluation artifact not found")
            connection.execute(
                """
                INSERT INTO havre.evaluation_retention_reviews (
                    retention_review_id, schema_version, owner_id, artifact_id,
                    decision, retain_until, reviewer, payload, content_hash, reviewed_at
                ) VALUES (%s,%s,%s,%s,%s,%s,'owner',%s,%s,%s)
                """,
                (
                    review.retention_review_id, review.schema_version, self.owner_id,
                    review.artifact_id, review.decision, review.retain_until,
                    Jsonb(review.model_dump(mode="json")), review.content_hash,
                    review.reviewed_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO havre.evaluation_artifact_access_grants (
                    access_grant_id, owner_id, artifact_id, actor_ref,
                    role, purpose, granted_by, expires_at
                ) VALUES (%s,%s,%s,%s,'owner','stage8_evidence_review','owner',%s)
                """,
                (
                    uuid7(), self.owner_id, review.artifact_id,
                    f"owner:{self.owner_id}", review.retain_until,
                ),
            )

    def _ensure_retention_policy(self, connection, artifact: EvaluationArtifact) -> UUID:
        policy = artifact.access_policy
        policy_hash = content_hash(policy.model_dump(mode="json"))
        row = connection.execute(
            """
            SELECT retention_policy_id
            FROM havre.evaluation_retention_policies
            WHERE owner_id = %s AND policy_version = %s AND content_hash = %s
            """,
            (self.owner_id, policy.policy_version, policy_hash),
        ).fetchone()
        if row is not None:
            return row["retention_policy_id"]
        retention_id = uuid7()
        connection.execute(
            """
            INSERT INTO havre.evaluation_retention_policies (
                retention_policy_id, schema_version, owner_id, policy_version,
                allowed_roles, review_after_days, automatic_deletion,
                deletion_requires_owner_authorization, external_transfer_allowed,
                payload, content_hash
            ) VALUES (%s,1,%s,%s,%s,%s,false,true,false,%s,%s)
            """,
            (
                retention_id, self.owner_id, policy.policy_version,
                list(policy.allowed_roles), policy.review_after_days,
                Jsonb(policy.model_dump(mode="json")), policy_hash,
            ),
        )
        return retention_id

    def request_review(self, request: HumanReviewRequest) -> None:
        if request.owner_id != self.owner_id:
            raise ValueError("review request owner mismatch")
        with self.repository.pool.connection() as connection, connection.transaction():
            if request.target_kind == "evidence_bundle":
                target_table, target_column = "evidence_bundles", "evidence_bundle_id"
            elif request.target_kind == "release_comparison":
                target_table, target_column = "release_comparisons", "comparison_id"
            else:
                target_table, target_column = "judge_calibration_runs", "calibration_id"
            found = connection.execute(
                f"SELECT 1 FROM havre.{target_table} WHERE owner_id = %s AND {target_column} = %s",
                (self.owner_id, request.target_id),
            ).fetchone()
            if found is None:
                raise LookupError("review target not found")
            target_columns = {
                "evidence_bundle": (request.target_id, None, None),
                "release_comparison": (None, request.target_id, None),
                "judge_calibration": (None, None, request.target_id),
            }[request.target_kind]
            connection.execute(
                """
                INSERT INTO havre.evaluation_review_requests (
                    review_request_id, schema_version, owner_id, target_kind,
                    target_id, evidence_bundle_id, release_comparison_id,
                    calibration_id, required_role, release_promotion_in_scope,
                    payload, content_hash, created_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,false,%s,%s,%s)
                """,
                (
                    request.review_request_id, request.schema_version, self.owner_id,
                    request.target_kind, request.target_id, *target_columns,
                    request.required_role,
                    Jsonb(request.model_dump(mode="json")), request.content_hash,
                    request.created_at,
                ),
            )

    def record_review_decision(self, decision: HumanReviewDecision) -> None:
        if decision.owner_id != self.owner_id:
            raise ValueError("review decision owner mismatch")
        with self.repository.pool.connection() as connection, connection.transaction():
            request = connection.execute(
                """
                SELECT required_role FROM havre.evaluation_review_requests
                WHERE owner_id = %s AND review_request_id = %s
                """,
                (self.owner_id, decision.review_request_id),
            ).fetchone()
            if request is None:
                raise LookupError("review request not found")
            if request["required_role"] != decision.reviewer_role:
                raise ValueError("reviewer role does not satisfy the request")
            connection.execute(
                """
                INSERT INTO havre.evaluation_review_decisions (
                    review_decision_id, schema_version, owner_id, review_request_id,
                    reviewer_role, reviewer_ref, decision, blocking_finding_count,
                    release_promotion_authorized, payload, content_hash, decided_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,false,%s,%s,%s)
                """,
                (
                    decision.review_decision_id, decision.schema_version, self.owner_id,
                    decision.review_request_id, decision.reviewer_role,
                    decision.reviewer_ref, decision.decision,
                    len(decision.blocking_findings),
                    Jsonb(decision.model_dump(mode="json")), decision.content_hash,
                    decision.decided_at,
                ),
            )

    def persist_release_comparison(self, comparison: ReleaseComparison) -> None:
        if comparison.owner_id != self.owner_id:
            raise ValueError("release comparison owner mismatch")
        with self.repository.pool.connection() as connection, connection.transaction():
            connection.execute(
                """
                INSERT INTO havre.release_comparisons (
                    comparison_id, schema_version, owner_id, baseline_bundle_id,
                    candidate_bundle_id, automated_recommendation,
                    critical_regression_count, automatic_promotion_authorized,
                    payload, content_hash, created_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,false,%s,%s,%s)
                """,
                (
                    comparison.comparison_id, comparison.schema_version, self.owner_id,
                    comparison.baseline_bundle_id, comparison.candidate_bundle_id,
                    comparison.automated_recommendation,
                    len(comparison.critical_regressions),
                    Jsonb(comparison.model_dump(mode="json")), comparison.content_hash,
                    comparison.created_at,
                ),
            )

    def authorize_artifact_access(
        self, *, artifact_id: UUID, actor_ref: str, role: str, purpose: str
    ) -> str:
        if role not in {"owner", "technical_reviewer", "human_reviewer"}:
            raise ValueError("unknown evaluation artifact access role")
        if not actor_ref or len(actor_ref) > 240 or not purpose or len(purpose) > 500:
            raise ValueError("access actor and purpose must be present and bounded")
        artifact_uri: str | None = None
        allowed = False
        with self.repository.pool.connection() as connection, connection.transaction():
            artifact = connection.execute(
                """
                SELECT artifact_uri FROM havre.evaluation_artifacts
                WHERE owner_id = %s AND artifact_id = %s
                """,
                (self.owner_id, artifact_id),
            ).fetchone()
            if artifact is None:
                raise LookupError("evaluation artifact not found")
            artifact_uri = artifact["artifact_uri"]
            allowed = connection.execute(
                """
                SELECT 1 FROM havre.evaluation_artifact_access_grants
                WHERE owner_id = %s AND artifact_id = %s AND actor_ref = %s
                  AND role = %s AND purpose = %s
                  AND expires_at > statement_timestamp()
                """,
                (self.owner_id, artifact_id, actor_ref, role, purpose),
            ).fetchone() is not None
            connection.execute(
                """
                INSERT INTO havre.evaluation_artifact_access_log (
                    access_log_id, owner_id, artifact_id, actor_ref, role, purpose,
                    decision, reason_code
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    uuid7(), self.owner_id, artifact_id, actor_ref, role, purpose,
                    "allowed" if allowed else "denied",
                    "active_role_grant" if allowed else "no_active_role_grant",
                ),
            )
        if not allowed:
            raise PermissionError("artifact access denied")
        assert artifact_uri is not None
        return artifact_uri

    def explore_trace(self, trace_id: str) -> TraceExploration:
        if (
            len(trace_id) != 32
            or any(character not in "0123456789abcdef" for character in trace_id)
        ):
            raise ValueError("trace_id must be 32 lowercase hex characters")
        nodes: list[TraceNode] = []
        edge_candidates: list[tuple[str, str, str]] = []
        registered = (
            "trace", "spans", "requests", "events", "retrieval", "context",
            "routing", "inference", "provenance", "proactive", "offline",
        )
        observed_sources = {"trace"}
        with self.repository.pool.connection() as connection:
            trace = connection.execute(
                """
                SELECT trace_id, root_request_id, started_at
                FROM havre.traces WHERE owner_id = %s AND trace_id = %s
                """,
                (self.owner_id, trace_id),
            ).fetchone()
            if trace is None:
                raise LookupError("trace not found")
            trace_node = f"trace:{trace_id}"
            nodes.append(TraceNode(
                node_id=trace_node, node_kind="trace", occurred_at=trace["started_at"],
                attributes={"root_request_id": str(trace["root_request_id"])},
            ))
            span_rows = connection.execute(
                """
                SELECT span_id, parent_span_id, name, kind, status, started_at
                FROM havre.spans WHERE trace_id = %s
                ORDER BY started_at, span_id
                """,
                (trace_id,),
            ).fetchall()
            if span_rows:
                observed_sources.add("spans")
            for row in span_rows:
                node_id = f"span:{row['span_id'].strip()}"
                nodes.append(TraceNode(
                    node_id=node_id, node_kind=f"span:{row['kind']}",
                    status=row["status"], occurred_at=row["started_at"],
                    attributes={"name": row["name"]},
                ))
                parent = row["parent_span_id"]
                edge_candidates.append((
                    f"span:{parent.strip()}" if parent else trace_node,
                    node_id, "contains",
                ))
            request_rows = connection.execute(
                """
                SELECT request_id, status, created_at
                FROM havre.interaction_requests
                WHERE owner_id = %s AND trace_id = %s
                ORDER BY created_at, request_id
                """,
                (self.owner_id, trace_id),
            ).fetchall()
            if request_rows:
                observed_sources.add("requests")
            for row in request_rows:
                node_id = f"request:{row['request_id']}"
                nodes.append(TraceNode(
                    node_id=node_id, node_kind="interaction_request",
                    status=row["status"], occurred_at=row["created_at"],
                ))
                edge_candidates.append((trace_node, node_id, "root_request"))
            event_rows = connection.execute(
                """
                SELECT event_id, request_id, event_type, causation_event_id, recorded_at
                FROM havre.events WHERE owner_id = %s AND trace_id = %s
                ORDER BY recorded_at, event_id
                """,
                (self.owner_id, trace_id),
            ).fetchall()
            if event_rows:
                observed_sources.add("events")
            for row in event_rows:
                node_id = f"event:{row['event_id']}"
                nodes.append(TraceNode(
                    node_id=node_id, node_kind="event", status=row["event_type"],
                    occurred_at=row["recorded_at"],
                ))
                source = (
                    f"event:{row['causation_event_id']}"
                    if row["causation_event_id"] is not None
                    else f"request:{row['request_id']}"
                )
                edge_candidates.append((source, node_id, "causes"))

            typed_queries = (
                (
                    "retrieval", "retrieval_results", "retrieval_result_id", "created_at",
                    "NULL::text", "request_id", None, None,
                ),
                (
                    "context", "context_packs", "context_pack_id", "created_at",
                    "purpose", "request_id", None, None,
                ),
                (
                    "route", "route_decisions", "route_decision_id", "created_at",
                    "execution_environment", "request_id", None, None,
                ),
                (
                    "inference", "inference_attempts", "inference_response_id", "created_at",
                    "status", "request_id", "context_pack_id", "route_decision_id",
                ),
            )
            for kind, table, id_column, time_column, status_expr, request_column, first_ref, second_ref in typed_queries:
                reference_select = ""
                if first_ref:
                    reference_select += f", {first_ref} AS first_ref"
                if second_ref:
                    reference_select += f", {second_ref} AS second_ref"
                rows = connection.execute(
                    f"SELECT {id_column} AS item_id, {time_column} AS occurred_at, "
                    f"{status_expr} AS item_status, {request_column} AS request_id"
                    f"{reference_select} FROM havre.{table} "
                    "WHERE owner_id = %s AND trace_id = %s "
                    f"ORDER BY {time_column}, {id_column}",
                    (self.owner_id, trace_id),
                ).fetchall()
                if rows:
                    observed_sources.add({"route": "routing"}.get(kind, kind))
                for row in rows:
                    node_id = f"{kind}:{row['item_id']}"
                    nodes.append(TraceNode(
                        node_id=node_id, node_kind=kind, status=row["item_status"],
                        occurred_at=row["occurred_at"],
                    ))
                    edge_candidates.append((f"request:{row['request_id']}", node_id, "produces"))
                    if kind == "inference":
                        edge_candidates.append((f"context:{row['first_ref']}", node_id, "supplies_context"))
                        edge_candidates.append((f"route:{row['second_ref']}", node_id, "selects_provider"))

            provenance_rows = connection.execute(
                """
                SELECT provenance_edge_id, source_kind, source_id, derived_kind,
                       derived_id, relation, created_at
                FROM havre.provenance_edges
                WHERE owner_id = %s AND trace_id = %s
                ORDER BY created_at, provenance_edge_id
                """,
                (self.owner_id, trace_id),
            ).fetchall()
            if provenance_rows:
                observed_sources.add("provenance")
            for row in provenance_rows:
                node_id = f"provenance:{row['provenance_edge_id']}"
                nodes.append(TraceNode(
                    node_id=node_id, node_kind="provenance_edge",
                    status=row["relation"], occurred_at=row["created_at"],
                    attributes={
                        "source_kind": row["source_kind"],
                        "derived_kind": row["derived_kind"],
                    },
                ))
                source_id = (
                    f"event:{row['source_id']}"
                    if row["source_kind"] == "event" else trace_node
                )
                edge_candidates.append((source_id, node_id, "provenance_source"))

            proactive_rows = connection.execute(
                """
                SELECT 'trigger' AS kind, trigger_id AS item_id, request_id AS parent_id,
                       recorded_at AS occurred_at, NULL::text AS item_status
                FROM havre.proactive_triggers WHERE owner_id = %s AND trace_id = %s
                UNION ALL
                SELECT 'proposal', proposal_id, primary_trigger_id, created_at, NULL::text
                FROM havre.proactive_proposals WHERE owner_id = %s AND trace_id = %s
                UNION ALL
                SELECT 'decision', interruption_decision_id, proposal_id, decided_at, decision
                FROM havre.interruption_decisions WHERE owner_id = %s AND trace_id = %s
                UNION ALL
                SELECT 'proactive_context', proactive_context_pack_id,
                       interruption_decision_id, created_at, NULL::text
                FROM havre.proactive_context_packs WHERE owner_id = %s AND trace_id = %s
                UNION ALL
                SELECT 'rendering', rendering_id, proactive_context_pack_id,
                       created_at, NULL::text
                FROM havre.rendered_proactive_messages WHERE owner_id = %s AND trace_id = %s
                UNION ALL
                SELECT 'delivery', delivery_attempt_id, rendering_id,
                       created_at, status
                FROM havre.proactive_delivery_attempts WHERE owner_id = %s AND trace_id = %s
                UNION ALL
                SELECT 'owner_action', action_id, proposal_id,
                       observed_at, action_type
                FROM havre.proactive_owner_actions WHERE owner_id = %s AND trace_id = %s
                UNION ALL
                SELECT 'lifecycle_event', lifecycle_event_id, proposal_id,
                       recorded_at, event_type
                FROM havre.proactive_lifecycle_events WHERE owner_id = %s AND trace_id = %s
                ORDER BY occurred_at, item_id
                """,
                tuple(value for _ in range(8) for value in (self.owner_id, trace_id)),
            ).fetchall()
            if proactive_rows:
                observed_sources.add("proactive")
            parent_prefix = {
                "trigger": "request", "proposal": "trigger", "decision": "proposal",
                "proactive_context": "decision", "rendering": "proactive_context",
                "delivery": "rendering",
                "owner_action": "proposal", "lifecycle_event": "proposal",
            }
            for row in proactive_rows:
                node_id = f"{row['kind']}:{row['item_id']}"
                nodes.append(TraceNode(
                    node_id=node_id, node_kind=row["kind"], status=row["item_status"],
                    occurred_at=row["occurred_at"],
                ))
                edge_candidates.append((
                    f"{parent_prefix[row['kind']]}:{row['parent_id']}",
                    node_id, "lifecycle",
                ))

            offline_rows = connection.execute(
                """
                SELECT 'reflection_proposal' AS kind,
                       reflection_proposal_id AS item_id, created_at,
                       proposal_kind AS item_status
                FROM havre.reflection_proposals WHERE owner_id = %s AND trace_id = %s
                UNION ALL
                SELECT 'memory_lifecycle_proposal', lifecycle_proposal_id,
                       created_at, action
                FROM havre.memory_lifecycle_proposals WHERE owner_id = %s AND trace_id = %s
                ORDER BY created_at, item_id
                """,
                (self.owner_id, trace_id, self.owner_id, trace_id),
            ).fetchall()
            if offline_rows:
                observed_sources.add("offline")
            for row in offline_rows:
                node_id = f"{row['kind']}:{row['item_id']}"
                nodes.append(TraceNode(
                    node_id=node_id, node_kind=row["kind"], status=row["item_status"],
                    occurred_at=row["created_at"],
                ))
                edge_candidates.append((trace_node, node_id, "offline_derivative"))

        node_ids = {node.node_id for node in nodes}
        missing = tuple(item for item in registered if item not in observed_sources)
        edges = tuple(
            TraceEdge(source_node_id=source, target_node_id=target, relation=relation)
            for source, target, relation in edge_candidates
            if source in node_ids and target in node_ids
        )
        return TraceExploration(
            owner_id=self.owner_id, trace_id=trace_id,
            nodes=tuple(nodes), edges=tuple(edges),
            registered_source_kinds=registered,
            missing_source_kinds=missing,
            complete_for_registered_sources=(len(missing) == 0),
        )
