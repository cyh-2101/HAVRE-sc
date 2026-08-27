# Stage 4 Goal Insert Guard Correction Checkpoint

Status: **Historical correction snapshot; superseded by the required-provenance correction checkpoint. Stage 5 was unauthorized at this checkpoint and was authorized later on 2026-08-14.**

Date: **2026-08-14**

Execution-source snapshot: `sha256:b42356bdd0290175f67e364b3336acf7423656e5935794e320c937acfb3ba715`

This checkpoint preserves the exact `0011` evidence. The current gate and
newer correction evidence are in
[`STAGE4_REQUIRED_PROVENANCE_CORRECTION_CHECKPOINT.md`](STAGE4_REQUIRED_PROVENANCE_CORRECTION_CHECKPOINT.md).

The Product Owner identified that the prior Goal guard covered UPDATE and
DELETE but not INSERT. This checkpoint records only the bounded initial Goal
projection correction. It does not self-approve Stage 4, authorize Stage 5,
permit a commit or push, or activate proactive interaction.

## Correction delivered

- Additive migration `0011_stage4_goal_insert_guard.sql` adds a dedicated
  `BEFORE INSERT` trigger without modifying migrations `0001`-`0010`.
- Every initial Goal must be active revision 1 and point to one immutable,
  same-owner `GOAL_CREATED` event whose causation is another same-owner event.
  The lifecycle payload content, policy, Goal/event identity, and revision must
  exactly match the inserted row.
- The INSERT guard applies the same exact top-level/nested key sets and unique
  canonical projection reconstruction introduced in `0010`. PostgreSQL hashes
  its own reconstructed material and requires both the lifecycle event and Goal
  row to carry that digest.
- PostgreSQL authors both initial projection timestamps with
  `statement_timestamp()`. The repository returns those durable values instead
  of returning its provisional application timestamps.

## Exact bypass regressions

The direct-SQL test does not construct an attack fixture through Goal or
Pydantic. It reproduces the reported bypass with:

- `revision = 999`;
- an all-zero syntactically valid SHA-256 content hash;
- `last_event_id` referencing the source `USER_MESSAGE`;
- no `GOAL_CREATED` event and no projection material;
- caller-supplied future creation/update timestamps.

The insert is rejected by `goal projection insert guard` with SQLSTATE `55000`.
Two additional raw probes prove that a `GOAL_CREATED` event without projection
material and a complete raw event paired with a forged Goal hash are rejected
by the same intended guard. The ordinary Goal creation path succeeds, persists
active revision 1, returns the database timestamps, and retains the exact
`GOAL_CREATED` projection digest.

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
- `0011_stage4_goal_insert_guard.sql`: `3a4e802c2833305c8cdac99bc2c94f9ba7d498b40e74714e670244b923a34172`

The recorded `0001`-`0010` hashes are unchanged.

## PostgreSQL verification evidence

Environment: Windows 11, CPython 3.12.13, Psycopg 3.3.4, PostgreSQL
18.4, and pgvector 0.8.1.

### Fresh `0001`-`0011`

- Preserved database: `havre_s4_reaccept_0011_fresh_20260814`.
- Migration result: `0001` through `0011` applied in exact order.
- Complete suite: **175 passed, 0 failed, 0 skipped** in **23.661 s**.
- Provenance audit: `[]`.
- Full Stage 4 referencing-FK catalog audit: `[]`.
- Exact Goal INSERT/UPDATE/canonical SQL probes and Stage 4 erasure closure
  passed inside the complete suite; the INSERT probe was also rerun alone.

### Populated `0010` to `0011` in-place upgrade

- Preserved database: `havre_s4_reaccept_0011_upgrade_20260814`.
- The retained populated `0010` database was verified to have `0010` as its
  last migration and contain 384 events, 11 belief revisions, 12 Goals, 7 Goal
  progress records, 7 consolidation proposals, and 73 provenance edges before
  cloning. Its pre-upgrade provenance and FK audits were both `[]`.
- Applying the current migration set to the clone applied only
  `0011_stage4_goal_insert_guard.sql`.
- Complete suite: **175 passed, 0 failed, 0 skipped** in **23.579 s**.
- Post-upgrade provenance audit: `[]`.
- Full Stage 4 referencing-FK catalog audit: `[]`.
- Exact Goal INSERT/UPDATE/canonical SQL probes and Stage 4 erasure closure
  passed inside the complete suite; the INSERT probe was also rerun alone.

Both final databases are preserved for Product Owner review. The dedicated
PostgreSQL cluster was returned to its prior stopped state after verification.

## Repeatability and generated evidence

New report directory: `evals/reports/stage4_20260814_goal_insert_correction/`

Belief replay stability report:

- file SHA-256: `7e3404ad060777c0000097ae7cb92a77516c2bd92bf23625e304a44410dbdfd3`;
- internal content hash: `sha256:44ca43f3f76e289413d2c44b4c9e82ee2235e7cbf628f52b3225f438eca2e57c`;
- source snapshot: `sha256:b42356bdd0290175f67e364b3336acf7423656e5935794e320c937acfb3ba715`;
- result: **100 completed, 100 passed, 0 failed**, one independent process per run.

Regenerated synthetic User Model report:

- file SHA-256: `a9ddfff59ae2af058a9fc732d7d39e67ee129b2668903f6500577010cf3ca63b`;
- internal content hash: `sha256:ba386744b5edbfd0a4dc82d6e62f187dc1ffa4e82ffcbad197ed57c91cd92ba0`;
- source snapshot: `sha256:b42356bdd0290175f67e364b3336acf7423656e5935794e320c937acfb3ba715`;
- result: 8/8 synthetic cases passed, false-stability count `0`, and
  counter-evidence retention `1.0`;
- the report remains non-binding and confidence calibration is unevaluated.

All earlier Stage 4 reports and old benchmark reports remain unchanged.

## Additional checks

- Contract schema export and committed-schema consistency test: passed.
- `python -m pip check`: passed.
- `python -m compileall -q companion contracts identity mlsys scripts services tests`:
  passed.
- `git diff --check`: passed.
- Final execution-source snapshot recheck:
  `sha256:b42356bdd0290175f67e364b3336acf7423656e5935794e320c937acfb3ba715`.

## Limits and stop boundary

The frozen synthetic suite does not establish production semantic quality,
confidence calibration, longitudinal benefit, or a personalized model release.
No Stage 5 or proactive runtime capability was implemented or activated.

The next allowed action is Product Owner reacceptance or another bounded Stage
4 correction request. **Do not commit, push, begin Stage 5, or activate
proactive runtime without a new explicit Product Owner decision.**
