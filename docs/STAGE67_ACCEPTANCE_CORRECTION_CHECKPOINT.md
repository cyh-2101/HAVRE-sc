# Stage 6/7 acceptance correction checkpoint

Date: **2026-08-19**
Status: **Historical correction candidate; rejected after two additional P1 findings**
Execution-source snapshot: `sha256:c6bfc4dd0ed24559659c4df2814ff510cd29881a176e7edce0549270852cd56d`

## Why the previous candidate was rejected

Acceptance review reproduced seven blockers. The prior Stage 6 and Stage 7 checkpoints are retained as rejected historical evidence and do not establish completion.

1. The Stage 7 Reflection query reused revoked Events and recreated forbidden evidence.
2. Stage 6 policy evaluation serialized only an idempotency key, allowing concurrent budget/cooldown/deduplication bypass.
3. Stage 6 lacked Roadmap-required owner controls, response linkage, scheduled/event-driven work, and explicit retry/reconciliation paths.
4. The proactive HTTP endpoint generated a new policy revision on every retry, breaking idempotency.
5. A real Stage 7 processing exception rolled back its lease and attempt count instead of entering durable retry state.
6. Stage 7 job idempotency keys were not bound to the requested time window.
7. Architecture and governance documents contradicted the accepted ADR and authorization state.

## Corrections

Additive migration `0021_stage67_acceptance_corrections.sql` preserves all earlier migration bytes and adds:

- database admission triggers rejecting revoked Events in Reflection, memory-lifecycle, and dataset evidence;
- immutable, owner-qualified proactive action records for response, dismissal, snooze, non-response, and stop;
- exact response-event and inbox/proposal linkage guards;
- durable scheduled/event-driven proactive work items with leases, bounded retries, typed safe failures, and exact input fingerprints;
- covering indexes and lifecycle event types for the new boundaries.

Runtime corrections include:

- Stage 7 Reflection excludes `offline_source_revocations`; Reflection, dataset building, and privileged erasure share one owner-scoped transaction lock so revocation and regeneration cannot race.
- Stage 7 claims commit before processing. Processing rollback is followed by a separate fenced failure transaction, so retry state and attempt count survive real exceptions.
- Stage 7 enqueue normalizes and compares both time-window endpoints; same-key changed input is a conflict.
- Stage 6 acquires an owner-scoped advisory lock before reading delivery counts or active equivalents and keeps it through decision and local delivery.
- Proactive HTTP policy revision identity is deterministic for the exact owner and semantic policy; the fingerprint includes the complete policy snapshot.
- Owner actions feed Interruption Policy. Snooze defers; dismissal and stop suppress; observed non-response suppresses equivalent follow-up because no new cadence is approved. Silence creates no urgency or escalation.
- Scheduled and event-driven work use the same idempotent Core path. If delivery commits but worker completion fails, retry replays the same request and reconciliation proves one local visible effect.

## Direct regression evidence

- Budget-one concurrency: two distinct simultaneous keys produced exactly one `SEND_NOW`, one `DEFER`, and one delivered attempt.
- Revocation: after derivative erasure, a new Reflection job succeeded using only remaining Events; revoked evidence counts stayed zero, raw INSERT was rejected with SQLSTATE `55000`, and provenance audit returned `[]`.
- Real worker failure: injected processing failure produced `retryable_failed`, `attempt_count=1`, and `last_error_code=worker_processing_error`; the next claim succeeded.
- Stage 7 idempotency: an exact window replay returned the original job; changing the window under the same key raised a conflict.
- HTTP idempotency: two identical requests with one key returned the same Proposal and the second response reported `idempotent_replay=true`.
- Delivery reconciliation: an injected post-delivery completion failure entered retry state; retry used the existing request and exactly one delivered attempt remained.
- Owner controls and response linkage: dismissal, stop, snooze, and non-response each affected an equivalent follow-up conservatively; a later same-owner `USER_MESSAGE` linked successfully, while an assistant event was rejected as a response source.

## Complete verification

Environment: Windows 11, CPython 3.12.13, FastAPI 0.141.1, Pydantic 2.13.4, Psycopg 3.3.4, PostgreSQL 18.4, pgvector 0.8.6.

Fresh installation:

- Dedicated disposable database; migrations `0001`–`0021`.
- Complete suite: **226 passed, 0 failed, 0 skipped** in **15.091 s**.
- Provenance and Stage 4/5/6/7 foreign-key-index audits: `[]`.

Populated upgrade:

- A `0001`–`0020` database contained one complete Stage 6 delivered local-inbox fixture and one Stage 7 Reflection proposal.
- Current source applied only `0021_stage67_acceptance_corrections.sql`; both historical artifacts remained readable.
- Complete suite: **226 passed, 0 failed, 0 skipped** in **13.661 s**.
- Migration reapplication: `applied: []`.
- Provenance and Stage 4/5/6/7 foreign-key-index audits: `[]`.

Contract export, `pip check`, bytecode compilation, and `git diff --check` also passed.

## Boundaries and next gate

All proactive effects remain local and simulation-only. Database checks still require `external_delivery_authorized=false`. No external Context Source, real contact, private-data transfer, training eligibility, automatic Memory mutation, governance-policy change, Stage 8 work, or personalized release was activated.

This correction was not accepted. A later review found stale preference execution and a remaining lifecycle-evidence/revocation race; its evidence is historical and cannot establish Stage 6/7 completion.
