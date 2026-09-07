# Ordinary reply recovery checkpoint — 2026-09-05

## Authorization and incident evidence

The owner explicitly approved recovery and a fix for disconnect/timeout requests
that block later chat. No source erasure or automatic re-sending is part of this
repair. Before activation, production head was 0067, API/Memory/Diary were healthy,
and one ordinary request from 2026-09-04 21:27:59 America/Chicago remained
`processing`. Its USER_MESSAGE was durable, without durable ContextPack, route,
inference-attempt, terminal Event, or active provider child. The missing durable
lineage does not establish how far a volatile provider invocation progressed.

The old service failed a new AnyIO CancelScope regression: repeated level
cancellation interrupted failure reconciliation, leaving status `processing`.
Earlier tests only cancelled the task once. This reproduces a concrete mechanism
consistent with a streaming disconnect, not proof that this phone disconnected
at a particular instant. The PWA also stopped polling while a pending request
existed, preventing terminal state reconciliation without a reconnect.

## Repair

- The API owns ordinary streaming reply tasks separately from their HTTP viewer.
  Disconnecting leaves an accepted turn running through Core and durable commit.
- The service drains cancellation cleanup outside the caller's cancel scope.
  Task timeout is 300 seconds; service shutdown drains owned replies and the
  in-flight recovery transaction before closing the runtime.
- Every 15 seconds, the API scans only its owner for ordinary processing requests
  older than 330 seconds lacking durable ContextPack lineage. A short transaction
  locks at most 25 rows with SKIP LOCKED, appends source-qualified failure Events,
  marks them failed, releases interaction leases, and defers claimed fusion.
  Existing completion fencing rejects late writes. No migrations are rewritten
  or added; exact-source privacy and training policy remain unchanged.
- Expired failures use the existing no-durable-ContextPack contract with
  `failure_code=interaction_expired`. Its `context_build` stage names the available
  persisted lineage, not a claim about the historical provider execution stage.
- PWA v13 bounds stream waiting at 350 seconds and ordinary API reads at 20
  seconds. Reconciliation reuses idempotency keys for ambiguous results. It polls
  pending turns after the active fetch has ended, restores failed-message drafts,
  and exposes a manual retry affordance without overwriting a different draft.
  Retry requires the owner to press Send; it is a new user turn, not an edit to
  the failed turn. Unsupported or more restrictive source policies fail closed.
- The service worker updates its versioned assets. It does not forcibly reload a
  page with an unsaved draft. The owner must refresh/reopen to use the new client.

## Verification

Disposable database: `havre_interaction_recovery_test_20260905`, freshly migrated
0001–0067. Full suite uses this dedicated database, never production.

- New recovery tests: 8 passed, including actual ASGI stream disconnect and
  cancellation while the chat-lease transaction is starting.
- Primary suite: 730 passed in 78.705 seconds; pinned Stage 9A Torch suite: 62
  passed in 87.551 seconds; combined 792 passed with zero skipped database tests. Logs are under
  `var/interaction-recovery-primary-tests.log` and
  `var/interaction-recovery-torch-tests.log`.
- Node PWA contract, pip check, Python compileall, and git diff --check passed.
- Test-database provenance audit returned `[]`.
- After all tests, the exact disposable database was dropped only after verifying
  no remaining connections. Production data was not deleted; PostgreSQL remained
  running in its pre-task state.

## Production activation

The owner-local API and worker restarted at 2026-09-05 08:51:37 UTC (03:51:37
America/Chicago), after checking that the exact old request was the only ordinary
processing turn. API launcher PID 24968 and worker launcher PID 22360 were verified
after launch. The shared PostgreSQL server and pre-existing local model remained
running; no migration changes were needed. Startup used the existing launcher and
its hidden-window, least-privilege, private-serve-attested path.

At 08:51:42 UTC the startup sweep terminalized that request with
`interaction_expired`, retained its original USER_MESSAGE and identical content
hash, appended an exact-causation INTERACTION_FAILED Event, and released its
chat lease. No assistant Event or duplicate user prompt was created. Ordinary
processing requests then numbered zero. Production provenance audit returned
`[]`; readiness, timeline, Memory, and Diary returned HTTP 200; the live HTML
referenced PWA v13. The source text is intentionally not copied into this document.

No synthetic result establishes phone UX, GPT response
quality, or immunity to database outages/forced process termination. Cleanup can
take longer than the nominal deadline while an already-started commit drains.
Recovery resumes when the API/database become available; it cannot finish while
the owner's PC is off. Existing daily-review and contact schedules are unchanged.
