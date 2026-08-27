from __future__ import annotations

import tempfile
import hashlib
import json
import unittest
import uuid
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from pydantic import ValidationError

from companion.consolidation import PatternEvidenceObservation, detect_pattern_candidate
from companion.context import ContextBuilder, ContextRetrievalRejected, PersonalContextItem
from companion.evidence import EvidenceRef, EvidenceRelation, EvidenceSourceKind
from companion.events import (
    EventEnvelope,
    EventType,
    GoalLifecyclePayload,
    TextContentPart,
    UserMessagePayload,
)
from companion.goals import Goal, GoalProjectionMaterial
from companion.hashing import canonical_json, content_hash
from companion.identity import IdentityLoader
from companion.policy import DataPolicy, PrivacyClass
from companion.state import CurrentStateSnapshot
from evals.user_model_evaluation import run_user_model_evaluation


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OWNER_ID = uuid.UUID("00000000-0000-7000-8000-000000000001")


class EvidenceContractTests(unittest.TestCase):
    def test_revisioned_sources_require_exact_revision(self) -> None:
        with self.assertRaises(ValidationError):
            EvidenceRef(
                source_kind=EvidenceSourceKind.MEMORY_REVISION,
                source_id=uuid.uuid4(),
                relation=EvidenceRelation.SUPPORTS,
            )
        with self.assertRaises(ValidationError):
            EvidenceRef(
                source_kind=EvidenceSourceKind.EVENT,
                source_id=uuid.uuid4(),
                source_revision=1,
                relation=EvidenceRelation.SUPPORTS,
            )

    def test_pattern_detector_rejects_one_day_and_retains_counter_evidence(self) -> None:
        start = datetime(2026, 7, 1, tzinfo=UTC)
        transient = detect_pattern_candidate((
            PatternEvidenceObservation(
                source_id=uuid.uuid4(), occurred_at=start, supports_pattern=True
            ),
        ))
        self.assertFalse(transient.eligible_for_proposal)
        stable = detect_pattern_candidate((
            PatternEvidenceObservation(
                source_id=uuid.uuid4(), occurred_at=start, supports_pattern=True
            ),
            PatternEvidenceObservation(
                source_id=uuid.uuid4(),
                occurred_at=start + timedelta(days=7),
                supports_pattern=True,
            ),
            PatternEvidenceObservation(
                source_id=uuid.uuid4(),
                occurred_at=start + timedelta(days=8),
                supports_pattern=False,
            ),
        ))
        self.assertTrue(stable.eligible_for_proposal)
        self.assertEqual(stable.counter_evidence_count, 1)
        self.assertTrue(stable.requires_owner_review)

    def test_pattern_detector_normalizes_utc_and_rejects_naive_time(self) -> None:
        instant = datetime(2026, 7, 2, 0, 30, tzinfo=UTC)
        same_instant = instant.astimezone(timezone(timedelta(hours=-4)))
        result = detect_pattern_candidate((
            PatternEvidenceObservation(
                source_id=uuid.uuid4(), occurred_at=instant, supports_pattern=True
            ),
            PatternEvidenceObservation(
                source_id=uuid.uuid4(),
                occurred_at=same_instant,
                supports_pattern=True,
            ),
        ))
        self.assertFalse(result.eligible_for_proposal)
        self.assertEqual(result.distinct_support_days, 1)
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            detect_pattern_candidate((
                PatternEvidenceObservation(
                    source_id=uuid.uuid4(),
                    occurred_at=datetime(2026, 7, 2, 12, 0),
                    supports_pattern=True,
                ),
            ))

    def test_current_state_must_expire(self) -> None:
        now = datetime.now(UTC)
        evidence = (
            EvidenceRef(
                source_kind=EvidenceSourceKind.EVENT,
                source_id=uuid.uuid4(),
                relation=EvidenceRelation.SUPPORTS,
            ),
        )
        with self.assertRaises(ValidationError):
            CurrentStateSnapshot(
                owner_id=OWNER_ID,
                summary="Tired today.",
                state={"energy": "low"},
                uncertainty=0.2,
                estimated_at=now,
                expires_at=now,
                evidence=evidence,
                created_event_id=uuid.uuid4(),
                trace_id=uuid.uuid4().hex,
                data_policy=DataPolicy.owner_default(PrivacyClass.NORMAL),
            )


class GoalProjectionContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.goal = Goal(
            owner_id=OWNER_ID,
            track="reality",
            title="Keep canonical Goal material exact",
            why="The content hash must bind every and only projection field.",
            next_action="Validate before hashing.",
            review_at=datetime(2026, 9, 1, 8, 0, tzinfo=UTC),
            revision=1,
            last_event_id=uuid.uuid4(),
            data_policy=DataPolicy.owner_default(PrivacyClass.PRIVATE),
        )

    def test_projection_contract_forbids_extra_and_missing_keys(self) -> None:
        material = self.goal.projection_material().model_dump(mode="json")
        top_extra = {**material, "unexpected": True}
        with self.assertRaises(ValidationError):
            GoalProjectionMaterial.model_validate_json(canonical_json(top_extra))

        policy_extra = json.loads(canonical_json(material))
        policy_extra["data_policy"]["unexpected"] = True
        with self.assertRaises(ValidationError):
            GoalProjectionMaterial.model_validate_json(canonical_json(policy_extra))

        missing = dict(material)
        missing.pop("why")
        with self.assertRaises(ValidationError):
            GoalProjectionMaterial.model_validate_json(canonical_json(missing))

    def test_lifecycle_projection_requires_contract_then_unique_canonical_json(self) -> None:
        material = self.goal.projection_material().model_dump(mode="json")
        noncanonical = json.dumps(
            material, ensure_ascii=False, sort_keys=False, separators=(", ", ": ")
        )
        base_payload = {
            "goal_id": self.goal.goal_id,
            "goal_revision": self.goal.revision,
            "action": "created",
            "track": self.goal.track.value,
            "title": self.goal.title,
            "why": self.goal.why,
            "priority": self.goal.priority.value,
            "status": self.goal.status.value,
            "next_action": self.goal.next_action,
            "review_at": self.goal.review_at,
            "reason": "Contract regression",
            "projection_content_hash": "sha256:" + hashlib.sha256(
                noncanonical.encode("utf-8")
            ).hexdigest(),
            "projection_canonical_json": noncanonical,
        }
        with self.assertRaisesRegex(ValidationError, "canonical JSON"):
            GoalLifecyclePayload(**base_payload)

        extra = json.loads(canonical_json(material))
        extra["opaque_bypass"] = "valid JSON with its own matching hash"
        extra_json = canonical_json(extra)
        base_payload.update(
            projection_content_hash=content_hash(extra),
            projection_canonical_json=extra_json,
        )
        with self.assertRaisesRegex(ValidationError, "strict contract"):
            GoalLifecyclePayload(**base_payload)


class Stage4ContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.identity = IdentityLoader(PROJECT_ROOT / "identity").load()
        self.request_id = uuid.uuid4()
        self.event = EventEnvelope(
            event_type=EventType.USER_MESSAGE,
            owner_id=OWNER_ID,
            session_id=uuid.uuid4(),
            request_id=self.request_id,
            trace_id=uuid.uuid4().hex,
            data_policy=DataPolicy.owner_default(PrivacyClass.NORMAL),
            payload=UserMessagePayload(
                content_parts=(TextContentPart(text="piano practice"),),
                channel="api",
            ),
        )

    def test_qualified_belief_context_keeps_confidence_and_sources(self) -> None:
        item = PersonalContextItem(
            owner_id=OWNER_ID,
            section_id="belief-1",
            section_type="user_belief",
            content_text=(
                "Qualified belief (owner-reviewed confidence 0.60; 2 supporting "
                "and 1 counter-evidence sources): piano practice is easier slowly."
            ),
            priority=80,
            source_refs=("belief/test@1", "event/a", "event/b"),
            data_policy=DataPolicy.owner_default(PrivacyClass.NORMAL),
        )
        pack = ContextBuilder(
            max_input_tokens=4096, reserved_output_tokens=256
        ).build(
            request_id=self.request_id,
            trace_id=self.event.trace_id,
            owner_id=OWNER_ID,
            identity=self.identity,
            user_event=self.event,
            personal_context=(item,),
        )
        section = next(value for value in pack.sections if value.section_type == "user_belief")
        self.assertIn("confidence 0.60", section.content_parts[0].text)
        self.assertEqual(section.source_refs, item.source_refs)

    def test_builder_rejects_more_restrictive_personal_context(self) -> None:
        item = PersonalContextItem(
            owner_id=OWNER_ID,
            section_id="belief-private",
            section_type="user_belief",
            content_text="Private belief.",
            priority=80,
            source_refs=("belief/private@1",),
            data_policy=DataPolicy.owner_default(PrivacyClass.LOCAL_ONLY),
        )
        with self.assertRaises(ContextRetrievalRejected):
            ContextBuilder(max_input_tokens=4096, reserved_output_tokens=256).build(
                request_id=self.request_id,
                trace_id=self.event.trace_id,
                owner_id=OWNER_ID,
                identity=self.identity,
                user_event=self.event,
                personal_context=(item,),
            )


class Stage4EvaluationTests(unittest.TestCase):
    def test_frozen_synthetic_suite_passes_without_binding_quality_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report = run_user_model_evaluation(
                fixture_path=(
                    PROJECT_ROOT
                    / "evals"
                    / "fixtures"
                    / "user_model_evidence_sequences_v1.json"
                ),
                output_path=Path(temporary) / "report.json",
                project_root=PROJECT_ROOT,
            )
        self.assertEqual(report.metrics["failed"], 0)
        self.assertEqual(report.metrics["false_stability_count"], 0)
        self.assertEqual(report.metrics["counter_evidence_retention_rate"], 1.0)
        self.assertFalse(report.binding_evaluation)
        self.assertEqual(report.gate_status, "not_evaluated")


if __name__ == "__main__":
    unittest.main()
