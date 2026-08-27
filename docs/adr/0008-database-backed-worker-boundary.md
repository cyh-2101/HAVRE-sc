# ADR-0008: PostgreSQL-backed durable worker boundary before a queue service

- Status: Accepted
- Accepted: 2026-08-13 by Product Owner
- Date: 2026-08-12
- Decision owners: Product Owner/System Architect
- Supersedes: None
- Superseded by: None

## Context and real problem

Memory extraction, reflection, consolidation, evaluation, and dataset building must not block interactive requests and must survive crashes. In-process background tasks can be lost; Redis/Celery or distributed queues add infrastructure without a measured single-user workload.

## Decision

Keep a separate worker executable and use a PostgreSQL durable job/outbox table with transactional enqueue, leases, retries, typed terminal failure, and idempotent handlers. Add a specialized queue only when measured throughput, scheduling, isolation, or operational needs justify it.

## Why it belongs in the final system

The background-work boundary is permanent. The initial transport can evolve without changing job semantics or domain handlers.

## Simplest viable current implementation

Stage 1 inserts event and required job in one transaction. Workers claim available rows with locking/lease semantics, process idempotently, and record attempts. One worker process is sufficient.

## Alternatives considered

- **FastAPI/in-process background tasks:** minimal code but not durable across restarts and hard to reconcile transactionally.
- **Redis/Celery immediately:** mature features but another stateful service, broker failure mode, and dual-write problem.
- **Synchronous extraction/reflection:** harms interaction latency and availability.

## Consequences

### Benefits

- No event-to-job loss window.
- Simple local operations, backups, and trace correlation.
- Permanent worker API without premature broker choice.

### Costs and constraints

- Polling/locking adds database load.
- Scheduling and priority features remain basic.
- Long-running jobs need careful lease renewal and cancellation.

## Failure modes and future migration risks

Poison jobs, duplicate attempts, lease expiry, and backlog must be visible. Measure queue age, claim latency, throughput, retry/terminal failures, and database contention. If migrating, publish from the transactional outbox and preserve job/idempotency IDs; do not dual-write application transactions directly to two systems.

## Validation

- Crash/retry/idempotency tests.
- Atomic event+job transaction test.
- Lease recovery and poison-job tests.
- Backlog/throughput benchmark before broker migration.

## Approval note

Accepted by the Product Owner on 2026-08-13.

### 2026-08-13 Stage 1 scope clarification

The later-approved Stage 1 scope contains no background capability. Therefore no job table or worker executable is activated in Stage 1. This ADR remains the accepted boundary for the first later stage that introduces durable background work; that activation must preserve the transaction/outbox and idempotency requirements above.
