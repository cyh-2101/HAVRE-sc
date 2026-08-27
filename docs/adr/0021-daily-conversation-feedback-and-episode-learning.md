# ADR-0021: Daily conversation, episode consolidation, and governed owner feedback

- Status: Accepted
- Date: 2026-08-22
- Accepted: 2026-08-22 by Product Owner
- Decision owners: Product Owner/System Architect
- Supersedes: None
- Superseded by: None

## Context

HAVRE already separates append-oriented Events, reviewed Memory, canonical
training data, candidate models, and explicit promotion. Daily use nevertheless
had two development-shaped gaps: the normal computer entry point was a CLI, and
the Stage 2 worker treated each eligible user Event as a possible isolated
episodic candidate. A thumbs-down also did not preserve enough exact evidence to
distinguish model communication, Memory grounding/retrieval, Core policy, mode
selection, and other system failures.

The Product Owner wants complete conversation history and natural multi-turn
episodes without promoting incidental utterances into durable claims. The owner
also wants edits and ratings to improve future HAVRE candidates, but explicitly
rejects online weight updates and automatic training eligibility.

## Decision

Keep five distinct, provenance-linked layers:

```text
raw USER_MESSAGE / ASSISTANT_MESSAGE Events
  -> closed conversation episode + source-linked summary
  -> reviewed derived Memory / belief / preference artifacts
  -> reviewed personalization feedback revision
  -> future immutable training/evaluation snapshot and candidate release
```

The daily Web client is another same-origin entry to the existing Companion
Core, Event Store, Memory, provider, trace, privacy, and deployment boundaries.
It is not a second Companion. Every completed turn remains an immutable Event.
The browser stores only the current session ID in local storage, not private
message copies. The desktop launcher bootstraps an HttpOnly owner-session cookie
from a protected local secret; owner-data HTTP responses are `no-store`.

A Web conversation is consolidated when the owner starts a new conversation,
explicitly closes it, or a future versioned idle policy declares a boundary.
The episode has exact ordered Event membership and an immutable summary. The
current implementation uses a deliberately modest owner-message-only extractive
summary; assistant Events remain exact history/members but are not recopied into
the derivative. It does not infer identity or truth. Episode summaries are
eligible for shared-history recall under their conservative derived DataPolicy. Derived Memory suggestions
are reviewed in a separate Memory surface and never interrupt chat. One-off
self-criticism is not promoted into Semantic/Pattern Memory merely because it
appeared in a message or summary.

Response feedback is an append-only revision thread attached to the exact
assistant Event, request, session, trace, ContextPack, route, inference attempt,
provider/model/adapter/tokenizer, and serving configuration. The original answer
is never overwritten. An owner rewrite is a proposed alternative, capable of
later supporting supervised personalization, a chosen/rejected pair, and a
regression case.

Rating/reason labels are owner observations, not automatic root-cause diagnoses.
Review attribution distinguishes personality/communication,
Memory-grounding/truthfulness, Memory retrieval, Core policy, mode selection,
reasoning/understanding, other system, mixed, and unclassified issues.

Saved feedback always has `training_eligible=false`. The current service and
database reject `approved_for_personalization_training` and every true training
flag because Stage 9B is not active. A future separately authorized Stage 9B
must add a durable, least-privilege owner-authorization path for one current
exact feedback revision before a dataset builder may consider it. There are no
online weight updates.

An explicit versioned response-length preference may enter Context as a runtime
communication control. It cannot rewrite Constitution/Identity/Values or become
an arbitrary hidden prompt.

## Consequences

- Casual messages remain honest history without becoming user-profile facts.
- Shared experiences can be recalled as episodes rather than isolated facts.
- Chat is uninterrupted; Memory and personalization review are concentrated.
- Runtime defects can be fixed without contaminating personality training data.
- Future datasets can select only exact owner-approved feedback revisions with
  complete lineage and erasure closure.
- Episode quality, semantic extraction, automatic boundary cadence, and future
  candidate training require later evidence; the extractive v1 summary is not a
  claim of human-quality consolidation.

## Privacy, retention, and erasure

Episode summaries inherit a conservative combination of eligible source user
Event policies. Non-Memory-eligible content remains raw history but is omitted
from summary content. Feedback and owner rewrites inherit the source response's
privacy class and remain owner-local under the existing deployment policy.
Source erasure removes affected feedback reviews, episode summaries/members,
suggestions, and downstream interaction artifacts before Event deletion.
Owner export includes all new owner-qualified tables.

## Validation

- original response and owner rewrite coexist;
- saved feedback remains non-training-eligible;
- training approval is rejected at service and direct-SQL boundaries while
  Stage 9B is inactive;
- direct SQL cannot forge model lineage or mutate immutable revisions;
- a closed episode has an exact ordered Event membership set;
- normal Web chat creates no per-utterance Memory job;
- episode recall links back to the episode/session;
- source erasure closes feedback and episode derivatives;
- streaming UI exposes text only after the assistant Event is durable.

## Relationship to accepted decisions

This extends ADR-0003, ADR-0004, ADR-0007 through ADR-0011, ADR-0014, and
ADR-0020. It clarifies ADR-0020's current daily-chat promotion cadence but does
not weaken its review, provenance, retention, or erasure rules. It does not
authorize Stage 9B, training, adapter promotion, deployment, new external data,
or a change to Identity/Constitution/Values.
