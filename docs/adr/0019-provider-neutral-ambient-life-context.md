# ADR-0019: Provider-neutral Ambient Life Context with local minimization

- Status: Accepted
- Date: 2026-08-17
- Accepted: 2026-08-19 by Product Owner
- Decision owners: Product Owner/System Architect
- Supersedes: None
- Superseded by: None

## Context and real problem

HAVRE cannot become a useful ambient companion using conversation history alone. It eventually needs authorized evidence from Calendar, Windows, iPhone, voice, location, wearables, manual input, and future sources. Direct provider payloads would bind life understanding to vendors and devices. Centralizing unrestricted raw capture would create surveillance, privacy, retention, and migration risk. Allowing sources to trigger delivery would bypass accepted proactive governance.

## Decision

Add a permanent **Ambient Life Context** layer upstream of the Event Store. Define provider-neutral `ContextSource`, `ContextSourceCapability`, `ContextAdapter`, `ContextObservationDraft`, `LifeContextObservation`, `ConsentScope`, `SamplingPolicy`, `RetentionPolicy`, `SignalFreshness`, and `ContextSourceHealth` contracts.

Source adapters translate provider/OS data into a bounded canonical observation taxonomy. They preprocess locally and transmit the minimum useful representation. The Core ingest boundary validates owner/device/source identity, capability, consent, schema, idempotency, time, freshness metadata, retention, and DataPolicy before committing an append-oriented observation event.

The canonical observation is source evidence, not an interpretation. Adapters cannot emit user-model conclusions, authorize outreach, render messages, or call delivery. The governed path remains:

```text
LifeContextObservation
-> Current State / temporal interpretation
-> Trigger evaluation
-> TriggerRecord
-> ProactiveProposal
-> InterruptionPolicy
-> governed rendering and delivery, or silence
```

Missing/stale/offline/revoked sources remain explicit. Absence of a signal is never negative evidence unless an approved source contract establishes complete coverage for that exact claim.

Every observation and derived artifact resolves provider-independent DataPolicy, consent, retention, and exact provenance. Local aggregation or redaction never lowers source restrictions without explicit owner-approved declassification. Constant screenshots, continuous microphone capture, keystroke/clipboard logging, unrestricted app contents, and collect-everything-first storage are forbidden defaults.

## Why it belongs in the final system

Ambient context is how HAVRE can understand relevant real-life timing and conditions across changing providers and devices. Provider-neutral semantics preserve continuity when a Calendar, phone, wearable, OS, or adapter changes. Consent, minimization, health, freshness, and provenance remain necessary for the lifetime of a deeply personal system.

## Simplest viable current implementation

Stage 6 activates only synthetic/manual canonical fixtures to exercise downstream governance. External sources remain inactive until their later Product Owner gates. The first Stage 12 external capabilities may be one coarse Windows context adapter and one Calendar adapter, but each still requires separate consent, evaluation, and Product Owner authorization. No external service or source worker is introduced by this decision.

## Alternatives considered

- **Direct Calendar/Windows/iOS payloads in Companion Core:** quick per integration, but provider fields become permanent domain meaning.
- **Central raw sensor lake:** maximizes future optionality at the cost of surveillance, breach surface, deletion complexity, and unclear purpose.
- **One untyped external-context JSON event:** flexible, but cannot enforce consent, freshness, missingness, privacy, provider replacement, or conformance.
- **Let context sources create notifications:** confuses evidence with permission and violates ADR-0016/0017.
- **Separate context microservices now:** adds operations and distributed consistency before any authorized workload exists.

## Consequences

### Benefits

- Calendar, Windows, iPhone, voice, location, and wearables share one durable semantic boundary.
- Higher-precision collection must justify itself against a minimized baseline.
- Source failure and missingness become explicit inputs rather than silent inference errors.
- Device/provider replacement does not rewrite Event, State, User Model, Memory, or proactive contracts.
- Core authorization remains independent from collection and delivery.

### Costs and constraints

- Each capability needs schema, adapter conformance, consent, retention, health, freshness, privacy, and deletion behavior.
- Local aggregation can discard detail that a later use might have wanted; that is an intentional privacy trade-off, not a defect.
- Offline devices and provider clocks require reconciliation and uncertainty metadata.
- Mobile OS limitations constrain availability and must remain visible.

## Failure modes and future migration risks

Adapters may smuggle provider-specific or sensitive fields into generic payloads, consent can drift broader, source health can be mistaken for user state, and stale observations can outlive their valid use. Enforce strict registered schemas and field allowlists, exact adapter/capability/consent versions, source-local privacy tests, freshness gates, coverage-aware estimation, and provenance/erasure audits.

If throughput later requires a broker or separate ingest process, preserve canonical drafts, owner/source idempotency, and PostgreSQL authority; publish from the accepted outbox boundary rather than dual-writing. If a higher-precision signal is proposed, compare measured downstream benefit, privacy exposure, retention, energy, and failure behavior before approval.

## Relationship to accepted decisions

This extends ADR-0001, ADR-0003, ADR-0004, ADR-0006, ADR-0008, ADR-0011, ADR-0012, ADR-0013, and ADR-0016 through ADR-0018. It supersedes none of them. `EXTERNAL_CONTEXT_OBSERVED` was an unimplemented placeholder in the Event Model; if this ADR is accepted, the typed Ambient Life Context family replaces that future placeholder before activation.

## Validation

- Shared adapter conformance fixtures across replaceable providers.
- Owner/device/source, capability, consent, schema, idempotency, timestamp, clock, and policy tests.
- Field-allowlist tests proving default Windows/iPhone/Calendar adapters do not transmit forbidden raw content.
- Health/freshness/coverage fixtures proving missing data is not negative evidence.
- Offline, duplicate, out-of-order, stale, invalidated, revoked, and unsupported cases.
- DataPolicy non-relaxation, `LOCAL_ONLY`, retention expiry, and source-erasure closure tests.
- Provenance from observation through every derived artifact and proactive decision.
- Dependency tests proving adapters/sources cannot authorize, render, schedule, or deliver outreach.

## Unresolved owner decisions

Initial sources/capabilities, global default, precision, sampling, retention, device enrollment, third-party processor eligibility, voice/audio policy, location policy, health/freshness thresholds, and context-derived proactive permissions remain Product Owner decisions at their activation stages.

## Approval note

Accepted by the Product Owner on 2026-08-19. The same decision authorized the conservative Stage 6 local-simulation configuration: global outreach remains disabled by default, preview is `none` by default, `SEND_NOW` requires an explicit owner preference, and unresolved controls fail closed. Acceptance does not authorize external context collection, device agents, real proactive contact, private-data export, or any governance-policy change.
