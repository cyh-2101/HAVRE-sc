# ADR-0022: Core-governed response delivery after model rendering

- Status: Accepted
- Date: 2026-08-25
- Requested implementation evidence: 2026-08-25 by Product Owner
- Accepted: 2026-08-25 by Product Owner
- Decision owners: Product Owner/System Architect
- Supersedes: None
- Superseded by: None

## Context

Stage 9A v6 and v7 showed that a behavioral adapter can improve concision or
recover some capability while still fabricating shared history, giving unsafe
urgent guidance, disclosing hidden instructions, violating exact output, or
claiming unavailable tool effects. Those are not acceptable release tradeoffs,
and they are not all personality-learning problems.

Before this proposal, ordinary `InteractionService` treated a valid provider
`InferenceResponse` as the owner-visible `ASSISTANT_MESSAGE`. Context and
routing already enforced provenance, privacy, and provider eligibility, but no
versioned Core decision separated raw model output from delivered output.

## Decision

Model output is a candidate rendering. Before delivery, Companion Core applies
the versioned `core-response-policy-v1` boundary with this precedence:

```text
urgent safety
  -> hidden/system confidentiality
  -> privacy/tool authorization and effect truth
  -> recognized exact/structured response contract
  -> unsupported shared-history claim
  -> pass through ordinary companion language unchanged
```

Core owns evidence admission and source presence, recognized imminent-hazard
minimum actions, hidden-instruction confidentiality, tool authorization and
effect receipts, narrow deterministic serialization, and blocking explicit
unsupported-history claims. The model owns natural mode selection, voice,
warmth/firmness, repair, opinions, evidence-faithful memory use, and useful
elaboration outside a Core minimum.

Every new completed interaction embeds a `ResponsePolicyDecision` in the
assistant Event. It binds request, trace, Context Pack, inference response,
action/category/reason, raw inference-output hash, delivered-output hash, and
available effect capabilities. Persistence rejects missing or tampered
bindings. Historical Events remain readable.

The first policy is deliberately high precision. Pattern coverage is not proof
of exhaustive semantic safety or memory entailment. Unrecognized ambiguous
cases remain visible failures and require separately reviewed versioning.

## Consequences

- Raw-model and full-pipeline evaluation are reported separately.
- Prompt wording is not the enforcement boundary.
- Future tool runtimes must pass explicit capabilities and receipts; ordinary
  chat currently supplies none.
- No v8, Stage 9B, private-chat training, candidate status change, promotion,
  deployment, UI candidate change, or broader sensing/context activation
  follows from this decision.

## Validation evidence

- unit coverage for pass-through, memory provenance, unsupported recurrence,
  urgent hazards, confidentiality, exact/structured output, unavailable tools,
  and precedence;
- persistence recomputation of raw/delivered hashes and complete lineage;
- deterministic exported schemas;
- replay of the exact frozen v7 80-case/five-arm output without model inference,
  training, prompt change, or candidate mutation;
- PostgreSQL integration, migration reapplication, provenance audit, schema
  export, and frozen replay verification passed as recorded in the Stage 9A
  model-vs-Core checkpoint.

## Relationship to accepted decisions

This extends ADR-0003 through ADR-0005, ADR-0009 through
ADR-0011, ADR-0014, and ADR-0021 without changing Constitution, Identity, Core
Values, training authority, or promotion authority.
