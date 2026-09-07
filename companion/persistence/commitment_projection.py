"""Refresh an already-authorized five-field projection inside a Goal transaction."""
from datetime import UTC

from psycopg.types.json import Jsonb

from companion.hashing import content_hash
from companion.ids import uuid7


def refresh_commitment_projection(connection, *, owner_id, goal, previous_revision):
    # Older migration fixtures legitimately have no commitment broker tables.
    if not connection.execute(
        "SELECT to_regclass('havre.commitment_projections') IS NOT NULL AS present"
    ).fetchone()["present"]:
        return
    previous = connection.execute(
        "SELECT * FROM havre.commitment_projections "
        "WHERE owner_id=%s AND goal_id=%s AND goal_revision=%s",
        (owner_id, goal.goal_id, previous_revision),
    ).fetchone()
    if previous is None:
        return  # Never manufacture disclosure authority for an ordinary Goal.
    event = connection.execute(
        "SELECT content_hash FROM havre.events WHERE owner_id=%s AND event_id=%s",
        (owner_id, goal.last_event_id),
    ).fetchone()
    history_rows = connection.execute(
        "SELECT delivered_at,delivery_mode,reminder_kind "
        "FROM havre.commitment_reminder_deliveries WHERE owner_id=%s AND goal_id=%s "
        "ORDER BY delivered_at DESC LIMIT 12", (owner_id, goal.goal_id),
    ).fetchall()
    history = [dict(row, delivered_at=row["delivered_at"].isoformat()) for row in history_rows]
    material = {
        "owner_id": str(owner_id), "goal_id": str(goal.goal_id),
        "goal_revision": goal.revision, "source_goal_content_hash": goal.content_hash,
        "source_event_id": str(goal.last_event_id),
        "source_event_content_hash": event["content_hash"],
        "authorization_id": str(previous["authorization_id"]),
        "entry_id": previous["entry_id"], "course_name": previous["course_name"],
        "task_name": previous["task_name"],
        "deadline_at": previous["deadline_at"].astimezone(UTC).isoformat()
        if previous["deadline_at"] else None,
        "completion_state": goal.status.value, "reminder_history": history,
        "policy_revision_id": str(previous["policy_revision_id"]),
    }
    connection.execute(
        """INSERT INTO havre.commitment_projections (
            commitment_projection_id,owner_id,goal_id,goal_revision,
            source_goal_content_hash,source_event_id,source_event_content_hash,
            authorization_id,source_document_sha256,entry_id,course_name,task_name,
            deadline_at,completion_state,reminder_history,privacy_class,memory_eligible,
            training_eligible,cloud_eligible,policy_version,policy_revision_id,
            policy_decision_source,policy_authorization_ref,content_hash
        ) SELECT %s,owner_id,goal_id,%s,%s,%s,%s,authorization_id,
            source_document_sha256,entry_id,course_name,task_name,deadline_at,%s,%s,
            privacy_class,memory_eligible,training_eligible,cloud_eligible,
            policy_version,policy_revision_id,policy_decision_source,
            policy_authorization_ref,%s
          FROM havre.commitment_projections WHERE owner_id=%s
            AND commitment_projection_id=%s""",
        (uuid7(), goal.revision, goal.content_hash, goal.last_event_id,
         event["content_hash"], goal.status.value, Jsonb(history), content_hash(material),
         owner_id, previous["commitment_projection_id"]),
    )
