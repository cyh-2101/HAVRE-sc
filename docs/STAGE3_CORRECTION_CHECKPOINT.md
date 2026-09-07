# Stage 3 Acceptance Correction Checkpoint

Status: **Accepted by the Product Owner; Stage 3 approved and complete**

Date: 2026-08-14

Source HEAD: `e87326703aa73abe66e9640827e6ebafda92778d`

Current source snapshot: `sha256:9a43713e082dec08039a93c673c7a0af812b881dcb0d5d3da68a0b17e7075436`

The Product Owner reaccepted Stage 3 on 2026-08-14, with approval bound to source
snapshot `sha256:9a43713e082dec08039a93c673c7a0af812b881dcb0d5d3da68a0b17e7075436`.
Existing Stage 3 benchmark directories were not overwritten. Stage 4, User
Model, Intervention Policy, Scene, Reflection, training, LoRA, and proactive
runtime remain unauthorized and unimplemented.

## Correction summary

- Added shared production runtime attestation in `mlsys/serving`; benchmark code
  now consumes the same boundary instead of owning a stronger private copy.
- Added typed runtime-attestation references to provider/response/result
  contracts and the existing 20 generated JSON Schemas.
- Added migration `0006_stage3_runtime_attestation.sql`; migrations `0001`-`0005`
  were not changed.
- Added immutable, content-free runtime-attestation persistence and exact
  inference-attempt references.
- Split transient version endpoint failure from deterministic mismatch.
- Hardened local start/reuse/rollback/stop ownership and preserved the developer
  chat's real Companion Core, `LOCAL_ONLY`, and no-fake-history boundaries.
- Corrected historical documentation so configured, pinned, startup-attested,
  and per-interaction-attested are no longer used as synonyms.
- Closed the direct-adapter bypass: `generate()` and `stream()` now require a
  live attestation before opening any HTTP request, and self-hosted version and
  response lineage cannot omit its ID/hash.
- Closed the migration legacy exemption: historical rows retain contract v0,
  while an INSERT trigger rejects every new v0 attempt and every unattested
  self-hosted attempt.
- Added exact PostgreSQL cluster/version/pgvector identity checks before any
  create-database or migration action, aggregate best-effort rollback, and an
  orphan-safe missing-API-PID stop refusal.

## Findings, root causes, and fixes

### A. Configuration was being persisted as runtime identity

Root cause: `OpenAICompatibleProvider` built `ProviderVersion` and response
`VersionReferences` directly from settings. `/props` could prove a llama.cpp
build but not the model artifact behind a reused alias. Benchmark-only process
verification did not protect ordinary Companion interactions.

Fix: runtime construction now hashes and binds checked-in manifest bytes,
runtime state, PID and process creation time, executable path/hash, exact launch
arguments, model path/size/hash, loopback binding, disabled request logging/Web
UI, serving configuration, engine build expectation, and model alias. The
result is an immutable typed attestation with a stable content hash for one
process lifetime. Each provider version check cheaply revalidates PID/start
time/executable/arguments and then checks the live build and loaded alias.
Missing or mismatched evidence fails closed before inference.

### B. Version-check failure lost its type

Root cause: endpoint transport errors and deterministic mismatches escaped as
ordinary `RuntimeError`, so the orchestration fallback stored `internal_error`
with `retryable = false`.

Fix: `ProviderVersionError` carries only a safe code, retryability, and safe
message. Transport/timeout/unavailable endpoint failures become
`model_unavailable`, retryable `true`. Process/build/model/alias mismatch becomes
`provider_protocol_error`, retryable `false`. Interaction request state,
`INTERACTION_FAILED`, and API error detail use the same values. A version-stage
failure creates no inference-attempt row and no `ASSISTANT_MESSAGE`.

### C. Developer startup trusted health and lacked exact ownership rollback

Root cause: `start_havre_local.ps1` treated HTTP 200 on port 8080 as identity
and its existing API reuse check trusted a small health document. Failure after
partial startup did not use one explicit ownership model.

Fix: model reuse requires the same process-bound attestation used by Companion.
API reuse requires the recorded PID, executable, process start time, and exact
`/version` values including the model attestation ID/hash. A healthy but
unattestable listener is rejected. Startup records ownership for PostgreSQL,
llama.cpp, and HAVRE API; rollback runs in reverse order and stops only resources
started by that run. The stop path still refuses an unverified PID. Executable,
PID/start-time, and rollback behavior is exercised by executable PowerShell
tests rather than text-presence assertions alone.

### D. Windows temporary-directory hang

The acceptance reports include a full discovery still running after 124
seconds and an exact isolated-test timeout after 30 seconds. A 10-second
faulthandler dump places the blocked thread at
`tempfile.TemporaryDirectory(dir=var_root)` -> `tempfile.mkdtemp()` ->
`os.mkdir`, before `run_live_inference_benchmark()` or resource-collector
construction. Earlier quick runs therefore did not establish stability.

`var/` is a normal local NTFS directory rather than a junction/reparse point
and had ample free space during diagnosis, but the repository cannot identify
which Windows filesystem filter or security component intermittently blocks
`os.mkdir`. Explicit `NullResourceCollector` injection remains a valid removal
of hidden collector coupling; it is **not** claimed as the filesystem-hang root
cause or fix.

The test now delegates the entire real filesystem scenario to a fresh,
terminable Python worker. The worker creates one UUID-named child directly
under repository `var/`, runs the real live benchmark helper, verifies the
pending-directory protocol and atomic final publication, validates all four
report files and persisted workload binding, and removes only that exact owned
root. The parent imposes a 20-second hard timeout. On timeout it kills the
worker and invokes a second, ten-second-bounded cleanup worker whose path parser
accepts only the exact `.stage3-benchmark-fs-test-<UUID>` child of `var/`.
Failure diagnostics include the last flushed phase, owned path, stderr, and
cleanup result. A simulated 60-second block proves discovery returns a clear
timeout failure instead of hanging indefinitely; it is not skipped or swallowed.

Post-correction repetition used separate Python processes, not repeated cases
inside one interpreter:

- exact test: **10/10 passed**, 0 failed, 0 timed out; individual wall times
  1.059-1.158 seconds;
- complete discovery: **3/3 passed**, 0 failed, 0 timed out; 152 tests in
  9.151, 6.711, and 6.562 seconds respectively, each with 34 PostgreSQL skips.

This demonstrates bounded behavior and repeatability for these runs. It does
not prove that Windows filesystem/security software is universally stable, and
all prior timeout observations remain part of the record.

Clean-checkout portability was then corrected without moving filesystem work
back into the parent test process. Before creating the UUID-owned child, the
worker now creates a missing direct project `var/` with `parents=False` and
validates that it is a real directory rather than a file, symlink, or Windows
junction. Absolute path, direct-child, fixed-prefix, and UUID validation remain
mandatory. A worker-internal clean-project simulation begins with no `var/`,
runs the full benchmark/pending/atomic-publication/persistence scenario, and
then deletes only its exact outer UUID ownership root. Neither normal nor
timeout cleanup recursively removes repository `var/`.

Deletion was subsequently hardened against path replacement. Normal-run
`finally` and standalone cleanup call the same function, which revalidates on
every deletion attempt using `lstat`, symlink/junction checks, and the Windows
reparse-point attribute. Repository `var/` must still be the real direct child
of the project, and the UUID-owned root must still be its direct, real directory
child. A missing `var/` returns a no-op without creating it. Controlled worker
fixtures create (1) a `var` junction to another controlled directory and (2) a
UUID-named owned-root junction. Both deletion attempts are rejected and both
sentinels/targets are verified unchanged before controlled fixture teardown.

Commands used for the final filesystem/discovery evidence were:

```powershell
# Repeated ten times, with a new Python process each time.
.\.venv\Scripts\python.exe -m unittest tests.test_stage3_benchmark.Stage3BenchmarkHarnessTests.test_isolated_live_runner_writes_under_ignored_var_and_adds_baseline

# Repeated three times, with a new Python process each time.
.\.venv\Scripts\python.exe -m unittest discover -s tests

# Proves bounded timeout, missing-var portability, exact ownership, and reparse rejection.
.\.venv\Scripts\python.exe -m unittest tests.test_stage3_benchmark.Stage3BenchmarkHarnessTests.test_var_filesystem_worker_timeout_is_bounded_and_diagnostic tests.test_stage3_benchmark.Stage3BenchmarkHarnessTests.test_var_filesystem_worker_creates_missing_parent_var tests.test_stage3_benchmark.Stage3BenchmarkHarnessTests.test_var_filesystem_cleanup_rejects_every_nonowned_path tests.test_stage3_benchmark.Stage3BenchmarkHarnessTests.test_var_filesystem_cleanup_rejects_reparse_boundaries -v
```

## Current verification

### Earlier non-database evidence (historical)

- Three fresh full discoveries each completed: **152 tests; 118 passed; 0
  failed; 34 skipped**, in **9.151 s**, **6.711 s**, and **6.562 s**. Every skip
  is a PostgreSQL-gated integration test; this is not reported as a full pass.
- Focused serving/provider/runtime/PowerShell suite: **51 passed** in 4.016 s.
- Contract plus benchmark harness suite: **43 passed** in 1.053 s.
- The exact isolated benchmark test passed 10/10 fresh-process runs; the
  deliberate hard-timeout regression also passed by returning bounded,
  path-qualified cleanup diagnostics.
- Final portability verification: the four filesystem tests passed **4/4** in
  **2.073 s**; full discovery passed **153 tests** in **9.946 s**, with **119
  passed, 0 failed, 34 PostgreSQL skips, and 0 timeouts**.
- Final cleanup-boundary verification: all five filesystem safety tests passed
  **5/5** in **2.335 s**; full discovery passed **154 tests** in **9.999 s**,
  with **120 passed, 0 failed, 34 PostgreSQL skips, and 0 timeouts**.
- `pip check`: no broken requirements.
- Python compilation: passed.
- PowerShell parsing: passed for setup/start/stop/local chat scripts and the
  shared runtime module.
- `git diff --check`: passed.
- Contract export: 20 active JSON Schemas; five generated schemas changed for
  attestation references and stronger benchmark evidence.
- Direct unattested `generate()` and `stream()` each fail before HTTP; their
  regression transport counters remain zero.
- PowerShell behavioral tests reject wrong PostgreSQL data directory/version,
  missing pgvector, and missing owned API PID, and prove rollback attempts API,
  llama.cpp, and PostgreSQL even when multiple stops fail.
- The new database-level v0 INSERT bypass test is present but is one of the 34
  PostgreSQL-gated skips; no passing database result is claimed.

### Earlier pinned runtime attestation (historical)

The real pinned llama.cpp/Qwen service was started and verified without
PostgreSQL:

| Evidence | Value |
|---|---|
| llama.cpp live build | `b10405-e79e4bf66` |
| Loaded alias | `qwen3-8b-q4-k-m` |
| PID | `31548` |
| Process started (UTC) | `2026-08-13T18:01:13.257215Z` |
| Attestation ID | `stage3-runtime:31548:1786644073257215` |
| Stable attestation hash | `sha256:cc45f74d37f647086600c9acf5dc8777a9407cbf9f0f70692bc8f7341719ceda` |
| Model bytes | `5,027,783,488` |
| Model SHA-256 | `sha256:d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785` |

Repeated strong verification of that same PID produced the same attestation
hash. `ProviderVersion` then returned the pinned model, tokenizer, serving
configuration, engine commit, and this exact attestation reference only after
the live build and alias check.

### Renewed PostgreSQL and migration evidence

Windows Device Guard still blocks the MSYS PostgreSQL executable, and the run
did not disable or weaken that policy. Ubuntu 26.04 already exposed signed
PostgreSQL 18.4 and pgvector 0.8.1 packages. They were downloaded and extracted
without administrator installation under `/home/OWNER/.local/opt/havre-pg18`.
The dedicated cluster `/home/OWNER/.local/share/havre/postgres18-stage3` bound
only to `127.0.0.1:55432`. Before any database was created, checks established:

- PostgreSQL `18.4 (Ubuntu 18.4-0ubuntu0.26.04.1)`;
- exact `data_directory` equal to the dedicated cluster path;
- `listen_addresses = 127.0.0.1` and Windows-to-WSL loopback reachability;
- pgvector `0.8.1` available to `CREATE EXTENSION`.

Fresh database `havre_s3corr_fresh_20260814` applied `0001` through `0006` in
order. Its complete discovery passed **154/154, 0 failed, 0 skipped** in
**13.086 seconds**.

For the populated upgrade, committed source `e87326703aa73abe66e9640827e6ebafda92778d`
created the exact `0001`-through-`0005` schema and sent a real durable
`LOCAL_ONLY` Companion request. Current source then applied only `0006`. The
historical request remained readable; its attempt retained the intended v0
contract and null attestation references. The complete discovery then passed
**154/154, 0 failed, 0 skipped** in **10.609 seconds**.

The first fresh zero-skip run was **153 passed, 1 error, 0 skipped**. It exposed
a test-fixture ordering defect: the direct self-hosted HTTP-failure integration
test constructed a valid synthetic attestation but did not register it before
the durable failure insert. The database foreign key correctly rejected the
unregistered reference. The fixture now explicitly registers its attestation,
the focused regression passed, and both complete results above followed. No
production attestation precondition was weakened.

Provenance audits returned `[]` independently for the fresh database, the
populated-upgrade database, and the real-evidence database.

### Renewed durable real request

The pinned runtime was relaunched and strongly attested:

| Evidence | Value |
|---|---|
| llama.cpp | `b10405@e79e4bf660e19f2ad851e06c6913f7a8c5852621` |
| Qwen model | `model-qwen3-8b-gguf-q4-k-m-7c41481f` |
| Model SHA-256 | `sha256:d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785` |
| Attestation ID | `stage3-runtime:17536:1786650350448656` |
| Attestation hash | `sha256:3db71df2da8ae18e65c1926ab5f0255033e9b70257d53d7991624a048f883a2c` |

Request `019ffcaa-2c68-7217-8823-80a5fc8813e0`, trace
`fb0f5de6ccd837a0e56a3c4189c9110b`, passed through Companion Core and stored
`USER_MESSAGE` `019ffcaa-2c68-721a-b862-903a4eece718` plus
`ASSISTANT_MESSAGE` `019ffcaa-306e-7b0e-b786-e1644794f68d`. Effective privacy
was `LOCAL_ONLY`; cloud and training eligibility were both false. Provider
usage was 550 prompt, 25 output, and 575 total tokens. TTFT was 514.071 ms,
generation 329.908 ms, and provider inference total 854.282 ms.

### Renewed immutable benchmark pair

The new report directory is
`var/benchmarks/stage3-correction-20260814-final-9a43713e`; no historical report
was overwritten. It records exact source snapshot
`sha256:9a43713e082dec08039a93c673c7a0af812b881dcb0d5d3da68a0b17e7075436`.

- benchmark run: `019ffcac-50db-77c3-b2ad-08d0786477da`;
- measured requests: **32/32 completed**, zero typed errors;
- systems hash:
  `sha256:4a81b34c8eb6b787107cd6da152216458303766efb6536cc19007a3eacf1225c`;
- compatibility run: `019ffcac-696d-7bd8-aaa5-bac34a5bacbb`;
- compatibility hash:
  `sha256:6f69a9ce4541369570bed79bb4955bc5300a10159e760a91c851f169f4fc0070`;
- compatibility remains explicitly non-binding, `gate_status = not_evaluated`.

Both JSON reports reloaded through their typed contracts, their content hashes
and pair relationship validated, the process attestation matched, and the two
database rows contained the exact same immutable hashes. All four compatibility
cases completed; both structured observations remained non-parseable JSON, so
this is evidence, not a quality or release approval.

### Renewed verification commands

The acceptance databases used unique, dedicated names. The relevant commands
were:

```powershell
# User-local WSL packages; no Windows service or policy change.
wsl.exe -d Ubuntu -- mkdir -p /home/OWNER/.local/opt/havre-pg18/packages /home/OWNER/.local/opt/havre-pg18/root /home/OWNER/.local/share/havre/postgres18-stage3-socket
wsl.exe -d Ubuntu --cd /home/OWNER/.local/opt/havre-pg18/packages -- apt-get download postgresql-18=18.4-0ubuntu0.26.04.1 postgresql-client-18=18.4-0ubuntu0.26.04.1 postgresql-18-pgvector=0.8.1-2 liburing2=2.14-1
wsl.exe -d Ubuntu -- bash -lc 'for deb in /home/OWNER/.local/opt/havre-pg18/packages/*.deb; do dpkg-deb -x "$deb" /home/OWNER/.local/opt/havre-pg18/root; done'
wsl.exe -d Ubuntu -- env LD_LIBRARY_PATH=/home/OWNER/.local/opt/havre-pg18/root/usr/lib/x86_64-linux-gnu /home/OWNER/.local/opt/havre-pg18/root/usr/lib/postgresql/18/bin/initdb --pgdata=/home/OWNER/.local/share/havre/postgres18-stage3 --username=postgres --auth=trust --encoding=UTF8 --no-locale
wsl.exe -d Ubuntu -- env LD_LIBRARY_PATH=/home/OWNER/.local/opt/havre-pg18/root/usr/lib/x86_64-linux-gnu /home/OWNER/.local/opt/havre-pg18/root/usr/lib/postgresql/18/bin/pg_ctl -D /home/OWNER/.local/share/havre/postgres18-stage3 -l /home/OWNER/.local/share/havre/postgres18-stage3.log -o "-p 55432 -h 127.0.0.1 -k /home/OWNER/.local/share/havre/postgres18-stage3-socket" -w start

$env:HAVRE_DATABASE_URL = 'postgresql://postgres@127.0.0.1:55432/havre_s3corr_fresh_20260814'
.\.venv\Scripts\python.exe -m services.api.cli migrate
$env:HAVRE_TEST_DATABASE_URL = $env:HAVRE_DATABASE_URL
.\.venv\Scripts\python.exe -m unittest discover -s tests -q

# Repeated against havre_s3corr_upgrade_20260814 after the real 0005 seed and
# application of only 0006.
$env:HAVRE_TEST_DATABASE_URL = 'postgresql://postgres@127.0.0.1:55432/havre_s3corr_upgrade_20260814'
.\.venv\Scripts\python.exe -m unittest discover -s tests -q

$env:HAVRE_DATABASE_URL = 'postgresql://postgres@127.0.0.1:55432/havre_s3corr_evidence_20260814'
$env:HAVRE_PROVIDER_ID = 'self-hosted-openai-compatible'
$env:HAVRE_SELF_HOSTED_BASE_URL = 'http://127.0.0.1:8080'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_stage3_local_serving.ps1 -ReadyTimeoutSeconds 180
.\.venv\Scripts\python.exe -m services.api.cli demo 'Give me one grounded sentence about completing careful verification work.' --privacy LOCAL_ONLY --idempotency-key stage3-correction-local-only-real-20260814
.\.venv\Scripts\python.exe -m services.api.cli audit-provenance
.\.venv\Scripts\python.exe -m services.api.cli benchmark-inference --output-directory C:\HAVRE\var\benchmarks\stage3-correction-20260814-final-9a43713e
```

## Remaining limitations

- The Product Owner accepted the completed correction evidence and reapproved
  Stage 3 at the exact source snapshot recorded above. This approval does not
  authorize Stage 4.
- The user-local WSL PostgreSQL runtime is an acceptance environment, not a
  production permission/lifecycle model. Deployment still needs separately
  reviewed migrator, application, and privileged erasure roles.
- Process attestation proves the active serving system identity; it does not
  make the candidate model a production or personalized release.
- Historical benchmark quality limitations remain: structured JSON failed and
  concurrency-two output was not globally deterministic.
- The developer chat intentionally has no synthetic transcript injection or
  Stage 4 long-term user model.

## Worktree and stop boundary

The preserved developer-chat changes and acceptance corrections form the Stage
3 checkpoint payload authorized for commit. No push was performed. Migrations
`0001`-`0005` and old benchmark report directories are unchanged.

**Stage 3 is approved and complete. Stage 4 has not started and remains
unauthorized until a separate explicit Product Owner decision.**
