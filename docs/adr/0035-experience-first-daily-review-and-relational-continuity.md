# ADR-0035: Experience-first daily review and relational continuity

- Status: Proposed; implementation authorized for the owner-local runtime
- Date: 2026-09-04
- Decision owner: Product Owner
- Formal ADR acceptance: open
- Implementation authorization references:
  - `product-owner:2026-09-04:experience-first-companion-v1`
  - `product-owner:2026-09-04:oa70-all70-runtime-examples`
  - `product-owner/experience-first-daily-review-2026-09-04`
  - `product-owner/explicit-chat-goal-planning-2026-09-04`
- Proposed amendments: ADR-0031's first-20 OA70 runtime limit, ADR-0032's
  prohibition on conversation/Memory proactive sources, ADR-0033's deterministic
  Diary timing, and ADR-0034's request-time Diary refresh and fixed-enum-only
  review output

## Context

The owner found that technically correct chat could still feel like a tool: it
analyzed before relating, turned low-value流水 into long Diary pages, exposed
implementation detail in “记得”, flattened course and personal Goals, and limited
proactive contact to scheduled commitments. The owner explicitly prioritized
felt experience and supplied the relationship behavior that should govern this
owner-local product.

## Authorized implementation

1. A mandatory owner-response instruction is rendered separately from Memory.
   HAVRE chats first and solves second, infers whether the owner wants company or
   analysis, permits silence and one gentle invitation, stops when asked, may be
   warm and firm, may have humor and opinions, and never replaces owner agency.
   It may use relationship language while remaining reality-grounded and must
   never manufacture dependence or claim history it was not supplied.
2. The exact frozen OA70 cases 1-70 may be transformed into the owner-only,
   GPT-branch runtime example bank. The source file remains byte-identical. This
   authorization is runtime calibration only: it is not training, tuning,
   declassification, public release, or local-model evidence. Anchor 034 is
   selected only for the exact “did you miss me” reality-grounding case and is
   not a generic relationship template.
3. Diary generation moves to the existing owner-local worker at 05:00 in the
   configured owner timezone and reviews the just-finished previous day. GET
   requests are read-only. The high-effort GPT request receives only eligible
   PUBLIC/NORMAL GPT-routed messages, up to seven days of bounded eligible prior
   chat, and bounded current eligible Memory. Private/local text remains absent;
   only its count is disclosed. Prior context may check continuity but cannot be
   imported as a fact into that day's Diary.
4. Low-value greetings, acknowledgements, status chatter, governance mechanics,
   technical logs, and transactional流水 do not create a Diary. Meaningful entries
   are coherent first-person owner narratives, not chronological transcripts.
5. Every successful review may produce structured, evidence-ID-bound product
   suggestions. Companion writes a local Markdown file under
   `owner_improvement_reviews/`; it contains no chat transcript and never edits
   code, Identity, values, policy, or configuration. The owner may later hand the
   file to Codex manually. This supersedes ADR-0034's automatic 14-day quality-flag
   instruction mapping: review artifacts are not selected as chat instructions on
   either route. The 2026-09-05 correction removes that selection, preserving
   stored reviews, exact provenance, private boundaries, and explicit owner
   feedback. It does not declassify reviews to make GPT eligible.
6. One daily review may propose one natural relationship follow-up sourced from
   a current-day owner Event and, optionally, admitted Memory. Memory or recent
   conversation is evidence, not send authority. The existing Core Interruption
   Policy resolves the current preference, a separate
   `relationship_follow_up` permission, one-per-24-hour category budget, stop
   subjects, quiet hours, deduplication, expiry, and delivery. Silence never
   triggers. A current “do not ask/push/talk” signal rejects the proposal.
7. Only explicit owner language such as “create/record this Goal”, “plan this”,
   or “remind me” opens the high-effort chat Goal planner. Ordinary conversation
   cannot create a Goal or reminder. Core validates an exact source quote,
   objective, horizon, and reminder window; persists an evidence-linked Goal and
   guarded queue work; and supplies the Replyer with a durable action receipt.
   The Replyer may say “saved” only after that receipt exists. Private/local
   messages are not uploaded and this cloud planner creates nothing for them.
8. The “记得” page presents friendly Memory, pending confirmation, User Model,
   and hierarchical Goals without confidence scores, hashes, raw JSON, or
   implementation labels. Course assignment/exam Goals are grouped by course;
   other explicit chat Goals appear separately.
9. One durable assistant Event may be presented as multiple complete UI bubbles.
   Long replies are split into one or a few sentences per bubble and revealed at
   2-second intervals. This is delivery presentation only; it does not forge
   separate model turns or Events.
10. Diary month colors follow restrained seasonal/birth-flower associations and
    are supplemental navigation cues. Text retains at least 4.5:1 contrast and
    month identity never depends on color alone.
11. Additive migration 0059 binds schedule receipts, prior Memory sources,
    generated-file receipts, explicit chat plan/action receipts, and the new
    proactive source kinds. Authorized source erasure deletes every affected run,
    Memory/Goal/reminder/proactive derivative, receipt, and exact local review
    file before raw-source removal. No source is erased without a newly named
    source Event.

## Rejected alternatives for this implementation

- **Generate Diary when the page opens:** timing depends on browsing and can make
  a read endpoint costly or surprising.
- **Let a model send because it is curious:** bypasses owner controls and Core's
  sole interruption authority.
- **Treat all conversation as a Goal or Memory:** turns relationship chat into a
  task extractor and violates the owner's experience priority.
- **Let daily review patch the repository:** converts reflective evidence into an
  unauthorized self-modifying system.
- **Generalize Anchor 034:** loses the exact reality-grounding boundary the owner
  explicitly called special.

## Evidence boundary

Passing tests prove typed contracts, database guards, exact provenance,
source-erasure closure, no private prompt leakage in fixtures, worker scheduling,
UI grouping, and Core-owned proactive execution. The first real 05:00 run
initially exposed provider enum drift and immediate retry amplification; the
bounded optional-effect repair and persisted backoff recovered it with exact
receipts. That execution still does not prove the resulting Diary is useful,
that a physical iPhone displayed the revised UI, or that relational follow-ups
improve the owner's life. Those require actual owner experience and feedback.
Formal ADR acceptance remains a separate owner decision.

## Owner-authorized multi-turn action repair (2026-09-08)

The explicit Goal planner may resolve a pending request from at most eight
contiguous eligible messages within 24 hours, with exact owner quotes and no
reliance on assistant promises as authority. Unrelated conversation, revocation
or restricted sources end that chain. Explicit daily schedules of at most 31
dates use the existing one-off reminder queue and current permission checks;
random daytime is used only on owner request and disclosed as 10:00–21:00.
A current durable receipt precedes any claim of saving or scheduling. “再说点”
does not re-execute actions. Migration 0072 records immutable owner-qualified
source manifests and adds earlier-source erasure closure. This is an authorized
repair of point 7, not a new proactive scheduler, permission or formal acceptance
of any other pending ADR scope. See [repair evidence](../CHAT_REPAIR_REVIEW_2026-09-08.md).
