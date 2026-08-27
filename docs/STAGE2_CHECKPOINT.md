# Stage 2 Checkpoint — Episodic Memory and Retrieval Benchmark

Status: **Historical Stage 2 checkpoint; accepted by the Product Owner on 2026-08-13**

Date: 2026-08-13

## Scope completed

Stage 2 adds the first permanent long-term-memory slice without activating User Model inference, Intervention Policy, Scene functionality, Reflection, training, LoRA, proactive execution, or Stage 3 model serving.

```text
durable USER_MESSAGE
  -> transactional episodic extraction job
  -> owner-inspectable candidate
  -> owner acceptance/rejection
  -> immutable episodic memory revision
  -> exact versioned embedding in pgvector
  -> standalone RetrievalResult
  -> relevance threshold + duplicate suppression
  -> token-budgeted ContextPack memory section
  -> provider-neutral inference path
```

## Acceptance corrections

The review findings were valid. The first group was corrected in additive migration `0004_stage2_acceptance_corrections.sql`; subsequent groups were corrected in application contracts, Context Builder, persistence logic, tests, and documentation. Already-applied migrations `0003` and `0004` were not rewritten.

- **Complete Stage 2 deletion closure:** the privileged erasure path now runs even when no memory was accepted. It removes matching pending/succeeded jobs, pending/rejected/accepted candidates, memory revisions, heads, embeddings, provenance, retrieval candidate snapshots and both exclusion references (`memory_id` and `duplicate_of_memory_id`), ContextPack sections, inference attempts, route decisions, and assistant events that copied or could have been influenced by the source. Affected interaction requests are retained as content-free failed ledger entries. Raw source-event deletion remains a separate owner-authorized step.
- **Concurrency-safe erasure:** immutable triggers are no longer disabled globally. A transaction-local erasure flag works only for a database role with `havre_privileged_erasure` membership.
- **Source-side owner isolation:** generated typed source columns give event and memory-revision provenance sources real owner-qualified foreign keys. `havre.provenance_integrity_violations` and `havre audit-provenance` provide a repeatable integrity audit; the command exits nonzero when violations exist.
- **Lease ownership:** both success and failure submission require the same `lease_owner`, attempt generation, leased status, and unexpired lease. A stale worker cannot commit after expiry or after a replacement worker reclaims the job; a zero-row update raises `LeaseLostError`.
- **Reviewed-candidate immutability:** only one complete `pending -> accepted|rejected|duplicate` owner-review transition is permitted. After review, content, hash, importance, provenance, and decision are immutable. Importance may be set only as part of owner acceptance.
- **Context safety gate:** the default is `retrieval-r1-vector-gated-v2`, top K defaults to 5, semantic similarity must be at least `0.35`, and duplicates require both token-overlap `>= 0.65` and embedding similarity `>= 0.70`. Below-threshold and duplicate candidates receive explicit exclusion records. `RetrievalResult` rejects inconsistent algorithm/policy/threshold/eligibility combinations, missing/non-finite/below-threshold candidate semantic scores, and repeated candidate content hashes. Context Builder independently repeats those checks plus owner/request/trace/query-event lineage, so a forged boolean or candidate score cannot enter ContextPack.
- **Benchmark fidelity:** Gold fixture importance values are applied during owner acceptance instead of being replaced by extractor default `0.5`.
- **Documentation accuracy:** benchmark artifacts are described as SHA-256 content-hash verified, not digitally signed. ADR-0016 through ADR-0018 now consistently say Accepted.

These retrieval thresholds are an evidence-backed Stage 2 implementation safety gate, not a material privacy, intervention, or governance rule. They remain explicitly versioned and must be re-evaluated when the embedding model or gold set changes.

## Plain-English component guide

- **Durable job/outbox:** a memory-eligible message and its extraction job are stored together, so a crash cannot silently lose the work.
- **Memory worker:** a separate owner-bound worker leases one job at a time with `SKIP LOCKED`; only the current lease holder may finish it.
- **Inspectable candidate:** extraction proposes memory instead of silently declaring a sentence permanent truth. Only the owner can accept, reject, or assign reviewed importance.
- **Memory revision/head:** correction and retraction append immutable revisions; the head points to the current version.
- **Provenance:** every source and derived endpoint is owner-bound, version-specific, auditable, and protected by database constraints.
- **Embedding/pgvector:** Stage 2 uses a deterministic local 64-dimensional feature hash as a reproducible infrastructure baseline, not as a claim of production semantic quality.
- **Retriever and safety gate:** retrieval produces inspectable scores and exclusions. Only candidates that pass relevance and duplicate controls can enter a prompt.
- **Context Builder:** retrieval and prompt composition remain separate. The ContextPack records exact memory/source references, exclusions, token use, and effective privacy.

## Exact versions

| Component | Version |
|---|---|
| HAVRE package | `0.2.3` |
| Interaction orchestrator | `interaction-orchestrator-v4` |
| Context Builder | `context-builder-v5` |
| Episodic extractor | `episodic-extractor-rule-v1` |
| Memory worker | `memory-worker-v3` |
| Memory service | `memory-service-v2` |
| Embedding | `embedding-deterministic-hash-v1` |
| R0 benchmark retriever | `retrieval-r0-recency-v1` |
| Legacy ungated R1 benchmark | `retrieval-r1-vector-v1` |
| Default gated R1 | `retrieval-r1-vector-gated-v2` |
| Context selection policy | `retrieval-selection-context-safe-v1` |
| Index strategy | `memory-exact-scan-v1` |
| PostgreSQL / pgvector | 18.4 / 0.8.6 |

No ANN index is activated: the seven-memory measured corpus does not justify one. Exact scanning remains the reproducible baseline.

## Verification evidence

All **57 tests passed** against a fresh PostgreSQL database after migrations `0001` through `0004`, with 0 failures and 0 skips. The non-database subset is **38/38**. The suite includes the review-requested regressions:

1. deletion before any memory exists, covering a pending job and a rejected candidate;
2. deletion of retrieval-result, ContextPack, inference, route, and assistant-response copies;
3. provenance insertion where only the source belongs to another owner;
4. stale worker completion after another worker reclaimed the lease;
5. deletion propagation through a below-relevance exclusion;
6. deletion propagation through a duplicate-suppressed exclusion;
7. typed rejection of a legacy result with `context_eligible = true`;
8. Context Builder rejection of spoofed versions and mismatched owner/request/trace/query-event lineage;
9. failure submission after lease expiry and after replacement by a newer lease generation;
10. deletion of a snapshot where the source memory appears only as `duplicate_of_memory_id`;
11. result-contract and independent Context Builder rejection of missing, non-finite, and below-minimum semantic scores;
12. result-contract and independent Context Builder rejection of repeated content hashes, with the exact `0.35` boundary still accepted.

It also covers reviewed-candidate immutability, gated empty results, duplicate suppression, rejection of ungated results by Context Builder, owner-reviewed importance, Stage 1 regression, privacy/as-of filtering, correction/retraction, provider swap, timeout, idempotency, and governance isolation.

An additional compatibility exercise created real memory/retrieval/context data using checkpoint `e32c742` and migrations `0001–0003`, then applied only `0004`. Existing rows remained readable, received the explicit `retrieval-selection-legacy-ungated-v1` marker, the integrity audit returned zero violations, and a new gated request successfully retrieved the old memory.

## Reproducible benchmark result

Pinned workload: `retrieval-gold-v1`, 7 synthetic memories with reviewed importance values, 5 reviewed queries, top K = 5, Windows 11, Python 3.12.13, PostgreSQL 18.4, pgvector 0.8.6.

| Metric | R0 recency | Legacy R1 vector | Gated R1 v2 |
|---|---:|---:|---:|
| Recall@5 | 1.00 | 1.00 | 1.00 |
| Recall@10 | 1.00 | 1.00 | 1.00 |
| MRR | 0.457 | 0.90 | 0.90 |
| Wrong-memory rate | 0.80 | 0.76 | **0.375** |
| Stale-memory rate | 0.00 | 0.00 | 0.00 |
| Duplicate-group rate | 0.00 | 0.20 | **0.00** |
| Should-not-surface rate | 0.00 | 0.00 | 0.00 |
| Provenance completeness | 1.00 | 1.00 | 1.00 |
| p50 latency | 0.872 ms | 0.912 ms | 1.083 ms |
| p95 latency | 1.275 ms | 1.196 ms | 1.525 ms |
| Error rate | 0.00 | 0.00 | 0.00 |

A repeat run produced valid SHA-256 content hashes and identical rankings, selection policies, exclusion decisions, and non-latency quality metrics; latency varied normally. The R0 change from the original report is expected because the corrected benchmark now uses the fixture's reviewed importance values. The final erasure/validation correction does not change retrieval ranking and, per the scoped re-acceptance request, the benchmark was not regenerated in that correction run.

The gated result is safer but is not a production semantic-quality claim: wrong-memory rate `0.375` is still too high for broad confidence, and the deterministic embedding is intentionally limited. The raw, SHA-256 content-hash-verified reports are generated under `var/benchmarks/`; immutable benchmark rows are stored in `havre.retrieval_benchmark_runs` during the run.

## Operational commands

```powershell
havre worker-once
havre memory-candidates
havre memory-accept <candidate-id> --importance 0.7
havre memory-reject <candidate-id>
havre memories
havre memory-correct <memory-id> "corrected text"
havre memory-retract <memory-id>
havre audit-provenance
havre benchmark-retrieval
```

## Known limits kept inside Stage 2

- `deterministic-local` still validates contracts and infrastructure rather than conversational ability.
- The extractor proposes direct user-reported episodes; it does not infer beliefs, patterns, diagnoses, goals, or User Model state.
- Authentication and a review UI are still required before broader exposure.
- The implemented deletion closure covers online Stage 2 records. Final source deletion, provider-side deletion, backup expiry/restore replay, and an owner-approved erasure-receipt policy remain future governed work.
- Migration `0004` grants the privileged erasure role to `CURRENT_USER` for local acceptance only. A real deployment must separate migrator, ordinary application, and erasure database roles; the application must not inherit erasure authority.
- The small synthetic benchmark establishes reproducibility and exposes failures; it does not prove general retrieval quality.

## Stop boundary

At the time of this checkpoint, the corrected evidence awaited Product Owner
reacceptance and Stage 3 remained unauthorized. The Product Owner subsequently
accepted Stage 2 and later approved Stage 3. Current authorization is recorded
in [`STATE.md`](STATE.md); this historical checkpoint does not authorize Stage
4.
