"""Governed, owner-triggered Strong Brain reruns over one selected ContextPack."""

from __future__ import annotations

from datetime import UTC, datetime
import re
from uuid import UUID, uuid5

from companion.application import InteractionCommand, InteractionService, ManualStrongContext
from companion.context import ConversationHistoryItem, PersonalContextItem
from companion.events import AssistantMessagePayload, EventType, UserMessagePayload
from companion.hashing import content_hash
from companion.policy import DataPolicy, PrivacyClass
from mlsys.serving.deepseek_cloud import (
    OWNER_MANUAL_AUTHORIZATION_REF,
    OWNER_MANUAL_BOUNDARY,
)


_ACTION = "请用 Strong Brain 重新想想上一条回复。"
MANUAL_STRONG_RESERVED_OUTPUT_TOKENS = 4_096
_PERSONAL_TYPES = {
    "episodic_memory",
    "semantic_memory",
    "pattern_memory",
    "progress_memory",
    "user_belief",
    "goal",
    "current_state",
    "communication_preference",
    "owner_response_instruction",
    "owner_wording_correction",
    "owner_fact_correction",
    "calendar_availability",
}


def assert_manual_context_current(repository, *, owner_id, source_assistant_event_id) -> None:
    """Reject an obsolete selected snapshot without widening its disclosure."""
    from companion.context.corrections import owner_fact_revision_refs
    from companion.context.freshness import StalePersonalContextError, source_context_is_current

    assistant = repository.event_by_id(owner_id=owner_id, event_id=source_assistant_event_id)
    if assistant is None or assistant.event_type is not EventType.ASSISTANT_MESSAGE:
        raise LookupError("Strong Brain source assistant message was not found")
    evidence = repository.evidence(assistant.request_id, owner_id=owner_id)
    pack = evidence.get("context_pack") if evidence else None
    stale = StalePersonalContextError(
        "manual Strong source context is no longer current; create a new reviewed reply before preparing a new disclosure"
    )
    if pack is None or not source_context_is_current(repository, owner_id=owner_id,
                                                    context_pack_id=pack["context_pack_id"]):
        raise stale
    event_ids = {assistant.event_id, assistant.causation_event_id} - {None}
    memory_ids = set()
    admitted_owner_refs = set()
    for section in pack["sections"]:
        for ref in section["source_refs"]:
            event = re.fullmatch(r"event/([0-9a-f-]{36})", ref)
            memory = re.fullmatch(r"memory/([0-9a-f-]{36})(?:/revision/|@)([1-9][0-9]*)", ref)
            if event:
                event_ids.add(UUID(event[1]))
            if memory:
                memory_ids.add(UUID(memory[1]))
                if section["section_type"] == "owner_fact_correction":
                    admitted_owner_refs.add(f"memory/{memory[1]}/revision/{memory[2]}")
    with repository.pool.connection() as connection:
        revoked = connection.execute(
            "SELECT EXISTS(SELECT 1 FROM havre.offline_source_revocations "
            "WHERE owner_id=%s AND source_event_id=ANY(%s::uuid[])) AS present",
            (owner_id, list(event_ids)),
        ).fetchone()["present"]
    required_refs = owner_fact_revision_refs(repository, owner_id=owner_id,
        as_of=datetime.now(UTC), event_ids=list(event_ids), memory_ids=list(memory_ids))
    if revoked or not required_refs.issubset(admitted_owner_refs):
        raise stale


class ManualStrongBrainService:
    """Prepare, bind, execute, and close one exact manual cloud disclosure."""

    def __init__(
        self,
        *,
        owner_id: UUID,
        repository,
        interaction_service: InteractionService,
    ) -> None:
        if not interaction_service.manual_strong_only:
            raise ValueError("Strong Brain requires a dedicated strict interaction service")
        self.owner_id = owner_id
        self.repository = repository
        self.interaction_service = interaction_service

    def _existing(self, disclosure_id: UUID) -> dict[str, object] | None:
        return next(
            (
                row
                for row in self.repository.list_manual_cloud_disclosures(
                    owner_id=self.owner_id, limit=200
                )
                if row["disclosure_id"] == disclosure_id
            ),
            None,
        )

    def prepare(
        self, *, source_assistant_event_id: UUID, idempotency_key: str
    ) -> ManualStrongContext:
        assistant = self.repository.event_by_id(
            owner_id=self.owner_id, event_id=source_assistant_event_id
        )
        if (
            assistant is None
            or assistant.event_type is not EventType.ASSISTANT_MESSAGE
            or not isinstance(assistant.payload, AssistantMessagePayload)
            or assistant.causation_event_id is None
        ):
            raise LookupError("Strong Brain source assistant message was not found")
        source_user = self.repository.event_by_id(
            owner_id=self.owner_id, event_id=assistant.causation_event_id
        )
        if (
            source_user is None
            or source_user.event_type is not EventType.USER_MESSAGE
            or not isinstance(source_user.payload, UserMessagePayload)
        ):
            raise ValueError("Strong Brain source lacks its canonical user message")
        evidence = self.repository.evidence(
            assistant.request_id, owner_id=self.owner_id
        )
        if evidence is None or evidence.get("context_pack") is None:
            raise LookupError("Strong Brain source ContextPack was not found")

        assert_manual_context_current(self.repository, owner_id=self.owner_id,
                                      source_assistant_event_id=source_assistant_event_id)
        disclosure_id = uuid5(
            self.owner_id,
            f"manual-strong:{source_assistant_event_id}:{idempotency_key}",
        )
        policy = DataPolicy(
            policy_revision_id=uuid5(disclosure_id, "selected-context-policy"),
            privacy_class=PrivacyClass.HIGHLY_PRIVATE,
            memory_eligible=False,
            training_eligible=False,
            cloud_eligible=True,
            decision_source="owner_explicit",
            authorization_ref=OWNER_MANUAL_AUTHORIZATION_REF,
        )

        personal: list[PersonalContextItem] = []
        for section in evidence["context_pack"]["sections"]:
            section_type = section["section_type"]
            if section_type not in _PERSONAL_TYPES:
                continue
            value = "\n".join(part["text"] for part in section["content_parts"])
            personal.append(
                PersonalContextItem(
                    owner_id=self.owner_id,
                    section_id=f"strong-{section['section_id']}",
                    section_type=section_type,
                    content_text=value,
                    priority=max(1, min(99, int(section["priority"]))),
                    source_refs=tuple(section["source_refs"]),
                    data_policy=policy,
                )
            )

        history_events = [source_user, assistant]
        selected_history_text = {}
        for section in evidence["context_pack"]["sections"]:
            if section["section_type"] not in {
                "conversation_user_message", "conversation_assistant_message"
            }:
                continue
            event_ref = next(
                (ref for ref in section["source_refs"] if ref.startswith("event/")),
                None,
            )
            if event_ref is None:
                continue
            event = self.repository.event_by_id(
                owner_id=self.owner_id, event_id=UUID(event_ref.removeprefix("event/"))
            )
            if event is not None:
                history_events.append(event)
                # The selected pack may contain only an exact excerpt. Event
                # identity supplies metadata, never permission to hydrate the
                # omitted text into this narrowly authorized disclosure.
                selected_history_text[event.event_id] = "\n".join(
                    part["text"] for part in section["content_parts"]
                )
        unique = {event.event_id: event for event in history_events}
        ordered = sorted(unique.values(), key=lambda event: (event.recorded_at, event.event_id))
        history: list[ConversationHistoryItem] = []
        for event in ordered:
            if isinstance(event.payload, UserMessagePayload):
                role = "user"
            elif isinstance(event.payload, AssistantMessagePayload):
                role = "assistant"
            else:
                continue
            history.append(
                ConversationHistoryItem(
                    owner_id=self.owner_id,
                    session_id=event.session_id,
                    event_id=event.event_id,
                    request_id=event.request_id,
                    role=role,
                    content_text=(selected_history_text[event.event_id]
                        if event.event_id in selected_history_text else "\n".join(
                            part.text for part in event.payload.content_parts
                        )),
                    recorded_at=event.recorded_at,
                    data_policy=policy,
                )
            )

        selected_material = {
            "schema_version": 1,
            "personal_context": [item.model_dump(mode="json") for item in personal],
            "conversation_history": [item.model_dump(mode="json") for item in history],
        }
        selected_hash = content_hash(selected_material)
        context = ManualStrongContext(
            disclosure_id=disclosure_id,
            source_assistant_event_id=source_assistant_event_id,
            data_policy=policy,
            personal_context=tuple(personal),
            conversation_history=tuple(history),
            selected_content_hash=selected_hash,
        )
        self.repository.prepare_manual_cloud_disclosure(
            owner_id=self.owner_id,
            disclosure_id=disclosure_id,
            source_assistant_event_id=source_assistant_event_id,
            policy_revision_id=policy.policy_revision_id,
            selected_source_refs=tuple(
                ref
                for item in (*context.personal_context, *context.conversation_history)
                for ref in item.source_refs
            ),
            selected_content_hash=selected_hash,
            authorization_ref=OWNER_MANUAL_AUTHORIZATION_REF,
            data_boundary=OWNER_MANUAL_BOUNDARY,
        )
        return context

    async def rethink(
        self, *, source_assistant_event_id: UUID, idempotency_key: str
    ) -> dict[str, object]:
        disclosure_id = uuid5(
            self.owner_id,
            f"manual-strong:{source_assistant_event_id}:{idempotency_key}",
        )
        existing = self._existing(disclosure_id)
        if existing is not None:
            if existing["status"] == "sent":
                return {
                    "status": "sent",
                    "disclosure_id": disclosure_id,
                    "assistant_event_id": existing["result_assistant_event_id"],
                    "idempotent_replay": True,
                }
            if existing["status"] != "prepared":
                raise ValueError(
                    f"Strong Brain disclosure is already {existing['status']}"
                )
        context = self.prepare(
            source_assistant_event_id=source_assistant_event_id,
            idempotency_key=idempotency_key,
        )
        source = self.repository.event_by_id(
            owner_id=self.owner_id, event_id=source_assistant_event_id
        )
        assert source is not None
        try:
            result = await self.interaction_service.interact(
                InteractionCommand(
                    message=_ACTION,
                    privacy_class=PrivacyClass.HIGHLY_PRIVATE,
                    memory_eligible=False,
                    session_id=source.session_id,
                    channel="web",
                    idempotency_key=f"strong:{idempotency_key}",
                ),
                manual_strong_context=context,
            )
        except BaseException as error:
            row = self._existing(context.disclosure_id)
            if row is not None and row["status"] == "prepared":
                self.repository.revoke_manual_cloud_disclosure(
                    owner_id=self.owner_id, disclosure_id=context.disclosure_id
                )
            elif row is not None and row["status"] == "bound":
                self.repository.finish_manual_cloud_disclosure(
                    owner_id=self.owner_id,
                    disclosure_id=context.disclosure_id,
                    error_code=type(error).__name__[:200],
                )
            raise
        row = self._existing(context.disclosure_id)
        if row is not None and row["status"] == "bound":
            self.repository.finish_manual_cloud_disclosure(
                owner_id=self.owner_id,
                disclosure_id=context.disclosure_id,
                result_assistant_event_id=result.assistant_event_id,
            )
        return {
            "status": "sent",
            "disclosure_id": context.disclosure_id,
            "assistant_event_id": result.assistant_event_id,
            "provider_id": result.provider_id,
            "model_version_id": result.model_version_id,
            "idempotent_replay": result.idempotent_replay,
        }
