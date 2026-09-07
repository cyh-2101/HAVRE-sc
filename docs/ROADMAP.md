# HAVRE Roadmap

## Owner-approved short conversational turns (2026-09-06)

The owner approved brief default turns with optional “再说点”, while preserving
complete requested work, recall and Goal behavior. The [verified implementation](SHORT_TURNS_REVIEW_2026-09-06.md)
extends ADR-0033's adaptive conversation behavior: new instructions and PWA v17
are loaded owner-locally, with 922 tests passing, zero skips, 13/13 context budgets
and unchanged targeted source sets. No Context architecture, model, training or
proactive authority expansion is introduced. Naturalness remains owner-use
validation rather than a sentence-count score. No new Stage, commit or push.

## Targeted recall after accepted Context A/B (2026-09-06)

The owner retained the production architecture and authorized a bounded repair of
S03/S04 source/entity ambiguity, regression tests and a small owner blind review.
The [local implementation and verification](TARGETED_RECALL_REVIEW_2026-09-06.md)
retain both same-name source alternatives without relaxing global thresholds;
909 tests pass with zero skips. The eight-pair owner packet is ready, with choices
pending and training eligibility false. New cloud semantic verification requires
the exact-payload/cost authorization requested after automatic approval rejection.
No architecture switch, new Stage, production restart, training, promotion, commit
or push is included in this follow-up.

## Bounded Context A/B after the accepted checkpoint (2026-09-06)

The owner accepted the fresh review as a stable checkpoint and limited the next
work to a fixed-model blind context comparison, recall stress cases, necessary
fixes, tests, review and local commit, without push or training. The
[completed experiment](CONTEXT_AB_EXPERIMENT_2026-09-06.md) records Simple 12 / Full 8 /
tie 1 / unresolved 11 on 32 real cases. After detecting date and word-boundary
corruption in experimental deidentification, all 80 real answers and 80 reviews
were rerun with unchanged targets and audited final provider inputs; earlier real
analyses are invalidated diagnostics. Simple share is 56.3%, its family-clustered
95% interval is 42.9%–65.9%, and order agreement is 65.6%, below the frozen gate.
All eight repeat consensus labels change, including two direct arm reversals.
No global winner or production context policy is adopted. Twelve constructed
stress cases remain separate evidence, including unresolved source-admission gaps.
Final verification is 824 primary plus 62 pinned-Torch tests, zero skips.
The runtime baseline below stays active; this experiment adds no Stage authority,
model promotion, new service or architecture mandate. Stop after the local commit.

## Owner-authorized evolution after the fresh review (2026-09-06)

The owner explicitly authorized a fresh evidence-led reassessment, justified
architecture changes, implementation, additive migration, validation, independent
review and local commits without push. This task is not limited by earlier Stage
labels. [ADR-0039](adr/0039-personal-context-engine-and-evidence-compiler.md) records
its durable direction: personal history and identity persist independently of the
Brain, with shared evidence compilation and governed delivery.

The implemented slice addresses concrete-history admission, lifetime raw recall,
owner correction/retraction continuity, cross-path identity, delayed-source
freshness and explainable Memory UI. The
[review/checkpoint](PERSONAL_CONTEXT_ENGINE_REVIEW_2026-09-06.md) records exit
measurements separately from long-term owner usefulness. New data disclosure,
sensing, trust boundaries, recurring services, training and model promotion remain
separate decisions. Existing stage entries below remain historical evidence and
roadmap dependencies, not permission to override these owner limits.

Status: **Stage 6/7 accepted; Stage 8 technically accepted without promotion; Stage 9 closed at the candidate-only boundary; Stage 10 complete; Stage 11 at an implementation checkpoint but not exited; Stage 12A at a disabled implementation checkpoint; daily Web chat/episode/feedback is active; ADR-0026 retires Seed 9201 from default use; ADR-0027 authorizes Stage 13A-C conversation-intelligence implementation and candidate evidence; ADR-0028 implements the PUBLIC-only Stage 14A MCP pilot; ADR-0029/0030's Stage 14B DataPolicy-driven GPT/unadapted-Qwen dual route is technically verified and active owner-locally while its Practical Utility Gate remains open; Stage 13D local-model promotion, private-data cloud admission, Stage 9B, and Stage 12B remain separate owner gates**

Authority: [`MASTER_PLAN.md`](../MASTER_PLAN.md)

## 1. How stages work

Each stage activates a permanent part of the final architecture. A stage is complete only when it has:

1. an owner-visible problem statement and final-architecture role;
2. versioned inputs, outputs, failure modes, and privacy boundaries;
3. tests plus an evaluation/benchmark plan written before implementation;
4. implementation that uses the locked boundaries rather than a throwaway path;
5. real measurements where relevant, with reproducible artifacts;
6. updated `docs/STATE.md` and ADRs for changed decisions;
7. a “what you should understand” handoff;
8. explicit Product Owner approval before the next stage.

Stages define dependency order, not fixed calendar time. A later concern may have a small contract or safety check earlier; its full capability activates at the named stage.

Every stage is also reviewed against five permanent North Star flows:

1. **Talk** — user-initiated meaningful discussion;
2. **Prepare** — planning for a real-world situation;
3. **Guide** — low-bandwidth support during the situation;
4. **Reflect** — examining what happened afterward;
5. **Reach Out** — HAVRE initiates contact for a clear, explainable, user-benefiting reason.

Reach Out connects the other flows; it never replaces them. A stage may provide evidence or prerequisites without activating proactive delivery.

## 2. Stage 0 — Architecture Lock + Measurement Contracts

### Problem and final role

Without stable boundaries, early chat, memory, and provider code would harden into a disposable architecture. Stage 0 defines the durable seams and what evidence future changes must produce.

### Deliverables

- source-of-truth `MASTER_PLAN.md` at the expected path;
- architecture, database, event, ML systems, evaluation, benchmark, roadmap, and state documents;
- ADR process and proposed decisions;
- permanent repository skeleton proposal;
- Raw Event, trace propagation, provider, inference, memory, retrieval, Context Pack, evaluation, benchmark, registry, dataset, and provenance contracts;
- explicit unresolved decisions and recommended Master Plan clarifications.

### Exit gate

- all requested contracts exist and agree on IDs, versions, provenance, privacy, and ownership;
- no product feature has been implemented;
- all ADRs remain `Proposed` until Product Owner review;
- Stage 0 walkthrough covers interaction, memory retrieval, and training/deployment flows;
- Product Owner explicitly approves, rejects, or requests revision.

### Stage 0.1 focused revision

Directional Stage 0 approval opened a documentation-only refinement, not implementation. Stage 0.1 added provider-independent privacy/use policy, temporal belief history, first-class Scene Sessions, governed Constitution-to-learning hierarchy, outcome-aware evaluation, and an explicit permanent Stage 1 vertical slice. The Product Owner approved this baseline on 2026-08-13 and authorized Stage 1 only.

### Proactive Interaction documentation amendment

After approving Stage 1, the Product Owner accepted a documentation-only architecture amendment before Stage 2. It adds Reach Out, durable Trigger/ProactiveProposal contracts, Core-owned Interruption Policy, owner controls and anti-annoyance limits, provider-neutral privacy-safe delivery, response linkage, and proactive evaluation/benchmark coverage. ADR-0016 through ADR-0018 are accepted future boundaries. No proactive runtime is activated in Stage 2.

### Ambient Life Context and experience-to-memory amendment (accepted)

After Stage 5 acceptance, the Product Owner requested an upstream context and multi-year memory clarification. On 2026-08-19 the Product Owner accepted [`AMBIENT_LIFE_CONTEXT.md`](AMBIENT_LIFE_CONTEXT.md), ADR-0019, and ADR-0020 and authorized conservative Stage 6 followed by Stage 7 implementation. Only synthetic/manual local contracts are active; no external source, sensor, real contact, private-data export, or governance-policy change is authorized.

## 3. Stage 1 — Companion Foundation + End-to-End Trace

### Build

Activate this smallest real vertical slice of the final architecture:

```text
User request
  -> request_id
  -> W3C trace
  -> durable raw USER_MESSAGE Event + DataPolicy
  -> approved Constitution / Identity / Values loading
  -> minimal token-budgeted ContextPack + provenance + effective privacy
  -> provider-neutral ModelProvider / InferenceRequest
  -> model response
  -> durable delivered ASSISTANT_MESSAGE Event
  -> metrics + exact versions + provenance
```

Implementation work is limited to what supports that slice:

- Python project/package structure and dependency lock;
- FastAPI service; the worker executable boundary remains reserved but inactive because the owner-approved slice has no background work;
- PostgreSQL migrations for owner, Constitution/identity/value versions and approval records, sessions, request idempotency, events, direct DataPolicy snapshots, protected Context Pack/route/inference metadata, and trace correlation;
- human-approved, model-independent Constitution/Identity/Values package;
- provider-independent DataPolicy resolution with separate `memory_eligible`, `training_eligible`, and `cloud_eligible` flags;
- Model Provider, inference, route, and minimal Context Pack contracts in Pydantic;
- one versioned local deterministic acceptance provider behind the permanent provider port;
- API and CLI development ingress; no web UI in the owner-limited Stage 1 slice;
- end-to-end `request_id`/`trace_id`, event persistence, idempotency, provenance, exact version metadata, and typed failures.

Stage 1 does **not** activate memory retrieval, User Model belief inference, Intervention Policy, Scene Sessions, reflection/consolidation, dataset construction, or training. Their final contracts exist so later stages insert them into this slice rather than replace it.

### Why it remains

This is the permanent ingress, governance, data-policy, identity, event, context, provider, provenance, and trace foundation. Later models and clients reuse it; later Companion capabilities enter between identity/context construction and provider inference.

### Evaluation and measurement

- DataPolicy/event/provider/context/trace/provenance contract tests;
- append-only and owner-isolation database tests;
- provider swap test without changing Companion Core;
- deterministic behavioral smoke suite;
- end-to-end stage latency recorded as a development baseline, not a performance claim;
- privacy test proving raw message content is absent from ordinary telemetry.
- enforcement test proving `LOCAL_ONLY` never enters a cloud adapter and unresolved policy fails closed;
- governance test proving no worker/model/adapter can activate a Constitution or identity version;
- training eligibility defaults false even when memory/cloud eligibility is true.

Correction verification on 2026-08-13 covers every item above, including owner-qualified database relationships and evidence reads, a provider swap through the unchanged Companion Core, rejection of provider/model governance activation, enforced inference timeout, and content-bound idempotency. The same suite passes repeatedly on the migrated historical test database and from scratch on a new database.

The Product Owner formally approved Stage 1 on 2026-08-13. The approved behavior remains unchanged by the Proactive Interaction documentation amendment.

Stage 1 provenance is expressed through direct immutable source references on events, Context Pack sections, inference attempts, and response events. The generic cross-artifact provenance graph activates in Stage 2 without replacing these references.

### Required Product Owner decisions before production-like personal use

- initial identity and communication/boundary files;
- initial Constitution/Core Principles package and definition of material human-approved changes;
- privacy-class names/defaults, explicit declassification authority, and whether cloud-safe redaction/omission is ever permitted;
- whether any cloud provider may receive highly private content and under what consent/redaction rules;
- authentication and local access model;
- crisis/professional-help boundary;
- initial export/erasure behavior and backup policy.

### Exit evidence

One interaction has a request ID, complete trace, durable `USER_MESSAGE` and delivered `ASSISTANT_MESSAGE` events, explicit DataPolicy, approved Constitution/Identity/Values versions, a reproducible policy-enforced Context Pack, provider-neutral inference, exact provider/model metadata, provenance links, and measured trace/inference metrics. No provider binding exists in domain code, and every step is part of the final pipeline.

## 4. Stage 2 — Episodic Memory + Retrieval Benchmark

### Build

- immutable memory revisions and provenance edges;
- episodic extraction job with idempotency and human-inspectable candidates;
- embedding version registry and pgvector storage;
- Retrieval Request/Result contract implementation;
- simple candidate search, filters, transparent scoring, and Context Builder integration;
- memory correction/retraction and source deletion propagation;
- manually reviewed retrieval gold set v1.

### Why it remains

This is the first durable long-term-memory and independently measurable retrieval pipeline.

### Evaluation and measurement

- provenance and evidence completeness;
- exact replay with `as_of`;
- Recall@5, Recall@10, MRR, wrong/stale/duplicate rate;
- p50/p95 retrieval latency under a pinned corpus/environment;
- comparison of metadata/recency baseline with embedding retrieval;
- inappropriate-intimate-memory cases.

### Exit evidence

A new interaction retrieves a relevant episodic memory through a standalone result contract, the answer's Context Pack shows whether it was used, and the benchmark report contains real reproducible measurements.

### 2026-08-13 implementation checkpoint

Implemented and verified after successive acceptance-correction rounds. Additive migration `0004` closes the original online deletion, provenance, candidate-immutability, and lease-completion gaps without rewriting `0003`. Application corrections follow candidate references plus both exclusion reference fields during erasure, require the exact gated retrieval contract and lineage twice before ContextPack injection, verify every admitted candidate's actual semantic score and unique content hash, and fence failure submission to an active lease. The fresh-database suite passes 57 tests, and the previously verified populated `0001–0003` database upgrades in place. `retrieval-gold-v1` applies reviewed importance and compares R0, legacy R1, and gated R1 v2; the gate reduces measured wrong-memory rate from 0.76 to 0.375 and duplicate rate from 0.20 to 0 without reducing Recall@5 on the small corpus. See [`STAGE2_CHECKPOINT.md`](STAGE2_CHECKPOINT.md). The Product Owner accepted Stage 2 and explicitly authorized Stage 3 on 2026-08-13.

## 5. Stage 3 — Self-hosted Inference Baseline

### Build

- independently deployable inference service behind an OpenAI-compatible adapter;
- one open-weight model that available hardware can run reliably;
- streaming, health/version endpoints, typed errors, and resource metrics;
- inference benchmark harness and immutable environment/workload manifests.

### Why it remains

HAVRE needs a user-controlled Personal Brain boundary whose serving engine/model can be benchmarked and replaced.

### Evaluation and measurement

- TTFT, TPOT, end-to-end latency, tokens/sec, throughput, VRAM/utilization, and errors;
- short scene, standard chat, long reflection, and structured-extraction workloads;
- behavioral compatibility with the Stage 1 provider baseline;
- at least one controlled serving/config comparison if hardware permits.

### Exit evidence

The same Companion interaction runs through the self-hosted provider by configuration, not domain-code edits, with real benchmark and quality reports.

### 2026-08-13 implementation checkpoint

The 2026-08-13 checkpoint implemented additive migration `0005`, a loopback-only OpenAI-compatible adapter, pinned Qwen3-8B Q4_K_M weights, pinned llama.cpp b10405 CUDA serving, ordered SSE, typed durable failures, and immutable paired benchmark reports. Fresh installation and a populated `0001–0004` database upgraded in place each passed the then-current 132-test suite. Two counterbalanced real benchmark runs completed 32/32 measured requests. A later acceptance review found that benchmark startup attestation was stronger than the ordinary interaction path: configured model/runtime identifiers could be persisted without a process-bound artifact proof. The additive `0006` correction now has renewed fresh and populated-upgrade PostgreSQL evidence, two zero-skip 154-test passes, zero-violation provenance audits, a durable attested `LOCAL_ONLY` Qwen request, and a new source-bound immutable benchmark pair. Exact evidence is tracked in [`STAGE3_CORRECTION_CHECKPOINT.md`](STAGE3_CORRECTION_CHECKPOINT.md). The Product Owner approved Stage 3 on 2026-08-14 at source snapshot `sha256:9a43713e082dec08039a93c673c7a0af812b881dcb0d5d3da68a0b17e7075436`. Stage 4 was subsequently authorized and implemented as recorded below.

## 6. Stage 4 — User Model + Pattern + Progress + Goals

### Build

- belief revisions with confidence method, supporting and counter-evidence;
- bitemporal belief history separating event occurrence, HAVRE learning time, revision creation, real-world validity, and contradiction/supersession/retraction/invalidation time;
- semantic, pattern, and progress memory semantics;
- reality and inner-life goal tracks with evidence-linked progress;
- consolidation proposals and human correction flow;
- explicit separation between expiring Current State and durable User Model;

### Evaluation and measurement

- evidence-sequence replay;
- unsupported-belief, counter-evidence-retention, false-stability, revision, and calibration tests;
- goal/progress provenance checks;
- behavioral cases for mistaken understanding and user correction;
- proposal-evidence fixtures may be drafted for future Reach Out, but Stage 4 User Model/Goals cannot authorize or deliver outreach.

### Exit evidence

HAVRE can state a qualified belief, show support and counter-evidence, revise it without deleting history, and avoid treating one bad day as a stable trait.

The 2026-08-14 implementation activates additive migration `0007`, immutable
owner-reviewed belief revisions and append-only transitions, typed evidence and
counter-evidence, bitemporal replay, semantic/pattern/progress memory classes,
proposal-only consolidation with owner correction, expiring Current State,
reality/inner-life goals, and evidence-linked progress. Context Builder v6
admits only qualified, owner/privacy/budget-safe personal context. The Product
Owner rejected the first acceptance checkpoint and the first correction
checkpoint. Additive migration `0009` retains exact `0001`-`0008` bytes and
replaces cross-clock belief-head freshness with single-use qualified transition
identity, binds Goal hash/time to immutable complete projections and PostgreSQL
statement time, and adds the remaining derived-memory provenance FK index. A
later Product Owner review rejected opaque Goal canonical material. Additive
`0010` retains exact `0001`-`0009` bytes, enforces strict complete Goal/DataPolicy
key sets, reconstructs the unique canonical projection in PostgreSQL, and hashes
only that reconstruction. A later probe found INSERT was not guarded. Additive
`0011` retains exact `0001`-`0010` bytes and requires active revision 1 plus an
exact same-owner GOAL_CREATED event, projection, digest, causation, and
database-authored timestamps. A fresh `0001`-`0011` installation and populated
`0010`-to-`0011` in-place upgrade each pass the complete 175-test
PostgreSQL-backed suite with zero failures and zero skips; provenance and Stage
4 FK-index audits are empty. Exact raw INSERT probes return SQLSTATE `55000`,
and the replay regression passes 100/100 in separate processes.
The regenerated frozen eight-case synthetic suite passes but remains
non-binding and evaluates no confidence calibration. Exact renewed evidence
and limitations are in
[`STAGE4_GOAL_INSERT_GUARD_CHECKPOINT.md`](STAGE4_GOAL_INSERT_GUARD_CHECKPOINT.md).

A later reacceptance review found that raw belief and Goal-progress rows could
omit required support provenance, the audit did not report absent edges, and
nullable Goal fields could not be cleared. Additive `0012` retains exact
`0001`-`0011` bytes; it adds belief/progress INSERT guards, deferred exact
required-provenance constraints for belief, consolidation, Current State, and
Goal progress records, missing-edge audit coverage, and distinct omitted/null
Goal update semantics. Fresh `0001`-`0012` and populated `0011`-to-`0012`
paths each pass the complete 177-test PostgreSQL suite with zero failures and
zero skips; provenance and Stage 4 FK-index audits are empty. Exact current
evidence is in
[`STAGE4_REQUIRED_PROVENANCE_CORRECTION_CHECKPOINT.md`](STAGE4_REQUIRED_PROVENANCE_CORRECTION_CHECKPOINT.md).
The Product Owner accepted Stage 4 on 2026-08-14 at execution-source snapshot
`sha256:34b65d5e9f2f2902369e0cd4d33f0f673a962f11ba17a899ed4727ea030435c8`.

## 7. Stage 5 — Intervention Policy + Scene System

### Build

- versioned structured Intervention Decision;
- first-class Scene Session aggregate and Before/During/After state machine;
- durable Situation → Intervention → Real-world Action → Outcome → Reflection links;
- web-based low-bandwidth scene signals;
- action, outcome, and post-scene reflection capture;
- safety/ambiguity branches that can prefer clarification, recovery, or help over action pressure;
- Scene phase/status and intervention outputs needed as future Proactive Core timing/meaning inputs; Stage 5 still does not authorize or deliver outreach.

### Evaluation and measurement

- policy decision evaluated separately from generated wording;
- scene phase correctness and interruption/recovery tests;
- during-scene response length and time-to-guidance;
- danger versus avoidance, exhaustion, coercion, and anti-dependence suites;
- outcome/progress provenance;
- consented action-attempt, Scene completion, helpfulness, passivity, forcefulness, and later-regret observations with missingness reported as unknown.

### Exit evidence

One simulated Scene Session completes all phases with durable Situation/Intervention/Action/Outcome links and creates evidence without turning live guidance into a full chat burden. No real-world benefit is claimed until consented outcome measurements exist.

### 2026-08-14 implementation checkpoint

The Product Owner authorized Stage 5 implementation limited to Intervention
Policy, Scene Session, and Web simulation. Additive migration `0013` and the
versioned local API/Web slice now implement guarded Before/During/After state,
structured candidate intervention decisions, low-bandwidth categorical
signals, durable action/outcome/reflection links, consented outcome
observations, exact owner/policy/provenance boundaries, and conservative source
erasure. Every decision is simulation-only and forbids outreach.

Fresh `0001`-`0013` and populated `0012`-to-`0013` databases each passed the
complete 193-test PostgreSQL suite with zero failures and zero skips.
Provenance and Stage 5 FK-index audits were empty. The frozen synthetic policy
suite passed 10/10 branch and wording cases with zero outreach-authorized
decisions. This establishes the Roadmap's simulated exit evidence only; it
does not establish real-world benefit, calibrated danger inference, or a
production Web release. Exact commands, results, limitations, and the
acceptance boundary are recorded in [`STAGE5_CHECKPOINT.md`](STAGE5_CHECKPOINT.md).
At this historical checkpoint Stage 5 stopped at Product Owner acceptance; the
later review rejected the snapshot described above. The correction checkpoint
below is the current gate and still does not self-approve Stage 5 or authorize
Stage 6.

### 2026-08-14 acceptance correction checkpoint

Independent acceptance review rejected the initial `0013` snapshot after
reproducing four integrity blockers: complete Scene erasure rolled back on a
decision/record FK cycle; the database admitted a During signal while the
Scene was still Before; a caller could advance the Scene projection with a
future start time and stale digest; and an intervention record could mix one
decision with another decision's guidance.

Additive `0014` leaves `0001`-`0013` unchanged. It closes the erasure cycle and
rehashes retained detached events, makes current Scene state authoritative,
uses database-bound UTC transition time, reconstructs canonical hashes from
actual rows, and requires an exact input/decision/guidance/policy chain. Four
adversarial regressions preserve the reproduced failures.

A later re-acceptance run exposed one cross-stage evidence-ordering ambiguity
when a user event and terminal failure shared `recorded_at`. Request evidence
now uses monotonic event ID as its stable secondary key, and a deterministic
equal-timestamp regression preserves the failure.

Fresh `0001`-`0014` and a populated `0013`-to-`0014` database containing a
complete historical Scene each passed the full 198-test PostgreSQL suite with
zero failures and zero skips. The old Scene remained readable; migration
reapplication, provenance audits, and Stage 5 FK-index audits were empty. A
separate populated `0012` path applying `0013` and `0014` passed the same suite.
Exact evidence, limits, and source snapshot are recorded in
[`STAGE5_ACCEPTANCE_CORRECTION_CHECKPOINT.md`](STAGE5_ACCEPTANCE_CORRECTION_CHECKPOINT.md).
The Product Owner accepted Stage 5 on 2026-08-14 and bound acceptance to the
execution-source snapshot in the correction checkpoint. This acceptance does
not authorize Stage 6.

## 8. Stage 6 — Proactive Core + Context Optimization + Adaptive Routing

### Build

- controlled Context Builder strategies and prefix-stable sections;
- cache instrumentation and only evidence-justified caches;
- rule-based router with hard privacy/capability filters, reasons, fallback, and calibration data;
- small/large or fast/strong eligible provider profiles;
- versioned Trigger Source contracts for scheduled time, Goals, Scene lifecycle, owner reminders, belief-confirmation candidates, and system-operational evidence; no Calendar/location/wearable connector yet;
- synthetic/manual `LifeContextObservation` fixtures may exercise observation → Trigger boundaries if ADR-0019 and Stage 6 are separately approved; fixtures remain explicitly simulated and no external source is activated;
- first-class `ProactiveProposal`, owner preference revisions, and append-oriented lifecycle;
- Core-owned `InterruptionPolicy` returning `SEND_NOW`, `DEFER`, `DROP`, or `REQUEST_OWNER_CONFIRMATION` with inspectable reasons;
- global/category permissions, quiet hours, budgets, cooldowns, duplicate suppression, expiration, snooze, dismissal, stop-reminding, and non-response frequency reduction under owner-approved defaults;
- purpose-bound proactive Context Packs and rendering through deterministic template, small/local, Personal Brain, or stronger eligible model paths only after `SEND_NOW`;
- provider-neutral Web/inbox delivery with idempotent attempts, safe retry/reconciliation, privacy-safe preview artifacts, and explicit response linkage;
- activation of the accepted PostgreSQL-backed worker/job boundary for scheduled and event-driven proactive work; no dedicated queue without measured need.

### Prerequisites and boundary

Stage 6 Proactive Core begins only after Stage 4 Goals/User Model and Stage 5 Scene/Intervention foundations are accepted and after a new explicit Product Owner authorization. A Trigger is evidence and a Proposal is a candidate, not permission. Models and Context Sources may supply evidence/proposals but cannot authorize, schedule, or deliver. Windows, email, iOS push, Calendar, location, wearables, and sensors remain later-stage work.

### Evaluation and measurement

- top-K, summary/raw, compression, and prefix layout comparisons;
- always-strongest baseline versus router;
- quality retention, wrong-route severity, TTFT/end-to-end latency, cost, cache hit/staleness, and fallback;
- privacy/capability constraint violations as critical gates;
- four-way Interruption Policy labeled cases, false-positive/false-negative outreach analysis, and understandable-reason coverage;
- unnecessary outreach, dismissal, ignore, snooze, duplicate, burden, too-passive, too-forceful, and later-regret observations with missingness/denominators;
- trigger-to-proposal, evaluation, rendering, delivery, scheduling accuracy, failure, retry, duplicate-visible-effect, expiration-before-delivery, and trace/provenance completeness metrics;
- critical tests for Core-only authorization, owner controls, cancellation/stop, privacy-safe previews, no assistant event before delivery, and no escalation from silence.

### Exit evidence

A complete Web/inbox Reach Out fixture records trigger → proposal → four-way policy decision → authorized rendering → delivery attempt → delivered message or conservative stop, with exact reason/privacy/provenance/trace and no model-owned authorization. A separate report shows a real quality/latency/cost trade-off; routing or caching is adopted only if evidence supports it. No real-world proactive benefit is claimed until consented outcome evidence exists.

### Implementation checkpoint

The initial candidate and first correction candidate were rejected after acceptance review reproduced concurrency bypass, missing required paths, and stale preference execution. Additive `0021` supplies the required controls/workers; additive `0022` supplies an authoritative preference head and resolves it under the same owner lock as preference saving before every new execution. The later accepted Daily Companion delivery amendment is recorded in ADR-0023. ADR-0024 and additive `0049`-`0050` now activate a bounded owner-local automatic evaluator: only explicit time-bound reminders, exact current active Goal review times, and exact current planned Scene start times may enqueue work. Memory, beliefs, Current State, Calendar/Life Context, ordinary conversation, and silence cannot independently trigger. Execution rechecks current Goal/Scene projections; Interruption Policy remains the only send authority. Owner preference revision 15 enables Reach Out with no cooldown/quiet hours and separately authorizes only the four-field generic Push envelope for LOCAL_ONLY messages. Current evidence is in [`STAGE67_SECOND_ACCEPTANCE_CORRECTION_CHECKPOINT.md`](STAGE67_SECOND_ACCEPTANCE_CORRECTION_CHECKPOINT.md), [`PRIVATE_CROSS_DEVICE_WEB_PUSH_CHECKPOINT.md`](PRIVATE_CROSS_DEVICE_WEB_PUSH_CHECKPOINT.md), and [`AUTOMATIC_PROACTIVE_REACH_OUT_CHECKPOINT.md`](AUTOMATIC_PROACTIVE_REACH_OUT_CHECKPOINT.md).

## 9. Stage 7 — Reflection + Consolidation + Offline Data Pipeline

### Build

- daily reflection and periodic consolidation worker flows;
- canonical training candidate builder that consumes only explicitly `training_eligible` sources, independently of memory/cloud eligibility;
- review, quality filtering, deduplication, and privacy deletion lineage;
- immutable dataset snapshots and split/holdout policy;
- artifact manifests and reproducibility checks;
- Reflection/Consolidation-generated proposal candidates for pattern checking, unresolved contradiction, progress recognition, and follow-up; Proactive Core remains the only delivery authority.
- explicit experience-to-memory promotion/review by memory class;
- contradiction, temporal validity, supersession, retraction, archival, and reconsolidation proposals;
- provenance-bound derived-data regeneration that cannot resurrect erased/expired sources.

### Evaluation and measurement

- extraction/reflection factuality and provenance;
- dataset acceptance/rejection, duplicate, review, category, and leakage metrics;
- snapshot reproducibility and erasure revocation tests;
- job backlog, throughput, retry, and terminal-failure metrics;
- tests proving Reflection/Teacher outputs can create only proposals and cannot produce `SEND_NOW` or call delivery.
- lifecycle replay proving ordinary Events are not automatically Memories, historical/current validity remain distinct, retrieval decay does not mutate truth, and regeneration uses only eligible sources.

### Exit evidence

The same immutable source snapshot rebuilds the same canonical member manifest; no model-specific tokenization is treated as source truth.

### Implementation checkpoint

The initial candidate and first correction candidate were rejected after acceptance review proved revoked-source regeneration, transactional loss of failure state, unbound job idempotency, and a remaining lifecycle-proposal/erasure race. Additive `0022` makes every evidence admission take the same owner/source transaction locks as erasure before checking revocation, including direct SQL. Reflection remains proposal-only. Current evidence is in [`STAGE67_SECOND_ACCEPTANCE_CORRECTION_CHECKPOINT.md`](STAGE67_SECOND_ACCEPTANCE_CORRECTION_CHECKPOINT.md).

## 10. Stage 8 — Unified Evaluation + Observability Operations

### Build

- unified runner/reporting for behavioral, retrieval, context, routing, inference, and regression suites;
- trace explorer using the vendor-neutral contract;
- judge calibration and human adjudication workflow;
- release comparison report and automated non-critical gates;
- protected artifact access/retention;
- unified proactive policy/usefulness/interruption-quality suites and proactive trace/provenance exploration;
- reports that keep “was the wording good?” separate from “should HAVRE have contacted the user?”.
- source-health, freshness, coverage/missingness, consent/revocation, and minimized-signal evaluation;
- memory promotion, stale-current-use, archival/reconsolidation, and erasure-regeneration evaluation.

### Clarification

Evaluation and tracing begin in Stages 1–3. Stage 8 operationalizes them into a unified platform; it does not introduce them for the first time.

### Exit evidence

A candidate release produces one evidence bundle linking per-case results, systems benchmarks, traces, exact versions, exceptions, and an explicit approval/rejection decision.

### Implementation checkpoint

The independently reviewed Stage 8 closure bundle and its exact limitations are
recorded in [`STAGE8_CHECKPOINT.md`](STAGE8_CHECKPOINT.md). The review reported no
P1/P2 blockers and authorized only the already-approved Stage 9 candidate
foundation transition; no release was promoted.

## 11. Stage 9 — Personal LoRA / QLoRA

### Build

- framework-selected training pipeline behind canonical datasets;
- model-specific rendering/tokenization artifacts;
- adapter/model/training registry and exact compatibility checks;
- candidate-only adapter deployment path.
- proof that training cannot modify or activate Constitution, identity, or intervention-policy versions.

### Evaluation and measurement

- Base / Base+Memory / Base+Adapter / Base+Memory+Adapter factorial comparison;
- behavioral, safety, general-capability, over-agreement, latency/VRAM, and load/switch measurements;
- multiple seeds when feasible or an explicit compute limitation;
- limited/shadow validation before promotion.

### Exit evidence

An adapter is deployed only if it contributes measured value beyond memory/context and passes regression gates. A failed adapter is rejected without affecting persistent identity/history.

### Implementation checkpoint

The initial candidate was rejected because evaluation holdout entered the
training snapshot and rendered artifact. The first correction physically
separated training-v2 and holdout-v2 but was rejected because its database guard
allowed one legal rendered member to be repeated while other members were
omitted. The additive second correction recomputes the durable member manifest,
requires unique rendered IDs, and proves an exact bidirectional one-to-one
membership relation. Correction evidence is recorded in
[`STAGE9_CHECKPOINT.md`](STAGE9_CHECKPOINT.md). Those foundation corrections
were later accepted and are preserved as historical Stage 9 evidence.

The Product Owner subsequently accepted the corrected bounded foundation and
authorized Stage 9A real transformer work under synthetic-only, local-only,
candidate-only limits. Historical Dataset v1 evidence remains immutable but
was superseded after boundary, overlap, and resource-evidence defects were
found. Dataset v2 and v3 were rejected without training.

### Dataset v4 Product Owner freeze gate

The Product Owner rejected Dataset v2 and v3 for training and supplied an
externally authored immutable v4 candidate. Its repo-native train/validation/
sealed-holdout artifacts contain 300/60/120 synthetic/public-safe examples and
reproduce exact bundle hash
`sha256:13fa5a62ec6edc571c51468a8a07c2c362744236de0b418a0d9c543de0b586c4`.
The renderer contract preserves multi-turn context, masks historical assistant
turns, supervises only the final HAVRE target, selectively injects only supplied
synthetic memory, and limits proactive examples to wording after governed Core
authorization. Behavioral properties and Product Owner review remain primary;
multilingual reference similarity is diagnostic only.

The separately supplied 70-case Owner Alignment Set is PRIVATE, local-only, and
permanently excluded from SFT, validation-for-training, hyperparameter tuning,
prompt/template tuning, and synthetic-data generation inputs. It was opened
only after the formal seed plan closed and is retained as historical evaluation
and regression evidence; its results cannot feed training or OA70 optimization.

### Final Stage 9A closure

Dataset v4 was exact-hash frozen and formally executed. Corrected Gates A-D,
QLoRA Seeds 9201/9202, exact reloads, two 120-case four-arm sealed evaluations,
the final PRIVATE Owner Alignment 70 examination, compatibility checks,
variance evidence, and fail-closed resource evidence are complete. Seed 9203
did not run under the predeclared material-variance rule. The exact evidence and
limitations are recorded in [`STAGE9_CHECKPOINT.md`](STAGE9_CHECKPOINT.md).

On 2026-08-21 the Product Owner accepted Stage 9A technical evidence and closed
Stage 9 at that boundary. Both adapters remain behavioral candidates only;
neither is promoted, deployed, or accepted as the final HAVRE brain. The owner
currently leans toward 9201 but explicitly retains fabricated-memory,
warm/firm-judgment, Talk/Guide-switching, and identity-continuity concerns.
Dataset v5, new training, a 9201 continuation experiment, and Stage 9B are
deferred. Stage 10 is authorized; blocker-free Stage 10 exit evidence
pre-authorizes Stage 11. Stage 12 remains unauthorized.

### Later Stage 9A behavioral revision evidence

On 2026-08-25 the Product Owner rejected the style-first v6 candidate while
retaining it as immutable evidence, then authorized one fresh-base,
capability-preserving revision. Generic v7 excluded Owner anchors, OA70,
private daily chat, and feedback. Its balanced PUBLIC synthetic dataset,
one-epoch seed 9701 run, independent reload, and post-plan 80-case unseen
evaluation completed. v7 recovered confidentiality, exact output, medical
uncertainty, and privacy/tool boundaries relative to v6, but semantic review
found absolute fabricated-memory and urgent-safety blockers and did not find a
clear naturalness improvement over 9201. It is rejected, unregistered, and not
available in daily use. The predeclared tradeoff stop rule prevented another
automatic candidate. Evidence and exact hashes are in
[STAGE9A_V7_CAPABILITY_PRESERVING_CHECKPOINT.md](STAGE9A_V7_CAPABILITY_PRESERVING_CHECKPOINT.md).

The Product Owner then kept v7 rejected and authorized a model-vs-Core
responsibility audit, not another candidate. A versioned, hash-bound response
decision is implemented before owner-visible delivery. On 2026-08-25 the
Product Owner accepted ADR-0022 at that verified responsibility and architecture
boundary. The exact frozen v7
80-case/five-arm generations were replayed with raw and pipeline results
separated. No model inference, prompt change, training, registry/UI mutation,
promotion, or Stage 9B work occurred. Evidence and residual model-owned limits
are in
[STAGE9A_MODEL_VS_CORE_RESPONSIBILITY_CHECKPOINT.md](STAGE9A_MODEL_VS_CORE_RESPONSIBILITY_CHECKPOINT.md).
The acceptance does not authorize v8, private training data, candidate status,
registry/serving/daily-use changes, deployment, or broader context activation.

On 2026-08-26 the Product Owner separately authorized one focused relevant-Memory-
use milestone. The permanent system correction introduced Context Builder v9 and a
versioned provider-facing Memory presentation, then replayed frozen 9201/9202/v7.
A small PUBLIC synthetic continuation from immutable rejected v7 produced
unregistered seed 9801. Post-plan unseen semantic review found a narrow 25/32 focused
result versus v7 24/32, but the representative AI/self-learning callback still
distorted the evidence into an accusation. The system correction is retained; 9801
is not behaviorally accepted or available for daily use, all prior lifecycle states
and the 9201 binding remain unchanged, and no further training is authorized. See
[RELEVANT_MEMORY_USE_MILESTONE_CHECKPOINT.md](RELEVANT_MEMORY_USE_MILESTONE_CHECKPOINT.md).

The Product Owner then authorized one Strong Cloud Brain ceiling experiment,
not a candidate or deployment change. A default-disabled `deepseek-v4-pro`
adapter ran only PUBLIC synthetic fixtures behind the unchanged ModelProvider,
Context, and Core boundaries. Independent 32-case same-prompt review scored
thinking/high 28/32 versus the best local 22/32, showing a material
model/inference-compute ceiling; it still fabricated familiarity once and was
weaker than 9201 on casual chat. The conditional 80-case run remains an absolute
regression because its local frozen system prompts are not exact. No training,
status, registry, binding, routing, serving, promotion, deployment, or Stage 9B
change occurred. See
[STRONG_CLOUD_BRAIN_CEILING_CHECKPOINT.md](STRONG_CLOUD_BRAIN_CEILING_CHECKPOINT.md).

### Permanent daily-use and personalization feedback loop

On 2026-08-22 the Product Owner authorized the provider-neutral daily computer
chat and governed long-term feedback loop in ADR-0021. This extends, rather than
replaces, the accepted Stage 2/4/7 Memory lifecycle and Stage 9 governance:

1. every completed user/assistant turn is an immutable Event and ordinary
   conversation history;
2. a complete Web session closes as an episode with exact ordered Event
   membership and a conservative source-linked summary;
3. derived episodic suggestions are reviewed in a
   concentrated Memory surface, not after every message;
4. ratings, reasons, and owner rewrites remain append-only feedback evidence
   attached to exact response/model/context lineage;
5. runtime defects are classified and fixed at runtime where appropriate;
6. the current runtime keeps every revision ineligible; a future separately
   authorized Stage 9B may add a durable owner-approval path for one exact
   feedback revision;
7. a later, separately authorized Stage 9B may freeze an immutable reviewed
   snapshot, train periodic candidates, compare them with the current brain,
   and request explicit promotion.

No saved rating, edit, episode summary, Memory suggestion, or runtime preference
automatically becomes training data. No online weight update is permitted.
Seed 9201 may be used only as the current local development candidate/integration
fixture; this does not change its lifecycle status.

On 2026-09-02 ADR-0026 superseded the preceding default-use clause. Seed 9201 is
retained only as immutable historical candidate evidence and is no longer the
owner-local daily binding. The exact unadapted Qwen3-8B Stage 3 candidate began
as the temporary no-adapter diagnostic baseline, not an accepted replacement.
ADR-0030 now separately authorizes that exact artifact as the owner-local route
for non-GPT-eligible and stricter daily ContextPacks without promoting it.
Bounded Response Plan, relevance-gated Memory Broker, Replyer/Core separation, offline
proposal review, and same-prompt local candidate comparison are authorized.
Hash-pinned official candidate downloads into the ignored owner-local runtime are
also authorized. Raw private-chat cloud review, driver changes, training, Stage 9B,
other automatic routing, promotion, and deployment remain separately gated.

The first same-prompt comparison completed against the exact official Qwen3-14B
Q4_K_M candidate. It loaded at the fixed 8,192-token context and completed all 39
PUBLIC synthetic requests without truncation. It materially improved conditional
uncertainty and relevant-Memory use over the 8B baseline, but is not promoted:
explicit decision-making and evidence-backed local-model hardware guidance remain
release blockers. The next bounded step is one targeted orchestration correction
and a full ContextPack/Core A/B before any owner promotion decision.

The local daily Web checkpoint uses the existing Core/API/Event Store and
provides durability-gated streamed rendering, conversation history, per-response
feedback and edits, a feedback pool, an explicit response-length preference,
accepted Memory inspection, episode summaries, and concentrated suggestion
review. The v1 episode summary is extractive and makes no semantic-quality
claim. Semantic, preference, and pattern suggestion extraction, automatic
high-quality semantic/pattern extraction, dataset building,
training, candidate comparison, promotion, and deployment remain future gates.

## 12. Stage 10 — User-Controlled Deployment + Reliability

Status: **Complete at source `22700334eb375e1ee21283ca9d40efe5650cd8ec`; final independent review P1=0/P2=0. An owner-local infrastructure-only release is deployed, behavioral routes remain unavailable, and no adapter was promoted or deployed. Exact evidence is in [`STAGE10_CHECKPOINT.md`](STAGE10_CHECKPOINT.md).**

### Build

- HTTPS, secrets, health/version endpoints, backups, restore, restart policy, and deployment manifests;
- monitoring for request/job health and resource limits;
- explicit promotion and rollback workflow;
- owner export/erasure and restored-backup deletion replay drills;
- controlled load and failure testing.

### Exit evidence

The system deployed and rolled back distinct immutable releases, restored
verified data, replayed erasures, and reported health without Kubernetes on the
owner-controlled Docker host. HTTPS/secrets, restart, controlled load/failure,
owner export/erasure, restored actual-login boundaries, and exact source/image
binding passed. Final independent review reported P1=0/P2=0; the exit criterion
is satisfied.

## 13. Stage 11 — Native iPhone + Voice

Current status (2026-08-22): source
`4b2d3096c1b303bab8ffba58cb1e370ee4e67e92` implements the bounded native
client foundation and passed independent code review with P1=0/P2=0. The
portable Core and PostgreSQL evidence do not satisfy the native exit evidence.
macOS/Xcode plus simulator/physical-device validation is still required. Native
push and lock-screen delivery are also inactive pending a Product Owner decision
on Apple/APNs processing, eligible privacy classes, minimized payload routing,
preview behavior, and credential custody. Current simulation-only Core rows
schedule zero OS notifications. See [`STAGE11_CHECKPOINT.md`](STAGE11_CHECKPOINT.md).

### Build

- SwiftUI client over the existing Companion API;
- text, voice, scene controls, notifications, playback, and protected local cache;
- native push/lock-screen delivery adapter behind the Stage 6 provider-neutral port;
- low-bandwidth reply/actions linked to the original proposal/delivery;
- notification preview controls for full, generic private, none, or owner-configured content;
- consent and OS-permission UX;
- offline queue/reconciliation for events.

### Evaluation and measurement

- interaction and accessibility tests;
- scene signal latency and failure behavior;
- offline ordering/idempotency;
- local-data protection and deletion;
- push idempotency/reconciliation, preview privacy, dismissal/snooze/stop propagation, and response linkage;
- voice transcription/synthesis quality and privacy by approved provider/device path.
- per-capability source health, freshness, consent expiry/revocation, background availability, battery/network cost, and minimum-signal privacy tests for any approved iPhone context capability.

### Exit evidence

iPhone is a new entrance to the same identity, event store, memory, scene, Proactive Core, context-source, and delivery contracts—not a second Companion implementation, a second notification policy, or an always-running background Core. Voice is user-initiated by default; no unrelated-app inspection or ambient microphone is implied.

## 14. Stage 12 — Ambient Life Context + Edge Brain + Hybrid Context

### Build

- on-device eligible task profile and Edge Brain adapter;
- offline/private routing with explicit capability boundaries;
- provider-neutral source registration, capability, ConsentScope, SamplingPolicy, RetentionPolicy, LifeContextObservation, source-health, freshness, and coverage contracts;
- Stage 12A: Windows coarse-context agent and Calendar adapter, one capability at a time with local minimization and scoped consent;
- Stage 12B: Location, mobility, wearable, richer sensor, or Edge context one capability at a time after separate review;
- Core-owned trigger evaluation over context Events; adapters can create observations but never interpretations, permission, notifications, or direct delivery;
- synchronization/conflict rules and protected on-device state.

### Evaluation and measurement

- edge/cloud quality, latency, energy, privacy, and availability trade-offs;
- wrong-route severity and offline degradation;
- sensor usefulness versus intrusion;
- consent, revocation, deletion, and stale-context tests.
- adapter conformance, offline replay, clock/coverage, source health, freshness, retention expiry, erasure closure, and provider replacement;
- trigger accuracy, source reliability, minimum-sufficient-signal comparisons, and no-contact behavior after permission revocation;
- explicit tests that missing Windows/Calendar/iPhone/location/wearable data cannot become negative user evidence.

### Exit evidence

The first Windows/Calendar capability and any later hybrid routing provide measured benefit and never let convenience silently broaden private context access. No higher-precision source is adopted unless it outperforms the minimum-sufficient baseline on an approved usefulness/privacy trade-off.

## 15. Stage 13 — Conversation Intelligence + Local Replyer Selection

Status: **Authorized and in progress under ADR-0027. Stage 13A-C are reversible,
local, candidate-only work. Stage 13D requires an explicit Product Owner decision.**

Stage 13 is independent of deferred Stage 11 native evidence and Stage 12 sensing.
It improves the already-active reactive conversation path and does not activate a
new context source, channel, or training path.

The acceptance standard is the owner-visible
[`STAGE13_PRACTICAL_UTILITY_GATE.md`](STAGE13_PRACTICAL_UTILITY_GATE.md):
HAVRE must reduce the owner's effort and produce a result the owner would actually
use. Passing tests, model size, benchmark averages, and natural prose cannot
substitute for that outcome.

### Stage 13A — Turn Contract and evidence path

- Build the deterministic, hash-bound Turn Contract before durable Memory
  retrieval.
- Preserve every distinct current-turn obligation and distinguish “define
  criteria” from “recommend one now.”
- Persist an explicit empty retrieval result when the Memory Gate is `none`; permit
  actual retrieval only for `possible|required`.
- Keep historical contract versions replayable and bind plan/gate versions into
  inference evidence.
- Preserve input, retrieval/gate, ContextPack, provider messages, raw completion,
  Core decision, delivered response, and review provenance as separate evidence.

Exit evidence: focused contract and application-boundary tests, generated schema
equality, complete PostgreSQL-backed regression with zero database skips,
provenance audit, and no unresolved P1/P2 contract or privacy defect.

### Stage 13B — Memory Broker and Context Compiler

The 2026-09-04 owner-authorized Memory repair adds the pinned local semantic
encoder, source-gated hybrid admission, recorded conversation times, and bounded
explicit past-conversation recall. See ADR-0037 and
[`REALTIME_MEMORY_EXPERIENCE_CHECKPOINT.md`](REALTIME_MEMORY_EXPERIENCE_CHECKPOINT.md).
This does not activate model training or Stage 13D promotion.

- Keep working dialogue, reviewed Episodes, confirmed communication preferences,
  and long-term Memory as separate evidence classes.
- Query long-term Memory only through the Turn Contract gate; record exclusions and
  never convert retrieval into a forced callback.
- Make the provider-facing Context the smallest complete form that preserves fixed
  Identity, current-turn precedence, source truth, and required obligations.
- Measure each presentation or budget change as one causal variable against the
  frozen suite.
- Treat the active session as working dialogue; use bounded raw cross-session
  fallback only for an explicit prior-conversation reference. Use reviewed
  Episodes and long-term Memory for ordinary cross-session continuity.
- ADR-0031 adds an owner-authorized, source-bound behavior-example class separate
  from Memory. ADR-0035's explicit owner-local implementation authorization
  extends eligibility to the exact OA70 cases 1-70, with deterministic relevance
  selection and a maximum of three examples per turn. All 70 are calibration,
  not independent holdout evidence.

Exit evidence: identical-turn relevant/irrelevant/absent/stale/partial
counterfactuals, final-request inspection, budget accounting, current-precedence
and fabricated-familiarity hard gates, plus long-context continuity.

### Stage 13C — Replyer comparison and full-stack A/B

- Keep the exact Qwen3-8B base as a diagnostic comparison control. ADR-0030 also
  permits this same unadapted artifact as a narrow owner-local privacy Replyer;
  that operational use does not promote it or establish candidate quality.
- Retain Qwen3-14B Q4_K_M as a rejected comparison control; do not spend a
  full-stack integration arm on it while raw hard failures remain.
- Evaluate the exact pinned Qwen3.6-35B-A3B Q4_K_M artifact first through the
  existing isolated llama.cpp boundary. Add FreeToken only as a separate
  speed/runtime arm if raw 35B quality passes and measured speed is the remaining
  bottleneck.
- Record exact artifact/runtime and measured RAM/VRAM/latency evidence;
  advertised parameter counts or throughput are insufficient.
- Score repeated raw Replyer output separately from full ContextPack/Core delivered
  output. Preserve regressions rather than selecting one favorable generation.
- Use the Codex development agent as an external engineering loop over
  authorized evidence, never as promotion authority. ADR-0029 separately uses
  an isolated no-tools GPT-5.6-sol process as the daily Replyer; it is not the
  development workspace session and cannot approve its own output.
- The active GPT arm uses explicit medium reasoning effort and authoritative
  owner-local message time. Measure latency and owner utility before increasing
  effort; model size or effort is not a utility proxy.

Exit evidence: repeated frozen PUBLIC arms, full ContextPack/Core A/B, hard-gate
results under the Practical Utility Gate, latency/resource evidence, calibrated
semantic review, and one concrete recommendation to the owner. Stage 13C may
reject all candidates.

### Stage 13D — Owner acceptance and promotion gate

- Run a blinded owner comparison on representative conversations.
- Review remaining quality, latency, privacy, and operational tradeoffs.
- Stop for explicit owner selection before any local-model lifecycle promotion,
  broader default binding, deployment, routing-policy expansion, or personalized
  release. ADR-0029 and ADR-0030 are narrow owner-local operational bindings,
  not Stage 13D promotion decisions.

Training is not a Stage 13 shortcut. A later Stage 9B may be proposed only if
Stage 13 evidence isolates a narrow trainable residual and the owner separately
authorizes data, training, evaluation, and promotion gates.

## 16. Stage 14 — ChatGPT-hosted Companion Surface

Status: **Stage 14A is implemented under ADR-0028. ADR-0029/0030's Stage 14B
DataPolicy-driven dual route is technically verified and active owner-locally:
cloud-eligible PUBLIC/NORMAL uses GPT-5.6-sol and non-GPT-eligible or stricter
ContextPacks use the exact unadapted Qwen3-8B. Its Practical Utility Gate remains
open. Private-data cloud admission remains a separate gate. ADR-0035 separately
activates only source-guarded relationship follow-ups under the existing Core;
broader model-selected proactive contact remains gated.**

This stage tests the shortest practical path to a companion the owner will
actually use: ChatGPT desktop supplies a strong host model while HAVRE supplies
its persistent approved Identity and deterministic Turn Contract. Stage 14A
tests that combination outside HAVRE through MCP. Stage 14B uses a separately
bounded Codex CLI `ModelProvider` so the final response returns through Core and
the Event Store.

### Stage 14A — PUBLIC identity and current-turn pilot

- Run a local official-SDK STDIO MCP server registered on the owner-controlled
  ChatGPT desktop/Codex host.
- Expose only approved PUBLIC Identity and planning over the current message
  already visible to ChatGPT.
- Mark every tool read-only, idempotent, non-destructive, and closed-world.
- Include explicit structured proof that no HAVRE private history, durable
  write, or OA70 material is involved.
- Evaluate real owner-visible usefulness: retained use, correction/restatement
  burden, complete understanding, fabricated familiarity, and comparison with
  ordinary ChatGPT.

Exit evidence: protocol tests including real STDIO subprocess transport, exact
dependency/config evidence, complete repository regression, and an owner
decision based on representative conversations. Passing transport tests closes
implementation but not the usefulness gate.

### Stage 14B — Governed continuity bridge

ADR-0029 authorizes one automatic GPT-5.6-sol call for each ordinary eligible
owner-local chat message. The provider receives the canonical ContextPack through
stdin in an isolated ephemeral no-tools Codex run, returns only the final agent
message, and remains behind the existing request binding, Core response policy,
and durable Event path. The daily UI has one routing policy rather than a separate
Strong Brain action.

ADR-0030 extends only the owner-local execution route:

- cloud-eligible PUBLIC/NORMAL selects GPT-5.6-sol;
- cloud-ineligible PUBLIC/NORMAL selects the exact local Qwen3-8B;
- PRIVATE/HIGHLY_PRIVATE/LOCAL_ONLY selects the same local Qwen3-8B with no
  HAVRE adapter.

The route consumes the effective ContextPack policy and cannot drop required
stricter evidence, reinterpret privacy, or use cloud after a local failure. The
first version performs no silent cross-provider failure retry. LOCAL_ONLY remains
cloud-ineligible, and the automatic route remains local for PRIVATE and
HIGHLY_PRIVATE even when a separate policy could permit a separately governed
cloud use.

The prior ADR-0029 exit evidence covered only its GPT branch. ADR-0030's current
technical implementation now has a versioned multi-provider RouteDecision,
provider-specific binding, the full privacy/cloud truth table, exact no-adapter
local attestation, an evidenced budget and boundary failure against the configured
8,192-token llama.cpp runtime profile, Core/Event integration for both branches,
negative no-cloud call proof, Web route/control evidence, and real synthetic GPT
and local probes. Verification passed 633/633 primary plus 62/62 pinned Torch
tests (695/695 combined), all with zero skips, and a disposable-database
provenance audit returned `[]`. The owner-local runtime is active at migration
`0053`. This closes the technical activation evidence; repeated owner use remains
the separate Practical Utility Gate and has not been manufactured from tests. The
current evidence checklist is
[`STAGE14B_DUAL_PROVIDER_ROUTING_CHECKPOINT.md`](STAGE14B_DUAL_PROVIDER_ROUTING_CHECKPOINT.md).
OA70, training, tools, automatic classification, and automatic Memory writes
remain outside this authorization.

### Stage 14C — Proactive language realization

The governing design is `deterministic trigger and interruption authority -> GPT
draft -> Core acceptance/rejection -> durable send`. GPT may make an already
authorized reminder sound natural, but it may not decide that silence, Memory,
emotion, or inferred need grants permission to contact the owner. A second model
may produce offline critique/proposals; it cannot be the sole send authority or
silently edit Identity, policy, or Memory. Activation requires its own failure,
latency, privacy, idempotency, fallback, and owner-burden evidence. ADR-0035's
owner-local implementation activates one narrow `relationship_follow_up`
category from exact eligible conversation/Memory evidence. It remains bounded by
the current preference revision, one-per-24-hour category budget, quiet hours,
stop subjects, expiry, deduplication, and Core delivery; it does not activate
general model-owned contact authority.

## 17. Stage 15 — Owner Commitments + Practical Reach Out

Status: **Stage 15A, the bounded Stage 15B commitment loop, and ADR-0035's
experience-first extension are implemented and owner-locally active by explicit
owner task direction. ADR-0036's bounded relational initiative is technically
verified and owner-locally active behind the global and friendly-check-in
controls; formal ADR-0032/0035/0036 acceptance remains pending. The current
projection is 48 active plus two abandoned LOCAL_ONLY Goals, 50 exact five-field
commitment projections, and 127 v2 pending reminders. Four historical legacy
items succeeded and all 130 remaining legacy items are durably cancelled. An
exact rerun creates no Goal, source interaction, reminder, or cancellation.
Migration 0059 adds fixed 05:00 daily review, explicit chat Goal receipts, and
source-guarded relationship follow-ups. Migration 0060 adds exact-turn local
continuation receipts; migrations 0061-0062 add the owner-authorized one-minute,
then delivery-relative 30-minute two-beat cadence. Repeated owner use remains the subjective
quality gate. This does not activate a general Calendar trigger or ungoverned
model-owned outreach.**

### Stage 15A — Manual owner schedule import

- verify one exact owner-selected source document and a separately reviewed,
  gitignored schedule plan;
- represent each confirmed, tentative, conditional, or TBA commitment as a
  durable source-bound reality Goal rather than an unstructured prompt;
- schedule multiple owner-selected contacts against the exact current Goal;
- use three sparse policies: ordinary work at 3/1 days, large work at 7/3/1
  days, and exams at 7/3/1 days with supportive day-before wording;
- keep tentative status visible and keep TBA/conditional items reminder-free;
- cancel older queued contacts automatically when the Goal is no longer the
  current active projection;
- retain Core permission, budget, stop, snooze, duplicate, expiry, privacy, and
  delivery checks on every contact.

Technical evidence: exact source hash; initial 50/134 apply and corrected
50/131 dry-run counts;
source-only local Qwen routing; focused and full zero-skip PostgreSQL regression;
provenance audit; owner-database readback of source Events, Goals, queued work
and policy; four due-now local inbox items plus one correction; and exact rerun
idempotency. Repeated owner observation and formal ADR-0032 review remain open.
Exact evidence is in
[`STAGE15_OWNER_COURSE_SCHEDULE_CHECKPOINT.md`](STAGE15_OWNER_COURSE_SCHEDULE_CHECKPOINT.md).

### Stage 15B — Bounded update, completion, fusion, and erasure closure

- expose only course name, task name, deadline, completion state, and reminder
  history to ordinary cloud-eligible conversation under the exact owner
  authorization; keep the `LOCAL_ONLY` source and private Goal fields out;
- resolve only a unique explicit owner completion report, preserve exact Event
  and Goal-transition evidence, cancel stale reminders, and ask one
  clarification when resolution is ambiguous;
- fuse a due reminder into a suitable active conversation only when Core can
  prove actual inclusion, otherwise preserve the governed Web-inbox path;
- insert a reviewed replacement queue generation before cancelling the exact
  source snapshot's legacy pending/retryable generation; never rewrite sent
  history and fail if a legacy item is leased;
- extend future privileged source erasure so an explicitly selected source
  Event closes its derived Goals, projections, transition evidence, reminder
  deliveries, fusion claims, and proactive queue artifacts. No real source was
  selected or erased during activation, and raw Event deletion remains a
  separate privileged phase.

Later course-source revisions may still add a review UI for changed/TBA dates
or source replacement. Scraping Canvas, Campuswire, email, or course sites is
not authorized.

### Stage 15C — Experience-first daily review and relational continuity

- run the owner-local Diary review once after 05:00 for the interval from the
  previous local 05:00 to this local 05:00, never from a GET request;
- generate eligible GPT-chat Memory/User Model updates after completed turns in
  an independent GPT-high background queue; private/local candidates still need
  owner review, and routine chat need not create a durable record;
- admit only GPT-routed PUBLIC/NORMAL current-day Events, bounded eligible prior
  context, and bounded current eligible Memory to the high-effort review;
- ignore greetings, acknowledgements, governance/status mechanics, and other
  transactional流水 rather than turning them into a Diary;
- write only evidence-ID-bound improvement suggestions under the owner review
  root; never let the review edit code, Identity, values, or policy;
- create Goals/reminders only after explicit owner language and a durable action
  receipt; ordinary relationship conversation is not a task extractor;
- allow conversation/Memory to support a `relationship_follow_up` proposal while
  keeping current preference, stop, quiet-hour, budget, deduplication, expiry,
  and delivery authority in Core;
- present technical records as friendly Memory, User Model, hierarchical Goal,
  and first-person Diary views; keep private/local transcript content in the
  local collapsed detail only;
- extend exact-source erasure through the daily review, generated file, explicit
  Goal/reminder, and proactive derivatives without selecting a source itself.

Technical evidence is recorded in
[`EXPERIENCE_FIRST_DAILY_REVIEW_CHECKPOINT.md`](EXPERIENCE_FIRST_DAILY_REVIEW_CHECKPOINT.md).
The first real 05:00 run completed after correcting provider enum drift and adding
persisted retry backoff. Physical-iPhone presentation, repeated usefulness, and
formal ADR-0035 acceptance remain open.

### Stage 15D — Bounded relational initiative

- permit a first delayed continuation exactly one minute after an exact eligible
  GPT-routed PUBLIC/NORMAL talk turn, cancel it on any newer owner message, expire
  it 15 minutes later, and plan new receipts with isolated GPT-5.6-sol at fixed
  high effort under the separate owner authorization; existing local receipts
  keep their original Qwen route;
- only after the first delayed line was actually visible, permit one final second
  beat exactly 30 minutes later; cancel on a newer owner message and never create
  a third beat for that source turn;
- allow the first reply itself to contain a question, while requiring the delayed
  line to be distinct; downgrade generic confirmation, unsupported mind-reading,
  default recovery coaching, fabricated personal history, guessed concrete facts,
  or pure restatement to no-action even when the planner proposes a send;
- send at most one or two short sentences, allow no-action, and forbid default
  analysis, tasks, urgency, non-response language, dependency cues, or invented
  shared history;
- give in-conversation continuation its own two-per-24-hour category budget;
  separately count only delivered cold relationship touches since the latest ordinary owner
  message, wait at least 24 hours before the second and 72 hours before the third,
  then pause after three until a new ordinary owner message;
- keep Goal reminders independent, fill only otherwise-empty authorized Goal days
  with at most one stable hash-derived daytime slot across all eligible Goals,
  prefer the nearest deadline, and defer all standalone delivery while a
  conversation is active;
- expose separate nontechnical owner controls for important reminders and friendly
  check-ins instead of one combined switch;
- preserve exact turn/provider/proactive provenance and extend explicit-source
  erasure through the new receipt and queue item.

Technical evidence is recorded in
[`BOUNDED_RELATIONAL_INITIATIVE_CHECKPOINT.md`](BOUNDED_RELATIONAL_INITIATIVE_CHECKPOINT.md).
Fresh and in-place migration through 0063, direct SQL attacks, timing/cadence,
reply races, active-chat deferral, two-beat erasure, daily Goal stability, complete
split-environment regression, exact GPT-high/local-legacy provider receipts, and
provenance checks pass. Production is ready at 0063 with live API/worker, no
backfilled GPT receipt, and PWA v11 idle-chat refresh. Repeated owner experience
and formal ADR-0036 acceptance remain open.

## 18. Recommended clarifications to the Master Plan

These are proposed interpretations, not unilateral edits to product authority:

1. **Rename the source file to `MASTER_PLAN.md`.** Done in Stage 0 because sections 30 and 33 explicitly require that path.
2. **Clarify “permanent” versus deletion.** Raw experience is durable until owner-requested erasure; ordinary operations are append-oriented, but privacy deletion must remove source and derived closure.
3. **Move evaluation/tracing foundations earlier in wording.** Stage 1 must trace and smoke-test, Stage 2 evaluates retrieval, and Stage 3 benchmarks inference. Stage 8 should be described as unification/operations.
4. **Add privacy/safety gates to Stage 1.** Before highly private data reaches a cloud model or durable store, approve provider eligibility, identity boundaries, crisis behavior, export, erasure, and backups.
5. **Separate evaluation holdouts from training explicitly.** The canonical dataset plan should forbid holdout membership and record leakage/revocation.
6. **Clarify event semantics.** `MEMORY_CREATED`, `MODEL_CHANGED`, and similar records are lifecycle/audit events in the ledger; memories/models themselves remain versioned derived tables/artifacts.
7. **Do not mandate model-size experiments without hardware need.** 8B/14B/27B-class is a useful candidate matrix, but real available hardware and the decision question should determine which runs are justified.
8. **Make user-data export/erasure and backup restore tests stage deliverables.** These cannot safely wait until late cloud deployment even if reliability automation matures in Stage 10.
9. **Add explicit human approval for identity/policy/personalized-adapter promotion.** Automated gates provide evidence but do not own HAVRE's values.
10. **Add Reach Out without renumbering the Roadmap.** Stage 6 activates Proactive Core after Goals/User Model/Scene prerequisites; Stage 7 adds Reflection proposals, Stage 11 native delivery, and Stage 12 external context triggers.
11. **Add Ambient Life Context without moving sensors earlier.** Contracts are reviewed now; Stage 6 uses only synthetic/manual observations, Stage 11 may add individually approved iPhone/voice capabilities, and Stage 12 activates Windows/Calendar before considering richer location/wearable context.
12. **Make Experience distinct from Memory.** Events remain append-preserved source history under retention/erasure; Memory requires versioned promotion and supports temporal validity, contradiction, archival, reconsolidation, regeneration, and deletion propagation.

## 19. Current stop condition

Stage 6 remains simulation-only and Stage 7 remains proposal-only. Stage 8
technical acceptance is complete without promotion. On 2026-08-21 the Product
Owner accepted the Stage 9A technical evidence and closed Stage 9 at the
candidate-only boundary. Stage 10 implementation and native exit evidence are
complete at source `22700334eb375e1ee21283ca9d40efe5650cd8ec`; neither candidate
was promoted or deployed. Final independent review reported P1=0/P2=0, so
Stage 10 is complete. Stage 11 has reached a reviewed implementation checkpoint
but has not satisfied its native-device and APNs/privacy exit gates. Voice
remains user-initiated and ambient microphone use is not authorized.
The Product Owner deferred Stage 11 native evidence without a waiver and
explicitly authorized Stage 12A on 2026-08-22. Stage 12A currently remains at a
disabled implementation checkpoint: Windows lacks real owner evidence and the
Calendar path is now owner-initiated local ICS import, with no Graph or polling.
The Product Owner requested iPhone Screen Time as the next separately gated
capability after Calendar. Its minimum-sufficient proposed value is an
owner-initiated iPhone daily total only; app/site identities and detailed
timelines remain outside scope. It is not implemented or activated because the
ordinary Apple report-extension boundary cannot export report data to Core,
direct export is currently region/entitlement gated, and native evidence is
deferred without a Mac. **Stop
before general Stage 12B, location/wearables/other richer sensing, Stage 9B, adapter
promotion/deployment, user-derived training, automatic Memory mutation,
governance changes, or any personalized production release.**

Stage 13A-C may continue within ADR-0027 using reversible local code, PUBLIC
synthetic evidence, and candidate-only model runs. ADR-0029 and ADR-0030
separately authorize the owner-local daily dual Replyer; the 8B privacy route is
not a local-candidate promotion. **Stop at Stage 13D before promoting a local
model or changing model lifecycle state, and also stop before private external
disclosure, broader routing-policy expansion, driver/system changes, training,
deployment, or any Identity/privacy/governance change.**

Stage 14A remains the PUBLIC read-only MCP control. Stage 14B is active only as
ADR-0029/0030's owner-local policy route with no GPT tools and with Core/Event
capture. ADR-0035 additionally authorizes the exact owner-only OA70 cases 1-70
runtime bank and one Core-governed source-guarded relationship category. **Stop
before automatic PRIVATE/HIGHLY_PRIVATE/LOCAL_ONLY cloud admission, automatic
classification, silent cross-provider failure fallback, OA70 training/tuning or
public release, proactive delivery outside the exact governed categories,
automatic Memory mutation outside the authorized GPT-source delegation, or
provider-controlled Identity/policy changes.**

The owner's explicit Stage 15 task directions authorize the exact selected Fall
2026 schedule snapshot, its five-field projection, deterministic Goal-bound
reminder generation, bounded completion/fusion behavior, ADR-0035's
experience-first daily review and relationship paths, and a future source-erasure
closure only when the owner explicitly names the source Event. Formal
ADR-0032/0035/0036 acceptance remains pending. **Stop
before general Calendar-to-outreach activation, course-site scraping,
relational expansion beyond ADR-0036's exact reviewed cadence/categories,
ungoverned GPT-selected cadence or contact, non-explicit completion inference, any actual
source erasure without a newly specified source Event, or any unreviewed
schedule-source replacement.**

ADR-0033's practical companion correction is implemented by explicit task
direction on the owner-local runtime. ADR-0034 additionally implements the exact
new owner authorization for high-effort GPT Diary synthesis, source-quoted automatic
Memory/User Model updates from eligible GPT-routed chats, and the enumerated paired
device review writes. ADR-0035 fixes Diary review at 05:00, adds bounded prior
context and manual improvement files, explicit chat Goal planning, friendly
Memory/Goal presentation, the all-70 owner-only runtime bank, and source-guarded
relationship follow-ups. Private/local chat remains excluded from GPT synthesis
and automatic understanding. The first real 05:00 run completed after a bounded
provider-enum/retry correction. Formal ADR acceptance, repeated owner-use quality
evidence, and physical iPhone validation remain open.
**Stop before any broader automatic Memory/User Model mutation, private cloud
disclosure, paired-device administration or erasure authority, automatic
code/Identity/policy changes, or treating a browser-width contract as
physical-iPhone acceptance.**
### September 6 audit-driven quality follow-through

The owner accepted the September 5 real-runtime audit and explicitly authorized
continuous implementation, validation, local commits and UX work without a gate
after each Priority. ADR-0038 scopes the correctness/continuity slice; it does not
activate another Stage, weaken private-data policy or authorize model promotion.
See DAILY_COMPANION_QUALITY_CHECKPOINT_2026-09-06.md for actual evidence and limits.
