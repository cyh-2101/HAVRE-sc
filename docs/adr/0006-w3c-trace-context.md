# ADR-0006: W3C-style trace context with linked deferred work

- Status: Accepted
- Accepted: 2026-08-13 by Product Owner
- Date: 2026-08-12
- Decision owners: Product Owner/System Architect
- Supersedes: None
- Superseded by: None

## Context and real problem

One interaction crosses API orchestration, database work, retrieval, policy, context building, routing, external/self-hosted inference, delivery, and later workers. HAVRE must explain latency/failure/component versions without binding to MLflow or another vendor, and without copying private text into telemetry.

## Decision

Use W3C-compatible 128-bit trace IDs and trace propagation for synchronous calls. Store trace IDs on events and important artifacts. Deferred jobs record origin context; long-delayed reflection/consolidation starts a new trace with links to origin traces. Keep attributes low-cardinality and content-free by default.

## Why it belongs in the final system

Request-level observability and causal diagnosis remain necessary across every provider, serving engine, worker, deployment, and client.

## Simplest viable current implementation

Stage 1 generates/validates `traceparent`, creates named spans, propagates headers, persists trace IDs, and exports through an optional vendor-neutral instrumentation adapter. Logs correlate by trace ID without raw message content.

## Alternatives considered

- **UUID request ID only:** useful correlation but lacks parent/child spans and standard propagation.
- **One multi-day trace for all derived work:** preserves one ID but creates impractical traces and misleading latency.
- **MLflow-native or vendor-native trace schema as domain contract:** expedient but creates observability lock-in.
- **Store full prompts in every span:** easy debugging but unnecessary sensitive duplication.

## Consequences

### Benefits

- Standard propagation and future exporter choice.
- Component latency/failure attribution.
- Trace and epistemic provenance remain clearly distinct.

### Costs and constraints

- Async causality requires links and explicit UI support.
- Sampling/export can make external trace views incomplete.
- Privacy-safe diagnostics require referenced protected artifacts for rare deep debugging.

## Failure modes and future migration risks

Untrusted incoming trace IDs could spoof correlation; ingress must validate/trust selectively. High-cardinality attributes can overwhelm a backend. Export failure cannot block domain persistence. Preserve the internal contract if MLflow or another backend is added.

## Validation

- End-to-end trace continuity tests.
- Background job link tests.
- Telemetry privacy scan.
- Exporter outage/degraded-mode test.

## Approval note

Accepted by the Product Owner on 2026-08-13.
