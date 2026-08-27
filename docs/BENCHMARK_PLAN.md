# Benchmark Plan

Status: **Stage 6/7 second acceptance-correction evidence technically verified at execution-source snapshot `sha256:8ba8b94632ae181c2966acc3d6c498d8f7a63337d2e8558629b47dd440386f9c`; pending Product Owner reacceptance**

Stage 2 activation uses `evals/fixtures/retrieval_gold_v1.json` and `havre benchmark-retrieval` against a dedicated synthetic database. It pins corpus/query counts, reviewed importance values, algorithms, embedding/index/selection-policy versions, Python/PostgreSQL/pgvector environment, per-case rankings, quality metrics, and p50/p95 latency in both a SHA-256 content-hash-verified JSON artifact and immutable database row. It compares R0, legacy ungated R1, and the default gated R1 v2. See [`STAGE2_CHECKPOINT.md`](STAGE2_CHECKPOINT.md).

Stage 3 activation uses the content-hash-verified synthetic [`inference_workload_v1.json`](../evals/fixtures/inference_workload_v1.json) and `havre benchmark-inference` against an already-running, manifest-attested local provider. It records warmup and every measured attempt, exact code/workload/system/environment versions, typed failures, TTFT/TPOT/end-to-end latency, token/attempt throughput, CPU/RAM, GPU utilization, VRAM, and a separate descriptive Stage 1 behavioral-compatibility report. The final artifacts are under [`../evals/reports/stage3_20260813_final_run1/`](../evals/reports/stage3_20260813_final_run1/) and [`../evals/reports/stage3_20260813_final_run2/`](../evals/reports/stage3_20260813_final_run2/); see [`STAGE3_CHECKPOINT.md`](STAGE3_CHECKPOINT.md). These reports use content hashes, not digital signatures, and set `binding_evaluation = false` / `gate_status = not_evaluated`.

Stage 4 uses the content-hash-verified synthetic
[`user_model_evidence_sequences_v1.json`](../evals/fixtures/user_model_evidence_sequences_v1.json)
and `havre evaluate-user-model`. The report records pattern-proposal and
bitemporal replay results plus in-process component latency. It is explicitly
non-binding, measures no confidence calibration or end-to-end service latency,
and is not evidence of real-world understanding quality. See the historical
[`STAGE4_GOAL_INSERT_GUARD_CHECKPOINT.md`](STAGE4_GOAL_INSERT_GUARD_CHECKPOINT.md).
The `0012` persistence-integrity correction did not change this workload or
algorithm and did not rebind the historical reports to the current source
snapshot; see
[`STAGE4_REQUIRED_PROVENANCE_CORRECTION_CHECKPOINT.md`](STAGE4_REQUIRED_PROVENANCE_CORRECTION_CHECKPOINT.md).

Result contract: [`MLSYS_DESIGN.md`](MLSYS_DESIGN.md#12-benchmark-result-format)

## 1. Purpose and boundary

Benchmarks measure repeatable component/system behavior under a defined workload and environment. Evaluation determines whether behavior is good or acceptable. HAVRE needs both:

- Retrieval quality metrics such as Recall@K are evaluation metrics; retrieval latency under the same corpus/workload is a systems benchmark.
- TTFT and throughput describe serving performance; they do not prove that responses are helpful.
- An adaptive router is useful only if measured resource/latency gains preserve approved quality and constraints.

No benchmark numbers exist in Stage 0. Example schemas use null or illustrative values and must never be reported as results.

## 2. Reproducibility requirements

A benchmark is valid only when its result pins:

- benchmark name and protocol version;
- system-under-test code revision and all component/artifact versions;
- immutable workload/dataset snapshot and content hash;
- hardware model/count, CPU, RAM, storage, network topology, and accelerator memory;
- operating system, driver, accelerator runtime, container image, serving engine, and relevant library versions;
- precision, quantization, model context limit, scheduler/serving configuration, and cache state;
- prompt/output token distributions and concurrency schedule;
- warmup, repetitions, timeouts, random seed, and measurement clock/source;
- start/end time, failures, exclusions, and raw sample artifact hash;
- environmental controls that matter, such as GPU power limit or shared host contention.

Changing any material dimension creates a new run. It may be compared, but not silently merged into the old one.

## 3. Shared measurement protocol

1. Validate system health and exact version endpoint.
2. Capture the environment manifest before the run.
3. Verify workload hash and prevent evaluation/training leakage.
4. Declare cache mode: `cold`, `warm`, or a controlled mixed distribution.
5. Execute protocol-defined warmup; exclude it from measured samples but report it.
6. Run every scheduled request, including failures and timeouts.
7. Use monotonic clocks for durations.
8. Persist per-request samples before aggregates.
9. Calculate aggregates with a versioned analysis script.
10. Store logs/traces privately with hashes; redact content from public reports.
11. Compare only compatible runs and name every deliberate difference.

Retries are separate attempts. An initial timeout remains an error even if a retry succeeds; report request-level success and eventual success separately when relevant.

## 4. Metric definitions

### Inference timing

- **End-to-end latency:** client/harness request dispatch to receipt of terminal completion/failure, including queue, network, prefill, decoding, and protocol overhead.
- **TTFT:** request dispatch to receipt of the first non-empty user-visible output token/chunk. Provider “start” metadata without content does not count.
- **Generation interval:** first visible output token to terminal output receipt.
- **TPOT:** for completed responses with at least two output tokens, `(time_last_token - time_first_token) / (output_tokens - 1)`. Report how tokens were counted.
- **Inter-token latency:** optional per-token distribution; more informative than mean TPOT for stalls.
- **Prefill/queue latency:** only reported when the serving engine exposes a trustworthy definition; otherwise left null rather than inferred.

### Throughput and resource

- completed requests per second and attempted requests per second;
- input, output, and total tokens per second at the server and harness perspective;
- concurrent in-flight requests;
- peak and time-series accelerator memory;
- accelerator utilization, CPU, RAM, I/O, and network where available;
- energy or GPU-hours only when measurement method is documented;
- error/timeout/cancellation rate with typed codes.

### Percentiles

Report at least p50 and p95 for latency, TTFT, and TPOT when sample size supports them. Include sample count; do not report unstable tails as precise facts. Prefer bootstrap confidence intervals for comparative reports, with the analysis method/version pinned.

### Cost

For external providers or cloud GPUs:

- provider cost per request and per 1K interactions;
- compute rental cost per benchmark hour;
- cost per successful output token or completed interaction;
- assumptions, currency, region, date, idle allocation, and excluded fixed costs.

Cost is time-sensitive and must be refreshed; old prices do not make a current claim.

## 5. Retrieval benchmark

### Question

Which retrieval pipeline returns the memories a human judge considers relevant and appropriate, with acceptable latency and redundancy?

### Dataset

An immutable snapshot contains:

- memory corpus with exact revisions, classes, timestamps, metadata, status, and embedding content hashes;
- queries with explicit `as_of` times and context features;
- graded relevance judgments;
- `should_not_surface`, stale, superseded, counter-evidence, and duplicate labels;
- corpus/query category distributions;
- judge instructions, adjudication, and agreement metadata.

Start with a small manually reviewed set in Stage 2. Expand by scenario coverage and retrieval failures, not by generating a large unreviewed synthetic “gold” set.

### Variants

Run controlled comparisons:

```text
R0 metadata/recency baseline
R1 embedding candidate retrieval
R2 embedding + explicit recency/importance/goal/scene features
R3 hybrid lexical + embedding
R4 hybrid + reranking
```

Activate a more complex variant only if it provides a measured benefit worth its latency and maintenance cost.

### Metrics

- Recall@5 and Recall@10;
- MRR;
- nDCG@5/10 for graded relevance;
- inappropriate/stale result rate;
- duplicate/redundant result rate;
- candidate and final result counts;
- p50/p95 total latency and breakdown;
- index size/build time and memory when relevant;
- errors/timeouts.

Report slices by memory class, query category, age, corpus size, and counter-evidence presence. One aggregate can hide failure on progress or contradictory memories.

### Scaling protocol

Use private, synthetic, or safely transformed padding records to test corpus-size behavior without claiming they improve relevance realism. Measure exact search first; introduce HNSW/IVFFlat or other approximate configurations only when corpus size/latency evidence requires them. Record index parameters and recall loss against exact search.

## 6. Inference serving benchmark

### Question

What quality/latency/resource frontier can each eligible model, precision, serving engine, and configuration provide on HAVRE workloads?

### Workload classes

- `scene_short`: small prompt, very short output, strict TTFT priority;
- `chat_standard`: representative conversation/context and moderate output;
- `reflection_long`: long context and structured output;
- `extraction_structured`: deterministic schema-constrained background task;
- `evaluation_batch`: offline throughput-oriented workload.
- `proactive_simple`: authorized short reminder rendered by deterministic template or small/local path;
- `proactive_reflective`: authorized evidence-rich outreach rendered by an eligible model, introduced only after Reflection exists.

Each class freezes prompt-token and requested-output distributions. Public reports use de-identified/synthetic prompts with the same shapes; private behavioral evaluation runs separately.

### Matrix

As stages activate, compare one variable at a time before larger factorial sweeps:

- model sizes that the available hardware can actually run;
- BF16/FP16 and supported quantization variants;
- short/medium/long context;
- concurrency levels such as 1, 2, 4, 8 only when capacity permits;
- streaming versus non-streaming client behavior;
- prefix cache cold/warm;
- different memory/context budgets;
- selected serving-engine versions/configurations.

The Master Plan's 8B/14B/27B-class comparison is a candidate matrix, not an obligation to rent hardware before a decision requires it.

### Metrics

- TTFT, TPOT, end-to-end latency p50/p95;
- inter-token latency/stall rate where available;
- input/output/total token throughput;
- completed/attempted request throughput;
- peak/time-series VRAM and utilization;
- CPU/RAM and server queue depth;
- error, timeout, cancellation, and malformed-output rate;
- cost under documented pricing;
- behavioral/structured-output evaluation reported alongside, not merged into speed.

## 7. Context-budget benchmark

### Question

Does more context improve correct, useful behavior enough to justify token, latency, cache, and privacy cost?

Variants include:

```text
top 3 vs top 5 vs top 10 memories
raw excerpts vs summaries vs mixed
recency-heavy vs relevance-heavy selection
with vs without redundancy control
stable prefix layouts
compression strategies
```

Measure:

- behavioral and memory-use rubric scores;
- relevant-context inclusion and harmful/stale inclusion;
- prompt tokens and truncation rate;
- Context Builder latency;
- inference TTFT/end-to-end changes;
- provider prefix-cache reuse when supported;
- protected-content exposure count by class.

Use paired cases so each strategy sees the same candidate set. The best context is the smallest pack that retains approved quality and safety, not the pack with the most history.

## 8. Cache benchmark

For each cache type, define key/version scope, invalidation, TTL, and correctness oracle before measuring:

- embedding cache;
- retrieval-result cache;
- stable prefix/provider cache;
- summary cache;
- semantic response cache only in a later explicitly approved experiment.

Metrics:

- hit, miss, stale-hit, and invalidation rate;
- latency saved by component and end to end;
- token/compute/cost saved;
- storage and invalidation overhead;
- quality/privacy failures caused by stale or cross-scope data.

Any cross-owner cache hit is a critical failure. An identity, belief, goal, memory, policy, model, or tokenizer version change must invalidate relevant keys.

## 9. Routing benchmark

### Baselines

```text
A always strongest eligible model
B rule-based router
C learned router later, only after labeled routing data exists
```

Replay the same frozen requests under all strategies. A route decision must not see reference output or future feedback unavailable at decision time.

Measure:

- quality retained and critical failures relative to baseline;
- end-to-end and TTFT distributions;
- model/provider utilization;
- estimated and realized cost;
- fallback and unavailable-route rate;
- wrong-route rate by severity;
- privacy/capability eligibility violations;
- predicted-versus-observed latency/cost/quality calibration.

The report presents a Pareto frontier. No single “router score” should obscure a serious quality or privacy loss.

## 10. Personalization experiment

When Stage 9 has enough reviewed data, compare:

```text
Base
Base + Memory
Base + Adapter
Base + Memory + Adapter
```

Controls:

- exact base model and decoding parameters;
- frozen train/validation/holdout snapshots;
- identical memory fixtures for applicable arms;
- exact prompt/policy/context versions;
- training seed/config/environment;
- multiple seeds or an explicit limitation if compute permits only one;
- blinded or randomized output order for human/judge comparison.

Measure behavioral quality, identity consistency, action usefulness, memory factuality, over-agreement, general capability regression, safety, latency, VRAM, and adapter load/switch overhead. An adapter that mimics wording but does not improve outcomes is not automatically valuable.

## 11. End-to-end and reliability benchmark

Once the relevant components exist, measure full interaction stages via traces:

```text
ingress
event commit
state/scene/goal load
retrieval
policy
context build
route
provider queue/inference
delivery
assistant event commit
```

For proactive interactions, measure a separate linked pipeline:

```text
trigger observation/record
proposal creation
interruption-policy evaluation
defer/drop/confirmation stop, or SEND_NOW continuation
proactive context build
render route/rendering
delivery eligibility and attempt
delivery reconciliation
proactive assistant event commit
optional explicit response linkage
```

For a future Ambient Life Context capability, measure its upstream path separately before attributing downstream behavior:

```text
source occurrence
source-local acquisition / aggregation
adapter normalization
offline buffer / transport
Core consent/schema/policy validation
LifeContextObservation Event commit
source-health / freshness / coverage evaluation
optional state / trigger evaluation
```

Scenarios:

- healthy baseline;
- retrieval unavailable/degraded;
- primary provider unavailable with eligible fallback;
- worker backlog;
- interrupted stream;
- database contention;
- deployment rollback and health recovery.
- scheduled proposal under normal operation and worker backlog;
- proposal invalidated, cancelled, dismissed, snoozed, or expired before delivery;
- duplicate worker/delivery attempt and ambiguous provider receipt;
- preference/policy/privacy change between authorization and attempt;
- ineligible notification preview/channel and privacy-safe fallback to generic/no preview or no delivery.

Metrics include per-span latency, total success, durable-record completeness, degraded-mode rate, queue age, retry amplification, recovery time, and untraceable interaction count (target must be zero, but only measured results may claim it). Proactive benchmarks additionally report duplicate visible effect, stale authorization rejection, expiration-before-delivery, and scheduled-time error.

## 12. Proactive interaction systems benchmark

This benchmark begins with Stage 6 Proactive Core. It measures execution and reliability, not whether outreach was behaviorally appropriate; the linked policy-quality evaluation remains authoritative for that question.

### Workload manifest

Freeze:

- trigger/proposal category and privacy distribution;
- immediate versus scheduled/deferred timing distribution;
- renderer path (template, local/small, Personal Brain, stronger eligible model) and exact versions;
- Web/inbox adapter version first, later channel adapter versions separately;
- owner preference/policy versions, quiet-hour/timezone fixtures, budget/cooldown/deduplication state;
- worker count/polling/lease/retry configuration and database state;
- delivery provider fault/receipt behavior;
- warmup, repetitions, concurrency, clock synchronization/error method, and trace sampling/export mode.

Private message/reason content is not required in a benchmark artifact; use synthetic protected fixtures with equivalent sizes/policy shapes and store hashes.

### Latency and scheduling metrics

- trigger observed to durable trigger recorded;
- trigger recorded to proposal created;
- trigger-to-proposal total latency;
- proposal evaluation latency;
- defer-until/eligible-time to evaluation-start error;
- `SEND_NOW` decision to Context Pack, rendering, first delivery attempt, and confirmed delivery;
- proposal-to-delivery total latency;
- rendering latency, inference TTFT/TPOT when model-based, token use, and cost;
- queue age, claim latency, lease recovery time, and backlog drain time.

Scheduling accuracy reports signed and absolute difference between declared eligible time and actual evaluation/attempt time, with early attempts counted as errors rather than hidden in an absolute average.

### Reliability and privacy metrics

- delivery attempt success/failure/unknown/reconciliation-required rates by typed status;
- delivery failure rate and eventual success after retry, reported separately;
- duplicate-attempt rate and duplicate-visible-delivery rate;
- expired-before-delivery and cancelled/snoozed/dismissed-before-attempt rates;
- stale policy/preference/authorization rejection rate;
- retry amplification and poison/terminal-failure rate;
- delivery/provider receipt ambiguity rate;
- trace, proposal, decision, Context Pack, rendering, attempt, and delivered-event linkage completeness;
- raw private content found in ordinary logs/traces/metric labels (critical if nonzero);
- notification-preview/privacy eligibility violations (critical if nonzero);
- local versus approved-cloud rendering distribution and channel distribution.

`duplicate-delivery rate` uses user-visible delivery effects as the numerator, not harmless duplicate job claims. Provider acceptance alone is not proof of visibility; unknown receipt state remains explicit.

### Controlled scenarios

At minimum compare:

1. healthy immediate Web/inbox delivery;
2. deferred scheduled delivery within and outside declared timing tolerance;
3. duplicate job claim/delivery call under one idempotency key;
4. worker crash before and after provider acceptance;
5. provider timeout, retryable failure, terminal failure, and ambiguous receipt;
6. cancellation, expiration, snooze, dismissal, stop, preference revocation, and privacy change between steps;
7. worker backlog and database contention;
8. deterministic template versus eligible model rendering for the same authorized simple-purpose fixture;
9. generic/no-preview handling for sensitive sources;
10. linked user response versus unrelated reactive conversation.

No current number or target is claimed. Stage 6 must establish a reproducible baseline before any limit or architecture change is justified.

## 12A. Ambient Life Context adapter benchmark (proposed Stage 11/12)

This benchmark begins only when one source capability is separately authorized. It measures source/adapter systems behavior and privacy exposure; linked evaluation determines whether the signal is useful or appropriate.

Freeze:

- source kind/provider/device/OS and exact capability/adapter/schema versions;
- ConsentScope, SamplingPolicy, RetentionPolicy, DataPolicy, allowed fields/precision, and source-health/freshness policy;
- event-driven, user-initiated, interval, offline, and recovery workload distribution;
- clock skew, duplicate/out-of-order, permission revoked, offline, stale, unsupported, and partial-coverage fault cases;
- local preprocessing hardware, battery/power method, network, buffer limits, Core ingest environment, and trace mode;
- synthetic or safely controlled source data; real private content is not required for systems evidence.

Metrics:

- source occurrence to acquisition, normalized draft, durable observation, and downstream eligibility latency;
- observation/drop/duplicate/out-of-order/reconciliation rates;
- signed and absolute timestamp/clock error and coverage gaps;
- health/freshness classification accuracy against the controlled fixture;
- bytes/events transmitted, local CPU/RAM/storage, battery/energy where measurable, and Core ingest load;
- forbidden raw field/content crossing the adapter boundary (critical if nonzero);
- consent/policy/revocation/retention violations (critical if nonzero);
- source-to-observation and observation-to-derived provenance completeness;
- deletion/retention propagation and offline-buffer cleanup completeness;
- provider replacement equivalence for the same canonical fixture.

Controlled comparisons start with the minimum sufficient representation. For Windows, compare coarse category/window summaries before any proposed exact app identity; screenshots/content capture are not benchmark candidates under the default architecture. For Calendar, compare time/busy/category before title/details. For location, compare coarse geofence/category before exact coordinates. More bytes, higher sampling, or richer fields are costs; adoption requires measured downstream value under the linked evaluation.

Source health and observation absence never become user-state ground truth in a benchmark report. An offline agent can demonstrate recovery behavior, not user inactivity.

## 13. Analysis and reporting

Every comparison report includes:

1. question and predeclared hypothesis;
2. baseline and candidate;
3. controlled and uncontrolled differences;
4. workload/environment/version table;
5. sample counts, raw distribution plots or summaries, confidence intervals where appropriate;
6. failures and excluded samples with reasons;
7. behavioral/evaluation companion results;
8. privacy and cost implications;
9. conclusion limited to measured scope;
10. recommendation: adopt, reject, run another experiment, or inconclusive.

Avoid:

- percentages without baseline values and sample sizes;
- comparing runs on different hardware/workloads as if only the model changed;
- hiding warmup, failures, or outliers without protocol justification;
- claiming production impact from a microbenchmark;
- choosing only favorable metrics after seeing results;
- writing future resume numbers before a reproducible artifact exists.

## 14. Stage deliverables

| Stage | Required benchmark artifact |
|---|---|
| 0 | This protocol and result schema; no performance claim |
| 1 | Trace overhead and basic end-to-end correctness timing for a deterministic provider, labeled development-only |
| 2 | Retrieval gold set v1 and R0/R1 measured comparison |
| 3 | Self-hosted inference baseline across declared workload classes |
| 4–5 | User Model/policy/scene component timing plus behavioral suites |
| 6 | Proactive Core trigger-to-delivery/reliability baseline plus context and routing controlled experiments |
| 7 | Data-pipeline throughput/quality, Reflection-proposal timing, memory lifecycle/regeneration, and snapshot reproducibility |
| 8 | Unified reports, proactive policy/systems evidence, source-health/freshness/missingness fixtures, trace explorer, regression automation, and repeatability checks |
| 9 | Four-arm personalization experiment |
| 10+ | deployment/load/rollback, Stage 11 iPhone/voice capability baselines, Stage 12 context-adapter baselines, and later edge/cloud routing experiments |

## 15. Stage 0 exit conditions for measurement contracts

- Metric start/stop definitions are approved.
- Benchmark result envelope is approved.
- Exact version, workload, hardware, environment, failure, and artifact metadata are mandatory.
- Retrieval, inference, routing, context, and personalization experiment questions are explicit.
- Evaluation and systems measurements remain separate but linked.
- No placeholder value can be mistaken for a measured HAVRE result.
- Proactive system latency/reliability metrics remain separate from the evaluation of whether contact should have occurred.
- Context adapter latency/coverage/resource metrics remain separate from whether the observation was useful, minimally sufficient, or justified.
