# GPT route and local capacity recovery — 2026-09-05

## Scope and incident

The owner reported that the previous no-reply repair had not restored their chat
and that GPT was no longer usable. The previous checkpoint verified orphan-request
recovery and HTTP readiness, not an owner retry receiving a GPT answer. That
verification was insufficient to claim the end-to-end issue fixed.

The 14:18:41 America/Chicago retry (`01a07302-3d6e-7aa5-be6d-67719db81cad`)
was NORMAL and cloud eligible. Its selected ContextPack was NORMAL but not cloud
eligible, so the router selected Qwen with `cloud_ineligible_local_route`; GPT
was never called. Qwen then returned HTTP 400. No assistant Event was committed.
Personal message text is intentionally omitted from this checkpoint.

Three linked defects were reproduced:

1. A recent daily-review quality flag was automatically selected as a standing
   response instruction. Its source-qualified review run was cloud-ineligible,
   contaminating otherwise eligible ordinary chat. This selection conflicted with
   the owner's later request for suggestion files to hand to Codex manually.
2. Local provider construction advertised the profile's total 8,192-token capacity
   as per-request capacity, although `--parallel 2` gives each slot 4,096. The live
   `/props` and `/v1/models` both reported 4,096. Applying the pinned chat template
   and tokenizer to the saved failed ContextPack produced 4,692 prompt tokens;
   a local-only diagnostic reproduced `exceed_context_size_error` at 4,096.
3. The streaming adapter classified the HTTP error before reading its body. A
   genuinely unread streaming response therefore lost the context-overflow code
   and became a generic `invalid_request`.

## Correction

- Daily quality flags and suggestions remain review artifacts and local files;
  neither route automatically injects them as chat instructions. Existing reviews,
  private references, policies, explicit owner feedback, and delegated grounded
  Memory/User Model updates remain intact. No source is reclassified or erased.
  ADR-0034/0035 document the later manual-review workflow supersession; formal
  acceptance remains pending.
- Production and inference-benchmark construction share the exact per-slot capacity
  calculation. Both the generated system manifest and provider now declare 4,096.
  Local reply reserve remains 1,024. The pinned manifest, total allocation, two
  slots, model weights, adapter-null binding, engine, and loopback endpoint are
  unchanged. Required context that cannot fit still fails closed, never to cloud.
- Streaming HTTP errors are read before the existing safe typed classifier runs.
  Provider response text is not exposed or retained as a new error artifact.
- No migrations or active contract schemas changed. Head remains 0067. No retries
  are sent automatically and no real conversation is used as a synthetic test.

## Verification

Dedicated disposable PostgreSQL database:
`havre_gpt_route_repair_test_20260905`, fresh migrations 0001–0067.

- Regression demonstrated failure before repair for automatic review injection and
  a truly unread streaming context error, then passed after repair.
- The NORMAL/cloud-ineligible review regression completes a GPT turn after the
  review, verifies the stored review policy/result are unchanged, and proves
  local-session text is absent from the GPT request. Existing privacy truth-table,
  no-cross-provider-fallback, and source-erasure fixture tests remain active.
- Full primary regression: 734 passed in 79.556 seconds; pinned Torch regression:
  62 passed in 47.310 seconds, zero
  skipped database tests. Logs: `var/gpt-route-repair-primary-final.log` and
  `var/gpt-route-repair-torch-tests.log`.
- Real ChatGPT-authenticated Codex CLI 0.153.0 / GPT-5.6-sol / medium generated and
  durably committed an isolated PUBLIC synthetic response in 6,447.652 ms.
- The actual `/v1/interactions/stream` ASGI endpoint, production provider factory,
  Core, and PostgreSQL completed two isolated synthetic requests: NORMAL to GPT
  (`01a0731f-3b26-79cf-82cc-fe889e332ea0`, 5,774.237 ms), and LOCAL_ONLY to Qwen
  (`01a0731f-530e-715b-9e84-85b8401c3d3f`, 893.328 ms). Both returned NDJSON
  completed events and durable assistant Events. This was not a stub or login-only
  test. It did not traverse the physical iPhone/tailnet.
- Checked-in controlled inference workload: 16 warmup and 32 measured local samples;
  all 32 measured samples completed, error rate zero at concurrency 1 and 2. Runtime
  b10405, unadapted Qwen3-8B Q4_K_M; system manifest context_limit=4096. Reports:
  `var/benchmarks/gpt-route-repair-inference/`. Compatibility is descriptive,
  `binding_evaluation=false`, `gate_status=not_evaluated`, not quality acceptance.
  An intermediate inconsistent benchmark manifest was rejected; it was corrected,
  not bypassed. Recorded source snapshot:
  `sha256:cd04bb3f6b282681dd6cd05c2a024114bd51960656124808c4a9ad1b613c35b0`.
- Existing 12-case synthetic semantic-memory benchmark: multilingual MiniLM int8
  9/12 versus deterministic 4/12, zero irrelevant admissions; semantic p50 2.867 ms.
  This is a small synthetic check, not evidence of human-like complete recall.
- Test CLI provenance audit and production read-only provenance audit returned
  `[]`. PWA Node contract, pip check, compileall, and diff check passed.
- After the final full suite, the test CLI provenance audit again returned `[]`.
  The exact disposable database was dropped only after verifying zero connections;
  production remained present and PostgreSQL retained its initial running state.

## Production activation and boundary

The owner-local API and worker restarted at 2026-09-05 19:54:08 UTC / 14:54:08
America/Chicago using the existing verified hidden launchers. Recorded launcher
PIDs: API 24092, worker 39200. No active ordinary chat existed at restart. The
shared PostgreSQL server and exact pre-existing local model PID 49192 stayed up.
Readiness, settings, timeline, Memory, and Diary returned HTTP 200. Settings report
the default eligible route available as GPT-5.6-sol and the local route available
as Qwen3-8B, with no silent fallback. The PWA shell is unchanged at v13.

The real failed message's corrected personal-context selection contains no review
instruction or cloud-ineligible item; the original review remains NORMAL with
cloud_eligible=false. Both failed source requests remain historical failures,
with their USER_MESSAGE records present and no automatically created assistant
answer. The previously orphaned source hash is unchanged. Processing count was
zero and production provenance audit returned `[]` after restart.

Physical-iPhone retry, mobile perceived latency, recurring owner usefulness, and
broader long-context private conversation remain separate evidence boundaries.
No new contact cadence, privacy disclosure, training, model promotion, source
erasure, commit, push, or next-stage acceptance is authorized by this repair.
