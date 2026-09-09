"""Run the test surface that is reproducible from the sanitized public mirror.

The private archive also has tests bound to excluded owner-only evaluation
artifacts.  Those tests are registered here instead of being silently replaced
with synthetic evidence or reported as passing.
"""

from __future__ import annotations

import argparse
import json
from urllib.parse import urlparse
import os
from pathlib import Path
import sys
import unittest

import psycopg
from psycopg import sql

from companion.persistence import apply_migrations


ROOT = Path(__file__).resolve().parents[1]

EXCLUDED_MODULES = {
    "tests.test_stage8_contracts": "requires ignored local Stage 2 benchmark output",
    "tests.test_stage8_integration": "requires ignored local Stage 2 benchmark output",
    "tests.test_stage9a_dataset_v7": "requires excluded owner-local v6 dataset evidence",
    "tests.test_stage9a_real_contracts": "requires the separate training environment and excluded local artifacts",
    "tests.test_stage9a_real_v6": "requires the separate training environment and excluded local artifacts",
    "tests.test_stage9a_real_v7": "requires the separate training environment and excluded local artifacts",
    "tests.test_stage9a_unseen_v7": "requires excluded private unseen-evaluation evidence",
}

EXCLUDED_TESTS = {
    'tests.test_strong_cloud_brain_broader.StrongCloudBrainBroaderTests.test_exact_existing_80_case_public_suite_and_current_context': 'requires intentionally omitted case-level local/cloud research outputs or local evaluation fixtures',
    'tests.test_strong_cloud_brain_broader_review.StrongCloudBrainBroaderReviewTests.test_packet_is_complete_and_contains_no_arm_identity': 'requires intentionally omitted case-level local/cloud research outputs or local evaluation fixtures',
    'tests.test_strong_cloud_brain_ceiling.StrongCloudBrainHarnessTests.test_exact_fixtures_are_synthetic_and_prompt_bound_to_local_arms': 'requires intentionally omitted case-level local/cloud research outputs or local evaluation fixtures',
    'tests.test_strong_cloud_brain_cost.StrongCloudBrainCostTests.test_formal_cost_is_independently_recomputed_from_every_request': 'requires intentionally omitted case-level local/cloud research outputs or local evaluation fixtures',
    'tests.test_strong_cloud_brain_decision.StrongCloudBrainDecisionTests.test_decision_is_bound_to_blind_reviews_and_preserves_stop_boundary': 'requires intentionally omitted case-level local/cloud research outputs or local evaluation fixtures',
    'tests.test_strong_cloud_brain_decision.StrongCloudBrainDecisionTests.test_review_case_metadata_must_match_blind_packets': 'requires intentionally omitted case-level local/cloud research outputs or local evaluation fixtures',
    'tests.test_strong_cloud_brain_review.StrongCloudBrainReviewTests.test_review_packet_is_complete_blinded_and_core_replayed': 'requires intentionally omitted case-level local/cloud research outputs or local evaluation fixtures',
    "tests.test_stage9a_dataset_v4.Stage9ADatasetV4Tests."
    "test_owner_alignment_is_permanently_evaluation_only_and_physically_separate":
        "requires the excluded private owner-alignment set",
}

# Unlike the artifact-bound tests above, the source for these tests itself
# contains private text and cannot be included in the public snapshot.
OMITTED_PRIVATE_TESTS = {
    "tests.test_chat_repair.ActionClaimTests.test_failed_action_cannot_become_a_promise":
        "exact reproduced assistant transcript; test source omitted for privacy",
}


def _iter_cases(suite: unittest.TestSuite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _iter_cases(item)
        else:
            yield item


def build_public_suite() -> tuple[unittest.TestSuite, list[str]]:
    discovered = unittest.defaultTestLoader.discover(
        start_dir=str(ROOT / "tests"),
        pattern="test_*.py",
        top_level_dir=str(ROOT),
    )
    selected = unittest.TestSuite()
    excluded: list[str] = list(OMITTED_PRIVATE_TESTS)
    for case in _iter_cases(discovered):
        test_id = case.id()
        module = test_id.rsplit(".", 2)[0]
        if module in EXCLUDED_MODULES:
            excluded.append(test_id)
            continue
        if test_id in EXCLUDED_TESTS:
            excluded.append(test_id)
            continue
        selected.addTest(case)
    return selected, excluded


def prepare_test_database(database_url: str) -> None:
    """Install the canonical schema and roles before any role-bound test runs."""
    apply_migrations(database_url, ROOT / "db" / "migrations")
    with psycopg.connect(database_url, autocommit=True) as connection:
        database_name = connection.execute("SELECT current_database()").fetchone()[0]
        roles_sql = (ROOT / "deploy" / "bootstrap_roles.sql").read_text(
            encoding="utf-8"
        ).replace(":DBNAME", sql.Identifier(database_name).as_string(connection))
        roles_sql = "\n".join(
            line for line in roles_sql.splitlines()
            if not line.lstrip().startswith("\\set ")
        )
        connection.execute(roles_sql)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        help="dedicated disposable PostgreSQL URL; also accepted through HAVRE_TEST_DATABASE_URL",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    if args.database_url:
        os.environ["HAVRE_TEST_DATABASE_URL"] = args.database_url
    if not os.environ.get("HAVRE_TEST_DATABASE_URL"):
        parser.error("provide --database-url or HAVRE_TEST_DATABASE_URL")

    parsed = urlparse(os.environ["HAVRE_TEST_DATABASE_URL"])
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"} or not parsed.path.lstrip("/").startswith("havre_showcase_"):
        parser.error("use a dedicated loopback havre_showcase_* database")
    prepare_test_database(os.environ["HAVRE_TEST_DATABASE_URL"])
    suite, excluded = build_public_suite()
    print(f"Public verification selected {suite.countTestCases()} tests.")
    print(f"Excluded {len(excluded)} private-artifact-bound tests; see docs/PUBLIC_TESTING.md.")
    result = unittest.TextTestRunner(verbosity=2 if args.verbose else 1).run(suite)
    summary = {"run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors), "skips": len(result.skipped), "excluded": excluded}
    output = ROOT / "var/public-verification.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return 0 if result.wasSuccessful() and not result.skipped else 1


if __name__ == "__main__":
    sys.exit(main())
