# Daily Companion quality checkpoint — 2026-09-06 UTC

Owner-authorized implementation following the accepted September 5 real-runtime
audit. Owner-local API/worker are updated; no push, model training/promotion, new
provider, sensing or private-data disclosure. Formal daily-use acceptance remains
with the owner. This is a correctness/continuity/product pass, not a claim of a
human-like perfect memory or independently proven long-term companion quality.

## 1. Starting reality

HEAD was 87a636a with 190 pre-existing changed/untracked source files through
migration 0067. They were preserved separately in local commit **9313fe1**; this is
a historical source checkpoint, not newly implemented work or a new quality claim.
The accepted audit found 0 chat Goal-plan runs/transitions, a completed course task
still active, Goal context in 43/52 Talk packs, and little concrete Memory admission.
GPT was already the ordinary eligible route; private/local turns used unadapted Qwen.
Real-time understanding and the 05:00 Diary job already existed.

## 2. Main causes addressed

- Narrow completion/Goal entry gates did not cover real owner language.
- Goal revision, authorized projection and queue changes were not one atomic action.
- The continuous UI concealed storage-session boundaries in model-visible history.
- Continuation saw less relationship context and was artificially Talk-only.
- Unrelated urgency and generic date words admitted coursework into casual talk.
- Provider presentation conflated internal reasoning with requested explanations;
  multi-message parsing could discard earlier answer parts.
- Layout, stale history refreshes, notification pagination and error states created
  unnecessary friction.

## 3. Previously hidden issues discovered during implementation

Real production-shaped replay exposed a further completion defect: a trailing
parenthesized due date such as 9/4 was treated as another composite task component.
A direct source-erasure regression proved that earlier-history-dependent
continuation queues could remain after the continuation record was removed.
Native structured-output validation initially rejected optional JSON Schema keys;
the adapter incorrectly reported that as GPT/login unavailability. All three were
fixed and reproduced in targeted tests. No private conversation was sent out for
these diagnostics.

Screenshot inspection also caught CSS overriding hidden form controls and a
desktop navigation regression after the mobile layout correction. Both were fixed.
Repeated Memory-to-belief proposals now explain the existing identity without
silently duplicating or overwriting it.

## 4. Key implemented changes

Completion matching checks negation, uncertainty, future/third-person reports,
task numbers, all composite parts and unique identification. Date suffixes are
not task parts; number-only overlap is not relevance. A committed completion has
an exact-source action receipt without suppressing the current owner's message.

Goal creation, action evidence and all reminders share one transaction. Rollback
tests prove no orphan Goal or success receipt after queue failure. Natural chosen
directions and substantial first-person reflections can enter GPT-high semantic
review; ordinary short wishes do not automatically become Goals. Source quotes,
dates and privacy still gate every write.

## 5–6. Daily surfaces and before/after UX

| Surface | Before / risk | Current experience |
| --- | --- | --- |
| Chat | Collapsed empty layout; old history replaced during polling | Stable composer/navigation; preserve reading position; return to latest |
| Notifications | Target had to be among recent 60 messages | Owner-qualified direct load through target Event, then highlight |
| Diary | Detail/list navigation could leave a hidden list; audit material competed with diary | Reliable return; readable paragraphs; review metadata collapsed |
| Memory | Technical actions/native prompts; no quick find | Search, source explanations, editable dialog, explicit correction/retraction and belief rejection |
| Settings | Mixed technical labels; focus could escape | Clear controls; modal focus/Escape; separate reminders/friendly contact retained |
| Errors/reconnect | Technical conflict text; misleading first-install update toast | Safe actionable conflict/retry text, preserved draft, no first-install update announcement |
| Windows/mobile | Desktop side-nav rules conflicted with new layout | Consistent compact navigation; checked at 390×844 and 1440×900 |

One continuous Chat remains; no New Chat/session list. Diary remains distinct
from Memory. Notifications are described as registered, not falsely certified
delivered. Static shell/cache version: **20260906-daily-v15**.

## 7. Memory / User Model / Goal / Context

Canonical Memory, belief revision, Current State and owner-review semantics are
unchanged. No new summary layer or inferred life-state graph was added.
Cross-device working history now supplies exact recent Web turns, including the
assistant side, within the existing bounded budget. For ordinary cloud context,
cross-session additions must already be completed, cloud-eligible GPT turns.
LOCAL_ONLY is not weakened.

Delayed continuation reuses source-bound identity, examples, corrections,
conversation, relevant Memory/beliefs/state from its originating reply. It does
not manufacture a separate summary. Task/ResponsePlan administrative instructions
are excluded. Talk/Guide/Reflect can remain eligible subject to existing dialogue,
privacy, silence, newer-message and timing controls.

The real audited course Goal was reconciled using its original explicit owner
completion Event: revision 2 active → revision 3 completed, matching projection,
**0 pending/leased matching reminder items**. The source chat was not deleted.
The audited 174-character personal-direction message now reaches the planner
(local predicate verification only); it was not retrospectively replayed or saved
as a new historical Goal.

## 8. Privacy and routing

Same GPT-5.6-sol/medium main reply and GPT-high authorized understanding/planning/
continuation; same unadapted owner-local Qwen privacy route. No new external model
or private category. Typed wording corrections cannot swallow Goal receipts/current
input. New adapter **codex-cli-provider-v3-complete-reply** retains all completed
answer items, rejects inconsistent duplicate IDs and still rejects tool activity.

## 9. Reliability and latency

Atomic state changes, typed provider failures, history preservation and direct
notification targeting are verified improvements. Application-only restart now
preserves credentials, devices, database and model instead of resetting the stack.
No end-to-end latency reduction is claimed: real synthetic GPT main calls measured
roughly 7.8–14.3 seconds; a Goal turn also pays for a separate high-effort planner.
Core-governed delivery remains buffered, then splits client bubbles at two seconds.
Physical lock-screen wake/network latency remains unmeasured.

## 10. Small useful additions

Memory quick search; source-preserving correction dialog; invalidating an incorrect
active understanding through the existing governed path; direct old-notification
lookup; return-to-latest; real-time Memory processing/retry explanation; safe app
recycling without credential churn. These are not new administrative workflows.

## 11. Deliberately not done

No broad Memory cleanup, automatic deletion/merging, new Current State semantics,
training, candidate promotion, additional sensors/services, wider private-cloud
permission, new contact cadence or synthetic data expansion. Historical failed
messages were not auto-resent. The daily 05:00 job still writes the previous
05:00–05:00 Diary and local improvement suggestions; it does not autonomously
rewrite Core/code overnight.

Semantic Goal deduplication/merging, general personal-Goal lifecycle language and
long-horizon memory consolidation still need controlled work. Repeating the same
Goal as a fresh message can create another Goal; request-idempotent retries are
protected. Fixing that should preserve genuine changed intentions and provenance.

## 12. Verification and evidence

Isolated databases: havre_daily_quality_test_20260906 and
havre_daily_quality_verify_20260906, localhost PostgreSQL port 55432. Fresh 0001→0068
and populated upgrades are exercised. No personal database was used for tests.

Protected/ignored artifacts live under var/daily-quality-20260906. Real provider
probes use constructed messages and a separate synthetic owner; no owner-private
logs or prompts were exported. GPT produced a concrete cross-device callback,
natural casual reply, and source-bound Goal creation with no unrequested reminders;
local-only routing also completed. One callback elaborated an unprovided detail,
so these probes do not prove calibrated companion quality. They did not load the
private OA70 bank and are not OA70 acceptance evidence.

Browser functional validation: 11 checks, zero JS errors, mobile and desktop,
Memory correction and repeat-conflict behavior, Diary navigation, real API submit,
offline/reconnect, history position and retry. Screenshots are local synthetic
fixtures, not physical iPhone evidence. Some fixture replies/Diary use deterministic
components and demonstrate UI functionality only.

Existing semantic retrieval benchmark: 12 cases, MiniLM top-one 9/12 versus hash
4/12, zero irrelevant admissions in that fixture; not new human-quality evidence.
Dependency check, contract export, compile and diff checks were run.

Final frozen-tree suite result is recorded in the verification addendum below.
An intermediate 745-test run had one Stage 8 finalization error: its stored
comparison explicitly recorded versions.code_revision as an uncontrolled
difference while source edits continued. No gate was weakened; final validation
must run with source edits paused.

## 13. Independent review P1/P2

The attempted external code-only review was blocked by the approval boundary.
No workaround or private-code export occurred. An independent existing local Qwen
review examined five bounded code areas, but produced demonstrably false claims
(decimal regex splitting, nonexistent PostgreSQL hash function, parameterized SQL
injection) and truncated opinions. It is preserved as limited evidence, **not a
credible zero-P1 signoff**. Strong independent review remains open pending permission.

Main-agent adversarial review closed the reproduced P1 state/queue atomicity and
shared-source erasure defects, plus the staged cross-session privacy regression.
P2 date-suffix recognition, misleading provider errors, hidden UI fields, desktop
layout and stale-history issues were tested. Remaining P2 work includes semantic
duplicate Goals, model latency and repeated real owner-use calibration.

## 14. Migration

Only new **0068_complete_reply_continuation_adapter.sql** is applied this iteration.
It admits old v2/new v3 exact authorized GPT receipts and rejects NULL provider
predicates. Direct SQL tests assert the exact CHECK constraint for NULL and unknown
providers. No existing migration bytes were rewritten. LF attributes pin the newly
tracked 0052–0068 files to their observed applied bytes.

## 15. Commits

- 9313fe1: preserved inherited audited source baseline (190 files).
- Implementation and final evidence commits are listed in the verification addendum.
- No push. Private review folders, raw runtime data, teaching archive and resume
  artifacts remain outside commits.

## 16. Next genuinely worthwhile work

Measure owner-visible latency and grounded continuity across ordinary real use,
without conflating provider ability with admission failures. Add provenance-safe
duplicate/changed-intent Goal handling; improve under-specified personal-goal
completion through source-bound clarification, not guessed writes. Evaluate
longer-term recall and contradictory/stale beliefs against exact experiences
before any canonical semantics change. Obtain physical iPhone cold notification,
keyboard/reconnect evidence and a stronger independent review. Do not claim that
more stages or larger prompts establish a better relationship.

## Verification addendum

Implementation commit: **e112b36** (42 files; inherited work is separate in 9313fe1).

- Frozen e112b36 primary suite: **745 passed, 0 failures, 0 errors, 0 skips** in
  81.728 seconds. Source revision before and after was identical:
  sha256:903fe17d88b652baa9ff6c488e4eac27b404eecf6f08d1af40f625b80e48ea59.
- Pinned Torch environment: **62 passed, 0 failures, 0 errors, 0 skips** in
  48.441 seconds. Combined distinct coverage: **807 tests**, zero skipped DB tests.
  No training/model promotion took place.
- Source-erasure + real-title completion + continuation regressions: 42 passed;
  direct NULL/unknown-provider CHECK test passed. These overlap the full suite.
- Fresh 0001→0068 installation: 744-test predecessor pass; final 745-test frozen
  run used that migrated dedicated database. Populated upgrade paths pass.
- CLI audit-provenance on the verification DB returned []; production repository
  provenance audit returned []; known course Goal's pending/leased queue count is 0.
- Live/readiness/version/timeline/Memory/Diary/settings production endpoints all
  returned HTTP 200. Provider version reports the v3 complete-reply adapter, exact
  GPT model/medium configuration and no active personalized adapter.
- Node PWA contract passed. Browser integration completed 11 checks with zero
  JavaScript errors. Final screenshots include final-chat-390.png,
  final-chat-1440.png, final-settings-390.png, final-memory-390.png,
  final-memory-edit-390.png, final-diary-390.png, final-memory-error-390.png and
  final-offline-draft-390.png under var/daily-quality-20260906.
- Contract schemas exported; pip check, compileall, PowerShell parser, and final
  working/staged diff checks passed. Original baseline Markdown whitespace was
  preserved in the historical checkpoint, not rewritten as new work.
- Final evidence-only documentation commit follows e112b36. No push.

No hardware-iPhone, repeated owner-use or strong independent-review signoff is
implied by these results. Raw owner audit records remain local and outside Git.
