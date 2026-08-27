# Stage 3 Checkpoint - Self-hosted Inference Baseline

Status: **Historical implementation checkpoint; superseded for acceptance by [`STAGE3_CORRECTION_CHECKPOINT.md`](STAGE3_CORRECTION_CHECKPOINT.md)**

Date: 2026-08-13

> **2026-08-14 correction:** This checkpoint correctly proves pinned artifact
> bytes and benchmark-time startup attestation, but it overstated ordinary
> interaction lineage. Before the acceptance correction, `/props` plus a model
> alias did not bind each Companion interaction to the active process/model
> artifact. Values copied from configuration were therefore configured and
> pinned, not per-interaction process-attested. The correction checkpoint is the
> authority for renewed acceptance. The Product Owner subsequently approved the
> correction checkpoint at source snapshot
> `sha256:9a43713e082dec08039a93c673c7a0af812b881dcb0d5d3da68a0b17e7075436`;
> Stage 4 remains unauthorized.

## Scope completed

Stage 3 adds a real, owner-controlled model-serving path behind HAVRE's existing provider boundary. It does not replace the Stage 1/2 request path, identity, privacy policy, ContextPack, memory, or provenance contracts.

```text
user request
  -> durable request / W3C trace / USER_MESSAGE
  -> approved Constitution, Identity, and Values
  -> retrieval-gated, token-budgeted ContextPack
  -> provider-neutral route and InferenceRequest
  -> loopback OpenAI-compatible adapter
  -> pinned llama.cpp service
  -> pinned Qwen3-8B GGUF model
  -> typed SSE stream and normalized InferenceResponse
  -> durable inference attempt / ASSISTANT_MESSAGE
  -> exact versions, timing, tokens, resources, and provenance
```

The active provider is selected with `HAVRE_PROVIDER_ID`. Changing from `deterministic-local` to `self-hosted-openai-compatible` requires configuration only; Companion domain code and persisted contracts do not change.

Stage 3 deliberately does **not** add User Model inference, Intervention Policy, Scene functionality, Reflection, consolidation, training, LoRA, proactive interaction, tools, voice, or a client application.

## Plain-English component guide

- **Pinned runtime manifests:** checked-in manifests name the exact model, serving-engine release, artifact sizes, SHA-256 hashes, license, network binding, context limit, and serving flags. Setup verifies every downloaded byte before use.
- **Local inference service:** `llama-server` is a separate process bound to `127.0.0.1`. It exposes health, version/properties, metrics, and OpenAI-compatible chat completion endpoints. Request logging and its Web UI are disabled.
- **OpenAI-compatible adapter:** HAVRE translates its provider-neutral request into the server protocol, consumes ordered SSE chunks, and translates the result back into HAVRE's typed response. The adapter accepts plaintext HTTP only on loopback and does not trust proxy environment variables.
- **Provider contract (original checkpoint):** capabilities, health, configured pinned version information, successful streams, and safe typed failures are first-class contracts. Benchmark startup used stronger process verification; the original ordinary interaction path did not yet carry that same proof.
- **Router:** privacy, execution location, streaming support, output limit, and combined input/output context limit are checked before inference. `LOCAL_ONLY` is eligible only for a local provider.
- **Interaction orchestrator:** the permanent Companion flow collects and validates the provider stream, enforces the request timeout, writes success or failure evidence, and delivers an assistant event only after a complete response exists.
- **Failure ledger:** pre-route and inference failures create a content-free `INTERACTION_FAILED` event. Failed attempts may exist without a fabricated response ID; safe typed codes are retained without raw provider response bodies.
- **Benchmark harness:** a frozen synthetic workload measures TTFT, TPOT, end-to-end latency, throughput, token counts, CPU/RAM, GPU utilization, VRAM, and typed errors. Environment and runtime attestation are captured before each run.
- **Immutable evidence store:** migration `0005` stores each systems report and its matching compatibility report as one immutable pair. Exact owner/request/trace foreign keys prevent same-owner cross-request lineage mixing in operational evidence.

## Pinned configured baseline

The model and server remain candidate artifacts; neither is a personalized production release.

| Item | Exact value |
|---|---|
| HAVRE package | `0.3.0` |
| Interaction orchestrator | `interaction-orchestrator-v5` |
| Context Builder | `context-builder-v5` |
| Router | `single-provider-router-v2` |
| Provider | `self-hosted-openai-compatible` (`self_hosted`, `local`) |
| Provider adapter | `openai-compatible-provider-adapter-v1` |
| Model version | `model-qwen3-8b-gguf-q4-k-m-7c41481f` |
| Upstream model / revision | `Qwen/Qwen3-8B-GGUF@7c41481f57cb95916b40956ab2f0b139b296d974` |
| Weights | GGUF `Q4_K_M`, 5,027,783,488 bytes |
| Model SHA-256 | `sha256:d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785` |
| Tokenizer | `Qwen/Qwen3-8B-GGUF@7c41481f57cb95916b40956ab2f0b139b296d974:embedded-gguf-tokenizer` |
| Model license | Apache-2.0 |
| Serving engine | `llama.cpp b10405@e79e4bf660e19f2ad851e06c6913f7a8c5852621` |
| Server executable SHA-256 | `sha256:731fe93a56a8cfbc460a18179be822f6b31bda0b1de3d10749004c9e46137582` |
| Server bundle SHA-256 | `sha256:7da18847181aa668a77b02fa8bd47bb9588b82ca077cf184bccc3bf016b46e79` |
| CUDA runtime bundle SHA-256 | `sha256:8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6` |
| Serving configuration | `sha256:5cf87ffb8b2f715cd00400d380739ea4a05993796e692cc6c3bf17dffd92ebce` |
| Serving profile | context 8,192; parallel slots 2; all GPU layers; flash attention; Jinja; thinking disabled |
| Benchmark harness / runner | `stage3-inference-benchmark-v1` / `stage3-inference-runner-v1` |
| Benchmark source snapshot | `sha256:8780e3b94ca5b740f029ecd37c475c096af1e2a5f1461359e4a2892976233187` |
| Candidate system-under-test manifest | `sha256:2a9cf4365906b2835529dd88062b67e070ff572053f136610241a2236957ba5f` in both final runs |

The pinned artifact definitions are in the [model manifest](../mlsys/serving/manifests/qwen3-8b-q4-k-m.json), [serving-engine manifest](../mlsys/serving/manifests/llama-cpp-b10405-win-cuda-12.4-x64.json), and [environment template](../mlsys/serving/manifests/stage3-environment-template-v1.json).

The measured host was Windows 11 build 26200 with CPython 3.12.13, an AMD Ryzen 9 7945HX (16 physical / 32 logical cores), 16,341,381,120 bytes of RAM, and one NVIDIA GeForce RTX 5070 Ti Laptop GPU with 12,820,938,752 bytes of VRAM and driver 573.22. The benchmark startup attested the live process path, executable hash, launch arguments, model hash, loopback endpoint, and disabled request logging. This did not, by itself, make the original ordinary Companion request per-interaction-attested.

## Additive persistence and contract changes

[`0005_stage3_self_hosted_inference.sql`](../db/migrations/0005_stage3_self_hosted_inference.sql) is additive to the checkpointed Stage 1/2 migrations. It was tested both from an empty database and as an in-place upgrade from a populated `0001`-through-`0004` database.

It adds or strengthens:

- immutable completed or failed inference attempts with an independent attempt ID;
- optional response IDs for failed attempts instead of invented successful records;
- exact provider adapter, serving engine, serving configuration, tokenizer, model, and artifact-hash evidence;
- durable `INTERACTION_FAILED` events and request pointers;
- exact `(owner_id, request_id, trace_id)` relationships across requests, events, ContextPacks, routes, and inference attempts;
- immutable `havre.inference_benchmark_runs` rows for the systems and compatibility report pair.

The active contract export contains 20 JSON Schemas, including provider version, stream event, inference failure, system/workload manifest, systems benchmark report, and behavioral compatibility report schemas.

## Complete real request

One end-to-end CLI interaction used the self-hosted provider with `LOCAL_ONLY` policy. The prompt content is not copied into this checkpoint; the durable owner-qualified records contain it under its original policy.

| Evidence | Stored value |
|---|---|
| Request ID | `019ffae5-7832-7921-b0d5-18f3e7324b54` |
| W3C trace ID | `f050fc8766b67e03a577568f120c11ae` |
| Durable `USER_MESSAGE` event | `019ffae5-7832-7924-a943-37185ff4c25a` |
| ContextPack | `019ffae5-784b-7085-ba79-359a2e38ca7e` |
| Route decision | `019ffae5-784b-7086-afeb-241c21a818bd` |
| Inference request / attempt | `019ffae5-784b-7087-a661-a9215cf72e09` |
| Inference response | `019ffae5-7855-7a57-9b7b-59b37f52a231` |
| Provider request | `chatcmpl-z6ta7OESLBzveod2Gy2wx9VWb1YqasiT` |
| Durable delivered `ASSISTANT_MESSAGE` event | `019ffae5-8051-7619-912d-81982f014567` |

The request, both message events, ContextPack, route, attempt, and response all carry the same owner-qualified request/trace lineage. The ContextPack records the approved Constitution/Identity/Values versions, token budget, effective policy, and source provenance. The effective policy was `LOCAL_ONLY`, `cloud_eligible = false`, and `training_eligible = false`; the selected provider was local. The stored model/runtime fields were copied from the pinned configuration and should not be read as proof that this particular active process loaded those bytes.

The exact completed-attempt measurements were:

| Measurement | Value |
|---|---:|
| Prompt tokens | 560 |
| Output tokens | 152 |
| Total tokens | 712 |
| TTFT | 162.324 ms |
| Visible generation interval | 1,878.010 ms |
| Provider end-to-end | 2,040.684 ms |
| Complete interaction span | 2,095.463 ms |

The provider streamed internally over SSE and terminated normally. The current Companion API/CLI still returns the complete interaction response rather than forwarding token chunks to a client, so the durable delivery timestamp represents completed delivery, not user-visible streaming. Exposing outward streaming is not claimed by this checkpoint.

## Verification evidence

Two complete PostgreSQL-backed paths were independently exercised:

- **Fresh install:** migrations `0001` through `0005`, then **132/132 passed, 0 failed, 0 skipped**.
- **Populated upgrade:** a real Stage 2 database containing 197 historical requests at `0004` was copied, migrated in place with only `0005`, and then **132/132 passed, 0 failed, 0 skipped**. Historical attempts remained readable after backfill, and the new exact lineage constraints were active.

The regression suite covers successful and failed streams, timeout enforcement, transport/rate-limit/protocol failures, stream ordering, version mismatch, stale capabilities, unsupported streaming/context limits, privacy routing, failed-attempt durability, exact same-request lineage, immutable benchmark-pair persistence, provider swap through unchanged Companion Core, and the full Stage 1/2 behavior.

Representative verification commands:

```powershell
$env:HAVRE_TEST_DATABASE_URL = 'postgresql://postgres@127.0.0.1:55432/<dedicated-test-database>'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m scripts.export_contract_schemas
.\.venv\Scripts\python.exe -m services.api.cli audit-provenance
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m compileall -q companion contracts identity mlsys scripts services tests
git diff --check
```

No database-backed test was skipped. The provenance integrity audit returned `[]`. The dedicated temporary databases are not application or personal databases; required handoff cleanup is limited to those exact verified targets and must restore PostgreSQL to its prior stopped state.

## Reproducible inference benchmark

The frozen base workload covers `scene_short`, `chat_standard`, `reflection_long`, and `extraction_structured`. The controlled comparison uses a counterbalanced concurrency order of `1, 2, 2, 1`, one warmup per case and two measured repetitions per case/schedule. Each final run therefore contains 16 warmups and 32 measured requests.

- Base workload content hash: `sha256:46f5a39afe751ec7378a586e08c89f3304362b7cb06a8a301f90795f9a6c9712`
- Controlled workload content hash: `sha256:26db3a3b8053d81564980406cda4c086eec4caafaa644d3b672b757dcfe5a49a`
- Analysis method: `havre-percentile-linear-v1`
- Runtime state hash: `sha256:2083cde656f37510b220cde668e71a5727e8ec2bd2561bc34aeb35f22b8ebec4`

### Immutable report identities

| Run | Systems report | Compatibility report | Workload / Stage 1 baseline manifest |
|---|---|---|---|
| 1 | ID `019ffae6-c8ef-7f63-8a6f-a38eaafc62a3`; `sha256:bae8a555e15068d299caf1da4cfaeedb01f30deeefbda85c742277da535382ad` | ID `019ffae6-e0bb-7318-b7dc-97f05a58e8f7`; `sha256:d44249588c6598a27a5e2b4670801a01c4ce9f5d46bddc985885f5d2aaf8090b` | `sha256:26db3a3b8053d81564980406cda4c086eec4caafaa644d3b672b757dcfe5a49a` / `sha256:833df755c35b2ebaebeaac431f374a46273398661bdc5dfa4ceb0a8fca5075f4` |
| 2 | ID `019ffae8-0253-7dfa-8019-e1d3ddf237fa`; `sha256:eca78f4f0d9564d107a0e455cba8ed4e89b09d526e7a2cda6c7da68af3f6985e` | ID `019ffae8-19a4-7535-9c66-1b55808da428`; `sha256:bc92d456bb6045c5ec3154c00d2a54605421b40725cfbef655582291c21a4b96` | `sha256:26db3a3b8053d81564980406cda4c086eec4caafaa644d3b672b757dcfe5a49a` / `sha256:833df755c35b2ebaebeaac431f374a46273398661bdc5dfa4ceb0a8fca5075f4` |

The four content-hash-verified artifacts for each run are available in [final run 1](../evals/reports/stage3_20260813_final_run1/) and [final run 2](../evals/reports/stage3_20260813_final_run2/). They are SHA-256 content-hash verified, not digitally signed.

### Systems results

Both runs completed **32/32 measured requests with zero errors**. Values below are p50 / p95 for each counterbalanced schedule block; VRAM is p95 GiB.

| Run / schedule | Concurrency | req/s | output tok/s | E2E ms | TTFT ms | TPOT ms/token | GPU % | VRAM GiB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Run 1 / A | 1 | 0.657 | 80.519 | 1,345.487 / 3,248.121 | 38.129 / 70.680 | 11.779 / 12.473 | 95.0 / 96.0 | 5.760 |
| Run 1 / A | 2 | 0.894 | 109.543 | 1,697.675 / 3,682.721 | 88.751 / 159.803 | 14.157 / 15.059 | 94.0 / 95.3 | 5.760 |
| Run 1 / B | 2 | 0.900 | 110.210 | 1,673.419 / 3,664.317 | 87.166 / 140.484 | 14.269 / 14.803 | 94.0 / 95.3 | 5.760 |
| Run 1 / B | 1 | 0.651 | 79.692 | 1,365.849 / 3,277.520 | 39.659 / 72.253 | 11.938 / 12.571 | 95.0 / 95.65 | 5.760 |
| Run 2 / A | 1 | 0.647 | 79.198 | 1,372.625 / 3,294.833 | 42.130 / 73.597 | 12.004 / 12.626 | 94.5 / 95.65 | 5.760 |
| Run 2 / A | 2 | 0.887 | 108.674 | 1,739.967 / 3,744.987 | 92.007 / 137.494 | 14.640 / 20.782 | 93.0 / 95.0 | 5.760 |
| Run 2 / B | 2 | 0.905 | 110.867 | 1,701.738 / 3,690.091 | 85.739 / 132.546 | 14.315 / 14.924 | 93.0 / 95.3 | 5.760 |
| Run 2 / B | 1 | 0.661 | 81.030 | 1,337.760 / 3,236.761 | 38.755 / 74.229 | 11.702 / 12.400 | 95.0 / 95.65 | 5.760 |

On this exact workload and host, concurrency 2 raised aggregate request/output-token throughput by roughly 37% while increasing per-request median E2E latency and TPOT. This is a measured local trade-off, not a universal capacity claim or a selected production setting.

### Behavioral compatibility observations

The Stage 1 deterministic provider and Stage 3 candidate both traversed the same typed workload contract. These checks are descriptive; there is no human-approved quality rubric or binding threshold in Stage 3.

| Workload | Candidate observation in both compatibility runs |
|---|---|
| `scene_short` | completed; non-empty; 10 output tokens |
| `chat_standard` | completed; non-empty; 128 output tokens |
| `reflection_long` | completed; non-empty; 256 output tokens; requested JSON object was **not parseable** |
| `extraction_structured` | completed; non-empty; 96 output tokens; requested JSON object was **not parseable** |

The serial compatibility outputs had identical candidate content hashes across both final runs. The concurrency-2 systems samples did **not** remain content-identical at temperature zero: five of 16 like-for-like samples changed across runs, and chat, reflection, and structured-extraction cases produced multiple content hashes while the short scene case stayed stable. All 16 matched concurrency-1 samples were stable. The benchmark records that nondeterminism instead of hiding it.

Both compatibility reports explicitly record `binding_evaluation = false` and `gate_status = not_evaluated`. No personalized production release or quality approval follows from these observations.

## Operational commands

Prepare and verify the pinned runtime once, then start it with health, metrics, and SSE startup checks:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\scripts\setup_stage3_local_serving.ps1
.\scripts\start_stage3_local_serving.ps1
```

Point the unchanged Companion runtime at the local provider and run the evidence paths:

```powershell
$env:HAVRE_DATABASE_URL = 'postgresql://postgres@127.0.0.1:55432/<dedicated-database>'
$env:HAVRE_PROVIDER_ID = 'self-hosted-openai-compatible'
$env:HAVRE_SELF_HOSTED_BASE_URL = 'http://127.0.0.1:8080'

.\.venv\Scripts\python.exe -m services.api.cli migrate
.\.venv\Scripts\python.exe -m services.api.cli demo --privacy LOCAL_ONLY
.\.venv\Scripts\python.exe -m services.api.cli evidence 019ffae5-7832-7921-b0d5-18f3e7324b54
.\.venv\Scripts\python.exe -m services.api.cli benchmark-inference --output-directory var/benchmarks/stage3-inference
```

Stop only the process proven to be the pinned Stage 3 executable:

```powershell
.\scripts\stop_stage3_local_serving.ps1
```

The stop script checks the PID and executable path before terminating anything. Runtime binaries, weights, PID files, and operational logs live under ignored `.runtime/stage3`; private request content is not written by llama.cpp request logging.

## Known limits kept inside Stage 3

- One 8B model, one quantization, one serving-engine version, one laptop GPU, and a small synthetic workload establish a reproducible baseline only. They do not establish broad conversational, safety, or production quality.
- The real request proves the permanent chain can use a real local model and retain exact evidence. It does not prove the response was helpful or that the model reliably follows HAVRE's long-term behavioral goals.
- Structured JSON failed in both long-reflection and extraction compatibility cases. Structured extraction is not ready to activate from this evidence.
- Concurrency 2 improved aggregate throughput but introduced output nondeterminism and higher per-request latency. No concurrency setting has been promoted as a production default.
- Current outward API/CLI delivery is completion-based even though provider transport streams internally.
- This is a local developer runtime, not deployment automation: there is no TLS, authentication, service manager, backup/restore runbook, or separated production database-role model.
- The provider is loopback-only and was exercised with `LOCAL_ONLY`; no cloud provider or external data transfer was added.
- Existing Stage 2 retrieval quality limits remain. A real model can now consume admitted ContextPack memory, but that does not improve or validate retrieval correctness.
- Publishing to the filesystem uses an atomic directory rename, and persisting the two database report rows uses one database transaction, but there is no transaction spanning both stores. A database failure after file publication can leave a valid file-only report directory that requires explicit reconciliation; the CLI surfaces the failure rather than claiming both stores succeeded.
- Proactive architecture remains inactive. No Stage 4 User Model or later-stage capability was implemented.

## Cleanup and stop boundary

After evidence capture, the verified llama.cpp process was stopped, the three exact dedicated Stage 3 temporary databases were removed after validating their names, generated `var/benchmarks` working directories were removed after their final artifacts were copied and revalidated, and the local PostgreSQL cluster was restored to its prior stopped state. Runtime binaries and weights remain under ignored `.runtime/stage3` so their multi-gigabyte pinned downloads do not enter Git. The eight canonical benchmark artifacts remain in the two linked report directories; the paired database rows were persisted and queried before the disposable evidence database was removed.

## Owner decision and stop boundary

At the time of this historical checkpoint, Stage 3 implementation and verification were complete but still awaited Product Owner review. The later correction checkpoint was approved at the exact source snapshot recorded above. The candidate Qwen/llama.cpp baseline has **not** been promoted to a personalized production release, and its non-binding quality gate remains unevaluated.

**The historical review gate is superseded by the accepted correction checkpoint. Stage 4 remains unauthorized.** Do not implement User Model inference or any Stage 4 capability without separate explicit Product Owner authorization.
