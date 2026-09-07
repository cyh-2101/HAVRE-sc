from __future__ import annotations

import json
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import httpx
import jsonschema
from pydantic import ValidationError

from companion.events import TextContentPart
from companion.hashing import content_hash
from companion.policy import DataPolicy, PrivacyClass
from mlsys.contracts import (
    GenerationSettings,
    InferenceMessage,
    InferenceRequest,
    InferenceResponseLineageError,
    InferenceStreamEvent,
    InferenceTiming,
    ProviderCapabilities,
    ProviderReference,
    ProviderVersion,
    RouteDecision,
    TokenUsage,
    VersionReferences,
    validate_inference_response_lineage,
)
from mlsys.contracts.inference import InferenceConstraints
from mlsys.serving import (
    DeterministicLocalProvider,
    OpenAICompatibleProvider,
    ProviderInferenceError,
    ProviderPolicyError,
    ProviderVersionError,
    RuntimeAttestation,
    Stage1Router,
)


class OpenAICompatibleProviderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.request = self._request(stream=False)
        liveness = patch(
            "mlsys.serving.openai_compatible.verify_attested_process_liveness"
        )
        liveness.start()
        self.addCleanup(liveness.stop)

    def test_stream_schema_exposes_the_exact_payload_discriminator(self) -> None:
        schema = InferenceStreamEvent.model_json_schema()
        variants = schema["allOf"][0]["oneOf"]
        by_event = {
            variant["properties"]["event"]["const"]: variant
            for variant in variants
        }

        self.assertEqual(set(by_event), {
            "response_started", "output_delta", "response_completed", "response_failed"
        })
        self.assertEqual(by_event["output_delta"]["required"], ["delta"])
        self.assertEqual(by_event["response_completed"]["required"], ["response"])
        self.assertEqual(by_event["response_failed"]["required"], ["failure"])
        self.assertEqual(
            by_event["response_started"]["properties"]["failure"],
            {"type": "null"},
        )
        base = {
            "schema_version": 1,
            "sequence_number": 0,
            "inference_response_id": str(uuid.uuid4()),
            "inference_request_id": str(uuid.uuid4()),
            "request_id": str(uuid.uuid4()),
            "trace_id": "1" * 32,
            "delta": None,
            "response": None,
            "failure": None,
            "created_at": datetime.now(UTC).isoformat(),
        }
        jsonschema.validate({**base, "event": "response_started"}, schema)
        for event, field in (
            ("output_delta", "delta"),
            ("response_completed", "response"),
            ("response_failed", "failure"),
        ):
            with self.subTest(event=event), self.assertRaises(
                jsonschema.ValidationError
            ):
                jsonschema.validate({**base, "event": event, field: None}, schema)

    async def test_non_streaming_normalizes_versions_usage_and_unknown_timings(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/v1/chat/completions")
            self.assertIsNone(request.headers.get("authorization"))
            payload = json.loads(request.content)
            self.assertEqual(payload["model"], "transport-model")
            self.assertFalse(payload["stream"])
            self.assertEqual(payload["messages"][0]["content"][0]["text"], "Help me.")
            self.assertEqual(
                payload["chat_template_kwargs"], {"enable_thinking": False}
            )
            self.assertEqual(payload["reasoning_effort"], "none")
            return httpx.Response(
                200,
                json={
                    "id": "provider-request-1",
                    "model": "transport-model",
                    "choices": [{
                        "message": {"role": "assistant", "content": "One grounded step."},
                        "finish_reason": "stop",
                    }],
                    "usage": {
                        "prompt_tokens": 3,
                        "completion_tokens": 4,
                        "total_tokens": 7,
                    },
                },
            )

        provider = self._provider(handler)
        response = await provider.generate(self.request)
        self.assertEqual(response.output_parts[0].text, "One grounded step.")
        self.assertEqual(response.provider.provider_class, "self_hosted")
        self.assertEqual(response.versions.model_version_id, "havre-model-v1")
        self.assertEqual(
            response.versions.provider_adapter_version_id,
            "openai-compatible-provider-adapter-v1",
        )
        self.assertEqual(response.versions.serving_engine, "vllm")
        self.assertIsNone(response.timing_ms.queue)
        self.assertIsNone(response.timing_ms.time_to_first_token)
        self.assertEqual(response.usage.total_tokens, 7)

    async def test_stream_is_typed_ordered_and_carries_authoritative_response(self) -> None:
        chunks = [
            {
                "id": "provider-stream-1",
                "model": "transport-model",
                "choices": [{"delta": {"content": "One "}, "finish_reason": None}],
            },
            {
                "id": "provider-stream-1",
                "model": "transport-model",
                "choices": [{"delta": {"content": "step."}, "finish_reason": None}],
            },
            {
                "id": "provider-stream-1",
                "model": "transport-model",
                "choices": [{"delta": {}, "finish_reason": "stop"}],
            },
            {
                "id": "provider-stream-1",
                "model": "transport-model",
                "choices": [],
                "usage": {
                    "prompt_tokens": 3,
                    "completion_tokens": 2,
                    "total_tokens": 5,
                },
            },
        ]
        body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
        body += "data: [DONE]\n\n"

        async def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            self.assertTrue(payload["stream"])
            self.assertTrue(payload["stream_options"]["include_usage"])
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=body,
            )

        provider = self._provider(handler)
        events = [
            event async for event in provider.stream(self._request(stream=True))
        ]
        self.assertEqual(
            [event.event for event in events],
            [
                "response_started",
                "output_delta",
                "output_delta",
                "response_completed",
            ],
        )
        self.assertEqual(
            [event.sequence_number for event in events], list(range(len(events)))
        )
        final = events[-1].response
        self.assertIsNotNone(final)
        self.assertEqual(final.output_parts[0].text, "One step.")
        self.assertEqual(final.usage.output_tokens, 2)
        self.assertIsNotNone(final.timing_ms.time_to_first_token)

    async def test_llama_cpp_terminal_usage_and_timings_are_accepted(self) -> None:
        fingerprint = "b10405-e79e4bf"
        chunks = [
            {
                "id": "llama-stream-1",
                "model": "transport-model",
                "system_fingerprint": fingerprint,
                "choices": [
                    {"delta": {"content": "Grounded."}, "finish_reason": None}
                ],
            },
            {
                "id": "llama-stream-1",
                "model": "transport-model",
                "system_fingerprint": fingerprint,
                "choices": [{"delta": {}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": 3,
                    "completion_tokens": 2,
                    "total_tokens": 5,
                    "prompt_tokens_details": {"cached_tokens": 1},
                },
                "timings": {
                    "prompt_n": 2,
                    "prompt_ms": 10.0,
                    "predicted_n": 2,
                    "predicted_ms": 42.5,
                },
            },
        ]
        body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
        body += "data: [DONE]\n\n"

        async def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            self.assertFalse(payload["chat_template_kwargs"]["enable_thinking"])
            self.assertEqual(payload["reasoning_effort"], "none")
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=body,
            )

        provider = self._provider(
            handler,
            serving_engine="llama.cpp",
            serving_engine_version="b10405",
            expected_build_substring=fingerprint,
        )
        events = [
            event async for event in provider.stream(self._request(stream=True))
        ]
        self.assertEqual(events[-1].event, "response_completed")
        self.assertEqual(events[-1].response.timing_ms.generation, 42.5)
        self.assertEqual(events[-1].response.usage.total_tokens, 5)

    async def test_broken_stream_yields_safe_typed_failure(self) -> None:
        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=(
                    'data: {"id":"p1","model":"transport-model",'
                    '"choices":[{"delta":{"content":"partial"},'
                    '"finish_reason":null}]}\n\n'
                ),
            )

        provider = self._provider(handler)
        events = [
            event async for event in provider.stream(self._request(stream=True))
        ]
        self.assertEqual(events[-1].event, "response_failed")
        self.assertEqual(events[-1].failure.code, "stream_interrupted")
        self.assertTrue(events[-1].failure.retryable)
        self.assertNotIn("partial", events[-1].failure.safe_message)

    async def test_transport_reset_after_delta_is_stream_interrupted(self) -> None:
        class ResetAfterDelta(httpx.AsyncByteStream):
            async def __aiter__(self):
                chunk = {
                    "id": "reset-stream-1",
                    "model": "transport-model",
                    "choices": [
                        {"delta": {"content": "partial"}, "finish_reason": None}
                    ],
                }
                yield f"data: {json.dumps(chunk)}\n\n".encode()
                raise httpx.ReadError("private tcp reset details")

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=ResetAfterDelta(),
                request=request,
            )

        provider = self._provider(handler)
        events = [
            event async for event in provider.stream(self._request(stream=True))
        ]
        self.assertEqual(
            [event.event for event in events],
            ["response_started", "output_delta", "response_failed"],
        )
        self.assertEqual(events[-1].failure.code, "stream_interrupted")
        self.assertTrue(events[-1].failure.retryable)
        self.assertNotIn("tcp reset", events[-1].failure.safe_message)

    async def test_oversized_delta_is_nonretryable_protocol_failure(self) -> None:
        chunk = {
            "id": "oversized-stream-1",
            "model": "transport-model",
            "choices": [
                {"delta": {"content": "x" * 100_001}, "finish_reason": None}
            ],
        }

        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n",
            )

        provider = self._provider(handler)
        events = [
            event async for event in provider.stream(self._request(stream=True))
        ]
        self.assertEqual(events[-1].event, "response_failed")
        self.assertEqual(events[-1].failure.code, "provider_protocol_error")
        self.assertFalse(events[-1].failure.retryable)

    async def test_status_mapping_does_not_expose_provider_body(self) -> None:
        secret_body = "raw-secret-provider-body"

        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, text=secret_body)

        provider = self._provider(handler)
        with self.assertRaises(ProviderInferenceError) as raised:
            await provider.generate(self.request)
        self.assertEqual(raised.exception.code, "provider_rate_limited")
        self.assertTrue(raised.exception.retryable)
        self.assertEqual(raised.exception.provider_status_code, 429)
        self.assertNotIn(secret_body, str(raised.exception))

    async def test_stream_http_failure_preserves_order_and_typed_code(self) -> None:
        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, text="private provider details")

        provider = self._provider(handler)
        events = [
            event async for event in provider.stream(self._request(stream=True))
        ]

        self.assertEqual(
            [event.event for event in events],
            ["response_started", "response_failed"],
        )
        self.assertEqual([event.sequence_number for event in events], [0, 1])
        self.assertEqual(events[-1].failure.code, "provider_rate_limited")
        self.assertTrue(events[-1].failure.retryable)

    async def test_stream_preflight_failure_is_an_ordered_typed_stream(self) -> None:
        calls = 0

        async def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(500)

        provider = self._provider(handler)
        unsafe = self._request(stream=True).model_copy(
            update={
                "constraints": self._request(stream=True).constraints.model_copy(
                    update={"allowed_execution_environments": ("cloud",)}
                )
            }
        )
        events = [event async for event in provider.stream(unsafe)]

        self.assertEqual(
            [event.event for event in events],
            ["response_started", "response_failed"],
        )
        self.assertEqual(
            events[-1].failure.code, "privacy_constraint_unsatisfied"
        )
        self.assertEqual(calls, 0)

    async def test_llama_cpp_context_limit_400_is_typed_separately(self) -> None:
        async def context_handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "code": 400,
                        "type": "invalid_request_error",
                        "message": "the prompt exceeds the available context size",
                    }
                },
            )

        provider = self._provider(context_handler)
        with self.assertRaises(ProviderInferenceError) as raised:
            await provider.generate(self.request)
        self.assertEqual(raised.exception.code, "context_limit_exceeded")

        async def generic_handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                400,
                json={"error": {"message": "temperature is invalid"}},
            )

        generic = self._provider(generic_handler)
        with self.assertRaises(ProviderInferenceError) as generic_raised:
            await generic.generate(self.request)
        self.assertEqual(generic_raised.exception.code, "invalid_request")

    async def test_transport_timeout_is_a_retryable_typed_failure(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("provider internals must stay private", request=request)

        provider = self._provider(handler)
        with self.assertRaises(ProviderInferenceError) as raised:
            await provider.generate(self.request)
        self.assertEqual(raised.exception.code, "provider_timeout")
        self.assertTrue(raised.exception.retryable)
        self.assertIsNone(raised.exception.provider_status_code)
        self.assertNotIn("provider internals", str(raised.exception))

    async def test_unread_streaming_http_error_keeps_context_limit_code(self) -> None:
        class ErrorBody(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'{"error":{"type":"exceed_context_size_error","message":"request (4692 tokens) exceeds the available context size (4096 tokens)"}}'
        async def handler(_request):
            return httpx.Response(400, stream=ErrorBody())
        provider = self._provider(handler)
        events = [event async for event in provider.stream(self._request(stream=True))]
        self.assertEqual(events[-1].event, 'response_failed')
        self.assertEqual(events[-1].failure.code, 'context_limit_exceeded')
        self.assertNotIn('4692', events[-1].failure.safe_message)

    async def test_injected_http_client_is_not_closed_by_provider(self) -> None:
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
            trust_env=False,
            follow_redirects=False,
        )
        provider = OpenAICompatibleProvider(
            base_url="http://127.0.0.1:9000",
            transport_model_id="transport-model",
            model_version_id="havre-model-v1",
            tokenizer_version_id="tokenizer-v1",
            serving_engine="vllm",
            serving_engine_version="vllm-v1",
            serving_config_version="serving-config-v1",
            client=client,
        )
        await provider.aclose()
        self.assertFalse(client.is_closed)
        await client.aclose()

    def test_owned_http_client_disables_environment_and_redirects(self) -> None:
        provider = self._provider(lambda _request: httpx.Response(500))
        self.assertFalse(provider._client.follow_redirects)

    async def test_redirect_is_rejected_without_following_location(self) -> None:
        seen: list[str] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(
                307, headers={"location": "https://outside.example/v1/chat/completions"}
            )

        provider = self._provider(handler)
        with self.assertRaises(ProviderInferenceError) as raised:
            await provider.generate(self.request)
        self.assertEqual(raised.exception.provider_error_code, "redirect_forbidden")
        self.assertEqual(len(seen), 1)

    async def test_local_environment_and_privacy_are_enforced_inside_adapter(self) -> None:
        calls = 0

        async def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(500)

        provider = self._provider(handler)
        unsafe = self.request.model_copy(update={
            "constraints": self.request.constraints.model_copy(update={
                "allowed_execution_environments": ("cloud",)
            })
        })
        with self.assertRaises(ProviderInferenceError) as raised:
            await provider.generate(unsafe)
        self.assertEqual(raised.exception.code, "privacy_constraint_unsatisfied")
        self.assertEqual(calls, 0)

    async def test_traceparent_must_belong_to_the_canonical_request_trace(self) -> None:
        calls = 0

        async def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(500)

        request = self.request.model_copy(update={
            "metadata": {
                "traceparent": f"00-{uuid.uuid4().hex}-0123456789abcdef-01"
            }
        })
        provider = self._provider(handler)
        with self.assertRaises(ProviderInferenceError) as raised:
            await provider.generate(request)
        self.assertEqual(raised.exception.code, "invalid_request")
        self.assertEqual(calls, 0)

    async def test_health_and_version_fail_closed_on_exact_version_mismatch(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/health":
                return httpx.Response(200, json={"status": "ok"})
            if request.url.path == "/version":
                return httpx.Response(200, json={
                    "serving_engine": "vllm",
                    "serving_engine_version": "wrong-version",
                })
            return httpx.Response(200, json={"data": [{"id": "transport-model"}]})

        provider = self._provider(handler)
        health = await provider.health()
        self.assertEqual(health.status, "unavailable")
        self.assertIn("version_mismatch", health.reasons)
        with self.assertRaisesRegex(RuntimeError, "version mismatch"):
            await provider.version()

    async def test_llama_cpp_props_verifies_configured_build_substring(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v1/models":
                return httpx.Response(200, json={"data": [{"id": "transport-model"}]})
            self.assertEqual(request.url.path, "/props")
            return httpx.Response(
                200,
                json={
                    "build_info": "b10405-e79e4bf",
                    "model_path": "ignored-local-path.gguf",
                },
            )

        provider = self._provider(
            handler,
            serving_engine="llama.cpp",
            serving_engine_version="b10405",
            expected_build_substring="b10405-e79e4bf",
            version_path="/props",
        )
        version = await provider.version()
        self.assertEqual(version.serving_engine_version, "b10405")

        mismatched = self._provider(
            handler,
            serving_engine="llama.cpp",
            serving_engine_version="b10405",
            expected_build_substring="b10405-deadbeef",
            version_path="/props",
        )
        with self.assertRaisesRegex(RuntimeError, "version mismatch"):
            await mismatched.version()

    async def test_version_transport_failure_is_retryable_model_unavailable(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("private local transport detail", request=request)

        provider = self._provider(handler)
        with self.assertRaises(ProviderVersionError) as raised:
            await provider.version()
        self.assertEqual(raised.exception.code, "model_unavailable")
        self.assertTrue(raised.exception.retryable)
        self.assertNotIn("private local transport detail", str(raised.exception))

    async def test_health_200_cannot_replace_process_bound_attestation(self) -> None:
        calls = 0

        async def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, json={"status": "ok"})

        provider = OpenAICompatibleProvider(
            base_url="http://127.0.0.1:9000",
            transport_model_id="transport-model",
            model_version_id="havre-model-v1",
            tokenizer_version_id="tokenizer-v1",
            serving_engine="vllm",
            serving_engine_version="vllm-v1",
            serving_config_version="serving-config-v1",
            transport=httpx.MockTransport(handler),
        )
        self.addAsyncCleanup(provider.aclose)
        with self.assertRaises(ProviderVersionError) as raised:
            await provider.version()
        self.assertEqual(raised.exception.code, "provider_protocol_error")
        self.assertFalse(raised.exception.retryable)
        self.assertEqual(calls, 0)

    async def test_direct_generate_without_attestation_fails_before_http(self) -> None:
        calls = 0

        async def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, json={})

        provider = self._provider_without_attestation(handler)
        with self.assertRaises(ProviderInferenceError) as raised:
            await provider.generate(self._request(stream=False))
        self.assertEqual(raised.exception.code, "provider_protocol_error")
        self.assertFalse(raised.exception.retryable)
        self.assertEqual(calls, 0)

    async def test_direct_stream_without_attestation_fails_before_http(self) -> None:
        calls = 0

        async def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, json={})

        provider = self._provider_without_attestation(handler)
        events = [
            event async for event in provider.stream(self._request(stream=True))
        ]
        self.assertEqual([event.event for event in events], [
            "response_started", "response_failed"
        ])
        self.assertEqual(events[-1].failure.code, "provider_protocol_error")
        self.assertFalse(events[-1].failure.retryable)
        self.assertEqual(calls, 0)

    def test_self_hosted_provider_version_requires_attestation(self) -> None:
        with self.assertRaisesRegex(
            ValidationError, "self-hosted provider version requires runtime attestation"
        ):
            ProviderVersion(
                provider_id="self-hosted-openai-compatible",
                provider_class="self_hosted",
                execution_environment="local",
                provider_adapter_version_id="adapter-v1",
                serving_engine="llama.cpp",
                serving_engine_version="b10405",
                serving_config_version="serving-v1",
                model_version_id="model-v1",
                tokenizer_version_id="tokenizer-v1",
                model_artifact_hash="sha256:" + "1" * 64,
            )

    async def test_live_model_alias_mismatch_is_nonretryable_protocol_failure(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/version":
                return httpx.Response(
                    200,
                    json={
                        "serving_engine": "vllm",
                        "serving_engine_version": "vllm-v1",
                    },
                )
            return httpx.Response(200, json={"data": [{"id": "wrong-model"}]})

        provider = self._provider(handler)
        with self.assertRaises(ProviderVersionError) as raised:
            await provider.version()
        self.assertEqual(raised.exception.code, "provider_protocol_error")
        self.assertFalse(raised.exception.retryable)

    def test_matching_build_and_alias_cannot_override_wrong_model_hash(self) -> None:
        settings = {
            "base_url": "http://127.0.0.1:9000",
            "transport_model_id": "transport-model",
            "model_version_id": "havre-model-v1",
            "tokenizer_version_id": "tokenizer-v1",
            "serving_engine": "vllm",
            "serving_engine_version": "vllm-v1",
            "serving_config_version": "serving-config-v1",
            "model_artifact_hash": "sha256:" + "9" * 64,
            "transport": httpx.MockTransport(lambda _request: httpx.Response(200)),
        }
        attested_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        payload = {
            "schema_version": 1,
            "attestation_id": "wrong-model-runtime:4242:1",
            "runtime_state_hash": "sha256:" + "1" * 64,
            "engine_manifest_hash": "sha256:" + "2" * 64,
            "model_manifest_hash": "sha256:" + "3" * 64,
            "server_executable_hash": "sha256:" + "4" * 64,
            "server_executable_path_hash": "sha256:" + "5" * 64,
            "process_executable_hash": "sha256:" + "4" * 64,
            "model_artifact_hash": "sha256:" + "6" * 64,
            "model_path_hash": "sha256:" + "7" * 64,
            "model_size_bytes": 1,
            "server_pid": 4242,
            "process_started_at": attested_at,
            "launch_arguments_hash": "sha256:" + "8" * 64,
            "base_url": settings["base_url"],
            "serving_engine": settings["serving_engine"],
            "serving_engine_version": settings["serving_engine_version"],
            "serving_config_version": settings["serving_config_version"],
            "model_version_id": settings["model_version_id"],
            "tokenizer_version_id": settings["tokenizer_version_id"],
            "loaded_model_alias": settings["transport_model_id"],
            "loopback_only": True,
            "request_logging_disabled": True,
            "web_ui_disabled": True,
            "attested_at": attested_at,
        }
        attestation = RuntimeAttestation.model_validate(
            {**payload, "attestation_hash": content_hash(payload)}
        )
        with self.assertRaisesRegex(ValueError, "attestation does not match"):
            OpenAICompatibleProvider(**settings, runtime_attestation=attestation)

    async def test_deterministic_provider_stream_conforms_to_typed_contract(self) -> None:
        provider = DeterministicLocalProvider()
        request = self._request(stream=False)
        events = [
            event async for event in provider.stream(
                request.model_copy(update={
                    "constraints": request.constraints.model_copy(update={"stream": True})
                })
            )
        ]
        self.assertTrue(all(isinstance(event, InferenceStreamEvent) for event in events))
        self.assertEqual(events[-1].event, "response_completed")
        self.assertEqual(
            events[-1].response.versions.provider_adapter_version_id,
            provider.provider_adapter_version_id,
        )

    def test_plain_http_is_loopback_only(self) -> None:
        with self.assertRaisesRegex(ValueError, "loopback-only"):
            OpenAICompatibleProvider(
                base_url="http://model.example",
                transport_model_id="transport-model",
                model_version_id="havre-model-v1",
                tokenizer_version_id="tokenizer-v1",
                serving_engine="vllm",
                serving_engine_version="vllm-v1",
                serving_config_version="serving-config-v1",
            )

    def test_remote_https_is_never_classified_as_local_in_stage3(self) -> None:
        settings = {
            "base_url": "https://outside.example",
            "transport_model_id": "transport-model",
            "model_version_id": "havre-model-v1",
            "tokenizer_version_id": "tokenizer-v1",
            "serving_engine": "vllm",
            "serving_engine_version": "vllm-v1",
            "serving_config_version": "serving-config-v1",
            "transport": httpx.MockTransport(lambda _request: httpx.Response(500)),
        }
        with self.assertRaisesRegex(ValueError, "loopback-only"):
            OpenAICompatibleProvider(**settings)

        settings["base_url"] = "http://localhost:9000"
        with self.assertRaisesRegex(ValueError, "loopback-only"):
            OpenAICompatibleProvider(**settings)

    def test_response_lineage_rejects_spoofed_request_provider_and_model(self) -> None:
        request = self.request
        response = self._normalized_response(request)
        for spoofed in (
            response.model_copy(update={"request_id": uuid.uuid4()}),
            response.model_copy(update={
                "provider": response.provider.model_copy(update={"provider_id": "other"})
            }),
            response.model_copy(update={
                "versions": response.versions.model_copy(update={
                    "model_version_id": "other-model"
                })
            }),
        ):
            with self.subTest(spoofed=spoofed.model_dump(mode="json")):
                with self.assertRaises(InferenceResponseLineageError):
                    validate_inference_response_lineage(
                        request=request,
                        response=spoofed,
                        expected_provider_id="self-hosted-openai-compatible",
                        expected_provider_class="self_hosted",
                        expected_model_version_id="havre-model-v1",
                        expected_adapter_version_id=None,
                        expected_provider_adapter_version_id=(
                            "openai-compatible-provider-adapter-v1"
                        ),
                    )

    def test_self_hosted_response_lineage_requires_attestation(self) -> None:
        with self.assertRaisesRegex(
            InferenceResponseLineageError, "runtime_attestation"
        ):
            validate_inference_response_lineage(
                request=self.request,
                response=self._normalized_response(self.request),
                expected_provider_id="self-hosted-openai-compatible",
                expected_provider_class="self_hosted",
                expected_model_version_id="havre-model-v1",
                expected_adapter_version_id=None,
                expected_provider_adapter_version_id=(
                    "openai-compatible-provider-adapter-v1"
                ),
            )

    def test_legacy_v1_response_remains_parseable_but_not_stage3_eligible(self) -> None:
        from mlsys.contracts import InferenceResponse

        request = self.request
        legacy_payload = self._normalized_response(request).model_dump(mode="json")
        legacy_payload["versions"].pop("provider_adapter_version_id")
        legacy_payload["versions"].pop("serving_engine")
        legacy_payload["versions"].pop("serving_engine_version")
        parsed = InferenceResponse.model_validate(legacy_payload)
        self.assertEqual(parsed.schema_version, 1)
        self.assertIsNone(parsed.versions.provider_adapter_version_id)
        with self.assertRaises(InferenceResponseLineageError):
            validate_inference_response_lineage(
                request=request,
                response=parsed,
                expected_provider_id="self-hosted-openai-compatible",
                expected_provider_class="self_hosted",
                expected_model_version_id="havre-model-v1",
                expected_adapter_version_id=None,
                expected_provider_adapter_version_id=(
                    "openai-compatible-provider-adapter-v1"
                ),
            )

    def test_token_usage_and_stream_payload_invariants_fail_closed(self) -> None:
        with self.assertRaises(ValidationError):
            TokenUsage(
                prompt_tokens=2,
                output_tokens=3,
                total_tokens=99,
                token_count_source="provider",
            )
        with self.assertRaises(ValidationError):
            InferenceTiming(total=float("nan"))
        request = self.request
        with self.assertRaises(ValidationError):
            InferenceStreamEvent(
                event="output_delta",
                sequence_number=0,
                inference_response_id=uuid.uuid4(),
                inference_request_id=request.inference_request_id,
                request_id=request.request_id,
                trace_id=request.trace_id,
            )

    def test_single_provider_router_v2_rejects_stale_and_undersized_capabilities(self) -> None:
        policy = DataPolicy.owner_default(PrivacyClass.LOCAL_ONLY)
        capabilities = ProviderCapabilities(
            provider_id="local-a",
            provider_class="self_hosted",
            execution_environment="local",
            available_model_version_ids=("model-v1",),
            approved_privacy_classes=(PrivacyClass.LOCAL_ONLY,),
            supports_streaming=True,
            max_context_tokens=8_192,
            max_output_tokens=128,
            observed_at=datetime.now(UTC),
            ttl_seconds=30,
        )
        router = Stage1Router()
        route = router.decide(
            request_id=uuid.uuid4(),
            trace_id=uuid.uuid4().hex,
            policy=policy,
            capabilities=capabilities,
            required_input_tokens=8_000,
            required_output_tokens=128,
            required_streaming=True,
        )
        self.assertEqual(route.router_version, "single-provider-router-v2")
        self.assertEqual(route.reason, "only_eligible_configured_provider")

        with self.assertRaisesRegex(ProviderPolicyError, "maximum output"):
            router.decide(
                request_id=uuid.uuid4(),
                trace_id=uuid.uuid4().hex,
                policy=policy,
                capabilities=capabilities,
                required_output_tokens=129,
            )
        with self.assertRaisesRegex(ProviderPolicyError, "context window"):
            router.decide(
                request_id=uuid.uuid4(),
                trace_id=uuid.uuid4().hex,
                policy=policy,
                capabilities=capabilities,
                required_input_tokens=8_100,
                required_output_tokens=128,
            )
        with self.assertRaisesRegex(ProviderPolicyError, "required streaming"):
            router.decide(
                request_id=uuid.uuid4(),
                trace_id=uuid.uuid4().hex,
                policy=policy,
                capabilities=capabilities.model_copy(
                    update={"supports_streaming": False}
                ),
                required_streaming=True,
            )
        with self.assertRaisesRegex(ProviderPolicyError, "stale"):
            router.decide(
                request_id=uuid.uuid4(),
                trace_id=uuid.uuid4().hex,
                policy=policy,
                capabilities=capabilities.model_copy(update={
                    "observed_at": datetime.now(UTC) - timedelta(seconds=31)
                }),
            )

        legacy_payload = route.model_dump(mode="json")
        legacy_payload["router_version"] = "stage1-single-provider-router-v1"
        legacy_payload["reason"] = "only_eligible_stage1_provider"
        legacy = RouteDecision.model_validate(legacy_payload)
        self.assertEqual(legacy.router_version, "stage1-single-provider-router-v1")

    def _provider(self, handler, **overrides) -> OpenAICompatibleProvider:
        settings = {
            "base_url": "http://127.0.0.1:9000",
            "transport_model_id": "transport-model",
            "model_version_id": "havre-model-v1",
            "tokenizer_version_id": "tokenizer-v1",
            "serving_engine": "vllm",
            "serving_engine_version": "vllm-v1",
            "serving_config_version": "serving-config-v1",
            "model_artifact_hash": "sha256:" + "1" * 64,
            "transport": httpx.MockTransport(handler),
        }
        settings.update(overrides)
        attested_at = datetime.now(UTC)
        attestation_payload = {
            "schema_version": 1,
            "attestation_id": "test-runtime:4242:1",
            "runtime_state_hash": "sha256:" + "2" * 64,
            "engine_manifest_hash": "sha256:" + "3" * 64,
            "model_manifest_hash": "sha256:" + "4" * 64,
            "server_executable_hash": "sha256:" + "5" * 64,
            "server_executable_path_hash": "sha256:" + "7" * 64,
            "process_executable_hash": "sha256:" + "5" * 64,
            "model_artifact_hash": settings["model_artifact_hash"],
            "model_path_hash": "sha256:" + "8" * 64,
            "model_size_bytes": 1,
            "server_pid": 4242,
            "process_started_at": attested_at.isoformat().replace("+00:00", "Z"),
            "launch_arguments_hash": "sha256:" + "6" * 64,
            "base_url": settings["base_url"],
            "serving_engine": settings["serving_engine"],
            "serving_engine_version": settings["serving_engine_version"],
            "serving_config_version": settings["serving_config_version"],
            "model_version_id": settings["model_version_id"],
            "tokenizer_version_id": settings["tokenizer_version_id"],
            "loaded_model_alias": settings["transport_model_id"],
            "loopback_only": True,
            "request_logging_disabled": True,
            "web_ui_disabled": True,
            "attested_at": attested_at.isoformat().replace("+00:00", "Z"),
        }
        settings["runtime_attestation"] = RuntimeAttestation.model_validate(
            {
                **attestation_payload,
                "attestation_hash": content_hash(attestation_payload),
            }
        )
        provider = OpenAICompatibleProvider(
            **settings,
        )
        self.addAsyncCleanup(provider.aclose)
        return provider

    def _provider_without_attestation(self, handler) -> OpenAICompatibleProvider:
        provider = OpenAICompatibleProvider(
            base_url="http://127.0.0.1:9000",
            transport_model_id="transport-model",
            model_version_id="havre-model-v1",
            tokenizer_version_id="tokenizer-v1",
            serving_engine="vllm",
            serving_engine_version="vllm-v1",
            serving_config_version="serving-config-v1",
            model_artifact_hash="sha256:" + "1" * 64,
            transport=httpx.MockTransport(handler),
        )
        self.addAsyncCleanup(provider.aclose)
        return provider

    @staticmethod
    def _request(*, stream: bool) -> InferenceRequest:
        return InferenceRequest(
            request_id=uuid.uuid4(),
            trace_id=uuid.uuid4().hex,
            messages=(InferenceMessage(
                role="user",
                content_parts=(TextContentPart(text="Help me."),),
                source_refs=("event/test",),
            ),),
            context_pack_id=uuid.uuid4(),
            generation=GenerationSettings(
                max_output_tokens=64, temperature=0.4, top_p=1.0
            ),
            constraints=InferenceConstraints(
                stream=stream,
                timeout_ms=20_000,
                effective_data_policy=DataPolicy.owner_default(PrivacyClass.LOCAL_ONLY),
                allowed_execution_environments=("local",),
            ),
            metadata={},
        )

    @staticmethod
    def _normalized_response(request: InferenceRequest):
        from mlsys.contracts import InferenceResponse

        return InferenceResponse(
            inference_request_id=request.inference_request_id,
            request_id=request.request_id,
            trace_id=request.trace_id,
            output_parts=(TextContentPart(text="Answer"),),
            finish_reason="stop",
            provider=ProviderReference(
                provider_id="self-hosted-openai-compatible",
                provider_request_id="provider-request",
                provider_class="self_hosted",
            ),
            versions=VersionReferences(
                model_version_id="havre-model-v1",
                adapter_version_id=None,
                tokenizer_version_id="tokenizer-v1",
                serving_config_version="serving-config-v1",
                provider_adapter_version_id=(
                    "openai-compatible-provider-adapter-v1"
                ),
                serving_engine="vllm",
                serving_engine_version="vllm-v1",
            ),
            usage=TokenUsage(
                prompt_tokens=1,
                output_tokens=1,
                total_tokens=2,
                token_count_source="provider",
            ),
            timing_ms=InferenceTiming(total=1.0),
            created_at=datetime.now(UTC),
        )


if __name__ == "__main__":
    unittest.main()
