# Stage 1 Correction Checkpoint

Status: **Implemented, verified, and approved by the Product Owner on 2026-08-13**

Scope: **Stage 1 approval blockers only; Stage 2 remains inactive**

## Corrected findings

### Enforced inference timeout

`InferenceRequest.constraints.timeout_ms` is now executed by the Companion orchestration layer with `asyncio.wait_for`. The default is 20,000 ms and is configurable through `HAVRE_INFERENCE_TIMEOUT_MS`.

The integration test uses a provider that waits forever and a 25 ms limit. The provider task is cancelled, the call returns in under one second, `interaction_requests.status` becomes `failed`, `error_code` is `InferenceTimeoutError`, the raw `USER_MESSAGE` remains durable, and no delivered `ASSISTANT_MESSAGE` is created.

This contract change increments the HAVRE service version to `0.1.1`. Root request spans record `interaction-orchestrator-v2` and the effective timeout; migration provenance records `0002_stage1_corrections.sql`.

### Content-bound idempotency

Each new request stores a `sha256:` fingerprint over:

- exact message content;
- privacy class;
- memory eligibility;
- optional client-selected session ID;
- channel;
- language.

`traceparent` is intentionally excluded because a network retry may arrive through a new parent span without changing request meaning. A matching owner/key/fingerprint replays the original result. The same key with different content or privacy returns `IdempotencyConflict` and creates no additional request or event. Legacy rows receive a `legacy:<request_id>` marker during migration and fail closed on replay because their original canonical ingress cannot be reconstructed safely.

The CLI no longer uses a fixed default key. It generates `stage1-demo-<uuid7>` unless the owner explicitly supplies `--idempotency-key`.

### Owner-scoped identity versions and evidence

Migration `0002_stage1_corrections.sql` changes the identity artifact primary key from globally unique `artifact_version_id` to `(owner_id, artifact_version_id)`. Existing owner approvals are used to copy the exact matching approved content/hash for legacy owners before new owner-qualified Context Pack constraints activate.

All Stage 1 personal-artifact relationships now use owner-qualified foreign keys. Evidence queries require an owner ID. Tests prove that:

- two owners can independently use `constitution-v1`, `identity-v1`, and `values-v1`;
- the same owner can bootstrap repeatedly;
- one owner cannot retrieve another owner's evidence;
- a cross-owner session link is rejected by PostgreSQL;
- every foreign-key column has an index.

## Previously missing ROADMAP coverage

| ROADMAP requirement | Verification |
|---|---|
| Append-only database | Direct event update rejected by immutable trigger |
| Owner isolation | Owner-qualified PK/FKs, evidence filter, two-owner and cross-owner-link tests |
| Provider swap | Alternate provider/model versions work through the unchanged `InteractionService` |
| Governance activation | Non-owner identity package rejected; provider response activation field rejected; provider swap leaves identity rows unchanged |
| Deterministic behavior | Versioned local provider contract tests |
| Timeout and typed failure | Hanging provider cancelled; request marked failed; no assistant delivery |
| Idempotency | Exact replay succeeds; different message/privacy conflicts |
| Telemetry privacy | Span test confirms protected message text is absent |
| `LOCAL_ONLY` and training defaults | Contract/router tests remain enforced |

## Existing and fresh database evidence

The historical `havre_stage1_test` database originally reproduced the reported failure. The first owner-qualified FK attempt was rejected because a historical Context Pack owner had no matching owner-scoped identity row; the migration transaction rolled back atomically. After adding the approval/hash-based legacy repair, the same database migrated in place:

```text
0001_stage1_foundation.sql
0002_stage1_corrections.sql
```

The full suite then passed twice consecutively on that same migrated database:

```text
Ran 28 tests — OK
Ran 28 tests — OK
```

A new `havre_stage1_correction_fresh` database applied both migrations from scratch and passed the same 28 tests. A foreign-key index audit returned zero missing indexed FK columns.

The temporary fresh verification database was removed after the run. The reusable historical test database was retained in its corrected migrated state, and PostgreSQL was stopped after final verification.

## Corrected end-to-end run

```text
request_id:          019ff73f-5845-7c58-a91b-21e3c512f515
trace_id:            8af4760b5366f7328825fb035979c680
user_event_id:       019ff73f-5845-7c5b-8b1c-5e12c009c868
assistant_event_id:  019ff73f-5855-7b1b-b2c3-316b5bb7c65e
request_fingerprint: sha256:9b32eda0f5b53fd0b54e1af9865c5f98d210305334aa8e2d97e2a13ddd731626
status:              completed
service_version:     0.1.1
orchestrator_version: interaction-orchestrator-v2
inference_timeout_ms: 20000
provider_id:         deterministic-local
model_version_id:    deterministic-companion-v1
prompt_tokens:       673 estimated
output_tokens:       36 estimated
total_tokens:        709 estimated
inference_total_ms:  0.007
stored_spans:        6
```

This remains an infrastructure acceptance response from a fixed deterministic local provider. It does not claim that HAVRE already has production conversational capability.

## Documentation scope alignment

The Stage 1 section of `MASTER_PLAN.md` now matches the later-approved `ROADMAP.md`: no Basic User Model and no Minimal Web Chat. ADR-0008 retains the permanent durable-worker decision but records that no worker/job table activates until a later approved capability actually needs background work.

## Approval outcome

The Product Owner approved Stage 1 after this correction checkpoint. This historical checkpoint remains unchanged by the later accepted Proactive Interaction amendment and completed Stage 2 work; current state lives in [`STATE.md`](STATE.md).
