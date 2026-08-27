# Architecture Decision Records

ADRs record durable decisions that shape HAVRE across stages. `MASTER_PLAN.md` remains the product authority; an ADR explains how an architectural choice satisfies it.

## Status lifecycle

```text
Proposed -> Accepted -> Superseded
                  \-> Deprecated
Proposed -> Rejected
```

- Only the Product Owner/System Architect can accept a material product or architecture decision.
- Implementing a proposal before approval does not make it accepted.
- Accepted records are never rewritten to hide history. A new ADR supersedes them.
- Small clarifications may append a dated note if they do not change the decision.

## Index

| ADR | Decision | Status |
|---|---|---|
| [0000](0000-template.md) | Template | Reference |
| [0001](0001-modular-monolith-and-process-boundaries.md) | Modular monolith and explicit process boundaries | Accepted |
| [0002](0002-postgresql-and-pgvector.md) | PostgreSQL and pgvector as system of record | Accepted |
| [0003](0003-append-oriented-events-and-erasure.md) | Append-oriented events and privileged erasure | Accepted |
| [0004](0004-provenance-and-derived-revisions.md) | Typed provenance and immutable derived revisions | Accepted |
| [0005](0005-provider-neutral-inference.md) | Provider-neutral inference contract | Accepted |
| [0006](0006-w3c-trace-context.md) | W3C trace context and async links | Accepted |
| [0007](0007-canonical-datasets-and-lineage.md) | Canonical datasets and immutable lineage | Accepted |
| [0008](0008-database-backed-worker-boundary.md) | Database-backed durable worker boundary first | Accepted |
| [0009](0009-model-independent-identity.md) | Model-independent identity | Accepted |
| [0010](0010-evaluation-gated-releases.md) | Evaluation-gated immutable releases | Accepted |
| [0011](0011-data-handling-policy.md) | Provider-independent privacy and data-use policy | Accepted |
| [0012](0012-temporal-belief-model.md) | Bitemporal belief revisions and lifecycle history | Accepted |
| [0013](0013-scene-session-domain-object.md) | Scene Session as a first-class domain object | Accepted |
| [0014](0014-governed-behavior-hierarchy.md) | Governed Constitution-to-personalization hierarchy | Accepted |
| [0015](0015-outcome-aware-evaluation.md) | Outcome-aware guidance evaluation | Accepted |
| [0016](0016-governed-core-authorizes-proactive-outreach.md) | Governed Core authorizes proactive outreach | Accepted |
| [0017](0017-interruption-policy-and-user-control.md) | Interruption Policy, owner control, and anti-annoyance limits | Accepted |
| [0018](0018-provider-neutral-private-delivery.md) | Provider-neutral, privacy-safe delivery | Accepted |
| [0019](0019-provider-neutral-ambient-life-context.md) | Provider-neutral Ambient Life Context with local minimization | Accepted |
| [0020](0020-experience-memory-lifecycle.md) | Experience-to-memory promotion and temporal consolidation | Accepted |
| [0021](0021-daily-conversation-feedback-and-episode-learning.md) | Daily conversation, episode consolidation, and governed owner feedback | Accepted |
| [0022](0022-core-governed-response-delivery.md) | Core-governed response delivery after model rendering | Accepted |

## When a new ADR is required

- changing domain ownership or a public/internal contract;
- adding or replacing an authoritative data store;
- changing event, provenance, privacy, or deletion semantics;
- binding to or replacing a provider/serving/training/observability platform;
- introducing a new deployable service or infrastructure class;
- changing evaluation gates or release authority;
- intentionally diverging from `MASTER_PLAN.md`.

Dependency/library upgrades that preserve the decision and contracts normally belong in ordinary change records, not new ADRs.
