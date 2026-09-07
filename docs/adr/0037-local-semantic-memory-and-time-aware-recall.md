# ADR-0037: Real-time understanding, local semantic Memory, and five-to-five Diary

- Status: implementation authorized by the owner's 2026-09-04 request to review
  HAVRE chats and improve Memory; formal acceptance pending.
- Scope: Stage 13B memory/context repair and existing Stage 15 daily intelligence.

## Observed problem

The hash encoder cannot reliably connect Chinese paraphrases. A 16-event recent
window loses earlier same-day conversations. Cross-session fallback previously
ran only for an empty current session and selected the last six events without
topic relevance. Provider-visible history omitted its recorded timestamps, so a
short completion statement could be attached to an hours-old meal conversation.

## Decision

Use a pinned, checksum-verified multilingual MiniLM ONNX CPU encoder, loaded from
owner-local files without runtime networking, text caches, or remote model code.
Its 384-dimensional vectors coexist with historical 64-dimensional vectors in
the existing source-qualified embedding table. Migration 0064 validates both
registered dimension and exact source revision content hash. Reindexing adds
vectors without changing source Events, accepted memories, beliefs, or statuses.

The new retrieval-r2-hybrid-v1 uses semantic candidate search plus Chinese
bigram/Latin-token overlap in ranking. Rank weights are .70 semantic, .15 lexical,
.10 recency, .05 importance. Admission requires cosine >= .45, or cosine >= .20
with lexical overlap >= .25. Both the result contract and ContextBuilder repeat
this condition. Duplicate suppression requires .92 similarity and .80 lexical
overlap; equal content hashes are always duplicates. Thresholds are conservative
engineering choices for this version, not psychological confidence estimates.

ResponsePlanner v4 permits optional retrieval for substantive turns; acknowledgments
and greetings retain no-retrieval behavior. The old planner and encoder remain
available for historical tests and comparison. Current Memory validity dates are
enforced, and the existing privacy, owner, provenance, and erasure paths remain
authoritative. Qualified User Model and Goal selection use the same local semantic
and lexical criteria when configured.

On explicit references to prior conversation, supplementary recall reads at most
256 completed events from seven days, filtered BEFORE encoding to PUBLIC/NORMAL,
cloud_eligible, memory_eligible, and an already recorded GPT cloud route. It
selects topic or explicit owner-local time windows and nearby corrections, adding
at most 16 events to recent context. It excludes all private/local sources from
this supplementary path; existing private current-session context stays on the
original local route. All admitted Events keep their exact IDs and policies in
ContextPack. No summary, new enduring trait, or new contact permission is created.

ContextBuilder v15 includes owner-local recorded timestamps and preserves token
accounting. Provider guidance prioritizes current time and later owner corrections.
Daily delegated Memory checks existing heads and rejected candidates so unchanged
statements do not duplicate or resurrect an owner's rejection/retraction.

## Real-time understanding is not the daily review

The owner's clarification on 2026-09-04 separates these workflows. A completed
eligible GPT turn atomically queues an exact owner/user/assistant source pair.
The worker leases at most four pairs, calls the isolated GPT-high provider with
the `memory_intelligence` purpose, validates exact owner quotes, and commits the
understanding run, delegated updates, and completed jobs in one fenced transaction.
Retries back off; expiry permits recovery; erasure during generation prevents a
late write. No alternate provider receives the work on failure. Empty updates are
valid: ordinary chat is not automatically a durable belief.

A real GPT probe found an overlong exact source quote was being dropped by the
shared optional-effect sanitizer. Prompt v2 explicitly bounds quotes to 2-500
characters and statements to 3-500. Real-time parsing now fails/retries on invalid
understanding shape or nonexact sources; this differs from the historical daily
review's optional-effect tolerance. The prompt version participates in the source
fingerprint so corrected inference is not treated as the old cached result.

The existing source-qualified intelligence ledger is shared, with explicit
`run_kind` rather than a second competing provenance system. Migration 0066
independently guards source privacy, exact completed GPT route, leases, and
real-time runs' prohibition on Diary, review-file, and contact side effects.
Realtime, daily review, and continuation use separate bounded worker tasks so
long GPT calls do not block the main reminder/heartbeat loop.

Important one-off experiences can become episodic Memory without being promoted
to a personality claim. Source-quoted stable User Model statements use existing
owner delegation. Existing belief keys are not automatically revised by this
extractor; contradiction/revision machinery still requires its governed path.
For non-cloud/private chat, local narrative extraction creates only an owner-review
candidate. There is no private GPT transfer or silent acceptance.

At 05:00 owner-local time, Diary v6 summarizes the half-open interval from the
previous local 05:00 to this local 05:00. Calendar dates are computed in the named
timezone, including DST, not by assuming a fixed 24-hour UTC interval. Migration
0067 binds Diary source dates to that method; historical v5 revisions preserve
their midnight-based meaning. The daily result may add supported understanding,
but is no longer the first or only opportunity to remember a conversation. It
writes evidence-bound improvement suggestions for manual Codex work, not code.

## Operations and evidence

Install `requirements-memory.lock`, run `python -m scripts.fetch_memory_encoder`,
apply additive migrations, and run `python -m scripts.reindex_memories` with the
explicit owner/database before activating `HAVRE_MEMORY_ENCODER_ROOT`. Missing or
modified weights fail startup rather than silently returning to hash retrieval.
No private chat is uploaded to obtain embeddings. The official model is Apache-2.0:
https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
revision e8f8c211226b894fcb81acc59f3b34ba3efd5f42; quantized ONNX plus tokenizer is
approximately 128 MB on disk. Offline CPU inference guidance:
https://www.sbert.net/docs/sentence_transformer/usage/efficiency.html

Required evidence: Chinese paraphrase/distractor benchmark; source/owner/privacy,
same-day recall, timestamp, correction, validity and rejection regressions; direct
SQL dimension/hash attacks; populated upgrade with old-vector preservation; full
PostgreSQL suite, schema exports, and provenance audit. No new training, automatic
code editing, privacy declassification, broad contact cadence, or model promotion.
