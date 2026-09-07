# Daily Companion Memory, Diary, and Manual Strong Repair Checkpoint

- Date: 2026-08-28
- Scope: focused owner-authorized Daily Companion repair and manual Strong Brain activation
- Default daily model: Seed 9201, unchanged
- Cloud behavior: explicit per-reply action only; no automatic routing

## Reproduced causes

1. Recent conversation admission was owner-and-session scoped even though the
   product promises one continuous owner/HAVRE timeline. A device/session
   rotation could therefore hide the owner's immediately preceding correction.
2. Thumbs and reason text were durable, but reason text was not presented to a
   later model request. An explicit phrase correction remained only an ordinary
   chat turn, which Seed 9201 could see yet ignore.
3. Diary v1 was extractive: it used the first user utterance for the title and
   joined early turns with fixed transition words. Greetings and acknowledgments
   therefore became diary content. A cached-summary response omitted sources,
   while the client assumed the field existed, producing undefined.
4. Memory cards exposed a fixed direct-extraction confidence as if it were a
   psychological certainty. Advanced details exposed implementation identifiers
   without explaining provenance or the distinction between Memory, beliefs,
   goals, current state, and proposals.
5. The current product does not automatically infer or update durable User Model
   beliefs, accepted patterns, or Current State after every message. Those paths
   remain governed proposal/review/revision services.

## Implemented correction

- Recent raw conversation is selected owner-wide across engineering sessions,
  with the same owner/privacy/Event provenance checks and bounded budget.
- Exact owner phrase corrections and recent negative/mixed feedback reason text
  become source-bound, high-priority response constraints in Context presentation
  v3. They are not Memory, personality beliefs, or training labels, and the model
  is told to apply them silently rather than announce a callback.
- Diary v2 filters greetings, acknowledgments, transient unsupported emotion,
  and control actions; it selects concrete owner events/actions and falls back
  to a truthful generic entry when none exists. Cached and regenerated details
  return the same full source list.
- Memory UI groups governed record types, explains what confidence means, shows
  human-readable provenance, keeps developer identifiers under technical detail,
  and uses existing accept/reject/revise/delete services rather than direct row
  mutation. It now states the real automatic-understanding boundary.
- ADR-0025 and migration 0051_manual_strong_brain_disclosure.sql add a narrow
  per-action Strong Brain disclosure lifecycle. The source Context is selected,
  hashed, durably permitted, request-bound, sent only after exact validation,
  and completed against the durable resulting assistant Event.

## Evidence and limits

The first primary run passed 556/557 and exposed one test-ceiling mismatch for
the exact LOCAL_ONLY phrase correction 别再说‘替我过掉’啦; that run is not
counted as passing evidence. After the general Chinese quote parser and test
privacy ceiling were corrected, a rebuilt fresh database passed the complete
primary selection: 557/557, zero failed, zero skipped. The three complete
Torch-dependent modules then passed 62/62 in the pinned Stage 9A environment.
The final combined suite is 619/619 with zero skipped.

Migration reapplication returned applied: [], the complete provenance audit
returned [], and a direct catalog query found zero missing left-prefix indexes
for the new disclosure foreign keys. JavaScript syntax, Python compileall,
both environment pip checks, generated-contract equality, PowerShell parsing,
and git diff --check passed.

The owner-local runtime was validated without sending a real Strong request:
health was ready, Seed 9201 remained the active default, and Strong reported
manual_governed plus available. All three existing Diary days were re-derived
as evidence-event-diary-v2; every detail returned a non-empty source transcript,
with zero greeting titles and zero old transition summaries. Both active
Memories and all four pending candidates returned readable source previews.
The API truthfully reported automatic short-term chat context enabled and
automatic durable User Model beliefs disabled.

## Windows Application Control recovery

The prior MSYS2 postgres.exe is unsigned and Windows Application Control now
blocks it. The stopped 373 MB cluster was copied without modifying the source
to /home/OWNER/.local/share/havre/postgres18-owner-20260828. PostgreSQL
pg_controldata reported version 18 and clean shut down before first start.
The WSL runtime is PostgreSQL 18.4 with pgvector 0.8.1; before migration it
preserved 75 Events, two Memory revisions, and migration head 0050. Migration
0051 then applied exactly once.

The candidate start/stop launchers now prefer a validly signed Windows binary
when available and otherwise fail closed to the exact Ubuntu distribution,
binary bundle, data directory, socket, and dynamic-library path above. A real
all-stopped cold start recorded postgres_backend=wsl and
postgres_started_by_this_run=true; the matching owned stop closed it; a second
cold start restored PostgreSQL, 9201, API, worker, Tailscale Serve attestation,
and the Daily Companion. The original C:/HAVRE/var/postgres directory
remains an untouched pre-0051 recovery snapshot, not a second writable truth.

No real owner conversation was sent to DeepSeek during verification. Only the
owner pressing 用 Strong Brain 重新想想 may initiate the first real disclosure.

This repair does not add automatic User Model inference, automatic Memory
mutation, training, promotion, deployment, Stage 9B, provider-side deletion, or
always-on behavior while the owner PC/backend is unavailable.

## Post-activation screenshot correction

Owner screenshots then reproduced two remaining product defects. First, the
model-facing correction instruction quoted the rejected phrase while recent
conversation repeated both the rejected assistant reply and the correction.
The durable Event history was correct, but this presentation encouraged Seed
9201 to echo the phrase. Context presentation v4 now keeps the original Events
and exact source refs while replacing only those provider-facing turn texts
with neutral rejection/repair representations; the instruction itself no
longer contains the rejected wording. A local-only synthetic 9201 probe then
returned `Okay. Let me start fresh.` without reconstructing the phrase.

Second, the failed manual Strong receipt was durably `prepared -> bound ->
failed` with `provider_protocol_error` and no assistant Event. Manual Strong
had reused Local's 256-token output reserve even though the accepted
thinking/high evidence used 4096 because reasoning and final content share the
budget. The dedicated Strong ContextBuilder now preserves the same input
allowance while reserving 4096 output tokens. Empty final content is classified
as a safe typed `content_blocked` result with content-free diagnostic detail
instead of a generic invalid-response message.

On a newly recreated disposable PostgreSQL database, the complete primary
suite passed 558/558 and the pinned Torch suite passed 62/62: 620/620 total,
zero skipped. Provenance audit returned `[]`; compileall, both pip checks, and
git diff --check passed. An earlier 557/558 run reused a database containing
focused-test history and failed one fixed-owner Stage 1 source-ref assertion;
it is contamination evidence, not a product failure and not counted as pass.
No real owner DeepSeek request was replayed automatically.

The post-commit desktop restart also exposed a pre-existing immutable-migration
byte drift. Owner activation had applied migration 0051 with one intentional
mixed-EOL authorization line and one blank EOF line, then a whitespace cleanup
removed the EOF line before the earlier commit. The checksum gate correctly
refused startup. The exact applied bytes were recovered from the local rollout
record and restored at SHA-256
`4670029dda2b01cafb4c34105f4af3706c53ea7a249660aa286b12df9e3104f0`.
A per-file Git binary/whitespace attribute preserves those historical bytes.
The database migration row was not changed, the checksum runner was not
weakened, and owner reapplication returned `applied: []`.
