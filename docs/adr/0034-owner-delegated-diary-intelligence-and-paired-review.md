# ADR-0034: Owner-delegated Diary intelligence and paired review

- Status: Implemented by explicit Product Owner task direction; formal ADR acceptance pending
- Date: 2026-09-03
- Implementation authority: Product Owner request on 2026-09-03
- Extends: ADR-0020, ADR-0021, ADR-0030, ADR-0032, and ADR-0033

## Context

Diary v3 fixed obvious governance/import noise, but it remained deterministic and
extractive: it ranked owner phrases, joined the highest-scoring clauses, truncated
them into a title and preview, and therefore still looked like a long message plus
chronological流水. It also could not use the strong GPT branch to produce a coherent
first-person daily reflection, while private/local dialogue must never be disclosed
to that branch.

The owner additionally authorized the already paired iPhone to perform a narrow set
of durable Memory and User Model review actions, and explicitly delegated automatic
Memory/User Model updates when the evidence itself came from an eligible GPT-routed
conversation. Private-chat-derived understanding remains owner-reviewed.

## Proposed decision for formal review

1. Diary intelligence considers only message Events belonging to completed ordinary
   interactions on one exact owner-local calendar day.
2. Only exact Events already routed through the cloud GPT Replyer, with effective
   PUBLIC or NORMAL and cloud_eligible=true, may enter the high-effort Diary
   request. PRIVATE, HIGHLY_PRIVATE, LOCAL_ONLY, local-route, incomplete, or
   otherwise ineligible Events never enter that request.
3. Private/local Events may appear only as an owner-local collapsed transcript
   reference. Their content and IDs are absent from the GPT request; the request may
   contain only a count stating that unsupplied private Events exist.
4. The isolated Diary provider uses high reasoning effort and a hash-bound
   diary_intelligence request purpose. It returns one strict JSON object. A Diary is
   omitted when the day contains only greetings, acknowledgements, status chatter,
   technical logs, or transactional流水. Otherwise the title is 4-12 Chinese
   characters and the body is a factual, coherent first-person “我” diary rather
   than a transcript.
5. At most three Memory and three User Model updates may be delegated per run. Every
   update must quote an exact memory_eligible owner USER_MESSAGE from the eligible
   GPT source set. Transient moods, one-off plans, technical tasks, and governance
   authorizations are rejected. Memory is created as an active immutable revision.
   A belief is created as candidate and activated only through the existing immutable
   activated transition in the same transaction. Both retain exact Event
   provenance and this Product Owner authorization reference.
6. Private/local conversation never uses this delegated update path. Its Memory or
   User Model candidates continue through explicit owner review.
7. Every successful Diary run may return fixed quality-review enums. The original
   14-day automatic instruction mapping is superseded by the owner's later manual
   review workflow in ADR-0035, implemented in the 2026-09-05 routing repair.
   Flags and suggestions remain local review artifacts, not chat instructions on
   either provider. Existing review records and their source policies remain
   unchanged. Model text cannot change Core, edit code, alter Identity/policy,
   authorize tools, or create proactive contact.
8. A paired owner device may accept/reject/edit Memory candidates, correct/retract
   active Memory, propose a confirmed Memory into User Model review, and revise or
   transition a belief. It still cannot manage devices, product settings, privacy
   exports, workers, Strong Brain, source erasure, or other owner-primary operations.
9. Diary month typography uses a 12-color seasonal palette with contrast checked
   against the paper background. This is navigation styling, not semantic state.
10. Source erasure remains exact-event-only. Selecting one source Event closes over
    every Diary run that consumed it and all delegated Memory/belief derivatives of
    that run before removing its local/private references. No provider or Diary run
    may select an erasure source.

## Why it belongs in the final system

Daily reflection, private-source separation, owner-legible review, and correction of
repeated response defects are stable product responsibilities. They must remain
independent of one provider while preserving exact source and policy provenance.

## Alternatives considered

- **Keep deterministic phrase extraction:** rejected because it cannot turn a day
  into a coherent first-person reflection and continues to expose流水 structure.
- **Send the complete day, including private dialogue, to GPT:** rejected because it
  violates the active DataPolicy route and the owner's explicit private boundary.
- **Let GPT rewrite Memory/User Model without source quotes:** rejected because it
  would turn plausible synthesis into untraceable durable identity claims.
- **Let the quality review directly rewrite prompts or code:** rejected because model
  output cannot own HAVRE behavior hierarchy or governance.
- **Grant the paired device all owner-primary powers:** rejected because the owner
  authorized only the enumerated understanding-review operations.

## Consequences

### Benefits

- low-value流水 can disappear instead of becoming a Diary page;
- useful GPT-routed dialogue becomes a readable first-person daily reflection;
- private dialogue remains inspectable locally without being summarized in cloud;
- durable automatic understanding is quote-grounded and source-erasable;
- the paired iPhone can complete ordinary understanding review without gaining
  administrative or erasure authority;
- recurring response defects produce inspectable suggestions for owner-directed
  Codex implementation, without automatically changing later chat instructions.

### Costs and constraints

- a provider failure leaves a durable failed run and no partial Diary/Memory/belief
  writes;
- strict quote and durability gates intentionally miss some valid understanding;
- a source change creates a new run/revision instead of mutating prior evidence;
- the month palette is a researched product choice, not an official universal
  month-color standard;
- physical iPhone Safari/PWA behavior still requires owner-device validation.

## Validation

Fresh and in-place migration, direct-SQL attack probes, complete PostgreSQL-backed
regression, provenance audit, PWA contract, production readback, and remaining limits
are recorded in
[GPT Diary and paired review checkpoint](../GPT_DIARY_PAIRED_REVIEW_CHECKPOINT.md).

## Approval note

The Product Owner explicitly authorized implementation, owner-local production
activation, the narrow paired-device write list, and automatic GPT-source-derived
Memory/User Model updates. Formal acceptance of this ADR remains a separate decision.
No actual source erasure is authorized until the owner names the exact source Event.
