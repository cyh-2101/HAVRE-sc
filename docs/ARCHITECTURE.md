# HAVRE Architecture

## Current personal-context boundary (2026-09-06)

[ADR-0039](adr/0039-personal-context-engine-and-evidence-compiler.md) records the
owner-authorized fresh review. HAVRE evolves as a persistent Personal Context /
Memory / Identity Engine with governed action and a replaceable reasoning Brain.
This changes selectors and evidence compilation, not canonical Identity or privacy.

The main reply and delayed continuation use `PersonalContextCompiler`: current
intent, Identity and owner constraints, grouped recent exchanges, concrete past
experience, relevant Goal/State/Calendar, lower-authority understanding, then
optional behavior examples. Owner corrections and retractions qualify older raw
sources without rewriting them. Required qualification that cannot fit fails
closed. Event search uses an owner/time/route-qualified lifetime lexical index and
bounded local semantic reranking; exact long-text excerpts carry source offsets.
Unresolved people references remain uncertain; there is no inferred entity graph.
Delayed generation and final transactional delivery recheck revisable sources;
Current State publication shares a database lock with delivery. Product source
previews traverse exact owner-qualified revisions back to original chat.

See the [fresh review and evidence](PERSONAL_CONTEXT_ENGINE_REVIEW_2026-09-06.md)
for current implementations, measured improvements, rollout and remaining limits.
The stage-specific sections below preserve the history of their activation.

Status: **Durable Core boundaries are accepted through ADR-0030. Stage 13 conversation intelligence, Stage 14's dual Replyer, the bounded Stage 15 commitment loop, migration 0059's experience-first daily review, and migrations 0060-0063's bounded relational initiative are implemented and owner-locally active within explicit owner directions. New two-beat planning is source-bound to GPT-5.6-sol/high for eligible PUBLIC/NORMAL turns; historical local receipts retain Qwen. The same Core controls remain authoritative; formal ADR-0032/0034/0035/0036 acceptance and practical usefulness remain open.**

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
5. `inference`: an independently deployable, loopback-only OpenAI-compatible server activated in Stage 3, currently pinned to an owner-controlled llama.cpp/Qwen candidate baseline. ADR-0030 binds this exact unadapted artifact as the implemented local daily privacy branch. The self-hosted composition root binds declarations to a process-specific runtime attestation before interactions can persist model lineage. This is an execution binding, not promotion or proof of conversational quality; runtime configuration can later swap it with another contract-compatible provider without changing Companion domain code.
6. `mcp-companion`: a local STDIO adapter activated only for the Stage 14A
   ChatGPT desktop pilot. It exposes approved PUBLIC Identity and deterministic
   planning over the already-visible current message. It has no database,
   network, private-context, write, inference-provider, or delivery capability.

These are not six independent product microservices. API, worker, MCP adapter,
and domain packages remain one codebase until measured workload or ownership
constraints justify separation.

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
- **Conversation Intelligence:** pre-retrieval deterministic Turn Contract, relevance-gated Memory Broker, Context Compiler, replaceable Replyer, and coverage evidence as specified in [`CONVERSATION_INTELLIGENCE_ARCHITECTURE.md`](CONVERSATION_INTELLIGENCE_ARCHITECTURE.md).
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
3. Application services load bounded recent dialogue, confirmed response constraints, active scene/goals, relevant User Model beliefs, and non-expired Current State.
4. A deterministic, versioned Turn Contract decides the current obligations, mode, depth, stance, uncertainty, decision requirement, and whether durable Memory retrieval is needed.
5. The Memory Gate persists an explicit empty result for `none`; otherwise Retrieval receives a standalone `RetrievalRequest` and returns ranked candidates, score components, versions, exclusions, and latency without invoking the response model.
6. Intervention Policy emits a versioned structured decision where the active flow requires it.
7. Context Builder produces a versioned, token-budgeted `ContextPack` with source references and selection reasons.
8. A versioned presentation renderer translates only the already-admitted ContextPack into provider-facing messages. It keeps one leading identity/Turn-Contract/personal-context system message, preserves every source reference, presents ranked Memory as optional evidence, and makes current-input precedence, partial-evidence uncertainty, silent use, and no-forced-callback semantics explicit.
9. Router selects an eligible model/provider from explicit privacy, latency, capability, availability, and cost constraints.
10. The selected Replyer adapter translates the canonical `InferenceRequest` to the provider protocol. Provider-specific identifiers stay in the response metadata.
11. Bounded coverage evidence records obligation/decision/truncation failures without an open-ended model loop.
12. Core applies the accepted versioned Response Policy to the completed model rendering. The policy passes ordinary companion language through, but fails closed on its recognized memory-provenance, urgent-safety, hidden-instruction, deterministic exact/structured, and tool-effect boundaries.
13. The owner-visible output is returned to the client. A completed `ASSISTANT_MESSAGE` Event binds the policy decision to the request, trace, Context Pack, inference response, raw-output hash, and delivered-output hash. Raw inference remains separate evidence. A failed call emits an explicit failure event; it is never recorded as a successful assistant response.
14. Feedback, user action, outcome, and later reflection are new events, never edits to the original interaction.

If persistence of the user message fails, HAVRE must not proceed as though a durable interaction exists. If assistant-response persistence fails after output was shown, an idempotent reconciliation record must repair the gap and flag the trace.

ADR-0022 assigns hard delivery guarantees to Core/runtime without turning Core
into a style rewriter. Personality, mode selection, warmth/firmness, repair,
opinions, relationship continuity, evidence-faithful natural Memory use, and
long-form quality remain model responsibilities.

The Strong Cloud Brain ceiling experiment exercises this existing seam with a
default-disabled cloud adapter on explicitly authorized PUBLIC synthetic
fixtures only. It does not add a provider-specific Companion path: current
Identity/Context becomes the canonical request, the adapter performs transport
translation, and Core independently governs the returned rendering. The
experiment activates no production route and grants no cloud eligibility to
owner or private data.

### ChatGPT desktop MCP pilot boundary

The Stage 14A path is deliberately outside the canonical interaction path:

```text
current ChatGPT message + PUBLIC HAVRE Identity
        -> local read-only MCP tool
        -> ChatGPT-hosted generation
        -> owner-visible ChatGPT reply
```

MCP is a tool/context interface, not HAVRE's `ModelProvider`. The host's final
reply does not pass through ContextPack persistence, provider request binding,
ADR-0022 Core response policy, the Event Store, feedback linkage, or governed
Memory. This makes the pilot useful for testing whether a strong host model plus
HAVRE's fixed Identity and Turn Contract improves conversation quality, but it
does not establish HAVRE continuity.

No private source receives cloud eligibility from this path. Any later
private-context bridge is a separately derived disclosure with owner authority,
policy, provenance, minimization, retention, revocation, and erasure semantics;
it cannot be implemented as an ungoverned Memory query.

### Owner-local dual Replyer boundary

ADR-0029 adds a different Stage 14B path inside the canonical interaction seam:

```text
ordinary PUBLIC/NORMAL user Event
  -> ResponsePlan -> retrieval gate -> ContextPack
  -> exact Codex request authorization and hash binding
  -> ephemeral no-tools GPT-5.6-sol reply
  -> Core response policy
  -> durable assistant Event -> HAVRE Web chat
```

This is a `ModelProvider`, not MCP. It reuses the owner-local Codex app's
ChatGPT authentication without reading an API key. Each call is an independent
ephemeral process in an empty read-only workspace; HAVRE supplies bounded
short/long context every turn. Only final agent-message output is accepted, and
any tool event fails closed. The provider cannot read the repository, browse,
call MCP/apps, mutate Memory, or authorize proactive contact.

The GPT route does not reclassify data. Only an already cloud-eligible PUBLIC or
NORMAL effective ContextPack may pass. Provider-side retention/account policy
and the model alias are external constraints, while Core/Event persistence,
provenance, correction, and erasure remain HAVRE responsibilities.

ADR-0030 extends this seam with a second eligible Replyer rather than widening
the cloud boundary:

```text
completed canonical ContextPack
  -> effective DataPolicy
       PUBLIC/NORMAL + cloud eligible -> isolated GPT-5.6-sol Provider
       otherwise                      -> attested local Qwen3-8B Provider
  -> provider-specific request binding
  -> one raw inference result
  -> shared Core response policy
  -> durable assistant Event -> HAVRE Web chat
```

The local branch is the exact Stage 3 Qwen3-8B Q4_K_M artifact on the pinned
loopback llama.cpp runtime with no HAVRE adapter. It is an owner-local privacy
execution binding, not a promoted or personalized model release. PRIVATE,
HIGHLY_PRIVATE, and LOCAL_ONLY remain ineligible for automatic GPT use. A
PUBLIC/NORMAL pack whose cloud flag is false also uses local execution because
cloud eligibility is a hard permission, not a preference.

The Router consumes the completed pack's policy and records the selected and
excluded providers before provider-specific binding. It is a deterministic
DataPolicy router, not a semantic sensitivity classifier. It cannot omit required
stricter context to select GPT, attach Codex authorization metadata to Qwen, or
use cloud when the local provider is unavailable or over the authorized
llama.cpp runtime profile's 8,192-token total-context cap. That configured cap is
not a claim about the intrinsic context capacity of Qwen3-8B. The implemented
route has no silent cross-provider retry: either provider's failure remains typed
and creates no successful assistant Event.

The Web client's ordinary default is NORMAL with an explicit only-local choice.
The former per-response Strong Brain/Strong UX choice is retired and is not an
input to routing; its guarded legacy endpoint is compatibility surface only.
Changing a later turn back to NORMAL does not authorize earlier stricter history
for cloud use. Tests establish that the completed effective pack stays local when
required stricter context is present; whether that boundary produces useful
owner-visible continuity remains part of the practical-use gate.

Real synthetic probes have exercised both the authenticated owner-local Codex
CLI GPT-5.6-sol branch and the exact unadapted local Qwen3-8B branch through this
shared ResponsePlan, ContextPack, Core, and Event pipeline. One current GPT probe
reported 11,824 prompt tokens, while an earlier GPT-only probe reported 10,818.
These are separate observations, not a fixed overhead, capacity guarantee, or
conversation-quality result.

ADR-0031 adds three Context-compiler rules to the same provider-neutral path.
The active session is the raw working dialogue; cross-session raw Event fallback
is bounded and only used when the current message explicitly refers backward.
The message-receipt timestamp is rendered in the configured owner timezone.
An owner-authorized behavior-example bank is a separate evidence class from
Memory. ADR-0035's explicit owner-local implementation direction permits the
exact OA70 cases 1-70; at most three relevant cases may be selected per turn,
with complete source hashes and no Memory/training eligibility. This runtime
calibration does not amend the frozen source or create training evidence.
ResponsePlan v3 distinguishes acknowledgement, sharing, asking, requesting, and
deciding so short social turns do not reopen a completed plan.

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

### Owner-delegated Diary intelligence

Diary generation is a separate provider-neutral inference purpose, not another
ordinary conversation turn. It selects one owner-local day only after interaction
completion and partitions exact Events before model invocation:

1. eligible GPT-routed PUBLIC/NORMAL messages enter one high-effort Diary request;
2. private/local messages remain local-only collapsed transcript references;
3. one strict first-person result and fixed quality enum are validated;
4. source-quoted delegated Memory/belief updates and an immutable Diary revision are
   written as one transaction with exact erasure closure.

The cloud request never receives private content or private Event IDs. Automatic
understanding accepts only exact quotes from eligible owner USER_MESSAGE Events and
records the Product Owner delegation. A User Model belief still travels through the
existing candidate plus immutable activated-transition path; the model cannot bypass
belief lifecycle guards. Private-source understanding stays owner-reviewed.

Quality review is not a self-modifying agent. Only enumerated flags may cross the
boundary, and code maps them to a bounded set of response instructions. Free-form
model output cannot edit prompts, code, Identity, policy, tools, or proactive
authorization.

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

- **Ordinary Web reply lifecycle (owner-authorized 2026-09-05 repair):** the API
  owns the reply task independently of the viewing HTTP stream. Disconnecting
  the phone does not cancel an already-reserved turn. A 300-second task deadline
  cancels generation; cancellation cleanup drains outside the caller's AnyIO
  level-cancelled scope. Graceful shutdown drains owned tasks before closing
  persistence. A 15-second owner-qualified sweep terminalizes ordinary requests
  older than 330 seconds only when they still lack durable ContextPack/completion
  lineage. It appends an exact-source failure, releases chat leases, and defers
  outstanding fusion claims under a short request-row lock with SKIP LOCKED.
  Late completion must fail the existing non-processing fence. Recovery does not
  send another prompt or change source policy; GET endpoints never perform this
  repair. These are operational deadlines, not contact/intervention thresholds.
- **Database unavailable:** reject new state-changing interactions; do not create untraceable “ghost” history.
- **Retrieval unavailable:** a response may proceed only in an explicitly recorded degraded mode using recent conversation and stable identity; no memory-dependent factual claims.
- **Provider unavailable:** the general architecture permits only an explicitly versioned eligible fallback whose privacy constraints are rechecked. ADR-0030's first dual-route implementation does not silently retry across providers; it records a typed failure.
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

### Stage 15 owner commitment loop

An owner-reviewed `LOCAL_ONLY` schedule remains a source-bound reality Goal and
guarded proactive queue. A separate exact authorization may project only course
name, task name, deadline, completion state, and reminder history into a
`NORMAL`, cloud-eligible, memory/training-ineligible Context item. The Replyer
does not receive the source document, private Goal reason, or next action.

Clear completion reports create an immutable Event-to-Goal transition-evidence
edge. Due reminders may be claimed for conversation fusion, but Core records a
delivery only after exact inclusion is provable; otherwise the ordinary Web
inbox remains authoritative. Schedule-generation replacement inserts the new
queue before cancelling the exact source's old pending generation. Future
source erasure traverses these derivatives only after the owner explicitly
selects the source Event; activation itself selects and erases nothing.

### Experience-first daily review and relationship continuity

The owner-local worker leases one receipt at 05:00 in the configured owner
timezone and reviews the previous local 05:00 to current local 05:00 interval. Its isolated high-effort GPT
request receives only eligible cloud-routed PUBLIC/NORMAL Events, bounded
eligible prior conversation, and bounded current Memory; private/local text is
never prompt input. Prior context is continuity evidence rather than permission
to copy earlier facts into that day's first-person Diary. Read endpoints do not
generate or refresh Diary content.

ADR-0037 separates real-time understanding from this review. Completed eligible
GPT turns atomically enqueue exact pairs; an independent bounded task performs
GPT-high memory extraction and commits source-bound effects with a fenced job
receipt. Ordinary chat can yield no new Memory. Private/local narrative candidates
remain local and await owner review. The shared intelligence ledger distinguishes
`realtime_memory` from `daily_review`; real-time work cannot create Diary or contact
effects. Local semantic retrieval and timestamped, source-gated supplementary
history improve access to existing evidence without changing its privacy.

The same result may contain evidence-bound product suggestions and at most one
relationship follow-up proposal. Suggestions are materialized as local Markdown
for the owner to review manually; they never patch HAVRE. Memory and recent
conversation may explain a follow-up, but Core still resolves stop signals,
deduplication, expiry, category permission, the one-per-day relationship budget,
and delivery. Silence is not a trigger.

Ordinary chat remains non-transactional. Only an explicit owner request to
record/create/plan/remind opens the high-effort Goal planner. A successful write
creates an exact source-bound Goal, optional guarded reminders, plan/action
receipts, and a durable effect receipt before the Replyer may claim it was saved.
Course commitments remain grouped separately from these owner-created Goals.

ADR-0036 adds a separate governed continuation planner behind a production-
enforced runtime flag and the owner's global and friendly-check-in permissions.
It may inspect only one already-completed eligible cloud-routed
PUBLIC/NORMAL owner/assistant pair. Under the later explicit owner authorization,
new receipts use isolated no-tools GPT-5.6-sol at fixed high effort; PRIVATE,
HIGHLY_PRIVATE, LOCAL_ONLY, and cloud-ineligible turns remain excluded. Historical
receipts keep their exact local Qwen authorization rather than being rewritten.
Beat one is due after one minute. Beat two
exists only after beat one was actually visible, is due 30 minutes after that
delivery, and is the final beat. A newer owner message cancels either path, and
any active interaction defers standalone delivery. These beats use their own
two-per-24-hour category ceiling. Separately, cold delivered relationship touches
use 24-hour then 72-hour unanswered spacing and pause after three until a new
ordinary owner message. Goal reminders do not count toward that pause and may
receive at most one supplemental stable hash-derived daytime slot per local day
across all eligible Goals after an owner-approved start reminder, with the nearest
deadline selected first. Exact scheduled reminders remain independent. The owner
can separately disable important reminders or friendly check-ins. The Proactive
Core remains the only send authority. The bounded owner-local path is active
after its non-delivering wording readback; repeated owner usefulness remains
unproven.

The initial reply may itself ask one grounded question. The delayed planner may
still run, but its output must add a distinct curiosity or view. A local quality
gate turns generic emotional confirmation, unsupported mind-reading, default
recovery coaching, fabricated HAVRE life history, guessed concrete facts, and
non-opinion restatement into no-action. A visible, idle PWA polls the timeline so
Core-delivered beats appear without requiring a manual reload.

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
