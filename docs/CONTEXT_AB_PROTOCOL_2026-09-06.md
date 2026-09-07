# HAVRE Context A/B protocol — 2026-09-06

Status: **pre-generation protocol; source packet v2 explicitly approved by the
owner with “批准v2”. No model training or promotion.** The accepted baseline is
`PERSONAL_CONTEXT_ENGINE_REVIEW_2026-09-06` / commit `c5cd202`.

## Question and competing inputs

Which produces the better HAVRE response, under one fixed strong GPT configuration?

- **Full**: current v17 builder/compiler, v5 ResponsePlan, v13 presentation,
  qualified Memory retrieval, personal context selection and OA70 runtime examples.
- **Simple**: the same approved Identity and owner response constraints, continuous
  recent raw conversation, query-targeted recall of original conversation, and
  explicit owner corrections. No ResponsePlan, behavioral examples, derived
  episodic/pattern summaries, User Model or proactive Goal injection. It uses the
  existing local raw recall algorithm for substantive current queries, including
  queries without an explicit “remember”. No new retrieval model or trained policy.

Both compile independently under 16,384 total estimated tokens, reserving 3,072
for output. Unused optional-layer budget is available to raw conversation. Current
user text, time, Identity, explicit constraints and provider wrapper stay equal.
No arm receives a rewritten target, the historical target answer, or future facts.
The source pools are the same authorized owner history; different selection is
part of the comparison. Neither arm mutates Goals, memories or follow-up queues.
This isolates context-dependent response quality, not action execution success.

Full is rebuilt with current code; archived old ContextPacks are not substituted
for current behavior. Historical Goal projections come from hash-validated
immutable lifecycle events. Memory/Belief selection is as-of; correction and
feedback heads are reconstructed at that time. An unavailable/unverifiable source
causes an exclusion, not an invented historical state. Record actual admitted
layers: a layer absent from the real cases cannot be declared valuable or useless.
Calendar/Scene sources absent in this corpus are not fabricated.

## Data and privacy

Owner-approved source packet v2 manifest SHA-256:
`08cb5e2f799ce57ac1338134eb27138bd2bcc98e78a8f04f05366249c693d520`.
It contains 70 candidate Web messages and 138 ordinary NORMAL/cloud-eligible raw
events from Aug 22–Sep 5 UTC. Original text, source hashes, exact owner IDs, local
entity extraction and pseudonym mapping remain in an owner-only ACL directory
under ignored `var/context-ab-20260906/case-review-v2/`. Earlier drafts were never
used for answer generation. LOCAL_ONLY and one-time HIGHLY_PRIVATE authorizations
are excluded; redaction does not change their classification.

Only the purpose-bound pseudonymized NORMAL derivative may be used for this
one-off generation and semantic review. It is still personal data, not anonymous
or public. Existing qualified context dependencies retain their provenance and
source policies. Derived artifacts remain training-ineligible and outside product
ingestion. Recheck source revocations and hashes before running; revoke all
descendants if an included source is revoked. No hosted evaluation dataset or new
service is created. No raw private text goes into Git, stdout or command arguments.

## Cases, contamination and sampling

Before seeing outputs, select 32 real targets across eight primary strata:
casual, cross-day continuation, past-experience recall, correction, Goal-related,
person/task ambiguity, stale information, and history that should not be surfaced.
Store exact case membership, temporal evidence and semantic requirements in the
sealed local manifest. Use all evidence-rich real Memory/User Model opportunities
that fit these strata rather than presenting an examples-only ablation as a test
of every layer. Labels from keyword matching are sampling hints only; semantic
inspection determines actual scenario coverage.

Preserve dialogue families in analysis. Repeated/rephrased messages and adjacent
turns about one experience are not independent users or independent life events.
Each case gets one primary generation per arm. Eight cases, selected before
generation (one per stratum), get a second independent generation per arm to
measure instability: 80 primary/stability generation calls in total. No optional
stopping, content-driven retry, selection after seeing answers, or target edits.

OA70 is allowed only as Full's existing runtime layer. All 70 OA70 prompts have
been exposed to this runtime and are not an independent evaluation set. Synthetic
stress cases are separately labeled and separately reported, never counted as
owner daily experience or years of demonstrated relationship continuity.

The real archive is short. Explicit no-callback and stale-state cases exist, but
genuinely old stored sources and multiple same-name people may require constructed
stress cases. State these gaps rather than relabeling a recent message as years
of storage. Freeze stress targets/ground truth before generating either arm.

## Generator and controls

Pin the installed `gpt-5.6-sol` / **medium** Codex CLI provider, its executable
SHA-256 and version, provider adapter, serving configuration, code hashes,
Identity hashes and all exact input payloads. Fresh ephemeral, tool-disabled
process per answer; one shared wrapper and output request budget. Validate the
returned model and serving configuration on every response; drift invalidates
the comparison. The alias does not expose an immutable backend weights snapshot.

The current adapter does not transmit temperature, top-p or seed. Those are
**provider-managed/uncontrolled**, not purportedly fixed sampler parameters.
The 3,072-token output budget is carried in the reply contract, not a verified
server-side hard cap. Preserve actual usage and truncation. Randomize case order
and balanced within-pair execution order with a recorded local seed. Run serially
for interpretable generation latency; record cache hits and other concurrent
runtime activity. Separate any infrastructure retry and retain failed attempts.

## Blinding and semantic review

Give each pair fresh opaque answer labels and a fresh shuffled order. Keep the
mapping in a separate owner-only key file. Reviewer packets contain only current
message, approved raw pre-target evidence, frozen fact/uncertainty constraints,
and the two responses. They exclude architecture, internal prompts, source-layer
names, generation order, latency, tokens, cost and historical target replies.
Never edit an answer to hide a revealing style or internal leakage: score that
behavior. Explicitly ask reviewers not to guess architecture.

Use detailed semantic pairwise review, with concise evidence-grounded reasons
and uncertainty, not keyword counts. Obtain fresh model reviews in both candidate
orders and preserve disagreement. These are **model semantic reviews**, not owner
ratings or human-validated relationship truth. A reviewer in the design task may
inspect anonymous answers but does not qualify as an independent human judge.
Without human calibration, model-judge preferences remain provisional.

Score the following with anchored 1–5 ratings; `null` is allowed only when truly
inapplicable. Higher is better for positive dimensions; lower is better for harms.

| Dimension | 1 | 3 | 5 |
|---|---|---|---|
| Naturalness | mechanical / awkward | acceptable | fluent and proportionate |
| Relationship continuity | resets or changes persona | neutral continuity | grounded, same HAVRE |
| Relevant recall | wrong/missing needed facts | partial useful history | correct, sufficient, restrained |
| Correction obedience | repeats rejected fact | partly adjusts | fully respects latest correction |
| Usefulness | misses current need | helps partly | addresses actual current need well |
| Over-analysis harm | absent | noticeable excess | dominates or pathologizes |
| Forced callback harm | absent | distracting callback | unrelated history dominates |
| Fabricated familiarity harm | absent | unsupported inference | invented shared events/intimacy |

Require an overall `left`, `right`, `tie`, or `unjudgeable` preference plus reasons.
Do not use a mechanical weighted sum as a replacement for that semantic judgment.
Flag fabricated shared facts, contradiction of explicit correction, unsupported
action/persistence claims, or acute safety failures separately. Model judges cannot
clear a critical disagreement solely by voting.

Pairwise/order controls and human calibration follow the existing evaluation
plan and [OpenAI evaluation guidance](https://developers.openai.com/api/docs/guides/evaluation-best-practices).
The ephemeral execution behavior is documented in
[Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode).

## Systems metrics and decisions

Lock semantic reviews before joining systems metadata. Report provider-observed
input/output/reasoning/cache tokens, total generation latency, failures and total
calls. Preparation timings have shared-work/cache differences and are not a valid
end-to-end architecture latency estimate. Report generation median and p90 with
paired differences; do not infer causality from a handful of warm/cache samples.

This authenticated Codex route does not return per-call USD billing. Report USD
as **unavailable**, not zero; include measured token/call use. Do not apply an
unrelated API price to subscription usage or invent a dollar saving.

Analyze real cases and stress cases separately. Primary preference is the fraction
of wins with ties worth 0.5; opposite-order disagreement is unresolved. Replicates
measure stability and never double the independent sample size. Report strata and
dialogue-family clustered bootstrap intervals with a frozen seed, raw wins/ties/
losses/unjudgeables and sensitivity to unresolved judgments. Small strata support
case findings, not a production router learned from case IDs.

An arm is a **candidate** for broad simplification/retention only if its real-case
win share including ties is at least 0.65, the dialogue-family clustered 95% lower
bound exceeds 0.50, both-order agreement is at least 0.80, no additional critical
failure is unresolved, and the effect is not confined to a single family. These
are conservative experiment decision rules, not newly activated product outcome
or intervention scales. Without calibrated owner evidence, no global claim that
it is the better long-term companion follows even if this threshold is met.

For a clear, localized result, propose the smallest policy supported by the
observed cause; do not train a router. If uncertain or materially incomplete,
record “inconclusive” and retain the accepted runtime. No forced architecture
change is required to count honest experimental work as useful.

After results: review any necessary change, run proportional tests (full
PostgreSQL-backed suite if persistence/privacy/governance/runtime changes), record
exact evidence and limitations, make the user-authorized local commit, stop.
Do not push, train, promote a model or start recurring work.
