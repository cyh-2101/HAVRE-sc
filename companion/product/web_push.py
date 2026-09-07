"""Governed, generic-only Web Push delivery for durable proactive messages."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from typing import Any, Callable
from uuid import UUID

from psycopg.types.json import Jsonb

from companion.hashing import content_hash
from companion.ids import uuid7
from companion.persistence.postgres import PostgresRepository
from companion.product.daily import (
    acquire_web_push_owner_lock,
    validate_web_push_endpoint,
)

PushSender = Callable[[dict[str, Any], str], str]
TailnetAttestor = Callable[[], bool]


class WebPushDeliveryProvider:
    """At-least-once transport with one durable, leased dispatch per endpoint."""

    adapter_version = "web-push-vapid-v2"
    payload_policy_version = "generic-private-preview-v1"
    authorization_ref = "po-private-web-push-2026-08-27"
    pwa_shell_version = "havre-shell-v5"

    def __init__(
        self, *, repository: PostgresRepository, owner_id: UUID,
        public_base_url: str | None, vapid_private_key: str | None,
        vapid_subject: str | None, enabled: bool,
        vapid_public_key: str | None = None,
        vapid_key_version: str | None = None,
        sender: PushSender | None = None, worker_id: str | None = None,
        lease_seconds: int = 90,
        retry_base_seconds: int = 5,
        max_attempts: int = 4,
        tailnet_attested: bool = False,
        tailnet_attestor: TailnetAttestor | None = None,
    ) -> None:
        self.repository = repository
        self.owner_id = owner_id
        self.public_base_url = public_base_url.rstrip("/") if public_base_url else None
        self.vapid_private_key = vapid_private_key
        self.vapid_subject = vapid_subject
        self.vapid_public_key = vapid_public_key
        self.vapid_key_version = vapid_key_version
        self.enabled = enabled
        self.sender = sender or self._protocol_send
        self.worker_id = worker_id or f"web-push-{uuid7()}"
        if lease_seconds < 1 or lease_seconds > 300:
            raise ValueError("web push lease must be between 1 and 300 seconds")
        self.lease_seconds = lease_seconds
        if retry_base_seconds < 1 or retry_base_seconds > 300:
            raise ValueError("web push retry base must be between 1 and 300 seconds")
        self.retry_base_seconds = retry_base_seconds
        if max_attempts < 1 or max_attempts > 8:
            raise ValueError("web push max attempts must be between 1 and 8")
        self.max_attempts = max_attempts
        self.tailnet_attested = tailnet_attested
        self.tailnet_attestor = tailnet_attestor
        self.worker_instance_id = uuid7()
        self.worker_started_at = datetime.now(UTC)
        self.send_timeout_seconds = max(0.1, min(30.0, lease_seconds / 2))

    @property
    def available(self) -> bool:
        try:
            attested = (
                bool(self.tailnet_attestor())
                if self.tailnet_attestor is not None
                else self.tailnet_attested
            )
        except Exception:
            attested = False
        return bool(
            self.enabled and attested and self.public_base_url
            and self.public_base_url.startswith("https://")
            and self.vapid_private_key and self.vapid_public_key
            and self.vapid_key_version and self.vapid_subject
        )

    @property
    def runtime_ready(self) -> bool:
        return self.available and self.worker_status()["live"]

    @property
    def real_device_validated(self) -> bool:
        """Whether an exact real-device receipt/tap/timeline chain was confirmed."""
        with self.repository.pool.connection() as connection:
            row = connection.execute(
                """SELECT 1 FROM havre.web_push_real_device_validations
                   WHERE owner_id=%s AND pwa_shell_version=%s LIMIT 1""",
                (self.owner_id,self.pwa_shell_version),
            ).fetchone()
        return row is not None

    @property
    def delivery_active(self) -> bool:
        """Runtime-ready delivery with a still-active validated device path."""
        if not self.runtime_ready or self.vapid_key_version is None:
            return False
        with self.repository.pool.connection() as connection:
            row = connection.execute(
                """SELECT 1
                   FROM havre.web_push_real_device_validations validation
                   JOIN havre.web_push_subscriptions subscription
                     ON subscription.owner_id=validation.owner_id
                    AND subscription.subscription_id=validation.subscription_id
                   JOIN havre.companion_devices device
                     ON device.owner_id=validation.owner_id
                    AND device.device_id=validation.device_id
                   JOIN havre.web_push_vapid_key_versions vapid
                     ON vapid.owner_id=subscription.owner_id
                    AND vapid.vapid_key_version=subscription.vapid_key_version
                   WHERE validation.owner_id=%s
                     AND subscription.status='active'
                     AND subscription.vapid_key_version=%s
                     AND (subscription.expires_at IS NULL
                          OR subscription.expires_at>clock_timestamp())
                     AND device.revoked_at IS NULL
                     AND device.session_expires_at>clock_timestamp()
                     AND vapid.status='active'
                     AND validation.pwa_shell_version=%s
                   LIMIT 1""",
                (self.owner_id,self.vapid_key_version,self.pwa_shell_version),
            ).fetchone()
        return row is not None

    def record_real_device_validation(
        self, *, delivery_locator: UUID, device_id: UUID,
        pwa_shell_version: str, owner_confirmation_ref: str,
    ) -> dict[str, Any]:
        """Record an owner-confirmed physical receipt/tap/timeline outcome."""
        if pwa_shell_version != self.pwa_shell_version:
            raise ValueError("PWA shell version is not the current served revision")
        if not owner_confirmation_ref.strip():
            raise ValueError("owner confirmation reference is required")
        with self.repository.pool.connection() as connection, connection.transaction():
            acquire_web_push_owner_lock(connection, self.owner_id)
            row = connection.execute(
                """SELECT dispatch.dispatch_id,dispatch.delivery_locator,
                          dispatch.subscription_id,dispatch.assistant_event_id,
                          subscription.device_id,attempt.web_push_attempt_id
                   FROM havre.web_push_dispatches dispatch
                   JOIN havre.web_push_subscriptions subscription
                     ON subscription.owner_id=dispatch.owner_id
                    AND subscription.subscription_id=dispatch.subscription_id
                   JOIN havre.web_push_delivery_attempts attempt
                     ON attempt.owner_id=dispatch.owner_id
                    AND attempt.dispatch_id=dispatch.dispatch_id
                   WHERE dispatch.owner_id=%s
                     AND dispatch.delivery_locator=%s
                     AND subscription.device_id=%s
                     AND dispatch.status='accepted'
                     AND attempt.status='delivered'
                     AND attempt.provider_receipt_id IS NOT NULL
                   ORDER BY attempt.attempt_number DESC
                   LIMIT 1
                   FOR UPDATE OF dispatch,subscription,attempt""",
                (self.owner_id,delivery_locator,device_id),
            ).fetchone()
            if row is None:
                raise LookupError("delivered notification evidence not found")
            existing = connection.execute(
                """SELECT * FROM havre.web_push_real_device_validations
                   WHERE owner_id=%s AND dispatch_id=%s""",
                (self.owner_id,row["dispatch_id"]),
            ).fetchone()
            if existing is not None:
                if existing["pwa_shell_version"] != pwa_shell_version:
                    raise ValueError(
                        "delivered notification was validated for a different PWA shell; "
                        "a fresh delivery is required"
                    )
                return dict(existing)
            validation_id = uuid7()
            validated = connection.execute(
                """INSERT INTO havre.web_push_real_device_validations
                   (owner_id,validation_id,dispatch_id,web_push_attempt_id,
                    subscription_id,device_id,assistant_event_id,delivery_locator,
                    validation_kind,pwa_shell_version,owner_confirmation_ref,
                    lock_screen_received,notification_tap_opened,
                    timeline_message_located)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,
                           'lock_screen_tap_timeline_located',%s,%s,true,true,true)
                   RETURNING *""",
                (
                    self.owner_id,validation_id,row["dispatch_id"],
                    row["web_push_attempt_id"],row["subscription_id"],
                    row["device_id"],row["assistant_event_id"],
                    row["delivery_locator"],pwa_shell_version,
                    owner_confirmation_ref.strip(),
                ),
            ).fetchone()
        return dict(validated)

    def record_worker_heartbeat(
        self, *, status: str, live_for_seconds: float
    ) -> None:
        if status not in {"running", "stopped"}:
            raise ValueError("worker heartbeat status is invalid")
        if status == "running" and not self.available:
            status = "stopped"
        live_for_seconds = max(1.0, min(float(live_for_seconds), 300.0))
        with self.repository.pool.connection() as connection, connection.transaction():
            connection.execute(
                """INSERT INTO havre.web_push_worker_heartbeats
                   (owner_id,worker_instance_id,worker_id,adapter_version,status,
                    started_at,last_seen_at,live_until)
                   VALUES (%s,%s,%s,%s,%s,%s,clock_timestamp(),
                           clock_timestamp()+make_interval(secs => %s))
                   ON CONFLICT (owner_id,worker_instance_id) DO UPDATE SET
                     status=EXCLUDED.status,last_seen_at=EXCLUDED.last_seen_at,
                     live_until=EXCLUDED.live_until""",
                (
                    self.owner_id,self.worker_instance_id,self.worker_id,
                    self.adapter_version,status,self.worker_started_at,
                    0 if status == "stopped" else live_for_seconds,
                ),
            )

    def worker_status(self) -> dict[str, Any]:
        with self.repository.pool.connection() as connection:
            row = connection.execute(
                """SELECT worker_instance_id,worker_id,status,started_at,last_seen_at,
                          live_until,(status='running' AND live_until>clock_timestamp()) AS live
                   FROM havre.web_push_worker_heartbeats
                   WHERE owner_id=%s ORDER BY last_seen_at DESC LIMIT 1""",
                (self.owner_id,),
            ).fetchone()
        if row is None:
            return {"live":False,"status":"missing","last_seen_at":None}
        return {
            "live":bool(row["live"]),"status":row["status"],
            "worker_id":row["worker_id"],"last_seen_at":row["last_seen_at"],
            "live_until":row["live_until"],
        }

    def _protocol_send(self, subscription: dict[str, Any], payload: str) -> str:
        try:
            from pywebpush import webpush
            from requests import Session
        except ImportError as error:
            raise RuntimeError("web push protocol dependencies are not installed") from error
        endpoint = validate_web_push_endpoint(str(subscription["endpoint"]))
        session = Session()
        session.trust_env = False
        session.max_redirects = 0
        try:
            response = webpush(
                subscription_info={
                    "endpoint": endpoint,
                    "keys": {
                        "p256dh": subscription["p256dh"],
                        "auth": subscription["auth_secret"],
                    },
                },
                data=payload, vapid_private_key=self.vapid_private_key,
                vapid_claims={"sub": self.vapid_subject}, ttl=300,
                timeout=self.send_timeout_seconds, requests_session=session,
            )
        finally:
            session.close()
        return str(
            response.headers.get("Location")
            or response.headers.get("X-Request-Id")
            or f"webpush-accepted-{response.status_code}"
        )

    def ensure_configuration(self) -> None:
        if not self.available:
            raise ValueError("live private Tailscale Serve attestation is required")
        assert self.vapid_public_key is not None and self.vapid_key_version is not None
        with self.repository.pool.connection() as connection, connection.transaction():
            existing = connection.execute(
                """SELECT public_key,public_key_hash,status
                   FROM havre.web_push_vapid_key_versions
                   WHERE owner_id=%s AND vapid_key_version=%s""",
                (self.owner_id, self.vapid_key_version),
            ).fetchone()
            key_hash = content_hash({"public_key": self.vapid_public_key})
            if existing is not None:
                if existing["public_key"] != self.vapid_public_key or existing["public_key_hash"] != key_hash:
                    raise ValueError("VAPID version already binds different public key bytes")
                if existing["status"] != "active":
                    raise ValueError("configured VAPID version is not active")
                return
            connection.execute(
                """INSERT INTO havre.web_push_vapid_key_versions
                   (owner_id,vapid_key_version,public_key,public_key_hash,secret_storage,
                    status,authorization_ref)
                   VALUES (%s,%s,%s,%s,'windows_dpapi_current_user','active',%s)""",
                (self.owner_id, self.vapid_key_version, self.vapid_public_key,
                 key_hash, self.authorization_ref),
            )

    def enqueue_eligible(self, *, limit: int = 200) -> int:
        """Create durable pre-send dispatches only for an exact SEND_NOW chain."""
        if not self.available:
            return 0
        self.ensure_configuration()
        with self.repository.pool.connection() as connection, connection.transaction():
            acquire_web_push_owner_lock(connection, self.owner_id)
            rows = connection.execute(
                """SELECT subscription.subscription_id,inbox.assistant_event_id,
                          inbox.delivery_attempt_id,
                          LEAST(decision.expires_at,proposal.expires_at) AS eligible_until
                   FROM havre.proactive_inbox_messages inbox
                   JOIN havre.events event ON event.owner_id=inbox.owner_id
                    AND event.event_id=inbox.assistant_event_id
                   JOIN havre.proactive_delivery_attempts attempt
                    ON attempt.owner_id=inbox.owner_id
                   AND attempt.delivery_attempt_id=inbox.delivery_attempt_id
                   JOIN havre.interruption_decisions decision
                    ON decision.owner_id=attempt.owner_id
                   AND decision.interruption_decision_id=attempt.interruption_decision_id
                   JOIN havre.proactive_proposals proposal
                    ON proposal.owner_id=decision.owner_id
                   AND proposal.proposal_id=decision.proposal_id
                   JOIN havre.proactive_preference_revisions preference
                    ON preference.owner_id=decision.owner_id
                   AND preference.preference_revision_id=decision.preference_revision_id
                   JOIN havre.web_push_subscriptions subscription
                    ON subscription.owner_id=inbox.owner_id
                   JOIN havre.companion_devices device
                    ON device.owner_id=subscription.owner_id
                   AND device.device_id=subscription.device_id
                   WHERE inbox.owner_id=%s AND decision.decision='SEND_NOW'
                     AND attempt.status='delivered'
                     AND decision.expires_at>clock_timestamp()
                     AND proposal.expires_at>clock_timestamp()
                      AND inbox.external_delivery_admitted_at IS NOT NULL
                      AND inbox.external_delivery_admitted_at>=subscription.delivery_eligible_from
                     AND event.event_type='ASSISTANT_MESSAGE'
                     AND (
                       event.privacy_class IN ('PUBLIC','NORMAL','PRIVATE','HIGHLY_PRIVATE')
                       OR (
                         event.privacy_class='LOCAL_ONLY'
                         AND COALESCE((preference.payload->>'generic_push_for_local_only')::boolean,false)
                       )
                     )
                     AND subscription.status='active'
                     AND subscription.vapid_key_version=%s
                     AND (subscription.expires_at IS NULL OR subscription.expires_at>clock_timestamp())
                     AND device.revoked_at IS NULL
                     AND device.session_expires_at>clock_timestamp()
                     AND NOT EXISTS (
                       SELECT 1 FROM havre.web_push_dispatches dispatch
                       WHERE dispatch.owner_id=inbox.owner_id
                         AND dispatch.subscription_id=subscription.subscription_id
                         AND dispatch.assistant_event_id=inbox.assistant_event_id
                     )
                   ORDER BY inbox.visible_at,subscription.created_at LIMIT %s""",
                (self.owner_id, self.vapid_key_version, max(1, min(limit, 500))),
            ).fetchall()
            inserted = 0
            for row in rows:
                inserted += connection.execute(
                    """INSERT INTO havre.web_push_dispatches
                       (owner_id,dispatch_id,subscription_id,assistant_event_id,
                        proactive_delivery_attempt_id,delivery_locator,vapid_key_version,
                        payload_policy_version,authorization_ref,status,max_attempts,
                        delivery_eligible_until)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending',%s,%s)
                       ON CONFLICT (owner_id,subscription_id,assistant_event_id) DO NOTHING""",
                    (self.owner_id, uuid7(), row["subscription_id"],
                     row["assistant_event_id"], row["delivery_attempt_id"], uuid7(),
                      self.vapid_key_version, self.payload_policy_version,
                      self.authorization_ref,self.max_attempts,row["eligible_until"]),
                ).rowcount
        return inserted

    def _claim(self) -> dict[str, Any] | None:
        with self.repository.pool.connection() as connection, connection.transaction():
            connection.execute(
                """UPDATE havre.web_push_dispatches
                   SET status='expired',last_error_code='delivery_window_expired',
                       completed_at=clock_timestamp()
                   WHERE owner_id=%s AND status IN ('pending','retry_wait')
                     AND delivery_eligible_until<=clock_timestamp()""",
                (self.owner_id,),
            )
            exhausted = connection.execute(
                """SELECT * FROM havre.web_push_dispatches
                   WHERE owner_id=%s AND status='leased'
                     AND lease_expires_at<=clock_timestamp()
                   ORDER BY lease_expires_at,created_at
                   FOR UPDATE SKIP LOCKED LIMIT 1""",
                (self.owner_id,),
            ).fetchone()
            if exhausted is not None:
                payload = {
                    "title":"HAVRE","body":"HAVRE 有条消息给你",
                    "delivery_locator":str(exhausted["delivery_locator"]),
                    "url":f"/chat#delivery-{exhausted['delivery_locator']}",
                }
                retryable = bool(
                    exhausted["attempt_count"] < exhausted["max_attempts"]
                    and exhausted["delivery_eligible_until"] > datetime.now(UTC)
                )
                connection.execute(
                    """INSERT INTO havre.web_push_delivery_attempts
                       (owner_id,web_push_attempt_id,subscription_id,assistant_event_id,
                        proactive_delivery_attempt_id,idempotency_key,attempt_number,status,
                        retryable,preview_level,payload,payload_hash,provider_receipt_id,
                        failure_code,attempted_at,dispatch_id)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,'failed',%s,'private',%s,%s,
                               NULL,'worker_lease_expired_outcome_unknown',clock_timestamp(),%s)""",
                    (self.owner_id,uuid7(),exhausted["subscription_id"],
                     exhausted["assistant_event_id"],
                     exhausted["proactive_delivery_attempt_id"],
                     f"web-push:{exhausted['dispatch_id']}",
                     exhausted["attempt_count"],retryable,Jsonb(payload),content_hash(payload),
                     exhausted["dispatch_id"]),
                )
                next_status = (
                    "expired" if exhausted["delivery_eligible_until"] <= datetime.now(UTC)
                    else "retry_wait" if retryable else "dead"
                )
                connection.execute(
                    """UPDATE havre.web_push_dispatches
                       SET status=%s,lease_owner=NULL,lease_expires_at=NULL,
                           last_error_code='worker_lease_expired_outcome_unknown',
                           next_attempt_at=clock_timestamp(),
                           completed_at=CASE WHEN %s IN ('dead','expired')
                                             THEN clock_timestamp() ELSE NULL END
                       WHERE owner_id=%s AND dispatch_id=%s AND status='leased'
                          AND attempt_count=%s""",
                    (next_status,next_status,self.owner_id,exhausted["dispatch_id"],
                     exhausted["attempt_count"]),
                )
            row = connection.execute(
                """WITH claimable AS (
                   SELECT owner_id,dispatch_id FROM havre.web_push_dispatches
                     WHERE owner_id=%s
                       AND status IN ('pending','retry_wait')
                       AND next_attempt_at<=clock_timestamp()
                       AND attempt_count<max_attempts
                       AND delivery_eligible_until>clock_timestamp()
                     ORDER BY next_attempt_at,created_at
                     FOR UPDATE SKIP LOCKED LIMIT 1
                   )
                   UPDATE havre.web_push_dispatches dispatch
                   SET status='leased',lease_owner=%s,
                       lease_expires_at=clock_timestamp()+make_interval(secs => %s),
                       attempt_count=attempt_count+1
                   FROM claimable
                   WHERE dispatch.owner_id=claimable.owner_id
                     AND dispatch.dispatch_id=claimable.dispatch_id
                   RETURNING dispatch.*""",
                (self.owner_id, self.worker_id, self.lease_seconds),
            ).fetchone()
            if row is None:
                return None
            return dict(row)

    @staticmethod
    def _failure(error: Exception) -> tuple[str, bool, str | None]:
        response = getattr(error, "response", None)
        status_code = getattr(response, "status_code", None)
        if status_code in {404, 410}:
            return "endpoint_gone", False, "expired"
        if status_code in {401, 403}:
            return "vapid_rejected", False, None
        return type(error).__name__[:120], True, None

    def _complete_locked(
        self, *, connection: Any, row: dict[str, Any], status: str,
        failure_code: str | None, receipt: str | None, retryable: bool,
        payload: dict[str, Any],
    ) -> None:
        now = datetime.now(UTC)
        locked = connection.execute(
            """SELECT attempt_count,max_attempts FROM havre.web_push_dispatches
               WHERE owner_id=%s AND dispatch_id=%s AND status='leased'
                 AND lease_owner=%s AND attempt_count=%s
                 AND lease_expires_at>clock_timestamp() FOR UPDATE""",
            (self.owner_id,row["dispatch_id"],self.worker_id,row["attempt_count"]),
        ).fetchone()
        if locked is None:
            raise RuntimeError("web push worker lost its exact active dispatch lease")
        attempt_status = "delivered" if status == "accepted" else "failed"
        connection.execute(
            """INSERT INTO havre.web_push_delivery_attempts
               (owner_id,web_push_attempt_id,subscription_id,assistant_event_id,
                proactive_delivery_attempt_id,idempotency_key,attempt_number,status,
                retryable,preview_level,payload,payload_hash,provider_receipt_id,
                failure_code,attempted_at,dispatch_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'private',%s,%s,%s,%s,%s,%s)""",
            (self.owner_id, uuid7(), row["subscription_id"],
             row["assistant_event_id"], row["proactive_delivery_attempt_id"],
             f"web-push:{row['dispatch_id']}", row["attempt_count"],
             attempt_status, retryable, Jsonb(payload), content_hash(payload),
             receipt, failure_code, now, row["dispatch_id"]),
        )
        terminal = status in {"accepted","blocked","revoked","expired","dead"}
        next_status, next_at = status, now
        if status == "retry_wait":
            if locked["attempt_count"] >= locked["max_attempts"]:
                next_status, terminal = "dead", True
            else:
                next_at = now + timedelta(
                    seconds=min(300, 2 ** locked["attempt_count"] * self.retry_base_seconds)
                )
        changed = connection.execute(
            """UPDATE havre.web_push_dispatches
               SET status=%s,lease_owner=NULL,lease_expires_at=NULL,
                   next_attempt_at=%s,last_error_code=%s,
                   completed_at=CASE WHEN %s THEN %s ELSE NULL END
               WHERE owner_id=%s AND dispatch_id=%s AND status='leased'
                 AND lease_owner=%s AND attempt_count=%s
                 AND lease_expires_at>clock_timestamp()""",
            (next_status,next_at,failure_code,terminal,now,self.owner_id,
             row["dispatch_id"],self.worker_id,row["attempt_count"]),
        ).rowcount
        if changed != 1:
            raise RuntimeError("web push dispatch completion lost its exact lease")
        if status == "accepted":
            connection.execute(
                """UPDATE havre.web_push_subscriptions
                   SET last_success_at=clock_timestamp(),updated_at=clock_timestamp()
                   WHERE owner_id=%s AND subscription_id=%s""",
                (self.owner_id,row["subscription_id"]),
            )
        else:
            connection.execute(
                """UPDATE havre.web_push_subscriptions
                   SET last_failure_at=clock_timestamp(),updated_at=clock_timestamp(),
                        status=CASE WHEN %s='expired' THEN 'expired' ELSE status END
                   WHERE owner_id=%s AND subscription_id=%s""",
                (status,self.owner_id,row["subscription_id"]),
            )

    def _fresh_claim(self, connection: Any, row: dict[str, Any]) -> dict[str, Any]:
        current = connection.execute(
            """SELECT dispatch.*,subscription.endpoint,subscription.p256dh,
                      subscription.auth_secret,
                      subscription.status AS subscription_status,
                      subscription.expires_at,device.revoked_at,
                      device.session_expires_at,event.privacy_class,
                      COALESCE((preference.payload->>'generic_push_for_local_only')::boolean,false) AS generic_push_for_local_only
               FROM havre.web_push_dispatches dispatch
               JOIN havre.proactive_delivery_attempts proactive_attempt
                 ON proactive_attempt.owner_id=dispatch.owner_id
                AND proactive_attempt.delivery_attempt_id=dispatch.proactive_delivery_attempt_id
               JOIN havre.interruption_decisions decision
                 ON decision.owner_id=proactive_attempt.owner_id
                AND decision.interruption_decision_id=proactive_attempt.interruption_decision_id
               JOIN havre.proactive_preference_revisions preference
                 ON preference.owner_id=decision.owner_id
                AND preference.preference_revision_id=decision.preference_revision_id
               JOIN havre.web_push_subscriptions subscription
                 ON subscription.owner_id=dispatch.owner_id
                AND subscription.subscription_id=dispatch.subscription_id
               JOIN havre.companion_devices device
                 ON device.owner_id=subscription.owner_id
                AND device.device_id=subscription.device_id
               JOIN havre.events event ON event.owner_id=dispatch.owner_id
                AND event.event_id=dispatch.assistant_event_id
               WHERE dispatch.owner_id=%s AND dispatch.dispatch_id=%s
                 AND dispatch.status='leased' AND dispatch.lease_owner=%s
                 AND dispatch.attempt_count=%s
                 AND dispatch.lease_expires_at>clock_timestamp()
               FOR UPDATE OF dispatch,subscription,device,event""",
            (self.owner_id,row["dispatch_id"],self.worker_id,row["attempt_count"]),
        ).fetchone()
        if current is None:
            raise RuntimeError("web push worker lost its exact active dispatch lease")
        return dict(current)

    def _deliver_claimed(self, row: dict[str, Any], payload: dict[str, Any]) -> str:
        with self.repository.pool.connection() as connection, connection.transaction():
            acquire_web_push_owner_lock(connection, self.owner_id)
            current = self._fresh_claim(connection, row)
            now = datetime.now(UTC)
            invalid_status = None
            invalid_failure_code = None
            if current["subscription_status"] == "revoked" or current["revoked_at"] is not None:
                invalid_status = "revoked"
            elif current["subscription_status"] == "expired" or (
                current["expires_at"] is not None and current["expires_at"] <= now
            ) or current["session_expires_at"] <= now:
                invalid_status = "expired"
            elif current["delivery_eligible_until"] <= now:
                invalid_status = "blocked"
                invalid_failure_code = "delivery_window_expired"
            elif current["privacy_class"] == "LOCAL_ONLY" and not current[
                "generic_push_for_local_only"
            ]:
                invalid_status = "blocked"
            elif current["privacy_class"] not in {
                "PUBLIC","NORMAL","PRIVATE","HIGHLY_PRIVATE","LOCAL_ONLY"
            }:
                invalid_status = "blocked"
            try:
                current["endpoint"] = validate_web_push_endpoint(str(current["endpoint"]))
            except ValueError:
                invalid_status = "blocked"
            if invalid_status is not None:
                self._complete_locked(
                    connection=connection,row=current,status=invalid_status,
                    failure_code=(invalid_failure_code or f"pre_send_{invalid_status}"),
                    receipt=None,
                    retryable=False,payload=payload,
                )
                return "skipped"
            try:
                receipt = self.sender(current, json.dumps(payload, ensure_ascii=False))
            except Exception as error:
                failure_code,retryable,terminal_status = self._failure(error)
                self._complete_locked(
                    connection=connection,row=current,
                    status=terminal_status or ("retry_wait" if retryable else "dead"),
                    failure_code=failure_code,receipt=None,retryable=retryable,
                    payload=payload,
                )
                return "failed"
            self._complete_locked(
                connection=connection,row=current,status="accepted",failure_code=None,
                receipt=receipt,retryable=False,payload=payload,
            )
            return "delivered"

    def deliver_pending(self, *, limit: int = 50) -> dict[str, Any]:
        if not self.available:
            return {"status":"disabled","queued":0,"delivered":0,"failed":0,"skipped":0}
        queued = self.enqueue_eligible(limit=max(limit,1)*4)
        result = {"status":"completed","queued":queued,"delivered":0,"failed":0,"skipped":0}
        for _ in range(max(1,min(limit,200))):
            row = self._claim()
            if row is None:
                break
            locator = str(row["delivery_locator"])
            payload = {
                "title":"HAVRE","body":"HAVRE 有条消息给你",
                "delivery_locator":locator,"url":f"/chat#delivery-{locator}",
            }
            try:
                outcome = self._deliver_claimed(row, payload)
            except RuntimeError:
                result["failed"] += 1
                continue
            result[outcome] += 1
        return result

    def resolve_navigation(self, *, delivery_locator: UUID, device_id: UUID | None) -> UUID:
        with self.repository.pool.connection() as connection:
            row = connection.execute(
                """SELECT dispatch.assistant_event_id,subscription.device_id
                   FROM havre.web_push_dispatches dispatch
                   JOIN havre.web_push_subscriptions subscription
                     ON subscription.owner_id=dispatch.owner_id
                    AND subscription.subscription_id=dispatch.subscription_id
                   WHERE dispatch.owner_id=%s AND dispatch.delivery_locator=%s""",
                (self.owner_id, delivery_locator),
            ).fetchone()
        if row is None or (device_id is not None and row["device_id"] != device_id):
            raise LookupError("notification target not found")
        return row["assistant_event_id"]
