# Project State

- Last updated: **2026-09-06 UTC**
- Current gate: **The owner approved short default conversational turns and an optional “再说点” button after finding both Context A/B arms too verbose. Owner experience v3, planner v6/v7 and PWA v17 are implemented and loaded on the owner-local API/worker. Final verification: 860 primary + 62 pinned-Torch tests, zero failures/errors/skips; provenance []; 13/13 budget/raw-retention cases and all 16 targeted source sets preserved. The preceding authorized targeted-recall patch is included. Production Context architecture, compiler, thresholds, model settings and reminder permissions are unchanged. No training, model promotion, evaluation cloud generation, commit or push. Real conversational likeness and physical-iPhone experience remain owner-use evidence; the earlier 18-call cloud proposal remains pending. See SHORT_TURNS_REVIEW_2026-09-06.**
- Stage 1: **Approved and complete**
- Proactive Interaction architecture amendment: **ADR-0024 accepted; governed automatic Reach Out and the narrow generic LOCAL_ONLY Push envelope are owner-enabled while the owner PC/backend is online**
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
- Stage 12A: **Calendar is owner-locally activated through the canonical manual-ICS availability-only path; Windows real-evidence remains deferred and Stage 12B remains unauthorized**
- Stage 13: **Authorized and in progress under ADR-0027; 13A-C are local candidate/evidence work, 13D default-model promotion is an explicit owner gate**
- Stage 14: **14A PUBLIC-only MCP control is implemented. ADR-0030's Stage 14B dual route is technically verified and active on the owner-local runtime: eligible PUBLIC/NORMAL ContextPacks use GPT-5.6-sol and non-GPT-eligible or stricter ContextPacks use the exact unadapted Qwen3-8B. This is an operational privacy route, not local-model promotion or proof of conversational usefulness. Private cloud continuity remains unauthorized. ADR-0035 separately authorizes the existing source-guarded `relationship_follow_up` category. ADR-0036's latest explicit authorization permits the exact eligible completed PUBLIC/NORMAL turn to be sent to GPT-5.6-sol/high for the one-minute/30-minute two-beat continuation; stricter turns remain excluded and old local receipts remain local.**
- Stage 15: **15A and the bounded 15B commitment loop are implemented and active for the exact Fall 2026 owner schedule by explicit task direction. Migration 0059 extends the same exact-source closure to daily-review files, explicit chat Goal receipts, their derived Goals/reminders, and Memory/conversation-sourced proactive work. Migrations 0060-0063 add exact source-pair receipts, immutable beat lineage, delivered-parent enforcement, exact GPT-high versus historical-local provider binding, and erasure through both continuation beats and queue items. Exact scheduled Goal reminders remain independent; the optional daily filler is limited to one stable daytime message across all eligible Goals and prefers the nearest deadline. Important reminders and friendly check-ins have separate owner-facing controls. The in-conversation two-beat stop, newer-message cancellation, active-chat deferral, and separate cold 24/72-hour three-touch pause are technically verified and production-active. Formal ADR-0032/0035/0036 review, owner-observed usefulness, and remaining enrollment/date clarifications remain open.**
- Practical companion UX: **ADR-0033/0034/0035 and ADR-0037's owner-authorized repair are active. Eligible completed GPT turns now generate source-quoted Memory/User Model understanding through an independent high-effort background queue; private/local candidates still require owner review. Diary v6 covers the previous local 05:00 to current local 05:00 and writes first-person content plus source-bound improvement files. A real long-experience omission was repaired and the record verified; neither complete recall nor repeated owner usefulness is claimed. PWA v12 corrects stale-message flashes and focus-before-ack notification navigation, with physical-iPhone verification still open. The paired iPhone retains only its enumerated review writes; no broader privacy or write authority is implied.**
- Owner-calibrated runtime examples: **ADR-0031 formally accepted cases 1-20; ADR-0035's explicit owner-local implementation direction extends the runtime bank to exact OA70 cases 1-70. At most three relevant examples enter one GPT turn, with no training or Memory eligibility; all 70 cases are now contaminated as independent holdout evidence.**
- Ambient Life Context / experience-to-memory architecture amendment: **Accepted; only synthetic/manual Stage 6 contracts active**
- Daily conversation / episode / personalization-feedback amendment: **ADR-0021 accepted and implemented for owner-local use; no training or promotion authorization**
- Core-governed response delivery: **ADR-0022 accepted on 2026-08-25 at the verified hash-bound pre-delivery architecture boundary**
- Showcase checkpoint: **Public-safe synthetic demo and evidence documentation authorized on 2026-08-26; publication remains blocked by the separate public-release audit**

## Approved baseline

### Short default turns and explicit continuation (2026-09-06)

The [short-turn review](SHORT_TURNS_REVIEW_2026-09-06.md) records the owner's
approved refinement of ADR-0033. Default replies normally make one short
conversational move; requested detailed work remains complete. “再说点” creates one
ordinary visible owner turn using existing privacy, session and idempotency rules.
Four-second paragraph presentation pauses during typing and stops automatically
on a newer owner message; saved text remains available. No hidden essay or
repeated-generation loop is added. Goal reminders and the separately authorized
relational initiative keep their existing behavior.

Source `sha256:fdddede16771aa1e09a0c2981445780da64df0ecbd174e2ceac7b14d37aa1e2a`, **922 tests passed, zero skips**, test provenance empty.
Owner-local runtime restarted and healthy on migration 0071; v17 shell verified.
Model-generation preference, repeated-use usefulness and physical-iPhone evidence
are not established by this patch's deterministic tests and synthetic browser run.


### Bounded targeted recall and owner preference review (2026-09-06)

The [targeted recall report](TARGETED_RECALL_REVIEW_2026-09-06.md) records source-only
resolution from explicit owner naming statements, exact request-pair preservation,
short same-session clarification hints and conservative ambiguity/unknown handling.
It introduces no entity registry, inferred durable identity, new model or threshold
change. Tests bind S03/S04 sources through final provider messages; generated
clarification quality is not yet verified for this patch. Source snapshot:
`sha256:91b63c1b9a995fa9ad98ef6d639343bfff8bfa164a701e251e63ca0ffbd0029e`.
The eight-pair LOCAL_ONLY review asks only owner likeness and willingness to keep
chatting. Exact choices may become source-bound product regression receipts,
never automatic training or product ingestion. Production rollout and the proposed
new cloud regression were not executed; the latter awaits an explicit owner reply
to the consolidated automatic-review approval gate.

### Completed blind Context A/B (2026-09-06)

The owner-approved source packet v2 produced 32 real targets across eight nominal
strata and 12 dialogue families, plus eight preselected generation repeats and
12 separately constructed recall stress cases. All 104 valid answers use the same
GPT-5.6-sol/medium configuration. The initial reviewer-clock repair was followed
by an actual outbound audit that found date and word-boundary corruption in real
case deidentification. Both earlier real analyses are preserved as invalidated
diagnostics. All 80 real answers and 80 dual-order reviews were rerun with exact
unchanged targets and verified final provider inputs; 24 unaffected stress answers
and their 24 clock-informed reviews were reused unchanged.

The [experiment report](CONTEXT_AB_EXPERIMENT_2026-09-06.md) records the final
inconclusive result, all dimensions, latency/tokens/cost limits, source visibility
failures and the exact stop boundary. Simple wins 12 / Full 8 / tie 1 / unresolved
11; its 56.3% share has a family-clustered 95% interval of 42.9%–65.9%. Order
agreement is 65.6%, and all eight repeat consensus labels change, including two
direct arm reversals. No global simplification or production scenario router is
justified. No Goal/Current State layer was admitted in the real sample, so its
architectural value remains untested.

The permanent change is offline experiment tooling, clock and deidentification
integrity regressions, and the 12-case synthetic stress fixture. Candidate retrieval
found both same-name sources in two stress queries but existing admission rejected
them; this remains an observed recall gap, not a tuned-away target. Final tests:
824 primary plus 62 pinned Torch, zero failures/errors/skips; source snapshot
`sha256:5dd65306b5733031a4009202f8bd65c3b8d5d503ea9699dca1cc9484ff6e91ff`.
Test provenance is empty. Production code/schema/configuration were not changed.
These are model semantic judgments without owner pairwise calibration, not
proof of long-term companionship, physical-phone UX or proactive usefulness.

### Latest fresh reassessment and verified software slice (2026-09-06 UTC)

The [complete 21-part review](PERSONAL_CONTEXT_ENGINE_REVIEW_2026-09-06.md) and
[ADR-0039](adr/0039-personal-context-engine-and-evidence-compiler.md) supersede
older algorithm/UI/verification snapshots below. A strong Brain plus simpler
persistent identity, continuous raw history, explicit source lookup, correction
and governed delivery is a valid competing baseline; the project does not treat
Personal Context Engine, RAG or ML Systems complexity as ends in themselves.

Implemented: shared evidence allocation; indexed lifetime raw recall with exact
long-text excerpt boundaries; owner correction/retraction overlays; valid-time
selection and stale queued-context guards; canonical follow-up identity; OA70
selection without case-ID bias; recursive owner-qualified source previews and
return-to-chat; PWA v16. Manual Strong retains exact selected excerpts and cannot
append newly discovered private sources to its prepared disclosure snapshot.

Verified source snapshot:
`sha256:81d84a1a6199061d9e1a2b68061b593634edead45d4319ac83aa1712b295fc3c`.
Primary 805/805 and pinned Torch 62/62, zero skips. Fresh 0001→0071 and populated
0068→0071 match all 71 migration checksums; production additive upgrade preserved
all old checksums and 16 checked owner-table counts, with zero provenance findings.
The owner-local API/worker were restarted through the existing `-RestartApp` path;
PostgreSQL, model artifacts and paired-device credentials remain in place.
Final production checks: seven authorized endpoints HTTP 200, four private
endpoints unauthenticated HTTP 401, provenance zero, no ordinary processing
request, worker live, PWA v16 served JS matching disk; exact process/provider
attestations recorded in the review's linked local evidence.

Measured regression gains include raw-experience retention 9/13→13/13 under
budget pressure and recovery of constructed old/long-tail source omissions.
A four-pair real-GPT context ablation also found simpler input retained the tested
facts with fewer tokens; it does not establish a global architecture winner.
Browser functional checks cover 12 scenarios at 390/1440 widths using synthetic
data. Physical-iPhone Push/keyboard/cold-start and repeated owner usefulness remain
unverified. Source-only snapshots still have a concurrent first-correction window;
head/State transaction locks are not a claim that all network-time edits are atomic.

### Previous daily-product quality follow-through (2026-09-06 UTC)

The owner-local correctness/continuity and UI pass is active. Migration 0068,
production state repair, exact provider versions, tests, screenshots and explicit
limits are recorded in [the quality checkpoint](DAILY_COMPANION_QUALITY_CHECKPOINT_2026-09-06.md).
Use that record before the earlier checkpoints below. Application-only restart is
available through `scripts/start_havre_desktop.ps1 -NoBrowser -RestartApp`, preserving
database/model processes and existing paired-device credentials. This does not
authorize another Stage or claim physical-device/long-term companion acceptance.

Final frozen-code validation: 745 primary plus 62 pinned-Torch tests passed,
zero skipped database tests; source revision stayed fixed during the primary run.
Migration 0068 is production-active. Production provenance violations are zero;
all seven checked product/health endpoints returned HTTP 200. Strong independent
review and physical-iPhone/repeated-use evidence remain explicitly open.

### Latest verified GPT-route recovery (2026-09-05, 14:54 America/Chicago)

The owner retry exposed another failure not covered by the earlier readiness
check: a cloud-ineligible daily-review flag became a chat instruction and redirected
ordinary chat to Qwen, whose per-slot capacity was overstated; its unread streaming
error was then mislabeled. Daily reviews now stay in the manual suggestion workflow
on both routes, with their stored policy intact. Runtime and benchmark both use the
evidenced 4,096-token local slot bound within the unchanged 8,192-token/two-slot
profile; streaming context errors keep their safe typed code. No private source was
made cloud eligible. API/worker are live; eligible default GPT and local Qwen each
completed a real synthetic reply through the actual chat endpoint and durable Core
path in an isolated database. Full regression: 734 primary + 62 Torch = 796 passed,
zero database skips. Live local benchmark: 32/32 measured requests completed;
production provenance `[]`, Memory/Diary/settings/timeline/readiness HTTP 200.
Historical failed messages remain preserved and are not automatically resent.
See [`GPT_ROUTE_RECOVERY_CHECKPOINT.md`](GPT_ROUTE_RECOVERY_CHECKPOINT.md).
Physical-iPhone retry and repeated conversational usefulness remain unverified.

### Earlier request-lifecycle recovery (2026-09-05)

The owner approved repair and recovery of a stuck ordinary chat request. The
updated owner-local API/worker are live at unchanged migration head 0067. Ordinary
streaming replies are process-owned across viewer disconnects; cancellation
cleanup is drained; expired requests receive exact-source terminal failures
rather than indefinitely blocking the PWA. The identified old request is now
failed/retryable with its original Event/hash preserved and no automatic resend.
There are zero ordinary processing requests at the post-restart check. PWA v13
adds bounded waits, pending-state polling, and manual original-draft retry with
privacy and draft preservation. It supersedes v12 below while retaining those
earlier rendering/navigation fixes. Full regression: 730 primary + 62 pinned
Torch = 792 passed, zero database skips; test and production provenance `[]`;
readiness, timeline, Memory, and Diary HTTP 200. See
[`INTERACTION_RECOVERY_CHECKPOINT.md`](INTERACTION_RECOVERY_CHECKPOINT.md).
This is a bounded operational correction, not new model, privacy, erasure,
contact-cadence, or stage acceptance authority. Physical-iPhone verification and
an owner-initiated real retry remain unproven.

### Latest verified Memory/Diary repair (2026-09-04)

See [`REALTIME_MEMORY_EXPERIENCE_CHECKPOINT.md`](REALTIME_MEMORY_EXPERIENCE_CHECKPOINT.md).
Migrations 0064-0067, eight additive local semantic indexes, independent real-time
GPT-high understanding, and the five-to-five Diary boundary are owner-locally
active. A real output probe reproduced a 558-character source quote exceeding
the 500-character contract: prompt v2 now specifies an exact bounded excerpt,
and real-time shape/source errors retry instead of silently completing empty.
The corrected prior-window review durably created three Memory records and five
local improvement suggestions. Its source-bound history remains append-oriented.
Memory and Diary endpoints return HTTP 200. This supersedes the older v5 timing
descriptions below; those paragraphs retain their historical evidence meaning.


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
- On 2026-09-03 the Product Owner accepted ADR-0031 and explicitly authorized OA70 cases 1-20 as runtime examples. The frozen OA70 source remains unchanged; a separate owner-specific NORMAL/cloud-eligible, memory/training-ineligible bank preserves exact source and case hashes and admits at most three relevant examples. Cases 1-20 are now prompt-exposed and no longer independent holdout evidence. The same bounded repair adds authoritative owner-local message time, current-session-first raw history with explicit-reference-only cross-session fallback, ResponsePlan v3 dialogue acts, and an explicit medium Codex reasoning effort. Cases 21-70, training/tuning, GPT-authored proactive delivery, and all other prior boundaries remain unauthorized.
- ADR-0031 implementation and owner-local activation are verified in [`STAGE13_OWNER_CALIBRATED_RUNTIME_CHECKPOINT.md`](STAGE13_OWNER_CALIBRATED_RUNTIME_CHECKPOINT.md): 641/641 primary plus 62/62 pinned-Torch tests passed (703/703 combined, zero database skips), provenance audit returned `[]`, and the live runtime is ready with GPT-5.6-sol medium effort, the exact first-20 example bank, and an unadapted Qwen3-8B local route. This is technical evidence only; the owner-visible Practical Utility Gate remains open.
- On 2026-09-04 the Product Owner explicitly authorized ADR-0035's owner-local
  implementation: the exact OA70 cases 1-70 runtime bank, a mandatory
  experience-first response instruction, fixed 05:00 Diary v5 review, bounded
  prior eligible context, evidence-bound improvement files, explicit chat Goal
  planning, Memory/conversation-sourced relationship follow-ups under Core, and
  friendly Memory/Goal/Diary presentation. Migration 0059 and the owner-local
  API/worker are active. Verification passed 678/678 primary plus 62/62
  pinned-Torch tests (740/740 combined, zero database skips), and both disposable
  and owner production provenance audits returned `[]`. A live Memory endpoint
  failure caused by a missing `re` import was corrected, regression-covered, and
  both Memory and Diary endpoints returned HTTP 200 after restart. Exact evidence
  and remaining boundaries are in
  [`EXPERIENCE_FIRST_DAILY_REVIEW_CHECKPOINT.md`](EXPERIENCE_FIRST_DAILY_REVIEW_CHECKPOINT.md).
- Later on 2026-09-04 the Product Owner authorized design and implementation of
  bounded friend-like initiative: one local-only continuation after 30 seconds,
  increasing unanswered intervals, at most three relationship touches before a
  reply reset, and Goal reminders that remain independent. Migration 0060 and
  the candidate implementation passed 692/692 primary plus 62/62 pinned-Torch
  tests (754/754 combined, zero database skips); its initial focused suite passed 13/13,
  including direct SQL wrong-hash, wrong-pair, LOCAL_ONLY-source, and illegal-
  transition attacks. Fresh and in-place migrations passed, provenance audits
  returned `[]`, and production is healthy at migration head 0060 with a live
  worker heartbeat, clean operational startup, and zero continuation rows. A
  real local-Qwen dry-run plus owner-facing runtime readback then cleared the
  bounded activation gate; the launcher now enables it while the owner preference
  and all Core controls remain authoritative. Exact evidence is
  in [`BOUNDED_RELATIONAL_INITIATIVE_CHECKPOINT.md`](BOUNDED_RELATIONAL_INITIATIVE_CHECKPOINT.md).
- A same-day experience audit then found that the settings page still described
  Memory/conversation outreach as impossible and exposed only one combined Reach
  Out switch, while the daily filler could enqueue one item per eligible Goal.
  The owner-facing PWA now separates **重要提醒** from **日常聊聊**, explains the
  three-unanswered pause without technical vocabulary, and limits supplemental
  Goal contact to one stable slot per local day across all eligible Goals while
  leaving exact scheduled reminders unchanged. Focused verification passed 57/57;
  final repository verification remained 692/692 primary plus 62/62 pinned-Torch
  (754/754 total). The activation run repeated 57/57 focused and all 754 split-
  environment tests. After restart, production served PWA v10 with both independent
  controls and the actual natural-continuation state, Memory and Diary returned
  HTTP 200, API and worker were live, migration head was 0060, provenance audit
  returned `[]`, the preference was globally enabled with both categories
  allowed, and the continuation table remained empty rather than backfilling history.
- A later owner correction authorized friend-like initiative during the current
  conversation: the first delayed beat is due after one minute, a second only 30
  minutes after the first was actually visible, and there is no third beat. The
  first GPT reply may itself ask one grounded question or offer a view; a separate
  owner-experience v2 instruction makes everyday curiosity a valid purpose instead
  of requiring a task. Migrations 0061-0062 add immutable beat/parent lineage and
  append-correct the delivered-work guard. Focused continuation verification passed
  17/17; the complete suite passed 699/699 primary plus 62/62 pinned-Torch tests
  (761/761, zero database skips), and test/production provenance audits returned
  `[]`. Production is healthy at migration head 0062 with live API/worker, PWA v11
  foreground timeline refresh, preference revision 17, and a two-per-24-hour
  `conversation_continuation` ceiling. Memory and Diary return HTTP 200, stderr is
  empty, five historical v1 receipts remain unchanged, and no v2 receipt was
  backfilled. The local quality gate rejects default recovery coaching, fabricated
  HAVRE life history, closed guesses about unmentioned facts, generic confirmation,
  and unsupported mind-reading. Repeated owner-observed naturalness remains open.
- After asking why the delayed path still used Qwen, the Product Owner explicitly
  approved the separate GPT data flow. Migration 0063 and
  `conversation-continuation-v3-gpt-high` bind new exact-source receipts to
  isolated no-tools GPT-5.6-sol/high while retaining old local receipts. Focused
  verification passed 20/20, including zero Qwen calls on GPT failure; the
  complete suite passed 702/702 primary plus 62/62 pinned-Torch tests
  (764/764, zero database skips). The disposable and production
  provenance audits returned `[]`. A synthetic non-delivering real GPT probe
  returned and passed the quality gate; its distinct question continued the topic
  without entering the database or queue. Production is ready at migration head
  0063 with live API/worker, Memory and Diary HTTP 200, current stderr logs empty,
  the existing two-per-24-hour permission intact, no silent fallback, five
  historical v1 rows unchanged, and no GPT receipt backfilled. Repeated real-owner
  usefulness remains unproven.
- The first naturally due production 05:00 review initially produced 38 durable
  `ValidationError` failures because GPT used near-synonym enum labels, while
  the worker retried immediately. Optional provider effects now fail closed or
  normalize only three explicit follow-up aliases and one explicit belief alias;
  unknown suggestion categories enter the existing `experience` catch-all,
  and persisted 1m/5m/15m/1h/6h backoff prevents a provider retry storm. The
  repaired run completed at attempt 41 with GPT-5.6-sol/high, a 7-character title,
  266-character first-person Diary, three evidence-bound suggestions, one exact-
  source User Model update, and a hash-matched local review file. Final verification
  is 695/695 primary plus 62/62 pinned-Torch (757/757, zero skips), with production
  provenance `[]`.
- On 2026-09-03 the Product Owner directed implementation of the exact Fall
  2026 course schedule slice. Stage 15A created 50 active LOCAL_ONLY reality
  Goals and an initial 134 source-guarded reminder work items. Five source batches
  completed through exact unadapted Qwen3-8B without GPT fallback; four
  catch-up items reached the local Web inbox at 15:00 and 130 future items
  remained pending. Their obsolete relative-day wording was found by live
  readback, corrected in the generator, covered by regression, and followed by
  one source-guarded consolidated correction in the inbox. Same-day catch-up
  duplication was then removed: 131 reminders remain effective (four delivered
  and 127 current pending), while three append-preserved stale rows are bound to
  old Goal revisions and must cancel at execution. The corrected rerun reused
  all 50 Goals, replayed 127 future keys, and skipped four past catch-ups. Internal
  source batches remain auditable but are hidden from the conversation timeline.
  Final verification passed 644/644 primary plus 62/62 pinned-Torch tests
  (706/706 combined, zero database skips), and the owner-database provenance
  audit returned `[]`. Formal ADR-0032 acceptance remains pending. Exact
  evidence and remaining enrollment/date questions are in
  [`STAGE15_OWNER_COURSE_SCHEDULE_CHECKPOINT.md`](STAGE15_OWNER_COURSE_SCHEDULE_CHECKPOINT.md).
- Later on 2026-09-03 the Product Owner explicitly authorized the bounded Stage
  15 commitment-loop extension and owner-local runtime activation. Migrations
  `0054` and `0055` add the exact five-field projection, immutable completion
  evidence, conversation-fusion and delivery records, integrity view, and FK
  indexes. The production import reused all 50 Goals, transitioned the two
  4-credit-only Goals to `abandoned`, created 48 active plus two abandoned
  current projections under one exact authorization, inserted 127 v2 future
  reminders, skipped four past catch-ups, and created no new source interaction.
  Source-scoped generation replacement cancelled all 130 legacy pending items
  while preserving four historical succeeded items; an identical rerun
  cancelled zero more items. The running owner-local API and worker are ready on
  migration head `0055`, both GPT-5.6-sol and the exact unadapted Qwen3-8B are
  healthy, the Stage 15 integrity view returns zero rows, and owner-database
  provenance audit returns `[]`. The privileged source-erasure closure now
  includes derived Goals, projections, transition evidence, reminder records,
  fusion claims, and proactive queue artifacts only after the owner explicitly
  names a source Event. No production source or derivative was erased in this
  activation. Exact evidence is in
  [`STAGE15_COMMITMENT_LOOP_CHECKPOINT.md`](STAGE15_COMMITMENT_LOOP_CHECKPOINT.md).
  Final complete PostgreSQL-backed regression after the queue-replacement
  repair passed 722/722 with zero skips; the dedicated test database was
  removed afterward.
- Later on 2026-09-03 the Product Owner authorized implementation and production
  activation of the practical companion UX correction recorded as pending
  ADR-0033. Web automatic Memory proposals now require explicit stable owner
  statements; review supports edit-before-accept without rewriting candidates;
  confirmed Memory can propose but never auto-activate a User Model belief;
  Diary v3 retains selected owner-life facts instead of authorization/import
  mechanics; and visual reply grouping remains one governed assistant Event.
  Additive migration `0056` is active. Final unified verification passed
  730/730 PostgreSQL-backed tests with zero skips and provenance audit `[]`.
  Authenticated production Chrome at 390 x 844 measured client/scroll width
  390/390 on Chat, Memory, and Diary, with the complete bottom navigation
  inside the viewport. The API and worker are running; both GPT-5.6-sol and the
  exact unadapted Qwen3-8B report healthy. This does not prove physical iPhone
  keyboard/safe-area behavior or subjective usefulness, does not authorize
  paired-device persistent writes, and erased no source. Exact evidence is in
  [`PRACTICAL_COMPANION_UX_CHECKPOINT.md`](PRACTICAL_COMPANION_UX_CHECKPOINT.md).
- Later on 2026-09-03 the Product Owner explicitly authorized ADR-0034's bounded
  Diary intelligence and paired-review extension. The prior long-title/流水 behavior
  came from Diary v3's deterministic top-phrase join and truncation. Diary v4 now
  sends only completed GPT-routed PUBLIC/NORMAL cloud-eligible day Events to an
  isolated high-effort GPT request, produces a short first-person “我” reflection,
  omits low-value days, and exposes all private/local messages only through a local
  collapsed transcript. Exact-quote durable updates from eligible GPT owner messages
  may create active Memory and candidate-plus-activated User Model revisions under
  the recorded owner delegation; private-derived understanding stays owner-reviewed.
  Fixed quality flags can influence later replies only through code-owned bounded
  instructions. Migrations 0057 and additive hardening 0058 are active. The production
  run used 30 cloud-summary plus 30 private-reference Events, high effort, and created
  two Memory plus two User Model updates; private content was never model input.
  Complete verification passed 735/735 with zero skips and production provenance
  audit returned []. No source Event was selected or erased. Exact evidence is in
  [`GPT_DIARY_PAIRED_REVIEW_CHECKPOINT.md`](GPT_DIARY_PAIRED_REVIEW_CHECKPOINT.md).
- Constitution v1 remains active with Agency, Reality, Warmth and Firmness, Growth, Truthfulness, and Continuity.
- Approved privacy defaults remain unchanged. `training_eligible = false`; only the owner may declassify; transformations receive their own policy and provenance and cannot bypass their source policy.
- Material changes to Constitution, Core Identity, Core Values, privacy, safety, intervention authority, training-data policy, or personalized production releases require explicit owner approval.
- Quantitative outcome scales, automatically inferred Scene signals, belief-confidence algorithms, follow-up cadence, and quantitative intervention thresholds remain deliberately unresolved. Stage 5 uses only an explicit categorical Web-simulation signal vocabulary.

- On 2026-08-25 the Product Owner authorized HAVRE_STAGE9A_V6_STYLE_FIRST for bounded Stage 9A audit/freeze/fresh-base training. Repo-native audit preserved 69 exact NORMAL owner anchors, rejected the external validation/holdout independence claim, and froze canonical bundle sha256:f69f0d0670424dbb200350efe29d4008b78e213859cccd7d7734c40e3dc783e9. After smoke and independent reload, the single fresh seed 9601 completed 1,928/1,928 optimizer steps; its adapter manifest is sha256:8e9e2c6cec7039348605eb97ff31536f9eac4237d2f93f9125555a2bf50d8959. A four-arm exact-base/9201/9202/v6 run completed all 256 post-plan unseen generations. v6 was shorter and less templated, but fabricated one no-evidence memory, underperformed 9201 on warm/firm and critical hard capability, omitted urgent safety actions, reproduced hidden system instructions, and broke one exact numeric output. It therefore remains an unregistered, unserved candidate blocked at behavior/data-quality and registry gates. Exact evidence and limits are in docs/STAGE9A_V6_STYLE_FIRST_CHECKPOINT.md.
- The Product Owner accepted the v6 experimental conclusion, rejected that candidate, and authorized one fresh capability-preserving revision without Owner anchors, OA70, private chat, or warm start. Balanced v7 canonical data contains 568 train/120 validation PUBLIC synthetic rows; bundle sha256:16af8325dbc5b5091cf973488682a0e51cbfb0f0ccabf54c85a9e1988650ea38. Seed 9701 completed 568/568 steps and exact reload. The post-plan 80-case unseen set remained separate from training/tuning. v7 recovered system confidentiality and exact output and materially improved medical uncertainty and tool/privacy boundaries, but fabricated memory in three no-evidence cases, gave unsafe or insufficient emergency guidance in three urgent cases, and was not clearly more natural than 9201. Semantic review sha256:13332eb3b6303c92702950358e40ec5b7eb4f3fdcff75b6e6a809346f7153c5e rejects it as a tradeoff. No second candidate or UI integration ran. Exact evidence is in [STAGE9A_V7_CAPABILITY_PRESERVING_CHECKPOINT.md](STAGE9A_V7_CAPABILITY_PRESERVING_CHECKPOINT.md).
- The Product Owner then kept v7 rejected and authorized a model-vs-Core responsibility audit plus necessary system corrections. `core-response-policy-v1` now preserves raw model evidence while binding the owner-visible assistant Event to a separate decision and delivered-output hash. Exact frozen v7 unseen generations were replayed without GPU/model execution: final source-bound report `sha256:97221a9cfdcc3faf2168b4d66670a2577a09863d5310fa979c68bfbba52aa436`. v7 raw versus pipeline deterministic hard passes are 10/40 versus 32/40; the remaining strict-marker failures are five evidence-bearing relevant-memory cases and three generalized confidentiality refusals. Runtime repair is not credited to v7, whose rejection/status remains unchanged. Exact evidence and limitations are in [STAGE9A_MODEL_VS_CORE_RESPONSIBILITY_CHECKPOINT.md](STAGE9A_MODEL_VS_CORE_RESPONSIBILITY_CHECKPOINT.md).
- On 2026-08-25 the Product Owner accepted ADR-0022 and only its verified responsibility boundary and Core response-delivery architecture. Core/runtime owns fail-closed memory provenance and unsupported-history blocking, urgent-safety minimum actions, hidden/system confidentiality, deterministic exact/structured serialization, and tool authorization/effect truthfulness. The personality model remains responsible for natural conversation and modes, warm/firm judgment, repair, opinions, identity/relationship continuity, natural use of legitimately supplied Memory, and long-form quality. This acceptance does not authorize v8, Stage 9B, private training data, candidate promotion/deployment/status changes, registry/serving/daily-use changes, or broader sensing/context activation.
- On 2026-08-26 the Product Owner authorized one focused relevant-Memory-use milestone. `context-builder-v9` now validates rank/score order, budgets gated Memory before optional old history while reserving recent conversation, and accounts exact presentation overhead. `context-presentation-v2-natural-memory-linking` renders one provenance-preserving system context with optional-use, current-precedence, partial-evidence, silent-influence, semantic-scope, and tentative-link guidance. The final system-only replay is `sha256:470c9370e3abc426754a59a0624b5a81e5da0c48029975fa202c87289801f539`. A separately closed 45-train/20-validation PUBLIC synthetic continuation from frozen rejected v7 produced unregistered seed 9801; it completed 45 steps but the final post-plan unseen strict semantic result was only 25/32 versus v7 24/32, and the representative AI/self-learning callback still became an unsupported accusation. 9801 is not behaviorally accepted, registered, served, promoted, deployed, or bound for daily use; 9201 remains the unchanged owner-local binding. Exact evidence and limits are in [RELEVANT_MEMORY_USE_MILESTONE_CHECKPOINT.md](RELEVANT_MEMORY_USE_MILESTONE_CHECKPOINT.md).
- On 2026-08-26 the Product Owner authorized one Strong Cloud Brain ceiling experiment. A default-disabled DeepSeek `deepseek-v4-pro` adapter now implements the existing provider-neutral boundary with environment-only authentication, a sealed exact-request PUBLIC-synthetic permit, private-data fail-closed admission, safe typed errors, provider-verifiable alias lineage, and discarded reasoning content. Independent focused same-prompt review scored thinking/high 28/32 versus the best local 22/32, without forced-callback or current-precedence failures, but with one fabricated-familiarity failure and weaker casual results. The conditional 80-case absolute regression found stronger primary quality but worse naturalness/verbosity; its frozen local prompts are 0/80 exact and are not used for model attribution. No training or lifecycle/binding change occurred. Exact evidence is in [STRONG_CLOUD_BRAIN_CEILING_CHECKPOINT.md](STRONG_CLOUD_BRAIN_CEILING_CHECKPOINT.md).
- On 2026-08-28 the Product Owner separately authorized manual Strong Brain use for owner data. ADR-0025 keeps 9201 as the default and permits only an explicit per-reply action. The selected canonical source Context is derived as HIGHLY_PRIVATE, remains memory/training-ineligible, and must be durably prepared and request-bound before DeepSeek receives content. The focused Daily Companion repair also makes short-term chat continuous across engineering sessions, admits source-bound owner corrections and feedback reasons as response constraints, replaces extractive Diary v1 with concrete-event Diary v2, and clarifies Memory/User Model semantics. This does not activate automatic routing or globally change source privacy. Final fresh PostgreSQL verification and owner-local runtime activation are complete. Windows Application Control blocked the unsigned Windows PostgreSQL binary, so the governed launcher now uses the existing project-owned WSL PostgreSQL 18.4 + pgvector runtime after exact data-directory and capability attestation. The active canonical owner cluster is `/home/OWNER/.local/share/havre/postgres18-owner-20260828`; `C:\HAVRE\var\postgres` remains an untouched pre-0051 recovery snapshot, not a second writable source of truth. Exact evidence is tracked in [DAILY_COMPANION_MEMORY_DIARY_STRONG_REPAIR_CHECKPOINT.md](DAILY_COMPANION_MEMORY_DIARY_STRONG_REPAIR_CHECKPOINT.md).
- On 2026-09-02 the Product Owner superseded only ADR-0025's default-brain clause and accepted ADR-0026. Seed 9201 is owner-rejected for daily use because its real conversation experience is materially too far from the intended assistant. Its candidate registry and evidence remain immutable. The desktop launcher now uses the existing exact unadapted Qwen3-8B Stage 3 candidate as a temporary no-adapter baseline so model, Context, Memory, Core, and evaluator defects can be separated before choosing a stronger local base. Typed Response Plan, relevance-gated Memory Broker, replaceable Replyer, existing Core, and proposal-only offline review are the accepted direction. Same-prompt candidate comparison and hash-pinned official downloads into the ignored owner-local runtime are authorized, but raw private-chat cloud disclosure, driver changes, training, routing, promotion, and deployment are not.
- The first ADR-0026 slice is implemented at `response-planner-v1` / `context-builder-v11` / `context-presentation-v5-response-plan`. Response obligations are escaped and explicitly retained at untrusted user priority. A three-run, runtime-bound 13-case PUBLIC synthetic raw screen rejects the unadapted 8B baseline as a replacement: in 3/3 samples it truncates before the requested model decision, makes unsupported migration guarantees, gives shallow local-model hardware guidance, and loses positive relevant-Memory use under the secured control context. It still suppresses irrelevant/stale/absent/partial Memory and respects current correction. Earlier evaluator arms are superseded because injected Memory and the Response Plan conflicted, case modes were misclassified, or user obligation text lacked an explicit priority boundary. This remains proposal-only model-judge evidence, not owner-calibrated end-to-end acceptance. The exact implementation, report hashes, verification, MaiBot comparison, and 14B preparation boundary are in [CONVERSATION_STACK_BASELINE_CHECKPOINT.md](CONVERSATION_STACK_BASELINE_CHECKPOINT.md).
- The exact official Qwen3-14B Q4_K_M candidate subsequently passed pinned artifact verification, isolated loopback health/SSE, and three runtime-bound PUBLIC synthetic runs on the RTX 5070 Ti Laptop GPU. All 39 requests ended normally. Relative to 8B it removed the multi-request truncation, stopped making unsupported migration guarantees, and restored natural use of the relevant-Memory precedent, at about 48.4% higher median arm latency. It remains held from daily promotion because 3/3 runs still avoided the requested clear model decision and omitted essential VRAM/system-RAM/quantization/runtime and live-price constraints from buying guidance. The daily runtime was restored to exact unadapted Qwen3-8B with no adapter; 14B is only the leading local candidate for a later full ContextPack/Core A/B and owner comparison.
- On 2026-09-02 the Product Owner clarified that GPT-5.6-sol means the current Codex development agent, approved the refined architecture, requested a new stage and documentation, and asked the agent to continue until a real decision gate. ADR-0027 therefore creates Stage 13. Stage 13A now introduces `response-planner-v2`, `interaction-orchestrator-v8`, `context-builder-v12`, and `context-presentation-v7-practical-utility`: the Turn Contract is independent of retrieval, explicitly records when one recommendation is required, gates actual Memory search before Context construction, and renders a requested decision answer-first with a reversible bottleneck test and an explicit no-invention rule. Historical plan v1 remains replayable. Verification completed at 587/587 primary plus 62/62 pinned Torch tests (649/649 combined), zero skips, schema export, compile checks, clean dependency checks, provenance audit `[]`, and diff validation. A real database-boundary regression proves independent turns persist explicit empty retrieval while explicit continuation permits retrieval.
- The three-run 14B Turn Contract v2 raw replay was reproducible on 12/13, 12/13, and 13/13 cases, but is rejected as a quality improvement. All three model-decision turns reached the 768-token ceiling before completing the answer and recommended further tuning without evidence; all three uncertainty turns invented rollback/data-safety and duration claims; buying guidance remained generic. Relevant Memory use passed and irrelevant/absent/stale/partial counterfactuals stayed contained. Stage 13 therefore retains the pre-retrieval Memory Gate and typed decision field, rejects the v6 decision wording, and does not advance 14B to full-stack or daily promotion.
- The corrected v7 practical-utility wording then received its own three-run 14B raw replay rather than being credited from tests alone. All 39 requests completed normally and the requested model recommendation appeared in 3/3 runs, proving that the wording removed the v6 truncation/non-decision failure. The arm still fails the Practical Utility Gate: 3/3 decision replies invent current validation and cost/effect claims; 3/3 migration replies invent decision-critical loss/rollback/downtime facts; 3/3 buying replies remain generic; and 3/3 “save tonight” replies give no time-boxed deliverable and repeat unwanted reassurance. Report hashes are `988971e0c40d8068058f54a36008edf888441a41ef5ce55b13c383d50cb66e33`, `e1c432325e023f54e7c4c07d94321a1e15cb0468c3b60d580d6b5e8116210ebb`, and `5867d0c0e023f2b75e8b31aced892d6e67fdf8c034f970740be23d6da5836e37`; proposal-only semantic review file SHA-256 is `563c84d4bf3ba5103c8f2f39916e9ec1cfc067793f07b182b065976d3493fe10`. V7's pre-retrieval gate and decision guidance remain useful architecture, but neither 14B nor v7 wording is sufficient quality evidence.
- The Stage 13 Practical Utility Gate now makes “would the owner actually use this instead of redoing it in a generic chat product?” a non-averagable acceptance condition. Workstation feasibility records Ryzen 9 7945HX, 31.2 GB RAM, RTX 5070 Ti Laptop 12,227 MiB, driver 573.22, and 126.6 GB free on D:. A hash-pinned 20,419,565,568-byte Qwen3.6-35B-A3B Q4_K_M candidate is prepared for the existing isolated llama.cpp path. FreeToken remains deferred because its documented R580+ requirement would require a driver/system change and current upstream issue reports identify native-Windows RTX 50/Qwen3.6 risks.
- The owner-authorized exact 35B artifact transfer is resumable and currently incomplete, so the candidate remains unverified and unrun. The daily runtime was restored after the 14B v7 arm and is ready on the exact unadapted Qwen3-8B model with `adapter_version_id=null`; no 35B, 14B, or FreeToken route is active.
- On 2026-09-03 the Product Owner authorized the direct ChatGPT MCP route.
  ADR-0028 and Stage 14A add an official-SDK 2.1.1 local STDIO server with
  exact owner-approved PUBLIC Identity and deterministic current-message Turn
  Contract tools. Both tools are read-only/closed-world and explicitly return
  that no private HAVRE history, durable write, or OA70 material is present.
  The server is registered as `havre-companion` in the owner host's shared
  ChatGPT desktop/Codex MCP configuration with no credential. Focused protocol
  and planner verification is 17/17, including a real spawned STDIO transport.
  Fresh-database repository verification is 592/592 primary plus 62/62 pinned
  Torch (654/654 combined), zero skipped, with clean dependency/compile/schema
  checks and provenance audit `[]`.
  ChatGPT's final response on this Stage 14A control still remains outside HAVRE.
- Later on 2026-09-03 the Product Owner authorized ADR-0029 and removed the
  daily Strong Brain distinction. Stage 14B adds a no-API-key
  `openai-codex-chatgpt` provider using the authenticated Codex CLI. Ordinary
  PUBLIC/NORMAL chat now follows the normal ResponsePlan, relevant
  conversation/Memory, ContextPack, request binding, Core, durable assistant
  Event, feedback, and episode path. The isolated provider uses stdin, an empty
  ephemeral read-only workspace, a minimized environment, and no tools. A real
  PUBLIC synthetic call returned a captured GPT-5.6-sol reply and measured
  10,818 input plus 17 output tokens. PRIVATE, HIGHLY_PRIVATE, LOCAL_ONLY, OA70,
  training, automatic Memory mutation, and GPT-authored proactive delivery
  remain blocked. Focused/static verification passed 4/4 and 9/9; complete
  repository verification passed 597/597 primary plus 62/62 pinned Torch tests
  (659/659 combined), zero skipped, with clean schema/dependency/compile/diff
  checks and provenance audit `[]`. The owner desktop was then safely restarted:
  readiness returned `ready`, live version reported
  `openai-codex-chatgpt` / `gpt-5.6-sol` with no adapter, and the protected
  product settings reported GPT as the default while Local default was false.
  Exact implementation evidence is in
  [STAGE14B_DEFAULT_CHATGPT_REPLY_CHECKPOINT.md](STAGE14B_DEFAULT_CHATGPT_REPLY_CHECKPOINT.md).
- The Product Owner then clarified that LOCAL_ONLY must have an eligible local
  Replyer and explicitly selected the unadapted Qwen3-8B. ADR-0030 accepts the
  narrow dual-route target: cloud-eligible PUBLIC/NORMAL remains on GPT-5.6-sol;
  cloud-ineligible PUBLIC/NORMAL and PRIVATE/HIGHLY_PRIVATE/LOCAL_ONLY use the
  exact attested local Stage 3 Qwen artifact with no adapter. This is an
  owner-local operational route, not model promotion or private cloud
  declassification. The earlier 659/659 GPT-route result and historical Stage 3
  local evidence did not prove the combined route; renewed implementation and
  evidence are now recorded in
  [STAGE14B_DUAL_PROVIDER_ROUTING_CHECKPOINT.md](STAGE14B_DUAL_PROVIDER_ROUTING_CHECKPOINT.md).
- The ADR-0030 composition passed 633/633 primary PostgreSQL-backed tests and
  62/62 pinned Torch tests (695/695 combined), all with zero skips; focused
  PostgreSQL/API evidence passed 110/110, the migration runner passed 5/5, a
  populated upgrade passed, generated schemas and static/dependency checks were
  clean, and the disposable-database provenance audit returned `[]`. Migrations
  `0052` and `0053` bind every ordinary interaction to one canonical terminal
  assistant-or-failure lineage while preserving the exact privileged source-
  erasure tombstone transition. The owner runtime is active and `/health/ready`
  reports migration head `0053`. Synthetic NORMAL request
  `01a066de-8a89-7665-9199-3fc91e65cf27` completed through
  `openai-codex-chatgpt` / `gpt-5.6-sol` with adapter null and reported 11,824
  prompt plus 7 output tokens. Synthetic LOCAL_ONLY request
  `01a066de-f578-73fc-8d0a-7b4ad16252e6` completed through the exact base Qwen
  artifact `sha256:d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785`
  with adapter null, current process attestation, and 755 prompt plus 4 output
  tokens. Protected settings hide Strong Brain and declare no silent fallback.
  These facts prove routing, isolation, lineage, and live execution, not practical
  conversation quality.
- The first fresh-browser owner check exposed an authentication UX defect rather
  than a provider failure: opening the bare loopback `/chat` URL without the
  launcher's one-time owner bootstrap correctly produced HTTP 401, but the Web UI
  stayed on "confirming reply engine" and offered an unusable pairing path. Web
  shell `dual-route-v5` now distinguishes loopback owner-session absence from a
  remote unpaired device, shows persistent launcher guidance, and disables the
  composer instead of pretending to load. The launcher-opened page completed the
  bootstrap redirect and then received authenticated settings/timeline responses.
  Executable PWA and focused static contract tests pass; this correction does not
  weaken or bypass owner authentication.
- A post-activation owner screenshot reproduced two residual defects without changing the accepted architecture: correction text was being echoed because the rejected wording appeared repeatedly in provider-facing Context, and manual Strong reused Local's 256-token output reserve despite thinking/high sharing reasoning and final-answer tokens. `context-presentation-v4-silent-owner-corrections` now neutralizes only provider-facing rejected turns while preserving raw Events and exact source refs; manual Strong reserves the already-evidenced 4096 output tokens and records empty final content as a typed, content-free failure. A local-only synthetic 9201 probe did not echo the phrase. Fresh-database verification is 558/558 primary plus 62/62 pinned Torch, with zero skipped and provenance audit `[]`; no owner DeepSeek request was replayed automatically.
- Restart validation also restored the exact already-applied 0051 migration bytes at SHA-256 `4670029dda2b01cafb4c34105f4af3706c53ea7a249660aa286b12df9e3104f0`. The owner migration row and checksum runner were not changed; reapplication returned `applied: []`.

- On 2026-08-27 the Product Owner selected Tailscale Serve as the private
  cross-device HTTPS boundary and authorized additive governed external Web
  Push with generic-only previews. ADR-0023 and migrations 0043 through 0048
  implement and close the durable post-SEND_NOW dispatch, retry, erasure,
  export, and exact-shell physical-validation boundary. A fresh v5 delivery
  received a provider receipt and was confirmed from the locked iPhone through
  tap-to-same-timeline-message without restart. Exact evidence is in
  [PRIVATE_CROSS_DEVICE_WEB_PUSH_CHECKPOINT.md](PRIVATE_CROSS_DEVICE_WEB_PUSH_CHECKPOINT.md).

- On 2026-08-27 the Product Owner authorized completion of automatic proactive
  triggering, removal of cooldown/quiet hours, and the exact generic Push
  exception for LOCAL_ONLY source messages. ADR-0024 and additive migrations
  0049-0050 implement immutable source-bound evaluation for explicit reminders,
  current Goal reviews, and planned Scene starts; stale Goal/Scene work cancels
  before proposal execution. Memory, Calendar/Life Context, Current State,
  beliefs, ordinary chat, and silence have no independent trigger authority.
  Owner preference revision 15 is active; the historical scan ignored all 32
  eligible prior Events and created zero automatic work. The exact non-Torch
  suite passed 599/599 with zero skips, and provenance/FK audits returned `[]`.
  Exact implementation, activation, and remaining physical evidence are in
  [AUTOMATIC_PROACTIVE_REACH_OUT_CHECKPOINT.md](AUTOMATIC_PROACTIVE_REACH_OUT_CHECKPOINT.md).

## What exists now

- A public-safe deterministic showcase runner using a random synthetic owner and
  a dedicated loopback-only havre_showcase_ database. It demonstrates durable
  interaction/history, reviewed Memory, gated retrieval/ContextPack, response,
  feedback/edit lineage, exact episode membership, and a zero-violation
  provenance audit. This is wiring and persistence evidence, not model-quality
  or production evidence.

- The owner-local Daily Companion exposes proposed Memory, confirmed Memory,
  User Model, Goals, Current State, and patterns as friendly review groups without
  hashes, scores, raw JSON, or implementation labels. Course assignment/exam Goals
  are grouped by course and explicit non-course Goals remain separate. Diary v5
  creates a coherent first-person summary only from eligible GPT-routed day Events
  at the fixed 05:00 worker schedule and keeps private/local transcripts in a
  separate collapsed local box.
  Month headings use distinct contrast-checked colors. Mobile cards and navigation
  are contained to the effective visual viewport, while assistant paragraph bubbles
  remain one durable Event.

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
- A default-disabled, experiment-only DeepSeek cloud adapter behind that same contract. It is eligible only for exact owner-authorized PUBLIC synthetic fixtures and cannot receive LOCAL_ONLY/private/unknown data or enter daily routing.
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
- The daily Web product at `/chat` provides durability-gated response streaming, continuous conversation history, thumbs feedback, owner-edited alternatives, reason labels, a review pool, explicit response-length preference, accepted Memory inspection, episode summaries, and episode-suggestion review. Current turns enter `interaction-orchestrator-v9`; its pre-retrieval `response-planner-v2` and `context-builder-v12` preserve exact user/assistant roles and Event provenance. Gated Memory is budgeted before optional older history while recent conversation retains a bounded reservation; the versioned provider presentation preserves all source references and never requires a callback. PostgreSQL migration `0036_owner_feedback_personalization.sql` adds the records; corrective `0037_daily_learning_canonical_hash_guards.sql` makes session closure terminal at service and direct-SQL boundaries, binds conservative summary/suggestion DataPolicy, reconstructs canonical hashes and complete same-session membership at commit, rejects training approval while Stage 9B is inactive, preserves export/erasure/replay closure, and fails closed rather than rewriting pre-correction episode evidence. Feedback/review/episode contracts are exported as JSON Schema.
- Stage 9 closeout verification used fresh database `havre_stage9_closeout_rerun_20260821`, migrated through `0001`-`0032`, and the two pinned runtime environments: **343 passed, 0 failed, 0 skipped**; Stage 9 FK/catalog and full provenance audits both returned `[]`; both `pip check` runs, bytecode compilation, and the exact registry consumer passed against the unchanged immutable registry artifact. No migration or active contract schema changed.
- Additive migrations `0033_stage10_deployment_reliability.sql` and `0034_stage10_backup_fk_index.sql` implement immutable release/approval/deployment, backup/replay, owner-export, role, and exact FK-index boundaries. Stage 10 adds HTTPS/deployment manifests, health/version/metrics quarantine, exact image/source/component binding, least-privilege offline operations, backup/restore, deletion replay, and explicit release/rollback workflows. Exact evidence and limitations are in [`STAGE10_CHECKPOINT.md`](STAGE10_CHECKPOINT.md).

## What does not exist

- No general automated User Model inference or confidence algorithm, free-running Scene sensing, user-derived training run, approved personalized adapter, or personalized release. ADR-0034 permits only exact-quote GPT-source Memory/belief delegation under its fixed authorization and guards; every private/local source remains owner-reviewed. Stage 7 reflection/consolidation remains deterministic and proposal-only. Stage 9A real transformer training used repository-owned synthetic/public-safe data only and does not establish personal or real-world benefit.
- Daily conversation now admits exact recent owner response corrections and reason-text feedback into later Context Packs as source-bound response constraints. This improves short-term adaptation but does not create or accept a durable User Model belief, Pattern, Current State, or Memory.
- No approved production conversational release. The Stage 3 self-hosted model remains a candidate baseline and Seed 9201 is available only as an owner-local development fixture; neither establishes production, personalized, structured-output, or broad conversation quality.
- No always-on Reach Out exists when the owner PC sleeps, shuts down, loses
  Tailscale, or stops the backend/worker. The current real-device Web Push path
  is private and active only while those components are online; Reach Out is
  owner-disabled after acceptance.
- No Stage 12B source, Windows sensing agent, iPhone sensing, ambient voice,
  location, mobility, or wearable connector exists. The only real external
  Context Source is the accepted owner-local Stage 12A manual ICS projection;
  it is LOCAL_ONLY, file-copy false, network false, and not Memory.
- No public production Web client, native iPhone client, voice, or tool use.
  The responsive PWA is private tailnet-only. Stage 10's infrastructure-only
  Docker deployment activates no behavioral release and contains no promoted
  adapter.
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
cluster at `C:/HAVRE/var/postgres` on `127.0.0.1:55432`, with pgvector
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
`/home/OWNER/.local/share/havre/postgres18-stage3`. That is historical runtime
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
- Stage 14B's green routing, privacy, persistence, and live synthetic evidence does
  not establish that either branch is pleasant or useful across real multi-turn
  owner conversation. The GPT alias, account limits, retention, availability, and
  latency remain external; the local 8B branch is expected to be materially weaker
  and remains unpromoted. Repeated owner use is still the Practical Utility Gate.
- OA70 cases 1-70 are prompt-exposed under ADR-0031 plus ADR-0035's explicit
  implementation authorization. They may calibrate runtime behavior but cannot
  provide independent evaluation evidence for that runtime; none of the original
  70 cases may be reported as a clean holdout.
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

Use the technically verified owner-local dual Replyer and evaluate representative
real conversations against the Practical Utility Gate: complete intent coverage,
appropriate length, natural relevant-Memory use, no fabricated familiarity, less
owner correction/restatement, and an answer the owner would actually use. Observe
ADR-0036's newly active bounded cadence on future real eligible turns and explicitly
review wording, timing, annoyance risk, and no-action choices. Record poor turns with their exact
ContextPack, selected route, raw response, Core decision, and delivered Event
before changing prompts, orchestration, or models. Technical activation does not
itself close either owner-value gate.

Keep Seed 9201 as immutable rejected history and the incomplete 35B transfer as
optional Stage 13C evidence rather than a prerequisite. Feedback and edits stay
non-training-eligible. Stop before any PRIVATE/HIGHLY_PRIVATE/LOCAL_ONLY cloud
admission, automatic sensitivity classifier, silent cross-provider failure
fallback, OA70 training/tuning/public release or use outside ADR-0035's exact
owner-only bank, raw private-chat cloud review, a second delayed cloud planning
call or expansion beyond ADR-0036's exact cadence/categories, proactive delivery
outside the exact governed categories, driver/system
change, training, Stage 9B, model promotion or
deployment, public exposure, automatic Memory/User Model mutation outside
ADR-0034's exact GPT-source delegation, paired-device administration/erasure, or
the separate always-on Core hosting/privacy decision.
