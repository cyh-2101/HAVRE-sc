# Stage 14B Dual Provider Routing Checkpoint

Date: 2026-09-03
Decision: ADR-0030 is Product Owner accepted; the dual route is technically
verified and active on the owner-local runtime. Practical utility remains open.
Prior evidence: [`STAGE14B_DEFAULT_CHATGPT_REPLY_CHECKPOINT.md`](STAGE14B_DEFAULT_CHATGPT_REPLY_CHECKPOINT.md)

## Authorized target

The owner-local daily interaction path may route a completed ContextPack by its
effective DataPolicy:

- cloud-eligible PUBLIC/NORMAL -> authenticated no-tools GPT-5.6-sol;
- cloud-ineligible PUBLIC/NORMAL -> exact local Qwen3-8B;
- PRIVATE/HIGHLY_PRIVATE/LOCAL_ONLY -> exact local Qwen3-8B.

The local branch is the pinned Stage 3 Qwen3-8B Q4_K_M artifact with no HAVRE
adapter. Both branches must retain the existing ResponsePlan, ContextPack, Core,
Event, feedback, episode, provenance, and erasure path.

## Current evidence boundary

ADR-0029's earlier 659/659 result proved only the prior PUBLIC/NORMAL GPT route
and its fail-closed private boundary. Historical Stage 3 evidence proved an
exact attested local Qwen interaction in an older single-provider composition.
Neither result was counted as proof of the new dual composition. The current
evidence below separately exercises its route selection, UI, mixed-privacy
continuity, provider-specific request binding, local runtime budget, durable
terminal lineage, and both live providers.

No owner-private conversation or OA70 is required for engineering validation.
Synthetic NORMAL, PRIVATE, HIGHLY_PRIVATE, and LOCAL_ONLY turns are sufficient
to establish routing and persistence mechanics. Owner use remains necessary to
assess practical value.

## Required implementation evidence

- [x] RouteDecision/router version names the multi-provider policy and preserves
  legacy single-provider contract compatibility.
- [x] Generated route schema matches the active contract.
- [x] PUBLIC/NORMAL with cloud eligibility selects GPT; PUBLIC/NORMAL without it
  selects local; PRIVATE/HIGHLY_PRIVATE/LOCAL_ONLY select local.
- [x] Mixed-policy ContextPacks use the most restrictive effective policy and do
  not discard required stricter context to enable cloud.
- [x] Codex binder and authorization metadata apply only to GPT requests.
- [x] Private/local route tests observe zero content-bearing Codex inference
  calls, including when Qwen is unavailable or over its context limit.
- [x] GPT failure does not silently call Qwen; Qwen failure does not call GPT.
- [x] Local ProviderVersion and inference lineage match
  `model-qwen3-8b-gguf-q4-k-m-7c41481f`, the exact artifact hash, the pinned
  llama.cpp runtime, a current process attestation, and null adapter fields.
- [x] The local branch has a demonstrated budget compatible with the configured
  8,192-token total window, including a boundary failure case.
- [x] NORMAL-to-GPT and all three stricter-class-to-local flows pass through Core
  and persist one correctly linked assistant Event.
- [x] Provider failure creates a typed failure and no assistant Event.
- [x] Idempotent replay returns the original route/result without a second model
  call.
- [x] The Web composer defaults to NORMAL, exposes an explicit only-local choice,
  refreshes stale cached assets, and truthfully displays the provider actually
  used.
- [x] Switching away from a stricter context cannot disclose its prior history;
  the owner-visible continuity boundary is tested.
- [x] Real synthetic GPT and Qwen probes succeed through the current dual
  composition without owner-private data.
- [x] Live desktop startup and readiness verify both configured providers and
  expose their exact model/runtime state.
- [x] Complete PostgreSQL-backed tests pass with zero database skips, the pinned
  Torch modules pass, provenance audit is `[]`, generated schemas are current,
  and dependency, compile, PowerShell, JavaScript, and diff checks pass.

## Verification evidence

- The primary PostgreSQL-backed suite passed 633/633 with zero skips. The pinned
  Torch environment passed 62/62, for an authoritative combined 695/695.
- Focused PostgreSQL/API regression passed 110/110. The migration-runner suite
  passed 5/5, a populated upgrade passed, a fresh database applied all 53
  migrations and reapplied zero, and the `0052`/`0053` disk hashes matched their
  ledger rows. The disposable-database provenance audit returned `[]`.
- Generated schema equality, both dependency checks, Python compilation, Node/PWA
  checks, 17 PowerShell parse checks, and `git diff --check` passed.
- The active owner runtime reports `ready` at `/health/ready` with migration head
  `0053`. Its GPT provider is healthy. Its local provider reports exact base model
  `model-qwen3-8b-gguf-q4-k-m-7c41481f`, artifact
  `sha256:d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785`,
  a current process attestation, and null adapter identity.
- Synthetic NORMAL request `01a066de-8a89-7665-9199-3fc91e65cf27` completed
  through `openai-codex-chatgpt` / `gpt-5.6-sol` with adapter null and reported
  11,824 prompt plus 7 output tokens. The different prompt count from the earlier
  10,818-token probe confirms that neither observation is a fixed-overhead or
  capacity measurement.
- Synthetic LOCAL_ONLY request `01a066de-f578-73fc-8d0a-7b4ad16252e6`
  completed through the exact attested unadapted Qwen branch with adapter null
  and reported 755 prompt plus 4 output tokens. Its Context never entered a
  content-bearing Codex inference call.
- Protected settings expose the actual dual route, hide Strong Brain, and declare
  no silent cross-provider fallback. No owner-private conversation or OA70 was
  used for these engineering probes.
- A fresh browser opened at the copied bare loopback URL correctly received 401
  because it lacked the launcher's one-time owner session. The original UI hid
  that fact behind "confirming reply engine." Web shell `dual-route-v5` now shows
  persistent launcher guidance and disables sending on loopback 401, while a
  genuinely remote unpaired device retains the pairing flow. The authenticated
  launcher path was observed completing `POST /v1/desktop/session` with a 303
  redirect followed by 200 settings and timeline reads. The executable PWA
  contract and focused Python asset tests pass.

## Claims that remain prohibited

- Technical verification and live activation do not establish owner-visible
  conversational success. Repeated owner use remains the Practical Utility Gate.
- The unadapted 8B is not promoted, personalized, production-proven, or shown to
  be as useful as GPT.
- PRIVATE/HIGHLY_PRIVATE/LOCAL_ONLY remain forbidden from automatic GPT upload.
- No automatic classification, cloud fallback, training, OA70 use, adapter/35B
  promotion, automatic Memory mutation, or GPT-authored proactive contact is
  activated by this checkpoint.
