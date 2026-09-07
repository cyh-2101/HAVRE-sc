# Stage 13 owner-calibrated runtime checkpoint

Date: 2026-09-03
Authority: ADR-0031 and the Product Owner directive
"把前20条当示例。其他的按你的修。"

## Implemented

- exact OA70 source verification at
  `sha256:51152825976d42971413cdd9b18609a2392036f114d8f4177c2a8d446e1031e9`;
- exact cases `owner-anchor-001` through `owner-anchor-020` derived into
  `owner-example-bank-oa70-first20-v1` with content hash
  `sha256:cc0c73b0cb2a58e6bc07cf3394a4473a98d0326fb1f30205c0d7e67a085af6e2`;
- deterministic relevance selection with a three-example maximum, complete
  source references, NORMAL/cloud-eligible owner authorization, and false
  Memory/training eligibility;
- `context-builder-v13`: authoritative owner-local message time and
  current-session-first raw history, with bounded cross-session fallback only
  when the current message explicitly refers to prior conversation;
- `response-planner-v3`: acknowledgement/share/ask/request/decide dialogue acts,
  one-sentence acknowledgement guidance, ordinary-sharing restraint, and
  current-time evidence requirements;
- `context-presentation-v8-owner-examples`: examples presented separately from
  Memory and from current-situation facts;
- GPT-5.6-sol Codex reasoning effort changed from fixed high to explicit medium,
  with the value bound into the exact cloud request hash;
- desktop startup derives and validates the bank before API startup and records
  the active bank and effort in its protected state file.

No weights were trained or changed. The local privacy route remains the exact
unadapted Qwen3-8B with null adapter fields.

## Verification

- focused ResponsePlan, owner-example, provider, Memory-presentation regression:
  44/44 passed;
- final complete primary suite on dedicated PostgreSQL database
  `havre_adr0031_tests_20260903`: 641/641 passed, zero skips;
- exact three historical Stage 9A modules in the pinned Torch environment:
  62/62 passed;
- combined repository coverage: 703/703 passed, zero database skips;
- generated contract schemas match typed contracts;
- provenance audit on the dedicated database: `[]`;
- primary and pinned-Torch `pip check`: passed;
- Python compileall, desktop PowerShell parse, and `git diff --check`: passed;
- live desktop `/health/ready`: `ready`;
- live provider: `openai-codex-chatgpt` / `gpt-5.6-sol`;
- live local route: `model-qwen3-8b-gguf-q4-k-m-7c41481f`, adapter null;
- protected desktop state: effort `medium`, bank
  `owner-example-bank-oa70-first20-v1`.

The exact disposable test database was dropped after the empty provenance audit;
the already-running owner-local PostgreSQL cluster was kept online for HAVRE.

The first activation exposed a pre-existing restart defect: registering the
same runtime-attestation ID and hash could collide on the secondary unique hash
before the ID-specific conflict target handled it. Registration now ignores any
unique conflict and then verifies the exact requested ID/hash, preserving
fail-closed collision behavior. A PostgreSQL regression passes, and the second
activation reached ready state.

## Evidence limits and stop boundary

This checkpoint proves mechanics, privacy/policy handling, provenance, restart,
and regression behavior. It does not prove that the next real conversations will
feel good. No owner message was generated automatically for this verification.

Cases 1-20 are prompt-exposed and are no longer independent holdout evidence.
Cases 21-70 remain unauthorized. Stop before training/tuning, automatic Memory
mutation, PRIVATE/HIGHLY_PRIVATE/LOCAL_ONLY cloud admission, GPT-authored
proactive delivery, model promotion, automatic sensitivity classification,
silent cross-provider fallback, public exposure, or always-on hosting changes.

The next gate is real owner use: fewer corrections, complete context
understanding, appropriate length, natural use of relevant shared history, no
fabricated familiarity, and replies the owner actually wants to use.
