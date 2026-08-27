# Public Verification Boundary

The private HAVRE archive has a larger acceptance matrix than this sanitized
mirror can reproduce. The mirror deliberately excludes owner-alignment cases,
private unseen-evaluation material, local benchmark output under `var/`, model
weights, and the separate training runtime. Those absences are privacy and
evidence-integrity controls, not files to recreate with invented substitutes.

Run the public-compatible matrix against a dedicated disposable PostgreSQL
database:

```powershell
$env:HAVRE_TEST_DATABASE_URL = 'postgresql://postgres@127.0.0.1:55432/havre_showcase_public_tests'
.\.venv\Scripts\python.exe -m scripts.run_public_verification
.\.venv\Scripts\python.exe -m services.api.cli audit-provenance
```

The runner discovers the repository tests, reports the selected and excluded
counts, and excludes only the following private-artifact-bound surface:

| Test surface | Why it is not reproducible from the public mirror |
| --- | --- |
| `tests.test_stage8_contracts` | Reads ignored local Stage 2 benchmark output. |
| `tests.test_stage8_integration` | Reads the same ignored benchmark output. |
| One owner-alignment test in `tests.test_stage9a_dataset_v4` | Reads the physically separate private OA set. |
| `tests.test_stage9a_dataset_v7` | Reads excluded owner-local v6 dataset evidence. |
| `tests.test_stage9a_unseen_v7` | Reads excluded private unseen-evaluation evidence. |
| `tests.test_stage9a_real_contracts`, `tests.test_stage9a_real_v6`, and `tests.test_stage9a_real_v7` | Require the separate training environment and excluded local artifacts. |

Running raw `unittest discover` from this mirror will therefore reach expected
missing-file failures in those archival tests. Do not describe those tests as
passing, and do not treat their absence as evidence that the underlying private
evaluation was reproduced publicly. Exact historical acceptance results remain
bound to the checkpoint documents and private canonical artifacts.

The synthetic showcase is independently reproducible and uses no owner data:

```powershell
createdb -h 127.0.0.1 -p 55432 -U postgres havre_showcase_demo
.\scripts\run_showcase_demo.ps1 -ExternalDatabaseUrl 'postgresql://postgres@127.0.0.1:55432/havre_showcase_demo'
```

Its success proves the declared synthetic interaction, memory, retrieval,
feedback/edit, and provenance flow. It does not replace the excluded evaluation
evidence or establish production model quality.
