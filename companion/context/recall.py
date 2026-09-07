"""Source-only lifetime recall within the current local/cloud policy boundary."""

from __future__ import annotations

from datetime import datetime, time, timedelta
import re
from zoneinfo import ZoneInfo

from companion.context.models import ConversationHistoryItem
from companion.memory.lexical import overlap
from companion.context.event_search import VERSION as SEARCH_VERSION, event_candidates, source_neighborhood, scoring_windows
from companion.context.source_resolution import (
    VERSION as RESOLUTION_VERSION, reference_query, resolve_sources, suppresses_callback, targeted_reference,
)
from companion.policy import PrivacyClass
from companion.policy.models import PRIVACY_RESTRICTION_ORDER

VERSION = "conversation-recall-indexed-lifetime-v3"


def recalled_history(repository, *, owner_id, query: str, current_event,
                     recent, explicit: bool, timezone_name: str):
    encoder = getattr(repository, "memory_encoder", None)
    lookup_query = reference_query(query, recent, current_event)
    if (encoder is None or suppresses_callback(query)
            or not (explicit or targeted_reference(query) or lookup_query != query)):
        return recent
    local_only = not current_event.data_policy.cloud_eligible or current_event.data_policy.privacy_class not in (PrivacyClass.PUBLIC, PrivacyClass.NORMAL)
    eligible_classes = tuple(PrivacyClass) if local_only else (PrivacyClass.PUBLIC, PrivacyClass.NORMAL)
    allowed = [p.value for p in eligible_classes
               if PRIVACY_RESTRICTION_ORDER[p]
               <= PRIVACY_RESTRICTION_ORDER[current_event.data_policy.privacy_class]]
    zone = ZoneInfo(timezone_name)
    today = current_event.recorded_at.astimezone(zone).date()
    temporal = any(word in query for word in ("凌晨", "昨晚", "昨天", "今天早上"))
    temporal_window = None
    if temporal:
        day = today - timedelta(days=1) if ("昨天" in query or "昨晚" in query) else today
        start_hour = 18 if "昨晚" in query else 6 if "今天早上" in query else 0
        end_hour = 6 if "凌晨" in query else 12 if "今天早上" in query else 24
        start = datetime.combine(day, time(start_hour), tzinfo=zone)
        end = datetime.combine(day + timedelta(days=1), time(0), tzinfo=zone) if end_hour == 24 else datetime.combine(day, time(end_hour), tzinfo=zone)
        temporal_window = (start, end)
    rows = event_candidates(repository, owner_id=owner_id, allowed_privacy=allowed,
                            before=current_event.recorded_at, query=lookup_query,
                            temporal_window=temporal_window, local_only=local_only)
    rows.sort(key=lambda r: (r["recorded_at"], str(r["event_id"])))

    def history_item(row):
        policy = repository._policy_from_row(row)
        if policy.privacy_class.value not in allowed:
            raise ValueError("recall source exceeds request privacy ceiling")
        if not local_only and (not policy.cloud_eligible or policy.privacy_class not in (PrivacyClass.PUBLIC, PrivacyClass.NORMAL)):
            raise ValueError("cloud recall source failed independent privacy check")
        text = "\n".join(p.get("text", "") for p in row["payload"].get("content_parts", ())
                         if p.get("type", "text") == "text").strip()
        if not text:
            return None
        return ConversationHistoryItem(
            owner_id=owner_id, session_id=row["session_id"], event_id=row["event_id"],
            request_id=row["request_id"], role="user" if row["event_type"] == "USER_MESSAGE" else "assistant",
            content_text=text, recorded_at=row["recorded_at"], data_policy=policy,
        )
    turns = [item for row in rows if (item := history_item(row)) is not None]
    resolution = resolve_sources(lookup_query, turns, explicit=explicit or lookup_query != query)
    if resolution.anchors:
        # Focus the same policy-qualified index on an exact owner-declared name.
        # The general semantic threshold and all route boundaries stay unchanged.
        focused = event_candidates(repository, owner_id=owner_id, allowed_privacy=allowed,
            before=current_event.recorded_at, query=" ".join(resolution.anchors), local_only=local_only)
        rows = sorted({r["event_id"]: r for r in (*rows, *focused)}.values(),
                      key=lambda r: (r["recorded_at"], str(r["event_id"])))
        turns = [item for row in rows if (item := history_item(row)) is not None]
        resolution = resolve_sources(lookup_query, turns, explicit=True)
        if not resolution.event_ids:
            # Never choose the top-scoring name to manufacture uniqueness.
            return recent
    elif not explicit:
        # A name-like follow-up does not open general low-relevance retrieval.
        return recent
    anchors = [(i, t) for i, t in enumerate(turns)
               if t.role == "user"]
    if not anchors:
        return recent
    windows = [(index, turn, start, end) for index, turn in anchors
               for start, end in scoring_windows(turn.content_text, query)]
    vectors = (() if resolution.event_ids else
               encoder.embed_many([query, *(turn.content_text[start:end] for _,turn,start,end in windows)]))
    ranked_by_index = {}
    best_spans = {}
    for (index, turn, start, end), vector in zip(windows if vectors else (), vectors[1:], strict=True):
        semantic = sum(a * b for a, b in zip(vectors[0], vector, strict=True))
        lexical = overlap(query, turn.content_text[start:end])
        if temporal or semantic >= 0.45 or (semantic >= 0.20 and lexical >= 0.25):
            score = 0.85 * semantic + 0.15 * lexical
            if score > ranked_by_index.get(index, float("-inf")):
                ranked_by_index[index] = score
                best_spans[turn.event_id] = (start, end)
    ranked = [(score,index) for index,score in ranked_by_index.items()]
    topic_query = re.sub(r"你|我|还|记得|凌晨|昨天|今天|早上|昨晚|和|说的|事情|的|吗|那段|对话|聊天|[\s？?]", "", query)
    if resolution.event_ids:
        selected = [i for i, turn in anchors if turn.event_id in resolution.event_ids]
        for i in selected:
            turn = turns[i]
            best_spans[turn.event_id] = scoring_windows(turn.content_text, lookup_query)[0]
    elif temporal and len(topic_query) < 3:
        substantive = [(i, t) for i, t in anchors if len(t.content_text) >= 20]
        # A broad temporal reference needs the opening as well as the emotional
        # high point and ending, not just the two longest messages.
        selected = [anchors[0][0]]
        selected += [i for i, _ in sorted(substantive, key=lambda x: -len(x[1].content_text))[:1]]
        selected += [i for i, _ in anchors[-2:]]
    else:
        selected = [i for _, i in sorted(ranked, reverse=True)[:2]]
    selected_ids = {turns[i].event_id for i in selected}
    neighborhoods = source_neighborhood(repository, owner_id=owner_id, allowed_privacy=allowed,
        before=current_event.recorded_at, anchors=[r for r in rows if r["event_id"] in selected_ids], local_only=local_only)
    if resolution.event_ids:
        # A name lookup needs exact source pairs, not every later topic in the
        # old thirty-minute neighborhood. Keep an immediately following explicit
        # correction, but do not import a different project/person by proximity.
        user_rows = [r for r in neighborhoods if r["event_type"] == "USER_MESSAGE"]
        requests = {r["request_id"] for r in user_rows if r["event_id"] in selected_ids}
        for index, row in enumerate(user_rows[:-1]):
            following = user_rows[index+1]
            item = history_item(following)
            if (row["event_id"] in selected_ids and following["session_id"] == row["session_id"]
                    and item is not None and re.match(r"(?:更正|纠正|刚才.{0,8}说错|撤回刚才)", item.content_text)):
                requests.add(following["request_id"])
        neighborhoods = [r for r in neighborhoods if r["request_id"] in requests]
    recalled = [item for row in neighborhoods if (item := history_item(row)) is not None]
    bounded = []
    for item in recalled:
        if len(item.content_text) > 1200:
            center = best_spans.get(item.event_id, (0,200))[0]
            start = max(0, center-100)
            end = min(len(item.content_text), start+600)
            text = (f"[Exact excerpt from preserved Event, characters {start}:{end} of {len(item.content_text)}; "
                    "omitted text is not visible here.]\n" + item.content_text[start:end])
            item = item.model_copy(update={"content_text": text})
        selector = (f"{RESOLUTION_VERSION}/{resolution.status}" if resolution.event_ids
                    else "query-anchor-window-v1")
        bounded.append(item.model_copy(update={"selector_version": f"{SEARCH_VERSION}/{VERSION}/{selector}"}))
    recalled = bounded
    merged = {t.event_id: t for t in (*recent, *recalled)}
    return tuple(sorted(merged.values(), key=lambda t: (t.recorded_at, str(t.event_id))))
