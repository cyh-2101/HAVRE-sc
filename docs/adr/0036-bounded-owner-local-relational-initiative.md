# ADR-0036: Bounded relational initiative

- Status: Proposed; the original bounded path, two-beat correction, and later owner-authorized GPT-high planning correction are production-active; formal acceptance and repeated owner-experience review remain open
- Date: 2026-09-04
- Decision owner: Product Owner
- Formal ADR acceptance: open
- Authorization references: `product-owner/local-relational-initiative-2026-09-04`, `product-owner/two-beat-friend-conversation-2026-09-04`, and `product-owner/gpt-two-beat-friend-conversation-2026-09-04`

## Context

The owner wants HAVRE to behave less like a request/response tool and more like a
good long-known friend: sometimes continue a personal topic after the first
reply, start an ordinary life conversation, offer a view, and gently try again
after silence without becoming clingy. Goal reminders are obligations and must
not be suppressed merely because relationship conversation was unanswered.

This introduces a material interruption risk. Message count, timing, silence,
and generated wording cannot become engagement optimization or a model-owned
permission to contact the owner.

## Candidate design

1. A completed eligible GPT-routed PUBLIC/NORMAL talk turn may create an exact-
   source first continuation candidate. Sharing, asking, and deciding turns are
   eligible; technical/governance mechanics and explicit stop language are not.
   Beat one is eligible exactly one minute after the durable assistant Event and
   expires 15 minutes later. A question in the first reply no longer suppresses
   the candidate, but the delayed line must remain distinct.
2. Any newer owner message cancels pending planning or delivery. An interaction
   currently in flight defers standalone delivery. The user-arrival epoch is
   rechecked in the same delivery transaction so a race cannot interrupt the new
   chat. Only after beat one was actually visible may Core create beat two,
   eligible exactly 30 minutes after that delivery and expiring 15 minutes later.
   There is no third beat for the same source turn.
3. Under the later explicit owner authorization, new delayed continuation
   receipts use isolated no-tools GPT-5.6-sol at fixed high effort. They receive
   only the already completed PUBLIC/NORMAL cloud-eligible owner/assistant turn,
   plus the first delivered beat when planning beat two. PRIVATE,
   HIGHLY_PRIVATE, LOCAL_ONLY, and cloud-ineligible sources remain excluded.
   Existing local receipts keep their original exact Qwen3-8B authorization and
   are never rewritten or silently switched.
4. Each planner run may produce one or two short sentences: a grounded everyday
   question, a direct continuation, or one proportionate view. It may also choose
   no action. It may not analyze by default, assign a task, mention non-response,
   manufacture urgency/dependence, or invent history.
   A deterministic output gate downgrades generic emotional confirmation,
   unsupported mind-reading, default recovery coaching, closed guesses about
   unmentioned facts, fabricated HAVRE life history, and non-opinion restatement
   to no-action.
5. In-conversation beats use a separate `conversation_continuation` category,
   limited to two deliveries per 24 hours and still bounded by the existing global
   budget. Cold relationship contact counts only delivered `relationship_follow_up` messages
   after the most recent ordinary owner message. Goal reminders are excluded.
   The candidate cadence is:

   - first unanswered relational touch: eligible normally;
   - second: no earlier than 24 hours after the first;
   - third: no earlier than 72 hours after the second;
   - after three unanswered touches: pause until a new owner message.

6. A new ordinary owner message resets the derived relationship cadence without
   claiming that its meaning was a response to any particular prompt. “Stop”,
   dismiss, snooze, quiet hours, category permission, global/category budgets,
   expiry, deduplication, privacy, and the hard anti-runaway breaker remain
   stronger controls.
7. Goal reminders remain a separate `owner_reminder` category. Once a Goal's
   first approved reminder date has begun, the filler may add at most one
   source-guarded check-in across all eligible Goals at a stable pseudorandom
   daytime slot, preferring the nearest deadline. Exact scheduled reminders stay
   independent and are not removed by this filler ceiling. An existing filler on
   that day prevents another. Active conversation always defers standalone
   delivery. Current Goal revision, explicit completion, stop/snooze, quiet hours,
   delivery budget, and the hard breaker remain authoritative.
8. Random-looking times are derived from owner/Goal/revision/local-date hashes.
   They are stable under retry and replay; nondeterministic retry storms are
   forbidden.
9. Migration 0060 stores the original exact source IDs/hashes, status, provider
   receipt, bounded result, and optional proactive work reference. Migration
   0061 adds immutable beat identity and parent lineage; migration 0062 corrects
   the delivery guard to require the proactive work table's actual `succeeded`
   terminal state. Migration 0063 binds new terminal receipts to exact
   GPT-5.6-sol/high evidence, preserves earlier local receipts, and requires both
   beats in one chain to keep the same authorization. Authorized exact-source
   erasure removes both beats and both queue items before the source Event.
10. Owner settings expose separate important-reminder and friendly-check-in
    permissions. The global master switch and all stronger Core controls remain.

## Activation gate

Production activation remains conditional on the launch flag, the owner's global
Reach Out preference, and the separate friendly-check-in permission. The bounded
candidate required all of the following before its first activation:

- fresh and in-place migration through 0063;
- direct-SQL source-pair/hash/privacy/transition attacks;
- owner reply before claim, during planning, and during delivery races;
- exact one-minute beat-one timing, delivery-relative 30-minute beat-two timing,
  15-minute per-beat expiry, two-beat stop, and unchanged 24/72-hour cold cadence;
- Goal reminders excluded from the relationship count;
- stable daily Goal jitter, same-day deduplication, current-revision cancellation,
  explicit completion, active-chat deferral, and retry idempotency;
- complete PostgreSQL-backed suite with zero database skips;
- provenance audit `[]`;
- an owner-visible status/readback and real GPT non-delivering dry-run before
  production worker activation.

## Evidence boundary

The 2026-09-04 implementation evidence passed fresh and in-place migration through
0060, the direct-SQL wrong-hash/mismatched-pair/LOCAL_ONLY-source/illegal-transition
matrix, reply and active-chat races, 30-second/15-minute timing, 24/72-hour cadence,
three-touch pause, Goal exclusion, stable daily Goal scheduling, and exact-source
erasure. The initial focused module passed 13/13; the final relationship-plus-product
activation regression passed 57/57. The final complete split-environment suite
passed 692/692 primary plus 62/62 pinned-Torch tests (754/754 total, zero database
skips), and provenance audits returned `[]`. A real ten-case synthetic Qwen
readback retained only one specific message after the final quality gate.

The production launcher now sets
`HAVRE_RELATIONAL_INITIATIVE_ENABLED=true`. After controlled restart,
`/v1/product/settings` reported `relationship_initiative_active=true`,
the owner preference remained globally enabled with important reminders and
friendly check-ins both allowed, Memory and Diary returned HTTP 200, the worker
was live, migration head remained 0060, and the production provenance audit
returned `[]`. The continuation table contained zero rows at activation, so
no historical conversation was backfilled. PWA v10 shows the actual natural-
continuation runtime status in owner-facing language.

The owner still needs to judge whether this restraint and timing feel natural
over repeated real use. The master switch, friendly-check-in permission, stop,
snooze, quiet hours, budgets, three-touch pause, and launch flag remain rollback
and control boundaries.

Passing this gate proves bounded scheduling, persistence, privacy, and race
behavior. It does not prove that the messages feel caring or that proactive
contact helps the owner's life. Those remain repeated owner-experience questions.
The original evidence in this section preceded the later explicit authorization
for delayed GPT planning recorded below.

## Two-beat owner correction evidence

The owner's later 2026-09-04 correction supersedes only the original 30-second,
single-beat in-conversation cadence. Focused continuation tests pass 17/17,
including exact timing, delivered-parent enforcement, owner-reply cancellation,
active-chat deferral, two-beat stop, direct-SQL attacks, and two-run/two-work-item
source erasure. The complete primary PostgreSQL suite passes 699/699 and the exact
historical pinned-Torch split passes 62/62, for 761/761 with zero database skips.
Dependency, compile, PWA executable-contract, JavaScript syntax, whitespace, and
test/production provenance checks pass; both provenance audits return `[]`.

Production is at migration head 0062 with API and two-second-poll worker live.
Preference revision 17 allows `conversation_continuation` with a two-per-24-hour
category ceiling while preserving the owner's prior global and reminder limits.
Memory and Diary return HTTP 200, new stderr logs are empty, and PWA v11 polls the
visible idle chat timeline every four seconds so a delivered beat appears without
a manual reload. The five historical v1 receipts remain two cancelled and three
no-action rows; no v2 receipt was backfilled.

## GPT-high delayed-planning owner correction

Later on 2026-09-04 the Product Owner explicitly approved the separate cloud
data flow after asking why delayed planning still used Qwen. New eligible
receipts now carry
`product-owner/gpt-two-beat-friend-conversation-2026-09-04` and use the
already isolated Codex CLI GPT-5.6-sol provider at fixed high effort. The request
is no-tools/no-web and contains only the exact source pair, plus beat one when
planning beat two. Private or cloud-ineligible turns cannot create the receipt,
and provider failure is never a silent local fallback.

Migration 0063 preserves both earlier local authorization forms and adds an
exact terminal-provider constraint for new GPT receipts. The focused suite passes
20/20, including a real Codex-adapter mock execution, new-authority/local-provider
forgery rejection, legacy-local completion, zero local calls on GPT failure,
timing, races, two-beat stop, and source erasure. The complete split suite passes
702/702 primary plus 62/62 pinned-Torch tests, 764/764 total with zero database
skips. The disposable
provenance audit returns `[]`; both dependency and compile environments,
PWA executable contract, JavaScript syntax, and diff checks pass.

The controlled restart applied only migration 0063. Production is ready at that
head with live API and two-second worker, friendly continuation allowed with its
two-per-24-hour budget, no silent cross-provider fallback, Memory and Diary HTTP
200, current API/worker stderr logs empty, and production provenance audit
`[]`. The five historical v1 local rows remain unchanged and no GPT receipt
was backfilled. A real non-delivering GPT-5.6-sol/high synthetic probe returned a
specific distinct question and passed the deterministic quality gate; no Event,
receipt, queue item, or delivery was created. This activates the exact path but
does not prove owner-visible naturalness.
