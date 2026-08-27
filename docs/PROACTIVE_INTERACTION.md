# Proactive Interaction Architecture

Status: **Accepted proactive and Ambient Life Context architecture; conservative local Stage 6 candidate technically reverified and pending Product Owner reacceptance; real outreach inactive**

Date: **2026-08-13**

Authority: [`MASTER_PLAN.md`](../MASTER_PLAN.md). Accepted by the Product Owner on 2026-08-13. Related accepted decisions: [ADR-0016](adr/0016-governed-core-authorizes-proactive-outreach.md), [ADR-0017](adr/0017-interruption-policy-and-user-control.md), [ADR-0018](adr/0018-provider-neutral-private-delivery.md), [ADR-0019](adr/0019-provider-neutral-ambient-life-context.md), and [ADR-0020](adr/0020-experience-memory-lifecycle.md).

## 1. Purpose and scope

HAVRE must support two governed ways for an interaction to begin:

```text
Reactive path
User initiates
  -> HAVRE responds

Proactive path
A valid trigger is observed
  -> HAVRE records evidence
  -> HAVRE evaluates whether outreach is permitted and useful now
  -> HAVRE may initiate a message
```

The proactive path exists to support the user's chosen life: prepare for a planned Scene, follow up on a commitment, request a missing outcome, check an uncertain hypothesis, or recognize evidence-backed progress. It does not exist to increase application use.

This amendment defines the durable boundaries. The current Stage 6 candidate activates only a local, simulation-only Web-inbox fixture and durable scheduled/event-driven work under the accepted conservative constraints. It does **not** activate real outreach, an external delivery channel, or any external Context Source.

## 2. Five North Star user flows

Every future stage is evaluated against five permanent flows:

1. **Talk** — the user initiates a meaningful discussion.
2. **Prepare** — HAVRE and the user prepare for a real-world situation.
3. **Guide** — HAVRE gives low-bandwidth guidance during a situation.
4. **Reflect** — HAVRE and the user examine what happened afterward.
5. **Reach Out** — HAVRE initiates contact for a clear, explainable, user-benefiting reason.

Reach Out connects the other four; it does not replace them:

```text
Goal or planned Scene
  -> Reach Out before the event
  -> Guide during the event
  -> Reach Out for a missing outcome
  -> Reflect afterward
```

## 3. Non-negotiable proactive principles

### 3.1 Agency, not engagement

HAVRE must not optimize proactive behavior for conversation count, daily activity, notification clicks, time in the product, emotional dependency, or return frequency. It must never contact the user merely because the user has been silent.

HAVRE must not simulate loneliness, jealousy, disappointment, neediness, waiting, or hurt. It must not guilt the user for ignoring or dismissing a message. Silence is a valid and often preferable policy outcome.

### 3.2 Every outreach has a legible reason

For every proposal and delivery, HAVRE must be able to answer “Why did you contact me?” using inspectable records:

- the exact trigger and relevant evidence;
- the user-chosen goal, value, Scene, or operational purpose it was intended to support;
- the Interruption Policy version and decision reasons;
- the applicable permission, budget, cooldown, timing, channel, and privacy rules;
- the Context Pack, renderer/model/template version, delivery attempt, and trace.

A model-written explanation is not the authority. The durable proposal and policy decision are.

### 3.3 Core authorization, never model authorization

A language model may suggest a candidate proposal, summarize evidence, estimate uncertainty, or render authorized wording. It may not authorize, schedule, retry, or deliver outreach.

Only the governed HAVRE Core decides whether to `SEND_NOW`, `DEFER`, `DROP`, or `REQUEST_OWNER_CONFIRMATION`. The model cannot wake itself, create its own permission, expand the proposal's purpose, or bypass a policy decision.

### 3.4 Conservative default and owner control

When evidence quality, confidence, timing, permission, privacy, or likely benefit is unclear, HAVRE defaults to silence or deferment. It does not manufacture urgency.

The owner must eventually be able to disable proactive interaction globally; control categories, quiet hours, budgets, cooldowns, and channels; snooze or dismiss proposals; stop reminders for a goal or Scene; inspect the reason for delivery; and revoke prior permission. Exact defaults, thresholds, and UI remain unresolved until their roadmap stage.

### 3.5 Existing authority remains in force

Proactive behavior remains subordinate to:

```text
Constitution / Core Principles
  -> Identity and Values
  -> governed policy layer
       - InterventionPolicy: what guidance is appropriate
       - InterruptionPolicy: whether, when, and where to initiate contact
  -> Learned Preferences
  -> Personalized rendering/model behavior
```

Privacy classes, eligibility flags, owner boundaries, provider restrictions, traces, provenance, and material-change approvals remain hard constraints. The policy layer shown above is an accepted future sibling-policy extension to the governance hierarchy, not permission for a lower layer to override it or activate runtime work early.

## 4. Component boundaries

```text
Trigger Source
  -> TriggerRecord
  -> Proposal Builder
  -> ProactiveProposal
  -> InterruptionPolicy
       -> DROP
       -> DEFER
       -> REQUEST_OWNER_CONFIRMATION
       -> SEND_NOW
            -> proactive ContextPack
            -> Content Renderer
            -> RenderedProactiveMessage
            -> DeliveryProvider
            -> DeliveryAttempt
            -> delivered ASSISTANT_MESSAGE
            -> response/dismissal/outcome linkage
```

No single `send_notification()` function owns this lifecycle. Each boundary has a distinct responsibility, version, failure model, and audit record.

For external life context, a `ContextSource` is not itself this diagram's `Trigger Source`. It first produces a canonical `LifeContextObservation` and `ContextSourceHealth` record through the governed ingest boundary. Core-owned state/trigger evaluation may then create a `TriggerRecord`. This preserves the required separation between observation, interpretation, proposal, and permission.

### 4.1 Trigger Sources

A Trigger Source is a Core-owned evaluator over durable evidence that may justify later outreach. Initial contract categories may eventually include scheduled time, goal action/deadline, Scene lifecycle, missing outcome/follow-up, owner-created reminder, belief-confirmation need, progress milestone, reflection proposal, system-operational event, and—only in its later stage—fresh consented life-context observations.

A trigger is evidence, not permission. Trigger Sources cannot call delivery adapters or models. External Windows, Calendar, location, wearable, mobile, voice, and sensor connectors remain inactive until Stage 11/12 and must first enter through the proposed provider-neutral ContextAdapter/LifeContextObservation port with scoped consent, source health, freshness, retention, DataPolicy, and provenance. They do not emit `SEND_NOW` or call the Trigger port directly.

Conceptual `TriggerRecord`:

```json
{
  "schema_version": 1,
  "trigger_id": "uuidv7",
  "owner_id": "uuidv7",
  "trigger_type": "registered_string",
  "source_kind": "goal | scene_session | reflection | owner_reminder | system | external",
  "source_refs": ["typed_exact_reference"],
  "subject_refs": ["goal_or_scene_or_other_reference"],
  "observed_at": "timestamptz",
  "recorded_at": "timestamptz",
  "source_version": "immutable_version",
  "consent_scope_ref": "optional_exact_reference",
  "data_policy": "effective_DataPolicy",
  "trace_id": "w3c_trace_id",
  "status": "recorded | invalidated"
}
```

### 4.2 Proactive Proposal

`ProactiveProposal` is a first-class, durable candidate for outreach. It is not a delivered message and does not imply authorization.

```json
{
  "schema_version": 1,
  "proposal_id": "uuidv7",
  "owner_id": "uuidv7",
  "category": "registered_string",
  "trigger_refs": ["trigger_id"],
  "reason": {
    "code": "registered_reason_code",
    "summary": "owner_legible_text"
  },
  "intended_user_benefit": {
    "kind": "registered_benefit_code",
    "goal_or_value_refs": ["typed_exact_reference"]
  },
  "evidence_refs": ["typed_exact_reference"],
  "confidence": {
    "value": "0_to_1",
    "method_version": "immutable_version",
    "limitations": ["string"]
  },
  "urgency": {
    "class": "registered_non_numeric_class",
    "basis_refs": ["typed_exact_reference"]
  },
  "data_policy": "effective_DataPolicy",
  "earliest_eligible_at": "timestamptz",
  "expires_at": "timestamptz",
  "deduplication_key": "opaque_owner_scoped_key",
  "candidate_channels": ["registered_channel"],
  "required_context_refs": ["typed_exact_reference"],
  "status": "lifecycle_projection",
  "policy_version_hint": "optional_immutable_version",
  "created_at": "timestamptz",
  "trace_id": "w3c_trace_id"
}
```

Confidence and urgency are not a combined engagement score. Exact scales and thresholds remain unresolved. Changes to the projection are driven by append-oriented lifecycle events; the proposal's original reason and evidence are never rewritten to make a later decision look inevitable.

### 4.3 Owner preferences and permissions

Immutable `ProactivePreferenceRevision` records preserve history while one owner-qualified authoritative head resolves current settings. It covers global enablement, category permissions, quiet hours and timezone behavior, budgets, cooldowns, snooze/dismissal rules, goal/Scene-specific stops, candidate channels, preview policy, and revoked consent. Saving a revision and every new execution share one owner transaction lock; queued work must adopt the head that is current at execution time.

Preferences constrain policy; they do not force contact. “Allowed” and “should send now” remain different decisions.

### 4.4 Interruption Policy

`InterruptionPolicy` evaluates a proposal and returns one immutable `InterruptionDecision`:

```json
{
  "schema_version": 1,
  "interruption_decision_id": "uuidv7",
  "owner_id": "uuidv7",
  "proposal_id": "uuidv7",
  "decision": "SEND_NOW | DEFER | DROP | REQUEST_OWNER_CONFIRMATION",
  "reason_codes": ["registered_reason_code"],
  "human_explanation": "owner_legible_text",
  "policy_version": "immutable_version",
  "preference_revision_id": "uuidv7",
  "governing_versions": {
    "constitution_version_id": "immutable_version",
    "identity_version_id": "immutable_version"
  },
  "inputs_snapshot": {
    "category_permission": "allowed | denied | confirmation_required",
    "quiet_hours_result": "inside | outside | unresolved",
    "global_budget_result": "available | exhausted | unresolved",
    "category_budget_result": "available | exhausted | unresolved",
    "cooldown_result": "clear | active | unresolved",
    "deduplication_result": "unique | duplicate | unresolved",
    "active_scene_result": "compatible | incompatible | none | unresolved",
    "prior_response_result": "responded | dismissed | ignored | none",
    "channel_eligibility": ["registered_result"],
    "privacy_eligibility": "eligible | ineligible | unresolved"
  },
  "defer_until": "optional_timestamptz",
  "expires_at": "timestamptz",
  "rendering_constraints": ["purpose_and_wording_constraint"],
  "source_refs": ["typed_exact_reference"],
  "trace_id": "w3c_trace_id",
  "decided_at": "timestamptz"
}
```

Rules are explicit and inspectable. Unresolved hard inputs cannot become `SEND_NOW`. `REQUEST_OWNER_CONFIRMATION` places the proposal in an owner review surface; it is not itself permission to send an unsolicited confirmation notification.

### 4.5 Content rendering

Only `SEND_NOW` may proceed to rendering. HAVRE builds a purpose-specific Context Pack that includes the approved reason, benefit, policy decision, required evidence, governing identity, delivery channel constraints, and effective DataPolicy.

Rendering paths are replaceable:

```text
deterministic template
small or local model
Personal Brain
stronger eligible model when policy and privacy permit
```

Simple reminders should default to a deterministic or small/local path when adequate. A model router selects only among eligible renderers after authorization. The render contract includes an immutable authorized-purpose boundary; extra advice, new claims, emotional hooks, urgency, or a broader call to continue talking are invalid outputs.

Conceptual `RenderedProactiveMessage` records `rendering_id`, proposal and decision IDs, Context Pack ID, renderer kind, exact template/provider/model/tokenizer versions, content hash, DataPolicy, preview artifact reference, provenance, trace, and render status. A rendered draft is still not delivered conversation history.

### 4.6 Provider-neutral delivery

`DeliveryProvider` is a port owned by the delivery boundary, not by iOS or a notification vendor:

```python
class DeliveryProvider(Protocol):
    async def capabilities(self) -> DeliveryCapabilities: ...
    async def deliver(self, request: DeliveryRequest) -> DeliveryResult: ...
    async def cancel(self, delivery_id: UUID) -> DeliveryResult: ...
```

Potential adapters include Web inbox, Web live message, in-app notification, iPhone push, lock-screen action, wearable/audio, and explicitly approved future email. The first implementation is a Web/inbox adapter in Stage 6; native push and voice wait until Stage 11.

A `DeliveryRequest` includes proposal/decision/rendering IDs, owner and destination scope, channel, preview artifact/policy, delivery idempotency key, not-before and expiration times, effective DataPolicy, exact adapter version, and trace context. A `DeliveryAttempt` is append-oriented and records attempt number, provider receipt ID, timing, status, typed failure, retryability, and reconciliation result.

Delivery semantics:

- exactly-once effect is attempted per owner, proposal, channel, and idempotency key; no cross-network exactly-once claim is made;
- retry repeats policy, expiration, cancellation, preference, channel, and privacy checks;
- a failed or expired attempt never becomes an `ASSISTANT_MESSAGE`;
- successful user-visible delivery creates one durable proactive `ASSISTANT_MESSAGE` linked to proposal, trigger, policy decision, Context Pack, rendering, delivery attempt, versions, provenance, and trace;
- retries must not create duplicate visible messages or duplicate delivered events;
- cancellation, dismissal, expiration, and “stop reminding me” prevent unsafe subsequent attempts.

### 4.7 Response linkage

A reply to proactive outreach enters the ordinary reactive request path, but its `USER_MESSAGE` and request carry an explicit reply reference to the delivered proactive `ASSISTANT_MESSAGE`. A durable `ProactiveResponseLink` connects:

```text
reactive request / USER_MESSAGE
  -> delivered proactive ASSISTANT_MESSAGE
  -> DeliveryAttempt
  -> RenderedProactiveMessage
  -> InterruptionDecision
  -> ProactiveProposal
  -> TriggerRecord(s)
  -> related Goal / Scene / Memory / Belief / Reflection
```

Without that explicit link, a new user conversation remains unrelated. HAVRE does not infer that temporal proximity alone means the user replied to outreach.

## 5. Complete auditable lifecycle

```text
1. Trigger observed
2. Trigger recorded as evidence
3. Proposal created with reason, benefit, evidence, privacy, timing, and dedupe key
4. Proposal evaluated by InterruptionPolicy
5. One decision recorded
   - DROP -> terminal reason recorded
   - DEFER -> next eligible evaluation time recorded
   - REQUEST_OWNER_CONFIRMATION -> owner review required; no outreach authorized
   - SEND_NOW -> rendering is authorized for the exact purpose
6. ContextPack built with provenance and effective privacy
7. Content rendered by an eligible template/model path
8. Delivery attempted through an eligible channel adapter
9. Delivered / failed / expired / cancelled recorded
10. If delivered, one proactive ASSISTANT_MESSAGE becomes visible history
11. User response / dismissal / snooze / non-response recorded when actually observed
12. Linked outcome or feedback recorded without treating missingness as failure
```

### 5.1 Proposal lifecycle projection

| State | Meaning | Terminal? |
|---|---|---|
| `created` | Durable candidate exists but is not authorized | No |
| `awaiting_evaluation` | Ready for current policy evaluation | No |
| `deferred` | Not appropriate now; may be re-evaluated before expiration | No |
| `awaiting_owner_confirmation` | Owner decision is required through a review surface | No |
| `authorized_for_rendering` | `SEND_NOW` authorizes only the recorded purpose | No |
| `rendered` | Delivery artifact exists but is not yet visible | No |
| `delivery_pending` | Eligible delivery attempt may begin | No |
| `delivered` | User-visible message and linked `ASSISTANT_MESSAGE` exist | Delivery terminal |
| `delivery_failed` | Latest attempt failed; retry requires policy re-check | Conditional |
| `dropped` | Policy decided outreach should not occur | Yes |
| `expired` | Useful window closed | Yes |
| `cancelled` | Owner/system cancelled before delivery | Yes |
| `dismissed` | User dismissed a delivered message | Post-delivery terminal for equivalent follow-up |
| `responded` | Explicit linked user response exists | Post-delivery outcome |

No-response is an observation, not proof of distress, rejection, or permission to escalate.

Similarly, unavailable context is not user evidence. Calendar disconnected, Windows offline, location stale, phone unreachable, or permission revoked must appear in the proposal/policy input coverage when relevant. They cannot be rewritten as “no commitment,” “inactive,” “at home,” “ignoring,” or any other negative fact.

### 5.2 Event taxonomy

The event taxonomy uses the existing uppercase, past-tense lifecycle convention:

| Event type | Meaning |
|---|---|
| `PROACTIVE_TRIGGER_RECORDED` | A versioned TriggerRecord was durably observed |
| `PROACTIVE_TRIGGER_INVALIDATED` | Source correction made a trigger ineligible |
| `PROACTIVE_PROPOSAL_CREATED` | A proposal was created from exact trigger/evidence references |
| `PROACTIVE_POLICY_DECIDED` | An immutable InterruptionDecision was recorded |
| `PROACTIVE_PROPOSAL_DEFERRED` | A decision set a future eligible evaluation time |
| `PROACTIVE_OWNER_CONFIRMATION_REQUESTED` | Proposal entered owner review without outreach permission |
| `PROACTIVE_OWNER_DECISION_RECORDED` | Owner approved, rejected, or changed proposal scope |
| `PROACTIVE_PROPOSAL_DROPPED` | Policy ended the candidate with a reason |
| `PROACTIVE_MESSAGE_RENDERED` | A non-delivered rendering artifact was finalized |
| `PROACTIVE_DELIVERY_ATTEMPTED` | A channel attempt began under an idempotency key |
| `PROACTIVE_DELIVERY_FAILED` | An attempt ended in typed failure |
| `PROACTIVE_MESSAGE_DELIVERED` | A channel confirmed visibility and links the delivered `ASSISTANT_MESSAGE` |
| `PROACTIVE_PROPOSAL_SNOOZED` | Owner deferred a proposal until a chosen time |
| `PROACTIVE_MESSAGE_DISMISSED` | Owner dismissed delivered outreach |
| `PROACTIVE_PROPOSAL_EXPIRED` | Useful delivery window ended |
| `PROACTIVE_PROPOSAL_CANCELLED` | Owner/system cancelled the proposal |
| `PROACTIVE_RESPONSE_LINKED` | A reactive request was explicitly linked to delivered outreach |

These lifecycle events reference domain records rather than duplicating private content. Existing `USER_MESSAGE`, `ASSISTANT_MESSAGE`, `FEEDBACK_RECORDED`, `USER_ACTION_REPORTED`, and `OUTCOME_REPORTED` continue to represent actual communication and observed outcomes.

## 6. Three separate decisions

Anti-annoyance requires three different decisions:

1. **Is there enough evidence to create a potentially useful proposal?** Trigger and proposal building answer this.
2. **Should HAVRE speak now, on this channel?** Interruption Policy answers this.
3. **Should HAVRE speak again after delivery, dismissal, or non-response?** A new trigger/proposal and policy evaluation answer this; delivery retry logic cannot decide it.

The third answer defaults to no for substantially equivalent messages after dismissal, non-response, recent delivery, expired usefulness, or a stop request. Transport retry is permitted only to complete the same authorized delivery safely, not to create another attempt at persuasion.

## 7. Integration with other HAVRE domains

### Goals

Goals may supply planned-action, unresolved-commitment, and progress evidence. A goal never grants unlimited reminders. Proposals remain category-permission, budget, cooldown, expiry, dismissal, and policy constrained.

### SceneSession

Scene Sessions may support preparation, low-bandwidth availability, missing-outcome follow-up, and reflection prompts. Current phase/status is a hard timing input: an active Scene can suppress irrelevant outreach, and a cancelled/ended Scene can invalidate stale proposals.

### Memory

Memory may improve relevance and wording. Memory alone cannot authorize outreach. A painful or intimate memory is never a trigger merely because retrieval found it.

### User Model

Qualified beliefs may inform relevance. They cannot authorize contact. An uncertain belief may later support a confirmation proposal, but the proposal must state uncertainty and pass Interruption Policy.

### Reflection and Consolidation

Reflection, consolidation, and Teacher processes may create proposals for pattern checking, contradiction resolution, progress recognition, or follow-up. They cannot approve or deliver them.

### Ambient Life Context (proposed)

Fresh `LifeContextObservation` Events may support a Current State estimate, Goal/Scene evidence, memory/belief revision, or TriggerRecord. Each downstream artifact retains exact observation, source/capability/adapter, consent, sampling, retention, DataPolicy, health/freshness/coverage, and transform provenance.

The Interruption Policy must see source limitations and missingness. If a proposal needs current Windows activity but the agent is offline or the observation is stale, the proposal cannot use the absence as evidence and normally ends in `DEFER`/`DROP` or is never created. More collection is not an automatic degraded-mode fallback.

### InterventionPolicy versus InterruptionPolicy

| Question | `InterventionPolicy` | `InterruptionPolicy` |
|---|---|---|
| Core purpose | What guidance is appropriate for this situation? | Is HAVRE permitted and justified to initiate contact now, and on which channel? |
| Typical input | Current state, danger, goal, Scene, evidence, desired action | Proposal, permissions, benefit, timing, evidence quality, budgets, cooldowns, prior contact, channel/privacy |
| Output | Structured guidance, style, constraints, minimum action, clarification/recovery choice | `SEND_NOW`, `DEFER`, `DROP`, or `REQUEST_OWNER_CONFIRMATION` with reasons |
| Can authorize outreach? | No | Yes, only within higher-level governance and owner controls |
| Can choose message wording? | Constrains meaning; renderer writes wording | Constrains purpose/timing/channel; renderer writes wording |

For proactive guidance, Interruption Policy decides whether HAVRE may initiate; Intervention Policy may then decide what kind of guidance the authorized message should contain. Neither replaces the other.

### Model Router

The Router runs only after `SEND_NOW` and Context Pack construction. It selects an eligible renderer/provider under privacy and capability constraints. Quality, latency, or cost can never override privacy or outreach authorization.

### Worker and scheduling

Proactive execution eventually requires event-driven and scheduled background work. It reuses the accepted PostgreSQL-backed job/outbox boundary with transactional enqueue, leases, idempotent handlers, retries, typed terminal failure, and trace links. A dedicated queue is introduced only after measured workload justifies it.

No worker, job table, scheduler, or queue is activated by this amendment.

## 8. Privacy-safe proactive delivery

### 8.1 Conservative inheritance

Trigger, proposal, decision input, Context Pack, rendered content, preview, and delivery attempt each resolve a DataPolicy. A proposal and full rendering inherit the most restrictive required source constraints. Channel eligibility is checked independently from model/cloud eligibility.

### 8.2 Notification previews

Each channel supports a versioned preview policy:

```text
FULL_CONTENT
GENERIC_PRIVATE_PREVIEW
NO_PREVIEW
OWNER_CONFIGURED_PREVIEW
```

The default for sensitive classes remains an owner decision. A generic preview such as “HAVRE has a follow-up for you” can avoid exposing private details on a lock screen.

A preview is a separate derived artifact with its own classification, provenance, transform/version, omitted-field record, eligibility decision, and content hash. Redaction cannot silently make `LOCAL_ONLY` content eligible for an external push provider or weaken any source restriction. Any declassification requires explicit owner authority under the accepted DataPolicy.

### 8.3 Tracing and logs

Traces and operational logs use IDs, hashes, registered categories/reason codes, timings, counts, status, and exact versions. They do not copy trigger evidence, proposal reason text, message content, memory text, or notification previews by default. Protected diagnostics remain opt-in, access-controlled, time-limited artifacts.

## 9. Anti-annoyance and anti-dependency rules

The future policy must explicitly support:

- global and category permissions;
- quiet hours and timezone-aware timing;
- global and per-category budgets;
- cooldowns and same-goal/Scene duplicate suppression;
- proposal expiration;
- snooze, dismissal, and “stop reminding me”;
- lower frequency after repeated non-response;
- cancellation when the source goal/Scene is closed or corrected;
- no emotional prompting, artificial urgency, or conversation-for-conversation's-sake;
- no punishment, guilt, or escalation because the user was silent;
- no assumption that silence means distress;
- no delivery whose primary purpose is to keep the user inside HAVRE.

Budgets are maximum permissions, never quotas to fill. An unused budget does not create a reason to contact the user.

## 10. Evaluation and systems measurement

No current proactive performance is claimed. Future labeled cases evaluate both wording and whether contact should have happened.

### Usefulness

- user-rated helpfulness;
- support for a user-chosen goal or value;
- whether a suggested action was attempted when outcome evidence is known;
- missing Scene outcome collection;
- useful correction/confirmation from reflection outreach;
- progress recognition that is evidence-backed and not exaggerated.

### Interruption quality

- unnecessary-outreach, dismissal, ignore, snooze, duplicate, later-regret, too-passive, and too-forceful rates;
- burden per day/week, always with owner settings, denominator, and observation coverage;
- percentage of delivered messages whose reason the owner can understand;
- false-positive outreach: sent/authorized when `DEFER`, `DROP`, or confirmation was appropriate;
- false-negative outreach: dropped/deferred when a labeled case supports timely contact;
- confusion matrix and severity by `SEND_NOW`, `DEFER`, `DROP`, and `REQUEST_OWNER_CONFIRMATION`.

### Systems performance

- trigger-to-proposal, proposal-evaluation, proposal-to-render, and proposal-to-delivery latency;
- delivery failure, duplicate-delivery, scheduling error, and expired-before-delivery rates;
- renderer latency, token use, and cost;
- local versus approved-cloud routing distribution;
- worker queue age, retry amplification, and stale-policy/preference rejection;
- trace/provenance completeness.

No engagement, return-frequency, or conversation-duration metric may serve as a success objective. Missing responses remain unknown, not negative outcomes.

## 11. Roadmap placement and prerequisites

The smallest coherent placement keeps existing stage numbers:

| Stage | Proactive layer | Prerequisites |
|---|---|---|
| Stage 4 | Goals/User Model produce governed evidence, not outreach | Memory and bitemporal beliefs |
| Stage 5 | Scene and Intervention contracts expose lifecycle/timing inputs | Goals/User Model and Scene state |
| **Stage 6** | **Proactive Core:** trigger contracts, proposals, Interruption Policy, preferences, budgets/cooldowns, Web/inbox delivery, provenance/tracing | Stages 1–5 plus worker/job activation under ADR-0008 |
| Stage 7 | Reflection/Consolidation may create proposals; Core still authorizes | Proactive Core and reflection evidence |
| Stage 8 | Unified proactive evaluation and operations | Measured Stage 6–7 cases/traces |
| Stage 11 | Native iPhone push, lock-screen actions, low-bandwidth replies, preview controls | Stable provider-neutral delivery contract |
| Stage 12 | Windows, Calendar, location, mobility, wearable, sensor, and Edge context adapters feeding Core trigger evaluation | Accepted Ambient Context contracts, scoped consent, source health/freshness, native/privacy controls, connector-specific evaluation |

Stage 6 begins with Web/inbox delivery. It does not require iOS, Calendar, location, wearables, email, or a dedicated queue.

## 12. Compatibility with accepted ADRs

No accepted ADR must be superseded if this amendment is approved:

| Accepted decision | Compatibility |
|---|---|
| ADR-0001 modular monolith | Proactive Core remains a domain/module with ports; worker is an existing process boundary |
| ADR-0002 PostgreSQL authority | Future proposals/jobs/delivery metadata use the existing system of record |
| ADR-0003 append-oriented events | Proposal and delivery lifecycle changes append events; erasure still outranks append-only history |
| ADR-0004 provenance | Triggers, evidence, renderings, previews, and responses use typed exact lineage |
| ADR-0005 provider-neutral inference | Model-based rendering reuses provider-neutral inference after authorization |
| ADR-0006 W3C trace links | Scheduled/deferred work creates linked traces without private content in telemetry |
| ADR-0008 PostgreSQL jobs first | Proactive scheduling is the first planned activation of the accepted worker boundary; no queue is added now |
| ADR-0009 model-independent identity | Models cannot authorize outreach or own proactive identity |
| ADR-0010 evaluation-gated releases | Proactive policy/render/delivery changes enter versioned suites and release evidence |
| ADR-0011 DataPolicy | Every proactive artifact and channel conservatively resolves privacy/use eligibility |
| ADR-0013 SceneSession | Scene lifecycle supplies typed triggers and suppression/timing evidence |
| ADR-0014 governance hierarchy | Interruption Policy is a proposed governed-policy sibling to Intervention Policy, not a higher or model-owned authority |
| ADR-0015 outcome-aware evaluation | Outreach usefulness remains separate from engagement and reports missing outcomes as unknown |

The only material extension is adding Interruption Policy beside Intervention Policy in the governed policy layer and adding a provider-neutral delivery port. ADR-0016 through ADR-0018 are accepted; implementation remains gated by the named later stages and unresolved owner decisions.

ADR-0019/0020 extend the upstream evidence and memory lifecycle without superseding ADR-0016 through ADR-0018. Observation sources still cannot authorize contact, and memory promotion still cannot create a reason to contact the owner merely because an event was retained.

## 13. Owner decisions still unresolved

The amendment deliberately does not decide:

1. global proactive default and consent/onboarding flow;
2. category taxonomy and per-category default permissions;
3. categories that may ever use `SEND_NOW` without case-by-case confirmation;
4. quiet-hour semantics, timezone changes, and any narrowly defined exception path;
5. global/category budget units and numeric limits;
6. cooldown lengths, duplicate-equivalence rules, and same-goal/Scene deduplication windows;
7. confidence, urgency, evidence-quality scales and decision thresholds;
8. expiration rules and maximum defer/re-evaluation cadence;
9. exact meaning of snooze, dismissal, non-response, and “stop reminding me” across related proposals;
10. which repeated non-response pattern reduces frequency and by how much;
11. owner-confirmation review UX and whether it may ever create a separate notification;
12. first Web/inbox behavior, read/delivered semantics, and retry/reconciliation limits;
13. allowed delivery channels and whether email is ever approved;
14. preview defaults by privacy class/channel and the approved redaction/declassification workflow;
15. channel-specific privacy, retention, export, erasure, and third-party processor requirements;
16. exact renderer selection rules and approved cloud providers/purposes;
17. allowed system-operational trigger categories and whether any can interrupt the owner;
18. crisis/professional-help and safety behavior for proactive proposals, including a strict rule that silence alone is not distress;
19. owner-facing “Why did you contact me?” detail level and protected-evidence access;
20. evaluation rubric anchors, label protocol, observation windows, minimum coverage, and binding gates.
21. which context-derived trigger categories may exist and which source coverage/freshness is required;
22. Windows/Calendar/iPhone/location/voice/wearable capability, precision, sampling, retention, and revocation defaults;
23. whether any context-derived category may ever use `SEND_NOW` without case-by-case confirmation.

These require Product Owner approval at or before their activation stage. The 2026-08-19 Stage 6 authorization resolves only the conservative local-simulation subset: global disabled by default, preview `none`, explicit owner preference before `SEND_NOW`, and unresolved controls fail closed. Unresolved real-delivery or external-context choices remain inactive.

## 14. Historical amendment gate and current extension

The Product Owner accepted this document and ADR-0016 through ADR-0018 on 2026-08-13 as future architecture. On 2026-08-19 the Product Owner accepted the Ambient Life Context extension in [`AMBIENT_LIFE_CONTEXT.md`](AMBIENT_LIFE_CONTEXT.md), ADR-0019, and ADR-0020 and separately authorized conservative Stage 6 followed by Stage 7 implementation. That authorization activates only local simulation/proposal flows; external Context Sources, sensing, real delivery, private-data export, and governance changes remain separately gated.
