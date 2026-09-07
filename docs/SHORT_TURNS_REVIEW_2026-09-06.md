# Short conversational turns and explicit continuation

Owner authorization: “好，按你的建议做”, after the OA70 comparison and the concrete
short-turn / optional continuation recommendation. Prior Context A/B owner feedback
is a product-level rejection of excessive verbosity, not pairwise votes and not
training consent. Prior targeted-recall changes and unrelated work are preserved.

## Implemented scope

- Versioned owner-experience-first-v3-short-turns and response-planner-v6/v7.
  Default speaking budget is brief even for a long personal story. Context clauses
  do not each require commentary; no obligatory validation/analysis/advice/question
  sequence. Explicit task/detail requests, facts, corrections and action receipts
  remain complete. This changes speaking instructions, not evidence admission,
  retrieval thresholds, Context Compiler, Identity, provider or output token limits.
- The explicit “再说点” button sends one visible owner request through the existing
  ordinary interaction, current session/privacy and idempotent retry path. It is
  absent while drafting, generating, recovering a pending request, reading focused
  history, or when the last item is proactive/from another session. It never wipes
  a draft or grants cloud access that the existing route does not already permit.
- PWA v17 preserves paragraph, code and list boundaries. Eligible small ordinary
  multi-paragraph replies reveal at four-second intervals; input pauses them and
  a new owner message cancels their automatic reveal. Saved remainder is accessible
  immediately. This is a view of one governed Event, not new separately delivered
  messages. Full saved text remains intact and may appear in subsequent context;
  no claim is made that the owner read every paragraph. Historical read watermarks
  remain coarse timeline watermarks.
- The timeline adds only a read-only projection of the existing response-policy
  category so unknown/legacy/Core-replaced output is never paced. No SQL migration
  or new API action/schema is needed. The ResponsePlan JSON schema adds planner
  versions while preserving historical versions and their render behavior.
- Eleven constructed multi-turn regression cases cover casual talk, continuation,
  correction, ambiguity, unknown recall, no callback, detailed explanation, code,
  stopping, Goal completion and cross-day conversation. They contain qualitative
  review expectations, not a keyword scorer or measured semantic acceptance.

## Evidence

Evidence directory: `var/short-turns-20260906/` (local, ignored).

- Focused reply/contract tests: 50 passed. Product and relational-continuation
  PostgreSQL tests: 67 passed, including idempotent LOCAL_ONLY “再说点”.
- Node PWA contract passes, including fake-clock 3999/4000ms boundary, pause,
  resume, cancel, explicit remainder, structured output and continuation guards.
- Actual Edge DOM with synthetic mocked HTTPS API: ten interaction checks pass,
  five simulated requests; 390x844 and 1100x844 have no horizontal overflow and
  no page JavaScript errors. Screenshots are illustrative synthetic conversations,
  not GPT outputs or physical-iPhone evidence. Review included the mobile image.
- Complete suite, current source snapshot, benchmark and runtime verification:
  see the final verification section below.

## Limits and stop boundary

No new cloud generation or semantic judging has been performed. The earlier
18-payload targeted-recall cloud proposal remains unapproved and was not retried.
No conclusion that GPT now consistently matches OA70, no measured latency gain,
and no real-device or repeated-use quality claim follows from deterministic tests.
The speaking budget is deliberately soft: a model may still over-explain, which is
an owner-observed regression to inspect, not something a character cutter hides.

No training, model promotion, push, commit or new Stage is authorized by this task.
Existing original and uncommitted targeted-recall work is preserved. Code review
in this task is self-review, not an independent reviewer verdict.


## Final verification and activation

Execution source: `sha256:fdddede16771aa1e09a0c2981445780da64df0ecbd174e2ceac7b14d37aa1e2a` (identical before and after the final complete
suite). Final primary **860 passed**, pinned Torch **62 passed**, total **922**;
zero failures, errors or skips. `verification-summary.json` binds the logs and
benchmark artifacts. The primary run covers all `tests/test_*.py` except the
three pinned-Torch modules, which pass in their required separate environment.

- Dedicated database: `havre_context_engine_test_20260906`, verified loopback port
  55432 and PostgreSQL data directory before the run. Existing fresh/upgrade tests
  run through migration 0071; this patch introduces no migration. PostgreSQL was
  already running and remains running. CLI `audit-provenance` returns `[]` with
  an isolated test auth token and erasure ledger.
- First complete run exposed two fixed-budget overflows, not a failing retrieval
  threshold. Compressing duplicate owner guidance from 2408 to 1898 characters
  preserved its boundaries and the new short-turn behavior. The budgets and
  inference output limits were not enlarged. Follow-on parsing also now retains
  the request verb in “再比较 …” / “再给我 …”, rather than mislabeling that request
  as optional context. The failed first run is retained as a diagnostic.
- `scripts.benchmark_personal_context` with baseline
  `b5664e53ccb527d89a5b07f036b3dabd2f54ef34`: 13/13 budget cases retain the raw
  experience within budget. Beyond-256-event, two-year-old, long-tail and nearby
  correction cases retain their sources; absent and ambiguous cases remain
  conservative. These are source/admission checks, not semantic preference scores.
- `scripts.benchmark_targeted_recall`: all 16 final source sets match the prior
  targeted patch. S03 retains both person sources and S04 both project sources.
  No target, global threshold or compiler policy was altered for these results.
- Schema export, pip check, compileall and diff check pass. Historical planner
  version rendering is explicitly tested. Self-review checked request completeness,
  draft/idempotency/privacy handling, timer lifecycle, preserved full-text lineage,
  structured/urgent output, and the existing Goal/relational continuation boundaries.

The existing owner-local API and worker were restarted using
`scripts/start_havre_desktop.ps1 -RestartApp -NoBrowser` after verifying no active
owner interactions. Both process identities are guarded by the existing launcher.
Readiness is HTTP 200, migration head remains 0071, and public shell v17 plus the
new authenticated read-only timeline projection are confirmed. Before/after
provider records differ only in `observed_at`: GPT-5.6-sol/medium, the exact
unadapted Qwen3-8B route, tokenizer, serving settings and model artifacts are
unchanged. Private Tailscale Serve attestation passes. No test chat was inserted
into production and no new model-generation evaluation call was made.

Activation includes the preceding already-authorized targeted-recall repair in
this checkout, which passed the combined suite and unchanged 16-case source
regression. The production Context architecture, compiler, retrieval thresholds,
model settings and reminder permissions remain as before. Refresh the existing
web/PWA page to load the new shell; the service worker does not force a reload
that could discard an in-progress draft. Physical-iPhone and owner semantic
experience remain unmeasured.
