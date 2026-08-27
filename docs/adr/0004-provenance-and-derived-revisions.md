# ADR-0004: Typed provenance graph and immutable derived revisions

- Status: Accepted
- Accepted: 2026-08-13 by Product Owner
- Date: 2026-08-12
- Decision owners: Product Owner/System Architect
- Supersedes: None
- Superseded by: None

## Context and real problem

Memories, patterns, progress claims, reflections, and User Model beliefs can be wrong. HAVRE must show support and counter-evidence, revise interpretations, rebuild them with stronger models, and remove their derivatives when source data is erased.

## Decision

Store important derived artifacts as immutable revisions with active/superseded/retracted status. Link exact source and derived revisions using typed provenance edges that record relationship, transform identity/version, creation event, and trace.

## Why it belongs in the final system

Evidence-aware revision is central to “understand, do not label.” It enables correction, reprocessing, dataset lineage, evaluation audit, and privacy deletion across the system's lifetime.

## Simplest viable current implementation

Stage 1 uses belief revisions and exact source event references. Stage 2 introduces the generic provenance edge table for memory/belief evidence, with application validation and an integrity check.

## Alternatives considered

- **Source IDs only inside JSON:** easy initially but hard to constrain, traverse, query, or erase.
- **Separate evidence table for every artifact:** strong foreign keys but duplicated semantics and slow evolution.
- **Overwrite derived rows:** simple current reads but destroys uncertainty/revision history.
- **Full graph database:** flexible traversal but adds another authority and operations before scale evidence.

## Consequences

### Benefits

- Uniform evidence and counter-evidence model.
- Rebuildable and challengeable derived understanding.
- Clear lineage into datasets/models/releases.

### Costs and constraints

- Polymorphic edges lack universal relational foreign keys.
- Graph integrity and query performance require explicit checks/indexes.
- Confidence changes need human-readable reasons, not silent updates.

## Failure modes and future migration risks

Edge volume may grow quickly and relation meanings can drift. Use a registered relation taxonomy and transform versions. Materialize typed/hot relations when measured queries require it. A graph store may become a derived read model later, never the only lineage authority.

## Validation

- Evidence/counter-evidence traversal tests.
- Cross-owner edge rejection.
- Revision/retraction projection replay.
- Integrity scan and privacy erasure closure.

## Approval note

Accepted by the Product Owner on 2026-08-13.
