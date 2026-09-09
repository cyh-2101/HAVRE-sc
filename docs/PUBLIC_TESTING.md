# Public verification

## September 8, 2026 result

**841 tests passed**, zero failures/errors/skips in the selected public matrix.
**98 tests are explicitly excluded**: 97 require unavailable private/local
artifacts or the separate training environment; one contains an exact reproduced
assistant transcript and its source is intentionally omitted. Exclusions are not
passes. No private transcript test was replaced with invented data.

[Exact excluded test IDs](PUBLIC_TEST_EXCLUSIONS.json) are generated from the same
runner used for this result. Private tests and the separate pinned Torch
environment are different evidence; their counts are not added here.

The first export verification attempted 842 tests and reported one role-permission
failure and six missing-source-snapshot errors. The final run used an independent
Git snapshot of the staged public bytes and a newly created empty database. The
runner now initializes canonical migrations and role grants before discovery,
removing a dependency on test order. The private-transcript test was omitted for
privacy; it was not one of the failing tests. No product assertion or database
guard was weakened. The matrix completed in 143.014 seconds; this is not an
application-latency or capacity measurement.

## Reproduce

Start from a Git clone, not a source ZIP: provenance tests require Git metadata.
Install Python 3.12 and the pinned packages into a virtual environment:

~~~powershell
git clone https://github.com/cyh-2101/HAVRE-sc.git
Set-Location HAVRE-sc
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock -r requirements-memory.lock
.\.venv\Scripts\python.exe -m scripts.fetch_memory_encoder
createdb -h 127.0.0.1 -p 55432 -U postgres havre_showcase_tests
.\.venv\Scripts\python.exe -m scripts.run_public_verification --database-url postgresql://postgres@127.0.0.1:55432/havre_showcase_tests --verbose
~~~

Use PostgreSQL 18 with pgvector and a dedicated disposable loopback database.
Run with its setup administrator: the canonical role bootstrap creates missing
NOLOGIN roles and applies the existing least-privilege grants. The runner rejects
other database names and treats skipped selected tests as a failure. Never point
it at an owner database. Migrations 0001 through 0075 were applied in order to the
fresh database; the matrix also exercises migration boundaries and SQL guards.

The local ONNX encoder is a hash-pinned public prerequisite downloaded into
ignored storage. This refresh reused verified encoder bytes and the existing
pinned Python environment; it was not a clean OS/package installation. No owner
example bank or personal data is needed for the selected matrix.

## Other checks

- A second disposable database completed the synthetic interaction, memory,
  feedback, episode and provenance demo. The provenance CLI returned an empty
  violation list. The deterministic provider does not prove model quality.
- Real headless Edge with synthetic API responses: 21 interaction checks passed,
  including continuation recovery, visibility, privacy and paragraph pacing.
- Rendered bubble motion: seven checks passed; 117 frames sampled. This tests
  actual movement and stable nodes rather than only a CSS class name.
- Real Service Worker upgrade: ten checks passed, including request/draft
  preservation, offline reload and shell-only caches. The public run uses
  constructed version changes, not an omitted private legacy-client directory.
- Documentation/link, compilation, dependency and whitespace checks passed.
  These do not establish physical-iPhone acceptance.

The browser checks require Node.js, Playwright and installed Microsoft Edge:

~~~powershell
npm install --no-save --prefix var/browser-test-runtime playwright
$env:HAVRE_PLAYWRIGHT_MODULE = (Resolve-Path var/browser-test-runtime/node_modules/playwright).Path
node tests/pwa_natural_chat_browser.cjs
node tests/pwa_bubble_motion_browser.cjs
node tests/pwa_update_browser.cjs
~~~

Generated results and synthetic screenshots stay under ignored var/. No real
provider generation is needed. September 7 (825 selected, 97 excluded) and
August 26 (433 selected, 90 excluded) results are historical. Public verification,
private-source tests, candidate evaluation and repeated owner-use quality remain
distinct evidence boundaries.
