# Project evidence and contribution boundaries

## AI-assisted authorship

Most code and automated tests in HAVRE were produced with AI coding agents.
The human contribution is product requirements, personal-use feedback, acceptance
decisions and learning the request/data flow. The repository does not establish
that its owner independently implemented, debugged or mastered each subsystem.

A suitable project title is **HAVRE — AI-Assisted Personal Companion Project**.
Two conservative resume bullets, subject to the applicant's own confirmation:

- Defined conversational continuity, memory-correction and daily-use interaction
  requirements for an AI-assisted personal companion project.
- Tested the application through personal use and supplied concrete feedback on
  incorrect recall, repeated continuations and message display to guide revisions.

After being able to explain the chain without assistance, one may add:

- Traced the user-message, stored-event, context-selection and model-response
  workflow, focusing on source provenance and the boundary between records and
  generated claims.

Do not claim to have independently designed or implemented the context compiler,
database constraints, retrieval algorithms or training pipeline simply because
those features are present here. Do not claim personal test authorship from test
counts. An architecture diagram or an AI-written explanation is not proof of
understanding.

## What the repository demonstrates

| Implemented behavior | Inspectable evidence | Limit |
| --- | --- | --- |
| A durable request/context/reply chain | [Interaction service](../companion/application/service.py), [Event model](EVENT_MODEL.md), [Context builder](../companion/context/builder.py) | System behavior, not individual authorship or answer correctness. |
| Source-qualified memory and corrections | [Memory design](DATABASE_DESIGN.md), [context compiler](../companion/context/compiler.py), [retrieval tests](../tests/test_relevant_memory_use.py) | Admission does not prove that a model will recall or use the fact naturally. |
| Privacy-based provider routing | [Router](../mlsys/serving/router.py), [architecture](ARCHITECTURE.md) | A public clone needs its own credentials and local provider setup. |
| Requested personal-record context and action receipts | [September 8 update](CHAT_INTERACTION_UPDATE_2026-09-08.md), [repair tests](../tests/test_chat_repair.py) | A textual promise is not evidence that an action was saved. |
| Audited continuation, recovery and animated PWA | [Button tests](../tests/test_continuation_button.py), [PWA tests](../tests/pwa_v5_contract.js), [motion test](../tests/pwa_bubble_motion_browser.cjs) | Synthetic browser behavior is not physical-phone acceptance or natural conversation quality. |
| Public synthetic verification | [Testing protocol](PUBLIC_TESTING.md), [demo](SHOWCASE_DEMO.md) | Report selected passes and explicit exclusions separately. |
| Historical candidate training and rejection | [Stage 9 checkpoint](STAGE9_CHECKPOINT.md), [model/Core distinction](STAGE9A_MODEL_VS_CORE_RESPONSIBILITY_CHECKPOINT.md) | Pipeline/candidate evidence; no behavioral adapter was promoted to the current product. |

## Claims to leave out

Avoid production-ready, expert-level ML systems, superior long-term memory,
independently trained/deployed a personalized model, or improved naturalness by a
percentage. Historical QLoRA runs and benchmark scores remain in their original
checkpoint documents, with candidate and synthetic limits; they are not default
resume bullets for someone still learning those mechanisms.

The public mirror excludes owner transcripts, OA case material, private review
outputs, secrets, device origins and runtime artifacts. See
[publication scope](../PUBLICATION.md) and [release audit](PUBLIC_RELEASE_AUDIT.md).
