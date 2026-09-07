from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from companion.identity import IdentityLoader
from evals.strong_cloud_brain_ceiling import (
    AUTHORIZATION_REF,
    DIAGNOSTIC_SUITE_PATH,
    FOCUSED_SUITE_PATH,
    MAX_OUTPUT_TOKENS,
    THINKING_MAX_OUTPUT_TOKENS,
    _all_cases,
    _diagnostic_case,
    _decide_route_with_fresh_capabilities,
    _load_exact_suite,
    _load_progress,
    _request_for_case,
    _verify_diagnostic_prompt_binding,
    _verify_local_prompt_bindings,
    explicit_public_synthetic_policy,
    preflight_cost_upper_bound,
    pricing_period,
    usage_cost,
)
from mlsys.contracts import TokenUsage
from mlsys.training.stage9a_provenance import PROJECT_ROOT


class StrongCloudBrainHarnessTests(unittest.TestCase):
    def test_exact_fixtures_are_synthetic_and_prompt_bound_to_local_arms(self) -> None:
        suite, fixture_hash = _load_exact_suite(FOCUSED_SUITE_PATH)
        self.assertEqual(suite["privacy_class"], "SYNTHETIC")
        self.assertFalse(suite["contains_user_data"])
        self.assertTrue(fixture_hash.startswith("sha256:"))
        identity = IdentityLoader(PROJECT_ROOT / "identity").load().system_text()
        binding = _verify_local_prompt_bindings(
            _all_cases(suite), identity=identity
        )
        self.assertEqual(len(binding["report_hashes"]), 2)
        diagnostic, _ = _diagnostic_case()
        diagnostic_binding = _verify_diagnostic_prompt_binding(
            diagnostic, identity=identity
        )
        self.assertEqual(len(diagnostic_binding["report_hashes"]), 2)

    def test_request_uses_canonical_contract_and_explicit_public_policy(self) -> None:
        suite, fixture_hash = _load_exact_suite(FOCUSED_SUITE_PATH)
        identity = IdentityLoader(PROJECT_ROOT / "identity").load().system_text()
        case = _all_cases(suite)[0]
        policy = explicit_public_synthetic_policy()
        request, messages, prompt_hash = _request_for_case(
            case,
            arm_name="deepseek_v4_pro_thinking_disabled",
            identity=identity,
            fixture_hash=fixture_hash,
            policy=policy,
        )
        self.assertEqual(request.constraints.allowed_execution_environments, ("cloud",))
        self.assertEqual(request.generation.max_output_tokens, MAX_OUTPUT_TOKENS)
        self.assertEqual(request.metadata["cloud_authorization_ref"], AUTHORIZATION_REF)
        self.assertEqual(policy.privacy_class.value, "PUBLIC")
        self.assertTrue(policy.cloud_eligible)
        self.assertEqual(policy.decision_source, "owner_explicit")
        self.assertEqual(
            [(item.role, item.content_parts[0].text) for item in request.messages],
            [(item["role"], item["content"]) for item in messages],
        )
        self.assertTrue(prompt_hash.startswith("sha256:"))

        thinking_request, thinking_messages, _ = _request_for_case(
            case,
            arm_name="deepseek_v4_pro_thinking_enabled",
            identity=identity,
            fixture_hash=fixture_hash,
            policy=policy,
            max_output_tokens=THINKING_MAX_OUTPUT_TOKENS,
        )
        self.assertEqual(
            [(item.role, item.content_parts[0].text) for item in thinking_request.messages],
            [(item["role"], item["content"]) for item in thinking_messages],
        )
        self.assertEqual(
            thinking_request.generation.max_output_tokens,
            THINKING_MAX_OUTPUT_TOKENS,
        )

    def test_peak_windows_and_cost_use_official_cache_breakdown(self) -> None:
        self.assertEqual(
            pricing_period(datetime(2026, 8, 26, 2, tzinfo=UTC)), "peak"
        )
        self.assertEqual(
            pricing_period(datetime(2026, 8, 26, 5, tzinfo=UTC)), "off_peak"
        )
        self.assertEqual(
            pricing_period(datetime(2026, 8, 30, 2, tzinfo=UTC)), "off_peak"
        )
        usage = TokenUsage(
            prompt_tokens=100,
            output_tokens=10,
            total_tokens=110,
            token_count_source="provider",
            prompt_cache_hit_tokens=80,
            prompt_cache_miss_tokens=20,
            reasoning_tokens=3,
        )
        cost = usage_cost(
            usage, at=datetime(2026, 8, 26, 2, tzinfo=UTC)
        )
        expected = (
            Decimal(80) * Decimal("0.044")
            + Decimal(20) * Decimal("1.32")
            + Decimal(10) * Decimal("3.96")
        ) / Decimal(1_000_000)
        self.assertEqual(Decimal(cost["cost_usd"]), expected)
        self.assertTrue(cost["cost_exact_from_provider_cache_usage"])

    def test_missing_cache_breakdown_is_conservative_not_claimed_exact(self) -> None:
        usage = TokenUsage(
            prompt_tokens=100,
            output_tokens=10,
            total_tokens=110,
            token_count_source="provider",
        )
        cost = usage_cost(
            usage, at=datetime(2026, 8, 26, 5, tzinfo=UTC)
        )
        self.assertFalse(cost["cost_exact_from_provider_cache_usage"])
        self.assertEqual(cost["unclassified_prompt_tokens_billed_as_cache_miss"], 100)
        upper = preflight_cost_upper_bound(
            [{"role": "user", "content": "synthetic"}],
            at=datetime(2026, 8, 26, 5, tzinfo=UTC),
        )
        self.assertGreater(upper, Decimal(cost["cost_usd"]))

    def test_progress_is_exact_bound_and_rejects_drift(self) -> None:
        _, focused_hash = _load_exact_suite(FOCUSED_SUITE_PATH)
        _, diagnostic_hash = _load_exact_suite(DIAGNOSTIC_SUITE_PATH)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "progress.json"
            progress = _load_progress(
                path,
                focused_fixture_hash=focused_hash,
                diagnostic_fixture_hash=diagnostic_hash,
            )
            path.write_text(json.dumps(progress), encoding="utf-8")
            loaded = _load_progress(
                path,
                focused_fixture_hash=focused_hash,
                diagnostic_fixture_hash=diagnostic_hash,
            )
            self.assertEqual(loaded, progress)
            with self.assertRaisesRegex(ValueError, "binding mismatch"):
                _load_progress(
                    path,
                    focused_fixture_hash="sha256:" + "0" * 64,
                    diagnostic_fixture_hash=diagnostic_hash,
                )


class StrongCloudBrainLiveRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_route_decision_fetches_fresh_capabilities(self) -> None:
        suite, fixture_hash = _load_exact_suite(FOCUSED_SUITE_PATH)
        identity = IdentityLoader(PROJECT_ROOT / "identity").load().system_text()
        policy = explicit_public_synthetic_policy()
        request, messages, _ = _request_for_case(
            _all_cases(suite)[0],
            arm_name="deepseek_v4_pro_thinking_disabled",
            identity=identity,
            fixture_hash=fixture_hash,
            policy=policy,
        )
        provider = SimpleNamespace(capabilities=AsyncMock(side_effect=["first", "second"]))
        router = Mock()
        router.decide.side_effect = ["route-a", "route-b"]

        first = await _decide_route_with_fresh_capabilities(
            provider=provider,
            router=router,
            request=request,
            policy=policy,
            messages=messages,
        )
        second = await _decide_route_with_fresh_capabilities(
            provider=provider,
            router=router,
            request=request,
            policy=policy,
            messages=messages,
        )

        self.assertEqual((first, second), ("route-a", "route-b"))
        self.assertEqual(provider.capabilities.await_count, 2)
        self.assertEqual(
            [call.kwargs["capabilities"] for call in router.decide.call_args_list],
            ["first", "second"],
        )


if __name__ == "__main__":
    unittest.main()
