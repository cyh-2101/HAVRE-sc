# ADR-0031: Owner-calibrated runtime examples and practical-utility repairs

- Status: Accepted
- Date: 2026-09-03
- Decision owner: Product Owner
- Supersedes in part: ADR-0029 and ADR-0030 only where they prohibited every OA70 transformation

## Context

The technically verified GPT/local Replyer path still felt slow, over-instructed,
and unlike the intended fixed warm-and-strong personality. Live evidence showed
old raw conversations entering otherwise new sessions, no authoritative
owner-local time in the provider Context, conversational acknowledgements being
treated as requests for another plan, and a fixed `high` Codex reasoning effort.
The Product Owner explicitly directed: "把前20条当示例。其他的按你的修。"

The frozen 70-case Owner Alignment Set was previously evaluation-only and
LOCAL_ONLY. That historical source must remain immutable even though the owner
has now authorized one exact derived use.

## Decision

1. The original OA70 v1 file remains byte-for-byte unchanged at
   `sha256:51152825976d42971413cdd9b18609a2392036f114d8f4177c2a8d446e1031e9`.
2. Only `owner-anchor-001` through `owner-anchor-020` may be transformed into
   `owner-example-bank-oa70-first20-v1`. The derived artifact is owner-specific,
   `NORMAL`, cloud-eligible, memory-ineligible, and training-ineligible under
   authorization `product-owner:2026-09-03:oa70-first20-runtime-examples`.
   Every case retains its exact source-case content hash and the bank retains the
   exact source artifact hash.
3. The bank is not training, tuning, Memory, or a user-profile store. A
   deterministic selector may admit at most three relevant examples per turn.
   The provider is told to learn the intended naturalness, restraint, warmth,
   and directness without copying the scenario or treating it as current fact.
4. `ContextBuilder v13` includes the authoritative owner-local timestamp at
   message receipt. It treats the active session as short-term working Memory.
   Raw cross-session messages are permitted only as a bounded fallback when the
   current message explicitly refers to prior conversation; reviewed Episode and
   long-term Memory paths remain the normal cross-session continuity mechanism.
5. `ResponsePlan v3` distinguishes acknowledgement/share/ask/request/decide,
   keeps acknowledgements brief, prevents ordinary sharing from becoming an
   unsolicited checklist, and requires admitted time evidence for time claims.
6. GPT-5.6-sol remains the single default eligible Replyer, with Codex reasoning
   effort changed from fixed `high` to explicit `medium`. This is a latency and
   interaction-fit choice, not a model downgrade or a new Strong Brain route.
7. The derived first-20 bank is admitted only on the GPT branch. The attested
   local Qwen branch keeps Identity, current-session context, governed Memory,
   and ResponsePlan, but omits these optional examples because their actual
   tokenizer cost can overflow its 8,192-token profile even when the
   provider-neutral estimator appears to fit. This is provider-capacity
   scoping, not authorization to remove required owner context.

## Evaluation consequence

Cases 1-20 are prompt-exposed and cannot be used as an independent holdout for
this runtime. OA70 must no longer be reported as one clean 70-case holdout.
Cases 21-70 remain unexposed by this decision, but any future evaluation must
declare the selection history and cannot use cases 1-20 to claim generalization.
The practical gate remains repeated owner use, not green unit tests.

## Preserved boundaries

- Cases 21-70 are not authorized for prompting, tuning, training, or review.
- No owner conversation is newly declassified.
- No automatic Memory write, Identity change, model promotion, 35B dependency,
  private cloud admission, silent provider fallback, or public exposure is
  authorized.
- Proactive trigger and send authority remain deterministic Core decisions.
  GPT-authored proactive delivery is still inactive.

## Verification required

- exact-source-hash derivation and exact 20-case membership;
- owner/policy/hash validation at runtime load;
- relevance selection, three-example cap, source references, token accounting,
  stricter effective-policy preservation, and final provider-message inspection;
- acknowledgement, sharing, current-time, historical plan replay, and configured
  reasoning-effort tests;
- current-session isolation and explicit cross-session fallback in PostgreSQL;
- full zero-skip database regression, schema export, provenance audit, dependency,
  compile, and diff checks before activation.
