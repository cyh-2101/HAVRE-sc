# ADR-0010: Evaluation-gated immutable release manifests

- Status: Accepted
- Accepted: 2026-08-13 by Product Owner
- Date: 2026-08-12
- Decision owners: Product Owner/System Architect
- Supersedes: None
- Superseded by: None

## Context and real problem

HAVRE behavior depends on more than a model: identity, policy, context, retrieval, router, adapter, database schema, and serving configuration all matter. Informal conversations cannot reliably detect regressions, and changing floating components makes rollback/reproduction impossible.

## Decision

Represent each candidate/production release as an immutable manifest pinning every behaviorally relevant version. Require contract, behavioral, safety/privacy, retrieval/context, systems, and available outcome evidence appropriate to the changed components. Language quality, systems performance, and real-world guidance outcomes remain separate evidence classes. Material Constitution, identity, safety policy, personalized model/adapter, or data-scope promotion requires explicit human approval. Deployment promotes or rolls back whole manifests.

## Why it belongs in the final system

Continual personalization and model replacement are safe only when changes are measured, attributable, reversible, and unable to silently rewrite the Companion.

## Simplest viable current implementation

Stage 1 records version manifests and runs contract/smoke suites manually. Later stages automate component suites and reporting. Stage 8 unifies evidence and gates; Stage 9 uses them for adapters; Stage 10 deploys/rolls back manifests.

## Alternatives considered

- **Chat with candidate and decide by feel:** useful exploration but not reproducible or broad enough for regression safety.
- **Model-only registry:** ignores retrieval/policy/prompt/schema changes that alter behavior.
- **One aggregate quality score:** hides critical safety/privacy regressions and trade-offs.
- **Fully automatic promotion:** premature for a personal system with value-laden behavior and fallible judges.

## Consequences

### Benefits

- Reproducible comparison and rollback.
- Failed experiments remain evidence rather than production incidents.
- Quality/latency/cost/privacy trade-offs are explicit.

### Costs and constraints

- Suite maintenance and human review take time.
- Model judges require calibration and can bias results.
- Thresholds may become stale or overfit.

## Failure modes and future migration risks

Small suites can be gamed; holdouts, leakage tracking, novel failure cases, and periodic review are required. Inconclusive measurements must not be presented as passes. The gate system may later move to MLflow or another platform, but manifest and evidence contracts remain vendor-neutral.

## Validation

- Manifest completeness/hash tests.
- Fixed-suite reproducibility and judge calibration.
- Critical-gate failure blocks promotion.
- Rollback drill to the previous immutable manifest.
- Human approval audit for material changes.
- Outcome reports preserve denominators, missingness, regret/forcefulness evidence, and uncertainty instead of substituting language scores.

## Approval note

Accepted as an architectural baseline by the Product Owner on 2026-08-13. Exact later-stage quantitative gates remain intentionally unresolved until evidence exists.
