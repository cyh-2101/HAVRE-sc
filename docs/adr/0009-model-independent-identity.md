# ADR-0009: Companion identity remains outside model weights

- Status: Accepted
- Accepted: 2026-08-13 by Product Owner
- Date: 2026-08-12
- Decision owners: Product Owner/System Architect
- Supersedes: None
- Superseded by: None

## Context and real problem

A base model, prompt, or LoRA can change personality and behavior. If HAVRE's mission and values exist only implicitly in model behavior, replacing or retraining the brain can erase or distort identity.

## Decision

Maintain a human-approved Constitution/Core Principles package above canonical identity. Maintain mission, personality, values, boundaries, and communication style as human-reviewable, version-controlled identity content with immutable deployed identity versions. Prompts, policies, learned preferences, models, and adapters consume these higher layers; none is their authority. Material changes require an explicit human approval record.

## Why it belongs in the final system

“Model is replaceable; identity is persistent” is central to HAVRE. Identity must survive cloud/self-hosted/edge models and personalization cycles.

## Simplest viable current implementation

Stage 1 creates the five identity files, hashes/version metadata, a loader, and Context Pack section. Product Owner approves content. A release manifest pins the exact identity version.

## Alternatives considered

- **System prompt only:** reviewable but often embedded in code/config and not a complete versioned identity package.
- **Persona LoRA only:** model-specific and difficult to inspect/correct.
- **Rely on base-model temperament:** replaceable provider behavior becomes product identity.
- **Store identity only in database prose:** versionable, but repository review and release coupling become less clear; deployment metadata still needs a package hash.

## Consequences

### Benefits

- Human ownership and auditability.
- Provider/model swap tests against one approved identity.
- Clear distinction between identity, policy, and learned preference.

### Costs and constraints

- Models may not follow identity consistently; evaluation remains necessary.
- File, database, prompt, and release versions must not drift.
- Identity evolution needs explicit approval and migration notes.

## Failure modes and future migration risks

Conflicting copies or ad hoc prompt edits can cause identity drift. Generate deployed identity packages from one canonical source and pin hashes. If identity moves to a signed package/store later, preserve the same version/hash/review contract.

## Validation

- Identity hash/version and release-manifest tests.
- Behavioral consistency suite across providers/models.
- Test that no adapter/provider can silently replace required identity sections.

## Approval note

Accepted by the Product Owner on 2026-08-13; the initial approved identity content is versioned in `identity/`.
