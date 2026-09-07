# ADR-0027: Stage 13 conversation-intelligence architecture

- Status: Accepted
- Accepted: 2026-09-02 by Product Owner
- Date: 2026-09-02
- Decision owners: Product Owner/System Architect
- Extends: ADR-0005, ADR-0009, ADR-0010, ADR-0011, ADR-0021, ADR-0022, ADR-0026
- Supersedes: None; clarifies ADR-0026's orchestration and reviewer roles
- Superseded in part by: ADR-0030 only for the accepted owner-local DataPolicy
  route; broader routing and model-promotion gates remain unchanged

## Context

The first ADR-0026 experiment separated a weak daily model from the rest of the
stack and established Qwen3-14B Q4_K_M as a more capable local candidate. It also
exposed two architecture defects that model replacement alone cannot solve:

1. durable Memory retrieval happened before the Response Plan decided whether
   Memory was needed, so the supposed gate was circular; and
2. the plan recorded distinct requests but did not represent the owner's demand
   for one present recommendation, allowing a model to answer only with
   conditions and avoid the decision.

The Product Owner also clarified that “GPT-5.6-sol continuously analyzes and
corrects” means the current Codex engineering agent working on the repository,
not a second model embedded inside HAVRE's product runtime.

## Decision

Stage 13 is the independent **Conversation Intelligence** stage. It may progress
while deferred Stage 11 native evidence and Stage 12 sensing work remain closed,
because it changes only the existing reactive conversation path.

The runtime path is:

```text
durable current turn + recent dialogue + confirmed response preferences
    -> deterministic Turn Contract
    -> Memory Gate
    -> relevance-ranked Memory Broker
    -> token-budgeted Context Compiler
    -> replaceable Replyer
    -> bounded response-coverage evidence
    -> existing Core Response Policy
    -> durable owner-visible reply
```

The current `ResponsePlan` is the typed Turn Contract. Version 2 is built before
retrieval and records distinct obligations, mode, depth, stance, uncertainty,
Memory need/query, and whether the owner explicitly requires one recommendation.
It is deterministic rather than another model/agent loop. Historical v1 remains
parseable for evidence replay.

When `memory_need=none`, the application persists an explicit empty retrieval
result and performs no Memory search. `possible` and `required` permit retrieval
but never guarantee admission or mention. The broker and Context Builder continue
to enforce owner, request, trace, privacy, provenance, relevance, duplicate, and
token-budget boundaries. Current dialogue and confirmed preferences are not
reclassified as long-term Memory.

The fixed HAVRE Constitution, Identity, Values, and approved communication
preferences remain the Identity Kernel. The planner does not invent a mood,
imitate the owner, or learn a new personality. No MaiBot-style emotional state or
automatic user-profile mutation is adopted.

The Replyer stays behind the provider-neutral inference contract. Qwen3-8B is a
temporary diagnostic baseline; Qwen3-14B Q4_K_M is the leading candidate; a
35B-class model is considered only after exact artifact, runtime, RAM/VRAM,
latency, and stability evidence justifies the experiment. A small model is not
introduced as a separate planner until deterministic planning is proven
insufficient.

The post-generation coverage component initially records evidence and may request
at most one bounded repair in a later separately verified slice. It cannot alter
facts, Memory, identity, tool authority, or privacy, and Core remains the only
final delivery authority under ADR-0022.

## External Codex development loop

The current Codex agent is outside the product runtime. It may, within the
owner-delegated reversible scope:

1. inspect complete authorized evidence from input through delivered output;
2. classify the responsible layer;
3. change one causal variable;
4. run focused and full regression evidence; and
5. update code and evidence documentation.

It must not become a runtime dependency, write production Memory, alter the fixed
Identity from self-scoring, train on saved conversation, change model lifecycle
state, or promote/deploy its own proposal. PUBLIC synthetic evidence is the
default. Raw private owner conversation may be reviewed by an external model only
under a new explicit disclosure scope. Local repository diagnostics over owner
data remain bounded by the existing filesystem, privacy, and audit rules.

## Stage authorization

The Product Owner explicitly authorized the new architecture, documentation, and
Stage 13 on 2026-09-02 and asked the agent to continue until a real owner decision
is needed. This authorizes reversible Stage 13A-C implementation and PUBLIC
synthetic/local candidate evaluation. It does not authorize:

- raw private-chat cloud disclosure;
- a driver, operating-system, or broad infrastructure change;
- automatic local/cloud routing;
- training, Stage 9B, or user-derived dataset use;
- default-model promotion, deployment, or public exposure; or
- automatic identity, preference, Memory, or policy mutation.

Stage 13D is an explicit owner gate. The agent must stop there with exact evidence
and a concrete recommendation.

## Consequences

### Benefits

- Memory retrieval becomes causally gated instead of just post-hoc filtered.
- Complete intent and explicit decisions become inspectable contracts rather than
  broad prompt wishes.
- Model quality, Context quality, Core containment, and reviewer quality remain
  separately measurable.
- HAVRE can adopt a stronger local model without binding continuity or governance
  to that checkpoint.

### Costs and limits

- Regex/deterministic planning can still misclassify ambiguous language and needs
  adversarial multilingual fixtures.
- A Turn Contract can request completeness but cannot make an incapable Replyer
  reason well.
- A model judge and Codex reviewer can share blind spots; owner pairwise review is
  still required for promotion.
- Stage 13 improves reactive conversation only. It does not prove native iPhone,
  proactive, sensing, training, or outcome quality.

## Validation

- Contract tests for v1 replay, v2 hash integrity, obligation splitting, explicit
  recommendation detection, no-premature-choice counterexamples, and injection
  escaping.
- Application-boundary tests that `memory_need=none` calls only the explicit empty
  retrieval path while prior-context turns permit actual retrieval.
- Frozen PUBLIC same-turn Memory counterfactuals with identical Turn Contracts.
- Repeated raw Replyer comparison followed by a full ContextPack/Core comparison;
  raw and delivered outputs remain separately scored.
- Full PostgreSQL-backed suite with zero database skips plus provenance audit for
  any persistence, privacy, retrieval, or Context change.
- Blinded owner comparison before Stage 13D promotion.

## Subsequent evidence

Stage 13A passed the complete primary and pinned-Torch suites with zero skips,
schema/compile/dependency checks, PostgreSQL provenance audit `[]`, and a real
database-boundary Memory Gate regression. The first three-run 14B v2 raw replay
preserved relevant-Memory behavior but introduced repeated truncation and
unsupported-uncertainty failures; it therefore rejects that presentation wording
and 14B promotion without changing this ADR's accepted boundaries. Current
candidate decisions and the owner-visible acceptance rule are maintained in
`STAGE13_CONVERSATION_INTELLIGENCE_CHECKPOINT.md` and
`STAGE13_PRACTICAL_UTILITY_GATE.md`.
