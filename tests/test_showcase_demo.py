from __future__ import annotations

import os
import unittest

from scripts.showcase_demo import run_showcase, validate_showcase_database_url


DATABASE_URL = os.getenv("HAVRE_TEST_DATABASE_URL")


class ShowcaseDatabaseBoundaryTests(unittest.TestCase):
    def test_accepts_only_loopback_named_showcase_database(self) -> None:
        values = validate_showcase_database_url(
            "postgresql://postgres@127.0.0.1:55432/havre_showcase_demo"
        )
        self.assertEqual(values["dbname"], "havre_showcase_demo")

    def test_rejects_remote_or_nonshowcase_database(self) -> None:
        with self.assertRaisesRegex(ValueError, "loopback-only"):
            validate_showcase_database_url(
                "postgresql://postgres@example.invalid:55432/havre_showcase_demo"
            )
        with self.assertRaisesRegex(ValueError, "name must match"):
            validate_showcase_database_url(
                "postgresql://postgres@127.0.0.1:55432/havre"
            )
        with self.assertRaisesRegex(ValueError, "name must match"):
            validate_showcase_database_url(
                "postgresql://postgres@127.0.0.1:55432/havre_showcase_demo-hijack"
            )


@unittest.skipUnless(DATABASE_URL, "HAVRE_TEST_DATABASE_URL is required")
class ShowcaseFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_synthetic_flow_reaches_feedback_and_clean_provenance(self) -> None:
        result = await run_showcase(
            database_url=str(DATABASE_URL),
            validate_database_url=False,
        )
        flow = result["flow"]
        self.assertEqual(result["scope"], "public_safe_synthetic_showcase")
        self.assertEqual(
            flow["model_response"]["provider_id"],
            "deterministic-local",
        )
        self.assertFalse(flow["reviewed_memory"]["training_eligible"])
        self.assertTrue(flow["retrieval_and_context"]["selected_candidates"])
        self.assertEqual(flow["events_and_history"]["conversation_roles"], [
            "user", "assistant", "user", "assistant",
        ])
        self.assertFalse(flow["feedback_and_owner_edit"]["training_eligible"])
        self.assertEqual(flow["episode_and_provenance"]["message_count"], 4)
        self.assertEqual(flow["episode_and_provenance"]["provenance_audit"], [])
