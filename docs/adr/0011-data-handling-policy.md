# ADR-0011: Provider-independent privacy and data-use policy

- Status: Accepted
- Accepted: 2026-08-13 by Product Owner
- Date: 2026-08-13
- Decision owners: Product Owner/System Architect
- Supersedes: None
- Superseded by: None

## Context and real problem

HAVRE will contain information ranging from public identity text to deeply personal or device-local experience. A single sensitivity label cannot answer whether data may become memory, enter training, or be disclosed to a cloud processor. Provider-specific privacy controls would disappear when providers change and would not protect workers, caches, judges, datasets, or tools.

## Decision

Define a provider-independent `DataPolicy` for every relevant event, memory, belief, Context Pack item, training/evaluation example, Scene Session record, and derived personal artifact. Initial privacy classes are `PUBLIC`, `NORMAL`, `PRIVATE`, `HIGHLY_PRIVATE`, and `LOCAL_ONLY`. Independent booleans state `memory_eligible`, `training_eligible`, and `cloud_eligible`, with policy version and decision/consent provenance.

`training_eligible` defaults false. `LOCAL_ONLY` requires `cloud_eligible = false`. Derived artifacts inherit the most restrictive source constraints unless an explicit owner-approved policy revision authorizes a narrowly scoped declassification. Context Builder and Router both fail closed on unresolved policy.

## Why it belongs in the final system

The same data will flow through memory, context, evaluation, teacher review, training, and local/cloud/edge brains over many years. Durable, provider-neutral policy is required to keep ownership and consent meaningful as implementations change.

## Simplest viable current implementation

Stage 1 places an immutable DataPolicy snapshot on each raw event and Context Pack section, supports append-only policy revisions, computes pack-level effective policy, and rejects cloud calls when any required content is not cloud eligible. Training permission remains false because training is not active.

## Alternatives considered

- **One sensitivity enum:** cannot distinguish memory, training, and cloud uses.
- **Provider-specific flags:** does not protect non-provider pipelines and creates vendor lock-in.
- **Infer training permission from memory use:** violates purpose limitation and owner consent.
- **Encrypt everything but allow all processing:** encryption does not decide legitimate use or execution location.

## Consequences

### Benefits

- Memory usefulness no longer implies training consent.
- Local-only content has an enforceable execution boundary.
- Policy follows derived artifacts across providers and stages.
- Consent changes are versioned and auditable.

### Costs and constraints

- Every protected-data path must propagate and test policy.
- Mixed-policy Context Packs and derived artifacts need conservative aggregation.
- Declassification and consent-revision UX require human-readable explanations.

## Failure modes and future migration risks

Policy can be lost in caches, traces, exports, model judges, or dataset renderers even when source rows are correct. Centralize resolution, require policy in contracts, and test each boundary. Classification names may evolve; preserve semantic migrations and never weaken old records by renaming. A future richer policy engine may replace booleans while maintaining independent purposes and the `LOCAL_ONLY` invariant.

## Validation

- Database/domain rejection of `LOCAL_ONLY` plus cloud eligibility.
- End-to-end cloud-adapter denial tests.
- Independent truth-table tests for memory/training/cloud eligibility.
- Derived-policy inheritance and explicit declassification tests.
- Dataset builder rejects non-explicit training permission.
- Privacy scans across traces, caches, evaluation artifacts, and exports.

## Approval note

Accepted by the Product Owner on 2026-08-13 with the Stage 0.1/Stage 1 privacy defaults and owner-only declassification authority. Future declassification/redaction UX and narrower operation-specific rules remain separately gated.
