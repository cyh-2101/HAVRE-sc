# HAVRE Repository Instructions

## Scope

This file applies to the entire repository. It is an execution guide for coding agents; it does not replace HAVRE's approved product, architecture, privacy, or governance documents. A future nested `AGENTS.md` may add stricter local instructions, but it must not weaken these repository-wide rules.

## Required orientation

Before planning or editing:

1. Read [`docs/STATE.md`](docs/STATE.md) for the implemented reality, current approval gate, known limits, and next allowed action.
2. Read the relevant stage in [`docs/ROADMAP.md`](docs/ROADMAP.md).
3. Read the relevant architecture, contract, evaluation, and ADR documents before changing their code boundaries.
4. Inspect the existing tests and migrations for the area being changed.
5. Check Git status and preserve all unrelated or pre-existing user changes.

Document responsibilities are intentionally separate:

- [`MASTER_PLAN.md`](MASTER_PLAN.md): mission, principles, and long-term direction.
- [`docs/STATE.md`](docs/STATE.md): current implemented facts and current authorization gate.
- [`docs/ROADMAP.md`](docs/ROADMAP.md): stage scope, dependencies, exit evidence, and approval gates.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), [`docs/DATABASE_DESIGN.md`](docs/DATABASE_DESIGN.md), [`docs/EVENT_MODEL.md`](docs/EVENT_MODEL.md), and [`docs/MLSYS_DESIGN.md`](docs/MLSYS_DESIGN.md): durable system and contract boundaries.
- [`docs/EVALUATION_PLAN.md`](docs/EVALUATION_PLAN.md) and [`docs/BENCHMARK_PLAN.md`](docs/BENCHMARK_PLAN.md): evidence and measurement protocols.
- [`docs/adr/`](docs/adr/): accepted architecture decisions and their consequences.
- `docs/STAGE*_CHECKPOINT.md`: historical evidence and handoff records, not authorization for later stages.

If these sources conflict, do not silently choose the convenient interpretation. Follow the latest explicit Product Owner decision for the authorized task, identify the conflict, and require an ADR plus Product Owner approval when the resolution would materially change accepted architecture or governance.

## Approval and governance boundaries

- Work only inside the currently authorized stage and task. Acceptance of a future design does not activate its runtime or authorize its implementation.
- Never begin the next stage without explicit Product Owner approval, even when the current stage is implemented and tests pass.
- Explicit Product Owner approval is required for material changes to the Constitution, Core Identity, Core Values, privacy rules, safety boundaries, intervention authority, training-data policy, or personalized production model releases.
- Only the owner may authorize declassification. Redaction or transformation never silently bypasses the source policy; every derived artifact requires its own policy classification and complete provenance.
- `training_eligible` remains false by default for user-derived information. `LOCAL_ONLY` data must never leave owner-controlled infrastructure. Fail closed when policy or authorization is unresolved.
- Do not activate deliberately unresolved outcome scales, Scene signals, belief-confidence algorithms, follow-up cadence, or quantitative intervention thresholds without stage-specific evidence and owner approval.

## Engineering rules

- Build permanent vertical slices along the accepted boundaries. Do not introduce disposable MVP paths, future-stage placeholders, or duplicate abstractions for speed.
- Keep foundation models and providers replaceable. Identity, values, governed history, policy, and relationship continuity belong to HAVRE rather than to a provider.
- Use typed contracts, explicit versions, durable storage, exact provenance, and tests for success and failure behavior from the first implementation.
- Enforce owner isolation and privacy at durable boundaries, not only in application filters. Every derived record must be traceable to owner-qualified source records.
- Preserve append-oriented event and revision history. Corrections, supersession, retraction, and authorized erasure must use their governed paths.
- Treat checked-in migrations as potentially applied. Never rewrite a migration recorded by a checkpoint; add a new numbered migration and test both fresh installation and in-place upgrade when relevant.
- Keep provider-, embedding-, retrieval-, prompt-, policy-, and schema-specific behavior behind their versioned interfaces. Unsupported capabilities must fail visibly rather than being silently ignored.
- Do not add production dependencies, external services, cloud data transfer, or broader privileges unless they are required by the authorized scope and their privacy, operational, and migration consequences are documented.
- Make focused changes and preserve unrelated work. Do not perform destructive Git or database operations against an unverified target.
- Report capability boundaries honestly. A deterministic provider, synthetic fixture, or small benchmark proves only what it directly measures; it does not establish production conversation or semantic quality.

## Verification

Run tests in proportion to the change. Stage completion and changes to persistence, privacy, provenance, owner isolation, retrieval admission, or governance require the complete PostgreSQL-backed suite with zero skipped database tests.

Typical Windows commands are:

```powershell
$env:HAVRE_TEST_DATABASE_URL = 'postgresql://postgres@127.0.0.1:55432/<dedicated_test_database>'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m compileall -q companion contracts identity mlsys scripts services tests
git diff --check
```

Additional requirements:

- Use a dedicated disposable test database, never a personal or development database. Verify the exact target before creating or removing it, and restore PostgreSQL to its prior running/stopped state afterward.
- Run `.\.venv\Scripts\python.exe -m scripts.export_contract_schemas` when active contracts change, and review the generated diff.
- Run `.\.venv\Scripts\python.exe -m services.api.cli audit-provenance` against the migrated test database after provenance or persistence changes; any returned violation is a failure.
- Run the relevant checked-in benchmark when retrieval, ranking, embeddings, inference, context budgeting, or benchmark fixtures change. Record the system-under-test versions and distinguish latency variance from deterministic quality results.
- Add regression tests for every reproduced defect. For database constraints, prove the exact forbidden relationship rather than relying on a different constraint to reject the fixture.
- Never describe a suite as fully passed when database tests were skipped. Report exact pass, failure, and skip counts, the migration path, and any checks that could not run.

## Documentation and handoff

- Update `docs/STATE.md` only when implemented reality, verified evidence, limits, or the current gate changes.
- Update `docs/ROADMAP.md` only for approved scope or durable stage evidence; do not use it as a session log.
- Add or amend an ADR when an accepted architecture decision changes. Do not mark a proposal accepted without Product Owner approval.
- Keep checkpoint documents evidence-based: exact versions, commands, results, measurable metrics, limitations, and the explicit stop boundary.
- Keep README instructions runnable and concise. Prefer links to authoritative documents over copying volatile state, commit IDs, test counts, or benchmark values into this file.
- At handoff, state what changed, what was verified, what remains limited, and what owner decision is next.
- Do not commit, push, open a pull request, or begin the next stage unless the Product Owner explicitly requests it as part of the task.
