# ADR-0014: Governed Constitution-to-personalization hierarchy

- Status: Accepted
- Accepted: 2026-08-13 by Product Owner
- Date: 2026-08-13
- Decision owners: Product Owner/System Architect
- Supersedes: None
- Superseded by: None

## Context and real problem

HAVRE will learn what language and interventions appear helpful and may later train personalized adapters. Without an authority hierarchy, frequent preferences or model behavior could gradually override core values, safety boundaries, epistemic humility, or the mission to increase real-world agency.

## Decision

Use this descending authority order:

```text
Constitution / Core Principles
-> Identity and Values
-> Intervention Policy
-> Learned Preferences
-> Personalized model behavior / adapters
```

Lower layers must comply with higher layers and cannot activate changes to them. They may create versioned proposals with evidence. Material Constitution, identity/value, safety/intervention-policy, and personalized-release changes require an explicit human `ApprovalRecord` tied to exact artifact versions/hashes. The learning pipeline can never rewrite or approve the Constitution.

## Why it belongs in the final system

Persistent identity requires governance, not only storage. This hierarchy protects HAVRE from personality drift, sycophantic preference learning, unsafe policy adaptation, and an adapter becoming the de facto source of values.

## Simplest viable current implementation

Stage 1 loads a human-approved Constitution and Identity/Values package into the Context Pack, records exact parent versions, and blocks activation without approval records. Intervention policies, learned preferences, and adapters are not yet active but their version metadata reserves parent references.

## Alternatives considered

- **One merged system prompt:** easy to render but hides authority and change ownership.
- **Let feedback update all behavior:** responsive but permits local preferences to erode principles.
- **Put identity in LoRA weights:** difficult to inspect, approve, or migrate.
- **Fully formal policy language now:** stronger enforcement but premature before the policies and scenarios are exercised.

## Consequences

### Benefits

- Human ownership of mission, identity, safety, and releases.
- Learned personalization remains useful without gaining constitutional authority.
- Changes and conflicts are attributable and reviewable.

### Costs and constraints

- Version/approval references must propagate into Context Packs and releases.
- Conflicts require explicit resolution rather than automatic blending.
- “Material change” needs an approved definition and review process.

## Failure modes and future migration risks

Duplicated prompt text can drift from canonical layers. Build rendered prompts from pinned packages and test hashes. A model may still violate higher layers; evaluation and structured policy remain necessary. If a future policy engine formalizes constraints, preserve layer authority and human approval semantics.

## Validation

- Dependency/version tests enforce parent references.
- Workers, teacher models, adapters, and training jobs cannot write effective higher-layer versions.
- Material activation without a matching human ApprovalRecord fails.
- Behavioral regression suites check higher-layer invariants across providers/adapters.
- Release manifests show all governing versions and approvals.

## Approval note

Accepted by the Product Owner on 2026-08-13 together with the listed material-change approval boundaries. Quantitative policy details and future workflow UX remain stage-gated.
