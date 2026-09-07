# ADR-0038: Audit-driven Daily Companion correctness and continuity

Status: implementation authorized by the owner's acceptance of the September 5
real-runtime audit and explicit continuous engineering/product workflow. Formal
product-quality acceptance remains with the owner.

## Decisions

- Goal transitions refresh an existing authorized commitment projection inside
  the same transaction as the lifecycle Event and reminder/fusion cancellation.
  They never create disclosure authority for a Goal that lacks it.
- A conservative completion fast path distinguishes task numbers, composite
  tasks, negation, future and third-person reports. Prior ContextPack inclusion
  alone is not proof of which task 'done' refers to. Ambiguity must not close a Goal.
- The existing source-quoted GPT-high Goal planner accepts natural owner-chosen
  objectives, not just command syntax. The model proposes; source/date validation
  and a single transaction own Goal/action/queue/receipt writes. Ordinary wishes
  and feelings may yield no action. No extra general-purpose agent or model.
- Typed wording corrections alone may suppress rejected wording in presentation;
  action receipts must preserve the current owner's actual words.
- Web is the one continuous Daily Companion Chat across devices. Its bounded
  recent Web Events share working history across storage session IDs. Cross-session
  supplementation of ordinary cloud chat admits only already cloud-eligible,
  completed GPT turns. Explicit LOCAL_ONLY chat may use owner-local Web history.
  API/CLI session behavior is unchanged. Owner, time and privacy qualification remain.
- Delayed continuation can follow an everyday personal discussion in Talk,
  Guide or Reflect. It reuses concrete, source-bound evidence from the originating
  reply's ContextPack, not an independent summary. The existing stop conditions,
  one-minute/30-minute cadence, two-beat limit, model and source policy remain.
- Deadline urgency alone does not admit an unrelated course Goal into smalltalk.
  Independent reminder delivery remains governed by the existing scheduler.
- GPT answer parsing preserves ordered completed message items and rejects
  inconsistent duplicate IDs. It still rejects all tool activity. Migration 0068
  admits this adapter version under the same exact model/effort/trust boundary
  and makes the terminal receipt constraint explicitly NULL-fail-closed.
- The existing Goal planner uses native Codex structured output. Nullable fields
  are all required by its strict JSON Schema; invalid schemas are invalid requests,
  not login failures. A longer first-person "should/need" reflection may enter
  semantic review without command words; no-action remains a valid result.
- Imported parenthesized due dates are metadata, not composite task components.
  Numbers alone do not identify a task. The exact audited owner completion report
  was reconciled through the existing append-oriented Goal transition, not erasure.
- Erasing a specifically selected source also removes delayed queues whose
  originating reply used that source or its derived Memory/Belief/State in context.
  Tests cover earlier shared history, not just the immediately preceding message.
- Application-only restart preserves existing credentials, paired devices,
  PostgreSQL and the local model. It does not provision a new trust boundary.
- Product UI exposes actionable state and source explanations, not internal
  contract terminology. Memory processing is real-time; five-to-five Diary is
  a separate daily workflow. UI validation uses isolated synthetic data.

## Unchanged boundaries

Canonical Memory/User Model semantics, privacy classes, LOCAL_ONLY, training
eligibility, source-erasure authority, model promotion and cloud providers are
unchanged. No owner data cleanup or inferred belief rewriting follows from this
ADR. Past source events and revisions are retained. New raw debug archives and
automatic model-quality judgments are not introduced.

## Evidence

See `docs/DAILY_COMPANION_QUALITY_CHECKPOINT_2026-09-06.md` for test/runtime/review
evidence and explicit limits. This ADR does not certify repeated owner usefulness.
