# Stage 14B Default ChatGPT Reply Checkpoint

Date: 2026-09-03
Decision: ordinary PUBLIC/NORMAL HAVRE chat uses GPT-5.6-sol automatically;
the daily Strong Brain distinction is removed.
Architecture: ADR-0029

## Implemented

- Added an `openai-codex-chatgpt` provider over the authenticated owner-local
  Codex CLI JSONL interface; it reads no OpenAI API key.
- Bound every request to the provider, owner authorization, data boundary, and
  exact canonical request hash.
- Used an empty ephemeral read-only workspace, stdin-only prompt transport,
  minimized environment, and disabled shell/web/image/MCP/app tools.
- Accepted only final agent-message output and rejected any tool activity.
- Routed ordinary chat to GPT-5.6-sol before the existing ADR-0022 Core policy
  and durable assistant Event path.
- Removed the per-message Strong Brain action and exposed one truthful reply
  engine status.
- Preserved `training_eligible=false`; PRIVATE, HIGHLY_PRIVATE, and LOCAL_ONLY
  fail closed rather than being silently uploaded or reclassified.

## Verification evidence

- Focused provider/config tests: 4 passed.
- Chat/PWA static behavior tests: 9 passed.
- Primary PostgreSQL-backed suite, excluding only the separately pinned Torch
  modules: 597/597 passed, zero skipped.
- Pinned Stage 9A Torch environment: 62/62 passed, zero skipped.
- Authoritative combined result: 659/659 passed, zero skipped.
- Dedicated disposable database: `havre_stage14b_20260903_01`; provenance audit
  returned `[]`.
- Contract schema export, both environment dependency checks, compile checks,
  and `git diff --check` completed successfully.
- A real PUBLIC synthetic call returned provider `openai-codex-chatgpt`, model
  alias `gpt-5.6-sol`, and `好，我在这儿陪你。你不用说什么。`
- That call reported 10,818 prompt, 17 output, and zero reasoning tokens. This
  proves transport, capture, and usage parsing, not conversation quality,
  latency distribution, capacity, or immutable model weights.
- The owner desktop was safely stopped and restarted. Live `/health/ready`
  returned `ready`; live `/version` reported provider
  `openai-codex-chatgpt`, model `gpt-5.6-sol`, adapter `null`, and
  `codex-cli-0.152.0`. The protected settings endpoint reported GPT as the one
  default reply engine and the Local default as false.
- The protected browser bootstrap reopened the HAVRE chat. An actual owner
  conversation remains the practical usefulness gate and is not manufactured
  by an engineering test.
- A post-activation correction made the already-running launcher reuse that
  protected bootstrap instead of opening `/chat` directly; its focused
  Web/launcher regression suite re-passed 9/9.

## Boundaries

- No OA70 or owner conversation was read or sent during engineering validation.
- No training, fine-tuning, adapter/local-model promotion, or automatic Memory
  mutation occurred.
- The proactive engine still uses its accepted deterministic rendering; GPT
  proactive wording is only a separately gated design direction.
- Provider retention/account handling and model alias updates remain external.
- A provider failure is explicit and does not silently substitute 8B.
- The local 8B process still starts only as a governed recovery/diagnostic
  control and for the launcher's existing database lifecycle; eligible normal
  chat requests do not route to it.
- Owner use in the HAVRE window is still required to establish practical value.
