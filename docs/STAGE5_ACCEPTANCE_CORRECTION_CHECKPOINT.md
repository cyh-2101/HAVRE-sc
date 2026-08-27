# Stage 5 Acceptance Correction Checkpoint

Status: **Accepted by the Product Owner; Stage 5 approved and complete; Stage 6 unauthorized**

Date: **2026-08-14**

Execution-source snapshot: `sha256:e5497d6103c394a0885b667b828181c2f213da4c4b352f8d4f9fd92911c0032e`

Product Owner acceptance: **2026-08-14**, bound to the exact execution-source
snapshot above.

This checkpoint supersedes the acceptance claim of the historical
[`STAGE5_CHECKPOINT.md`](STAGE5_CHECKPOINT.md) snapshot. It records a bounded
Stage 5 correction after independent acceptance review reproduced four durable
integrity failures. A later re-acceptance run found one additional cross-stage
evidence-ordering failure at the first corrected snapshot; this checkpoint now
includes that bounded correction and renewed evidence. The evidence did not
self-approve Stage 5; the explicit Product Owner decision recorded above did.
That acceptance does not authorize Stage 6, permit a commit or push, promote the
simulation policy candidate to production, or activate proactive interaction.

## Acceptance blockers corrected

- Full Scene source erasure now deletes outcome observations, then decisions,
  then their cyclicly linked records. Retained raw/lifecycle events have their
  erased Scene and deleted-decision causation references detached inside the
  privileged transaction and receive a newly reconstructed canonical event
  hash. The complete Before/During/After chain can therefore commit erasure
  without leaving unreadable retained events.
- Additive migration `0014_stage5_acceptance_corrections.sql` makes the current
  `scene_sessions.phase/status` authoritative for every new Scene record. A
  `during` signal or intervention cannot be inserted while the Scene is still
  `before/planned`, even through direct persistence calls.
- Scene transition timestamps are aware UTC in the typed contracts and are
  bound to PostgreSQL transaction time. PostgreSQL recursively reconstructs
  compact key-sorted material from the actual Scene, record, decision, and
  outcome rows and verifies their SHA-256 hashes. A future caller timestamp,
  stale digest, or opaque replacement digest is rejected.
- An intervention record must bind one exact decision event, decision row,
  guidance event, input record, phase, trace, policy, visible text, structured
  content, and candidate-policy output. A Before decision cannot be paired
  with another decision's During guidance.
- Decision guards additionally require the current Scene revision/state,
  exact phase-dependent evidence set, owner-approved Constitution/Identity/
  Values versions, immutable input/decision/guidance causation, and the fixed
  no-outreach candidate-policy constraints.
- Durable request evidence now orders events by `recorded_at, event_id`. The
  monotonic UUIDv7 identifier is the stable secondary key when Windows clock
  resolution gives a user event and terminal failure the same timestamp, so
  evidence consumers no longer observe planner-dependent terminal ordering.

Migrations `0001` through `0013` were not modified. The SHA-256 of migration
`0014` is
`e12c69782d26cf03cfc51e80182f322b6b5d452dc7284a5ef2126365759c65dd`.

## Exact adversarial regressions

Four Stage 5 PostgreSQL regressions preserve the initial acceptance review's
attacks:

- a complete Scene containing 7 ordered records, 3 decisions, and 1 outcome
  observation erases successfully; six derived decision/guidance events are
  gone, every retained event remains parseable with its canonical hash, and no
  retained causation points to an erased event;
- a validly hashed `during` signal/event/record submitted while its Scene is
  `before/planned` is rejected with SQLSTATE `55000`;
- a revision-2 start event followed by `started_at = 2099-01-01` and the
  unchanged revision-1 digest is rejected with SQLSTATE `55000`;
- a validly hashed During intervention record that combines a Before decision
  with a different During guidance event is rejected with SQLSTATE `55000`.

One additional PostgreSQL regression creates two events with the same
`recorded_at` while deliberately making physical insertion order disagree with
event-ID order. It failed against the prior `ORDER BY recorded_at` query and
passes only when evidence uses the unique event ID as a secondary key. The
original route/provider-version failure regression also passes in focused and
full-suite execution.

The superseded first corrected snapshot
`sha256:2e6354aa99ea890efb244eabd6030e25583424fb8839eaddbfbd2608e2886e0d`
had passed its implementation-time 197-test runs. Independent re-acceptance
later exposed the tied-timestamp ordering ambiguity when a fresh full run
completed 197 tests with one error, while focused reruns and a populated full
run passed. That inconsistent evidence is historical and is not the current
acceptance candidate.

## PostgreSQL verification evidence

Environment: Windows 11, CPython 3.12.13, FastAPI 0.141.1, Pydantic 2.13.4,
Psycopg 3.3.4, PostgreSQL 18.4, and pgvector 0.8.6. Verification used the
repository-owned cluster on `127.0.0.1:55432`. It was stopped before the task
and was restored to stopped state after cleanup.

### Fresh `0001` through `0014`

- Database: `havre_s5_fix_fresh_20260814_01`.
- Exact ordered migration set: 14 migrations, ending at `0014`.
- Complete PostgreSQL-backed suite: **198 passed, 0 failed, 0 skipped** in
  **13.620 s**.
- Migration idempotency recheck: `applied: []`.
- `audit-provenance`: `[]`.
- Stage 5 referencing-FK index audit: `[]`.

### Populated `0013` to `0014` in-place upgrade

- Database: `havre_s5_upgrade_fix_20260814_01`.
- Before correction it contained exact migrations `0001` through `0013`, a
  real Stage 4 interaction/belief/state/Goal/progress/consolidation/memory
  lineage, and a closed full Stage 5 Scene. Counts included 27 events, 1 belief
  revision, 1 Goal, 15 provenance edges, 1 Scene, 7 Scene records, 3 decisions,
  and 1 outcome observation. The pre-upgrade provenance audit was empty.
- Applying the current migration set applied only
  `0014_stage5_acceptance_corrections.sql`.
- The pre-existing closed Scene remained readable with all 7 records,
  3 decisions, and 1 outcome observation after upgrade.
- Complete PostgreSQL-backed suite: **198 passed, 0 failed, 0 skipped** in
  **13.416 s**.
- Migration idempotency recheck: `applied: []`.
- `audit-provenance`: `[]`.
- Stage 5 referencing-FK index audit: `[]`.

### Stage 4 populated compatibility path

For an additional earlier-schema compatibility check,
`havre_s5_upgrade_fix_compat_20260814_01` contained exact populated Stage 4 data
at `0012`; applying the current set applied only `0013` and `0014`. The
complete suite passed **198 passed, 0 failed, 0 skipped** in **15.037 s**;
migration reapplication and both audits were again empty.

## Other checks and bounded evaluation

- Committed-schema consistency regression: passed. No active contract changed,
  so schema export was not required for this correction.
- `python -m pip check`: passed.
- `python -m compileall -q companion contracts identity mlsys scripts services tests`:
  passed.
- `git diff --check`: passed.
- Execution-source snapshot recheck:
  `sha256:e5497d6103c394a0885b667b828181c2f213da4c4b352f8d4f9fd92911c0032e`.
- Frozen `scene-policy-simulation-v1`: 10/10 decision cases, 10/10 wording
  checks, zero outreach-authorized decisions, maximum guidance length 113
  characters. Final report run ID:
  `01a000ce-0dbd-74d2-877d-b4b3a18e3ea5`; content hash:
  `sha256:b6485e85793b90e8783569cea35d53cb2aa65e778aebc056e0d9b4c580a5aa9a`.

The policy suite is deterministic synthetic evidence. It is non-binding and
does not prove real-world benefit, calibrated safety inference, production Web
readiness, or permission to contact the owner.

## Handoff gate

The four reproduced Stage 5 integrity blockers and the later deterministic
evidence-ordering blocker are corrected. The Product Owner accepted the bounded
Stage 5 implementation on 2026-08-14 at the exact source snapshot above. Stage
5 is complete. **Do not begin Stage 6, activate proactive runtime, commit, or
push without a new explicit owner decision.**
