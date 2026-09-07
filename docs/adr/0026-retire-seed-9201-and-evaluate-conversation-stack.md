# ADR-0026: Retire Seed 9201 from daily use and evaluate the conversation stack

- Status: Accepted
- Accepted: 2026-09-02 by Product Owner
- Date: 2026-09-02
- Decision owners: Product Owner/System Architect
- Extends: ADR-0005, ADR-0010, ADR-0011, ADR-0021, ADR-0022
- Supersedes: ADR-0025 only where it names Seed 9201 as the default Local Daily Brain
- Superseded in part by: ADR-0030 only where it permits the same exact
  unadapted Qwen3-8B as the owner-local privacy route and authorizes that narrow
  automatic selection; candidate/promotion/training limits remain unchanged

## Context and real problem

The Product Owner found Seed 9201 materially farther from the intended companion
than its earlier bounded evaluations suggested. Its shortness, incomplete intent
coverage, shallow judgment, and unnatural conversation make continued daily use
more harmful than useful. Earlier test passes proved contracts, provenance, and
specific behavioral fixtures; they did not prove that the assistant was pleasant
or valuable across real multi-turn conversation.

The defect cannot safely be attributed to model size alone. Final behavior also
depends on short-term history, Memory admission and presentation, mode selection,
response budgeting, Core transformation, and the validity of the evaluator.

## Decision

Seed 9201 is retired from default daily use and is owner-rejected as a product
direction. Its immutable artifacts, registry entry, raw generations, and prior
evidence remain historical candidate records; this decision does not delete them,
rewrite their lifecycle fields, or promote another model.

Until a stronger local candidate passes comparison, the daily owner-local launcher
uses the exact attested, unadapted Qwen3-8B Stage 3 candidate as a diagnostic
baseline. This is deliberately a baseline, not a claim that the base model is good
enough. It remains local, loopback-only, request-log-disabled, candidate-only,
unpromoted, and undeployed.

HAVRE will evaluate one conversation stack whose durable responsibilities are:

1. a typed Response Plan captures mode, intent, every point that must be addressed,
   memory need/query, answer depth, stance, and uncertainty;
2. a Memory Broker retrieves only when relevant and distinguishes short-term
   dialogue, reviewed long-term Memory, and tentative links;
3. the replaceable Replyer produces natural language under the fixed HAVRE Identity;
4. the existing Core retains privacy, provenance, safety, authorization, and final
   delivery authority under ADR-0022;
5. an offline reviewer may diagnose failures and propose prompts, fixtures, or code
   changes, but may not mutate production behavior, Memory, training data, weights,
   lifecycle state, or release state automatically.

Local model comparison may include the unadapted Qwen3-8B baseline, Seed 9201 as a
historical control, Qwen3.5-9B, and Qwen3.6-35B-A3B when the exact artifacts and
hardware/runtime prerequisites are separately verified. The Product Owner's
delegation authorizes exact official candidate artifacts to be downloaded into
the owner-controlled ignored runtime directory for this comparison. Driver or
system changes, training, promotion, and deployment are not implied by this ADR.

GPT-5.6-sol may be used as an offline teacher/reviewer for PUBLIC synthetic or
explicitly owner-selected redacted material. Raw private owner conversation must
not be sent to it without a separate, explicit disclosure scope. Reviewer output
is proposal evidence, never ground truth or self-approval.

## Why it belongs in the final system

Provider replacement alone cannot supply relationship continuity or verify that a
reply understood the whole turn. A small typed plan, relevance-gated Memory access,
and separate offline review keep those responsibilities observable and testable
while allowing the foundation model to change.

## Simplest viable current implementation

- Switch the owner-local desktop startup to the existing exact unadapted Qwen3-8B
  runtime and attest that no adapter is active.
- Preserve the direct Seed 9201 candidate launcher for historical regression only.
- Add a frozen conversation-quality set and score raw model, admitted context,
  delivered response, and reviewer agreement separately before changing weights.
- Implement the Response Plan at the existing Context/Inference boundary without
  adding a second agent loop or allowing untyped prompt mutation.

## Alternatives considered

- **Keep tuning Seed 9201:** rejected because the owner-visible failure is broad and
  prior style/capability continuations traded one defect for another.
- **Immediately train a 35B model:** rejected for now because the current machine
  and runtime are not yet proven suitable, and training would confound model,
  context, orchestration, and evaluator defects.
- **Route ordinary private chat to a cloud model automatically:** rejected because
  it changes the privacy/disclosure boundary and is not authorized.
- **Copy a social-chatbot emotion/personality engine:** rejected because HAVRE needs
  one fixed Identity and reliable understanding, not simulated mood churn.

## Consequences

### Benefits

- Removes a known-bad daily default without destroying audit evidence.
- Creates a clean causal baseline for deciding whether the main bottleneck is the
  model, context construction, Memory use, delivery policy, or evaluation.
- Keeps the long-term architecture provider-neutral and the personality governed by
  HAVRE rather than by a single checkpoint.

### Costs and constraints

- The temporary 8B base may still feel weak and may be worse on behaviors that 9201
  learned; that is acceptable only as a diagnostic baseline.
- More capable local candidates may require downloads, RAM/VRAM tradeoffs, driver
  changes, and new serving attestations before any meaningful comparison.
- Offline reviewer judgments need blinded human calibration and counterexamples;
  repeated self-scoring alone can optimize toward a biased judge.

## Failure modes and future migration risks

The system can still appear good on isolated prompts while failing over a real
conversation. Memory retrieval can be correct but absent from final model input,
or present but ignored. The Core can mask a raw model defect. A reviewer can reward
verbosity, stylistic similarity, or unsupported familiarity. Therefore every
failure must retain evidence for retrieval, admitted ContextPack, final provider
request, raw completion, delivered response, and score provenance.

## Validation

- Static and runtime proof that desktop startup binds the exact Qwen3-8B base with
  `active_adapter_version_id = null` and retains candidate-only boundaries.
- Counterfactual conversation cases for relevant, irrelevant, absent, stale, and
  partial Memory, plus multi-request and mode-switching conversations.
- Separate raw-model and delivered-response scores for intent completeness,
  context continuity, naturalness, warm/firm judgment, uncertainty, safety, privacy,
  fabricated familiarity, verbosity, and latency.
- Blinded same-prompt pairwise owner review; GPT-5.6-sol is one reviewer signal and
  cannot promote its own proposal.
- Full PostgreSQL-backed regression and provenance audit for any persistence,
  privacy, feedback, or Memory change.

## Approval note

On 2026-09-02 the Product Owner explicitly said Seed 9201 could be abandoned because
it was far from the intended experience, delegated the remaining reversible
engineering choices, and asked the agent to stop only at necessary gates. This
authorizes the bounded baseline switch and evaluation/architecture work above. It
does not authorize private-data disclosure, driver modification, training, model
promotion, deployment, or automatic routing. It does authorize hash-pinned model
downloads that stay inside the owner-controlled candidate-evaluation runtime.
