"""Export the local Stage 9 synthetic/public candidate-only dry-run evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import UUID

from companion.hashing import content_hash
from companion.identity import IdentityLoader
from mlsys.training import GovernanceVersionSet, run_stage9_synthetic_dry_run


PROJECT_ROOT = Path(__file__).resolve().parents[1]


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner-id", required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            PROJECT_ROOT / "evals" / "reports" / "stage9_20260819"
            / "candidate-dry-run-correction2.json"
        ),
    )
    args = parser.parse_args()
    experiment = run_stage9_synthetic_dry_run(
        owner_id=UUID(args.owner_id),
        training_fixture_path=(
            PROJECT_ROOT / "mlsys" / "training" / "fixtures"
            / "stage9_synthetic_public_training_v2.json"
        ),
        holdout_fixture_path=(
            PROJECT_ROOT / "mlsys" / "training" / "fixtures"
            / "stage9_synthetic_public_holdout_v2.json"
        ),
        governance_versions=governance_versions(),
    )
    payload = {
        "schema_version": 1,
        "evidence_scope": "local_synthetic_public_candidate_only",
        "personal_model_quality_claimed": False,
        "promotion_authorized": False,
        "deployment_authorized": False,
        "snapshot": experiment.snapshot.model_dump(mode="json"),
        "holdout_suite": experiment.holdout_suite.model_dump(mode="json"),
        "model": experiment.model.model_dump(mode="json"),
        "rendered_artifact": experiment.rendered_artifact.model_dump(mode="json"),
        "training_runs": [run.model_dump(mode="json") for run in experiment.training_runs],
        "adapters": [adapter.model_dump(mode="json") for adapter in experiment.adapters],
        "compatibility_reports": [
            report.model_dump(mode="json") for report in experiment.compatibility_reports
        ],
        "evaluation": experiment.evaluation.model_dump(mode="json"),
        "rejection": experiment.rejection.model_dump(mode="json"),
    }
    payload["content_hash"] = content_hash(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"output": str(args.output), "content_hash": payload["content_hash"]}))


if __name__ == "__main__":
    main()
