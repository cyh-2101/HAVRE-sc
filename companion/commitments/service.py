"""Bounded Goal/Chat/Proactive commitment broker.

The durable Goal remains the schedule authority.  This service exposes only the
five fields the owner explicitly authorized for cloud-eligible conversation:
course name, task name, deadline, completion state, and reminder history.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import re
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from companion.commitments.models import (
    CommitmentCompletionResolution,
    CommitmentFusionClaim,
)
from companion.commitments.recognition import completion_intent, match_task, task_tokens
from companion.context import PersonalContextItem
from companion.goals import GoalStatus
from companion.hashing import content_hash
from companion.ids import uuid7
from companion.persistence.postgres import PostgresRepository
from companion.policy import DataPolicy, PrivacyClass
from companion.policy.models import PRIVACY_RESTRICTION_ORDER


COMMITMENT_AUTHORIZATION_REF = (
    "product-owner-decision:2026-09-03:course-commitment-field-projection-v1"
)
AUTHORIZED_FIELDS = (
    "course_name",
    "task_name",
    "deadline",
    "completion_state",
    "reminder_history",
)
COMMITMENT_POLICY_REVISION_ID = UUID("7f9f93c0-4fa2-4b91-8f29-2a95c0a9c315")


def commitment_data_policy() -> DataPolicy:
    return DataPolicy(
        policy_revision_id=COMMITMENT_POLICY_REVISION_ID,
        privacy_class=PrivacyClass.NORMAL,
        memory_eligible=False,
        training_eligible=False,
        cloud_eligible=True,
        decision_source="owner_explicit",
        authorization_ref=COMMITMENT_AUTHORIZATION_REF,
    )


def _tokens(value: str) -> set[str]:
    return task_tokens(value)


def _completion_intent(message: str) -> bool:
    return completion_intent(message)


def _conversation_suitable(message: str, *, hours_to_deadline: float | None) -> bool:
    text = message.casefold().strip()
    if not text:
        return False
    if any(marker in text for marker in (
        "只回复", "只输出", "精确回复", "胸痛", "呼吸困难", "想自杀",
        "gas leak", "燃气味", "煤气味",
    )):
        return False
    directly_relevant = any(marker in text for marker in (
        "deadline", "due", "作业", "考试", "lab", "quiz", "exam",
        "安排", "计划", "what's next",
    ))
    return directly_relevant


class CommitmentBroker:
    version = "commitment-broker-v1"

    def __init__(self, *, repository: PostgresRepository, owner_id: UUID) -> None:
        self.repository = repository
        self.owner_id = owner_id

    def record_field_authorization(
        self, *, source_sha256: str, authorization_ref: str
    ) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9a-f]{64}", source_sha256):
            raise ValueError("source_sha256 must be 64 lowercase hex characters")
        if authorization_ref != COMMITMENT_AUTHORIZATION_REF:
            raise ValueError("commitment projection requires the exact owner authorization")
        policy = commitment_data_policy()
        material = {
            "owner_id": str(self.owner_id),
            "authorization_ref": authorization_ref,
            "source_sha256": source_sha256,
            "allowed_fields": AUTHORIZED_FIELDS,
            "policy": policy.model_dump(mode="json"),
        }
        authorization_id = uuid7()
        digest = content_hash(material)
        with self.repository.pool.connection() as connection, connection.transaction():
            row = connection.execute(
                """
                INSERT INTO havre.commitment_field_authorizations (
                    authorization_id,owner_id,authorization_ref,source_document_sha256,
                    allowed_fields,policy_revision_id,privacy_class,memory_eligible,
                    training_eligible,cloud_eligible,policy_version,
                    policy_decision_source,policy_authorization_ref,content_hash
                ) VALUES (%s,%s,%s,%s,%s,%s,'NORMAL',false,false,true,
                          'data-policy-v1','owner_explicit',%s,%s)
                ON CONFLICT (owner_id,authorization_ref,source_document_sha256)
                DO NOTHING
                RETURNING *
                """,
                (
                    authorization_id,
                    self.owner_id,
                    authorization_ref,
                    f"sha256:{source_sha256}",
                    list(AUTHORIZED_FIELDS),
                    policy.policy_revision_id,
                    authorization_ref,
                    digest,
                ),
            ).fetchone()
            if row is None:
                row = connection.execute(
                    """SELECT * FROM havre.commitment_field_authorizations
                       WHERE owner_id=%s AND authorization_ref=%s
                         AND source_document_sha256=%s""",
                    (self.owner_id,authorization_ref,f"sha256:{source_sha256}"),
                ).fetchone()
        return dict(row)

    def supersede_legacy_course_reminders(
        self, *, source_sha256: str, replacement_generation: str
    ) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9a-f]{64}", source_sha256):
            raise ValueError("source_sha256 must be 64 lowercase hex characters")
        if replacement_generation != "v2":
            raise ValueError("unsupported course reminder replacement generation")
        source_hash = f"sha256:{source_sha256}"
        legacy_prefix = f"course-{source_sha256[:16]}-%"
        goal_marker = f"owner_course_schedule:%:{source_sha256}:%"
        with self.repository.pool.connection() as connection, connection.transaction():
            authorization = connection.execute(
                """
                SELECT authorization_id
                FROM havre.commitment_field_authorizations
                WHERE owner_id=%s AND authorization_ref=%s
                  AND source_document_sha256=%s
                """,
                (self.owner_id, COMMITMENT_AUTHORIZATION_REF, source_hash),
            ).fetchone()
            if authorization is None:
                raise LookupError("commitment field authorization not found")
            rows = connection.execute(
                """
                SELECT work.work_item_id,work.status
                FROM havre.proactive_work_items work
                JOIN havre.goals goal
                  ON goal.owner_id=work.owner_id
                 AND goal.goal_id=(
                       work.command_payload#>>'{source_guard,projection_id}'
                     )::uuid
                WHERE work.owner_id=%s AND work.work_kind='scheduled'
                  AND work.idempotency_key LIKE %s
                  AND work.command_payload->>'reason_code'='owner_goal_reminder'
                  AND work.command_payload#>>'{source_guard,projection_kind}'='goal'
                  AND goal.why LIKE %s
                  AND work.status IN ('pending','retryable_failed','leased')
                FOR UPDATE OF work
                """,
                (self.owner_id, legacy_prefix, goal_marker),
            ).fetchall()
            if any(row["status"] == "leased" for row in rows):
                raise ValueError(
                    "a legacy course reminder is currently leased; retry after it resolves"
                )
            work_item_ids = [row["work_item_id"] for row in rows]
            cancelled = 0
            if work_item_ids:
                cancelled = connection.execute(
                    """
                    UPDATE havre.proactive_work_items
                    SET status='cancelled',
                        last_error_code='superseded_by_owner_schedule_v2',
                        completed_at=statement_timestamp(),
                        lease_owner=NULL,lease_expires_at=NULL
                    WHERE owner_id=%s AND work_item_id=ANY(%s::uuid[])
                      AND status IN ('pending','retryable_failed')
                    """,
                    (self.owner_id, work_item_ids),
                ).rowcount
        return {
            "source_sha256": source_sha256,
            "replacement_generation": replacement_generation,
            "legacy_reminders_cancelled": cancelled,
        }

    def project_goal(
        self,
        *,
        goal_id: UUID,
        source_sha256: str,
        entry_id: str,
        course_name: str,
        task_name: str,
        deadline_at: datetime | None,
    ) -> dict[str, Any]:
        course_name = course_name.strip()
        task_name = task_name.strip()
        if not course_name or len(course_name) > 160:
            raise ValueError("course_name must contain 1 to 160 characters")
        if not task_name or len(task_name) > 500:
            raise ValueError("task_name must contain 1 to 500 characters")
        if deadline_at is not None and deadline_at.utcoffset() is None:
            raise ValueError("deadline_at must be timezone-aware")
        source_hash = f"sha256:{source_sha256}"
        policy = commitment_data_policy()
        with self.repository.pool.connection() as connection, connection.transaction():
            authorization = connection.execute(
                """
                SELECT * FROM havre.commitment_field_authorizations
                WHERE owner_id=%s AND authorization_ref=%s
                  AND source_document_sha256=%s
                """,
                (self.owner_id, COMMITMENT_AUTHORIZATION_REF, source_hash),
            ).fetchone()
            if authorization is None:
                raise LookupError("commitment field authorization not found")
            goal = connection.execute(
                """
                SELECT goal.*,event.content_hash AS source_event_content_hash
                FROM havre.goals goal
                JOIN havre.events event ON event.owner_id=goal.owner_id
                  AND event.event_id=goal.last_event_id
                WHERE goal.owner_id=%s AND goal.goal_id=%s
                """,
                (self.owner_id, goal_id),
            ).fetchone()
            if goal is None:
                raise LookupError("goal not found")
            history = self._reminder_history(connection, goal_id=goal_id)
            projection_id = uuid7()
            material = {
                "owner_id": str(self.owner_id),
                "goal_id": str(goal_id),
                "goal_revision": goal["revision"],
                "source_goal_content_hash": goal["content_hash"],
                "source_event_id": str(goal["last_event_id"]),
                "source_event_content_hash": goal["source_event_content_hash"],
                "authorization_id": str(authorization["authorization_id"]),
                "entry_id": entry_id,
                "course_name": course_name,
                "task_name": task_name,
                "deadline_at": deadline_at.astimezone(UTC).isoformat() if deadline_at else None,
                "completion_state": goal["status"],
                "reminder_history": history,
                "policy_revision_id": str(policy.policy_revision_id),
            }
            digest = content_hash(material)
            row = connection.execute(
                """
                INSERT INTO havre.commitment_projections (
                    commitment_projection_id,owner_id,goal_id,goal_revision,
                    source_goal_content_hash,source_event_id,source_event_content_hash,
                    authorization_id,source_document_sha256,entry_id,course_name,
                    task_name,deadline_at,
                    completion_state,reminder_history,privacy_class,memory_eligible,
                    training_eligible,cloud_eligible,policy_version,policy_revision_id,
                    policy_decision_source,policy_authorization_ref,content_hash
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                          'NORMAL',false,false,true,'data-policy-v1',%s,
                          'owner_explicit',%s,%s)
                ON CONFLICT (owner_id,goal_id,goal_revision)
                DO NOTHING
                RETURNING *
                """,
                (
                    projection_id,self.owner_id,goal_id,goal["revision"],
                    goal["content_hash"],goal["last_event_id"],
                    goal["source_event_content_hash"],authorization["authorization_id"],
                    source_hash,entry_id,course_name,task_name,
                    deadline_at.astimezone(UTC) if deadline_at else None,
                    goal["status"],Jsonb(history),policy.policy_revision_id,
                    COMMITMENT_AUTHORIZATION_REF,digest,
                ),
            ).fetchone()
            if row is None:
                row = connection.execute(
                    """SELECT * FROM havre.commitment_projections
                       WHERE owner_id=%s AND goal_id=%s AND goal_revision=%s""",
                    (self.owner_id,goal_id,goal["revision"]),
                ).fetchone()
        return dict(row)

    def _reminder_history(
        self, connection, *, goal_id: UUID
    ) -> list[dict[str, str]]:
        rows = connection.execute(
            """
            SELECT delivered_at,delivery_mode,reminder_kind
            FROM havre.commitment_reminder_deliveries
            WHERE owner_id=%s AND goal_id=%s
            ORDER BY delivered_at DESC LIMIT 12
            """,
            (self.owner_id,goal_id),
        ).fetchall()
        return [
            {
                "delivered_at": row["delivered_at"].isoformat(),
                "delivery_mode": row["delivery_mode"],
                "reminder_kind": row["reminder_kind"],
            }
            for row in rows
        ]

    def select_context(
        self,
        *,
        query_text: str,
        maximum_privacy_class: PrivacyClass,
        as_of: datetime | None = None,
        limit: int = 3,
    ) -> tuple[PersonalContextItem, ...]:
        policy = commitment_data_policy()
        if (
            PRIVACY_RESTRICTION_ORDER[policy.privacy_class]
            > PRIVACY_RESTRICTION_ORDER[maximum_privacy_class]
        ):
            return ()
        instant = (as_of or datetime.now(UTC)).astimezone(UTC)
        query_tokens = _tokens(query_text)
        planning = any(marker in query_text.casefold() for marker in (
            "deadline", "due", "what's next", "作业", "考试", "安排", "计划",
            "有什么要做", "该做什么", "接下来做什么", "任务",
        ))
        with self.repository.pool.connection() as connection:
            rows = connection.execute(
                """
                SELECT projection.*
                FROM havre.commitment_projections projection
                JOIN havre.goals goal ON goal.owner_id=projection.owner_id
                  AND goal.goal_id=projection.goal_id
                  AND goal.revision=projection.goal_revision
                  AND goal.content_hash=projection.source_goal_content_hash
                WHERE projection.owner_id=%s AND goal.status='active'
                  AND projection.completion_state='active'
                  AND (projection.deadline_at IS NULL
                       OR projection.deadline_at>=%s-interval '1 day')
                ORDER BY projection.deadline_at NULLS LAST,projection.task_name
                """,
                (self.owner_id, instant),
            ).fetchall()
        scored: list[tuple[float, Any]] = []
        for row in rows:
            matching = query_tokens.intersection(_tokens(
                f"{row['course_name']} {row['task_name']}"
            ))
            # A number in smalltalk ("ate two bowls") is not a task reference.
            overlap = len(matching) if any(not token[0].isdigit() for token in matching) else 0
            hours = None
            if row["deadline_at"] is not None:
                hours = (row["deadline_at"] - instant).total_seconds() / 3600
            urgency = 0 if hours is None else max(0.0, 168.0 - max(hours, 0.0)) / 168.0
            if overlap == 0 and not planning:
                continue
            scored.append((overlap * 10 + urgency, row))
        scored.sort(key=lambda value: (-value[0], value[1]["task_name"]))
        items: list[PersonalContextItem] = []
        for _, row in scored[: max(1, min(limit, 3))]:
            with self.repository.pool.connection() as history_connection:
                history = self._reminder_history(
                    history_connection,
                    goal_id=row["goal_id"],
                )
            content = json.dumps(
                {
                    "course_name": row["course_name"],
                    "task_name": row["task_name"],
                    "deadline": (
                        row["deadline_at"].isoformat()
                        if row["deadline_at"] is not None else None
                    ),
                    "completion_state": row["completion_state"],
                    "reminder_history": history,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            items.append(PersonalContextItem(
                owner_id=self.owner_id,
                section_id=f"commitment-{row['commitment_projection_id']}",
                section_type="goal",
                content_text=(
                    "Owner-authorized commitment projection. Use only these fields; "
                    "do not infer grades, source-document content, journal facts, or "
                    f"other memories: {content}"
                ),
                priority=92,
                source_refs=(
                    f"commitment/{row['commitment_projection_id']}",
                    f"goal/{row['goal_id']}@{row['goal_revision']}",
                    f"authorization/{row['authorization_id']}",
                ),
                data_policy=policy,
            ))
        return tuple(items)

    def resolve_completion(
        self, *, user_event_id: UUID, session_id: UUID, message: str
    ) -> CommitmentCompletionResolution:
        if not _completion_intent(message):
            return CommitmentCompletionResolution(status="none")
        with self.repository.pool.connection() as connection:
            rows = connection.execute(
                """
                SELECT projection.*,goal.priority
                FROM havre.commitment_projections projection
                JOIN havre.goals goal ON goal.owner_id=projection.owner_id
                  AND goal.goal_id=projection.goal_id
                  AND goal.revision=projection.goal_revision
                  AND goal.status='active'
                WHERE projection.owner_id=%s AND projection.completion_state='active'
                """,
                (self.owner_id,),
            ).fetchall()
            scored: list[tuple[int, Any]] = []
            for row in rows:
                overlap, complete = match_task(
                    message, course_name=row["course_name"], task_name=row["task_name"]
                )
                if overlap:
                    scored.append((overlap, dict(row, fully_identified=complete)))
        if not scored:
            # A prior prompt containing a Goal is not evidence that a later 'done'
            # refers to it. Nor should finishing lunch invite task administration.
            normalized = re.sub(r"^不是(?:啊|呀)?[，,\s]+", "", message.casefold().strip(" 。.!！"))
            if not re.fullmatch(r"(?:(?:我)?(?:都|已经)?(?:搞完|做完|写完|完成)了|done|finished|completed)",normalized) or not rows:
                return CommitmentCompletionResolution(status="none")
            return CommitmentCompletionResolution(
                status="ambiguous",
                clarification_text="你说的是哪一项任务完成了？给我课程名或任务名就行。",
            )
        best = max(score for score, _ in scored)
        candidates = [row for score, row in scored if score == best]
        if len(candidates) != 1 or not candidates[0]["fully_identified"]:
            names = "、".join(row["task_name"] for row in candidates[:3])
            return CommitmentCompletionResolution(
                status="ambiguous",
                candidate_goal_ids=tuple(row["goal_id"] for row in candidates),
                clarification_text=f"你完成的是哪一个：{names}？",
            )
        target = candidates[0]
        updated = self.repository.update_goal(
            owner_id=self.owner_id,
            goal_id=target["goal_id"],
            expected_revision=target["goal_revision"],
            reason="Owner explicitly reported this commitment complete in chat",
            status=GoalStatus.COMPLETED,
            source_event_id=user_event_id,
        )
        return CommitmentCompletionResolution(
            status="completed",
            goal_id=updated.goal_id,
            goal_revision=updated.revision,
        )

    def _project_after_transition(self, *, previous: Any, goal: Any) -> None:
        source_hash = previous["source_document_sha256"].removeprefix("sha256:")
        self.project_goal(
            goal_id=goal.goal_id,
            source_sha256=source_hash,
            entry_id=previous["entry_id"],
            course_name=previous["course_name"],
            task_name=previous["task_name"],
            deadline_at=previous["deadline_at"],
        )

    def cancel_goal_reminders(self, *, goal_id: UUID) -> int:
        with self.repository.pool.connection() as connection, connection.transaction():
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (f"proactive-owner:{self.owner_id}",),
            )
            rows = connection.execute(
                """
                UPDATE havre.proactive_work_items
                SET status='cancelled',last_error_code='goal_no_longer_active',
                    completed_at=statement_timestamp(),lease_owner=NULL,
                    lease_expires_at=NULL
                WHERE owner_id=%s
                  AND status IN ('pending','retryable_failed','leased')
                  AND command_payload#>>'{source_guard,projection_kind}'='goal'
                  AND command_payload#>>'{source_guard,projection_id}'=%s
                RETURNING work_item_id
                """,
                (self.owner_id, str(goal_id)),
            ).fetchall()
        return len(rows)

    def begin_interaction_activity(self, *, request_id: UUID) -> int:
        with self.repository.pool.connection() as connection, connection.transaction():
            state = connection.execute(
                """
                INSERT INTO havre.owner_conversation_delivery_state (
                    owner_id,arrival_epoch,updated_at
                ) VALUES (%s,1,statement_timestamp())
                ON CONFLICT (owner_id) DO UPDATE
                  SET arrival_epoch=havre.owner_conversation_delivery_state.arrival_epoch+1,
                      updated_at=statement_timestamp()
                RETURNING arrival_epoch
                """,
                (self.owner_id,),
            ).fetchone()
            connection.execute(
                """
                INSERT INTO havre.interaction_activity_leases (
                    owner_id,request_id,arrival_epoch,expires_at
                ) VALUES (%s,%s,%s,statement_timestamp()+interval '5 minutes')
                """,
                (self.owner_id, request_id, state["arrival_epoch"]),
            )
        return state["arrival_epoch"]

    def end_interaction_activity(self, *, request_id: UUID) -> None:
        with self.repository.pool.connection() as connection, connection.transaction():
            connection.execute(
                """
                UPDATE havre.interaction_activity_leases
                SET ended_at=COALESCE(ended_at,statement_timestamp())
                WHERE owner_id=%s AND request_id=%s
                """,
                (self.owner_id, request_id),
            )

    def standalone_epoch(self) -> int | None:
        with self.repository.pool.connection() as connection:
            state = connection.execute(
                """
                SELECT arrival_epoch,
                       EXISTS(SELECT 1 FROM havre.interaction_activity_leases lease
                              WHERE lease.owner_id=state.owner_id
                                AND lease.ended_at IS NULL
                                AND lease.expires_at>statement_timestamp()) AS active
                FROM havre.owner_conversation_delivery_state state
                WHERE state.owner_id=%s
                """,
                (self.owner_id,),
            ).fetchone()
        if state is None:
            return 0
        return None if state["active"] else state["arrival_epoch"]

    def claim_due_for_interaction(
        self,
        *,
        request_id: UUID,
        query_text: str,
        as_of: datetime | None = None,
        limit: int = 2,
    ) -> tuple[CommitmentFusionClaim, ...]:
        instant = (as_of or datetime.now(UTC)).astimezone(UTC)
        with self.repository.pool.connection() as connection, connection.transaction():
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (f"proactive-owner:{self.owner_id}",),
            )
            delivered_24h = connection.execute(
                """
                SELECT count(*) AS value FROM havre.commitment_reminder_deliveries
                WHERE owner_id=%s AND delivered_at>=%s-interval '24 hours'
                """,
                (self.owner_id, instant),
            ).fetchone()["value"]
            if delivered_24h >= 24:
                return ()
            rows = connection.execute(
                """
                SELECT work.*,goal.revision AS current_goal_revision,
                       goal.content_hash AS current_goal_content_hash,
                       goal.last_event_id AS current_goal_event_id,
                       goal.priority,projection.*
                FROM havre.proactive_work_items work
                JOIN havre.goals goal
                  ON goal.owner_id=work.owner_id
                 AND goal.goal_id=(work.command_payload#>>'{source_guard,projection_id}')::uuid
                JOIN havre.commitment_projections projection
                  ON projection.owner_id=goal.owner_id
                 AND projection.goal_id=goal.goal_id
                 AND projection.goal_revision=goal.revision
                WHERE work.owner_id=%s AND work.status IN ('pending','retryable_failed')
                  AND (work.not_before<=%s
                       OR work.last_error_code='active_conversation_deferred')
                  AND (work.command_payload->>'expires_at')::timestamptz>%s
                  AND work.command_payload->>'reason_code'='owner_goal_reminder'
                  AND goal.status='active'
                  AND NOT EXISTS (
                    SELECT 1 FROM havre.proactive_fusion_claims claim
                    WHERE claim.owner_id=work.owner_id
                      AND claim.work_item_id=work.work_item_id
                      AND claim.status='claimed'
                  )
                FOR UPDATE OF work SKIP LOCKED
                """,
                (self.owner_id, instant, instant),
            ).fetchall()
            ranked: list[tuple[float, Any, str]] = []
            query_tokens = _tokens(query_text)
            for row in rows:
                command = row["command_payload"]
                guard = command.get("source_guard") or {}
                if (
                    guard.get("projection_revision") != row["current_goal_revision"]
                    or guard.get("projection_content_hash") != row["current_goal_content_hash"]
                    or guard.get("source_event_id") != str(row["current_goal_event_id"])
                ):
                    continue
                deadline = row["deadline_at"]
                hours = None if deadline is None else (deadline-instant).total_seconds()/3600
                if not _conversation_suitable(query_text, hours_to_deadline=hours):
                    continue
                overlap = len(query_tokens.intersection(_tokens(
                    f"{row['course_name']} {row['task_name']}"
                )))
                urgency = 0.0 if hours is None else max(0.0, 168-max(hours,0))/24
                importance = {"high": 3.0, "normal": 2.0, "low": 1.0}[row["priority"]]
                history = row["reminder_history"] or []
                recency_penalty = 3.0 if history and (
                    instant-datetime.fromisoformat(history[0]["delivered_at"])
                ) < timedelta(hours=12) else 0.0
                ranked.append((overlap*4+urgency+importance-recency_penalty,row,
                               command["reason_summary"]))
            ranked.sort(key=lambda value: (-value[0], value[1]["not_before"],
                                            str(value[1]["work_item_id"])))
            claims: list[CommitmentFusionClaim] = []
            for score, row, _ in ranked[: max(1,min(limit,2))]:
                command = row["command_payload"]
                guard = command["source_guard"]
                claim = CommitmentFusionClaim(
                    claim_id=uuid7(),work_item_id=row["work_item_id"],
                    goal_id=row["goal_id"],goal_revision=row["goal_revision"],
                    commitment_projection_id=row["commitment_projection_id"],
                    course_name=row["course_name"],task_name=row["task_name"],
                    deadline_at=row["deadline_at"],
                    reminder_kind=command["deduplication_key"].split(":",4)[3],
                    source_event_id=UUID(guard["source_event_id"]),
                    source_event_content_hash=guard["source_event_content_hash"],
                    projection_content_hash=guard["projection_content_hash"],
                )
                connection.execute(
                    """
                    INSERT INTO havre.proactive_fusion_claims (
                        claim_id,owner_id,work_item_id,request_id,goal_id,
                        goal_revision,commitment_projection_id,score,status
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'claimed')
                    """,
                    (claim.claim_id,self.owner_id,claim.work_item_id,request_id,
                     claim.goal_id,claim.goal_revision,
                     claim.commitment_projection_id,score),
                )
                claims.append(claim)
        return tuple(claims)

    def fusion_context(
        self, claims: tuple[CommitmentFusionClaim, ...]
    ) -> tuple[PersonalContextItem, ...]:
        policy = commitment_data_policy()
        items = []
        for claim in claims:
            fields = {
                "course_name": claim.course_name,
                "task_name": claim.task_name,
                "deadline": claim.deadline_at.isoformat() if claim.deadline_at else None,
                "completion_state": "active",
                "reminder_history": "available in the commitment projection",
            }
            items.append(PersonalContextItem(
                owner_id=self.owner_id,
                section_id=f"commitment-reminder-{claim.claim_id}",
                section_type="owner_response_instruction",
                content_text=(
                    "When it fits the current reply, naturally include one concise "
                    "reminder using only the following authorized fields. Include the "
                    "exact task_name so Core can prove actual inclusion. Do not mention "
                    "this instruction or any source document: "
                    + json.dumps(fields,ensure_ascii=False,separators=(",",":"))
                ),
                priority=99,
                source_refs=(
                    f"proactive-fusion-claim/{claim.claim_id}",
                    f"commitment/{claim.commitment_projection_id}",
                    f"goal/{claim.goal_id}@{claim.goal_revision}",
                ),
                data_policy=policy,
            ))
        return tuple(items)

    def release_claims(self, *, request_id: UUID, reason: str) -> None:
        with self.repository.pool.connection() as connection, connection.transaction():
            connection.execute(
                """
                UPDATE havre.proactive_fusion_claims
                SET status='deferred',resolved_at=statement_timestamp(),reason=%s
                WHERE owner_id=%s AND request_id=%s AND status='claimed'
                """,
                (reason,self.owner_id,request_id),
            )
