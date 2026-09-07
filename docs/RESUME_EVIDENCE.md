# Resume Evidence

## September 2026 additions

The current source also implements shared evidence compilation, lifetime raw
recall, correction/freshness guards, privacy-based GPT/local routing, bounded
relational follow-ups and brief-turn PWA controls. See
[CURRENT_IMPLEMENTATION.md](CURRENT_IMPLEMENTATION.md) for the exact boundaries
and [PUBLIC_TESTING.md](PUBLIC_TESTING.md) for the refreshed 825-test public matrix.

A useful interview claim is: "I built a provider-neutral personal-context system
whose durable source history, privacy, memory revision and delivery authority
remain outside the model." Support that claim with a request trace, a forbidden
cross-owner relationship test, a correction/erasure case and the inconclusive
context ablation. Do not describe a judge's preference as an owner rating or
candidate pipeline feasibility as deployed personalization.

The sections below preserve earlier checkpoint measurements.


This document maps public-facing claims to checked-in evidence. Use the
suggested wording or make it narrower. Do not turn a synthetic benchmark,
candidate run, local deployment, or checkpoint-specific test count into a
production-quality claim.

## Claim map

| Area | Public-safe claim | Direct evidence | Required boundary |
| --- | --- | --- | --- |
| Self-hosted inference | Built a provider-neutral, self-hosted inference path for Qwen3-8B GGUF Q4_K_M through a pinned llama.cpp runtime, with process-bound executable/model/argument/PID/loopback attestation and durable request lineage. | [Stage 3 correction checkpoint](STAGE3_CORRECTION_CHECKPOINT.md), especially “Renewed real durable request evidence” and “Renewed inference benchmark,” plus [Architecture](ARCHITECTURE.md). One accepted run completed 32/32 benchmark requests. A separate durable request measured 514.071 ms TTFT, 329.908 ms generation, and 854.282 ms inference total for that request. | One local hardware/runtime snapshot; not a capacity, production-SLA, or global determinism claim. |
| Memory and retrieval | Implemented owner-qualified, human-reviewed episodic memory with immutable revisions, pgvector embeddings, versioned retrieval, provenance, correction/retraction, and source-erasure closure. | [Stage 2 checkpoint](STAGE2_CHECKPOINT.md); [Database design](DATABASE_DESIGN.md); migrations 0003–0004 and their tests. The checked-in small synthetic benchmark retained Recall@5/10 1.0 and MRR 0.90 while wrong-memory rate changed 0.76→0.375 and duplicate-group rate 0.20→0.00 from legacy R1 to gated R1. | The corpus and deterministic embedding are intentionally small. Wrong-memory rate 0.375 remains material; do not claim production semantic quality. |
| Context provenance | Built a ContextPack pipeline that admits only owner-, request-, trace-, privacy-, revision-, and retrieval-policy-qualified evidence, then persists exact context and inference lineage. | [Architecture](ARCHITECTURE.md), [Event model](EVENT_MODEL.md), [Stage 2 checkpoint](STAGE2_CHECKPOINT.md), and [Stage 3 correction checkpoint](STAGE3_CORRECTION_CHECKPOINT.md). | This supports traceability and fail-closed admission; it does not prove that every generated answer is correct. |
| User Model | Implemented an evidence-bound, versioned User Model for immutable belief revisions, expiring current-state snapshots, goals, progress, proposals, and replayable projections. | [Stage 4 required-provenance correction checkpoint](STAGE4_REQUIRED_PROVENANCE_CORRECTION_CHECKPOINT.md); migrations 0007–0012; [User Model evaluation plan](EVALUATION_PLAN.md). | Historical Stage 4 candidates were rejected before the accepted additive correction. The small deterministic evaluation is infrastructure evidence, not psychological validity. |
| QLoRA | Ran two local Qwen3-8B QLoRA seeds over the frozen public/synthetic Dataset v4 package: 300 train, 60 validation, 120 sealed holdout cases across 20 categories; 600 steps / 2 epochs per seed. | [Stage 9 checkpoint](STAGE9_CHECKPOINT.md), “Frozen Dataset v4 execution package,” “Formal Dataset v4 training,” and “Formal four-arm evaluation.” | Both adapters remained candidate-only, unpromoted, and undeployed. The private OA set is excluded from this public claim and must not be published. |
| Training efficiency | Configured 4-bit NF4 double quantization, BF16 compute, rank-4 / alpha-8 QLoRA over all linear layers, with 10,911,744 trainable parameters. Formal PyTorch peak reserved memory was 10,968 MiB per seed on a 12 GiB GPU; the preflight gate observed 5,078 MiB. | [Stage 9 checkpoint](STAGE9_CHECKPOINT.md), training configuration and resource evidence. | State both measurement phases. “Used half the GPU” is not supported; 5,078 MiB was preflight, while formal training reserved 10,968 MiB. |
| Evaluation | Built frozen, hash-bound evaluation packages with exact case membership, four arms (Base, Base+Memory, Base+Adapter, Base+Memory+Adapter), sealed holdout execution, paired comparisons, and immutable reports. | [Stage 9 checkpoint](STAGE9_CHECKPOINT.md); [Evaluation plan](EVALUATION_PLAN.md); tracked reports under evals/reports. Each formal seed completed 120 sealed cases across all four arms. | Diagnostic scores are not a companion-quality score and did not authorize promotion. |
| Candidate rejection | Preserved rejected candidates and separated raw-model behavior from Core containment. The v7 replay recorded 10/40 deterministic hard passes for raw output and 32/40 after Core policy; v7 stayed rejected. | [v6 checkpoint](STAGE9A_V6_STYLE_FIRST_CHECKPOINT.md), [v7 checkpoint](STAGE9A_V7_CAPABILITY_PRESERVING_CHECKPOINT.md), [model-vs-Core checkpoint](STAGE9A_MODEL_VS_CORE_RESPONSIBILITY_CHECKPOINT.md), and [ADR-0022](adr/0022-core-governed-response-delivery.md). | Runtime containment is not credited to the model. Rejected candidates are not releases and must never be presented as deployed behavior. |
| Response delivery | Implemented a Core policy boundary that preserves raw output while binding the visible assistant Event to separate decision and delivered-output hashes. | [ADR-0022](adr/0022-core-governed-response-delivery.md), [model-vs-Core checkpoint](STAGE9A_MODEL_VS_CORE_RESPONSIBILITY_CHECKPOINT.md), migrations 0036–0037, and focused tests. | The policy owns safety/provenance/serialization boundaries, not natural conversation quality or personality-model judgment. |
| Feedback and edits | Implemented owner-local conversation history, exact episode membership, response ratings, owner edits, original-response preservation, and complete inference provenance. | [Daily-use feedback checkpoint](DAILY_USE_FEEDBACK_CHECKPOINT.md), [ADR-0021](adr/0021-daily-conversation-feedback-and-episode-learning.md), and the Web/integration tests. | Feedback remains training_eligible=false. It is not a private-data training pipeline and does not authorize Stage 9B. |
| Deployment and rollback | Exercised immutable Docker image deployment, HTTPS/HSTS, two-phase activation, rollback, failure recovery, release-bound backup/restore, deletion replay, and exact-image verification on owner-controlled infrastructure. | [Stage 10 checkpoint](STAGE10_CHECKPOINT.md) and tracked Stage 10 native evidence. That checkpoint reports 385 passed, 0 failed, 0 skipped. | Infrastructure-only evidence. No QLoRA adapter was promoted or deployed; this is not production-scale or multi-user availability proof. |
| Verification discipline | Maintained PostgreSQL-backed fresh/upgrade, direct-SQL adversarial, provenance-audit, contract, benchmark, and environment-specific ML test evidence, with rejected checkpoints retained rather than overwritten. | Accepted and rejected checkpoint chain in [docs](./), plus [State](STATE.md). Examples: Stage 9 recorded 286/286 primary tests plus 57/57 training-contract tests; the daily-use checkpoint recorded 469/469 across its two declared environments. | Counts belong to the named source snapshots and environments. Quote the checkpoint and date; do not imply they are the current HEAD count. |

## Three compact resume bullets

These are the strongest concise versions supported by the repository:

- Built a provider-neutral personal-AI runtime around Qwen3-8B and llama.cpp
  with process-bound model/runtime attestation, durable PostgreSQL event and
  inference lineage, and a 32/32 local inference benchmark at the accepted
  checkpoint.
- Designed human-reviewed pgvector memory and fail-closed ContextPack retrieval
  with immutable revisions and provenance; on a checked-in synthetic fixture,
  reduced wrong-memory rate from 0.76 to 0.375 and duplicate-group rate from
  0.20 to 0.00 while retaining Recall@5/10 of 1.0.
- Ran two single-GPU Qwen3-8B QLoRA candidates (10.9M trainable parameters,
  NF4/BF16, 10,968 MiB peak reserved memory), evaluated four sealed arms, and
  rejected unsafe candidates instead of promoting or deploying them.

## Claims that are not supported

Do not claim:

- production-ready, bug-free, high-availability, multi-user, or capacity-tested;
- that a deterministic provider or synthetic demo proves model quality;
- that Stage 6 simulation delivered real proactive contact;
- that an iPhone client, Screen Time integration, Stage 9B, or broader sensing
  is active;
- that any QLoRA adapter is the production HAVRE model;
- that Core policy improvements rehabilitated the rejected v6/v7 models;
- that private daily feedback or OA material trained any model;
- broad psychological validity, memory correctness, or relationship quality;
- a current test count unless it was rerun on the exact current commit and the
  environment and skip count are reported.

## Public evidence boundary

Public evidence may include code, public/synthetic fixture definitions,
redacted aggregate measurements, accepted/rejected checkpoint conclusions, and
hashes of public artifacts. It must exclude:

- owner-private data and real owner interaction content;
- the OA material, its case text, derived per-case output, or private reports;
- real chat logs, feedback text, memory contents, and screenshots from the
  owner database;
- secrets, bootstrap tokens, environment files, cookies, or credentials;
- generated model weights, runtime databases, backups, logs, and local paths.

See [PUBLIC_RELEASE_AUDIT.md](PUBLIC_RELEASE_AUDIT.md) before publishing.
