# Public-safe Showcase Demo

This demo uses a fresh synthetic owner identity and a dedicated local database.
Do not substitute the normal owner database, a real chat export, OA material,
or a personal screenshot.

## Fast path

From the repository root:

~~~powershell
.\scripts\run_showcase_demo.ps1
~~~

Expected result:

1. The runner verifies that PostgreSQL is the repository-local HAVRE cluster,
   creates or reuses only havre_showcase_demo, and applies current migrations.
2. It submits a synthetic piano-practice interaction.
3. The memory worker creates a candidate; the synthetic owner explicitly
   accepts it.
4. A later question retrieves that reviewed memory into a persisted
   ContextPack and receives a deterministic-provider response.
5. The synthetic owner records MIXED / Too AI feedback and an edited answer.
6. The session closes with four exact message Event members.
7. The provenance audit returns zero violations.

The JSON evidence is var/showcase/latest.json. That directory is ignored by
Git. If PostgreSQL was stopped before the command, the runner stops it again
before returning.

The script deliberately rejects a remote database, a non-loopback host, a
different port, or a database name without the havre_showcase_ prefix.

## Web walkthrough

~~~powershell
.\scripts\run_showcase_demo.ps1 -ServeWeb
~~~

Open the printed loopback URL. It contains a random one-time bootstrap token in
the URL fragment. Keep the terminal and address bar out of all public captures.
Press Ctrl+C in the same terminal when finished.

Recommended walkthrough:

1. Show the conversation and point out that both user and assistant messages
   come from the durable Event history.
2. Click Edit answer on the latest assistant response. Show the notice that the
   original stays unchanged and saving does not make feedback training data.
3. Cancel the modal if you only need a screenshot; the synthetic flow has
   already saved a public-safe feedback/edit record.
4. Open Settings & review. Show Personalization feedback and the
   “training not eligible” label.
5. Open Memory review. Show the accepted synthetic piano-practice memory and
   exact Event-linked episode summary.

## Public-safe screenshots

Capture only this synthetic Web profile. A useful README/gallery set is:

- Desktop 1440×900: conversation plus assistant feedback controls.
- Desktop 1440×900: Settings & review with feedback and Memory sections.
- Mobile 390×844: composer, Send button, conversation drawer, and tools drawer
  inside the viewport.

Before capture:

- use a private/incognito browser profile if practical;
- hide the address bar, bookmarks, account avatar, terminal, and Windows user
  name;
- confirm every visible sentence is the synthetic piano-practice fixture;
- exclude localhost tokens, database URLs, file paths, process IDs, and logs;
- do not open var, model manifests with local paths, OA files, or owner history;
- crop browser chrome and inspect the final image at full resolution.

The current HTML has static/integration coverage for the normal-flow composer,
mobile drawers, visible pending state, and feedback controls. A real viewport
capture is still required before committing any screenshot asset because
static tests cannot prove geometry.

## 1–2 minute video order

Suggested timing:

- 0:00–0:15 — README: one sentence on the problem and the architecture diagram.
- 0:15–0:35 — Run the one-command synthetic demo; point to the seven flow
  stages and zero provenance violations, not the raw IDs.
- 0:35–0:55 — Web history: show the synthetic interaction and retrieved-memory
  answer.
- 0:55–1:15 — Edit answer / feedback modal: emphasize original preservation
  and training_eligible=false.
- 1:15–1:35 — Memory review: show accepted memory, episode summary, and exact
  Event links.
- 1:35–1:55 — Resume Evidence: self-hosted inference, retrieval benchmark, and
  QLoRA/rejection evidence.
- 1:55–2:00 — End with the boundary: research system, rejected candidates
  retained, no production-model claim.

## What to show a professor

Start with the architecture diagram and
[RESUME_EVIDENCE.md](RESUME_EVIDENCE.md), then run the synthetic flow. For a
systems-oriented discussion, open:

- [Stage 3 correction checkpoint](STAGE3_CORRECTION_CHECKPOINT.md) for
  self-hosted inference attestation and real local benchmark evidence;
- [Stage 2 checkpoint](STAGE2_CHECKPOINT.md) for retrieval gates and the small
  synthetic benchmark;
- [Stage 9 checkpoint](STAGE9_CHECKPOINT.md) plus
  [the model-vs-Core checkpoint](STAGE9A_MODEL_VS_CORE_RESPONSIBILITY_CHECKPOINT.md)
  for QLoRA, sealed evaluation, negative results, and rejection discipline;
- [ADR-0022](adr/0022-core-governed-response-delivery.md) for the boundary
  between learned behavior and deterministic system responsibility.

Do not lead with every Stage document. Use the checkpoint chain only when the
professor asks how claims were accepted, corrected, or rejected.
