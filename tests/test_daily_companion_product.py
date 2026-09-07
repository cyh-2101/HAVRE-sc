from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
import shutil
import subprocess
import time
import threading
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from fastapi.testclient import TestClient

from companion.application import InteractionCommand, InteractionService
from companion.context import ContextBuilder, render_inference_messages
from companion.identity import IdentityLoader
from companion.memory import DeterministicEmbeddingProvider
from companion.persistence import PostgresRepository, Stage10PostgresStore, apply_migrations
from companion.persistence.proactive import ProactivePostgresStore
from companion.policy import DataPolicy, PrivacyClass
from companion.product import (
    DailyCompanionStore,
    ManualStrongBrainService,
    WebPushDeliveryProvider,
)
from companion.product.daily import validate_web_push_endpoint
from companion.product.strong import (
    MANUAL_STRONG_RESERVED_OUTPUT_TOKENS,
)
from companion.proactive import InterruptionOutcome, ProactivePreferenceRevision
from mlsys.retrieval.service import RetrievalService
from mlsys.serving import DeepSeekCloudProvider, DeterministicLocalProvider, Stage1Router
from mlsys.serving.deepseek_cloud import (
    DEEPSEEK_MODEL_ID,
    DEEPSEEK_PROVIDER_ID,
    OWNER_MANUAL_AUTHORIZATION_REF,
)
from services.api.app import _course_task_type, _reply_routes_settings, create_app
from services.api.settings import Settings


ROOT = Path(__file__).resolve().parents[1]
DATABASE_URL = os.getenv("HAVRE_TEST_DATABASE_URL")


class DailyCompanionPwaAssetsTests(unittest.TestCase):
    def test_course_task_grouping_executes_for_real_projection_titles(self) -> None:
        self.assertEqual(_course_task_type("ECE 385 Midterm 1"), "exam")
        self.assertEqual(_course_task_type("CS 444 Homework 2"), "assignment")

    def test_reply_route_settings_never_fabricate_a_local_provider(self) -> None:
        cloud = SimpleNamespace(
            provider_id="cloud-test",
            model_version_id="cloud-model",
            execution_environment="cloud",
            active_adapter_version_id=None,
        )
        without_local = _reply_routes_settings(
            provider_version=cloud,
            local_version=None,
        )
        self.assertEqual(
            without_local["default"]["privacy_classes"],
            ("PUBLIC", "NORMAL"),
        )
        self.assertFalse(without_local["local_only_available"])
        self.assertIsNone(without_local["local_only"])
        self.assertFalse(without_local["silent_cross_provider_fallback"])

        mislabeled_local = _reply_routes_settings(
            provider_version=cloud,
            local_version=cloud,
        )
        self.assertFalse(mislabeled_local["local_only_available"])
        self.assertIsNone(mislabeled_local["local_only"])

        local = SimpleNamespace(
            provider_id="self-hosted-openai-compatible",
            model_version_id="model-qwen3-8b-gguf-q4-k-m-7c41481f",
            execution_environment="local",
            active_adapter_version_id=None,
        )
        dual = _reply_routes_settings(
            provider_version=cloud,
            local_version=local,
        )
        self.assertTrue(dual["local_only_available"])
        self.assertEqual(dual["local_only"]["execution_environment"], "local")
        self.assertEqual(dual["local_only"]["label"], "Qwen3-8B Base")
        self.assertIn("LOCAL_ONLY", dual["local_only"]["privacy_classes"])

        adapted = SimpleNamespace(**{
            **local.__dict__,
            "active_adapter_version_id": "qwen3-8b-stage9a-qlora-seed-9201",
        })
        adapted_routes = _reply_routes_settings(
            provider_version=adapted,
            local_version=adapted,
        )
        self.assertIn("9201", adapted_routes["local_only"]["label"])

    def test_protocol_sender_disables_redirects_and_ambient_proxy_settings(self) -> None:
        provider = WebPushDeliveryProvider(
            repository=None, owner_id=uuid4(),
            public_base_url="https://havre-node.tail-test.ts.net",
            vapid_private_key="private-test-key",
            vapid_public_key="B" + "p" * 86,
            vapid_key_version="vapid-test-20260827",
            vapid_subject="mailto:owner@example.test", enabled=True,
            lease_seconds=10,
            tailnet_attested=True,
        )
        with patch(
            "pywebpush.webpush",
            return_value=SimpleNamespace(headers={}, status_code=201),
        ) as send:
            receipt = provider._protocol_send(
                {
                    "endpoint":"https://web.push.apple.com/device/abc",
                    "p256dh":"p256dh-test", "auth_secret":"auth-test",
                },
                "{}",
            )
        self.assertEqual(receipt, "webpush-accepted-201")
        session = send.call_args.kwargs["requests_session"]
        self.assertFalse(session.trust_env)
        self.assertEqual(session.max_redirects, 0)
        self.assertLess(send.call_args.kwargs["timeout"], provider.lease_seconds)

    def test_push_endpoint_allowlist_is_exactly_apple_https(self) -> None:
        self.assertEqual(
            validate_web_push_endpoint("https://WEB.PUSH.APPLE.COM:443/device/abc?x=1"),
            "https://web.push.apple.com/device/abc?x=1",
        )
        for endpoint in (
            "https://127.0.0.1/push",
            "https://[::1]/push",
            "https://web.push.apple.com.evil.test/push",
            "https://owner@web.push.apple.com/push",
            "https://web.push.apple.com:8443/push",
            "http://web.push.apple.com/push",
            "https://web.push.apple.com/push#fragment",
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                validate_web_push_endpoint(endpoint)

    def test_manifest_service_worker_and_single_chat_shell_are_installable(self) -> None:
        manifest = json.loads((ROOT / "apps/web/manifest.webmanifest").read_text("utf-8"))
        worker = (ROOT / "apps/web/service-worker.js").read_text("utf-8")
        html = (ROOT / "apps/web/havre-chat.html").read_text("utf-8")
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(manifest["start_url"], "/chat")
        self.assertIn("self.addEventListener('push'", worker)
        self.assertIn("notificationclick", worker)
        self.assertIn("delivery_locator", worker)
        self.assertNotIn("event_id", worker)
        self.assertIn("shellEntry(url)", worker)
        self.assertIn("havre-static-20260906-short-turns-v17", worker)
        self.assertIn("PUSH_SHELL_VERSION='havre-shell-v5'", worker)
        self.assertNotIn("'/metrics'", worker)
        self.assertIn('rel="manifest"', html)
        self.assertNotIn("New Chat", html)
        self.assertEqual(html.count('class="nav-item'), 3)
        script = (ROOT / "apps/web/havre-app.js").read_text("utf-8")
        self.assertEqual(script.count("async function loadSettings()"), 1)
        self.assertIn("resolveDeliveryHash({refresh=true}={})", script)
        self.assertIn("if(refresh)await loadTimeline({refreshAfterCurrent:true})", script)
        self.assertIn("resolve({refresh:false})", script)
        self.assertIn("havre-shell-v5", worker)
        self.assertIn("searchParams.set('notification_open'", worker)
        self.assertIn("catch{return clients.openWindow(target)}", worker)
        self.assertIn("postMessage(message,[channel.port2])", worker)
        self.assertIn("HAVRE_NOTIFICATION_OPEN", worker)
        self.assertIn("HAVRE_NOTIFICATION_OPEN_ACK", worker)
        self.assertIn("new MessageChannel()", worker)
        self.assertIn("setTimeout(()=>finish(false),750)", worker)
        self.assertIn("current.navigate(target)", worker)
        self.assertIn("async function openNotification(locator)", script)
        self.assertIn("await resolveDeliveryHash()", script)
        self.assertIn("HAVRE_NOTIFICATION_OPEN_ACK", script)
        self.assertIn("initializeTimeline()", script)
        self.assertIn("cooldown?Number(cooldown):null", script)
        self.assertIn("reminders_enabled:$('#reachOutReminders').checked", script)
        self.assertIn("friendly_check_ins_enabled:$('#reachOutFriendly').checked", script)
        self.assertIn("reach?.cooldown_seconds==null?'':String(reach.cooldown_seconds)", script)
        self.assertIn("quiet?.start_local?.slice(0,5)||''", script)
        self.assertIn('<option value="">不额外限制</option>', html)
        self.assertIn('id="reachOutReminders"', html)
        self.assertIn('id="reachOutFriendly"', html)
        self.assertIn("聊天里停一分钟时，HAVRE 可以自然接一句", html)
        self.assertIn("半小时后最多再接一句，然后停", html)
        self.assertNotIn("Memory、Calendar、情绪和沉默只作 Context", html)
        css = (ROOT / "apps/web/havre-app.css").read_text("utf-8")
        self.assertIn("grid-template-columns:minmax(52px,60px) minmax(0,1fr)", css)
        self.assertIn("overflow-x:hidden", css)
        self.assertIn("white-space:pre-wrap", css)
        self.assertIn("top:var(--app-top,0px)", css)
        self.assertIn("私密聊天只在本地展开，不会交给云端整理", html)
        self.assertIn("哪里记错了，随时告诉我", html)
    def test_pwa_v5_notification_and_reconnect_contract_executes(self) -> None:
        node = shutil.which("node")
        self.assertIsNotNone(node,"Node.js is required for executable PWA behavior tests")
        completed = subprocess.run(
            [node,str(ROOT/"tests"/"pwa_v5_contract.js")],
            cwd=ROOT,text=True,capture_output=True,timeout=20,check=False,
        )
        self.assertEqual(
            completed.returncode,0,
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
        )
        self.assertIn("pwa-v5-contract: ok",completed.stdout)


    def test_push_client_never_places_credentials_in_notification_url(self) -> None:
        worker = (ROOT / "apps/web/service-worker.js").read_text("utf-8")
        script = (ROOT / "apps/web/havre-app.js").read_text("utf-8")
        self.assertNotIn("token=", worker)
        self.assertNotIn("token=", script)
        self.assertIn("credentials:'same-origin'", script)
        self.assertIn("HAVRE 有条消息给你", worker)
        activation = (ROOT / "scripts/activate_stage12a_owner_calendar.py").read_text("utf-8")
        self.assertNotIn("context-database-url.secret", activation)
        self.assertNotIn("device-secret.secret", activation)

    def test_desktop_lifecycle_fences_ambient_push_and_pid_reuse(self) -> None:
        start = (ROOT / "scripts/start_havre_desktop.ps1").read_text("utf-8")
        stop = (ROOT / "scripts/stop_havre_desktop.ps1").read_text("utf-8")
        self.assertIn("$acl.SetOwner($ownerIdentity)",start)
        self.assertIn("$verified.Owner.Equals(",start)
        self.assertIn("PreviousLaunchEnvironment", start)
        for name in (
            "HAVRE_DATABASE_URL","HAVRE_DATABASE_URL_FILE",
            "HAVRE_OWNER_API_TOKEN","HAVRE_OWNER_API_TOKEN_FILE",
            "HAVRE_DESKTOP_BOOTSTRAP_TOKEN","HAVRE_DESKTOP_BOOTSTRAP_TOKEN_FILE",
            "HAVRE_PROVIDER_ID","HAVRE_SELF_HOSTED_BASE_URL",
            "HAVRE_RUNTIME_ADAPTER_VERSION","HAVRE_RUNTIME_ADAPTER_HASH",
        ):
            self.assertIn(f'"{name}"',start)
        self.assertIn("HAVRE_WEB_PUSH_VAPID_PRIVATE_KEY_DPAPI_FILE", start)
        self.assertIn("Restore-HavreLaunchEnvironment", start)
        self.assertIn('Remove-Item -LiteralPath "Env:$name"', start)
        self.assertIn("Set-HavreOwnerOnlyPath -Path $child.FullName",start)
        self.assertIn("Set-HavreOwnerOnlyPath -Path $BootstrapPage",start)
        self.assertIn("if (-not $NoBrowser) { Open-HavreDesktop }", start)
        self.assertNotIn('if (-not $NoBrowser) { Start-Process "$BaseUrl/chat" }', start)
        self.assertIn("Set-HavreOwnerOnlyPath -Path $TailscaleOrigin",start)
        self.assertIn("Set-HavreOwnerOnlyPath -Path $StatePath",start)
        self.assertIn("worker_started_at", start)
        self.assertIn("worker_command_marker", start)
        self.assertIn("Get-CimInstance Win32_Process", start)
        self.assertIn("Get-CimInstance Win32_Process", stop)
        self.assertIn("ExpectedStartedAt", stop)
        self.assertIn("ExpectedStartedAt -is [DateTime]", start)
        self.assertIn("ExpectedStartedAt -is [DateTime]", stop)
        self.assertIn('$BaseUrl/health/ready', start)
        self.assertIn('[int]$response.StatusCode -eq 200', start)
        self.assertIn('[string]$payload.status -eq "ready"', start)
        self.assertEqual(start.count("[void](Wait-HavreReady"), 2)
        self.assertIn("Local database/privacy runtime startup failed", start)
        self.assertNotIn("fallback runtime", start)


    def test_diary_summary_ignores_greetings_and_transient_chat(self) -> None:
        result = DailyCompanionStore._summary([
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "好呀好呀"},
            {"role": "user", "content": "我感觉有点怪"},
        ])
        self.assertIsNone(result)

    def test_diary_summary_excludes_authorization_import_and_hash_chatter(self) -> None:
        result = DailyCompanionStore._summary([
            {"role": "user", "content": "我批准启动 owner-local worker 并应用 Stage 15 migration"},
            {"role": "assistant", "content": "已记录 Product Owner 授权。"},
            {"role": "user", "content": "导入完成，sha256:abcdef0123456789"},
        ])
        self.assertIsNone(result)

    def test_diary_summary_is_short_curated_and_user_sourced(self) -> None:
        curated = DailyCompanionStore._curated_summary([
            {"role": "user", "content": "今天在图书馆完成了机器人课程的小组演示，终于松了一口气"},
            {"role": "assistant", "content": "你今天真的做了很多。"},
            {"role": "user", "content": "晚上和朋友吃了火锅，聊得很开心"},
        ])
        self.assertIsNotNone(curated)
        title, summary, preview, sources = curated
        self.assertLessEqual(len(title), 19)
        self.assertIn("图书馆", summary)
        self.assertIn("火锅", summary)
        self.assertLessEqual(len(preview), 121)
        self.assertEqual([source["role"] for source in sources], ["user", "user"])

    def test_diary_summary_indexes_concrete_events_not_chat_transitions(self) -> None:
        title, summary, _ = DailyCompanionStore._summary([
            {"role": "user", "content": "你好"},
            {"role": "user", "content": "今天把 Strong Brain 跑通了"},
            {"role": "assistant", "content": "好呀好呀"},
            {"role": "user", "content": "决定日常继续用 9201"},
        ])
        self.assertIn("Strong Brain", title)
        self.assertIn("跑通", summary)
        self.assertIn("9201", summary)
        self.assertNotIn("今天主要", summary)
        self.assertNotIn("后来还提到", summary)

    def test_default_codex_reply_route_replaces_manual_strong_action(self) -> None:
        script = (ROOT / "apps/web/havre-app.js").read_text("utf-8")
        self.assertIn("这个浏览器没有本机授权", script)
        self.assertIn("start_havre_desktop.ps1", script)
        self.assertIn("等待本机授权", script)
        self.assertIn("回到这段聊天", script)
        self.assertIn("source_previews", script)
        self.assertIn("PENDING_INTERACTION_KEY='havre-pending-interaction-v1'", script)
        self.assertIn("'Idempotency-Key':pending.idempotency_key", script)
        self.assertIn("submitPendingWithReconciliation", script)
        self.assertNotIn("'Idempotency-Key':crypto.randomUUID()", script)
        self.assertIn("await loadTimeline({refreshAfterCurrent:true})", script)
        self.assertIn("settings.brain?.reason", script)
        self.assertNotIn('data-action="strong"', script)
        self.assertNotIn("/v1/brain/strong/rethink/", script)
        start = (ROOT / "scripts/start_havre_desktop.ps1").read_text("utf-8")
        self.assertIn("Get-Command codex.exe", start)
        self.assertIn("login status", start)
        self.assertIn('HAVRE_CODEX_CLI_PATH', start)
        self.assertIn('"HAVRE_MANUAL_STRONG_BRAIN_ENABLED"', start)
        self.assertIn('"DEEPSEEK_API_KEY","DEEPSEEK_API_KEY_FILE"', start)
        self.assertNotIn('$env:HAVRE_MANUAL_STRONG_BRAIN_ENABLED = "true"', start)
        self.assertNotIn('GetEnvironmentVariable("DEEPSEEK_API_KEY","User")', start)

        candidate_start = (ROOT / "scripts/start_havre_candidate_local.ps1").read_text("utf-8")
        self.assertIn("Get-AuthenticodeSignature", candidate_start)
        self.assertIn("postgres18-owner-20260828", candidate_start)
        self.assertIn('param([switch]$BaseOnly)', candidate_start)
        self.assertIn('runtime_kind = $RuntimeKind', candidate_start)
        self.assertIn('model-qwen3-8b-gguf-q4-k-m-7c41481f', candidate_start)
        stop = (ROOT / "scripts/stop_havre_candidate_local.ps1").read_text("utf-8")
        self.assertIn('postgres_backend', stop)
        self.assertIn('LD_LIBRARY_PATH=$WslLibraryPath', stop)
        self.assertIn('stage3-base', stop)
        desktop_start = (ROOT / "scripts/start_havre_desktop.ps1").read_text("utf-8")
        self.assertIn('start_havre_candidate_local.ps1") -BaseOnly', desktop_start)
        self.assertIn('$ExpectedProviderId = "openai-codex-chatgpt"', desktop_start)
        self.assertIn('$ExpectedModelVersion = "gpt-5.6-sol"', desktop_start)
        self.assertNotIn('$ExpectedAdapterVersion =', desktop_start)

@unittest.skipUnless(DATABASE_URL, "HAVRE_TEST_DATABASE_URL is required")
class DailyCompanionProductTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        assert DATABASE_URL is not None
        apply_migrations(DATABASE_URL, ROOT / "db/migrations")
        cls.identity = IdentityLoader(ROOT / "identity").load()
        cls.repository = PostgresRepository(DATABASE_URL)
        cls.repository.open()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.repository.close()

    async def asyncSetUp(self) -> None:
        self.owner = uuid4()
        self.repository.bootstrap_owner_and_identity(owner_id=self.owner, identity=self.identity)
        embedding = DeterministicEmbeddingProvider()
        self.repository.register_embedding_version(embedding.version)
        self.service = InteractionService(
            owner_id=self.owner,
            identity=self.identity,
            repository=self.repository,
            context_builder=ContextBuilder(max_input_tokens=4096, reserved_output_tokens=256),
            router=Stage1Router(),
            provider=DeterministicLocalProvider(),
            retrieval_service=RetrievalService(
                repository=self.repository, embedding_provider=embedding
            ),
        )
        self.product = DailyCompanionStore(repository=self.repository, owner_id=self.owner)

    def _push_provider(
        self, *, owner=None, sender=None, worker_id=None,
        lease_seconds=90, retry_base_seconds=5, max_attempts=4,
    ):
        provider = WebPushDeliveryProvider(
            repository=self.repository,
            owner_id=owner or self.owner,
            public_base_url="https://havre-node.tail-test.ts.net",
            vapid_private_key="private-test-key",
            vapid_public_key="B" + "p" * 86,
            vapid_key_version="vapid-test-20260827",
            vapid_subject="mailto:owner@example.test",
            enabled=True,
            sender=sender or (lambda subscription, payload: "accepted-test-receipt"),
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            retry_base_seconds=retry_base_seconds,
            max_attempts=max_attempts,
            tailnet_attested=True,
        )
        provider.ensure_configuration()
        return provider

    def _product_for_owner(self, owner):
        self.repository.bootstrap_owner_and_identity(owner_id=owner,identity=self.identity)
        return DailyCompanionStore(repository=self.repository,owner_id=owner)

    async def _talk(self, message: str, *, key: str | None = None):
        return await self.service.interact(
            InteractionCommand(
                message=message,
                privacy_class=PrivacyClass.LOCAL_ONLY,
                memory_eligible=True,
                channel="web",
                idempotency_key=key or f"daily-companion:{uuid4()}",
            )
        )

    async def test_turn_contract_gates_memory_retrieval_before_context_build(self) -> None:
        inner = self.service.retrieval_service

        class TrackingRetrievalService:
            default_algorithm = inner.default_algorithm
            def __init__(self):
                self.calls = []

            def retrieve(self, request, *, persist=True):
                self.calls.append(("retrieve", request.query.text))
                return inner.retrieve(request, persist=persist)

            def retrieve_empty(self, request, *, persist=True):
                self.calls.append(("empty", request.query.text))
                return inner.retrieve_empty(request, persist=persist)

        tracking = TrackingRetrievalService()
        self.service.retrieval_service = tracking
        await self._talk("解释一下本地模型量化是什么。")
        await self._talk("继续之前的本地模型方案。")
        self.assertEqual([kind for kind, _ in tracking.calls], ["empty", "retrieve"])

    async def test_manual_strong_disclosure_is_exact_idempotent_and_revocable(self) -> None:
        source = await self._talk("今天把 Strong Brain 手动入口跑通了")
        strong_interaction = InteractionService(
            owner_id=self.owner,
            identity=self.identity,
            repository=self.repository,
            context_builder=ContextBuilder(
                max_input_tokens=4096, reserved_output_tokens=256
            ),
            router=Stage1Router(),
            provider=DeterministicLocalProvider(),
            retrieval_service=self.service.retrieval_service,
            manual_strong_only=True,
        )
        strong = ManualStrongBrainService(
            owner_id=self.owner,
            repository=self.repository,
            interaction_service=strong_interaction,
        )
        key = f"manual-strong:{uuid4()}"
        context = strong.prepare(
            source_assistant_event_id=source.assistant_event_id,
            idempotency_key=key,
        )
        replay = strong.prepare(
            source_assistant_event_id=source.assistant_event_id,
            idempotency_key=key,
        )
        self.assertEqual(replay.disclosure_id, context.disclosure_id)
        rows = self.repository.list_manual_cloud_disclosures(
            owner_id=self.owner
        )
        self.assertEqual(len([
            row for row in rows if row["disclosure_id"] == context.disclosure_id
        ]), 1)
        self.assertEqual(rows[0]["status"], "prepared")
        self.assertTrue(self.repository.manual_cloud_context_prepared(
            owner_id=self.owner,
            disclosure_id=context.disclosure_id,
            source_assistant_event_id=source.assistant_event_id,
            policy_revision_id=context.data_policy.policy_revision_id,
            selected_source_refs=tuple(
                ref
                for item in (*context.personal_context, *context.conversation_history)
                for ref in item.source_refs
            ),
            selected_content_hash=context.selected_content_hash,
        ))
        foreign_owner = uuid4()
        self.repository.bootstrap_owner_and_identity(
            owner_id=foreign_owner, identity=self.identity
        )
        self.assertEqual(
            self.repository.list_manual_cloud_disclosures(owner_id=foreign_owner),
            (),
        )
        revoked = self.repository.revoke_manual_cloud_disclosure(
            owner_id=self.owner, disclosure_id=context.disclosure_id
        )
        self.assertEqual(revoked["status"], "revoked")
        with self.assertRaisesRegex(ValueError, "only a prepared disclosure"):
            self.repository.revoke_manual_cloud_disclosure(
                owner_id=self.owner, disclosure_id=context.disclosure_id
            )

    async def test_manual_strong_mock_delivery_uses_same_durable_timeline(self) -> None:
        source = await self._talk("我想让 Strong Brain 更认真地重新想一下")

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET" and request.url.path.endswith("/models"):
                return httpx.Response(
                    200, json={"data": [{"id": DEEPSEEK_MODEL_ID}]}
                )
            self.assertEqual(request.method, "POST")
            payload = json.loads(request.content)
            self.assertEqual(payload["user_id"], "havre-owner-manual-inference")
            self.assertEqual(payload["thinking"], {"type": "enabled"})
            self.assertEqual(
                payload["max_tokens"],
                MANUAL_STRONG_RESERVED_OUTPUT_TOKENS,
            )
            chunks = [
                {
                    "id": "manual-strong-stream-a",
                    "model": DEEPSEEK_MODEL_ID,
                    "choices": [{"finish_reason": None, "delta": {
                        "reasoning_content": "must remain hidden"
                    }}],
                    "usage": None,
                },
                {
                    "id": "manual-strong-stream-a",
                    "model": DEEPSEEK_MODEL_ID,
                    "choices": [{"finish_reason": "stop", "delta": {
                        "content": "这是 Strong Brain 重新想过后的回答。"
                    }}],
                    "usage": {
                        "prompt_tokens": 30, "completion_tokens": 12,
                        "total_tokens": 42,
                        "completion_tokens_details": {"reasoning_tokens": 5},
                    },
                },
            ]
            body = "".join(
                f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                for chunk in chunks
            ) + "data: [DONE]\n\n"
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"}, text=body
            )

        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "not-a-real-key"}):
            provider = DeepSeekCloudProvider(
                enabled=True,
                explicit_authorization_ref=OWNER_MANUAL_AUTHORIZATION_REF,
                mode="owner_manual",
                thinking="enabled",
                reasoning_effort="high",
                manual_permit_validator=lambda request: (
                    self.repository.manual_cloud_request_permitted(
                        owner_id=self.owner, request=request
                    )
                ),
                transport=httpx.MockTransport(handler),
            )
        self.addAsyncCleanup(provider.aclose)
        interaction = InteractionService(
            owner_id=self.owner,
            identity=self.identity,
            repository=self.repository,
            context_builder=ContextBuilder(
                max_input_tokens=(
                    4096 - 256 + MANUAL_STRONG_RESERVED_OUTPUT_TOKENS
                ),
                reserved_output_tokens=MANUAL_STRONG_RESERVED_OUTPUT_TOKENS,
            ),
            router=Stage1Router(
                approved_cloud_provider_ids=frozenset({DEEPSEEK_PROVIDER_ID})
            ),
            provider=provider,
            retrieval_service=self.service.retrieval_service,
            response_policy=self.service.response_policy,
            inference_timeout_ms=30_000,
            manual_strong_only=True,
        )
        strong = ManualStrongBrainService(
            owner_id=self.owner,
            repository=self.repository,
            interaction_service=interaction,
        )
        result = await strong.rethink(
            source_assistant_event_id=source.assistant_event_id,
            idempotency_key=f"strong-e2e:{uuid4()}",
        )
        self.assertEqual(result["status"], "sent")
        self.assertEqual(result["provider_id"], DEEPSEEK_PROVIDER_ID)
        rows = self.repository.list_manual_cloud_disclosures(
            owner_id=self.owner
        )
        self.assertEqual(rows[0]["status"], "sent")
        self.assertEqual(rows[0]["result_assistant_event_id"], result["assistant_event_id"])
        timeline = self.product.timeline(limit=20)
        delivered = next(
            item for item in timeline["items"]
            if item["event_id"] == result["assistant_event_id"]
        )
        self.assertIn("重新想过后的回答", delivered["content"])
        self.assertNotIn("must remain hidden", delivered["content"])

    async def test_explicit_phrase_correction_is_admitted_with_event_provenance(self) -> None:
        correction = await self._talk("别再说‘替我过掉’啦")
        selected = self.repository.select_personal_context(
            owner_id=self.owner,
            query_text="8点起",
            maximum_privacy_class=PrivacyClass.LOCAL_ONLY,
        )
        instruction = next(
            item for item in selected
            if item.section_type == "owner_wording_correction"
            and item.source_refs == (f"event/{correction.user_event_id}",)
        )
        self.assertEqual(
            instruction.source_refs, (f"event/{correction.user_event_id}",)
        )
        self.assertNotIn("替我过掉", instruction.content_text)
        self.assertNotIn("memory", instruction.section_type)
        user_event = self.repository.event_by_id(
            owner_id=self.owner, event_id=correction.user_event_id
        )
        self.assertIsNotNone(user_event)
        pack = self.service.context_builder.build(
            request_id=correction.request_id,
            trace_id=user_event.trace_id,
            owner_id=self.owner,
            identity=self.identity,
            user_event=user_event,
            personal_context=tuple(selected),
        )
        provider_text = "\n".join(
            part.text
            for message in render_inference_messages(pack)
            for part in message.content_parts
        )
        self.assertNotIn("替我过掉", provider_text)


    async def test_say_more_is_a_durable_idempotent_owner_turn_with_policy_projection(self) -> None:
        await self._talk("刚看完一个展览。")
        key=f"say-more:{uuid4()}"
        reply=await self._talk("再说点",key=key)
        replay=await self._talk("再说点",key=key)
        self.assertEqual(reply.assistant_event_id,replay.assistant_event_id)
        timeline=self.product.timeline(limit=100)["items"]
        owners=[item for item in timeline if item["role"]=="user" and item["content"]=="再说点"]
        self.assertEqual(len(owners),1)
        self.assertIsNone(owners[0]["response_policy_category"])
        assistant=next(item for item in timeline if item["event_id"]==reply.assistant_event_id)
        self.assertEqual(assistant["response_policy_category"],"ordinary")
        self.assertEqual(assistant["privacy_class"],"LOCAL_ONLY")
        self.assertFalse(assistant["cloud_eligible"])
        self.assertEqual(assistant["content"],reply.content)

    async def test_timeline_is_cross_session_keyset_paginated_and_idempotent(self) -> None:
        key = f"same-message:{uuid4()}"
        first = await self._talk("第一台设备发来的消息", key=key)
        replay = await self._talk("第一台设备发来的消息", key=key)
        self.assertTrue(replay.idempotent_replay)
        self.assertEqual(first.assistant_event_id, replay.assistant_event_id)
        await asyncio.gather(
            self._talk("手机同时发来的消息"),
            self._talk("电脑同时发来的消息"),
        )
        newest = self.product.timeline(limit=3)
        self.assertTrue(newest["has_more"])
        older = self.product.timeline(limit=100, **newest["next_cursor"])
        all_ids = [item["event_id"] for item in (*older["items"], *newest["items"])]
        self.assertEqual(len(all_ids), len(set(all_ids)))
        self.assertEqual(len(all_ids), 6)
        self.assertEqual(
            all_ids,
            sorted(
                all_ids,
                key=lambda event_id: next(
                    item["recorded_at"]
                    for item in (*older["items"], *newest["items"])
                    if item["event_id"] == event_id
                ),
            ),
        )
        assistant_item = next(
            item
            for item in (*older["items"], *newest["items"])
            if item["event_id"] == first.assistant_event_id
        )
        self.assertEqual(assistant_item["provider_id"], first.provider_id)
        self.assertEqual(
            assistant_item["model_version_id"],
            first.model_version_id,
        )
        self.assertEqual(assistant_item["execution_environment"], "local")
        focused = self.product.timeline(limit=2, through_event_id=first.assistant_event_id)
        self.assertEqual(focused["items"][-1]["event_id"], first.assistant_event_id)
        other = self._product_for_owner(uuid4())
        with self.assertRaisesRegex(ValueError, "no longer available"):
            other.timeline(through_event_id=first.assistant_event_id)

    async def test_timeline_hides_internal_course_source_interactions(self) -> None:
        imported = await self._talk(
            "内部课程来源批次，不是 owner 可见聊天。",
            key=f"course-source-v3-{uuid4()}",
        )
        visible_ids = {
            item["event_id"] for item in self.product.timeline(limit=100)["items"]
        }
        self.assertNotIn(imported.user_event_id, visible_ids)
        self.assertNotIn(imported.assistant_event_id, visible_ids)
        self.assertIsNotNone(self.repository.event_by_id(
            owner_id=self.owner,
            event_id=imported.user_event_id,
        ))
        self.assertIsNotNone(self.repository.event_by_id(
            owner_id=self.owner,
            event_id=imported.assistant_event_id,
        ))

    async def test_pairing_is_one_time_and_revoke_closes_device_and_push(self) -> None:
        pairing = self.product.create_pairing(ttl_seconds=600)
        with self.assertRaisesRegex(ValueError, "invalid or expired"):
            self.product.claim_pairing(
                pairing_id=pairing["pairing_id"], code="00000000",
                display_name="iPhone", device_kind="iphone"
            )
        claimed = self.product.claim_pairing(
            pairing_id=pairing["pairing_id"], code=pairing["code"],
            display_name="Owner iPhone", device_kind="iphone"
        )
        self.assertEqual(
            self.product.authenticate_device(claimed["device_token"]), claimed["device_id"]
        )
        with self.assertRaisesRegex(ValueError, "invalid or expired"):
            self.product.claim_pairing(
                pairing_id=pairing["pairing_id"], code=pairing["code"],
                display_name="Replay", device_kind="browser"
            )
        self._push_provider()
        subscription = self.product.save_subscription(
                device_id=claimed["device_id"], endpoint="https://web.push.apple.com/subscription/1",
            p256dh="p" * 65, auth_secret="a" * 24, preview_level="private",
            vapid_key_version="vapid-test-20260827",
        )
        self.assertEqual(subscription["status"], "active")
        self.product.revoke_device(device_id=claimed["device_id"])
        self.assertIsNone(self.product.authenticate_device(claimed["device_token"]))
        with self.repository.pool.connection() as connection:
            row = connection.execute(
                "SELECT status FROM havre.web_push_subscriptions WHERE owner_id=%s",
                (self.owner,),
            ).fetchone()
        self.assertEqual(row["status"], "revoked")

    async def test_pairing_locks_after_five_wrong_codes(self) -> None:
        pairing = self.product.create_pairing(ttl_seconds=600)
        for attempt in range(5):
            with self.assertRaisesRegex(ValueError, "invalid or expired"):
                self.product.claim_pairing(
                    pairing_id=pairing["pairing_id"],
                    code=f"{attempt:08d}",
                    display_name="Unknown phone",
                    device_kind="iphone",
                )
        with self.assertRaisesRegex(ValueError, "invalid or expired"):
            self.product.claim_pairing(
                pairing_id=pairing["pairing_id"],
                code=pairing["code"],
                display_name="Late correct phone",
                device_kind="iphone",
            )
        with self.repository.pool.connection() as connection:
            row = connection.execute(
                """SELECT failed_attempts,consumed_at
                   FROM havre.device_pairing_challenges
                   WHERE owner_id=%s AND pairing_id=%s""",
                (self.owner, pairing["pairing_id"]),
            ).fetchone()
        self.assertEqual(row["failed_attempts"], 5)
        self.assertIsNone(row["consumed_at"])

    async def test_daily_companion_foreign_keys_have_left_prefix_indexes(self) -> None:
        assert DATABASE_URL is not None
        query = """
        WITH wanted(table_name) AS (
          VALUES ('companion_devices'),('device_pairing_challenges'),
            ('device_read_cursors'),('web_push_subscriptions'),
            ('web_push_delivery_attempts'),('web_push_vapid_key_versions'),
            ('web_push_dispatches'),('manual_cloud_disclosures'),
            ('daily_diary_entry_heads'),
            ('daily_diary_entry_revisions'),('daily_diary_entry_sources')
        ), fk AS (
          SELECT con.conname,con.conrelid,con.conkey,rel.relname
          FROM pg_constraint con
          JOIN pg_class rel ON rel.oid=con.conrelid
          JOIN pg_namespace ns ON ns.oid=rel.relnamespace
          JOIN wanted ON wanted.table_name=rel.relname
          WHERE con.contype='f' AND ns.nspname='havre'
        )
        SELECT fk.relname,fk.conname FROM fk WHERE NOT EXISTS (
          SELECT 1 FROM pg_index idx
          WHERE idx.indrelid=fk.conrelid AND idx.indisvalid
            AND (idx.indkey::smallint[])[0:cardinality(fk.conkey)-1]=fk.conkey
        ) ORDER BY 1,2
        """
        with psycopg.connect(DATABASE_URL) as connection:
            self.assertEqual(connection.execute(query).fetchall(), [])

    async def test_diary_has_exactly_one_revisioned_entry_per_conversation_day(self) -> None:
        timezone_name = "America/Chicago"
        future = (datetime.now(UTC) + timedelta(days=30)).date()
        self.assertIsNone(
            self.product.sync_diary_day(local_date=future, timezone_name=timezone_name)
        )
        await self._talk("把 Strong Brain 跑通了")
        local_today = datetime.now(UTC).astimezone(ZoneInfo(timezone_name)).date()
        first = self.product.sync_diary_day(
            local_date=local_today, timezone_name=timezone_name
        )
        self.assertEqual(first["current_revision"], 1)
        self.assertIn("Strong Brain", first["title"])
        await self._talk("晚上开始准备手机端和主动消息")
        second = self.product.sync_diary_day(
            local_date=local_today, timezone_name=timezone_name
        )
        self.assertEqual(second["current_revision"], 2)
        entries = self.product.list_diary(timezone_name=timezone_name)
        self.assertEqual(len([item for item in entries if item["local_date"] == local_today]), 1)
        self.assertEqual(len(second["sources"]), 2)
        self.assertEqual({item["role"] for item in second["sources"]}, {"user"})
        with self.repository.pool.connection() as connection:
            head_count = connection.execute(
                """SELECT count(*) AS value FROM havre.daily_diary_entry_heads
                   WHERE owner_id=%s AND local_date=%s AND timezone_name=%s""",
                (self.owner, local_today, timezone_name),
            ).fetchone()["value"]
        self.assertEqual(head_count, 1)

    async def test_source_erasure_removes_diary_derivative_and_prevents_stale_summary(self) -> None:
        timezone_name = "America/Chicago"
        interaction = await self._talk("今天完成了一个稍后会删除的测试片段")
        local_today = datetime.now(UTC).astimezone(ZoneInfo(timezone_name)).date()
        self.assertIsNotNone(self.product.sync_diary_day(
            local_date=local_today, timezone_name=timezone_name
        ))
        counts = self.repository.erase_source_event_derivatives(
            owner_id=self.owner, source_event_id=interaction.user_event_id
        )
        self.assertEqual(counts["daily_diary_entries"], 1)
        self.assertEqual(counts["daily_diary_entry_sources"], 1)
        self.assertIsNone(self.product.sync_diary_day(
            local_date=local_today, timezone_name=timezone_name
        ))
        with self.repository.pool.connection() as connection:
            self.assertIsNone(connection.execute(
                """SELECT 1 FROM havre.daily_diary_entry_heads
                   WHERE owner_id=%s AND local_date=%s AND timezone_name=%s""",
                (self.owner, local_today, timezone_name),
            ).fetchone())

    def _proactive_message(
        self, *, owner, privacy_class: PrivacyClass,
        expires_at: datetime | None = None,
        generic_push_for_local_only: bool = False,
    ):
        self.repository.bootstrap_owner_and_identity(owner_id=owner, identity=self.identity)
        store = ProactivePostgresStore(
            repository=self.repository, owner_id=owner, identity=self.identity
        )
        preference = ProactivePreferenceRevision(
            owner_id=owner, revision=1, global_enabled=True,
            category_permissions={"owner_reminder": "allowed"},
            allowed_channels=("web_inbox",), global_budget_per_24h=4,
            category_budget_per_24h={"owner_reminder": 4}, cooldown_seconds=60,
            generic_push_for_local_only=generic_push_for_local_only,
            authorization_ref="daily-companion-web-push-test",
        )
        with self.repository.pool.connection() as connection:
            existing_preference = connection.execute(
                """SELECT 1 FROM havre.proactive_preference_revisions
                   WHERE owner_id=%s AND revision=1""",
                (owner,),
            ).fetchone()
        if existing_preference is None:
            store.save_preference(preference)
        now = datetime.now(UTC)
        result = store.execute_fixture(
            trigger_type="owner_requested_reminder", source_kind="owner_reminder",
            source_refs=(f"owner-reminder/{uuid4()}",), subject_refs=(f"goal/{uuid4()}",),
            category="owner_reminder", reason_code="owner_requested_fixture",
            reason_summary="Check the evidence-grounded owner reminder",
            intended_benefit="Support an owner-chosen commitment",
            data_policy=DataPolicy.owner_default(privacy_class, memory_eligible=False),
            preference_revision=1, idempotency_key=f"proactive:{uuid4()}",
            observed_at=now, earliest_eligible_at=now-timedelta(seconds=1),
            expires_at=expires_at or now+timedelta(hours=2),
            deduplication_key=f"dedupe:{uuid4()}",
        )
        self.assertEqual(result.decision.decision, InterruptionOutcome.SEND_NOW)
        return result

    async def test_governed_send_now_creates_one_generic_external_push(self) -> None:
        owner = uuid4()
        product = self._product_for_owner(owner)
        pairing = product.create_pairing()
        device = product.claim_pairing(
            pairing_id=pairing["pairing_id"], code=pairing["code"],
            display_name="Push iPhone", device_kind="iphone"
        )
        other_pairing = product.create_pairing()
        other_device = product.claim_pairing(
            pairing_id=other_pairing["pairing_id"], code=other_pairing["code"],
            display_name="Unrelated iPhone", device_kind="iphone"
        )
        provider = self._push_provider(owner=owner)
        subscription = product.save_subscription(
            device_id=device["device_id"], endpoint="https://web.push.apple.com/normal",
            p256dh="p" * 65, auth_secret="a" * 24, preview_level="private",
            vapid_key_version="vapid-test-20260827",
        )
        result = self._proactive_message(owner=owner, privacy_class=PrivacyClass.NORMAL)
        outbound = []
        provider.sender = lambda subscription, payload: outbound.append(json.loads(payload)) or "receipt-1"
        delivered = provider.deliver_pending()
        self.assertEqual(delivered["delivered"], 1)
        self.assertEqual(delivered["skipped"], 0)
        self.assertEqual(len(outbound), 1)
        self.assertEqual(outbound[0]["body"], "HAVRE 有条消息给你")
        self.assertEqual(set(outbound[0]), {"title","body","delivery_locator","url"})
        self.assertNotIn("event_id", outbound[0])
        self.assertEqual(provider.deliver_pending()["delivered"], 0)
        with self.repository.pool.connection() as connection:
            dispatch = connection.execute(
                """SELECT dispatch.dispatch_id,dispatch.delivery_locator,
                          dispatch.subscription_id,dispatch.assistant_event_id,
                          attempt.web_push_attempt_id
                   FROM havre.web_push_dispatches dispatch
                   JOIN havre.web_push_delivery_attempts attempt
                     ON attempt.owner_id=dispatch.owner_id
                    AND attempt.dispatch_id=dispatch.dispatch_id
                   WHERE dispatch.owner_id=%s AND dispatch.assistant_event_id=%s""",
                (owner,result.assistant_event_id),
            ).fetchone()
        with self.assertRaises(psycopg.Error) as lineage_error:
            with psycopg.connect(DATABASE_URL) as connection:
                with connection.transaction():
                    connection.execute("SET LOCAL ROLE havre_application")
                    connection.execute(
                        """INSERT INTO havre.web_push_real_device_validations
                           (owner_id,validation_id,dispatch_id,web_push_attempt_id,
                            subscription_id,device_id,assistant_event_id,
                            delivery_locator,validation_kind,pwa_shell_version,
                            owner_confirmation_ref,lock_screen_received,
                            notification_tap_opened,timeline_message_located)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,
                             'lock_screen_tap_timeline_located','havre-shell-v5',
                             'wrong-device-attack',true,true,true)""",
                        (
                            owner,uuid4(),dispatch["dispatch_id"],
                            dispatch["web_push_attempt_id"],
                            dispatch["subscription_id"],other_device["device_id"],
                            dispatch["assistant_event_id"],
                            dispatch["delivery_locator"],
                        ),
                    )
        self.assertEqual(lineage_error.exception.sqlstate,"55000")
        with self.assertRaisesRegex(RuntimeError,"rollback forged timestamp probe"):
            with self.repository.pool.connection() as connection:
                with connection.transaction():
                    forged = connection.execute(
                        """INSERT INTO havre.web_push_real_device_validations
                           (owner_id,validation_id,dispatch_id,web_push_attempt_id,
                            subscription_id,device_id,assistant_event_id,
                            delivery_locator,validation_kind,pwa_shell_version,
                            owner_confirmation_ref,lock_screen_received,
                            notification_tap_opened,timeline_message_located,
                            validated_at)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,
                             'lock_screen_tap_timeline_located','havre-shell-v5',
                             'forged-clock-test',true,true,true,%s)
                           RETURNING validated_at""",
                        (
                            owner,uuid4(),dispatch["dispatch_id"],
                            dispatch["web_push_attempt_id"],
                            dispatch["subscription_id"],device["device_id"],
                            dispatch["assistant_event_id"],
                            dispatch["delivery_locator"],
                            datetime(2000,1,1,tzinfo=UTC),
                        ),
                    ).fetchone()
                    self.assertGreater(
                        forged["validated_at"],datetime.now(UTC)-timedelta(seconds=5)
                    )
                    raise RuntimeError("rollback forged timestamp probe")
        with self.assertRaisesRegex(ValueError,"current served revision"):
            provider.record_real_device_validation(
                delivery_locator=dispatch["delivery_locator"],
                device_id=device["device_id"],
                pwa_shell_version="havre-shell-v4",
                owner_confirmation_ref="stale-shell-test",
            )
        with self.assertRaises(LookupError):
            provider.record_real_device_validation(
                delivery_locator=dispatch["delivery_locator"],
                device_id=uuid4(),
                pwa_shell_version="havre-shell-v5",
                owner_confirmation_ref="owner-confirmed-test",
            )
        validation = provider.record_real_device_validation(
            delivery_locator=dispatch["delivery_locator"],
            device_id=device["device_id"],
            pwa_shell_version="havre-shell-v5",
            owner_confirmation_ref="owner-confirmed-test",
        )
        with tempfile.TemporaryDirectory() as temp:
            export_root = Path(temp) / "owner-export"
            operations = Stage10PostgresStore(
                repository=self.repository,
                owner_id=owner,
                erasure_repository=self.repository,
            )
            manifest = operations.export_owner_data(export_root)
            operations.verify_owner_export(export_root)
            validation_export = (
                export_root / "tables/web_push_real_device_validations.jsonl"
            ).read_text(encoding="utf-8")
            self.assertIn(str(validation["validation_id"]),validation_export)
            self.assertIn("owner-confirmed-test",validation_export)
            self.assertIn("web_push_real_device_validations.jsonl",str(manifest))
        self.assertEqual(validation["subscription_id"],subscription["subscription_id"])
        self.assertTrue(provider.real_device_validated)
        self.assertFalse(provider.delivery_active)
        provider.record_worker_heartbeat(status="running",live_for_seconds=5)
        self.assertTrue(provider.delivery_active)
        with self.assertRaises(psycopg.Error),self.repository.pool.connection() as connection:
            with connection.transaction():
                connection.execute(
                    """UPDATE havre.web_push_real_device_validations
                       SET pwa_shell_version='havre-shell-v5'
                       WHERE owner_id=%s AND validation_id=%s""",
                    (owner,validation["validation_id"]),
                )
        with self.assertRaises(psycopg.Error) as delete_error:
            with self.repository.pool.connection() as connection:
                with connection.transaction():
                    connection.execute(
                        "DELETE FROM havre.web_push_real_device_validations "
                        "WHERE owner_id=%s AND validation_id=%s",
                        (owner,validation["validation_id"]),
                    )
        self.assertEqual(delete_error.exception.sqlstate,"55000")
        timeline = product.timeline(limit=10)
        self.assertTrue(any(
            item["event_id"] == result.assistant_event_id and item["proactive"]
            for item in timeline["items"]
        ))

    async def test_local_only_proactive_event_never_calls_external_push_sender(self) -> None:
        owner = uuid4()
        product = self._product_for_owner(owner)
        pairing = product.create_pairing()
        device = product.claim_pairing(
            pairing_id=pairing["pairing_id"], code=pairing["code"],
            display_name="Private iPhone", device_kind="iphone"
        )
        provider = self._push_provider(owner=owner)
        product.save_subscription(
            device_id=device["device_id"], endpoint="https://web.push.apple.com/private",
            p256dh="p" * 65, auth_secret="a" * 24, preview_level="detailed",
            vapid_key_version="vapid-test-20260827",
        )
        self._proactive_message(owner=owner, privacy_class=PrivacyClass.LOCAL_ONLY)
        calls = []
        provider.sender = lambda subscription, payload: calls.append(payload) or "forbidden"
        result = provider.deliver_pending()
        self.assertEqual(result["skipped"], 0)
        self.assertEqual(result["delivered"], 0)
        self.assertEqual(calls, [])

    async def test_local_only_generic_envelope_requires_exact_preference_authorization(self) -> None:
        owner = uuid4()
        product = self._product_for_owner(owner)
        pairing = product.create_pairing()
        device = product.claim_pairing(
            pairing_id=pairing["pairing_id"], code=pairing["code"],
            display_name="Authorized private iPhone", device_kind="iphone",
        )
        payloads = []
        provider = self._push_provider(
            owner=owner,
            sender=lambda subscription, payload: payloads.append(json.loads(payload))
            or "generic-local-only-receipt",
        )
        product.save_subscription(
            device_id=device["device_id"],
            endpoint="https://web.push.apple.com/private-authorized",
            p256dh="p" * 65,
            auth_secret="a" * 24,
            preview_level="detailed",
            vapid_key_version="vapid-test-20260827",
        )
        result = self._proactive_message(
            owner=owner,
            privacy_class=PrivacyClass.LOCAL_ONLY,
            generic_push_for_local_only=True,
        )
        delivery = provider.deliver_pending()
        self.assertEqual(delivery["delivered"], 1)
        self.assertEqual(len(payloads), 1)
        self.assertEqual(
            set(payloads[0]),
            {"title", "body", "delivery_locator", "url"},
        )
        self.assertEqual(payloads[0]["title"], "HAVRE")
        self.assertEqual(
            payloads[0]["body"],
            "HAVRE \u6709\u6761\u6d88\u606f\u7ed9\u4f60",
        )
        self.assertNotIn(result.rendering.content_text, payloads[0].values())

    async def test_dispatch_lease_blocks_concurrent_sender_and_recovers_after_expiry(self) -> None:
        owner = uuid4()
        product = self._product_for_owner(owner)
        pairing = product.create_pairing()
        device = product.claim_pairing(
            pairing_id=pairing["pairing_id"], code=pairing["code"],
            display_name="Lease iPhone", device_kind="iphone",
        )
        first = self._push_provider(owner=owner, worker_id="worker-a", lease_seconds=1)
        product.save_subscription(
            device_id=device["device_id"], endpoint="https://web.push.apple.com/lease",
            p256dh="p" * 65, auth_secret="a" * 24, preview_level="private",
            vapid_key_version="vapid-test-20260827",
        )
        self._proactive_message(owner=owner, privacy_class=PrivacyClass.NORMAL)
        self.assertEqual(first.enqueue_eligible(), 1)
        claimed = first._claim()
        self.assertIsNotNone(claimed)
        second = self._push_provider(owner=owner, worker_id="worker-b")
        self.assertIsNone(second._claim())
        time.sleep(1.1)
        reclaimed = second._claim()
        self.assertEqual(reclaimed["dispatch_id"], claimed["dispatch_id"])
        self.assertEqual(reclaimed["attempt_count"], 2)
        stale_payload = {
            "title":"HAVRE","body":"HAVRE 有条消息给你",
            "delivery_locator":str(claimed["delivery_locator"]),
            "url":f"/chat#delivery-{claimed['delivery_locator']}",
        }
        with self.assertRaisesRegex(RuntimeError, "exact active dispatch lease"):
            first._deliver_claimed(claimed, stale_payload)
        self.assertEqual(second._deliver_claimed(reclaimed, stale_payload), "delivered")
        with self.repository.pool.connection() as connection:
            attempts = connection.execute(
                """SELECT attempt_number,failure_code,status
                   FROM havre.web_push_delivery_attempts WHERE owner_id=%s
                   ORDER BY attempt_number""",(owner,),
            ).fetchall()
        self.assertEqual(
            [(row["attempt_number"],row["failure_code"],row["status"]) for row in attempts],
            [(1,"worker_lease_expired_outcome_unknown","failed"),(2,None,"delivered")],
        )

    async def test_final_expired_lease_becomes_dead_with_durable_unknown_evidence(self) -> None:
        owner = uuid4()
        product = self._product_for_owner(owner)
        pairing = product.create_pairing()
        device = product.claim_pairing(
            pairing_id=pairing["pairing_id"], code=pairing["code"],
            display_name="Crash iPhone", device_kind="iphone",
        )
        provider = self._push_provider(
            owner=owner,worker_id="crash-worker",lease_seconds=1,max_attempts=1,
        )
        product.save_subscription(
            device_id=device["device_id"],endpoint="https://web.push.apple.com/crash",
            p256dh="p"*65,auth_secret="a"*24,preview_level="private",
            vapid_key_version="vapid-test-20260827",
        )
        self._proactive_message(owner=owner, privacy_class=PrivacyClass.NORMAL)
        self.assertEqual(provider.enqueue_eligible(), 1)
        self.assertIsNotNone(provider._claim())
        time.sleep(1.1)
        self.assertIsNone(provider._claim())
        with self.repository.pool.connection() as connection:
            dispatch = connection.execute(
                """SELECT status,last_error_code FROM havre.web_push_dispatches
                   WHERE owner_id=%s""",(owner,),
            ).fetchone()
            attempt = connection.execute(
                """SELECT status,retryable,failure_code FROM havre.web_push_delivery_attempts
                   WHERE owner_id=%s""",(owner,),
            ).fetchone()
        self.assertEqual(
            (dispatch["status"],dispatch["last_error_code"]),
            ("dead","worker_lease_expired_outcome_unknown"),
        )
        self.assertEqual(
            (attempt["status"],attempt["retryable"],attempt["failure_code"]),
            ("failed",False,"worker_lease_expired_outcome_unknown"),
        )

    async def test_revoke_waits_for_inflight_send_and_prevents_later_send(self) -> None:
        owner = uuid4()
        product = self._product_for_owner(owner)
        pairing = product.create_pairing()
        device = product.claim_pairing(
            pairing_id=pairing["pairing_id"],code=pairing["code"],
            display_name="Fence iPhone",device_kind="iphone",
        )
        started,release = threading.Event(),threading.Event()
        calls = []
        def sender(subscription, payload):
            calls.append(payload)
            started.set()
            if not release.wait(timeout=5):
                raise TimeoutError("test sender release timed out")
            return "fenced-receipt"
        provider = self._push_provider(owner=owner,sender=sender)
        subscription = product.save_subscription(
            device_id=device["device_id"],endpoint="https://web.push.apple.com/fence",
            p256dh="p"*65,auth_secret="a"*24,preview_level="private",
            vapid_key_version="vapid-test-20260827",
        )
        self._proactive_message(owner=owner,privacy_class=PrivacyClass.NORMAL)
        with ThreadPoolExecutor(max_workers=2) as executor:
            sending = executor.submit(provider.deliver_pending)
            self.assertTrue(started.wait(timeout=5))
            revoking = executor.submit(
                product.revoke_subscription,
                device_id=device["device_id"],
                subscription_id=subscription["subscription_id"],
            )
            time.sleep(0.1)
            self.assertFalse(revoking.done())
            release.set()
            self.assertEqual(sending.result(timeout=5)["delivered"],1)
            revoking.result(timeout=5)
        self.assertEqual(len(calls),1)
        self.assertEqual(provider.deliver_pending()["delivered"],0)

    async def test_source_erasure_removes_web_push_dispatch_and_receipt(self) -> None:
        owner = uuid4()
        product = self._product_for_owner(owner)
        pairing = product.create_pairing()
        device = product.claim_pairing(
            pairing_id=pairing["pairing_id"], code=pairing["code"],
            display_name="Erasure iPhone", device_kind="iphone",
        )
        provider = self._push_provider(owner=owner)
        product.save_subscription(
            device_id=device["device_id"],
            endpoint="https://web.push.apple.com/erasure",
            p256dh="p"*65, auth_secret="a"*24, preview_level="private",
            vapid_key_version="vapid-test-20260827",
        )
        proactive = self._proactive_message(
            owner=owner, privacy_class=PrivacyClass.NORMAL
        )
        self.assertEqual(provider.deliver_pending()["delivered"], 1)
        with self.repository.pool.connection() as connection:
            delivery_locator = connection.execute(
                """SELECT delivery_locator FROM havre.web_push_dispatches
                   WHERE owner_id=%s""",
                (owner,),
            ).fetchone()["delivery_locator"]
        provider.record_real_device_validation(
            delivery_locator=delivery_locator,
            device_id=device["device_id"],
            pwa_shell_version="havre-shell-v5",
            owner_confirmation_ref="owner-confirmed-erasure-test",
        )
        erased = self.repository.erase_source_event_derivatives(
            owner_id=owner, source_event_id=proactive.assistant_event_id
        )
        self.assertEqual(erased["web_push_delivery_attempts"], 1)
        self.assertEqual(erased["web_push_dispatches"], 1)
        self.assertEqual(erased["web_push_real_device_validations"], 1)
        with self.repository.pool.connection() as connection:
            self.assertIsNone(connection.execute(
                "SELECT 1 FROM havre.web_push_delivery_attempts WHERE owner_id=%s",
                (owner,),
            ).fetchone())
            self.assertIsNone(connection.execute(
                "SELECT 1 FROM havre.web_push_dispatches WHERE owner_id=%s",
                (owner,),
            ).fetchone())
            self.assertIsNone(connection.execute(
                """SELECT 1 FROM havre.web_push_real_device_validations
                   WHERE owner_id=%s""",
                (owner,),
            ).fetchone())

    async def test_source_erasure_waits_for_inflight_send_then_closes_receipt(self) -> None:
        owner = uuid4()
        product = self._product_for_owner(owner)
        pairing = product.create_pairing()
        device = product.claim_pairing(
            pairing_id=pairing["pairing_id"],code=pairing["code"],
            display_name="Erase fence iPhone",device_kind="iphone",
        )
        started,release = threading.Event(),threading.Event()
        def sender(subscription, payload):
            started.set()
            if not release.wait(timeout=5):
                raise TimeoutError("test erasure release timed out")
            return "erase-fenced-receipt"
        provider = self._push_provider(owner=owner,sender=sender)
        product.save_subscription(
            device_id=device["device_id"],endpoint="https://web.push.apple.com/erase-fence",
            p256dh="p"*65,auth_secret="a"*24,preview_level="private",
            vapid_key_version="vapid-test-20260827",
        )
        proactive = self._proactive_message(owner=owner,privacy_class=PrivacyClass.NORMAL)
        with ThreadPoolExecutor(max_workers=2) as executor:
            sending = executor.submit(provider.deliver_pending)
            self.assertTrue(started.wait(timeout=5))
            erasing = executor.submit(
                self.repository.erase_source_event_derivatives,
                owner_id=owner,source_event_id=proactive.assistant_event_id,
            )
            time.sleep(0.1)
            self.assertFalse(erasing.done())
            release.set()
            self.assertEqual(sending.result(timeout=5)["delivered"],1)
            erased = erasing.result(timeout=5)
        self.assertEqual(erased["web_push_delivery_attempts"],1)
        self.assertEqual(erased["web_push_dispatches"],1)

    async def test_subscription_watermark_and_delivery_window_block_backlog(self) -> None:
        owner = uuid4()
        self._proactive_message(owner=owner,privacy_class=PrivacyClass.NORMAL)
        product = self._product_for_owner(owner)
        pairing = product.create_pairing()
        device = product.claim_pairing(
            pairing_id=pairing["pairing_id"],code=pairing["code"],
            display_name="Watermark iPhone",device_kind="iphone",
        )
        provider = self._push_provider(owner=owner)
        product.save_subscription(
            device_id=device["device_id"],endpoint="https://web.push.apple.com/watermark",
            p256dh="p"*65,auth_secret="a"*24,preview_level="private",
            vapid_key_version="vapid-test-20260827",
        )
        self.assertEqual(provider.enqueue_eligible(),0)
        post = self._proactive_message(owner=owner,privacy_class=PrivacyClass.NORMAL)
        self.assertEqual(provider.enqueue_eligible(),1)
        with self.repository.pool.connection() as connection:
            dispatch = connection.execute(
                """SELECT assistant_event_id,delivery_eligible_until
                   FROM havre.web_push_dispatches WHERE owner_id=%s""",(owner,),
            ).fetchone()
        self.assertEqual(dispatch["assistant_event_id"],post.assistant_event_id)
        self.assertGreater(dispatch["delivery_eligible_until"],datetime.now(UTC))

        expired_owner = uuid4()
        expires_at = datetime.now(UTC)+timedelta(milliseconds=300)
        self._proactive_message(
            owner=expired_owner,privacy_class=PrivacyClass.NORMAL,expires_at=expires_at,
        )
        expired_product = self._product_for_owner(expired_owner)
        pairing = expired_product.create_pairing()
        device = expired_product.claim_pairing(
            pairing_id=pairing["pairing_id"],code=pairing["code"],
            display_name="Expired iPhone",device_kind="iphone",
        )
        expired_provider = self._push_provider(owner=expired_owner)
        expired_product.save_subscription(
            device_id=device["device_id"],endpoint="https://web.push.apple.com/expired-window",
            p256dh="p"*65,auth_secret="a"*24,preview_level="private",
            vapid_key_version="vapid-test-20260827",
        )
        time.sleep(0.4)
        self.assertEqual(expired_provider.enqueue_eligible(),0)

    async def test_claimed_message_window_expiry_keeps_subscription_active(self) -> None:
        owner = uuid4()
        product = self._product_for_owner(owner)
        pairing = product.create_pairing()
        device = product.claim_pairing(
            pairing_id=pairing["pairing_id"],code=pairing["code"],
            display_name="Window iPhone",device_kind="iphone",
        )
        sent = []
        provider = self._push_provider(
            owner=owner,lease_seconds=3,
            sender=lambda subscription,payload: sent.append(payload) or "forbidden",
        )
        subscription = product.save_subscription(
            device_id=device["device_id"],
            endpoint="https://web.push.apple.com/claimed-window",
            p256dh="p"*65,auth_secret="a"*24,preview_level="private",
            vapid_key_version="vapid-test-20260827",
        )
        self._proactive_message(
            owner=owner,privacy_class=PrivacyClass.NORMAL,
            expires_at=datetime.now(UTC)+timedelta(seconds=1),
        )
        self.assertEqual(provider.enqueue_eligible(),1)
        claimed = provider._claim()
        self.assertIsNotNone(claimed)
        time.sleep(1.1)
        payload = {
            "title":"HAVRE","body":"HAVRE 有条消息给你",
            "delivery_locator":str(claimed["delivery_locator"]),
            "url":f"/chat#delivery-{claimed['delivery_locator']}",
        }
        self.assertEqual(provider._deliver_claimed(claimed,payload),"skipped")
        self.assertEqual(sent,[])
        with self.repository.pool.connection() as connection:
            subscription_status = connection.execute(
                """SELECT status FROM havre.web_push_subscriptions
                   WHERE owner_id=%s AND subscription_id=%s""",
                (owner,subscription["subscription_id"]),
            ).fetchone()["status"]
            dispatch = connection.execute(
                """SELECT status,last_error_code FROM havre.web_push_dispatches
                   WHERE owner_id=%s""",(owner,),
            ).fetchone()
        self.assertEqual(subscription_status,"active")
        self.assertEqual(
            (dispatch["status"],dispatch["last_error_code"]),
            ("blocked","delivery_window_expired"),
        )

    async def test_subscription_identity_and_attempt_hash_fail_closed_in_database(self) -> None:
        owner = uuid4()
        product = self._product_for_owner(owner)
        pairing = product.create_pairing()
        device = product.claim_pairing(
            pairing_id=pairing["pairing_id"],code=pairing["code"],
            display_name="Integrity iPhone",device_kind="iphone",
        )
        provider = self._push_provider(owner=owner)
        subscription = product.save_subscription(
            device_id=device["device_id"],endpoint="https://web.push.apple.com/integrity",
            p256dh="p"*65,auth_secret="a"*24,preview_level="private",
            vapid_key_version="vapid-test-20260827",
        )
        self._proactive_message(owner=owner,privacy_class=PrivacyClass.NORMAL)
        with self.assertRaises(psycopg.Error),self.repository.pool.connection() as connection:
            with connection.transaction():
                connection.execute(
                    """UPDATE havre.web_push_subscriptions
                       SET endpoint='https://web.push.apple.com/remapped'
                       WHERE owner_id=%s AND subscription_id=%s""",
                    (owner,subscription["subscription_id"]),
                )
        with self.assertRaises(psycopg.Error),self.repository.pool.connection() as connection:
            with connection.transaction():
                connection.execute(
                    """INSERT INTO havre.web_push_subscriptions
                       (owner_id,subscription_id,device_id,endpoint,endpoint_hash,p256dh,
                        auth_secret,preview_level,status,vapid_key_version,
                        delivery_eligible_from,created_at,updated_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,'private','active',%s,%s,%s,%s)""",
                    (owner,uuid4(),device["device_id"],
                     "https://web.push.apple.com/forged-hash","sha256:"+"0"*64,
                     "p"*65,"a"*24,"vapid-test-20260827",
                     datetime(2020,1,1,tzinfo=UTC),datetime(2020,1,1,tzinfo=UTC),
                     datetime(2020,1,1,tzinfo=UTC)),
                )
        canonical_endpoint = "https://web.push.apple.com/canonical-time"
        canonical_hash = "sha256:"+hashlib.sha256(canonical_endpoint.encode()).hexdigest()
        canonical_id = uuid4()
        with self.repository.pool.connection() as connection,connection.transaction():
            connection.execute(
                """INSERT INTO havre.web_push_subscriptions
                   (owner_id,subscription_id,device_id,endpoint,endpoint_hash,p256dh,
                    auth_secret,preview_level,status,vapid_key_version,
                    delivery_eligible_from,created_at,updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,'private','active',%s,%s,%s,%s)""",
                (owner,canonical_id,device["device_id"],canonical_endpoint,canonical_hash,
                 "p"*65,"a"*24,"vapid-test-20260827",
                 datetime(2020,1,1,tzinfo=UTC),datetime(2020,1,1,tzinfo=UTC),
                 datetime(2020,1,1,tzinfo=UTC)),
            )
            canonical_row = connection.execute(
                """SELECT created_at,updated_at,delivery_eligible_from
                   FROM havre.web_push_subscriptions
                   WHERE owner_id=%s AND subscription_id=%s""",
                (owner,canonical_id),
            ).fetchone()
        self.assertGreater(canonical_row["created_at"],datetime.now(UTC)-timedelta(seconds=5))
        self.assertEqual(canonical_row["created_at"],canonical_row["updated_at"])
        self.assertEqual(canonical_row["created_at"],canonical_row["delivery_eligible_from"])
        self.assertEqual(provider.enqueue_eligible(),1)
        claimed = provider._claim()
        payload = {"title":"HAVRE","body":"HAVRE 有条消息给你",
                   "delivery_locator":str(claimed["delivery_locator"]),
                   "url":f"/chat#delivery-{claimed['delivery_locator']}"}
        with self.assertRaises(psycopg.Error),self.repository.pool.connection() as connection:
            with connection.transaction():
                connection.execute(
                    """INSERT INTO havre.web_push_delivery_attempts
                       (owner_id,web_push_attempt_id,subscription_id,assistant_event_id,
                        proactive_delivery_attempt_id,idempotency_key,attempt_number,status,
                        retryable,preview_level,payload,payload_hash,failure_code,dispatch_id)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,'failed',true,'private',%s,%s,'forged',%s)""",
                    (owner,uuid4(),claimed["subscription_id"],claimed["assistant_event_id"],
                     claimed["proactive_delivery_attempt_id"],f"web-push:{claimed['dispatch_id']}",
                     claimed["attempt_count"],Jsonb(payload),"sha256:"+"0"*64,
                     claimed["dispatch_id"]),
                )
        with self.assertRaises(psycopg.Error),self.repository.pool.connection() as connection:
            with connection.transaction():
                connection.execute(
                    """DELETE FROM havre.web_push_subscriptions
                       WHERE owner_id=%s AND subscription_id=%s""",
                    (owner,subscription["subscription_id"]),
                )
        with self.repository.pool.connection() as connection,connection.transaction():
            connection.execute(
                """UPDATE havre.web_push_subscriptions
                   SET status='revoked',revoked_at=clock_timestamp(),
                       updated_at=clock_timestamp()
                   WHERE owner_id=%s AND subscription_id=%s""",
                (owner,subscription["subscription_id"]),
            )
        with self.assertRaises(psycopg.Error),self.repository.pool.connection() as connection:
            with connection.transaction():
                connection.execute(
                    """UPDATE havre.web_push_subscriptions
                       SET status='active',revoked_at=NULL,updated_at=clock_timestamp()
                       WHERE owner_id=%s AND subscription_id=%s""",
                    (owner,subscription["subscription_id"]),
                )

    async def test_worker_heartbeat_is_durable_and_expires_closed(self) -> None:
        provider = self._push_provider()
        self.assertFalse(provider.worker_status()["live"])
        provider.record_worker_heartbeat(status="running",live_for_seconds=5)
        self.assertTrue(provider.worker_status()["live"])
        self.assertTrue(provider.runtime_ready)
        self.assertFalse(provider.delivery_active)
        provider.record_worker_heartbeat(status="stopped",live_for_seconds=1)
        self.assertFalse(provider.worker_status()["live"])
        self.assertFalse(provider.runtime_ready)
        self.assertFalse(provider.delivery_active)

    async def test_populated_0042_to_current_web_push_upgrade_is_additive(self) -> None:
        assert DATABASE_URL is not None
        params = conninfo_to_dict(DATABASE_URL)
        database_name = f"havre_webpush_upgrade_{uuid4().hex[:12]}"
        admin_params = dict(params)
        admin_params["dbname"] = "postgres"
        target_params = dict(params)
        target_params["dbname"] = database_name
        admin_url = make_conninfo(**admin_params)
        target_url = make_conninfo(**target_params)
        with psycopg.connect(admin_url,autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        old_repository = None
        try:
            with tempfile.TemporaryDirectory() as temp:
                old_migrations = Path(temp)/"migrations"
                old_migrations.mkdir()
                for path in sorted((ROOT/"db"/"migrations").glob("*.sql")):
                    if path.name >= "0043_":
                        continue
                    shutil.copy2(path,old_migrations/path.name)
                applied = apply_migrations(target_url,old_migrations)
                self.assertEqual(applied[-1],"0042_daily_companion_review_corrections.sql")
            old_repository = PostgresRepository(target_url)
            old_repository.open()
            owner = uuid4()
            old_repository.bootstrap_owner_and_identity(owner_id=owner,identity=self.identity)
            legacy_service = InteractionService(
                owner_id=owner,
                identity=self.identity,
                repository=old_repository,
                context_builder=ContextBuilder(
                    max_input_tokens=4096,
                    reserved_output_tokens=256,
                ),
                router=Stage1Router(),
                provider=DeterministicLocalProvider(),
            )
            legacy_interaction = await legacy_service.interact(
                InteractionCommand(
                    message="Preserve a migration-0006-compatible v0 attempt.",
                    privacy_class=PrivacyClass.NORMAL,
                    channel="api",
                    idempotency_key=f"legacy-attestation-v0:{uuid4()}",
                )
            )
            device_id = uuid4()
            subscription_id = uuid4()
            now = datetime.now(UTC)
            with psycopg.connect(target_url) as connection:
                connection.execute(
                    "DROP TRIGGER inference_attempts_are_immutable "
                    "ON havre.inference_attempts"
                )
                connection.execute(
                    """UPDATE havre.inference_attempts
                       SET provider_class='self_hosted',
                           runtime_attestation_contract_version=0,
                           runtime_attestation_id=NULL,
                           runtime_attestation_hash=NULL
                       WHERE owner_id=%s AND request_id=%s""",
                    (owner, legacy_interaction.request_id),
                )
                connection.execute(
                    """CREATE TRIGGER inference_attempts_are_immutable
                       BEFORE UPDATE OR DELETE ON havre.inference_attempts
                       FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation()"""
                )
                connection.execute(
                    """INSERT INTO havre.companion_devices
                       (owner_id,device_id,display_name,device_kind,session_token_hash,
                        session_expires_at,last_seen_at,created_at)
                       VALUES (%s,%s,'Legacy iPhone','iphone',%s,%s,%s,%s)""",
                    (owner,device_id,"sha256:"+"1"*64,
                     now+timedelta(days=1),now,now),
                )
                connection.execute(
                    """INSERT INTO havre.web_push_subscriptions
                       (owner_id,subscription_id,device_id,endpoint,endpoint_hash,p256dh,
                        auth_secret,preview_level,status,created_at,updated_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,'private','active',%s,%s)""",
                    (owner,subscription_id,device_id,
                     "https://web.push.apple.com/legacy-upgrade",
                     "sha256:"+hashlib.sha256(
                         b"https://web.push.apple.com/legacy-upgrade"
                     ).hexdigest(),
                     "p"*65,"a"*24,now,now),
                )
            with tempfile.TemporaryDirectory() as temp:
                pre_lineage_migrations = Path(temp)/"migrations"
                pre_lineage_migrations.mkdir()
                for path in sorted((ROOT/"db"/"migrations").glob("*.sql")):
                    if path.name >= "0052_":
                        continue
                    shutil.copy2(path,pre_lineage_migrations/path.name)
                pre_lineage_applied = apply_migrations(
                    target_url,
                    pre_lineage_migrations,
                )

            legacy_tombstone = await legacy_service.interact(
                InteractionCommand(
                    message="Create a governed source-erasure tombstone.",
                    privacy_class=PrivacyClass.NORMAL,
                    channel="api",
                    idempotency_key=f"legacy-erasure-tombstone:{uuid4()}",
                )
            )
            old_repository.erase_source_event_derivatives(
                owner_id=owner,
                source_event_id=legacy_tombstone.user_event_id,
            )
            with psycopg.connect(target_url) as connection:
                connection.execute(
                    """UPDATE havre.interaction_requests
                       SET error_code='legacy_mark_failed_without_event'
                       WHERE owner_id=%s AND request_id=%s""",
                    (owner,legacy_tombstone.request_id),
                )
            with self.assertRaises(
                psycopg.errors.ObjectNotInPrerequisiteState
            ) as legacy_failure:
                apply_migrations(target_url,ROOT/"db"/"migrations")
            self.assertEqual(legacy_failure.exception.sqlstate,"55000")
            with psycopg.connect(target_url) as connection:
                lineage_before_repair = [
                    row[0]
                    for row in connection.execute(
                        """SELECT migration_id
                           FROM havre.schema_migrations
                           WHERE migration_id >= '0052_'
                           ORDER BY migration_id"""
                    ).fetchall()
                ]
            self.assertEqual(
                lineage_before_repair,
                ["0052_interaction_lineage_guards.sql"],
            )

            # The per-file migration transaction commits 0052 DDL and its
            # checksum row together before the populated 0053 scan rejects
            # this deliberately malformed legacy row.  The 0052
            # terminal-request guard then correctly makes an ordinary UPDATE
            # fail closed.  A
            # real affected database therefore needs an explicit, audited
            # repair window rather than an application-role workaround.  Model
            # that narrow repair here, restoring the one exact governed
            # source-erasure tombstone before retrying 0053.
            with psycopg.connect(target_url) as connection:
                connection.execute(
                    """DROP TRIGGER
                       interaction_requests_require_exact_assistant_adoption
                       ON havre.interaction_requests"""
                )
                connection.execute(
                    """UPDATE havre.interaction_requests
                       SET error_code='source_erasure_propagated'
                       WHERE owner_id=%s AND request_id=%s""",
                    (owner,legacy_tombstone.request_id),
                )
                connection.execute(
                    """CREATE TRIGGER
                       interaction_requests_require_exact_assistant_adoption
                       BEFORE UPDATE ON havre.interaction_requests
                       FOR EACH ROW EXECUTE FUNCTION
                       havre.guard_interaction_assistant_adoption()"""
                )
            lineage_applied = apply_migrations(
                target_url,
                ROOT/"db"/"migrations",
            )
            applied = [
                *pre_lineage_applied,
                *lineage_before_repair,
                *lineage_applied,
            ]
            self.assertEqual(
                applied,
                ["0043_governed_web_push_activation.sql",
                 "0044_web_push_security_closure.sql",
                 "0045_web_push_subscription_insert_guard.sql",
                 "0046_web_push_inbox_admission_clock.sql",
                 "0047_web_push_real_device_validation.sql",
                 "0048_web_push_validation_db_clock.sql",
                 "0049_governed_automatic_proactive_triggers.sql",
                 "0050_proactive_natural_renderer.sql",
                 "0051_manual_strong_brain_disclosure.sql",
                 "0052_interaction_lineage_guards.sql",
                 "0053_interaction_erasure_lineage_correction.sql",
                 "0054_stage15_commitment_broker.sql",
                 "0055_stage15_commitment_fk_indexes.sql",
                 "0056_curated_owner_diary_v3.sql",
                 "0057_gpt_diary_intelligence_and_paired_review.sql",
                 "0058_diary_intelligence_provenance_guards.sql",
                 "0059_experience_first_daily_review.sql",
                 "0060_owner_conversation_continuation.sql",
                 "0061_two_beat_conversation_continuation.sql",
                 "0062_correct_continuation_delivery_guard.sql",
                 "0063_owner_authorized_gpt_conversation_continuation.sql",
                 "0064_local_semantic_memory.sql",
                 "0065_hybrid_selection_nonnull_guard.sql",
                 "0066_realtime_memory_and_five_am_days.sql",
                 "0067_five_am_diary_source_guard.sql",
                 "0068_complete_reply_continuation_adapter.sql",
                 "0069_personal_context_event_search.sql",
                 "0070_personal_context_short_search_terms.sql",
                 "0071_current_state_delivery_freshness_lock.sql"],
            )
            self.assertEqual(
                lineage_applied,
                ["0053_interaction_erasure_lineage_correction.sql",
                 "0054_stage15_commitment_broker.sql",
                 "0055_stage15_commitment_fk_indexes.sql",
                 "0056_curated_owner_diary_v3.sql",
                 "0057_gpt_diary_intelligence_and_paired_review.sql",
                 "0058_diary_intelligence_provenance_guards.sql",
                 "0059_experience_first_daily_review.sql",
                 "0060_owner_conversation_continuation.sql",
                 "0061_two_beat_conversation_continuation.sql",
                 "0062_correct_continuation_delivery_guard.sql",
                 "0063_owner_authorized_gpt_conversation_continuation.sql",
                 "0064_local_semantic_memory.sql",
                 "0065_hybrid_selection_nonnull_guard.sql",
                 "0066_realtime_memory_and_five_am_days.sql",
                 "0067_five_am_diary_source_guard.sql",
                 "0068_complete_reply_continuation_adapter.sql",
                 "0069_personal_context_event_search.sql",
                 "0070_personal_context_short_search_terms.sql",
                 "0071_current_state_delivery_freshness_lock.sql"],
            )
            with psycopg.connect(target_url,row_factory=dict_row) as connection:
                legacy_attempt = connection.execute(
                    """SELECT provider_class,runtime_attestation_contract_version,
                              runtime_attestation_id,runtime_attestation_hash
                       FROM havre.inference_attempts
                       WHERE owner_id=%s AND request_id=%s""",
                    (owner, legacy_interaction.request_id),
                ).fetchone()
                self.assertEqual(legacy_attempt["provider_class"], "self_hosted")
                self.assertEqual(
                    legacy_attempt["runtime_attestation_contract_version"],
                    0,
                )
                self.assertIsNone(legacy_attempt["runtime_attestation_id"])
                self.assertIsNone(legacy_attempt["runtime_attestation_hash"])
                row = connection.execute(
                    """SELECT delivery_eligible_from,created_at,vapid_key_version
                       FROM havre.web_push_subscriptions
                       WHERE owner_id=%s AND subscription_id=%s""",
                    (owner,subscription_id),
                ).fetchone()
                self.assertIsNotNone(row)
                self.assertGreaterEqual(row["delivery_eligible_from"],row["created_at"])
                self.assertIsNone(row["vapid_key_version"])
                self.assertIsNotNone(connection.execute(
                    """SELECT 1 FROM pg_trigger trigger
                       JOIN pg_class relation ON relation.oid=trigger.tgrelid
                       JOIN pg_namespace namespace ON namespace.oid=relation.relnamespace
                       WHERE namespace.nspname='havre'
                         AND relation.relname='web_push_subscriptions'
                         AND trigger.tgname='guard_web_push_subscription_transition'
                         AND NOT trigger.tgisinternal"""
                ).fetchone())
        finally:
            if old_repository is not None:
                old_repository.close()
            with psycopg.connect(admin_url,autocommit=True) as admin:
                admin.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s",
                    (database_name,),
                )
                admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database_name)))

    async def test_network_failure_is_durable_and_retry_uses_same_locator(self) -> None:
        owner = uuid4()
        product = self._product_for_owner(owner)
        pairing = product.create_pairing()
        device = product.claim_pairing(
            pairing_id=pairing["pairing_id"], code=pairing["code"],
            display_name="Retry iPhone", device_kind="iphone",
        )
        failing = self._push_provider(
            owner=owner, worker_id="retry-a",
            sender=lambda subscription, payload: (_ for _ in ()).throw(OSError("offline")),
            retry_base_seconds=1,
        )
        product.save_subscription(
            device_id=device["device_id"], endpoint="https://web.push.apple.com/retry",
            p256dh="p" * 65, auth_secret="a" * 24, preview_level="private",
            vapid_key_version="vapid-test-20260827",
        )
        self._proactive_message(owner=owner, privacy_class=PrivacyClass.NORMAL)
        self.assertEqual(failing.deliver_pending()["failed"], 1)
        with self.repository.pool.connection() as connection, connection.transaction():
            before = connection.execute(
                """SELECT dispatch_id,delivery_locator,status,attempt_count
                   FROM havre.web_push_dispatches WHERE owner_id=%s""",
                (owner,),
            ).fetchone()
            self.assertEqual(before["status"], "retry_wait")
        time.sleep(2.1)
        sent = []
        retry = self._push_provider(
            owner=owner, worker_id="retry-b",
            sender=lambda subscription, payload: sent.append(json.loads(payload)) or "receipt-retry",
        )
        self.assertEqual(retry.deliver_pending()["delivered"], 1)
        self.assertEqual(sent[0]["delivery_locator"], str(before["delivery_locator"]))
        with self.repository.pool.connection() as connection:
            after = connection.execute(
                """SELECT status,attempt_count FROM havre.web_push_dispatches
                   WHERE owner_id=%s AND dispatch_id=%s""",
                (owner, before["dispatch_id"]),
            ).fetchone()
        self.assertEqual((after["status"], after["attempt_count"]), ("accepted", 2))

    async def test_database_rejects_forged_dispatch_completion(self) -> None:
        owner = uuid4()
        product = self._product_for_owner(owner)
        pairing = product.create_pairing()
        device = product.claim_pairing(
            pairing_id=pairing["pairing_id"], code=pairing["code"],
            display_name="Forgery probe", device_kind="iphone",
        )
        provider = self._push_provider(owner=owner)
        product.save_subscription(
            device_id=device["device_id"], endpoint="https://web.push.apple.com/forgery",
            p256dh="p" * 65, auth_secret="a" * 24, preview_level="private",
            vapid_key_version="vapid-test-20260827",
        )
        self._proactive_message(owner=owner, privacy_class=PrivacyClass.NORMAL)
        self.assertEqual(provider.enqueue_eligible(), 1)
        with self.assertRaises(psycopg.Error), self.repository.pool.connection() as connection:
            with connection.transaction():
                connection.execute(
                    """UPDATE havre.web_push_dispatches
                       SET status='accepted',completed_at=clock_timestamp()
                       WHERE owner_id=%s""",
                    (owner,),
                )

    async def test_database_keeps_provider_attempt_receipts_immutable(self) -> None:
        owner = uuid4()
        product = self._product_for_owner(owner)
        pairing = product.create_pairing()
        device = product.claim_pairing(
            pairing_id=pairing["pairing_id"],code=pairing["code"],
            display_name="Receipt iPhone",device_kind="iphone",
        )
        provider = self._push_provider(owner=owner)
        product.save_subscription(
            device_id=device["device_id"],endpoint="https://web.push.apple.com/receipt",
            p256dh="p"*65,auth_secret="a"*24,preview_level="private",
            vapid_key_version="vapid-test-20260827",
        )
        self._proactive_message(owner=owner,privacy_class=PrivacyClass.NORMAL)
        self.assertEqual(provider.deliver_pending()["delivered"],1)
        with self.repository.pool.connection() as connection:
            attempt_id = connection.execute(
                """SELECT web_push_attempt_id FROM havre.web_push_delivery_attempts
                   WHERE owner_id=%s""",(owner,),
            ).fetchone()["web_push_attempt_id"]
        for statement in (
            """UPDATE havre.web_push_delivery_attempts SET provider_receipt_id='forged'
               WHERE owner_id=%s AND web_push_attempt_id=%s""",
            """DELETE FROM havre.web_push_delivery_attempts
               WHERE owner_id=%s AND web_push_attempt_id=%s""",
        ):
            with self.subTest(statement=statement),self.assertRaises(psycopg.Error):
                with self.repository.pool.connection() as connection,connection.transaction():
                    connection.execute(statement,(owner,attempt_id))

    async def test_database_rejects_non_apple_push_endpoint(self) -> None:
        owner = uuid4()
        self.repository.bootstrap_owner_and_identity(owner_id=owner,identity=self.identity)
        product = self._product_for_owner(owner)
        pairing = product.create_pairing()
        device = product.claim_pairing(
            pairing_id=pairing["pairing_id"],code=pairing["code"],
            display_name="Endpoint probe",device_kind="iphone",
        )
        self._push_provider(owner=owner)
        with self.assertRaises(ValueError):
            product.save_subscription(
                device_id=device["device_id"],endpoint="https://127.0.0.1/internal",
                p256dh="p"*65,auth_secret="a"*24,preview_level="private",
                vapid_key_version="vapid-test-20260827",
            )


@unittest.skipUnless(DATABASE_URL, "HAVRE_TEST_DATABASE_URL is required")
class DailyCompanionApiAuthenticationTests(unittest.TestCase):
    def test_manual_strong_runtime_requires_explicit_gate_and_key(self) -> None:
        assert DATABASE_URL is not None
        with patch.dict(os.environ, {
            "DEEPSEEK_API_KEY": "stale-key-must-not-activate",
            "HAVRE_MANUAL_STRONG_BRAIN_ENABLED": "false",
            "HAVRE_DEPLOYMENT_ENVIRONMENT": "development",
        }, clear=False):
            # A parent launcher may use a file-backed secret.  This case
            # deliberately supplies the direct synthetic key while preserving
            # Windows SystemRoot/WINDIR, which OpenSSL needs to initialize.
            os.environ.pop("DEEPSEEK_API_KEY_FILE", None)
            stale_settings = Settings.from_env(
                require_owner_api_token=False,
                enable_erasure_ledger=False,
            ).model_copy(update={
                "database_url": DATABASE_URL,
                "owner_id": uuid4(),
            })
            with TestClient(create_app(stale_settings)) as client:
                self.assertIsNone(client.app.state.runtime.strong_brain_service)
                strong = client.get("/v1/product/settings").json()["strong_brain"]
                self.assertFalse(strong["runtime_active"])
                self.assertFalse(strong["available_for_owner_data"])
                self.assertFalse(strong["default"])
                self.assertFalse(strong["user_facing"])
                blocked = client.post(
                    f"/v1/brain/strong/rethink/{uuid4()}",
                    headers={"Idempotency-Key": str(uuid4())},
                )
                self.assertEqual(blocked.status_code, 409)
                self.assertIn("未显式启用", blocked.json()["detail"])

        with patch.dict(os.environ, {
            "DEEPSEEK_API_KEY": "explicit-test-key",
            "HAVRE_MANUAL_STRONG_BRAIN_ENABLED": "true",
            "HAVRE_DEPLOYMENT_ENVIRONMENT": "development",
        }, clear=False):
            os.environ.pop("DEEPSEEK_API_KEY_FILE", None)
            enabled_settings = Settings.from_env(
                require_owner_api_token=False,
                enable_erasure_ledger=False,
            ).model_copy(update={
                "database_url": DATABASE_URL,
                "owner_id": uuid4(),
            })
            with TestClient(create_app(enabled_settings)) as client:
                self.assertIsNotNone(client.app.state.runtime.strong_brain_service)
                strong = client.get("/v1/product/settings").json()["strong_brain"]
                self.assertTrue(strong["runtime_active"])
                self.assertTrue(strong["available_for_owner_data"])
                self.assertFalse(strong["default"])
                self.assertFalse(strong["user_facing"])
                missing_source = client.post(
                    f"/v1/brain/strong/rethink/{uuid4()}",
                    headers={"Idempotency-Key": str(uuid4())},
                )
                self.assertEqual(missing_source.status_code, 404)

    def test_non_loopback_request_fails_when_private_serve_attestation_is_lost(self) -> None:
        assert DATABASE_URL is not None
        base = Settings.from_env(
            require_owner_api_token=False, enable_erasure_ledger=False
        )
        settings = base.model_copy(update={
            "database_url": DATABASE_URL,
            "owner_id": uuid4(),
            "owner_api_token": "o" * 48,
            "require_owner_api_token": True,
            "public_base_url": "https://havre-node.tail-test.ts.net",
            "web_push_enabled": True,
            "web_push_vapid_public_key": "public",
            "web_push_vapid_private_key": "private",
            "web_push_vapid_private_key_from_dpapi": True,
            "web_push_vapid_key_version": "vapid-owner-test",
            "web_push_vapid_subject": "mailto:owner@example.test",
            "tailscale_cli_path": Path("C:/Program Files/Tailscale/tailscale.exe"),
        })
        with TestClient(create_app(settings)) as client:
            for path in (
                "/", "/chat", "/diary", "/memory", "/settings",
                "/v1/timeline", "/metrics",
            ):
                with self.subTest(path=path):
                    response = client.get(path)
                    self.assertEqual(response.status_code, 503)
                    self.assertEqual(
                        response.json()["detail"],
                        "private Tailscale Serve attestation is unavailable",
                    )
            self.assertEqual(client.get("/health").status_code, 200)
            self.assertEqual(client.get("/service-worker.js").status_code, 200)

    def test_paired_device_cookie_access_and_strong_brain_fail_closed(self) -> None:
        assert DATABASE_URL is not None
        owner = uuid4()
        base = Settings.from_env(
            require_owner_api_token=False, enable_erasure_ledger=False
        )
        settings = base.model_copy(update={
            "database_url": DATABASE_URL,
            "owner_id": owner,
            "owner_api_token": "o" * 48,
            "require_owner_api_token": True,
            "deepseek_api_key": None,
            "deepseek_api_key_from_secret_file": False,
            "manual_strong_brain_enabled": False,
        })
        app = create_app(settings)
        with TestClient(app) as client:
            unauthorized = client.get("/v1/timeline")
            self.assertEqual(unauthorized.status_code, 401)
            owner_headers = {"Authorization": f"Bearer {settings.owner_api_token}"}
            validation_body = {
                "delivery_locator": str(uuid4()),
                "device_id": str(uuid4()),
                "pwa_shell_version": "havre-shell-v5",
                "owner_confirmation_ref": "primary-owner-auth-test",
            }
            with patch.object(
                app.state.runtime.web_push_provider,
                "record_real_device_validation",
                return_value={"validation_id": str(uuid4())},
            ):
                primary_validation = client.post(
                    "/v1/push/real-device-validations",
                    headers=owner_headers,json=validation_body,
                )
            self.assertEqual(primary_validation.status_code,200)
            pairing = client.post("/v1/devices/pair", headers=owner_headers).json()
            reach_out = client.post(
                "/v1/product/reach-out",
                headers=owner_headers,
                json={
                    "enabled": True,
                    "reminders_enabled": True,
                    "friendly_check_ins_enabled": False,
                    "cooldown_seconds": 21600,
                    "quiet_start": "22:30:00",
                    "quiet_end": "08:00:00",
                },
            )
            self.assertEqual(reach_out.status_code, 200)
            self.assertTrue(reach_out.json()["global_enabled"])
            self.assertEqual(
                reach_out.json()["category_permissions"]["owner_reminder"],
                "allowed",
            )
            self.assertEqual(
                reach_out.json()["category_permissions"]["relationship_follow_up"],
                "denied",
            )
            self.assertEqual(
                reach_out.json()["category_permissions"]["conversation_continuation"],
                "denied",
            )
            self.assertEqual(
                reach_out.json()["category_budget_per_24h"]["conversation_continuation"],
                2,
            )
            self.assertEqual(
                reach_out.json()["quiet_hours"][0]["timezone_name"],
                settings.owner_timezone,
            )
            paired = client.post("/v1/devices/pair/claim", json={
                "pairing_id": pairing["pairing_id"], "code": pairing["code"],
                "display_name": "Paired browser", "device_kind": "browser",
            })
            self.assertEqual(paired.status_code, 200)
            self.assertTrue(paired.cookies.get("havre_device_session"))
            self.assertEqual(client.get("/v1/timeline").status_code, 200)
            product_settings = client.get("/v1/product/settings")
            self.assertEqual(product_settings.status_code, 200)
            self.assertFalse(
                product_settings.json()["relationship_initiative_active"]
            )
            self.assertFalse(product_settings.json()["auth_capabilities"]["owner_primary"])
            self.assertTrue(product_settings.json()["auth_capabilities"]["mutate_memory"])
            self.assertTrue(product_settings.json()["auth_capabilities"]["review_understanding"])
            self.assertFalse(product_settings.json()["web_push_delivery_active"])
            strong = product_settings.json()["strong_brain"]
            self.assertFalse(strong["runtime_active"])
            self.assertFalse(strong["available_for_owner_data"])
            self.assertFalse(strong["default"])
            self.assertFalse(strong["user_facing"])
            self.assertEqual(
                product_settings.json()["local_brain"]["binding"],
                "deterministic-companion-v1",
            )
            reply_routes = product_settings.json()["reply_routes"]
            self.assertTrue(reply_routes["local_only_available"])
            self.assertEqual(
                reply_routes["default"]["execution_environment"],
                "local",
            )
            self.assertEqual(
                reply_routes["local_only"]["execution_environment"],
                "local",
            )
            self.assertFalse(reply_routes["silent_cross_provider_fallback"])
            for method, path in (
                ("get", "/v1/devices"),
                ("post", "/v1/devices/pair"),
                ("post", "/v1/product/reach-out"),
                ("post", "/v1/privacy/exports"),
                ("post", "/v1/proactive/work/run-once"),
                ("post", "/v1/push/real-device-validations"),
            ):
                self.assertEqual(getattr(client, method)(path).status_code, 403, path)
            review_id = uuid4()
            paired_review_responses = (
                client.post(
                    f"/v1/memory/candidates/{review_id}/accept",
                    json={"reason": "paired review test"},
                ),
                client.post(
                    f"/v1/memory/candidates/{review_id}/reject",
                    json={"reason": "paired review test"},
                ),
                client.post(
                    f"/v1/memories/{review_id}/correct",
                    json={"reason": "paired review test", "content_text": "corrected"},
                ),
                client.post(
                    f"/v1/user-model/beliefs/{review_id}/transitions",
                    json={
                        "revision": 1,
                        "transition_type": "activated",
                        "reason": "paired review test",
                        "evidence": [],
                    },
                ),
            )
            self.assertTrue(all(
                response.status_code != 403 for response in paired_review_responses
            ))
            blocked = client.post(
                f"/v1/brain/strong/rethink/{uuid4()}",
                headers={"Idempotency-Key": str(uuid4())},
            )
            self.assertEqual(blocked.status_code, 403)
            self.assertIn("paired device is not authorized", blocked.json()["detail"])
