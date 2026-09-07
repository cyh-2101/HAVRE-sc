# ADR-0024: Governed automatic Reach Out and generic LOCAL_ONLY Push

- Status: Accepted
- Accepted: 2026-08-27 by Product Owner
- Date: 2026-08-27
- Decision owners: Product Owner/System Architect
- Extends: ADR-0016, ADR-0017, ADR-0018, and ADR-0023

## Decision

The Stage 6 worker may automatically evaluate durable Events, but trigger
authority is deliberately narrow. Only these exact current sources may create
scheduled proactive work:

1. a `USER_MESSAGE` containing an explicit owner request to be reminded and an
   unambiguous supported time;
2. the exact current active Goal revision with an owner-supplied `review_at`;
3. the exact current planned, before-phase Scene revision with
   `planned_start_at`.

Memory, User Model beliefs, Current State, and Calendar/Life Context may inform
an already-authorized proposal but never create outreach by themselves.
Silence or elapsed time since the last chat is not a trigger.

Every evaluation is immutable and bound to the source Event ID, source Event
hash, evaluator version, disposition, reason, and optional work item. Queued
Goal/Scene work carries the exact projection ID, revision, content hash, and
last Event. The worker rechecks that guard immediately before proposal
execution and cancels stale, paused, superseded, or already-started work.

Interruption Policy remains the only send authority. Global/category enable,
owner stop controls, budgets, privacy, duplicate suppression, expiry, and
delivery eligibility remain fail closed. A null cooldown means the owner has
chosen no minimum interval; an empty quiet-hours list means no quiet-hours
window. Neither choice disables the remaining controls.

After `SEND_NOW`, deterministic natural templates may render an explicit
reminder, Goal review, or planned Scene prompt. They must not invent urgency,
familiarity, evidence, or a reason to continue talking.

## Narrow privacy amendment

ADR-0023 previously blocked every `LOCAL_ONLY` Event from external delivery.
The Product Owner now explicitly authorizes one narrower derived disclosure:
when the exact interruption-decision preference revision contains
`generic_push_for_local_only=true`, Web Push may transmit only the existing
generic-private envelope:

- title `HAVRE`;
- body `HAVRE 有条消息给你`;
- one opaque delivery locator;
- one same-origin `/chat` URL.

The full message and all owner content remain LOCAL_ONLY and are fetched only
after the authenticated client opens the private Tailscale application. The
payload may not contain message text, Event IDs, ContextPack, Memory, User
Model, Goals, Calendar, conversation history, prompts, credentials, or raw
evidence. The provider and database both recheck the exact preference revision
and current Event privacy. Missing, false, stale, or unknown authorization
fails closed. This decision does not generally declassify LOCAL_ONLY data.

## Limits

No model chooses triggers, policy outcomes, or delivery. No training, model
promotion, automatic cloud routing, broader sensing, public endpoint, VPS, or
always-on Core is authorized. PC sleep/offline still prevents new Reach Out.
Real proactive usefulness and burden remain owner-observation questions rather
than claims established by synthetic tests.
