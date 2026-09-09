# ADR-0033: Reviewed understanding, curated Diary, and adaptive mobile conversation

- Status: Implemented by explicit Product Owner task direction; formal ADR acceptance pending
- Date: 2026-09-03
- Implementation authority: Product Owner request on 2026-09-03
- Extends: ADR-0021, ADR-0027, ADR-0031, and ADR-0032

## Context

The owner-local Daily Companion had durable history, reviewed Memory, User Model,
Goals, and Diary records, but the product surface blurred their meanings. Low-value
system/governance turns could become Memory candidates or Diary content; confirmed
Memory had no direct proposal path into the independently reviewed User Model; raw
technical payloads dominated the mobile reading experience; and iPhone screenshots
showed horizontal clipping and incomplete bottom navigation. The response contract
also encouraged a generic fixed multi-part answer shape even when one compact reply
would be more natural.

These are product-boundary defects, not merely styling defects. If review states and
provenance classes are indistinguishable, the owner cannot tell what HAVRE currently
knows, what it is only proposing, or what might affect a later response.

## Proposed decision for formal review

1. The owner product treats recent conversation, confirmed Memory, proposed Memory,
   User Model, Goals, and Diary as six distinct surfaces. One may inform another only
   through its existing explicit review/provenance contract.
2. Automatic Web Memory proposals are conservative. They require an explicit,
   owner-authored stable statement such as a durable preference or biographical fact.
   Authorization text, stage/governance instructions, hashes, import mechanics,
   reminder queues, and transient utterances do not qualify. API/CLI ingestion keeps
   its existing explicit behavior.
3. A proposed Memory is editable before acceptance. The candidate remains immutable;
   an accepted correction creates the reviewed Memory revision with explicit owner
   correction provenance. Repeating an already rejected unchanged proposal records a
   duplicate outcome rather than resurrecting it as pending.
4. A confirmed active Memory may create one candidate User Model belief with exact
   `MEMORY_REVISION` evidence. It never activates automatically; owner activation or
   invalidation remains a separate transition.
5. Diary v3 selects only meaningful owner-authored daily facts that inform the
   summary. It excludes system authorization, import, hash, policy, migration,
   provenance, and queue mechanics. Only selected messages appear as Diary sources.
   Historical v1/v2 rows remain immutable; additive migration `0056` admits v3.
6. Response planning requests the shortest complete natural shape: one compact
   paragraph for a simple move, two or three parts only when they are genuinely
   distinct, and at most one useful question. Generic three-part templates,
   interrogation, and fabricated intimacy are defects. Multiple visual assistant
   bubbles remain one governed assistant Event with one provenance record.
7. The Web shell must fit the effective visual viewport, including iPhone safe areas
   and keyboard-driven viewport changes. Long identifiers and technical payloads must
   wrap inside their cards. Technical detail stays collapsed by default.
8. Paired-device review stays read-only. This implementation does not grant paired
   iPhone sessions persistent Memory/User Model mutation authority. Any such grant
   requires a new explicit Product Owner authorization with an exact capability list.

## Why it belongs in the final system

HAVRE's continuity depends on owner-legible review states and durable provenance.
Curated daily recall, explicit promotion between understanding layers, adaptive
conversation shape, and usable mobile geometry are permanent product responsibilities,
independent of the selected Replyer or model.

## Simplest viable current implementation

- use conservative deterministic owner-statement admission for Web Memory proposals;
- preserve immutable candidate/revision records while accepting edited content;
- expose one confirmed-Memory-to-candidate-belief operation through existing User
  Model contracts;
- recompute current Diary projections through `curated-owner-day-diary-v3`;
- present review classes as separate collapsed groups;
- keep one Event while splitting paragraphs visually;
- bind the app shell to `visualViewport` metrics and responsive containment.

## Alternatives considered

- **Treat every owner message as Memory or Diary material:** rejected because it turns
  governance mechanics and transient chat into false long-term understanding.
- **Infer and activate User Model beliefs automatically:** rejected because topical
  similarity and accepted Memory do not authorize silent owner characterization.
- **Rewrite historical Diary rows or candidates in place:** rejected because it would
  destroy accepted evidence and review history.
- **Grant paired devices all owner-desktop mutations:** deferred because the exact
  cross-device write capability and threat boundary have not been owner-approved.

## Consequences

### Benefits

- the owner can distinguish proposal, accepted knowledge, model belief, Goal, and
  daily recollection without reading raw JSON;
- stable facts can move through review without being conflated with transient chat;
- Diary better reflects lived events and carries only the sources that informed it;
- mobile navigation and cards remain inside the actual viewport;
- conversation shape can vary without changing Event or inference lineage.

### Costs and constraints

- conservative extraction intentionally misses ambiguous statements;
- existing low-value candidates remain append-preserved but are suppressed from the
  ordinary review surface;
- User Model remains sparse until the owner proposes and activates beliefs;
- physical iPhone/Safari keyboard behavior still requires owner-device evidence.

## Failure modes and future migration risks

Monitor false-positive and false-negative proposal admission, Diary omission or
overcollection, mobile keyboard/safe-area clipping, belief evidence drift, and visual
bubble grouping that could be mistaken for multiple durable Events. Any broader
semantic extractor, automatic belief activation, or paired-device mutation requires
new evidence and explicit authority.

## Validation

The exact implementation, complete PostgreSQL-backed regression, owner-database
readback, provider-bound ContextPack traces, and 390 x 844 production browser evidence
are recorded in
[`PRACTICAL_COMPANION_UX_CHECKPOINT.md`](../PRACTICAL_COMPANION_UX_CHECKPOINT.md).

## Approval note

On 2026-09-03 the Product Owner authorized implementation and owner-local production
activation of this practical companion correction. Formal acceptance of this ADR,
paired-device write authority, and any actual source erasure remain separate decisions.


## Owner-approved short-turn refinement (2026-09-06)

The owner compared OA70 with the real Context A/B review packet, found both arms
unacceptably verbose, and explicitly approved implementing short default turns
and an optional “再说点” control. This updates point 6 for new replies; it does
not accept any unrelated pending ADR scope or change canonical Identity.

- Owner experience v3 and planner v6/v7 prefer one short conversational move,
  normally one or two short sentences. A long personal story does not itself
  request an analysis. Explicit detail, code, multiple tasks, correction, urgent
  guidance and verified action results remain complete. There is no hard token,
  character or sentence truncation. Historical v1-v5 plans remain readable and
  retain their previous render instructions.
- “再说点” sends that exact, visible owner message through the existing interaction
  path, with its current privacy/session, pending-request recovery and idempotency.
  It asks for one contextual next step. No hidden essay, new model loop, service,
  model training, proactive authority or automatic repeated generation is added.
- Complete paragraphs replace mechanical sentence/character slicing. Fresh,
  ordinary short replies may reveal their two or three paragraphs every four
  seconds. Long, structured, requested-detail, proactive and Core-replaced replies
  display without this delay; unknown/legacy policy categories fail closed to
  immediate display. Reduced-motion users also get immediate display.
- Typing pauses scheduled reveals; clearing the draft resumes. Sending a new owner
  message or receiving one from another device cancels the old automatic reveal.
  The remaining text is explicitly available under “查看余下 … 条”. This stops
  presentation, not an already completed inference or a saved Event. No original
  text or response-policy hash is deleted or rewritten; refresh shows saved history.
  “再说点” never masquerades as the control for revealing an existing remainder.
- A timeline read watermark is not a human read attestation. The client does not
  mark a still-partially-revealed Event read when the last paragraph is hidden;
  normal later watermarks retain their existing semantics. No per-bubble delivery
  receipt or new durable state is introduced.
- Existing scheduled Goal reminders and the separate one-minute/30-minute
  relational continuation retain their controls and permissions.

Verification and operational limits: [short-turn review](../SHORT_TURNS_REVIEW_2026-09-06.md).

## Owner-authorized continuation and requested-read repair (2026-09-08)

A visible “再说点/多说点” now carries the exact preceding completed assistant Event
ID and its owner source into the existing interaction contract. Same owner,
session, source policy, revocation and budget checks apply; retries retain the
binding. While the reply has undisplayed paragraphs, the control is explicitly
“看完这条” and expands that saved Event without inference. This refines the
2026-09-06 button description above; four-second presentation remains unchanged.
Experience v4 reduces over-interpretation and repeated elaboration while retaining
complete requested work. It is not a canonical Identity amendment.

Owner-requested record reads now supply bounded, source-qualified Diary summaries,
current Goal status and revisable User Model evidence. Existing commitment
field authorization is reused; no SQL tool, broader privacy grant or arbitrary
model database access is added. Ordinary selectors and compiler policy remain.
See [repair evidence and limits](../CHAT_REPAIR_REVIEW_2026-09-08.md).


## Owner-authorized invisible continuation control (2026-09-08)

The owner's latest instruction supersedes the earlier **visible user message**
requirement for the button. Typed messages retain their normal display. Button
requests use an optional typed `input_origin=continuation_button` on the existing
interaction/Event path; completed control Events are not conversation bubbles,
while failed requests retain an explicit retry. Exact reply/session/privacy and
idempotency bindings remain required. The tap is labelled as a control in Context,
excluded from diary utterances and new realtime understanding, and does not seed
another automatic two-beat continuation. Additive migrations 0074/0075 guard these
new payloads and understanding admission; historical hashes and Events remain.

Only a three-dot indicator is displayed while generating. Newly delivered bubbles
animate on entry; history and unchanged polls do not. Four-second paragraph pacing,
complete requested work and reduced-motion behavior remain intact. A requested
continuation aims for one or two useful message-sized contributions, without
re-asking an unanswered question or replaying an action. There is no hard text cap.

The v5 prompt candidate and CLI base-instruction probe did not show consistent
conversational gains and were not activated. Existing v4/planner v6-v7/provider
configuration remain; the latest rejection supersedes the previously endorsed
four manual drafts as target-quality references. This is an experience correction,
not a canonical Identity or global Context-policy amendment. See
[natural chat repair evidence](../NATURAL_CHAT_REPAIR_2026-09-08.md).
