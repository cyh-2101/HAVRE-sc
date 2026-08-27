# ADR-0003: Append-oriented event ledger with privileged owner erasure

- Status: Accepted
- Accepted: 2026-08-13 by Product Owner
- Date: 2026-08-12
- Decision owners: Product Owner/System Architect
- Supersedes: None
- Superseded by: None

## Context and real problem

HAVRE must retain raw experience so future models can reinterpret it, yet the data is deeply personal and the owner must be able to delete it. A naive “immutable forever” ledger conflicts with privacy ownership; mutable chat rows destroy historical and causal evidence.

## Decision

Use an append-oriented event ledger for ordinary operation. Corrections, outcomes, revisions, and lifecycle changes append new events. Ordinary application roles cannot update/delete events. A separate privileged erasure workflow can physically delete owner-selected source data and its derived/provenance closure, including backups through expiry/replay policy.

## Why it belongs in the final system

Raw experience is the long-term source for memory, reflection, training, and reprocessing. Owner-controlled export/erasure is equally permanent as a product and privacy requirement.

## Simplest viable current implementation

Stage 1 uses one events table, typed payload versions, an owner-scoped request/idempotency ledger with semantic fingerprints, trace IDs, insert-only permissions, and tests. Implement full-owner export/erasure before production-like retention; partial provenance-closure deletion matures with Stage 2 derived data.

## Alternatives considered

- **Strict immutable/event-sourced database:** strong auditability but can make deletion false or operationally dangerous.
- **Mutable messages/state rows only:** easy CRUD but loses what was originally communicated and makes reinterpretation/audit unreliable.
- **Store only summaries:** reduces volume but makes derived misunderstanding irreversible.

## Consequences

### Benefits

- Durable chronological source and replay.
- Clear correction semantics.
- Retry/idempotency and traceability.

### Costs and constraints

- Schema evolution and projection rebuilds require discipline.
- Erasure is more complex because derivatives and backups must be traversed.
- “Permanent” must always be described with the owner-erasure qualification.

## Failure modes and future migration risks

Events can become a dumping ground for logs or oversized blobs; a registry and review prevents this. Partitioning may later be needed. Erasure can leave embeddings/caches/artifacts behind unless provenance and verification are complete. A content-free erasure receipt is retained only under an approved policy.

## Validation

- Insert-only role tests and schema-version golden cases.
- Idempotent retry tests.
- Correction/replay projection tests.
- Export and erasure closure tests, including restored backups.

## Approval note

Accepted as an architectural baseline by the Product Owner on 2026-08-13. Deletion-receipt and backup policy remain unresolved before production-like personal use.
