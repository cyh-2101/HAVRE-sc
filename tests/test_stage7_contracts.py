from __future__ import annotations

import json
import unittest
import uuid
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from companion.offline import (
    CanonicalDatasetSnapshot,
    DatasetRejection,
    MemoryLifecycleProposal,
)
from companion.policy import DataPolicy, PrivacyClass
from scripts.export_contract_schemas import CONTRACTS
from services.api.app import create_app


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Stage7LifecycleContractTests(unittest.TestCase):
    def test_targeted_lifecycle_requires_exact_memory_revision(self) -> None:
        base = {
            "owner_id": uuid.uuid4(),
            "action": "archive",
            "memory_class": "semantic",
            "source_memory_refs": (f"memory/{uuid.uuid4()}@1",),
            "reason": "Synthetic archive proposal",
            "data_policy": DataPolicy.owner_default(
                PrivacyClass.LOCAL_ONLY, memory_eligible=True
            ),
            "trace_id": uuid.uuid4().hex,
        }
        with self.assertRaises(ValidationError):
            MemoryLifecycleProposal.model_validate(base)
        proposal = MemoryLifecycleProposal.model_validate(
            {**base, "target_memory_id": uuid.uuid4(), "target_revision": 1}
        )
        self.assertTrue(proposal.review_required)
        self.assertFalse(proposal.automatically_applied)

    def test_dataset_snapshot_is_reproducible_and_rejection_only(self) -> None:
        owner = uuid.uuid4()
        rejection = DatasetRejection(
            source_ref=f"event/{uuid.uuid4()}",
            source_content_hash="sha256:" + "1" * 64,
            reason_code="training_not_eligible",
        )
        first = CanonicalDatasetSnapshot(
            owner_id=owner,
            source_snapshot_hash="sha256:" + "2" * 64,
            rejections=(rejection,),
        )
        second = CanonicalDatasetSnapshot(
            owner_id=owner,
            source_snapshot_hash=first.source_snapshot_hash,
            rejections=(rejection,),
        )
        self.assertEqual(first.member_manifest_hash, second.member_manifest_hash)
        self.assertEqual(first.content_hash, second.content_hash)
        self.assertEqual(first.members, ())

    def test_stage7_schemas_and_routes_are_exported(self) -> None:
        expected = {
            "reflection-proposal-v1", "memory-lifecycle-proposal-v1",
            "memory-lifecycle-review-v1", "dataset-rejection-v1",
            "canonical-dataset-snapshot-v1", "offline-artifact-manifest-v1",
        }
        self.assertTrue(expected.issubset(CONTRACTS))
        paths = create_app().openapi()["paths"]
        for path in (
            "/v1/offline/jobs", "/v1/offline/jobs/run-once",
            "/v1/offline/datasets/rebuild",
            "/v1/offline/memory-lifecycle/{proposal_id}/review",
        ):
            self.assertIn(path, paths)

    def test_committed_stage7_schemas_match_contracts(self) -> None:
        root = PROJECT_ROOT / "contracts" / "schemas"
        for name in (
            "reflection-proposal-v1", "memory-lifecycle-proposal-v1",
            "memory-lifecycle-review-v1", "dataset-rejection-v1",
            "canonical-dataset-snapshot-v1", "offline-artifact-manifest-v1",
        ):
            with self.subTest(name=name):
                committed = json.loads((root / f"{name}.json").read_text(encoding="utf-8"))
                self.assertEqual(committed, CONTRACTS[name].model_json_schema())
