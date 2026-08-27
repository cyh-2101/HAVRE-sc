"""Transactional owner-feedback persistence and review gates."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from psycopg.types.json import Jsonb

from companion.feedback.models import (
    CommunicationPreference,
    FeedbackIssueAttribution,
    FeedbackRating,
    FeedbackReasonCode,
    FeedbackReviewDecision,
    PersonalizationFeedback,
    PersonalizationFeedbackReview,
)
from companion.ids import uuid7
from companion.hashing import content_hash
from companion.policy import combine_policies


class FeedbackService:
    version = "owner-feedback-service-v1"

    def __init__(self, *, repository, owner_id: UUID) -> None:
        self.repository = repository
        self.owner_id = owner_id

    def save(
        self,
        *,
        assistant_event_id: UUID,
        rating: FeedbackRating,
        reason_codes: tuple[FeedbackReasonCode, ...] = (),
        reason_text: str | None = None,
        owner_revision_text: str | None = None,
        expected_revision: int | None = None,
    ) -> PersonalizationFeedback:
        with self.repository.pool.connection() as connection, connection.transaction():
            source = connection.execute(
                """
                SELECT req.request_id, req.session_id, req.trace_id, req.user_event_id,
                       req.assistant_event_id, req.context_pack_id,
                       attempt.route_decision_id, req.inference_response_id,
                       attempt.provider_id, attempt.model_version_id,
                       attempt.adapter_version_id, attempt.tokenizer_version_id,
                       attempt.serving_config_version, event.privacy_class
                FROM havre.interaction_requests AS req
                JOIN havre.events AS event
                  ON event.owner_id=req.owner_id
                 AND event.event_id=req.assistant_event_id
                JOIN havre.inference_attempts AS attempt
                  ON attempt.owner_id=req.owner_id
                 AND attempt.inference_response_id=req.inference_response_id
                WHERE req.owner_id=%s AND req.assistant_event_id=%s
                  AND req.status='completed'
                FOR UPDATE OF req
                """,
                (self.owner_id, assistant_event_id),
            ).fetchone()
            if source is None:
                raise LookupError("completed assistant response not found")
            head = connection.execute(
                """SELECT * FROM havre.response_feedback_heads
                   WHERE owner_id=%s AND assistant_event_id=%s FOR UPDATE""",
                (self.owner_id, assistant_event_id),
            ).fetchone()
            if head is None:
                if expected_revision not in (None, 0):
                    raise ValueError("feedback expected_revision conflict")
                feedback_id, revision = uuid7(), 1
            else:
                if expected_revision is None or expected_revision != head["current_revision"]:
                    raise ValueError("feedback expected_revision conflict")
                feedback_id, revision = head["feedback_id"], head["current_revision"] + 1
            item = PersonalizationFeedback(
                feedback_id=feedback_id,
                revision=revision,
                owner_id=self.owner_id,
                **source,
                rating=rating,
                reason_codes=reason_codes,
                reason_text=reason_text,
                owner_revision_text=owner_revision_text,
            )
            if head is None:
                connection.execute(
                    """
                    INSERT INTO havre.response_feedback_heads (
                      owner_id, feedback_id, request_id, session_id, trace_id,
                      user_event_id, assistant_event_id, context_pack_id,
                      route_decision_id, inference_response_id, current_revision
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1)
                    """,
                    (
                        self.owner_id, feedback_id, source["request_id"],
                        source["session_id"], source["trace_id"], source["user_event_id"],
                        source["assistant_event_id"], source["context_pack_id"],
                        source["route_decision_id"], source["inference_response_id"],
                    ),
                )
            if head is not None:
                connection.execute(
                    """UPDATE havre.response_feedback_heads
                       SET current_revision=%s, updated_at=clock_timestamp()
                       WHERE owner_id=%s AND feedback_id=%s""",
                    (revision, self.owner_id, feedback_id),
                )
            connection.execute(
                """
                INSERT INTO havre.response_feedback_revisions (
                  owner_id, feedback_id, revision, rating, reason_codes,
                  reason_text, owner_revision_text, provider_id, model_version_id,
                  adapter_version_id, tokenizer_version_id, serving_config_version,
                  privacy_class, training_eligible, content_hash, created_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,false,%s,%s)
                """,
                (
                    self.owner_id, feedback_id, revision, rating.value,
                    [value.value for value in reason_codes], reason_text,
                    owner_revision_text, source["provider_id"],
                    source["model_version_id"], source["adapter_version_id"],
                    source["tokenizer_version_id"], source["serving_config_version"],
                    source["privacy_class"], item.content_hash, item.created_at,
                ),
            )
        return item

    def list(self, *, limit: int = 100) -> tuple[PersonalizationFeedback, ...]:
        with self.repository.pool.connection() as connection:
            rows = connection.execute(
                """
                SELECT head.*, rev.*, review.review_id
                FROM havre.response_feedback_heads AS head
                JOIN havre.response_feedback_revisions AS rev
                  ON rev.owner_id=head.owner_id AND rev.feedback_id=head.feedback_id
                 AND rev.revision=head.current_revision
                LEFT JOIN havre.personalization_feedback_reviews AS review
                  ON review.owner_id=rev.owner_id AND review.feedback_id=rev.feedback_id
                 AND review.feedback_revision=rev.revision
                WHERE head.owner_id=%s
                ORDER BY rev.created_at DESC LIMIT %s
                """,
                (self.owner_id, limit),
            ).fetchall()
        return tuple(self._feedback(row, reviewed=row["review_id"] is not None) for row in rows)

    def list_conversations(self, *, limit: int = 50) -> tuple[dict, ...]:
        with self.repository.pool.connection() as connection:
            rows = connection.execute(
                """
                SELECT session.session_id, session.created_at, session.last_activity_at,
                       session.closed_at,
                       first_user.payload AS first_payload,
                       count(event.event_id) AS event_count
                FROM havre.sessions AS session
                JOIN havre.events AS event
                  ON event.owner_id=session.owner_id AND event.session_id=session.session_id
                LEFT JOIN LATERAL (
                  SELECT payload FROM havre.events first_event
                  WHERE first_event.owner_id=session.owner_id
                    AND first_event.session_id=session.session_id
                    AND first_event.event_type='USER_MESSAGE'
                  ORDER BY first_event.recorded_at, first_event.event_id LIMIT 1
                ) AS first_user ON true
                WHERE session.owner_id=%s
                GROUP BY session.session_id, session.created_at,
                         session.last_activity_at, session.closed_at, first_user.payload
                ORDER BY session.last_activity_at DESC LIMIT %s
                """,
                (self.owner_id, limit),
            ).fetchall()
        result = []
        for row in rows:
            title = self._payload_text(row["first_payload"])[:80] or "New conversation"
            result.append({
                "session_id": row["session_id"], "title": title,
                "event_count": row["event_count"],
                "created_at": row["created_at"],
                "last_activity_at": row["last_activity_at"],
                "closed_at": row["closed_at"],
            })
        return tuple(result)

    def conversation(self, *, session_id: UUID) -> tuple[dict, ...]:
        with self.repository.pool.connection() as connection:
            rows = connection.execute(
                """
                SELECT event.event_id, event.request_id, event.event_type,
                       event.payload, event.recorded_at, request.trace_id,
                       head.feedback_id, head.current_revision,
                       feedback.rating, feedback.reason_codes,
                       feedback.reason_text, feedback.owner_revision_text,
                       review.decision AS review_decision
                FROM havre.events AS event
                JOIN havre.interaction_requests AS request
                  ON request.owner_id=event.owner_id AND request.request_id=event.request_id
                LEFT JOIN havre.response_feedback_heads AS head
                  ON head.owner_id=event.owner_id AND head.assistant_event_id=event.event_id
                LEFT JOIN havre.response_feedback_revisions AS feedback
                  ON feedback.owner_id=head.owner_id AND feedback.feedback_id=head.feedback_id
                 AND feedback.revision=head.current_revision
                LEFT JOIN havre.personalization_feedback_reviews AS review
                  ON review.owner_id=feedback.owner_id
                 AND review.feedback_id=feedback.feedback_id
                 AND review.feedback_revision=feedback.revision
                WHERE event.owner_id=%s AND event.session_id=%s
                  AND event.event_type IN ('USER_MESSAGE','ASSISTANT_MESSAGE')
                ORDER BY event.recorded_at, event.event_id
                """,
                (self.owner_id, session_id),
            ).fetchall()
        return tuple({
            "event_id": row["event_id"], "request_id": row["request_id"],
            "trace_id": row["trace_id"],
            "role": "user" if row["event_type"] == "USER_MESSAGE" else "assistant",
            "content": self._payload_text(row["payload"]),
            "recorded_at": row["recorded_at"],
            "feedback": None if row["feedback_id"] is None else {
                "feedback_id": row["feedback_id"],
                "revision": row["current_revision"], "rating": row["rating"],
                "reason_codes": row["reason_codes"], "reason_text": row["reason_text"],
                "owner_revision_text": row["owner_revision_text"],
                "review_decision": row["review_decision"],
                "training_eligible": row["review_decision"] == "approved_for_personalization_training",
            },
        } for row in rows)

    def close_episode(
        self, *, session_id: UUID, boundary_reason: str
    ) -> dict:
        if boundary_reason not in {
            "owner_started_new_conversation", "owner_closed", "idle_boundary"
        }:
            raise ValueError("unsupported episode boundary reason")
        with self.repository.pool.connection() as connection, connection.transaction():
            session = connection.execute(
                """SELECT * FROM havre.sessions
                   WHERE owner_id=%s AND session_id=%s FOR UPDATE""",
                (self.owner_id, session_id),
            ).fetchone()
            if session is None:
                raise LookupError("conversation session not found")
            if session["closed_at"] is not None:
                existing = connection.execute(
                    """SELECT * FROM havre.conversation_episodes
                       WHERE owner_id=%s AND episode_id=%s""",
                    (self.owner_id, session["closed_episode_id"]),
                ).fetchone()
                if existing is None:
                    raise RuntimeError("closed session is missing its durable episode")
                return dict(existing)
            processing = connection.execute(
                """SELECT 1 FROM havre.interaction_requests
                   WHERE owner_id=%s AND session_id=%s AND status='processing'
                   LIMIT 1""",
                (self.owner_id, session_id),
            ).fetchone()
            if processing is not None:
                raise ValueError("conversation still has an interaction in progress")
            rows = connection.execute(
                """
                SELECT event_id,event_type,payload,content_hash,privacy_class,
                       memory_eligible,training_eligible,cloud_eligible,
                       policy_version,policy_revision_id,policy_decision_source,
                       policy_authorization_ref,recorded_at
                FROM havre.events
                WHERE owner_id=%s AND session_id=%s
                  AND event_type IN ('USER_MESSAGE','ASSISTANT_MESSAGE')
                ORDER BY recorded_at,event_id FOR SHARE
                """,
                (self.owner_id, session_id),
            ).fetchall()
            if not rows:
                raise LookupError("conversation has no durable message events")
            episode_id = uuid7()
            user_text = [self._payload_text(row["payload"]) for row in rows
                         if row["event_type"] == "USER_MESSAGE"
                         and row["memory_eligible"]]
            user_rows = [row for row in rows if row["event_type"] == "USER_MESSAGE"]
            policies = tuple(self.repository._policy_from_row(row) for row in user_rows)
            episode_policy = combine_policies(policies)
            # V1 summary is minimum-sufficient owner experience only. Assistant
            # Events remain exact episode members/history but are not copied into
            # a recalled derivative whose own Memory policy may be stricter.
            summary = self._episode_summary(user_text)
            privacy_rank = {
                "PUBLIC":0,"NORMAL":1,"PRIVATE":2,"HIGHLY_PRIVATE":3,"LOCAL_ONLY":4
            }
            privacy = max((row["privacy_class"] for row in rows), key=privacy_rank.get)
            material = {
                "schema_version":1,"owner_id":str(self.owner_id),
                "episode_id":str(episode_id),"session_id":str(session_id),
                "member_event_hashes":[row["content_hash"] for row in rows],
                "summary_text":summary,"summary_method":"extractive-episode-summary-v1",
                "privacy_class":privacy,"memory_eligible":episode_policy.memory_eligible,
                "training_eligible":False,"cloud_eligible":episode_policy.cloud_eligible,
                "boundary_reason":boundary_reason,
            }
            episode_hash = content_hash(material)
            connection.execute(
                """
                INSERT INTO havre.conversation_episodes (
                  owner_id,episode_id,session_id,status,boundary_reason,message_count,
                  summary_text,summary_method,privacy_class,memory_eligible,
                  training_eligible,cloud_eligible,policy_version,policy_revision_id,
                  policy_decision_source,policy_authorization_ref,
                  content_hash,started_at,ended_at
                ) VALUES (%s,%s,%s,'closed',%s,%s,%s,
                          'extractive-episode-summary-v1',%s,%s,false,%s,%s,%s,%s,%s,
                          %s,%s,%s)
                """,
                (self.owner_id,episode_id,session_id,boundary_reason,len(rows),summary,
                 privacy,episode_policy.memory_eligible,episode_policy.cloud_eligible,
                 episode_policy.policy_version,episode_policy.policy_revision_id,
                 episode_policy.decision_source,episode_policy.authorization_ref,
                 episode_hash,rows[0]["recorded_at"],rows[-1]["recorded_at"]),
            )
            for ordinal,row in enumerate(rows):
                connection.execute(
                    """INSERT INTO havre.conversation_episode_members
                       (owner_id,episode_id,ordinal,event_id,event_content_hash,event_type)
                       VALUES (%s,%s,%s,%s,%s,%s)""",
                    (self.owner_id,episode_id,ordinal,row["event_id"],
                     row["content_hash"],row["event_type"]),
                )
            suggestion_id = uuid7()
            suggestion_material = {
                "schema_version":1,"owner_id":str(self.owner_id),
                "suggestion_id":str(suggestion_id),"episode_id":str(episode_id),
                "memory_class":"episodic","content_text":summary,
                "extractor_version":"episode-suggestion-v1",
                "privacy_class":privacy,
                "memory_eligible":episode_policy.memory_eligible,
                "training_eligible":False,
                "cloud_eligible":episode_policy.cloud_eligible,
                "policy_version":episode_policy.policy_version,
                "policy_revision_id":str(episode_policy.policy_revision_id),
                "policy_decision_source":episode_policy.decision_source,
                "policy_authorization_ref":episode_policy.authorization_ref,
            }
            connection.execute(
                """INSERT INTO havre.episode_memory_suggestions (
                     owner_id,suggestion_id,episode_id,memory_class,content_text,
                     extractor_version,status,privacy_class,memory_eligible,
                     training_eligible,cloud_eligible,policy_version,
                     policy_revision_id,policy_decision_source,
                     policy_authorization_ref,content_hash
                   ) VALUES (%s,%s,%s,'episodic',%s,'episode-suggestion-v1',
                             'pending',%s,%s,false,%s,%s,%s,%s,%s,%s)""",
                (self.owner_id,suggestion_id,episode_id,summary,privacy,
                 episode_policy.memory_eligible,episode_policy.cloud_eligible,
                 episode_policy.policy_version,episode_policy.policy_revision_id,
                 episode_policy.decision_source,episode_policy.authorization_ref,
                 content_hash(suggestion_material)),
            )
            connection.execute(
                """UPDATE havre.sessions
                   SET closed_at=clock_timestamp(),closed_reason=%s,
                       closed_episode_id=%s,last_activity_at=clock_timestamp()
                   WHERE owner_id=%s AND session_id=%s AND closed_at IS NULL""",
                (boundary_reason,episode_id,self.owner_id,session_id),
            )
            return dict(connection.execute(
                """SELECT * FROM havre.conversation_episodes
                   WHERE owner_id=%s AND episode_id=%s""",
                (self.owner_id,episode_id),
            ).fetchone())

    def list_episodes(self, *, limit: int = 50) -> tuple[dict, ...]:
        with self.repository.pool.connection() as connection:
            rows = connection.execute(
                """
                SELECT episode.*,
                       COALESCE(jsonb_agg(jsonb_build_object(
                         'ordinal',member.ordinal,'event_id',member.event_id,
                         'event_type',member.event_type,
                         'event_content_hash',member.event_content_hash
                       ) ORDER BY member.ordinal),'[]'::jsonb) AS members
                FROM havre.conversation_episodes episode
                LEFT JOIN havre.conversation_episode_members member
                  ON member.owner_id=episode.owner_id AND member.episode_id=episode.episode_id
                WHERE episode.owner_id=%s
                GROUP BY episode.owner_id,episode.episode_id
                ORDER BY episode.ended_at DESC LIMIT %s
                """,
                (self.owner_id,limit),
            ).fetchall()
        return tuple(dict(row) for row in rows)

    def list_episode_suggestions(self, *, status: str = "pending") -> tuple[dict, ...]:
        with self.repository.pool.connection() as connection:
            rows = connection.execute(
                """SELECT suggestion.*,episode.session_id,episode.summary_text
                   FROM havre.episode_memory_suggestions suggestion
                   JOIN havre.conversation_episodes episode
                     ON episode.owner_id=suggestion.owner_id
                    AND episode.episode_id=suggestion.episode_id
                   WHERE suggestion.owner_id=%s AND suggestion.status=%s
                   ORDER BY suggestion.created_at DESC""",
                (self.owner_id,status),
            ).fetchall()
        return tuple(dict(row) for row in rows)

    def review_episode_suggestion(
        self, *, suggestion_id: UUID, decision: str, reason: str
    ) -> dict:
        if decision not in {"accepted","rejected"}:
            raise ValueError("episode suggestion decision must be accepted or rejected")
        with self.repository.pool.connection() as connection, connection.transaction():
            row = connection.execute(
                """UPDATE havre.episode_memory_suggestions
                   SET status=%s,review_reason=%s,reviewed_at=clock_timestamp()
                   WHERE owner_id=%s AND suggestion_id=%s AND status='pending'
                   RETURNING *""",
                (decision,reason,self.owner_id,suggestion_id),
            ).fetchone()
            if row is None:
                raise LookupError("pending episode suggestion not found")
        return dict(row)

    def review(
        self,
        *,
        feedback_id: UUID,
        feedback_revision: int,
        decision: FeedbackReviewDecision,
        issue_attributions: tuple[FeedbackIssueAttribution, ...],
        review_notes: str | None,
        authorization_ref: str | None,
    ) -> PersonalizationFeedbackReview:
        if decision is FeedbackReviewDecision.APPROVED_FOR_PERSONALIZATION_TRAINING:
            raise ValueError(
                "Stage 9B training authorization is not active; feedback remains in review"
            )
        with self.repository.pool.connection() as connection, connection.transaction():
            row = connection.execute(
                """
                SELECT rev.*, head.current_revision
                FROM havre.response_feedback_revisions AS rev
                JOIN havre.response_feedback_heads AS head
                  ON head.owner_id=rev.owner_id AND head.feedback_id=rev.feedback_id
                WHERE rev.owner_id=%s AND rev.feedback_id=%s AND rev.revision=%s
                FOR UPDATE OF rev
                """,
                (self.owner_id, feedback_id, feedback_revision),
            ).fetchone()
            if row is None:
                raise LookupError("feedback revision not found")
            if row["current_revision"] != feedback_revision:
                raise ValueError("only the current exact feedback revision may be reviewed")
            review = PersonalizationFeedbackReview(
                review_id=uuid7(), owner_id=self.owner_id,
                feedback_id=feedback_id, feedback_revision=feedback_revision,
                decision=decision, issue_attributions=issue_attributions,
                review_notes=review_notes, training_eligible=False,
                authorization_ref=authorization_ref,
            )
            connection.execute(
                """
                INSERT INTO havre.personalization_feedback_reviews (
                  owner_id, review_id, feedback_id, feedback_revision, decision,
                  issue_attributions, review_notes, training_eligible,
                  authorization_ref, content_hash, reviewed_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    self.owner_id, review.review_id, feedback_id, feedback_revision,
                    decision.value, [v.value for v in issue_attributions], review_notes,
                    False, authorization_ref, review.content_hash, review.reviewed_at,
                ),
            )
        return review

    def current_preference(self) -> CommunicationPreference | None:
        with self.repository.pool.connection() as connection:
            row = connection.execute(
                """SELECT * FROM havre.communication_preference_revisions
                   WHERE owner_id=%s ORDER BY revision DESC LIMIT 1""",
                (self.owner_id,),
            ).fetchone()
        return None if row is None else CommunicationPreference.model_validate(row)

    def set_preference(self, *, response_length: str, reason: str) -> CommunicationPreference:
        with self.repository.pool.connection() as connection, connection.transaction():
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (f"communication-preference:{self.owner_id}",),
            )
            row = connection.execute(
                """SELECT COALESCE(max(revision),0) AS revision
                   FROM havre.communication_preference_revisions
                   WHERE owner_id=%s""",
                (self.owner_id,),
            ).fetchone()
            item = CommunicationPreference(
                owner_id=self.owner_id, revision=row["revision"] + 1,
                response_length=response_length, reason=reason,
            )
            connection.execute(
                """INSERT INTO havre.communication_preference_revisions
                   (owner_id,revision,response_length,reason,content_hash,created_at)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (self.owner_id, item.revision, item.response_length, reason,
                 item.content_hash, item.created_at),
            )
        return item

    @staticmethod
    def _feedback(row, *, reviewed: bool) -> PersonalizationFeedback:
        return PersonalizationFeedback(
            feedback_id=row["feedback_id"], revision=row["revision"],
            owner_id=row["owner_id"], request_id=row["request_id"],
            session_id=row["session_id"], trace_id=row["trace_id"],
            user_event_id=row["user_event_id"], assistant_event_id=row["assistant_event_id"],
            context_pack_id=row["context_pack_id"], route_decision_id=row["route_decision_id"],
            inference_response_id=row["inference_response_id"], provider_id=row["provider_id"],
            model_version_id=row["model_version_id"], adapter_version_id=row["adapter_version_id"],
            tokenizer_version_id=row["tokenizer_version_id"],
            serving_config_version=row["serving_config_version"], rating=row["rating"],
            reason_codes=tuple(row["reason_codes"]), reason_text=row["reason_text"],
            owner_revision_text=row["owner_revision_text"], privacy_class=row["privacy_class"],
            status="reviewed" if reviewed else "saved", content_hash=row["content_hash"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _payload_text(payload) -> str:
        if not payload:
            return ""
        parts = payload.get("content_parts", [])
        return "\n".join(
            str(part.get("text", "")) for part in parts
            if isinstance(part, dict) and part.get("type") == "text"
        ).strip(" \t\n\r\f\v")

    @staticmethod
    def _episode_summary(user_text: list[str]) -> str:
        whitespace = " \t\n\r\f\v"
        user = " ".join(
            value.strip(whitespace)
            for value in user_text
            if value.strip(whitespace)
        )
        if len(user) > 900:
            user = user[:897].rstrip(whitespace) + "…"
        if not user:
            return (
                "Conversation retained as raw history; summary content was omitted "
                "because its effective policy was not Memory-eligible."
            )
        return f"In this conversation, the owner said: {user}"
