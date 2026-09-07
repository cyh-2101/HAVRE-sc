# Experience-first daily review checkpoint

- Date: 2026-09-04
- Scope: owner-local ADR-0035 implementation authorized by the Product Owner
- Current production migration head: `0060_owner_conversation_continuation.sql`
- Formal ADR-0035 acceptance: open
- Practical Utility Gate: open

## Implemented owner experience

- A mandatory provider-facing instruction applies the owner's “chat like a
  person first, solve like an AI second” behavior without pretending to remember
  evidence that is absent.
- The exact OA70 cases 1-70 are derived into the owner-only GPT runtime example
  bank. At most three relevant cases enter a turn. The frozen source is unchanged;
  this is not training, tuning, declassification, or independent holdout evidence.
- Diary v5 runs from the owner-local worker after 05:00 for the just-finished
  prior day. GET endpoints do not generate it. The high-effort request receives
  only eligible GPT-routed PUBLIC/NORMAL current-day evidence, bounded eligible
  prior context, and bounded current eligible Memory.
- Greetings, acknowledgements, operational status, governance mechanics, and
  other low-value流水 do not create a Diary. A meaningful result is a coherent
  first-person narrative. Private/local content stays out of the GPT request and
  remains available only in the local collapsed transcript detail.
- Each successful review may write one evidence-ID-bound Markdown suggestion
  under `owner_improvement_reviews/`. It contains no transcript and cannot edit
  code, Identity, values, policy, or configuration.
- Eligible GPT-chat evidence may create exact-quote delegated Memory/User Model
  updates. Private/local evidence still requires owner review.
- Only explicit Goal/plan/reminder language opens the high-effort chat Goal
  planner. A Goal or reminder is described as saved only after a durable action
  receipt exists.
- `relationship_follow_up` may use exact current conversation/Memory evidence,
  but preference, stop, quiet hours, one-per-24-hour category budget,
  deduplication, expiry, and delivery remain Core decisions.
- “记得” removes hashes, confidence scores, raw JSON, and implementation labels;
  course assignments/exams are grouped by course and other explicit Goals remain
  separate. Diary month headings use twelve distinct contrast-checked colors.
- One durable assistant Event may be rendered as multiple short bubbles without
  inventing extra model turns or Events.

## Persistence and erasure closure

Migration 0059 adds owner/date review schedule receipts, bounded prior-Event and
Memory source membership, exact generated-file receipts, explicit chat Goal
plan/action receipts, and Memory/conversation proactive source kinds. When the
owner later names an exact source Event for privileged erasure, its derived
Diary/review files, delegated understanding, Goals, reminders, projections,
fusion claims, proactive work, and receipts are closed before raw source removal.
Activation selected and erased no production source.

## Verification

The dedicated PostgreSQL-backed verification completed with zero database skips:

- primary non-Torch suite: 678/678 passed;
- pinned-Torch suite: 62/62 passed;
- combined: 740/740 passed;
- focused Diary intelligence suite: 5/5 passed, including explicit 04:59 no-run
  and 05:01 run scheduling cases;
- PWA contract: passed;
- main and pinned environment `pip check`: passed;
- contract schema export and equality checks: passed;
- Python compile: passed;
- disposable-database provenance audit: `[]`;
- owner production provenance audit after migration 0059: `[]`;
- twelve month colors measured 5.48:1 through 7.82:1 against `#fbfaf7`.

After the first real production schedule exposed provider enum drift, the final
repository verification was repeated on a fresh dedicated database:

- Diary intelligence module: 8/8 passed, including conservative optional-output
  repair and a PostgreSQL proof that persisted backoff does not call the provider
  or increment attempts early;
- primary non-Torch suite: 695/695 passed;
- pinned-Torch suite: 62/62 passed;
- combined: 757/757 passed, zero database skips;
- disposable and production provenance audits: `[]`;
- main and pinned `pip check`, compileall, PWA executable contract, and
  `git diff --check`: passed.

The owner-local production runtime was restarted with GPT-5.6-sol for eligible
cloud requests and the exact unadapted Qwen3-8B local privacy route. The derived
OA70 bank contains 70 entries with content hash
`sha256:ef90ae212622356ebbab8ae5d6e3ec0a74a097eddbc3df102330df792730a43e`.
The API and worker were ready, migration 0059 was present, the worker
heartbeat was live, and no proactive delivery occurred during the first
15-minute activation observation.

## Production incident and correction

The first owner read of “记得” after activation exposed a missing `re` import in
the friendly course task grouping path. This was not exercised by the earlier
fixtures because they did not combine the endpoint with an active course
projection. The import was restored, task grouping was isolated behind a helper,
and a regression now executes both exam and assignment titles. After restart:

- `GET /v1/product/memory` returned HTTP 200;
- `GET /v1/diary?limit=90` returned HTTP 200.

No owner record was removed or rewritten by this correction.

### First real 05:00 review

The naturally due 2026-09-03 production review first failed because GPT returned
valid Diary content but used near-synonym values such as
`overconfident_claim`, `communication_preference`, and
`natural_continuation` in strict optional enum fields. The worker marked the
result retryable but immediately reclaimed it, producing 38 durable
`ValidationError` run receipts and 40 attempts before diagnosis.

The correction does not loosen source, privacy, or durable-update validation:

- the provider prompt enumerates every allowed belief, improvement, quality, and
  follow-up value;
- malformed optional Memory/User Model effects are dropped rather than blocking a
  valid Diary;
- one explicit belief alias and three explicit follow-up aliases are normalized;
- unknown improvement categories enter the existing `experience` catch-all,
  while supplied Event membership is still checked before the suggestion survives;
- retryable schedule receipts use persisted 1-minute, 5-minute, 15-minute,
  1-hour, then 6-hour backoff.

After complete verification and controlled restart, attempt 41 completed once
with `openai-codex-chatgpt` / `gpt-5.6-sol` / high effort. The receipt
records an included 7-character title, a 266-character first-person Diary, three
evidence-bound improvement suggestions, no automatic Memory write, and one exact-
source User Model update. Its Markdown suggestion file exists under
`owner_improvement_reviews/`, matches the durable SHA-256 receipt, and does
not contain copied transcript text. Memory and Diary returned HTTP 200, the
worker error log remained empty after restart, and production provenance was
`[]`. No production source Event was erased.

A non-content quality probe found no terminal punctuation in the title, zero
technical/governance markers, zero sequential “then/after that” transition
markers, and five sentences in the Diary body. This supports the requested
short-title/non-log structure but is not a substitute for the owner's reading.

## Evidence not yet established

- The first naturally scheduled production 05:00 run has completed, but the owner
  has not yet judged whether its wording and selected facts are genuinely useful.
- A physical iPhone screenshot/interaction acceptance run has not been completed.
- The in-app browser screenshot audit was blocked by the Windows UI automation
  helper during this task; code and contract checks are not a substitute for a
  visual accessibility audit.
- Green tests do not establish that Diary summaries, relationship follow-ups, or
  ordinary conversations feel like a good friend over repeated real use.
- Formal ADR-0035 acceptance remains a separate Product Owner decision.

## Current stop boundary

Do not upload PRIVATE/HIGHLY_PRIVATE/LOCAL_ONLY conversation to GPT, silently
fall back across providers, use OA70 for training/tuning/public release, let a
model own interruption authority, infer course completion without an explicit
owner statement, erase a source that the owner has not newly and exactly named,
or let generated review suggestions modify the product automatically.
