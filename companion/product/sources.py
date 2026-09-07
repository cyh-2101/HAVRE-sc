"""Owner-local, exact-revision source previews for the Memory product surface.

This reads the canonical provenance graph; it creates no copy, summary, inferred
relationship or permission to send the sources to a model.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb


def source_previews(
    repository: Any, *, owner_id: UUID,
    subjects: tuple[tuple[str, UUID, int | None], ...],
) -> dict[tuple[str, UUID, int | None], tuple[dict[str, Any], ...]]:
    """Follow exact source revisions, including corrections and belief support.

    UNION deduplicates graph nodes and terminates even if historical data contains
    a cycle. Every edge and terminal Event is independently owner-qualified.
    Retractions do not erase raw Events, but an authorized source revocation makes
    that source unavailable here as well as in retrieval.
    """
    if not subjects:
        return {}
    roots = []
    for kind, identifier, revision in dict.fromkeys(subjects):
        if kind not in {'event', 'memory_revision', 'belief_revision'}:
            raise ValueError('unsupported source preview kind')
        if (kind == 'event') != (revision is None):
            raise ValueError('source previews require an exact derived revision')
        roots.append({'kind': kind, 'id': str(identifier), 'revision': revision})
    with repository.pool.connection() as connection:
        rows = connection.execute(
            """WITH RECURSIVE roots AS (
                 SELECT * FROM jsonb_to_recordset(%s::jsonb)
                   AS value(kind text,id uuid,revision integer)
               ), lineage(root_kind,root_id,root_revision,kind,id,revision) AS (
                 SELECT kind,id,revision,kind,id,revision FROM roots
                 UNION
                 SELECT l.root_kind,l.root_id,l.root_revision,
                        edge.source_kind,edge.source_id,edge.source_revision
                 FROM lineage l JOIN havre.provenance_edges edge
                   ON edge.owner_id=%s AND edge.derived_kind=l.kind
                  AND edge.derived_id=l.id
                  AND edge.derived_revision IS NOT DISTINCT FROM l.revision
               )
               SELECT l.root_kind,l.root_id,l.root_revision,e.event_id,
                      e.event_type,e.recorded_at,e.payload
               FROM lineage l JOIN havre.events e
                 ON l.kind='event' AND e.owner_id=%s AND e.event_id=l.id
               WHERE NOT EXISTS (
                 SELECT 1 FROM havre.offline_source_revocations revoked
                 WHERE revoked.owner_id=e.owner_id
                   AND revoked.source_event_id=e.event_id)
               ORDER BY l.root_kind,l.root_id,l.root_revision,
                        e.recorded_at,e.event_id""",
            (Jsonb(roots), owner_id, owner_id),
        ).fetchall()
    grouped: dict[tuple[str, UUID, int | None], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        parts = row['payload'].get('content_parts', ())
        content = '\n'.join(
            part['text'] for part in parts
            if isinstance(part, dict) and isinstance(part.get('text'), str)
        )
        if not content:
            continue
        grouped[(row['root_kind'], row['root_id'], row['root_revision'])].append({
            'source_ref': f"event/{row['event_id']}",
            'event_type': row['event_type'],
            'recorded_at': row['recorded_at'],
            'content': content,
        })
    return {key: tuple(values) for key, values in grouped.items()}
