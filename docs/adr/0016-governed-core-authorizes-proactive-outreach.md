# ADR-0016: Governed HAVRE Core authorizes proactive outreach

- Status: Accepted
- Accepted: 2026-08-13 by Product Owner
- Date: 2026-08-13
- Decision owners: Product Owner/System Architect
- Supersedes: None
- Superseded by: None

## Context and real problem

HAVRE must eventually initiate useful contact for planned Scenes, commitments, missing outcomes, uncertain hypotheses, and progress. A language model can produce plausible reasons and wording, but it is not a durable policy authority and can be prompt-sensitive, provider-dependent, or wrong. Allowing a model to schedule or deliver messages would let replaceable weights decide when HAVRE enters the user's life.

## Decision

Only the governed HAVRE Core may authorize proactive outreach. Trigger sources and models may create evidence or propose candidates. An `InterruptionPolicy` owned by Companion Core records an explainable decision: `SEND_NOW`, `DEFER`, `DROP`, or `REQUEST_OWNER_CONFIRMATION`.

A model may render content only after `SEND_NOW`; it cannot wake itself, authorize, schedule, retry, select a channel, or expand the authorized purpose. Every delivered proactive message links to its trigger, proposal, policy decision, Context Pack, renderer versions, delivery attempt, provenance, and trace.

## Why it belongs in the final system

The decision preserves user agency, provider replacement, model-independent identity, explainability, privacy, and anti-dependence across every future Personal, Teacher, and Edge Brain.

## Simplest viable activation

In Stage 6, deterministic trigger fixtures create durable proposals. A rule-based Interruption Policy evaluates them. Only authorized proposals reach a deterministic template or eligible provider-neutral renderer and a Web/inbox adapter. No model-originated proposal receives special authority.

Acceptance establishes the future boundary only. It does not activate proactive runtime capability in Stage 2.

## Alternatives considered

- **Let the model decide and send:** flexible, but unauditable and provider/prompt dependent.
- **Every trigger automatically sends:** simple scheduling, but confuses evidence with permission and creates annoyance/privacy risks.
- **Require owner approval for every message forever:** safe but prevents useful low-burden automation; retained as one policy outcome rather than the only mode.
- **Put authorization in delivery adapters:** duplicates product policy across channels and makes iOS/vendor behavior authoritative.

## Consequences

### Benefits

- One inspectable authority for whether contact occurs.
- Model/provider changes cannot silently broaden intervention authority.
- Rendering quality can improve without changing outreach permission.
- “Why did you contact me?” has durable evidence.

### Costs and constraints

- Proposal, policy, rendering, and delivery become separate persisted steps.
- Policy needs versioned settings, evidence, and reason codes.
- Models can suggest useful candidates that the Core conservatively drops.

## Failure modes and migration risks

Application orchestration could accidentally let a renderer or adapter bypass policy. Enforce dependency rules, authorization tokens/references scoped to one proposal/purpose, and contract tests. A learned policy may be considered later only behind the same Core authority, explainability, evaluation, and owner approval.

## Relationship to accepted decisions

This extends ADR-0005, ADR-0009, and ADR-0014 without superseding them. Interruption Policy is proposed as a governed-policy sibling to Intervention Policy. It remains below Constitution and Identity/Values and above learned preferences/model behavior.

## Validation

- A model/trigger/renderer/delivery adapter cannot create `SEND_NOW` authority.
- No rendering or delivery occurs without an exact active policy decision.
- Rendered output cannot broaden authorized purpose.
- Provider swap does not change proposal or authorization semantics.
- Every delivered message answers why/when/how from durable references.

## Acceptance scope

Accepted by the Product Owner on 2026-08-13. Acceptance establishes the future architectural boundary; it does not activate proactive implementation in Stage 2 or authorize work ahead of the Roadmap.
