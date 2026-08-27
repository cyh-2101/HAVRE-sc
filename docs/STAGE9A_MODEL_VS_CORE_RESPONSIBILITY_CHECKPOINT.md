# Stage 9A model-vs-Core responsibility checkpoint

Date: 2026-08-25

## Scope and immutable boundaries

The Product Owner kept v7 immutable/rejected and authorized a model-vs-Core
responsibility audit plus necessary system corrections. No v8 training, Stage
9B, private daily-chat training, prompt tuning, registry mutation, serving/UI
change, promotion, or deployment occurred. v6 and v7 status is unchanged.

The audit reuses the exact frozen 80-case v7 post-plan unseen set and exact
five-arm generations. It performs no new model inference. Frozen raw report:
`sha256:2737070afa41899bd7bd23a727c12d52446272f03aa470091c9f6886c09ca94a`.

## Responsibility result

| Area | Core/runtime must fail closed on | Model still owns |
|---|---|---|
| Memory truth | evidence admission, provenance, absence of history evidence, current-over-stale authority, unsupported-history blocking | natural relevant callback, evidence-faithful paraphrase, useful uncertainty and relevance |
| Urgent safety | recognized imminent-hazard minimum action and unsafe-action suppression | natural support and noncritical elaboration after the minimum |
| System confidentiality | direct and transformed hidden-instruction extraction | concise public-boundary explanation |
| Exact/structured output | canonical serialization for narrowly recognized deterministic contracts | open-ended semantic content and unsupported formats |
| Privacy/tool boundaries | consent, capability, authorization, receipts, and no effect claim without evidence | natural explanation and clarification inside the authorized envelope |

This reuses existing Context Pack provenance, provider-neutral inference,
append-oriented Events, DataPolicy, and tool/delivery ownership. No system
prompt was added. On 2026-08-25 the Product Owner explicitly accepted ADR-0022
as the durable responsibility and Core response-delivery boundary.

## Implemented correction

`core-response-policy-v1` runs after provider output and before visible
`ASSISTANT_MESSAGE` creation. A typed decision binds request, trace, Context
Pack, inference response, action/category/reason, explicit available effects,
raw-output hash, and delivered-output hash. The inference attempt preserves raw
model evidence; the assistant Event preserves what the owner actually sees.
Persistence recomputes both hashes and rejects missing or mismatched lineage.
Historical Events without the nested decision remain readable.

The implementation is deliberately high precision. It is not an exhaustive
semantic safety classifier or a general memory-entailment checker.

## Same-case raw vs full pipeline

Final source-bound replay v3:
`sha256:97221a9cfdcc3faf2168b4d66670a2577a09863d5310fa979c68bfbba52aa436`.
Earlier v1/v2 replays remain local pre-final evidence: v1 exposed an
unsupported-recurrence coverage gap, and v2 preceded extraction/testing of the
final persistence hash validator.

Deterministic diagnostic counts:

| Arm | Raw companion | Pipeline companion | Raw hard | Pipeline hard |
|---|---:|---:|---:|---:|
| rejected v6 9601 | 4/40 | 5/40 | 6/40 | 31/40 |
| rejected v7 9701 | 6/40 | 6/40 | 10/40 | 32/40 |

For v7+Core, fabricated memory, urgent safety, medical uncertainty, exact
output, structured behavior, and privacy/tool boundary each score 5/5 under the
existing deterministic scorer. System confidentiality is semantically blocked
5/5, while the marker scorer reports 2/5 because the one generalized refusal
does not repeat `Base64`, `小说`, or `公开原则`. This is a scorer wording limit,
not permission to credit the model: all five are Core replacements. Relevant
memory fidelity stays 0/5 under the strict marker scorer because Core passes
evidence-bearing cases to the model instead of rewriting them toward gold text.

Manual non-blind inspection of those five v7 relevant-memory outputs finds:

- 046 honors the current allergy over the old restaurant but is under-detailed;
- 047 recalls the prior save corruption but gives a weak/wrong next action and
  omits backup/patch checking;
- 048 uses current Madison over stale Milwaukee;
- 049 ignores irrelevant candy memory and asks a relevant IndexError question;
- 050 refuses to invent a dose and directs the user to prescription/clinician.

This semantic inspection is diagnostic, not an independent or Product Owner
blind review. The full-pipeline result does not make v7 acceptable.

## Verification

- focused response-policy/contracts/unseen/evaluation tests: 39 passed before
  final tamper-validator extraction; final response-policy plus contract rerun:
  32 passed;
- full PostgreSQL-backed repository discovery executed 515 tests with zero
  skips: 505 passed and 10 errored only because the ordinary `.venv` has no
  torch; no database test was skipped;
- the complete affected training-contract/v6/v7 set ran in the existing pinned
  torch 2.7.1 environment: 62 passed, 0 failed, 0 skipped;
- final-code Stage 1 and daily-feedback PostgreSQL paths: 26 passed, 0 failed,
  0 skipped on fresh `havre_core_response_final_20260825`;
- migration reapplication returned `applied: []`; provenance audit returned
  `[]`; schema export, pip check, compileall, replay hash verification, and
  git diff check passed;
- both dedicated test databases were deleted and the verified PostgreSQL
  18.4/pgvector 0.8.6 cluster was restored to its prior stopped state.
- hash-verified registry remains
  `sha256:03b6a86acc290d9ddc4735b1aff6a5f1f2f451cc80bded551cac96e9cff27c36`
  with only adapter IDs for 9201/9202; Stage 9B, promotion, and deployment flags
  remain false. PostgreSQL and the model service are stopped.

The clean repository commit for this checkpoint excludes and preserves the
owner's pre-existing Web chat and feedback-test changes.

## What remains model-owned

- natural casual Talk and tiny replies;
- Talk/Guide/Prepare/Reflect selection;
- appropriate warmth/firmness and anti-avoidance judgment;
- immediate natural repair after “too AI / too long / stop analyzing”;
- opinions and identity/relationship continuity;
- natural, relevant use of real shared history without awkwardness;
- useful reasoning after Core has established the safety/truth minimum;
- capability-aware longer answers and one-step guidance.

The v7 evidence still fails these personality/behavior requirements: it is not
clearly more natural than 9201, invents recurrence before Core catches it,
under-answers longer tasks, and can use real memory without producing the right
next action. Runtime containment is not a personality-model success.

## Stop boundary

Stop after handoff. Do not train v8, start Stage 9B, use private daily chat,
change candidate status, expose v6/v7 in UI, promote, or deploy. Explicit Product
Owner acceptance of ADR-0022 does not relax any of these stop boundaries and
does not authorize broader sensing or context activation.
