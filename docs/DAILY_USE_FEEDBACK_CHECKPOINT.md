# Daily Web Chat, Episode Memory, and Owner Feedback Checkpoint

- Date: 2026-08-22
- Decision: ADR-0021 accepted by Product Owner
- Migration head: `0037_daily_learning_canonical_hash_guards.sql`
- Model used for owner-local integration: `qwen3-8b-stage9a-qlora-seed-9201`
- Model lifecycle: development candidate only; no promotion or deployment
- Stage 9B/training: not started and not authorized
- Exact implementation commit: `8c2f06c554906b22e635a4383c45d6867fe7810e`
- Exact implementation source snapshot: `sha256:4f6282e3b2d1d73473d46919f20b006988ceb5a5f7a4a3901ccce3a897ac35d6`

## Delivered owner flow

`scripts/start_havre_desktop.ps1` starts the exact loopback Seed 9201 candidate,
applies additive migrations to the owner-local database, starts the existing
FastAPI/Core process on `127.0.0.1:8765`, verifies exact provider/adapter
attestation, and opens `/chat` unless `-NoBrowser` is supplied.

The Web product provides continuous conversation/history, durability-gated
streamed rendering, thumbs feedback, owner-edited alternatives, reason labels,
a feedback pool, issue classification for non-training review, response-length
preference, active Memory inspection, episode summaries, and concentrated
episode-suggestion review. The browser persists only a session UUID in local
storage and receives an HttpOnly owner-session cookie through the protected
loopback bootstrap; owner-data responses are `no-store`. Message content remains
in owner-local PostgreSQL.

Starting a new conversation atomically and terminally closes the prior session
as one episode. Its member table freezes every ordered
`USER_MESSAGE`/`ASSISTANT_MESSAGE` Event ID and hash. The v1 summary copies only
eligible owner messages, is deterministic/extractive, and retains a conservative
derived DataPolicy. Normal Web turns do not enqueue the legacy one-candidate-per-user-
Event Memory job. Existing CLI/API behavior remains compatible for diagnostics.
Core also supplies policy-eligible recent turns from the active session to the
replaceable model provider with exact user/assistant roles and Event references;
conversation history is not a browser-only display illusion.

## Feedback and training boundary

The original assistant Event is never overwritten. Every feedback revision
binds the exact request, session, trace, user/assistant Events, ContextPack,
route, inference response, provider, model, adapter, tokenizer, and serving
configuration. A rewrite is stored as the owner's proposed alternative.

Saved feedback always remains `training_eligible=false`. The daily UI does not
offer training approval, and both the service and direct-SQL boundary reject
`approved_for_personalization_training` while Stage 9B is inactive. A future
authorized stage must add a separately privileged durable owner-approval path;
the present checkpoint creates no dataset, run, adapter, promotion, or
deployment.

## Memory layers

1. Raw Events are complete conversation history under existing retention and
   owner erasure.
2. Episode summaries are source-linked shared-history recall artifacts, not
   claims about owner identity.
3. Episode Memory suggestions are a concentrated reviewed queue. Accept/reject
   records the review; v1 does not silently create a canonical MemoryRevision.
4. Existing accepted Memory continues to use its candidate/revision/correction/
   retraction lifecycle.
5. Feedback/edit evidence and future training authorization are separate from
   all four layers.

## Verification

Dedicated disposable database:

```text
postgresql://postgres@127.0.0.1:55432/havre_feedback_fix_20260822
```

Exact primary command:

```powershell
$env:HAVRE_TEST_DATABASE_URL='postgresql://postgres@127.0.0.1:55432/havre_feedback_fix_20260822'
$modules=Get-ChildItem -LiteralPath tests -Filter 'test_*.py' |
  Where-Object {$_.Name -ne 'test_stage9a_real_contracts.py'} |
  Sort-Object Name |
  ForEach-Object {'tests.'+$_.BaseName}
.\.venv\Scripts\python.exe -m unittest $modules -q
```

Result: **412 tests, 0 failures, 0 errors, 0 skips** in 42.034 seconds.

Isolated immutable Stage 9A command:

```powershell
$env:HAVRE_TEST_DATABASE_URL='postgresql://postgres@127.0.0.1:55432/havre_feedback_fix_20260822'
.\var\stage9a\env-windows\Scripts\python.exe -m unittest tests.test_stage9a_real_contracts -q
```

Result: **57 tests, 0 failures, 0 errors, 0 skips** in 36.261 seconds.
Combined: **469/469**.

Additional checks:

- focused daily feedback/episode/API suite: 17/17;
- fresh `0001` through `0037` migration path: passed;
- populated `0036` fixture with pre-correction episode evidence: `0037`
  rejected automatic upgrade with SQLSTATE `55000` and retained the exact
  legacy summary; immutable owner-reviewed text was not rewritten;
- contract schema export: passed and reviewed;
- `compileall`: passed;
- `pip check`: no broken requirements;
- provenance audit: `[]`;
- `git diff --check`: passed (line-ending notices only);
- application-role direct SQL rejects forged inference lineage, privacy/hash,
  training authorization, cross-session membership, and forged episode summary;
- owner export contains feedback/review/episode artifacts; erasure-ledger
  replay removes feedback head/revisions/review, episode, members, suggestion,
  and the session link with absence verified;
- cancellation regressions cover reservation, mid-provider, and final database
  commit boundaries; no path leaves a request in `processing`;
- owner-local real runtime: `/version` reported exact Seed 9201 and Runtime
  Attestation v2; `/health/ready` and `/chat` returned HTTP 200; owner-data API
  rejected an unauthenticated request with 401 and accepted the protected
  HttpOnly bootstrap session; `/chat` returned `Cache-Control: no-store`;
- the real desktop login was `havre_desktop_application`, inherited only the
  intended application group, could insert reviewed feedback, could not delete
  Events, and reported migration head `0037`; the secret directory had protected
  inheritance and one owner FullControl rule before credentials were written.

No synthetic chat message was written to the owner's daily history for the
runtime smoke.

## Honest limits and stop boundary

- Client text streaming begins after durable completion. It improves rendering
  but does not reduce provider time-to-first-token; pre-commit interrupted-token
  reconciliation is not implemented.
- Extractive episode summary v1 is a provenance/retrieval baseline, not evidence
  of human-quality semantic consolidation or longitudinal benefit.
- Reviewed episode suggestions do not yet auto-promote canonical Semantic,
  Pattern, preference, or episodic Memory. Existing governed Memory lifecycle
  remains authoritative.
- Real owner usage and corrections are now needed to learn which failures belong
  to runtime, Memory/retrieval, policy/mode, or personality communication.
- Stage 9B, training, automatic dataset construction, online weight updates,
  adapter promotion/deployment, and new sensing/external-data paths remain out
  of scope.
