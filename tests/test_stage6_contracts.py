from __future__ import annotations

import json
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from companion.context import ControlledContextStrategy
from companion.identity import IdentityLoader
from companion.life_context import LifeContextObservation, SignalFreshness
from companion.policy import DataPolicy, PrivacyClass
from companion.proactive import (
    InterruptionOutcome,
    InterruptionPolicy,
    ProactivePreferenceRevision,
    ProactiveProposal,
)
from evals.proactive_evaluation import run_proactive_evaluation
from mlsys.serving import AdaptiveRouter, EligibleProviderProfile
from scripts.export_contract_schemas import CONTRACTS
from services.api.app import create_app


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Stage6PolicyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.identity = IdentityLoader(PROJECT_ROOT / "identity").load()
        cls.policy = InterruptionPolicy(
            constitution_version_id=cls.identity.constitution.version_id,
            identity_version_id=cls.identity.identity.version_id,
        )
        cls.owner = uuid.uuid4()
        cls.now = datetime.now(UTC)

    def _proposal(self, **overrides):
        values = {
            "owner_id": self.owner,
            "category": "owner_reminder",
            "trigger_refs": (uuid.uuid4(),),
            "reason_code": "owner_requested_fixture",
            "reason_summary": "Review the owner-chosen goal",
            "intended_benefit": "Support a chosen commitment",
            "evidence_refs": ("goal/synthetic",),
            "data_policy": DataPolicy.owner_default(
                PrivacyClass.LOCAL_ONLY, memory_eligible=False
            ),
            "earliest_eligible_at": self.now - timedelta(minutes=1),
            "expires_at": self.now + timedelta(hours=2),
            "deduplication_key": "goal:synthetic",
            "trace_id": uuid.uuid4().hex,
        }
        values.update(overrides)
        return ProactiveProposal.model_validate(values)

    def _preference(self, **overrides):
        values = {
            "owner_id": self.owner,
            "revision": 1,
            "global_enabled": True,
            "category_permissions": {"owner_reminder": "allowed"},
            "allowed_channels": ("web_inbox",),
            "global_budget_per_24h": 2,
            "category_budget_per_24h": {"owner_reminder": 1},
            "cooldown_seconds": 3600,
            "authorization_ref": "stage6-contract-fixture",
        }
        values.update(overrides)
        return ProactivePreferenceRevision.model_validate(values)

    def test_send_requires_every_explicit_hard_control(self) -> None:
        decision = self.policy.decide(
            proposal=self._proposal(), preference=self._preference(), now=self.now,
            delivered_global_24h=0, delivered_category_24h=0,
            last_equivalent_delivery_at=None, duplicate_active=False,
        )
        self.assertEqual(decision.decision, InterruptionOutcome.SEND_NOW)
        self.assertTrue(decision.simulation_only)
        self.assertFalse(decision.external_delivery_authorized)

    def test_unresolved_limits_and_confirmation_never_send(self) -> None:
        for preference in (
            self._preference(global_budget_per_24h=None),
            self._preference(category_permissions={"owner_reminder": "confirmation_required"}),
        ):
            with self.subTest(preference=preference):
                decision = self.policy.decide(
                    proposal=self._proposal(), preference=preference, now=self.now,
                    delivered_global_24h=0, delivered_category_24h=0,
                    last_equivalent_delivery_at=None, duplicate_active=False,
                )
                self.assertEqual(
                    decision.decision, InterruptionOutcome.REQUEST_OWNER_CONFIRMATION
                )

    def test_owner_snooze_and_non_response_fail_closed(self) -> None:
        snooze_until = self.now + timedelta(minutes=20)
        snoozed = self.policy.decide(
            proposal=self._proposal(), preference=self._preference(), now=self.now,
            delivered_global_24h=0, delivered_category_24h=0,
            last_equivalent_delivery_at=None, duplicate_active=False,
            prior_response_result="snoozed", snooze_until=snooze_until,
        )
        self.assertEqual(snoozed.decision, InterruptionOutcome.DEFER)
        self.assertEqual(snoozed.defer_until, snooze_until)
        silent = self.policy.decide(
            proposal=self._proposal(), preference=self._preference(), now=self.now,
            delivered_global_24h=0, delivered_category_24h=0,
            last_equivalent_delivery_at=None, duplicate_active=False,
            prior_response_result="non_response",
        )
        self.assertEqual(silent.decision, InterruptionOutcome.DROP)
        self.assertIn("non_response_frequency_suppressed", silent.reason_codes)

    def test_synthetic_context_signal_is_observation_not_interpretation(self) -> None:
        observation = LifeContextObservation(
            owner_id=self.owner,
            value="unknown",
            freshness=SignalFreshness(
                observed_at=self.now, valid_until=self.now + timedelta(minutes=5),
                clock_uncertainty_seconds=1,
            ),
            data_policy=DataPolicy.owner_default(
                PrivacyClass.LOCAL_ONLY, memory_eligible=False
            ),
            trace_id=uuid.uuid4().hex,
        )
        self.assertFalse(observation.external_source_activated)
        payload = observation.model_dump(mode="json")
        payload["source_id"] = "windows-agent"
        with self.assertRaises(ValidationError):
            LifeContextObservation.model_validate(payload)


class Stage6OptimizationAndEvaluationTests(unittest.TestCase):
    def test_prefix_is_stable_across_controlled_strategies(self) -> None:
        candidates = (("event/a", "alpha " * 50, 3), ("event/b", "beta " * 50, 2))
        raw = ControlledContextStrategy(mode="raw_top_k", top_k=2).build(
            identity_version="identity-v1", policy_version="policy-v1", candidates=candidates
        )
        compressed = ControlledContextStrategy(mode="compressed_top_k", top_k=1).build(
            identity_version="identity-v1", policy_version="policy-v1", candidates=candidates
        )
        self.assertEqual(raw.prefix_hash, compressed.prefix_hash)
        self.assertLess(compressed.estimated_tokens, raw.estimated_tokens)

    def test_adaptive_router_filters_cloud_before_ranking(self) -> None:
        policy = DataPolicy.owner_default(PrivacyClass.LOCAL_ONLY, memory_eligible=False)
        profiles = (
            EligibleProviderProfile(
                "cloud", "cloud", "cloud-v1", "cloud", "strong", 10000,
                frozenset({PrivacyClass.LOCAL_ONLY}), measured_quality=1.0,
            ),
            EligibleProviderProfile(
                "local", "local", "local-v1", "local", "fast", 4096,
                frozenset({PrivacyClass.LOCAL_ONLY}), measured_quality=0.8,
                measured_latency_ms=10,
            ),
        )
        decision = AdaptiveRouter().decide(
            policy=policy, required_input_tokens=1000,
            quality_requirement="strong", profiles=profiles,
        )
        self.assertEqual(decision.selected_profile_id, "local")
        self.assertEqual(dict(decision.excluded_profiles)["cloud"], "cloud_forbidden_by_data_policy")

    def test_frozen_four_way_report_and_exported_schemas(self) -> None:
        report = run_proactive_evaluation(
            fixture_path=PROJECT_ROOT / "evals" / "fixtures" / "proactive_policy_cases_v1.json",
            identity=IdentityLoader(PROJECT_ROOT / "identity").load(),
        )
        self.assertEqual(report.metrics["failed"], 0)
        self.assertEqual(report.metrics["external_delivery_authorized"], 0)
        self.assertEqual(report.routing_tradeoff["adoption"], "routine-fast-with-strong-fallback")
        expected = {
            "proactive-trigger-v1", "proactive-proposal-v1",
            "proactive-preference-revision-v1", "interruption-decision-v1",
            "proactive-context-pack-v1", "rendered-proactive-message-v1",
            "delivery-attempt-v1", "life-context-observation-v1",
            "proactive-evaluation-report-v1", "proactive-owner-action-v1",
            "proactive-work-command-v1",
        }
        self.assertTrue(expected.issubset(CONTRACTS))
        paths = create_app().openapi()["paths"]
        for path in (
            "/v1/proactive/preferences",
            "/v1/proactive/simulations/reach-out",
            "/v1/proactive/proposals/{proposal_id}/actions",
            "/v1/proactive/proposals/{proposal_id}/delivery-reconciliation",
            "/v1/proactive/work",
            "/v1/proactive/work/run-once",
        ):
            self.assertIn(path, paths)

    def test_committed_stage6_schemas_match_contracts(self) -> None:
        root = PROJECT_ROOT / "contracts" / "schemas"
        names = (
            "proactive-trigger-v1", "proactive-proposal-v1",
            "proactive-preference-revision-v1", "interruption-decision-v1",
            "proactive-context-pack-v1", "rendered-proactive-message-v1",
            "delivery-attempt-v1", "life-context-observation-v1",
            "proactive-evaluation-report-v1", "proactive-owner-action-v1",
            "proactive-work-command-v1",
        )
        for name in names:
            with self.subTest(name=name):
                committed = json.loads((root / f"{name}.json").read_text(encoding="utf-8"))
                self.assertEqual(committed, CONTRACTS[name].model_json_schema())
