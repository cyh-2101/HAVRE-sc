"""Recheck revisable understanding before a delayed answer becomes visible."""
from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime
import re
from uuid import UUID

from companion.context.corrections import owner_fact_revision_refs


class StalePersonalContextError(ValueError):
    """The preserved source context no longer describes current understanding."""


def lock_current_state_scope(connection, owner_id: UUID) -> None:
    """Serialize immutable State publication with delayed-context delivery."""
    connection.execute(
        "SELECT pg_advisory_xact_lock(hashtext('havre-current-state-v1'),hashtext(%s))",
        (str(owner_id),),
    )


def source_context_is_current(repository, *, owner_id: UUID, context_pack_id: UUID,
                              as_of: datetime | None = None, connection=None,
                              lock_current: bool = False) -> bool:
    """Keep history immutable and reject delayed use of changed derivatives.

    Primary section identities distinguish admitted revisions from their older
    provenance ancestors. A corrected Memory may correctly cite an old revision.
    Delivery can retain shared head locks in its own transaction, serializing
    the final check with owner correction/retraction through the same head rows.
    """
    instant = as_of or datetime.now(UTC)
    with (nullcontext(connection) if connection is not None else repository.pool.connection()) as c:
        pack = c.execute("SELECT sections,created_at FROM havre.context_packs WHERE owner_id=%s AND context_pack_id=%s",
                         (owner_id, context_pack_id)).fetchone()
        if pack is None:
            return False
        memories, beliefs, states = set(), set(), set()
        events, admitted_owner_refs = set(), set()
        for section in pack["sections"]:
            # Manual Strong preserves the selected section under this known
            # wrapper. Normalize its name only; all exact source refs stay intact.
            section_id = re.sub(r"^(?:strong-)+", "", section["section_id"])
            memory = (re.fullmatch(r"memory-([0-9a-f-]{36})-([1-9][0-9]*)", section_id)
                      if section["section_type"] in {"episodic_memory", "semantic_memory"} else None)
            belief = (re.fullmatch(r"belief-([0-9a-f-]{36})-([1-9][0-9]*)", section_id)
                      if section["section_type"] == "user_belief" else None)
            state = (re.fullmatch(r"current-state-([0-9a-f-]{36})", section_id)
                     if section["section_type"] == "current_state" else None)
            retraction = (re.fullmatch(r"owner-fact-retraction-([0-9a-f-]{36})-([1-9][0-9]*)", section_id)
                          if section["section_type"] == "owner_fact_correction" else None)
            if memory:
                memories.add((UUID(memory[1]), int(memory[2]), "active"))
            elif belief:
                beliefs.add((UUID(belief[1]), int(belief[2])))
            elif state:
                states.add(UUID(state[1]))
            if retraction:
                memories.add((UUID(retraction[1]), int(retraction[2]), "retracted"))
            for ref in section.get("source_refs", ()):
                event_ref = re.fullmatch(r"event/([0-9a-f-]{36})", ref)
                if event_ref:
                    events.add(UUID(event_ref[1]))
                memory_ref = re.fullmatch(r"memory/([0-9a-f-]{36})(?:/revision/|@)([1-9][0-9]*)", ref)
                belief_ref = re.fullmatch(r"belief/([0-9a-f-]{36})@([1-9][0-9]*)", ref)
                state_ref = re.fullmatch(r"current-state/([0-9a-f-]{36})", ref)
                if memory_ref:
                    if section["section_type"] == "owner_fact_correction":
                        admitted_owner_refs.add(f"memory/{memory_ref[1]}/revision/{memory_ref[2]}")
                    # The current Memory's own correction lineage is historical
                    # provenance, not a second admitted stale understanding.
                    if memory and memory[1] == memory_ref[1] and memory[2] != memory_ref[2]:
                        continue
                    expected_status = ("retracted" if retraction
                        and retraction[1] == memory_ref[1] and retraction[2] == memory_ref[2]
                        else "active")
                    memories.add((UUID(memory_ref[1]), int(memory_ref[2]), expected_status))
                elif belief_ref:
                    if belief and belief[1] == belief_ref[1] and belief[2] != belief_ref[2]:
                        continue
                    beliefs.add((UUID(belief_ref[1]), int(belief_ref[2])))
                elif state_ref:
                    states.add(UUID(state_ref[1]))
        # Stable lock ordering prevents two shared-context deliveries from
        # taking overlapping derived heads in different orders.
        lock = " FOR SHARE OF head" if lock_current else ""
        validity_windows = []
        for memory_id, revision, expected_status in sorted(memories, key=lambda item: (str(item[0]), item[1], item[2])):
            row = c.execute("""SELECT head.current_revision,head.status,r.created_by,r.valid_from,r.valid_to
                FROM havre.memory_heads head JOIN havre.memory_revisions r
                  ON r.owner_id=head.owner_id AND r.memory_id=head.memory_id
                 AND r.revision=head.current_revision
                WHERE head.owner_id=%s AND head.memory_id=%s""" + lock,
                (owner_id, memory_id)).fetchone()
            if row is None or row["current_revision"] != revision or row["status"] != expected_status:
                return False
            if expected_status == "retracted":
                if row["created_by"] != "owner":
                    return False
            else:
                validity_windows.append((row["valid_from"], row["valid_to"]))
        for belief_id, revision in sorted(beliefs, key=lambda item: (str(item[0]), item[1])):
            row = c.execute("""SELECT head.current_revision,head.status,head.updated_at,r.valid_from,r.valid_to
                FROM havre.belief_heads head JOIN havre.user_belief_revisions r
                  ON r.owner_id=head.owner_id AND r.belief_id=head.belief_id
                 AND r.revision=head.current_revision
                WHERE head.owner_id=%s AND head.belief_id=%s""" + lock,
                (owner_id, belief_id)).fetchone()
            if (row is None or row["current_revision"] != revision or row["status"] != "active"
                or row["updated_at"] > pack["created_at"]):
                return False
            validity_windows.append((row["valid_from"], row["valid_to"]))
        if states:
            if lock_current:
                lock_current_state_scope(c, owner_id)
                if as_of is None:
                    instant = datetime.now(UTC)
            row = c.execute("""SELECT state_snapshot_id,expires_at FROM havre.current_state_snapshots
                WHERE owner_id=%s AND estimated_at<=%s AND created_at<=%s AND expires_at>%s
                ORDER BY estimated_at DESC,created_at DESC,state_snapshot_id DESC LIMIT 1""",
                (owner_id, instant, instant, instant)).fetchone()
            if row is None or states != {row["state_snapshot_id"]}:
                return False
            validity_windows.append((None, row["expires_at"]))
        # A competing publication or correction may have held a lock until
        # after this call began. Evaluate all time windows at the final instant,
        # never at a stale timestamp captured before the lock wait.
        check_at = datetime.now(UTC) if lock_current and as_of is None else instant
        # A raw-only pack has no Memory head ref to invalidate when its source
        # is reviewed later. Require any now-current owner repair of the exact
        # selected sources to have been disclosed in the preserved pack already.
        required_owner_refs = owner_fact_revision_refs(repository, owner_id=owner_id,
            as_of=check_at, event_ids=list(events),
            memory_ids=list({item[0] for item in memories}), connection=c)
        if not required_owner_refs.issubset(admitted_owner_refs):
            return False
        return all((start is None or start <= check_at)
                   and (end is None or end > check_at)
                   for start, end in validity_windows)
