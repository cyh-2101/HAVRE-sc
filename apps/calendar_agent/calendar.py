"""Provider-neutral Calendar availability projection.

Provider-native content exists only inside the owner-local provider.  The
adapter emits the stable, minimized HAVRE availability contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import hmac
from typing import Callable, Protocol
import uuid

from companion.hashing import canonical_json
from companion.life_context import (
    CalendarAvailabilityWindow,
    ConsentScopeRevision,
    ContextCollectionPermit,
    ContextObservationDraft,
    ContextSourceCapability,
    ContextSourceDescriptor,
    sign_observation_draft,
)


class CalendarAvailabilityProvider(Protocol):
    def read_all_calendar_availability(
        self,
        *,
        window_from: datetime,
        window_to: datetime,
        before_read: Callable[[], None] | None = None,
    ) -> tuple[CalendarAvailabilityWindow, int, int]: ...


@dataclass(frozen=True)
class CalendarCollectionResult:
    draft: ContextObservationDraft
    calendars_seen: int
    provider_rows_seen: int
    retained_busy_intervals: int


def opaque_manual_calendar_binding(label: str) -> str:
    normalized = label.strip().casefold()
    if not normalized or len(normalized) > 200:
        raise ValueError("manual Calendar source label is required and bounded")
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class CalendarAvailabilityAdapter:
    def __init__(
        self,
        *,
        source: ContextSourceDescriptor,
        capability: ContextSourceCapability,
        consent: ConsentScopeRevision,
        signing_secret: bytes,
        provider: CalendarAvailabilityProvider,
        permit_resolver: Callable[[], ContextCollectionPermit],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if source.source_kind != "calendar":
            raise ValueError("Calendar adapter requires a Calendar source")
        if (
            capability.capability_id != "calendar.read_availability.v1"
            or capability.allowed_fields != ("busy_intervals",)
        ):
            raise ValueError("Calendar adapter requires availability-only capability")
        if (
            capability.source_instance_id != source.source_instance_id
            or consent.source_instance_id != source.source_instance_id
            or consent.capability_revision_id != capability.capability_revision_id
            or consent.allowed_fields != ("busy_intervals",)
        ):
            raise ValueError("Calendar adapter requires one exact consent chain")
        self.source = source
        self.capability = capability
        self.consent = consent
        self.signing_secret = signing_secret
        self.provider = provider
        self.permit_resolver = permit_resolver
        self.clock = clock

    def _require_current_permit(self) -> None:
        permit = self.permit_resolver()
        if (
            permit.source.source_instance_id != self.source.source_instance_id
            or permit.source.device_binding_id != self.source.device_binding_id
            or permit.capability.capability_revision_id
                != self.capability.capability_revision_id
            or permit.capability.capability_id != self.capability.capability_id
            or permit.consent.consent_scope_revision_id
                != self.consent.consent_scope_revision_id
            or permit.valid_until <= self.clock()
        ):
            raise PermissionError("Calendar collection permit is not current")

    def collect(
        self, *, window_from: datetime, window_to: datetime
    ) -> CalendarCollectionResult:
        value, rows_seen, calendars_seen = self.provider.read_all_calendar_availability(
            window_from=window_from,
            window_to=window_to,
            before_read=self._require_current_permit,
        )
        observed_at = self.clock()
        fingerprint = hmac.new(
            self.signing_secret,
            canonical_json(
                {
                    "source_instance_id": str(self.source.source_instance_id),
                    "window_from": window_from.astimezone(UTC).isoformat(),
                    "window_to": window_to.astimezone(UTC).isoformat(),
                    "value": value.model_dump(mode="json"),
                }
            ).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        draft = sign_observation_draft(
            ContextObservationDraft(
                owner_id=self.source.owner_id,
                source_instance_id=self.source.source_instance_id,
                device_binding_id=self.source.device_binding_id,
                capability_revision_id=self.capability.capability_revision_id,
                capability_id=self.capability.capability_id,
                observation_kind=self.capability.observation_kind,
                value=value,
                occurred_from=window_from,
                occurred_to=window_to,
                source_observed_at=observed_at,
                consent_scope_revision_id=self.consent.consent_scope_revision_id,
                sampling_policy_version=self.consent.sampling_policy.policy_version,
                retention_policy_version=self.consent.retention_policy.policy_version,
                adapter_version=self.source.adapter_version,
                data_policy=self.consent.data_policy,
                idempotency_key=f"calendar-window:{fingerprint}",
                trace_id=uuid.uuid4().hex,
            ),
            secret=self.signing_secret,
        )
        return CalendarCollectionResult(
            draft=draft,
            calendars_seen=calendars_seen,
            provider_rows_seen=rows_seen,
            retained_busy_intervals=len(value.busy_intervals),
        )
