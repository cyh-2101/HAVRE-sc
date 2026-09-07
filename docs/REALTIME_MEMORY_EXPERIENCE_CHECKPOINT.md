# Real-time Memory and five-to-five Diary correction

Date: 2026-09-04. Scope: the owner's explicit Memory/experience repair, not a new
stage, identity release, privacy declassification, or training authorization.
ADR-0037 records implementation authorization; formal acceptance remains open.

## Implemented behavior

- Eligible completed GPT chat pairs atomically enqueue real-time understanding.
  A separate worker task leases up to four pairs and calls GPT-5.6-sol/high.
  Parsing, exact-source validation, delegated writes, and fenced job completion
  are independent of the daily schedule. Empty understanding is legitimate;
  invalid generated understanding is a retryable failure, not successful empty
  Memory. Errors back off at 1m/5m/15m/1h/6h; no Qwen fallback is introduced.
- Private/local conversation never enters that GPT path. Long local narratives
  may become owner-review candidates, never automatically accepted beliefs.
- Diary v6 uses the half-open previous local 05:00 to current local 05:00 window,
  with the configured America/Chicago timezone and DST-aware dates. GET requests
  only read. Daily review may catch missed understanding, but is not the normal
  first opportunity to remember a turn. The PC/backend must be online.
- GPT-authored improvement suggestions are source-bound Markdown under
  `owner_improvement_reviews`; they cannot edit code, Identity, or policy.
- Local semantic retrieval combines semantic similarity, lexical overlap,
  recency, and importance. Existing memories and old vectors remain intact.
  Age affects ranking, not database deletion or a claim that HAVRE has forgotten.
- Explicit references to earlier chats can add at most 16 source-qualified,
  already GPT-authorized events from a seven-day/256-event search window to
  recent context. Recorded local timestamps and nearby clarifications reach the
  model. Private/local sources are excluded before encoding in this extra path.
- User Model remains source-backed, revisable structured beliefs, not training
  model weights. The delegated extractor can add explicit stable statements and
  supported patterns. It does not automatically revise an existing belief key;
  broader contradiction/reconciliation behavior is not claimed complete.
- PWA v12 rejects stale timeline fetches, preserves optimistic turns until the
  confirmed timeline is available, reuses unchanged message rows, and restores
  scroll positioning before paint. Notifications focus the existing app before
  waiting for its acknowledgement. Only versioned public shell assets use
  cache-first behavior; personal API data is not service-worker cached. The
  existing two-second message pacing is unchanged.

## Versions and migrations

- Encoder: `embedding-minilm-multilingual-int8-v1`, 384 dimensions, ONNX CPU.
  Model: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, immutable
  revision `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`. Checked artifact hashes are
  enforced at startup; no runtime network or chat-text cache.
- Retrieval: `retrieval-r2-hybrid-v1`; ResponsePlanner v4; ContextBuilder v15;
  presentation v11; supplementary recall `conversation-recall-semantic-time-v1`.
- Understanding prompt: `gpt-owner-review-important-experiences-v2`;
  real-time purpose `memory_intelligence`; Diary `gpt-owner-five-am-diary-v6`.
- 0064 adds exact-source registered-dimension embedding guards and hybrid binding.
  0065 closes nullable hybrid thresholds. 0066 adds exact-pair real-time jobs,
  fenced lifecycle, typed ledger run kinds, and five-hour window metadata.
  0067 binds Diary source membership to v6's date semantics. Applied migration
  bytes were never rewritten.
- The source-qualified intelligence ledger is shared intentionally; historical
  table names do not mean real-time work depends on the daily schedule.

## Verification

- Complete primary suite: 722 tests, zero failures/skips. The separate pinned
  Torch environment: 62 tests, zero failures/skips; 784 combined. Commands and
  outputs are retained locally in `var/semantic-memory-primary-tests.log` and
  `var/semantic-memory-torch-tests.log`.
- Dedicated test target: `havre_memory_v2_test_20260904`. Initial fresh 0001-0064
  was followed by populated incremental 0065-0067. An additional empty dedicated
  `havre_memory_final_fresh_20260904` verified all 67 migrations from scratch.
- Direct SQL coverage includes exact owner/source pair, private exclusion,
  dimension and source-hash binding, non-null admission values, and source
  erasure. Worker tests cover concurrency, backoff, late-result suppression after
  erasure, no real-time Diary effect, and 04:59 inclusion versus 05:00 exclusion.
- `export_contract_schemas`, `pip check`, `compileall`, Node PWA contract checks,
  and provenance audit passed. Test and fresh-install provenance results: `[]`.
- The checked-in legacy PostgreSQL retrieval benchmark also ran. The new local
  synthetic paraphrase probe has only 12 cases: baseline 4/12 versus semantic
  9/12, specifically 5/8 positive matches and 4/4 correct distractor abstentions.
  It still misses three paraphrases; these figures are not an owner-quality
  acceptance rate. Query encoding/ranking median was about 2.4ms, not API latency.
- A read-only replay of the real explicit morning-history question admitted 32
  history sections (recent plus recalled), including the complete 558-character
  story and recorded timestamps. Estimated input was 4,855 of 13,312 available
  tokens. This proves model-input availability, not a guaranteed good reply.

## Owner-local operation and live correction

Production target was verified as `havre_local_20260822`, with no nonterminal
interaction before restart. The checked-in owned-process stop/start path applied
0064-0067 and added eight exact current-revision semantic vectors. Both old vectors
and the owner's retracted record were preserved. The runtime reports semantic
retrieval, real-time generation enabled, and the five-to-five Diary window.

Exactly three user-requested early-morning turns were queued for bounded repair;
no blanket history backfill was performed. The first real GPT-high run completed
but yielded zero Memory and one supported User Model update. A separate read-only
probe reproduced why: its experience quote was all 558 characters, violating the
500-character contract. This prompted the strict real-time parsing/quote-limit fix
and regression tests; the original run and completed receipts remain immutable.

The corrected prior-window GPT-high review completed as
`01a06e87-da0e-7914-b2cf-c9f17b549ae5`, created three actual Memory records, and wrote
five suggestions in the registered source-bound review file. Its long-experience
record is linked to the selected original source, preserves uncertainty, and does
not infer the other person's intent. This one-off repair had outreach disabled.
No private transcript was supplied to GPT; no production source was erased.

After the final prompt/validation restart, authenticated Memory and Diary endpoints
returned HTTP 200; provider readiness and both runtime stderr logs were healthy.
Production and final disposable provenance audits returned `[]`. The final primary
suite completed in 78.583 seconds. Both exact disposable databases were removed
after verifying no active connections; production and the previously running
PostgreSQL service were preserved. Test fixtures can recreate the disposable data.

## Limits and handoff

Semantic candidate search is bounded and the encoder truncates at 128 tokens;
long-document chunking and comprehensive human-like recall are not implemented.
GPT output quality still varies; exact quote checking is not a proof that every
interpretation is correct. Repeated owner experience, existing-belief reconciliation,
and physical iPhone lockscreen/opening latency remain unverified. Browser automation
could not initialize in this environment, so no visual/device audit is claimed.

No commit, push, public deployment, new source erasure, or broader contact cadence
was performed. A refreshed iPhone app can exercise v12; owner feedback, not a
synthetic test score, is the remaining companion-quality acceptance boundary.
