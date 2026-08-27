# ADR-0018: Provider-neutral delivery with privacy-safe notification previews

- Status: Accepted
- Accepted: 2026-08-13 by Product Owner
- Date: 2026-08-13
- Decision owners: Product Owner/System Architect
- Supersedes: None
- Superseded by: None

## Context and real problem

Proactive delivery will span Web inbox, live Web messages, native push, lock-screen actions, wearables, audio, and possibly future email. Binding the Core to iOS or a notification vendor would mix product authorization with transport and could expose sensitive context in previews, logs, or third-party processors.

## Decision

Define a provider-neutral `DeliveryProvider` port and canonical request/result/attempt contracts. Delivery occurs only for an authorized, rendered proposal. Attempts use owner-scoped idempotency, safe retry, expiration/cancellation checks, typed failures, exact adapter versions, and trace/provenance links.

Channels have explicit privacy eligibility and versioned preview policies: full content, generic private preview, no preview, or owner-configured preview. A preview/redaction is a separately classified derived artifact with provenance, omitted/transformed-source records, and a new eligibility decision. It cannot silently bypass `LOCAL_ONLY`, `cloud_eligible = false`, or owner declassification authority.

## Why it belongs in the final system

One delivery boundary lets HAVRE add native clients and devices without rewriting Core authorization or conversation history. Privacy rules follow the information rather than a vendor SDK.

## Simplest viable activation

Stage 6 uses one Web/inbox adapter with deterministic delivery confirmation and reconciliation. Stage 11 adds native push/lock-screen adapters behind the same port. Stage 12 may add wearable/audio channels only after scoped consent and measurement.

## Alternatives considered

- **Direct APNs/iOS calls from Core:** makes one client and vendor part of domain policy.
- **Reuse ModelProvider as notification delivery:** generation and transport have different capabilities, failures, privacy, and idempotency.
- **Store only final notifications:** loses failed attempts, retries, cancellation, and exact delivery evidence.
- **Redact and assume public:** violates source privacy inheritance and owner authority.

## Consequences

### Benefits

- Channel adapters are replaceable and conformance-testable.
- Core policy remains independent of iOS and delivery vendors.
- Sensitive lock-screen exposure becomes explicit and testable.
- Duplicate delivery and retry behavior are auditable.

### Costs and constraints

- Channel receipts and “visible” semantics vary and need normalized definitions.
- Preview artifacts add policy/provenance work.
- External notification services may be ineligible for some data, requiring generic/no preview or no delivery.

## Failure modes and migration risks

Provider receipts can be mistaken for user visibility; contracts must distinguish accepted, delivered when knowable, displayed when knowable, and unknown. Retry races can duplicate messages; idempotency and reconciliation are mandatory. Channel metadata/logs must not carry private content.

## Relationship to accepted decisions

This applies ADR-0003, ADR-0004, ADR-0006, ADR-0008, and ADR-0011 to a new delivery port. It does not weaken event, trace, provenance, job, or DataPolicy semantics.

## Validation

- Shared delivery-adapter conformance suite.
- Duplicate attempt/retry/reconciliation and cancellation/expiration tests.
- A failed delivery creates no delivered `ASSISTANT_MESSAGE`.
- Preview inheritance/redaction tests, including hard `LOCAL_ONLY` denial.
- Telemetry scan proving message and preview contents are absent by default.
- Response linkage resolves proposal through delivered event and exact attempt.

## Unresolved owner decisions

Initial channels, preview defaults, third-party processor eligibility, delivery/read semantics, retry limits, retention/erasure behavior, and whether email is ever allowed remain unresolved.

## Acceptance scope

Accepted by the Product Owner on 2026-08-13. Acceptance establishes the future architectural boundary; it does not activate delivery providers or proactive implementation in Stage 2.
