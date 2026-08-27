# Stage 4 Goal Canonical Projection Correction Checkpoint

Status: **Historical: Product Owner reacceptance blocked; superseded by the Goal INSERT guard correction checkpoint. Stage 5 was unauthorized at this checkpoint and was authorized later on 2026-08-14.**

Date: **2026-08-14**

Execution-source snapshot: `sha256:0584255c42e797f75116a1da01675c9c1989dc7074c8129d3913698371cc2ebd`

This document preserves the exact canonical-projection evidence for its
recorded snapshot. It was superseded after a raw SQL probe proved that
`havre.goals` had no INSERT guard. Current evidence is in
[`STAGE4_GOAL_INSERT_GUARD_CHECKPOINT.md`](STAGE4_GOAL_INSERT_GUARD_CHECKPOINT.md).

The Product Owner rejected the second reacceptance checkpoint and authorized
only the Goal canonical-projection completeness correction recorded here. This
checkpoint does not self-approve Stage 4, authorize Stage 5, permit a commit or
push, or activate proactive interaction.

## Correction delivered

- Additive migration `0010_stage4_goal_canonical_projection.sql` replaces the
  active Goal projection guard without modifying migrations `0001`-`0009`.
- `GoalProjectionMaterial` is the exact typed hash material. It and its nested
  `GoalProjectionDataPolicy` are frozen, strict, `extra="forbid"` contracts;
  all top-level and policy keys are required. Aware `review_at` values are
  normalized to UTC before canonical serialization.
- Goal construction validates this material before computing `content_hash`.
  `GoalLifecyclePayload` reparses `projection_canonical_json` through the same
  strict contract, requires the one application canonical representation, and
  only then checks its digest.
- PostgreSQL verifies the exact top-level and nested key sets. It reconstructs
  canonical JSON from the guarded `NEW` Goal row, compares the supplied string
  byte-for-byte, and computes the accepted SHA-256 digest from that reconstructed
  material rather than trusting an opaque caller string or hash.
- The direct-SQL attack fixtures bypass all Goal/Pydantic construction. They
  insert raw immutable events containing a top-level extra key, a DataPolicy
  extra key, reordered/whitespace JSON, a missing required key, or a wrong
  schema value. Each fixture carries a hash matching its own raw JSON. Every
  attempted Goal update is rejected with SQLSTATE `55000` and a
  `goal projection guard` error. An ordinary update containing quotes,
  backslashes, a newline, Unicode, and a microsecond timestamp succeeds,
  proving application/database canonical agreement on the normal path.

## Immutable migration boundary

Hashes rechecked after final verification:

- `0001_stage1_foundation.sql`: `b5d38a27ca58e1f665ebba5f0e55be99d0690f63b0f0bcb9e352156eb9c4799a`
- `0002_stage1_corrections.sql`: `9d2b839b258e0e1764769100f0afd926caefff703aa4319a85e36b21e77b0303`
- `0003_stage2_episodic_memory.sql`: `59a8ba1fc8887c89d3759c6f0848b52b348d9ad12043c6e418600a134629e023`
- `0004_stage2_acceptance_corrections.sql`: `49cdac396e3871630009ed52a13470aa555f0c455f9a756c392b86a156fa1cd4`
- `0005_stage3_self_hosted_inference.sql`: `6ce48a5599eb6af3e9bc1aabef84532d99e2c5739d231573e6b4954980c16434`
- `0006_stage3_runtime_attestation.sql`: `d1a5e99e9b0ad1baaadb40fc9de19156796ff567149165b719ee16da06eff411`
- `0007_stage4_user_model_goals.sql`: `d8b19039939c38b3d55057c8db9b40460287eb3769f68c45d14c7f2427cbfdd5`
- `0008_stage4_acceptance_corrections.sql`: `3f204df33e82382400bf88bfc5896c5a9075747a9ab508a4c864f98043b6dc58`
- `0009_stage4_reacceptance_corrections.sql`: `42c0f42774bbca2e7da805d9889cc6e40af8daa28a7b1b5599641cff163a6a34`
- `0010_stage4_goal_canonical_projection.sql`: `e1eea4b31a8be3073ab64c0d807cca8429b38bb70a3958aa81675063a3235e74`

The recorded `0001`-`0009` hashes are unchanged.

## PostgreSQL verification evidence

Environment: Windows 11, CPython 3.12.13, Psycopg 3.3.4, PostgreSQL
18.4, and pgvector 0.8.1.

### Fresh `0001`-`0010`

- Preserved database: `havre_s4_reaccept_0010_fresh_20260814`.
- Migration result: `0001` through `0010` applied in exact order.
- Complete suite: **174 passed, 0 failed, 0 skipped** in **33.300 s**.
- Provenance audit: `[]`.
- Full Stage 4 referencing-FK catalog audit: `[]`.
- Raw Goal canonical-bypass probes and Stage 4 erasure closure passed inside
  the complete suite; the new Goal probes were also rerun alone and passed.

### Populated `0009` to `0010` in-place upgrade

- Preserved database: `havre_s4_reaccept_0010_upgrade_20260814`.
- The retained populated `havre_s4_reaccept_0009_upgrade_20260814` database was
  verified to contain exact migrations `0001`-`0009`, 196 events, 6 belief
  revisions, 6 Goals, 4 Goal progress records, 4 consolidation proposals, and
  40 provenance edges before cloning. Its pre-upgrade provenance and FK audits
  were both `[]`.
- Applying the current migration set to the clone applied only
  `0010_stage4_goal_canonical_projection.sql`.
- Complete suite: **174 passed, 0 failed, 0 skipped** in **23.249 s**.
- Post-upgrade provenance audit: `[]`.
- Full Stage 4 referencing-FK catalog audit: `[]`.
- Raw Goal canonical-bypass probes and Stage 4 erasure closure passed inside
  the complete suite; the new Goal probes were also rerun alone and passed.

Both final databases are preserved for Product Owner review. The dedicated
PostgreSQL cluster was returned to its prior stopped state after verification.

## Repeatability and generated evidence

New report directory:
`evals/reports/stage4_20260814_canonical_correction/`

Belief replay stability report:

- file: `belief-replay-stability.json`;
- file SHA-256: `d63abb4559b6682271e008e7d6811ab366898dac86fb356f177caf6df41f2a22`;
- internal content hash: `sha256:ad47f3c9e9da4490a879be0556704ddf752df8dd3789dc738c70e0be2ff07160`;
- source snapshot: `sha256:0584255c42e797f75116a1da01675c9c1989dc7074c8129d3913698371cc2ebd`;
- result: **100 completed, 100 passed, 0 failed**, with one independent
  Python process per repetition.

Regenerated synthetic User Model report:

- file: `user-model-evaluation.json`;
- file SHA-256: `35d9447358a5defa992349f97edffcc1c3f7da8aab34fd492dc25392ac1fc4df`;
- internal content hash: `sha256:c80bbfa07e2498a85de7313d08890fcb8973574b6ee70c3374c64c500e33c831`;
- source snapshot: `sha256:0584255c42e797f75116a1da01675c9c1989dc7074c8129d3913698371cc2ebd`;
- result: 8/8 synthetic cases passed, false-stability count `0`, and
  counter-evidence retention `1.0`;
- `binding_evaluation = false`, `gate_status = not_evaluated`, and confidence
  calibration remains explicitly unevaluated.

All earlier Stage 4 reports and old benchmark reports remain unchanged.

## Additional checks

- `python -m scripts.export_contract_schemas`: passed; the new
  `goal-projection-material-v1.json` schema has SHA-256
  `b66f564ab0a21c0e5d1db7c5dbae7fd77be8ab3e7b0fad5350d5c1636925cd52`.
- `python -m pip check`: passed.
- `python -m compileall -q companion contracts identity mlsys scripts services tests`:
  passed.
- `git diff --check`: passed.
- Final execution-source snapshot recheck:
  `sha256:0584255c42e797f75116a1da01675c9c1989dc7074c8129d3913698371cc2ebd`.

## Limits and stop boundary

The frozen synthetic suite and deterministic lexical/proposal components do not
establish production semantic quality, confidence calibration, longitudinal
benefit, or a personalized model release. No Stage 5 or proactive runtime
capability was implemented or activated.

The next allowed action is Product Owner reacceptance or another bounded Stage
4 correction request. **Do not commit, push, begin Stage 5, or activate
proactive runtime without a new explicit Product Owner decision.**
