# Stage 4 Acceptance Correction Checkpoint (Historical, Not Accepted)

Status: **Historical: Product Owner reacceptance rejected; superseded by later correction checkpoints. Stage 5 was unauthorized at this checkpoint and was authorized later on 2026-08-14.**

Date: **2026-08-14**

Source snapshot: `sha256:06947a3ac5a455dc0a7b4c9ac42529b84ed3d7cdc76b5dcbf270a18792615044`

The Product Owner did not accept the first Stage 4 checkpoint and authorized
only the corrections recorded here. The Product Owner later rejected this
reacceptance snapshot as well. Current evidence is in
[`STAGE4_REACCEPTANCE_CORRECTION_CHECKPOINT.md`](STAGE4_REACCEPTANCE_CORRECTION_CHECKPOINT.md).
This historical file preserves its original source snapshot and evidence; it
does not self-approve Stage 4, authorize Stage 5, or activate proactive
interaction.

## Correction scope delivered

### Goal-progress policy propagation

- `record_goal_progress()` now conservatively combines the exact current Goal
  policy and every evidence-source policy before creating either the progress
  record or its `PROGRESS_RECORDED` lifecycle event.
- Ordinary application-path regressions prove `PRIVATE` Goal plus `NORMAL`
  evidence remains `PRIVATE`, `LOCAL_ONLY` Goal plus less-restrictive evidence
  remains `LOCAL_ONLY`, `LOCAL_ONLY` remains cloud-ineligible, and training
  eligibility remains false on both records and events.

### Pattern and progress proposal admission

- Both classes require at least two distinct supporting source identities and
  support on at least two distinct UTC dates.
- Aware occurrence timestamps are normalized with
  `astimezone(UTC).date()`. Naive occurrence timestamps are rejected rather
  than interpreted in the process or machine timezone.
- `pattern-proposal-distinct-days-v1` and
  `progress-proposal-distinct-days-v1` are the only recognized detector
  versions for those proposal classes; unsupported versions fail before a
  proposal or lifecycle event is written.
- Regressions cover two sources on one UTC date for both classes, two offset
  representations of one instant for both classes, naive timestamps, two real
  UTC dates producing pending-only proposals, and unsupported versions.

### Durable belief-head projection

- Additive migration `0008_stage4_acceptance_corrections.sql` replaces the
  `0007` guard function without modifying `0007`.
- A status-only projection update now requires exactly one fresh immutable
  transition for the same owner, belief, current revision, transition event,
  and permitted target status.
- A revision projection update must advance exactly one revision, reference
  the exact newly inserted same-owner immutable revision, point back to the
  previous revision, include the exact fresh `superseded` transition and
  immutable transition event, and project the new revision's permitted initial
  status.
- Direct SQL candidate-to-active and active-to-candidate bypasses fail with
  SQLSTATE `55000` and the `belief head guard` message. A skipped revision also
  fails in that guard before a foreign-key or status constraint can become the
  reason for rejection.

### Durable Goal projection

- Every Goal update must advance exactly one revision and reference one
  immutable same-owner `GOAL_UPDATED` or `GOAL_COMPLETED` event as appropriate.
- The event must be caused by the prior `last_event_id`; its payload Goal ID,
  revision, action, track, title, why, priority, status, next action, and review
  time must match the new projection; its complete DataPolicy must match the
  projection; and the new DataPolicy cannot be less restrictive than the old
  projection.
- Direct SQL regressions separately reject an unrelated event, a forged Goal
  ID payload, a skipped revision, a forged status, mismatched title content,
  wrong causation, and a weaker policy. Every case asserts SQLSTATE `55000` and
  a `goal projection guard` message so another constraint cannot produce a
  false pass.

### Foreign-key indexes

- Migration `0008` adds FK-side composite indexes for belief supersession and
  replacement revisions; proposal accepted memory, created event, review
  event, and trace; Current State created event and trace; Goal last event; and
  Goal-progress created event and trace.
- The existing partial generated-column provenance indexes from migrations
  `0004` and `0007` were reviewed and retained rather than duplicated.
- A catalog query over every Stage 4 foreign key returned `[]` for referencing
  relationships without a covering index.

## Immutable migration boundary

The pre-correction hashes were captured before implementation and rechecked
after final verification. Migrations `0001`-`0007` retained the same bytes:

- `0001_stage1_foundation.sql`: `b5d38a27ca58e1f665ebba5f0e55be99d0690f63b0f0bcb9e352156eb9c4799a`
- `0002_stage1_corrections.sql`: `9d2b839b258e0e1764769100f0afd926caefff703aa4319a85e36b21e77b0303`
- `0003_stage2_episodic_memory.sql`: `59a8ba1fc8887c89d3759c6f0848b52b348d9ad12043c6e418600a134629e023`
- `0004_stage2_acceptance_corrections.sql`: `49cdac396e3871630009ed52a13470aa555f0c455f9a756c392b86a156fa1cd4`
- `0005_stage3_self_hosted_inference.sql`: `6ce48a5599eb6af3e9bc1aabef84532d99e2c5739d231573e6b4954980c16434`
- `0006_stage3_runtime_attestation.sql`: `d1a5e99e9b0ad1baaadb40fc9de19156796ff567149165b719ee16da06eff411`
- `0007_stage4_user_model_goals.sql`: `d8b19039939c38b3d55057c8db9b40460287eb3769f68c45d14c7f2427cbfdd5`

The new migration hash is:

- `0008_stage4_acceptance_corrections.sql`: `3f204df33e82382400bf88bfc5896c5a9075747a9ab508a4c864f98043b6dc58`

## PostgreSQL reacceptance evidence

Environment: Windows 11, CPython 3.12.13, Psycopg 3.3.4, PostgreSQL
18.4, and pgvector 0.8.1. The owner-controlled WSL cluster remained bound to
`127.0.0.1:55432` and was returned to its prior stopped state after evidence
collection.

### Fresh path

- Database: `havre_s4_reaccept_fresh_20260814`
- Migration result: applied `0001` through `0008` in exact order.
- Final complete suite: **170 passed, 0 failed, 0 skipped** in **22.537 s**.
- Provenance audit: `[]`.
- The direct-SQL projection regressions and Stage 4 source-erasure closure ran
  inside this complete pass.

### Populated in-place upgrade path

- Database: `havre_s4_reaccept_upgrade_20260814`
- Exact `0001`-`0007` was installed first. The repeatable fixture in
  `scripts/populate_stage4_upgrade_fixture.py` then created two durable source
  interactions, belief revision 2 plus activation/supersession transitions,
  Current State, Goal revision 2, Goal progress, a reviewed pattern proposal,
  and its accepted memory. Its pre-upgrade provenance audit was `[]`.
- Applying the repository migration set afterward applied only
  `0008_stage4_acceptance_corrections.sql`.
- Final complete suite: **170 passed, 0 failed, 0 skipped** in **22.573 s**.
- Post-upgrade provenance audit: `[]`.
- The same direct-SQL projection regressions and Stage 4 source-erasure closure
  ran inside this complete pass.

Both databases are intentionally preserved for Product Owner review. They were
not dropped or rewritten; they are available after restarting the dedicated
cluster.

## Additional checks

- `python -m scripts.export_contract_schemas`: passed; committed schemas match
  the active typed contracts.
- `python -m pip check`: `No broken requirements found.`
- `python -m compileall -q companion contracts identity mlsys scripts services tests`:
  passed.
- `git diff --check`: passed.
- Stage 4 referencing-FK catalog audit: no uncovered relationship (`[]`).
- Old benchmark and Stage 4 report directories were not modified.

## Regenerated synthetic report

New artifact:
`evals/reports/stage4_20260814_reacceptance/user-model-evaluation.json`

- Report file SHA-256: `f4893660a6d021816dd6a165463f4d8942d83b2488a8b12326b7552926a41ba3`
- Internal content hash: `sha256:c4542d7500a73b2fedf213baf306da0c1abaf324736308ec260b5c98bff3af76`
- Bound source snapshot:
  `sha256:06947a3ac5a455dc0a7b4c9ac42529b84ed3d7cdc76b5dcbf270a18792615044`
- Result: 8/8 synthetic cases passed; false-stability count `0`;
  counter-evidence retention `1.0`; confidence calibration
  `not_evaluated_owner_reviewed_only`.
- `binding_evaluation = false` and `gate_status = not_evaluated` remain
  explicit. Component latency is in-process fixture timing only.

The original `evals/reports/stage4_20260814/` report remains unchanged as
historical evidence. No Stage 3 benchmark report was modified.

## Honest limits

- The PostgreSQL tests establish the implemented contracts, exact forbidden
  relationships, migration paths, owner isolation, provenance, and erasure
  behavior in the dedicated acceptance environment. They do not establish a
  production permission model or operational deployment path.
- The synthetic evaluation is small, deterministic, non-binding, and not
  evidence of broad semantic understanding, calibration, longitudinal benefit,
  production conversation quality, or a stable human trait.
- Durable confidence remains owner-reviewed. No automatic confidence updater,
  outcome scale, intervention threshold, Scene system, training pipeline,
  personalized release, or proactive runtime is active.

## Reacceptance and stop boundary

This correction snapshot did not pass Product Owner reacceptance. It is
superseded by
[`STAGE4_REACCEPTANCE_CORRECTION_CHECKPOINT.md`](STAGE4_REACCEPTANCE_CORRECTION_CHECKPOINT.md).
**Do not commit, push, begin Stage 5, or activate proactive runtime without a
new explicit Product Owner decision.**
