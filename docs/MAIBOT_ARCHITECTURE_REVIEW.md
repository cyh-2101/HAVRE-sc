# MaiBot architecture review for HAVRE

- Reviewed repository: `Mai-with-u/MaiBot`
- Reviewed revision: `ed8493cb741f462684d392a5b477456e8a188399`
- Review date: 2026-09-02
- Scope: architecture concepts only; no MaiBot source is copied
- License note: MaiBot is GPL-3.0. Any future code reuse would require a separate
  license/compatibility decision. This review authorizes no code import.

## Executive conclusion

MaiBot is useful evidence that a chatbot can feel less like a generic answer API
when it separates deciding, remembering, wording, and sending. HAVRE should adopt
that separation, but not MaiBot's emotional simulation, group-engagement goals,
style imitation, or automatic identity/profile learning. The intended HAVRE form
is one stable warm-and-strong identity, one observable response plan, selective
Memory, one capable Replyer, and the existing governed Core.

The key upstream evidence is:

- [`reasoning_engine.py`](https://github.com/Mai-with-u/MaiBot/blob/ed8493cb741f462684d392a5b477456e8a188399/src/maisaka/reasoning_engine.py)
  runs an interruptible Planner/action loop, builds tool visibility, refreshes
  context references, and records planner/tool evidence;
- [`reply.py`](https://github.com/Mai-with-u/MaiBot/blob/ed8493cb741f462684d392a5b477456e8a188399/src/maisaka/builtin_tool/reply.py)
  turns a Planner reply action into a separate Replyer request and applies
  post-processing/send hooks;
- [`query_memory.py`](https://github.com/Mai-with-u/MaiBot/blob/ed8493cb741f462684d392a5b477456e8a188399/src/maisaka/builtin_tool/query_memory.py)
  exposes retrieval as an explicit tool and passes structured results forward to
  the Replyer;
- [`chat_loop_service.py`](https://github.com/Mai-with-u/MaiBot/blob/ed8493cb741f462684d392a5b477456e8a188399/src/maisaka/chat_loop_service.py)
  preserves selected history/tool turns and exposes before/after request hooks;
- [`memory_search_service.py`](https://github.com/Mai-with-u/MaiBot/blob/ed8493cb741f462684d392a5b477456e8a188399/src/A_memorix/core/runtime/services/memory_search_service.py)
  separates memory search execution, scope filtering, aggregation, and final
  response construction.

## What HAVRE should learn

### 1. Plan before wording, but keep the plan small

MaiBot's Planner/Replyer boundary is directionally correct: deciding what to do is
not the same task as saying it naturally. HAVRE's typed `ResponsePlan` adopts the
useful part—mode, intent, required points, Memory need, depth, stance, and
uncertainty—without starting a free-running multi-agent loop.

For ordinary one-to-one conversation, a deterministic/typed plan is cheaper and
more auditable than asking a weak local model to repeatedly reason about whether
to call `reply`. Escalation to a model planner should happen only when measured
failures show the typed planner is the bottleneck.

### 2. Make Memory an explicit, relevance-conditioned capability

MaiBot does not treat the entire database as permanent prompt text. Its planner can
request Memory and its search service applies multiple scopes before returning
results. HAVRE should retain its stronger guarantees—owner isolation, provenance,
review, validity time, retraction, DataPolicy, and ContextPack admission—while
moving toward the same product behavior: retrieve only when the reply genuinely
depends on earlier facts, and use the result silently rather than announcing the
memory system.

This does not require importing A-Memorix. HAVRE already has durable Events,
episodes, reviewed long-term Memory, User Model revisions, counter-evidence, and
erasure/export boundaries. The missing work is orchestration and natural use, not
another storage subsystem.

### 3. Preserve the actual context and tool chain for debugging

MaiBot's request/response hooks and planner/tool monitoring make it possible to
see what the model actually received and did. HAVRE should expose equivalent
versioned evidence at fixed boundaries: retrieved candidates, admitted
ContextPack, ResponsePlan, final provider messages, raw completion, Core decision,
and delivered output. Hooks must remain typed and fail closed; an arbitrary plugin
must not mutate Identity, privacy, Memory, or delivery authority.

### 4. Let new messages invalidate stale work

MaiBot can interrupt a Planner request when a new message arrives. The underlying
lesson is useful for a private assistant: the latest user turn has priority over a
half-finished answer to an older state. HAVRE should eventually cancel or re-plan
stale generation, but only after the current single-turn response stack is
measured. It is not required for the first model comparison.

### 5. Separate online conversation from slow learning

Style/profile/memory consolidation should be asynchronous and inspectable rather
than part of every visible reply. HAVRE already has episode closure and reviewed
Memory suggestions. Future reviewer proposals can add failure cases or suggest
changes, but they must not automatically change prompts, profiles, Memory,
datasets, weights, or the daily model.

## What HAVRE should not copy

- simulated emotion, mood drift, deliberate mistakes, typos, or meme behavior;
- group-chat speaking probability, silence-as-engagement, or autonomous chatter;
- imitation of another person's wording or slang as the identity mechanism;
- scalar affection/relationship scores as permission or truth;
- automatic conversion of every interaction into a durable profile fact;
- a large Planner/tool loop on every simple private-chat turn;
- post-processing that can silently replace meaning after evaluation;
- source-code copying across the GPL-3.0 boundary without a separate decision.

Those features support MaiBot's goal of feeling like an autonomous group member.
HAVRE's goal is different: a dependable private companion with a fixed, gentle,
strong identity and user-governed continuity.

## Bounded fusion into HAVRE

The target flow is:

```text
latest turn + short history
          |
          v
typed Turn State / Response Plan
          |
          +---- memory_need=false -------------------+
          |                                           |
          +---- memory_need=true -> governed Memory --+
                                                      v
                                           replaceable Replyer
                                                      |
                                                      v
                                      existing governed Core
                                                      |
                                                      v
                                          owner-visible reply
                                                      |
                                                      v
                                 append-only feedback/evidence
```

The model comparison changes only the Replyer arm. It must not simultaneously
replace Memory, Identity, Core, and evaluation criteria, because that would make
the result uninterpretable. The first stronger local candidate is the pinned
Qwen3-14B GGUF; Qwen3.6-35B-A3B/FreeToken remains a later hardware/runtime
experiment, not the architecture of HAVRE itself.

## Acceptance boundary

This review accepts concepts, not a MaiBot dependency or feature port. ADR-0026 and
`EVALUATION_PLAN.md` remain authoritative. Any future plugin API, model-planner,
automatic learning, private-cloud review, or code reuse requires its own scoped
decision and verification.
