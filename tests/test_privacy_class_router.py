from __future__ import annotations

import unittest
from datetime import UTC, datetime

from companion.ids import uuid7
from companion.policy import DataPolicy, PrivacyClass
from mlsys.contracts import ProviderCapabilities
from mlsys.serving import PrivacyClassRouter, ProviderPolicyError


CLOUD_PROVIDER_ID = "cloud-gpt-test"
LOCAL_PROVIDER_ID = "local-qwen-base-test"


def capabilities(
    provider_id: str,
    *,
    execution_environment: str,
    approved_privacy_classes: tuple[PrivacyClass, ...],
) -> ProviderCapabilities:
    return ProviderCapabilities(
        provider_id=provider_id,
        provider_class=(
            "cloud" if execution_environment == "cloud" else "self_hosted"
        ),
        execution_environment=execution_environment,
        available_model_version_ids=(f"{provider_id}-model-v1",),
        approved_privacy_classes=approved_privacy_classes,
        supports_streaming=True,
        max_context_tokens=8192,
        max_output_tokens=4096,
        observed_at=datetime.now(UTC),
        ttl_seconds=30,
    )


class PrivacyClassRouterTests(unittest.TestCase):
    def test_llama_context_capacity_is_per_slot_not_total(self) -> None:
        from mlsys.serving.openai_compatible import llama_context_tokens_per_slot
        for total, slots, expected in ((8192, 2, 4096), (8192, 1, 8192), (4096, 1, 4096)):
            with self.subTest(total=total, slots=slots):
                self.assertEqual(llama_context_tokens_per_slot({
                    "context_tokens": total, "parallel_slots": slots,
                }), expected)
        for invalid in (0, -1, True, "2"):
            with self.subTest(slots=invalid), self.assertRaises(ValueError):
                llama_context_tokens_per_slot({
                    "context_tokens": 8192, "parallel_slots": invalid,
                })

    def setUp(self) -> None:
        self.router = PrivacyClassRouter(
            cloud_provider_id=CLOUD_PROVIDER_ID,
            local_provider_id=LOCAL_PROVIDER_ID,
            approved_cloud_provider_ids=frozenset({CLOUD_PROVIDER_ID}),
        )
        self.cloud = capabilities(
            CLOUD_PROVIDER_ID,
            execution_environment="cloud",
            approved_privacy_classes=(
                PrivacyClass.PUBLIC,
                PrivacyClass.NORMAL,
            ),
        )
        self.local = capabilities(
            LOCAL_PROVIDER_ID,
            execution_environment="local",
            approved_privacy_classes=tuple(PrivacyClass),
        )

    def test_complete_owner_default_privacy_matrix(self) -> None:
        expected = {
            PrivacyClass.PUBLIC: CLOUD_PROVIDER_ID,
            PrivacyClass.NORMAL: CLOUD_PROVIDER_ID,
            PrivacyClass.PRIVATE: LOCAL_PROVIDER_ID,
            PrivacyClass.HIGHLY_PRIVATE: LOCAL_PROVIDER_ID,
            PrivacyClass.LOCAL_ONLY: LOCAL_PROVIDER_ID,
        }
        for privacy_class, provider_id in expected.items():
            with self.subTest(privacy_class=privacy_class):
                policy = DataPolicy.owner_default(privacy_class)
                self.assertEqual(
                    self.router.select_provider_id(policy=policy),
                    provider_id,
                )
                route = self.router.decide(
                    request_id=uuid7(),
                    trace_id="a" * 32,
                    policy=policy,
                    capabilities=(
                        self.cloud if provider_id == CLOUD_PROVIDER_ID else self.local
                    ),
                    required_input_tokens=100,
                    required_output_tokens=100,
                    required_streaming=True,
                )
                self.assertEqual(route.selected_provider_id, provider_id)
                self.assertEqual(route.router_version, "privacy-class-router-v1")
                self.assertEqual(
                    route.execution_environment,
                    "cloud" if provider_id == CLOUD_PROVIDER_ID else "local",
                )

    def test_cloud_ineligible_ordinary_policy_uses_local(self) -> None:
        policy = DataPolicy(
            privacy_class=PrivacyClass.NORMAL,
            memory_eligible=True,
            cloud_eligible=False,
            decision_source="derived_conservative",
        )
        route = self.router.decide(
            request_id=uuid7(),
            trace_id="b" * 32,
            policy=policy,
            capabilities=self.local,
            required_input_tokens=100,
            required_output_tokens=100,
            required_streaming=True,
        )
        self.assertEqual(route.selected_provider_id, LOCAL_PROVIDER_ID)
        self.assertEqual(route.reason, "cloud_ineligible_local_route")

    def test_router_rejects_capabilities_from_non_selected_provider(self) -> None:
        with self.assertRaisesRegex(
            ProviderPolicyError,
            "do not match the privacy-selected route",
        ):
            self.router.decide(
                request_id=uuid7(),
                trace_id="c" * 32,
                policy=DataPolicy.owner_default(PrivacyClass.LOCAL_ONLY),
                capabilities=self.cloud,
                required_input_tokens=100,
                required_output_tokens=100,
                required_streaming=True,
            )

    def test_router_rejects_environment_mismatch_for_each_provider_slot(self) -> None:
        cases = (
            (
                DataPolicy.owner_default(PrivacyClass.NORMAL),
                capabilities(
                    CLOUD_PROVIDER_ID,
                    execution_environment="local",
                    approved_privacy_classes=(PrivacyClass.NORMAL,),
                ),
            ),
            (
                DataPolicy.owner_default(PrivacyClass.LOCAL_ONLY),
                capabilities(
                    LOCAL_PROVIDER_ID,
                    execution_environment="cloud",
                    approved_privacy_classes=(PrivacyClass.LOCAL_ONLY,),
                ),
            ),
        )
        for policy, candidate in cases:
            with self.subTest(
                privacy_class=policy.privacy_class,
                provider_id=candidate.provider_id,
            ), self.assertRaisesRegex(
                ProviderPolicyError,
                "execution environment does not match",
            ):
                self.router.decide(
                    request_id=uuid7(),
                    trace_id="e" * 32,
                    policy=policy,
                    capabilities=candidate,
                    required_input_tokens=100,
                    required_output_tokens=100,
                    required_streaming=True,
                )

    def test_local_context_limit_fails_without_selecting_cloud(self) -> None:
        with self.assertRaisesRegex(
            ProviderPolicyError,
            "context window cannot satisfy",
        ):
            self.router.decide(
                request_id=uuid7(),
                trace_id="d" * 32,
                policy=DataPolicy.owner_default(PrivacyClass.LOCAL_ONLY),
                capabilities=self.local,
                required_input_tokens=8000,
                required_output_tokens=1000,
                required_streaming=True,
            )
        self.assertEqual(
            self.router.select_provider_id(
                policy=DataPolicy.owner_default(PrivacyClass.LOCAL_ONLY)
            ),
            LOCAL_PROVIDER_ID,
        )


if __name__ == "__main__":
    unittest.main()
