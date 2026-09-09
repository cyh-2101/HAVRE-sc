"""Product projections over canonical HAVRE Events.

This module does not create a second chat or Memory store. The timeline is a
keyset-paginated view of ``havre.events`` and diary rows are replaceable,
provenance-bound summaries whose sources remain exact Event revisions.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import hashlib
import re
import secrets
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from psycopg.types.json import Jsonb

from companion.hashing import content_hash
from companion.ids import uuid7
from companion.persistence.postgres import PostgresRepository


def acquire_web_push_owner_lock(connection: Any, owner_id: UUID) -> None:
    """Serialize outbound send authorization with revoke and erasure."""
    connection.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (f"web-push-owner:{owner_id}",),
    )


def validate_web_push_endpoint(endpoint: str) -> str:
    """Admit only Apple's exact iPhone Web Push origin for this milestone."""
    if any(character.isspace() for character in endpoint):
        raise ValueError("Web Push endpoint contains whitespace")
    try:
        parsed = urlsplit(endpoint)
        port = parsed.port
    except ValueError as error:
        raise ValueError("Web Push endpoint is malformed") from error
    if (
        parsed.scheme.lower() != "https"
        or parsed.hostname is None
        or parsed.hostname.lower() != "web.push.apple.com"
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or not parsed.path.startswith("/")
        or len(parsed.path) < 2
        or parsed.fragment
    ):
        raise ValueError("Web Push endpoint is outside the authorized Apple Push origin")
    return urlunsplit(("https", "web.push.apple.com", parsed.path, parsed.query, ""))


class DailyCompanionStore:
    diary_summary_method = "curated-owner-day-diary-v3"

    def __init__(self, *, repository: PostgresRepository, owner_id: UUID) -> None:
        self.repository = repository
        self.owner_id = owner_id

    @staticmethod
    def _token_hash(token: str) -> str:
        digest = hashlib.sha256(f"havre-device-session-v1:{token}".encode()).hexdigest()
        return f"sha256:{digest}"

    @staticmethod
    def _pairing_hash(owner_id: UUID, pairing_id: UUID, code: str) -> str:
        material = f"havre-pairing-v1:{owner_id}:{pairing_id}:{code}".encode()
        return f"sha256:{hashlib.sha256(material).hexdigest()}"

    @staticmethod
    def _payload_text(payload: dict[str, Any] | None) -> str:
        if not payload:
            return ""
        parts = payload.get("content_parts", ())
        if isinstance(parts, list):
            return "\n".join(
                str(part.get("text", ""))
                for part in parts
                if isinstance(part, dict) and part.get("type", "text") == "text"
            ).strip()
        return ""

    def create_pairing(self, *, ttl_seconds: int = 600) -> dict[str, Any]:
        pairing_id = uuid7()
        code = f"{secrets.randbelow(100_000_000):08d}"
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=max(60, min(ttl_seconds, 1800)))
        with self.repository.pool.connection() as connection, connection.transaction():
            connection.execute(
                """INSERT INTO havre.device_pairing_challenges
                   (owner_id,pairing_id,code_hash,expires_at,created_at)
                   VALUES (%s,%s,%s,%s,%s)""",
                (
                    self.owner_id,
                    pairing_id,
                    self._pairing_hash(self.owner_id, pairing_id, code),
                    expires_at,
                    now,
                ),
            )
        return {"pairing_id": pairing_id, "code": code, "expires_at": expires_at}

    def claim_pairing(
        self,
        *,
        pairing_id: UUID,
        code: str,
        display_name: str,
        device_kind: str,
        session_days: int = 180,
    ) -> dict[str, Any]:
        if not re.fullmatch(r"\d{8}", code):
            raise ValueError("pairing code is invalid")
        display_name = display_name.strip()
        if not 1 <= len(display_name) <= 120:
            raise ValueError("device name is invalid")
        if device_kind not in {"windows", "iphone", "browser", "other"}:
            raise ValueError("device kind is invalid")
        token = secrets.token_urlsafe(48)
        device_id = uuid7()
        now = datetime.now(UTC)
        expires_at = now + timedelta(days=max(1, min(session_days, 365)))
        expected = self._pairing_hash(self.owner_id, pairing_id, code)
        invalid_code = False
        with self.repository.pool.connection() as connection, connection.transaction():
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (f"device-pairing:{self.owner_id}:{pairing_id}",),
            )
            row = connection.execute(
                """SELECT * FROM havre.device_pairing_challenges
                   WHERE owner_id=%s AND pairing_id=%s FOR UPDATE""",
                (self.owner_id, pairing_id),
            ).fetchone()
            if (
                row is None
                or row["consumed_at"] is not None
                or row["expires_at"] <= now
                or row["failed_attempts"] >= 5
            ):
                raise ValueError("pairing code is invalid or expired")
            if not secrets.compare_digest(row["code_hash"], expected):
                connection.execute(
                    """UPDATE havre.device_pairing_challenges
                       SET failed_attempts=failed_attempts+1,
                           last_failed_at=GREATEST(
                             clock_timestamp(),
                             COALESCE(last_failed_at,clock_timestamp()) + interval '1 microsecond'
                           )
                       WHERE owner_id=%s AND pairing_id=%s""",
                    (self.owner_id, pairing_id),
                )
                invalid_code = True
            else:
                connection.execute(
                """INSERT INTO havre.companion_devices
                   (owner_id,device_id,display_name,device_kind,session_token_hash,
                    session_expires_at,last_seen_at,created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    self.owner_id,
                    device_id,
                    display_name,
                    device_kind,
                    self._token_hash(token),
                    expires_at,
                    now,
                    now,
                ),
            )
                connection.execute(
                """UPDATE havre.device_pairing_challenges
                   SET consumed_at=%s,consumed_device_id=%s
                   WHERE owner_id=%s AND pairing_id=%s""",
                    (now, device_id, self.owner_id, pairing_id),
                )
        if invalid_code:
            raise ValueError("pairing code is invalid or expired")
        return {
            "device_id": device_id,
            "device_token": token,
            "session_expires_at": expires_at,
        }

    def authenticate_device(self, token: str) -> UUID | None:
        token_hash = self._token_hash(token)
        now = datetime.now(UTC)
        with self.repository.pool.connection() as connection, connection.transaction():
            row = connection.execute(
                """SELECT device_id FROM havre.companion_devices
                   WHERE owner_id=%s AND session_token_hash=%s
                     AND revoked_at IS NULL AND session_expires_at>%s""",
                (self.owner_id, token_hash, now),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                """UPDATE havre.companion_devices SET last_seen_at=%s
                   WHERE owner_id=%s AND device_id=%s""",
                (now, self.owner_id, row["device_id"]),
            )
            return row["device_id"]

    def list_devices(self) -> tuple[dict[str, Any], ...]:
        with self.repository.pool.connection() as connection:
            rows = connection.execute(
                """SELECT device_id,display_name,device_kind,session_expires_at,
                          last_seen_at,revoked_at,created_at
                   FROM havre.companion_devices WHERE owner_id=%s
                   ORDER BY created_at DESC""",
                (self.owner_id,),
            ).fetchall()
        return tuple(dict(row) for row in rows)

    def revoke_device(self, *, device_id: UUID) -> None:
        with self.repository.pool.connection() as connection, connection.transaction():
            acquire_web_push_owner_lock(connection, self.owner_id)
            changed = connection.execute(
                """UPDATE havre.companion_devices SET revoked_at=clock_timestamp()
                   WHERE owner_id=%s AND device_id=%s AND revoked_at IS NULL""",
                (self.owner_id, device_id),
            ).rowcount
            if changed == 0:
                raise LookupError("active device not found")
            connection.execute(
                """UPDATE havre.web_push_subscriptions
                   SET status='revoked',revoked_at=clock_timestamp(),
                       updated_at=clock_timestamp()
                   WHERE owner_id=%s AND device_id=%s AND status='active'""",
                (self.owner_id, device_id),
            )

    def save_subscription(
        self,
        *,
        device_id: UUID,
        endpoint: str,
        p256dh: str,
        auth_secret: str,
        preview_level: str,
        vapid_key_version: str,
        expires_at: datetime | None = None,
    ) -> dict[str, Any]:
        if preview_level not in {"private", "detailed"}:
            raise ValueError("preview level is invalid")
        endpoint = validate_web_push_endpoint(endpoint)
        endpoint_hash = f"sha256:{hashlib.sha256(endpoint.encode()).hexdigest()}"
        subscription_id = uuid7()
        with self.repository.pool.connection() as connection, connection.transaction():
            acquire_web_push_owner_lock(connection, self.owner_id)
            now = datetime.now(UTC)
            device = connection.execute(
                """SELECT 1 FROM havre.companion_devices
                   WHERE owner_id=%s AND device_id=%s AND revoked_at IS NULL
                     AND session_expires_at>%s""",
                (self.owner_id, device_id, now),
            ).fetchone()
            if device is None:
                raise ValueError("active device session is required")
            connection.execute(
                """INSERT INTO havre.web_push_subscriptions
                   (owner_id,subscription_id,device_id,endpoint,endpoint_hash,p256dh,
                    auth_secret,preview_level,status,expires_at,created_at,updated_at,
                    vapid_key_version,delivery_eligible_from)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'active',%s,%s,%s,%s,%s)
                   ON CONFLICT (owner_id,endpoint_hash) DO NOTHING
                   RETURNING subscription_id""",
                (
                    self.owner_id,
                    subscription_id,
                    device_id,
                    endpoint,
                    endpoint_hash,
                    p256dh,
                    auth_secret,
                    preview_level,
                    expires_at,
                    now,
                    now,
                    vapid_key_version,
                    now,
                ),
            )
            row = connection.execute(
                """SELECT subscription_id,device_id,endpoint,p256dh,auth_secret,
                          preview_level,status,expires_at,created_at,updated_at,
                          vapid_key_version,delivery_eligible_from
                   FROM havre.web_push_subscriptions
                   WHERE owner_id=%s AND endpoint_hash=%s""",
                (self.owner_id, endpoint_hash),
            ).fetchone()
            if row is None or any((
                row["device_id"] != device_id,
                row["endpoint"] != endpoint,
                row["p256dh"] != p256dh,
                row["auth_secret"] != auth_secret,
                row["preview_level"] != preview_level,
                row["status"] != "active",
                row["expires_at"] != expires_at,
                row["vapid_key_version"] != vapid_key_version,
            )):
                raise ValueError(
                    "existing Web Push endpoint binding is immutable; register a fresh endpoint"
                )
        return dict(row)

    def revoke_subscription(self, *, device_id: UUID, subscription_id: UUID) -> None:
        with self.repository.pool.connection() as connection, connection.transaction():
            acquire_web_push_owner_lock(connection, self.owner_id)
            changed = connection.execute(
                """UPDATE havre.web_push_subscriptions
                   SET status='revoked',revoked_at=clock_timestamp(),
                       updated_at=clock_timestamp()
                   WHERE owner_id=%s AND device_id=%s AND subscription_id=%s
                      AND status='active'""",
                (self.owner_id, device_id, subscription_id),
            ).rowcount
            if changed == 0:
                raise LookupError("active push subscription not found")

    def timeline(
        self,
        *,
        limit: int = 60,
        before_at: datetime | None = None,
        before_event_id: UUID | None = None,
        through_event_id: UUID | None = None,
    ) -> dict[str, Any]:
        limit = max(1, min(limit, 100))
        if (before_at is None) != (before_event_id is None):
            raise ValueError("timeline cursor is incomplete")
        cursor_sql = ""
        parameters: list[Any] = [self.owner_id]
        if before_at is not None:
            cursor_sql = "AND (event.recorded_at,event.event_id)<(%s,%s)"
            parameters.extend((before_at, before_event_id))
        parameters.append(limit + 1)
        with self.repository.pool.connection() as connection:
            if through_event_id is not None:
                if before_at is not None:
                    raise ValueError("choose a history cursor or a message, not both")
                target = connection.execute(
                    "SELECT recorded_at FROM havre.events WHERE owner_id=%s AND event_id=%s "
                    "AND event_type IN ('USER_MESSAGE','ASSISTANT_MESSAGE')",
                    (self.owner_id, through_event_id),
                ).fetchone()
                if target is None:
                    raise ValueError("message is no longer available")
                cursor_sql = "AND (event.recorded_at,event.event_id)<=(%s,%s)"
                parameters = [self.owner_id, target["recorded_at"], through_event_id, limit + 1]
            rows = connection.execute(
                f"""SELECT event.event_id,event.session_id,event.request_id,event.trace_id,
                           event.event_type,event.payload,event.recorded_at,
                           event.privacy_class,event.memory_eligible,event.cloud_eligible,
                           request.status AS interaction_status,
                           request.error_code AS interaction_error_code,
                           COALESCE(
                             inference.provider_id,route.selected_provider_id
                           ) AS provider_id,
                           COALESCE(
                             inference.model_version_id,
                             route.selected_model_version_id
                           ) AS model_version_id,
                           inference.adapter_version_id,
                           route.execution_environment,
                           feedback.feedback_id,feedback.current_revision,
                           revision.rating,revision.reason_codes,revision.reason_text,
                           revision.owner_revision_text,
                           (inbox.assistant_event_id IS NOT NULL) AS proactive
                    FROM havre.events event
                    LEFT JOIN havre.interaction_requests request
                      ON request.owner_id=event.owner_id
                     AND request.request_id=event.request_id
                    LEFT JOIN havre.inference_attempts inference
                      ON inference.owner_id=request.owner_id
                     AND inference.inference_attempt_id=request.inference_attempt_id
                     AND (
                       (event.event_type='ASSISTANT_MESSAGE'
                        AND request.status='completed'
                        AND inference.status='completed')
                       OR
                       (event.event_type='USER_MESSAGE'
                        AND request.status='failed'
                        AND inference.status='failed')
                     )
                    LEFT JOIN LATERAL (
                      SELECT candidate.selected_provider_id,
                             candidate.selected_model_version_id,
                             candidate.execution_environment
                      FROM havre.route_decisions candidate
                      WHERE candidate.owner_id=request.owner_id
                        AND candidate.request_id=request.request_id
                        AND candidate.trace_id=request.trace_id
                        AND (
                          inference.route_decision_id IS NULL
                          OR candidate.route_decision_id=inference.route_decision_id
                        )
                      ORDER BY
                        (candidate.route_decision_id=inference.route_decision_id) DESC,
                        candidate.created_at DESC,
                        candidate.route_decision_id DESC
                      LIMIT 1
                    ) route ON (
                      (event.event_type='ASSISTANT_MESSAGE'
                       AND request.status='completed')
                      OR
                      (event.event_type='USER_MESSAGE'
                       AND request.status='failed')
                    )
                    LEFT JOIN havre.response_feedback_heads feedback
                      ON feedback.owner_id=event.owner_id
                     AND feedback.assistant_event_id=event.event_id
                    LEFT JOIN havre.response_feedback_revisions revision
                      ON revision.owner_id=feedback.owner_id
                     AND revision.feedback_id=feedback.feedback_id
                     AND revision.revision=feedback.current_revision
                    LEFT JOIN havre.proactive_inbox_messages inbox
                      ON inbox.owner_id=event.owner_id
                     AND inbox.assistant_event_id=event.event_id
                    WHERE event.owner_id=%s
                      AND event.event_type IN ('USER_MESSAGE','ASSISTANT_MESSAGE')
                      AND COALESCE(request.idempotency_key,'') NOT LIKE 'course-source-%%'
                      AND (
                        event.event_type='USER_MESSAGE'
                        OR (
                          request.request_kind='interaction'
                          AND request.status='completed'
                          AND request.assistant_event_id=event.event_id
                        )
                        OR request.request_kind<>'interaction'
                      )
                      {cursor_sql}
                    ORDER BY event.recorded_at DESC,event.event_id DESC LIMIT %s""",
                parameters,
            ).fetchall()
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = []
        for row in reversed(rows):
            items.append(
                {
                    "event_id": row["event_id"],
                    "session_id": row["session_id"],
                    "request_id": row["request_id"],
                    "trace_id": row["trace_id"],
                    "role": "user" if row["event_type"] == "USER_MESSAGE" else "assistant",
                    "content": self._payload_text(row["payload"]),
                    # Read-only projection: absent/legacy decisions never opt into pacing.
                    "response_policy_category": (
                        (row["payload"].get("response_policy_decision") or {}).get("category")
                        if isinstance(row["payload"], dict) else None
                    ),
                    "reply_to_event_id": row["payload"].get("reply_to_event_id") if isinstance(row["payload"],dict) else None,
                    "input_origin": row["payload"].get("input_origin", "owner_text"),
                    "client_created_at": (
                        row["payload"].get("client_created_at")
                        if isinstance(row["payload"], dict)
                        else None
                    ),
                    "recorded_at": row["recorded_at"],
                    "privacy_class": row["privacy_class"],
                    "effective_privacy_class": row["privacy_class"],
                    "memory_eligible": row["memory_eligible"],
                    "cloud_eligible": row["cloud_eligible"],
                    "interaction_status": row["interaction_status"],
                    "interaction_error_code": row["interaction_error_code"],
                    "provider_id": row["provider_id"],
                    "model_version_id": row["model_version_id"],
                    "adapter_version_id": row["adapter_version_id"],
                    "execution_environment": row["execution_environment"],
                    "proactive": row["proactive"],
                    "feedback": None
                    if row["feedback_id"] is None
                    else {
                        "feedback_id": row["feedback_id"],
                        "revision": row["current_revision"],
                        "rating": row["rating"],
                        "reason_codes": row["reason_codes"],
                        "reason_text": row["reason_text"],
                        "owner_revision_text": row["owner_revision_text"],
                    },
                }
            )
        next_cursor = None
        if has_more and items:
            next_cursor = {
                "before_at": items[0]["recorded_at"],
                "before_event_id": items[0]["event_id"],
            }
        return {"items": tuple(items), "has_more": has_more, "next_cursor": next_cursor}

    def mark_read(self, *, device_id: UUID, event_id: UUID) -> dict[str, Any]:
        now = datetime.now(UTC)
        with self.repository.pool.connection() as connection, connection.transaction():
            event = connection.execute(
                "SELECT recorded_at FROM havre.events WHERE owner_id=%s AND event_id=%s",
                (self.owner_id, event_id),
            ).fetchone()
            device = connection.execute(
                """SELECT 1 FROM havre.companion_devices
                   WHERE owner_id=%s AND device_id=%s AND revoked_at IS NULL""",
                (self.owner_id, device_id),
            ).fetchone()
            if event is None or device is None:
                raise LookupError("device or event not found")
            connection.execute(
                """INSERT INTO havre.device_read_cursors
                   (owner_id,device_id,last_read_event_id,last_read_at,updated_at)
                   VALUES (%s,%s,%s,%s,%s)
                   ON CONFLICT (owner_id,device_id) DO UPDATE SET
                     last_read_event_id=CASE WHEN
                       (SELECT recorded_at FROM havre.events WHERE owner_id=EXCLUDED.owner_id
                        AND event_id=EXCLUDED.last_read_event_id) >=
                       (SELECT recorded_at FROM havre.events WHERE owner_id=havre.device_read_cursors.owner_id
                        AND event_id=havre.device_read_cursors.last_read_event_id)
                       THEN EXCLUDED.last_read_event_id ELSE havre.device_read_cursors.last_read_event_id END,
                     last_read_at=GREATEST(havre.device_read_cursors.last_read_at,EXCLUDED.last_read_at),
                     updated_at=EXCLUDED.updated_at""",
                (self.owner_id, device_id, event_id, now, now),
            )
        return {"device_id": device_id, "last_read_event_id": event_id, "last_read_at": now}

    @staticmethod
    def _clean_title(text: str) -> str:
        compact = re.sub(r"\s+", " ", text).strip(" \t\r\n。.!！?？,，;；:\"'“”")
        if not compact:
            return "今天的小片段"
        headline = re.split(r"[，,；;。.!！？?：:]", compact, maxsplit=1)[0].strip()
        if len(headline) < 4:
            headline = compact
        return headline[:18] + ("…" if len(headline) > 18 else "")

    @staticmethod
    def _diary_excluded(value: str) -> bool:
        compact = re.sub(r"\s+", " ", value).strip()
        return bool(re.search(
            r"product\s+owner|owner[- ]local|sha256:|\badr-?\d+|\bstage\s*\d+|"
            r"source[- ]erasure|policy[_ -]?version|migration|provenance|"
            r"我(?:确认)?批准|我确认授权|明确授权|授权扩展|批准启动|"
            r"五字段投影|提醒队列|课程.{0,12}(?:goal|投影|队列|导入|转换)",
            compact,
            re.I,
        ))

    @staticmethod
    def _event_phrase(value: str) -> str | None:
        compact = re.sub(r"\s+", " ", value).strip()
        if not compact or DailyCompanionStore._diary_excluded(compact):
            return None
        plain = re.sub(r"[\s。.!！?？,，;；:：'\"“”‘’]", "", compact).casefold()
        low_information = {
            "你好", "你好呀", "你好啊", "嗨", "哈喽", "hello", "hi", "在吗",
            "好", "好的", "好呀", "好呀好呀", "行", "可以", "嗯", "嗯嗯", "哦",
            "哦哦", "知道了", "收到", "谢谢", "晚安", "早安", "睡了", "哈哈",
        }
        if plain in low_information:
            return None
        if re.fullmatch(r"(?:好|嗯|哦|哈|呀|啊|行|可以|收到|谢谢)+", plain):
            return None
        if compact in {"用 Strong Brain 重新想想上一条回复。", "用 Strong Brain 重新想想"}:
            return None
        action_markers = (
            "完成", "开始", "决定", "发现", "解决", "通过", "失败", "准备",
            "去了", "要去", "约了", "见了", "做了", "改了", "跑通", "授权",
            "提交", "交了", "买了", "到了", "起床", "睡觉", "吃了", "聊了",
            "看了", "玩了", "散步", "运动", "聚会",
        )
        if ("?" in compact or "？" in compact) and not any(
            marker in compact for marker in action_markers
        ):
            return None
        if any(marker in compact for marker in ("我感觉", "我觉得", "有点")) and not any(
            marker in compact for marker in action_markers
        ):
            return None
        if not any(marker in compact for marker in action_markers) and not re.search(
            r"\d|\b(?:今天|明天|昨天|上午|下午|晚上)\b", compact
        ):
            return None
        phrase = re.sub(r"^(?:然后|那个|就是|对了)[，,：:\s]*", "", compact)
        phrase = re.sub(r"^我(?:今天|刚刚|刚|现在)?", "", phrase).strip()
        phrase = phrase.strip(" \t\r\n。.!！?？,，;；:：'\"“”‘’")
        if not phrase:
            return None
        return phrase[:180]

    @staticmethod
    def _event_score(value: str) -> int:
        score = min(len(value), 120)
        score += 35 * sum(
            marker in value
            for marker in (
                "完成", "开始", "决定", "发现", "解决", "通过", "失败", "准备",
                "去了", "要去", "约了", "见了", "做了", "改了", "跑通", "授权",
                "吃了", "聊了", "看了", "玩了", "散步", "运动", "聚会",
            )
        )
        return score

    @staticmethod
    def _curated_summary(
        messages: list[dict[str, Any]],
    ) -> tuple[str, str, str, list[dict[str, Any]]] | None:
        candidates: list[tuple[int, str, dict[str, Any]]] = []
        seen: set[str] = set()
        for ordinal, item in enumerate(messages):
            if item["role"] != "user" or not item["content"]:
                continue
            phrase = DailyCompanionStore._event_phrase(item["content"])
            if phrase is None or phrase in seen:
                continue
            seen.add(phrase)
            candidates.append((ordinal, phrase, item))
        if not candidates:
            return None
        ranked = sorted(
            candidates,
            key=lambda item: -DailyCompanionStore._event_score(item[1]),
        )
        title = DailyCompanionStore._clean_title(ranked[0][1])
        selected = sorted(ranked[:3], key=lambda item: item[0])
        phrases: list[str] = []
        selected_messages: list[dict[str, Any]] = []
        for _, value, source in selected:
            candidate = value.rstrip("。")
            next_summary = "；".join([*phrases, candidate]) + "。"
            if phrases and len(next_summary) > 220:
                continue
            phrases.append(candidate)
            selected_messages.append(source)
        summary = "；".join(phrases).rstrip("。") + "。"
        preview = summary[:120].rstrip("；，, ") + ("…" if len(summary) > 120 else "")
        return title, summary, preview, selected_messages

    @staticmethod
    def _summary(messages: list[dict[str, Any]]) -> tuple[str, str, str] | None:
        curated = DailyCompanionStore._curated_summary(messages)
        return None if curated is None else curated[:3]

    def _day_events(self, *, local_date: date, timezone_name: str) -> list[dict[str, Any]]:
        with self.repository.pool.connection() as connection:
            rows = connection.execute(
                """SELECT event_id,event_type,payload,content_hash,recorded_at
                   FROM havre.events
                   WHERE owner_id=%s
                     AND event_type IN ('USER_MESSAGE','ASSISTANT_MESSAGE')
                     AND COALESCE(payload->>'input_origin','owner_text') <> 'continuation_button'
                     AND (recorded_at AT TIME ZONE %s)::date=%s
                   ORDER BY recorded_at,event_id""",
                (self.owner_id, timezone_name, local_date),
            ).fetchall()
        return [
            {
                "event_id": row["event_id"],
                "role": "user" if row["event_type"] == "USER_MESSAGE" else "assistant",
                "content": self._payload_text(row["payload"]),
                "content_hash": row["content_hash"],
                "recorded_at": row["recorded_at"],
            }
            for row in rows
        ]

    def sync_diary_day(self, *, local_date: date, timezone_name: str) -> dict[str, Any] | None:
        messages = self._day_events(local_date=local_date, timezone_name=timezone_name)
        curated = self._curated_summary(messages)
        now = datetime.now(UTC)
        with self.repository.pool.connection() as connection, connection.transaction():
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (f"diary:{self.owner_id}:{local_date}:{timezone_name}",),
            )
            head = connection.execute(
                """SELECT * FROM havre.daily_diary_entry_heads
                   WHERE owner_id=%s AND local_date=%s AND timezone_name=%s FOR UPDATE""",
                (self.owner_id, local_date, timezone_name),
            ).fetchone()
            has_conversation = (
                any(item["role"] == "user" for item in messages)
                and any(item["role"] == "assistant" for item in messages)
            )
            if not messages or not has_conversation or curated is None:
                if head is not None and head["status"] != "invalidated":
                    connection.execute(
                        """UPDATE havre.daily_diary_entry_heads
                           SET status='invalidated',invalidated_at=%s,updated_at=%s
                           WHERE owner_id=%s AND local_date=%s AND timezone_name=%s""",
                        (now, now, self.owner_id, local_date, timezone_name),
                    )
                return None
            title, summary, preview, source_messages = curated
            source_set_hash = content_hash(
                [
                    {"event_id": str(item["event_id"]), "content_hash": item["content_hash"]}
                    for item in source_messages
                ]
            )
            if head is not None:
                current = connection.execute(
                    """SELECT * FROM havre.daily_diary_entry_revisions
                       WHERE owner_id=%s AND local_date=%s AND timezone_name=%s
                         AND revision=%s""",
                    (self.owner_id, local_date, timezone_name, head["current_revision"]),
                ).fetchone()
                if (
                    current is not None
                    and current["source_set_hash"] == source_set_hash
                    and current["summary_method"] == self.diary_summary_method
                ):
                    return self.diary_day(
                        local_date=local_date, timezone_name=timezone_name
                    )
                revision = head["current_revision"] + 1
            else:
                revision = 1
                connection.execute(
                    """INSERT INTO havre.daily_diary_entry_heads
                       (owner_id,local_date,timezone_name,current_revision,status,created_at,updated_at)
                       VALUES (%s,%s,%s,1,'current',%s,%s)""",
                    (self.owner_id, local_date, timezone_name, now, now),
                )
            revision_hash = content_hash(
                {
                    "local_date": local_date.isoformat(),
                    "timezone_name": timezone_name,
                    "revision": revision,
                    "title": title,
                    "summary_text": summary,
                    "preview_text": preview,
                    "summary_method": self.diary_summary_method,
                    "source_set_hash": source_set_hash,
                }
            )
            connection.execute(
                """INSERT INTO havre.daily_diary_entry_revisions
                   (owner_id,local_date,timezone_name,revision,title,summary_text,
                    preview_text,summary_method,source_set_hash,content_hash,created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    self.owner_id,
                    local_date,
                    timezone_name,
                    revision,
                    title,
                    summary,
                    preview,
                    self.diary_summary_method,
                    source_set_hash,
                    revision_hash,
                    now,
                ),
            )
            for ordinal, item in enumerate(source_messages):
                connection.execute(
                    """INSERT INTO havre.daily_diary_entry_sources
                       (owner_id,local_date,timezone_name,revision,ordinal,event_id,event_content_hash)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        self.owner_id,
                        local_date,
                        timezone_name,
                        revision,
                        ordinal,
                        item["event_id"],
                        item["content_hash"],
                    ),
                )
            finalized_at = None
            local_today = connection.execute(
                "SELECT (clock_timestamp() AT TIME ZONE %s)::date AS value",
                (timezone_name,),
            ).fetchone()["value"]
            if local_date < local_today:
                finalized_at = now
            connection.execute(
                """UPDATE havre.daily_diary_entry_heads
                   SET current_revision=%s,status='current',invalidated_at=NULL,
                       finalized_at=COALESCE(finalized_at,%s),updated_at=%s
                   WHERE owner_id=%s AND local_date=%s AND timezone_name=%s""",
                (
                    revision,
                    finalized_at,
                    now,
                    self.owner_id,
                    local_date,
                    timezone_name,
                ),
            )
        return self.diary_day(local_date=local_date, timezone_name=timezone_name)

    def list_diary(self, *, timezone_name: str, limit: int = 60) -> tuple[dict[str, Any], ...]:
        with self.repository.pool.connection() as connection:
            dates = connection.execute(
                """SELECT DISTINCT (recorded_at AT TIME ZONE %s)::date AS local_date
                   FROM havre.events WHERE owner_id=%s
                     AND event_type IN ('USER_MESSAGE','ASSISTANT_MESSAGE')
                   ORDER BY local_date DESC LIMIT %s""",
                (timezone_name, self.owner_id, max(1, min(limit, 180))),
            ).fetchall()
        for row in dates:
            self.sync_diary_day(local_date=row["local_date"], timezone_name=timezone_name)
        with self.repository.pool.connection() as connection:
            rows = connection.execute(
                """SELECT head.local_date,head.timezone_name,head.current_revision,
                          head.finalized_at,revision.title,revision.preview_text,
                          revision.summary_method,revision.created_at,
                          count(source.event_id) AS source_count
                   FROM havre.daily_diary_entry_heads head
                   JOIN havre.daily_diary_entry_revisions revision
                     ON revision.owner_id=head.owner_id AND revision.local_date=head.local_date
                    AND revision.timezone_name=head.timezone_name
                    AND revision.revision=head.current_revision
                   JOIN havre.daily_diary_entry_sources source
                     ON source.owner_id=revision.owner_id AND source.local_date=revision.local_date
                    AND source.timezone_name=revision.timezone_name
                    AND source.revision=revision.revision
                   WHERE head.owner_id=%s AND head.timezone_name=%s AND head.status='current'
                   GROUP BY head.local_date,head.timezone_name,head.current_revision,
                            head.finalized_at,revision.title,revision.preview_text,
                            revision.summary_method,revision.created_at
                   ORDER BY head.local_date DESC LIMIT %s""",
                (self.owner_id, timezone_name, max(1, min(limit, 180))),
            ).fetchall()
        return tuple(dict(row) for row in rows)

    def diary_day(self, *, local_date: date, timezone_name: str) -> dict[str, Any] | None:
        with self.repository.pool.connection() as connection:
            row = connection.execute(
                """SELECT head.local_date,head.timezone_name,head.current_revision,
                          head.finalized_at,revision.title,revision.summary_text,
                          revision.preview_text,revision.summary_method,revision.created_at
                   FROM havre.daily_diary_entry_heads head
                   JOIN havre.daily_diary_entry_revisions revision
                     ON revision.owner_id=head.owner_id AND revision.local_date=head.local_date
                    AND revision.timezone_name=head.timezone_name
                    AND revision.revision=head.current_revision
                   WHERE head.owner_id=%s AND head.local_date=%s
                     AND head.timezone_name=%s AND head.status='current'""",
                (self.owner_id, local_date, timezone_name),
            ).fetchone()
            if row is None:
                return None
            sources = connection.execute(
                """SELECT source.ordinal,source.event_id,source.event_content_hash,
                          event.recorded_at,event.event_type,event.payload
                   FROM havre.daily_diary_entry_sources source
                   JOIN havre.events event ON event.owner_id=source.owner_id
                    AND event.event_id=source.event_id
                   WHERE source.owner_id=%s AND source.local_date=%s
                     AND source.timezone_name=%s AND source.revision=%s
                   ORDER BY source.ordinal""",
                (self.owner_id, local_date, timezone_name, row["current_revision"]),
            ).fetchall()
        result = dict(row)
        result["sources"] = tuple(
            {
                "ordinal": item["ordinal"],
                "event_id": item["event_id"],
                "event_content_hash": item["event_content_hash"],
                "recorded_at": item["recorded_at"],
                "role": "user" if item["event_type"] == "USER_MESSAGE" else "assistant",
                "content": self._payload_text(item["payload"]),
            }
            for item in sources
        )
        return result

    def calendar_status(self) -> dict[str, Any]:
        with self.repository.pool.connection() as connection:
            row = connection.execute(
                """SELECT source.source_instance_id,source.provider_id,source.adapter_version,
                          source.created_at,state.revision,state.status,state.reason,
                          state.effective_at,observation.source_observed_at AS last_import_at,
                          observation.observation_id,observation.fresh_until,
                          observation.retention_expires_at,
                          consent.status AS consent_status,
                          consent.effective_at AS consent_effective_at,
                          consent.expires_at AS consent_expires_at,
                          health.status AS health_status,
                          health.last_successful_observation_id
                   FROM havre.context_sources source
                   JOIN LATERAL (
                     SELECT * FROM havre.context_source_state_revisions value
                     WHERE value.owner_id=source.owner_id
                       AND value.source_instance_id=source.source_instance_id
                     ORDER BY value.revision DESC LIMIT 1
                   ) state ON true
                   LEFT JOIN LATERAL (
                     SELECT * FROM havre.life_context_observations value
                     WHERE value.owner_id=source.owner_id
                       AND value.source_instance_id=source.source_instance_id
                       AND value.observation_kind='calendar_availability_window'
                     ORDER BY value.source_observed_at DESC LIMIT 1
                   ) observation ON true
                   LEFT JOIN LATERAL (
                     SELECT status,effective_at,expires_at
                     FROM havre.context_consent_scope_revisions value
                     WHERE value.owner_id=source.owner_id
                       AND value.source_instance_id=source.source_instance_id
                     ORDER BY value.revision DESC LIMIT 1
                   ) consent ON true
                   LEFT JOIN LATERAL (
                     SELECT status,last_successful_observation_id
                     FROM havre.context_source_health_records value
                     WHERE value.owner_id=source.owner_id
                       AND value.source_instance_id=source.source_instance_id
                     ORDER BY value.checked_at DESC LIMIT 1
                   ) health ON true
                   WHERE source.owner_id=%s AND source.source_kind='calendar'
                   ORDER BY source.created_at DESC LIMIT 1""",
                (self.owner_id,),
            ).fetchone()
        if row is None:
            return {"configured": False, "status": "not_imported"}
        value = dict(row)
        value["configured"] = True
        now = datetime.now(UTC)
        value["context_eligible"] = bool(
            value["status"] == "enabled"
            and value["observation_id"] is not None
            and value["fresh_until"] is not None
            and value["fresh_until"] > now
            and value["retention_expires_at"] is not None
            and value["retention_expires_at"] > now
            and value["consent_status"] == "active"
            and value["consent_effective_at"] <= now
            and value["consent_expires_at"] > now
            and value["health_status"] == "healthy"
            and value["last_successful_observation_id"] == value["observation_id"]
        )
        return value

    def proactive_preference(self) -> dict[str, Any] | None:
        with self.repository.pool.connection() as connection:
            row = connection.execute(
                """SELECT revision.payload
                   FROM havre.proactive_preference_heads head
                   JOIN havre.proactive_preference_revisions revision
                     ON revision.owner_id=head.owner_id
                    AND revision.preference_revision_id=head.preference_revision_id
                   WHERE head.owner_id=%s""",
                (self.owner_id,),
            ).fetchone()
        return None if row is None else row["payload"]
