from __future__ import annotations

import json
import os
import unittest
import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import httpx

from companion.events import TextContentPart
from companion.policy import DataPolicy, PrivacyClass
from mlsys.contracts import (
    GenerationSettings,
    InferenceMessage,
    InferenceRequest,
    TokenUsage,
)
from mlsys.contracts.inference import InferenceConstraints
from mlsys.serving import DeepSeekCloudProvider, Stage1Router
from mlsys.serving.deepseek_cloud import (
    DEEPSEEK_MODEL_ID,
    DEEPSEEK_MODEL_VERSION,
    DEEPSEEK_PROVIDER_ID,
    OWNER_MANUAL_AUTHORIZATION_REF,
    OWNER_MANUAL_BOUNDARY,
    PUBLIC_SYNTHETIC_BOUNDARY,
    STRONG_CLOUD_BRAIN_AUTHORIZATION_REF,
    bind_cloud_experiment_request,
)
from mlsys.serving.provider import (
    ProviderInferenceError,
    ProviderPolicyError,
    ProviderVersionError,
)


AUTHORIZATION_REF = STRONG_CLOUD_BRAIN_AUTHORIZATION_REF
FIXTURE_HASH = "sha256:" + "1" * 64


def _policy(privacy: PrivacyClass = PrivacyClass.PUBLIC) -> DataPolicy:
    return DataPolicy(
        privacy_class=privacy,
        memory_eligible=False,
        cloud_eligible=privacy is not PrivacyClass.LOCAL_ONLY,
        decision_source="owner_explicit",
        authorization_ref=AUTHORIZATION_REF,
    )


def _request(
    *,
    stream: bool,
    policy: DataPolicy | None = None,
    metadata: dict[str, str] | None = None,
    thinking: str = "disabled",
) -> InferenceRequest:
    request = InferenceRequest(
        request_id=uuid.uuid4(),
        trace_id=uuid.uuid4().hex,
        messages=(
            InferenceMessage(
                role="system",
                content_parts=(TextContentPart(text="Synthetic identity."),),
                source_refs=("identity/public-fixture",),
            ),
            InferenceMessage(
                role="user",
                content_parts=(TextContentPart(text="Synthetic question."),),
                source_refs=("eval-fixture/case-a",),
            ),
        ),
        context_pack_id=uuid.uuid4(),
        generation=GenerationSettings(
            max_output_tokens=96,
            temperature=0,
            top_p=1,
        ),
        constraints=InferenceConstraints(
            stream=stream,
            timeout_ms=30_000,
            effective_data_policy=policy or _policy(),
            allowed_execution_environments=("cloud",),
        ),
        metadata=(
            metadata
            if metadata is not None
            else {
                "evaluation_data_boundary": PUBLIC_SYNTHETIC_BOUNDARY,
                "evaluation_fixture_hash": FIXTURE_HASH,
                "cloud_authorization_ref": AUTHORIZATION_REF,
            }
        ),
    )
    return bind_cloud_experiment_request(
        request, thinking=thinking, reasoning_effort="high"
    )


def _permit(*requests: InferenceRequest) -> dict[str, frozenset[str]]:
    return {
        "allowed_fixture_hashes": frozenset({FIXTURE_HASH}),
        "allowed_request_hashes": frozenset(
            request.metadata["cloud_request_binding_hash"] for request in requests
        ),
    }


class DeepSeekCloudProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_disabled_provider_never_calls_network(self) -> None:
        calls = 0

        async def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(500)

        with patch.dict(os.environ, {}, clear=True):
            provider = DeepSeekCloudProvider(
                transport=httpx.MockTransport(handler)
            )
        self.addAsyncCleanup(provider.aclose)
        health = await provider.health()
        self.assertEqual(health.status, "unavailable")
        self.assertEqual(health.reasons, ("cloud_provider_disabled",))
        with self.assertRaises(ProviderVersionError):
            await provider.capabilities()
        with self.assertRaises(ProviderInferenceError) as raised:
            await provider.generate(_request(stream=False))
        self.assertEqual(raised.exception.code, "unsupported_capability")
        self.assertEqual(calls, 0)

    def test_enabled_provider_reads_only_named_environment_secret(self) -> None:
        request = _request(stream=False)
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "DEEPSEEK_API_KEY is required"):
                DeepSeekCloudProvider(
                    enabled=True,
                    explicit_authorization_ref=AUTHORIZATION_REF,
                    **_permit(request),
                )

    def test_enabled_provider_rejects_arbitrary_authorization_and_malformed_permit(self) -> None:
        request = _request(stream=False)
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "not-a-real-key"}):
            with self.assertRaisesRegex(ValueError, "exact experiment authorization"):
                DeepSeekCloudProvider(
                    enabled=True,
                    explicit_authorization_ref="owner-says-ok",
                    **_permit(request),
                )
            with self.assertRaisesRegex(ValueError, "invalid fixture hash"):
                DeepSeekCloudProvider(
                    enabled=True,
                    explicit_authorization_ref=AUTHORIZATION_REF,
                    allowed_fixture_hashes=frozenset({"sha256:" + "z" * 64}),
                    allowed_request_hashes=frozenset(
                        {request.metadata["cloud_request_binding_hash"]}
                    ),
                )

    async def test_permit_rejects_canonical_request_drift_before_http(self) -> None:
        calls = 0
        request = _request(stream=False)

        async def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(500)

        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "not-a-real-key"}):
            provider = DeepSeekCloudProvider(
                enabled=True,
                explicit_authorization_ref=AUTHORIZATION_REF,
                **_permit(request),
                transport=httpx.MockTransport(handler),
            )
        self.addAsyncCleanup(provider.aclose)
        changed = request.model_copy(
            update={
                "messages": (
                    *request.messages[:-1],
                    InferenceMessage(
                        role="user",
                        content_parts=(TextContentPart(text="Different synthetic question."),),
                        source_refs=("eval-fixture/case-a",),
                    ),
                )
            }
        )
        with self.assertRaises(ProviderInferenceError) as raised:
            await provider.generate(changed)
        self.assertEqual(raised.exception.code, "privacy_constraint_unsatisfied")
        self.assertEqual(calls, 0)

    async def test_capabilities_and_router_require_explicit_cloud_approval(self) -> None:
        request = _request(stream=False)
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "not-a-real-key"}):
            provider = DeepSeekCloudProvider(
                enabled=True,
                explicit_authorization_ref=AUTHORIZATION_REF,
                **_permit(request),
            )
        self.addAsyncCleanup(provider.aclose)
        capabilities = await provider.capabilities()
        self.assertEqual(capabilities.provider_id, DEEPSEEK_PROVIDER_ID)
        self.assertEqual(capabilities.provider_class, "cloud")
        self.assertEqual(capabilities.execution_environment, "cloud")
        self.assertEqual(capabilities.available_model_version_ids, (
            DEEPSEEK_MODEL_VERSION,
        ))
        self.assertEqual(capabilities.approved_privacy_classes, (PrivacyClass.PUBLIC,))
        with self.assertRaisesRegex(ProviderPolicyError, "explicit owner approval"):
            Stage1Router().decide(
                request_id=uuid.uuid4(),
                trace_id=uuid.uuid4().hex,
                policy=_policy(),
                capabilities=capabilities,
                required_output_tokens=96,
                required_streaming=True,
            )
        route = Stage1Router(
            approved_cloud_provider_ids=frozenset({DEEPSEEK_PROVIDER_ID})
        ).decide(
            request_id=uuid.uuid4(),
            trace_id=uuid.uuid4().hex,
            policy=_policy(),
            capabilities=capabilities,
            required_output_tokens=96,
            required_streaming=True,
        )
        self.assertEqual(route.selected_provider_id, DEEPSEEK_PROVIDER_ID)
        self.assertEqual(route.execution_environment, "cloud")

    async def test_generate_maps_canonical_request_without_special_prompt(self) -> None:
        observed: dict[str, object] = {}
        inference_request = _request(stream=False)

        async def handler(request: httpx.Request) -> httpx.Response:
            observed["authorization"] = request.headers.get("Authorization")
            observed["payload"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "id": "deepseek-request-a",
                    "model": DEEPSEEK_MODEL_ID,
                    "choices": [{
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "Synthetic answer."},
                    }],
                    "usage": {
                        "prompt_tokens": 20,
                        "completion_tokens": 5,
                        "total_tokens": 25,
                        "prompt_cache_hit_tokens": 12,
                        "prompt_cache_miss_tokens": 8,
                        "completion_tokens_details": {"reasoning_tokens": 0},
                    },
                },
            )

        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "not-a-real-key"}):
            provider = DeepSeekCloudProvider(
                enabled=True,
                explicit_authorization_ref=AUTHORIZATION_REF,
                **_permit(inference_request),
                thinking="disabled",
                transport=httpx.MockTransport(handler),
            )
        self.addAsyncCleanup(provider.aclose)
        response = await provider.generate(inference_request)
        self.assertEqual(response.output_parts[0].text, "Synthetic answer.")
        self.assertEqual(response.provider.provider_class, "cloud")
        self.assertEqual(response.usage.prompt_cache_hit_tokens, 12)
        self.assertEqual(response.usage.prompt_cache_miss_tokens, 8)
        payload = observed["payload"]
        self.assertEqual(payload["model"], DEEPSEEK_MODEL_ID)
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertEqual(payload["temperature"], 0.0)
        self.assertEqual(payload["top_p"], 1.0)
        self.assertEqual(payload["messages"], [
            {"role": "system", "content": "Synthetic identity."},
            {"role": "user", "content": "Synthetic question."},
        ])
        self.assertEqual(observed["authorization"], "Bearer not-a-real-key")

    async def test_every_non_public_or_ambiguous_policy_fails_before_http(self) -> None:
        calls = 0

        async def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(500)

        requests = [
            _request(stream=False, policy=_policy(PrivacyClass.NORMAL)),
            _request(stream=False, policy=_policy(PrivacyClass.PRIVATE)),
            _request(stream=False, policy=_policy(PrivacyClass.HIGHLY_PRIVATE)),
            _request(stream=False, policy=_policy(PrivacyClass.LOCAL_ONLY)),
            _request(
                stream=False,
                policy=DataPolicy.owner_default(PrivacyClass.PUBLIC),
            ),
            _request(stream=False, metadata={}),
        ]
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "not-a-real-key"}):
            provider = DeepSeekCloudProvider(
                enabled=True,
                explicit_authorization_ref=AUTHORIZATION_REF,
                **_permit(*requests),
                transport=httpx.MockTransport(handler),
            )
        self.addAsyncCleanup(provider.aclose)
        for request in requests:
            with self.subTest(policy=request.constraints.effective_data_policy):
                with self.assertRaises(ProviderInferenceError) as raised:
                    await provider.generate(request)
                self.assertEqual(
                    raised.exception.code, "privacy_constraint_unsatisfied"
                )
        self.assertEqual(calls, 0)

    async def test_thinking_stream_ignores_reasoning_content_and_records_ttft(self) -> None:
        inference_request = _request(stream=True, thinking="enabled")
        async def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            self.assertEqual(payload["thinking"], {"type": "enabled"})
            self.assertEqual(payload["reasoning_effort"], "high")
            self.assertNotIn("temperature", payload)
            self.assertNotIn("top_p", payload)
            chunks = [
                {
                    "id": "deepseek-stream-a",
                    "model": DEEPSEEK_MODEL_ID,
                    "choices": [{
                        "finish_reason": None,
                        "delta": {"reasoning_content": "private reasoning"},
                    }],
                    "usage": None,
                },
                {
                    "id": "deepseek-stream-a",
                    "model": DEEPSEEK_MODEL_ID,
                    "choices": [{
                        "finish_reason": None,
                        "delta": {"content": "Final "},
                    }],
                    "usage": None,
                },
                {
                    "id": "deepseek-stream-a",
                    "model": DEEPSEEK_MODEL_ID,
                    "choices": [{
                        "finish_reason": "stop",
                        "delta": {"content": "answer."},
                    }],
                    "usage": {
                        "prompt_tokens": 20,
                        "completion_tokens": 9,
                        "total_tokens": 29,
                        "prompt_cache_hit_tokens": 20,
                        "prompt_cache_miss_tokens": 0,
                        "completion_tokens_details": {"reasoning_tokens": 4},
                    },
                },
            ]
            body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
            body += "data: [DONE]\n\n"
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=body,
            )

        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "not-a-real-key"}):
            provider = DeepSeekCloudProvider(
                enabled=True,
                explicit_authorization_ref=AUTHORIZATION_REF,
                **_permit(inference_request),
                thinking="enabled",
                transport=httpx.MockTransport(handler),
            )
        self.addAsyncCleanup(provider.aclose)
        events = [event async for event in provider.stream(inference_request)]
        self.assertEqual(
            [event.event for event in events],
            ["response_started", "output_delta", "output_delta", "response_completed"],
        )
        response = events[-1].response
        self.assertEqual(response.output_parts[0].text, "Final answer.")
        self.assertNotIn("private reasoning", response.output_parts[0].text)
        self.assertIsNotNone(response.timing_ms.time_to_first_token)
        self.assertEqual(response.usage.reasoning_tokens, 4)


    async def test_thinking_stream_reports_empty_final_after_output_limit(self) -> None:
        inference_request = _request(stream=True, thinking="enabled")

        async def handler(_request: httpx.Request) -> httpx.Response:
            chunks = [
                {
                    "id": "deepseek-stream-empty",
                    "model": DEEPSEEK_MODEL_ID,
                    "choices": [{
                        "finish_reason": None,
                        "delta": {"reasoning_content": "private reasoning only"},
                    }],
                    "usage": None,
                },
                {
                    "id": "deepseek-stream-empty",
                    "model": DEEPSEEK_MODEL_ID,
                    "choices": [{
                        "finish_reason": "length",
                        "delta": {"content": None},
                    }],
                    "usage": {
                        "prompt_tokens": 20,
                        "completion_tokens": 96,
                        "total_tokens": 116,
                        "completion_tokens_details": {"reasoning_tokens": 96},
                    },
                },
            ]
            body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
            body += "data: [DONE]\n\n"
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"}, text=body
            )

        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "not-a-real-key"}):
            provider = DeepSeekCloudProvider(
                enabled=True,
                explicit_authorization_ref=AUTHORIZATION_REF,
                **_permit(inference_request),
                thinking="enabled",
                transport=httpx.MockTransport(handler),
            )
        self.addAsyncCleanup(provider.aclose)
        events = [event async for event in provider.stream(inference_request)]
        self.assertEqual(events[-1].event, "response_failed")
        failure = events[-1].failure
        self.assertEqual(
            failure.code, "content_blocked", failure.model_dump_json()
        )
        self.assertTrue(failure.retryable)
        self.assertEqual(
            failure.provider_error_code, "empty_final_content_output_limit"
        )
    async def test_provider_error_never_exposes_secret_or_response_body(self) -> None:
        secret = "not-a-real-key-should-never-escape"
        private_body = "private prompt and provider internals"
        inference_request = _request(stream=False)

        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, text=private_body)

        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": secret}):
            provider = DeepSeekCloudProvider(
                enabled=True,
                explicit_authorization_ref=AUTHORIZATION_REF,
                **_permit(inference_request),
                transport=httpx.MockTransport(handler),
            )
        self.addAsyncCleanup(provider.aclose)
        with self.assertRaises(ProviderInferenceError) as raised:
            await provider.generate(inference_request)
        rendered = str(raised.exception)
        self.assertNotIn(secret, rendered)
        self.assertNotIn(private_body, rendered)
        self.assertEqual(raised.exception.code, "provider_rate_limited")
        self.assertEqual(raised.exception.provider_error_code, "http_429")

    async def test_insufficient_balance_is_non_retryable_model_unavailable(self) -> None:
        inference_request = _request(stream=False)
        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(402, text="provider billing detail must stay private")

        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "not-a-real-key"}):
            provider = DeepSeekCloudProvider(
                enabled=True,
                explicit_authorization_ref=AUTHORIZATION_REF,
                **_permit(inference_request),
                transport=httpx.MockTransport(handler),
            )
        self.addAsyncCleanup(provider.aclose)
        with self.assertRaises(ProviderInferenceError) as raised:
            await provider.generate(inference_request)
        self.assertEqual(raised.exception.code, "model_unavailable")
        self.assertFalse(raised.exception.retryable)
        self.assertEqual(raised.exception.provider_error_code, "http_402")
        self.assertNotIn("billing detail", str(raised.exception))

    def test_extended_usage_details_remain_optional_and_bounded(self) -> None:
        legacy = TokenUsage(
            prompt_tokens=2,
            output_tokens=3,
            total_tokens=5,
            token_count_source="provider",
        )
        self.assertIsNone(legacy.prompt_cache_hit_tokens)
        with self.assertRaisesRegex(ValueError, "cache token detail"):
            TokenUsage(
                prompt_tokens=2,
                output_tokens=3,
                total_tokens=5,
                token_count_source="provider",
                prompt_cache_hit_tokens=2,
                prompt_cache_miss_tokens=1,
            )
        with self.assertRaisesRegex(ValueError, "reasoning token detail"):
            TokenUsage(
                prompt_tokens=2,
                output_tokens=3,
                total_tokens=5,
                token_count_source="provider",
                reasoning_tokens=4,
            )


    async def test_manual_owner_mode_requires_exact_bound_permit(self) -> None:
        calls = 0
        observed: dict[str, object] = {}
        disclosure_id = uuid.uuid4()
        policy = DataPolicy(
            privacy_class=PrivacyClass.HIGHLY_PRIVATE,
            memory_eligible=False,
            cloud_eligible=True,
            decision_source="owner_explicit",
            authorization_ref=OWNER_MANUAL_AUTHORIZATION_REF,
        )
        request = InferenceRequest(
            request_id=uuid.uuid4(),
            trace_id=uuid.uuid4().hex,
            messages=(
                InferenceMessage(
                    role="system",
                    content_parts=(TextContentPart(text="Selected owner context."),),
                    source_refs=("event/source-a",),
                ),
                InferenceMessage(
                    role="user",
                    content_parts=(TextContentPart(text="Rethink the prior reply."),),
                    source_refs=("event/source-b",),
                ),
            ),
            context_pack_id=uuid.uuid4(),
            generation=GenerationSettings(max_output_tokens=96, temperature=0, top_p=1),
            constraints=InferenceConstraints(
                stream=False, timeout_ms=30_000, effective_data_policy=policy,
                allowed_execution_environments=("cloud",),
            ),
            metadata={
                "cloud_authorization_ref": OWNER_MANUAL_AUTHORIZATION_REF,
                "cloud_data_boundary": OWNER_MANUAL_BOUNDARY,
                "cloud_disclosure_id": str(disclosure_id),
                "selected_content_hash": "sha256:" + "2" * 64,
            },
        )
        request = bind_cloud_experiment_request(
            request, thinking="enabled", reasoning_effort="high"
        )

        async def handler(http_request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            observed["payload"] = json.loads(http_request.content)
            return httpx.Response(200, json={
                "id": "manual-request-a",
                "model": DEEPSEEK_MODEL_ID,
                "choices": [{"finish_reason": "stop", "message": {
                    "role": "assistant", "content": "A more considered answer."
                }}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 6, "total_tokens": 18},
            })

        permit = lambda candidate: candidate.inference_request_id == request.inference_request_id
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "not-a-real-key"}):
            provider = DeepSeekCloudProvider(
                enabled=True,
                explicit_authorization_ref=OWNER_MANUAL_AUTHORIZATION_REF,
                mode="owner_manual",
                thinking="enabled",
                reasoning_effort="high",
                manual_permit_validator=permit,
                transport=httpx.MockTransport(handler),
            )
        self.addAsyncCleanup(provider.aclose)
        capabilities = await provider.capabilities()
        self.assertEqual(capabilities.approved_privacy_classes, (
            PrivacyClass.HIGHLY_PRIVATE,
        ))
        response = await provider.generate(request)
        self.assertEqual(response.output_parts[0].text, "A more considered answer.")
        self.assertEqual(observed["payload"]["user_id"], "havre-owner-manual-inference")
        self.assertEqual(calls, 1)
        changed = request.model_copy(update={
            "messages": (*request.messages[:-1], InferenceMessage(
                role="user",
                content_parts=(TextContentPart(text="Tampered owner content."),),
                source_refs=("event/source-b",),
            )),
        })
        with self.assertRaises(ProviderInferenceError) as raised:
            await provider.generate(changed)
        self.assertEqual(raised.exception.code, "privacy_constraint_unsatisfied")
        self.assertEqual(calls, 1)

if __name__ == "__main__":
    unittest.main()
