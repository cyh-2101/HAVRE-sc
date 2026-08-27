# ADR-0001: Modular monolith with explicit process boundaries

- Status: Accepted
- Accepted: 2026-08-13 by Product Owner
- Date: 2026-08-12
- Decision owners: Product Owner/System Architect
- Supersedes: None
- Superseded by: None

## Context and real problem

HAVRE has many conceptual capabilities, but it begins as a single-user system without measured scale or multiple engineering teams. A single unstructured application would blur boundaries; early microservices would add deployment, consistency, tracing, and failure complexity before a workload requires them.

## Decision

Keep Companion Core, orchestration, ML-system adapters, and learning logic in one versioned Python codebase with enforced module boundaries and provider-neutral ports. Run API and background worker as separate executables. Run model serving as an independent boundary when self-hosted inference activates. Treat web/iOS as clients.

## Why it belongs in the final system

Domain ownership and ports survive future process extraction. API/worker/inference have genuinely different latency, reliability, and hardware needs, so those execution boundaries are permanent even if deployment topology evolves.

## Simplest viable current implementation

Stage 1 uses one Python package, one FastAPI process, one PostgreSQL instance, and one provider adapter. The worker executable boundary remains reserved but inactive because Stage 1 has no approved background work. A later stage activates one worker process behind the same module and job contracts. No internal network calls exist between domain modules.

## Alternatives considered

- **One script/process:** simpler to launch but makes background work, retries, and provider replacement entangled with request handling.
- **Microservices per capability:** visually matches the architecture diagram but creates distributed transactions and operational overhead without evidence.
- **Framework-heavy agent architecture:** does not solve the product's durable identity/data/evaluation problems and risks framework lock-in.

## Consequences

### Benefits

- Transactional correctness and simple local development.
- Clear domains without premature network boundaries.
- Easy refactoring and end-to-end tests.

### Costs and constraints

- Module dependency rules need tests/review.
- One code release may contain multiple logical components.
- Worker and API scaling are coupled until packaging/deployment separation matures.

## Failure modes and future migration risks

Cross-module imports can erode boundaries. Heavy retrieval/training workloads may later require independent services. Extract only when measured resource isolation, deploy cadence, security, or ownership needs justify it; preserve the existing port contract and use an outbox during migration.

## Validation

- Architecture dependency tests.
- Provider and database adapters replaceable in integration tests.
- API remains responsive when worker is stopped/backlogged.
- Trace spans make process boundaries visible.

## Approval note

Accepted by the Product Owner on 2026-08-13.
