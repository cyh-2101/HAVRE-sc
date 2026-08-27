# ADR-0013: Scene Session as a first-class domain object

- Status: Accepted
- Accepted: 2026-08-13 by Product Owner
- Date: 2026-08-13
- Decision owners: Product Owner/System Architect
- Supersedes: None
- Superseded by: None

## Context and real problem

Before/During/After Scene interaction is central to HAVRE's real-world role. Chat messages alone cannot reliably represent a planned situation, low-bandwidth signals, structured interventions, what the user actually did, outcomes, and later reflection—especially when they span sessions or devices.

## Decision

Create a first-class `SceneSession` aggregate with scene type, situation, planned goal/minimum success, anticipated triggers, phase/status, planned/actual start and end times, DataPolicy, and ordered linked records for signals, interventions, actions, outcomes, and reflection.

Preserve the core evidence chain:

```text
Situation -> Intervention -> Real-world Action -> Outcome -> Reflection
```

Each record retains its own occurrence/recording times, source/uncertainty, provenance, and policy. Partial, abandoned, cancelled, and unknown-outcome sessions remain truthful states.

## Why it belongs in the final system

Scene Sessions connect companionship to life outside the conversation. They enable low-bandwidth guidance, post-scene learning, pattern/progress evidence, outcome-aware evaluation, and future iPhone/watch/edge clients without creating a second Companion.

## Simplest viable current implementation

Stage 0.1 defines the contract and data model only. Stage 5 activates a root projection plus append-oriented linked records and a web simulation. Earlier stages preserve `scene_session_id` in event/provenance contracts without implementing Scene behavior.

## Alternatives considered

- **Ordinary chat with scene tags:** loses lifecycle invariants and action/outcome structure.
- **One large JSON scene blob:** difficult to append, trace, correct, and query temporally.
- **Workflow engine now:** premature infrastructure for a small domain state machine.
- **Separate Scene microservice:** unnecessary operational boundary before workload evidence.

## Consequences

### Benefits

- Explicit link from guidance to action and outcome.
- One domain model across web, iPhone, watch, voice, and edge clients.
- Honest partial/unknown outcomes and later corrections.

### Costs and constraints

- Lifecycle/state transition rules need care.
- One Scene Session may span conversational sessions and offline events.
- Outcome linkage is evidence, not automatic causal proof.

## Failure modes and future migration risks

The taxonomy can become rigid or imply clinical certainty. Keep scene types extensible and trigger/state claims uncertain. Offline devices can reorder events; use idempotent IDs and separate occurred/recorded times. If workflow infrastructure is later justified, preserve the Scene Session aggregate and event meanings.

## Validation

- Lifecycle transition and idempotency tests.
- Cross-session/device ordering fixtures.
- Intervention-to-action-to-outcome provenance traversal.
- Partial/abandoned/unknown-outcome cases.
- DataPolicy propagation through every Scene record.

## Approval note

Accepted by the Product Owner on 2026-08-13. Exact signal taxonomy remains a Stage 5 decision.
