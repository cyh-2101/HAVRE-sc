# Practical Companion UX and Reviewed Understanding Checkpoint

Date: **2026-09-03**

Decision: **ADR-0033 is implemented and owner-locally active by explicit task
direction; formal ADR acceptance remains pending. This is technical and production-
path evidence, not proof that the Practical Utility Gate or physical-iPhone acceptance
has passed.**

## Implemented slice

- Web-originated automatic Memory proposals now admit only explicit stable
  owner-authored statements and suppress governance/import/hash/queue mechanics.
- The owner can edit a Memory proposal before acceptance without rewriting the
  immutable candidate; unchanged rejected repeats become duplicate outcomes.
- A confirmed Memory can propose a separately reviewed candidate User Model belief
  with exact Memory-revision evidence. No belief activates automatically.
- Diary method `curated-owner-day-diary-v3` selects meaningful owner-authored life
  facts, keeps only the sources that informed the summary, and excludes technical
  authorization/import/provenance chatter.
- ResponsePlan asks for one compact answer by default, uses two or three parts only
  when useful, and permits at most one helpful question. Paragraph bubbles are a
  presentation-only split of one durable assistant Event.
- The mobile shell tracks the effective visual viewport, contains long text and raw
  technical details, preserves safe-area spacing, and keeps technical details
  collapsed by default.
- Memory, proposed Memory, User Model, Goals, current state, and pattern proposals are
  separate review groups. Paired-device persistent mutation remains closed.

## Persistence and migration

- Additive migration: `0056_curated_owner_diary_v3.sql`.
- Historical Diary v1/v2 rows and all source Events remain immutable.
- Production migration head after activation:
  `0056_curated_owner_diary_v3.sql`.
- No source Event was selected or erased. Stage 15 source-erasure authority therefore
  performed no deletion in this work.

## Verification

### Automated

- Final unified PostgreSQL-backed suite: **730/730 passed, 0 failed, 0 errors,
  0 skipped** in 127.564 seconds. The run used the main project environment with the
  existing pinned Stage 9A Torch site-packages added to Python's import path.
- A preceding plain-main-environment run executed 730 tests and exposed only ten
  `ModuleNotFoundError: torch` environment errors; all 62 Stage 9A tests passed in the
  existing pinned Torch environment before the unified zero-error run.
- Focused non-database UX/Memory/Diary/ResponsePlan set: **49/49 passed**.
- Focused PostgreSQL integration set: **5/5 passed**.
- Executable PWA v5 JavaScript contract: passed.
- Provenance audit against the migrated disposable database: `[]`.
- `pip check`: no broken requirements.
- Full Python bytecode compilation: passed.
- Contract schema export and `git diff --check`: passed; only existing Windows
  line-ending warnings were reported.
- The dedicated test database `havre_practical_ux_20260903` was verified as distinct
  from production and removed after the run.

### Production readback

- `/health/ready`: `ready`; failed Memory/proactive/offline jobs: `0/0/0`.
- API PID after final restart: `46428`; worker PID: `16672`.
- Default cloud-eligible Replyer: `openai-codex-chatgpt` / `gpt-5.6-sol`, adapter
  `null`.
- Private route: exact unadapted
  `model-qwen3-8b-gguf-q4-k-m-7c41481f`, artifact
  `sha256:d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785`,
  adapter `null`.
- Product aggregate: two confirmed Memories, zero visible pending Memory candidates,
  twenty append-preserved low-value candidates suppressed, zero User Model beliefs,
  and fifty Goals.
- Current Diary v3 pages are dated 2026-09-03, 2026-08-27, and 2026-08-24. Their
  titles are owner-life content rather than the prior authorization/import trace.

### Final inference-path evidence

- Cloud request `01a06985-f953-78d0-8a6b-94ec9a0c482f` completed through GPT-5.6-sol
  and was bound to ContextPack `01a06985-f97b-7f6f-989f-7210d78db259`, whose admitted
  sections included three exact `behavior_example` sources from
  `owner-example-bank-oa70-first20-v1`.
- LOCAL_ONLY request `01a06987-6295-7e76-ace4-159c85cf91a6` completed through the
  exact Qwen artifact above with adapter `null`, runtime attestation
  `stage3-runtime:38900:1788473118492567`, and ContextPack
  `01a06987-62bb-7029-a7f8-2a235893098d`.
- This proves the exact ContextPack bound to each final inference attempt and the
  selected provider/version. It is not an independent capture of provider transport
  bytes and does not by itself prove subjective conversation quality.

## Mobile production evidence

Authenticated headless Chrome rendered the production owner page at 390 x 844:

| Surface | document client/scroll width | bottom navigation | auth |
|---|---:|---|---|
| Chat | `390 / 390` | left `0`, right `390`, bottom `844` | owner session |
| Memory | `390 / 390` | left `0`, right `390`, bottom `844` | owner session |
| Diary | `390 / 390` | left `0`, right `390`, bottom `843.39` | owner session |

Evidence files are owner-local under
`.runtime/desktop/diagnostics/ux-audit-20260903/03-postfix-chat-390x844.png`,
`04-postfix-memory-390x844.png`, and `05-postfix-diary-390x844.png`.

This proves production-browser geometry and rendered content at the target viewport.
The JavaScript contract separately exercises a reduced visual viewport and textarea
growth. It does **not** replace a physical Safari/PWA keyboard, safe-area, rotation,
or lock-screen test on the owner's iPhone.

## Remaining gates

1. The owner must judge real conversation usefulness over repeated ordinary use; the
   Practical Utility Gate remains open.
2. Formal ADR-0033 acceptance remains open.
3. Physical iPhone Safari/PWA evidence remains open.
4. Paired iPhone sessions remain read-only for Memory/User Model review. Enabling
   candidate accept/reject/edit, confirmed-Memory correction/retraction, or candidate
   belief activation/invalidation requires an exact new Product Owner authorization.
5. No source-erasure operation may run until the owner explicitly supplies the exact
   source Event.

No commit, push, pull request, training, promotion, source erasure, or paired-device
write expansion was performed.
