# Stage 13 Practical Utility Gate

Status: active Stage 13 acceptance standard

## Purpose

Stage 13 exists to make HAVRE useful enough that the owner genuinely chooses to use it. Architecture cleanliness, passing tests, benchmark averages, natural wording, and larger parameter counts are necessary evidence at most; none of them is the product outcome.

The non-substitutable owner question is:

> For the conversations and decisions I actually care about, does HAVRE reduce my effort and give me a better result than opening a generic chat product and explaining myself again?

A candidate that fails this question is not promotable even if its aggregate score improves.

## Utility dimensions

Every Stage 13 candidate must be reviewed on the following dimensions.

1. **Understands the whole turn**
   - answers every material request;
   - resolves references from recent conversation correctly;
   - does not mistake topical similarity for a request to use old Memory;
   - asks only for information that can materially change the answer.

2. **Produces a usable result**
   - gives the conclusion, deliverable, or first executable step early enough to act on;
   - makes a concrete recommendation when the owner needs a decision;
   - includes timeboxes, stop conditions, rollback points, or verification steps when they matter;
   - avoids generic checklists that transfer the thinking burden back to the owner.

3. **Uses continuity naturally**
   - preserves short-term conversational continuity;
   - retrieves episode, preference, or long-term Memory only when the current turn needs it;
   - uses relevant history without announcing a forced memory callback;
   - never treats an inferred summary as a confirmed user fact.

4. **Is truthfully decisive**
   - distinguishes observed facts, likely inferences, unknowns, and owner choices;
   - does not invent duration, reversibility, compatibility, prices, or data-safety guarantees;
   - identifies the one missing fact most likely to reverse a recommendation;
   - prefers a reversible bottleneck test before costly training or platform changes.

5. **Communicates with proportional depth**
   - simple questions may be brief, but completeness is never sacrificed to a fixed token target;
   - complex decisions may be long, but the useful answer is not buried after generic exposition;
   - tone remains warm, strong, direct, and stable without emotional imitation or mood simulation;
   - repetition, therapy-like filler, canned empathy, and report-shaped padding count as defects.

6. **Has acceptable interaction cost**
   - first-token and full-turn latency remain tolerable for the use case;
   - the owner should not need repeated corrections to obtain an actionable answer;
   - local privacy and continuity benefits must be large enough to justify any quality or latency cost versus a cloud chat baseline.

## Hard failures

The following cannot be averaged away by strengths on other fixtures:

- omitting a material part of the request;
- a confident unsupported fact that changes a decision;
- stale or wrong-subject Memory overriding the current message;
- disclosure outside the authorized privacy boundary;
- truncation before the promised recommendation or deliverable;
- recommending training, purchase, deployment, or migration before testing the actual bottleneck;
- requiring the owner to restate information that HAVRE had valid, admissible access to;
- a result that the owner would discard and redo in a generic chat product.

## Evidence ladder

Evidence must be reported at its real level:

1. contract and unit tests;
2. deterministic counterfactual fixtures;
3. raw-model candidate replay;
4. full ContextPack, Core, and delivered-output replay;
5. blinded semantic review against the current baseline and a strong external reference;
6. owner shadow use on real, consented conversations;
7. explicit owner promotion decision.

Passing a lower level never implies a higher one. In particular, raw-model quality does not prove full HAVRE quality, and public/synthetic evaluation does not authorize private conversation disclosure.

## Minimum Stage 13 comparison set

Each serious model or architecture candidate must include:

- independent question with no Memory retrieval;
- explicit continuation needing recent context;
- relevant, irrelevant, absent, stale, partial, and wrong-subject Memory counterfactuals;
- a multi-request decision turn;
- an uncertain factual turn where invention would be harmful;
- an action-planning turn with a deliverable and stop condition;
- a natural supportive conversation turn;
- a hardware or purchase decision requiring current facts;
- at least one owner-selected real conversation after the synthetic gate passes.

## Promotion rule

A candidate may be presented for promotion only when:

- no hard failure remains in the required comparison set;
- it improves practical usefulness rather than only style or benchmark score;
- the improvement survives repeated runs and the full delivery path;
- latency, memory, disk, and operational costs are measured on the owner's machine;
- rollback is prepared and verified;
- the owner has compared blinded outputs and explicitly chooses the candidate.

No automatic scorer, teacher model, or coding agent may make the final promotion decision.

## OA70 later-case dialogue-structure review

On 2026-09-03 the Product Owner permitted inspection of the later OA70 examples
to diagnose why a technically stronger Replyer could still feel like a
question-answer bot. Cases 21-70 were not added to runtime prompts, training,
tuning, or Memory. Their titles, turn structure, and reference continuations
show five requirements that the practical gate must test explicitly:

- respond to the immediately preceding conversational move instead of
  restarting the whole topic;
- carry forward small local facts and repair uncertainty without fabricating a
  complete recollection;
- vary pressure across turns: one light invitation may be useful, repeated
  pressure after a refusal is not;
- recognize ordinary sharing, teasing, silence, celebration, disagreement,
  and companionship as conversation, not as requests for a plan;
- let a governed proactive opening become an ordinary multi-turn conversation
  once the owner replies, while keeping trigger/send authority in Core.

The active chat surface is still reactive turn-taking: it produces one reply
for one owner message. Proactive Core can add a separate assistant-initiated
opening when a durable trigger is authorized. Together they can form a normal
conversation, but green endpoint tests do not prove that the model consistently
maintains the right local conversational stance across several turns.

## External reviewer boundary

GPT-5.6-sol in the current Codex task may help the engineering loop by:

- classifying failures;
- proposing minimal changes;
- generating PUBLIC synthetic regressions;
- reviewing traces and candidate outputs that are already permitted to leave the local boundary;
- recording evidence and rejecting unsupported claims.

It is not a HAVRE runtime dependency, may not silently receive LOCAL_ONLY conversations, may not mutate Identity or Memory, and may not continuously self-train or promote a model. Private review requires a separate explicit owner decision and an approved disclosure path.

## 2026-09-03 practical companion correction

ADR-0033 implements a narrower, owner-legible product boundary around the gate:
stable owner statements become reviewable Memory proposals; confirmed Memory may
propose but never auto-activate a User Model belief; Diary v3 retains selected lived
facts rather than authorization/import mechanics; and the mobile conversation surface
uses adaptive reply shape and contained 390 px geometry. Exact technical and
production-browser evidence is in
[`PRACTICAL_COMPANION_UX_CHECKPOINT.md`](PRACTICAL_COMPANION_UX_CHECKPOINT.md).

This correction removes reproduced product defects but does not close the Practical
Utility Gate. Formal ADR-0033 review, repeated owner conversation, physical iPhone
behavior, and subjective comparison with a generic chat product remain higher-level
evidence.
