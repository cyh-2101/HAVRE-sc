from __future__ import annotations

import os
import asyncio
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from companion.evaluation import (
    ArtifactRetentionReview,
    EvidenceBundle,
    HumanReviewDecision,
    HumanReviewRequest,
    Stage8OperationalEvidence,
)
from companion.identity import IdentityLoader
from companion.application import InteractionCommand, InteractionService
from companion.context import ContextBuilder
from companion.life_context import (
    ContextSourceHealth, LifeContextObservation, SignalFreshness,
    classify_observation_eligibility,
)
from companion.persistence import (
    PostgresRepository, Stage7PostgresStore, Stage8PostgresStore, apply_migrations,
)
from companion.persistence.proactive import ProactivePostgresStore
from companion.memory import DeterministicEmbeddingProvider, DeterministicEpisodicExtractor
from companion.memory.service import MemoryService, MemoryWorker
from companion.offline import MemoryLifecycleAction, MemoryLifecycleProposal
from companion.policy import DataPolicy, PrivacyClass
from companion.proactive import ProactivePreferenceRevision
from mlsys.retrieval.service import RetrievalService
from mlsys.serving import DeterministicLocalProvider, Stage1Router
from evals.unified_runner import (
    compare_evidence_bundles, finalize_stage8_evidence_bundle,
    run_stage8_unified_evaluation,
)


DATABASE_URL = os.getenv("HAVRE_TEST_DATABASE_URL")
PROJECT_ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(DATABASE_URL, "HAVRE_TEST_DATABASE_URL is required")
class Stage8PostgresIntegrationTests(unittest.TestCase):
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
        cls.store = Stage8PostgresStore(repository=cls.repository, owner_id=cls.owner)
        cls.operational_evidence = cls._exercise_stage67_runtime()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.repository.close()

    def test_empty_payload_cannot_forge_accepted_stage8_closure(self) -> None:
        with self.assertRaises(psycopg.errors.CheckViolation):
            with self.repository.pool.connection() as connection, connection.transaction():
                connection.execute(
                    """
                    INSERT INTO havre.evidence_bundles (
                        evidence_bundle_id,schema_version,owner_id,candidate_release_id,
                        runner_version,automated_gate,explicit_decision,decision_scope,
                        release_promotion_authorized,critical_failure_count,payload,
                        content_hash,created_at
                    ) VALUES (%s,1,%s,'forged-empty-payload','unified-evaluation-runner-v1',
                              'candidate_review','accepted_for_stage9_candidate_foundation',
                              'local_candidate_evidence_only',false,0,'{}'::jsonb,%s,%s)
                    """,
                    (uuid.uuid4(), self.owner, "sha256:" + "0" * 64, datetime.now(UTC)),
                )

    @classmethod
    def _exercise_stage67_runtime(cls) -> Stage8OperationalEvidence:
        now = datetime.now(UTC)
        proactive = ProactivePostgresStore(
            repository=cls.repository, owner_id=cls.owner,
            identity=IdentityLoader(PROJECT_ROOT / "identity").load(),
        )
        proactive.save_preference(ProactivePreferenceRevision(
            owner_id=cls.owner, revision=1, global_enabled=True,
            category_permissions={"owner_reminder": "allowed"},
            allowed_channels=("web_inbox",), global_budget_per_24h=4,
            category_budget_per_24h={"owner_reminder": 4}, cooldown_seconds=60,
            authorization_ref="stage8-local-synthetic-operational-evidence",
        ))
        key = f"stage8-operational-{uuid.uuid4()}"
        command = dict(
            trigger_type="owner_requested_reminder", source_kind="owner_reminder",
            source_refs=(f"owner-reminder/{key}",), subject_refs=(f"goal/{key}",),
            category="owner_reminder", reason_code="owner_requested_fixture",
            reason_summary="Stage 8 local synthetic lifecycle evidence",
            intended_benefit="Exercise the authorized local synthetic path",
            data_policy=DataPolicy.owner_default(PrivacyClass.LOCAL_ONLY, memory_eligible=False),
            preference_revision=1, idempotency_key=key, observed_at=now,
            earliest_eligible_at=now - timedelta(seconds=1),
            expires_at=now + timedelta(hours=1), deduplication_key=f"dedupe:{key}",
        )
        sent = proactive.execute_fixture(**command)
        replay = proactive.execute_fixture(**command)
        owner_action = proactive.record_owner_action(
            proposal_id=sent.proposal.proposal_id, action_type="dismissed",
            idempotency_key=f"stage8-action-{uuid.uuid4()}",
            reason="Local synthetic interruption-quality linkage",
            observed_at=now + timedelta(seconds=1),
        )
        proactive.save_preference(ProactivePreferenceRevision(owner_id=cls.owner, revision=2))
        disabled_key = f"stage8-disabled-{uuid.uuid4()}"
        dropped = proactive.execute_fixture(**{
            **command,
            "source_refs": (f"owner-reminder/{disabled_key}",),
            "subject_refs": (),
            "preference_revision": 2,
            "idempotency_key": disabled_key,
            "deduplication_key": f"dedupe:{disabled_key}",
        })
        embedding = DeterministicEmbeddingProvider()
        memory = MemoryService(repository=cls.repository, embedding_provider=embedding)
        interaction = InteractionService(
            owner_id=cls.owner, identity=IdentityLoader(PROJECT_ROOT / "identity").load(),
            repository=cls.repository,
            context_builder=ContextBuilder(max_input_tokens=4096, reserved_output_tokens=256),
            router=Stage1Router(), provider=DeterministicLocalProvider(),
            retrieval_service=RetrievalService(
                repository=cls.repository, embedding_provider=embedding,
            ),
        )
        memory_source = asyncio.run(interaction.interact(InteractionCommand(
            message="Stage 8 synthetic memory lifecycle target.", memory_eligible=True,
            channel="api", idempotency_key=f"stage8-memory-{uuid.uuid4()}",
        )))
        worker = MemoryWorker(
            repository=cls.repository, extractor=DeterministicEpisodicExtractor(),
            owner_id=cls.owner, worker_id="stage8-memory-worker",
        )
        assert worker.run_once() is not None
        candidate = next(
            row for row in memory.list_candidates(owner_id=cls.owner)
            if row["source_event_id"] == memory_source.user_event_id
        )
        revision = memory.accept_candidate(
            owner_id=cls.owner, candidate_id=candidate["candidate_id"],
            reason="Owner-created local synthetic Stage 8 lifecycle target",
        )
        stage7 = Stage7PostgresStore(repository=cls.repository, owner_id=cls.owner)
        stage7.enqueue(
            job_type="daily_reflection", window_start=now - timedelta(minutes=1),
            window_end=now + timedelta(minutes=1), idempotency_key=f"stage8-{uuid.uuid4()}",
        )
        offline = stage7.run_once(worker_id="stage8-operational-evidence")
        assert offline is not None and offline["memory_lifecycle_proposal_id"] is not None
        review = stage7.review_memory_lifecycle(
            lifecycle_proposal_id=offline["memory_lifecycle_proposal_id"],
            decision="accepted", reason="Proposal-only Stage 8 synthetic review",
        )
        stage7.propose_memory_lifecycle(MemoryLifecycleProposal(
            owner_id=cls.owner, action=MemoryLifecycleAction.PROMOTE,
            memory_class="episodic",
            source_memory_refs=(
                f"memory/{revision.memory_id}/revision/{revision.revision}",
            ),
            proposed_content_text="Expired proposal must not become current memory.",
            valid_from=now - timedelta(days=2), valid_to=now - timedelta(days=1),
            reason="Stage 8 stale-current-use local synthetic coverage",
            data_policy=revision.data_policy, trace_id=memory_source.trace_id,
        ))
        lifecycle_reviews = []
        for action, decision in (
            (MemoryLifecycleAction.ARCHIVE, "accepted"),
            (MemoryLifecycleAction.RECONSOLIDATE, "rejected"),
        ):
            proposal = MemoryLifecycleProposal(
                owner_id=cls.owner, action=action, memory_class="episodic",
                source_memory_refs=(
                    f"memory/{revision.memory_id}/revision/{revision.revision}",
                ),
                target_memory_id=revision.memory_id, target_revision=revision.revision,
                reason=f"Stage 8 local synthetic {action.value} proposal coverage",
                data_policy=revision.data_policy, trace_id=memory_source.trace_id,
            )
            stage7.propose_memory_lifecycle(proposal)
            lifecycle_reviews.append(stage7.review_memory_lifecycle(
                lifecycle_proposal_id=proposal.lifecycle_proposal_id,
                decision=decision, reason="Proposal-only review; no automatic mutation",
            ))
        before, before_manifest = stage7.build_canonical_dataset_snapshot()
        repeated, repeated_manifest = stage7.build_canonical_dataset_snapshot()
        assert sent.assistant_event_id is not None
        erased = cls.repository.erase_source_event_derivatives(
            owner_id=cls.owner, source_event_id=sent.assistant_event_id,
        )
        rebuilt, _ = stage7.build_canonical_dataset_snapshot()
        stage7.enqueue(
            job_type="periodic_consolidation", window_start=now - timedelta(minutes=1),
            window_end=now + timedelta(minutes=2),
            idempotency_key=f"stage8-post-erasure-{uuid.uuid4()}",
        )
        post_erasure = stage7.run_once(worker_id="stage8-post-erasure-evidence")
        assert post_erasure is not None
        with cls.repository.pool.connection() as connection:
            memory_count = connection.execute(
                "SELECT count(*) AS value FROM havre.memory_revisions WHERE owner_id = %s",
                (cls.owner,),
            ).fetchone()["value"]
            active_memory_count = connection.execute(
                """
                SELECT count(*) AS value FROM havre.memory_revisions
                WHERE owner_id=%s AND memory_id=%s AND revision=%s AND status='active'
                """,
                (cls.owner, revision.memory_id, revision.revision),
            ).fetchone()["value"]
        fresh = LifeContextObservation(
            owner_id=cls.owner, value="available",
            freshness=SignalFreshness(
                observed_at=now, valid_until=now + timedelta(minutes=5),
                clock_uncertainty_seconds=1,
            ),
            data_policy=DataPolicy.owner_default(PrivacyClass.LOCAL_ONLY, memory_eligible=False),
            trace_id=sent.trace_id,
        )
        available = ContextSourceHealth(
            owner_id=cls.owner, status="available", observed_at=now,
            trace_id=sent.trace_id,
        )
        revoked = ContextSourceHealth(
            owner_id=cls.owner, status="revoked", observed_at=now,
            trace_id=sent.trace_id,
        )
        trace_ids = (sent.trace_id, dropped.trace_id, memory_source.trace_id)
        explorations = tuple(cls.store.explore_trace(trace_id) for trace_id in trace_ids)
        trace_hashes = {item.trace_id: item.content_hash for item in explorations}
        covered_sources = {
            source
            for item in explorations
            for source in set(item.registered_source_kinds) - set(item.missing_source_kinds)
        }
        all_registered_sources = set(explorations[0].registered_source_kinds)
        return Stage8OperationalEvidence(
            owner_id=cls.owner,
            memory_lifecycle_outcomes={
                "ordinary-event-remains-event-only": "proposal_pending"
                if post_erasure["reflection_proposal_id"]
                and post_erasure["memory_lifecycle_proposal_id"] else "missing",
                "historical-validity-not-current": "excluded_stale_current",
                "archive-review-does-not-mutate-memory": "active_memory"
                if review.applied_artifact_ref is None and active_memory_count == 1 else "mutated",
                "reconsolidation-rejection-does-not-mutate-memory": "active_memory"
                if all(item.applied_artifact_ref is None for item in lifecycle_reviews)
                and active_memory_count == 1 else "mutated",
            },
            erasure_regeneration_outcomes={
                "revoked-source-cannot-regenerate": "rejected_source_revoked"
                if erased["memory_lifecycle_proposals"] >= 1 and all(
                    item.source_ref != f"event/{sent.assistant_event_id}"
                    for item in rebuilt.rejections
                ) else "regenerated",
                "eligible-synthetic-source-can-rebuild-manifest": "same_content_hash"
                if before.content_hash == repeated.content_hash
                and before_manifest.content_hash == repeated_manifest.content_hash else "hash_changed",
            },
            source_health_outcomes={
                "fresh-consented-observation": classify_observation_eligibility(
                    observation=fresh, health=available, consent_active=True, as_of=now,
                ),
                "stale-observation": classify_observation_eligibility(
                    observation=fresh, health=available, consent_active=True,
                    as_of=now + timedelta(minutes=10),
                ),
                "revoked-observation": classify_observation_eligibility(
                    observation=fresh, health=revoked, consent_active=False, as_of=now,
                ),
                "missing-source-is-not-negative-evidence": classify_observation_eligibility(
                    observation=None, health=None, consent_active=True, as_of=now,
                ),
            },
            proactive_outcomes={
                "trace_complete": covered_sources == all_registered_sources,
                "proposal_decision_render_delivery_linked": all((
                    sent.context_pack, sent.rendering, sent.delivery_attempt,
                    sent.assistant_event_id,
                )),
                "delivery_idempotent": replay.idempotent_replay
                and replay.proposal.proposal_id == sent.proposal.proposal_id,
                "privacy_local_only": sent.delivery_attempt is not None
                and sent.delivery_attempt.external_delivery_authorized is False,
                "missing_context_fails_closed": dropped.context_pack is None
                and dropped.rendering is None and dropped.delivery_attempt is None,
                "owner_action_linked": owner_action.proposal_id == sent.proposal.proposal_id,
            },
            trace_ids=trace_ids,
            trace_content_hashes=trace_hashes,
        )

    def test_bundle_artifact_access_and_human_review_are_append_only(self) -> None:
        bundle, artifacts, calibration = run_stage8_unified_evaluation(
            project_root=PROJECT_ROOT, owner_id=self.owner,
            candidate_release_id=f"stage8-integration-{uuid.uuid4()}",
            operational_evidence=self.operational_evidence,
        )
        self.store.persist_bundle(
            bundle=bundle, artifacts=artifacts, calibrations=(calibration,),
            operational_evidence=self.operational_evidence,
        )
        reviewer = "test:independent-reviewer"
        review_purpose = "independent Stage 8 technical review"
        with self.assertRaises(PermissionError):
            self.store.authorize_artifact_access(
                artifact_id=artifacts[0].artifact_id, actor_ref=reviewer,
                role="technical_reviewer", purpose=review_purpose,
            )
        for artifact in artifacts:
            self.store.grant_artifact_access(
                artifact_id=artifact.artifact_id, actor_ref=reviewer,
                role="technical_reviewer", purpose=review_purpose,
            )
        uri = self.store.authorize_artifact_access(
            artifact_id=artifacts[0].artifact_id, actor_ref=reviewer,
            role="technical_reviewer", purpose=review_purpose,
        )
        self.assertTrue(uri.startswith("inline://"))
        request = HumanReviewRequest(
            owner_id=self.owner, target_kind="evidence_bundle",
            target_id=bundle.evidence_bundle_id,
            required_role="technical_reviewer",
            review_scope="Stage 8 technical completeness and blocker review",
        )
        self.store.request_review(request)
        decision = HumanReviewDecision(
            owner_id=self.owner, review_request_id=request.review_request_id,
            reviewer_role="technical_reviewer", reviewer_ref=reviewer,
            decision="accepted_for_candidate_evidence",
            rationale="Synthetic integration review found no blocking fixture failure.",
        )
        self.store.record_review_decision(decision)
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
            with self.repository.pool.connection() as connection:
                connection.execute(
                    """
                    UPDATE havre.evaluation_review_decisions
                    SET decision = 'rejected' WHERE review_decision_id = %s
                    """,
                    (decision.review_decision_id,),
                )
        with self.repository.pool.connection() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT count(*) AS value FROM havre.stage8_integrity_violations WHERE owner_id = %s",
                    (self.owner,),
                ).fetchone()["value"],
                0,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT count(*) AS value FROM havre.evaluation_artifact_access_log WHERE owner_id = %s",
                    (self.owner,),
                ).fetchone()["value"],
                2,
            )

    def test_database_rejects_external_or_training_eligible_artifact(self) -> None:
        with self.repository.pool.connection() as connection:
            policy = connection.execute(
                """
                SELECT retention_policy_id FROM havre.evaluation_retention_policies
                WHERE owner_id = %s LIMIT 1
                """,
                (self.owner,),
            ).fetchone()
            self.assertIsNotNone(policy)
        with self.assertRaises(psycopg.errors.CheckViolation):
            with self.repository.pool.connection() as connection:
                connection.execute(
                    """
                    INSERT INTO havre.evaluation_artifacts (
                        artifact_id, schema_version, owner_id, retention_policy_id,
                        artifact_kind, artifact_uri, artifact_content_hash, media_type,
                        privacy_class, memory_eligible, training_eligible, cloud_eligible,
                        external_transfer_allowed, payload, content_hash, created_at
                    ) VALUES (%s,1,%s,%s,'suite_result','local://forged',%s,
                              'application/json','LOCAL_ONLY',false,true,false,false,
                              %s,%s,statement_timestamp())
                    """,
                    (
                        uuid.uuid4(), self.owner, policy["retention_policy_id"],
                        "sha256:" + "1" * 64, Jsonb({}), "sha256:" + "2" * 64,
                    ),
                )

    def test_database_binds_review_target_and_reviewer_role(self) -> None:
        missing_target = uuid.uuid4()
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            with self.repository.pool.connection() as connection:
                connection.execute(
                    """
                    INSERT INTO havre.evaluation_review_requests (
                        review_request_id, schema_version, owner_id, target_kind,
                        target_id, evidence_bundle_id, required_role,
                        release_promotion_in_scope, payload, content_hash, created_at
                    ) VALUES (%s,1,%s,'evidence_bundle',%s,%s,'technical_reviewer',
                              false,'{}'::jsonb,%s,statement_timestamp())
                    """,
                    (
                        uuid.uuid4(), self.owner, missing_target, missing_target,
                        "sha256:" + "1" * 64,
                    ),
                )
        bundle, artifacts, calibration = run_stage8_unified_evaluation(
            project_root=PROJECT_ROOT, owner_id=self.owner,
            candidate_release_id=f"review-role-{uuid.uuid4()}",
            operational_evidence=self.operational_evidence,
        )
        self.store.persist_bundle(
            bundle=bundle, artifacts=artifacts, calibrations=(calibration,),
            operational_evidence=self.operational_evidence,
        )
        request = HumanReviewRequest(
            owner_id=self.owner, target_kind="judge_calibration",
            target_id=calibration.calibration_id, required_role="technical_reviewer",
            review_scope="Direct SQL role binding regression",
        )
        self.store.request_review(request)
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
            with self.repository.pool.connection() as connection:
                connection.execute(
                    """
                    INSERT INTO havre.evaluation_review_decisions (
                        review_decision_id, schema_version, owner_id, review_request_id,
                        reviewer_role, reviewer_ref, decision, blocking_finding_count,
                        release_promotion_authorized, payload, content_hash, decided_at
                    ) VALUES (%s,1,%s,%s,'human_reviewer','forged:reviewer',
                              'accepted_for_candidate_evidence',0,false,'{}'::jsonb,%s,
                              statement_timestamp())
                    """,
                    (
                        uuid.uuid4(), self.owner, request.review_request_id,
                        "sha256:" + "2" * 64,
                    ),
                )

    def test_trace_explorer_is_owner_scoped_and_content_redacted(self) -> None:
        trace_id = uuid.uuid4().hex
        now = datetime.now(UTC)
        with self.repository.pool.connection() as connection, connection.transaction():
            connection.execute(
                """
                INSERT INTO havre.traces (
                    trace_id, owner_id, root_request_id, trace_flags, started_at
                ) VALUES (%s,%s,%s,'01',%s)
                """,
                (trace_id, self.owner, uuid.uuid4(), now),
            )
            connection.execute(
                """
                INSERT INTO havre.spans (
                    span_id, trace_id, name, kind, started_at, ended_at,
                    duration_ms, status, attributes
                ) VALUES (%s,%s,'stage8.synthetic','internal',%s,%s,1.0,'ok',%s)
                """,
                (
                    uuid.uuid4().hex[:16], trace_id, now,
                    now + timedelta(milliseconds=1), Jsonb({"safe": True}),
                ),
            )
        explored = self.store.explore_trace(trace_id)
        self.assertFalse(explored.complete_for_registered_sources)
        self.assertTrue(explored.missing_source_kinds)
        self.assertTrue(all(node.content_redacted for node in explored.nodes))
        self.assertEqual({node.node_kind for node in explored.nodes}, {"trace", "span:internal"})

    def test_operational_trace_covers_real_proactive_and_offline_sources(self) -> None:
        explored = tuple(
            self.store.explore_trace(trace_id)
            for trace_id in self.operational_evidence.trace_ids
        )
        kinds = {node.node_kind for item in explored for node in item.nodes}
        self.assertTrue({
            "trace", "interaction_request", "event", "trigger", "proposal",
            "decision", "proactive_context", "rendering", "delivery",
            "owner_action", "lifecycle_event",
            "reflection_proposal", "memory_lifecycle_proposal",
        }.issubset(kinds))
        covered = {
            source for item in explored
            for source in set(item.registered_source_kinds) - set(item.missing_source_kinds)
        }
        self.assertEqual(covered, set(explored[0].registered_source_kinds))

    def test_persistence_recomputes_operational_outcomes_and_trace_hashes(self) -> None:
        bundle, artifacts, calibration = run_stage8_unified_evaluation(
            project_root=PROJECT_ROOT, owner_id=self.owner,
            candidate_release_id=f"forged-operational-{uuid.uuid4()}",
            operational_evidence=self.operational_evidence,
        )
        forged_hash_payload = self.operational_evidence.model_dump(mode="python")
        forged_hash_payload["trace_content_hashes"] = {
            trace_id: "sha256:" + "1" * 64
            for trace_id in self.operational_evidence.trace_ids
        }
        forged_hash_payload["content_hash"] = ""
        forged_hash = Stage8OperationalEvidence.model_validate(forged_hash_payload)
        with self.assertRaisesRegex(ValueError, "trace hashes"):
            self.store.persist_bundle(
                bundle=bundle, artifacts=artifacts, calibrations=(calibration,),
                operational_evidence=forged_hash,
            )
        forged_outcome_payload = self.operational_evidence.model_dump(mode="python")
        forged_outcome_payload["proactive_outcomes"] = {
            **forged_outcome_payload["proactive_outcomes"],
            "delivery_idempotent": False,
        }
        forged_outcome_payload["content_hash"] = ""
        forged_outcome = Stage8OperationalEvidence.model_validate(forged_outcome_payload)
        with self.assertRaisesRegex(ValueError, "proactive outcomes"):
            self.store.persist_bundle(
                bundle=bundle, artifacts=artifacts, calibrations=(calibration,),
                operational_evidence=forged_outcome,
            )

    def test_durable_gate_rejects_forged_case_summary(self) -> None:
        rejected, _, calibration = run_stage8_unified_evaluation(
            project_root=PROJECT_ROOT, owner_id=self.owner,
            candidate_release_id=f"forged-gate-source-{uuid.uuid4()}",
        )
        # Persist the runs without a bundle by rolling the same inserts through a
        # valid rejected bundle first, then attempt a second forged summary.
        rejected_artifacts = tuple()
        rejected_payload = rejected.model_dump(mode="python")
        rejected_payload.update({"artifact_ids": (), "content_hash": ""})
        rejected_without_artifacts = EvidenceBundle.model_validate(rejected_payload)
        self.store.persist_bundle(
            bundle=rejected_without_artifacts,
            artifacts=rejected_artifacts, calibrations=(calibration,),
        )
        forged_id = uuid.uuid4()
        forged_release = f"forged-{uuid.uuid4()}"
        forged_hash = "sha256:" + "0" * 64
        payload = rejected.model_dump(mode="json")
        payload.update({
            "evidence_bundle_id": str(forged_id), "artifact_ids": [],
            "trace_ids": [], "judge_calibration_ids": [],
            "critical_failures": [], "automated_gate": "candidate_review",
            "candidate_release_id": forged_release, "content_hash": forged_hash,
        })
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
            with self.repository.pool.connection() as connection, connection.transaction():
                connection.execute(
                    """
                    INSERT INTO havre.evidence_bundles (
                        evidence_bundle_id, schema_version, owner_id, candidate_release_id,
                        runner_version, automated_gate, explicit_decision, decision_scope,
                        release_promotion_authorized, critical_failure_count,
                        payload, content_hash, created_at
                    ) VALUES (%s,1,%s,%s,'unified-evaluation-runner-v1',
                              'candidate_review','pending_human_review',
                              'local_candidate_evidence_only',false,0,%s,%s,%s)
                    """,
                    (
                        forged_id, self.owner, forged_release, Jsonb(payload),
                        forged_hash, datetime.now(UTC),
                    ),
                )
                for suite in rejected.suite_results:
                    connection.execute(
                        """
                        INSERT INTO havre.evidence_bundle_runs (
                            owner_id, evidence_bundle_id, evaluation_run_id
                        ) VALUES (%s,%s,%s)
                        """,
                        (self.owner, forged_id, suite.suite_result_id),
                    )

        baseline, _, baseline_calibration = run_stage8_unified_evaluation(
            project_root=PROJECT_ROOT, owner_id=self.owner,
            candidate_release_id=f"comparison-baseline-{uuid.uuid4()}",
            operational_evidence=self.operational_evidence,
        )
        baseline_payload = baseline.model_dump(mode="python")
        baseline_payload.update({"artifact_ids": (), "content_hash": ""})
        baseline_without_artifacts = EvidenceBundle.model_validate(baseline_payload)
        self.store.persist_bundle(
            bundle=baseline_without_artifacts, artifacts=(),
            calibrations=(baseline_calibration,),
            operational_evidence=self.operational_evidence,
        )
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
            with self.repository.pool.connection() as connection, connection.transaction():
                comparison_id = uuid.uuid4()
                comparison_hash = "sha256:" + "3" * 64
                connection.execute(
                    """
                    INSERT INTO havre.release_comparisons (
                        comparison_id, schema_version, owner_id, baseline_bundle_id,
                        candidate_bundle_id, automated_recommendation,
                        critical_regression_count, automatic_promotion_authorized,
                        payload, content_hash, created_at
                    ) VALUES (%s,1,%s,%s,%s,'candidate_review',0,false,%s,%s,%s)
                    """,
                    (
                        comparison_id, self.owner,
                        baseline_without_artifacts.evidence_bundle_id,
                        rejected_without_artifacts.evidence_bundle_id,
                        Jsonb({
                            "comparison_id": str(comparison_id),
                            "owner_id": str(self.owner),
                            "baseline_bundle_id": str(baseline_without_artifacts.evidence_bundle_id),
                            "candidate_bundle_id": str(rejected_without_artifacts.evidence_bundle_id),
                            "controlled_differences": [],
                            "uncontrolled_differences": [],
                            "observed_version_differences": [],
                            "critical_regressions": [],
                            "automated_recommendation": "candidate_review",
                            "content_hash": comparison_hash,
                        }),
                        comparison_hash, datetime.now(UTC),
                    ),
                )

    def test_retention_extension_and_expiry_bounds_are_durable(self) -> None:
        bundle, artifacts, calibration = run_stage8_unified_evaluation(
            project_root=PROJECT_ROOT, owner_id=self.owner,
            candidate_release_id=f"retention-{uuid.uuid4()}",
            operational_evidence=self.operational_evidence,
        )
        self.store.persist_bundle(
            bundle=bundle, artifacts=artifacts, calibrations=(calibration,),
            operational_evidence=self.operational_evidence,
        )
        artifact = artifacts[0]
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
            with self.repository.pool.connection() as connection:
                connection.execute(
                    """
                    INSERT INTO havre.evaluation_artifact_access_grants (
                        access_grant_id, owner_id, artifact_id, actor_ref, role,
                        purpose, granted_by, expires_at
                    ) VALUES (%s,%s,%s,'forged:reviewer','technical_reviewer',
                              'beyond retention','owner',%s)
                    """,
                    (uuid.uuid4(), self.owner, artifact.artifact_id,
                     datetime.now(UTC) + timedelta(days=365)),
                )
        retain_until = datetime.now(UTC) + timedelta(days=60)
        self.store.review_artifact_retention(ArtifactRetentionReview(
            owner_id=self.owner, artifact_id=artifact.artifact_id,
            retain_until=retain_until, reason="Owner keeps local Stage 8 exit evidence.",
        ))
        self.store.grant_artifact_access(
            artifact_id=artifact.artifact_id, actor_ref="reviewer:retained",
            role="technical_reviewer", purpose="retained evidence review",
        )
        with self.repository.pool.connection() as connection:
            expiry = connection.execute(
                """
                SELECT expires_at FROM havre.evaluation_artifact_access_grants
                WHERE owner_id=%s AND artifact_id=%s AND actor_ref='reviewer:retained'
                """,
                (self.owner, artifact.artifact_id),
            ).fetchone()["expires_at"]
        self.assertEqual(expiry, retain_until)

    def test_final_bundle_requires_comparison_and_reviewer_bound_acceptance(self) -> None:
        baseline, baseline_artifacts, baseline_calibration = run_stage8_unified_evaluation(
            project_root=PROJECT_ROOT, owner_id=self.owner,
            candidate_release_id=f"baseline-{uuid.uuid4()}",
            operational_evidence=self.operational_evidence,
        )
        candidate, candidate_artifacts, candidate_calibration = run_stage8_unified_evaluation(
            project_root=PROJECT_ROOT, owner_id=self.owner,
            candidate_release_id=f"candidate-{uuid.uuid4()}",
            operational_evidence=self.operational_evidence,
        )
        self.store.persist_bundle(
            bundle=baseline, artifacts=baseline_artifacts,
            calibrations=(baseline_calibration,),
            operational_evidence=self.operational_evidence,
        )
        self.store.persist_bundle(
            bundle=candidate, artifacts=candidate_artifacts,
            calibrations=(candidate_calibration,),
            operational_evidence=self.operational_evidence,
        )
        comparison = compare_evidence_bundles(
            owner_id=self.owner, baseline=baseline, candidate=candidate,
            controlled_differences=("candidate_release_id",),
        )
        self.store.persist_release_comparison(comparison)
        reviewer = "reviewer:stage8-final"
        purpose = "Stage 8 final technical review"
        for artifact in candidate_artifacts:
            self.store.grant_artifact_access(
                artifact_id=artifact.artifact_id, actor_ref=reviewer,
                role="technical_reviewer", purpose=purpose,
            )
        request = HumanReviewRequest(
            owner_id=self.owner, target_kind="evidence_bundle",
            target_id=candidate.evidence_bundle_id, required_role="technical_reviewer",
            review_scope="Independent blocker review of Stage 8 candidate evidence",
        )
        self.store.request_review(request)
        decision = HumanReviewDecision(
            owner_id=self.owner, review_request_id=request.review_request_id,
            reviewer_role="technical_reviewer", reviewer_ref=reviewer,
            decision="accepted_for_candidate_evidence",
            rationale="Synthetic durable workflow review has no blocking finding.",
        )
        self.store.record_review_decision(decision)
        final, final_artifacts = finalize_stage8_evidence_bundle(
            owner_id=self.owner, candidate=candidate,
            candidate_artifacts=candidate_artifacts, comparison=comparison,
            review_decision=decision,
        )
        self.store.persist_bundle(
            bundle=final, artifacts=final_artifacts,
            calibrations=(candidate_calibration,),
            operational_evidence=self.operational_evidence,
        )
        self.assertEqual(final.explicit_decision, "accepted_for_stage9_candidate_foundation")
        with self.repository.pool.connection() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT count(*) AS value FROM havre.stage8_integrity_violations WHERE owner_id=%s",
                    (self.owner,),
                ).fetchone()["value"],
                0,
            )
