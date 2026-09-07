# ADR-0039: Personal Context Engine and shared evidence compiler

Status: **Implementation authorized by the owner's September 6, 2026 fresh-project
review request. Technical verification is recorded in the associated checkpoint;
long-term owner usefulness is not self-approved.**

## Context and authorization

The owner explicitly authorized inspection of the complete current system,
architecture changes justified by evidence, implementation, migrations, testing,
independent review and local commits without push. Existing Stage labels do not
limit this authorized work. The request preserves Identity, privacy, LOCAL_ONLY,
source preservation and erasure, owner control, Core authority over effects, and
separate model-promotion/training decisions. This ADR exercises that software
authorization; it does not approve new cloud disclosure or sensing.

The starting production database was at migration 0068. Content-free inspection
found 371 Events, one Episode, 15 active Memory heads, 11 belief heads, no Current
State snapshots, 50 Goals and 126 ContextPacks. In the latest 50 packs, 147 behavior
examples but only 16 episodic-Memory sections were admitted. These counts expose
selection imbalance; they do not independently establish that every omitted
Memory was relevant or every included Goal was wrong.

Code and reproduced defects established that:

- behavior examples consumed budget before shared experience;
- separate selectors mixed numerical importance with evidence authority;
- explicit raw-history recall could not see beyond seven days and 256 Events;
- generic recall words admitted unrelated recent Episodes;
- personal selection lacked a consistent current-turn as-of cutoff;
- expired understanding and re-extraction of an owner-corrected source could
  revive a rejected interpretation;
- corrected Memory retained provenance but its product source preview disappeared;
- delayed replies used a different budget/identity presentation from the main reply.

## Decision

The owner's later clarification makes every architecture name a hypothesis and
places actual experience and complexity cost first. Preserve persistent identity,
source history, correction and governed delivery with a replaceable reasoning,
understanding and language Brain. A strong cloud Brain with simpler continuous
history and direct source lookup remains a valid competing design; the measured
regressions do not establish that a multilayer engine is optimal.
It is not merely a vector database, a static user profile, or a larger prompt.
"Virtual infinite context" is a useful retrieval abstraction, not a promise of
lossless, unlimited or always-correct memory.

Keep the modular monolith and PostgreSQL/pgvector. No new graph database, agent
framework, external embedding service, sensing source or training pipeline is
introduced. New boundaries are implemented inside the existing architecture:

1. Raw Events and exact correction/erasure history remain canonical evidence.
2. Episodes and Memory revisions remain separate revisable projections. A summary
   must never replace its original source. Diary is a dated reading surface.
3. Indexed lifetime lexical candidates and bounded local semantic reranking can
   reconstruct concrete experience without converting every turn into Memory.
4. A small `PersonalContextCompiler` replaces duplicated allocation code with one evidence authority and whole-record
   budget mechanism for the main reply and delayed continuation.
5. Canonical Identity and existing owner-authorized experience guidance remain
   provider independent; examples are optional behavior calibration, not biography.
6. Existing Core, policy router, effect receipts, interruption limits and durable
   response lineage remain authoritative.

## Evidence authority

Instruction authority and factual authority are different. Constitution and Core
rules constrain behavior. Current explicit owner instructions govern this turn.
Recorded owner statements establish **what was said**, not automatically whether
another person's motives or an external assertion are true.

For personal facts, current correction and valid exact evidence take precedence
over older interpretations. Preserve recent raw owner/assistant exchanges as
whole request groups; retain topic-bearing concrete experiences; include relevant
Goal/state/calendar evidence only within its valid scope. Abstract User Model,
patterns and semantic generalizations have lower authority. OA70 is last and
optional. No evidence layer acquires permission to execute a side effect.

The compiler records budget and duplicate exclusions, keeps selected source
references, preserves policy composition, and does not truncate a record into an
apparently complete fact. Budget failure cannot become permission to send required
private material to the cloud.

## Retrieval and corrections

The Event search index is an owner-local, rebuildable derivative of existing text.
It is never a new canonical memory or a policy bypass. Runtime independently
checks owner, as-of, completion, route eligibility and source revocation. Exact
selected request pairs and nearby clarifications are reconstructed from Events.
Current head/validity checks remain necessary for derived understanding.

An unresolved pronoun does not create an entity identity. Several possible people
remain several possibilities. Ask a short grounded clarification if evidence does
not identify the intended person. No inferred person/project graph is promoted by
this decision. Pure paraphrase without a lexical anchor and very large histories
remain evaluation priorities rather than solved capabilities.

Re-extraction of the same source must not undo an owner correction. A genuinely
new owner statement can describe a changed preference; it is not permanently
blacklisted merely because similar words were once corrected.

## Identity and learning

Keep canonical Identity and values, existing experience guidance, and versioned
provider-neutral source references. Remove case-ID-specific behavior-selection
branches. Select at most three examples by current-turn relevance and general
dialogue behavior; earlier conversation may help rank but cannot force an
unrelated example. OA70's frozen source and authorization are unchanged, and all
70 prompt-exposed examples remain unsuitable as independent holdout evidence.

Fast personalization is source-preserving experience, correction and context
selection. Medium-speed improvement is owner-reviewed failure classification,
ranking and regression evaluation. Slow personalization uses separately approved
exact feedback revisions, datasets, candidate training, clean evaluation and
explicit promotion. This ADR does not authorize that slow training path.

## Product consequences

Keep one continuous Chat and dated Diary. Memory shows current wording, revision
and declared validity dates, follows exact provenance back to raw conversation,
and offers a direct return to that conversation. "Stop referring to this" is a
retraction, not a false claim that all raw source/backup history was erased.
Source expansion remains owner-qualified and read-only; it grants no model or
paired-device administration authority.

## Verification and rollout

Use source-bound counterfactuals for irrelevant context, corrections, ambiguity,
long-horizon recall, privacy, erasure and token budgets; inspect final provider
messages. Compare old and new implementations against the same constructed
fixtures. Those fixtures are regression evidence, not independent human-quality
or years-of-life evaluation.

Run the complete PostgreSQL-backed suite without skips in its existing two Python
environments, fresh/additive migrations, provenance audit, existing retrieval
benchmarks, synthetic real-provider requests, browser functional/visual checks,
and independent adversarial review. Freeze source during final verification.
Apply only additive tested migrations and restart the owner-local application
without changing model artifacts, privacy routing, device credentials or cadence.
No push or model promotion is permitted. The architecture name is provisional;
retain or remove each mechanism according to incremental product evidence, not
existing training/ML Systems investment.

Evidence and limits: [Personal Context Engine review and checkpoint](../PERSONAL_CONTEXT_ENGINE_REVIEW_2026-09-06.md).
