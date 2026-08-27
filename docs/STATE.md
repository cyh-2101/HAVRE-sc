# Project State

- Last updated: **2026-08-26**
- Current gate: **Major development is paused at the clean showcase checkpoint. ADR-0022 is accepted at the verified Core response-delivery boundary. v6/v7 remain immutable failed/rejected behavioral candidates and no further training is authorized. Raw and pipeline evidence remain separate; runtime containment does not rehabilitate either model. No new Stage, v8, Stage 9B, iPhone/Screen Time, Stage 12, private daily-feedback training, candidate status/UI/registry/serving change, promotion, deployment, product expansion, or broader sensing/context activation is authorized.**
- Stage 1: **Approved and complete**
- Proactive Interaction architecture amendment: **Accepted; Stage 6 conservative local runtime accepted, real outreach inactive**
- Stage 2: **Approved and complete**
- Stage 3: **Approved and complete at source snapshot `sha256:9a43713e082dec08039a93c673c7a0af812b881dcb0d5d3da68a0b17e7075436`**
- Stage 4: **Approved and complete at execution-source snapshot `sha256:34b65d5e9f2f2902369e0cd4d33f0f673a962f11ba17a899ed4727ea030435c8`**
- Stage 5: **Approved and complete at execution-source snapshot `sha256:e5497d6103c394a0885b667b828181c2f213da4c4b352f8d4f9fd92911c0032e`**
- Stage 6: **Accepted at execution-source snapshot `sha256:8ba8b94632ae181c2966acc3d6c498d8f7a63337d2e8558629b47dd440386f9c`; simulation-only**
- Stage 7: **Accepted at the same execution-source snapshot; proposal-only**
- Stage 8: **Technical exit evidence complete; independently reviewed with no P1/P2 blockers**
- Stage 9: **Accepted and closed at the technical-evidence boundary; 9201/9202 retained as unpromoted, undeployed behavioral candidates; Stage 9B deferred**
- Stage 10: **Complete at source `22700334eb375e1ee21283ca9d40efe5650cd8ec`; final independent review P1=0/P2=0; infrastructure-only deployment active, no adapter promotion/deployment**
- Stage 11: **Implementation checkpoint at `4b2d3096c1b303bab8ffba58cb1e370ee4e67e92`; code review P1=0/P2=0; exit blocked on Xcode/device evidence and Product Owner APNs/privacy decision**
- Stage 12A: **Authorized and implemented as a disabled checkpoint; Windows real-evidence gate and the first owner-supplied ICS import still block activation/exit**
- Ambient Life Context / experience-to-memory architecture amendment: **Accepted; only synthetic/manual Stage 6 contracts active**
- Daily conversation / episode / personalization-feedback amendment: **ADR-0021 accepted and implemented for owner-local use; no training or promotion authorization**
- Core-governed response delivery: **ADR-0022 accepted on 2026-08-25 at the verified hash-bound pre-delivery architecture boundary**
- Showcase checkpoint: **Public-safe synthetic demo and evidence documentation authorized on 2026-08-26; publication remains blocked by the separate public-release audit**

## Approved baseline

- Stage 0.1, ADR-0001 through ADR-0015, and Stage 1 were approved by the Product Owner on 2026-08-13.
- Stage 2, including its latest acceptance corrections, was approved by the Product Owner on 2026-08-13. Stage 3 implementation is explicitly authorized.
- Stage 3, including its acceptance corrections and renewed PostgreSQL, provenance, durable-request, and benchmark evidence, was approved by the Product Owner on 2026-08-14. Approval is bound to source snapshot `sha256:9a43713e082dec08039a93c673c7a0af812b881dcb0d5d3da68a0b17e7075436`.
- The Product Owner explicitly authorized Stage 4 implementation on 2026-08-14 and subsequently identified several acceptance blockers. After the Goal INSERT correction, renewed raw SQL probes found that required belief/progress provenance could be omitted and nullable Goal fields could not be cleared. The bounded correction and renewed evidence are recorded in [`STAGE4_REQUIRED_PROVENANCE_CORRECTION_CHECKPOINT.md`](STAGE4_REQUIRED_PROVENANCE_CORRECTION_CHECKPOINT.md). On 2026-08-14, the Product Owner accepted Stage 4 and bound that acceptance to execution-source snapshot `sha256:34b65d5e9f2f2902369e0cd4d33f0f673a962f11ba17a899ed4727ea030435c8`.
- On 2026-08-14, the Product Owner explicitly authorized Stage 5 implementation limited to Intervention Policy, Scene Session, and Web simulation. Independent acceptance review rejected the initial snapshot after reproducing four blockers. A later re-acceptance run found nondeterministic request-evidence ordering when two events shared one timestamp; evidence now uses monotonic event ID as the stable secondary key and the renewed 198-test evidence is recorded in [`STAGE5_ACCEPTANCE_CORRECTION_CHECKPOINT.md`](STAGE5_ACCEPTANCE_CORRECTION_CHECKPOINT.md). On 2026-08-14, the Product Owner accepted Stage 5 and bound that acceptance to execution-source snapshot `sha256:e5497d6103c394a0885b667b828181c2f213da4c4b352f8d4f9fd92911c0032e`.
- The Proactive Interaction amendment and ADR-0016 through ADR-0018 were accepted on 2026-08-13. This accepts future Core/Interruption/Delivery boundaries; it does not activate outreach.
- On 2026-08-19 the Product Owner accepted Stage 6/7 at execution-source snapshot `sha256:8ba8b94632ae181c2966acc3d6c498d8f7a63337d2e8558629b47dd440386f9c`, authorized Stage 8, and pre-authorized continuous transition to the bounded Stage 9 candidate foundation after blocker-free Stage 8 exit evidence. Stage 6 remains default-disabled local Web/inbox simulation; Stage 7 remains proposal-only. The decision does not authorize real contact, private-data export, external Context Sources, governance changes, personalized adapter promotion/deployment, or Stage 10.
- On 2026-08-19 the Product Owner accepted the corrected Stage 9 candidate foundation at execution-source snapshot `sha256:bf0ffbba5ade5d1370252c1f84ea1806b6ba5910f1c59ab4dff6df1f155d4119` with evidence hash `sha256:260b311a6bc8b21ff721687dc2f30150eb9d45e72dd4b90fa0c41f8e0ba54277`. The Product Owner then authorized Stage 9A real-transformer feasibility and training using repository-owned synthetic data only, all local-only and candidate-only, with no promotion, production deployment, Stage 9B, or Stage 10. The initial v1 real runs remain historical evidence. On 2026-08-20 independent review found a fail-closed file-boundary defect and 45/96 exact holdout-target overlaps with train. The boundary defect is corrected and regression-tested. Dataset v2 and v3 were subsequently rejected for training. The Product Owner supplied, reviewed, and exact-hash froze canonical Dataset v4 plus a physically separate 70-case PRIVATE Owner Alignment Set. Dataset v4 formal execution is complete. The Owner Alignment Set remained permanently excluded from training, validation-for-training, hyperparameter tuning, prompt/template tuning, synthetic-data generation, remediation selection, and seed selection; it was opened only for the final examination after the seed plan closed.
- On 2026-08-21 the Product Owner accepted the Stage 9A technical execution and ML pipeline evidence, including frozen Dataset v4, QLoRA, Seeds 9201/9202, four-arm evaluation, final Owner Alignment examination, and corrected resource evidence. Both adapters remain `candidate`; neither is promoted, deployed, or accepted as the final HAVRE brain. The owner's current preference for 9201 is explicitly non-promotional because fabricated-memory behavior, warm/firm judgment, Talk/Guide switching, and HAVRE identity continuity remain unresolved. OA70 v1 is retained only as PRIVATE historical evaluation/regression evidence and cannot be used to continue training or optimize OA70. Dataset v5, new training, a 9201 continuation experiment, and Stage 9B are deferred. The same decision authorizes Stage 10 and pre-authorizes Stage 11 only after blocker-free Stage 10 exit evidence; Stage 12 remains unauthorized.
- On 2026-08-22 Docker Desktop was installed on the owner-controlled Windows host and the previously missing native evidence was executed. Distinct immutable API images were deployed and rolled back, the final exact image was applied behind HTTPS/HSTS with two-phase activation, restart/failure recovery was exercised, and a release-bound backup restored with post-backup deletion replay and actual-login cutover verification. A live restore test exposed implicit restore-object ownership; source `22700334eb375e1ee21283ca9d40efe5650cd8ec` adds checked ownership finalization, revokes `PUBLIC` database CONNECT, and passes renewed native and 385-test evidence. Final independent exit review reported P1=0/P2=0. Exact evidence is in [`STAGE10_CHECKPOINT.md`](STAGE10_CHECKPOINT.md). Stage 10 is complete, Stage 11 is the next authorized stage, and Stage 12 remains unauthorized.
- On 2026-08-22 Stage 11 reached an implementation checkpoint at source `4b2d3096c1b303bab8ffba58cb1e370ee4e67e92`. The SwiftUI foundation uses the existing Core for text, owner-initiated on-device voice, playback, Scene controls, protected cache, exact-owner enrollment, FIFO offline reconciliation, and proposal/delivery-linked in-app actions. Current simulation-only records schedule zero OS notifications; APNs, Push entitlement, background audio, and real lock-screen delivery are inactive. Python/PostgreSQL regression passed 396/396, portable Swift XCTest passed 13/13, and independent code review reported P1=0/P2=0. Stage 11 exit is blocked on macOS/Xcode/device evidence and an explicit Product Owner APNs/privacy/data-routing decision. Exact evidence and limits are in [`STAGE11_CHECKPOINT.md`](STAGE11_CHECKPOINT.md).
- On 2026-08-22 the Product Owner explicitly deferred, without waiving, Stage 11 macOS/Xcode/physical-iPhone evidence and authorized Stage 12A only. Stage 12A remains minimum-sufficient and one capability at a time: Windows coarse context, then provider-neutral Calendar. After UIUC blocked the experimental Microsoft Graph consent, the Product Owner discontinued Graph and selected owner-initiated local ICS import before each semester. HAVRE makes no Microsoft login or Calendar network request: it obtains a current Core permit before opening the owner-selected file, parses bounded RFC 5545 daily/weekly recurrence locally, sends only availability intervals, never copies the ICS, and provides whole-source erasure plus restore replay. The Product Owner subsequently requested iPhone Screen Time as the next separately gated capability; no implementation or sensing begins until Calendar closes, and Apple entitlement plus deferred native evidence remain required. Stage 12B generally, location, wearables, all other richer sensing, Stage 9B, new training, and adapter promotion remain unauthorized. Exact evidence and limits are in [`STAGE12A_CHECKPOINT.md`](STAGE12A_CHECKPOINT.md).
- On 2026-08-22 the Product Owner accepted ADR-0021 and redirected near-term work toward real daily conversation plus longitudinal owner feedback. Every Web turn uses the existing Event Store; sessions close as exact-member episodes; summary/Memory suggestions are reviewed away from the chat flow; response ratings/edits preserve the original response and complete inference provenance. Saved data does not authorize training. A future Stage 9B may consume only exact separately approved revisions and still requires immutable dataset, evaluation, and promotion gates.
- Constitution v1 remains active with Agency, Reality, Warmth and Firmness, Growth, Truthfulness, and Continuity.
- Approved privacy defaults remain unchanged. `training_eligible = false`; only the owner may declassify; transformations receive their own policy and provenance and cannot bypass their source policy.
- Material changes to Constitution, Core Identity, Core Values, privacy, safety, intervention authority, training-data policy, or personalized production releases require explicit owner approval.
- Quantitative outcome scales, automatically inferred Scene signals, belief-confidence algorithms, follow-up cadence, and quantitative intervention thresholds remain deliberately unresolved. Stage 5 uses only an explicit categorical Web-simulation signal vocabulary.

- On 2026-08-25 the Product Owner authorized HAVRE_STAGE9A_V6_STYLE_FIRST for bounded Stage 9A audit/freeze/fresh-base training. Repo-native audit preserved 69 exact NORMAL owner anchors, rejected the external validation/holdout independence claim, and froze canonical bundle sha256:f69f0d0670424dbb200350efe29d4008b78e213859cccd7d7734c40e3dc783e9. After smoke and independent reload, the single fresh seed 9601 completed 1,928/1,928 optimizer steps; its adapter manifest is sha256:8e9e2c6cec7039348605eb97ff31536f9eac4237d2f93f9125555a2bf50d8959. A four-arm exact-base/9201/9202/v6 run completed all 256 post-plan unseen generations. v6 was shorter and less templated, but fabricated one no-evidence memory, underperformed 9201 on warm/firm and critical hard capability, omitted urgent safety actions, reproduced hidden system instructions, and broke one exact numeric output. It therefore remains an unregistered, unserved candidate blocked at behavior/data-quality and registry gates. Exact evidence and limits are in docs/STAGE9A_V6_STYLE_FIRST_CHECKPOINT.md.
- The Product Owner accepted the v6 experimental conclusion, rejected that candidate, and authorized one fresh capability-preserving revision without Owner anchors, OA70, private chat, or warm start. Balanced v7 canonical data contains 568 train/120 validation PUBLIC synthetic rows; bundle sha256:16af8325dbc5b5091cf973488682a0e51cbfb0f0ccabf54c85a9e1988650ea38. Seed 9701 completed 568/568 steps and exact reload. The post-plan 80-case unseen set remained separate from training/tuning. v7 recovered system confidentiality and exact output and materially improved medical uncertainty and tool/privacy boundaries, but fabricated memory in three no-evidence cases, gave unsafe or insufficient emergency guidance in three urgent cases, and was not clearly more natural than 9201. Semantic review sha256:13332eb3b6303c92702950358e40ec5b7eb4f3fdcff75b6e6a809346f7153c5e rejects it as a tradeoff. No second candidate or UI integration ran. Exact evidence is in [STAGE9A_V7_CAPABILITY_PRESERVING_CHECKPOINT.md](STAGE9A_V7_CAPABILITY_PRESERVING_CHECKPOINT.md).
- The Product Owner then kept v7 rejected and authorized a model-vs-Core responsibility audit plus necessary system corrections. `core-response-policy-v1` now preserves raw model evidence while binding the owner-visible assistant Event to a separate decision and delivered-output hash. Exact frozen v7 unseen generations were replayed without GPU/model execution: final source-bound report `sha256:97221a9cfdcc3faf2168b4d66670a2577a09863d5310fa979c68bfbba52aa436`. v7 raw versus pipeline deterministic hard passes are 10/40 versus 32/40; the remaining strict-marker failures are five evidence-bearing relevant-memory cases and three generalized confidentiality refusals. Runtime repair is not credited to v7, whose rejection/status remains unchanged. Exact evidence and limitations are in [STAGE9A_MODEL_VS_CORE_RESPONSIBILITY_CHECKPOINT.md](STAGE9A_MODEL_VS_CORE_RESPONSIBILITY_CHECKPOINT.md).
- On 2026-08-25 the Product Owner accepted ADR-0022 and only its verified responsibility boundary and Core response-delivery architecture. Core/runtime owns fail-closed memory provenance and unsupported-history blocking, urgent-safety minimum actions, hidden/system confidentiality, deterministic exact/structured serialization, and tool authorization/effect truthfulness. The personality model remains responsible for natural conversation and modes, warm/firm judgment, repair, opinions, identity/relationship continuity, natural use of legitimately supplied Memory, and long-form quality. This acceptance does not authorize v8, Stage 9B, private training data, candidate promotion/deployment/status changes, registry/serving/daily-use changes, or broader sensing/context activation.

## What exists now

- A public-safe deterministic showcase runner using a random synthetic owner and
  a dedicated loopback-only havre_showcase_ database. It demonstrates durable
  interaction/history, reviewed Memory, gated retrieval/ContextPack, response,
  feedback/edit lineage, exact episode membership, and a zero-violation
  provenance audit. This is wiring and persistence evidence, not model-quality
  or production evidence.

- The approved Stage 1 permanent request/trace/event/governance/ContextPack/provider/evidence slice.
- PostgreSQL migrations `0003_stage2_episodic_memory.sql` and additive `0004_stage2_acceptance_corrections.sql`; `0003` was not rewritten.
- pgvector-backed owner-qualified Stage 2 tables, constraints, indexes, immutable records, and a callable provenance-integrity audit.
- Transactional event/job enqueue plus an owner-bound `SKIP LOCKED` worker. Success and failure submission are fenced by lease owner, attempt generation, status, and expiry.
- Pending, human-inspectable candidates; one owner review transition; immutable reviewed content/hash/importance/decision; optional owner-reviewed importance.
- Immutable episodic memory revisions, current-head projection, correction, retraction, exact lifecycle events, embeddings, and owner-bound source/derived provenance.
- Typed `RetrievalRequest`/`RetrievalResult` contracts, exact `as_of` replay, privacy/status/time filtering, transparent scoring, explicit exclusions, and persisted versions/timing.
- Default `retrieval-r1-vector-gated-v2`: top K 5, minimum semantic similarity `0.35`, duplicate token overlap `0.65`, duplicate embedding similarity `0.70`.
- RetrievalResult and Context Builder v5 independently require the exact gated algorithm, selection policy, and thresholds; verify actual semantic scores and unique content hashes; and reject missing, non-finite, or below-minimum candidate similarity. Context Builder also verifies owner/request/trace/query-event lineage.
- Conservative privacy behavior: an interaction retrieves only classes no more restrictive than its current input classification.
- Stage 2 source-erasure closure across jobs/candidates, memories/vectors/provenance, retrieval candidates and both exclusion reference fields, ContextPacks, route/inference records, and affected assistant events. Raw source deletion remains separately authorized.
- API/CLI operations for memory lifecycle, owner-reviewed importance, evidence, provenance audit, and retrieval benchmarking.
- A checked-in, reviewed synthetic `retrieval-gold-v1` that now applies every fixture importance value and compares R0, legacy R1, and gated R1.
- Generated JSON Schemas for all active contracts.
- Full evidence in [`STAGE2_CHECKPOINT.md`](STAGE2_CHECKPOINT.md).
- Additive migration `0005_stage3_self_hosted_inference.sql`, with exact owner/request/trace-qualified inference lineage, immutable paired benchmark evidence, and durable typed pre-route/pre-inference/inference failure evidence.
- Additive migration `0006_stage3_runtime_attestation.sql`; `0001`-`0005` remain unchanged. It stores immutable content-free process attestations, binds new inference attempts to their attestation ID/hash, preserves historical rows as contract v0, and uses an INSERT trigger so no new caller can explicitly claim v0. Fresh installation and a populated `0005` in-place upgrade are now verified.
- A provider-neutral Stage 3 contract with exact version attestation, ordered streaming, health/version checks, typed failures, enforced timeouts, and capability/privacy/context eligibility checks.
- A loopback-only OpenAI-compatible adapter and independently deployable pinned llama.cpp b10405 service running Qwen3-8B GGUF Q4_K_M. Runtime construction now fails closed unless checked-in manifests, runtime state, active PID/start time, executable path/hash, exact arguments, model path/size/hash, loopback binding, disabled request logging/Web UI, live build, and loaded alias form one typed process-bound attestation.
- Ordinary Companion interactions recheck cheap PID/start/executable/argument liveness plus live build/alias before accepting `ProviderVersion`; direct self-hosted `generate()` and `stream()` also require valid attestation before any HTTP request. Self-hosted ProviderVersion and response lineage require the ID/hash, and completed and failed attempts retain the immutable reference. A healthy endpoint alone is not trusted.
- Version endpoint transport failures are durable `model_unavailable` / retryable failures. Deterministic runtime/build/model mismatch is durable `provider_protocol_error` / non-retryable. Neither path creates a fake inference attempt or assistant event before inference begins.
- Configuration-only swapping between `deterministic-local` and `self-hosted-openai-compatible`; Companion domain code and governed Identity/Values remain unchanged.
- Immutable, content-hash-verified workload/environment/system/compatibility reports for short scene-shaped, standard chat, long-reflection, and structured-extraction workloads, including a counterbalanced concurrency 1/2 comparison.
- A renewed real `LOCAL_ONLY` request proves the durable Companion path with per-interaction process attestation, exact model/runtime lineage, both durable message events, and measured token/latency evidence.
- A small Stage 3 developer chat CLI that reuses one durable session across turns while sending every message independently through Companion Core. It defaults to `LOCAL_ONLY`, disables memory ingestion, and does not fabricate conversational history or call the model server directly.
- Historical evidence is in [`STAGE3_CHECKPOINT.md`](STAGE3_CHECKPOINT.md). Renewed evidence and the approval-bound snapshot are in [`STAGE3_CORRECTION_CHECKPOINT.md`](STAGE3_CORRECTION_CHECKPOINT.md); existing report directories remain unchanged.
- Additive migration `0007_stage4_user_model_goals.sql`, activating immutable belief revisions and transitions, typed owner-qualified provenance, guarded consolidation proposals, expiring Current State, goal projections, goal progress records, and immutable User Model evaluation reports without rewriting `0001`-`0006`.
- Additive migration `0008_stage4_acceptance_corrections.sql`; `0001`-`0007` retain their exact pre-correction bytes. It strengthens belief-head and Goal projection guards, adds the missing Stage 4 foreign-key indexes, and leaves the existing partial generated-column provenance indexes unchanged.
- Additive migration `0009_stage4_reacceptance_corrections.sql`; `0001`-`0008` retain their exact bytes. It replaces cross-clock belief-head freshness with explicit single-use owner/belief/revision-qualified transition identities, binds Goal content hashes to immutable complete lifecycle projections and PostgreSQL statement time, and closes the derived-memory provenance FK index gap.
- Additive migration `0010_stage4_goal_canonical_projection.sql`; `0001`-`0009` retain their exact bytes. It requires the exact Goal and nested DataPolicy key sets, reconstructs the unique canonical projection from the guarded database row, and derives the accepted digest from that reconstruction instead of trusting caller-provided opaque JSON/hash material.
- Additive migration `0011_stage4_goal_insert_guard.sql`; `0001`-`0010` retain their exact bytes. It adds a dedicated Goal INSERT guard requiring active revision 1, one exact immutable same-owner `GOAL_CREATED` event and causation source, the strict canonical projection/digest, and database-authored initial timestamps.
- Additive migration `0012_stage4_required_provenance_guards.sql`; `0001`-`0011` retain their exact bytes. It guards belief revision/head creation, makes support/snapshot provenance a deferred commit requirement for Stage 4 derived records, extends the audit to missing required edges, and binds Goal progress INSERT to the current Goal revision, exact lifecycle event, evidence snapshot, and database-reconstructed hash. Goal update omission is now distinct from explicit null clearing.
- Goal progress now conservatively combines the exact current Goal policy with every evidence-source policy. Pattern and progress admission both require two distinct supporting identities on two normalized UTC dates, reject naive occurrence timestamps, recognize only their supported detector versions, and still create pending proposals only.
- Owner-reviewed qualified beliefs with support/counter-evidence, bitemporal `known_as_of` and `valid_at` replay, revision/supersession/contradiction/retraction/invalidation history, and no automatic confidence updater.
- Proposal-only semantic/pattern/progress consolidation with distinct-source/distinct-day admission for patterns and progress, one immutable owner review transition, correction on acceptance, and retrieval through the existing versioned memory boundary.
- Reality and inner-life goals with event-backed projection revisions and evidence-linked progress, plus expiring owner-reported Current State that cannot silently become a durable trait.
- Context Builder v6 admission for active qualified beliefs, goals, and non-expired state with independent owner/privacy/source/budget enforcement; retained under API stage `7` and service version `0.7.0`.
- Stage 4 erasure propagation through its complete derived lineage and any later prompt/inference/answer copies while retaining the separately governed raw source event.
- Superseded Stage 4 snapshots remain historical evidence in the prior checkpoint documents, including [`STAGE4_GOAL_INSERT_GUARD_CHECKPOINT.md`](STAGE4_GOAL_INSERT_GUARD_CHECKPOINT.md). Exact current fresh-install, populated-upgrade, raw direct-SQL, erasure, catalog-audit, limitation, and stop evidence is in [`STAGE4_REQUIRED_PROVENANCE_CORRECTION_CHECKPOINT.md`](STAGE4_REQUIRED_PROVENANCE_CORRECTION_CHECKPOINT.md).
- Additive migration `0013_stage5_intervention_scenes.sql`; `0001`-`0012` retain their exact bytes. It adds owner-qualified Scene Session projections, ordered Scene records, immutable Intervention Decisions, consented guidance-outcome observations, Stage 5 provenance destinations/audit coverage, and immutable synthetic evaluation reports.
- Additive migration `0014_stage5_acceptance_corrections.sql`; `0001`-`0013` retain their exact bytes. It makes current Scene state authoritative for record admission, binds transition time to PostgreSQL, reconstructs canonical row hashes in the database, requires one exact decision/input/guidance/policy chain, and preserves existing `0013` rows during in-place upgrade.
- Versioned `intervention-policy-sim-v1` categorical decisions for safety-first help, clarification, recovery, minimum action, preparation, and reflection. Every decision is `simulation_only = true`, `outreach_authorized = false`, carries the governing Constitution/Identity/Values versions, and has a hard low-bandwidth During guidance limit.
- A first-class optimistic-concurrency Scene aggregate with guarded Before/During/After/closed transitions and a durable Intervention → Action → Outcome → Reflection chain. Action and outcome records remain owner self-reports with uncertainty; outcome observations retain unknown/not-asked missingness and explicit consent.
- A real FastAPI Scene API and responsive local `/scene-simulator` Web page. The page calls the durable API; it is not a mock, does not schedule contact, and cannot initiate outreach.
- Frozen synthetic `scene-policy-simulation-v1` evaluation, separating branch correctness from wording constraints and recording phase, guidance length, in-process latency, safety/avoidance, exhaustion, coercion, and anti-dependence evidence. Current correction evidence and limitations are in [`STAGE5_ACCEPTANCE_CORRECTION_CHECKPOINT.md`](STAGE5_ACCEPTANCE_CORRECTION_CHECKPOINT.md); the initial snapshot remains historical in [`STAGE5_CHECKPOINT.md`](STAGE5_CHECKPOINT.md).
- Stage 5 source erasure conservatively removes the affected Scene projection, ordered records, decisions, outcome observations, provenance, and derived guidance. Separately governed raw/lifecycle events are retained with erased Scene/deleted-decision references detached and their canonical event hashes reconstructed.
- Additive migrations `0015` through `0017` activate the Stage 6 local proactive lifecycle: immutable owner preferences, Trigger/Proposal/four-way Core decision, purpose-bound Context Pack, deterministic rendering, idempotent local Web inbox delivery, and provenance audits. Database checks require `simulation_only = true` and `external_delivery_authorized = false`.
- Controlled raw/summary/compressed Context strategies retain prefix-stable governed sections and cache instrumentation. The adaptive router hard-filters privacy/capability incompatibility before ranking and records its reasons and fallback.
- Synthetic/manual `LifeContextObservation`, freshness, and source-health contracts are available for local fixtures only. They explicitly remain observations rather than interpretations and set `external_source_activated = false`.
- Additive migrations `0018` through `0020` activate Stage 7 local jobs, reflection and memory-lifecycle proposals, append-only owner reviews, canonical dataset snapshots, rejection manifests, artifact manifests, retry ceilings/metrics, and source-revocation records.
- The current canonical dataset builder independently checks source policy and rejects every owner-derived event under unchanged `training_eligible = false`; therefore its member manifest is intentionally empty. Same-source rebuilds produce the same content hash.
- Stage 7 reflection creates proposals only. It cannot create an Interruption Decision, call delivery, mutate Memory, or activate training. Source erasure removes affected offline derivatives and records revocation so regeneration cannot resurrect them.
- Additive migration `0021_stage67_acceptance_corrections.sql` closes the reproduced Stage 6/7 acceptance blockers without rewriting `0001`–`0020`: revoked-source admission guards, owner-action/response linkage, durable proactive work items, and their indexes. Runtime corrections add owner-scoped proactive serialization, stable HTTP policy identity, exact job-input binding, and failure state that survives processing rollback.
- Additive migration `0022_stage67_second_acceptance_corrections.sql` adds the authoritative owner preference head and database-level offline owner/source admission locks without rewriting `0001`–`0021`. New proactive execution resolves the current head under the same owner lock used to save preferences; direct SQL evidence admission serializes with erasure before checking revocation.
- Additive migration `0023_stage8_unified_evaluation.sql` and typed Stage 8 services provide ten-domain unified evaluation, versioned evidence bundles, trace exploration, release comparison, calibrated judge/human review, protected artifact retention/access, and durable closure guards. Exact evidence and independent review are in [`STAGE8_CHECKPOINT.md`](STAGE8_CHECKPOINT.md).
- Additive migrations `0024` through `0032` provide the accepted Stage 9 local synthetic/public canonical dataset, physically separate evaluation holdout, model-specific rendered artifact, model/training/adapter registries, exact compatibility and factorial evaluation binding, candidate-only adapters, and rejection/no-activation rollback evidence. The initial candidate was rejected because holdout crossed the persisted training boundary. The first correction was rejected because `0030` allowed repeated rendered members and omitted canonical members. Additive `0032` recomputes the actual member manifest and requires a unique, bidirectionally exact rendered-member bijection without rewriting `0030`. The Product Owner accepted the corrected bounded foundation; exact evidence and limitations are in [`STAGE9_CHECKPOINT.md`](STAGE9_CHECKPOINT.md).
- A separate Stage 9A environment on `D:` contains the hash-verified exact Qwen/Qwen3-8B revision `b968826d9c46dd6066d109eabc6255188de91218` and immutable historical v1/v2 evidence. The Product Owner-authored v4 canonical dataset has 300/60/120 train/validation/sealed-holdout examples and reproduces external bundle hash `sha256:13fa5a62ec6edc571c51468a8a07c2c362744236de0b418a0d9c543de0b586c4`. The v4 rendered manifest is `sha256:8bad6bd7042b3039f549ea5f8080f5e4f63ed83582aa91aa5aa15ec42e1c659a`; it contains only train/validation at max length 336 with zero measured truncation. The renderer masks all historical/context labels, supervises only the final HAVRE target, selectively injects supplied synthetic memory, and treats proactive examples as wording after Core-authorized `SEND_NOW`. Independent review found the first formal source's Windows shared-GPU collector could fail open to zero, so that evidence remains historical and is superseded. The minimal correction reran the exact Stage 9A plan using a versioned fail-closed `typeperf` collector. Corrected formal Seeds 9201/9202 and fresh reloads are bound to archived execution-source snapshot `sha256:943fa77aa164e4e8dff517dbcd5e3dbfe468da54edcf97a07cbb2fe114660a07`; final Owner Alignment remains bound to `sha256:63992b001daac065ad5b4c3cdd0f771aad219698ed05ed80de03eadbf560d03d`. A second independent review found aggregate resource fields also needed exact recomputation from raw samples. The superseding registry does that fail-closed under source snapshot `sha256:915f29920d43b4b51185c48432b956e135bddbadc1950abd1de10dce1ee0a8bb`; its exact hash is `sha256:03b6a86acc290d9ddc4735b1aff6a5f1f2f451cc80bded551cac96e9cff27c36`. The snapshot is now revalidated from a private 316-file archive against the exact blobs of committed source revision `a28acc8a499e30b80688ceb130b7e20c027f09d1`; explicit CRLF-to-LF comparison handles historical checkout bytes without consulting ambient Git filters, and future HEAD changes do not rewrite this historical binding. No promotion or deployment exists.
- Owner-local development use can load the exact registered Seed 9201 PEFT adapter over the exact Stage 9A base through a loopback-only, request-log-disabled candidate runtime. Companion Core verifies the sealed registry, exact adapter/base bytes and revisions, launcher/server/process arguments, and RuntimeAttestation v2. The legacy CLI retains explicit per-candidate review for diagnostics; the normal Web chat no longer interrupts each turn. It preserves raw history, closes a complete session into one exact-member episode, and moves derived suggestions to concentrated Memory review. Seed 9201 remains an unpromoted, undeployed, replaceable development fixture; no training, Dataset v4/OA70, evaluation criteria, or release status changed.
- The daily Web product at `/chat` provides durability-gated response streaming, continuous conversation history, thumbs feedback, owner-edited alternatives, reason labels, a review pool, explicit response-length preference, accepted Memory inspection, episode summaries, and episode-suggestion review. Policy-eligible recent turns enter ContextBuilder v8 with exact user/assistant roles and Event provenance, so multi-turn behavior is supplied by Core rather than browser-only state. PostgreSQL migration `0036_owner_feedback_personalization.sql` adds the records; corrective `0037_daily_learning_canonical_hash_guards.sql` makes session closure terminal at service and direct-SQL boundaries, binds conservative summary/suggestion DataPolicy, reconstructs canonical hashes and complete same-session membership at commit, rejects training approval while Stage 9B is inactive, preserves export/erasure/replay closure, and fails closed rather than rewriting pre-correction episode evidence. Feedback/review/episode contracts are exported as JSON Schema.
- Stage 9 closeout verification used fresh database `havre_stage9_closeout_rerun_20260821`, migrated through `0001`-`0032`, and the two pinned runtime environments: **343 passed, 0 failed, 0 skipped**; Stage 9 FK/catalog and full provenance audits both returned `[]`; both `pip check` runs, bytecode compilation, and the exact registry consumer passed against the unchanged immutable registry artifact. No migration or active contract schema changed.
- Additive migrations `0033_stage10_deployment_reliability.sql` and `0034_stage10_backup_fk_index.sql` implement immutable release/approval/deployment, backup/replay, owner-export, role, and exact FK-index boundaries. Stage 10 adds HTTPS/deployment manifests, health/version/metrics quarantine, exact image/source/component binding, least-privilege offline operations, backup/restore, deletion replay, and explicit release/rollback workflows. Exact evidence and limitations are in [`STAGE10_CHECKPOINT.md`](STAGE10_CHECKPOINT.md).

## What does not exist

- No automated User Model inference or confidence algorithm, free-running Scene sensing, automatic memory mutation, user-derived training run, approved personalized adapter, or personalized release. Stage 7 reflection/consolidation remains deterministic and proposal-only. Stage 9A real transformer training used repository-owned synthetic/public-safe data only and does not establish personal or real-world benefit.
- No approved production conversational release. The Stage 3 self-hosted model remains a candidate baseline and Seed 9201 is available only as an owner-local development fixture; neither establishes production, personalized, structured-output, or broad conversation quality.
- No real proactive contact or external delivery adapter. The only Stage 6 visible effect is an explicitly enabled, local, simulation-only Web inbox fixture.
- No external Ambient Life Context source registry, consent/sampling/retention worker, Windows agent, Calendar adapter, iPhone sensing, ambient voice capture, location connector, or wearable connector. Synthetic/manual contracts do not establish any sensing capability.
- No production Web client, iPhone client, voice, or tool use. The Stage 5 Web surface is a local simulator only. Stage 10 now has an owner-local infrastructure-only Docker deployment; it activates no behavioral release and contains no promoted adapter.
- No final multi-device identity policy, provider-side deletion, erasure receipt policy, or approved crisis/professional-help boundary. Stage 10 now provides the bounded single-owner bearer, exact owner export, confirmed source deletion, backup expiry, and restored-backup deletion replay paths.

## Verification evidence

Stage 6/7 verification used the repository-owned PostgreSQL 18.4 cluster on
`127.0.0.1:55432`. It was stopped before the task, started only for verification,
and is restored to stopped state at handoff.

Current Stage 8/9 correction verification used a dedicated fresh database and
migrations `0001` through `0032`:

- full PostgreSQL-backed repository suite: **264 passed, 0 failed, 0 skipped**
  in **24.464 s**;
- Stage 4/5/6/7/8/9 foreign-key index audits and the complete provenance audit:
  `[]`;
- Stage 8 and Stage 9 integrity violations: `0` and `0`;
- the trainer-visible snapshot/artifact contains train `4`, validation `2`, and
  holdout `0`; the separately persisted evaluation holdout contains `2` cases,
  all training-ineligible, evaluation-only, and access-limited;
- populated `0028` upgrade evidence preserves the rejected contaminated row,
  records `evaluation_holdout_in_training_snapshot_v1`, and prevents it from
  producing new trainer-visible artifacts;
- populated `0031 -> 0032` evidence retains the valid artifact/runs, rejects a
  repeated-member artifact and its bound run with SQLSTATE `55000`, and leaves
  both forged counts at zero;
- exact evidence and limits: [`STAGE8_CHECKPOINT.md`](STAGE8_CHECKPOINT.md) and
  [`STAGE9_CHECKPOINT.md`](STAGE9_CHECKPOINT.md).

The current second-correction evidence supersedes both earlier rejected Stage 6/7 candidates:

- Fresh `0001`–`0022`: **228 passed, 0 failed, 0 skipped** in **15.491 s**.
- Populated `0021`-to-`0022`: preference revisions 1/4 backfilled to exact current head 4 and existing Reflection/lifecycle evidence remained readable; applying only `0022` was followed by **228 passed, 0 failed, 0 skipped** in **15.064 s**.
- On both final paths, migration reapplication was empty and provenance plus Stage 4/5/6/7 foreign-key-index audits returned `[]`.
- Direct regressions additionally prove queued work adopts a later global disable and database evidence admission serializes with concurrent erasure even when the Python owner lock is bypassed.
- Full current details are in [`STAGE67_SECOND_ACCEPTANCE_CORRECTION_CHECKPOINT.md`](STAGE67_SECOND_ACCEPTANCE_CORRECTION_CHECKPOINT.md). The 226-test [`STAGE67_ACCEPTANCE_CORRECTION_CHECKPOINT.md`](STAGE67_ACCEPTANCE_CORRECTION_CHECKPOINT.md) is historical rejected evidence.

The following 218-test evidence is historical and was rejected by acceptance review:

- Fresh `0001`-`0020`: **218 passed, 0 failed, 0 skipped** in **12.156 s** after contract schema regeneration. The preceding run's three failures were stale generated schemas after a typed default-factory hardening; it is not counted as passing evidence.
- Populated `0017`-to-`0020`: a complete Stage 6 local inbox fixture was created before upgrade. Applying only `0018`, `0019`, and `0020` preserved the delivered fixture with `simulation_only = true` and `external_delivery_authorized = false`; the complete suite passed **218 passed, 0 failed, 0 skipped** in **11.533 s**.
- Migration reapplication returned `applied: []`. Provenance and Stage 4, 5, 6, and 7 foreign-key-index audits returned `[]` on the final paths.
- Contract export, `pip check`, bytecode compilation, and `git diff --check` passed. Exact Stage 6 and Stage 7 evidence and limitations are in [`STAGE6_CHECKPOINT.md`](STAGE6_CHECKPOINT.md) and [`STAGE7_CHECKPOINT.md`](STAGE7_CHECKPOINT.md).

Stage 5 correction verification used the repository-owned PostgreSQL 18.4
cluster at `D:/projects/HAVRE/var/postgres` on `127.0.0.1:55432`, with pgvector
0.8.6. It was stopped before the task, started only for verification, and is
restored to stopped state at handoff.

- Fresh `0001`-`0014`: **198 passed, 0 failed, 0 skipped** in **13.620 s**.
- Populated `0013`-to-`0014`: the pre-upgrade database contained a complete
  closed Stage 5 Scene with 7 records, 3 decisions, and 1 outcome observation,
  plus real Stage 4 lineage. Applying the current set applied only `0014`; the
  historical Scene remained readable and the complete suite passed
  **198 passed, 0 failed, 0 skipped** in **13.416 s**.
- A separate populated `0012` compatibility path applied only `0013` and
  `0014`, then passed **198 passed, 0 failed, 0 skipped** in **15.037 s**.
- Migration reapplication returned `applied: []` on all current paths.
  Provenance and Stage 5 FK-index audits returned `[]` on every path.
- The frozen policy suite passed **10/10** decision and wording cases with zero
  outreach-authorized decisions; maximum guidance length was 113 characters.
  This is small deterministic simulation evidence, not real-world benefit.
- Contract schema export, Web/API integration, owner isolation, raw-SQL
  immutability/outreach constraints, current-state record admission,
  database-time/canonical-hash binding, exact decision/guidance binding,
  outcome provenance, and complete cyclic Scene erasure closure are included
  in the zero-skip suite.

Environment: Windows 11, CPython 3.12.13, FastAPI 0.141.1, Pydantic
2.13.4, Psycopg 3.3.4, PostgreSQL 18.4, and pgvector 0.8.6.

The Stage 3 evidence below used the then-required user-local WSL cluster at
`<owner-home>/.local/share/havre/postgres18-stage3`. That is historical runtime
evidence. The current Stage 5 verification instead used the exact
repository-owned Windows cluster identified above; neither path installed a
Windows service.

- Fresh database: `0001` through `0006` applied in order, then the full suite
  passed **154/154, 0 failed, 0 skipped** in **13.086 s**.
- Populated upgrade: committed source `e873267` created a real durable
  `LOCAL_ONLY` request on an exact `0001`-through-`0005` schema; current source
  then applied only `0006`. The historical inference attempt remained readable
  as contract v0 with null attestation references, and the full suite passed
  **154/154, 0 failed, 0 skipped** in **10.609 s**.
- The first fresh zero-skip run exposed one integration-fixture error: a direct
  self-hosted failure test supplied a valid attestation to the provider but did
  not register it before durable insertion. The fixture now uses the same
  registration precondition as the real runtime. Its focused regression passed,
  followed by both complete passes above.
- Fresh, populated-upgrade, and real-evidence provenance audits each returned
  `[]`.
- Focused serving/provider/benchmark and Windows orchestration tests pass,
  including model-hash, alias, PID reuse, executable/start-time/argument,
  health-without-attestation, typed version failure, and ownership-aware
  rollback cases.
- The isolated benchmark test has repeatedly blocked inside Windows
  `tempfile.mkdtemp()` / `os.mkdir` under repository `var/`, including an exact
  test timeout after 30 seconds and a full discovery still running after 124
  seconds. This occurs before benchmark execution or resource-collector
  construction. Explicit `NullResourceCollector` injection remains the correct
  removal of hidden collector coupling, but did not establish or fix the
  observed filesystem root cause.
- The complete `var/`-backed scenario now runs in a terminable subprocess with
  a 20-second hard timeout. It still verifies the required `var/` child path,
  pending-directory atomic publication, report files, persistence call, and
  cleanup. On timeout, the parent terminates it and starts a separately bounded
  cleanup process that accepts only the exact UUID-owned `var/` child. Progress,
  owned path, worker output, and cleanup outcome are included in the failure.
- After this isolation correction, the final exact test passed **10/10** in ten
  fresh Python processes (1.059-1.158 s each; 0 failures, 0 timeouts). Three
  final fresh full discoveries passed **3/3**: 152 tests in 9.151 s, 6.711 s,
  and 6.562 s; each had 118 passed, 34 PostgreSQL skips, 0 failures, and 0
  timeouts. These
  bound discovery impact in the current environment; they do not prove Windows
  filesystem or security software is generally stable.
- Clean-checkout portability is covered inside the terminable worker. It safely
  creates and validates a missing direct project `var/` before the UUID-owned
  child, rejects a file/link/junction or wrong parent, and never moves directory
  creation into the parent discovery process. A simulated clean project with no
  `var/` completed the full benchmark publication and persistence checks.
  Cleanup still accepts only the exact direct
  `.stage3-benchmark-fs-test-<UUID>` child and never removes `var/` itself.
- Every normal-finally and standalone-cleanup deletion now revalidates the same
  boundary with `lstat` and Windows reparse attributes: `var/` must still be the
  real direct project child, and the direct UUID-owned root must itself be a
  real directory. Missing `var/` is a no-op and is not created by cleanup.
  Controlled junction regressions prove that a linked `var/` and a linked
  owned root are both rejected while their sentinel and target remain intact.
- Local startup now verifies the active server's normalized `data_directory`, PostgreSQL 18 version, and available pgvector before database creation or migration. Rollback attempts every resource it started and aggregates failures; stop refuses to erase state when an owned API PID file is missing.
- The renewed pinned llama.cpp/Qwen runtime produced process-bound attestation
  `stage3-runtime:17536:1786650350448656` with hash
  `sha256:3db71df2da8ae18e65c1926ab5f0255033e9b70257d53d7991624a048f883a2c`,
  model size `5,027,783,488`, and model SHA-256
  `sha256:d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785`.
- Real durable request `019ffcaa-2c68-7217-8823-80a5fc8813e0` used trace
  `fb0f5de6ccd837a0e56a3c4189c9110b`, stored both `USER_MESSAGE` and
  `ASSISTANT_MESSAGE`, and was handled by Qwen3-8B through llama.cpp
  `b10405@e79e4bf660e19f2ad851e06c6913f7a8c5852621`. Policy remained
  `LOCAL_ONLY`, `cloud_eligible = false`, and `training_eligible = false`.
  Provider usage was 550 prompt, 25 output, and 575 total tokens; measured TTFT,
  generation, and inference total were 514.071 ms, 329.908 ms, and 854.282 ms.
- New immutable report directory
  `var/benchmarks/stage3-correction-20260814-final-9a43713e` matches final source
  snapshot `sha256:9a43713e082dec08039a93c673c7a0af812b881dcb0d5d3da68a0b17e7075436`.
  Benchmark run `019ffcac-50db-77c3-b2ad-08d0786477da` completed all 32/32
  measured requests with zero typed errors. The systems and non-binding
  compatibility hashes are respectively
  `sha256:4a81b34c8eb6b787107cd6da152216458303766efb6536cc19007a3eacf1225c`
  and
  `sha256:6f69a9ce4541369570bed79bb4955bc5300a10159e760a91c851f169f4fc0070`;
  typed reload, pair validation, process attestation, and both immutable
  database rows matched.

- Fresh database, migrations `0001–0005`: **132 passed, 0 failed, 0 skipped**.
- A populated database containing 197 Stage 1/2 requests upgraded in place from `0001–0004` to `0005`; **132/132** tests passed afterward, and all 142 old inference responses retained exact request linkage.
- An `e32c742` database containing real Stage 2 rows upgraded from `0001–0003` by applying only `0004`; all old rows remained readable and a new gated request used the old memory.
- Pending-job and rejected-candidate deletion succeeds without any accepted memory.
- Source deletion propagation removes stored retrieval, prompt, inference, route, and affected assistant-response copies while retaining the separately governed raw source event.
- An insertion with correct derived/event/trace owner but a foreign-owner provenance source fails at the database boundary; the integrity audit reports zero violations.
- A stale worker cannot finish after a replacement claims a newer lease generation.
- A stale worker also cannot submit failure after lease expiry or replacement.
- Reviewed candidates reject content, hash, and decision mutation.
- Below-threshold retrieval returns an empty candidate set; duplicate memory is suppressed; deletion follows `exclusion.memory_id` and `exclusion.duplicate_of_memory_id`; both validation layers reject spoofed eligibility, unsafe semantic scores, duplicate hashes, and mismatched lineage.
- Gold fixture importance values `0.3–0.9` are present in the benchmark database.
- Two benchmark runs produced identical rankings, policies, exclusions, and non-latency quality metrics; latency varied normally.

| Metric | Legacy R1 | Gated R1 v2 |
|---|---:|---:|
| Recall@5 / Recall@10 | 1.0 / 1.0 | 1.0 / 1.0 |
| MRR | 0.90 | 0.90 |
| Wrong-memory rate | 0.76 | **0.375** |
| Duplicate-group rate | 0.20 | **0.00** |
| Should-not-surface / stale / error | 0 / 0 / 0 | 0 / 0 / 0 |
| Provenance completeness | 1.0 | 1.0 |
| p50 / p95 latency, final run | 0.912 / 1.196 ms | 1.083 / 1.525 ms |

Stage 4 required-provenance correction verification used CPython 3.12.13 with
PostgreSQL 18.4 / pgvector 0.8.1. A fresh `0001`-`0012` installation and a
populated exact `0001`-`0011` database upgraded by applying only `0012` each
passed the complete **177-test suite with 0 failures and 0 skips**. Required
provenance and full Stage 4 referencing-FK index audits returned `[]` on both
paths. Raw SQL regressions prove that active initial beliefs, missing belief
support, nonexistent Goal revisions, forged Goal-progress hashes, and missing
Goal-progress snapshot edges fail at their intended durable boundaries. The
ordinary Goal service path proves omitted nullable fields are retained and
explicit null clears them. Historical synthetic/replay reports were not
rebound to this persistence-only correction. See
[`STAGE4_REQUIRED_PROVENANCE_CORRECTION_CHECKPOINT.md`](STAGE4_REQUIRED_PROVENANCE_CORRECTION_CHECKPOINT.md).

## Current limitations and risks

- The repository-owned local database runtime is suitable for this verification
  run, not a production permission model. Deployment still requires a separately
  reviewed installation/lifecycle path and distinct migrator, application, and
  privileged erasure roles.

- The deterministic feature-hash embedding and tiny synthetic corpus do not establish broad semantic quality. Gated wrong-memory rate `0.375` remains material.
- The `0.35/0.65/0.70` gate is tied to the current embedding/gold set and must be versioned and re-evaluated when either changes.
- Exact vector scanning is correct for the measured corpus. Lexical search, a reranker, and ANN require larger-corpus evidence.
- Online Stage 2 deletion closure is implemented; source deletion authorization, backups/restores, external processors, and content-free receipts remain governed future work.
- Owner review currently relies on the configured local owner boundary. Authentication and UI remain required before production-like sensitive use.
- The current `GRANT ... TO CURRENT_USER` erasure setup is for local acceptance only. Real deployment requires separate migrator, application, and privileged erasure database roles.
- The Stage 3 candidate returned nonempty responses for every measured case, but both structured workloads failed the JSON parse observation; no quality threshold or release gate was approved.
- Two final real runs completed all 32/32 measured requests. Concurrency 2 increased aggregate output throughput, but it also increased per-request latency/TPOT and produced five cross-run output-hash differences out of 16 concurrency-2 samples; all 16 matched concurrency-1 samples were stable. Temperature zero therefore must not be described as globally deterministic under parallel continuous batching.
- Stage 3 still measures provider TTFT internally. The Web endpoint now streams text to the client only after the completed assistant Event is durable; this is truthful progressive rendering, not a low-TTFT claim. Interrupted pre-commit token reconciliation remains unimplemented.
- Stage 4's proposal detector and lexical personal-context selector are small deterministic baselines. They do not establish broad semantic understanding, stable-trait inference, calibration, or longitudinal benefit.
- Durable belief confidence uses only `owner-reviewed-v1`; the deliberately unresolved automatic confidence algorithm remains inactive.
- Current State is owner-reported and expiring. Goal progress is evidence-linked but does not compute a percentage or claim real-world improvement.
- Stage 5 policy cases are categorical, deterministic, and synthetic. They do
  not establish calibrated danger assessment, clinical safety, human wording
  quality, longitudinal usefulness, or real-world benefit.
- Scene signals and outcomes are explicit owner-entered Web-simulation inputs;
  HAVRE performs no passive sensing and does not infer that discomfort is
  avoidance or that silence is danger.
- Source health and freshness are synthetic contracts only. Consent scopes,
  provider-neutral external adapters, and real-world signal quality remain
  unimplemented and unevaluated.
- Stage 6 policy and routing evaluation uses eight deterministic synthetic
  cases. It establishes branch behavior and enforced boundaries, not calibrated
  interruption quality or real-world proactive benefit.
- Stage 7's empty canonical member manifest is the correct result of the current
  training policy, not evidence that a personalized dataset or model is useful.
- Stage 8 proactive usefulness remains inconclusive without real owner benefit
  labels; its synthetic/manual source-health evidence activates no external
  source or sensing capability.
- The accepted Stage 9 foundation still uses six repository-authored examples
  and a tiny linear matrix dry-run. Stage 9A separately provides real Qwen3-8B
  QLoRA evidence on frozen synthetic/public-safe Dataset v4. Its two formal
  adapters and synthetic evaluations establish bounded local feasibility and
  fixture behavior only, not real-world benefit, personalization, or release
  readiness. Both adapters remain candidate-only and unactivated.
- The intervention policy release status remains
  `candidate_owner_acceptance`. Quantitative thresholds and outcome scales are
  not activated, and no Stage 5 output authorizes contact or delivery. Stage 5
  acceptance does not promote this simulation candidate to a production policy
  release.

## Next allowed action

Stop at the Stage 9A v7 behavior and hard-capability gate. Do not register,
serve, promote, deploy, expose, or continue training seed 9701 automatically.
Owner-local daily use remains on the unchanged 9201 development binding, and
feedback/edits remain non-training-eligible. Any later Stage 9A experiment
requires an explicit Product Owner decision and a newly closed plan. Stage 9B,
private-chat training, and automatic promotion remain unauthorized. The
disabled Stage 12A gates remain available separately.
