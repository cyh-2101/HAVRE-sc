# Strong Cloud Brain Ceiling Checkpoint

- Date: **2026-08-26**
- Scope: one owner-authorized, PUBLIC-synthetic, provider-neutral model-ceiling experiment
- Provider/model: `deepseek-cloud` / provider-verifiable alias `deepseek-v4-pro`
- Decision evidence: `sha256:44ce37e5a5d4173f435dc4b1d639ded5919708de3e5ba06f607f0f49cd6c9e2d`
- Result: **C — model capability is a major relevant-Memory bottleneck, while Context/Core containment remains essential**

## Boundary and implementation

`DeepSeekCloudProvider` implements the existing `ModelProvider` and canonical
`InferenceRequest` boundary. It is disabled by default and cannot advertise
eligible capabilities while disabled. Authentication is read only from
`DEEPSEEK_API_KEY`; the value is absent from requests, events, traces, evidence,
errors, and the repository. The adapter ignores proxy environment variables,
refuses redirects, verifies the requested live model alias, and retains only
final-answer content: provider reasoning content is discarded. The API did not
expose an independently verifiable immutable revision. The initial experiment
report's `DeepSeek-V4-Pro-0813` value was a configured declaration, not verified
lineage; the corrected v2 adapter records only `deepseek-v4-pro` and the result
is attributed to that alias at the recorded request times.

Cloud routing requires all of the following: `PUBLIC`, `cloud_eligible=true`, an
exact milestone authorization reference, `PUBLIC_SYNTHETIC` metadata, a
strict-hex fixture hash in the verified-suite allowlist, and an exact canonical
request hash in the sealed run allowlist. The request hash covers messages,
source references, policy, generation settings, model alias, and thinking mode;
drift fails before HTTP. `LOCAL_ONLY`, private, unknown, owner-default, arbitrary
authorization strings, or incomplete permits fail before HTTP. No production router, daily chat, candidate
registry, lifecycle state, deployment, or binding was changed.

`TokenUsage` gained optional provider-neutral cache-hit, cache-miss, and
reasoning-token fields. The fields are mutually and arithmetically validated;
active schemas were regenerated.

## Focused exact comparison

The 32-case focused suite used the same current Identity, Context presentation,
Memory fixtures, user messages, and per-case provider-facing prompt hashes for
9201, rejected v7/9701, unregistered 9801, DeepSeek non-thinking, and DeepSeek
thinking. Core was replayed independently and raw/pipeline outputs remain
separate. An independent reviewer scored 160 blinded outputs semantically.

| Arm | Strict | Paired Memory | Multi-Memory | Casual | Naturalness | Useful | Provenance | Forced-callback pass | Relevant-history pass | Current precedence |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 9201 | 22/32 | 13/20 | 2/4 | 7/8 | 30/32 | 26/32 | 26/32 | 19/20 | 10/12 | 3/4 |
| rejected v7/9701 | 22/32 | 16/20 | 1/4 | 5/8 | 28/32 | 26/32 | 29/32 | 18/20 | 10/12 | 4/4 |
| unregistered 9801 | 20/32 | 11/20 | 3/4 | 6/8 | 30/32 | 29/32 | 27/32 | 18/20 | 9/12 | 3/4 |
| DeepSeek non-thinking | 23/32 | 14/20 | 4/4 | 5/8 | 27/32 | 31/32 | 31/32 | 19/20 | 9/12 | 4/4 |
| DeepSeek thinking/high | **28/32** | **19/20** | **4/4** | 5/8 | 30/32 | **32/32** | 31/32 | **20/20** | **11/12** | **4/4** |

Thinking/high is +6 strict cases over the best local result, with no forced
callback or current-precedence failure. Its remaining critical failure was
fabricated familiarity in one no-Memory earphones case; it ignored one partial
chapter-history case. It also remained weaker than 9201 on casual regression.
The exact comparison proves a material model/inference-compute ceiling, not a
pure base-model-only effect: thinking used `max_tokens=4096` because provider
reasoning and final text share the limit, while local and non-thinking arms used
96.

For the representative AI/self-learning case, 9201 ignored the admitted
Memory; v7 and 9801 turned it into an unsupported accusation. DeepSeek instead
asked whether this was the earlier “did a lot but did not really learn it”
feeling, preserving uncertainty and naturally connecting the shared history.

## Conditional broader replay

The +6 focused result triggered the existing 80-case PUBLIC-synthetic replay.
The frozen local report used the v7 dataset system text, while the cloud run used
the current Identity; seven Memory cases also used the current presentation.
Therefore exact provider-facing prompt comparability is **0/80**. This is an
absolute regression over the same messages, Memory content, and targets, not a
causal local-versus-cloud comparison.

Independent blinded review of the 40 companion cases found:

| Arm | Strict | Naturalness | Primary quality | Truth/provenance |
|---|---:|---:|---:|---:|
| 9201 | 25/40 | **34/40** | 26/40 | 30/40 |
| rejected v7/9701 | 19/40 | 30/40 | 21/40 | 35/40 |
| DeepSeek thinking/high | 25/40 | 27/40 | **32/40** | **40/40** |

DeepSeek was stronger on warm/firm, repair, earned familiarity, identity
continuity, and capability-aware length, but over-analysed casual and opinion
turns; natural opinion was 0/5. Raw hard-capability deterministic checks were
18/40, versus 9/40 for frozen 9201, but Core still replaced 36/80 cloud outputs.
Core remains necessary, and replacements are not model credit.

## Performance and cost

| Run | Requests | Prompt tokens | Output tokens | Reasoning tokens | Cost | Latency p50/p95 | TTFT p50/p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Focused non-thinking | 33 | 22,327 | 1,963 | 0 | $0.013725888 | 2.70s / 4.23s | 1.06s / 1.33s |
| Focused thinking/high | 33 | 24,934 | 16,482 | 13,212 | $0.069762528 | 12.86s / 26.62s | 10.71s / 25.24s |
| Broader thinking/high | 80 | 50,954 | 36,366 | 26,277 | $0.156717088 | 8.93s / 36.36s | 7.03s / 25.07s |

The three complete, hash-bound formal reports cost **$0.240205504**, exactly
recomputed from a prompt-free 146-request ledger containing provider
cache-hit/cache-miss/output usage and the recorded pricing window. An
operator log recorded $0.025235584 for ten successful rows from an incomplete
1024-token diagnostic and a $0.016938240 conservative maximum for two failed
calls, but no source-bound spend artifact was retained for those values. They are
excluded from the independently reproducible cost total and all quality results.
The verified formal total is below the $1 ceiling.

## Decision and stop boundary

No training was needed or performed. The focused same-prompt comparison shows
that the current Context representation is usable and that model capability plus
reasoning compute is a major remaining Memory-use bottleneck. System work is not
finished: privacy admission, provenance, current-message precedence, and Core
containment remain non-negotiable, and the strong cloud model still regresses on
casual brevity/opinion and can fabricate familiarity.

9201 remains the best current daily-use candidate because it is the unchanged
authorized local binding and is materially more natural in ordinary chat.
DeepSeek is experiment-only and default-disabled. v6/v7 remain immutable
rejected candidates; 9801 remains unregistered/rejected. No status, training,
routing, serving, promotion, deployment, Stage 9B, or private-data decision is
made here.

## Verification

- focused comparison: `sha256:3a861a693cb3349d171223884b55470ad41ae648d576da464a99412c3d09d55b`
- focused blind packet: `sha256:38a418e759c3ac6ee883c06f487667d8d4ea9e336788435697aa979cd0831548`
- focused independent review file: `sha256:2185bdf2ed7f53fc23bbf203a286c588eaf05a7651a975cda6ad015572306704`
- broader cloud report: `sha256:630a68686248739e69d4a2693fa91c39782ac73bd2b64afd813ceded0bdb8a20`
- broader blind packet: `sha256:0159673642049192e507bae1903fd0291a0cd009c079aab1941975cc8085b334`
- broader independent review file: `sha256:cb3be8e06fa6b333dc8bb85a27ab382e156dda3c761d864d5a98936f51e904a`
- formal per-request cost evidence: `sha256:ddbc6da4b47386fa92fe7bdd9107fc5543ef60e8eff17a7a7e37074e0f9802d1`
- dedicated PostgreSQL `havre_strong_cloud_20260826`: migrations `0001`–`0037`, empty reapply, provenance audit `[]`, then dropped; prior stopped state restored
- ordinary environment: 554 discovered, 544 passed, 0 skipped, 10 `torch` import errors
- pinned Stage 9A environment: the corresponding 62 transformer tests passed, including those 10 modules
- `pip check`, schema export, compilation, and `git diff --check` passed
- final independent code/evidence review initially found P1=0/P2=5. Before
  commit, v2 corrected exact-version overclaiming and sealed request admission;
  the decision builder was hardened to verify every report/packet/key hash edge
  and cross-check every case/arm against its blind packet before recomputing all
  160 focused and 120 broader per-output review aggregates; a prompt-free
  146-request usage ledger now independently recomputes formal cost;
  the stale review hash was corrected and non-source-bound cost was downgraded.
  Final independent re-review found **P1=0, P2=0**. The retained historical
  caveat is that formal outputs came from adapter v1; v2 hardening governs future
  calls and does not rewrite immutable historical generations.

The split Python environments are an existing verified repository boundary, not
a claim that one interpreter alone ran every test.
