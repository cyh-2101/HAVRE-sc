# Bounded Relational Initiative Checkpoint

Date: **2026-09-04**

Status: **Candidate implemented, technically verified, and production-active
under the exact owner-authorized GPT-high boundary. Formal ADR-0036 acceptance
and repeated owner-experience judgment remain open.**

## Owner intent and bounded design

The Product Owner asked HAVRE to feel more like a good long-known friend: it may
naturally continue a suitable everyday topic, sometimes ask a small follow-up or
offer a view, space further contact increasingly after silence, stop after three
unanswered relationship touches, and resume normally after the owner returns.
Goal reminders remain obligations and must continue independently without
interrupting an active conversation.

The implemented candidate preserves that intent without treating silence as
consent or engagement optimization:

- one eligible completed GPT-routed PUBLIC/NORMAL sharing turn may create an
  exact-source receipt eligible after 30 seconds and expired after 15 minutes;
- if the first reply already asks a question, no receipt is created: HAVRE waits
  instead of stacking another prompt before the owner has answered;
- any newer ordinary owner message cancels the receipt before planning or delivery;
- the second-beat planner is the exact owner-local Qwen provider and sees only the
  already completed turn; no second GPT/cloud disclosure is authorized;
- output is at most one or two short sentences or no-action, with no default
  analysis, task assignment, urgency, non-response language, dependence cue, or
  invented history;
- a deterministic quality gate turns generic emotional confirmation, unsupported
  mind-reading, and non-opinion restatement into no-action;
- delivered relationship contacts wait at least 24 hours before the second and
  72 hours before the third, then pause after three until a new owner message;
- Goal reminders do not increment that count. After an owner-approved reminder
  start date, all eligible Goals share at most one supplemental stable hash-derived
  daytime check-in per day, with the nearest deadline considered first; retries
  cannot randomize a new time. Exact scheduled reminders remain independent;
- the settings page exposes separate nontechnical controls for important reminders
  and friendly check-ins;
- standalone proactive work defers during an active interaction and still passes
  preference, stop, snooze, quiet-hour, budget, expiry, deduplication, privacy,
  and anti-runaway Core controls.

## Persistence and erasure

Migration `0060_owner_conversation_continuation.sql` stores immutable owner,
source user/assistant Event IDs and hashes, session, timing, authorization, local
provider receipt, bounded result, and optional proactive work reference. Database
guards reconstruct the exact completed cloud-routed turn and reject mismatched or
private sources and invalid transitions.

The privileged derivative-erasure path now removes continuation receipts and
their proactive queue items when, and only when, a future owner request explicitly
names the source Event. This task selected and erased **no production source**.

## Verification

- initial focused relational-initiative module: **13/13 passed**;
- final relationship-plus-product activation regression: **57/57 passed** in
  17.990 seconds;
- final primary PostgreSQL-backed suite: **692/692 passed** in 75.916 seconds;
- exact three historical Stage 9A modules in the pinned-Torch environment:
  **62/62 passed** in 43.827 seconds;
- combined inventory: **754/754 passed**, zero database skips;
- fresh empty-database migration through 0060 and populated 0059-to-0060 upgrade:
  passed;
- direct SQL wrong-hash, mismatched-turn, LOCAL_ONLY-source, and illegal-transition
  attacks: rejected;
- exact assistant-source derivative-erasure probe removed the continuation receipt
  and queue item while leaving raw-source deletion to its separate privileged phase;
- disposable and production provenance audits: `[]`;
- main and pinned `pip check`, Python compileall, PWA/Node syntax, contract checks,
  and `git diff --check`: passed.

One superseded full-run attempt used the wrong primary/Torch module split and
reported four `ModuleNotFoundError: torch` environment errors. No product assertion
failed. The authoritative rerun used the repository's exact three-module pinned
boundary and produced the zero-error results above.

## Production readback and stop boundary

Migration 0060 is applied to `havre_local_20260822`. After a controlled desktop
restart, `/health/ready` reported `ready`, the protected Memory and Diary endpoints
returned HTTP 200, the worker heartbeat was live, current API and worker stderr
logs were empty, and the continuation table contained zero rows.

The follow-up UX correction passed 57/57 focused tests plus the same complete
754-test split-environment inventory. The final activation run independently
repeated 57/57 focused tests, 692/692 primary tests, and 62/62 pinned-Torch tests,
all with zero skips. Test and production provenance audits returned `[]`;
both dependency checks, compileall, PWA executable contract, JavaScript syntax,
PowerShell parse, and diff checks passed.

The launcher now explicitly sets
`HAVRE_RELATIONAL_INITIATIVE_ENABLED=true`. After controlled restart,
production served PWA cache
`havre-static-20260904-reachout-v10`, returned independent important-reminder
and friendly-check-in controls plus an owner-facing actual-runtime status, kept
Memory and Diary at HTTP 200, reported live API and worker processes, retained
migration head 0060, and returned `relationship_initiative_active=true`.
The production preference remained globally enabled with both categories allowed.
The continuation table still had zero rows at activation, proving the launch did
not backfill older conversations.

The bounded path now applies only to future eligible turns. It remains subject to
the master and friendly-check-in switches, owner arrival, first-reply question
suppression, 15-minute expiry, active-chat deferral, 24/72-hour spacing, three-touch
pause, quiet hours, stop/snooze, budgets, privacy, and the anti-runaway breaker.
The next evidence is repeated real owner use: review whether wording feels natural,
whether no-action decisions are sensible, whether timing is welcome, and whether
messages avoid pressure or dependence. Technical correctness does not prove
companionship quality.

The final non-delivering synthetic readback used the live `qwen3-8b-q4-k-m`
service with the formal provider's `enable_thinking=false` and `reasoning_effort=none`
parameters. The model proposed sends for five of ten cases; the deterministic
quality gate rejected four generic, mind-reading, or restatement outputs and kept
only the specific “what breed was the dog?” continuation. This is safer but may
be too conservative. Exact examples and the superseded findings are in
`owner_improvement_reviews/2026-09-04-relational-initiative-dry-run.md`.

## Owner correction: current-conversation two-beat cadence

Later on 2026-09-04 the Product Owner explicitly replaced only the in-conversation
30-second/single-beat behavior. The production path now creates beat one exactly
one minute after an eligible completed GPT-routed PUBLIC/NORMAL talk turn. If the
owner sends nothing new and beat one is actually visible, beat two becomes eligible
30 minutes after that delivery; there is no third beat. A newer ordinary owner
message cancels pending planning or delivery, and an active interaction still
defers standalone work.

The first GPT response now receives owner-experience v2 guidance: ordinary-life
curiosity, one grounded follow-up, or one real view are valid conversational ends
even when no task needs solving. The delayed planner remains exact unadapted local
Qwen3-8B; no second cloud disclosure was added. Deterministic gates now also reject
default recovery coaching, fabricated HAVRE life experience, and closed guesses
about an unmentioned concrete fact. In-conversation work uses the separate
`conversation_continuation` category with a two-per-24-hour ceiling. The earlier
24/72-hour/three-touch logic remains only for later cold `relationship_follow_up`
contact, and Goal reminders remain independent.

Migrations 0061 and 0062 add immutable beat/parent lineage and require beat two to
name the matching completed first run plus its actual visible delivery time. 0062
is additive because 0061 had already entered a dedicated test database; it corrects
the proactive work predicate from the continuation-run name `completed` to the
work table's real terminal state `succeeded`. Direct SQL rejects a wrong beat-one
window and a beat-two insert without a delivered parent. Exact-source erasure was
executed against synthetic data and removed both run rows and both work items while
the raw source remained for the separate privileged phase.

Final evidence:

- focused continuation contract/integration: **17/17 passed**;
- primary PostgreSQL-backed inventory: **699/699 passed** in 73.542 seconds;
- exact three pinned-Torch modules: **62/62 passed** in 45.404 seconds;
- combined: **761/761 passed**, zero database skips;
- disposable and production provenance audits: `[]`;
- main and pinned dependency checks, compileall, PWA v11 executable contract,
  JavaScript syntax, and `git diff --check`: passed.

After two controlled restarts, production is healthy at migration head 0062.
The second restart rotated the least-privilege database credential immediately
after a local diagnostic error echoed the prior URL. API and two-second-poll worker
are live, current stderr logs are empty, Memory and Diary return HTTP 200, and
preference revision 17 allows the new category with budget two while preserving
the owner's existing reminder/global limits. PWA cache
`havre-static-20260904-conversation-v11` refreshes the visible idle timeline every
four seconds. The five old v1 rows remain two cancelled and three no-action; no v2
row was backfilled.

A final owner-free, non-delivering five-case Qwen readback accepted two specific
questions and rejected three cases: one invented HAVRE food history/guessed dish,
one owner-voice restatement, and one transactional translation. This proves the
new path is not categorically no-action and that the new gates catch the observed
fabrications. It does not prove every delayed line is natural: one accepted game
question was close in meaning to the first reply's question. Repeated real owner
use remains the decisive quality evidence.

## Owner-approved GPT planning correction

After the owner asked why this path still used Qwen, the Product Owner explicitly
approved sending the exact eligible completed turn to GPT again for delayed
planning. New receipts now use isolated, no-tools/no-web GPT-5.6-sol at fixed
high effort. Only PUBLIC/NORMAL, cloud-eligible turns already proven to have used
the GPT route qualify. PRIVATE, HIGHLY_PRIVATE, LOCAL_ONLY, and cloud-ineligible
content remain excluded, and a GPT failure does not fall back to Qwen.

Migration `0063_owner_authorized_gpt_conversation_continuation.sql` is
additive. It keeps old Qwen receipts valid under their original authorization,
requires new terminal receipts to record the exact GPT model/adapter/high-effort
configuration, and forbids a two-beat chain from changing authorization.

Verification on dedicated database
`havre_gpt_continuation_test_20260904`:

- focused continuation suite: **20/20 passed**, including zero Qwen calls on
  synthetic GPT failure;
- complete primary PostgreSQL-backed suite: **702/702 passed** in 75.519 seconds;
- exact three pinned-Torch modules: **62/62 passed** in 44.252 seconds;
- combined: **764/764 passed**, zero database skips;
- migration head: `0063_owner_authorized_gpt_conversation_continuation.sql`;
- disposable provenance audit: `[]`;
- main and pinned dependency checks, both compile checks, PWA executable
  contract, JavaScript syntax, and diff checks: passed.

The controlled restart applied only migration 0063. `/health/ready` reports
ready at that head with both providers healthy; API and the two-second worker are
live. Friendly continuation remains allowed with budget two, silent fallback is
false, Memory and Diary return HTTP 200, the newest API/worker stderr logs are
both zero bytes, and production provenance audit is `[]`. The five historical
v1 Qwen rows remain unchanged and no GPT receipt was backfilled.

A real non-delivering GPT-5.6-sol/high probe used only a fictional soda
conversation and returned the distinct continuation “光看那个夸张的名字，你本来以为
它会是什么味道？”, which passed the deterministic quality gate. It created no
Event, receipt, proactive work item, or delivery. The first capture attempt
completed the provider call but failed only while printing Chinese through the
terminal's CP1252 encoding; the ASCII-safe rerun supplied the recorded evidence.
This proves route/protocol compatibility, not repeated owner-visible usefulness.
