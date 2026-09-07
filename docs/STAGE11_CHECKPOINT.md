# Stage 11 Checkpoint — Native iPhone + Voice

Date: 2026-08-22

Implementation source: `4b2d3096c1b303bab8ffba58cb1e370ee4e67e92`

Status: **implementation checkpoint; Stage 11 exit is blocked**

## Decision boundary

The authorized Stage 11 implementation slice is present and its current code
review reported **P1=0, P2=0**. This checkpoint does not claim Stage 11 exit,
native-device validation, APNs delivery, or Product Owner approval of a new data
processor. Stage 12 has not begun and remains unauthorized.

Seeds 9201 and 9202 remain replaceable development candidates. Neither adapter
was promoted or deployed. No training, retraining, Dataset v4 change, OA70
rerun, Stage 9B work, ambient microphone, or new external Context Source was
performed.

## Implemented slice

- A SwiftUI iOS 17+ client uses the existing interaction, Scene, Proactive Core,
  delivery-reconciliation, and owner-action APIs. It contains no second
  personality, memory, notification policy, or Companion runtime.
- Text input and owner-initiated voice create ordinary Core interaction drafts.
  Speech recognition is on-device-only and fails closed when unavailable; raw
  audio is not retained. Playback uses the platform speech synthesizer.
- A durable FIFO offline queue preserves sequence and idempotency, stops on the
  first failure, persists before acknowledging UI actions, and reconciles
  responses by server event identity.
- Enrollment is bound to an authenticated, versioned owner/Core receipt.
  Transport stays quarantined until launch re-verification succeeds, and an
  owner/Core switch requires explicit protected local erasure.
- The bearer is device-bound in Keychain. Queue/cache files use iOS data
  protection, are excluded from backup, and have an explicit local-erasure path
  that also clears pending and delivered local notifications.
- The in-app inbox is an owner-isolated projection of existing Core records.
  Dismiss, snooze, stop, and reply actions retain the exact proposal and delivery
  attempt identities. Reply drafts are isolated per delivery attempt and are
  cleared only after durable queue persistence succeeds.
- Two generated contracts record the new projection boundaries:
  `mobile-enrollment-receipt-v1` and `proactive-inbox-item-v1`.

## Notification and privacy boundary

Current Stage 6 records are `simulation_only=true` and
`external_delivery_authorized=false`. The mobile projection redacts full message
content and exposes only the permitted generic preview for the foreground app.
The native scheduler checks both authorization fields and therefore schedules
**zero OS or lock-screen notifications** for current records.

Remote APNs enrollment, Push Notifications entitlement, background audio, and
production lock-screen delivery are not activated. Implementing them requires
an explicit Product Owner decision covering Apple as a processor, eligible
privacy classes, minimized payload/routing policy, credential ownership, and
notification preview behavior. A local-notification workaround must not convert
simulation evidence into delivery authority.

## Verification

Dedicated disposable PostgreSQL 18 database:
`havre_stage10_native_final_tests` on `127.0.0.1:55432`.

- Primary suite excluding the separately pinned Stage 9A environment:

  ```powershell
  $env:HAVRE_TEST_DATABASE_URL = 'postgresql://postgres@127.0.0.1:55432/havre_stage10_native_final_tests'
  $modules = Get-ChildItem -LiteralPath tests -Filter 'test_*.py' | Where-Object { $_.Name -ne 'test_stage9a_real_contracts.py' } | Sort-Object Name | ForEach-Object { 'tests.' + $_.BaseName }
  .\.venv\Scripts\python.exe -m unittest $modules -q
  ```

  Result: **339 passed, 0 failed, 0 skipped** in 37.914 s.
- Isolated Stage 9A real-contract suite:

  ```powershell
  .\var\stage9a\env-windows\Scripts\python.exe -m unittest tests.test_stage9a_real_contracts -q
  ```

  Result: **57 passed, 0 failed, 0 skipped** in 36.187 s.
- Total Python/PostgreSQL regression: **396 passed, 0 failed, 0 skipped**.
- Portable Swift tests used the pinned official image with networking disabled:

  ```powershell
  docker run --rm --network none -v 'C:\HAVRE\apps\ios:/workspace:ro' -w /workspace swift@sha256:d01f3252ff3942f9fabc7b94aade5ab4102b7c75cfe1b5f6cd9989c0733071a7 swift test --scratch-path /tmp/havre-stage11-build --parallel
  ```

  Result: **13/13 XCTest cases passed**. This covers the portable
  `HAVREMobileCore`, not code excluded by `#if os(iOS)`.
- Exact-source synthetic benchmark:
  [`../evals/reports/stage11_20260822/portable-core.json`](../evals/reports/stage11_20260822/portable-core.json).
  It enqueued and reconciled 5,000 LOCAL_ONLY synthetic envelopes with 5,000
  acknowledgements and zero remaining/blocked entries. Timing is diagnostic and
  varied materially between local runs; it is not a capacity claim.

  ```powershell
  docker run --rm --network none -v 'C:\HAVRE\apps\ios:/workspace:ro' -w /workspace swift@sha256:d01f3252ff3942f9fabc7b94aade5ab4102b7c75cfe1b5f6cd9989c0733071a7 swift run -c release --scratch-path /tmp/havre-stage11-benchmark HAVREMobileBenchmarks
  ```
- Provenance audit returned `[]`; Stage 4 through Stage 10 foreign-key audits
  returned `[]`; `pip check`, `compileall`, and `git diff --check` passed.
- Independent source review after the final fixes reported **P1=0, P2=0**.

## Exit blockers and handoff

Stage 11 exit requires both of the following:

1. **Native Apple evidence.** A Mac with Xcode 16 and an iOS 17+ simulator/device
   must generate the project and compile/run the SwiftUI, Keychain,
   UserNotifications, Speech, and AVFoundation paths. Physical-device evidence
   is required for on-device speech availability, permission UX, Local Network
   access, protected-file behavior, local erasure, and playback. Portable Linux
   Swift tests do not substitute for this evidence.
2. **Product Owner APNs/privacy decision.** Native push and lock-screen delivery
   require explicit approval of Apple processing/data routing, eligible privacy
   classes, minimized payload contents, preview policy, signing/push credential
   custody, and failure/reconciliation behavior. After approval, APNs and exact
   device delivery still require implementation and native validation.

Until then, Stage 11 remains at this implementation checkpoint. The app is an
in-app/text/voice foundation, not a completed native push release. Stop before
Stage 12, adapter promotion/deployment, Stage 9B, new training, ambient sensing,
or any unapproved external data source.
