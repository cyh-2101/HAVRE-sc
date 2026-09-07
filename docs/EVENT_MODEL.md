# Event Model

Status: **Durable Event boundaries are accepted through ADR-0030. Migrations 0052-0063 are technically verified for interaction lineage, the bounded Stage 15 commitment loop, source-separated Diary intelligence, explicit chat Goal effects, source-guarded relationship follow-ups, and two-beat exact-turn continuation receipts with exact GPT-high or historical local provider lineage; formal ADR-0032/0034/0035/0036 acceptance and practical utility remain open.**

Related decisions: [ADR-0003](adr/0003-append-oriented-events-and-erasure.md), [ADR-0004](adr/0004-provenance-and-derived-revisions.md), [ADR-0006](adr/0006-w3c-trace-context.md), [ADR-0011](adr/0011-data-handling-policy.md), [ADR-0012](adr/0012-temporal-belief-model.md), [ADR-0013](adr/0013-scene-session-domain-object.md), [ADR-0019](adr/0019-provider-neutral-ambient-life-context.md), [ADR-0020](adr/0020-experience-memory-lifecycle.md), [ADR-0022](adr/0022-core-governed-response-delivery.md), and [ADR-0030](adr/0030-data-policy-driven-dual-replyer-routing.md)

## 1. What an event means

An HAVRE event is an immutable statement that something was observed, requested, produced, changed, or attempted at a point in time. It is the durable chronology from which current projections and derived understanding can be rebuilt.

An event is not necessarily objective truth:

- `USER_MESSAGE` faithfully records what the user communicated; it does not prove every claim in the message.
- `CURRENT_STATE_ESTIMATED` records an estimate and its uncertainty; it does not permanently label the user.
- `MEMORY_CREATED` records that a memory revision was created; the memory remains a revisable interpretation.
- `OUTCOME_REPORTED` records a report and source, not an independently verified outcome unless its source says so.

This distinction keeps raw experience durable while letting HAVRE admit and repair misunderstandings.

For Ambient Life Context, the first retained normalized observation is “raw” relative to downstream understanding. This does not require retaining the device-native pixels, audio frames, exact coordinates, or provider payload that an approved source-local transform minimized. Append preservation is the normal write rule, not a promise of immortality: owner erasure and approved retention expiry remove source content and its derived closure.

## 2. Normative envelope

All events use this model-independent envelope. JSON names are the canonical wire names; the database uses equivalent typed columns.

```json
{
  "event_id": "019b3a9e-bd2d-7d5b-9b89-8c0e18f72118",
  "event_type": "USER_MESSAGE",
  "event_version": 1,
  "owner_id": "019b3a9d-67c9-7b8f-bc7f-9702c1e5674b",
  "occurred_at": "2026-08-12T14:22:05.410Z",
  "recorded_at": "2026-08-12T14:22:05.487Z",
  "actor": {
    "type": "user",
    "id": null
  },
  "source": {
    "type": "web",
    "name": "havre-web",
    "version": "0.1.0",
    "external_id": null
  },
  "session_id": "019b3a9e-5f28-744c-b391-6fd1de5435f2",
  "scene_session_id": null,
  "request_id": "019b3a9e-b80c-7d6b-af5f-ad226fbdad98",
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "causation_event_id": null,
  "idempotency_key": "web:message:client-generated-id",
  "data_policy": {
    "schema_version": 1,
    "privacy_class": "HIGHLY_PRIVATE",
    "memory_eligible": true,
    "training_eligible": false,
    "cloud_eligible": false,
    "policy_version": "data-policy-v1",
    "decision_source": "owner_default",
    "consent_event_id": null
  },
  "payload": {},
  "content_hash": "sha256:..."
}
```

### Required-field rules

- `event_id`: UUID. Producers generate it before retryable persistence.
- `event_type`: registered uppercase name. Unknown names are rejected for writes but remain readable after software rollback.
- `event_version`: positive integer scoped to `event_type`.
- `owner_id`: required for personal data. System-wide operational events use a separate non-owner event path rather than a fake owner.
- `occurred_at`: source event time. It may precede ingestion for imports or offline clients.
- `recorded_at`: server-assigned ingestion time. It never precedes the transaction's trusted clock.
- `actor`: who caused or communicated the occurrence: `user`, `companion`, `system`, `tool`, or `external`.
- `source`: concrete producer and version. `actor` and `source` must not be conflated.
- `session_id` / `scene_session_id`: nullable only when the event is not scoped to one. A Scene Session is a first-class domain object, not merely chat metadata.
- `request_id`: correlation for an ingress or job attempt; separate from distributed tracing.
- `trace_id`: required 32-character lowercase W3C trace ID for every stored event. Imports and maintenance commands create an ingestion trace.
- `causation_event_id`: the one direct domain cause, if there is one. Multiple evidence sources use provenance edges.
- `idempotency_key`: required for retryable external/client ingestion; scoped to owner and source.
- `data_policy`: required provider-independent privacy/use snapshot. `privacy_class` is one of `PUBLIC`, `NORMAL`, `PRIVATE`, `HIGHLY_PRIVATE`, or `LOCAL_ONLY`; memory, training, and cloud eligibility are independent booleans. `training_eligible` defaults false. `LOCAL_ONLY` with `cloud_eligible = true` is invalid.
- `payload`: object validated against the exact event type/version schema.
- `content_hash`: hash of a canonical representation excluding `recorded_at` and the hash itself. Used for integrity and reconciliation, not identity or authorization.

## 3. Event families and initial registry

The registry distinguishes source observations from derived lifecycle and operations. They share an envelope but have different epistemic meaning.

### Interaction and observation

| Event type | Meaning | Minimum payload |
|---|---|---|
| `USER_MESSAGE` | User communicated content | `content_parts`, `channel`, optional `reply_to_event_id` |
| `ASSISTANT_MESSAGE` | A completed or interrupted companion response actually shown to the user, reactive or proactive | `content_parts`, `status`, `interaction_mode`, `inference_response_id` or renderer reference, `context_pack_id`, applicable policy decision IDs, delivery metadata |
| `USER_SIGNAL` | Explicit low-bandwidth Web-simulation Scene signal | `scene_session_id`, `scene_record_id`, categorical signal/safety/avoidance/energy/coercion/goal fields, `input_method`, `occurred_at` |
| `USER_ACTION_REPORTED` | User reported an action in a Scene | `scene_session_id`, `scene_record_id`, `intervention_record_id`, `action`, `action_attempted`, `reporter`, `occurred_at` |
| `OUTCOME_REPORTED` | A Scene outcome was reported | `scene_session_id`, `scene_record_id`, `action_record_id`, `outcome`, `reporter`, `observation_scope`, `occurred_at` |
| `FEEDBACK_RECORDED` | Explicit user feedback | `target_event_id`, `rating`, optional `dimensions`, optional `comment` |

`ASSISTANT_MESSAGE` is created only for content actually exposed to the user. A provider draft or proactive rendering that fails before delivery belongs in protected rendering/inference and delivery-attempt data, not conversational history. A proactive assistant event identifies `interaction_mode = proactive` and links to its proposal, trigger(s), Interruption Decision, Context Pack, rendering, delivery attempt, and trace without duplicating all lifecycle metadata in the message payload.

### Ambient Life Context lifecycle (proposed, external adapters Stage 11/12)

The earlier unimplemented `EXTERNAL_CONTEXT_OBSERVED` placeholder is too broad to activate safely. If ADR-0019 is accepted, this typed family replaces it before any connector exists:

| Event type | Meaning | Minimum payload/reference |
|---|---|---|
| `CONTEXT_SOURCE_REGISTERED` | Owner/device-bound source and exact capabilities were registered | `source_instance_id`, source/adapter versions, capability descriptors, device/owner binding |
| `CONTEXT_CONSENT_REVISED` | Owner granted, narrowed, expired, or revoked one exact source capability/purpose | consent revision, allowed fields/precision/purpose, sampling, retention, policy, validity |
| `CONTEXT_SOURCE_HEALTH_RECORDED` | A versioned health transition or policy-required sample was recorded | source/capability, health state, last success/coverage, clock/freshness/error metadata |
| `LIFE_CONTEXT_OBSERVED` | A canonical minimized observation was durably accepted | observation ID/kind, source/capability/adapter, occurrence window, source/ingest times, expiry, value, measurement limitations, consent/sampling/retention/DataPolicy references |
| `LIFE_CONTEXT_OBSERVATION_INVALIDATED` | Source correction, consent/quality finding, or reconciliation made a prior observation ineligible | prior observation ID, reason, replacement reference when any |

This family is not implemented by the active `EventType` contract. High-frequency heartbeats remain operational data; the domain ledger records health transitions or policy-required samples, not every poll.

Initial `observation_kind` values are bounded to `calendar_commitment`, `device_activity_summary`, `device_presence_state`, `task_session`, `location_context`, `mobility_context`, `voice_session`, `sleep_summary`, `user_declared_state`, `notification_interaction`, and `wearable_summary`. Exact semantics and minimization rules are in [`AMBIENT_LIFE_CONTEXT.md`](AMBIENT_LIFE_CONTEXT.md). New provider fields do not create new canonical meaning without a registered schema and approval.

A `LIFE_CONTEXT_OBSERVED` event is evidence only. `calendar_commitment` does not encode “upcoming”; device activity does not encode productivity or procrastination; notification non-response does not encode attention or distress. Interpretations belong to separately versioned Current State, belief, pattern, memory, and Trigger records.

### Scene Session and goal lifecycle

| Event type | Meaning |
|---|---|
| `SCENE_SESSION_PLANNED` | A first-class Scene Session with situation, planned goal, and anticipated triggers was created |
| `SCENE_SESSION_STARTED` | The planned or ad-hoc Scene Session actually began |
| `SCENE_PHASE_CHANGED` | Scene Session moved between Before, During, and After |
| `SCENE_SESSION_PAUSED` | Active real-world interaction paused without falsifying completion |
| `SCENE_SESSION_ENDED` | Scene Session completed, was abandoned, or was cancelled with an explicit reason |
| `INTERVENTION_DECIDED` | Versioned structured simulation-only Intervention Decision was persisted before guidance |
| `REFLECTION_CREATED` | Owner supplied an After Scene reflection and consented outcome-observation link |
| `GOAL_CREATED` | Goal was accepted into a track |
| `GOAL_UPDATED` | Goal projection changed |
| `GOAL_COMPLETED` | Goal reached or intentionally closed |
| `PROGRESS_RECORDED` | Evidence-linked observation was recorded against an exact goal revision |

Stage 15 does not invent a new completion Event. A clear owner report is the
source `USER_MESSAGE`; the resulting existing `GOAL_COMPLETED` Event remains the
lifecycle record. `goal_transition_evidence` binds both immutable Events, their
request/session/trace identities, hashes, and the exact Goal revision.
Ambiguity produces no lifecycle Event. Future erasure of either explicitly
selected source follows that evidence edge into the affected Goal closure.

An explicitly requested chat Goal reuses `GOAL_CREATED` and any ordinary Goal
lifecycle Events; `owner_chat_goal_plan_runs` and `owner_chat_goal_actions` are
effect receipts, not substitute lifecycle Events. A relationship follow-up also
reuses the existing proactive lifecycle. Its Memory or conversation reference is
evidence for a proposal, never an Event that grants send authority. The existing
Core policy and delivered `ASSISTANT_MESSAGE` remain the authoritative decision
and user-visible effect.

The ADR-0036 continuation receipt is not a new conversational Event and does not
claim that silence has meaning. It is a derived, expiring planning receipt bound
to one completed eligible turn. If authorized planning and Core delivery both
pass, the existing proactive lifecycle and delivered `ASSISTANT_MESSAGE` record
the actual effect. Any newer ordinary owner `USER_MESSAGE` invalidates the old turn's
continuation before delivery and resets only the derived cadence counter.

Stage 5 emits `ASSISTANT_MESSAGE` with `interaction_mode = scene_guidance`
only for guidance actually rendered by the local simulator. Its payload links
the exact Intervention Decision and renderer version. `INTERVENTION_DECIDED`
always records `outreach_authorized = false` and `simulation_only = true`;
these fields are database-constrained and have no delivery side effect.

### Proactive interaction lifecycle (proposed Stage 6)

These event names follow the existing uppercase, past-tense lifecycle convention. They are proposed contracts only; this amendment creates no schemas or runtime producers.

| Event type | Meaning |
|---|---|
| `PROACTIVE_TRIGGER_RECORDED` | A versioned trigger was durably observed as evidence, not permission |
| `PROACTIVE_TRIGGER_INVALIDATED` | A source correction or cancellation invalidated a prior trigger |
| `PROACTIVE_PROPOSAL_CREATED` | A durable outreach candidate was created with exact trigger/evidence references |
| `PROACTIVE_POLICY_DECIDED` | An immutable `SEND_NOW`, `DEFER`, `DROP`, or `REQUEST_OWNER_CONFIRMATION` decision was recorded |
| `PROACTIVE_PROPOSAL_DEFERRED` | The decision established a future eligible evaluation time |
| `PROACTIVE_OWNER_CONFIRMATION_REQUESTED` | The proposal entered owner review without authorizing outreach |
| `PROACTIVE_OWNER_DECISION_RECORDED` | The owner approved, rejected, or narrowed proposal scope |
| `PROACTIVE_PROPOSAL_DROPPED` | Policy ended a candidate with an explainable reason |
| `PROACTIVE_MESSAGE_RENDERED` | A purpose-constrained, not-yet-delivered rendering artifact was finalized |
| `PROACTIVE_DELIVERY_ATTEMPTED` | One channel attempt began under owner-scoped idempotency |
| `PROACTIVE_DELIVERY_FAILED` | An attempt ended with a typed failure; no delivered message is implied |
| `PROACTIVE_MESSAGE_DELIVERED` | Channel delivery produced one linked user-visible `ASSISTANT_MESSAGE` |
| `PROACTIVE_PROPOSAL_SNOOZED` | The owner chose a later eligible time |
| `PROACTIVE_MESSAGE_DISMISSED` | The owner dismissed a delivered outreach |
| `PROACTIVE_PROPOSAL_EXPIRED` | The proposal's useful window ended |
| `PROACTIVE_PROPOSAL_CANCELLED` | The owner/system cancelled the proposal before completion |
| `PROACTIVE_RESPONSE_LINKED` | A reactive request/`USER_MESSAGE` was explicitly linked to delivered proactive outreach |

The registry does not add an `IGNORED` event merely because time passed. Non-response may be a projection over a declared observation window, but it is not evidence of distress, permission to escalate, or proof the user saw the message. Existing `FEEDBACK_RECORDED`, `USER_ACTION_REPORTED`, and `OUTCOME_REPORTED` represent actual observed feedback/outcomes and may link to the proactive chain.

### Derived understanding lifecycle

| Event type | Meaning |
|---|---|
| `CURRENT_STATE_ESTIMATED` | Expiring current-state snapshot created |
| `MEMORY_CREATED` | First memory revision committed |
| `MEMORY_REVISED` | New memory revision superseded or challenged an older one |
| `MEMORY_RETRACTED` | Memory marked not suitable as active understanding |
| `USER_BELIEF_CREATED` | Belief candidate or active revision created |
| `USER_BELIEF_REVISED` | Belief confidence/content/status changed by a new revision |
| `USER_BELIEF_TRANSITIONED` | A revision was activated, contradicted, superseded, retracted, or invalidated at an explicit time |
| `CONSOLIDATION_PROPOSED` | Inspectable semantic/pattern/progress candidate created without authorizing durable memory |
| `CONSOLIDATION_REVIEWED` | Owner accepted, corrected, or rejected one proposal |
| `PATTERN_REVISED` | Pattern revision created |
| `PROGRESS_RECORDED` | Progress evidence/revision created |
| `REFLECTION_CREATED` | Reflection artifact created from source records |
| `TRAINING_EXAMPLE_CREATED` | Canonical training candidate created |

The active Stage 4 payloads point to the derived record/revision and include the
minimum reason or projection fields required for replay; sensitive evidence
content remains in governed records and provenance. `GOAL_UPDATED` and
`GOAL_COMPLETED` additionally bind the complete canonical new Goal projection
and projection content hash. The database verifies that immutable material
against the projection row and the same-statement database timestamp. Future
registry entries remain inactive until their named stage.

### ML systems and release lifecycle

| Event type | Meaning |
|---|---|
| `DATASET_SNAPSHOT_FINALIZED` | Immutable snapshot manifest finalized |
| `TRAINING_RUN_COMPLETED` | Training attempt reached a terminal result |
| `MODEL_VERSION_REGISTERED` | Model artifact metadata registered |
| `ADAPTER_VERSION_REGISTERED` | Adapter artifact metadata registered |
| `EVALUATION_RUN_COMPLETED` | Evaluation reached terminal result |
| `BENCHMARK_RUN_COMPLETED` | Benchmark reached terminal result |
| `RELEASE_APPROVED` | Human/system gate approved an immutable manifest |
| `DEPLOYMENT_CHANGED` | Deployment activated, failed, rolled back, or retired |

### Failure and privacy lifecycle

| Event type | Meaning |
|---|---|
| `INTERACTION_FAILED` | Interaction could not complete; contains typed stage/error, no secret stack trace |
| `DEGRADED_MODE_USED` | A deliberate fallback omitted a component |
| `ERASURE_REQUESTED` | Owner requested deletion scope |
| `ERASURE_COMPLETED` | Optional content-free receipt when policy permits |
| `DATA_POLICY_REVISED` | Owner or approved policy changed privacy/use eligibility for an exact subject/revision |
| `MATERIAL_CHANGE_APPROVED` | Human approved an exact Constitution, identity, safety policy, or personalized-release version |

The registry should remain small. Do not turn every log line or span into a domain event.

The current ordinary interaction path persists `INTERACTION_FAILED` at the exact
failed phase: `context_build`, `capability_check`, `routing`, `version_check`, or
`inference`. A pre-Context failure has no fabricated ContextPack, route, or
inference identity. Later failures carry only the phase-appropriate typed safe
code, retryability, ContextPack/route/inference IDs, and safe message—never a
prompt, raw provider body, API key, or stack trace.

Migrations `0052` and `0053` require each ordinary `interaction_requests` terminal
row to adopt exactly one canonical terminal Event. A completed request binds its
exact `USER_MESSAGE`, ContextPack, selected route, completed inference
attempt/response, Core policy decision, and delivered `ASSISTANT_MESSAGE`. A
failed request binds the exact `INTERACTION_FAILED` Event and the Context/attempt
lineage appropriate to its failure phase. Completed and failed terminals are
mutually exclusive and immutable. The sole privileged exception is the exact
content-free `source_erasure_propagated` request tombstone used while deleting the
source Event and its derived closure; it cannot be used as an ordinary terminal
shape.

## 4. Data policy contract

Privacy class answers how sensitive the information is. Eligibility answers which uses are permitted. They are deliberately separate:

```json
{
  "schema_version": 1,
  "privacy_class": "PRIVATE",
  "memory_eligible": true,
  "training_eligible": false,
  "cloud_eligible": true,
  "policy_version": "data-policy-v1",
  "decision_source": "explicit_owner_choice",
  "consent_event_id": "019b3d13-1ab3-782c-8e08-f981e1c839d1"
}
```

This permits, for example, a private event to inform local memory without entering training, or a normal event to be memory-ineligible but cloud-eligible for the immediate response. No flag implies another.

Policy resolution rules:

1. The event stores the policy snapshot active at ingestion.
2. Later changes append `DATA_POLICY_REVISED` and a `data_policy_revisions` record; the event bytes are not overwritten.
3. Consumers resolve the latest applicable policy plus source constraints before use.
4. Derived artifacts inherit the most restrictive source privacy/use constraints unless an explicit owner-approved policy decision authorizes a narrower declassification.
5. Training candidate and dataset builders require explicit effective `training_eligible = true` for every required source.
6. The Context Builder copies resolved policy to each item and the Router applies it as a hard provider constraint.
7. `LOCAL_ONLY` can never be sent to a cloud model, tool, judge, tracing payload capture, or externally hosted training service.
8. Proactive triggers, proposals, decisions, Context Packs, renderings, previews, delivery attempts, and response links each carry or resolve policy; a channel is ineligible when any required content cannot be disclosed through it.
9. Notification previews are separately classified derived artifacts with exact transform/provenance and omitted-source records. Redaction cannot silently create cloud/channel eligibility or bypass owner-only declassification.
10. Life-context ingestion requires an exact active ConsentScope and RetentionPolicy in addition to DataPolicy. OS/provider permission alone is insufficient.
11. Source-local preprocessing, aggregation, or redaction never makes the canonical observation less restrictive merely because raw material was not retained.
12. Retention expiry follows the same provenance/invalidation/deletion closure as selected owner erasure; it is not implemented as an untracked row purge.

## 5. Content parts

Messages use a model-independent list of typed parts so future voice or images do not corrupt the original text contract.

```json
{
  "content_parts": [
    {
      "type": "text",
      "text": "I really do not want to go in."
    }
  ],
  "channel": "web",
  "language": "en",
  "reply_to_event_id": null,
  "client_created_at": "2026-08-12T14:22:05.385Z"
}
```

Future binary content parts contain an `artifact_id`, media type, hash, and owner-visible description—not a public URL or large base64 value.

## 6. Examples

### Assistant message

```json
{
  "event_type": "ASSISTANT_MESSAGE",
  "event_version": 1,
  "payload": {
    "content_parts": [
      {
        "type": "text",
        "text": "I know you want to leave. That is a prediction, not a fact. Go in for two minutes; you do not need to perform."
      }
    ],
    "status": "completed",
    "inference_response_id": "019b3aa0-dca0-7590-812a-f0d8a9f85770",
    "context_pack_id": "019b3aa0-3f36-781b-a090-c107a310a208",
    "policy_decision_id": "019b3a9f-d3b7-77ef-9924-ff711a04250f",
    "delivery": {
      "channel": "web",
      "first_visible_at": "2026-08-12T14:22:06.214Z",
      "completed_at": "2026-08-12T14:22:07.980Z"
    }
  }
}
```

### Outcome report

```json
{
  "event_type": "OUTCOME_REPORTED",
  "event_version": 1,
  "causation_event_id": "019b3a9e-bd2d-7d5b-9b89-8c0e18f72118",
  "payload": {
    "outcome": {
      "kind": "scene_attendance",
      "entered": true,
      "duration_minutes": 32
    },
    "reporter": "user",
    "observation_scope": "self_report",
    "notes": "It was awkward for the first few minutes, then easier."
  }
}
```

The envelope for a Scene Session outcome also carries `scene_session_id`; its payload should identify the preceding intervention/action records when known so the long-term chain remains queryable.

For a future proactive `ASSISTANT_MESSAGE`, `interaction_mode` is `proactive`; the payload/envelope contains typed references to `proposal_id`, `interruption_decision_id`, `rendering_id`, and `delivery_attempt_id`. `reply_to_event_id` on a later `USER_MESSAGE` identifies an explicit reply. A `PROACTIVE_RESPONSE_LINKED` lifecycle event preserves the complete trigger-to-reply chain. An unrelated conversation has no such link.

### Belief revision lifecycle event

```json
{
  "event_type": "USER_BELIEF_REVISED",
  "event_version": 1,
  "causation_event_id": "019b3ac7-f992-71a2-8ee7-7c47ce7289fb",
  "payload": {
    "belief_id": "019b3ac8-0341-7331-bbba-b765c5a903a0",
    "belief_revision": 3,
    "action": "revised",
    "reason": "Owner corrected an overgeneralization after counter-evidence.",
    "previous_revision": 2
  }
}
```

The event points to the belief revision; the belief table contains its statement,
owner-reviewed confidence, evidence-occurrence interval, learning time, validity
interval, creation time, and exact provenance edges. A
`USER_BELIEF_TRANSITIONED` event and immutable transition row record exactly when
it was activated, contradicted, superseded, retracted, or invalidated. This
avoids duplicating sensitive text while preserving both system history and the
period of the user's life the belief described.

## 7. Ordering and concurrency

- `recorded_at` plus `event_id` gives deterministic ingestion order, not universal causal order.
- `occurred_at` supports offline/imported observations and may be inaccurate; payload/source metadata can record clock quality.
- Life-context intervals carry `occurred_from`/`occurred_to` plus source observation time in the payload. The envelope's server-controlled `recorded_at` remains the trusted ingestion order.
- `causation_event_id` and provenance edges encode causality/evidence explicitly.
- Two concurrent events are both preserved. Projections use optimistic concurrency and deterministic reducers; conflicts result in a later resolution event or revision.
- Never infer that a later timestamp automatically disproves earlier evidence.
- `occurred_at` describes the underlying occurrence; `recorded_at` describes when HAVRE learned it. Derived revision creation and real-world validity are separate timestamps in the derived record.

## 8. Idempotency and delivery semantics

The event store provides **at-least-once attempt, exactly-once effect per idempotency key**:

1. Client/source creates a stable idempotency key before retry.
2. Ingress stores a canonical request fingerprint covering content, policy-relevant fields, channel/language, and any client-selected session.
3. The user event and any required durable work record occur in one transaction. Stage 1 has no background work to enqueue.
4. A duplicate key returns the original event only when its fingerprint matches; a mismatch is a typed conflict.
5. Later consumers record processed event/job identity and make derived writes idempotent.
6. Proactive delivery uses a separate owner/proposal/channel delivery idempotency key. A retry may complete the same authorized effect only after cancellation, expiration, preference, budget/cooldown reservation, channel, and privacy are rechecked.
7. A successful proactive delivery commits/reconciles one `PROACTIVE_MESSAGE_DELIVERED` and one linked `ASSISTANT_MESSAGE`; failed, expired, or cancelled attempts create no delivered assistant history.

There is no claim of magical end-to-end exactly-once delivery across browsers, providers, and networks. Reconciliation is explicit and measurable.

## 9. Schema evolution

- Each `event_type` has independent monotonic integer versions.
- Existing stored payloads are never rewritten just to match a new schema.
- Readers support the current version and a documented compatibility window; old versions may be upcast in memory with pure, tested functions.
- A breaking semantic change creates a new event type or major payload version.
- Fields may be added only when old readers can safely ignore them.
- Removing meaning is not compatible; preserve the old field or version the event.
- Schema definitions will become machine-readable JSON Schema or Pydantic-generated JSON Schema in Stage 1. This document is the Stage 0 normative contract.

Migration tests use golden examples for every retained version.

## 10. Trace propagation

HAVRE adopts W3C-style trace identifiers while keeping observability vendor-neutral.

### Synchronous path

1. Accept a valid incoming `traceparent` only from trusted ingress; otherwise generate a new trace.
2. Create `request` root/server span and a separate UUID `request_id`.
3. Propagate `traceparent` to provider/inference HTTP calls and tool calls.
4. Child spans cover state estimation, retrieval, policy, context build, route, inference, persistence, and delivery.
5. Store the trace ID on events, context packs, retrieval results, inference responses, and durable jobs.

### Background path

- A job created as part of the immediate interaction records `origin_trace_id` and the producing span context.
- Short immediate jobs may continue the trace when the tracing backend supports it safely.
- Deferred reflection/consolidation starts a new trace and uses a span link to the origin trace(s). This avoids a single multi-day trace while preserving causality.
- Deferred/scheduled proactive evaluation and delivery also starts a new trace linked to trigger/evidence origin traces. Re-evaluation and retry attempts have their own spans/traces and exact prior-decision links rather than pretending delay is request latency.
- Offline/context adapter ingestion starts or continues a bounded ingest trace and records source/device/adapter IDs, versions, counts, status, and timing without raw content. Later interpretation uses linked traces plus provenance; it does not stretch one device trace across days.
- Derived events store the worker trace ID; provenance retains exact source events and their traces.

### Privacy rules

- Never place message text, access tokens, exact location, health details, or personal labels in trace baggage, span names, metric labels, or log keys.
- Trace attributes use identifiers, versions, counts, booleans, durations, and approved low-cardinality classifications.
- Protected diagnostic payload capture is opt-in, access-controlled, time-limited, and referenced as an artifact.
- Proactive traces/logs use trigger/proposal/decision/delivery IDs, hashes, registered categories/reason codes, statuses, versions, counts, and timings; they do not copy proposal reasons, evidence, message text, or notification previews by default.

Trace export failure must not prevent durable event persistence.

## 11. Provenance conventions

Use exact, typed references:

```text
source: event/<uuid>
source: memory/<uuid>@<revision>
derived: belief/<uuid>@<revision>
relation: supports | contradicts | derived_from | summarizes | supersedes | evaluates
transform: <name>@<immutable-version>
```

Rules:

- A memory derived from a conversation links to the exact source event IDs, not only `session_id`.
- A state, memory, belief, pattern, or trigger derived from Ambient Life Context links to exact `LIFE_CONTEXT_OBSERVED` events and records the source instance, capability, adapter, consent, sampling, retention, freshness/coverage evaluation, and transform versions.
- A User Model belief must have support or be explicitly marked `unsubstantiated_candidate`.
- Counter-evidence is never deleted merely because confidence rises.
- Summaries keep both source links and a transform version.
- Dataset examples link to the exact event/memory revisions used, plus any human or teacher edit record.
- Provenance to deleted data must not leak content. Erasure removes affected edges and invalidates derived artifacts as required.

## 12. Corrections, supersession, and retraction

### Conversation episodes and response feedback

Every normal chat turn continues to use the existing `USER_MESSAGE` and
`ASSISTANT_MESSAGE` Events. A conversation episode is a derived aggregate, not a
replacement Event: its member table freezes the exact ordered Event IDs and
hashes. The extractive summary and later Memory suggestions therefore cannot
erase, merge, or reinterpret the source history.

Owner response feedback is likewise an append-only derived revision attached to
an exact `ASSISTANT_MESSAGE` and its request/trace/context/route/inference
lineage. Editing an answer never edits the Event. A separate review can classify
the likely issue and explicitly authorize one exact revision for future dataset
consideration, while both the source Event and feedback revision keep
`training_eligible=false`. These records follow ADR-0021 and the same privileged
erasure closure as their sources.

Diary intelligence does not invent a replacement chat Event. It reads exact completed
USER_MESSAGE and ASSISTANT_MESSAGE Events and records their IDs, content hashes, and
one of two dispositions: cloud_summary or private_reference. Only the former may
enter the GPT request. The resulting Diary, delegated Memory, delegated belief, and
quality-review flags are derived records with exact source/run provenance, not
rewritten source history.

An owner-delegated belief still emits USER_BELIEF_CREATED and
USER_BELIEF_TRANSITIONED lifecycle Events and uses the accepted candidate-to-active
transition. A delegated Memory still emits MEMORY_CREATED. Private-reference Events
cannot become delegated updates through this path. Erasure of any run member removes
the affected mixed synthesis and its delegated derivatives before removing the
selected source Event.

Normal correction flow:

1. Preserve the original event as what was communicated or produced.
2. Append a correcting source event or new derived revision.
3. Link it with `contradicts`, `corrects`, or `supersedes` semantics.
4. Update the active projection, not the original event.

Example: if the user says “I meant Tuesday, not Thursday,” the original message remains part of the conversation; a correction event and revised goal/memory prevent the stale date from being treated as current truth.

User-requested erasure is different: it physically removes selected personal content and its derived closure as defined in [`DATABASE_DESIGN.md`](DATABASE_DESIGN.md).

Approved source retention expiry uses the same closure guarantees. A content-free record that a signal existed may remain only when its policy was approved in advance and it cannot reconstruct the deleted content. Regeneration from remaining evidence creates new revisioned artifacts and cannot resurrect deleted source material.

## 13. Invariants and contract tests

Every active stage must test that:

- every event has a valid owner, type/version, trace ID, payload, and content hash;
- every personal event has a valid DataPolicy; `LOCAL_ONLY` rejects cloud eligibility and training eligibility defaults false;
- `recorded_at` is server-controlled;
- duplicate idempotency keys return the same event;
- ordinary roles cannot update or delete events;
- unknown payload fields/types fail according to the version policy;
- cross-owner session, Scene Session, causation, or provenance links fail;
- assistant content is not recorded as delivered when delivery never occurred;
- event and mandatory job creation are atomic;
- schema upcasters are deterministic and preserve original stored bytes;
- logs/traces contain no raw protected content by default;
- corrections and retractions change projections without mutating source events.
- Scene Session lifecycle events preserve allowed phase/status transitions and Intervention → Action → Outcome links;
- belief replay distinguishes event occurrence, learning/recording, revision creation, validity interval, and lifecycle-transition time.
- proposed Stage 6 proactive contract tests prove a trigger/proposal cannot authorize delivery, only `SEND_NOW` can precede rendering, owner confirmation is not itself an outbound permission, and render/delivery references preserve the complete lifecycle;
- proposed delivery tests prove retry idempotency, expiration/cancellation, duplicate suppression, and that no `ASSISTANT_MESSAGE` is stored before actual user-visible delivery;
- bounded conversation-continuation tests prove elapsed silence can advance only
  an owner-authorized exact-turn receipt: beat one after one minute, beat two only
  after beat one was visible and another 30 minutes elapsed, then stop; any newer
  owner interaction cancels the chain and the model never owns send authority.
- proposed context-adapter tests reject an unknown source/device, capability outside consent, forbidden fields, policy downgrade, invalid interval/clock metadata, duplicate-key mismatch, and unregistered observation kind;
- proposed source-health/freshness tests prove offline, stale, revoked, unsupported, and absent observations remain missing/unknown rather than negative user evidence;
- proposed lifecycle tests prove an experience is not automatically promoted to Memory, relevance decay does not mutate truth/validity, and retention/erasure cannot leave contaminated derivatives.
