# Public verification

## September 7, 2026 result

825 tests passed, zero failures/errors/skips in the selected public matrix.
97 archival tests are explicitly excluded because their exact local/private
evaluation artifacts or separate training environment are absent. Excluded tests
are not passed tests. The initial refreshed run selected 832 and reported seven
missing-artifact errors; those exact dependencies were then documented in the
exclusion registry. No product assertion was weakened to hide a defect.

[Exact excluded test IDs](PUBLIC_TEST_EXCLUSIONS.json) are generated from the same
runner used for this result. The main private source separately passed 860 primary
plus 62 pinned-Torch tests (922 total, zero skips). That is separate evidence.

## Reproduce

Install Python 3.12 and the pinned packages into a fresh virtual environment:

~~~powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock -r requirements-memory.lock
.\.venv\Scripts\python.exe -m scripts.fetch_memory_encoder
createdb -h 127.0.0.1 -p 55432 -U postgres havre_showcase_tests
.\.venv\Scripts\python.exe -m scripts.run_public_verification --database-url postgresql://postgres@127.0.0.1:55432/havre_showcase_tests --verbose
~~~

Use PostgreSQL 18 with pgvector and an isolated loopback database. The runner
rejects other database names and treats skipped selected tests as a failure.
The local ONNX encoder is a hash-pinned public prerequisite, downloaded into
ignored storage. No owner example bank or personal data is needed for this matrix.
The handoff run reused the same verified public encoder bytes locally.

The synthetic showcase ran in a second disposable database and completed the
declared interaction, memory, feedback, episode and provenance flow. Its
deterministic provider does not prove model quality. No real provider generation
or owner database request is necessary. Generated results stay under ignored var/.

The August 26 result (433 selected tests, 90 exclusions) is historical. The
September result supersedes it for this source tree. Public test exclusions,
private-source verification, candidate evaluation and physical-device acceptance
are distinct evidence boundaries.
