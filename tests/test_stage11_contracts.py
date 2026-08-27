from __future__ import annotations

import plistlib
import json
import os
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from companion.identity import IdentityLoader
from companion.mobile import MobileEnrollmentReceipt
from companion.persistence import PostgresRepository, apply_migrations
from companion.persistence.proactive import ProactivePostgresStore
from companion.policy import DataPolicy, PrivacyClass
from companion.proactive import ProactivePreferenceRevision
from pydantic import ValidationError
from services.api.app import create_app
from services.api.settings import Settings
from scripts.export_contract_schemas import CONTRACTS


ROOT = Path(__file__).resolve().parents[1]
IOS = ROOT / "apps" / "ios"
DATABASE_URL = os.getenv("HAVRE_TEST_DATABASE_URL")


class Stage11NativeClientContracts(unittest.TestCase):
    def test_voice_is_owner_started_on_device_and_has_no_ambient_path(self) -> None:
        controller = (IOS / "Sources/HAVREiPhone/VoiceController.swift").read_text()
        machine = (IOS / "Sources/HAVREMobileCore/NotificationPolicy.swift").read_text()
        app_sources = "\n".join(
            path.read_text() for path in (IOS / "Sources").rglob("*.swift")
        ).lower()
        self.assertIn("ownerTappedStart()", controller)
        self.assertIn("requiresOnDeviceRecognition = true", controller)
        self.assertIn("guard state == .requestingPermission", machine)
        self.assertNotIn("registerforremotenotifications", app_sources)
        self.assertNotIn("startmonitoring", app_sources)
        self.assertNotIn("wake word", app_sources)

    def test_iophone_uses_existing_core_endpoints_and_exact_delivery_linkage(self) -> None:
        client = (IOS / "Sources/HAVREMobileCore/APIClient.swift").read_text()
        models = (IOS / "Sources/HAVREMobileCore/Models.swift").read_text()
        for route in (
            "/v1/interactions",
            "/v1/scenes/",
            "/delivery-reconciliation",
            "/actions",
        ):
            self.assertIn(route, client)
        self.assertIn('values["proposal_id"]', models)
        self.assertIn('values["delivery_attempt_id"]', models)
        self.assertIn("delivery linkage mismatch", client)
        self.assertNotIn("9201", client)
        self.assertNotIn("9202", client)

    def test_backend_exposes_existing_inbox_projection_route(self) -> None:
        source = (ROOT / "services/api/app.py").read_text()
        self.assertIn('@app.get("/v1/proactive/inbox")', source)
        self.assertIn("runtime.proactive_store.list_pending_inbox", source)
        self.assertIn('@app.get("/v1/mobile/enrollment")', source)

    def test_stage11_contract_schemas_are_exact(self) -> None:
        for name in ("mobile-enrollment-receipt-v1", "proactive-inbox-item-v1"):
            committed = json.loads(
                (ROOT / "contracts" / "schemas" / f"{name}.json").read_text()
            )
            self.assertEqual(committed, CONTRACTS[name].model_json_schema())

    def test_enrollment_receipt_binds_exact_owner(self) -> None:
        owner = uuid.uuid4()
        values = {
            "owner_id": owner,
            "core_binding_id": f"owner:{owner}",
            "constitution_version_id": "constitution-v1",
            "identity_version_id": "identity-v1",
            "values_version_id": "values-v1",
            "governance_version": "governance-v1",
        }
        self.assertEqual(MobileEnrollmentReceipt(**values).owner_id, owner)
        with self.assertRaisesRegex(ValidationError, "exact owner_id"):
            MobileEnrollmentReceipt(**(values | {"core_binding_id": f"owner:{uuid.uuid4()}"}))

    def test_native_project_has_permissions_but_no_push_or_background_entitlement(self) -> None:
        with (IOS / "Configuration/Info.plist").open("rb") as handle:
            info = plistlib.load(handle)
        self.assertIn("NSMicrophoneUsageDescription", info)
        self.assertIn("NSSpeechRecognitionUsageDescription", info)
        self.assertIn("NSLocalNetworkUsageDescription", info)
        self.assertNotIn("UIBackgroundModes", info)
        project = (IOS / "project.yml").read_text()
        self.assertNotIn("aps-environment", project)
        self.assertNotIn("Push Notifications", project)

    def test_protected_cache_and_explicit_local_erasure_are_present(self) -> None:
        storage = (IOS / "Sources/HAVREiPhone/ProtectedStorage.swift").read_text()
        model = (IOS / "Sources/HAVREiPhone/AppModel.swift").read_text()
        self.assertIn("completeUntilFirstUserAuthentication", storage)
        self.assertIn("isExcludedFromBackup = true", storage)
        self.assertIn("kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly", storage)
        self.assertIn("messageCacheURL", storage)
        self.assertIn("kSecAttrService", storage)
        self.assertIn("eraseAll", storage)
        self.assertIn("func eraseLocalData()", model)

    def test_offline_queue_preserves_sequence_and_stops_on_first_failure(self) -> None:
        queue = (IOS / "Sources/HAVREMobileCore/OfflineQueue.swift").read_text()
        app_model = (IOS / "Sources/HAVREiPhone/AppModel.swift").read_text()
        self.assertIn("entries.sorted { $0.sequence < $1.sequence }", queue)
        self.assertIn("for envelope in await queue.pending()", queue)
        self.assertIn("blockedEnvelopeID: envelope.id", queue)
        self.assertIn("await queue.acknowledge(id: envelope.id)", queue)
        send_body = app_model.split("func send() async", 1)[1].split(
            "func enqueueSceneSignal", 1
        )[0]
        self.assertIn("await reconcile()", send_body)
        self.assertNotIn("client.send", send_body)
        self.assertIn("enrollmentVerified", send_body)
        init_body = app_model.split("init()", 1)[1].split("func enroll", 1)[0]
        self.assertNotIn("enrollmentVerified = true", init_body)
        resume_body = app_model.split("func resume() async", 1)[1].split(
            "func refreshNotificationInbox", 1
        )[0]
        self.assertIn("enrollmentVerified = false", resume_body)
        self.assertIn("enrollmentVerified = true", resume_body)

    def test_notification_sync_and_local_erasure_clear_stale_content(self) -> None:
        notifications = (IOS / "Sources/HAVREiPhone/NotificationController.swift").read_text()
        app_model = (IOS / "Sources/HAVREiPhone/AppModel.swift").read_text()
        self.assertIn("removeAllDeliveredNotifications", notifications)
        self.assertIn("removeAllPendingNotificationRequests", notifications)
        self.assertIn("!item.simulationOnly, item.externalDeliveryAuthorized", notifications)
        erase_body = app_model.split("func eraseLocalData() async", 1)[1].split(
            "func requestNotificationPermission", 1
        )[0]
        self.assertIn("clearLocalNotifications()", erase_body)
        root = (IOS / "Sources/HAVREiPhone/RootView.swift").read_text()
        reply = root.split('Button("Send linked reply")', 1)[1].split(
            "private func queueAction", 1
        )[0]
        self.assertLess(reply.index("await queueAction"), reply.index("replyDrafts.take"))


@unittest.skipUnless(DATABASE_URL, "HAVRE_TEST_DATABASE_URL is required")
class Stage11PostgresIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        assert DATABASE_URL is not None
        apply_migrations(DATABASE_URL, ROOT / "db" / "migrations")
        identity = IdentityLoader(ROOT / "identity").load()
        cls.repository = PostgresRepository(DATABASE_URL)
        cls.repository.open()
        cls.owner = uuid.uuid4()
        cls.other_owner = uuid.uuid4()
        cls.repository.bootstrap_owner_and_identity(owner_id=cls.owner, identity=identity)
        cls.repository.bootstrap_owner_and_identity(owner_id=cls.other_owner, identity=identity)
        cls.store = ProactivePostgresStore(
            repository=cls.repository, owner_id=cls.owner, identity=identity
        )
        cls.other_store = ProactivePostgresStore(
            repository=cls.repository, owner_id=cls.other_owner, identity=identity
        )
        for store, owner in ((cls.store, cls.owner), (cls.other_store, cls.other_owner)):
            store.save_preference(ProactivePreferenceRevision(
                owner_id=owner, revision=1, global_enabled=True,
                category_permissions={"owner_reminder": "allowed"},
                allowed_channels=("web_inbox",), preview_policy="generic_private",
                global_budget_per_24h=4,
                category_budget_per_24h={"owner_reminder": 4},
                cooldown_seconds=60, authorization_ref="stage11-native-inbox-fixture",
            ))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.repository.close()

    @staticmethod
    def _execute(store: ProactivePostgresStore, key: str):
        now = datetime.now(UTC)
        return store.execute_fixture(
            trigger_type="owner_requested_reminder", source_kind="owner_reminder",
            source_refs=(f"owner-reminder/{key}",), subject_refs=(f"goal/{key}",),
            category="owner_reminder", reason_code="owner_requested_fixture",
            reason_summary="Review the owner-chosen native fixture",
            intended_benefit="Prove the same Core-owned inbox projection",
            data_policy=DataPolicy.owner_default(
                PrivacyClass.LOCAL_ONLY, memory_eligible=False
            ),
            preference_revision=1, idempotency_key=key,
            observed_at=now, earliest_eligible_at=now - timedelta(seconds=1),
            expires_at=now + timedelta(hours=1), deduplication_key=f"dedupe:{key}",
        )

    def test_pending_inbox_is_owner_isolated_linked_and_action_reconciled(self) -> None:
        mine = self._execute(self.store, f"stage11-mine-{uuid.uuid4()}")
        other = self._execute(self.other_store, f"stage11-other-{uuid.uuid4()}")
        items = self.store.list_pending_inbox()
        item = next(value for value in items if value.proposal_id == mine.proposal.proposal_id)
        self.assertEqual(item.delivery_attempt_id, mine.delivery_attempt.delivery_attempt_id)
        self.assertNotIn(other.proposal.proposal_id, {value.proposal_id for value in items})
        self.assertEqual(item.privacy_class, "LOCAL_ONLY")
        self.assertIsNone(item.content_text)
        self.assertFalse(item.external_delivery_authorized)
        self.store.record_owner_action(
            proposal_id=mine.proposal.proposal_id, action_type="dismissed",
            idempotency_key=f"stage11-dismiss-{uuid.uuid4()}",
            reason="owner dismissed native fixture", observed_at=datetime.now(UTC),
        )
        self.assertNotIn(
            mine.proposal.proposal_id,
            {value.proposal_id for value in self.store.list_pending_inbox()},
        )
        with self.assertRaisesRegex(ValueError, "between 1 and 100"):
            self.store.list_pending_inbox(limit=101)

    def test_http_inbox_projection_returns_exact_existing_delivery(self) -> None:
        assert DATABASE_URL is not None
        result = self._execute(self.store, f"stage11-http-{uuid.uuid4()}")
        settings = Settings.from_env().model_copy(update={
            "database_url": DATABASE_URL,
            "owner_id": self.owner,
            "provider_id": "deterministic-local",
        })
        with TestClient(create_app(settings)) as client:
            response = client.get("/v1/proactive/inbox?limit=100")
            invalid = client.get("/v1/proactive/inbox?limit=101")
            enrollment = client.get("/v1/mobile/enrollment")
        self.assertEqual(response.status_code, 200, response.text)
        match = next(
            item for item in response.json()["items"]
            if item["proposal_id"] == str(result.proposal.proposal_id)
        )
        self.assertEqual(
            match["delivery_attempt_id"], str(result.delivery_attempt.delivery_attempt_id)
        )
        self.assertEqual(match["external_delivery_authorized"], False)
        self.assertEqual(invalid.status_code, 422, invalid.text)
        self.assertEqual(enrollment.status_code, 200, enrollment.text)
        self.assertEqual(enrollment.json()["owner_id"], str(self.owner))
        self.assertEqual(enrollment.json()["core_binding_id"], f"owner:{self.owner}")


if __name__ == "__main__":
    unittest.main()
