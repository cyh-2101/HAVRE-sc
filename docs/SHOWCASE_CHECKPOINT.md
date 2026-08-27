# Clean Showcase Checkpoint

- Date: 2026-08-26
- Scope: documentation, public-safe synthetic demo, daily Web usability
  completion, evidence indexing, and public-release/privacy audit
- Stage effect: none
- Training/model execution: none
- Promotion/deployment effect: none
- Push/publication: none

## Product Owner boundary

Major HAVRE development is paused. This checkpoint does not authorize a new
Stage, v8, Stage 9B, iPhone/Screen Time, Stage 12, new training, private
feedback training, model status/registry/serving changes, promotion,
deployment, product expansion, or broader sensing/context activation.

## Changes

- Replaced the README landing page with a concise research-showcase overview,
  existing-system architecture diagram, five-minute demo, exact ML-systems
  highlights, verification boundary, and public-release status.
- Added RESUME_EVIDENCE.md with checkpoint-linked claims and prohibited
  overclaims for inference, retrieval, User Model, QLoRA/resources, evaluation,
  rejection, response delivery, feedback, deployment/rollback, and tests.
- Added SHOWCASE_DEMO.md with one-command, Web, screenshot, professor, and
  1–2-minute video paths using synthetic data only.
- Added PUBLIC_RELEASE_AUDIT.md with fail-closed publication findings.
- Added a deterministic synthetic flow and PowerShell runner using a random
  synthetic owner and dedicated loopback-only havre_showcase_ database.
- Completed the pending daily Web chat layout/usability changes: the composer
  remains in chat flow, mobile drawers and safe-area/viewport sizing are
  present, pending generation is visible, the textarea and Send control remain
  usable, and request errors retain server detail.
- Added focused boundary, end-to-end synthetic flow, Web asset, documentation
  link, and public-document privacy tests.

No contract schema or database migration changed.

## Current verification

### Synthetic flow

The final one-command run completed on the verified repository-local PostgreSQL
18 + pgvector cluster and then restored PostgreSQL to its prior stopped state.
It produced:

- two synthetic user interactions and four exact user/assistant message Events;
- one explicitly accepted, training-ineligible episodic Memory;
- gated retrieval using retrieval-r1-vector-gated-v2;
- a persisted ContextPack containing the reviewed Memory plus exact history;
- deterministic-local response lineage;
- MIXED / Too AI feedback plus an immutable owner edit;
- a four-member closed episode;
- zero provenance-audit violations.

The deterministic response did not naturally use the memory. That is
intentional evidence for the feedback/edit path, not a model-quality success.

### Web smoke

The synthetic -ServeWeb profile:

- bound only to 127.0.0.1:8765;
- returned HTTP 200 for /health/ready;
- returned HTTP 200 for /chat;
- stopped its listener and restored PostgreSQL to stopped after Ctrl+C.

The in-app browser runtime failed to start in this session, so no new
desktop/mobile geometry claim or screenshot asset is recorded. Static and API
integration tests passed, but a real 390×844 and desktop capture remains
required before adding public screenshots.

### Test matrix

- Primary .venv, dedicated disposable PostgreSQL database, all modules except
  the three torch-dependent Stage 9A/v6/v7 modules: **461 passed, 0 failed,
  0 skipped**.
- Existing pinned Stage 9A environment, contract-only execution for those three
  modules: **62 passed, 0 failed, 0 skipped**.
- Combined declared matrix: **523 passed, 0 failed, 0 skipped**.
- Both disposable test databases were removed. PostgreSQL was restored to its
  prior stopped state.

These tests did not run training, inference generation, Docker deployment,
native Swift/Xcode/device evidence, or capacity/load tests.

## Public-release decision

The private source branch was not safe for direct publication. This public
mirror resolves that boundary by using a new squashed history, Apache-2.0,
GitHub noreply author identity, owner-path placeholders, and a fresh full-tree
privacy scan. No private Git history was rewritten or copied.

Follow [PUBLIC_RELEASE_AUDIT.md](PUBLIC_RELEASE_AUDIT.md) before every future
push. The private archive remains the canonical evidence and governance source.

## Stop boundary

This checkpoint does not authorize training, a new Stage, candidate
promotion/deployment, iPhone/Stage 12 work, broader product capabilities, or
publication of any artifact outside the sanitized public mirror.
