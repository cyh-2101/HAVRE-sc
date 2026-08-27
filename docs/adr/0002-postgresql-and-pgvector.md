# ADR-0002: PostgreSQL and pgvector as the system of record

- Status: Accepted
- Accepted: 2026-08-13 by Product Owner
- Date: 2026-08-12
- Decision owners: Product Owner/System Architect
- Supersedes: None
- Superseded by: None

## Context and real problem

HAVRE needs transactional events, structured state, provenance, revisions, version registries, evaluation metadata, and vector retrieval. Splitting these across databases early would make consistency, export, deletion, and recovery harder.

## Decision

Use PostgreSQL as the authoritative database and pgvector for memory embeddings/vector search. Store large binary artifacts externally with immutable URI/hash metadata in PostgreSQL.

## Why it belongs in the final system

Long-term memory retrieval requires both semantic vectors and strict metadata/provenance filters. Relational constraints, transactions, and standard backup/export support remain valuable at every stage.

## Simplest viable current implementation

One PostgreSQL instance. Stage 1 creates only foundational tables; pgvector activates in Stage 2. Begin with exact/simple vector search and ordinary indexes. Add approximate indexes only after corpus/latency measurements.

## Alternatives considered

- **Separate vector database:** may scale specialized retrieval but creates two authorities and harder provenance/deletion transactions.
- **Document database:** flexible payloads but weaker fit for revisions, lineage, and registry relationships.
- **SQLite/local files:** convenient for a demo but diverges from final concurrency, vector, migration, and deployment behavior.

## Consequences

### Benefits

- One transaction and ownership boundary.
- SQL metadata filters and vector scores can be composed.
- Simpler export, backup, erasure traversal, and local deployment.

### Costs and constraints

- Vector index tuning and embedding-dimension changes need care.
- Very large artifact or vector workloads may exceed one instance's practical envelope.
- Database-backed jobs add contention if poorly indexed.

## Failure modes and future migration risks

If measured corpus size, latency, or isolation needs exceed PostgreSQL/pgvector, a retrieval service/index may be added as a derived cache. PostgreSQL remains authority; dual-write is avoided by rebuilding the index from versioned records/outbox events. Embedding versions must not overwrite each other.

## Validation

- Migration/constraint tests.
- Retrieval quality/latency benchmark at measured corpus sizes.
- Backup/restore plus export/erasure tests.
- Database resource and job-queue contention metrics.

## Approval note

Accepted by the Product Owner on 2026-08-13.
