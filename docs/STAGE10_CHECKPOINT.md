# Stage 10 Checkpoint — User-Controlled Deployment + Reliability

Date: 2026-08-22

Implementation source: `22700334eb375e1ee21283ca9d40efe5650cd8ec`

Migration head: `0034_stage10_backup_fk_index.sql`

Deployment source snapshot: `sha256:52cdecdc609c7805514f4fd4fa206ac1ddee7cdbc4b7851f1b4380145eb69457`

## Decision boundary

Stage 10 technical implementation and native exit evidence are complete. Final
independent review reported **P1=0, P2=0**. This is an owner-local, infrastructure-only
deployment; it is not a behavioral HAVRE release. Seeds 9201 and 9202 remain
candidate-only, neither adapter was promoted or deployed, and the manifest has
`adapter_deployment_authorized=false`. The deterministic provider remains a
replaceable integration fixture. Production behavioral routes and the worker
remain unavailable under the `infrastructure_only` scope.

Stage 9B, new training, Dataset v5, ambient microphone use, new external
Context Sources, and Stage 12 remain out of scope. The Product Owner authorized
Stage 11 only after blocker-free Stage 10 independent review; that gate is now
clear and Stage 11 is the next authorized stage.

## Implemented slice

- Immutable, hash-bound API, operations, PostgreSQL, and Caddy images; exact
  committed source/config/build-recipe closure; deny-all root Docker context;
  artifact-hashed Linux wheel lock; runtime source/image/component attestation.
- Durable release manifests, Product Owner infrastructure approvals, typed
  health evidence, two-phase preflight/activation, latest-only rollback, and
  fail-closed production behavior/adapter gates.
- HTTPS/HSTS, protected file secrets, liveness/readiness/version, bounded
  content-free metrics, resource limits, restart policies, and separate
  application, erasure, release, backup, and restore credentials.
- Release, backup, and restore one-shot profiles; checksum/expiry/release-bound
  PostgreSQL backups; serialized erasure watermarks; all-owner restored-backup
  deletion replay; absence/provenance audit; retention prune.
- Restore cutover finalization reassigns temporary restore-owned objects to the
  administrator before role bootstrap. `PUBLIC` database CONNECT is revoked,
  and four actual LOGIN secrets are checked independently.
- Exact LOCAL_ONLY owner export membership, indirect owner spans, explicit
  source-erasure closure, and an external hash-chained erasure ledger.

## Native immutable deployment evidence

Tracked evidence: [`../evals/reports/stage10_20260822/native-deployment.json`](../evals/reports/stage10_20260822/native-deployment.json)

- Docker Desktop 4.87.0, Engine 29.7.2, Compose 5.4.0, and a loopback-only
  registry were used on the owner-controlled Windows host.
- A fresh PostgreSQL 18/pgvector volume applied migrations `0001` through
  `0034` and bootstrapped the single synthetic owner.
- Final API image:
  `sha256:8dca9bdd550c228b263ec5f858a02afd637501a9918a90ceed5643769577dc93`.
- Final operations image:
  `sha256:da921dcff322ede1bb4de89e847d0a0732eded93e8808061737fbcbc8a6ede0c`.
- Final infrastructure manifest:
  `sha256:e770502ef13bc56a03115e9fdc3d6018863bc47ff0c3a68df5fbda4d74a626b5`;
  applied deployment `01a0259a-50f1-7cd4-8a81-6d5e8b6a5d8e`.
- Before the applied record, HTTPS readiness was 200 with
  `release_active=false`, HSTS was present, and an authenticated behavioral
  request was 503. After the exact applied record, readiness reported
  `release_active=true`; behavior remained 503 because the release is
  infrastructure-only.
- A separate immutable image was actually deployed, inspected, and then
  rolled back to the pinned prior image. The distinct digests, deployment IDs,
  and rollback record are preserved in the tracked native evidence.
- The exact final image with `restart: unless-stopped` automatically restarted
  a disposable crash probe once. Stopping only HAVRE PostgreSQL made readiness
  fail closed at 503; database recovery returned readiness to 200 while the API
  remained healthy.

## Backup, restore, erasure, and export evidence

- Final release-bound backup manifest:
  `sha256:091f7de03f315550a4abc17aade1e5ec7237346807d24f5184f07e0921b15212`;
  artifact:
  `sha256:2ae8cc71c8b8b73dae8e1c152c5379335aa7591057eba18c443a3cfec6de0869`.
- The backup recorded erasure watermark 1. A bounded synthetic PRIVATE event
  was erased at sequence 2. Restore replay applied exactly one directive from
  1 through 2; the source and marker were absent, `absence_verified=true`, and
  provenance violations were 0.
- Restore returned `cutover_ready=false` until the checked finalization and
  role bootstrap ran. Afterwards the restore login owned zero HAVRE objects;
  the actual app, erasure, release, and restore LOGIN secrets were distinct and
  matched their exact least-privilege boundaries.
- An exact-image API started against the restored target with ready/preflight
  200 and `release_active=true`; the isolated release credential independently
  verified the restored approved/applied manifest.
- Owner export `01a025a0-d155-7ef9-b2bb-038b7cd4ff03` verified with content hash
  `sha256:cc1c7d3b945ec087787757af4d8b1bc9bea831e945d13e697b18cdcb819e3c9f`.
  All destructive drills used synthetic markers; OA70 and real private owner
  data were not accessed.

## Regression and controlled reliability

Dedicated disposable PostgreSQL 18 database:
`havre_stage10_native_final_tests` on `127.0.0.1:55432`.

- Primary suite excluding the separately pinned Stage 9A environment:

  ```powershell
  $env:HAVRE_TEST_DATABASE_URL = 'postgresql://postgres@127.0.0.1:55432/havre_stage10_native_final_tests'
  $modules = Get-ChildItem -LiteralPath tests -Filter 'test_*.py' | Where-Object { $_.Name -ne 'test_stage9a_real_contracts.py' } | Sort-Object Name | ForEach-Object { 'tests.' + $_.BaseName }
  .\.venv\Scripts\python.exe -m unittest $modules -q
  ```

  Result: **328 passed, 0 failed, 0 skipped** in 36.484 s.
- Isolated Stage 9A real-contract suite:

  ```powershell
  .\var\stage9a\env-windows\Scripts\python.exe -m unittest tests.test_stage9a_real_contracts -q
  ```

  Result: **57 passed, 0 failed, 0 skipped** in 39.652 s.
- Total: **385 passed, 0 failed, 0 skipped**.
- Focused Stage 10 contract/integration suite: **42/42 passed**.
- Provenance audit: `[]`. Stage 4/5/6/7/8/9/10 foreign-key index audits:
  all `[]`. Role-boundary verifier passed. `pip check`, `compileall`, and
  `git diff --check` passed.
- Controlled report:
  [`../evals/reports/stage10_20260821/reliability.json`](../evals/reports/stage10_20260821/reliability.json).
  It records 64/64 synthetic LOCAL_ONLY, memory-ineligible requests at
  concurrency 8, 0 failures, 79.022 requests/s, median 88.703 ms, p95
  112.290 ms, maximum 120.274 ms, content-free metrics, bearer rejection, and
  fail-closed provider/database health behavior. These fixture measurements
  are not production capacity or conversational-quality claims.

## Independent review and handoff

The previous native Docker/Compose evidence blocker is closed. Final independent
review of this exact source, native evidence, live Docker/DB state, and
checkpoint reported **P1=0, P2=0**. Stage 10 is complete. The Product Owner's
conditional authorization for Stage 11 is now active.

No adapter was promoted or deployed, no PRIVATE OA material left the owner host,
and no production behavioral HAVRE was activated.
