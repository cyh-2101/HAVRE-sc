"""Durable Stage 12 ambient-context source, consent, and ingest boundary."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
import re
from typing import Callable
from uuid import UUID
from zoneinfo import ZoneInfo

from psycopg.types.json import Jsonb

from companion.events import (
    ContextCapabilityLifecyclePayload,
    ContextConsentLifecyclePayload,
    ContextSourceLifecyclePayload,
    EventEnvelope,
    EventType,
    LifeContextObservedPayload,
)
from companion.hashing import canonical_json, content_hash
from companion.ids import new_trace_id, uuid7
from companion.life_context import (
    CalendarContextActivationBundle,
    ConsentScopeRevision,
    ContextIngestResult,
    ContextObservationDraft,
    ContextSourceHealthDraft,
    ContextSourceCapability,
    ContextSourceDescriptor,
    ContextSourceHealthV2,
    ContextSourceStateRevision,
    ContextCapabilityStateRevision,
    ContextCollectionPermit,
    ContextCollectionPermitRequest,
    WindowsContextActivationBundle,
    LifeContextObservationV2,
    verify_observation_draft_signature,
    verify_health_draft_signature,
    verify_collection_permit_request_signature,
)
from companion.policy import DataPolicy
from companion.policy import PrivacyClass
from companion.policy.models import PRIVACY_RESTRICTION_ORDER
from companion.context.models import PersonalContextItem
from companion.persistence.postgres import PostgresRepository


class ContextIngestRejected(ValueError):
    """A draft failed a fail-closed source/consent/clock boundary."""


class ContextIdempotencyConflict(ContextIngestRejected):
    """An idempotency key was reused for different minimized material."""


def require_isolated_context_operator(database_url: str) -> str:
    """Fail unless the actual login has only the narrow context-operator role."""

    import psycopg

    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            """
            SELECT current_user AS login,
                   rolsuper,
                   pg_has_role(current_user,'havre_context_operator','MEMBER') AS context_role,
                   pg_has_role(current_user,'havre_application','MEMBER') AS app_role,
                   pg_has_role(current_user,'havre_release_operator','MEMBER') AS release_role,
                   pg_has_role(current_user,'havre_privileged_erasure','MEMBER') AS erasure_role,
                   pg_has_role(current_user,'havre_restore_operator','MEMBER') AS restore_role
            FROM pg_roles WHERE rolname=current_user
            """
        ).fetchone()
    if row is None:
        raise ContextIngestRejected(
            "context credential must be an isolated context operator login"
        )
    (
        login, is_superuser, has_context, has_app, has_release,
        has_erasure, has_restore,
    ) = row
    if (
        is_superuser
        or not has_context
        or has_app
        or has_release
        or has_erasure
        or has_restore
    ):
        raise ContextIngestRejected(
            "context credential must be an isolated context operator login"
        )
    return login


class Stage12ContextStore:
    def __init__(
        self,
        *,
        repository: PostgresRepository,
        owner_id: UUID,
        device_secret_resolver: Callable[[str], bytes],
        owner_timezone: str = "UTC",
    ) -> None:
        self.repository = repository
        self.owner_id = owner_id
        self.device_secret_resolver = device_secret_resolver
        self.owner_timezone = ZoneInfo(owner_timezone)

    def activate_windows_bundle(
        self, bundle: WindowsContextActivationBundle
    ) -> tuple[ContextSourceStateRevision, ContextCapabilityStateRevision]:
        return self._activate_bundle(bundle)

    def activate_calendar_bundle(
        self, bundle: CalendarContextActivationBundle
    ) -> tuple[ContextSourceStateRevision, ContextCapabilityStateRevision]:
        return self._activate_bundle(bundle)

    def select_calendar_context(
        self, *, query_text: str, maximum_privacy_class: PrivacyClass
    ) -> tuple[PersonalContextItem, ...]:
        """Select fresh availability only when the current turn actually asks for it."""
        if (
            PRIVACY_RESTRICTION_ORDER[maximum_privacy_class]
            < PRIVACY_RESTRICTION_ORDER[PrivacyClass.LOCAL_ONLY]
        ):
            return ()
        normalized = query_text.casefold()
        schedule_intents = (
            "calendar", "schedule", "class", "course", "meeting", "busy", "free",
            "availability", "日程", "课程", "课表", "有空", "忙不忙", "几点", "安排",
        )
        if not any(intent in normalized for intent in schedule_intents):
            return ()
        now = datetime.now(UTC)
        with self.repository.pool.connection() as connection:
            row = connection.execute(
                """SELECT observation.*
                   FROM havre.life_context_observations observation
                   JOIN LATERAL (
                     SELECT status FROM havre.context_source_state_revisions state
                     WHERE state.owner_id=observation.owner_id
                       AND state.source_instance_id=observation.source_instance_id
                       AND state.effective_at<=%s
                     ORDER BY state.revision DESC LIMIT 1
                   ) source_state ON true
                   JOIN LATERAL (
                     SELECT status FROM havre.context_capability_state_revisions state
                     WHERE state.owner_id=observation.owner_id
                       AND state.capability_revision_id=observation.capability_revision_id
                       AND state.effective_at<=%s
                     ORDER BY state.revision DESC LIMIT 1
                   ) capability_state ON true
                   JOIN havre.context_consent_scope_revisions consent
                     ON consent.owner_id=observation.owner_id
                    AND consent.consent_scope_revision_id=observation.consent_scope_revision_id
                   JOIN LATERAL (
                     SELECT health.status,health.last_successful_observation_id
                     FROM havre.context_source_health_records health
                     WHERE health.owner_id=observation.owner_id
                       AND health.source_instance_id=observation.source_instance_id
                       AND health.capability_revision_id=observation.capability_revision_id
                     ORDER BY health.checked_at DESC LIMIT 1
                   ) latest_health ON true
                   WHERE observation.owner_id=%s
                     AND observation.observation_kind='calendar_availability_window'
                     AND observation.fresh_until>%s
                     AND observation.retention_expires_at>%s
                     AND source_state.status='enabled'
                     AND capability_state.status='enabled'
                     AND consent.status='active'
                     AND consent.effective_at<=%s AND consent.expires_at>%s
                     AND NOT EXISTS (
                       SELECT 1 FROM havre.context_consent_scope_revisions newer
                       WHERE newer.owner_id=consent.owner_id
                         AND newer.consent_scope_id=consent.consent_scope_id
                         AND newer.revision>consent.revision
                     )
                     AND latest_health.status='healthy'
                     AND latest_health.last_successful_observation_id=observation.observation_id
                   ORDER BY observation.source_observed_at DESC LIMIT 1""",
                (now, now, self.owner_id, now, now, now, now),
            ).fetchone()
        if row is None:
            return ()
        observation = self._observation_from_row(row)
        if not hasattr(observation.value, "busy_intervals"):
            return ()
        window_from, window_to = self._calendar_query_window(
            normalized=normalized,
            now=now,
            coverage_from=observation.occurred_from,
            coverage_to=observation.occurred_to,
        )
        if window_to <= window_from:
            return ()
        intervals = tuple(
            item for item in observation.value.busy_intervals
            if item.ends_at > window_from and item.starts_at < window_to
        )
        rendered = "; ".join(
            f"{item.starts_at.isoformat()} to {item.ends_at.isoformat()} ({item.availability})"
            for item in intervals[:24]
        ) or "No busy intervals were present in the requested covered range; absence is not evidence of availability."
        text = (
            "Owner-local calendar availability only (no titles, locations, attendees, or content): "
            f"requested range {window_from.isoformat()} to {window_to.isoformat()}; "
            f"{rendered}. Treat missing or stale calendar data as unknown."
        )
        return (
            PersonalContextItem(
                owner_id=self.owner_id,
                section_id=f"calendar-availability-{observation.observation_id}",
                section_type="calendar_availability",
                content_text=text,
                priority=92,
                source_refs=(f"context-observation/{observation.observation_id}",),
                data_policy=observation.data_policy,
                selector_version="stage12a-calendar-context-selector-v1",
            ),
        )

    def _calendar_query_window(
        self,
        *,
        normalized: str,
        now: datetime,
        coverage_from: datetime,
        coverage_to: datetime,
    ) -> tuple[datetime, datetime]:
        local_now = now.astimezone(self.owner_timezone)
        explicit = re.search(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)", normalized)
        if explicit is not None:
            start_local = datetime(
                int(explicit.group(1)), int(explicit.group(2)), int(explicit.group(3)),
                tzinfo=self.owner_timezone,
            )
            end_local = start_local + timedelta(days=1)
        elif "tomorrow" in normalized or "明天" in normalized:
            requested_date = local_now.date() + timedelta(days=1)
            start_local = datetime.combine(requested_date, time.min, self.owner_timezone)
            end_local = start_local + timedelta(days=1)
        elif "today" in normalized or "今天" in normalized:
            start_local = datetime.combine(local_now.date(), time.min, self.owner_timezone)
            end_local = start_local + timedelta(days=1)
        elif "next week" in normalized or "下周" in normalized:
            next_monday = local_now.date() + timedelta(days=7-local_now.weekday())
            start_local = datetime.combine(next_monday, time.min, self.owner_timezone)
            end_local = start_local + timedelta(days=7)
        elif "this week" in normalized or "这周" in normalized:
            monday = local_now.date() - timedelta(days=local_now.weekday())
            start_local = max(
                local_now,
                datetime.combine(monday, time.min, self.owner_timezone),
            )
            end_local = datetime.combine(
                monday + timedelta(days=7), time.min, self.owner_timezone
            )
        else:
            start_local = local_now
            end_local = local_now + timedelta(days=14)
        start = max(start_local.astimezone(UTC), coverage_from, now)
        end = min(end_local.astimezone(UTC), coverage_to)
        return start, end

    def _activate_bundle(
        self, bundle: WindowsContextActivationBundle | CalendarContextActivationBundle
    ) -> tuple[ContextSourceStateRevision, ContextCapabilityStateRevision]:
        """Atomically persist one exact owner-approved source capability."""

        source, capability, consent = bundle.source, bundle.capability, bundle.consent
        if source.owner_id != self.owner_id:
            raise ContextIngestRejected("activation bundle owner mismatch")
        secret = self.device_secret_resolver(source.device_binding_id)
        now = datetime.now(UTC)
        source_state = ContextSourceStateRevision(
            owner_id=self.owner_id,
            source_instance_id=source.source_instance_id,
            revision=1,
            status="enabled",
            reason="registered",
            effective_at=now,
            authorization_ref=bundle.owner_activation_ref,
        )
        capability_state = ContextCapabilityStateRevision(
            owner_id=self.owner_id,
            capability_revision_id=capability.capability_revision_id,
            revision=1,
            status="enabled",
            reason="registered",
            effective_at=now,
            authorization_ref=bundle.owner_activation_ref,
        )
        source_event = self._source_state_event(
            source=source, state=source_state, data_policy=consent.data_policy
        )
        capability_event = self._capability_state_event(
            capability=capability,
            state=capability_state,
            data_policy=consent.data_policy,
        )
        consent_event = EventEnvelope(
            event_type=EventType.CONTEXT_CONSENT_REVISED,
            owner_id=self.owner_id,
            session_id=uuid7(),
            request_id=uuid7(),
            trace_id=new_trace_id(),
            data_policy=consent.data_policy,
            payload=ContextConsentLifecyclePayload(
                consent_scope_id=consent.consent_scope_id,
                consent_scope_revision_id=consent.consent_scope_revision_id,
                revision=consent.revision,
                action="activated",
                source_instance_id=source.source_instance_id,
                capability_revision_id=capability.capability_revision_id,
                consent_content_hash=consent.content_hash,
            ),
        )
        with self.repository.pool.connection() as connection, connection.transaction():
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (f"context-activation:{self.owner_id}:{bundle.activation_id}",),
            )
            existing = connection.execute(
                """
                SELECT source.content_hash AS source_hash,
                       capability.content_hash AS capability_hash,
                       consent.content_hash AS consent_hash,
                       binding.signing_secret AS signing_secret,
                       source_state.state_revision_id AS source_state_revision_id,
                       capability_state.state_revision_id AS capability_state_revision_id
                FROM havre.context_sources source
                LEFT JOIN havre.context_source_capabilities capability
                  ON capability.owner_id=source.owner_id
                 AND capability.capability_revision_id=%s
                LEFT JOIN havre.context_consent_scope_revisions consent
                  ON consent.owner_id=source.owner_id
                 AND consent.consent_scope_revision_id=%s
                LEFT JOIN havre.context_device_bindings binding
                  ON binding.owner_id=source.owner_id
                 AND binding.source_instance_id=source.source_instance_id
                 AND binding.device_binding_id=source.device_binding_id
                LEFT JOIN LATERAL (
                    SELECT * FROM havre.context_source_state_revisions state
                    WHERE state.owner_id=source.owner_id
                      AND state.source_instance_id=source.source_instance_id
                    ORDER BY state.revision DESC LIMIT 1
                ) source_state ON true
                LEFT JOIN LATERAL (
                    SELECT * FROM havre.context_capability_state_revisions state
                    WHERE state.owner_id=capability.owner_id
                      AND state.capability_revision_id=capability.capability_revision_id
                    ORDER BY state.revision DESC LIMIT 1
                ) capability_state ON true
                WHERE source.owner_id=%s AND source.source_instance_id=%s
                """,
                (
                    capability.capability_revision_id,
                    consent.consent_scope_revision_id,
                    self.owner_id,
                    source.source_instance_id,
                ),
            ).fetchone()
            if existing is not None:
                quarantined = connection.execute(
                    """
                    SELECT 1 FROM havre.context_restore_quarantines
                    WHERE owner_id=%s AND source_instance_id=%s LIMIT 1
                    """,
                    (self.owner_id, source.source_instance_id),
                ).fetchone()
                if quarantined is not None:
                    raise ContextIngestRejected(
                        "restored source requires a new source enrollment"
                    )
                if (
                    existing["source_hash"] != source.content_hash
                    or existing["capability_hash"] != capability.content_hash
                    or existing["consent_hash"] != consent.content_hash
                    or bytes(existing["signing_secret"]) != secret
                    or existing["source_state_revision_id"] is None
                    or existing["capability_state_revision_id"] is None
                ):
                    raise ContextIngestRejected(
                        "existing source is not the exact activation bundle"
                    )
                persisted_source_state = connection.execute(
                    "SELECT * FROM havre.context_source_state_revisions WHERE state_revision_id=%s",
                    (existing["source_state_revision_id"],),
                ).fetchone()
                persisted_capability_state = connection.execute(
                    "SELECT * FROM havre.context_capability_state_revisions WHERE state_revision_id=%s",
                    (existing["capability_state_revision_id"],),
                ).fetchone()
                return (
                    self._source_state_from_row(persisted_source_state),
                    self._capability_state_from_row(persisted_capability_state),
                )
            self._insert_event_scaffold(
                connection=connection, event=source_event,
                idempotency_key=f"context-source:{source_state.state_revision_id}",
                request_fingerprint=source_state.content_hash,
            )
            connection.execute(
                """
                INSERT INTO havre.context_sources (
                    source_instance_id,schema_version,owner_id,source_kind,
                    provider_id,device_binding_id,adapter_version,source_version,
                    provider_tenant_binding,provider_account_binding,
                    enrollment_status,registration_event_id,content_hash
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    source.source_instance_id,source.schema_version,source.owner_id,
                    source.source_kind,source.provider_id,source.device_binding_id,
                    source.adapter_version,source.source_version,
                    source.provider_tenant_binding,source.provider_account_binding,
                    source.enrollment_status,source_event.event_id,source.content_hash,
                ),
            )
            connection.execute(
                """
                INSERT INTO havre.context_device_bindings (
                    owner_id,device_binding_id,source_instance_id,key_version,
                    signing_secret,status
                ) VALUES (%s,%s,%s,1,%s,'enabled')
                """,
                (self.owner_id,source.device_binding_id,source.source_instance_id,secret),
            )
            self._insert_source_state(connection, source_state, source_event.event_id)
            self._insert_event_scaffold(
                connection=connection,event=capability_event,
                idempotency_key=f"context-capability:{capability_state.state_revision_id}",
                request_fingerprint=capability_state.content_hash,
            )
            connection.execute(
                """
                INSERT INTO havre.context_source_capabilities (
                    capability_revision_id,schema_version,owner_id,source_instance_id,
                    capability_id,revision,observation_kind,observation_schema_version,
                    allowed_fields,precision,sampling_modes,conformance_version,status,
                    registration_event_id,content_hash
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    capability.capability_revision_id,capability.schema_version,
                    capability.owner_id,capability.source_instance_id,
                    capability.capability_id,capability.revision,
                    capability.observation_kind,capability.observation_schema_version,
                    Jsonb(list(capability.allowed_fields)),capability.precision,
                    Jsonb(list(capability.sampling_modes)),capability.conformance_version,
                    capability.status,capability_event.event_id,capability.content_hash,
                ),
            )
            self._insert_capability_state(
                connection, capability_state, capability_event.event_id
            )
            self._insert_event_scaffold(
                connection=connection,event=consent_event,
                idempotency_key=f"context-consent:{consent.consent_scope_revision_id}",
                request_fingerprint=consent.content_hash,
            )
            connection.execute(
                """
                INSERT INTO havre.context_consent_scope_revisions (
                    consent_scope_revision_id,consent_scope_id,schema_version,owner_id,
                    source_instance_id,capability_revision_id,revision,status,purpose,
                    allowed_observation_kinds,allowed_fields,permitted_destinations,
                    sampling_policy,retention_policy,data_policy,effective_at,expires_at,
                    authorization_ref,decision_event_id,content_hash
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    consent.consent_scope_revision_id,consent.consent_scope_id,
                    consent.schema_version,consent.owner_id,consent.source_instance_id,
                    consent.capability_revision_id,consent.revision,consent.status,
                    consent.purpose,Jsonb(list(consent.allowed_observation_kinds)),
                    Jsonb(list(consent.allowed_fields)),
                    Jsonb(list(consent.permitted_destinations)),
                    Jsonb(consent.sampling_policy.model_dump(mode="json")),
                    Jsonb(consent.retention_policy.model_dump(mode="json")),
                    Jsonb(consent.data_policy.model_dump(mode="json")),
                    consent.effective_at,consent.expires_at,consent.authorization_ref,
                    consent_event.event_id,consent.content_hash,
                ),
            )
        return source_state, capability_state

    def register_source(
        self, source: ContextSourceDescriptor, *, data_policy: DataPolicy
    ) -> ContextSourceStateRevision:
        if source.owner_id != self.owner_id:
            raise ContextIngestRejected("source owner mismatch")
        if data_policy.authorization_ref is None:
            raise ContextIngestRejected("source registration authorization is required")
        secret = self.device_secret_resolver(source.device_binding_id)
        now = datetime.now(UTC)
        state = ContextSourceStateRevision(
            owner_id=self.owner_id,
            source_instance_id=source.source_instance_id,
            revision=1,
            status="enabled",
            reason="registered",
            effective_at=now,
            authorization_ref=data_policy.authorization_ref,
        )
        event = self._source_state_event(
            source=source, state=state, data_policy=data_policy
        )
        with self.repository.pool.connection() as connection, connection.transaction():
            self._insert_event_scaffold(
                connection=connection,
                event=event,
                idempotency_key=f"context-source:{state.state_revision_id}",
                request_fingerprint=state.content_hash,
            )
            connection.execute(
                """
                INSERT INTO havre.context_sources (
                    source_instance_id, schema_version, owner_id, source_kind,
                    provider_id, device_binding_id, adapter_version, source_version,
                    provider_tenant_binding, provider_account_binding,
                    enrollment_status, registration_event_id, content_hash
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    source.source_instance_id, source.schema_version, source.owner_id,
                    source.source_kind, source.provider_id, source.device_binding_id,
                    source.adapter_version, source.source_version,
                    source.provider_tenant_binding, source.provider_account_binding,
                    source.enrollment_status, event.event_id, source.content_hash,
                ),
            )
            connection.execute(
                """
                INSERT INTO havre.context_device_bindings (
                    owner_id, device_binding_id, source_instance_id, key_version,
                    signing_secret, status
                ) VALUES (%s,%s,%s,1,%s,'enabled')
                """,
                (self.owner_id, source.device_binding_id, source.source_instance_id, secret),
            )
            self._insert_source_state(connection, state, event.event_id)
        return state

    def register_capability(
        self, capability: ContextSourceCapability, *, data_policy: DataPolicy
    ) -> ContextCapabilityStateRevision:
        if capability.owner_id != self.owner_id:
            raise ContextIngestRejected("capability owner mismatch")
        if data_policy.authorization_ref is None:
            raise ContextIngestRejected("capability registration authorization is required")
        now = datetime.now(UTC)
        state = ContextCapabilityStateRevision(
            owner_id=self.owner_id,
            capability_revision_id=capability.capability_revision_id,
            revision=1,
            status="enabled",
            reason="registered",
            effective_at=now,
            authorization_ref=data_policy.authorization_ref,
        )
        event = self._capability_state_event(
            capability=capability, state=state, data_policy=data_policy
        )
        with self.repository.pool.connection() as connection, connection.transaction():
            self._insert_event_scaffold(
                connection=connection,
                event=event,
                idempotency_key=f"context-capability:{state.state_revision_id}",
                request_fingerprint=state.content_hash,
            )
            connection.execute(
                """
                INSERT INTO havre.context_source_capabilities (
                    capability_revision_id, schema_version, owner_id,
                    source_instance_id, capability_id, revision, observation_kind,
                    observation_schema_version, allowed_fields, precision,
                    sampling_modes, conformance_version, status,
                    registration_event_id, content_hash
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    capability.capability_revision_id, capability.schema_version,
                    capability.owner_id, capability.source_instance_id,
                    capability.capability_id, capability.revision,
                    capability.observation_kind,
                    capability.observation_schema_version,
                    Jsonb(list(capability.allowed_fields)), capability.precision,
                    Jsonb(list(capability.sampling_modes)),
                    capability.conformance_version, capability.status,
                    event.event_id, capability.content_hash,
                ),
            )
            self._insert_capability_state(connection, state, event.event_id)
        return state

    def save_source_state(
        self, state: ContextSourceStateRevision, *, data_policy: DataPolicy
    ) -> UUID:
        if state.owner_id != self.owner_id:
            raise ContextIngestRejected("source state owner mismatch")
        now = datetime.now(UTC)
        if state.status == "disabled" and state.effective_at > now:
            raise ContextIngestRejected("source disablement must be effective immediately")
        with self.repository.pool.connection() as connection, connection.transaction():
            source_row = connection.execute(
                "SELECT * FROM havre.context_sources WHERE owner_id=%s AND source_instance_id=%s",
                (self.owner_id, state.source_instance_id),
            ).fetchone()
            if source_row is None:
                raise ContextIngestRejected("registered source is required")
            source = self._source_from_row(source_row)
            event = self._source_state_event(
                source=source, state=state, data_policy=data_policy
            )
            self._insert_event_scaffold(
                connection=connection, event=event,
                idempotency_key=f"context-source:{state.state_revision_id}",
                request_fingerprint=state.content_hash,
            )
            if state.status == "disabled":
                capability = connection.execute(
                    """
                    SELECT capability_revision_id
                    FROM havre.context_source_capabilities
                    WHERE owner_id=%s AND source_instance_id=%s
                    ORDER BY revision DESC LIMIT 1
                    """,
                    (self.owner_id, state.source_instance_id),
                ).fetchone()
                if capability is not None:
                    self._insert_health(
                        connection,
                        ContextSourceHealthV2(
                            owner_id=self.owner_id,
                            source_instance_id=state.source_instance_id,
                            capability_revision_id=capability["capability_revision_id"],
                            status="permission_revoked",
                            checked_at=now,
                            safe_error_category="permission_revoked",
                            adapter_version=source.adapter_version,
                            source_version=source.source_version,
                            trace_id=event.trace_id,
                        ),
                        causal_event_id=event.event_id,
                    )
            self._insert_source_state(connection, state, event.event_id)
        return event.event_id

    def save_capability_state(
        self, state: ContextCapabilityStateRevision, *, data_policy: DataPolicy
    ) -> UUID:
        if state.owner_id != self.owner_id:
            raise ContextIngestRejected("capability state owner mismatch")
        with self.repository.pool.connection() as connection, connection.transaction():
            row = connection.execute(
                "SELECT * FROM havre.context_source_capabilities WHERE owner_id=%s AND capability_revision_id=%s",
                (self.owner_id, state.capability_revision_id),
            ).fetchone()
            if row is None:
                raise ContextIngestRejected("registered capability is required")
            capability = self._capability_from_row(row)
            event = self._capability_state_event(
                capability=capability, state=state, data_policy=data_policy
            )
            self._insert_event_scaffold(
                connection=connection, event=event,
                idempotency_key=f"context-capability:{state.state_revision_id}",
                request_fingerprint=state.content_hash,
            )
            self._insert_capability_state(connection, state, event.event_id)
        return event.event_id

    def save_consent(self, consent: ConsentScopeRevision) -> UUID:
        if consent.owner_id != self.owner_id:
            raise ContextIngestRejected("consent owner mismatch")
        event_id = uuid7()
        request_id = uuid7()
        session_id = uuid7()
        trace_id = new_trace_id()
        action = {
            "active": "activated",
            "revoked": "revoked",
            "expired": "expired",
        }[consent.status]
        event = EventEnvelope(
            event_id=event_id,
            event_type=EventType.CONTEXT_CONSENT_REVISED,
            owner_id=self.owner_id,
            session_id=session_id,
            request_id=request_id,
            trace_id=trace_id,
            data_policy=consent.data_policy,
            payload=ContextConsentLifecyclePayload(
                consent_scope_id=consent.consent_scope_id,
                consent_scope_revision_id=consent.consent_scope_revision_id,
                revision=consent.revision,
                action=action,
                source_instance_id=consent.source_instance_id,
                capability_revision_id=consent.capability_revision_id,
                consent_content_hash=consent.content_hash,
            ),
        )
        with self.repository.pool.connection() as connection, connection.transaction():
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (
                    f"context-consent-semantic:{self.owner_id}:"
                    f"{consent.source_instance_id}:{consent.capability_revision_id}:"
                    f"{consent.purpose}",
                ),
            )
            self._insert_event_scaffold(
                connection=connection,
                event=event,
                idempotency_key=f"context-consent:{consent.consent_scope_revision_id}",
                request_fingerprint=consent.content_hash,
            )
            connection.execute(
                """
                INSERT INTO havre.context_consent_scope_revisions (
                    consent_scope_revision_id, consent_scope_id, schema_version,
                    owner_id, source_instance_id, capability_revision_id,
                    revision, status, purpose, allowed_observation_kinds,
                    allowed_fields, permitted_destinations, sampling_policy,
                    retention_policy, data_policy, effective_at, expires_at,
                    authorization_ref, decision_event_id, content_hash
                ) VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                )
                """,
                (
                    consent.consent_scope_revision_id, consent.consent_scope_id,
                    consent.schema_version, consent.owner_id,
                    consent.source_instance_id, consent.capability_revision_id,
                    consent.revision, consent.status, consent.purpose,
                    Jsonb(list(consent.allowed_observation_kinds)),
                    Jsonb(list(consent.allowed_fields)),
                    Jsonb(list(consent.permitted_destinations)),
                    Jsonb(consent.sampling_policy.model_dump(mode="json")),
                    Jsonb(consent.retention_policy.model_dump(mode="json")),
                    Jsonb(consent.data_policy.model_dump(mode="json")),
                    consent.effective_at, consent.expires_at,
                    consent.authorization_ref, event_id, consent.content_hash,
                ),
            )
        return event_id

    def current_collection_permit(
        self, *, source_instance_id: UUID, device_binding_id: str,
    ) -> ContextCollectionPermit:
        with self.repository.pool.connection() as connection, connection.transaction():
            capability_identity = connection.execute(
                """
                SELECT capability_revision_id
                FROM havre.context_source_capabilities
                WHERE owner_id=%s AND source_instance_id=%s
                ORDER BY revision DESC LIMIT 1
                """,
                (self.owner_id, source_instance_id),
            ).fetchone()
            if capability_identity is None:
                raise ContextIngestRejected("source capability state is unavailable")
            capability_revision_id = capability_identity["capability_revision_id"]
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (
                    f"context-consent-semantic:{self.owner_id}:"
                    f"{source_instance_id}:{capability_revision_id}:"
                    "companion_timing_context",
                ),
            )
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"context-source:{self.owner_id}:{source_instance_id}",),
            )
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"context-capability:{self.owner_id}:{capability_revision_id}",),
            )
            instant = connection.execute(
                "SELECT statement_timestamp() AS authority_time"
            ).fetchone()["authority_time"]
            source_row = connection.execute(
                "SELECT * FROM havre.context_sources WHERE owner_id=%s AND source_instance_id=%s AND device_binding_id=%s",
                (self.owner_id, source_instance_id, device_binding_id),
            ).fetchone()
            if source_row is None:
                raise ContextIngestRejected("unknown source device binding")
            quarantined = connection.execute(
                """
                SELECT 1 FROM havre.context_restore_quarantines
                WHERE owner_id=%s AND source_instance_id=%s LIMIT 1
                """,
                (self.owner_id, source_instance_id),
            ).fetchone()
            if quarantined is not None:
                raise ContextIngestRejected(
                    "restored source requires a new source enrollment"
                )
            source_state_row = connection.execute(
                """
                SELECT * FROM havre.context_source_state_revisions
                WHERE owner_id=%s AND source_instance_id=%s AND effective_at<=%s
                ORDER BY revision DESC LIMIT 1
                """,
                (self.owner_id, source_instance_id, instant),
            ).fetchone()
            capability_row = connection.execute(
                """
                SELECT capability.* FROM havre.context_source_capabilities capability
                JOIN havre.context_capability_state_revisions state
                  ON state.owner_id=capability.owner_id
                 AND state.capability_revision_id=capability.capability_revision_id
                WHERE capability.owner_id=%s AND capability.source_instance_id=%s
                  AND state.effective_at<=%s
                ORDER BY state.revision DESC LIMIT 1
                """,
                (self.owner_id, source_instance_id, instant),
            ).fetchone()
            if source_state_row is None or capability_row is None:
                raise ContextIngestRejected("source capability state is unavailable")
            capability_state_row = connection.execute(
                """
                SELECT * FROM havre.context_capability_state_revisions
                WHERE owner_id=%s AND capability_revision_id=%s AND effective_at<=%s
                ORDER BY revision DESC LIMIT 1
                """,
                (self.owner_id, capability_row["capability_revision_id"], instant),
            ).fetchone()
            consent_row = connection.execute(
                """
                SELECT consent.* FROM havre.context_consent_scope_revisions consent
                WHERE consent.owner_id=%s AND consent.source_instance_id=%s
                  AND consent.capability_revision_id=%s
                  AND consent.purpose='companion_timing_context'
                ORDER BY consent.revision DESC LIMIT 1
                """,
                (self.owner_id, source_instance_id, capability_revision_id),
            ).fetchone()
            if capability_state_row is None or consent_row is None:
                raise ContextIngestRejected("current consent is unavailable")
            consent = self._consent_from_row(consent_row)
            if (
                source_state_row["status"] != "enabled"
                or capability_state_row["status"] != "enabled"
                or consent.status != "active"
                or not (consent.effective_at <= instant < consent.expires_at)
            ):
                raise ContextIngestRejected("current consent is not valid")
            return ContextCollectionPermit(
                source=self._source_from_row(source_row),
                source_state=self._source_state_from_row(source_state_row),
                capability=self._capability_from_row(capability_row),
                capability_state=self._capability_state_from_row(capability_state_row),
                consent=consent,
                issued_at=instant,
                valid_until=min(instant + timedelta(seconds=30), consent.expires_at),
            )

    def issue_collection_permit(
        self, request: ContextCollectionPermitRequest
    ) -> ContextCollectionPermit:
        if request.owner_id != self.owner_id:
            raise ContextIngestRejected("permit owner mismatch")
        now = datetime.now(UTC)
        if abs((now - request.requested_at).total_seconds()) > 60:
            raise ContextIngestRejected("permit request clock exceeds allowed skew")
        try:
            secret = self.device_secret_resolver(request.device_binding_id)
        except (KeyError, OSError) as error:
            raise ContextIngestRejected("unknown device binding") from error
        if not verify_collection_permit_request_signature(request, secret=secret):
            raise ContextIngestRejected("invalid permit device signature")
        return self.current_collection_permit(
            source_instance_id=request.source_instance_id,
            device_binding_id=request.device_binding_id,
        )

    def ingest(self, draft: ContextObservationDraft) -> ContextIngestResult:
        if draft.owner_id != self.owner_id:
            raise ContextIngestRejected("draft owner mismatch")
        try:
            secret = self.device_secret_resolver(draft.device_binding_id)
        except (KeyError, OSError) as error:
            raise ContextIngestRejected("unknown device binding") from error
        if not verify_observation_draft_signature(draft, secret=secret):
            raise ContextIngestRejected("invalid device signature")
        draft_hash = content_hash(
            draft.model_dump(mode="json", exclude={"signature"})
        )
        with self.repository.pool.connection() as connection, connection.transaction():
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"context:{self.owner_id}:{draft.source_instance_id}:{draft.idempotency_key}",),
            )
            existing = connection.execute(
                """
                SELECT * FROM havre.life_context_observations
                WHERE owner_id=%s AND source_instance_id=%s AND idempotency_key=%s
                """,
                (self.owner_id, draft.source_instance_id, draft.idempotency_key),
            ).fetchone()
            if existing and existing["draft_content_hash"] != draft_hash:
                raise ContextIdempotencyConflict(
                    "context idempotency key was reused with different material"
                )
            source = connection.execute(
                """
                SELECT * FROM havre.context_sources
                WHERE owner_id=%s AND source_instance_id=%s
                """,
                (self.owner_id, draft.source_instance_id),
            ).fetchone()
            consent_row = connection.execute(
                """
                SELECT * FROM havre.context_consent_scope_revisions
                WHERE owner_id=%s AND consent_scope_revision_id=%s
                """,
                (self.owner_id, draft.consent_scope_revision_id),
            ).fetchone()
            if source is None or consent_row is None:
                raise ContextIngestRejected("registered source and consent are required")
            quarantined = connection.execute(
                """
                SELECT 1 FROM havre.context_restore_quarantines
                WHERE owner_id=%s AND source_instance_id=%s LIMIT 1
                """,
                (self.owner_id, draft.source_instance_id),
            ).fetchone()
            if quarantined is not None:
                raise ContextIngestRejected(
                    "restored source requires a new source enrollment"
                )
            if source["device_binding_id"] != draft.device_binding_id:
                raise ContextIngestRejected("device binding mismatch")
            consent = self._consent_from_row(consent_row)
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (
                    f"context-consent-semantic:{self.owner_id}:"
                    f"{consent.source_instance_id}:{consent.capability_revision_id}:"
                    f"{consent.purpose}",
                ),
            )
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"context-source:{self.owner_id}:{draft.source_instance_id}",),
            )
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"context-capability:{self.owner_id}:{draft.capability_revision_id}",),
            )
            now = datetime.now(UTC)
            self._validate_draft_against_consent(
                draft=draft, consent=consent, now=now
            )
            latest_revision = connection.execute(
                """
                SELECT max(revision) AS revision
                FROM havre.context_consent_scope_revisions
                WHERE owner_id=%s AND consent_scope_id=%s
                """,
                (self.owner_id, consent.consent_scope_id),
            ).fetchone()["revision"]
            if latest_revision != consent.revision:
                raise ContextIngestRejected("consent revision is not current")
            source_state = connection.execute(
                """
                SELECT status FROM havre.context_source_state_revisions
                WHERE owner_id=%s AND source_instance_id=%s AND effective_at<=%s
                ORDER BY revision DESC LIMIT 1
                """,
                (self.owner_id, draft.source_instance_id, now),
            ).fetchone()
            capability_state = connection.execute(
                """
                SELECT status FROM havre.context_capability_state_revisions
                WHERE owner_id=%s AND capability_revision_id=%s AND effective_at<=%s
                ORDER BY revision DESC LIMIT 1
                """,
                (self.owner_id, draft.capability_revision_id, now),
            ).fetchone()
            if (
                source_state is None or source_state["status"] != "enabled"
                or capability_state is None or capability_state["status"] != "enabled"
            ):
                raise ContextIngestRejected("source or capability is disabled")
            if existing:
                return ContextIngestResult(
                    observation=self._observation_from_row(existing),
                    idempotent_replay=True,
                )
            max_future = now + timedelta(
                seconds=consent.sampling_policy.max_clock_skew_seconds
            )
            oldest = now - timedelta(
                seconds=consent.sampling_policy.offline_buffer_seconds
            )
            if draft.source_observed_at > max_future:
                raise ContextIngestRejected("source clock exceeds allowed future skew")
            if draft.source_observed_at < oldest:
                raise ContextIngestRejected("draft exceeds the consented offline buffer")
            if draft.observation_kind == "device_activity_summary":
                if (
                    draft.source_observed_at - draft.occurred_to
                ).total_seconds() > consent.sampling_policy.max_clock_skew_seconds:
                    raise ContextIngestRejected(
                        "coverage end is too far from source observation"
                    )
                duration = int((draft.occurred_to - draft.occurred_from).total_seconds())
                if (
                    duration != consent.sampling_policy.summary_window_seconds
                    or draft.value.window_seconds != duration
                    or draft.value.sample_count != (
                        duration // consent.sampling_policy.sample_interval_seconds
                    )
                    or draft.value.active_seconds + draft.value.idle_seconds != duration
                ):
                    raise ContextIngestRejected(
                        "summary window does not match sampling policy"
                    )
                fresh_until = draft.occurred_to + timedelta(
                    seconds=consent.sampling_policy.fresh_for_seconds
                )
                measurement_quality = "coarse_local_aggregate"
                clock_quality = "host_utc_clock"
                limitations = (
                    "coarse category only",
                    "no application identity or content retained",
                    "not an interpretation of intent or productivity",
                )
            else:
                skew = consent.sampling_policy.max_clock_skew_seconds
                coverage = int((draft.occurred_to - draft.occurred_from).total_seconds())
                if (
                    draft.occurred_to <= draft.source_observed_at
                    or draft.occurred_to > consent.expires_at
                    or coverage > consent.sampling_policy.max_coverage_seconds
                    or any(
                        interval.starts_at < draft.occurred_from
                        or interval.ends_at > draft.occurred_to
                        for interval in draft.value.busy_intervals
                    )
                ):
                    raise ContextIngestRejected(
                        "Calendar coverage does not match owner-initiated import policy"
                    )
                fresh_until = draft.occurred_to
                measurement_quality = "owner_supplied_ics_projection"
                clock_quality = "ics_timezone_normalized"
                limitations = (
                    "availability only; no subject, body, location, organizer, or attendees retained",
                    "owner-supplied snapshot can become outdated until manually replaced",
                    "missing calendar data is not negative evidence about the owner",
                )

            event_id = uuid7()
            request_id = uuid7()
            session_id = uuid7()
            observation = LifeContextObservationV2(
                draft_id=draft.draft_id,
                owner_id=self.owner_id,
                source_instance_id=draft.source_instance_id,
                capability_revision_id=draft.capability_revision_id,
                capability_id=draft.capability_id,
                observation_kind=draft.observation_kind,
                observation_schema_version=draft.observation_schema_version,
                value=draft.value,
                occurred_from=draft.occurred_from,
                occurred_to=draft.occurred_to,
                source_observed_at=draft.source_observed_at,
                ingested_at=now,
                fresh_until=fresh_until,
                retention_expires_at=now + timedelta(
                    days=consent.retention_policy.canonical_retention_days
                ),
                consent_scope_revision_id=draft.consent_scope_revision_id,
                sampling_policy_version=draft.sampling_policy_version,
                retention_policy_version=draft.retention_policy_version,
                adapter_version=draft.adapter_version,
                data_policy=draft.data_policy,
                event_id=event_id,
                trace_id=draft.trace_id,
                idempotency_key=draft.idempotency_key,
                draft_content_hash=draft_hash,
                device_binding_id=draft.device_binding_id,
                draft_signing_material=draft.signing_material(),
                device_signature=draft.signature,
                measurement_quality=measurement_quality,
                clock_quality=clock_quality,
                limitations=limitations,
            )
            event = EventEnvelope(
                event_id=event_id,
                event_type=EventType.LIFE_CONTEXT_OBSERVED,
                owner_id=self.owner_id,
                session_id=session_id,
                request_id=request_id,
                trace_id=draft.trace_id,
                data_policy=draft.data_policy,
                payload=LifeContextObservedPayload(
                    observation_id=observation.observation_id,
                    source_instance_id=observation.source_instance_id,
                    capability_revision_id=observation.capability_revision_id,
                    consent_scope_revision_id=observation.consent_scope_revision_id,
                    observation_kind=observation.observation_kind,
                    observation_content_hash=observation.content_hash,
                ),
            )
            self._insert_event_scaffold(
                connection=connection,
                event=event,
                idempotency_key=f"context:{draft_hash}",
                request_fingerprint=draft_hash,
            )
            self._insert_observation(connection, observation)
            latest_coverage = connection.execute(
                """
                SELECT coverage_to FROM havre.context_source_health_records
                WHERE owner_id=%s AND source_instance_id=%s
                  AND capability_revision_id=%s AND status='healthy'
                ORDER BY coverage_to DESC LIMIT 1
                """,
                (self.owner_id, draft.source_instance_id, draft.capability_revision_id),
            ).fetchone()
            if latest_coverage is None or draft.occurred_to > latest_coverage["coverage_to"]:
                health = ContextSourceHealthV2(
                    owner_id=self.owner_id,
                    source_instance_id=draft.source_instance_id,
                    capability_revision_id=draft.capability_revision_id,
                    status="healthy",
                    checked_at=now,
                    last_successful_observation_id=observation.observation_id,
                    last_successful_observation_at=draft.source_observed_at,
                    coverage_from=draft.occurred_from,
                    coverage_to=draft.occurred_to,
                    adapter_version=draft.adapter_version,
                    source_version=source["source_version"],
                    trace_id=draft.trace_id,
                )
                self._insert_health(
                    connection, health, causal_event_id=observation.event_id
                )
            return ContextIngestResult(
                observation=observation,
                idempotent_replay=False,
            )

    def ingest_health(self, draft: ContextSourceHealthDraft) -> ContextSourceHealthV2:
        if draft.owner_id != self.owner_id:
            raise ContextIngestRejected("health owner mismatch")
        try:
            secret = self.device_secret_resolver(draft.device_binding_id)
        except (KeyError, OSError) as error:
            raise ContextIngestRejected("unknown device binding") from error
        if not verify_health_draft_signature(draft, secret=secret):
            raise ContextIngestRejected("invalid health device signature")
        now = datetime.now(UTC)
        if abs((now - draft.checked_at).total_seconds()) > 300:
            raise ContextIngestRejected("health clock exceeds allowed skew")
        with self.repository.pool.connection() as connection, connection.transaction():
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"context-source:{self.owner_id}:{draft.source_instance_id}",),
            )
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"context-capability:{self.owner_id}:{draft.capability_revision_id}",),
            )
            source = connection.execute(
                "SELECT * FROM havre.context_sources WHERE owner_id=%s AND source_instance_id=%s",
                (self.owner_id, draft.source_instance_id),
            ).fetchone()
            capability = connection.execute(
                """
                SELECT * FROM havre.context_source_capabilities
                WHERE owner_id=%s AND capability_revision_id=%s
                """,
                (self.owner_id, draft.capability_revision_id),
            ).fetchone()
            states = connection.execute(
                """
                SELECT
                  (SELECT status FROM havre.context_source_state_revisions
                   WHERE owner_id=%s AND source_instance_id=%s AND effective_at<=%s
                   ORDER BY revision DESC LIMIT 1) AS source_status,
                  (SELECT status FROM havre.context_capability_state_revisions
                   WHERE owner_id=%s AND capability_revision_id=%s AND effective_at<=%s
                   ORDER BY revision DESC LIMIT 1) AS capability_status
                """,
                (
                    self.owner_id, draft.source_instance_id, now,
                    self.owner_id, draft.capability_revision_id, now,
                ),
            ).fetchone()
            if (
                source is None
                or capability is None
                or source["device_binding_id"] != draft.device_binding_id
                or capability["source_instance_id"] != draft.source_instance_id
                or source["adapter_version"] != draft.adapter_version
                or source["source_version"] != draft.source_version
                or states["source_status"] != "enabled"
                or states["capability_status"] != "enabled"
            ):
                raise ContextIngestRejected("health source or capability is disabled")
            quarantined = connection.execute(
                """
                SELECT 1 FROM havre.context_restore_quarantines
                WHERE owner_id=%s AND source_instance_id=%s LIMIT 1
                """,
                (self.owner_id, draft.source_instance_id),
            ).fetchone()
            if quarantined is not None:
                raise ContextIngestRejected(
                    "restored source requires a new source enrollment"
                )
            existing = connection.execute(
                """
                SELECT * FROM havre.context_source_health_records
                WHERE owner_id=%s AND source_instance_id=%s AND idempotency_key=%s
                """,
                (self.owner_id, draft.source_instance_id, draft.idempotency_key),
            ).fetchone()
            if existing is not None:
                if (
                    existing["draft_signing_material"] != draft.signing_material()
                    or existing["device_signature"] != draft.signature
                ):
                    raise ContextIdempotencyConflict(
                        "health idempotency key was reused with different material"
                    )
                return self._health_from_row(existing)
            latest = connection.execute(
                """
                SELECT checked_at FROM havre.context_source_health_records
                WHERE owner_id=%s AND source_instance_id=%s
                  AND capability_revision_id=%s
                ORDER BY checked_at DESC LIMIT 1
                """,
                (self.owner_id, draft.source_instance_id, draft.capability_revision_id),
            ).fetchone()
            if latest is not None and draft.checked_at <= latest["checked_at"]:
                raise ContextIngestRejected("out-of-order source health is not current")
            self._insert_operational_scaffold(
                connection=connection,
                trace_id=draft.trace_id,
                idempotency_key=f"context-health:{draft.idempotency_key}",
                request_fingerprint=content_hash(
                    draft.model_dump(mode="json", exclude={"signature"})
                ),
                recorded_at=now,
            )
            health = ContextSourceHealthV2(
                owner_id=self.owner_id,
                source_instance_id=draft.source_instance_id,
                capability_revision_id=draft.capability_revision_id,
                status=draft.status,
                checked_at=draft.checked_at,
                safe_error_category=draft.safe_error_category,
                adapter_version=draft.adapter_version,
                source_version=draft.source_version,
                trace_id=draft.trace_id,
            )
            self._insert_health(connection, health, draft=draft)
            return health

    @staticmethod
    def _validate_draft_against_consent(
        *, draft: ContextObservationDraft, consent: ConsentScopeRevision,
        now: datetime,
    ) -> None:
        if consent.status != "active":
            raise ContextIngestRejected("consent is not active")
        if not (consent.effective_at <= now < consent.expires_at):
            raise ContextIngestRejected("consent is not currently valid")
        if not (consent.effective_at <= draft.source_observed_at < consent.expires_at):
            raise ContextIngestRejected("draft falls outside consent validity")
        if (
            draft.source_instance_id != consent.source_instance_id
            or draft.capability_revision_id != consent.capability_revision_id
            or draft.observation_kind not in consent.allowed_observation_kinds
            or draft.sampling_policy_version != consent.sampling_policy.policy_version
            or draft.retention_policy_version != consent.retention_policy.policy_version
            or draft.data_policy != consent.data_policy
        ):
            raise ContextIngestRejected("draft does not match exact consent scope")
        if tuple(sorted(draft.value.model_dump(mode="json", exclude={"schema_version"}))) != tuple(
            sorted(consent.allowed_fields)
        ):
            raise ContextIngestRejected("draft fields exceed consent scope")

    def _insert_event_scaffold(
        self, *, connection, event: EventEnvelope,
        idempotency_key: str, request_fingerprint: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO havre.sessions (session_id, owner_id, channel)
            VALUES (%s,%s,'api')
            """,
            (event.session_id, event.owner_id),
        )
        connection.execute(
            """
            INSERT INTO havre.traces (
                trace_id, owner_id, root_request_id, trace_flags, started_at
            ) VALUES (%s,%s,%s,'01',%s)
            """,
            (event.trace_id, event.owner_id, event.request_id, event.recorded_at),
        )
        connection.execute(
            """
            INSERT INTO havre.interaction_requests (
                request_id, owner_id, session_id, trace_id, idempotency_key,
                request_fingerprint, request_kind, status, completed_at
            ) VALUES (%s,%s,%s,%s,%s,%s,'context_ingest','completed',%s)
            """,
            (
                event.request_id, event.owner_id, event.session_id, event.trace_id,
                idempotency_key, request_fingerprint, event.recorded_at,
            ),
        )
        PostgresRepository._insert_event(connection, event)

    def _insert_operational_scaffold(
        self, *, connection, trace_id: str, idempotency_key: str,
        request_fingerprint: str, recorded_at: datetime,
    ) -> None:
        session_id = uuid7()
        request_id = uuid7()
        connection.execute(
            "INSERT INTO havre.sessions (session_id, owner_id, channel) VALUES (%s,%s,'api')",
            (session_id, self.owner_id),
        )
        connection.execute(
            """
            INSERT INTO havre.traces (
                trace_id, owner_id, root_request_id, trace_flags, started_at
            ) VALUES (%s,%s,%s,'01',%s)
            """,
            (trace_id, self.owner_id, request_id, recorded_at),
        )
        connection.execute(
            """
            INSERT INTO havre.interaction_requests (
                request_id, owner_id, session_id, trace_id, idempotency_key,
                request_fingerprint, request_kind, status, completed_at
            ) VALUES (%s,%s,%s,%s,%s,%s,'context_ingest','completed',%s)
            """,
            (
                request_id, self.owner_id, session_id, trace_id,
                idempotency_key, request_fingerprint, recorded_at,
            ),
        )

    @staticmethod
    def _insert_observation(connection, observation: LifeContextObservationV2) -> None:
        policy = observation.data_policy
        connection.execute(
            """
            INSERT INTO havre.life_context_observations (
                observation_id, draft_id, schema_version, owner_id, source_instance_id,
                capability_revision_id, capability_id, observation_kind,
                observation_schema_version, value, occurred_from, occurred_to,
                source_observed_at, ingested_at, fresh_until,
                retention_expires_at, consent_scope_revision_id,
                sampling_policy_version, retention_policy_version, adapter_version,
                privacy_class, memory_eligible, training_eligible, cloud_eligible,
                policy_version, policy_revision_id, policy_decision_source,
                policy_authorization_ref, event_id, trace_id, idempotency_key,
                draft_content_hash, device_binding_id, draft_signing_material,
                device_signature, measurement_quality, clock_quality,
                limitations, canonical_content_material, content_hash
            ) VALUES (
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                %s,%s,%s,%s
            )
            """,
            (
                observation.observation_id, observation.draft_id,
                observation.schema_version,
                observation.owner_id, observation.source_instance_id,
                observation.capability_revision_id, observation.capability_id,
                observation.observation_kind,
                observation.observation_schema_version,
                Jsonb(observation.value.model_dump(mode="json")),
                observation.occurred_from, observation.occurred_to,
                observation.source_observed_at, observation.ingested_at,
                observation.fresh_until, observation.retention_expires_at,
                observation.consent_scope_revision_id,
                observation.sampling_policy_version,
                observation.retention_policy_version, observation.adapter_version,
                policy.privacy_class.value, policy.memory_eligible,
                policy.training_eligible, policy.cloud_eligible,
                policy.policy_version, policy.policy_revision_id,
                policy.decision_source, policy.authorization_ref,
                observation.event_id, observation.trace_id,
                observation.idempotency_key, observation.draft_content_hash,
                observation.device_binding_id,
                observation.draft_signing_material,
                observation.device_signature,
                observation.measurement_quality, observation.clock_quality,
                Jsonb(list(observation.limitations)),
                canonical_json(
                    observation.model_dump(mode="json", exclude={"content_hash"})
                ),
                observation.content_hash,
            ),
        )

    @staticmethod
    def _insert_health(
        connection, health: ContextSourceHealthV2,
        *, draft: ContextSourceHealthDraft | None = None,
        causal_event_id: UUID | None = None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO havre.context_source_health_records (
                health_id, health_draft_id, schema_version, owner_id, source_instance_id,
                capability_revision_id, status, checked_at,
                last_successful_observation_id, last_successful_observation_at,
                coverage_from, coverage_to,
                safe_error_category, adapter_version, source_version, trace_id,
                idempotency_key, device_binding_id, draft_signing_material,
                device_signature, causal_event_id, canonical_content_material,
                content_hash
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                health.health_id, None if draft is None else draft.draft_id,
                health.schema_version, health.owner_id,
                health.source_instance_id, health.capability_revision_id,
                health.status, health.checked_at,
                health.last_successful_observation_id,
                health.last_successful_observation_at, health.coverage_from,
                health.coverage_to, health.safe_error_category,
                health.adapter_version, health.source_version, health.trace_id,
                None if draft is None else draft.idempotency_key,
                None if draft is None else draft.device_binding_id,
                None if draft is None else draft.signing_material(),
                None if draft is None else draft.signature,
                causal_event_id,
                canonical_json(health.model_dump(mode="json", exclude={"content_hash"})),
                health.content_hash,
            ),
        )

    def _source_state_event(
        self, *, source: ContextSourceDescriptor,
        state: ContextSourceStateRevision, data_policy: DataPolicy,
    ) -> EventEnvelope:
        if data_policy.authorization_ref != state.authorization_ref:
            raise ContextIngestRejected("source state authorization mismatch")
        return EventEnvelope(
            event_type=EventType.CONTEXT_SOURCE_STATE_REVISED,
            owner_id=self.owner_id,
            session_id=uuid7(), request_id=uuid7(), trace_id=new_trace_id(),
            data_policy=data_policy,
            payload=ContextSourceLifecyclePayload(
                source_instance_id=source.source_instance_id,
                state_revision_id=state.state_revision_id,
                revision=state.revision,
                action=state.status,
                reason=state.reason,
                source_content_hash=source.content_hash,
                state_content_hash=state.content_hash,
            ),
        )

    def _capability_state_event(
        self, *, capability: ContextSourceCapability,
        state: ContextCapabilityStateRevision, data_policy: DataPolicy,
    ) -> EventEnvelope:
        if data_policy.authorization_ref != state.authorization_ref:
            raise ContextIngestRejected("capability state authorization mismatch")
        return EventEnvelope(
            event_type=EventType.CONTEXT_CAPABILITY_STATE_REVISED,
            owner_id=self.owner_id,
            session_id=uuid7(), request_id=uuid7(), trace_id=new_trace_id(),
            data_policy=data_policy,
            payload=ContextCapabilityLifecyclePayload(
                source_instance_id=capability.source_instance_id,
                capability_revision_id=capability.capability_revision_id,
                state_revision_id=state.state_revision_id,
                revision=state.revision,
                action=state.status,
                reason=state.reason,
                capability_content_hash=capability.content_hash,
                state_content_hash=state.content_hash,
            ),
        )

    @staticmethod
    def _insert_source_state(connection, state: ContextSourceStateRevision, event_id: UUID) -> None:
        connection.execute(
            """
            INSERT INTO havre.context_source_state_revisions (
                state_revision_id, schema_version, owner_id, source_instance_id,
                revision, status, reason, effective_at, authorization_ref,
                decision_event_id, content_hash
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                state.state_revision_id, state.schema_version, state.owner_id,
                state.source_instance_id, state.revision, state.status, state.reason,
                state.effective_at, state.authorization_ref, event_id, state.content_hash,
            ),
        )

    @staticmethod
    def _insert_capability_state(
        connection, state: ContextCapabilityStateRevision, event_id: UUID
    ) -> None:
        connection.execute(
            """
            INSERT INTO havre.context_capability_state_revisions (
                state_revision_id, schema_version, owner_id, capability_revision_id,
                revision, status, reason, effective_at, authorization_ref,
                decision_event_id, content_hash
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                state.state_revision_id, state.schema_version, state.owner_id,
                state.capability_revision_id, state.revision, state.status,
                state.reason, state.effective_at, state.authorization_ref,
                event_id, state.content_hash,
            ),
        )

    @staticmethod
    def _source_from_row(row) -> ContextSourceDescriptor:
        return ContextSourceDescriptor.model_validate({
            "schema_version": row["schema_version"],
            "source_instance_id": row["source_instance_id"],
            "owner_id": row["owner_id"],
            "source_kind": row["source_kind"],
            "provider_id": row["provider_id"],
            "device_binding_id": row["device_binding_id"],
            "adapter_version": row["adapter_version"],
            "source_version": row["source_version"],
            "provider_tenant_binding": row["provider_tenant_binding"],
            "provider_account_binding": row["provider_account_binding"],
            "enrollment_status": row["enrollment_status"],
            "content_hash": row["content_hash"],
        })

    @staticmethod
    def _source_state_from_row(row) -> ContextSourceStateRevision:
        return ContextSourceStateRevision.model_validate({
            "schema_version": row["schema_version"],
            "state_revision_id": row["state_revision_id"],
            "owner_id": row["owner_id"],
            "source_instance_id": row["source_instance_id"],
            "revision": row["revision"],
            "status": row["status"],
            "reason": row["reason"],
            "effective_at": row["effective_at"],
            "authorization_ref": row["authorization_ref"],
            "content_hash": row["content_hash"],
        })

    @staticmethod
    def _capability_from_row(row) -> ContextSourceCapability:
        return ContextSourceCapability.model_validate({
            "schema_version": row["schema_version"],
            "capability_revision_id": row["capability_revision_id"],
            "owner_id": row["owner_id"],
            "source_instance_id": row["source_instance_id"],
            "capability_id": row["capability_id"],
            "revision": row["revision"],
            "observation_kind": row["observation_kind"],
            "observation_schema_version": row["observation_schema_version"],
            "allowed_fields": row["allowed_fields"],
            "precision": row["precision"],
            "sampling_modes": row["sampling_modes"],
            "conformance_version": row["conformance_version"],
            "status": row["status"],
            "content_hash": row["content_hash"],
        })

    @staticmethod
    def _capability_state_from_row(row) -> ContextCapabilityStateRevision:
        return ContextCapabilityStateRevision.model_validate({
            "schema_version": row["schema_version"],
            "state_revision_id": row["state_revision_id"],
            "owner_id": row["owner_id"],
            "capability_revision_id": row["capability_revision_id"],
            "revision": row["revision"],
            "status": row["status"],
            "reason": row["reason"],
            "effective_at": row["effective_at"],
            "authorization_ref": row["authorization_ref"],
            "content_hash": row["content_hash"],
        })

    @staticmethod
    def _health_from_row(row) -> ContextSourceHealthV2:
        return ContextSourceHealthV2.model_validate({
            "schema_version": row["schema_version"],
            "health_id": row["health_id"],
            "owner_id": row["owner_id"],
            "source_instance_id": row["source_instance_id"],
            "capability_revision_id": row["capability_revision_id"],
            "status": row["status"],
            "checked_at": row["checked_at"],
            "last_successful_observation_id": row["last_successful_observation_id"],
            "last_successful_observation_at": row["last_successful_observation_at"],
            "coverage_from": row["coverage_from"],
            "coverage_to": row["coverage_to"],
            "safe_error_category": row["safe_error_category"],
            "adapter_version": row["adapter_version"],
            "source_version": row["source_version"],
            "trace_id": row["trace_id"].strip(),
            "content_hash": row["content_hash"],
        })

    @staticmethod
    def _consent_from_row(row) -> ConsentScopeRevision:
        return ConsentScopeRevision.model_validate(
            {
                "schema_version": row["schema_version"],
                "consent_scope_revision_id": row["consent_scope_revision_id"],
                "consent_scope_id": row["consent_scope_id"],
                "owner_id": row["owner_id"],
                "source_instance_id": row["source_instance_id"],
                "capability_revision_id": row["capability_revision_id"],
                "revision": row["revision"],
                "status": row["status"],
                "purpose": row["purpose"],
                "allowed_observation_kinds": row["allowed_observation_kinds"],
                "allowed_fields": row["allowed_fields"],
                "permitted_destinations": row["permitted_destinations"],
                "sampling_policy": row["sampling_policy"],
                "retention_policy": row["retention_policy"],
                "data_policy": row["data_policy"],
                "effective_at": row["effective_at"],
                "expires_at": row["expires_at"],
                "authorization_ref": row["authorization_ref"],
                "content_hash": row["content_hash"],
            }
        )

    @staticmethod
    def _observation_from_row(row) -> LifeContextObservationV2:
        return LifeContextObservationV2.model_validate(
            {
                "schema_version": row["schema_version"],
                "observation_id": row["observation_id"],
                "draft_id": row["draft_id"],
                "owner_id": row["owner_id"],
                "source_instance_id": row["source_instance_id"],
                "capability_revision_id": row["capability_revision_id"],
                "capability_id": row["capability_id"],
                "observation_kind": row["observation_kind"],
                "observation_schema_version": row["observation_schema_version"],
                "value": row["value"],
                "occurred_from": row["occurred_from"],
                "occurred_to": row["occurred_to"],
                "source_observed_at": row["source_observed_at"],
                "ingested_at": row["ingested_at"],
                "fresh_until": row["fresh_until"],
                "retention_expires_at": row["retention_expires_at"],
                "consent_scope_revision_id": row["consent_scope_revision_id"],
                "sampling_policy_version": row["sampling_policy_version"],
                "retention_policy_version": row["retention_policy_version"],
                "adapter_version": row["adapter_version"],
                "data_policy": {
                    "schema_version": 1,
                    "policy_revision_id": row["policy_revision_id"],
                    "privacy_class": row["privacy_class"],
                    "memory_eligible": row["memory_eligible"],
                    "training_eligible": row["training_eligible"],
                    "cloud_eligible": row["cloud_eligible"],
                    "policy_version": row["policy_version"],
                    "decision_source": row["policy_decision_source"],
                    "authorization_ref": row["policy_authorization_ref"],
                },
                "event_id": row["event_id"],
                "trace_id": row["trace_id"].strip(),
                "idempotency_key": row["idempotency_key"],
                "draft_content_hash": row["draft_content_hash"],
                "device_binding_id": row["device_binding_id"],
                "draft_signing_material": row["draft_signing_material"],
                "device_signature": row["device_signature"],
                "measurement_quality": row["measurement_quality"],
                "clock_quality": row["clock_quality"],
                "limitations": row["limitations"],
                "content_hash": row["content_hash"],
            }
        )
