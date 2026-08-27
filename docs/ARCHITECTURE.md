# HAVRE Architecture

Status: **Stage 6/7 second acceptance corrections technically verified at execution-source snapshot `sha256:8ba8b94632ae181c2966acc3d6c498d8f7a63337d2e8558629b47dd440386f9c`; pending Product Owner reacceptance; ADR-0019/0020 accepted**

Authority: [`MASTER_PLAN.md`](../MASTER_PLAN.md) remains the product source of truth. If this document conflicts with it, the conflict must be resolved by an ADR and Product Owner approval.

## 1. Architecture objective

HAVRE must preserve one identity and one life history while context providers, devices, models, prompts, retrieval algorithms, serving engines, and training frameworks change around them. The architecture therefore makes minimized canonical observations, identity, contracts, provenance, and evaluation durable; implementations remain replaceable. Source experience is append-preserved by default under retention and owner-erasure policy, while derived understanding remains revisable.

This is an architecture lock on boundaries and data contracts, not a lock on every library or algorithm.

### Non-goals for Stage 0.1

- No chat UI, API, database, model invocation, memory extraction, or training implementation.
- No Kubernetes, distributed queue, service mesh, agent framework, or speculative multi-user platform.
- No performance or quality claims without measurements.
- No model-specific chat templates in canonical data.

## 2. System shape

HAVRE starts as a **modular monolith with explicit ports**, plus replaceable process boundaries for work that has different operational needs.

```text
Real life / authorized context sources
          |
          v
 local minimization + ContextAdapter
          |
          v
Web now / iPhone later / device ingest
          |
          v
    Companion API / context ingest process
          |
          +---------------- Companion Core ----------------+
          | identity | user model | goals | state | scene sessions |
          | memory semantics | policy | context | tools    |
          +---------------------+---------------------------+
                                |
                       provider-neutral ports
              +-----------------+-------------------+
              |                 |                   |
              v                 v                   v
       PostgreSQL +       Worker process      Model Provider
          pgvector        (same codebase)          Router
                                                     |
                                             HTTP inference service
                                             (vLLM candidate later)
```

The Companion Core owns meaning and policy. The ML Systems Backbone owns candidate generation, ranking, routing, serving, measurement, training, and deployment mechanics. The Backbone may suggest; it does not redefine identity, goals, evidence semantics, or product boundaries.

### Initial deployable units

1. `api`: FastAPI ingress and synchronous orchestration.
2. `worker`: future background jobs such as extraction, proactive trigger/proposal evaluation, scheduled delivery, reflection, consolidation, evaluation, and dataset building. It uses the same domain packages as the API but a separate executable boundary. It is not active in Stage 1 or this amendment.
3. `postgres`: system of record, pgvector index, and initially the durable job/outbox mechanism.
4. `web`: future browser client; the owner-scoped Stage 1 slice uses the API/CLI ingress and does not activate a web UI.
5. `inference`: an independently deployable, loopback-only OpenAI-compatible server activated in Stage 3, currently pinned to an owner-controlled llama.cpp/Qwen candidate baseline. The self-hosted composition root must bind declarations to a process-specific runtime attestation before interactions can persist model lineage. Runtime configuration can swap it with another contract-compatible provider without changing Companion domain code.

These are not five independent product microservices. API, worker, and domain packages remain one codebase until measured workload or ownership constraints justify separation.

## 3. Dependency rules

Dependencies point inward:

```text
apps / service entrypoints
        -> application orchestration
            -> Companion Core domain
                -> provider-neutral interfaces (ports)

database / provider / tracing / serving adapters
        -> implement ports; never define domain meaning
```

Rules:

- `companion/` must not import vLLM, MLflow, a cloud SDK, or web-framework request types.
- `mlsys/` may implement retrieval, routing, tracing, and serving adapters but must consume domain contracts.
- `learning/` consumes immutable events and versioned derived data; it never writes directly into production model status without an evaluation/deployment gate.
- `apps/` and `services/` are composition roots, not homes for domain logic.
- Context source hosts (Windows/iPhone/provider adapters) may normalize and minimize observations, but cannot own State/User Model interpretation, Memory promotion, Trigger/Interruption Policy, rendering, or delivery authorization.
- Large binary artifacts live outside PostgreSQL; the database stores their immutable URI, hash, size, and metadata.

## 4. Durable domains

### Companion Core

- **Constitution, identity, and values:** human-approved, model-independent principles, mission, personality, communication style, and boundaries, versioned separately from weights and prompts.
- **User Model:** temporally revisable beliefs with confidence, uncertainty, supporting evidence, counter-evidence, validity periods, and lifecycle history.
- **Goals:** reality and inner-life tracks, concrete next actions, progress, and review cadence.
- **Current State:** short-lived estimates that expire and do not silently rewrite durable beliefs.
- **Scene Sessions:** first-class Before, During, and After aggregates containing the planned situation, interventions, real-world actions, outcomes, and reflection—not merely a label on chat messages.
- **Memory semantics:** working, episodic, semantic, pattern, and progress classes with lifecycle and provenance.
- **Intervention Policy:** structured decision before natural-language rendering.
- **Proactive Interaction:** durable Trigger Records and Proactive Proposals that may connect Goals, Scene Sessions, Reflection, and actual outreach without treating any trigger as permission to send.
- **Interruption Policy:** separate governed decision about whether, when, and through which channel HAVRE may initiate contact; it never delegates authorization to a model.
- **Context Builder:** deterministic, token-budgeted selection with inspectable inclusion/exclusion reasons.
- **Response Policy:** versioned fail-closed decision between model rendering and owner-visible delivery, preserving raw output while binding any replacement to evidence, category, reason, and output hashes.
- **Tools:** capability boundary with explicit consent, scopes, and audit events.
- **Delivery:** provider-neutral, idempotent, privacy-aware channel boundary used only after Core authorization and rendering.
- **Ambient Life Context:** provider-neutral sources, narrow capabilities, local minimization, consent/sampling/retention policy, canonical life observations, source health, freshness, and missingness. It supplies evidence to existing domains and never authorizes outreach.

The active Stage 5 Scene slice stays inside the modular monolith. A local Web
simulator sends explicit categorical inputs to the Scene API; the Core first
persists an immutable structured `InterventionDecision`, then records the exact
guidance actually shown. Scene lifecycle transitions and ordered records
preserve Before/During/After state and the Intervention → Action → Outcome →
Reflection chain. Policy outputs are future Stage 6 inputs only: every active
decision is `simulation_only` and `outreach_authorized = false`, and no trigger,
scheduler, renderer, or delivery adapter exists.

### Governance hierarchy

HAVRE uses an explicit authority order:

```text
Constitution / Core Principles
        ↓ constrains
Identity and Values
        ↓ constrains
Governed policy layer
        ├── Intervention Policy: what guidance is appropriate
        └── Interruption Policy: whether/when/channel to initiate contact
        ↓ constrains
Learned Preferences
        ↓ constrains
Personalized rendering/model behavior / adapters
```

- **Constitution / Core Principles** states non-negotiable mission, agency, privacy, safety, epistemic humility, and human-approval rules.
- **Identity and Values** interprets those principles as HAVRE's stable personality, boundaries, and communication style.
- **Intervention Policy** turns approved principles and identity into versioned decisions about appropriate guidance for a situation.
- **Interruption Policy** evaluates a durable proactive proposal and returns `SEND_NOW`, `DEFER`, `DROP`, or `REQUEST_OWNER_CONFIRMATION`; only it may authorize outreach, and unresolved evidence/permission/privacy defaults to silence or deferment.
- **Learned Preferences** describe what appears helpful for this user, with uncertainty, temporal validity, evidence, and counter-evidence.
- **Personalized behavior/adapters** may improve rendering or learned behavior within all higher-layer constraints.

Authority only flows downward. A lower layer may propose a higher-layer change, but cannot activate it. Material changes to the Constitution, identity, core values, safety or intervention/interruption policy, or personalized model release require explicit human approval and a versioned audit record. The reflection/training pipeline may never rewrite the Constitution. ADR-0016 and ADR-0017 accept Interruption Policy as a future sibling in this layer; its runtime remains inactive until the named Roadmap stage and owner decisions.

### Data handling policy

Privacy classification and usage eligibility are domain policy, independent of any model provider. Every relevant event, memory, belief, Context Pack item, training example, evaluation artifact, and other derived personal artifact carries or resolves a versioned `DataPolicy`:

```text
privacy_class: PUBLIC | NORMAL | PRIVATE | HIGHLY_PRIVATE | LOCAL_ONLY
memory_eligible: true | false
training_eligible: true | false
cloud_eligible: true | false
policy_version
decision provenance / consent reference
```

The three eligibility flags are independent. Being useful as memory does not grant training permission; being permitted for cloud inference does not grant training permission. Defaults are conservative: `training_eligible = false` unless explicitly allowed, and `LOCAL_ONLY` implies `cloud_eligible = false` as an invariant.

Derived artifacts inherit the most restrictive source constraints unless an explicit owner-approved policy revision permits a narrowly defined declassification. The Context Builder records effective policy on every selected item and computes pack-level constraints. The Router treats those constraints as hard eligibility filters before considering latency, quality, availability, or cost. It may not drop required `LOCAL_ONLY` context merely to make a cloud route eligible.

On-device aggregation, redaction, categorization, or summarization does not by itself declassify source information. Every retained life-context observation has its own DataPolicy and exact consent/adapter/source provenance. Source-local raw sensor material may be ephemeral under an approved RetentionPolicy; any retained canonical observation and derivative remains subject to owner erasure and deletion propagation.

### Ambient Life Context boundary (proposed)

The permanent upstream path is:

```text
ContextSource
  -> narrow ContextSourceCapability + ConsentScope
  -> source-local preprocessing under SamplingPolicy / RetentionPolicy
  -> ContextAdapter normalization
  -> owner/device/source-authenticated ContextObservationDraft
  -> Core validation
  -> LifeContextObservation Event + ContextSourceHealth
  -> expiring Current State / temporal User Model / Memory / Goals
```

`LifeContextObservation` is the earliest retained provider-neutral evidence, not a psychological interpretation. The device-native input used to compute it need not be centralized. A Calendar interval is not yet “upcoming”; a coarse game-category duration is not procrastination; an offline Windows agent is not inactivity.

The Core records source coverage and computes use-specific freshness (`fresh`, `aging`, `stale`, `expired`, or `unknown`). Missing, stale, revoked, offline, or unsupported sources remain explicit and cannot silently become negative evidence. An estimate whose required coverage is absent returns insufficient evidence or a qualified partial result.

Windows, iPhone, Calendar, location, voice, and wearable implementations all use the same adapter/observation/health contracts. Windows defaults to coarse local summaries and no screenshots, keystrokes, clipboard, raw microphone, or unrestricted content capture. iPhone uses only OS-supported, individually consented capabilities and is not assumed to run arbitrary continuous background code or inspect other applications. Full semantics are in [`AMBIENT_LIFE_CONTEXT.md`](AMBIENT_LIFE_CONTEXT.md) and proposed [ADR-0019](adr/0019-provider-neutral-ambient-life-context.md).

### ML Systems Backbone

- Event ingestion and derived-data jobs
- Embeddings, candidate retrieval, hybrid scoring, reranking, and retrieval evaluation
- Provider adapters, inference serving, streaming, routing, and fallback
- Context/caching experiments
- Trace collection and request correlation
- Canonical dataset snapshots and lineage
- LoRA/QLoRA-compatible training runs and artifact registry
- Behavioral, retrieval, systems, and regression evaluation
- Release manifests, health checks, deployment state, and rollback

## 5. Synchronous interaction path

One ordinary user interaction follows this path:

1. API validates input, creates `request_id`, accepts or creates a W3C `trace_id`, and starts the request span.
2. The raw `USER_MESSAGE` event is committed before model generation. The same transaction may enqueue durable follow-up work.
3. Application services load the active scene, active goals, relevant User Model beliefs, and non-expired Current State.
4. Retrieval receives a standalone `RetrievalRequest`; it returns ranked candidates, score components, versions, and latency without invoking the response model.
5. Intervention Policy emits a versioned structured decision.
6. Context Builder produces a versioned, token-budgeted `ContextPack` with source references and selection reasons.
7. Router selects an eligible model/provider from explicit privacy, latency, capability, availability, and cost constraints.
8. The selected adapter translates the canonical `InferenceRequest` to the provider protocol. Provider-specific identifiers stay in the response metadata.
9. Core applies the accepted versioned Response Policy to the completed model rendering. The policy passes ordinary companion language through, but fails closed on its recognized memory-provenance, urgent-safety, hidden-instruction, deterministic exact/structured, and tool-effect boundaries.
10. The owner-visible output is returned to the client. A completed `ASSISTANT_MESSAGE` Event binds the policy decision to the request, trace, Context Pack, inference response, raw-output hash, and delivered-output hash. Raw inference remains separate evidence. A failed call emits an explicit failure event; it is never recorded as a successful assistant response.
11. Feedback, user action, outcome, and later reflection are new events, never edits to the original interaction.

If persistence of the user message fails, HAVRE must not proceed as though a durable interaction exists. If assistant-response persistence fails after output was shown, an idempotent reconciliation record must repair the gap and flag the trace.

ADR-0022 assigns hard delivery guarantees to Core/runtime without turning Core
into a style rewriter. Personality, mode selection, warmth/firmness, repair,
opinions, relationship continuity, evidence-faithful natural Memory use, and
long-form quality remain model responsibilities.

### Stage 1 permanent vertical slice

Stage 1 activates the smallest real path through the final system:

```text
User request
  -> request_id
  -> W3C trace
  -> durable raw USER_MESSAGE Event + DataPolicy
  -> approved Constitution / Identity / Values loading
  -> minimal token-budgeted ContextPack with provenance and effective privacy
  -> provider-neutral InferenceRequest / ModelProvider
  -> model response
  -> durable delivered ASSISTANT_MESSAGE Event
  -> inference/trace metrics + version/provenance links
```

This is not a disposable MVP. It uses the final event envelope, policy resolution, Context Pack, provider, inference, trace, and provenance contracts. Later stages insert retrieval, the temporal User Model, Intervention Policy, Scene Sessions, reflection, and training between these existing steps; they do not replace the path.

### Five North Star flows

The final architecture supports **Talk**, **Prepare**, **Guide**, **Reflect**, and **Reach Out**. The first four may begin through user activity; Reach Out is the governed proactive entrance that connects a Goal or Scene to preparation, guidance, outcome collection, and reflection. Every future stage must state which of these flows it enables or supplies evidence to, without treating Reach Out as a replacement for reactive interaction.

### Proposed proactive interaction path

The proactive path enters the same Companion Core but has a separate authorization lifecycle:

```text
Trigger evaluation over Events / Goals / Scenes / State / Memory
  -> durable TriggerRecord (evidence, not permission)
  -> durable ProactiveProposal
  -> InterruptionPolicy
       -> DROP / DEFER / REQUEST_OWNER_CONFIRMATION: stop or wait
       -> SEND_NOW
            -> purpose-bound ContextPack
            -> deterministic or provider-neutral model rendering
            -> provider-neutral DeliveryProvider
            -> idempotent DeliveryAttempt
            -> durable proactive ASSISTANT_MESSAGE only after visibility
            -> explicit response/dismissal/outcome linkage
```

Context observation, state interpretation, Trigger creation, proposal creation, authorization, content rendering, and delivery are different components. A ContextSource or model may supply evidence or suggest a proposal/wording but cannot schedule, authorize, retry, or deliver it. The first future delivery adapter is Web/inbox; iPhone push remains Stage 11 and Windows/Calendar/location/wearable context adapters remain Stage 12. See [`PROACTIVE_INTERACTION.md`](PROACTIVE_INTERACTION.md) and [`AMBIENT_LIFE_CONTEXT.md`](AMBIENT_LIFE_CONTEXT.md).

Long-deferred/scheduled proactive work uses a new trace linked to the trigger/evidence origin traces. Events and domain artifacts retain exact causality and provenance; telemetry remains content-free by default.

## 6. Memory ingestion and retrieval path

### Ingestion

```text
source events
  -> durable background job
  -> candidate extraction
  -> classification + importance + dedup/merge proposal
  -> evidence validation
  -> memory revision persisted
  -> embedding(s) persisted by embedding-version
  -> MEMORY_CREATED or MEMORY_REVISED lifecycle event
```

Extraction does not overwrite raw events. A memory can be superseded or retracted while its prior revisions remain inspectable until the user requests deletion.

An Event is experience; a Memory is a promoted derived artifact. `memory_eligible = true` allows candidate consideration but never forces promotion. Most observations and casual utterances remain Events only. Promotion, contradiction, temporal validity, consolidation, archival, reconsolidation, relevance decay, and regeneration are versioned processes with exact provenance. Decay may affect retrieval priority but cannot silently change confidence/truth or perform deletion. Owner erasure and approved retention expiry remove contaminated derivatives; rebuilding may use only remaining eligible sources. See accepted [ADR-0020](adr/0020-experience-memory-lifecycle.md).

### Retrieval

```text
RetrievalRequest
  -> query features / embedding
  -> candidate generation (exact vector + metadata/privacy filters)
  -> versioned score components
  -> minimum-relevance gate
  -> duplicate suppression
  -> ordered RetrievalResult + explicit exclusions
  -> Context Builder selection under a separate token budget
```

Retrieval is independently benchmarked against relevance judgments. The Stage 2 default `retrieval-r1-vector-gated-v2` admits only candidates with semantic similarity at least `0.35` and suppresses near duplicates using versioned token-overlap and embedding-similarity thresholds. `RetrievalResult` rejects inconsistent algorithm/policy/threshold/context-eligibility combinations, candidates whose actual semantic score is missing, non-finite, or below the declared minimum, and repeated candidate content hashes. Context Builder v5 independently repeats those checks, verifies owner/request/trace/query-event binding, and only then applies its token budget. Legacy R0/R1 results cannot enter a model prompt even if a caller changes `context_eligible`. These thresholds are tied to the current deterministic embedding and gold set, not universal relevance claims. Lexical retrieval and a reranker remain inactive until evidence justifies them.

## 7. Future training and deployment path

### Daily conversation and owner-feedback boundary

The computer Web client is a channel adapter over the existing Interaction
Service. It does not own personality, history, Memory, retrieval, policy, or
model state. Completed turns first become durable `USER_MESSAGE` and
`ASSISTANT_MESSAGE` Events. Client-visible text streaming is durability-gated:
Core consumes and validates the provider stream, commits the completed assistant
Event, and only then emits text deltas to the Web client. This favors truthful
history over lower apparent time-to-first-token until interrupted-response
reconciliation has its own accepted contract.

Web sessions form conversation episodes at an explicit boundary. Episode
membership is an ordered owner-qualified set of exact Event IDs and hashes. An
episode summary is a derived, policy-conservative retrieval artifact; it is not
a User Model fact. Derived Memory suggestions, response feedback revisions,
owner-edited alternatives, review attribution, and future training authorization
remain separate records. See ADR-0021.

```text
Web / other channel
  -> Interaction Service -> Event Store
  -> episode boundary -> summary + exact members -> shared-history recall
  -> concentrated Memory review

assistant Event -> feedback revision / owner alternative
  -> issue attribution -> runtime fix OR evaluation-only OR owner training review
  -> future immutable dataset -> candidate -> evaluation -> explicit promotion
```

The last line is not an online learner. Runtime and weights never change merely
because feedback was saved.

1. Only source records whose effective policy explicitly has `training_eligible = true` may become **training candidates**. Memory eligibility or cloud eligibility never implies training eligibility. Candidates retain policy provenance and review state.
2. A versioned filter/dedup policy builds immutable canonical examples. Provider chat templates and tokenization are not stored as canonical truth.
3. An immutable dataset snapshot freezes member IDs, splits, policies, hashes, and source coverage. Evaluation holdouts are excluded from training by policy.
4. A training run records code revision, seed, base-model revision, dataset version, configuration, environment, and output hashes.
5. The adapter is registered as `candidate`; it is never implicitly production.
6. Offline behavioral, safety, retrieval-context, and systems evaluations compare it with the current production release.
7. If gates pass, an approved release manifest pins every dependency: Companion Core, schema, identity/prompt/policy, retrieval components, base model, adapter, tokenizer, dataset, and eval report.
8. Deployment health and limited/shadow checks run. Promotion is explicit and rollback points to the previous immutable manifest.
9. A failed candidate is retained as `rejected` with evidence; it does not mutate production identity or history.

## 8. Failure and degradation policy

- **Database unavailable:** reject new state-changing interactions; do not create untraceable “ghost” history.
- **Retrieval unavailable:** a response may proceed only in an explicitly recorded degraded mode using recent conversation and stable identity; no memory-dependent factual claims.
- **Provider unavailable:** router may choose an eligible fallback; privacy constraints cannot be relaxed automatically.
- **Local-only data with no eligible local model:** fail closed or ask for an owner-visible alternative; never send the data to a cloud model and never silently omit required context to force a cloud route.
- **Worker unavailable:** synchronous interaction continues after the durable job is enqueued; queue age becomes an operational metric.
- **Proactive worker unavailable:** proposals remain durable and may expire; no API process sends an ungoverned substitute. Recovery rechecks permission, policy version, budget, cooldown, cancellation, expiration, channel, and privacy before work resumes.
- **Delivery unavailable:** record a typed failed attempt. Retry only the same authorized delivery under idempotency and a fresh eligibility check; never turn transport retry into a new persuasive message.
- **Tracing exporter unavailable:** local trace correlation and durable domain events still work; observability export must not block the companion.
- **Version mismatch:** fail closed for writes and deployment promotion; never silently coerce unknown event or dataset schema versions.
- **Unsafe or ambiguous scene:** product safety policy overrides pressure toward action.
- **Context source unavailable/stale/revoked:** record explicit health/coverage, exclude the source from current claims, and degrade to insufficient/partial evidence. Never infer the user's state from missing telemetry or broaden collection to compensate.

## 9. Permanent repository skeleton

Paths are created when their first permanent implementation lands. Stage 1 activates the root package/configuration, `companion/`, `mlsys/`, `services/api/`, `db/migrations/`, `identity/`, `contracts/`, `scripts/`, and `tests/` portions needed by the approved vertical slice; later domains remain absent rather than receiving placeholders.

```text
havre/
├── README.md
├── MASTER_PLAN.md
├── pyproject.toml                 # activated Stage 1
├── .env.example                  # names only; no secrets
├── compose.yaml                  # activates with a containerized deployment need
├── docs/
│   ├── ARCHITECTURE.md
│   ├── DATABASE_DESIGN.md
│   ├── EVENT_MODEL.md
│   ├── MLSYS_DESIGN.md
│   ├── EVALUATION_PLAN.md
│   ├── BENCHMARK_PLAN.md
│   ├── ROADMAP.md
│   ├── STATE.md
│   ├── PROACTIVE_INTERACTION.md
│   ├── AMBIENT_LIFE_CONTEXT.md
│   └── adr/
├── apps/
│   ├── web/
│   ├── ios/                       # activated Stage 11
│   └── windows-agent/             # first external source in Stage 12
├── services/
│   ├── api/
│   ├── worker/
│   └── inference/                 # adapter/config, not domain logic
├── companion/
│   ├── identity/
│   ├── user_model/
│   ├── goals/
│   ├── state/
│   ├── scenes/
│   ├── memory/
│   ├── patterns/
│   ├── policy/
│   ├── proactive/                  # activated with Stage 6 Proactive Core
│   ├── life_context/               # contracts/adapters activated by named later stages
│   ├── context/
│   ├── tools/
│   ├── delivery/                   # provider-neutral delivery contracts/adapters
│   └── events/
├── mlsys/
│   ├── contracts/
│   ├── retrieval/
│   ├── routing/
│   ├── serving/
│   ├── caching/
│   ├── tracing/
│   └── benchmarks/
├── learning/
│   ├── reflection/
│   ├── consolidation/
│   ├── datasets/
│   ├── finetuning/
│   └── registry/
├── evals/
│   ├── cases/
│   ├── fixtures/
│   ├── retrieval/
│   ├── behavioral/
│   ├── systems/
│   └── regression/
├── db/
│   ├── migrations/
│   └── seeds/                     # synthetic only
├── identity/
│   ├── mission.md
│   ├── personality.md
│   ├── principles.md
│   ├── boundaries.md
│   └── communication_style.md
├── scripts/
│   ├── bench/
│   ├── eval/
│   ├── train/
│   └── deploy/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contract/
│   └── end_to_end/
└── infra/
    ├── local/
    └── cloud/
```

The root `identity/` contains version-controlled Companion identity, not private user memories. User-specific data, secrets, production exports, model weights, and evaluation artifacts must be ignored by version control and stored in configured private locations.

## 10. Decision summary

| Decision | Real problem solved | Final-system role | Simplest activation | Alternatives | Main migration risk | Record |
|---|---|---|---|---|---|---|
| Modular monolith with ports | Preserve boundaries without operational sprawl | Stable domain ownership | API + worker from one codebase | Microservices; single script | Accidental cross-module imports | [ADR-0001](adr/0001-modular-monolith-and-process-boundaries.md) |
| PostgreSQL + pgvector | Transactions, metadata, vectors, provenance in one authority | Durable system of record | One PostgreSQL instance | Separate vector DB; document DB | Vector scale or artifact growth | [ADR-0002](adr/0002-postgresql-and-pgvector.md) |
| Append-oriented event ledger | Preserve source experience and audit evolution | Rebuildable history | One partition-ready table | Mutable chat rows; event sourcing everything | Schema evolution and user erasure | [ADR-0003](adr/0003-append-oriented-events-and-erasure.md) |
| Explicit provenance graph | Prevent derived claims from losing evidence | Recompute and challenge beliefs/memories | Generic typed edge table | IDs inside JSON only; per-table join tables | Edge volume and semantic drift | [ADR-0004](adr/0004-provenance-and-derived-revisions.md) |
| Provider-neutral inference contract | Prevent identity/business logic from binding to a model vendor | Replaceable Personal/Teacher/Edge brains | One adapter | Direct provider SDK calls | Lowest-common-denominator interface | [ADR-0005](adr/0005-provider-neutral-inference.md) |
| W3C trace propagation | Correlate API, worker, retrieval, and inference | Vendor-neutral observability | Trace IDs + spans, exporter optional | Random request IDs only | Async causality across long jobs | [ADR-0006](adr/0006-w3c-trace-context.md) |
| Canonical model-independent datasets | Reuse history across base models | Long-term personalization asset | JSON-compatible records + snapshot manifests | Tokenized provider datasets | Schema migrations and privacy deletions | [ADR-0007](adr/0007-canonical-datasets-and-lineage.md) |
| PostgreSQL durable jobs/outbox first | Avoid missed work without early queue infrastructure | Worker reliability boundary | Job/outbox table with leases | In-process tasks; Redis/Celery now | Throughput/locking limits | [ADR-0008](adr/0008-database-backed-worker-boundary.md) |
| Identity outside weights | Model changes must not erase the Companion | Persistent mission and values | Versioned files + release reference | Prompt-only; LoRA-only persona | Conflicting identity versions | [ADR-0009](adr/0009-model-independent-identity.md) |
| Evaluation-gated releases | Prevent subjective or systems regressions | Controlled model/system evolution | Versioned suites + explicit approval | “Chat and feel” acceptance | Imperfect judges and stale cases | [ADR-0010](adr/0010-evaluation-gated-releases.md) |
| Provider-independent data policy | Separate privacy, memory, training, and cloud permissions | Enforceable use constraints across all brains and pipelines | Versioned policy on protected records | Provider-specific privacy flags; one sensitivity label | Policy propagation and consent revision | [ADR-0011](adr/0011-data-handling-policy.md) |
| Bitemporal belief history | Explain what HAVRE believed, when, and about which life period | Longitudinal, revisable User Model | Immutable belief revisions + lifecycle transitions | Current-value row; event time only | Query complexity and uncertain dates | [ADR-0012](adr/0012-temporal-belief-model.md) |
| First-class Scene Session | Preserve situation-to-outcome evidence beyond chat | Before/During/After real-world interaction model | Root aggregate + linked event/artifact records | Chat tags; one JSON blob | Partial sessions and lifecycle evolution | [ADR-0013](adr/0013-scene-session-domain-object.md) |
| Governed behavior hierarchy | Prevent learning or adapters from rewriting principles | Persistent human-owned Companion identity | Versioned layers + approval gates | Prompt/weights as authority | Layer conflict and approval drift | [ADR-0014](adr/0014-governed-behavior-hierarchy.md) |
| Outcome-aware evaluation | Distinguish fluent responses from useful real-world guidance | Product evidence tied to values and goals | Consent-based action/outcome observations | Language-only judging; engagement metrics | Confounding and self-report bias | [ADR-0015](adr/0015-outcome-aware-evaluation.md) |
| Governed proactive authorization | Prevent a model/trigger from deciding when HAVRE enters the user's life | Explainable Reach Out flow | Rule-based Core decision after durable proposal | Model sends; trigger sends; owner confirms every message forever | Policy bypass or purpose expansion | [ADR-0016](adr/0016-governed-core-authorizes-proactive-outreach.md) |
| Interruption Policy and owner limits | Distinguish a useful reason from an appropriate time/channel | Anti-annoyance, revocable proactive control | Explicit four-way decision with settings/budgets/cooldowns | Opaque engagement score; channel settings only | Concurrency, hidden scoring, notification pressure | [ADR-0017, Accepted](adr/0017-interruption-policy-and-user-control.md) |
| Provider-neutral private delivery | Add Web/iPhone/wearable channels without making one vendor authoritative | Idempotent privacy-safe transport | Web/inbox adapter first | Direct iOS calls; reuse inference provider | Receipt ambiguity, duplicate delivery, preview leaks | [ADR-0018, Accepted](adr/0018-provider-neutral-private-delivery.md) |
| Provider-neutral Ambient Life Context | Obtain useful real-life evidence without provider lock-in or surveillance defaults | Minimized observations, source health, freshness, consent, and adapter replacement | Synthetic/manual Stage 6 contracts only; external adapters remain later gated work | Direct provider payloads; raw sensor lake | Consent/semantic drift and hidden missingness | [ADR-0019, Accepted](adr/0019-provider-neutral-ambient-life-context.md) |
| Experience-to-memory lifecycle | Preserve experience without making every event a permanent belief/memory | Promotion, consolidation, temporal validity, archival, reconsolidation, and erasure | Existing Stage 2/4 subset plus proposal-only Stage 7 activation | Every event is memory; overwritten summary | Stale identity labels and deleted-data resurrection | [ADR-0020, Accepted](adr/0020-experience-memory-lifecycle.md) |

## 11. What must be understood before the amendment review gate

- HAVRE's identity is data and policy owned by HAVRE, not behavior entrusted to one model.
- Constitution and identity constrain learning; learned preferences and adapters cannot silently modify higher layers.
- Events are durable observations; memories and beliefs are revisable interpretations.
- Privacy classification, memory eligibility, training eligibility, and cloud eligibility are separate decisions; `LOCAL_ONLY` never reaches a cloud model.
- Scene Sessions preserve the full Situation → Intervention → Action → Outcome chain as first-class data.
- Retrieval, context selection, policy, and generation are distinct measurable steps.
- A trace explains execution; provenance explains epistemic lineage. Neither substitutes for the other.
- “Append-only” governs normal operation and does not override the user's right to erase personal data.
- Stage 3 self-hosted inference is approved and complete as a candidate systems baseline at source snapshot `sha256:9a43713e082dec08039a93c673c7a0af812b881dcb0d5d3da68a0b17e7075436`; this is not a personalized production-model release.
- Stage 4 implements ADR-0004/0011/0012/0014/0015 inside the modular monolith: typed evidence feeds immutable bitemporal belief revisions, proposal-only consolidation, expiring Current State, and event-backed goals/progress; every context admission and erasure path remains owner/policy/provenance qualified. Additive `0009` uses single-use qualified transition identity for belief heads and database-time binding for Goals; additive `0010` makes Goal/DataPolicy projection material an exact strict contract and has PostgreSQL reconstruct the only accepted canonical digest; additive `0011` applies the same integrity to initial Goal INSERT; additive `0012` makes required support/snapshot provenance a deferred commit invariant, expands missing-edge audit coverage, and binds Goal progress INSERT to exact Goal/event/evidence/hash material. The Product Owner accepted Stage 4 at the recorded snapshot. Additive `0013` implements the bounded Stage 5 Scene/Intervention/Web slice, and `0014` closes its acceptance blockers. Additive `0015`–`0017` implement conservative local Stage 6; `0018`–`0020` implement proposal-only Stage 7; `0021` and `0022` close the reproduced acceptance blockers, including current-preference and database evidence/erasure serialization. Stages 6 and 7 await Product Owner reacceptance.
- Talk, Prepare, Guide, Reflect, and Reach Out are the five permanent North Star flows; Reach Out connects rather than replaces the others.
- A TriggerRecord is evidence and a ProactiveProposal is a candidate. Neither is permission to contact the user.
- Only the governed Core's Interruption Policy may authorize outreach. A model may render wording only after authorization.
- Intervention Policy decides what guidance is appropriate; Interruption Policy decides whether/when/channel HAVRE may initiate contact.
- Silence, deferment, expiration, dismissal, snooze, and stop are first-class outcomes; missing response is not distress.
- Proactive Core is the authorized Stage 6 scope, Reflection proposals are the authorized Stage 7 scope, native push remains Stage 11, and external context triggers remain Stage 12.
- ADR-0016 through ADR-0020 are accepted boundaries. The Product Owner separately activated only the conservative Stage 6 local simulation and proposal-only Stage 7 slice; real delivery and external Context Sources remain inactive.
- Context sources are replaceable and produce minimized observations plus health; they do not own interpretation or outreach.
- Observation, Current State, User Model belief, Pattern, Memory, Trigger, and authorization are separate lifecycle stages.
- Missing or stale telemetry is unknown evidence, never proof of inactivity, progress, intent, or distress.
- Experience is not automatically Memory. Historical validity can remain true while a later revision becomes current.
- ADR-0019 and ADR-0020 were accepted by the Product Owner on 2026-08-19. Their acceptance and the separate Stage 6/7 authorization do not authorize any external source or real delivery.
