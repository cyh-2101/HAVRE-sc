# Stage 4 Implementation Checkpoint (Historical, Not Accepted)

Status: **Historical: Product Owner acceptance rejected; superseded by later correction checkpoints. Stage 5 was unauthorized at this checkpoint and was authorized later on 2026-08-14.**

Date: **2026-08-14**

Stage 4 implementation was explicitly authorized by the Product Owner on
2026-08-14. The Product Owner subsequently rejected acceptance of this
checkpoint and requested the bounded corrections recorded in
[`STAGE4_CORRECTION_CHECKPOINT.md`](STAGE4_CORRECTION_CHECKPOINT.md). That first
correction was also rejected and is superseded by
[`STAGE4_REACCEPTANCE_CORRECTION_CHECKPOINT.md`](STAGE4_REACCEPTANCE_CORRECTION_CHECKPOINT.md).
This file preserves the original `sha256:6890af...` implementation evidence;
it does not self-approve the stage, authorize Stage 5, or activate proactive
interaction.

## Delivered scope

- Immutable, owner-qualified `BeliefRevision` records with the deliberately
  narrow `owner-reviewed-v1` confidence method, explicit support and
  counter-evidence, stable belief identity, guarded head projection, and
  append-only lifecycle transitions.
- Bitemporal replay separating source occurrence, HAVRE learning, revision
  creation, real-world validity, and transition occurrence/recording time.
- Semantic, pattern, and progress memory classes behind the existing versioned
  retrieval and Context Pack boundaries.
- Proposal-only pattern consolidation. A pattern/progress proposal requires at
  least two distinct supporting sources on two distinct UTC dates, remains at
  fixed unreviewed confidence `0.5`, and cannot become durable memory without
  one explicit owner accept/correct/reject transition.
- Expiring, immutable Current State snapshots using
  `owner-reported-state-v1`; these remain distinct from durable beliefs.
- Reality and inner-life goal tracks, event-backed goal projection revisions,
  and evidence-linked immutable progress records.
- Context Builder v6 admission for qualified beliefs, active goals, and the
  latest non-expired Current State, with independent owner, privacy, policy,
  source-reference, and token-budget checks.
- Typed FastAPI endpoints, CLI evaluation support, generated JSON Schemas, and
  service version `0.4.0` / API stage `4`.
- Additive migration `0007_stage4_user_model_goals.sql`; no historical
  migration was rewritten.
- Privileged erasure closure across Stage 4 belief identities and transitions,
  consolidation proposals and accepted memory, Current State, goal progress,
  goals created from the erased source, provenance, later retrieval/context,
  inference/route records, and affected assistant events. The independently
  governed raw source event remains.

## Database and upgrade evidence

The acceptance run used the existing owner-controlled PostgreSQL 18.4 cluster
at `/home/OWNER/.local/share/havre/postgres18-stage3`, listening only on
`127.0.0.1:55432`, with pgvector 0.8.1. It was stopped before this task and is
restored to stopped state at handoff.

Two explicitly disposable databases were used:

- `havre_s4_fresh_20260814`: fresh `0001` through `0007` installation;
- `havre_s4_upgrade_20260814`: populated Stage 3 installation followed by only
  `0007`.

For the upgrade path, archived Stage 3 application code from commit
`7ec86ab36082a45270b015ed5a65d794cd63e90d` wrote request
`019ffcfd-993b-7414-8a9c-986db5251493` with idempotency key
`stage4-upgrade-fixture-v1`. The migration runner then reported exactly:

```text
0007_stage4_user_model_goals.sql
```

Current Stage 4 code reconstructed the unchanged request as `completed`, with
two message events and its historical `context-builder-v5` Context Pack. An
initial archive-based setup was rejected before mutation because Git archive
line-ending normalization changed migration bytes. The disposable database was
rebuilt with the exact checked-out `0001`-`0006` bytes; the checksum guard was
not disabled or bypassed.

## Verification

Environment:

- Windows 11 `10.0.26200`;
- CPython `3.12.13`;
- pip `25.0.1`;
- PostgreSQL `18.4` and pgvector `0.8.1` in Ubuntu WSL;
- exact Stage 4 code/test source snapshot
  `sha256:6890af308888f42261ae2ebf88062865d27b61d33df7dce44c1a6a77b4be7297`.

The complete database-backed suite was run separately against the fresh and
in-place-upgraded databases:

```powershell
$env:HAVRE_TEST_DATABASE_URL = 'postgresql://postgres@127.0.0.1:55432/havre_s4_fresh_20260814'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

$env:HAVRE_TEST_DATABASE_URL = 'postgresql://postgres@127.0.0.1:55432/havre_s4_upgrade_20260814'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Final result on each path: **165 passed, 0 failed, 0 skipped**.

Additional checks:

```powershell
.\.venv\Scripts\python.exe -m scripts.export_contract_schemas
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m compileall -q companion contracts identity mlsys scripts services evals tests
git diff --check
.\.venv\Scripts\python.exe -m services.api.cli audit-provenance
```

- schema export matched the committed typed contracts;
- `pip check`: `No broken requirements found.`;
- compileall: passed;
- `git diff --check`: passed (Git emitted only expected Windows line-ending
  notices);
- provenance audit: `[]` on both fresh and upgrade paths.

The suite specifically proves bitemporal known-as-of/valid-at replay,
counter-evidence retention, qualified revision without deleted history,
proposal correction and reviewed-record immutability, expiring state, goal
revision/progress provenance, context inclusion and privacy rejection,
owner isolation at service and database source/destination boundaries, and
complete Stage 4 erasure propagation.

## Frozen synthetic evaluation

The content-hash-verified report is
[`../evals/reports/stage4_20260814/user-model-evaluation.json`](../evals/reports/stage4_20260814/user-model-evaluation.json).

| Field | Value |
|---|---:|
| Suite | `user-model-evidence-sequences-v1` |
| Evaluation run | `019ffd01-ac1d-700a-a866-9316a3d9835a` |
| Fixture hash | `sha256:247e636364351907e6c8dae3e2608d83590d16d97a585b2cc7f6cc4fc7d70a49` |
| Report hash | `sha256:a4cf35671ba785ba0e261a81ed600af16a32a22ef5c6f5d5f3949c6556415952` |
| Cases | `8` |
| Passed / failed | `8 / 0` |
| Unsupported stable beliefs | `0` |
| False-stability cases | `0` |
| Counter-evidence retention | `1.0` |
| Confidence/calibration cases | `0`; `not_evaluated_owner_reviewed_only` |
| Component latency mean / p50 / p95 | `0.0069 / 0.0041 / 0.0268 ms` |

The report is explicitly `binding_evaluation = false` and
`gate_status = not_evaluated`. It measures small in-process synthetic pattern
and replay logic only.

## Honest limits

- HAVRE does not infer or update durable numeric belief confidence
  automatically. The unresolved confidence algorithm remains inactive; the
  owner supplies and reviews confidence on every durable revision.
- The pattern detector creates inspectable proposals only. Two observations on
  different days are a conservative admission rule, not proof of a stable human
  trait or a production-quality pattern model.
- Personal-context selection is a small deterministic lexical baseline, not a
  broad semantic User Model or learned understanding system.
- The eight synthetic cases and five Stage 4 integration scenarios prove
  contracts and selected failure modes, not real-world understanding,
  calibration, longitudinal benefit, or production conversation quality.
- Goal progress records are evidence-linked observations, not an automatically
  computed percentage or claim of real-world improvement.
- The Stage 3 self-hosted model remains a candidate baseline. No personalized
  model release, Scene system, Intervention Policy, Reflection pipeline,
  training pipeline, proactive scheduler, renderer, or delivery runtime is
  active.
- Authentication, production role separation, complete export, raw-source
  deletion authorization, backup/restore erasure replay, external processors,
  and content-free erasure receipts remain future governed work.

## Stop boundary

This historical evidence did not pass Product Owner acceptance. Its review gate
is superseded by later correction checkpoints; the accepted Stage 4 evidence is
in [`STAGE4_REQUIRED_PROVENANCE_CORRECTION_CHECKPOINT.md`](STAGE4_REQUIRED_PROVENANCE_CORRECTION_CHECKPOINT.md).
At this checkpoint, Stage 5 and proactive runtime work required a new explicit
Product Owner decision. Stage 5 was later authorized on 2026-08-14 within its
recorded scope; proactive runtime remains unauthorized.
