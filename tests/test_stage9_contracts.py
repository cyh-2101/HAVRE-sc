from __future__ import annotations

import json
import unittest
import uuid
from pathlib import Path

from pydantic import ValidationError

from companion.hashing import content_hash
from companion.identity import IdentityLoader
from mlsys.training import (
    CanonicalTrainingExample,
    EvaluationHoldoutCase,
    GovernanceVersionSet,
    RenderedTrainingArtifact,
    TrainingConfig,
    build_stage9_fixture_snapshot,
    check_adapter_compatibility,
    run_stage9_synthetic_dry_run,
)
from scripts.export_contract_schemas import CONTRACTS


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRAINING_FIXTURE = (
    PROJECT_ROOT / "mlsys" / "training" / "fixtures"
    / "stage9_synthetic_public_training_v2.json"
)
HOLDOUT_FIXTURE = (
    PROJECT_ROOT / "mlsys" / "training" / "fixtures"
    / "stage9_synthetic_public_holdout_v2.json"
)


def governance_versions() -> GovernanceVersionSet:
    identity = IdentityLoader(PROJECT_ROOT / "identity").load()
    return GovernanceVersionSet(
        constitution_version=identity.constitution.version_id,
        constitution_hash=identity.constitution.content_hash,
        identity_version=identity.identity.version_id,
        identity_hash=identity.identity.content_hash,
        values_version=identity.values.version_id,
        values_hash=identity.values.content_hash,
        intervention_policy_version="intervention-policy-sim-v1",
        intervention_policy_hash=content_hash({"version": "intervention-policy-sim-v1"}),
    )


class Stage9ContractTests(unittest.TestCase):
    def test_canonical_fixture_is_model_independent_and_user_data_free(self) -> None:
        owner = uuid.uuid4()
        raw_training = json.loads(TRAINING_FIXTURE.read_text(encoding="utf-8"))["examples"]
        raw_holdout = json.loads(HOLDOUT_FIXTURE.read_text(encoding="utf-8"))["examples"]
        self.assertEqual({item["split"] for item in raw_training}, {"train", "validation"})
        self.assertEqual({item["split"] for item in raw_holdout}, {"holdout"})
        self.assertFalse(
            {item["example_id"] for item in raw_training}
            & {item["example_id"] for item in raw_holdout}
        )
        first = build_stage9_fixture_snapshot(
            owner_id=owner, training_fixture_path=TRAINING_FIXTURE,
            holdout_fixture_path=HOLDOUT_FIXTURE,
        )
        second = build_stage9_fixture_snapshot(
            owner_id=owner, training_fixture_path=TRAINING_FIXTURE,
            holdout_fixture_path=HOLDOUT_FIXTURE,
        )
        self.assertEqual(first.member_manifest_hash, second.member_manifest_hash)
        self.assertEqual(first.content_hash, second.content_hash)
        self.assertEqual(first.user_event_source_count, 0)
        self.assertTrue(all(item.training_eligible for item in first.examples))
        self.assertTrue(all(not item.contains_user_data for item in first.examples))
        self.assertEqual({item.split for item in first.examples}, {"train", "validation"})
        self.assertNotIn("holdout", {item.split for item in first.examples})
        self.assertEqual(len(first.examples), 6)
        self.assertEqual(len(first.excluded_evaluation_holdout_ids), 2)
        self.assertTrue(all("token" not in item.model_dump() for item in first.examples))

    def test_holdout_contract_is_evaluation_only_and_training_ineligible(self) -> None:
        raw = json.loads(HOLDOUT_FIXTURE.read_text(encoding="utf-8"))["examples"][-1]
        case = EvaluationHoldoutCase.model_validate(
            {**raw, "training_eligible": False, "evaluation_only": True, "access_limited": True}
        )
        self.assertFalse(case.training_eligible)
        self.assertTrue(case.evaluation_only)
        with self.assertRaises(ValidationError):
            CanonicalTrainingExample.model_validate(raw)

    def test_training_eligible_false_is_rejected_by_contract(self) -> None:
        fixture = json.loads(TRAINING_FIXTURE.read_text(encoding="utf-8"))["examples"][0]
        with self.assertRaises(ValidationError):
            CanonicalTrainingExample.model_validate({**fixture, "training_eligible": False})

    def test_qlora_requires_four_bit_base_quantization(self) -> None:
        with self.assertRaises(ValidationError):
            TrainingConfig(method="qlora", seed=1)
        TrainingConfig(method="qlora", seed=1, base_quantization_bits=4)

    def test_rendered_training_example_ids_must_be_unique(self) -> None:
        experiment = run_stage9_synthetic_dry_run(
            owner_id=uuid.uuid4(), training_fixture_path=TRAINING_FIXTURE,
            holdout_fixture_path=HOLDOUT_FIXTURE,
            governance_versions=governance_versions(),
        )
        payload = experiment.rendered_artifact.model_dump(mode="json")
        payload["examples"] = [payload["examples"][0]] * len(payload["examples"])
        payload["content_hash"] = ""
        with self.assertRaisesRegex(ValidationError, "must be unique"):
            RenderedTrainingArtifact.model_validate(payload)

    def test_lora_qlora_four_arm_and_rejection_path(self) -> None:
        experiment = run_stage9_synthetic_dry_run(
            owner_id=uuid.uuid4(), training_fixture_path=TRAINING_FIXTURE,
            holdout_fixture_path=HOLDOUT_FIXTURE,
            governance_versions=governance_versions(),
        )
        self.assertEqual({run.config.method for run in experiment.training_runs}, {"lora", "qlora"})
        self.assertTrue(all(run.final_loss <= run.initial_loss for run in experiment.training_runs))
        self.assertEqual(
            {arm.arm for arm in experiment.evaluation.arms},
            {"base", "base_memory", "base_adapter", "base_memory_adapter"},
        )
        self.assertFalse(experiment.evaluation.release_promotion_authorized)
        self.assertEqual(experiment.rejection.rollback_effect, "no_activation_to_rollback")
        self.assertTrue(all(not adapter.deployed for adapter in experiment.adapters))
        training_ids = {item.example_id for item in experiment.snapshot.examples}
        rendered_ids = {item.example_id for item in experiment.rendered_artifact.examples}
        holdout_ids = {item.example_id for item in experiment.holdout_suite.cases}
        self.assertEqual(training_ids, rendered_ids)
        self.assertFalse(training_ids & holdout_ids)
        self.assertFalse(experiment.holdout_suite.training_eligible)
        self.assertEqual(experiment.evaluation.holdout_suite_id, experiment.holdout_suite.holdout_suite_id)

    def test_exact_base_hash_compatibility_fails_closed(self) -> None:
        experiment = run_stage9_synthetic_dry_run(
            owner_id=uuid.uuid4(), training_fixture_path=TRAINING_FIXTURE,
            holdout_fixture_path=HOLDOUT_FIXTURE,
            governance_versions=governance_versions(),
        )
        bad_model = experiment.model.model_copy(
            update={"artifact_hash": "sha256:" + "0" * 64, "content_hash": ""}
        )
        report = check_adapter_compatibility(adapter=experiment.adapters[0], model=bad_model)
        self.assertFalse(report.compatible)
        self.assertIn("base_artifact_hash", report.mismatch_codes)

    def test_stage9_schemas_are_exported(self) -> None:
        expected = {
            "canonical-training-example-v1", "training-dataset-snapshot-v1",
            "evaluation-holdout-case-v1", "evaluation-holdout-suite-v1",
            "model-version-v1", "training-run-v1", "adapter-version-v1",
            "rendered-training-artifact-v1",
            "adapter-compatibility-report-v1", "factorial-evaluation-report-v1",
            "adapter-rejection-record-v1",
        }
        self.assertTrue(expected.issubset(CONTRACTS))
        root = PROJECT_ROOT / "contracts" / "schemas"
        for name in expected:
            with self.subTest(name=name):
                committed = json.loads((root / f"{name}.json").read_text(encoding="utf-8"))
                self.assertEqual(committed, CONTRACTS[name].model_json_schema())
