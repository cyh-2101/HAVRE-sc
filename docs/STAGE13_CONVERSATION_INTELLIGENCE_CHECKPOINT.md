# Stage 13 Conversation Intelligence Checkpoint

Status: **In progress — Stage 13A implemented and verified; repeated 14B raw controls rejected; 35B artifact transfer incomplete; no model promotion or training**

Date: 2026-09-03

## Owner decision

The Product Owner authorized the refined conversation architecture, requested a
new stage and documentation, and instructed the agent to continue until a real
owner gate is reached. ADR-0027 records the resulting scope.

## Stage slices

| Slice | Scope | Current status |
|---|---|---|
| 13A | Versioned Turn Contract, pre-retrieval Memory Gate, evidence chain | Implemented and verified |
| 13B | Memory Broker layering and lean Context Compiler | Gate implemented; further compiler evidence in progress |
| 13C | Repeated local Replyer comparison and full ContextPack/Core A/B | 14B v6/v7 raw arms rejected; 35B pinned artifact download in progress and unverified |
| 13D | Owner conversation comparison and default-model promotion decision | Blocked on explicit owner decision |

## Implemented in the current uncommitted worktree

- `response-planner-v2` is deterministic, hash-bound, and independent of retrieval
  output.
- It adds `decision_requirement=none|recommend_one` and keeps user obligation text
  escaped and untrusted.
- `interaction-orchestrator-v8` creates the Turn Contract before durable Memory
  retrieval. `memory_need=none` uses the explicit persisted empty-result path;
  `possible|required` permits real retrieval.
- `context-builder-v12` and
  `context-presentation-v7-practical-utility` carry the versioned contract.
- historical `response-plan-v1` remains schema-exported and replayable; v2 is a
  separate schema.
- The Practical Utility Gate makes owner-usefulness, early actionability,
  truthful uncertainty, continuity, and acceptable interaction cost explicit
  non-averagable criteria.
- The exact Qwen3.6-35B-A3B Q4_K_M manifest is pinned for an isolated
  llama.cpp/CPU-MoE candidate arm. No FreeToken, driver, or default-route change
  is included.

## Completed evidence

- focused Turn Contract, application-boundary, and candidate-asset tests pass;
- complete primary suite: 587/587, zero skips;
- pinned Torch suite: 62/62, zero skips;
- combined verification: 649/649, zero skips;
- generated-schema equality, both compile checks, both dependency checks, and
  diff validation pass;
- PostgreSQL provenance audit returns `[]`;
- a real database-boundary test proves the pre-retrieval Memory Gate behavior;
- three repeated 14B PUBLIC synthetic v2 raw arms are preserved and semantically
  reviewed. The v2 wording is rejected because hard truncation and invention
  failures recur in all three runs.
- a separate three-run 14B v7 practical-utility arm completed 39/39 requests
  normally. Exact-output agreement was 12/13, 12/13, and 13/13. V7 repaired
  the v6 truncation and missing-recommendation behavior, but the Practical
  Utility Gate still fails on invented decision/migration claims, generic buying
  criteria, and non-actionable “save tonight” guidance. Immutable report hashes
  are `988971e0c40d8068058f54a36008edf888441a41ef5ce55b13c383d50cb66e33`,
  `e1c432325e023f54e7c4c07d94321a1e15cb0468c3b60d580d6b5e8116210ebb`,
  and `5867d0c0e023f2b75e8b31aced892d6e67fdf8c034f970740be23d6da5836e37`;
  the proposal-only semantic review file is
  `sha256:563c84d4bf3ba5103c8f2f39916e9ec1cfc067793f07b182b065976d3493fe10`;
- the daily exact Qwen3-8B/no-adapter service was restored and `/health/ready`
  reports ready after the 14B comparison.

## Evidence still required

- download/hash verification and bounded raw replay of the 35B Q4_K_M candidate;
- measured 35B load, RAM/VRAM, first-token, decode, and restore behavior;
- full ContextPack/Core A/B before any owner comparison;
- owner approval at Stage 13D before changing the daily binding.

## Explicit limits

This checkpoint does not prove conversation quality, naturalness, usefulness,
production readiness, or model promotion. No private owner conversation was sent
to an external model. No training, driver change, automatic routing, deployment,
or lifecycle mutation is authorized or performed.
