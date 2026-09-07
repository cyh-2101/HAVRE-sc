# Stage 15 Commitment Loop Checkpoint

Date: 2026-09-03

Status: **Implemented and owner-locally active by explicit Product Owner task
direction. Formal ADR-0032 acceptance and repeated-use practical utility remain
open.**

## Authorized scope

The Product Owner authorized the Stage 15 production source-erasure closure for
future cases only when a source Event is explicitly named, and separately
authorized starting the owner-local API/worker and applying the reviewed Fall
2026 Goal transitions, five-field projections, and reminder queue update. The
owner acknowledged that starting the worker could immediately deliver due Web
inbox reminders.

No source Event was named for deletion during this activation. No production
source Event, Goal, projection, reminder, fusion record, or queue item was
erased through the destructive erasure path.

## Implemented boundary

- Migration `0054_stage15_commitment_broker.sql` adds exact field
  authorizations, five-field commitment projections, completion transition
  evidence, conversation-fusion claims, delivery records, and an integrity
  view. Migration `0055_stage15_commitment_fk_indexes.sql` adds reverse-closure
  indexes without rewriting an applied migration.
- Ordinary conversation may receive only course name, task name, deadline,
  completion state, and reminder history under the exact source-hash-bound
  owner authorization. The `LOCAL_ONLY` document and private Goal fields remain
  excluded; the projection is memory/training ineligible.
- A uniquely resolved explicit completion report transitions the exact Goal and
  records immutable source/lifecycle evidence. Ambiguity asks for clarification
  and does not mutate a Goal.
- A due reminder may be fused into a suitable active conversation only with
  durable claim and exact inclusion proof. Otherwise the existing Web-inbox
  path remains authoritative.
- Queue generation v2 is inserted before legacy pending/retryable work for the
  exact authorized source hash is cancelled. Leased work blocks replacement;
  succeeded work is preserved.
- Future privileged source erasure now traverses source-created Goals and Goals
  reached through completion evidence, then their projections, transition
  evidence, reminder deliveries, fusion claims, affected leases, and proactive
  queue artifacts. Raw source Event deletion remains separately governed.

## Production activation and readback

- Runtime: owner-local API PID `33548`, worker PID `44828`, database
  `havre_local_20260822`, migration head
  `0055_stage15_commitment_fk_indexes.sql`.
- Providers: GPT-5.6-sol through authenticated Codex CLI
  `0.153.0-alpha.5` and exact unadapted local Qwen3-8B were both healthy.
- Source snapshot SHA-256:
  `517c994a9e983a8a383ba2fe6cb32f75218236a22bf6fb6d3181dafffeb0e069`.
- Import: 50 existing Goals reused, zero created, zero new source interactions;
  48 current Goals remain active and the two 4-credit-only Goals are abandoned.
- Projection: 48 active plus two abandoned current projections under one exact
  field authorization.
- Queue: 127 v2 reminders pending; four past catch-ups were not replayed. One
  legacy item was cancelled by exact-slot replacement and the remaining 129 by
  source-scoped generation replacement. Four historical legacy items remain
  succeeded. A subsequent identical import replayed the 127 v2 keys and
  cancelled zero additional items.
- `stage15_commitment_integrity_violations` returned zero rows.
- Production `audit-provenance` returned `[]`; `/health/ready` returned `ready`
  with zero failed memory, proactive, or offline jobs.

## Fail-closed incidents during activation

The first apply attempt returned HTTP 409 because a prior source-ingest key was
reused with a changed request fingerprint. Existing complete Goal batches now
skip redundant source interactions; only a missing batch uses the stable v4
namespace.

The second apply attempt returned HTTP 409 because a legacy reminder key was
reused with changed governed input. The repair did not overwrite the row. It
introduced v2 reminder IDs, atomic exact-slot replacement, and the final
source-hash-authorized legacy-generation cancellation. Readback found no legacy
pending work afterward.

## Verification

- Focused Codex provider tests: 11/11 passed.
- Focused desktop launcher contract tests: 2/2 passed.
- Focused importer and PostgreSQL Stage 15 tests: 16/16 passed with zero skips
  against a dedicated disposable database; the database was removed afterward.
- Final complete PostgreSQL-backed verification after the queue-replacement
  repair passed 722/722 with zero skips in 121.733 seconds against a dedicated
  disposable database; the database was removed afterward.

## Remaining limits and stop boundary

- Formal ADR-0032 acceptance is still pending; this checkpoint records explicit
  task authority and technical evidence only.
- Repeated owner use must still establish that the cadence, fusion behavior,
  and conversation are genuinely useful.
- No GPT-selected reminder cadence or wording, course-site/email scraping,
  general Calendar-to-outreach trigger, automatic non-explicit completion
  inference, training, model promotion, public exposure, or cloud Core was
  authorized.
- Any actual irreversible erasure still requires a new owner instruction naming
  the exact source Event.
