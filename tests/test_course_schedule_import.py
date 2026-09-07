from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.import_owner_course_schedule import (
    SOURCE_INTERACTION_IDEMPOTENCY_VERSION,
    _expand_reminders,
    import_schedule,
)


class CourseScheduleImportTests(unittest.TestCase):
    def test_existing_complete_batch_reuses_goal_without_source_interaction(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = root / "schedule.md"
            source_path.write_text("owner-local schedule", encoding="utf-8")
            source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps({
                "schema_version": 1,
                "source_sha256": source_hash,
                "term": "Fall 2026",
                "timezone": "America/Chicago",
                "activation_at": "2026-09-03T15:00:00-05:00",
                "owner_decisions": {
                    "ece210_scope": "full_course",
                    "ece494_credits": 3,
                },
                "entries": [{
                    "entry_id": "ece210-existing",
                    "title": "ECE 210 Existing Task",
                    "next_action": "Review the requirements",
                    "reminder_policy": "none",
                }],
            }), encoding="utf-8")
            token_path = root / "token.secret"
            token_path.write_text("test-token", encoding="utf-8")
            calls: list[dict[str, object]] = []

            def fake_request(**kwargs):
                calls.append(kwargs)
                path = kwargs["path"]
                if path == "/v1/commitments/course-field-authorization":
                    return {"status": "authorized"}
                if path == "/v1/goals?include_inactive=true":
                    return [{
                        "goal_id": "00000000-0000-7000-8000-000000000001",
                        "why": (
                            "owner_course_schedule:Fall 2026:"
                            f"{source_hash}:ece210-existing;status=confirmed"
                        ),
                        "status": "active",
                        "revision": 1,
                    }]
                if path.endswith("/commitment-projection"):
                    return {"status": "projected"}
                if path == "/v1/commitments/course-reminders/supersede-legacy":
                    return {"legacy_reminders_cancelled": 0}
                self.fail(f"unexpected request: {path}")

            args = argparse.Namespace(
                source=str(source_path),
                plan=str(plan_path),
                token_file=str(token_path),
                base_url="http://127.0.0.1:8765",
                apply=True,
            )
            with patch(
                "scripts.import_owner_course_schedule._request",
                side_effect=fake_request,
            ):
                result = import_schedule(args)

        self.assertEqual(SOURCE_INTERACTION_IDEMPOTENCY_VERSION, "v4")
        self.assertEqual(result["goals_created"], 0)
        self.assertEqual(result["goals_reused"], 1)
        self.assertFalse(any(call["path"] == "/v1/interactions" for call in calls))

    def test_catchup_wording_never_claims_the_original_offset_remains(self) -> None:
        plan = {
            "timezone": "America/Chicago",
            "activation_at": "2026-09-03T15:00:00-05:00",
        }
        cases = (
            ("regular", "普通作业（9/4）", "2026-09-04T23:59:00-05:00"),
            ("large", "大型实验（9/4）", "2026-09-04T17:00:00-05:00"),
            ("exam", "考试（9/4）", "2026-09-04T19:00:00-05:00"),
        )
        for policy, title, due_at in cases:
            with self.subTest(policy=policy):
                reminders = _expand_reminders(plan, {
                    "entry_id": policy,
                    "title": title,
                    "reminder_policy": policy,
                    "due_times": [due_at],
                })
                self.assertEqual(len(reminders), 1)
                self.assertEqual(reminders[0]["remind_at"], plan["activation_at"])
                self.assertIn("已经进入", reminders[0]["text"])
                self.assertNotIn("还有一周", reminders[0]["text"])
                self.assertNotIn("还有三天", reminders[0]["text"])


if __name__ == "__main__":
    unittest.main()
