# Current implementation and evidence — 2026-09-08

This is a sanitized source snapshot of an owner-controlled research system.
The private archive remains authoritative for exact operating records and private
reviews. Published code does not grant permission to access personal data or to
activate a new model, sensor, training run, or delivery channel.

## System that exists

HAVRE keeps personal continuity outside any foundation model. A modular Python
Core owns identity, data policy, provenance, memory lifecycle, authorization and
response delivery. FastAPI and a database-backed worker compose the same domain
packages. PostgreSQL is the system of record; pgvector and local lexical/semantic
indexes support retrieval. The Web/PWA supplies chat, source previews, reviewed
understanding, diary and reminder controls. The separate Swift client is an
implementation checkpoint with native device acceptance still open.

The current data schema has 75 additive migrations. Historical migration bytes
are retained. Owner-qualified foreign keys, immutable revisions, hash-bound
requests and direct database guards preserve source relationships. A correction
qualifies earlier history; it does not silently overwrite the source event.

## A message through the system

1. Ingress authenticates the owner and handles request idempotency.
2. The source Event is preserved with its DataPolicy and trace identifiers.
3. The planner determines the current conversational intent and recall need.
4. History, relevant raw experience and reviewed understanding are selected with
   owner, route, time, correction and relevance checks.
5. PersonalContextCompiler allocates the bounded prompt budget. Required source
   qualifications cannot be dropped just to make the prompt fit.
6. The final InferenceRequest carries the selected source references and versions.
7. The privacy router chooses an eligible provider. In the private operating
   deployment, eligible PUBLIC/NORMAL turns use GPT-5.6-sol; stricter turns use the
   exact unadapted Qwen3-8B local artifact. A public clone needs its own setup.
8. Core response policy governs the candidate response before durable delivery.
   Raw model output and visible output keep distinct hashes and linked records.

Source: [architecture](ARCHITECTURE.md), [conversation intelligence](CONVERSATION_INTELLIGENCE_ARCHITECTURE.md),
[database design](DATABASE_DESIGN.md), and [ADR-0039](adr/0039-personal-context-engine-and-evidence-compiler.md).

## September 8 update

The [interaction update](CHAT_INTERACTION_UPDATE_2026-09-08.md) adds bounded
requested record reads, multi-turn Goal sources, receipt-based action claims,
exact-parent continuation controls and PWA version/animation repair. The existing
context architecture and model configuration remain. All generated source is
part of an AI-assisted project; system evidence is not personal mastery evidence.

## Changes since the August showcase

- Lifetime raw-history lookup, exact excerpts, source-qualified ambiguity and
  current corrections are carried through to final provider messages.
- Memory and User Model understanding have source-bound revision/review paths;
  saved data does not become training data automatically.
- Daily review uses an explicit local-day boundary, with first-person diary and
  separate improvement suggestions. Coverage and repeated usefulness are not
  established merely because a record was saved.
- Reminders and relational follow-ups have separate controls. Delayed work
  revalidates exact source pairs and current state, supports cancellation, and
  retains immutable lineage through both continuation beats.
- Request recovery preserves original drafts/events and supports bounded manual
  retry. Streaming viewer disconnect does not grant a second request.
- The PWA supports brief default conversational turns and explicit continuation,
  draft protection, and source previews. Structured or requested detailed work
  stays complete. Browser checks are not physical-device evidence.

## Verified and unproven

Public clone verification is separately recorded in
[PUBLIC_TESTING.md](PUBLIC_TESTING.md). Private/local-artifact exclusions are not
passing public tests. The preceding private backend repair recorded 877 primary
and 62 separate-environment tests, zero failures/errors/skips; later static UI
changes have their own browser evidence. These are different source snapshots.

Historical regression evidence includes 13/13 constructed input-budget cases
retaining raw experience and 16 constructed targeted-recall source sets. These
measure source admission and prompt construction, not whether generated replies
feel natural. No new cloud generation is part of this publication.

A completed fixed-model Context A/B experiment was inconclusive: among 32 main
cases, Simple won 12, Full 8, with 1 tie and 11 unresolved comparisons. The Simple
share was 56.3%, with a family-clustered 95% interval of 42.9%–65.9%; display-order
agreement was 65.6%. These are model-judge results with private underlying cases,
not an open reproducibility claim or owner satisfaction score. No architecture
winner was adopted. Case text and raw outputs are deliberately absent here.

QLoRA work established local pipeline/candidate feasibility. Candidate adapters
remain unpromoted; current local operation uses the unadapted base artifact.
Docker deploy/rollback and restore experiments establish bounded infrastructure
properties. They do not establish production scale or conversational quality.
Physical-iPhone behavior, repeated owner usefulness and formal remaining stage
acceptance gates remain open.

## How to inspect the evidence

Read one synthetic flow end to end, then its contracts and failure tests. Useful
entry points are `companion/application/service.py`, `companion/context/response_plan.py`,
`companion/context/recall.py`, `companion/context/compiler.py`,
`companion/context/presentation.py`, `mlsys/serving/router.py`,
`companion/persistence/postgres.py`, `companion/product/relationship.py`, and
`tests/test_short_conversation.py`. Exact paths are discoverable in the source;
no private database, example bank, screenshot or runtime attestation is required
to read the architecture.
