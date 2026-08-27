# ADR-0015: Outcome-aware guidance evaluation

- Status: Accepted
- Accepted: 2026-08-13 by Product Owner
- Date: 2026-08-13
- Decision owners: Product Owner/System Architect
- Supersedes: None
- Superseded by: None

## Context and real problem

A response can sound warmer, firmer, or more intelligent without helping the user act consistently with chosen values and goals. Language judges and systems benchmarks cannot show whether an action was attempted, a Scene Session was completed, guidance was too passive or forceful, or the user later regretted following it.

## Decision

Evaluate three linked but separate evidence classes: language/behavior quality, ML-system performance, and real-world guidance outcomes. Outcome observations link an exact intervention and delivered response to a Scene Session/goal, action, outcome, later feedback, observation window, source, uncertainty, DataPolicy, and provenance.

Candidate measures include action attempted, Scene completion/partial/abandonment, helpfulness, too passive, too forceful, later regret, goal/value alignment, and avoidance change across genuinely comparable situations. Missing follow-up is `unknown`. Engagement and conversation length are not outcome proxies. Results disclose denominators, missingness, time horizons, and limitations.

## Why it belongs in the final system

HAVRE's mission concerns life, agency, and internalized judgment rather than maximizing AI interaction. Outcome evidence is necessary to decide whether intervention, memory, routing, or personalization changes help beyond making outputs sound better.

## Simplest viable current implementation

Stage 0.1 defines the observation contract and interpretation rules only. Stage 5 can add low-burden, consented post-scene action/outcome/helpfulness checks. Later reflections may add delayed regret or corrections. No improvement target or claim exists until real data is collected and reviewed.

## Alternatives considered

- **Language-model judge only:** scalable but measures output appearance, not life outcomes.
- **Engagement/retention metrics:** conflict with HAVRE's anti-dependence mission.
- **Action completion alone:** rewards pressure and ignores safety, regret, recovery, and user ownership.
- **Automatic sensor inference:** intrusive and unreliable without explicit consent/context.
- **Randomized causal experiment immediately:** inappropriate and impractical for an early single-user personal system.

## Consequences

### Benefits

- Distinguishes eloquence from useful guidance.
- Makes passivity, forcefulness, and regret first-class negative evidence.
- Connects Scene Sessions, Intervention Policy, learning, and evaluation.

### Costs and constraints

- Follow-up can burden the user and produce missing/self-reported data.
- Life situations are non-stationary and difficult to compare.
- Outcome data is highly private and must not become training data by default.

## Failure modes and future migration risks

Metrics can incentivize action-at-any-cost or overclaim causality. Balance action with safety, consent, recovery, value alignment, and regret; use cautious “associated with” conclusions and human review. Never turn missingness into failure or pressure the user to provide data. Future richer causal/statistical methods must preserve raw observations and declared limitations.

## Validation

- Intervention → Action → Outcome provenance tests.
- Unknown/missing follow-up remains outside success/failure numerators.
- Reports include denominators, coverage, time windows, and source/confidence.
- Negative outcomes, forcefulness, passivity, and regret cannot be hidden by one aggregate.
- DataPolicy and explicit training-eligibility tests for outcome observations.

## Approval note

Accepted by the Product Owner on 2026-08-13. Exact scales, cadence, comparison windows, and gates remain later decisions.
