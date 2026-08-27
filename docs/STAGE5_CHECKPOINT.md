# Stage 5 Implementation Checkpoint

Status: **Historical snapshot rejected at acceptance review; superseded by the Stage 5 acceptance correction checkpoint**

Execution-source snapshot: `sha256:08082555d2fbffcf094050a15d8d467b51351263931f8234336dac526bf82a13`

Date: **2026-08-14**

The evidence below remains the historical record for this exact snapshot.
Independent acceptance review later reproduced four blocking integrity gaps in
full Scene erasure, current-state record admission, Scene projection time/hash
binding, and intervention decision/guidance binding. The bounded correction and
renewed evidence are recorded in
[`STAGE5_ACCEPTANCE_CORRECTION_CHECKPOINT.md`](STAGE5_ACCEPTANCE_CORRECTION_CHECKPOINT.md).
This historical snapshot is not the current re-acceptance candidate.

## Authorization and stop boundary

The Product Owner explicitly authorized Stage 5 and limited the work to the
Roadmap's Intervention Policy, Scene Session, and Web simulation. This
checkpoint does not approve its own implementation. It does not authorize
Stage 6, proactive triggers/proposals, scheduling, rendering, delivery,
external channels, or active outreach. No commit or push was requested or
performed.

The next action is Product Owner acceptance review of this exact source
snapshot and evidence. Until then the Intervention Policy release remains
`candidate_owner_acceptance`.

## Implemented vertical slice

- `intervention-policy-sim-v1` accepts only explicit categorical simulation
  inputs. Its ordered branches prefer safety/help, clarification, or recovery
  before minimum action, preparation, or reflection. It does not use a hidden
  numeric intervention score or activate unresolved quantitative thresholds.
- Every immutable `InterventionDecision` records its Constitution, Core
  Identity, Core Values, policy and renderer versions, reason codes,
  constraints, exact input evidence, and conservative DataPolicy. Every row is
  database-constrained to `simulation_only = true` and
  `outreach_authorized = false`.
- `SceneSession` is a first-class owner-qualified aggregate with guarded
  Before/During/After/closed phase and planned/active/paused/terminal status.
  Optimistic revisions and exact lifecycle events reject stale or invalid
  transitions.
- Ordered immutable `scene_records` retain visible Intervention, owner-reported
  Action, owner-reported Outcome, and consented Reflection links. A During
  action requires the latest record to be a fresh During intervention.
- `guidance_outcome_observations` join the exact visible guidance and
  Intervention Decision to Action, Outcome, and Reflection. Missingness remains
  categorical (`unknown`, `uncertain`, or `not_asked`); the stored limitations
  state that one self-report is association, not causal proof.
- The local `/scene-simulator` page calls the real FastAPI Scene endpoints. It
  completes the same durable path tested through service persistence; it is
  not a static mock and contains no background poller or outbound adapter.
- Source-erasure propagation conservatively removes an affected Scene
  projection, records, decisions, observations, derived guidance, and
  provenance while retaining the separately governed raw source event.

## Migration and durable integrity

Additive migration `0013_stage5_intervention_scenes.sql` leaves the recorded
`0001`-`0012` bytes unchanged. It adds:

- the `scene_command` durable request kind and nullable Scene scope on events;
- `scene_sessions`, `scene_records`, `intervention_decisions`,
  `guidance_outcome_observations`, and `scene_evaluation_runs`;
- owner-qualified foreign keys, exact event/record chain guards, append-only
  mutation protection, required deferred provenance, and an audit view;
- Stage 5 provenance destination types and complete matching FK-side indexes;
- no proactive trigger, proposal, interruption-policy, scheduler, renderer,
  delivery, or external-channel table.

Scene commands use owner/idempotency advisory locking, semantic fingerprints,
durable request/trace/event records, and exact replay. Reusing a key with
different input fails. Privacy remains fail-closed: `LOCAL_ONLY` never becomes
cloud eligible and `training_eligible` remains false.

## Verification evidence

Environment: Windows 11, CPython 3.12.13, FastAPI 0.141.1, Pydantic
2.13.4, Psycopg 3.3.4, PostgreSQL 18.4, and pgvector 0.8.6. Verification used
the exact repository-owned cluster at `D:/projects/HAVRE/var/postgres`, bound
to `127.0.0.1:55432`. It was stopped before this task and was restored to
stopped state after verification.

### Fresh installation

- Dedicated database: `havre_s5_fresh_20260814_codex`.
- Migration result: exact `0001` through `0013`, in order.
- Complete PostgreSQL-backed suite: **193 passed, 0 failed, 0 skipped** in
  **12.229 s**.
- Migration idempotency recheck: `applied: []`.
- Provenance audit: `[]`.
- Stage 5 referencing-FK index audit: `[]`.

### Populated Stage 4 upgrade

- Dedicated database: `havre_s5_upgrade_20260814_codex`.
- Before upgrade, the database had exact migrations `0001` through `0012` and
  real deterministic Stage 4 interaction, belief/transition, Current State,
  Goal/progress, consolidation, accepted memory, and provenance paths. It held
  13 events, one belief revision, one Goal, and 7 provenance edges, with an
  empty pre-upgrade provenance audit.
- Applying the current migration set applied only
  `0013_stage5_intervention_scenes.sql`; historical rows remained readable.
- Complete PostgreSQL-backed suite: **193 passed, 0 failed, 0 skipped** in
  **18.467 s**.
- Migration idempotency recheck: `applied: []`.
- Provenance audit: `[]`.
- Stage 5 referencing-FK index audit: `[]`.

### Focused Stage 5 evidence

- Six contract/policy tests and ten focused PostgreSQL/Web tests passed
  before the complete runs.
- One persisted full Scene completed Before, During, After, and closed with
  ordered `intervention, signal, intervention, action, intervention, outcome,
  reflection` records; it retained three decisions and one consented outcome
  observation, with an empty provenance audit.
- The local Web page was fetched through FastAPI and its actual create/start/get
  API flow was exercised against PostgreSQL.
- Raw-SQL regressions proved immutability, the hard false outreach constraint,
  owner isolation, valid transition sequencing, exact outcome-chain linkage,
  required provenance, and privileged erasure closure.
- JSON Schema export and committed-schema consistency passed.

## Synthetic policy evaluation

The frozen `scene-policy-simulation-v1` report is non-binding and stores
decision correctness separately from wording constraints. Its 10 cases cover
plausible danger, coercion, explicit help, uncertain safety, exhaustion,
low-danger avoidance, freezing, Before preparation, After reflection, and
no-goal ambiguity.

- Cases: **10**.
- Decision correct: **10**; incorrect: **0**.
- Wording constraints passed: **10**; failed: **0**.
- Outreach-authorized decisions: **0**.
- Maximum guidance length: **113 characters**.
- `binding_evaluation = false`; `gate_status = not_evaluated`.
- Final report run ID: `01a00060-af37-7070-a641-e133c04d86f1`.
- Final report hash:
  `sha256:e4728fdf968b34ec459fe36de42dab95c2f18d3e164eb6d6ab33e7874bc696af`.

The latency values measure only in-process deterministic policy execution and
are not a Web/service latency benchmark.

## Explicit limitations

- All policy cases and the end-to-end Scene are synthetic. They establish
  contracts, deterministic branch behavior, persistence, and Web/API wiring;
  they do not establish real-world benefit or safe production use.
- Danger, avoidance, energy, coercion, goal alignment, and urgency are explicit
  owner-selected categories. HAVRE does not passively sense them or claim that
  discomfort proves avoidance, danger, or incapacity.
- No human-labeled policy set, adjudication protocol, outcome scale, calibrated
  threshold, longitudinal denominator, clinical validation, or real-world
  benefit gate has been approved.
- Guidance is deterministic template wording. Passing forbidden-phrase and
  length checks does not establish that people will interpret it correctly.
- The Web page is a local developer simulator, not a production authenticated,
  multi-device, accessible, or deployed product surface.
- Stage 3 Qwen remains a candidate systems baseline. Stage 5 does not promote a
  model, add training data, activate LoRA, or establish broad semantic quality.
- Source erasure is implemented online, but full owner export, backup-expiry
  replay, external processor deletion, and content-free erasure receipts remain
  future governed work.

## Handoff gate

At this historical snapshot, Stage 5 implementation and verification appeared
complete; the later acceptance review rejected that conclusion and the current
candidate is recorded in the acceptance correction checkpoint. **Do not begin
Stage 6, enable proactive outreach, commit, or push without a new explicit
owner decision.**
