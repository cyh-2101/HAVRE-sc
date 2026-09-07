# Stage 14A ChatGPT Desktop MCP Pilot Checkpoint

- Date: 2026-09-03
- Decision: ADR-0028 accepted by the Product Owner
- Scope: local ChatGPT desktop pilot; PUBLIC Identity plus current-message Turn Contract only
- Status: implemented and globally registered on this owner-controlled Codex host

## What is implemented

`services.mcp_companion.server` is an official-SDK MCP 2.1.1 STDIO server
with two read-only tools:

- `havre_companion_profile` loads exact owner-approved Identity artifacts and
  returns their versions plus explicit conversation rules;
- `havre_plan_reply` analyzes only the current message already visible to
  ChatGPT and returns distinct obligations, depth, stance, decision requirement,
  missing-history status, and a natural-response instruction.

The server initialization instructions put the essential fixed personality and
response behavior in the first 512 characters. The host registration is named
`havre-companion` and launches the repository's pinned virtual-environment
Python directly. It contains no credential or owner token.

## Privacy proof boundary

This pilot intentionally has no database or HTTP client and imports no Event,
Memory, User Model, retrieval, persistence, interaction, provider, or delivery
service. Every tool result says:

```text
scope = PUBLIC_IDENTITY_AND_CURRENT_CHATGPT_MESSAGE_ONLY
private_havre_history_attached = false
durable_write_performed = false
oa70_used = false
```

The PRIVATE OA70 artifact and untracked owner learning package were not opened
or transformed. ChatGPT's visible conversation can provide ordinary short-term
context, but that is not governed HAVRE long-term Memory.

## Verification

Focused verification:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_chatgpt_mcp_companion tests.test_response_plan -v
```

Result: **17 passed, 0 failed, 0 skipped**. This includes an actual spawned
STDIO server, MCP initialization, tool discovery, a structured tool call,
read-only annotations, PUBLIC identity loading, Chinese multi-request
preservation, prior-context detection without history loading, and OA70/private
history absence assertions.

The registration was verified by `codex mcp list` as enabled with command
`C:\HAVRE\.venv\Scripts\python.exe -m
services.mcp_companion.server`, no environment variables, and no authentication
material.

Complete fresh-database verification used the dedicated disposable database
`havre_stage14_20260903_01`:

- primary suite: **592 passed, 0 failed, 0 skipped**;
- isolated pinned Torch suite: **62 passed, 0 failed, 0 skipped**;
- combined: **654 passed, 0 failed, 0 skipped**;
- both Python environments passed `pip check`;
- Python compile and contract-schema export completed successfully;
- `audit-provenance` returned `[]`;
- `git diff --check` passed (line-ending notices only).

This is implementation and regression evidence, not proof that the owner will
prefer the resulting conversations. The separate resumable 35B artifact
transfer remains incomplete and is neither loaded nor required by this pilot.

## How the owner tests it

1. Restart ChatGPT desktop so it reloads the shared MCP configuration.
2. Type `/mcp` and confirm `havre-companion` is connected.
3. Start a normal conversation. For the first diagnostic turn, ask:
   “请按 HAVRE 的人格回答，并先调用 havre_plan_reply，完整理解我的所有问题。”
4. Use real representative conversations rather than synthetic style prompts.

The pilot passes its product gate only if the owner would keep using the answer,
needs less restating/correction, sees no fabricated familiarity, and prefers it
to ordinary ChatGPT on the same task. Protocol success alone is not product
success.

## Stop boundary

Stop before any HAVRE private-history tool, OA70 use, response capture,
persistence, Memory write, automatic routing, default-model change, training,
or deployment. Stage 14B requires a new explicit owner decision after the
Stage 14A owner-visible usefulness trial.
