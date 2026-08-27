# Database Design

Status: **Stage 6/7 second acceptance corrections technically verified at execution-source snapshot `sha256:8ba8b94632ae181c2966acc3d6c498d8f7a63337d2e8558629b47dd440386f9c`; pending Product Owner reacceptance**

Related decisions: [ADR-0002](adr/0002-postgresql-and-pgvector.md), [ADR-0003](adr/0003-append-oriented-events-and-erasure.md), [ADR-0004](adr/0004-provenance-and-derived-revisions.md), [ADR-0008](adr/0008-database-backed-worker-boundary.md), [ADR-0011](adr/0011-data-handling-policy.md), [ADR-0012](adr/0012-temporal-belief-model.md), [ADR-0013](adr/0013-scene-session-domain-object.md), [ADR-0014](adr/0014-governed-behavior-hierarchy.md), [ADR-0016](adr/0016-governed-core-authorizes-proactive-outreach.md), [ADR-0017](adr/0017-interruption-policy-and-user-control.md), [ADR-0018](adr/0018-provider-neutral-private-delivery.md), [ADR-0019](adr/0019-provider-neutral-ambient-life-context.md), and [ADR-0020](adr/0020-experience-memory-lifecycle.md)

## 1. Purpose

PostgreSQL is HAVRE's authoritative metadata and state store. pgvector adds vector retrieval without moving memory metadata and provenance into a separate authority. The database must preserve raw events, revision history, evidence, model/dataset lineage, evaluation results, and release state while permitting complete owner-controlled export and erasure.

This document defines the logical model. Stage 1 migrations should implement only the first activation slice listed in section 13.

## 2. Data principles

1. **Raw before derived.** Commit source events before deriving memories, beliefs, summaries, training examples, or metrics from them.
2. **Ordinary writes append.** New facts and interpretations create new records or revisions. They do not rewrite history in place.
3. **Derived records are revisable.** Retraction and supersession are normal states, not exceptional data loss.
4. **Provenance is queryable.** Important derived records link to evidence with typed relationships and the transform version that created them.
5. **Versions are immutable.** Dataset snapshots, model versions, adapter versions, evaluation runs, benchmark runs, and release manifests are never edited after finalization; lifecycle status changes are separate transitions.
6. **Private content is not telemetry.** Traces reference protected records and store measurements; they do not duplicate raw message text by default.
7. **Deletion outranks append-only.** “Permanent” means durable across model and algorithm changes until the owner requests erasure or a configured retention rule applies.
8. **Large artifacts are external.** Audio, images, model weights, adapters, raw benchmark logs, and exports use private object/file storage with database URI and content hash.
9. **Privacy and use are explicit.** Relevant personal records resolve a versioned privacy classification and independent memory, training, and cloud eligibility. Training is denied by default; `LOCAL_ONLY` can never be cloud eligible.
10. **Time has multiple meanings.** Event time, system learning time, revision creation time, real-world validity time, and lifecycle transition time are stored separately rather than collapsed into one timestamp.
11. **Collection is minimized before persistence.** A canonical life-context observation is the earliest retained source evidence; device-native raw material is not centralized by default.
12. **Missingness is data quality, not user state.** Source health, coverage, freshness, permission, and clock quality remain explicit and cannot silently become negative evidence.

## 3. Common conventions

- Identifiers: application-generated UUIDv7 where available; UUID uniqueness is the contract, chronological ordering is an optimization.
- Time: `timestamptz`, stored in UTC. Preserve a source timezone or offset when human interpretation depends on local time.
- Names: `snake_case`; plural table names; explicit foreign-key names in migrations.
- JSON: `jsonb` only for versioned variable payloads or provider metadata, not as a substitute for relational fields needed for constraints or queries.
- Confidence: numeric value in `[0, 1]`, always paired with its method/version and never presented as objective probability unless calibrated.
- Hashes: algorithm-qualified strings such as `sha256:<hex>` over canonical bytes.
- Version strings: opaque stable identifiers, not floating tags such as `latest`.
- Optimistic concurrency: mutable head/projection tables use a revision or `updated_at` precondition.
- Secrets: never stored in ordinary application tables or event payloads.

Every owner-scoped table includes `owner_id`, even though HAVRE initially serves one person. This is a data-ownership boundary, not a plan to build a multi-tenant SaaS product.

## 4. Logical data map

```text
owners
  |
  +-- sessions -- scene_sessions -- scene_records
  |
  +-- events -----------------------------+
  |      |                                |
  |      +-- provenance_edges ------------+--> derived revisions
  |                                       |      memories
  |                                       |      user beliefs
  |                                       |      patterns/progress
  |                                       |      training examples
  |                                       |
  |                                       +--> dataset snapshots
  |
  +-- goals / current_state_snapshots
  +-- context_sources -- context_source_capabilities
  |       |-- context_consent_scope_revisions
  |       |-- context_source_health_records
  |       +-- life_context_observations -> events/provenance
  +-- proactive_triggers -- proactive_proposals -- interruption_decisions
  |                              |
  |                              +-- proactive_renderings -- delivery_attempts
  |                              +-- proactive_response_links
  +-- proactive_preference_revisions
  +-- data_policy_revisions
  +-- traces / spans
  +-- evaluation and benchmark runs
  +-- release manifests / deployments

constitution_versions -> identity_versions -> policy_versions
model_versions <-- adapter_versions <-- training_runs <-- dataset_snapshots
```

## 5. Identity and interaction tables

### `owners`

| Column | Type | Rule |
|---|---|---|
| `owner_id` | UUID PK | Stable data owner identifier |
| `display_name` | text nullable | Private presentation value |
| `locale` | text | BCP 47-style language tag |
| `timezone` | text | IANA timezone name |
| `created_at` | timestamptz | Server time |
| `erasure_requested_at` | timestamptz nullable | Blocks new processing once set |

Authentication identities should live in a separate table so changing an auth provider does not change `owner_id`.

### `constitution_versions`

Stores the highest-authority, human-approved package of core principles. Required fields are `constitution_version_id`, semantic version, content hash, source revision, created/effective timestamps, superseded version, approval record, and change reason. No worker, reflection, model, or training process may create an effective Constitution version.

### `identity_versions`

Stores the identity package included in releases.

| Column | Type | Rule |
|---|---|---|
| `identity_version_id` | UUID PK | Immutable version |
| `constitution_version_id` | UUID FK | Required higher-layer authority |
| `semantic_version` | text unique | Human-readable release version |
| `content_hash` | text unique | Hash of canonical identity files |
| `source_revision` | text | Repository commit or snapshot |
| `effective_at` | timestamptz | Activation time |
| `supersedes_id` | UUID nullable | Prior identity version |
| `change_reason` | text | Human-approved reason |
| `approval_record_id` | UUID FK | Explicit human approval |

Identity files remain reviewable in the repository; this table records what a deployed release actually used.

Stage 1 uses a unified physical `identity_artifact_versions` table for Constitution, Identity, and Values. Its primary key is `(owner_id, artifact_version_id)`: human-readable version names may be stable across owners, but content, approvals, Context Pack references, and activation are owner-scoped. Every personal-artifact relationship uses an owner-qualified foreign key.

### `sessions`

Groups conversational continuity without pretending that a session is the full lifetime relationship.

| Column | Type | Rule |
|---|---|---|
| `session_id` | UUID PK | Stable session |
| `owner_id` | UUID FK | Required |
| `channel` | text | `web`, `ios`, `api`, `import`, or future registered value |
| `started_at` | timestamptz | Required |
| `ended_at` | timestamptz nullable | Projection; closing is also an event |
| `metadata` | jsonb | Non-secret, schema-versioned channel metadata |

### `approval_records`

Append-only approvals for material Constitution, identity/value, safety/intervention-policy, and personalized-release changes. Each record identifies the exact proposed artifact hash/version, decision (`approved` or `rejected`), human actor, time, scope, rationale, and any expiry/conditions. Approval cannot be inferred from a model score or deployment status.

### `scene_sessions`

| Column | Type | Rule |
|---|---|---|
| `scene_session_id` | UUID PK | Stable first-class Scene Session |
| `owner_id` | UUID FK | Required |
| `opened_session_id` | UUID owner-qualified FK | Session that opened it |
| `scene_type` | text | Registered taxonomy value |
| `situation` | jsonb | Versioned situation/context known at planning time |
| `planned_goal` | jsonb | User-owned objective and minimum-success definition |
| `anticipated_triggers` | jsonb | Versioned trigger hypotheses with uncertainty |
| `phase` | text | `before`, `during`, `after`, `closed` |
| `status` | text | `planned`, `active`, `paused`, `completed`, `abandoned`, `cancelled` |
| `planned_start_at` | timestamptz nullable | Optional intended start |
| `started_at` | timestamptz nullable | Actual start |
| `ended_at` | timestamptz nullable | Required when closed |
| `revision` | integer | Optimistic concurrency for projection |
| DataPolicy snapshot columns | typed fields | Exact privacy/use decision; training remains false |

The event ledger remains the lifecycle authority; `scene_sessions` is a first-class current projection. It is not reducible to a chat session and may span multiple conversational sessions or low-bandwidth device interactions.

### `scene_records`

Append-oriented ordered records that form the long-term chain:

```text
Situation -> Intervention -> Real-world Action -> Outcome -> Reflection
```

| Column | Type | Rule |
|---|---|---|
| `scene_record_id` | UUID PK | Immutable record identity |
| `scene_session_id` | UUID FK | Required |
| `record_type` | text | `signal`, `intervention`, `action`, `outcome`, `reflection` |
| `occurred_at` | timestamptz | Real-world occurrence time |
| `recorded_at` | timestamptz | Time HAVRE learned/recorded it |
| `event_id` | UUID owner-qualified FK | Exact raw/lifecycle event |
| `artifact_kind` / `artifact_id` / `artifact_revision` | typed reference | Policy decision, reflection, or other derived artifact |
| `causal_predecessor_id` | UUID nullable FK | Explicit prior Situation/Intervention/Action record when known |
| `sequence_number` | integer | Stable order within one Scene Session |
| DataPolicy snapshot columns | typed fields | Exact privacy/use decision inherited for this record |

An intervention links to its policy decision and delivered assistant event; an action/outcome remains a report with source and uncertainty. Partial or abandoned Scene Sessions are retained as truthful outcomes, not forced into “completed.”

## 6. Event ledger

The normative event envelope and type rules are in [`EVENT_MODEL.md`](EVENT_MODEL.md).

### `events`

| Column | Type | Rule |
|---|---|---|
| `event_id` | UUID PK | Idempotent event identity |
| `owner_id` | UUID FK | Required |
| `event_type` | text | Registered type |
| `event_version` | integer | Payload schema version for this type |
| `occurred_at` | timestamptz | When the represented occurrence happened |
| `recorded_at` | timestamptz | Database ingestion time |
| `actor_type` | text | `user`, `companion`, `system`, `tool`, `external` |
| `source` | text | Concrete ingress or producer |
| `payload` | jsonb | Type/version validated before insert |
| `session_id` | UUID nullable FK | Conversational grouping |
| `scene_session_id` | UUID nullable FK | First-class Scene Session grouping |
| `request_id` | UUID nullable | Application request correlation |
| `trace_id` | char(32) | W3C trace identifier; required |
| `causation_event_id` | UUID nullable FK | Direct domain cause when singular |
| `idempotency_key` | text nullable | Unique per owner + source where supplied |
| `privacy_class` | text | `PUBLIC`, `NORMAL`, `PRIVATE`, `HIGHLY_PRIVATE`, or `LOCAL_ONLY` |
| `memory_eligible` | boolean | Independent policy snapshot at ingestion |
| `training_eligible` | boolean | Independent explicit training permission; defaults false |
| `cloud_eligible` | boolean | Independent cloud-processing permission |
| `data_policy_version` | text | Policy resolver version used at ingestion |
| `data_policy_revision_id` | UUID nullable FK | Later explicit policy decision when one exists |
| `content_hash` | text | Integrity/dedup aid, not an authentication mechanism |

No `updated_at` exists. Ordinary SQL roles receive `SELECT` and `INSERT`, not `UPDATE` or `DELETE`. Privileged erasure/repair procedures are separately audited.

Indexes begin with:

- `(owner_id, recorded_at desc, event_id desc)`
- `(owner_id, event_type, occurred_at desc)`
- `(trace_id)`
- `(session_id, occurred_at)` where not null
- `(scene_session_id, occurred_at)` where not null
- unique `(owner_id, source, idempotency_key)` where `idempotency_key is not null`

Time partitioning is deferred until measured table size or maintenance duration justifies it. The key shape is chosen so partitioning remains possible.

### `data_policy_revisions`

Privacy policy belongs to HAVRE, not a provider adapter. Each relevant source or derived artifact either contains an immutable policy snapshot or references this append-oriented policy history.

| Column | Type | Rule |
|---|---|---|
| `data_policy_revision_id` | UUID PK | Immutable decision |
| `owner_id` | UUID FK | Required for personal data |
| `subject_kind` / `subject_id` / `subject_revision` | typed reference | Exact event, memory, belief, context item, example, artifact, or Scene Session |
| `privacy_class` | text | `PUBLIC`, `NORMAL`, `PRIVATE`, `HIGHLY_PRIVATE`, `LOCAL_ONLY` |
| `memory_eligible` | boolean | May this source feed memory creation? |
| `training_eligible` | boolean | May this source feed training construction? |
| `cloud_eligible` | boolean | May content be disclosed to an approved cloud processor? |
| `policy_version` | text | Resolver/rule version |
| `decided_by` | text | Owner, approved import policy, or constrained system rule |
| `decision_event_id` | UUID FK | Audit/consent/correction event |
| `reason_code` | text | Owner-visible reason |
| `effective_at` | timestamptz | Policy decision time |
| `supersedes_id` | UUID nullable FK | Previous policy revision |

Invariants:

- `LOCAL_ONLY` requires `cloud_eligible = false` at the database and domain layers.
- `training_eligible` defaults false and is never inferred from `memory_eligible` or `cloud_eligible`.
- A derived artifact's effective policy is at least as restrictive as every source unless an explicit owner-approved policy revision documents a narrower declassification scope.
- Context Packs copy the resolved policy of each selected item and compute pack-level `cloud_eligible` with logical AND.
- A cloud route is forbidden when any required item is not cloud eligible.

## 7. Provenance

### `provenance_edges`

This is the common evidence graph for important derived artifacts.

| Column | Type | Rule |
|---|---|---|
| `provenance_edge_id` | UUID PK | Immutable edge |
| `owner_id` | UUID FK | Same owner as both ends |
| `source_kind` | text | `event`, `memory_revision`, `belief_revision`, `goal`, `dataset_example`, etc. |
| `source_id` | UUID | Stable source identifier |
| `source_revision` | integer nullable | Exact revision when applicable |
| `source_event_id` | UUID generated nullable | Typed event source; owner-qualified FK |
| `source_memory_id` | UUID generated nullable | Typed memory source; paired with revision and owner-qualified FK |
| `source_memory_revision` | integer generated nullable | Exact typed memory source revision |
| `derived_kind` | text | Destination artifact kind |
| `derived_id` | UUID | Destination identifier |
| `derived_revision` | integer nullable | Exact destination revision |
| `relation` | text | `supports`, `contradicts`, `derived_from`, `summarizes`, `supersedes`, `evaluates` |
| `weight` | numeric nullable | Method-specific evidence weight in `[0,1]` |
| `transform_name` | text | Extractor/consolidator/human process |
| `transform_version` | text | Immutable version |
| `created_event_id` | UUID FK | Lifecycle event that asserted the edge |
| `trace_id` | char(32) | Creation trace |
| `created_at` | timestamptz | Required |

The public polymorphic source contract remains `source_kind/source_id/source_revision`, but Stage 2 migration `0004` projects its active event and memory-revision variants into generated typed columns. Owner-qualified foreign keys therefore reject missing and cross-owner sources synchronously. Additive Stage 4 migration `0012` also requires at commit that every belief revision has supporting provenance and that each consolidation, Current State, and Goal-progress evidence snapshot exactly matches its owner-qualified edges. The provenance audit unions broken endpoints with missing/mismatched required Stage 4 edges; a nonempty result is an operational failure. Future source kinds must add equivalent typed enforcement before activation.

Provenance is not the same as tracing:

- provenance answers **which evidence supports this claim?**
- tracing answers **how did this execution produce or use it?**

## 7A. Proposed Ambient Life Context records

These contracts are accepted under ADR-0019. Stage 6 activates only synthetic/manual typed contracts; external adapters remain separately gated Stage 11/12 work.

### `context_sources`

One owner/device-bound source instance, with stable `source_instance_id`, source kind/provider, device identity reference, adapter and source versions, enrollment/disabled state, created/disabled events, and last known health reference. Credentials and provider tokens do not live in this table.

### `context_source_capabilities`

Versioned narrow capabilities for a source instance. Each row declares a registered capability identifier, allowed observation kinds/schema versions, supported precision/fields, poll/push/user-initiated modes, source limitations, and adapter conformance version. A broad device registration grants no capability by itself.

### `context_consent_scope_revisions`

Immutable owner decisions with a current-head projection. Required material includes source/capability, permitted observation kinds and fields/precision, named purpose, local processing, permitted destinations, SamplingPolicy, RetentionPolicy, default DataPolicy, effective/expiry time, revocation state/reason, and exact decision Event. OS/provider permission is evidence, not a substitute for this scope.

### `life_context_observations`

Canonical minimized observations linked one-to-one to a `LIFE_CONTEXT_OBSERVED` Event when activated:

| Column | Rule |
|---|---|
| `observation_id`, `owner_id` | Stable identity and owner isolation |
| `source_instance_id`, `capability_id`, `adapter_version` | Exact provider/device translation lineage |
| `observation_kind`, `schema_version` | Registered bounded taxonomy and payload contract |
| `occurred_from`, `occurred_to`, `source_observed_at`, `ingested_at` | Real-world interval, source clock, and trusted Core time remain separate |
| `expires_at` | Limits current-state eligibility; not deletion time |
| `value` | Strict kind/version payload containing only approved fields |
| `measurement_quality`, `clock_quality`, `limitations` | Source observation quality, not interpretation confidence |
| `consent_scope_revision_id`, `sampling_policy_version`, `retention_policy_version` | Exact allowed collection/use contract |
| `event_id`, `trace_id`, `idempotency_key`, `content_hash` | Durable event, execution, retry, and integrity bindings |
| DataPolicy snapshot columns | Provider-independent privacy/use policy; training remains false by default |

Ordinary roles cannot update/delete observation content. Source correction appends invalidation/replacement events. Retention expiry and owner erasure use the privileged provenance-closure path.

### `context_source_health_records`

Immutable versioned transitions or policy-required samples with source/capability, `unknown | healthy | degraded | stale | offline | permission_revoked | unsupported`, checked time, last successful observation and coverage interval, expected next observation when meaningful, clock quality, coverage gaps, safe error category, adapter/source versions, trace, and content-free hash. A current projection may point to the latest record. Poll heartbeats remain operational telemetry unless policy requires durable evidence.

Use-specific freshness is computed from observation times, health, and an exact freshness-policy version. The result (`fresh | aging | stale | expired | unknown`) is stored with a state-estimation/trigger input snapshot when it affects a derived decision; it is not an unversioned boolean on the source row.

## 8. Derived companion state

### `memory_revisions`

| Column | Type | Rule |
|---|---|---|
| `memory_id` | UUID | Stable memory identity |
| `revision` | integer | Composite PK with `memory_id` |
| `owner_id` | UUID FK | Required |
| `memory_class` | text | `working`, `episodic`, `semantic`, `pattern`, `progress` |
| `content` | jsonb | Class-specific, schema-versioned content |
| `content_text` | text | Canonical retrieval/rendering text |
| `confidence` | numeric | `[0,1]` with method metadata |
| `importance` | numeric | `[0,1]`; policy version required |
| `status` | text | `candidate`, `active`, `superseded`, `retracted` |
| `valid_from` | timestamptz nullable | Time the statement is believed to apply |
| `valid_to` | timestamptz nullable | End of applicability, not deletion |
| `created_at` | timestamptz | Required |
| `created_by` | text | Human or transform identity |
| `transform_version` | text | Required for machine-derived revisions |
| `supersedes_revision` | integer nullable | Prior revision |
| `trace_id` | char(32) | Creation trace |
| `data_policy_revision_id` | UUID FK | Effective privacy/use policy |

An active-head view resolves the current revision. Historical revisions stay immutable.

An Event is experience; a memory row exists only after explicit promotion. `memory_eligible = true` is a use permission, not a write command. The final lifecycle includes class-specific candidate/promotion decisions, current applicability, contradiction/counter-evidence, supersession, retraction, archival, reconsolidation, and regeneration. These are future revision/transition records rather than in-place edits. Relevance decay belongs to the retrieval result/policy evidence and never mutates stored confidence, validity, retention, or status. The active Stage 2/4 schema implements only the subset described in `docs/STATE.md`; broader lifecycle fields/transitions wait for an authorized Stage 7 migration.

### `memory_embeddings`

| Column | Type | Rule |
|---|---|---|
| `memory_id` | UUID | Source memory |
| `memory_revision` | integer | Exact content revision |
| `embedding_version_id` | UUID | Embedding model/config version |
| `chunk_index` | integer | Supports future chunking |
| `embedding` | vector | Dimension fixed by an embedding-version-specific table/index strategy |
| `content_hash` | text | Must match embedded canonical text |
| `created_at` | timestamptz | Required |

Re-embedding inserts another version; it never overwrites prior vectors. If embedding dimensions diverge, use version-specific tables or columns rather than unsafe padding.

### `user_belief_revisions`

| Column | Type | Rule |
|---|---|---|
| `belief_id` | UUID | Stable belief identity |
| `revision` | integer | Composite PK |
| `owner_id` | UUID FK | Required |
| `belief_key` | text | Stable semantic key where possible |
| `statement` | text | Qualified, falsifiable language |
| `belief_type` | text | Fact, preference, value, strength, vulnerability, pattern, uncertainty |
| `confidence` | numeric | `[0,1]` |
| `confidence_method` | text | Versioned method or `human` |
| `initial_status` | text | `candidate` or `active`; later state comes from transitions |
| `evidence_occurred_from` | timestamptz nullable | Earliest underlying source occurrence summarized by this revision |
| `evidence_occurred_to` | timestamptz nullable | Latest underlying source occurrence summarized by this revision |
| `learned_at` | timestamptz | When HAVRE received the evidence that caused this revision |
| `valid_from` | timestamptz nullable | When the claim is considered applicable in the user's life |
| `valid_to` | timestamptz nullable | End of that applicability when known at creation |
| `supersedes_revision` | integer nullable | Prior revision |
| `created_at` | timestamptz | When this immutable revision was persisted |
| `trace_id` | char(32) | Creation trace |
| `data_policy_revision_id` | UUID FK | Effective privacy/use policy |

Supporting and counter-evidence are `provenance_edges` with `supports` and `contradicts`. Confidence changes require a new revision and reason; a short-lived Current State cannot directly overwrite a belief.

### `belief_revision_transitions`

Append-only lifecycle facts for a specific immutable belief revision:

| Column | Type | Rule |
|---|---|---|
| `belief_transition_id` | UUID PK | Immutable transition |
| `belief_id` / `belief_revision` | composite FK | Exact revision |
| `transition_type` | text | `activated`, `counter_evidence_recorded`, `contradicted`, `superseded`, `retracted`, `invalidated` |
| `occurred_at` | timestamptz | When the lifecycle change is considered to have happened |
| `recorded_at` | timestamptz | When HAVRE learned/recorded it |
| `reason` | text | Owner-visible explanation |
| `causing_event_id` | UUID FK | Source/lifecycle event |
| `replacement_belief_id` / `replacement_revision` | nullable reference | Successor when applicable |

This yields bitemporal queries: “what did HAVRE know as of time X?” uses `created_at`/transition `recorded_at`; “what period of the user's life did the claim describe?” uses `valid_from`/`valid_to`; source event `occurred_at` shows when the underlying experience happened. Historical beliefs are never overwritten.

The active `0009` projection guard does not infer transition freshness from a
comparison between application and database clocks. Each head update names one
immutable owner/belief/revision-qualified transition ID, and an immutable
consumption row makes that identity single-use. PostgreSQL assigns belief
revision creation time, transition recording time, and default replay cutoffs.

### `current_state_snapshots`

| Column | Type | Rule |
|---|---|---|
| `state_snapshot_id` | UUID PK | Immutable estimate |
| `owner_id` | UUID FK | Required |
| `scene_session_id` | UUID nullable FK | Optional first-class Scene Session scope |
| `state` | jsonb | Versioned dimensions and uncertainty |
| `estimated_at` | timestamptz | Required |
| `expires_at` | timestamptz | Required |
| `estimator_version` | text | Required |
| `trace_id` | char(32) | Required |
| `data_policy_revision_id` | UUID FK | Effective privacy/use policy |

### `goals`

Goals are mutable projections with all meaningful changes also represented as
events. For every update, the immutable lifecycle event stores the complete
canonical new projection and its content hash. The database validates every
field and digest and assigns `updated_at` from the same statement timestamp, so
neither the hash nor the projection time is caller-forgeable. Application
updates preserve an omitted nullable field but treat explicit `null` as a
request to clear `next_action` or `review_at`.

Required fields include `goal_id`, `owner_id`, `track`, `title`, `why`, `priority`, `status`, `next_action`, `review_at`, `revision`, `created_at`, `updated_at`, and `data_policy_revision_id`. Progress evidence links through provenance rather than being an untraceable percentage.

### `consolidation_proposals`

Immutable proposal content, fixed unreviewed confidence, detector version, exact
evidence snapshot, and policy are followed by at most one guarded owner review
transition. Accepted or corrected proposals reference one exact semantic,
pattern, or progress memory revision; rejected proposals reference none.

### `goal_progress_records`

Each immutable record binds one goal projection revision to a direction,
summary, observation time, policy, lifecycle event, and exact supporting or
counter-evidence edges. It is evidence, not an automatically computed progress
percentage. The INSERT guard requires the referenced Goal revision to be the
current durable projection at record time, validates the exact
`PROGRESS_RECORDED` lifecycle event and evidence snapshot contract, and compares
the stored digest with PostgreSQL's canonical reconstruction. A deferred
constraint then requires the snapshot and durable provenance edges to match.

### `user_model_evaluation_runs`

Immutable content-hash-verified synthetic evaluation evidence records the suite,
fixture and code revisions, environment, metrics, case results, and limitations.
It does not represent a release decision or owner approval.

## 8A. Proposed proactive interaction records

These are logical contracts for future Stage 6 activation. This amendment creates no tables or migrations. The append-oriented event ledger remains lifecycle authority; current-status fields below are rebuildable projections.

### `proactive_triggers`

Immutable observations that may justify proposal construction. Required fields include `trigger_id`, `owner_id`, registered `trigger_type`, source kind/version, exact source/subject references, `observed_at`, `recorded_at`, optional consent scope, `trace_id`, `data_policy_revision_id`, and status (`recorded` or `invalidated`). A trigger is evidence, not outreach authorization.

### `proactive_proposals`

Durable candidates for outreach:

| Column | Type | Rule |
|---|---|---|
| `proposal_id` | UUID PK | Application-generated UUIDv7 |
| `owner_id` | UUID FK | Required; all referenced evidence belongs to the same owner |
| `category` | text | Registered permission/budget category |
| `reason_code` | text | Stable owner-legible reason category |
| `reason_summary` | protected text | Explanation, never ordinary telemetry |
| `intended_benefit_kind` | text | Registered user-benefit category |
| `confidence` / `confidence_method_version` | numeric/text | Optional `[0,1]` plus exact method and limitations |
| `urgency_class` | text | Registered class; never manufactured from engagement |
| `earliest_eligible_at` | timestamptz | Earliest possible evaluation/delivery time |
| `expires_at` | timestamptz | Latest useful time; required |
| `deduplication_key` | text | Owner-scoped equivalence key; no content in logs |
| `candidate_channels` | text[] or normalized relation | Only registered channels; permission not implied |
| `status` | text | Rebuildable lifecycle projection |
| `created_at` | timestamptz | Immutable creation time |
| `trace_id` | char(32) | Proposal creation trace |
| `data_policy_revision_id` | UUID FK | Conservative policy over required evidence |

Trigger and evidence membership use owner-qualified link tables or provenance edges with exact revisions; IDs hidden in one JSON blob are insufficient for core authorization and erasure traversal.

### `proactive_preference_revisions`

Immutable owner settings with an authoritative `proactive_preference_heads` projection. Each revision can represent global enablement, category permission, quiet-hour/timezone behavior, global/category budget policy, cooldown policy, channels, preview mode, goal/Scene-specific stops, and revoked consent. The head must reference one exact stored owner revision and advance monotonically. Preference save and every new policy execution share the owner transaction lock; older revisions remain available only to explain historical decisions and cannot authorize a new execution.

### `interruption_decisions`

One immutable evaluation result per attempt:

| Column | Type | Rule |
|---|---|---|
| `interruption_decision_id` | UUID PK | Stable decision identity |
| `owner_id` / `proposal_id` | owner-qualified FK | Required |
| `decision` | text | `SEND_NOW`, `DEFER`, `DROP`, `REQUEST_OWNER_CONFIRMATION` |
| `reason_codes` | registered relation/jsonb | Versioned list with no private content in telemetry |
| `policy_version` | text | Exact Interruption Policy version |
| `preference_revision_id` | UUID FK | Exact settings used |
| `governing_version_ids` | typed references | Constitution and Identity/Values parents |
| `input_snapshot` | jsonb | Schema-versioned permission/budget/cooldown/dedupe/timing/channel/privacy results |
| `defer_until` | timestamptz nullable | Required for time-based deferment |
| `rendering_constraints` | jsonb | Authorized purpose and wording/channel limits |
| `decided_at` | timestamptz | Required |
| `trace_id` | char(32) | Evaluation trace |

The decision row is never updated to a different outcome. Re-evaluation creates a new decision and lifecycle event. `SEND_NOW` is the only outcome that may create a rendering authorization.

### `proactive_renderings`

Protected immutable artifacts containing proposal/decision/Context Pack references, renderer kind, exact template/provider/model/adapter/tokenizer versions, content hash, effective DataPolicy, preview-artifact reference, provenance, trace, and status. A rendering is not conversation history until delivery succeeds.

### `delivery_attempts`

Append-oriented attempt records with `delivery_attempt_id`, `delivery_id`, owner/proposal/decision/rendering references, channel/destination scope, adapter version, preview policy/artifact, owner-scoped idempotency key, attempt number, not-before/expiry, status (`pending`, `accepted`, `delivered`, `failed`, `expired`, `cancelled`, `unknown`), typed failure/retryability, provider receipt ID, timestamps, reconciliation result, DataPolicy, and trace.

Unique owner/proposal/channel/idempotency constraints prevent duplicate visible effect. Provider acceptance is not silently equated with user visibility. Retry rechecks authorization, preference, budget reservation, cooldown, cancellation, expiration, channel, and privacy.

### `proactive_response_links`

Immutable owner-qualified links from a reactive `interaction_request`/`USER_MESSAGE` to the delivered proactive `ASSISTANT_MESSAGE`, delivery attempt, proposal, trigger(s), and related Goal/Scene/Memory/Belief/Reflection. Temporal proximity alone never creates a link.

## 9. Worker reliability

### `background_jobs`

| Column | Type | Rule |
|---|---|---|
| `job_id` | UUID PK | Durable job |
| `owner_id` | UUID nullable | Null only for non-owner system jobs |
| `job_type` | text | Registered worker operation |
| `payload` | jsonb | Versioned references, not duplicated sensitive content |
| `status` | text | `pending`, `leased`, `succeeded`, `retryable_failed`, `terminal_failed`, `cancelled` |
| `available_at` | timestamptz | Scheduling |
| `lease_owner` | text nullable | Worker identity |
| `lease_expires_at` | timestamptz nullable | Crash recovery |
| `attempt_count` | integer | Required |
| `max_attempts` | integer | Required |
| `origin_trace_id` | char(32) | Causality link |
| `created_at` | timestamptz | Required |
| `completed_at` | timestamptz nullable | Terminal time |
| `last_error_code` | text nullable | Typed, non-secret |

The event write and its required job insert share one transaction. Workers claim with `FOR UPDATE SKIP LOCKED`. Jobs must be idempotent. Throughput, queue age, retry rate, and dead jobs are measured before considering Redis or another queue.

When Stage 6 activates Proactive Core, registered job types may evaluate scheduled triggers, re-evaluate deferred proposals, render authorized content, attempt delivery, and reconcile receipts. Jobs carry IDs/references rather than copied private content. Every attempt rechecks policy/preference versions, cancellation, expiration, deduplication, budget/cooldown reservation, channel, and privacy. No proactive worker is activated by this amendment.

## 10. Learning and registry tables

### Daily conversation, episodes, and owner feedback

`sessions` plus immutable message `events` remain the canonical conversation
history. `conversation_episodes` closes one session at a governed boundary and
stores an immutable derived summary; `conversation_episode_members` freezes the
exact ordered Event membership and each source hash. `episode_memory_suggestions`
is a concentrated review queue with its own exact inherited DataPolicy. It never
rewrites the summary or source Events and always remains
`training_eligible=false`. Corrective migration `0037` makes session closure
terminal, reconstructs the complete ordered episode and summary at commit, and
rejects cross-session membership, privacy downgrade, and self-consistent forged
hashes at the database boundary.

`response_feedback_heads` identifies one append-only feedback thread for an
exact assistant response and binds its request/session/trace, user and assistant
Events, ContextPack, route, and inference attempt. `response_feedback_revisions`
stores rating, reason observations, optional owner reason, optional proposed
answer, and the exact provider/model/adapter/tokenizer/serving lineage copied
from and checked against the inference attempt. The source response and every
prior revision remain immutable.

`personalization_feedback_reviews` records root-cause attribution and one
non-training decision for a current exact revision. The schema retains the
future decision vocabulary, but corrective migration `0037` rejects
`approved_for_personalization_training` and every true training flag while
Stage 9B is inactive. A future authorized stage must add a separately
privileged durable approval path before any dataset builder can consume owner
feedback. `communication_preference_revisions` is an append-only, small typed
runtime control (`brief`, `balanced`, `detailed`).

All tables are owner-qualified, exported with owner data, and included in
source-erasure closure. Immutable content may be deleted only by the existing
privileged erasure path.

### `training_examples`

Canonical, model-independent examples with fields for situation, structured user state, goal, input, assistant output, feedback, action, outcome, review state, schema version, content hash, and effective DataPolicy. Source lineage is stored through provenance edges. Dataset construction may include an example only when every required source is explicitly `training_eligible = true`; memory eligibility does not count as consent. Rendered provider messages and token IDs are build artifacts, not canonical columns.

### `dataset_snapshots` and `dataset_snapshot_members`

Snapshot metadata follows the contract in [`MLSYS_DESIGN.md`](MLSYS_DESIGN.md). Membership freezes example ID, example revision/hash, split, order, and inclusion reason. Finalized membership is immutable. If an owner erases a source event, affected snapshots become `revoked_for_privacy`; any derived adapter or deployment becomes ineligible for future promotion until rebuilt. Physical removal policy is documented in the erasure report.

### `model_versions`

Stores provider-neutral model identity, exact upstream revision, tokenizer, format, precision/quantization, artifact hashes/URIs, license, capabilities, compatibility, and lifecycle status.

### `rendered_training_artifacts`

Stores the immutable model-specific rendering/tokenization build separately from
the canonical snapshot. The artifact's source-member manifest must equal the
manifest recomputed from durable snapshot-member rows. Rendered `example_id`
values are unique, and the rendered collection must be an exact bidirectional
one-to-one mapping of those rows: no missing, extra, or repeated member may be
bound to a training run.

### `adapter_versions`

Stores exact base-model compatibility, adapter type/config, dataset snapshot, training run, artifact hash/URI, evaluation references, and lifecycle status.

### `training_runs`

Stores input versions, code revision, environment lock, seed, configuration, status, measurements, output artifact references, and trace/run identifiers.

Lifecycle status transitions are append-audited. A version row's identity metadata is never rewritten to point at different bytes.

## 11. Evaluation, benchmark, trace, and release tables

- `evaluation_cases`: immutable case versions and content hashes.
- `evaluation_suites` / `evaluation_suite_members`: frozen composition.
- `evaluation_runs`: candidate release manifest, evaluator versions, environment, status, aggregate result.
- `evaluation_case_results`: per-case outputs, rubric scores, judge evidence, and failure classification.
- `benchmark_runs`: workload, system-under-test manifest, environment/hardware, protocol, raw artifact references.
- `benchmark_metrics`: normalized metric name, unit, aggregation, value, sample count, and confidence interval when applicable.
- `traces` / `spans`: vendor-neutral execution metadata. Raw user content is referenced, not copied by default.
- `release_manifests`: immutable pinning of all behaviorally relevant component versions.
- `deployments`: environment, release manifest, status, health evidence, previous deployment, and rollback record.
- `guidance_outcome_observations`: consented, source-qualified observations such as action attempted, planned Scene status, later regret, helpfulness, passivity, and forcefulness. They link one Intervention Decision and visible guidance event to exact action, outcome, reflection, observation window, evidence snapshot, and DataPolicy; unknown and not-asked values remain explicit, and the row is not causal or clinical truth.

Evaluation and benchmark contracts are defined in their respective plan documents.

## 12. Privacy, export, retention, and erasure

### Export

An owner export must include:

- raw events in a documented open format;
- identity/user-model/goal/memory revisions and provenance;
- dataset examples and snapshot metadata that contain owner data;
- model/adapter/release metadata needed to understand personalization;
- proactive triggers, proposals, preference revisions, interruption decisions, renderings, delivery attempts, response links, and their provenance;
- context source/capability descriptors, consent/sampling/retention revisions, life-context observations, health/freshness/coverage history, invalidations, and provenance;
- checksums and schema versions.

It does not need to include third-party proprietary model weights that the owner does not own, but must include exact identifiers and revisions.

### Erasure

Erasure is a privileged workflow, not ordinary application deletion:

1. Freeze new processing for the owner or selected scope.
2. Resolve the provenance closure from selected sources to derived memories, beliefs, embeddings, proactive proposals/renderings/previews, pending jobs, delivery metadata that duplicates content, examples, snapshots, caches, artifacts, and traces that duplicate content.
   Ambient-context scope additionally includes source-local buffers/receipts, canonical observations, health records containing personal metadata, state estimates, trigger/proposal inputs, and downstream copies.
3. Produce a dry-run manifest for confirmation when scope is partial.
4. Delete or cryptographically render inaccessible all selected personal content and derivatives.
5. Mark affected non-personal registry records unusable if their reproducibility or privacy claims no longer hold.
6. Verify absence using IDs and hashes, without restoring deleted content into logs.
7. Optionally retain a minimal content-free erasure receipt only with an explicit policy and owner approval.

The Stage 2 online subset closes source-event derivatives across jobs and every candidate status; memory revisions, heads, embeddings, and provenance; retrieval candidate and exclusion snapshots, including both an exclusion's `memory_id` and its retained canonical `duplicate_of_memory_id`; ContextPack sections; route/inference records; and affected assistant events. It runs even when no accepted memory exists. Affected request-ledger rows remain as content-free failed records. Raw source deletion, backups, external processors, and receipt policy remain separate owner-governed work. The erasure transaction uses a local flag accepted only from a member of the `havre_privileged_erasure` database role; it never disables immutable triggers globally.

Migration `0004` grants `havre_privileged_erasure` to `CURRENT_USER` solely so the present single-user local acceptance environment can exercise erasure. Before any real deployment, database access must be split into at least migrator, ordinary application, and privileged erasure roles. The application role must not inherit erasure authority, and the local acceptance grant must not be copied unchanged into production.

Backups need a documented expiry and restore-time deletion replay mechanism; otherwise “delete everything” is false after restoration.

### Retention

Canonical source experience is append-preserved and retained by default because it is the long-term source of truth. This is qualified by owner erasure and an exact owner-approved RetentionPolicy. High-volume device-native sensor/audio material should normally be processed locally and discarded immediately or kept briefly; it is not automatically a central Event payload. A content-free record that a signal occurred may remain only under an approved policy and must not reconstruct deleted content. Retention expiry follows the same derived invalidation/deletion and backup-replay guarantees as erasure. No retention shortening is introduced merely to reduce implementation work.

## 13. Stage activation

### Stage 1 physical subset

- `owners`
- `identity_artifact_versions` for Constitution, Identity, and Values
- `approval_records`
- `sessions`
- `events`
- direct immutable DataPolicy snapshots on events and Context Packs
- protected `context_packs`, `route_decisions`, and `inference_attempts`
- exact provider/model/adapter/tokenizer/serving versions on each inference attempt
- `traces` and `spans`
- `interaction_requests` for request lifecycle and idempotency
- schema migration ledger

`interaction_requests.request_fingerprint` binds each owner-scoped idempotency key to the canonical semantic ingress fields. A key reused with different content or privacy semantics fails with a typed conflict. Rows created before this invariant are marked `legacy:<request_id>` and fail closed on replay.

The Product Owner limited Stage 1 implementation to the synchronous permanent vertical slice. `background_jobs` and a worker executable remain architecturally reserved but inactive until an approved later capability has durable work to schedule.

### Stage 2 additions

- `memory_revisions`
- `memory_heads` current projection
- `memory_candidates`
- `memory_embeddings`
- `embedding_versions`
- `provenance_edges`
- `background_jobs` for episodic extraction
- `retrieval_results`
- retrieval benchmark cases/runs/results

The 2026-08-13 Stage 2 migrations activate this subset with owner-qualified foreign keys on both provenance endpoints, exact `vector(64)` storage, immutable revisions/embeddings/provenance/results, lease-generation-fenced jobs, complete online Stage 2 deletion closure, persisted retrieval selection policy/exclusions, and no ANN index before corpus evidence. `0004_stage2_acceptance_corrections.sql` is additive; applied `0003` databases are upgraded rather than rewritten.

### Stage 3 additions

- additive `0005_stage3_self_hosted_inference.sql`;
- additive `0006_stage3_runtime_attestation.sql`, which registers immutable,
  content-free process attestations and lets inference attempts reference the
  exact attestation ID/hash without rewriting historical `0001`-`0005` rows.
  Historical rows are marked contract v0 during migration; an INSERT trigger
  requires contract v1 for every new row, so a caller cannot explicitly select
  v0 to bypass the self-hosted attestation foreign key;
- terminal failed-attempt metadata and exact provider-adapter, serving-engine, model-artifact, token, and timing evidence;
- request pointers to exact successful response or durable failure event;
- owner/request/trace-qualified foreign keys across requests, events, ContextPacks, routes, and inference attempts, preventing same-owner cross-request substitution;
- immutable `inference_benchmark_runs` rows stored as an atomic systems/compatibility report pair, with each report bound to exact content hashes, workload, environment, and system manifest.

The migration upgrades populated `0001–0004` databases in place and backfills old inference rows without inventing Stage 3 version evidence. Operational interaction deletion closure includes both successful and failed Stage 3 inference derivatives. Benchmark rows contain only reviewed synthetic workload evidence and are separately immutable.

### Stage 4 additions

- additive `0007_stage4_user_model_goals.sql`, without rewriting `0001`-`0006`;
- `user_belief_revisions`, guarded `belief_heads`, and append-only
  `belief_revision_transitions`;
- `consolidation_proposals`, semantic/pattern/progress `memory_revisions`, and
  one guarded owner review transition;
- `current_state_snapshots`, guarded `goals`, and immutable
  `goal_progress_records`;
- `user_model_evaluation_runs`;
- owner-qualified source and destination foreign keys for event, memory, belief,
  proposal, state, and progress provenance;
- expanded provenance audit and privileged source-erasure closure;
- temporal User Model projections plus `known_as_of` / `valid_at` replay tests.
- additive `0008` and `0009` correction migrations without rewriting prior
  migrations; `0009` adds single-use belief transition consumption, complete
  Goal projection/hash/time binding, and the remaining derived-memory
  provenance FK index.

Fresh `0001`-`0009` installation and a populated `0001`-`0008` in-place upgrade
were verified at that historical reacceptance snapshot. Stage 4 activates no Scene,
Intervention Policy, training, or proactive tables.

### Stage 5 additions

- `scene_sessions` current projections guarded by exact lifecycle events and optimistic revisions
- append-oriented ordered `scene_records`
- immutable versioned `intervention_decisions` plus visible guidance-event links
- consented immutable `guidance_outcome_observations`
- immutable non-binding `scene_evaluation_runs`
- Stage 5 provenance destination constraints, required-edge audit view, complete referencing-FK indexes, and privileged erasure closure

These physical tables are added by migration `0013`. Additive `0014` leaves
them and every earlier migration in place while strengthening current-state
admission, canonical row hashes, exact decision/guidance binding, and Scene
erasure closure. They contain no proactive triggers, proposals, interruption
decisions, scheduled work, renderings, delivery attempts, or outbound channels.

### Stage 6 proposed Proactive Core additions

- `proactive_triggers` and exact trigger/evidence links
- `proactive_proposals` and append-oriented lifecycle events
- `proactive_preference_revisions`
- `interruption_decisions`
- `proactive_renderings` and separately classified preview artifacts
- `delivery_attempts`
- `proactive_response_links`
- activation of `background_jobs` and the accepted PostgreSQL-backed worker boundary for scheduled/event-driven work
- synthetic/manual `LifeContextObservation` fixtures may be accepted only as clearly labeled test evidence; no `context_sources` or external adapter is activated

This activation is contingent on Product Owner approval of the amendment and the future Stage 6 milestone. It is not part of Stage 1 or Stage 2.

### Stage 7 proposed memory-lifecycle additions

- broader class-specific promotion/review records;
- memory contradiction/supersession/archival/reconsolidation transitions or equivalent immutable revisions;
- regeneration manifests binding exact eligible sources and transform versions;
- retrieval exclusions that make historical-but-not-current and archived status inspectable;
- retention/erasure propagation through newly activated derivatives.

### Stage 11/12 proposed Ambient Life Context additions

- Stage 11 may activate individually approved iPhone/user-initiated voice capabilities behind the same source/consent/observation/health contracts;
- Stage 12A may activate Windows coarse-context and Calendar adapters one capability at a time;
- Stage 12B may add location, mobility, wearable, richer sensor, and Edge capabilities only after separate privacy/usefulness review;
- physical tables, migrations, indexes, roles, device authentication, and erasure paths are designed and verified in the first stage that actually persists these records, not by this amendment.

Later tables activate with the roadmap stage that uses them. Their contracts are fixed here so early IDs and lineage do not become throwaway data.

## 14. Verification expectations

Before a database milestone is accepted:

- migrations apply from empty and upgrade from the previous schema;
- constraints reject invalid confidence, unknown lifecycle transitions, and owner-crossing references;
- constraints reject `LOCAL_ONLY` with `cloud_eligible = true` and default training permission to false;
- retry tests prove idempotent event/job creation;
- append-only roles cannot update/delete events;
- provenance traversal finds supporting and counter-evidence;
- temporal belief queries distinguish source occurrence, learning, creation, validity, and lifecycle transition time;
- Scene Session chains preserve Intervention → Action → Outcome links even for incomplete sessions;
- proactive tests reject cross-owner triggers/evidence/decisions/delivery links, reject rendering without `SEND_NOW`, reserve budgets atomically, suppress duplicate delivery, and preserve explicit response linkage;
- proactive privacy tests prove renderings/previews inherit required evidence policy and redaction never silently makes `LOCAL_ONLY` externally deliverable;
- context-source tests reject unknown/cross-owner devices, out-of-scope capabilities, expired/revoked consent, unregistered fields/kinds, policy downgrade, invalid clocks/intervals, and mismatched idempotency;
- source-health/freshness tests prove absent/offline/stale data cannot become negative evidence and required coverage fails closed;
- memory-lifecycle tests prove experiences are not automatically promoted, historical/current validity remains distinct, decay is retrieval-only, and reconsolidation/regeneration creates new provenance-bound revisions;
- export round-trip preserves IDs, versions, timestamps, and hashes;
- erasure tests prove source and derived closure removal, including embeddings and caches;
- backup restore plus deletion replay is tested before any production claim.
