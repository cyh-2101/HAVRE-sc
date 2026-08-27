from __future__ import annotations

import json
import shutil
import tempfile
import unittest
import uuid
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from companion import __version__
from companion.context import ContextBudgetExceeded, ContextBuilder
from companion.events import (
    EventEnvelope,
    EventType,
    TextContentPart,
    UserMessagePayload,
)
from companion.identity import IdentityLoader
from companion.ids import new_span_id, new_trace_id, uuid7
from companion.policy import DataPolicy, PrivacyClass, combine_policies
from companion.tracing import TraceContext, parse_traceparent
from mlsys.contracts import (
    GenerationSettings,
    InferenceMessage,
    InferenceRequest,
    InferenceResponse,
)
from mlsys.contracts.inference import InferenceConstraints, ProviderCapabilities
from mlsys.serving import DeterministicLocalProvider, ProviderPolicyError, Stage1Router
from services.api.app import create_app
from services.api.cli import demo_idempotency_key, run_local_chat_loop
from scripts.export_contract_schemas import CONTRACTS


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OWNER_ID = uuid.UUID("00000000-0000-7000-8000-000000000001")


class IdentifierTests(unittest.TestCase):
    def test_uuid7_is_rfc_variant_version_and_monotonic(self) -> None:
        values = [uuid7() for _ in range(20)]
        self.assertTrue(all(item.version == 7 for item in values))
        self.assertTrue(all(item.variant == uuid.RFC_4122 for item in values))
        self.assertEqual(values, sorted(values))

    def test_trace_and_span_ids_are_nonzero_lowercase_hex(self) -> None:
        trace_id = new_trace_id()
        span_id = new_span_id()
        self.assertRegex(trace_id, r"^[0-9a-f]{32}$")
        self.assertRegex(span_id, r"^[0-9a-f]{16}$")
        self.assertNotEqual(trace_id, "0" * 32)
        self.assertNotEqual(span_id, "0" * 16)


class DataPolicyTests(unittest.TestCase):
    def test_owner_defaults_match_stage_1_decisions(self) -> None:
        expected_cloud = {
            PrivacyClass.PUBLIC: True,
            PrivacyClass.NORMAL: True,
            PrivacyClass.PRIVATE: True,
            PrivacyClass.HIGHLY_PRIVATE: False,
            PrivacyClass.LOCAL_ONLY: False,
        }
        for privacy, cloud in expected_cloud.items():
            with self.subTest(privacy=privacy):
                policy = DataPolicy.owner_default(privacy)
                self.assertEqual(policy.cloud_eligible, cloud)
                self.assertFalse(policy.training_eligible)

    def test_local_only_cannot_be_cloud_eligible(self) -> None:
        with self.assertRaises(ValidationError):
            DataPolicy(
                privacy_class=PrivacyClass.LOCAL_ONLY,
                memory_eligible=True,
                cloud_eligible=True,
                decision_source="owner_explicit",
                authorization_ref="owner-approval/1",
            )

    def test_highly_private_cloud_requires_owner_authorization(self) -> None:
        with self.assertRaises(ValidationError):
            DataPolicy(
                privacy_class=PrivacyClass.HIGHLY_PRIVATE,
                memory_eligible=True,
                cloud_eligible=True,
                decision_source="owner_default",
            )
        explicit = DataPolicy(
            privacy_class=PrivacyClass.HIGHLY_PRIVATE,
            memory_eligible=True,
            cloud_eligible=True,
            decision_source="owner_explicit",
            authorization_ref="owner-approval/1",
        )
        self.assertTrue(explicit.cloud_eligible)

    def test_training_cannot_be_enabled_in_stage_1_contract(self) -> None:
        with self.assertRaises(ValidationError):
            DataPolicy(
                privacy_class=PrivacyClass.NORMAL,
                memory_eligible=True,
                training_eligible=True,
                cloud_eligible=True,
                decision_source="owner_explicit",
                authorization_ref="owner-approval/2",
            )

    def test_derived_policy_is_separate_and_conservative(self) -> None:
        normal = DataPolicy.owner_default(PrivacyClass.NORMAL)
        local = DataPolicy.owner_default(PrivacyClass.LOCAL_ONLY)
        combined = combine_policies((normal, local))
        self.assertNotIn(
            combined.policy_revision_id,
            {normal.policy_revision_id, local.policy_revision_id},
        )
        self.assertEqual(combined.privacy_class, PrivacyClass.LOCAL_ONLY)
        self.assertFalse(combined.cloud_eligible)
        self.assertEqual(combined.decision_source, "derived_conservative")


class TraceContextTests(unittest.TestCase):
    def test_valid_traceparent_is_propagated(self) -> None:
        trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
        parent = "00f067aa0ba902b7"
        parsed = parse_traceparent(f"00-{trace_id}-{parent}-01")
        self.assertEqual(parsed, (trace_id, parent, "01"))
        context = TraceContext.from_traceparent(f"00-{trace_id}-{parent}-01")
        self.assertEqual(context.trace_id, trace_id)
        self.assertEqual(context.parent_span_id, parent)

    def test_invalid_or_all_zero_traceparent_generates_new_trace(self) -> None:
        self.assertIsNone(parse_traceparent("invalid"))
        self.assertIsNone(
            parse_traceparent(f"00-{'0' * 32}-{'1' * 16}-01")
        )
        context = TraceContext.from_traceparent("invalid")
        self.assertRegex(context.trace_id, r"^[0-9a-f]{32}$")

    def test_spans_contain_no_message_text(self) -> None:
        context = TraceContext.from_traceparent(None)
        with context.span("context.build", attributes={"selected_items": 2}):
            pass
        serialized = context.spans[0].model_dump_json()
        self.assertNotIn("protected user content", serialized)
        self.assertIn("selected_items", serialized)


class EventAndContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.identity = IdentityLoader(PROJECT_ROOT / "identity").load()
        self.request_id = uuid7()
        self.event = EventEnvelope(
            event_type=EventType.USER_MESSAGE,
            owner_id=OWNER_ID,
            session_id=uuid7(),
            request_id=self.request_id,
            trace_id=new_trace_id(),
            data_policy=DataPolicy.owner_default(PrivacyClass.LOCAL_ONLY),
            payload=UserMessagePayload(
                content_parts=(TextContentPart(text="A private current request."),),
                channel="api",
            ),
        )

    def test_event_hash_detects_tampering(self) -> None:
        self.assertRegex(self.event.content_hash, r"^sha256:[0-9a-f]{64}$")
        data = self.event.model_dump()
        data["content_hash"] = "sha256:" + "0" * 64
        with self.assertRaises(ValidationError):
            EventEnvelope.model_validate(data)

    def test_unknown_payload_fields_fail_closed(self) -> None:
        with self.assertRaises(ValidationError):
            UserMessagePayload.model_validate(
                {
                    "content_parts": [{"type": "text", "text": "hello"}],
                    "channel": "api",
                    "unexpected": True,
                }
            )

    def test_context_pack_has_budget_provenance_and_effective_policy(self) -> None:
        pack = ContextBuilder(
            max_input_tokens=4096,
            reserved_output_tokens=256,
        ).build(
            request_id=self.request_id,
            trace_id=self.event.trace_id,
            owner_id=OWNER_ID,
            identity=self.identity,
            user_event=self.event,
        )
        self.assertEqual([s.section_id for s in pack.sections], ["identity", "current-user-input"])
        self.assertEqual(pack.sections[1].source_refs, (f"event/{self.event.event_id}",))
        self.assertEqual(pack.effective_data_policy.privacy_class, PrivacyClass.LOCAL_ONLY)
        self.assertFalse(pack.effective_data_policy.cloud_eligible)
        self.assertLessEqual(
            pack.estimated_total_tokens,
            pack.token_budget.max_input_tokens - pack.token_budget.reserved_output_tokens,
        )

    def test_required_context_fails_instead_of_silent_truncation(self) -> None:
        with self.assertRaises(ContextBudgetExceeded):
            ContextBuilder(max_input_tokens=64, reserved_output_tokens=32).build(
                request_id=self.request_id,
                trace_id=self.event.trace_id,
                owner_id=OWNER_ID,
                identity=self.identity,
                user_event=self.event,
            )

    def test_identity_versions_are_exact_and_approved(self) -> None:
        self.assertEqual(self.identity.constitution.version_id, "constitution-v1")
        self.assertEqual(self.identity.identity.version_id, "identity-v1")
        self.assertEqual(self.identity.values.version_id, "values-v1")
        self.assertEqual(self.identity.constitution.approved_by, "owner")
        self.assertIn("Agency", self.identity.constitution.content)
        self.assertIn("Foundation models are replaceable", self.identity.constitution.content)

    def test_identity_loader_rejects_nonowner_governance_activation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            identity_root = Path(temporary) / "identity"
            shutil.copytree(PROJECT_ROOT / "identity", identity_root)
            governance_path = identity_root / "governance.json"
            governance = json.loads(governance_path.read_text(encoding="utf-8"))
            governance["approved_by"] = "model"
            governance_path.write_text(
                json.dumps(governance, indent=2),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "owner-approved"):
                IdentityLoader(identity_root).load()


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_deterministic_provider_normalizes_versions_usage_and_timing(self) -> None:
        provider = DeterministicLocalProvider()
        policy = DataPolicy.owner_default(PrivacyClass.NORMAL)
        request = InferenceRequest(
            request_id=uuid7(),
            trace_id=new_trace_id(),
            messages=(
                InferenceMessage(
                    role="user",
                    content_parts=(TextContentPart(text="Help me choose a step."),),
                    source_refs=("event/test",),
                ),
            ),
            context_pack_id=uuid7(),
            generation=GenerationSettings(max_output_tokens=128, temperature=0.4, top_p=1.0),
            constraints=InferenceConstraints(
                stream=False,
                timeout_ms=20_000,
                effective_data_policy=policy,
                allowed_execution_environments=("local", "cloud"),
            ),
            metadata={},
        )
        response = await provider.generate(request)
        self.assertEqual(response.request_id, request.request_id)
        self.assertEqual(response.trace_id, request.trace_id)
        self.assertEqual(response.provider.provider_id, "deterministic-local")
        self.assertEqual(response.versions.model_version_id, "deterministic-companion-v1")
        self.assertEqual(response.usage.total_tokens, response.usage.prompt_tokens + response.usage.output_tokens)
        self.assertGreaterEqual(response.timing_ms.total, 0)

    async def test_provider_response_cannot_activate_governance(self) -> None:
        provider = DeterministicLocalProvider()
        policy = DataPolicy.owner_default(PrivacyClass.NORMAL)
        request = InferenceRequest(
            request_id=uuid7(),
            trace_id=new_trace_id(),
            messages=(
                InferenceMessage(
                    role="user",
                    content_parts=(TextContentPart(text="A request."),),
                    source_refs=("event/test",),
                ),
            ),
            context_pack_id=uuid7(),
            generation=GenerationSettings(
                max_output_tokens=64,
                temperature=0.4,
                top_p=1.0,
            ),
            constraints=InferenceConstraints(
                stream=False,
                timeout_ms=100,
                effective_data_policy=policy,
                allowed_execution_environments=("local", "cloud"),
            ),
            metadata={},
        )
        response = await provider.generate(request)
        payload = response.model_dump(mode="json")
        payload["activate_constitution_version_id"] = "constitution-v999"
        with self.assertRaises(ValidationError):
            InferenceResponse.model_validate(payload)

    async def test_cloud_routing_requires_both_policy_and_approved_provider(self) -> None:
        policy = DataPolicy.owner_default(PrivacyClass.PRIVATE)
        capabilities = ProviderCapabilities(
            provider_id="cloud-a",
            provider_class="cloud",
            execution_environment="cloud",
            available_model_version_ids=("model-a-v1",),
            approved_privacy_classes=(PrivacyClass.PRIVATE,),
            supports_streaming=True,
            max_context_tokens=1000,
            max_output_tokens=100,
            observed_at=datetime.now(UTC),
            ttl_seconds=30,
        )
        with self.assertRaises(ProviderPolicyError):
            Stage1Router().decide(
                request_id=uuid7(),
                trace_id=new_trace_id(),
                policy=policy,
                capabilities=capabilities,
            )
        route = Stage1Router(
            approved_cloud_provider_ids=frozenset({"cloud-a"})
        ).decide(
            request_id=uuid7(),
            trace_id=new_trace_id(),
            policy=policy,
            capabilities=capabilities,
        )
        self.assertEqual(route.selected_provider_id, "cloud-a")


class ApiContractTests(unittest.TestCase):
    def test_openapi_exposes_stage4_user_model_state_and_goal_lifecycle(self) -> None:
        app = create_app()
        paths = app.openapi()["paths"]
        self.assertEqual(app.version, __version__)
        self.assertIn("/v1/interactions", paths)
        self.assertIn("/v1/interactions/{request_id}/evidence", paths)
        self.assertIn("/v1/memory/jobs/run-once", paths)
        self.assertIn("/v1/memory/candidates", paths)
        self.assertIn("/v1/memories", paths)
        self.assertIn("/v1/user-model/beliefs", paths)
        self.assertIn("/v1/user-model/beliefs/{belief_id}/revisions", paths)
        self.assertIn("/v1/user-model/beliefs/{belief_id}/transitions", paths)
        self.assertIn("/v1/consolidation/proposals", paths)
        self.assertIn("/v1/current-state", paths)
        self.assertIn("/v1/goals", paths)
        self.assertIn("/v1/goals/{goal_id}/progress", paths)

    def test_committed_json_schemas_match_typed_contracts(self) -> None:
        schema_root = PROJECT_ROOT / "contracts" / "schemas"
        for name, contract in CONTRACTS.items():
            with self.subTest(contract=name):
                committed = json.loads(
                    (schema_root / f"{name}.json").read_text(encoding="utf-8")
                )
                self.assertEqual(committed, contract.model_json_schema())

    def test_cli_demo_default_idempotency_keys_are_unique(self) -> None:
        first = demo_idempotency_key(None)
        second = demo_idempotency_key(None)
        self.assertNotEqual(first, second)
        self.assertEqual(demo_idempotency_key("owner-key"), "owner-key")


class LocalChatTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_chat_uses_core_with_one_local_only_session(self) -> None:
        commands = []

        class RecordingService:
            async def interact(self, command):
                commands.append(command)
                return type("Result", (), {"content": f"reply-{len(commands)}"})()

        inputs = iter(("first", "second", "/exit"))
        outputs = []
        session_id = await run_local_chat_loop(
            RecordingService(),
            input_fn=lambda _prompt: next(inputs),
            output_fn=outputs.append,
        )

        self.assertEqual(outputs, ["HAVRE Local", "", "HAVRE: reply-1", "", "HAVRE: reply-2", ""])
        self.assertEqual(len(commands), 2)
        self.assertTrue(all(command.session_id == session_id for command in commands))
        self.assertTrue(
            all(command.privacy_class is PrivacyClass.LOCAL_ONLY for command in commands)
        )
        self.assertTrue(all(not command.memory_eligible for command in commands))
        self.assertTrue(all(command.channel == "cli" for command in commands))
        self.assertEqual(len({command.idempotency_key for command in commands}), 2)


if __name__ == "__main__":
    unittest.main()
