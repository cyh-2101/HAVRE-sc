# ADR-0012: Bitemporal belief revisions and lifecycle history

- Status: Accepted
- Accepted: 2026-08-13 by Product Owner
- Date: 2026-08-13
- Decision owners: Product Owner/System Architect
- Supersedes: None
- Superseded by: None

## Context and real problem

A person's preferences, vulnerabilities, strengths, and patterns change. HAVRE can also learn old facts late or discover that an earlier interpretation was wrong. One `updated_at` timestamp and one current belief row cannot distinguish what happened, when HAVRE learned it, when its interpretation was created, or which period of life that interpretation describes.

## Decision

Store User Model beliefs as immutable revisions with separate:

- source event occurrence range;
- `learned_at` time when HAVRE received the evidence prompting the revision;
- revision `created_at` time;
- real-world `valid_from` / `valid_to` interval when applicable;
- append-only lifecycle transitions for activation, counter-evidence, contradiction, supersession, retraction, and invalidation, each with occurrence and recording times.

Queries support both `known_as_of` and `valid_at`. Evidence and counter-evidence link to exact source events/revisions. Historical belief content and confidence are never overwritten.

## Why it belongs in the final system

HAVRE must understand not only what may be true now, but how the user and HAVRE's understanding have changed. Temporal history enables honest longitudinal reflection, correction, progress reasoning, evaluation replay, and future reprocessing.

## Simplest viable current implementation

The contract is fixed in Stage 0.1. Stage 4 activates belief revision and transition tables, deterministic current/as-of projections, and explicit support/counter-evidence. Uncertain dates remain nullable ranges rather than fabricated precision.

## Alternatives considered

- **Overwrite one current belief row:** simple reads but destroys historical understanding.
- **Use event `occurred_at` only:** cannot represent late learning, revision creation, or belief validity.
- **Store a free-form history JSON list:** difficult to constrain, query, or replay.
- **Full temporal-database extension immediately:** unnecessary infrastructure before query/workload evidence.

## Consequences

### Benefits

- Answers “what did HAVRE know then?” separately from “what was true/applicable then?”
- Preserves changing beliefs and the user's growth over time.
- Makes contradiction and correction inspectable.

### Costs and constraints

- Queries and projections are more complex.
- Valid-time boundaries may be uncertain and require ranges/qualifiers.
- Confidence comparisons require method/version awareness.

## Failure modes and future migration risks

False timestamp precision can create a misleading life narrative. Store uncertainty and source quality. Transition semantics can drift; keep a registered taxonomy and version reducers. If native temporal features are adopted later, migrate from immutable revisions without changing the contract's meanings.

## Validation

- `known_as_of` and `valid_at` query fixtures.
- Late-reported old event and retrospective correction cases.
- Counter-evidence, contradiction, supersession, retraction, and invalidation replay.
- No update/delete path for historical revision content.
- Progress evaluations across comparable valid-time intervals.

## Approval note

Accepted by the Product Owner on 2026-08-13. Confidence update algorithms remain a later decision.
