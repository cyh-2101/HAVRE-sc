"""Bounded exact-source resolution, without an inferred entity registry.

Names must occur in an explicit owner naming statement and in the current
reference. Similarity alone never establishes that two people are the same.
The result describes eligible source alternatives, not exhaustive world knowledge.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import re
from typing import Literal
from uuid import UUID

from companion.memory.lexical import tokens

VERSION = "targeted-source-resolution-v1"
MAX_SOURCES = 6
_NAME = r"(?:[\u3400-\u9fff]{2,8}|[A-Za-z][A-Za-z0-9_-]{1,24}(?: [A-Z][a-z]{1,20})?)"
_NAMING = (
    re.compile(r"(?:叫做|名叫|名为|名字是|名称是|叫)[‘“\"「]?\s*(?P<name>" + _NAME + r")[’”\"」]?(?=[，,。.;；！!?？\n]|$)"),
    re.compile(r"(?:^|[。！？!?\n])\s*[‘“\"「]?(?P<name>" + _NAME + r")[’”\"」]?(?=是我(?:的|以前的|之前的))"),
    re.compile(r"\b(?:named|called)\s+[\"']?(?P<name>[A-Z][A-Za-z0-9_-]{1,24}(?: [A-Z][a-z]{1,20})?)[\"']?(?=[,.;!?\n]|$)"),
)
_REFERENCE = re.compile(
    r"又.{0,10}(?:找我|联系|发消息|来信)|(?:下一步|接下来).{0,16}(?:来着|之前|原来)|"
    r"(?:remember|recall|contacted me again|messaged me again|what was.{0,20}next)", re.I)
_NO_CALLBACK = re.compile(r"(?:不要|不用|别|先别).{0,10}(?:回忆|提历史|提以前|翻旧|联系以前)|"
                          r"(?:do not|don't|no need to).{0,15}(?:recall|bring up|remember)", re.I)
_NOT_ASSERTED = re.compile(r"假设|假如|例如|比如|虚构|如果|(?:for example|hypothetical|fictional|suppose|if )", re.I)
_NEGATED = re.compile(r"不是|不叫|并非|不确定|可能|也许|\b(?:not|isn't|maybe|perhaps)\b", re.I)
_FILLER = re.compile(
    r"你觉得|你认为|还记得|记不记得|记得|下一步|接下来|该做什么|做什么|是什么|怎么回|怎么说|"
    r"应该|来着|之前|原来|那个|这个|我的|我|你|又|今天|昨天|刚刚|最近|找我|联系|发消息|"
    r"项目|事情|同一个|的|了|吗|\b(?:my|the|a|an|what|was|is|next|step|project|"
    r"remember|recall|again|contacted|messaged|me|how|should|reply|to)\b", re.I)


@dataclass(frozen=True)
class SourceResolution:
    status: Literal["not_requested", "unknown", "resolved", "ambiguous"]
    anchors: tuple[str, ...] = ()
    event_ids: tuple[UUID, ...] = ()
    # A resolved source is not a claim of global entity uniqueness.
    reason: str = "no_supported_naming_anchor"


def targeted_reference(query: str) -> bool:
    return bool(_REFERENCE.search(query)) and not suppresses_callback(query)


def suppresses_callback(query: str) -> bool:
    return bool(_NO_CALLBACK.search(query))


def reference_query(query: str, recent, current_event) -> str:
    """Borrow only an immediate same-session owner turn for a short clarification."""
    if len(query) > 60 or suppresses_callback(query) or not re.fullmatch(
        r"(?:是|就是|我说的是|指的是)?[^。！？!?\n]{2,30}(?:那个|那位|那个项目)[。.!！]?|"
        r"(?:the )?[A-Za-z ]{2,35} one[.!]?", query.strip(), re.I):
        return query
    previous = next((s for s in reversed(recent) if s.role == "user"), None)
    if (previous is None or previous.owner_id != current_event.owner_id
            or previous.session_id != current_event.session_id
            or not timedelta(0) < current_event.recorded_at - previous.recorded_at <= timedelta(minutes=10)):
        return query
    return previous.content_text + "\n" + query


def exact_name_pattern(name: str) -> str:
    left = r"(?<![A-Za-z0-9_])" if name[0].isascii() else ""
    right = r"(?![A-Za-z0-9_])" if name[-1].isascii() else ""
    return left + re.escape(name) + right


def _in_reference(name: str, query: str) -> bool:
    for match in re.finditer(exact_name_pattern(name), query, re.I):
        suffix = query[match.end():]
        # Do not turn a prefix such as 北星 in 北星辰 into the same named object.
        if not name[-1].isascii() and suffix and re.match(r"[\u3400-\u9fff]", suffix):
            if not re.match(r"又|的|项目|下一步|接下来|之前|现在|今天|昨天|最近|是|吗|呢|还|上次", suffix):
                continue
        return True
    return False


def naming_anchors(query: str, sources) -> tuple[str, ...]:
    found = set()
    for source in sources:
        if source.role != "user":
            continue
        for sentence in re.split(r"[。！？!?\n]", source.content_text):
            if _NOT_ASSERTED.search(sentence) or not re.search(r"我|\b(?:my|our|I)\b", sentence, re.I):
                continue
            for pattern in _NAMING:
                for match in pattern.finditer(sentence):
                    name = match['name']
                    if not _NEGATED.search(sentence[:match.start('name')]) and _in_reference(name, query):
                        found.add(name)
    return tuple(sorted(found, key=lambda name: (-len(name), name)))


def _descriptors(text: str, name: str) -> set[str]:
    # Use only the affirmative clause containing the name. A comparison such as
    # "not the data-project colleague" cannot become a positive discriminator.
    clauses = re.split(r"[，,。.;；！？!?\n]", text)
    positive = [clause for clause in clauses if re.search(exact_name_pattern(name), clause, re.I)
                and not _NEGATED.search(clause) and not _NOT_ASSERTED.search(clause)]
    content = re.sub(exact_name_pattern(name), " ", " ".join(positive), flags=re.I)
    return set(tokens(_FILLER.sub(" ", content)))


def resolve_sources(query: str, sources, *, explicit: bool) -> SourceResolution:
    if suppresses_callback(query) or not (explicit or targeted_reference(query)):
        return SourceResolution("not_requested", reason="no_personal_history_request")
    anchors = naming_anchors(query, sources)
    if not anchors:
        return SourceResolution("unknown")
    candidates = [source for source in sources if source.role == "user" and any(
        re.search(exact_name_pattern(name), source.content_text, re.I) for name in anchors)]
    # Keep all occurrences including later corrections. Never select a source by
    # rank/recency alone and discard a competing namesake or a contradiction.
    if len(candidates) > MAX_SOURCES or len(anchors) != 1:
        return SourceResolution("ambiguous", anchors, reason="candidate_capacity_or_multiple_names")
    name = anchors[0]
    query_without_name = re.sub(exact_name_pattern(name), " ", query, flags=re.I)
    qualifiers = set(tokens(_FILLER.sub(" ", query_without_name)))
    matching = [source for source in candidates if qualifiers & _descriptors(source.content_text, name)]
    # Negative or conflicting descriptions are left together for the Brain to
    # interpret from raw evidence. The resolver does not infer entity negation.
    if len(matching) == 1 and not _NEGATED.search(query):
        # Other same-name statements may correct the selected source. Keep them
        # visible; exact scope selection must not bypass the correction overlay.
        return SourceResolution("resolved", anchors, tuple(s.event_id for s in candidates),
                                "one_affirmative_descriptor_match_sources_retained")
    return SourceResolution("resolved" if len(candidates) == 1 else "ambiguous", anchors,
                            tuple(s.event_id for s in candidates),
                            "single_visible_source" if len(candidates) == 1 else "multiple_source_alternatives")
