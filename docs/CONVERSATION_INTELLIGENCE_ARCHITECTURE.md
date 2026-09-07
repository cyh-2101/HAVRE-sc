# Conversation Intelligence Architecture

## Current shared context path (2026-09-06)

ADR-0039 updates the implementation described below. Context Builder v17 and
continuation v5 share a typed `PersonalContextCompiler`; factual evidence authority
is distinct from instruction authority and numerical ranking. Raw request groups
and topic-bearing experience receive budget protection before abstract User Model
and optional OA70. Current owner fact corrections/retractions accompany selected
old sources. Manual Strong Brain preserves its exact approved disclosure snapshot
and may not silently retrieve additional private context.

Raw recall v2 adds lifetime lexical candidates and bounded local semantic scoring,
with explicit source/version references and exact excerpt offsets for long Events.
DataPolicy, owner isolation, completed-turn admission and source revocation precede
use. Canonical Identity plus existing experience guidance stay provider independent;
Diary follow-up wording uses that identity without adding contact frequency.
Continuation checks source freshness before planning and inside final delivery.

The [fresh review](PERSONAL_CONTEXT_ENGINE_REVIEW_2026-09-06.md) is the current
implementation/evidence record; older algorithm descriptions below are historical.

Status: **Accepted by ADR-0027; Stage 13A is implemented and verified, Stage 13B-C evidence remains in progress, and ADR-0030's DataPolicy-driven dual Replyer is implemented with technical routing and lineage evidence. Practical conversational usefulness remains unproven pending repeated owner use.**

Authority: [`MASTER_PLAN.md`](../MASTER_PLAN.md),
[`ARCHITECTURE.md`](ARCHITECTURE.md), ADR-0022, ADR-0026, ADR-0027, ADR-0029,
and ADR-0030. This
document explains the conversation path; it does not weaken Core, privacy,
training, or promotion gates.

## 1. Objective

HAVRE should understand the complete current turn, maintain short- and long-term
continuity, answer at the length the meaning requires, and express one stable
warm/strong identity. It should not become verbose because it has more context or
shallow because a global “be concise” instruction wins over the actual request.

The architecture therefore separates four questions:

1. What must this turn accomplish?
2. Which prior evidence, if any, is needed?
3. Can the selected Replyer produce a good answer?
4. Is the answer safe, truthful, authorized, and durably deliverable?

## 2. Runtime path

```text
USER_MESSAGE Event
    |
    v
Turn State
  recent dialogue + current turn + confirmed response constraints
    |
    v
Turn Contract (ResponsePlan v2, deterministic, before retrieval)
  mode | must_address | memory_need/query | decision | depth | stance | uncertainty
    |
    +-- memory_need=none ---------> explicit empty RetrievalResult
    |
    `-- possible/required --------> Memory Broker
                                      query -> rank -> filter -> exclusions
    |
    v
Context Compiler (ContextBuilder + presentation)
  Identity Kernel + Turn Contract + admitted recent/personal/Memory evidence
    |
    v
DataPolicy Router
  cloud-eligible PUBLIC/NORMAL -> authenticated owner-local Codex CLI GPT-5.6-sol
  cloud-ineligible or stricter -> exact unadapted local Qwen3-8B
    |
    v
Replyer (one provider-neutral branch, exact route lineage)
    |
    v
Response Coverage Evidence
  obligations covered? requested decision present? incomplete/truncated?
    |
    v
Core Response Policy
  privacy | provenance | safety | hidden instructions | tool/effect truth
    |
    v
ASSISTANT_MESSAGE Event + complete evidence chain
```

No step may silently borrow authority from a later step. Retrieval does not decide
that Memory is relevant, the Replyer does not decide privacy, and a fluent answer
does not approve its own delivery or promotion.

## 3. Turn State and Turn Contract

Turn State contains only evidence already available before durable Memory search:

- the exact current user turn;
- bounded recent dialogue from the same session;
- active owner-reviewed response constraints;
- confirmed communication preference; and
- stable Identity versions and request/owner/trace lineage.

`ResponsePlan v2` is the current Turn Contract. It is deterministic and hash-bound.
Its obligations contain untrusted user text and are escaped before provider-facing
rendering. Its control fields are system-owned. `decision_requirement` distinguishes
“define criteria” from “recommend one now,” preventing both indecision and
premature prescription.

The contract is intentionally small. It is not a hidden chain of thought, a user
profile, a mood model, an authorization, or a place to store Memory.

## 4. Memory Gate and Broker

The gate is evaluated before retrieval:

- `none`: do not search durable Memory; persist an empty retrieval result so the
  evidence chain remains complete;
- `possible`: retrieval may help, but a relevant candidate is optional;
- `required`: the user explicitly relies on prior shared context; retrieve, and if
  the decisive detail remains unavailable, the Replyer must ask rather than invent.

The broker returns evidence, never instructions. It preserves candidate score,
source refs, policy, exclusions, version, and latency. Context admission separately
checks owner/request/trace binding, minimum relevance, current-message precedence,
privacy, duplicates, and token budget.

Memory layers remain distinct:

| Layer | Source | Default use |
|---|---|---|
| Working dialogue | Recent raw Events in this session | Always preserve continuity within budget |
| Episode | Reviewed source-linked summary of a completed session | Retrieve when the current turn refers to that episode |
| Communication preference | Owner-reviewed stable response constraint | Admit narrowly; never treat it as biography |
| Long-term Memory | Reviewed semantic/pattern/progress revision | Query only through the gate and relevance checks |

Raw chat is not automatically long-term Memory. A summary is not a confirmed fact.
Retrieved evidence is not a command to mention it.

## 5. Context Compiler

The compiler has two auditable stages:

1. `ContextBuilder` selects and budgets typed sections, retaining explicit
   inclusion/exclusion and source evidence.
2. the presentation renderer converts only admitted sections to provider messages.

Required ordering is Identity/Turn Contract/active owner constraints, admitted
personal evidence, relevant Memory evidence, ordered recent dialogue, then the
current user turn. Provider-facing identity text should be the smallest complete
version that preserves the fixed Identity; reducing it is a separately measured
causal change, not a silent rewrite.

## 6. Replyer and coverage

The Replyer owns natural language, full meaning, judgment, warmth/firmness, and
evidence-faithful use of context. It does not own privacy, Memory lifecycle, tool
effects, or model promotion.

ADR-0030 makes Replyer selection deterministic from the completed ContextPack's
effective policy. Cloud-eligible PUBLIC/NORMAL uses ADR-0029's isolated no-tools
GPT branch. Cloud-ineligible PUBLIC/NORMAL and every PRIVATE,
HIGHLY_PRIVATE, or LOCAL_ONLY pack use the exact attested local Qwen3-8B with no
HAVRE adapter. The Router, not either model, records eligibility and selection.
Cloud authorization metadata is branch-specific and must never reach the local
request.

This policy does not infer sensitivity from prose and has no semantic sensitivity
classifier. It consumes explicit and derived DataPolicy. It also does not
silently use another provider after failure or capacity rejection. The authorized
local llama.cpp runtime profile's 8,192-token total-context cap is a hard input to
Context compilation/eligibility; it is not a claim about Qwen3-8B's intrinsic
capacity. Exceeding it cannot permit cloud or deletion of required stricter
evidence.

A later NORMAL turn cannot disclose prior stricter conversation merely because
the composer default changed. The compiler either keeps the effective pack local
or establishes an owner-visible cloud-safe context boundary that excludes the
stricter history. Current tests prove the no-cloud boundary when required stricter
context is present; whether the resulting continuity feels useful remains an
owner-evaluated practical question.

Both Replyers use the same Turn Contract, retrieval gate, ContextPack, provider-
neutral inference contract, Core response policy, and durable assistant Event
path. The former per-response Strong Brain/Strong UX choice is retired; it does
not select a model, and its guarded legacy endpoint is compatibility surface only.
Real synthetic probes have returned through both branches. A current GPT probe
observed 11,824 prompt tokens and an earlier GPT-only probe observed 10,818;
neither observation defines fixed overhead, model capacity, or answer quality.

The first coverage implementation is evidence-only. It evaluates:

- every `must_address` item;
- a present recommendation when explicitly required;
- material uncertainty and reversal evidence;
- truncation/incomplete endings; and
- contradictions with current-turn constraints.

A future repair may run at most once and must preserve both raw attempts. It may
not create an open-ended Planner/Replyer loop. Until that slice is verified, a
coverage failure blocks candidate acceptance rather than silently rewriting the
owner-visible reply.

## 7. Core and evidence plane

ADR-0022 remains unchanged. Core owns deterministic hard boundaries and delivery;
it is not a general prose editor. Each evaluated turn must be reconstructable from:

```text
input Events
-> Turn Contract
-> RetrievalRequest/Result or explicit empty result
-> ContextPack and provider messages
-> route/runtime/model attestation
-> raw completion
-> coverage evidence
-> Core decision
-> delivered response
-> review provenance
```

Passing application tests proves this chain and its policies, not that the answer
feels human or useful. Candidate conversation quality needs semantic and owner
review.

## 8. External engineering loop

The Codex development agent remains an engineering collaborator outside HAVRE:

```text
authorized evidence
    -> failure classification
    -> one causal change
    -> focused regression
    -> frozen-suite rerun
    -> full-stack A/B
    -> recommendation to owner
```

It may implement and test reversible changes, but it does not approve its own
output, automatically learn from the owner, or mutate Identity, Memory, or
policy. External review defaults to PUBLIC synthetic evidence. Separately,
ADR-0029 uses GPT-5.6-sol as the owner-local runtime Replyer for eligible
ordinary chat. ADR-0030 separately selects the exact local Qwen branch for
non-GPT-eligible or stricter packs. The isolated GPT process sees only the
bounded canonical HAVRE request; it is not the development agent's
workspace/tool session and is not the system of record. Neither runtime may
approve its own route, policy, Memory, or release state.

## 9. Model strategy

- Keep the exact unadapted Qwen3-8B as an attested diagnostic/comparison control.
  ADR-0030 also authorizes that same artifact as the owner-local privacy Replyer,
  and the dual-route mechanics now have technical evidence. This is not promotion
  or a claim that 8B is generally good enough.
- Retain Qwen3-14B Q4_K_M as a rejected comparison control. It improved several
  8B failures, but the Turn Contract v2 replay added hard uncertainty/truncation
  failures and did not meet the practical-utility gate.
- Do not train another 8B until the same full-stack evaluation proves a narrow,
  trainable residual rather than a base-capability or orchestration defect.
- Evaluate the pinned Qwen3.6-35B-A3B Q4_K_M candidate through the existing
  isolated llama.cpp boundary before adding a new inference runtime. Only if raw
  quality passes and speed is the remaining bottleneck should FreeToken/WSL2
  become a separate runtime experiment. Parameter count and advertised
  tokens/second are not quality or fit evidence.

## 10. Stop boundaries

Continue autonomously through reversible local code, docs, synthetic fixtures,
tests, candidate runs, and maintenance of ADR-0030's narrow dual route. PRIVATE
synthetic route fixtures remain local and training-ineligible. Stop before
private external disclosure, automatic classification, silent cross-provider
failure fallback, driver/system change, training, broader automatic routing,
default-model promotion, deployment, public exposure, GPT-authored proactive
delivery, or any change to the fixed Identity/privacy/governance boundary.
