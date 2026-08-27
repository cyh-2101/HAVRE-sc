# Stage 4 Required Provenance Correction Checkpoint

Status: **Accepted by the Product Owner; Stage 4 approved and complete. Stage 5 was unauthorized at this checkpoint and was authorized later on 2026-08-14.**

Date: **2026-08-14**

Product Owner acceptance: **2026-08-14**, bound to the exact execution-source
snapshot below.

Execution-source snapshot: `sha256:34b65d5e9f2f2902369e0cd4d33f0f673a962f11ba17a899ed4727ea030435c8`

This checkpoint records the bounded correction requested after the latest
Stage 4 reacceptance review and the Product Owner's subsequent acceptance. The
acceptance closes Stage 4 at the exact snapshot below; it does not authorize
Stage 5, permit a commit or push, or activate proactive interaction.

## Acceptance blockers corrected

- Additive migration `0012_stage4_required_provenance_guards.sql` rejects a
  raw belief revision/head unless revision 1 is a candidate backed by the exact
  same-owner `USER_BELIEF_CREATED` lifecycle event. Every belief revision must
  also have at least one supporting provenance edge before commit.
- Consolidation proposals, Current State snapshots, and Goal progress records
  now require their exact evidence snapshot to match owner-qualified
  `supports`/`contradicts` provenance edges before commit. Pattern/progress
  proposals retain the two-supporting-source minimum.
- The provenance audit now includes missing or mismatched required Stage 4
  edges, rather than auditing only broken endpoints of edges that already
  exist. Migration `0012` refuses an in-place upgrade if historical required
  provenance is incomplete; it never fabricates evidence.
- Goal progress INSERT now requires the current durable Goal revision, an exact
  same-owner `PROGRESS_RECORDED` event and policy, a strict nonempty evidence
  snapshot, and a database-reconstructed canonical content hash.
- Goal updates distinguish an omitted nullable field from an explicit `null`.
  Omission retains `next_action`/`review_at`; explicit `null` clears them.
  Progress observation time is normalized to aware UTC before hashing.

Migrations `0001` through `0011` were not modified. The SHA-256 of the new
migration is
`4070c316142b6b938154553e3da916a72f71ca783d98ef3502d9a93d97b9a9bc`.

## Exact adversarial regressions

The new tests use raw SQL rather than a `BeliefRevision`,
`GoalProgressRecord`, or `EventEnvelope` attack fixture.

- A revision-1 belief inserted directly as active is rejected with SQLSTATE
  `55000`. An event-backed candidate/head without a support edge appears in the
  required-provenance audit and is rejected when deferred constraints run.
- Goal progress pointing to revision `999999` is rejected. A current-revision
  row with an all-zero syntactically valid SHA-256 is rejected by the canonical
  hash guard. A fully hash-valid row without its exact evidence edges appears
  in the audit and is rejected by the deferred constraint.
- The ordinary service path proves that omitting both nullable Goal fields
  retains their values and explicitly passing `None` clears both.

## PostgreSQL verification evidence

Environment: Windows 11, CPython 3.12.13, Psycopg 3.3.4, PostgreSQL
18.4, and pgvector 0.8.1.

### Fresh `0001`-`0012`

- Database: `havre_s4_fix0012_fresh_20260814`.
- Migration result: `0001` through `0012` applied in exact order.
- Complete suite: **177 passed, 0 failed, 0 skipped** in **12.506 s**.
- `havre audit-provenance`: `[]`.
- Full Stage 4 referencing-FK catalog audit: `[]`.

### Populated `0011` to `0012` in-place upgrade

- Database: `havre_s4_fix0012_upgrade_20260814`.
- The source database ended at exact migration `0011` and contained 573
  events, 16 belief revisions, 19 Goals, 10 Goal progress records, 10
  consolidation proposals, and 106 provenance edges before cloning. Its
  pre-upgrade endpoint provenance audit was empty.
- Applying the current migration set to the clone applied only
  `0012_stage4_required_provenance_guards.sql`; the fail-closed historical
  provenance preflight passed.
- Complete suite: **177 passed, 0 failed, 0 skipped** in **12.255 s**.
- `havre audit-provenance`: `[]`.
- Full Stage 4 referencing-FK catalog audit: `[]`.

## Additional checks

- Contract schema export and committed-schema consistency test: passed.
- `python -m pip check`: passed.
- `python -m compileall -q companion contracts identity mlsys scripts services tests`:
  passed.
- `git diff --check`: passed.
- Execution-source snapshot recheck:
  `sha256:34b65d5e9f2f2902369e0cd4d33f0f673a962f11ba17a899ed4727ea030435c8`.

The prior non-binding synthetic User Model and replay reports were not
regenerated: this correction changes persistence integrity and nullable update
semantics, not the frozen evidence-sequence algorithm or benchmark fixtures.
Those historical reports remain evidence only for their recorded snapshots.

## Limits and stop boundary

The database tests establish the implemented local contracts, migration paths,
owner-qualified required provenance, raw-SQL rejection, audit coverage, and
erasure compatibility. They do not establish a production database permission
model, broad semantic quality, calibrated belief confidence, longitudinal
benefit, or a personalized model release.

Stage 4 is approved and complete at the recorded snapshot. **Do not commit,
push, begin Stage 5, or activate proactive runtime without a new explicit
Product Owner decision.**
