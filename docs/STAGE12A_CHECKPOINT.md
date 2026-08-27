# Stage 12A implementation checkpoint

Date: 2026-08-22

Status: implementation checkpoint only. Neither Windows coarse context nor
Calendar is activated or scheduled. Stage 12A exit has not passed.

## Product Owner scope

The Product Owner explicitly deferred Stage 11 macOS/Xcode/physical-iPhone
evidence without waiving it, authorized Stage 12A, and did not authorize Stage
12B. Stage 12A remains minimum-sufficient and one capability at a time. The
Product Owner later discontinued Microsoft Graph and selected one manual,
owner-initiated ICS import before each semester. The durable HAVRE projection
remains availability-only. The Product Owner also requested iPhone Screen Time
as the next separately gated capability after Calendar; it is not part of this
checkpoint and no Screen Time sensing is active.

Stage 12B, location, wearables, richer sensing, Stage 9B, new training,
Dataset changes, and adapter promotion/deployment remain out of scope.

## Implemented boundary

- Migration `0035_stage12a_ambient_context.sql` adds provider-neutral source,
  capability, state, consent, permit, observation, health, retention, restore
  quarantine, and whole-source erasure tombstone records.
- Windows retains only bounded coarse activity summaries. Its task remains
  disabled and no real owner-activity gate is claimed.
- Calendar capability `calendar.read_availability.v1` retains only bounded busy
  intervals (`start`, `end`, availability class, all-day flag). Subject, body,
  location, organizer, attendees, provider IDs, attachments, and extensions do
  not cross the adapter boundary.
- The first active Calendar provider is `manual-ics`, behind the same
  provider-neutral availability port. Microsoft Graph/OAuth modules and runtime
  commands are removed; HAVRE makes no Microsoft login or Calendar network call.
- The owner explicitly selects one `.ics` file and a bounded semester coverage
  window. A current Core collection permit is required before the file is
  opened. The parser accepts bounded UTF-8 RFC 5545 events plus daily/weekly
  recurrence and fails closed on unsupported recurrence or ambiguous time.
- Parsing is local and ephemeral. HAVRE does not copy, upload, mutate, or delete
  the owner source file. Provider UID, title, description, location, organizer,
  attendees, attachments, and extensions are discarded before draft signing.
- There is no scheduler or polling path. A later file requires another explicit
  owner import. The canonical observation remains current only through its
  declared coverage end and then follows retention/erasure policy.
- Owner-confirmed whole-source erasure deletes the source, device HMAC key,
  authority chain, consent, observations, health, retention records, events,
  and downstream copies. A content-free tombstone prevents identity reuse and
  the external erasure ledger replays the same closure after restore.
- Neither adapter authorizes interpretations, Memory mutation, proactive
  contact, notification, or delivery.

## Manual ICS evidence and remaining gate

Synthetic fixtures cover content stripping, transparent/cancelled events,
timezone normalization, folded input, bounded daily/weekly recurrence,
exclusions, duplicate removal, unsupported-rule rejection, file and occurrence
limits, current-permit-before-read, idempotent Core ingest, durable provenance,
revocation, retention, whole-source erasure, and restore replay.

No real owner ICS file has been read. Calendar remains disabled until the owner
supplies the semester file, reviews the coverage window, enrolls the exact
source, and runs one manual Core-permitted import. The abandoned Entra app and
pre-hardening local DPAPI token are not runtime inputs or evidence; deleting
those owner-local/external credentials is a separate owner-controlled action.

## Requested iPhone Screen Time capability

The Product Owner requested a future capability for HAVRE to read the owner's
own iPhone Screen Time. The minimum-sufficient proposed canonical value is one
owner-initiated daily total (`total_active_seconds`) for the iPhone only. App
names, bundle identifiers, websites, notification contents, unlock history,
and per-app timelines are outside this request and remain forbidden unless the
owner later approves a distinct higher-precision scope.

This request is recorded but not represented as a working source. Apple's
ordinary privacy-preserving `DeviceActivityReport` can display activity inside
an iOS report extension, but Apple documents that the report sandbox prevents
network access and moving sensitive content outside the extension. Apple's
direct activity-data export API requires the separate Family Controls App and
Website Usage entitlement and is currently limited for customer installations
to EU devices signed into an Apple Account with an EU country or region. The
ordinary Family Controls capability also requires device-owner authorization;
distribution requires Apple approval for the entitlement.

Therefore HAVRE has not added a fake Core ingestion path. Native feasibility,
the exact owner-visible consent UX, entitlement eligibility, and physical-device
behavior must be verified later on macOS/Xcode/iPhone. A manual numeric import
or screenshot/OCR fallback would be a different privacy/source capability and
is not silently authorized by this request.

## Verification

Dedicated disposable PostgreSQL database:

`postgresql://postgres@127.0.0.1:55432/havre_stage12a_ics_20260822`

Commands:

```powershell
$env:HAVRE_TEST_DATABASE_URL = 'postgresql://postgres@127.0.0.1:55432/havre_stage12a_ics_20260822'
.\.venv\Scripts\python.exe -m unittest tests.test_stage12a_windows tests.test_stage12a_calendar -q

$modules = Get-ChildItem -LiteralPath tests -Filter 'test_*.py' |
  Where-Object { $_.Name -ne 'test_stage9a_real_contracts.py' } |
  Sort-Object Name | ForEach-Object { 'tests.' + $_.BaseName }
.\.venv\Scripts\python.exe -m unittest $modules -q

.\var\stage9a\env-windows\Scripts\python.exe -m unittest tests.test_stage9a_real_contracts -q
.\.venv\Scripts\python.exe -m scripts.export_contract_schemas
.\.venv\Scripts\python.exe -m compileall -q companion contracts identity mlsys scripts services apps tests
.\.venv\Scripts\python.exe -m pip check
$env:HAVRE_DATABASE_URL = $env:HAVRE_TEST_DATABASE_URL
.\.venv\Scripts\python.exe -m services.api.cli audit-provenance
.\.venv\Scripts\python.exe -m scripts.audit_stage12_fk_indexes
git diff --check
```

Results at the checkpoint source snapshot
`sha256:7cdb4c14d61ed53c9712e9a3aaa21d7a5bbbaa0a0627ab6464e19f77505c1bc1`:

- Stage 12A Windows + Calendar: 51/51, zero failures/skips.
- Primary suite excluding isolated Stage 9A real-training contracts: 390/390,
  zero failures/skips.
- Isolated Stage 9A real-training contracts: 57/57, zero failures/skips.
- Total Python/PostgreSQL regression: 447/447, zero failures/skips.
- Exported schemas match, compile passed, both Python environments report no
  broken requirements, provenance audit returned `[]`, Stage 12 FK-index audit
  returned `[]`, and `git diff --check` passed with line-ending notices only.
- The prior Graph checkpoint review is superseded. Manual ICS requires a fresh
  independent read-only review before activation.

Synthetic Calendar benchmark:

- 10,000 projections over a three-event synthetic ICS file;
- one busy interval retained, free/cancelled rows discarded;
- unsupported recurrence rejected;
- zero forbidden-content crossings;
- median projection latency 0.026300 ms, max 0.254100 ms;
- report: `evals/reports/stage12a_20260822/calendar-availability.json`.

The benchmark is synthetic conformance and latency evidence only. It does not
establish compatibility with the owner's future ICS file, owner benefit,
calendar density, battery cost,
or permission to retain richer content.

## Stop boundary

Do not activate or schedule either source on this checkpoint. Do not begin
Stage 12B or collect location, wearable, richer sensor, or unrelated app data.
Do not start Stage 9B, training, Dataset changes, adapter promotion/deployment,
automatic Memory mutation, or real proactive delivery.
