# HAVRE Roadmap

Status: **Stage 6/7 accepted; Stage 8 technically accepted without promotion; Stage 9 closed at the candidate-only boundary; Stage 10 complete; Stage 11 at an implementation checkpoint but not exited; Stage 12A at a disabled implementation checkpoint; the owner-authorized daily Web chat/episode/feedback foundation is active for local use; Stage 9B and Stage 12B remain unauthorized**

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

The initial candidate and first correction candidate were rejected after acceptance review reproduced concurrency bypass, missing required paths, and stale preference execution. Additive `0021` supplies the required controls/workers; additive `0022` supplies an authoritative preference head and resolves it under the same owner lock as preference saving before every new execution. External delivery remains structurally false. Current evidence is in [`STAGE67_SECOND_ACCEPTANCE_CORRECTION_CHECKPOINT.md`](STAGE67_SECOND_ACCEPTANCE_CORRECTION_CHECKPOINT.md).

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

## 15. Recommended clarifications to the Master Plan

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

## 16. Current stop condition

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
