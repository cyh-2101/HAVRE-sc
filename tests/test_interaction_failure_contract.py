from __future__ import annotations

import unittest
import uuid

from pydantic import ValidationError

from companion.events import InteractionFailurePayload


class InteractionFailureContractTests(unittest.TestCase):
    def test_context_build_failure_has_no_post_context_lineage(self) -> None:
        payload = InteractionFailurePayload(
            failure_stage="context_build",
            failure_code="context_limit_exceeded",
            retryable=False,
            safe_message="The selected provider cannot fit the required context.",
        )

        self.assertIsNone(payload.context_pack_id)
        self.assertIsNone(payload.route_decision_id)
        self.assertIsNone(payload.inference_request_id)

    def test_context_build_failure_rejects_invented_lineage(self) -> None:
        for field_name in (
            "context_pack_id",
            "route_decision_id",
            "inference_request_id",
        ):
            with self.subTest(field_name=field_name), self.assertRaisesRegex(
                ValidationError,
                "cannot claim context, route, or inference lineage",
            ):
                InteractionFailurePayload(
                    failure_stage="context_build",
                    failure_code="context_limit_exceeded",
                    retryable=False,
                    safe_message="Synthetic context failure.",
                    **{field_name: uuid.uuid4()},
                )

    def test_post_context_failure_requires_context_pack_id(self) -> None:
        with self.assertRaisesRegex(
            ValidationError,
            "require a ContextPack identifier",
        ):
            InteractionFailurePayload(
                failure_stage="capability_check",
                failure_code="capability_unavailable",
                retryable=False,
                safe_message="Synthetic capability failure.",
            )


if __name__ == "__main__":
    unittest.main()
