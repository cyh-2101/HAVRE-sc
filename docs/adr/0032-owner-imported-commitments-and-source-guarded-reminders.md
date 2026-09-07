# ADR-0032: Owner-imported commitments and source-guarded reminders

- Status: Implemented by explicit Product Owner task direction; formal ADR acceptance pending
- Date: 2026-09-03
- Implementation authority: Product Owner request on 2026-09-03
- Extends: ADR-0016, ADR-0024, and ADR-0031

## Context

The active Proactive Core could evaluate one explicit reminder in a chat turn,
one current Goal `review_at`, or one planned Scene start. That was not enough
for a semester schedule where one owner-confirmed commitment needs several
useful contacts before the same deadline. Treating a Markdown calendar as
ordinary Calendar context would not authorize outreach, while manufacturing
dozens of fake chat turns would weaken provenance and pollute the conversation.

The Product Owner supplied an exact Fall 2026 course-calendar document and
directed HAVRE to remember its deadlines and begin occasional contact three
days before ordinary work, one week before exams and large tasks, and to offer
encouragement the day before an exam. The Product Owner also asked HAVRE to
remain practically useful rather than merely pass a technical gate.

## Decision

1. An owner-reviewed local schedule snapshot may create durable reality Goals.
   The source interaction, Goals, and reminder text remain `LOCAL_ONLY`, retain
   the exact source-document SHA-256 and entry identifier, and are never made
   training eligible.
2. One current active Goal may own multiple deterministic reminder work items.
   Core derives the effective DataPolicy, current preference revision, Goal
   revision, Goal content hash, last lifecycle Event, and source Event hash.
   Callers may choose only the reminder time, one of three reminder roles, and
   owner-visible text.
3. Every work item carries an execution-time `ProactiveSourceGuard`. Updating,
   pausing, completing, abandoning, erasing, or superseding the Goal makes all
   older pending reminders fail closed before proposal or delivery.
4. The initial Fall 2026 policy is:
   - ordinary assignments/tasks: three days and one day before;
   - large tasks, including ECE 385 labs and CS 444 assignments: seven days,
     three days, and one day before;
   - exams: seven days, three days, and a supportive message one day before;
   - if the authorized window already opened when imported, one catch-up
     contact is eligible immediately and must say that the window has already
     opened rather than repeat an obsolete “one week/three days remain” claim;
   - tentative dates are labeled tentative; TBA and conditional 4-credit items
     are remembered but receive no automatic reminder until resolved.
5. Wording remains deterministic and owner-authored. GPT may answer the user's
   later conversation about a reminder, but GPT does not decide whether, when,
   or what proactive message is sent.
6. Existing Interruption Policy remains the only send authority. The current
   owner preference has no cooldown and no quiet-hours window, while its
   24-hour safety budget, stop, dismiss, snooze, deduplication, privacy, expiry,
   and channel checks remain active. "Occasional" is implemented as the sparse
   schedule above, not as a free-running model cadence.
7. Source-ingest interactions use the reserved `course-source-` idempotency
   namespace. Their Events and inference lineage remain canonical and auditable,
   but the owner chat timeline excludes them because they are ingestion
   mechanics, not conversation. Goal-bound proactive inbox messages remain
   visible normally.
8. The owner-authorized conversation projection contains exactly five fields:
   course name, task name, deadline, completion state, and reminder history.
   It is `NORMAL`, cloud eligible, memory/training ineligible, and bound to one
   exact source hash plus the recorded Product Owner authorization. The
   `LOCAL_ONLY` source document, source interaction, Goal reason, and next
   action never enter this projection.
9. A clear owner completion report may transition exactly one uniquely matched
   active Goal. The lifecycle Event and the reporting `USER_MESSAGE` are bound
   by immutable `goal_transition_evidence`; ambiguous reports request one
   clarification and do not mutate a Goal.
10. A due reminder may be fused into an already active suitable conversation,
    or delivered through the existing Web inbox. Claims, deferrals, actual
    inclusion, and delivery mode are durable. Inference failure or omission
    releases or defers the claim rather than pretending the reminder was sent.
11. The exact owner preference reference
    `stage15-owner-authorized-no-normal-cap` removes only ordinary category and
    global frequency caps for `owner_goal_reminder` / `owner_reminder`. The
    hard 24-per-24-hour safety breaker and every stop, privacy, expiry, source,
    channel, lease, and duplicate guard remain active.
12. Schedule generation changes are append-preserved. Generation v2 is inserted
    before the exact authorized source's legacy pending/retryable generation is
    cancelled. A leased item blocks supersession; sent history is not rewritten.
13. On a future privileged erasure request that explicitly names a source Event,
    the source-erasure transaction also removes Goals derived from that Event or
    from completion evidence rooted in it, commitment projections and field
    authorizations that become orphaned, transition evidence, fusion claims,
    reminder-delivery records, affected interaction leases, and proactive queue
    artifacts. This authority does not select a source by itself. Raw source
    Event deletion remains the separately governed phase.

## Source snapshot

- owner document SHA-256:
  `517c994a9e983a8a383ba2fe6cb32f75218236a22bf6fb6d3181dafffeb0e069`;
- timezone: `America/Chicago`;
- private reviewed plan: `var/owner/course-schedule-fall-2026.plan.json`
  (gitignored, owner-local);
- importer: `scripts/import_owner_course_schedule.py`.

## Preserved boundaries

- Course administration data does not authorize HAVRE to complete coursework.
- Course AI-use rules remain controlling.
- No broad Calendar-to-outreach trigger, automatic semantic sensitivity
  classifier, GPT-authored proactive message, always-on cloud Core, training,
  identity change, or public exposure is authorized.
- OA70 cases 21-70 remain outside runtime examples and prompts. Inspecting their
  dialogue structure for evaluation does not declassify or activate them.

## Verification required

- exact source-hash failure and dry-run counts;
- current-Goal guard, exact deterministic rendering, and stale-Goal
  cancellation regression;
- owner-only API idempotency and restart-safe queued work;
- live owner database readback of the source Event, imported Goals, pending
  work, current preference, and immediate due reminder;
- full zero-skip database regression and provenance audit before claiming the
  slice technically complete.

The implemented and owner-local activation evidence is recorded in
[`STAGE15_COMMITMENT_LOOP_CHECKPOINT.md`](../STAGE15_COMMITMENT_LOOP_CHECKPOINT.md).
That checkpoint is technical evidence, not formal ADR acceptance.
