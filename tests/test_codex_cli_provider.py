from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from companion.events import TextContentPart
from companion.policy import DataPolicy, PrivacyClass
from mlsys.contracts import GenerationSettings, InferenceMessage, InferenceRequest
from mlsys.contracts.inference import InferenceConstraints
from mlsys.serving.codex_cli import (
    CODEX_CLI_MODEL_ID,
    CODEX_CLI_PROVIDER_ID,
    CODEX_OWNER_AUTOMATIC_AUTHORIZATION_REF,
    CodexCliProvider,
    CodexProcessResult,
    _default_process_runner,
    bind_codex_cli_request,
)
from mlsys.serving.provider import ProviderInferenceError, ProviderPolicyError
from mlsys.serving.router import Stage1Router
from services.api.runtime import (
    LOCAL_PRIVACY_MODEL_VERSION_ID,
    LOCAL_PRIVACY_PROVIDER_ID,
    _build_provider,
    _build_reply_composition,
    _manual_strong_brain_enabled,
    _self_hosted_provider,
)
from services.api.settings import Settings


def _request(*, stream: bool = False, policy: DataPolicy | None = None) -> InferenceRequest:
    return bind_codex_cli_request(InferenceRequest(
        request_id=uuid.uuid4(),
        trace_id=uuid.uuid4().hex,
        messages=(
            InferenceMessage(
                role="system",
                content_parts=(TextContentPart(text="Stable HAVRE identity."),),
                source_refs=("identity/test",),
            ),
            InferenceMessage(
                role="user",
                content_parts=(TextContentPart(text="陪我安静一会儿。"),),
                source_refs=("event/test",),
            ),
        ),
        context_pack_id=uuid.uuid4(),
        generation=GenerationSettings(
            max_output_tokens=256,
            temperature=0.4,
            top_p=1,
        ),
        constraints=InferenceConstraints(
            stream=stream,
            timeout_ms=30_000,
            effective_data_policy=(
                policy
                or DataPolicy.owner_default(
                    PrivacyClass.NORMAL, memory_eligible=True
                )
            ),
            allowed_execution_environments=("cloud",),
        ),
        metadata={},
    ))


class CodexCliProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.executable = Path(self.temporary.name) / "codex.exe"
        self.executable.touch()
        self.calls: list[tuple[tuple[str, ...], str | None, dict[str, str], int]] = []

    async def _runner(self, args, stdin_text, _cwd, environment, timeout_ms):
        self.calls.append((args, stdin_text, dict(environment), timeout_ms))
        if args[-1] == "--version":
            return CodexProcessResult(0, "codex-cli 0.152.0\n", "")
        if args[1:] == ("login", "status"):
            return CodexProcessResult(0, "Logged in using ChatGPT\n", "")
        output = "\n".join((
            json.dumps({"type": "thread.started", "thread_id": "thread-test"}),
            json.dumps({"type": "turn.started"}),
            json.dumps({
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "我在。我们先安静一会儿。"},
            }, ensure_ascii=False),
            json.dumps({
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 111,
                    "cached_input_tokens": 11,
                    "output_tokens": 15,
                    "reasoning_output_tokens": 3,
                },
            }),
        ))
        return CodexProcessResult(0, output, "")

    def test_completed_message_parts_are_preserved_and_deduplicated(self):
        provider = CodexCliProvider(executable=self.executable, enabled=True,
            explicit_authorization_ref=CODEX_OWNER_AUTOMATIC_AUTHORIZATION_REF,
            process_runner=self._runner)
        events = [
            {"type":"thread.started", "thread_id":"multi-part"},
            {"type":"item.completed", "item":{"id":"a", "type":"agent_message", "text":"First thought."}},
            {"type":"item.completed", "item":{"id":"a", "type":"agent_message", "text":"First thought."}},
            {"type":"item.completed", "item":{"id":"b", "type":"agent_message", "text":"Second thought."}},
            {"type":"turn.completed", "usage":{"input_tokens":10, "output_tokens":10}},
        ]
        text, _, _ = provider._parse_jsonl(_request(), "\n".join(json.dumps(e) for e in events))
        self.assertEqual(text, "First thought.\n\nSecond thought.")

    async def test_default_process_runner_kills_and_reaps_child_on_cancellation(
        self,
    ) -> None:
        class FakeProcess:
            def __init__(self) -> None:
                self.returncode = None
                self.communicate_started = asyncio.Event()
                self.killed = False
                self.waited = False

            async def communicate(self, _input):
                self.communicate_started.set()
                await asyncio.Future()

            def kill(self) -> None:
                self.killed = True
                self.returncode = -9

            async def wait(self) -> int:
                self.waited = True
                return -9

        child = FakeProcess()
        create_kwargs = {}

        async def create_process(*_args, **kwargs):
            create_kwargs.update(kwargs)
            return child

        with patch(
            "mlsys.serving.codex_cli.asyncio.create_subprocess_exec",
            new=create_process,
        ):
            task = asyncio.create_task(_default_process_runner(
                (str(self.executable), "exec"),
                "private prompt on stdin",
                Path(self.temporary.name),
                {"PATH": "safe-path"},
                30_000,
            ))
            await child.communicate_started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        self.assertTrue(child.killed)
        self.assertTrue(child.waited)
        if os.name == "nt":
            self.assertNotEqual(create_kwargs.get("creationflags", 0), 0)

    async def test_default_process_runner_kills_and_reaps_child_on_timeout(
        self,
    ) -> None:
        class FakeProcess:
            def __init__(self) -> None:
                self.returncode = None
                self.killed = False
                self.waited = False

            async def communicate(self, _input):
                await asyncio.Future()

            def kill(self) -> None:
                self.killed = True
                self.returncode = -9

            async def wait(self) -> int:
                self.waited = True
                return -9

        child = FakeProcess()

        async def create_process(*_args, **_kwargs):
            return child

        with patch(
            "mlsys.serving.codex_cli.asyncio.create_subprocess_exec",
            new=create_process,
        ):
            with self.assertRaises(TimeoutError):
                await _default_process_runner(
                    (str(self.executable), "exec"),
                    "private prompt on stdin",
                    Path(self.temporary.name),
                    {"PATH": "safe-path"},
                    1,
                )

        self.assertTrue(child.killed)
        self.assertTrue(child.waited)

    def _provider(self, *, runner=None) -> CodexCliProvider:
        return CodexCliProvider(
            executable=self.executable,
            enabled=True,
            explicit_authorization_ref=CODEX_OWNER_AUTOMATIC_AUTHORIZATION_REF,
            process_runner=runner or self._runner,
            environment={
                "PATH": "safe-path",
                "CODEX_HOME": "safe-codex-home",
                "OPENAI_API_KEY": "must-not-leak",
                "DEEPSEEK_API_KEY": "must-not-leak",
            },
        )

    async def test_health_version_route_and_reply_use_chatgpt_without_tools(self) -> None:
        provider = self._provider()
        health = await provider.health()
        version = await provider.version()
        capabilities = await provider.capabilities()
        self.assertEqual(
            capabilities.approved_privacy_classes,
            (PrivacyClass.PUBLIC, PrivacyClass.NORMAL),
        )
        request = _request()
        with self.assertRaisesRegex(ProviderPolicyError, "explicit owner approval"):
            Stage1Router().decide(
                request_id=request.request_id,
                trace_id=request.trace_id,
                policy=request.constraints.effective_data_policy,
                capabilities=capabilities,
                required_output_tokens=256,
            )
        route = Stage1Router(
            approved_cloud_provider_ids=frozenset({CODEX_CLI_PROVIDER_ID})
        ).decide(
            request_id=request.request_id,
            trace_id=request.trace_id,
            policy=request.constraints.effective_data_policy,
            capabilities=capabilities,
            required_output_tokens=256,
        )
        response = await provider.generate(request)

        self.assertEqual(health.status, "healthy")
        self.assertEqual(version.model_version_id, CODEX_CLI_MODEL_ID)
        self.assertEqual(route.selected_provider_id, CODEX_CLI_PROVIDER_ID)
        self.assertEqual(response.output_parts[0].text, "我在。我们先安静一会儿。")
        self.assertEqual(response.provider.provider_request_id, "thread-test")
        self.assertEqual(response.usage.prompt_tokens, 111)
        self.assertEqual(response.usage.prompt_cache_hit_tokens, 11)

        exec_args, prompt, environment, timeout_ms = self.calls[-1]
        self.assertEqual(exec_args[-1], "-")
        self.assertIn("--json", exec_args)
        self.assertIn("--ephemeral", exec_args)
        self.assertIn("--ignore-user-config", exec_args)
        self.assertIn("--ignore-rules", exec_args)
        self.assertIn("read-only", exec_args)
        self.assertNotIn("陪我安静一会儿", " ".join(exec_args))
        self.assertIn("陪我安静一会儿", prompt or "")
        self.assertEqual(timeout_ms, 30_000)
        self.assertEqual(environment["CODEX_HOME"], "safe-codex-home")
        self.assertNotIn("OPENAI_API_KEY", environment)
        self.assertNotIn("DEEPSEEK_API_KEY", environment)

    async def test_health_accepts_and_records_semver_prerelease_cli(self) -> None:
        async def prerelease_runner(args, stdin_text, cwd, environment, timeout_ms):
            if args[-1] == "--version":
                return CodexProcessResult(0, "codex-cli 0.153.0-alpha.5\n", "")
            if args[1:] == ("login", "status"):
                return CodexProcessResult(0, "Logged in using ChatGPT\n", "")
            raise AssertionError("health/version must not start an inference turn")

        provider = self._provider(runner=prerelease_runner)
        self.assertEqual((await provider.health()).status, "healthy")
        self.assertEqual(
            (await provider.version()).serving_engine_version,
            "codex-cli-0.153.0-alpha.5",
        )

    async def test_binding_drift_and_local_only_fail_before_exec(self) -> None:
        provider = self._provider()
        changed = _request().model_copy(
            update={
                "messages": (
                    InferenceMessage(
                        role="user",
                        content_parts=(TextContentPart(text="changed after binding"),),
                        source_refs=("event/test",),
                    ),
                )
            }
        )
        with self.assertRaises(ProviderInferenceError) as drift:
            await provider.generate(changed)
        self.assertEqual(drift.exception.code, "privacy_constraint_unsatisfied")

        local_only = _request(policy=DataPolicy.owner_default(
            PrivacyClass.LOCAL_ONLY, memory_eligible=True
        ))
        with self.assertRaises(ProviderInferenceError) as local:
            await provider.generate(local_only)
        self.assertEqual(local.exception.code, "privacy_constraint_unsatisfied")
        private = _request(policy=DataPolicy.owner_default(
            PrivacyClass.PRIVATE, memory_eligible=True
        ))
        with self.assertRaises(ProviderInferenceError) as private_error:
            await provider.generate(private)
        self.assertEqual(
            private_error.exception.code, "privacy_constraint_unsatisfied"
        )
        self.assertEqual(self.calls, [])

    async def test_protocol_rejects_any_tool_activity(self) -> None:
        async def tool_runner(args, stdin_text, cwd, environment, timeout_ms):
            if args[-1] == "--version":
                return CodexProcessResult(0, "codex-cli 0.152.0\n", "")
            if args[1:] == ("login", "status"):
                return CodexProcessResult(0, "Logged in using ChatGPT\n", "")
            return CodexProcessResult(0, "\n".join((
                json.dumps({"type": "thread.started", "thread_id": "thread-test"}),
                json.dumps({
                    "type": "item.completed",
                    "item": {"type": "command_execution", "command": "whoami"},
                }),
            )), "")

        with self.assertRaises(ProviderInferenceError) as raised:
            await self._provider(runner=tool_runner).generate(_request())
        self.assertEqual(raised.exception.code, "provider_protocol_error")
        self.assertEqual(raised.exception.failure.provider_error_code, "forbidden_tool_activity")

    def test_settings_build_exact_codex_provider_only_in_owner_local_mode(self) -> None:
        with patch.dict(os.environ, {
            "HAVRE_PROVIDER_ID": CODEX_CLI_PROVIDER_ID,
            "HAVRE_CODEX_CLI_PATH": str(self.executable),
        }, clear=True):
            settings = Settings.from_env(require_owner_api_token=False)
        provider = _build_provider(settings)
        self.assertIsInstance(provider, CodexCliProvider)
        self.assertEqual(provider.executable, self.executable.resolve())

        with patch.dict(os.environ, {
            "HAVRE_PROVIDER_ID": CODEX_CLI_PROVIDER_ID,
            "HAVRE_CODEX_CLI_PATH": str(self.executable),
            "HAVRE_DEPLOYMENT_ENVIRONMENT": "production",
        }, clear=True):
            with self.assertRaisesRegex(ValueError, "owner-local development only"):
                Settings.from_env(require_owner_api_token=False)

    def test_manual_strong_requires_explicit_gate_in_addition_to_key(self) -> None:
        with patch.dict(os.environ, {
            "DEEPSEEK_API_KEY": "stale-key-must-not-activate",
        }, clear=True):
            stale_key = Settings.from_env(require_owner_api_token=False)
        self.assertFalse(stale_key.manual_strong_brain_enabled)
        self.assertFalse(_manual_strong_brain_enabled(stale_key))

        with patch.dict(os.environ, {
            "DEEPSEEK_API_KEY": "explicit-key",
            "HAVRE_MANUAL_STRONG_BRAIN_ENABLED": "true",
        }, clear=True):
            explicitly_enabled = Settings.from_env(require_owner_api_token=False)
        self.assertTrue(explicitly_enabled.manual_strong_brain_enabled)
        self.assertTrue(_manual_strong_brain_enabled(explicitly_enabled))

        with patch.dict(os.environ, {
            "HAVRE_MANUAL_STRONG_BRAIN_ENABLED": "true",
        }, clear=True):
            with self.assertRaisesRegex(
                ValueError,
                "requires a DeepSeek API key",
            ):
                Settings.from_env(require_owner_api_token=False)

    def test_dual_composition_pins_local_budget_and_cloud_only_binder(self) -> None:
        example_bank_path = Path(self.temporary.name) / "examples.json"
        example_bank_path.touch()
        with patch.dict(os.environ, {
            "HAVRE_PROVIDER_ID": CODEX_CLI_PROVIDER_ID,
            "HAVRE_CODEX_CLI_PATH": str(self.executable),
            "HAVRE_CONTEXT_TOKEN_BUDGET": "16384",
            "HAVRE_RESERVED_OUTPUT_TOKENS": "3072",
            "HAVRE_LOCAL_RESERVED_OUTPUT_TOKENS": "1024",
            "HAVRE_OWNER_EXAMPLE_BANK_PATH": str(example_bank_path),
        }, clear=True):
            settings = Settings.from_env(require_owner_api_token=False)

        class LocalRuntimeFixture:
            provider_id = LOCAL_PRIVACY_PROVIDER_ID
            max_context_tokens = 8192
            max_output_tokens = 4096

        cloud = self._provider()
        local = LocalRuntimeFixture()
        example_bank = object()
        with patch(
            "services.api.runtime.load_owner_example_bank",
            return_value=example_bank,
        ):
            (
                cloud_builder,
                builders,
                router,
                binders,
            ) = _build_reply_composition(
                settings,
                provider=cloud,
                providers={
                    cloud.provider_id: cloud,
                    local.provider_id: local,
                },
            )

        self.assertEqual(cloud_builder.token_budget.max_input_tokens, 16384)
        self.assertEqual(cloud_builder.token_budget.reserved_output_tokens, 3072)
        self.assertIs(cloud_builder.owner_example_bank, example_bank)
        self.assertEqual(
            builders[LOCAL_PRIVACY_PROVIDER_ID].token_budget.max_input_tokens,
            8192,
        )
        self.assertEqual(
            builders[LOCAL_PRIVACY_PROVIDER_ID].token_budget.reserved_output_tokens,
            1024,
        )
        self.assertIsNone(
            builders[LOCAL_PRIVACY_PROVIDER_ID].owner_example_bank
        )
        self.assertEqual(set(binders), {CODEX_CLI_PROVIDER_ID})
        self.assertIs(binders[CODEX_CLI_PROVIDER_ID].func, bind_codex_cli_request)
        self.assertEqual(
            binders[CODEX_CLI_PROVIDER_ID].keywords,
            {"reasoning_effort": "medium"},
        )
        self.assertEqual(router.cloud_provider_id, CODEX_CLI_PROVIDER_ID)
        self.assertEqual(router.local_provider_id, LOCAL_PRIVACY_PROVIDER_ID)

    def test_codex_reasoning_effort_is_explicit_and_configurable(self) -> None:
        with patch.dict(os.environ, {
            "HAVRE_PROVIDER_ID": CODEX_CLI_PROVIDER_ID,
            "HAVRE_CODEX_CLI_PATH": str(self.executable),
        }, clear=True):
            balanced = Settings.from_env(require_owner_api_token=False)
        self.assertEqual(balanced.codex_reasoning_effort, "medium")
        self.assertEqual(_build_provider(balanced).reasoning_effort, "medium")

        with patch.dict(os.environ, {
            "HAVRE_PROVIDER_ID": CODEX_CLI_PROVIDER_ID,
            "HAVRE_CODEX_CLI_PATH": str(self.executable),
            "HAVRE_CODEX_REASONING_EFFORT": "low",
        }, clear=True):
            faster = Settings.from_env(require_owner_api_token=False)
        self.assertEqual(_build_provider(faster).reasoning_effort, "low")

    def test_local_privacy_provider_rejects_other_model_and_any_adapter(self) -> None:
        with patch.dict(os.environ, {
            "HAVRE_PROVIDER_ID": CODEX_CLI_PROVIDER_ID,
            "HAVRE_CODEX_CLI_PATH": str(self.executable),
        }, clear=True):
            settings = Settings.from_env(require_owner_api_token=False)

        wrong_model = settings.model_copy(update={
            "self_hosted_model_manifest": (
                Path(__file__).resolve().parents[1]
                / "mlsys"
                / "serving"
                / "manifests"
                / "qwen3-6-35b-a3b-q4-k-m.json"
            ),
        })
        with self.assertRaisesRegex(
            ValueError,
            "exact approved Qwen3-8B base artifact",
        ):
            _self_hosted_provider(
                wrong_model,
                provider_id=LOCAL_PRIVACY_PROVIDER_ID,
                require_unadapted_qwen3_8b=True,
            )

        adapted = settings.model_copy(update={
            "runtime_adapter_version": "forbidden-adapter",
            "runtime_adapter_hash": "sha256:" + "a" * 64,
        })
        self.assertEqual(
            json.loads(
                settings.self_hosted_model_manifest.read_text(encoding="utf-8")
            )["manifest_id"],
            LOCAL_PRIVACY_MODEL_VERSION_ID,
        )
        with self.assertRaisesRegex(
            ValueError,
            "forbids every HAVRE adapter binding",
        ):
            _self_hosted_provider(
                adapted,
                provider_id=LOCAL_PRIVACY_PROVIDER_ID,
                require_unadapted_qwen3_8b=True,
            )


if __name__ == "__main__":
    unittest.main()
