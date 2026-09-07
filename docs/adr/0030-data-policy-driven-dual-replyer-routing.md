# ADR-0030: DataPolicy-driven dual Replyer routing

- Status: Accepted
- Accepted: 2026-09-03 by Product Owner
- Date: 2026-09-03
- Decision owners: Product Owner/System Architect
- Extends: ADR-0005, ADR-0011, ADR-0022, ADR-0026, ADR-0027, ADR-0029
- Supersedes in part: ADR-0026's diagnostic-only use of the exact unadapted
  Qwen3-8B baseline, ADR-0027's unqualified automatic-routing stop, and
  ADR-0029's fail-closed local handling for non-GPT-eligible daily turns

## Context

ADR-0029 made GPT-5.6-sol the automatic Replyer for eligible PUBLIC/NORMAL
owner-local chat, but it deliberately rejected PRIVATE, HIGHLY_PRIVATE, and
LOCAL_ONLY ContextPacks. The owner then clarified that LOCAL_ONLY must be an
execution choice, not a dead end: information that cannot leave the machine
still needs an eligible local Replyer. The Product Owner explicitly selected the
existing unadapted local Qwen3-8B for that role.

This is a routing and operational-binding decision. It does not reclassify any
source, grant cloud eligibility, declassify private material, or claim that the
8B model has passed a general conversational-quality or release gate.

## Decision

The owner-local daily interaction path selects one Replyer from the effective
DataPolicy of the completed canonical ContextPack:

| Effective ContextPack | Selected daily Replyer |
|---|---|
| PUBLIC or NORMAL and `cloud_eligible = true` | authenticated no-tools Codex CLI / GPT-5.6-sol |
| PUBLIC or NORMAL and `cloud_eligible = false` | exact attested local Qwen3-8B |
| PRIVATE, HIGHLY_PRIVATE, or LOCAL_ONLY | exact attested local Qwen3-8B |

Cloud eligibility is permission, not a command to use cloud. The automatic daily
route therefore remains local for PRIVATE and HIGHLY_PRIVATE even if an existing
policy revision would technically permit a separately governed cloud use.
LOCAL_ONLY remains invariantly cloud-ineligible.

The local branch is the checked-in Stage 3 artifact
`model-qwen3-8b-gguf-q4-k-m-7c41481f`, artifact SHA-256
`sha256:d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785`,
from Qwen upstream revision
`7c41481f57cb95916b40956ab2f0b139b296d974`. It is served through the
pinned loopback-only llama.cpp b10405 runtime at llama.cpp commit
`e79e4bf660e19f2ad851e06c6913f7a8c5852621`. "Unadapted" means that HAVRE
applies no LoRA/QLoRA adapter: `adapter_version_id` and adapter
artifact hash must both be null. The quantized upstream model remains a
candidate, unpromoted, and undeployed; this owner-local privacy route is not a
personalized model release.

Routing happens after policy-preserving Context construction and before
provider-specific request binding. The Router records the selected provider,
eligible and excluded candidates, reason, exact effective policy revision, and
execution environment. The Codex authorization/hash binder applies only to the
GPT branch. The local branch must not receive cloud authorization metadata.

The Router may not:

- drop required LOCAL_ONLY or more restrictive context to make GPT eligible;
- reinterpret or downgrade a privacy class;
- send PRIVATE, HIGHLY_PRIVATE, or LOCAL_ONLY material to GPT;
- treat local-provider unavailability or context-window overflow as permission
  to use cloud;
- silently retry a failed GPT request on Qwen or a failed Qwen request on GPT in
  this first implementation.

A provider or capacity failure is recorded through the existing typed failure
path and creates no successful assistant Event. The local profile has 8,192 total
KV tokens shared by two parallel slots: the per-request context limit is 4,096,
confirmed by the pinned runtime's `/props` and `/v1/models` on 2026-09-05.
Both runtime and benchmark capability construction use this per-slot bound.
The implementation must use
an evidenced compatible budget or fail explicitly; it must not evade the limit
by changing provider or silently removing required context.

The owner-local desktop profile reserves at most 1,024 output tokens for this
local branch, independently of the cloud branch's 3,072-token reserve. This
keeps the required prompt plus requested completion inside the attested
4,096-token slot within the unchanged 8,192-token llama.cpp profile. Earlier text
incorrectly treated the total allocation as per-request capacity. It is a capacity bound,
not a fixed reply-length target: the model may answer more briefly, while
requests that still cannot fit must continue to fail closed.

Optional owner-calibration examples authorized by ADR-0031 are not admitted to
the local branch. They remain available to the GPT branch, while the local
branch preserves required Identity, policy, current-session context, governed
Memory, and ResponsePlan inside its smaller attested window.

The Web composer defaults an ordinary owner-submitted turn to NORMAL and offers
an explicit only-local choice. Returning from a stricter turn to NORMAL never
authorizes prior stricter history to enter the cloud request. That history must
remain excluded with an owner-visible context boundary or keep the effective
ContextPack local. Cross-boundary continuity must not be claimed until the
chosen behavior is implemented and tested.

## Consequences and limits

- LOCAL_ONLY becomes a useful execution boundary rather than an automatic
  no-reply state.
- Both routes retain the same ResponsePlan, ContextPack, ADR-0022 Core policy,
  Event Store, feedback, episode, provenance, and erasure paths.
- Each assistant Event and inference record identifies the provider and exact
  model/runtime lineage actually used; the UI must not describe every turn as
  GPT or every turn as Local.
- The local reply may be materially weaker than GPT. Functional private routing
  does not establish conversational usefulness, safety breadth, or owner
  preference.
- No automatic semantic sensitivity classifier is accepted by this ADR.
  Classification remains an explicit or already-governed policy input. A future
  local detector may only tighten a route and requires its own false-negative,
  false-positive, and user-control evidence.
- The existing manual Strong Brain history remains historical. This decision
  does not reactivate DeepSeek or create another user-facing Strong Brain mode.
- Provider-side ChatGPT retention/account constraints remain external for the
  eligible GPT branch. The local branch remains loopback-only with request
  logging and Web UI disabled.
- OA70, private-cloud admission, training, tuning, adapter activation, 35B
  promotion, automatic Memory mutation, GPT-authored proactive delivery,
  Identity/policy changes, public exposure, and always-on hosting are not
  authorized.

ADR-0031 later supersedes only this decision's blanket OA70 prohibition. It
authorizes the exact source-bound first-20 runtime-example derivation and no
other OA70, training, tuning, Memory, proactive, or provider-policy use.

## Validation

- a versioned multi-provider RouteDecision contract that preserves legacy
  single-provider deserialization and exports an exact generated schema;
- complete routing truth-table coverage for all privacy classes and cloud
  eligibility, including mixed-policy ContextPacks;
- negative call-count proof that private/local turns never invoke Codex and a
  local failure never causes a cloud call;
- provider-specific binding tests proving cloud authorization metadata appears
  only on the GPT request;
- exact local model/runtime/process attestation with both adapter fields null;
- PostgreSQL integration for NORMAL-to-GPT and
  PRIVATE/HIGHLY_PRIVATE/LOCAL_ONLY-to-local turns through Core and durable
  assistant Events, plus no assistant Event on either provider failure;
- idempotent replay retaining the original route without a second provider call;
- Web tests for NORMAL default, explicit only-local selection, truthful selected
  route, cache refresh, and the stricter-history boundary;
- real synthetic probes through both branches without reading owner-private
  conversation or OA70;
- complete zero-skip PostgreSQL regression, pinned Torch tests, schema export,
  provenance audit, dependency/compile/PowerShell/JavaScript checks, and diff
  validation before implementation closure;
- repeated owner use remains the practical-quality gate for both routes.

## Approval note

After reviewing why LOCAL_ONLY had no eligible Replyer, the Product Owner said
"好的，按你的来。本地使用untuned过的吧". This accepts the narrow deterministic
dual route and exact unadapted Qwen3-8B local branch above. It does not accept a
private cloud disclosure, a new classifier, a model promotion, training, or
proactive GPT contact.
