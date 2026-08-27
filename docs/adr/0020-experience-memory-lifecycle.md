# ADR-0020: Experience-to-memory promotion and temporal consolidation

- Status: Accepted
- Date: 2026-08-17
- Accepted: 2026-08-19 by Product Owner
- Decision owners: Product Owner/System Architect
- Supersedes: None
- Superseded by: None

## Context and real problem

HAVRE experiences every durable interaction and authorized life-context observation, but most experiences are not useful long-term memories. Treating every event as Semantic Memory would create noise, over-personalization, surveillance pressure, and stale beliefs. Overwriting old summaries would erase how the owner and HAVRE's understanding changed. “Raw experience is permanent” is also misleading unless it is qualified by retention and the owner's right to delete.

## Decision

Use this permanent distinction:

```text
Experience = append-oriented source Event retained by default under policy
Memory = promoted, revisable, evidence-backed artifact for future recall
```

`memory_eligible = true` permits candidate consideration; it never requires promotion. A versioned class-specific promotion process creates a `MemoryCandidate`, validates evidence/DataPolicy, and creates an immutable `MemoryRevision` only after the applicable automated and/or owner-review gate.

Memories retain exact provenance, transform/promotion version, confidence method, importance method, applicability time, and status. New evidence produces new revisions, consolidation proposals, counter-evidence, contradiction, supersession, retraction, invalidation, or archival; it never overwrites a historical revision. Historical validity and current validity remain separate.

Relevance decay may affect retrieval under a versioned policy but cannot silently change confidence, truth, validity, retention, or deletion. Archival removes an item from ordinary hot retrieval without pretending it never existed. Reconsolidation creates a new revision from exact old and new evidence. Regeneration creates a new transform-versioned derivative from eligible sources.

Owner erasure and approved retention expiry outrank append preservation. They remove or invalidate contaminated derivatives through provenance, including embeddings, caches, datasets, previews, and backups. A regenerated artifact may use only remaining eligible evidence. Transforming or summarizing source data never weakens its privacy policy.

User Model beliefs continue to use ADR-0012's bitemporal contract. A pattern/semantic memory used to assert a proposition about the owner must link to the corresponding qualified belief revision rather than becoming an unversioned personality label.

## Why it belongs in the final system

Multi-year companionship requires remembering meaningful episodes and shared history without treating incidental conversation as permanent identity. It also requires preserving growth: a belief supported in 2026 may be historically valid but obsolete in 2028. Promotion, revision, consolidation, current validity, and deletion semantics remain necessary regardless of model, embedding, or retrieval implementation.

## Simplest viable current implementation

Stages 2 and 4 implement owner-reviewed episodic candidates, immutable memory revisions, proposal-only semantic/pattern/progress consolidation, retraction, bitemporal beliefs, provenance, and source-erasure closure. Stage 7 activates broader reflection/consolidation, archival/reconsolidation proposals, and governed regeneration as proposal-only local flows. It does not automate memory mutation, outreach, or training eligibility.

## Alternatives considered

- **Promote every event:** simple, but makes incidental speech and sensor observations durable interpreted identity.
- **Keep only raw events:** preserves evidence but cannot provide curated, efficient long-term recall.
- **Continuously overwrite one summary:** easy current reads but destroys history, provenance, correction, and temporal validity.
- **Delete obsolete beliefs/memories:** removes stale current use but falsifies historical understanding and prevents honest longitudinal reflection.
- **Let embedding recency implement decay implicitly:** opaque and conflates retrieval ranking with truth and retention.
- **Retain every raw sensor record indefinitely:** contradicts minimization, purpose limitation, and class-specific retention.

## Consequences

### Benefits

- Casual experiences remain history without automatically becoming Semantic Memory.
- Current understanding can change while historical truth and shared history remain inspectable.
- Retrieval can exclude stale/superseded/archived records without erasing evidence.
- New models can regenerate understanding without changing source experience.
- Owner deletion remains truthful across derivatives.

### Costs and constraints

- Promotion, contradiction, consolidation, archival, and regeneration need explicit policies and review UX.
- Memory classes and temporal belief artifacts can overlap unless domain responsibilities stay clear.
- Provenance and erasure traversal grow as derivatives accumulate.
- A single-user longitudinal system may not have enough evidence to calibrate automatic promotion or confidence safely.

## Failure modes and future migration risks

Promotion can overfit transient moments, decay can hide inconvenient counter-evidence, consolidation can produce essentializing labels, and regeneration can copy deleted content. Require class-specific evidence thresholds, exact counter-evidence retention, owner review for high-impact claims, method/version metadata, source snapshots, privacy closure, and replay tests. Keep pattern/progress memories as retrieval artifacts and temporal belief revisions as the authority for claims about the owner.

If future storage tiers archive old material, preserve IDs, hashes, policy, provenance, temporal validity, and owner export/erasure semantics. If confidence algorithms are later introduced, they must create revisions under a separately approved method rather than mutating existing confidence.

## Relationship to accepted decisions

This extends ADR-0003, ADR-0004, ADR-0007, ADR-0011, ADR-0012, ADR-0013, and ADR-0015. It supersedes none of them. “Permanent” in product prose is interpreted consistently with ADR-0003: append-preserved during ordinary operation, subject to owner erasure and approved retention.

## Validation

- Fixtures proving most events do not automatically become memories.
- Class-specific promotion, rejection, duplicate, and owner-correction cases.
- Distinct-source/time and counter-evidence requirements for pattern/progress claims.
- Historical/current validity, contradiction, supersession, retraction, invalidation, and archival replay.
- Retrieval excludes retracted, inapplicable, and archived records while audit/export remains possible.
- Relevance decay never mutates confidence, validity, status, or source evidence.
- Reconsolidation/regeneration creates a new revision with exact transform and source provenance.
- Retention/erasure closure removes contaminated derivatives and prevents resurrection after restore.
- Relationship/shared-history memories remain source-linked and provider-independent.

## Unresolved owner decisions

Promotion automation by class, high-impact review requirements, relevance-decay policy, archival tiers, reconsolidation cadence, relationship-memory UX, retention periods, and approved confidence methods remain Product Owner decisions before activation.

## Approval note

Accepted by the Product Owner on 2026-08-19 together with continuous Stage 6 and Stage 7 implementation authorization. Acceptance does not approve automatic confidence, automatic memory mutation, real proactive contact, new data collection, private-data export, training eligibility, or a production personalized-model release.
