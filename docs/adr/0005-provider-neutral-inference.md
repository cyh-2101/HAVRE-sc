# ADR-0005: Provider-neutral inference contract

- Status: Accepted
- Accepted: 2026-08-13 by Product Owner
- Date: 2026-08-12
- Decision owners: Product Owner/System Architect
- Supersedes: None
- Superseded by: None

## Context and real problem

HAVRE may use a cloud model first, a self-hosted Personal Brain later, a Teacher Brain, and an Edge Brain. Direct provider SDK calls in domain logic would bind identity, context, errors, tracing, and routing to one model/vendor.

## Decision

Companion Core depends on canonical inference request/response/stream/capability/failure contracts and a Model Provider port. Adapters translate those contracts to provider SDKs or OpenAI-compatible HTTP. Context construction, identity, and DataPolicy remain outside adapters. A cloud adapter must reject non-cloud-eligible requests; no adapter may weaken privacy policy.

## Why it belongs in the final system

Replaceable brains are a non-negotiable product principle. The same boundary also enables controlled model, quantization, serving, routing, and fallback experiments.

## Simplest viable current implementation

Stage 1 implements one real adapter and one deterministic fake against Pydantic contracts. Stage 3 connects the same port to self-hosted serving. Unsupported features fail visibly through capability checks.

## Alternatives considered

- **Direct cloud SDK in application services:** fastest first call, but provider types and behavior leak everywhere.
- **Use OpenAI API schema as the domain contract:** broad ecosystem support, but vendor/serving semantics would become HAVRE's internal meaning.
- **Lowest-common-denominator text-only interface:** portable but blocks structured output, tools, modalities, constraints, and precise metrics.

## Consequences

### Benefits

- Provider/model replacement by configuration and adapter.
- Uniform tracing, errors, privacy constraints, streaming, and benchmark capture.
- Router can compare eligible brains.

### Costs and constraints

- Adapter normalization is non-trivial.
- Provider-specific features require explicit capability extensions.
- A leaky abstraction is possible if arbitrary provider options enter generic metadata.

## Failure modes and future migration risks

Avoid silently dropping unsupported parameters or hiding provider errors. Keep an escape hatch as namespaced adapter options only for experiments, never core product behavior. Version contracts and use conformance tests before adapter upgrades.

## Validation

- Shared provider conformance suite.
- Swap/fallback tests without domain-code changes.
- Stream reconciliation and typed failure tests.
- Privacy/capability constraints retained across translation.

## Approval note

Accepted by the Product Owner on 2026-08-13.
