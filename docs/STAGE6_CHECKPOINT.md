# Stage 6 implementation checkpoint

Date: **2026-08-19**
Status: **Historical rejected acceptance candidate; superseded by `STAGE67_ACCEPTANCE_CORRECTION_CHECKPOINT.md`**
Execution-source snapshot: `sha256:0fa0a1b01e74aeac0a0eacf49bf5ce9849ded7ad6a04656fbe6650c2d4d40754`

## Authorized scope

The Product Owner authorized continuous Stage 6 then Stage 7 implementation and accepted ADR-0019 and ADR-0020. Stage 6 uses the conservative binding: global disabled by default, preview `none` by default, explicit owner preference required before `SEND_NOW`, and unresolved controls fail closed. Only a local Web/inbox simulation is in scope. Real contact, private-data export, external Context Sources, and governance-policy changes remain prohibited.

## Implemented slice

- Versioned Trigger, preference, Proposal, four-way Interruption Decision, proactive Context Pack, rendering, delivery-attempt, and lifecycle-view contracts.
- Core-owned rule policy for permission, quiet hours, expiration, subject stop, budgets, cooldown, duplicate suppression, and confirmation.
- Prefix-stable raw/summary/compressed Context strategies with cache instrumentation.
- Adaptive routing with hard privacy/capability exclusion, reasons, and fallback before ranking.
- Synthetic/manual `LifeContextObservation`, `SignalFreshness`, and `ContextSourceHealth`; every fixture is simulated and `external_source_activated=false`.
- Atomic PostgreSQL trigger → proposal → decision → rendering → local inbox attempt → visible assistant event path. No assistant event is recorded before the inbox effect is visible.
- Additive migrations `0015`–`0017`, immutable lifecycle tables, exact lineage, owner isolation, provenance audit, and foreign-key index audit.
- Local API routes for owner preference revision, a synthetic Reach Out run, and lifecycle inspection. There is no real-send route.

The durable boundary requires `simulation_only=true` and `external_delivery_authorized=false`. Direct SQL forgery of external delivery authority is rejected.

## Evaluation and exit evidence

The checked-in `proactive-policy-synthetic-v1` suite passed **8/8** cases. It exercised all four decisions, produced one explicitly enabled local `SEND_NOW`, and produced zero externally authorized deliveries.

The controlled synthetic comparison selected `local-fast` for routine work and `local-strong` for the stronger profile; the cloud candidate was excluded for privacy. Fixture values were 24 versus 85 ms, quality 0.91 versus 0.96, and cost units 1 versus 3. The adopted rule is routine-fast with strong local fallback. Raw versus compressed context was 160 versus 97 estimated tokens with an identical prefix hash; the adopted proactive fixture uses compressed top-3 context.

These are deterministic fixture measurements, not observed provider latency, production cost, calibrated interruption quality, or real-world benefit.

Before Stage 7 began, the complete PostgreSQL-backed Stage 6 source passed **208 tests, 0 failures, 0 skips** in **14.708 s** on a fresh `0001`–`0017` database. Provenance and Stage 6 foreign-key-index audits returned `[]`. Under the Product Owner's continuous authorization, this met the Stage 6 technical exit condition and allowed Stage 7 work to begin.

Final combined-source verification is recorded in the Stage 7 checkpoint and passed **218/218** on both fresh and populated-upgrade paths.

## Commands

```powershell
$env:HAVRE_TEST_DATABASE_URL = 'postgresql://postgres@127.0.0.1:55432/<dedicated_test_database>'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m services.api.cli audit-provenance
.\.venv\Scripts\python.exe -m scripts.audit_stage6_fk_indexes
.\.venv\Scripts\python.exe -m scripts.export_contract_schemas
```

## Limits and stop boundary

- No Windows, Calendar, iPhone, voice, location, wearable, email, push, or other external adapter exists.
- The local inbox effect is a testable simulation, not active outreach.
- Defaults do not infer permission from silence or past response.
- No production interruption thresholds or real-world usefulness claims are approved.
- Stage 6 is not self-accepted by the implementation agent.

The next governance action for this checkpoint is Product Owner acceptance or a bounded correction request.
