# Stage 4 Second Reacceptance Correction Checkpoint

Status: **Historical: Product Owner reacceptance rejected; superseded by the Goal canonical projection correction checkpoint. Stage 5 was unauthorized at this checkpoint and was authorized later on 2026-08-14.**

Date: **2026-08-14**

Source snapshot: `sha256:e65a76d653c9c1be837b93165b983e516968450b8cd8022d710a5fad04531dee`

This document preserves the exact second-reacceptance evidence for its recorded
snapshot. It was rejected because Goal canonical projection completeness was
not enforced. Current correction evidence is in
[`STAGE4_GOAL_CANONICAL_PROJECTION_CHECKPOINT.md`](STAGE4_GOAL_CANONICAL_PROJECTION_CHECKPOINT.md).

The Product Owner rejected the prior correction checkpoint and authorized only
the bounded corrections recorded here. This checkpoint does not self-approve
Stage 4, authorize Stage 5, permit a commit or push, or activate proactive
interaction.

## Corrections delivered

### Belief projection identity and replay ordering

- Additive migration `0009_stage4_reacceptance_corrections.sql` replaces the
  active belief-head guard without modifying migrations `0001`-`0008`.
- Every head update carries an explicit immutable transition ID qualified by
  owner, belief, and source revision. The new immutable consumption table makes
  each transition identity single-use; all pre-`0009` transitions are consumed
  during upgrade so they cannot be replayed afterward.
- The guard validates exact status/revision/transition/event relationships and
  uses PostgreSQL statement time for the head update. It contains no comparison
  between application `recorded_at` and database `updated_at`.
- Belief revision creation time, transition recording time, and default
  `known_as_of` cutoff now come from PostgreSQL. This removed the Windows clock
  resolution race found during the first final-suite attempt.
- The exact bitemporal replay integration test ran sequentially in 100 separate
  Python processes and passed **100/100**.

### Goal projection hash and time binding

- New Goal lifecycle events carry the full canonical new projection material
  and its SHA-256 content hash. The database guard verifies the digest and every
  projection field, including owner, Goal/event identity, revision, content,
  status, and complete DataPolicy.
- Goal `updated_at` is assigned by the same PostgreSQL `UPDATE` statement and
  must equal its `statement_timestamp()`; an application or direct SQL caller
  cannot supply a future time.
- Direct SQL probes assert SQLSTATE `55000` and a `goal projection guard`
  message for an unrelated event, forged payload, skipped revision, forged
  status, mismatched content, wrong causation, weaker policy, forged hash,
  future timestamp, and hash/content mismatch. They therefore cannot pass
  incidentally through a foreign key or check constraint.

### Foreign-key index closure

- `provenance_edges_owner_derived_memory_fk_idx` covers
  `(owner_id, derived_memory_id, derived_memory_revision)` while retaining the
  other partial generated-column provenance indexes.
- Migration `0009` also indexes its new belief transition-consumption and
  head-transition foreign keys.
- The reusable catalog audit checks every FK on the active Stage 4 tables for a
  matching referencing-index prefix. It returned `[]` on both final databases.

## Immutable migration boundary

Hashes captured after final verification:

- `0001_stage1_foundation.sql`: `b5d38a27ca58e1f665ebba5f0e55be99d0690f63b0f0bcb9e352156eb9c4799a`
- `0002_stage1_corrections.sql`: `9d2b839b258e0e1764769100f0afd926caefff703aa4319a85e36b21e77b0303`
- `0003_stage2_episodic_memory.sql`: `59a8ba1fc8887c89d3759c6f0848b52b348d9ad12043c6e418600a134629e023`
- `0004_stage2_acceptance_corrections.sql`: `49cdac396e3871630009ed52a13470aa555f0c455f9a756c392b86a156fa1cd4`
- `0005_stage3_self_hosted_inference.sql`: `6ce48a5599eb6af3e9bc1aabef84532d99e2c5739d231573e6b4954980c16434`
- `0006_stage3_runtime_attestation.sql`: `d1a5e99e9b0ad1baaadb40fc9de19156796ff567149165b719ee16da06eff411`
- `0007_stage4_user_model_goals.sql`: `d8b19039939c38b3d55057c8db9b40460287eb3769f68c45d14c7f2427cbfdd5`
- `0008_stage4_acceptance_corrections.sql`: `3f204df33e82382400bf88bfc5896c5a9075747a9ab508a4c864f98043b6dc58`
- `0009_stage4_reacceptance_corrections.sql`: `42c0f42774bbca2e7da805d9889cc6e40af8daa28a7b1b5599641cff163a6a34`

The recorded hashes for `0001`-`0008` are unchanged from the prior checkpoint.

## PostgreSQL reacceptance evidence

Environment: Windows 11, CPython 3.12.13, Psycopg 3.3.4, PostgreSQL
18.4, and pgvector 0.8.1.

### Fresh `0001`-`0009`

- Preserved database: `havre_s4_reaccept_0009_fresh_20260814`.
- Migration result: `0001` through `0009` applied in exact order.
- Final complete suite: **171 passed, 0 failed, 0 skipped** in **22.906 s**.
- Provenance audit: `[]`.
- Stage 4 FK-index catalog audit: `[]`.
- Exact Goal SQL probes and Stage 4 source-erasure closure passed inside the
  complete suite; the Goal probes were also rerun alone and passed.

The first complete-suite attempt on this database exposed the replay cutoff
race described above. It was not counted as final evidence. After the database
time correction and the 100-process stability run, the complete suite was
rerun and produced the zero-failure result reported here.

### Populated `0008` to `0009` in-place upgrade

- Preserved database: `havre_s4_reaccept_0009_upgrade_20260814`.
- Exact migrations `0001`-`0008` were installed first. The upgrade fixture
  created source events, a belief/head and immutable activation transition,
  Current State, a two-revision Goal, Goal progress, a pending/accepted pattern
  proposal, accepted memory, and provenance; its pre-upgrade provenance audit
  was `[]`.
- Applying the repository migration set afterward applied only
  `0009_stage4_reacceptance_corrections.sql`.
- The exact pre-`0009` transition ID
  `019fff78-d317-7223-8d31-1a90f89b70e4` has one immutable consumption row
  after upgrade.
- Final complete suite: **171 passed, 0 failed, 0 skipped** in **22.722 s**.
- Post-upgrade provenance audit: `[]`.
- Stage 4 FK-index catalog audit: `[]`.
- Exact Goal SQL probes and Stage 4 source-erasure closure passed inside the
  complete suite; the Goal probes were also rerun alone and passed.

Both final databases are intentionally preserved for Product Owner review.
The dedicated PostgreSQL cluster was returned to its prior stopped state after
verification.

## Repeatability and generated evidence

New report directory:
`evals/reports/stage4_20260814_reacceptance2/`

Belief replay stability report:

- file: `belief-replay-stability.json`;
- file SHA-256: `bd905ca4fbc2e43fcdd1d02f8768064465a9257dae6e772f5e05d840c748e782`;
- internal content hash: `sha256:bcc0b00ba2c6a0f2ddf97a2a1f9c565eb09e3cf665ea84879ca3a4b2b7e62562`;
- source snapshot: `sha256:e65a76d653c9c1be837b93165b983e516968450b8cd8022d710a5fad04531dee`;
- result: **100 completed, 100 passed, 0 failed**, with one independent
  process per repetition.

Regenerated synthetic User Model report:

- file: `user-model-evaluation.json`;
- file SHA-256: `d277adcf196da3786a34ed9381d9282a594f4702276b2b7679b2a58e84264d6e`;
- internal content hash: `sha256:608c1478130a6d7bd2e67e0cf2749fa0127a992bbea5c258cee7e90ff840808d`;
- source snapshot: `sha256:e65a76d653c9c1be837b93165b983e516968450b8cd8022d710a5fad04531dee`;
- result: 8/8 synthetic cases passed, false-stability count `0`, and
  counter-evidence retention `1.0`;
- `binding_evaluation = false`, `gate_status = not_evaluated`, and confidence
  calibration remains explicitly unevaluated.

The earlier Stage 4 report directories and old benchmark reports were not
modified.

## Additional checks

- `python -m scripts.export_contract_schemas`: passed; exported schemas match
  the typed contracts.
- `python -m pip check`: `No broken requirements found.`
- `python -m compileall -q companion contracts identity mlsys scripts services tests`:
  passed.
- `git diff --check`: passed; line-ending notices were warnings only.
- Final execution-source snapshot recheck:
  `sha256:e65a76d653c9c1be837b93165b983e516968450b8cd8022d710a5fad04531dee`.

## Limits and stop boundary

The frozen synthetic suite and deterministic lexical/proposal components do not
establish production semantic quality, confidence calibration, longitudinal
benefit, or a personalized model release. No Stage 5 or proactive runtime
capability was implemented or activated.

The next allowed action is Product Owner reacceptance or another bounded Stage
4 correction request. **Do not commit, push, begin Stage 5, or activate
proactive runtime without a new explicit Product Owner decision.**
