# GPT Diary Intelligence and Paired Review Checkpoint

Date: **2026-09-03**

Decision: **ADR-0034 is implemented and active on the owner-local production
runtime by explicit Product Owner direction; formal ADR acceptance remains
pending. This is technical and runtime-path evidence, not physical-iPhone or
subjective Diary-quality acceptance.**

## Root cause

Diary v3 was a deterministic extractive projection. It scored owner phrases,
joined the highest-ranked clauses with separators, used up to three clauses for
the body, and truncated the first clause into an 18-character title. That removed
some governance noise but still produced message-like long titles and chronological
流水. It had no synthesis step capable of writing one coherent first-person day.

## Implemented behavior

- Only USER_MESSAGE and ASSISTANT_MESSAGE Events from completed ordinary
  interactions on the exact owner-local day are considered.
- Only Events already routed to openai-codex-chatgpt in the cloud with PUBLIC or
  NORMAL, cloud_eligible=true enter the high-effort Diary request.
- Private, highly private, local-only, local-route, incomplete, and otherwise
  ineligible Events never enter that request. The request receives only a count
  that unsupplied private Events exist.
- The strict result either omits a low-value day or writes a 4-12 character title
  and coherent first-person “我” diary. Greetings, acknowledgements, status chatter,
  technical logs, authorization mechanics, and transactional流水 are explicitly
  excluded.
- The local detail view exposes private messages only inside a separate collapsed
  purple box. The GPT-produced summary and non-private sources remain separate.
- At most three Memory and three User Model updates are admitted per run. Each must
  copy an exact quote from one eligible memory-eligible owner message and pass a
  conservative durable-statement filter. Private-derived understanding remains in
  the existing owner-confirmation flow.
- User Model activation does not bypass lifecycle governance: the service creates a
  candidate revision and one exact immutable activated transition in the same
  transaction.
- Every successful generation can return only fixed quality flags. The latest
  eligible flags map to code-owned response instructions for at most 14 days.
  Free-form provider output cannot modify code, prompts, Core, Identity, policy,
  tools, proactive authority, or privacy.
- The paired owner iPhone may perform the enumerated Memory candidate, Memory
  correction/retraction, confirmed-Memory-to-belief, and belief revision/transition
  writes. Device administration, settings, privacy export, worker control, Strong
  Brain, source erasure, and all broader owner-primary operations remain denied.
- Source erasure remains dormant until an exact source Event is newly named. Once
  named, the closure removes the affected mixed Diary run and every delegated
  Memory/belief derivative of that run.

## Persistence and migrations

- 0057_gpt_diary_intelligence_and_paired_review.sql adds immutable runs, exact
  source dispositions, Diary run linkage, delegated Memory/belief maps, and
  high-effort/provider receipts.
- 0058_diary_intelligence_provenance_guards.sql is an additive correction because
  0057 had already been applied to a disposable database. It leaves 0057 bytes
  unchanged, tightens cloud-summary admission to completed cloud GPT routes, and
  requires exact run/source/lifecycle/head/provenance closure for every delegated
  update.
- Fresh installation applied all 58 migrations. The populated 0042-to-current
  regression applied 0057 and 0058 additively and preserved its historical data.
- Production migration head is
  0058_diary_intelligence_provenance_guards.sql.

## Verification

### Automated

- Final unified PostgreSQL-backed suite: **735/735 passed, 0 failed, 0 errors,
  0 skipped** in 115.159 seconds. The existing pinned Stage 9A Torch 2.7.1+cu128
  site-packages were added to the test process path.
- The plain main environment first ran all 735 tests; its only ten errors were the
  known missing-Torch imports. No application assertion failed in that run.
- Focused paired-auth, Daily Companion, Diary, Codex provider, and PWA set:
  **59/59 passed**; executable PWA v5 contract passed.
- Diary PostgreSQL end to end proved high-effort request binding, exact first-person
  JSON, private-secret absence from the model request, active Memory creation,
  candidate-plus-transition belief activation, and source-erasure closure.
- Direct SQL attack probes returned SQLSTATE 55000 for a private Event relabelled as
  cloud_summary, a forged delegated Memory map, and a forged delegated belief map.
- Provenance audit returned [] on both the disposable test database and production.
- Contract schema export, bytecode compilation, pip check, and diff validation
  passed. Diff validation reported only existing Windows LF-to-CRLF warnings.

### Production

- The reviewed launcher applied exactly 0057 and 0058, rebuilt least-privilege
  credentials, and restarted API PID 672 plus worker PID 44064.
- Readiness is ready; failed Memory/proactive/offline jobs are 0/0/0.
- GPT-5.6-sol and the exact unadapted Qwen3-8B privacy route both report healthy.
- One active, unrevoked, unexpired paired iPhone exists in the production device
  registry.
- The production owner-day entry uses gpt-owner-day-diary-v4 with a seven-character
  title. The verified latest run used GPT-5.6-sol,
  codex-cli-reply-only-no-tools-v2-high, and high effort.
- That run partitioned 30 cloud-summary Events and 30 private-reference Events.
  Because the local aggregate retains the stricter source policy, the run itself is
  LOCAL_ONLY and cloud_eligible=false even though only its eligible partition was
  sent for synthesis.
- It created two delegated Memory and two delegated User Model updates. Manual
  owner-local readback found only interpretable life/course/communication statements,
  not migration, hash, queue, or authorization流水. Quality review returned zero
  flags for this run.
- No source Event or derivative was erased.

This evidence proves the application request builder excludes the private partition
and that the provider received the exact hash-bound eligible request through the
tested adapter. It is not an independent packet capture of provider transport bytes.

## Month typography palette

There is no universal official color for each month. The UI uses a restrained
seasonal inference: winter blues/evergreen, February berry, spring greens/violet,
summer blue/rust/gold, and autumn olive/orange/brown. This follows common monthly
color associations and Chicago's four-season context:

- monthly color reference:
  https://phdns.latahcountyid.gov/article/what-color-represents-each-month-of-the-year-monthly-color-calendar-guide
- Chicago seasonal context:
  https://www.choosechicago.com/blog/special-events/the-best-time-to-visit-chicago/

The twelve text colors are January #3d6b8a, February #8c4562, March #3f6f4e,
April #6f5687, May #2f6b4f, June #2f668f, July #94463f, August #805319,
September #5f6b3b, October #8a471d, November #704438, and December #2f6253.
Against the Diary paper background #fbfaf7, computed contrast ranges from 5.48:1
to 7.82:1, above the WCAG 2.2 normal-text minimum of 4.5:1:
https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html

## Remaining gates

1. The owner should refresh/reopen the iPhone PWA so the new service-worker asset
   cache and paired write controls load.
2. Physical iPhone Safari/PWA validation remains open: private box interaction,
   safe areas, keyboard, rotation, and month colors have not been observed on the
   actual device in this run.
3. Diary usefulness and automatic Memory/User Model precision require repeated
   owner judgment. The Practical Utility Gate remains open.
4. Formal ADR-0034 acceptance remains open.
5. No source erasure may run until the owner supplies the exact source Event.

No commit, push, pull request, training, model promotion, public exposure, private
cloud disclosure, or source erasure was performed.
