"""Source-bound continuation of one delivered reply, never a replayed action."""
from uuid import UUID
from companion.context.models import ConversationHistoryItem, PersonalContextItem
from companion.context.response_plan import _SAY_MORE
from companion.events import EventType
from companion.policy import combine_policies


CONTINUATION_GUIDANCE = ("The owner requests continuation of the bound delivered reply, not a new answer to the original task. "
            "For a continuation_button event this was a tap, not a spoken or typed message. "
            "Read what HAVRE has already said, including earlier continuations. Add one or two message-sized paragraphs: "
            "a concrete next step if a problem needs solving, or a fresh observation or genuinely interesting detail to ask about. "
            "If a question is already unanswered, leave room for its answer instead of asking it again or piling on questions. "
            "Start with the new contribution; no recap, synonym rewrite, renewed greeting, or announcement of continuing. "
            "Do not save or schedule anything again. Never invent what happened next. "
            "If nothing worthwhile remains, a brief natural ending is enough.")

CONTINUATION_INPUT_TEXT = "[The owner tapped Continue on the preceding reply; no new message was entered.]"

def continuation_parent_for(repository, *, owner_id: UUID, session_id: UUID,
                            message: str, reply_to_event_id: UUID | None):
    if not _SAY_MORE.fullmatch(message):
        if reply_to_event_id is not None:
            raise ValueError("reply_to_event_id is supported only for an explicit continuation")
        return None
    if reply_to_event_id is None:
        with repository.pool.connection() as connection:
            row = connection.execute(
                "SELECT event_id,event_type FROM havre.events WHERE owner_id=%s AND session_id=%s "
                "AND event_type IN ('USER_MESSAGE','ASSISTANT_MESSAGE') ORDER BY recorded_at DESC,event_id DESC LIMIT 1",
                (owner_id, session_id),
            ).fetchone()
        if row is None or row["event_type"] != "ASSISTANT_MESSAGE":
            return None
        reply_to_event_id = row["event_id"]
    parent = repository.event_by_id(owner_id=owner_id, event_id=reply_to_event_id)
    if parent is None or parent.event_type != EventType.ASSISTANT_MESSAGE or parent.session_id != session_id:
        raise ValueError("continuation reply is unavailable in this conversation")
    with repository.pool.connection() as connection:
        delivered = connection.execute(
            "SELECT 1 FROM havre.interaction_requests WHERE owner_id=%s AND request_id=%s "
            "AND status='completed' AND request_kind='interaction'",
            (owner_id, parent.request_id),
        ).fetchone()
    if delivered is None:
        raise ValueError("continuation requires a completed reply")
    return parent


def continuation_context(repository, *, parent, current):
    with repository.pool.connection() as connection:
        row = connection.execute(
            "SELECT event_id FROM havre.events WHERE owner_id=%s AND request_id=%s AND event_type='USER_MESSAGE'",
            (parent.owner_id, parent.request_id),
        ).fetchone()
    source = repository.event_by_id(owner_id=parent.owner_id, event_id=row["event_id"]) if row else None
    if source is None:
        raise ValueError("continuation source was removed")
    with repository.pool.connection() as connection:
        revoked = connection.execute(
            "SELECT 1 FROM havre.offline_source_revocations WHERE owner_id=%s "
            "AND source_event_id=ANY(%s::uuid[])",
            (parent.owner_id, [source.event_id, parent.event_id]),
        ).fetchone()
    if revoked:
        raise ValueError("continuation source was revoked")
    history = tuple(ConversationHistoryItem(
        owner_id=e.owner_id,session_id=e.session_id,event_id=e.event_id,request_id=e.request_id,
        role="assistant" if e.event_type == EventType.ASSISTANT_MESSAGE else "user",
        content_text=(CONTINUATION_INPUT_TEXT if getattr(e.payload, "input_origin", None) == "continuation_button"
                      else "\n".join(part.text for part in e.payload.content_parts)),
        recorded_at=e.recorded_at,data_policy=e.data_policy,
        selector_version="explicit-reply-continuation-v1",
    ) for e in (source,parent))
    instruction = PersonalContextItem(
        owner_id=current.owner_id,section_id=f"reply-continuation-{parent.event_id}",
        section_type="owner_response_instruction", priority=99,
        content_text=CONTINUATION_GUIDANCE,
        source_refs=(f"event/{current.event_id}",f"event/{parent.event_id}",f"event/{source.event_id}"),
        data_policy=combine_policies((source.data_policy,parent.data_policy,current.data_policy)),
    )
    return history,instruction
