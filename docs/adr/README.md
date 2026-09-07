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
| [0023](0023-private-tailnet-web-push-delivery.md) | Private tailnet access and governed generic Web Push | Accepted |
| [0024](0024-governed-automatic-reach-out-and-generic-local-only-push.md) | Governed automatic Reach Out and generic LOCAL_ONLY Push | Accepted |
| [0025](0025-manual-owner-context-strong-brain.md) | Manual owner-context Strong Brain disclosure | Accepted |
| [0026](0026-retire-seed-9201-and-evaluate-conversation-stack.md) | Retire Seed 9201 and evaluate the conversation stack | Accepted |
| [0027](0027-stage13-conversation-intelligence-architecture.md) | Stage 13 conversation-intelligence architecture and external engineering loop | Accepted |
| [0028](0028-chatgpt-desktop-mcp-companion-surface.md) | ChatGPT desktop MCP companion surface | Accepted |
| [0029](0029-default-chatgpt-codex-reply-provider.md) | Default ChatGPT/Codex reply provider | Accepted |
| [0030](0030-data-policy-driven-dual-replyer-routing.md) | DataPolicy-driven GPT/local dual Replyer routing | Accepted |
| [0031](0031-owner-calibrated-runtime-examples-and-practical-utility-repairs.md) | Owner-calibrated runtime examples and practical-utility repairs | Accepted |
| [0032](0032-owner-imported-commitments-and-source-guarded-reminders.md) | Owner-imported commitments and source-guarded reminders | Implemented by task direction; formal acceptance pending |
| [0033](0033-reviewed-understanding-curated-diary-and-adaptive-mobile-conversation.md) | Reviewed understanding, curated Diary, and adaptive mobile conversation | Implemented by task direction; formal acceptance pending |
| [0034](0034-owner-delegated-diary-intelligence-and-paired-review.md) | Owner-delegated Diary intelligence and paired review | Implemented by task direction; formal acceptance pending |
| [0035](0035-experience-first-daily-review-and-relational-continuity.md) | Experience-first daily review and relational continuity | Implemented by task direction; formal acceptance pending |
| [0036](0036-bounded-owner-local-relational-initiative.md) | Bounded relational initiative | Proposed; GPT-high correction production-active, formal acceptance and usefulness review open |
| [0038](0038-audit-driven-daily-companion-correctness.md) | Audit-driven daily correctness and continuity | Owner-authorized implementation active; repeated-use acceptance and strong independent review open |

## When a new ADR is required

ADR [0037](0037-local-semantic-memory-and-time-aware-recall.md) implements the
owner-requested real-time understanding, local semantic Memory, and five-to-five
Diary correction. Implementation is authorized; formal acceptance remains open.

- changing domain ownership or a public/internal contract;
- adding or replacing an authoritative data store;
- changing event, provenance, privacy, or deletion semantics;
- binding to or replacing a provider/serving/training/observability platform;
- introducing a new deployable service or infrastructure class;
- changing evaluation gates or release authority;
- intentionally diverging from `MASTER_PLAN.md`.

Dependency/library upgrades that preserve the decision and contracts normally belong in ordinary change records, not new ADRs.
