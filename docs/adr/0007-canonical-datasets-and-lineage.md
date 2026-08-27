# ADR-0007: Model-independent canonical datasets and immutable lineage

- Status: Accepted
- Accepted: 2026-08-13 by Product Owner
- Date: 2026-08-12
- Decision owners: Product Owner/System Architect
- Supersedes: None
- Superseded by: None

## Context and real problem

LoRA artifacts and tokenized chat templates bind to a base model and framework. HAVRE's long-term history must remain reusable when models, tokenizers, templates, and training stacks change. Training also needs privacy deletion, holdout separation, and reproducibility.

## Decision

Store canonical training examples using semantic roles, structured situation/state/goal, assistant behavior, feedback, action, outcome, review state, exact provenance, and effective DataPolicy. Dataset construction requires explicit `training_eligible = true` for every required source; memory or cloud eligibility is insufficient. Finalize immutable dataset snapshots with selection/filter/dedup/split/privacy policies and member hashes. Render/tokenize into model-specific build artifacts separately.

## Why it belongs in the final system

Canonical experience and feedback are the durable personalization asset; any adapter is replaceable. Immutable lineage is required for comparison, regression gates, erasure, and future base-model migration.

## Simplest viable current implementation

Stage 0 defines schemas. Stage 7 implements JSON-compatible records and database snapshot manifests. A simple exporter/renderer produces framework-specific artifacts with its own version/hash. Evaluation holdouts are excluded by policy.

## Alternatives considered

- **Store only tokenized training files:** easy training but loses semantic meaning and base-model portability.
- **Generate a fresh unversioned dataset each run:** flexible but irreproducible.
- **Store only raw conversations:** preserves truth but omits review, outcome, intervention, and training intent.
- **Lock a training framework in Stage 0:** premature when no data/hardware experiment justifies it.

## Consequences

### Benefits

- Re-render for new base models/frameworks.
- Clear source, review, split, and deletion lineage.
- Fair Base/Memory/Adapter comparisons.

### Costs and constraints

- Canonical schema evolution needs migrations/upcasters.
- Private examples and artifacts require strong access controls.
- Snapshot revocation after erasure can invalidate downstream adapters/releases.

## Failure modes and future migration risks

The schema can become either too generic or too tied to current policy. Version it, retain raw source links, and allow typed extensions. Track evaluation leakage. When an erased source affected a dataset, revoke rather than silently rewrite the snapshot.

## Validation

- Snapshot membership/hash reproducibility.
- Holdout exclusion and leakage checks.
- Model-specific renderer round-trip/golden tests.
- Provenance and erasure revocation traversal.

## Approval note

Accepted by the Product Owner on 2026-08-13.
