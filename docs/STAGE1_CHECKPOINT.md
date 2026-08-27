# Stage 1 Checkpoint

Status: **Original acceptance run; superseded for approval purposes by the correction checkpoint**

Scope: **Permanent request-to-response vertical slice only**

The original evidence below remains valid as an infrastructure run. The later review found three approval blockers—unenforced timeout, unbound idempotency keys, and globally keyed identity versions—and missing coverage. Those issues are resolved and re-verified in [`STAGE1_CORRECTION_CHECKPOINT.md`](STAGE1_CORRECTION_CHECKPOINT.md), which is the current approval artifact.

## Acceptance result

One synthetic `PRIVATE` request was submitted through the live FastAPI endpoint with a W3C `traceparent` and an idempotency key. The API returned HTTP 201 only after the assistant event and its evidence were committed.

```text
request_id:             019ff712-4354-7ab5-a492-894941065b9d
trace_id:               8f92f3577b34da6a3ce929d0e0e47361
incoming parent span:   10f067aa0ba902b7
request root span:      74d7eb94ac72ddfe
user_event_id:          019ff712-4354-7ab8-b7d1-aa2a159d1289
context_pack_id:        019ff712-4366-704b-9ec6-55c14cb43245
route_decision_id:      019ff712-4366-704c-8e0d-bfe94bc2bd24
inference_response_id:  019ff712-4366-704f-a49b-81dd65e54bde
assistant_event_id:     019ff712-4366-7050-8701-7e3ae507a252
status:                 completed
```

The request, both events, Context Pack, route, inference attempt, and every span store the same `trace_id`. The assistant event names the user event as its direct cause.

## Stored events

### `USER_MESSAGE`

```json
{
  "event_id": "019ff712-4354-7ab8-b7d1-aa2a159d1289",
  "event_type": "USER_MESSAGE",
  "request_id": "019ff712-4354-7ab5-a492-894941065b9d",
  "trace_id": "8f92f3577b34da6a3ce929d0e0e47361",
  "privacy_class": "PRIVATE",
  "memory_eligible": true,
  "training_eligible": false,
  "cloud_eligible": true,
  "policy_version": "data-policy-v1",
  "policy_revision_id": "019ff712-4354-7ab7-b03d-b46d879dc7c5",
  "payload": {
    "channel": "api",
    "language": "en",
    "content_parts": [{
      "type": "text",
      "text": "I have been avoiding a difficult task. Help me choose one grounded next step while keeping the decision mine."
    }]
  },
  "content_hash": "sha256:2a380d882f8b2670c5c8b72be3035c19ab98d9cc17982121d0cd331a14fcb60a"
}
```

### Delivered `ASSISTANT_MESSAGE`

```json
{
  "event_id": "019ff712-4366-7050-8701-7e3ae507a252",
  "event_type": "ASSISTANT_MESSAGE",
  "request_id": "019ff712-4354-7ab5-a492-894941065b9d",
  "trace_id": "8f92f3577b34da6a3ce929d0e0e47361",
  "causation_event_id": "019ff712-4354-7ab8-b7d1-aa2a159d1289",
  "privacy_class": "PRIVATE",
  "memory_eligible": false,
  "training_eligible": false,
  "cloud_eligible": true,
  "policy_version": "data-policy-v1",
  "policy_revision_id": "019ff712-4366-704a-b4c8-344fa6ebf891",
  "payload": {
    "status": "completed",
    "content_parts": [{
      "type": "text",
      "text": "I’m here with you. We can separate what you know from what you’re inferring, then choose the smallest useful next step that remains yours."
    }],
    "context_pack_id": "019ff712-4366-704b-9ec6-55c14cb43245",
    "inference_response_id": "019ff712-4366-704f-a49b-81dd65e54bde",
    "delivery": {"channel": "api"}
  },
  "content_hash": "sha256:d365e708779164436357f64013ae0e0da251dbafcb32b1daca66ed98438f2b73"
}
```

The response inherits a new, separately identified, conservative policy snapshot derived from every required Context Pack section. No declassification or redaction occurred.

## Generated Context Pack

```json
{
  "context_pack_id": "019ff712-4366-704b-9ec6-55c14cb43245",
  "request_id": "019ff712-4354-7ab5-a492-894941065b9d",
  "trace_id": "8f92f3577b34da6a3ce929d0e0e47361",
  "builder_version": "context-builder-v1",
  "constitution_version_id": "constitution-v1",
  "identity_version_id": "identity-v1",
  "values_version_id": "values-v1",
  "token_budget": {
    "max_input_tokens": 4096,
    "reserved_output_tokens": 256,
    "estimator_id": "utf8-bytes-div4-v1",
    "target_tokenizer_version_id": "provider-neutral-estimator-v1"
  },
  "sections": [
    {
      "section_id": "identity",
      "estimated_tokens": 659,
      "source_refs": [
        "constitution/constitution-v1",
        "identity/identity-v1",
        "values/values-v1"
      ],
      "privacy_class": "PUBLIC",
      "selection_reason": "required_by_policy"
    },
    {
      "section_id": "current-user-input",
      "estimated_tokens": 28,
      "source_refs": ["event/019ff712-4354-7ab8-b7d1-aa2a159d1289"],
      "privacy_class": "PRIVATE",
      "selection_reason": "required_current_request"
    }
  ],
  "estimated_total_tokens": 687,
  "effective_privacy_class": "PRIVATE",
  "effective_memory_eligible": false,
  "effective_training_eligible": false,
  "effective_cloud_eligible": true,
  "effective_policy_revision_id": "019ff712-4366-704a-b4c8-344fa6ebf891",
  "content_hash": "sha256:ee5a768013234b967760146e627b3199cc2c7533b44e7e3cd4c79e1870d01b01"
}
```

The complete identity section is the exact content of the approved, content-hashed files in [`../identity/`](../identity/); it is not hidden prompt state. No memory, User Model, Scene, or intervention content exists in this pack.

## Provider and exact versions

```text
provider_id:            deterministic-local
provider_class:         local_test
execution_environment:  local
model_version_id:       deterministic-companion-v1
adapter_version_id:     deterministic-adapter-v1
tokenizer_version_id:   utf8-bytes-div4-v1
serving_config_version: deterministic-serving-v1
router_version:         stage1-single-provider-router-v1
context_builder:        context-builder-v1
```

`deterministic-local` is an intentionally simple local acceptance provider. It proves the permanent provider-neutral contract and privacy gate without sending data off-device; it is not presented as a conversational-quality production model.

## Measured metrics

| Measurement | Value | Source |
|---|---:|---|
| HTTP status | 201 | API ingress |
| Total request span | 30.747 ms | durable W3C-correlated span |
| Initial user-event persistence | 17.325 ms | durable span |
| Context build | 0.235 ms | durable span |
| Route decision | 0.031 ms | durable span |
| Provider client span | 0.055 ms | durable span |
| Provider-reported generation | 0.005 ms | normalized inference response |
| Delivered-response persistence | 12.637 ms | durable span |
| Estimated prompt/context tokens | 687 | `utf8-bytes-div4-v1` |
| Estimated output tokens | 36 | `utf8-bytes-div4-v1` |
| Estimated total tokens | 723 | normalized inference response |
| Stored spans | 6 | PostgreSQL |
| Stored events for request | 2 | PostgreSQL |
| Database size after acceptance run | 9510 kB | PostgreSQL `pg_database_size` |

Runtime versions: Windows 11, CPython 3.12.13, PostgreSQL 18.4, FastAPI 0.141.1, Pydantic 2.13.4, Psycopg 3.3.4. The provider health endpoint reported `healthy` with `deterministic-companion-v1` loaded. These are one local acceptance-run measurements, not throughput, quality, cost, or production latency claims.

## Components in plain English

- **API ingress:** validates a request, requires an idempotency key, and accepts or creates a standards-compatible trace.
- **DataPolicy:** gives every personal artifact an explicit privacy class plus separate memory, training, and cloud permissions. It fails closed on forbidden combinations.
- **Event ledger:** saves exactly what the user sent before model work starts, then appends an assistant event only for a response that will actually be returned. Ordinary updates and deletes are rejected.
- **Identity loader:** reads the owner-approved Constitution, Identity, and Values from version-controlled files, hashes them, and verifies their immutable approval records.
- **Context Builder:** constructs the exact provider input from required identity plus the current durable message, counts its budget, records every source, and computes the most restrictive effective policy.
- **Router:** checks hard privacy and provider-approval rules before selecting the only Stage 1 provider. It cannot weaken policy.
- **ModelProvider:** keeps HAVRE’s core independent from any provider SDK. The active local adapter returns the same normalized response shape a later approved model adapter must return.
- **PostgreSQL repository:** commits short, coherent units of work. The potentially slow provider call happens between transactions, so it never holds database locks.
- **Tracing and evidence:** correlates request, persistence, context, route, inference, and delivery with one trace while keeping raw message text out of span attributes.
- **Generated schemas and tests:** make the contracts machine-readable and verify both expected behavior and failure behavior against a real database.

## Test result and boundary

```text
Ran 21 tests in the original checkpoint
OK
```

The suite includes real PostgreSQL migration and interaction tests, event immutability, idempotent replay, cloud/privacy rejection, context budgeting, trace propagation, content-hash tamper detection, and provider-failure non-delivery.

Stage 2 work is absent. This checkpoint stops here until explicit Product Owner approval.
