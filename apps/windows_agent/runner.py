"""One authorized, bounded Windows collection/reconciliation cycle."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Callable

from companion.life_context import ContextObservationDraft, ContextSourceHealthDraft

from apps.windows_agent.coarse_context import (
    CollectionNotAuthorized,
    ProbeUnavailable,
    WindowsCoarseContextAdapter,
)
from apps.windows_agent.offline_queue import ProtectedOfflineQueue
from apps.windows_agent.transport import (
    ContextTransportRejected,
    ContextTransportUnavailable,
    WindowsAgentTransport,
)


class WindowsAgentRunner:
    def __init__(
        self, *, transport: WindowsAgentTransport,
        queue: ProtectedOfflineQueue,
        adapter_factory: Callable[..., WindowsCoarseContextAdapter] = WindowsCoarseContextAdapter,
    ) -> None:
        self.transport = transport
        self.queue = queue
        self.adapter_factory = adapter_factory

    def run_once(self) -> dict[str, object]:
        self.queue.prune_expired()
        try:
            permit = self.transport.request_permit()
        except ContextTransportRejected:
            self.queue.erase()
            return self._report("authorization_rejected", replayed=0, queued=False)
        except ContextTransportUnavailable:
            return self._report("core_unavailable", replayed=0, queued=False)

        replayed = 0
        for item in self.queue.load():
            try:
                if item.kind == "observation":
                    self.transport.submit_observation(
                        ContextObservationDraft.model_validate(item.payload)
                    )
                else:
                    self.transport.submit_health(
                        ContextSourceHealthDraft.model_validate(item.payload)
                    )
            except ContextTransportRejected:
                self.queue.erase()
                return self._report(
                    "authorization_rejected", replayed=replayed, queued=False
                )
            except ContextTransportUnavailable:
                return self._report("core_unavailable", replayed=replayed, queued=True)
            self.queue.remove(item.queue_id)
            replayed += 1

        adapter = self.adapter_factory(
            source=permit.source,
            capability=permit.capability,
            consent=permit.consent,
            signing_secret=self.transport.signing_secret,
            authorization_resolver=self.transport.request_permit,
        )
        try:
            draft = adapter.collect_window()
        except ContextTransportRejected:
            self.queue.erase()
            return self._report("authorization_rejected", replayed=replayed, queued=False)
        except ContextTransportUnavailable:
            return self._report("core_unavailable", replayed=replayed, queued=False)
        except CollectionNotAuthorized:
            self.queue.erase()
            return self._report("authorization_rejected", replayed=replayed, queued=False)
        except ProbeUnavailable as error:
            health = adapter.build_health_draft(
                status="degraded",
                safe_error_category=error.safe_error_category,
                checked_at=datetime.now(UTC),
            )
            return self._submit_or_queue_health(
                health=health, permit=permit, replayed=replayed
            )
        try:
            self.transport.submit_observation(draft)
        except ContextTransportRejected:
            self.queue.erase()
            return self._report("authorization_rejected", replayed=replayed, queued=False)
        except ContextTransportUnavailable:
            queued = self._queue(
                kind="observation", draft=draft, permit=permit
            )
            return self._report("core_unavailable", replayed=replayed, queued=queued)
        return self._report("observation_submitted", replayed=replayed, queued=False)

    def _submit_or_queue_health(self, *, health, permit, replayed: int) -> dict[str, object]:
        try:
            self.transport.submit_health(health)
        except ContextTransportRejected:
            self.queue.erase()
            return self._report("authorization_rejected", replayed=replayed, queued=False)
        except ContextTransportUnavailable:
            queued = self._queue(kind="health", draft=health, permit=permit)
            return self._report("health_unavailable", replayed=replayed, queued=queued)
        return self._report("health_submitted", replayed=replayed, queued=False)

    def _queue(self, *, kind: str, draft, permit) -> bool:
        permitted = min(
            permit.consent.sampling_policy.offline_buffer_seconds,
            permit.consent.retention_policy.normalized_draft_retention_seconds,
        )
        if permitted <= 0:
            return False
        self.queue.enqueue(
            kind=kind, draft=draft, max_age_seconds=permitted,
        )
        return True

    @staticmethod
    def _report(status: str, *, replayed: int, queued: bool) -> dict[str, object]:
        return {
            "schema_version": 1,
            "status": status,
            "replayed_count": replayed,
            "queued": queued,
            "content_included": False,
            "automatic_loop_enabled": False,
        }
