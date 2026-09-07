"""Indexed, owner-qualified candidates from preserved cloud-authorized Events."""

from __future__ import annotations

from datetime import timedelta
import re

from companion.memory.lexical import tokens


VERSION = "personal-event-search-indexed-v1"
_QUERY_FILLER = re.compile(
    r"\b(?:remember|recall|previous|conversation|yesterday|today|what|that|the)\b|"
    r"还记得|记不记得|记得|之前|那次|那个人|那件事|昨天|昨晚|今天早上|凌晨|"
    r"对话|聊天|事情|说过|说的|你|我|吗", re.I,
)


def query_terms(query: str) -> tuple[str, ...]:
    # Strip reference grammar, not inferred people or relationships. Each term
    # still comes directly from the owner's query; no model invents an entity.
    meaningful = _QUERY_FILLER.sub(" ", query)
    filler = {"an", "as", "at", "be", "by", "do", "if", "in", "is", "it", "of", "on", "or", "so", "to", "we", "he", "me", "my"}
    return tuple(sorted(t for t in tokens(meaningful) if len(t) >= 2 and t not in filler))[:64]


def scoring_windows(text: str, query: str) -> tuple[tuple[int, int], ...]:
    """Bounded exact query-anchored spans for the pinned encoder.

    Scoring a complete long Event truncates away late experiences. These bounded
    slices are only search views; the original Event is never shortened in storage.
    Character limits do not guarantee that every span fits the encoder token limit.
    """
    if len(text) <= 200:
        return ((0, len(text)),)
    folded = text.casefold()
    starts = {0, max(0, len(text)-200)}
    for term in query_terms(query):
        position = folded.find(term)
        if position >= 0:
            starts.add(max(0, position-60))
    from companion.memory.lexical import overlap
    ranked = sorted(starts, key=lambda start: (-overlap(query,text[start:start+200]),start))
    chosen = []
    for start in ranked:
        if any(abs(start-other) < 100 for other in chosen):
            continue
        chosen.append(start)
        if len(chosen) == 4:
            break
    return tuple((start,min(len(text),start+200)) for start in chosen)


_ELIGIBLE_USER = """
  FROM havre.events e
  JOIN havre.interaction_requests i ON i.owner_id=e.owner_id AND i.request_id=e.request_id
  JOIN havre.route_decisions r ON r.owner_id=e.owner_id AND r.request_id=e.request_id
  WHERE e.owner_id=%s AND e.event_type='USER_MESSAGE'
    AND e.privacy_class IN ('PUBLIC','NORMAL') AND e.privacy_class=ANY(%s::text[])
    AND e.memory_eligible AND e.cloud_eligible
    AND r.execution_environment='cloud' AND r.selected_provider_id='openai-codex-chatgpt'
    AND i.status='completed' AND i.request_kind='interaction'
    AND e.recorded_at<%s
    AND NOT EXISTS (SELECT 1 FROM havre.offline_source_revocations x
      WHERE x.owner_id=e.owner_id AND x.source_event_id=e.event_id)
"""


_ELIGIBLE_USER_LOCAL = _ELIGIBLE_USER.replace(
    "AND e.privacy_class IN ('PUBLIC','NORMAL') AND e.privacy_class=ANY(%s::text[])",
    "AND e.privacy_class=ANY(%s::text[])",
).replace("AND e.memory_eligible AND e.cloud_eligible", "AND e.memory_eligible").replace(
    "AND r.execution_environment='cloud' AND r.selected_provider_id='openai-codex-chatgpt'", "",
)


def event_candidates(repository, *, owner_id, allowed_privacy, before, query, temporal_window=None, local_only=False):
    """Union indexed lifetime lexical matches with a small recent semantic pool.

    The lifetime branch has no seven-day or most-recent-256 cutoff. Semantic-only
    paraphrases without any surviving lexical anchor still use the recent pool;
    this is a documented recall limit, not an inferred autobiographical graph.
    """
    eligible = _ELIGIBLE_USER_LOCAL if local_only else _ELIGIBLE_USER
    base = (owner_id, allowed_privacy, before)
    terms = query_terms(query)
    with repository.pool.connection() as connection:
        if temporal_window is not None:
            start, end = temporal_window
            bounds = " AND e.recorded_at>=%s AND e.recorded_at<%s"
            first = connection.execute(
                "SELECT e.*" + eligible + bounds + " ORDER BY e.recorded_at,e.event_id LIMIT 64",
                (*base, start, end),
            ).fetchall()
            last = connection.execute(
                "SELECT e.*" + eligible + bounds + " ORDER BY e.recorded_at DESC,e.event_id DESC LIMIT 64",
                (*base, start, end),
            ).fetchall()
            return list({r["event_id"]: r for r in (*first, *last)}.values())
        matched = []
        if terms:
            matched = connection.execute(
                "SELECT e.*" + eligible +
                """ AND havre.event_context_search_terms(e.payload) && %s::text[]
                ORDER BY cardinality(ARRAY(
                  SELECT unnest(havre.event_context_search_terms(e.payload))
                  INTERSECT SELECT unnest(%s::text[])
                )) DESC,e.recorded_at DESC,e.event_id DESC LIMIT 96""",
                (*base, list(terms), list(terms)),
            ).fetchall()
        recent = connection.execute(
            "SELECT e.*" + eligible + " ORDER BY e.recorded_at DESC,e.event_id DESC LIMIT 64",
            base,
        ).fetchall()
    return list({r["event_id"]: r for r in (*matched, *recent)}.values())


def source_neighborhood(repository, *, owner_id, allowed_privacy, before, anchors, local_only=False):
    """Expand selected exact owner turns to pairs and nearby clarifications."""
    rows = {}
    eligible = _ELIGIBLE_USER_LOCAL if local_only else _ELIGIBLE_USER
    with repository.pool.connection() as connection:
        for anchor in anchors:
            following = connection.execute(
                "SELECT e.request_id" + eligible +
                " AND e.recorded_at>=%s AND e.recorded_at<=%s ORDER BY e.recorded_at,e.event_id LIMIT 3",
                (owner_id, allowed_privacy, before, anchor["recorded_at"],
                 anchor["recorded_at"] + timedelta(minutes=30)),
            ).fetchall()
            request_ids = [row["request_id"] for row in following]
            if not request_ids:
                continue
            source_policy = "e.privacy_class=ANY(%s::text[])" if local_only else "e.privacy_class IN ('PUBLIC','NORMAL') AND e.privacy_class=ANY(%s::text[]) AND e.cloud_eligible"
            route_policy = "" if local_only else "AND r.execution_environment='cloud' AND r.selected_provider_id='openai-codex-chatgpt'"
            pair_rows = connection.execute(
                f"""SELECT e.* FROM havre.events e
                JOIN havre.interaction_requests i ON i.owner_id=e.owner_id AND i.request_id=e.request_id
                JOIN havre.route_decisions r ON r.owner_id=e.owner_id AND r.request_id=e.request_id
                WHERE e.owner_id=%s AND e.request_id=ANY(%s::uuid[])
                  AND e.event_type IN ('USER_MESSAGE','ASSISTANT_MESSAGE')
                  AND {source_policy}
                  AND (e.event_type='ASSISTANT_MESSAGE' OR e.memory_eligible)
                  {route_policy}
                  AND i.status='completed' AND i.request_kind='interaction' AND e.recorded_at<%s
                  AND NOT EXISTS (SELECT 1 FROM havre.offline_source_revocations x
                    WHERE x.owner_id=e.owner_id AND x.source_event_id=e.event_id)
                ORDER BY e.recorded_at,e.event_id""",
                (owner_id, request_ids, allowed_privacy, before),
            ).fetchall()
            # A revoked/missing user source cannot leave an orphaned assistant
            # interpretation in recalled evidence.
            owner_requests = {r["request_id"] for r in pair_rows if r["event_type"] == "USER_MESSAGE"}
            rows.update({r["event_id"]: r for r in pair_rows if r["request_id"] in owner_requests})
    return sorted(rows.values(), key=lambda r: (r["recorded_at"], str(r["event_id"])))
