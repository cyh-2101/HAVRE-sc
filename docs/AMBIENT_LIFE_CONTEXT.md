# Ambient Life Context Architecture

Status: **Accepted architecture; Stage 6 synthetic/manual contracts active, all external sources inactive**

Date: **2026-08-17**

Authority: [`MASTER_PLAN.md`](../MASTER_PLAN.md). Related accepted decisions remain in force, especially [ADR-0003](adr/0003-append-oriented-events-and-erasure.md), [ADR-0004](adr/0004-provenance-and-derived-revisions.md), [ADR-0011](adr/0011-data-handling-policy.md), [ADR-0012](adr/0012-temporal-belief-model.md), and [ADR-0016](adr/0016-governed-core-authorizes-proactive-outreach.md). This amendment is accepted through [ADR-0019](adr/0019-provider-neutral-ambient-life-context.md) and [ADR-0020](adr/0020-experience-memory-lifecycle.md).

## 1. Product purpose and boundary

HAVRE needs enough authorized evidence about the owner's life to understand relevant context without turning life into an unrestricted input stream.

Two product principles govern this layer:

> Presence should be continuous; intervention should be sparse.

> Infer from the minimum sufficient signal; do not maximize surveillance.

“Continuous presence” means that HAVRE can maintain durable continuity across authorized, intermittently available sources. It does not mean continuous raw recording. Sources remain individually permissioned, purpose-bound, revocable, freshness-aware, and allowed to be offline. Silence remains a valid output.

This document defines permanent semantics and staged activation. The Product Owner accepted it on 2026-08-19 and authorized synthetic/manual Stage 6 contracts only. It does not authorize or implement a Windows agent, Calendar connector, iPhone sensing, location, voice capture, wearable access, external source worker, real notification, or private-data export.

## 2. Placement in the existing system

The layer is named **Ambient Life Context** because it represents selectively available life context, not a surveillance substrate and not another Companion Core.

```text
REAL LIFE
  |
  +-- Calendar / task tools
  +-- Windows agent
  +-- iPhone interface and OS-authorized context
  +-- user-initiated voice
  +-- location / mobility
  +-- wearables
  +-- manual user input
  |
  v
ContextSource implementations
  -> source-local collection and minimization
  -> ContextAdapter normalization
  -> authenticated owner/device-bound ingest port
  -> canonical LifeContextObservation + ContextSourceHealth
  -> append-oriented Event Store
  -> Current State estimation
  -> temporal User Model / Goals / Memory / Pattern evidence
  -> Trigger evaluation
  -> TriggerRecord (evidence, not permission)
  -> ProactiveProposal (candidate, not permission)
  -> InterruptionPolicy
       -> DROP / DEFER / REQUEST_OWNER_CONFIRMATION / remain silent
       -> SEND_NOW -> rendering -> DeliveryProvider
```

This is one upstream evidence path into the accepted architecture. It does not create a parallel event store, user model, policy engine, delivery system, or device-owned Companion.

## 3. Canonical abstractions

| Abstraction | Product problem solved | Permanent role and provider replacement |
|---|---|---|
| `ContextSource` | HAVRE must know which real-world source instance produced evidence | Owner/device-bound registration with stable identity; Google Calendar can be replaced by Apple Calendar without changing life-context meaning |
| `ContextSourceCapability` | A source must not gain broad authority from one permission | Versioned, narrow capability such as read busy intervals, summarize foreground category, or report a user-started voice session |
| `ContextAdapter` | Provider and OS payloads differ | Translates one provider/OS contract into canonical drafts; provider SDK types never enter Companion Core |
| `ContextObservationDraft` | Offline/push/poll sources need one ingest boundary | Retryable adapter output validated by Core before it becomes durable evidence |
| `LifeContextObservation` | Downstream reasoning needs stable semantics | Earliest retained, provider-neutral observation; an Event Store source record, not an interpretation |
| `ConsentScope` | Device permission alone does not express HAVRE's allowed purpose | Owner-approved source, capability, fields/precision, purpose, processing location, destinations, retention, and validity |
| `SamplingPolicy` | “Allowed” must not become continuous collection | Event/user/interval mode, maximum cadence, aggregation window, local preprocessing, and pause conditions |
| `RetentionPolicy` | Raw source material and normalized evidence need different lifetimes | Versioned retention and expiry action for source-local raw material, canonical observations, and derivatives |
| `SignalFreshness` | Old context must not be treated as current | Observation-specific fresh/aging/stale/expired/unknown result under an exact policy version |
| `ContextSourceHealth` | Missing data must remain visible as missing | Source availability, permission, last success, coverage gaps, clock quality, and freshness status |

The existing `USER_SIGNAL` name remains reserved for explicit Stage 5 low-bandwidth Scene simulation. The canonical cross-device term is `LifeContextObservation`; this avoids making every external observation look like a user-entered Scene signal.

`SignalConfidence` is not a canonical field because it would blur measurement quality with interpretation confidence. Observations record `measurement_quality` and limitations. Current State, belief, pattern, Trigger, and proposal artifacts separately record their own versioned confidence/uncertainty when an approved method exists.

### Permanent-abstraction acceptance matrix

Together with the problem/final-role table above, this matrix makes every required design property explicit:

| Abstraction | Raw versus derived / canonical content | Privacy, consent, and provenance | Freshness / unavailable behavior | Verification, first activation, and migration risk avoided |
|---|---|---|---|---|
| `ContextSource` | Registration metadata, not user interpretation | Owner/device binding; no content authority; exact registration event | Disabled/unknown source remains unavailable | Enrollment/revocation/owner-isolation tests; Stage 11/12; avoids provider/device identity leaking into Core IDs |
| `ContextSourceCapability` | Canonical narrow permission surface | Exact allowed observation kinds/fields/precision; referenced by ConsentScope and every observation | Unsupported/revoked capability fails closed | Capability allowlist/conformance tests; Stage 11/12; avoids one broad OS permission silently expanding collection |
| `ContextAdapter` | Derived translation mechanism, never source truth | Adapter version and transform provenance; can only process approved capability fields | Reports degraded/offline/unsupported without fabricating data | Cross-provider golden fixtures and forbidden-field tests; Stage 11/12; avoids provider SDK types and semantics in Core |
| `ContextObservationDraft` | Retryable pre-persistence candidate | Owner/source/capability/consent/policy refs and content fingerprint | Rejected if stale schema, invalid clock, expired consent, or unsupported capability | Duplicate/out-of-order/offline replay tests; synthetic Stage 6 then external Stage 11/12; avoids transport-specific ingest contracts |
| `LifeContextObservation` | Canonical earliest retained evidence; not interpretation | Own DataPolicy, consent/sampling/retention refs, adapter/source receipt, Event/provenance links | Historical when stale; excluded from current claims when expired | Schema/idempotency/provenance/erasure tests; synthetic Stage 6, external Stage 11/12; avoids raw provider payload lock-in and untyped sensor events |
| `ConsentScope` | Governance decision, not observation | Owner-approved purpose, fields/precision, location, destinations, retention, validity, and decision event | Expiry/revocation blocks collection/use; no broader fallback | Grant/narrow/revoke/expiry tests; with first source; avoids treating OS permission as unlimited product consent |
| `SamplingPolicy` | Collection mechanics, not user state | Purpose-bound mode/cadence/window/local preprocessing; referenced by observation | Paused/unsupported sampling creates coverage gaps, not negative evidence | Cadence/window/pause/battery fixtures; with first source; avoids accidental continuous capture and irreproducible summaries |
| `RetentionPolicy` | Lifecycle rule for source-local raw, canonical, and derived data | Owner-approved duration/action, DataPolicy and consent provenance | Expiry triggers governed closure; it is not freshness | Expiry/dry-run/derivative/backup replay tests; before first retained source; avoids “permanent” contradicting deletion and untracked purges |
| `SignalFreshness` | Derived use-time eligibility result under a policy/version | References observation, health, evaluation time, use, and policy; no extra disclosure | Explicit fresh/aging/stale/expired/unknown; unknown fails required use | Boundary/clock/use-specific tests; synthetic Stage 6 then every source; avoids one global TTL and stale-current claims |
| `ContextSourceHealth` | Source availability/coverage evidence, not user evidence | Content-free by default; source/capability/version/trace provenance | Explicit unknown/healthy/degraded/stale/offline/revoked/unsupported | Health-transition/coverage/fault tests; synthetic Stage 6 then every source; avoids converting telemetry absence into user behavior |

Conceptual provider-neutral port:

```python
class ContextAdapter(Protocol):
    async def describe(self) -> ContextSourceDescriptor: ...
    async def capabilities(self) -> tuple[ContextSourceCapability, ...]: ...
    async def health(self) -> ContextSourceHealth: ...
    async def collect(
        self, request: ContextCollectionRequest
    ) -> AsyncIterator[ContextObservationDraft]: ...
```

Push-capable adapters submit the same draft contract instead of using `collect`. In both cases, the Core-side ingest boundary verifies owner/source/device identity, capability, consent revision, schema, idempotency, timestamps, freshness metadata, retention, and DataPolicy before persistence.

## 4. Canonical observation contract

The durable observation is the minimum useful representation HAVRE elects to retain. Device-native records used to compute it may remain transient and local. “Raw” therefore means raw source evidence from HAVRE's durable perspective, not a promise to centralize pixels, audio, keystrokes, or every provider field.

```json
{
  "schema_version": 1,
  "observation_id": "uuidv7",
  "owner_id": "uuidv7",
  "source_instance_id": "uuidv7",
  "source_capability": "windows.device_activity_summary.v1",
  "adapter_version": "windows-context-adapter-v1",
  "observation_kind": "device_activity_summary",
  "occurred_from": "timestamptz",
  "occurred_to": "timestamptz",
  "source_observed_at": "timestamptz",
  "ingested_at": "timestamptz",
  "expires_at": "timestamptz",
  "value": {
    "foreground_category": "game",
    "active_duration_seconds": 2820
  },
  "measurement_quality": {
    "status": "measured",
    "clock_quality": "synchronized",
    "limitations": ["coarse category; no application content"]
  },
  "consent_scope_revision_id": "uuidv7",
  "sampling_policy_version": "event-window-summary-v1",
  "retention_policy_version": "owner-approved-context-retention-v1",
  "data_policy": "effective_DataPolicy",
  "source_receipt_ref": "opaque_optional_local_reference",
  "trace_id": "w3c_trace_id",
  "idempotency_key": "owner-and-source-scoped-key"
}
```

`occurred_from`/`occurred_to` describe the real-world interval. `source_observed_at` is the source's acquisition time. `ingested_at`/the Event envelope's `recorded_at` use the trusted Core clock. `expires_at` limits current-state use; it is not a deletion timestamp. Measurement quality describes the source observation, not the probability of a psychological interpretation.

### Initial bounded observation taxonomy

| `observation_kind` | Canonical meaning | Not implied |
|---|---|---|
| `calendar_commitment` | Authorized time interval, attendance/busy state, and only approved semantic fields | “Upcoming” or important; those depend on evaluation time and goals |
| `device_activity_summary` | Locally aggregated coarse activity category and duration | App content, productivity, procrastination, or intent |
| `device_presence_state` | Active, idle, locked, unlocked, asleep, or other supported device state | User emotion, availability, or behavior away from the device |
| `task_session` | Owner-declared or explicitly integrated task interval and observed checkpoints | Progress from mere screen activity or absence of checkpoints |
| `location_context` | Owner-approved coarse place/category or geofence transition | Exact route, social meaning, or unrestricted location history |
| `mobility_context` | Coarse stationary/walking/transit-style state from an approved capability | Health, mood, destination, or purpose |
| `voice_session` | User-initiated voice interaction metadata and governed transcript/audio references | Ambient microphone permission or continuous listening |
| `sleep_summary` | Approved device/wearable summary with source limitations | Medical truth, fatigue cause, or fitness for intervention |
| `user_declared_state` | What the owner explicitly reported | Independently verified state or durable personality belief |
| `notification_interaction` | Delivery/display/action/dismissal when the channel can actually report it | Attention, agreement, helpfulness, or distress from non-response |
| `wearable_summary` | Purpose-bound, locally minimized measure or interval summary | Continuous raw biometrics, diagnosis, or broad health inference |

New kinds require a registered schema, purpose, precision, consent, retention, privacy, provenance, freshness, missingness behavior, adapter conformance cases, and stage authorization. A provider-specific field does not become canonical merely because an SDK exposes it.

## 5. Observation is not interpretation

```text
LifeContextObservation
  != Current State
  != User Model belief
  != Pattern
  != Memory
  != TriggerRecord
  != permission to contact the owner
```

| Layer | Meaning | Lifecycle |
|---|---|---|
| Observation/Event | What a source reported, with source limitations | Append-preserved by default, subject to retention and owner erasure |
| Current State | Expiring, evidence-backed estimate about now | Must carry estimator version, uncertainty, evidence, source coverage, and expiry |
| User Model belief | Revisable proposition about the owner over a validity interval | Immutable revisions, support/counter-evidence, bitemporal history, explicit lifecycle |
| Pattern | Repeated relationship across distinct evidence and time | Never inferred from one observation; method/version and counter-evidence required |
| Memory | Promoted, recall-worthy derived artifact | Revisioned, provenance-linked, retrieval-gated; not automatic for every event |
| TriggerRecord | Evidence that may justify proposal construction | Can be invalidated; cannot render or deliver |
| ProactiveProposal | Candidate reason to reach out | Must pass Interruption Policy; may end in silence |

A source adapter may normalize `foreground_category = game` and a duration. It may not emit `user_is_procrastinating`. State estimation and pattern/belief updates occur in the Core or learning boundary with exact evidence and uncertainty.

### Full proactive example

```text
Fresh calendar_commitment observation
  -> exam starts in 11 hours (the “11 hours” relation is derived at evaluation time)

Owner-declared task_session
  -> study session planned for tonight

Fresh Windows device_activity_summary
  -> coarse category “game”, active for 47 minutes

Optional explicitly authorized study-tool checkpoint
  -> no new checkpoint within the declared task session

Historical qualified pattern evidence
  -> deadline-related avoidance sometimes occurred before
  -> counter-evidence and validity period remain visible

State estimator
  -> possible task avoidance, illustrative uncalibrated confidence 0.71
  -> limitations: device activity is not intent; progress coverage is partial
  -> expires soon

Trigger evaluator
  -> may create a TriggerRecord if the future approved evidence rule is met

Proposal builder
  -> may create a time-bounded ProactiveProposal supporting the owner-chosen study goal

InterruptionPolicy
  -> DROP, DEFER, REQUEST_OWNER_CONFIRMATION, or SEND_NOW
  -> unresolved permission, stale source, quiet hours, weak evidence, burden, or low benefit means silence/deferment

SEND_NOW only
  -> purpose-bound ContextPack -> constrained rendering -> eligible DeliveryProvider
```

The `0.71` value is illustrative architecture notation, not an approved confidence algorithm or Stage 6 threshold. Windows activity alone cannot prove lack of progress; a progress claim requires an explicit task/tool observation or must remain unknown.

## 6. Source health, freshness, coverage, and missingness

`ContextSourceHealth` is separate from life observations. Its statuses are initially:

```text
unknown | healthy | degraded | stale | offline | permission_revoked | unsupported
```

It records source instance and capability, checked time, last successful observation, last covered interval, expected next observation when meaningful, clock quality, permission state, adapter/source versions, error category, coverage gaps, and a content-free trace reference. High-frequency heartbeats are operational data; only versioned health transitions or policy-required samples become domain events.

Freshness is evaluated per observation kind and use:

```text
fresh | aging | stale | expired | unknown
```

The result includes the policy version and evaluated time. A calendar interval may remain valid longer than a device-presence sample. A stale observation remains historical evidence but cannot be presented as current.

Rules:

- no observation is not a negative observation;
- Windows offline does not mean the owner is inactive;
- a disconnected Calendar does not mean there are no commitments;
- missing location does not mean the owner is at home;
- phone unreachable does not mean deliberate non-response;
- permission revocation stops collection and use under that scope; it cannot silently fall back to a broader source;
- every state estimate and proposal records which expected sources were fresh, stale, unavailable, or not required;
- hard required coverage that is absent yields `insufficient_evidence`, never a fabricated value.

### Disconnected-source example

```text
Windows ContextSourceHealth = offline
last successful coverage ended 2 hours ago
current device_activity_summary = stale
calendar_commitment = fresh

Result:
  preserve the calendar observation as evidence
  exclude stale Windows activity from “current activity” claims
  record partial source coverage
  do not infer inactivity or task progress
  drop/defer any proposal whose justification requires current Windows evidence
```

## 7. Consent, privacy, minimization, retention, and deletion

`ConsentScope` is narrower than an OS permission. It binds:

- owner, source instance, and capability;
- allowed observation kinds and exact fields/precision;
- named product purpose(s);
- user-initiated, event-driven, or bounded interval sampling;
- local preprocessing and permitted destinations;
- DataPolicy defaults and independent memory/training/cloud eligibility;
- retention policy for transient source material, canonical observations, and derived artifacts;
- effective/expiry time and revocation history.

Collection is denied when consent, capability, owner/device binding, schema, or policy is unresolved. Revocation stops new collection and future use under that scope. Whether revocation also requests historical erasure is an explicit owner choice; selected deletion or retention expiry follows the same provenance closure and backup replay requirements as other source erasure.

Preferred order:

```text
user-declared or event-driven signal
  -> coarse category / local aggregate
  -> purpose-bound normalized observation
  -> only then consider higher precision if measured benefit and owner approval justify it
```

Forbidden default strategy:

```text
constant screenshots
continuous microphone recording
keystroke or clipboard logging
unrestricted window/document/browser contents
raw high-rate location or biometric streams
collect-everything-now-decide-later storage
```

Source-local raw material should be discarded immediately after successful normalization unless an owner-approved purpose and retention rule requires otherwise. The normalized summary receives its own DataPolicy and provenance, but transformation never makes it less restrictive than required source constraints. On-device processing is not declassification.

“Append-preserved by default” means normal writes do not overwrite history. It does not override owner-controlled erasure or a pre-approved retention expiry. When a retained source is deleted or expires, contaminated derivatives are removed or invalidated through provenance; regeneration may use only remaining eligible evidence and creates new versioned artifacts.

## 8. Windows agent boundary

The future Windows agent is a `ContextSource` host and adapter execution environment, not a second Companion Core. It owns Windows API integration, source-local minimization, encrypted bounded offline buffering, health reporting, and translation into canonical drafts. It does not own Identity, Memory, User Model, Trigger policy, Interruption Policy, rendering, or delivery.

Communication path:

```text
Windows OS APIs / explicit tool integrations
  -> Windows agent local categorization and time-window aggregation
  -> signed owner/device/source-bound ContextObservationDraft
  -> local IPC or mutually authenticated HTTPS ingest transport
  -> Core validation and canonical Event persistence
```

The transport is replaceable. Each retry uses a stable idempotency key. The Core rejects an unknown device/source, capability outside consent, policy downgrade, stale schema, invalid clock metadata, or payload outside the registered taxonomy.

### Default information the Windows agent may eventually collect

Only after Stage 12 authorization and per-capability consent:

- coarse foreground application category, not content;
- active/idle duration in bounded summary windows;
- lock/unlock and supported device-presence state;
- owner-declared task-session start, pause, resume, and end;
- task-session continuity;
- coarse activity summaries;
- explicitly enabled study/development-tool checkpoints through separate scoped integrations;
- adapter permission, health, coverage, clock, and freshness metadata.

### Information it does not collect by default

- screenshots, screen pixels, OCR, or screen recordings;
- window titles, document contents, URLs, browser history, messages, or source code;
- keystrokes, mouse content, clipboard, passwords, or credentials;
- raw microphone/audio or ambient listening;
- unrestricted process, filesystem, network, or application telemetry;
- exact application identity when a coarse category is sufficient;
- psychological labels such as “procrastinating”, “lazy”, or “depressed”;
- any signal outside the current consent capability because it is technically accessible.

An exact app/tool integration is a separate capability and consent revision, not an invisible expansion of the default agent.

## 9. iPhone and voice boundary

The iPhone app is one client, delivery adapter, and possible set of ContextSource capabilities. It is not HAVRE's identity, memory authority, policy authority, or primary Core.

The design assumes mobile OS constraints:

- no arbitrary continuously running background process;
- no inspection of unrelated applications;
- background work, notifications, location, motion, health/wearable access, microphone, and speech services depend on OS-supported APIs, entitlements, permissions, scheduling, and power constraints;
- delivery-provider receipts do not automatically prove display or attention;
- offline events require bounded encrypted storage, idempotent replay, and separate occurrence/recording times.

Text and a user-initiated voice session enter the ordinary Companion interaction path. Raw audio, transcription, and synthesis are separate artifacts/providers with independent consent, retention, DataPolicy, and provenance. This proposal does not assume a background wake word or ambient microphone. Any future on-device wake or edge inference path requires explicit privacy, battery, OS-feasibility, and Product Owner approval.

## 10. One abstraction across providers and devices

| Source | Adapter responsibility | Canonical observation examples | Default minimization |
|---|---|---|---|
| Windows | OS integration and local aggregation | `device_activity_summary`, `device_presence_state`, `task_session` | Coarse category/duration; no screen or content capture |
| iPhone | OS-supported client/context APIs and offline reconciliation | `voice_session`, `device_presence_state`, optionally location/mobility | User-initiated or OS-event-driven; no unrelated-app inspection |
| Calendar provider | Provider auth, incremental sync, provider field mapping | `calendar_commitment` | Time/busy/category first; title/details only if required and consented |
| Location provider | Local geofence/place classification | `location_context`, `mobility_context` | Coarse named category or transition; exact coordinates off by default |
| Voice provider/device | Capture/transcription/synthesis adapter | `voice_session` plus ordinary message Events | User initiated; raw audio short-lived or unretained by policy |
| Wearable | Device/health API mapping and local summarization | `sleep_summary`, `wearable_summary` | Purpose-bound interval summary; no unrestricted raw stream |

Provider replacement changes source descriptors and adapter versions, not observation meaning, provenance, privacy, state, memory, trigger, or interruption contracts.

## 11. Experience and memory lifecycle

An experience is what HAVRE durably observed or communicated. A memory is a promoted derived artifact judged useful for future recall. Every conversation may contain experiences; most lines should not become long-term memory.

```text
Event / LifeContextObservation
  -> optional MemoryCandidate
  -> evidence and policy validation
  -> class-specific promotion or owner review
  -> immutable MemoryRevision
  -> retrieval eligibility
  -> later revision / consolidation / supersession / retraction / archival
```

### Lifecycle semantics

- **Promotion:** `memory_eligible = true` permits consideration; it does not require creation. Promotion uses a versioned policy and preserves rejected/duplicate decisions as governed metadata.
- **Episodic memory:** a meaningful bounded episode with exact source events and time. It is not every message.
- **Semantic memory:** a recall-worthy summary or fact supported by evidence; a user-model claim still uses the temporal belief contract when it asserts something about the owner.
- **Pattern/progress memory:** a retrievable derived artifact supported by distinct evidence over time. It cannot be promoted from one transient observation.
- **Consolidation:** creates a proposal or new revision from exact sources. It never overwrites those sources or self-approves high-impact understanding.
- **Contradiction and supersession:** old revisions remain historical while current retrieval/state projections prefer the applicable revision and retain counter-evidence.
- **Historical versus current validity:** what was once a valid description can remain true of 2026 while no longer being current in 2028.
- **Decay:** may reduce retrieval relevance under a versioned policy; it never silently lowers truth confidence, changes validity, or deletes evidence.
- **Archival:** removes an item from ordinary hot retrieval while preserving governed history. It is not deletion.
- **Reconsolidation:** new evidence creates a new revision/proposal linked to the old memory and new sources. Retrieval alone does not rewrite a memory.
- **Regeneration:** a new transform may rebuild derivatives from eligible sources with a new version/hash. Old derivatives remain historical unless erasure/retention requires removal.
- **Erasure/retention propagation:** deleted or expired source content cannot survive inside summaries, embeddings, caches, datasets, previews, or other derivatives. Rebuilding from remaining evidence creates a new artifact.
- **Shared-history memory:** relationship continuity is represented through ordinary episodic/semantic records with explicit participants, source events, and temporal validity; it is not a provider-owned transcript or an automatically immortal memory class.

Example of temporal change:

```text
2026 belief revision:
  “The owner often avoids social events.”
  valid for the supported 2026 interval, with evidence and counter-evidence

2028 evidence:
  frequent attendance and reported enjoyment

2028 result:
  append counter-evidence
  create a revised/successor belief with a new validity interval
  supersede the old revision for current use
  preserve the 2026 history without presenting it as current truth
```

### “今天天气蛮好的” example

```text
Owner says: “今天天气蛮好的。”
  -> durable USER_MESSAGE Event (an experience)
  -> normally no long-term MemoryRevision; memory eligibility is not promotion

Later authorized evidence:
  -> the owner reports going outside
  -> the owner reports improved mood
  -> exact events may support an Episodic Memory proposal about that day

Repeated evidence across months:
  -> versioned consolidation may propose a qualified semantic memory or belief:
     “Pleasant weather appears associated with greater willingness to go outside.”
  -> carries confidence method, supporting evidence, counter-evidence,
     temporal validity, limitations, last-supported time, and provenance
  -> remains revisable and may later be contradicted or superseded
```

## 12. Verification contract

When each capability reaches its authorized stage, evidence must include:

- adapter conformance across at least two interchangeable fixture providers for the same observation kind;
- strict schema, owner/device/source, capability, consent, idempotency, and timestamp validation;
- local-minimization assertions proving forbidden raw fields do not cross the ingest boundary;
- DataPolicy non-relaxation, `LOCAL_ONLY` denial, and independent memory/training/cloud eligibility;
- consent expiry/revocation and source disablement with no unauthorized fallback;
- freshness/health/coverage tests proving missing data is not negative evidence;
- out-of-order, duplicate, offline replay, clock-skew, stale, and invalidation cases;
- exact provenance from observation through state, memory/belief, trigger, proposal, decision, rendering, and delivery when those stages exist;
- tests proving a source/adapter/model/delivery provider cannot authorize outreach;
- retention expiry and owner-erasure closure through embeddings, caches, datasets, previews, and backups;
- source replacement without changes to Core semantics;
- privacy/usefulness evaluation that compares a minimized signal with any proposed higher-precision alternative before collecting more.

No benchmark may call increased collection a benefit by itself. Relevant measures are useful evidence coverage, ambiguity/error, freshness, latency, energy, storage, privacy exposure, and downstream decision quality under an approved labeled suite.

## 13. Staged activation

| Stage | Ambient Context / memory lifecycle scope |
|---|---|
| Architecture amendment now | Documents and proposed ADRs only; no code, schemas, adapters, workers, or sensors |
| Stage 6, only if separately authorized | Synthetic/manual `LifeContextObservation` fixtures may exercise Trigger/Proposal/Interruption contracts; no external device/provider connector |
| Stage 7 | Activate broader reflection/consolidation, memory promotion, contradiction, archival/reconsolidation proposals, and derived regeneration semantics using already authorized Events |
| Stage 8 | Unify source-health/freshness/missingness and memory-lifecycle evaluation with proactive and longitudinal reports |
| Stage 10 | Establish deployment authentication, device enrollment, encrypted transport/buffering, backup, export, and erasure prerequisites; still no source permission by implication |
| Stage 11 | iPhone interface, user-initiated voice, push, and individually approved OS-supported context capabilities behind the same contracts |
| Stage 12A | First external adapters: Windows coarse context and Calendar, one capability at a time with consent and minimization evidence |
| Stage 12B | Location, mobility, wearables, richer context, and Edge Brain capabilities one at a time after separate benefit/privacy review |

This keeps the existing stage numbers and dependency philosophy. Defining an interface now does not pull any device integration into Stage 6.

## 14. Unresolved Product Owner decisions

Approval of the architecture still leaves activation decisions unresolved:

1. whether Ambient Life Context is globally disabled by default and how onboarding/renewal works;
2. which source capabilities and observation kinds are allowed first;
3. Windows exact-app visibility versus coarse category-only behavior;
4. location precision and whether exact coordinates are ever retained;
5. voice providers, user initiation/wake behavior, raw-audio/transcript retention, and offline handling;
6. iPhone background, location, motion, Health/wearable, and notification permissions per capability;
7. sampling windows/cadence, local aggregation, offline-buffer limits, and battery/network budgets;
8. retention durations and expiry actions for each source-local raw class and canonical observation kind;
9. freshness thresholds, health sampling, required-coverage rules, and clock-skew tolerance;
10. approved adapter/device authentication, enrollment, revocation, and lost-device behavior;
11. whether third-party Calendar/location/voice/wearable processors are eligible for each privacy class;
12. memory-promotion automation versus owner review by class and impact;
13. relevance decay, archival, reconsolidation, and relationship-memory review policies;
14. state-estimator, pattern, and confidence methods and their activation evidence;
15. which context-derived proposal categories may exist and whether any may reach `SEND_NOW` without case-by-case confirmation;
16. “Why did you infer/contact me?” evidence detail and protected-source access UX;
17. whether consent revocation also initiates historical deletion by default;
18. source deletion receipts, backups, external-processor deletion, and restore-time replay.

Until their named stage and explicit approval, conservative behavior is no collection and no context-derived outreach.

## 15. Product Owner review gate

Before approving this amendment, understand that:

- provider-neutral context semantics are accepted as permanent only if ADR-0019 is accepted;
- experience-to-memory lifecycle semantics are accepted as permanent by ADR-0020;
- the canonical observation is minimized durable evidence, not a centralized copy of every device-native record;
- observations remain distinct from state, beliefs, patterns, memories, triggers, and authorization;
- source health and missingness prevent absence from being treated as evidence;
- local transformation never weakens privacy;
- Windows and iPhone remain replaceable sources/interfaces, not Companion Cores;
- accepting this design authorized only the separately stated Stage 6 synthetic/manual local-simulation slice; it does not authorize any sensor, external adapter, real proactive delivery, private-data export, or new data collection.

After review, the Product Owner may accept, reject, or request revision of the two proposed ADRs and this document. Runtime work still requires the separate Roadmap-stage authorization.
