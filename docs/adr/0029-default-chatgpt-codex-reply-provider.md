# ADR-0029: Default ChatGPT/Codex reply provider

- Status: Accepted
- Accepted: 2026-09-03 by Product Owner
- Date: 2026-09-03
- Decision owners: Product Owner/System Architect
- Extends: ADR-0005, ADR-0009, ADR-0011, ADR-0014, ADR-0022, ADR-0027, ADR-0028
- Supersedes for owner-local daily chat: ADR-0025 manual Strong Brain selection
- Superseded in part by: ADR-0030 for non-GPT-eligible and stricter owner-local
  ContextPacks; the cloud admission and isolation boundary remains unchanged

## Context

Stage 14A let a ChatGPT-hosted model receive PUBLIC HAVRE Identity and a Turn
Contract through MCP, but its final reply stayed outside HAVRE. The Product
Owner explicitly authorized one GPT-5.6-sol call for each ordinary daily chat
message and explicitly removed the normal-versus-Strong-Brain product choice.
The reply must return to the HAVRE window through the existing Core and Event
path. No OpenAI API key is required; the owner-local Codex CLI reuses the
ChatGPT authentication already held by the Codex app.

## Decision

The owner-local desktop profile uses provider `openai-codex-chatgpt` and model
alias `gpt-5.6-sol` as its default Replyer. One submitted user message creates
one provider call; punctuation within the message does not create extra calls.

```text
owner message
  -> durable USER_MESSAGE Event
  -> ResponsePlan
  -> relevance-gated recent conversation and reviewed Memory
  -> canonical ContextPack and provider messages
  -> exact provider/authorization/boundary/request-hash binding
  -> isolated ephemeral Codex CLI execution
  -> final agent-message extraction
  -> ADR-0022 Core response policy
  -> durable ASSISTANT_MESSAGE Event in the same HAVRE timeline
```

Each provider run receives the canonical request through stdin and uses a new
empty temporary working directory, read-only sandboxing, ignored ambient rules
and configuration, and disabled shell, shell snapshot, web, image, MCP, app,
and connector tools. Only reasoning and final-agent-message JSONL items are
accepted. Any tool item or malformed stream fails before delivery. A minimal
environment allowlist retains ChatGPT authentication while excluding API keys,
access tokens, and unrelated secrets.

Automatic admission is limited to ContextPacks whose existing effective
DataPolicy is PUBLIC or NORMAL and cloud-eligible. PRIVATE, HIGHLY_PRIVATE, and
LOCAL_ONLY fail closed and are not reclassified by this decision. All source
and derived chat evidence remains `training_eligible=false`. Normal chat may
remain eligible for governed local HAVRE Memory; that does not grant provider
training rights.

## Consequences and limits

- GPT replies appear in HAVRE and participate in existing feedback, episode,
  erasure, provenance, and long-term continuity mechanisms.
- HAVRE still owns Identity, planning, retrieval, Memory, Core delivery, and
  the durable conversation record.
- Codex executions are ephemeral and independent. HAVRE reconstructs bounded
  continuity each turn instead of relying on a hidden ChatGPT thread.
- The per-response Strong Brain button is removed from the daily UI. Its legacy
  endpoint remains backward-compatible but is not configured by the desktop
  launcher.
- Provider failure is visible and creates no assistant Event. The existing
  local profile remains an operator-controlled recovery path; one request never
  silently changes models.
- Provider retention, account policy, model alias updates, availability, and
  usage limits are external to HAVRE. The adapter records the observed Codex
  CLI version and usage but cannot pin an underlying model-weight snapshot.
- A live PUBLIC synthetic probe reported 10,818 input tokens for a tiny
  request, so this path has large fixed overhead. The owner accepted automatic
  use despite that cost; real latency and usage still require observation.
- OA70, training, tuning, adapter promotion, 35B promotion, automatic Memory
  mutation, private-data cloud admission, and GPT control over Identity or
  policy are not authorized by this decision.
- Proactive trigger authority remains unchanged. A future GPT proactive
  language realizer must run only after an allow decision and before a separate
  Core acceptance gate; it is not activated here.

ADR-0031 supersedes only the blanket OA70 prohibition above: the Product Owner
later authorized an exact source-bound derived runtime-example bank from cases
1-20. All other OA70 use and every other boundary in this ADR remain unchanged.

## Validation

- adapter tests for binding, DataPolicy, environment minimization, stdin-only
  transport, JSONL lineage, and tool rejection;
- PostgreSQL integration proving a normal chat turn becomes a Core-governed,
  durable GPT assistant Event with training disabled;
- real PUBLIC synthetic execution through the installed Codex CLI and signed-in
  ChatGPT account;
- desktop launcher checks for exact Codex path, CLI version, ChatGPT login, and
  provider/model binding;
- complete PostgreSQL-backed regression, dependency integrity, compilation,
  provenance audit, and diff validation before checkpoint closure;
- owner use remains the evidence for practical conversation quality.

## Implemented dual-route clarification (2026-09-03)

ADR-0030 now composes this GPT branch with the exact attested, unadapted local
Qwen3-8B branch. The implemented rule is determined from the completed
ContextPack's effective DataPolicy:

- PUBLIC or NORMAL with effective cloud eligibility uses the authenticated
  owner-local Codex CLI GPT-5.6-sol provider;
- cloud-ineligible PUBLIC/NORMAL and every PRIVATE, HIGHLY_PRIVATE, or
  LOCAL_ONLY pack use the exact local Qwen3-8B provider with null HAVRE adapter
  identity.

Both branches retain the same ResponsePlan, retrieval, ContextPack,
provider-neutral inference, ADR-0022 Core, durable assistant Event, feedback,
episode, provenance, and erasure path. There is no semantic sensitivity
classifier and no silent cross-provider failure fallback. The former
per-response Strong Brain/Strong UX choice is retired; its guarded legacy
endpoint is compatibility surface only and is neither a third route nor a
normal product control.

The local 8,192-token total-context value is the authorized llama.cpp runtime-
profile cap, not a claim about Qwen3-8B's intrinsic model capacity. Real
synthetic probes exercised both branches through the current composition. A
current GPT probe observed 11,824 prompt tokens, while the earlier GPT-only
probe observed 10,818. Those are per-call observations, not fixed overhead,
immutable model evidence, or a capacity guarantee; this clarification supersedes
any reading of the earlier 10,818 observation as a fixed constant.

The current probes and regression evidence establish transport, route
selection, privacy isolation, provider-specific binding, Core/Event lineage,
typed failure behavior, and idempotency. They do not establish practical
conversation quality. Repeated owner use in the HAVRE window remains the gate
for whether this assistant is actually useful.
