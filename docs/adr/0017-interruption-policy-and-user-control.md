# ADR-0017: Explainable Interruption Policy with owner control and anti-annoyance limits

- Status: Accepted
- Accepted: 2026-08-13 by Product Owner
- Date: 2026-08-13
- Decision owners: Product Owner/System Architect
- Supersedes: None
- Superseded by: None

## Context and real problem

A potentially useful reason to speak does not mean HAVRE should speak now or continue after silence. Without a separate policy, goals and memories could become unlimited reminders, models could optimize engagement, and retries could turn into repeated persuasion.

## Decision

Create a versioned `InterruptionPolicy` that decides among `SEND_NOW`, `DEFER`, `DROP`, and `REQUEST_OWNER_CONFIRMATION`. It evaluates category permission, intended benefit, evidence quality, confidence, urgency, quiet hours, global/category budgets, cooldowns, deduplication, active Scene, availability when legitimately known, prior delivery/dismissal/non-response, expiration, channel eligibility, privacy, and alignment with a user-chosen goal or value.

The owner can eventually disable proactive interaction globally; control categories, quiet hours, budgets, cooldowns, and channels; snooze, dismiss, stop goal/Scene reminders, inspect reasons, and revoke permission. Budgets are ceilings, never quotas. Silence is never itself a trigger or evidence of distress.

## Why it belongs in the final system

Interruption quality is a durable product responsibility across Web, iPhone, wearables, and future sensors. Central policy prevents channel- or model-specific engagement behavior and protects the constitutional goal of increasing agency rather than dependence.

## Simplest viable activation

Stage 6 begins with explicit rule evaluation, owner-scoped preference revisions, fixed test categories, conservative defaults, and a Web/inbox adapter. Numeric limits and defaults require Product Owner approval before binding use.

## Alternatives considered

- **One engagement/relevance score:** compact but opaque and capable of hiding critical denials.
- **Channel-specific notification settings only:** cannot reason about evidence, goals, duplicates, or cross-channel burden.
- **Model decides timing conversationally:** not reproducible, auditable, or safely testable.
- **Send whenever within a budget:** treats a maximum as a target and still creates unnecessary outreach.

## Consequences

### Benefits

- Explicit reasons for send, defer, drop, and confirmation.
- Owner preferences remain revocable and inspectable.
- Anti-annoyance behavior is testable independently from wording.
- Dismissal/non-response cannot silently become escalation.

### Costs and constraints

- Preference, budget, cooldown, and deduplication state need consistent projections.
- Timezone, offline devices, concurrent proposals, and retries complicate timing.
- Conservative false negatives are expected until policy evidence improves.

## Failure modes and migration risks

Opaque heuristics could reappear as a hidden score; reason codes and per-input results remain required. Race conditions could overspend budgets or duplicate delivery; policy reservation and delivery idempotency must be transactional. Learned preferences may tune within owner-approved bounds but cannot create new categories or permissions.

## Relationship to accepted decisions

This extends ADR-0014's policy layer and ADR-0015's anti-engagement/outcome principles. It does not change owner approval authority or turn engagement into an outcome.

## Validation

- Labeled four-way policy cases, including false-positive and false-negative outreach.
- Quiet-hour, budget, cooldown, duplicate, expiration, dismissal, snooze, stop, and non-response tests.
- Concurrent evaluation cannot exceed a reserved budget or create duplicate authorization.
- Denied/unresolved permission or privacy can never produce `SEND_NOW`.
- No proactive message is created solely from elapsed silence.

## Unresolved owner decisions

Category taxonomy/defaults, global default, numeric budgets/cooldowns, confidence/urgency thresholds, expiration/re-evaluation cadence, confirmation UX, no-response frequency reduction, and binding evaluation gates remain unresolved.

## Acceptance scope

Accepted by the Product Owner on 2026-08-13. Acceptance establishes the future architectural boundary; unresolved owner decisions remain unresolved, and no proactive implementation is activated in Stage 2.
