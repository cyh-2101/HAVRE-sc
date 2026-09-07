# Conversation-stack baseline checkpoint

- Date: 2026-09-02
- Status: **implementation and diagnostic checkpoint; not conversation-quality acceptance**
- Governing decision: [ADR-0026](adr/0026-retire-seed-9201-and-evaluate-conversation-stack.md)
- Evaluation authority: [EVALUATION_PLAN.md](EVALUATION_PLAN.md#32a-conversation-quality-calibration-and-candidate-comparison)

## Decision and current runtime boundary

The Product Owner rejected Seed 9201 as the daily product direction. The adapter,
registry record, raw generations, and historical evidence were not deleted or
rewritten. The owner-local desktop launcher now targets the exact Stage 3
Qwen3-8B GGUF baseline with `active_adapter_version_id = null`. This is a
diagnostic fallback, not an accepted replacement.

The activated owner-local runtime was checked after the switch:

- provider: `self-hosted-openai-compatible`;
- model version: `model-qwen3-8b-gguf-q4-k-m-7c41481f`;
- active adapter: `null`;
- API readiness: `ready`;
- serving boundary: loopback-only and request-log-disabled;
- Daily Companion, database, worker, and existing Tailscale Serve boundary: live.

No training, promotion, deployment, automatic model routing, private-cloud review,
or lifecycle mutation was performed.

## Implemented conversation slice

`response-planner-v1` creates a typed, immutable, content-hash-bound plan for each
turn. The plan records:

- Talk/Guide/Prepare/Reflect mode;
- distinct current-turn questions, requests, decisions, and context obligations;
- Memory need/query;
- brief/balanced/detailed depth;
- warm, warm-firm, direct, or analytical stance;
- uncertainty and exact source references.

`context-builder-v11` and
`context-presentation-v5-response-plan` carry the exact plan into the final
provider messages. The instruction explicitly prioritizes complete meaning over
forced shortness, requires all distinct requests to be covered naturally, and
forbids invented or forced Memory callbacks. Provider-request metadata preserves
the planner version/hash/mode/depth/Memory decision.

The plan renderer treats obligation text as escaped, untrusted current-user data
at its original priority. It explicitly denies any elevation to system/developer
policy, hidden-context authority, tool authorization, or disclosure permission.

Two defects found during calibration were corrected before acceptance claims:

- present-tense words such as “目前/当前” and bare “我们” no longer falsely mark
  long-term Memory as required;
- Chinese comma-linked requests using “再说/最后/接着” remain distinct response
  obligations.

This slice improves observability and intent coverage. It does not prove natural
language quality and does not yet implement a separate pre-retrieval Memory Broker;
the existing retrieval and Context admission path remains authoritative.

## Conversation-quality calibration

`conversation-quality-calibration-v1` is a PUBLIC synthetic, training-ineligible
13-case suite. It covers all four modes, multi-request completeness, correction,
verbosity fit, long-context continuity, and a five-way same-message Memory
counterfactual (`relevant`, `irrelevant`, `absent`, `stale_conflicting`, `partial`).

The raw-candidate collector accepts only PUBLIC non-user fixtures, fixes identity,
Response Plan, prompt messages, Memory text, and sampling settings, and writes only
under ignored `.runtime/evaluations`. Each row preserves prompt hash, raw output,
latency, token usage, and surface diagnostics. It is explicitly not an end-to-end
retrieval/Core acceptance run.

The first draft used the ambiguous phrase “体感差”; Qwen3-8B reasonably interpreted
it as bodily sensation. That output was not counted as a valid model failure. A
later code review found a second evaluator defect: synthetic admitted Memory was
placed in provider messages without a corresponding RetrievalResult signal, so
the Response Plan simultaneously said that no Memory existed. Both earlier arms
and their semantic reviews are preserved as superseded diagnostics, not candidate
evidence. The fixture wording and Memory signal were corrected and the entire arm
was rerun twice.

### Final secured Qwen3-8B raw baseline

- report hashes: `sha256:518bc6ea42d9d20502481b57c0032b45f4747b6e8c2edbb3ea13f2b3cbd13f86`, `sha256:77aff7c8f9d32adb2034b2ce2eec10bd506f5aa950953854013b09df62958c27`, and `sha256:a042d9e15e43f097464d0d4190cd4c9dea867deb117e2537b287810e9d5c1305`;
- finish-reason evidence report hash: `sha256:8ad09948da22f7fc6a0c5078aa62d0c5b5304ad10b527fd36e77fe989f4fa0cb`;
- suite hash: `sha256:f4edf57527ab5cb30bc7a413621230180319f5e000caeff114b35cbdd2e39632`;
- execution-source hash: `sha256:7d26b5895e7862da86968ad5e40d41c683efbf06c6494a86e9565a471284a390`;
- runtime-state hash: `sha256:213665b84ba8ad452a4e96bfcb80f440c09b8871f3ba9737cb45e5104dff5908`;
- response model verified on every case: `qwen3-8b-q4-k-m`;
- cases: 13/13 generated in each of three runs;
- elapsed: 35.980, 34.964, and 32.346 seconds;
- completion tokens: 2,412 in every run;
- reviewer: GPT-5.6-sol, PUBLIC synthetic proposal-only review;
- review artifact SHA-256: `sha256:758b53d2a4949fe117aafa21c60e2b3d3f9a84d1cf7b10e99db0faeab5c6c89e`;
- owner-calibrated: no.

The secured runs have the same execution-source, suite, generation settings,
13/13 provider-message hashes, and live candidate-only state. They agree exactly
on 13/13 completions. Earlier same-prompt runs exposed an alternate output track,
so a submitted seed is still not treated as a global exact-reproducibility
guarantee. The supplemental report matches the secured output 13/13 and proves
that the multi-request case ended with `finish_reason=length` at 768 tokens; all
other cases ended with `stop`.

The raw baseline is rejected as a replacement candidate. Four release-significant
failures were found:

1. in 3/3 samples it exhausted 768 tokens and ended mid-sentence before completing
   the explicitly requested clear model decision;
2. in 3/3 samples it guaranteed no data loss and rollback availability, asserted
   minutes of downtime, and invented a migration shape without system evidence;
3. it failed to explain the VRAM/system-RAM/runtime distinction in a local-model
   buying decision in 3/3 samples;
4. after the required untrusted-text boundary was added, it ignored the exact
   relevant-Memory precedent in 3/3 samples.

The secured base model still suppresses irrelevant, absent, stale-conflicting, and
partial Memory, respects a current correction, and avoids hidden-plan disclosure.
However, the richer control context causes the positive relevant-Memory behavior
seen in an earlier arm to disappear. Its dominant defects are generic wording,
over-reassurance, shallow domain judgment, unsupported certainty, verbosity that
crowds out completion, and fragile evidence use. Response Plan improves
observability and intent structure but does not repair those base-model
capabilities.

## MaiBot comparison

[MAIBOT_ARCHITECTURE_REVIEW.md](MAIBOT_ARCHITECTURE_REVIEW.md) pins the official
`Mai-with-u/MaiBot` revision reviewed and records the bounded fusion decision.
HAVRE adopts the useful conceptual split between planning, explicit Memory query,
reply generation, and observable send/effect boundaries. It does not adopt
emotion/mood simulation, deliberate mistakes, group-engagement behavior, style
imitation, scalar affection, or automatic profile writes. No GPL-3.0 source was
copied.

## Stronger local candidate comparison

The next candidate is the official Qwen3-14B GGUF Q4_K_M artifact pinned by exact
repository revision, size, SHA-256, and LFS object in
`mlsys/serving/manifests/qwen3-14b-q4-k-m.json`. The resumable fetcher publishes
only after size and hash verification. The isolated candidate launcher rechecks
the model and llama.cpp engine, refuses to overlap the daily 8B process, binds only
to `127.0.0.1:8082`, disables request logging/Web UI, probes health/metrics/SSE, and
records process-bound state. Its stop path verifies PID, executable, start time,
and command-line hash before stopping anything.

The exact 9,001,752,960-byte artifact downloaded and verified at
`sha256:500a8806e85ee9c83f3ae08420295592451379b4f8cf2d0f41c15dffeb6b81f0`;
no `.partial` file remained. It loaded with the fixed 8,192-token context and full
GPU-offload request on the RTX 5070 Ti Laptop GPU. While idle after the first run,
whole-GPU reporting showed 10,264 MiB used and 1,593 MiB free out of 12,227 MiB.
Windows WDDM did not expose trustworthy per-process memory, so this is capacity
evidence for the observed machine state, not a model-only memory measurement or
proof of sustained/concurrent headroom.

The same secured 13-case arm ran three times:

- report hashes: `sha256:729e851fcc52c3a0a8e57c5e71130c4d0a5e52aa2abf9d13aaab2588643915a2`,
  `sha256:822853f73c1895880e5c983982735f3675875251227719d8da6b6b19ab4d3a18`,
  and `sha256:f369d7215c13aed99a5895b120d39b638eee3828e6374b999f61a1f13c0660d2`;
- execution-source hash:
  `sha256:70f869c66867d9068b77d992395f7ace3be2b5ebb114c3623f505c1850e7107f`;
- runtime-state hash:
  `sha256:0944afb438a6572db1b9d647b91c9e525e6d1862e1f51fcebac992e09080a113`;
- response model verified on every case: `qwen3-14b-q4-k-m`;
- cases: 13/13 in each run, all 39 with `finish_reason=stop`;
- elapsed: 52.211, 51.887, and 51.016 seconds;
- completion tokens: 2,349, 2,359, and 2,359;
- exact-output agreement: 12/13 for r1-r2, 12/13 for r1-r3, and 13/13
  for r2-r3; only the no-solution casual reply varied;
- proposal-only GPT-5.6-sol review artifact:
  `sha256:ed7af133fd6b0b62f55974546cab4b6c6de44dab9a4b67aeb29e15c47fa48783`;
- owner-calibrated: no.

Relative to the secured 8B baseline, 14B removed the 768-token truncation, made
the migration answer conditional instead of guaranteeing outcomes, and naturally
used the admitted relevant-Memory precedent in 3/3 runs. Median arm latency rose
from 34.964 seconds to 51.887 seconds, about 48.4%.

The 14B candidate is still held from daily promotion. In 3/3 runs it covered the
multi-part model question but refused the requested clear recommendation and
introduced an unsupported cloud/local framing. In 3/3 buying-decision runs it
listed generic factors without distinguishing VRAM/system RAM, quantization, and
runtime compatibility, and did not explicitly preserve current-price uncertainty.
Its voice also remained formal, generic, and mildly therapeutic rather than the
intended distinctive gentle-and-strong companion. It is the leading local
candidate for the next full ContextPack/Core A/B, not an accepted daily brain.

## Verification

Completed in this work:

- contract schema export: passed;
- current Response Plan, calibration, collector, and candidate serving focused
  regressions: passed;
- complete primary non-Torch environment on a fresh dedicated PostgreSQL
  database: 582/582 passed, zero skips;
- pinned Torch Stage 9A regression: 62/62 passed;
- combined split-environment inventory: 644/644 passed;
- provenance audit on the migrated disposable database: `[]`;
- primary and pinned Torch `pip check`: passed;
- Python compilation: passed;
- PowerShell parse checks for the candidate fetch/start/stop scripts: passed;
- `git diff --check`: passed (Git emitted only configured LF-to-CRLF warnings).

The live candidate stop path initially failed closed because PowerShell 7 had
already deserialized the JSON `Z` timestamp to `DateTime`; converting it back to
an unqualified string and reparsing introduced the local UTC offset. The stop
script now casts the deserialized value directly to `DateTimeOffset`, compares
both instants in UTC, and retains all executable/path/command-hash checks. Its
focused regression and PowerShell parse check passed, the verified candidate PID
then stopped, port 8082 closed, and the daily desktop returned to the exact
unadapted 8B/no-adapter binding with `/health/ready = ready`.

An initial all-modules run in the primary interpreter reported ten
`ModuleNotFoundError: torch` errors across the three historical Stage 9A modules;
that interpreter intentionally omits Torch. The exact three modules then passed
62/62 in the pinned Torch environment, while every other module passed 582/582 in
the primary environment. The exact disposable database was dropped after its
empty provenance audit. No applied migration was edited.

## Stop boundary and next evidence

The 14B raw comparison is complete and materially improves three failed 8B
dimensions, but it retains two release-significant failures. The next bounded
evidence is a full ContextPack/Core A/B after a single targeted orchestration
correction for decisive recommendations, followed by blinded owner comparison.
Stop for Product Owner authority before raw private-chat cloud review,
driver/system changes, training, automatic routing, promotion, deployment, or
public exposure.
