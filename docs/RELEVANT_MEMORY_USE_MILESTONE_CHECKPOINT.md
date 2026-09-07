# Relevant Memory Use Focused Milestone Checkpoint

Date: 2026-08-26
Status: **Implemented and evaluated; system correction retained, targeted candidate retained as unregistered evidence, behavioral acceptance not reached**

## Authorization and stop boundary

The Product Owner authorized a focused inspect → diagnose → implement → replay →
if necessary narrow training → evaluate → independent review → document → commit
milestone for natural use of legitimately admitted Memory.  The authorization did
not permit changing the rejected status or bytes of v6/v7, Stage 9B, private daily
chat or OA70 training, registry/serving/daily-use binding changes, promotion, or
deployment.  Those boundaries remained unchanged.

## Root cause by layer

1. **Retrieval:** the gated retriever usually returned the intended synthetic
   Memory with exact owner/request/trace/query provenance.  A missing contract
   invariant allowed externally constructed results to carry non-contiguous ranks
   or ascending/non-finite scores; both the result contract and Context Builder now
   reject that shape independently.
2. **Admission:** ContextPack correctly revalidated eligibility, thresholds,
   content hashes, uniqueness, and lineage.  The primary failure was not missing
   admission.
3. **Final model input:** admitted Memory was emitted as raw, separate system
   messages.  It lacked a versioned explanation of optional use, current-message
   precedence, partial evidence, silent influence, and semantic-scope preservation.
   Conversation history was also budgeted before retrieved Memory, so a long recent
   session could consume the budget before a relevant item.
4. **Seen but ignored:** frozen candidates often received the correct item but
   answered generically.  The old strict keyword scorer detected some omissions but
   could both undercount useful paraphrases and overcount semantically wrong replies.
5. **Connection skill:** after production-aligned presentation, candidates still
   sometimes converted one event into a trait/repeated accusation, completed an
   unknown identity, or failed to make a tentative bridge from history to a short
   emotional message.  This is model-owned behavior under ADR-0022.
6. **Measurement:** the replacement suite separates paired variants, multi-Memory
   interference, and casual regression, exposes seven review dimensions, and labels
   deterministic results as a surface/property screen requiring semantic review.

## System correction

- `context-builder-v9` budgets correctly gated Memory before optional older
  conversation history while reserving a bounded share for recent conversation.
  It accounts for the complete presentation overhead and records whether Memory was
  excluded to preserve recent conversation.
- `context-presentation-v2-natural-memory-linking` creates one leading system
  message containing identity, other admitted personal context, and ordered Memory
  evidence.  Guidance says that retrieval is not a requirement to mention history,
  current input wins, partial identity/event evidence requires clarification,
  irrelevant items are ignored, useful context may remain silent, and callbacks may
  not be forced or narrated as “memory”.  It also requires exact preservation of
  people, time, frequency, and causal scope and recommends a brief tentative bridge
  rather than diagnosis for short emotional turns.
- Provider requests retain all original ContextPack source references and record the
  presentation version.  ContextPack remains the admission/provenance record; the
  renderer changes only provider-facing presentation.

The final legacy-versus-v2 system-only replay is
`evals/reports/relevant_memory_20260826/system-presentation-replay-v3-final.json`,
content hash
`sha256:470c9370e3abc426754a59a0624b5a81e5da0c48029975fa202c87289801f539`.
The report is PUBLIC synthetic and changes no candidate state. Independent review
required every applicable semantic dimension to pass:

| Arm | Legacy | v2 | Delta |
|---|---:|---:|---:|
| 9201 | 5/15 | 9/15 | +4 / +26.7 pp |
| 9202 | 8/15 | 12/15 | +4 / +26.7 pp |
| rejected v7 9701 | 8/15 | 11/15 | +3 / +20.0 pp |
| aggregate | 21/45 (46.7%) | 32/45 (71.1%) | +11 / +24.4 pp |

By variant, relevant rose 2/9→4/9, irrelevant 3/9→8/9, none stayed
7/9→7/9, stale 3/9→5/9, and partial 6/9→8/9. Multi-Memory rose
only 1/9→3/9. Casual outputs were byte-identical across presentation arms, so
this replay observed no casual-chat delta while providing no broad no-regression
claim.

## Focused evaluation design

`relevant-memory-use-paired-v1` contains 15 paired cases (three identical-user
messages × relevant / irrelevant / none / stale-conflicting / partial), three
multi-Memory cases with one useful item among distractors, and five casual cases.
The post-plan unseen suite contains 20 paired cases (four groups), four multi-Memory
cases, and eight casual cases.  It is exact-bound to the closed training-plan hash,
and tests prove that its user messages and Memory strings have no exact overlap with
the train or validation source.

The scorer checks surface properties only and explicitly leaves naturalness,
usefulness, provenance truth, fabricated familiarity, forced callback, ignored
relevant history, and current-message precedence to paired semantic review.  No
single composite is treated as release evidence.

## Narrow training experiment

Presentation replay isolated a remaining model bottleneck, so the authorized
training option was used.  The experiment is a continuation from the immutable
rejected v7 adapter rather than a fresh base: this directly tests whether the v7
lineage can gain the missing Memory-use behavior with the smallest parameter and
data change, while leaving v7 untouched.  It is not a continuation from 9201/9202
because the Product Owner's clarified question was whether v7 could be improved;
9201/9202 remain comparison and daily-path arms.

- Candidate: `havre-stage9a-memory-use-v1-seed-9801`
- Plan:
  `sha256:7873d3236f01a3ca422e246e18edc2bc601c7a8dd37052bb4b26cb07909f9ce7`
- PUBLIC synthetic source: 45 train / 20 validation; ten complete five-way
  counterfactual groups plus 15 casual-regression rows
- Dataset manifest:
  `sha256:48b5603139c078dfea31f6b52b0eda2b02d967a027f08336fdc4e5d7ef6da1e8`
- Rendered manifest:
  `sha256:cd8e0b3f69fc456ca3452052238948eadedd710d35996c319b1724beb58a7b73`
- Training input presentation was sealed as
  `context-presentation-v1-natural-memory`.  The later production v2 wording is
  intentionally not allowed to rewrite the completed experiment's dataset or plan
  hashes; candidate verification reproduces the sealed v1 renderer exactly.
- Objective: chosen-response supervised suffix only; rejected responses are retained
  as non-optimized preference evidence
- Exclusions: no user data, daily chats, OA70, safety, confidentiality, exact-output,
  promotion, or Stage 9B objective
- Run: seed 9801, one epoch, 45 optimizer steps, learning rate `5e-5`
- Validation loss: `2.96728640794754` → `2.66647832393646` (training-health evidence,
  not behavioral acceptance)
- Wall time: `125.1777 s`; peak VRAM: `10,984 MiB`
- Adapter SHA-256:
  `sha256:a7cebca09f24b75ea0081d271e747be9c5a6464d43a8c602ed8bd15f15c548c9`
- Adapter manifest:
  `sha256:6bb9c3b71614d9dbe7b4c6fdf979c0cd341a9884c01dfc7ea1bd7237f44cdee9`
- Training report:
  `sha256:02be890071992f7d0dc8c8d6bbc01701eebc92e6841fe6bf7cd72e95235b8284`

The candidate is explicitly `registered=false`, `served=false`,
`promoted=false`, and `deployed=false`.  The sealed registry remains
`sha256:03b6a86acc290d9ddc4735b1aff6a5f1f2f451cc80bded551cac96e9cff27c36`
and contains only unchanged 9201/9202 candidate entries.  v7 remains rejected.

## Final behavioral result

The post-plan unseen v2 report is
`evals/reports/relevant_memory_20260826/post-plan-unseen-replay-v2-final.json`,
content hash
`sha256:6420f9b48fabbed995650d2ccbfff7f8bc68012e824cc126aabf53c1d8525cb6`.
Independent strict semantic review requires every applicable dimension to pass:

| Arm | Paired | Relevant | Irrelevant | None | Stale | Partial | Multi | Casual | Total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rejected v7 9701 | 18/20 | 3/4 | 4/4 | 4/4 | 3/4 | 4/4 | 1/4 | 5/8 | 24/32 |
| 9202 | 14/20 | 3/4 | 3/4 | 4/4 | 3/4 | 1/4 | 3/4 | 6/8 | 23/32 |
| memory-use 9801 | 16/20 | 3/4 | 3/4 | 4/4 | 3/4 | 3/4 | **4/4** | 5/8 | **25/32** |

9801 is the strongest arm on this focused suite by one case over its v7 parent,
principally because multi-Memory selection improved from 1/4 to 4/4.  It did not
improve casual aggregate pass count (both 5/8).  It still fabricated familiarity
or merged partial identity in two paired cases, misapplied stale history in one,
and had three casual failures.  The owner-provided representative diagnostic still
fails: it changes “projects were often completed by AI, so little was learned” into
the stronger accusation “you treated AI output as your ability.”  The final seen
diagnostic report is
`sha256:1f8ac7d3fc72d0449a60ce083b42b8828c86b367852428823e7988c95378d6ab`.

Therefore this milestone does **not** accept natural relevant-Memory use as solved.
The system correction is retained because it fixes a real runtime mismatch and
improves evidence presentation without forcing callbacks.  Candidate 9801 is useful
negative/partial-positive evidence, not a daily-use or release candidate.  No second
candidate was tuned to the now-seen diagnostic suite.

## Candidate and daily-use decision

- **Focused Memory-use evidence:** 9801 is the strongest continuation to inspect
  next, but the margin is small and the canonical failure remains.
- **Existing-candidate relevant-Memory evidence:** 9202 is the strongest existing
  arm on the final system-only paired suite (12/15 versus v7 11/15 and 9201 9/15).
  This focused result does not override its broader prior evidence or lifecycle.
- **Overall daily-use evidence:** this milestone did not rerun v7's full 80-case
  hard/model-owned regression on 9801, so it cannot establish overall daily-use
  suitability.  The existing owner-local 9201 binding remains unchanged and is the
  only current daily-use choice; this is continuity of the prior decision, not a new
  claim that 9201 passed the focused suite.
- No promotion, deployment, registration, serving, status, UI, or binding change is
  authorized or performed.

## Independent review and verification

Independent read-only review found P1=0 and implementation P2=0.  It identified one
evidence boundary: claiming 9801 overall daily-use readiness would require the full
broader regression, which was not run.  This checkpoint keeps the conclusion focused
and therefore does not cross that boundary.

Verification used the dedicated disposable PostgreSQL database
`havre_memory_use_final_20260826`, migrated from 0001 through 0037.  The complete
repository discovery contained 537 tests with zero skips: 527 passed in the main
environment and the exact ten torch-dependent tests passed in the pinned Stage 9A
environment.  This is a combined designated-environment result, not a claim that
one interpreter contains both dependency sets.  The final focused Memory/retrieval
run passed 26/26; the sealed dataset tests passed 5/5; `pip check`, `compileall`, and
`git diff --check` passed; and `audit-provenance` returned `[]`.

The required retrieval benchmark completed after correcting its async cleanup path.
For `retrieval-r1-vector-gated-v2`, recall@5 and recall@10 were 1.0, MRR was
0.9, wrong-memory rate was 0.375, duplicate/stale/should-not-surface rates were 0,
provenance completeness was 1.0, p50 latency was 1.463 ms, p95 latency was
2.032 ms, and error rate was 0.  The report file hash is
`sha256:5c267308ac74cb6fd7346af2595cc85a54c638f58d3e2fd2b05f95dfe73c9606`;
its contract content hash is
`sha256:002f0d7c4f76e72772bfc8bba777613e1bb95b983c1179483e7b251ec9a2ab6f`.
Latency is environment evidence only; deterministic quality metrics are the
behavioral comparison.  The disposable database was then dropped (verified absent)
and the repository-owned PostgreSQL cluster was restored to its prior stopped state.
