# Automatic Proactive Reach Out checkpoint

Date: 2026-08-27
Classification: PRIVATE / owner-local activation evidence

## Result

The previously accepted Stage 6 policy and delivery chain is now fed by one
versioned automatic evaluator. It does not create a second proactive system.
The runtime path is:

`Event -> evaluation -> work -> Trigger -> Proposal -> InterruptionPolicy ->`
`durable ASSISTANT_MESSAGE -> Web Push dispatch/receipt -> same timeline`.

Only explicit time-bound owner reminders, current active Goal `review_at`, and
current planned Scene `planned_start_at` have trigger authority. Memory,
Calendar/Life Context, Current State, beliefs, ordinary chat, and elapsed
silence are context-only or ignored.

## Implementation

- `proactive-trigger-evaluator-v1` records immutable source-bound evaluations
  and idempotently enqueues due work.
- Additive migration 0049 adds evaluation provenance, exact source/hash/type
  database guards, and the governed generic-LOCAL_ONLY Push admission rule.
- Additive migration 0050 admits historical renderer v1 and natural renderer
  v2 without rewriting an applied migration.
- Work rechecks exact Goal/Scene projection state before execution and cancels
  stale work.
- `proactive-natural-template-v2` renders concise reminder/Goal/Scene messages
  only after `SEND_NOW`.
- Source erasure removes evaluations and derivatives only when the erased Event
  is the evaluator's exact source. Erasing a proactive output does not erase
  its origin provenance chain.
- Settings correctly round-trip `cooldown_seconds=null` and empty quiet hours.
  The UI states the three trigger sources and the context-only sources.
- Web Push admits LOCAL_ONLY only from an exact decision preference revision
  with `generic_push_for_local_only=true`; both enqueue and send recheck it.

## Owner-local activation

The owner database `havre_local_20260822` applied only migrations 0049 and
0050. The existing protected launcher restarted the same owner-local runtime.
Preference revision 15 is current with:

- Reach Out enabled;
- category `owner_reminder` allowed;
- `web_inbox` as the only channel;
- generic-private preview;
- global/category 24-hour budgets of 10;
- no cooldown;
- no quiet hours;
- `generic_push_for_local_only=true`;
- Product Owner authorization reference
  `product-owner-chat-authorize-automatic-reach-out-and-local-only-generic-push-2026-08-27`.

After one worker tick, the historical scan recorded 32 ignored evaluations:
29 ordinary/non-reminder user messages and 3 context-only Events. It created
zero automatic work. This is evidence that activation did not turn old chat,
Memory, or context into outreach.

The post-restart Product Settings readback reported Web Push available, worker
live, runtime ready, delivery active, and current-shell real-device validation
all true. `qwen3-8b-stage9a-qlora-seed-9201` remains the default local binding.

## Verification

- Focused automatic-trigger suite: 8/8 passed.
- Daily Companion module: 31/31 passed.
- Exact non-Torch repository suite: 599/599 passed, zero failures and zero
  skips, against a fresh dedicated database migrated 0001 through 0050.
- Full discovery contains 609 tests. The ten excluded tests are exact Stage 9A
  training tests that require Torch, which is absent from this interpreter;
  no database/product test was excluded.
- Stage 8 PostgreSQL regression: 10/10 passed.
- Contract schemas, Stage 6 schemas, populated 0042-to-0050 upgrade, and Stage
  10 current-head health regression passed.
- Provenance audit returned `[]`; Stage 6 and Stage 10 FK audits returned `[]`.
- `pip check` reported no broken requirements. Compileall and
  `git diff --check` passed.
- Paired privacy tests prove unapproved LOCAL_ONLY makes no sender call, while
  exact authorization sends only title/body/locator/URL.
- Forged evaluation source hash is rejected by PostgreSQL. Relevant Goal/Scene
  revision changes cancel queued work. Exact evaluator-source erasure removes
  the derived chain without deleting unrelated proactive provenance.

## Limits and stop boundary

Synthetic and database evidence establish wiring, provenance, policy, privacy,
and cancellation behavior. A new real automatic owner reminder still requires
the owner to send an explicit reminder in HAVRE and confirm the locked-iPhone
arrival; prior Web Push physical evidence establishes the delivery adapter but
not this newly automatic trigger source.
