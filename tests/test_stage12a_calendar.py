from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid

import psycopg
from pydantic import ValidationError

from apps.calendar_agent.calendar import (
    CalendarAvailabilityAdapter,
    opaque_manual_calendar_binding,
)
from apps.calendar_agent.ics import IcsCalendarProvider, IcsProtocolError, parse_ics_availability
from apps.calendar_agent.runner import CalendarAgentRunner
from apps.windows_agent.transport import ContextTransportRejected
from companion.life_context import (
    CalendarBusyInterval,
    CalendarAvailabilityWindow,
    CalendarContextActivationBundle,
    CalendarImportPolicy,
    ConsentScopeRevision,
    ContextCapabilityStateRevision,
    ContextCollectionPermit,
    ContextSourceCapability,
    ContextSourceDescriptor,
    ContextSourceStateRevision,
    RetentionPolicy,
)
from companion.policy import DataPolicy, PrivacyClass
from companion.identity import IdentityLoader
from companion.persistence import PostgresRepository, Stage12ContextStore, apply_migrations
from companion.persistence.operations import Stage10PostgresStore
from companion.operations.ledger import ErasureLedger


ROOT = Path(__file__).resolve().parents[1]
DATABASE_URL = os.environ.get("HAVRE_TEST_DATABASE_URL")
SECRET = b"calendar-test-device-secret-that-is-long-enough"
MANUAL_PROVIDER_BINDING = opaque_manual_calendar_binding("owner-local-manual-ics")
CALENDAR_BINDING = opaque_manual_calendar_binding("uiuc-course-calendar")


class ReversingProtector:
    def protect(self, plaintext: bytes) -> bytes:
        return b"protected:" + plaintext[::-1]

    def unprotect(self, ciphertext: bytes) -> bytes:
        if not ciphertext.startswith(b"protected:"):
            raise ValueError("not protected")
        return ciphertext[len(b"protected:"):][::-1]


def calendar_fixture(owner: uuid.UUID | None = None):
    now = datetime.now(UTC).replace(microsecond=0)
    owner = owner or uuid.uuid4()
    authorization_ref = "po-stage12a-manual-ics-calendar-2026-08-22"
    source = ContextSourceDescriptor(
        owner_id=owner,
        source_kind="calendar",
        provider_id="manual-ics",
        device_binding_id=f"calendar:manual-ics:{uuid.uuid4().hex}",
        adapter_version="manual-ics-calendar-v1",
        source_version="rfc5545-bounded-v1",
        provider_tenant_binding=MANUAL_PROVIDER_BINDING,
        provider_account_binding=CALENDAR_BINDING,
    )
    capability = ContextSourceCapability(
        owner_id=owner,
        source_instance_id=source.source_instance_id,
        capability_id="calendar.read_availability.v1",
        observation_kind="calendar_availability_window",
        allowed_fields=("busy_intervals",),
        precision="availability_only_no_content",
        sampling_modes=("owner_initiated_import",),
        conformance_version="calendar-availability-adapter-conformance-v1",
    )
    policy = DataPolicy(
        policy_revision_id=uuid.uuid4(),
        privacy_class=PrivacyClass.LOCAL_ONLY,
        memory_eligible=False,
        training_eligible=False,
        cloud_eligible=False,
        decision_source="owner_explicit",
        authorization_ref=authorization_ref,
    )
    consent = ConsentScopeRevision(
        owner_id=owner,
        source_instance_id=source.source_instance_id,
        capability_revision_id=capability.capability_revision_id,
        revision=1,
        status="active",
        allowed_observation_kinds=("calendar_availability_window",),
        allowed_fields=("busy_intervals",),
        sampling_policy=CalendarImportPolicy(
            policy_version="manual-ics-semester-import-v1",
            max_coverage_seconds=17_280_000,
            max_clock_skew_seconds=300,
            offline_buffer_seconds=300,
        ),
        retention_policy=RetentionPolicy(
            policy_version="calendar-canonical-retention-v1",
            normalized_draft_retention_seconds=0,
            canonical_retention_days=240,
        ),
        data_policy=policy,
        effective_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(days=180),
        authorization_ref=authorization_ref,
    )
    permit = ContextCollectionPermit(
        source=source,
        source_state=ContextSourceStateRevision(
            owner_id=owner,
            source_instance_id=source.source_instance_id,
            revision=1,
            status="enabled",
            reason="registered",
            effective_at=consent.effective_at,
            authorization_ref=authorization_ref,
        ),
        capability=capability,
        capability_state=ContextCapabilityStateRevision(
            owner_id=owner,
            capability_revision_id=capability.capability_revision_id,
            revision=1,
            status="enabled",
            reason="registered",
            effective_at=consent.effective_at,
            authorization_ref=authorization_ref,
        ),
        consent=consent,
        issued_at=now,
        valid_until=now + timedelta(seconds=30),
    )
    return source, capability, consent, permit


class Stage12CalendarContractTests(unittest.TestCase):
    def _ics(self) -> bytes:
        return b"""BEGIN:VCALENDAR\r
VERSION:2.0\r
BEGIN:VEVENT\r
UID:private-provider-id\r
SUMMARY:Private course title\r
LOCATION:Private room\r
DTSTART;TZID=Central Standard Time:20260824T090000\r
DTEND;TZID=Central Standard Time:20260824T095000\r
RRULE:FREQ=WEEKLY;COUNT=3;BYDAY=MO,WE\r
EXDATE;TZID=Central Standard Time:20260831T090000\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:free-event\r
TRANSP:TRANSPARENT\r
DTSTART:20260825T150000Z\r
DTEND:20260825T160000Z\r
END:VEVENT\r
END:VCALENDAR\r
"""

    def test_content_free_synthetic_calendar_benchmark(self) -> None:
        from scripts.run_stage12a_calendar_benchmark import run

        report = run(iterations=100)
        self.assertTrue(report["passed"])
        self.assertEqual(report["conformance"]["forbidden_content_crossings"], [])
        self.assertFalse(report["workload"]["real_calendar_content_collected"])

    def test_manual_ics_is_minimized_and_expands_bounded_recurrence(self) -> None:
        value, rows = parse_ics_availability(
            self._ics(),
            window_from=datetime(2026, 8, 1, tzinfo=UTC),
            window_to=datetime(2026, 12, 31, tzinfo=UTC),
            default_timezone="America/Chicago",
        )
        self.assertEqual(rows, 2)
        self.assertEqual(len(value.busy_intervals), 2)
        serialized = value.model_dump_json().lower()
        for forbidden in ("private-provider-id", "private course", "private room", "summary", "location", "uid"):
            self.assertNotIn(forbidden, serialized)

    def test_manual_ics_fails_closed_on_unsupported_or_oversized_input(self) -> None:
        base = self._ics().replace(
            b"FREQ=WEEKLY;COUNT=3;BYDAY=MO,WE",
            b"FREQ=MONTHLY;COUNT=3",
        )
        with self.assertRaisesRegex(IcsProtocolError, "daily or weekly"):
            parse_ics_availability(
                base,
                window_from=datetime(2026, 8, 1, tzinfo=UTC),
                window_to=datetime(2026, 12, 31, tzinfo=UTC),
                default_timezone="America/Chicago",
            )
        with self.assertRaisesRegex(IcsProtocolError, "bounded size"):
            parse_ics_availability(
                b"x" * (4 * 1024 * 1024 + 1),
                window_from=datetime(2026, 8, 1, tzinfo=UTC),
                window_to=datetime(2026, 12, 31, tzinfo=UTC),
            )

        for recurrence, message in (
            (b"FREQ=WEEKLY;COUNT=x;BYDAY=MO", "bounds"),
            (b"FREQ=WEEKLY;COUNT=3;BYDAY=1MO", "weekday"),
            (b"FREQ=WEEKLY;COUNT=3;BYDAY=MO;WKST=SU", "Monday-based"),
        ):
            malformed = self._ics().replace(
                b"FREQ=WEEKLY;COUNT=3;BYDAY=MO,WE", recurrence
            )
            with self.assertRaisesRegex(IcsProtocolError, message):
                parse_ics_availability(
                    malformed,
                    window_from=datetime(2026, 8, 1, tzinfo=UTC),
                    window_to=datetime(2026, 12, 31, tzinfo=UTC),
                    default_timezone="America/Chicago",
                )

    def test_manual_ics_supports_folded_and_all_day_without_retaining_content(self) -> None:
        value, rows = parse_ics_availability(
            b"""BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nSUMMARY:Private long \r\n course title\r\nDTSTART;VALUE=DATE:20260907\r\nDTEND;VALUE=DATE:20260908\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n""",
            window_from=datetime(2026, 9, 1, tzinfo=UTC),
            window_to=datetime(2026, 9, 30, tzinfo=UTC),
            default_timezone="America/Chicago",
        )
        self.assertEqual(rows, 1)
        self.assertEqual(len(value.busy_intervals), 1)
        self.assertTrue(value.busy_intervals[0].is_all_day)
        self.assertNotIn("private", value.model_dump_json().lower())

    def test_semester_scale_availability_fits_the_signed_observation_contract(self) -> None:
        source, capability, consent, permit = calendar_fixture()
        starts = datetime(2026, 8, 24, 14, tzinfo=UTC)
        intervals = tuple(
            CalendarBusyInterval(
                starts_at=starts + timedelta(hours=index * 8),
                ends_at=starts + timedelta(hours=index * 8 + 1),
                availability="busy",
                is_all_day=False,
            )
            for index in range(512)
        )
        class SemesterProvider:
            def read_all_calendar_availability(self, *, window_from, window_to, before_read=None):
                if before_read is not None:
                    before_read()
                return CalendarAvailabilityWindow(busy_intervals=intervals), 6, 1

        provider = SemesterProvider()
        collected = CalendarAvailabilityAdapter(
            source=source,
            capability=capability,
            consent=consent,
            signing_secret=SECRET,
            provider=provider,
            permit_resolver=lambda: permit,
            clock=lambda: permit.issued_at,
        ).collect(window_from=starts, window_to=starts + timedelta(days=171))
        self.assertGreater(len(collected.draft.signing_material()), 32_768)
        self.assertLessEqual(len(collected.draft.signing_material()), 262_144)
        self.assertEqual(len(collected.draft.value.busy_intervals), 512)

    def _historical_graph_scope_is_delegated_read_without_user_profile_scope(self) -> None:
        self.assertEqual(
            GRAPH_DELEGATED_SCOPES, ("offline_access", "Calendars.ReadBasic")
        )
        self.assertNotIn("User.Read", GRAPH_DELEGATED_SCOPES)
        self.assertNotIn("Calendars.ReadWrite", GRAPH_DELEGATED_SCOPES)

    def _historical_graph_payload_is_minimized_before_draft(self) -> None:
        source, capability, consent, permit = calendar_fixture()
        now = datetime.now(UTC).replace(microsecond=0)
        window_to = now + timedelta(days=7)
        observed_requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            observed_requests.append(request)
            if request.url.path == "/v1.0/me/calendars":
                return httpx.Response(200, json={"value": [{"id": "calendar-a"}]})
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "provider-secret-event-id",
                            "subject": "Private medical appointment",
                            "body": {"content": "private body"},
                            "location": {"displayName": "private location"},
                            "attendees": [{"emailAddress": {"address": "friend@example.com"}}],
                            "organizer": {"emailAddress": {"address": "doctor@example.com"}},
                            "showAs": "busy",
                            "isAllDay": False,
                            "isCancelled": False,
                            "start": {"dateTime": (now + timedelta(hours=1)).isoformat(), "timeZone": "UTC"},
                            "end": {"dateTime": (now + timedelta(hours=2)).isoformat(), "timeZone": "UTC"},
                        },
                        {
                            "subject": "Free event is not retained",
                            "showAs": "free",
                            "isAllDay": False,
                            "isCancelled": False,
                            "start": {"dateTime": (now + timedelta(hours=3)).isoformat(), "timeZone": "UTC"},
                            "end": {"dateTime": (now + timedelta(hours=4)).isoformat(), "timeZone": "UTC"},
                        },
                    ]
                },
            )

        adapter = MicrosoftGraphCalendarAdapter(
            source=source,
            capability=capability,
            consent=consent,
            signing_secret=SECRET,
            provider=MicrosoftGraphCalendarProvider(
                http_client=httpx.Client(transport=httpx.MockTransport(handler))
            ),
            permit_resolver=lambda: permit,
            clock=lambda: now,
        )
        result = adapter.collect(
            access_token="not-a-real-token",
            window_from=now,
            window_to=window_to,
        )
        self.assertEqual(result.provider_rows_seen, 2)
        self.assertEqual(result.calendars_seen, 1)
        self.assertEqual(result.retained_busy_intervals, 1)
        serialized = result.draft.model_dump_json().lower()
        for forbidden in (
            "provider-secret-event-id", "medical", "private body", "private location",
            "friend@example.com", "doctor@example.com", "subject", "attendees",
            "organizer", "location",
        ):
            self.assertNotIn(forbidden, serialized)
        request = observed_requests[1]
        self.assertEqual(
            request.url.params["$select"],
            "start,end,showAs,isAllDay,isCancelled",
        )
        self.assertEqual(request.headers["Prefer"], 'outlook.timezone="UTC"')

    def _historical_graph_rechecks_permit_and_rejects_cross_origin_pagination(self) -> None:
        source, capability, consent, permit = calendar_fixture()
        now = datetime.now(UTC).replace(microsecond=0)
        requests: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request.url.path)
            if request.url.path == "/v1.0/me/calendars":
                return httpx.Response(200, json={"value": [{"id": "calendar-a"}]})
            return httpx.Response(200, json={"value": []})

        permit_checks = 0

        def permit_resolver() -> ContextCollectionPermit:
            nonlocal permit_checks
            permit_checks += 1
            if permit_checks > 1:
                raise PermissionError("revoked during poll")
            return permit

        adapter = MicrosoftGraphCalendarAdapter(
            source=source,
            capability=capability,
            consent=consent,
            signing_secret=SECRET,
            provider=MicrosoftGraphCalendarProvider(
                http_client=httpx.Client(transport=httpx.MockTransport(handler))
            ),
            permit_resolver=permit_resolver,
            clock=lambda: now,
        )
        with self.assertRaisesRegex(PermissionError, "revoked during poll"):
            adapter.collect(
                access_token="fixture",
                window_from=now,
                window_to=now + timedelta(days=7),
            )
        self.assertEqual(requests, ["/v1.0/me/calendars"])

        def hostile_pagination(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"value": [], "@odata.nextLink": "https://attacker.example/token"},
            )

        provider = MicrosoftGraphCalendarProvider(
            http_client=httpx.Client(transport=httpx.MockTransport(hostile_pagination))
        )
        with self.assertRaisesRegex(MicrosoftGraphProtocolError, "trusted origin"):
            provider.read_availability(
                access_token="fixture",
                window_from=now,
                window_to=now + timedelta(days=1),
            )

    def test_calendar_activation_is_provider_neutral_and_local_only(self) -> None:
        source, capability, consent, permit = calendar_fixture()
        bundle = CalendarContextActivationBundle(
            source=source,
            capability=capability,
            consent=consent,
            owner_activation_ref=consent.authorization_ref,
        )
        self.assertEqual(bundle.source_access_mode, "manual_owner_file")
        self.assertEqual(consent.data_policy.privacy_class, PrivacyClass.LOCAL_ONLY)
        self.assertFalse(consent.data_policy.memory_eligible)
        self.assertFalse(consent.data_policy.training_eligible)
        self.assertFalse(consent.data_policy.cloud_eligible)
        self.assertNotIn("outlook", CalendarAvailabilityWindow.model_json_schema().__str__().lower())
        with self.assertRaisesRegex(ValidationError, "exact Calendar scope"):
            CalendarContextActivationBundle(
                source=source.model_copy(update={
                    "provider_id": "microsoft-graph", "content_hash": ""
                }),
                capability=capability,
                consent=consent,
                owner_activation_ref=consent.authorization_ref,
            )

        replacement_source = source.model_copy(
            update={
                "provider_id": "replacement-calendar-provider",
                "adapter_version": "replacement-calendar-v1",
                "content_hash": "",
            }
        )
        interval = CalendarBusyInterval(
            starts_at=datetime.now(UTC).replace(microsecond=0),
            ends_at=datetime.now(UTC).replace(microsecond=0) + timedelta(hours=1),
            availability="busy",
            is_all_day=False,
        )
        graph_value = CalendarAvailabilityWindow(busy_intervals=(interval,))
        class ReplacementCalendarProvider:
            def read_all_calendar_availability(self, **kwargs):
                before_read = kwargs.get("before_read")
                if before_read is not None:
                    before_read()
                return graph_value, 1, 1

        replacement_permit = permit.model_copy(
            update={"source": replacement_source, "content_hash": ""}
        )
        replacement_result = CalendarAvailabilityAdapter(
            source=replacement_source,
            capability=capability,
            consent=consent,
            signing_secret=SECRET,
            provider=ReplacementCalendarProvider(),
            permit_resolver=lambda: replacement_permit,
        ).collect(window_from=interval.starts_at, window_to=interval.ends_at)
        replacement_value = CalendarAvailabilityWindow.model_validate(
            replacement_result.draft.value.model_dump(mode="json")
        )
        self.assertEqual(graph_value, replacement_value)
        self.assertEqual(replacement_result.provider_rows_seen, 1)
        self.assertNotEqual(source.provider_id, replacement_source.provider_id)

    def _historical_graph_minimization_deduplicates_and_rejects_ambiguous_flags(self) -> None:
        now = datetime.now(UTC).replace(microsecond=0)
        duplicate = {
            "showAs": "busy",
            "isAllDay": False,
            "isCancelled": False,
            "start": {"dateTime": now.isoformat(), "timeZone": "UTC"},
            "end": {
                "dateTime": (now + timedelta(hours=1)).isoformat(),
                "timeZone": "UTC",
            },
        }
        from apps.calendar_agent.microsoft_graph import minimize_graph_events

        minimized = minimize_graph_events(
            [duplicate, dict(duplicate)],
            window_from=now,
            window_to=now + timedelta(days=1),
        )
        self.assertEqual(len(minimized.busy_intervals), 1)
        with self.assertRaisesRegex(MicrosoftGraphProtocolError, "booleans"):
            minimize_graph_events(
                [duplicate | {"isAllDay": "false"}],
                window_from=now,
                window_to=now + timedelta(days=1),
            )

    def test_wrong_capability_or_ambiguous_ics_fails_closed(self) -> None:
        source, capability, consent, _permit = calendar_fixture()
        with self.assertRaises(ValidationError):
            ContextSourceCapability.model_validate(
                capability.model_dump(exclude={"content_hash"})
                | {"allowed_fields": ("subject", "busy_intervals")}
            )

    def test_manual_runner_requires_core_permit_before_reading_ics(self) -> None:
        _source, _capability, _consent, permit = calendar_fixture()

        class Transport:
            signing_secret = SECRET

            def __init__(self, *, revoke_after: int | None = None):
                self.permit_calls = 0
                self.revoke_after = revoke_after
                self.submitted = []

            def request_permit(self):
                self.permit_calls += 1
                if self.revoke_after is not None and self.permit_calls > self.revoke_after:
                    raise ContextTransportRejected("revoked")
                return permit

            def submit_observation(self, draft):
                self.submitted.append(draft)

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "schedule.ics"
            path.write_bytes(self._ics())
            transport = Transport()
            report = CalendarAgentRunner(transport=transport).import_ics(
                path=path,
                window_from=datetime(2026, 8, 1, tzinfo=UTC),
                window_to=datetime(2026, 12, 31, tzinfo=UTC),
                default_timezone="America/Chicago",
            )
            self.assertEqual(report["status"], "observation_submitted")
            self.assertEqual(transport.permit_calls, 2)
            self.assertEqual(len(transport.submitted), 1)
            self.assertFalse(report["network_provider_used"])
            self.assertFalse(report["source_native_file_copied"])

            revoked = Transport(revoke_after=1)
            blocked = CalendarAgentRunner(transport=revoked).import_ics(
                path=path,
                window_from=datetime(2026, 8, 1, tzinfo=UTC),
                window_to=datetime(2026, 12, 31, tzinfo=UTC),
                default_timezone="America/Chicago",
            )
            self.assertEqual(blocked["status"], "authorization_rejected")
            self.assertEqual(revoked.submitted, [])
        with self.assertRaisesRegex(IcsProtocolError, "DTSTART and DTEND"):
            parse_ics_availability(
                b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nDTSTART:20260825T150000Z\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n",
                window_from=datetime(2026, 8, 1, tzinfo=UTC),
                window_to=datetime(2026, 12, 31, tzinfo=UTC),
            )

    def _historical_token_cache_is_protected_and_scope_downgrade_is_rejected(self) -> None:
        token_set = OAuthTokenSet(
            access_token="sensitive-access-token",
            refresh_token="sensitive-refresh-token",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            granted_scopes=("Calendars.ReadBasic",),
            account_subject="sha256:" + "a" * 64,
            tenant_id=TENANT_ID,
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "outlook-token.dpapi"
            cache = ProtectedOAuthTokenCache(
                path=path, protector=ReversingProtector()
            )
            cache.save(token_set)
            raw = path.read_bytes()
            self.assertNotIn(b"sensitive-access-token", raw)
            self.assertNotIn(b"sensitive-refresh-token", raw)
            self.assertEqual(cache.load(), token_set)
            cache.erase()
            self.assertFalse(path.exists())

        def handler(request: httpx.Request) -> httpx.Response:
            self.assertNotIn("client_secret", request.content.decode())
            return httpx.Response(
                200,
                json={
                    "access_token": "a",
                    "refresh_token": "r",
                    "expires_in": 3600,
                    "scope": "Calendars.Read",
                },
            )

        client = MicrosoftDeviceAuthorizationClient(
            client_id=str(uuid.uuid4()),
            tenant="organizations",
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        with self.assertRaisesRegex(MicrosoftOAuthError, "omitted a required"):
            client.refresh("refresh", required_scopes=GRAPH_DELEGATED_SCOPES)

        def surplus_scope_refresh(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "access_token": "a",
                    "refresh_token": "r",
                    "expires_in": 3600,
                    "scope": "Calendars.ReadBasic Calendars.Read User.Read",
                },
            )

        client = MicrosoftDeviceAuthorizationClient(
            client_id=str(uuid.uuid4()),
            tenant="organizations",
            http_client=httpx.Client(
                transport=httpx.MockTransport(surplus_scope_refresh)
            ),
        )
        with self.assertRaisesRegex(MicrosoftOAuthError, "unapproved delegated"):
            client.refresh("refresh", required_scopes=GRAPH_DELEGATED_SCOPES)

        def successful_refresh(request: httpx.Request) -> httpx.Response:
            self.assertNotIn("client_secret", request.content.decode())
            return httpx.Response(
                200,
                json={
                    "access_token": "next-access",
                    "refresh_token": "next-refresh",
                    "expires_in": 3600,
                    "scope": "Calendars.ReadBasic",
                },
            )

        client = MicrosoftDeviceAuthorizationClient(
            client_id=str(uuid.uuid4()),
            tenant="organizations",
            http_client=httpx.Client(transport=httpx.MockTransport(successful_refresh)),
        )
        refreshed = client.refresh(
            "refresh",
            required_scopes=GRAPH_DELEGATED_SCOPES,
            account_subject=token_set.account_subject,
            tenant_id=token_set.tenant_id,
        )
        self.assertEqual(refreshed.account_subject, token_set.account_subject)
        self.assertEqual(refreshed.tenant_id, token_set.tenant_id)

    def _historical_disconnect_serializes_with_refresh_and_removes_failed_temporaries(self) -> None:
        token_set = OAuthTokenSet(
            access_token="sensitive-access-token",
            refresh_token="sensitive-refresh-token",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            granted_scopes=("Calendars.ReadBasic",),
            account_subject=ACCOUNT_BINDING,
            tenant_id=TENANT_ID,
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "outlook-token.dpapi"
            cache = ProtectedOAuthTokenCache(path=path, protector=ReversingProtector())
            disconnect_cache = ProtectedOAuthTokenCache(
                path=path, protector=ReversingProtector()
            )
            cache.save(token_set)
            operation_started = threading.Event()
            allow_refresh_save = threading.Event()

            def refresh_then_save() -> None:
                with cache.operation():
                    self.assertEqual(cache.load_unlocked(), token_set)
                    operation_started.set()
                    self.assertTrue(allow_refresh_save.wait(timeout=5))
                    cache.save_unlocked(token_set)

            refresh_thread = threading.Thread(target=refresh_then_save)
            refresh_thread.start()
            self.assertTrue(operation_started.wait(timeout=5))
            disconnect_thread = threading.Thread(target=disconnect_cache.erase)
            disconnect_thread.start()
            self.assertTrue(disconnect_thread.is_alive())
            allow_refresh_save.set()
            refresh_thread.join(timeout=5)
            disconnect_thread.join(timeout=5)
            self.assertFalse(refresh_thread.is_alive())
            self.assertFalse(disconnect_thread.is_alive())
            self.assertFalse(path.exists())

            cache.save(token_set)
            with mock.patch(
                "apps.calendar_agent.oauth.os.replace",
                side_effect=OSError("injected replace failure"),
            ):
                with self.assertRaisesRegex(OSError, "injected replace failure"):
                    cache.save(token_set)
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])
            cache.erase()

    def _historical_mailbox_binding_is_opaque_and_requires_calendar_permission(self) -> None:
        provider_calendar_id = "provider-private-calendar-identifier"

        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.params["$select"], "id")
            return httpx.Response(200, json={"id": provider_calendar_id})

        binding = MicrosoftGraphCalendarProvider(
            http_client=httpx.Client(transport=httpx.MockTransport(handler))
        ).read_opaque_account_binding(access_token="fixture")
        self.assertEqual(
            binding,
            "sha256:" + hashlib.sha256(provider_calendar_id.encode()).hexdigest(),
        )
        self.assertNotIn(provider_calendar_id, binding)

    def _historical_runner_requires_core_permit_before_every_graph_request(self) -> None:
        source, _capability, _consent, permit = calendar_fixture()
        now = datetime.now(UTC).replace(microsecond=0)
        graph_paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            graph_paths.append(request.url.path)
            if request.url.path == "/v1.0/me/calendar":
                return httpx.Response(200, json={"id": "mailbox-binding"})
            if request.url.path == "/v1.0/me/calendars":
                return httpx.Response(200, json={"value": [{"id": "calendar-a"}]})
            return httpx.Response(200, json={"value": []})

        class Transport:
            signing_secret = SECRET

            def __init__(self):
                self.permit_calls = 0
                self.submitted = []

            def request_permit(self):
                self.permit_calls += 1
                return permit

            def submit_observation(self, draft):
                self.submitted.append(draft)

            def submit_health(self, _draft):
                raise AssertionError("healthy run must not submit health")

        token = OAuthTokenSet(
            access_token="fixture-access",
            refresh_token="fixture-refresh",
            expires_at=now + timedelta(hours=1),
            granted_scopes=("Calendars.ReadBasic",),
            account_subject=ACCOUNT_BINDING,
            tenant_id=TENANT_ID,
        )
        with tempfile.TemporaryDirectory() as temporary:
            cache = ProtectedOAuthTokenCache(
                path=Path(temporary) / "token.dpapi",
                protector=ReversingProtector(),
            )
            cache.save(token)
            transport = Transport()
            runner = CalendarAgentRunner(
                transport=transport,
                oauth_client=MicrosoftDeviceAuthorizationClient(
                    client_id=str(uuid.uuid4()),
                    tenant=TENANT_ID,
                    http_client=httpx.Client(transport=httpx.MockTransport(handler)),
                ),
                token_cache=cache,
                provider=MicrosoftGraphCalendarProvider(
                    http_client=httpx.Client(transport=httpx.MockTransport(handler))
                ),
                clock=lambda: now,
            )
            report = runner.run_once()
            self.assertEqual(report["status"], "observation_submitted")
            self.assertEqual(
                graph_paths,
                [
                    "/v1.0/me/calendar",
                    "/v1.0/me/calendars",
                    "/v1.0/me/calendars/calendar-a/calendarView",
                ],
            )
            self.assertEqual(transport.permit_calls, 4)
            self.assertEqual(len(transport.submitted), 1)

            graph_paths.clear()
            cache.save(token.__class__(
                access_token=token.access_token,
                refresh_token=token.refresh_token,
                expires_at=token.expires_at,
                granted_scopes=("Calendars.ReadBasic", "Calendars.Read"),
                account_subject=token.account_subject,
                tenant_id=token.tenant_id,
            ))

            def surplus_refresh(_request: httpx.Request) -> httpx.Response:
                return httpx.Response(200, json={
                    "access_token": "broader-access",
                    "refresh_token": "broader-refresh",
                    "expires_in": 3600,
                    "scope": "Calendars.ReadBasic Calendars.Read",
                })

            surplus_runner = CalendarAgentRunner(
                transport=Transport(),
                oauth_client=MicrosoftDeviceAuthorizationClient(
                    client_id=str(uuid.uuid4()),
                    tenant=TENANT_ID,
                    http_client=httpx.Client(
                        transport=httpx.MockTransport(surplus_refresh)
                    ),
                ),
                token_cache=cache,
                provider=runner.provider,
                clock=lambda: now,
            )
            self.assertEqual(
                surplus_runner.run_once()["status"], "oauth_scope_rejected"
            )
            self.assertEqual(graph_paths, [])
            cache.save(token)

            graph_paths.clear()
            cache.save(token.__class__(
                access_token=token.access_token,
                refresh_token=token.refresh_token,
                expires_at=token.expires_at,
                granted_scopes=token.granted_scopes,
                account_subject="sha256:" + "f" * 64,
                tenant_id=TENANT_ID,
            ))
            mismatched = CalendarAgentRunner(
                transport=Transport(),
                oauth_client=runner.oauth_client,
                token_cache=cache,
                provider=runner.provider,
                clock=lambda: now,
            ).run_once()
            self.assertEqual(mismatched["status"], "mailbox_binding_mismatch")
            self.assertEqual(graph_paths, [])
            cache.save(token)

            class RevokedTransport(Transport):
                def request_permit(self):
                    self.permit_calls += 1
                    if self.permit_calls > 1:
                        raise ContextTransportRejected("revoked")
                    return permit

            graph_paths.clear()
            revoked = RevokedTransport()
            blocked = CalendarAgentRunner(
                transport=revoked,
                oauth_client=runner.oauth_client,
                token_cache=cache,
                provider=runner.provider,
                clock=lambda: now,
            ).run_once()
            self.assertEqual(blocked["status"], "authorization_rejected")
            self.assertEqual(graph_paths, [])


@unittest.skipUnless(DATABASE_URL, "HAVRE_TEST_DATABASE_URL is required")
class Stage12CalendarPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        assert DATABASE_URL is not None
        apply_migrations(DATABASE_URL, ROOT / "db" / "migrations")
        cls.repository = PostgresRepository(DATABASE_URL)
        cls.repository.open()
        cls.owner = uuid.uuid4()
        cls.repository.bootstrap_owner_and_identity(
            owner_id=cls.owner,
            identity=IdentityLoader(ROOT / "identity").load(),
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.repository.close()

    def test_calendar_bundle_and_minimized_observation_are_durable(self) -> None:
        source, capability, consent, _fixture_permit = calendar_fixture(self.owner)
        store = Stage12ContextStore(
            repository=self.repository,
            owner_id=self.owner,
            device_secret_resolver=lambda binding: (
                SECRET if binding == source.device_binding_id
                else (_ for _ in ()).throw(KeyError(binding))
            ),
        )
        bundle = CalendarContextActivationBundle(
            source=source,
            capability=capability,
            consent=consent,
            owner_activation_ref=consent.authorization_ref,
        )
        source_state, capability_state = store.activate_calendar_bundle(bundle)
        self.assertEqual(source_state.status, "enabled")
        self.assertEqual(capability_state.status, "enabled")
        with self.repository.pool.connection() as connection:
            with self.assertRaises(psycopg.errors.CheckViolation) as raised:
                with connection.transaction():
                    connection.execute("SET LOCAL session_replication_role='replica'")
                    connection.execute(
                        """
                        UPDATE havre.context_sources SET provider_id='microsoft-graph'
                        WHERE owner_id=%s AND source_instance_id=%s
                        """,
                        (self.owner, source.source_instance_id),
                    )
        self.assertEqual(
            raised.exception.diag.constraint_name,
            "context_sources_provider_profile_check",
        )
        now = datetime.now(UTC).replace(microsecond=0)

        class Provider:
            def read_all_calendar_availability(self, **kwargs):
                kwargs["before_read"]()
                return CalendarAvailabilityWindow(busy_intervals=(
                    CalendarBusyInterval(
                        starts_at=now + timedelta(hours=1),
                        ends_at=now + timedelta(hours=2),
                        availability="busy",
                        is_all_day=False,
                    ),
                    CalendarBusyInterval(
                        starts_at=now + timedelta(days=100, hours=1),
                        ends_at=now + timedelta(days=100, hours=2),
                        availability="tentative",
                        is_all_day=False,
                    ),
                )), 1, 1

        adapter = CalendarAvailabilityAdapter(
            source=source,
            capability=capability,
            consent=consent,
            signing_secret=SECRET,
            provider=Provider(),
            permit_resolver=lambda: store.current_collection_permit(
                source_instance_id=source.source_instance_id,
                device_binding_id=source.device_binding_id,
            ),
        )
        collection = adapter.collect(window_from=now, window_to=now + timedelta(days=120))
        ingested = store.ingest(collection.draft)
        self.assertEqual(
            ingested.observation.observation_kind,
            "calendar_availability_window",
        )
        self.assertEqual(len(ingested.observation.value.busy_intervals), 2)
        self.assertEqual(
            ingested.observation.fresh_until,
            ingested.observation.occurred_to,
        )
        with self.repository.pool.connection() as connection:
            row = connection.execute(
                """
                SELECT value::text AS value,canonical_content_material,
                       draft_signing_material
                FROM havre.life_context_observations
                WHERE owner_id=%s AND observation_id=%s
                """,
                (self.owner, ingested.observation.observation_id),
            ).fetchone()
        serialized = " ".join(str(value) for value in row.values()).lower()
        for forbidden in (
            "private course title", "private room", "provider-private-id",
        ):
            self.assertNotIn(forbidden, serialized)
        selected = store.select_calendar_context(
            query_text="我明天什么时候有空？",
            maximum_privacy_class=PrivacyClass.LOCAL_ONLY,
        )
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].section_type, "calendar_availability")
        self.assertIn(
            f"context-observation/{ingested.observation.observation_id}",
            selected[0].source_refs,
        )
        self.assertNotIn("Private course title", selected[0].content_text)
        late_date = (now + timedelta(days=100)).date().isoformat()
        late = store.select_calendar_context(
            query_text=f"我的课表在 {late_date} 是什么？",
            maximum_privacy_class=PrivacyClass.LOCAL_ONLY,
        )
        self.assertEqual(len(late), 1)
        self.assertIn((now + timedelta(days=100, hours=1)).isoformat(), late[0].content_text)
        self.assertNotIn((now + timedelta(hours=1)).isoformat(), late[0].content_text)
        outside_date = (ingested.observation.occurred_to + timedelta(days=30)).date()
        self.assertEqual(
            store.select_calendar_context(
                query_text=f"我的课表在 {outside_date.isoformat()} 是什么？",
                maximum_privacy_class=PrivacyClass.LOCAL_ONLY,
            ),
            (),
        )
        self.assertEqual(
            store.select_calendar_context(
                query_text="我明天什么时候有空？",
                maximum_privacy_class=PrivacyClass.NORMAL,
            ),
            (),
        )
        self.assertEqual(
            store.select_calendar_context(
                query_text="我刚看完一部电影",
                maximum_privacy_class=PrivacyClass.LOCAL_ONLY,
            ),
            (),
        )
        for irrelevant in ("今天心情很差", "when did we discuss Strong Brain?"):
            self.assertEqual(
                store.select_calendar_context(
                    query_text=irrelevant,
                    maximum_privacy_class=PrivacyClass.LOCAL_ONLY,
                ),
                (),
            )
        with self.assertRaisesRegex(Exception, "owner-initiated import policy"):
            store.ingest(adapter.collect(
                window_from=now,
                window_to=consent.expires_at + timedelta(seconds=1),
            ).draft)
        with self.repository.pool.connection() as connection, connection.transaction():
            connection.execute("SET LOCAL session_replication_role='replica'")
            connection.execute(
                """DELETE FROM havre.context_source_health_records
                   WHERE owner_id=%s AND last_successful_observation_id=%s""",
                (self.owner, ingested.observation.observation_id),
            )
        self.assertEqual(
            store.select_calendar_context(
                query_text="我的课表是什么？",
                maximum_privacy_class=PrivacyClass.LOCAL_ONLY,
            ),
            (),
        )
        self.repository.erase_source_event_derivatives(
            owner_id=self.owner,
            source_event_id=ingested.observation.event_id,
        )

    def test_maximum_512_interval_calendar_window_is_durable(self) -> None:
        source, capability, consent, _permit = calendar_fixture(self.owner)
        store = Stage12ContextStore(
            repository=self.repository,
            owner_id=self.owner,
            device_secret_resolver=lambda _binding: SECRET,
        )
        store.activate_calendar_bundle(CalendarContextActivationBundle(
            source=source,
            capability=capability,
            consent=consent,
            owner_activation_ref=consent.authorization_ref,
        ))
        starts = datetime.now(UTC).replace(microsecond=0)
        intervals = tuple(
            CalendarBusyInterval(
                starts_at=starts + timedelta(hours=index * 8),
                ends_at=starts + timedelta(hours=index * 8 + 1),
                availability="working_elsewhere",
                is_all_day=False,
            )
            for index in range(512)
        )

        class Provider:
            def read_all_calendar_availability(self, **kwargs):
                kwargs["before_read"]()
                return CalendarAvailabilityWindow(busy_intervals=intervals), 512, 1

        adapter = CalendarAvailabilityAdapter(
            source=source,
            capability=capability,
            consent=consent,
            signing_secret=SECRET,
            provider=Provider(),
            permit_resolver=lambda: store.current_collection_permit(
                source_instance_id=source.source_instance_id,
                device_binding_id=source.device_binding_id,
            ),
        )
        ingested = store.ingest(adapter.collect(
            window_from=starts,
            window_to=starts + timedelta(days=171),
        ).draft)
        with self.repository.pool.connection() as connection:
            row = connection.execute(
                """SELECT length(draft_signing_material) AS draft_length,
                          length(canonical_content_material) AS canonical_length
                   FROM havre.life_context_observations
                   WHERE owner_id=%s AND observation_id=%s""",
                (self.owner, ingested.observation.observation_id),
            ).fetchone()
        self.assertEqual(len(ingested.observation.value.busy_intervals), 512)
        self.assertLessEqual(row["draft_length"], 262_144)
        self.assertLessEqual(row["canonical_length"], 262_144)
        self.repository.erase_source_event_derivatives(
            owner_id=self.owner,
            source_event_id=ingested.observation.event_id,
        )

    def test_calendar_revocation_stops_reads_and_erasure_closes_derivatives(self) -> None:
        source, capability, consent, _fixture_permit = calendar_fixture(self.owner)
        store = Stage12ContextStore(
            repository=self.repository,
            owner_id=self.owner,
            device_secret_resolver=lambda binding: (
                SECRET if binding == source.device_binding_id
                else (_ for _ in ()).throw(KeyError(binding))
            ),
        )
        store.activate_calendar_bundle(CalendarContextActivationBundle(
            source=source,
            capability=capability,
            consent=consent,
            owner_activation_ref=consent.authorization_ref,
        ))
        now = datetime.now(UTC).replace(microsecond=0)

        class Provider:
            def __init__(self):
                self.reads = 0

            def read_all_calendar_availability(self, **kwargs):
                kwargs["before_read"]()
                self.reads += 1
                return CalendarAvailabilityWindow(busy_intervals=(CalendarBusyInterval(
                    starts_at=now + timedelta(hours=1),
                    ends_at=now + timedelta(hours=2),
                    availability="busy",
                    is_all_day=False,
                ),)), 1, 1

        provider = Provider()
        adapter = CalendarAvailabilityAdapter(
            source=source,
            capability=capability,
            consent=consent,
            signing_secret=SECRET,
            provider=provider,
            permit_resolver=lambda: store.current_collection_permit(
                source_instance_id=source.source_instance_id,
                device_binding_id=source.device_binding_id,
            ),
        )
        observation = store.ingest(adapter.collect(
            window_from=now, window_to=now + timedelta(days=7)
        ).draft).observation

        revoked = ConsentScopeRevision.model_validate(
            consent.model_dump(exclude={"content_hash"}) | {
                "consent_scope_revision_id": uuid.uuid4(),
                "revision": 2,
                "status": "revoked",
                "effective_at": datetime.now(UTC),
            }
        )
        store.save_consent(revoked)
        reads_before = provider.reads
        blocked_adapter = CalendarAvailabilityAdapter(
            source=source,
            capability=capability,
            consent=consent,
            signing_secret=SECRET,
            provider=provider,
            permit_resolver=lambda: store.current_collection_permit(
                source_instance_id=source.source_instance_id,
                device_binding_id=source.device_binding_id,
            ),
        )
        with self.assertRaisesRegex(Exception, "consent"):
            blocked_adapter.collect(window_from=now, window_to=now + timedelta(days=7))
        self.assertEqual(provider.reads, reads_before)

        self.repository.erase_source_event_derivatives(
            owner_id=self.owner,
            source_event_id=observation.event_id,
        )
        with self.repository.pool.connection() as connection:
            counts = connection.execute(
                """
                SELECT
                  (SELECT count(*) FROM havre.life_context_observations
                   WHERE owner_id=%s AND observation_id=%s) AS observations,
                  (SELECT count(*) FROM havre.context_source_health_records
                   WHERE owner_id=%s AND last_successful_observation_id=%s) AS health
                """,
                (
                    self.owner, observation.observation_id,
                    self.owner, observation.observation_id,
                ),
            ).fetchone()
        self.assertEqual(counts, {"observations": 0, "health": 0})
        self.assertEqual(self.repository.audit_provenance_integrity(), [])

    def test_database_rejects_calendar_provider_content_even_without_triggers(self) -> None:
        source, capability, consent, _fixture_permit = calendar_fixture(self.owner)
        store = Stage12ContextStore(
            repository=self.repository,
            owner_id=self.owner,
            device_secret_resolver=lambda _binding: SECRET,
        )
        store.activate_calendar_bundle(CalendarContextActivationBundle(
            source=source,
            capability=capability,
            consent=consent,
            owner_activation_ref=consent.authorization_ref,
        ))
        now = datetime.now(UTC).replace(microsecond=0)

        class Provider:
            def read_all_calendar_availability(self, **kwargs):
                kwargs["before_read"]()
                return CalendarAvailabilityWindow(busy_intervals=()), 0, 1

        adapter = CalendarAvailabilityAdapter(
            source=source,
            capability=capability,
            consent=consent,
            signing_secret=SECRET,
            provider=Provider(),
            permit_resolver=lambda: store.current_collection_permit(
                source_instance_id=source.source_instance_id,
                device_binding_id=source.device_binding_id,
            ),
        )
        observation = store.ingest(adapter.collect(
            window_from=now, window_to=now + timedelta(days=7)
        ).draft).observation
        with self.repository.pool.connection() as connection:
            with self.assertRaises(psycopg.errors.CheckViolation) as raised:
                with connection.transaction():
                    connection.execute("SET LOCAL session_replication_role='replica'")
                    connection.execute(
                        """
                        INSERT INTO havre.life_context_observations (
                            observation_id,draft_id,schema_version,owner_id,
                            source_instance_id,capability_revision_id,capability_id,
                            observation_kind,observation_schema_version,value,
                            occurred_from,occurred_to,source_observed_at,ingested_at,
                            fresh_until,retention_expires_at,consent_scope_revision_id,
                            sampling_policy_version,retention_policy_version,
                            adapter_version,privacy_class,memory_eligible,
                            training_eligible,cloud_eligible,policy_version,
                            policy_revision_id,policy_decision_source,
                            policy_authorization_ref,event_id,trace_id,idempotency_key,
                            draft_content_hash,device_binding_id,draft_signing_material,
                            device_signature,measurement_quality,clock_quality,
                            limitations,canonical_content_material,content_hash
                        )
                        SELECT gen_random_uuid(),gen_random_uuid(),schema_version,owner_id,
                            source_instance_id,capability_revision_id,capability_id,
                            observation_kind,observation_schema_version,
                            value || '{"subject":"PRIVATE provider content"}'::jsonb,
                            occurred_from,occurred_to,source_observed_at,ingested_at,
                            fresh_until,retention_expires_at,consent_scope_revision_id,
                            sampling_policy_version,retention_policy_version,
                            adapter_version,privacy_class,memory_eligible,
                            training_eligible,cloud_eligible,policy_version,
                            policy_revision_id,policy_decision_source,
                            policy_authorization_ref,gen_random_uuid(),trace_id,
                            'forged-provider-content-' || gen_random_uuid()::text,
                            draft_content_hash,device_binding_id,draft_signing_material,
                            device_signature,measurement_quality,clock_quality,
                            limitations,canonical_content_material,content_hash
                        FROM havre.life_context_observations
                        WHERE owner_id=%s AND observation_id=%s
                        """,
                        (self.owner, observation.observation_id),
                    )
        self.assertEqual(
            raised.exception.diag.constraint_name,
            "life_context_observation_exact_kind_value_check",
        )

    def test_whole_calendar_source_erasure_is_tombstoned_and_idempotent(self) -> None:
        source, capability, consent, permit = calendar_fixture(self.owner)
        context_store = Stage12ContextStore(
            repository=self.repository,
            owner_id=self.owner,
            device_secret_resolver=lambda binding: (
                SECRET if binding == source.device_binding_id
                else (_ for _ in ()).throw(KeyError(binding))
            ),
        )
        context_store.activate_calendar_bundle(CalendarContextActivationBundle(
            source=source,
            capability=capability,
            consent=consent,
            owner_activation_ref=consent.authorization_ref,
        ))
        with self.repository.pool.connection() as connection:
            registration_event_id = connection.execute(
                """
                SELECT registration_event_id FROM havre.context_sources
                WHERE owner_id=%s AND source_instance_id=%s
                """,
                (self.owner, source.source_instance_id),
            ).fetchone()["registration_event_id"]
        now = datetime.now(UTC).replace(microsecond=0)

        class FixtureProvider:
            def read_all_calendar_availability(self, **kwargs):
                before_read = kwargs.get("before_read")
                if before_read is not None:
                    before_read()
                return CalendarAvailabilityWindow(busy_intervals=()), 0, 1

        draft = CalendarAvailabilityAdapter(
            source=source,
            capability=capability,
            consent=consent,
            signing_secret=SECRET,
            provider=FixtureProvider(),
            permit_resolver=lambda: permit,
            clock=lambda: now,
        ).collect(window_from=now, window_to=now + timedelta(days=7)).draft
        observation = context_store.ingest(draft).observation

        with tempfile.TemporaryDirectory() as temporary:
            ledger = ErasureLedger(Path(temporary) / "erasure.sqlite3")
            operations = Stage10PostgresStore(
                repository=self.repository,
                erasure_repository=self.repository,
                owner_id=self.owner,
            )
            result = operations.erase_context_source(
                source_instance_id=source.source_instance_id,
                ledger=ledger,
            )
            self.assertTrue(result["absence_verified"])
            self.assertFalse(result["already_erased"])
            directive = ledger.verify()[-1]
            self.assertEqual(directive.scope, "context_source_and_derived")
            self.assertEqual(directive.source_event_id, registration_event_id)
            repeated = operations.erase_context_source(
                source_instance_id=source.source_instance_id,
                ledger=ledger,
            )
            self.assertTrue(repeated["already_erased"])
            self.assertEqual(
                repeated["directive_sequence"], result["directive_sequence"]
            )

        with self.repository.pool.connection() as connection:
            for table in (
                "context_sources",
                "context_device_bindings",
                "context_source_state_revisions",
                "context_source_capabilities",
                "context_consent_scope_revisions",
                "life_context_observations",
                "context_source_health_records",
            ):
                count = connection.execute(
                    f"SELECT count(*) AS count FROM havre.{table} "
                    "WHERE owner_id=%s AND source_instance_id=%s",
                    (self.owner, source.source_instance_id),
                ).fetchone()["count"]
                self.assertEqual(count, 0, table)
            capability_states = connection.execute(
                """
                SELECT count(*) AS count FROM havre.context_capability_state_revisions
                WHERE owner_id=%s AND capability_revision_id=%s
                """,
                (self.owner, capability.capability_revision_id),
            ).fetchone()["count"]
            self.assertEqual(capability_states, 0)
            tombstone = connection.execute(
                """
                SELECT * FROM havre.context_source_erasure_tombstones
                WHERE owner_id=%s AND source_instance_id=%s
                """,
                (self.owner, source.source_instance_id),
            ).fetchone()
            self.assertIsNotNone(tombstone)
            self.assertIsNone(connection.execute(
                "SELECT 1 FROM havre.events WHERE owner_id=%s AND event_id=%s",
                (self.owner, observation.event_id),
            ).fetchone())
        with self.assertRaisesRegex(Exception, "erased context source identity"):
            context_store.activate_calendar_bundle(CalendarContextActivationBundle(
                source=source,
                capability=capability,
                consent=consent,
                owner_activation_ref=consent.authorization_ref,
            ))

    def test_context_source_erasure_directive_replays_against_pre_erasure_state(self) -> None:
        source, capability, consent, _permit = calendar_fixture(self.owner)
        context_store = Stage12ContextStore(
            repository=self.repository,
            owner_id=self.owner,
            device_secret_resolver=lambda _binding: SECRET,
        )
        context_store.activate_calendar_bundle(CalendarContextActivationBundle(
            source=source,
            capability=capability,
            consent=consent,
            owner_activation_ref=consent.authorization_ref,
        ))
        with self.repository.pool.connection() as connection:
            registration_event_id = connection.execute(
                """
                SELECT registration_event_id FROM havre.context_sources
                WHERE owner_id=%s AND source_instance_id=%s
                """,
                (self.owner, source.source_instance_id),
            ).fetchone()["registration_event_id"]
        with tempfile.TemporaryDirectory() as temporary:
            ledger = ErasureLedger(Path(temporary) / "erasure.sqlite3")
            directive = ledger.append(
                owner_id=self.owner,
                source_event_id=registration_event_id,
                scope="context_source_and_derived",
            )
            operations = Stage10PostgresStore(
                repository=self.repository,
                erasure_repository=self.repository,
                owner_id=self.owner,
            )
            replay = operations.replay_erasure_directives(
                ledger=ledger,
                after_sequence=0,
                restore_id=f"calendar-restore-{uuid.uuid4()}",
            )
            self.assertEqual(replay["directives_applied"], 1)
            self.assertTrue(replay["absence_verified"])
            self.assertGreaterEqual(ledger.completed_sequence(), directive.sequence)
        with self.repository.pool.connection() as connection:
            self.assertIsNone(connection.execute(
                """
                SELECT 1 FROM havre.context_sources
                WHERE owner_id=%s AND source_instance_id=%s
                """,
                (self.owner, source.source_instance_id),
            ).fetchone())
            self.assertIsNotNone(connection.execute(
                """
                SELECT 1 FROM havre.context_source_erasure_tombstones
                WHERE owner_id=%s AND source_instance_id=%s
                """,
                (self.owner, source.source_instance_id),
            ).fetchone())


if __name__ == "__main__":
    unittest.main()
