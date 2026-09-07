# ADR-0025: Manual owner-context Strong Brain disclosure

- Status: Accepted
- Accepted: 2026-08-28 by Product Owner
- Date: 2026-08-28
- Decision owners: Product Owner/System Architect
- Extends: ADR-0005, ADR-0011, ADR-0022

## Decision

Seed 9201 remains the default Local Daily Brain. The owner may explicitly ask
one already-delivered HAVRE reply to be reconsidered by the governed DeepSeek
Strong Cloud Brain. This is a per-action disclosure, not automatic routing or a
general change to the source records' privacy classification.

Each action derives one minimal selected-context disclosure from the canonical
ContextPack that produced the source reply, plus the exact source user and
assistant Events. The derived disclosure is HIGHLY_PRIVATE, cloud-eligible
only under the exact Product Owner authorization, and remains memory- and
training-ineligible. A durable immutable record is prepared before inference,
bound to the canonical provider request hash before owner content leaves the
machine, and completed with the resulting durable assistant Event or a typed
failure. Replays are idempotent; mismatched request material fails closed.

The dedicated manual provider accepts no ordinary request. The ordinary
public-synthetic Strong Brain experiment accepts no owner request. Provider
reasoning content is never delivered or persisted as HAVRE speech. The model
result still passes the ordinary ADR-0022 Core response-delivery boundary and
enters the same continuous conversation timeline.

The API key remains outside Git and PostgreSQL. The desktop launcher reads the
current Windows user's environment and supplies it only to the API and worker
processes without logging the value. Availability may be shown in Settings,
but no request is sent until the owner presses the manual action.

## Consequences and limits

- There is no automatic cloud routing, background cloud inference, provider
  replacement, candidate promotion, training, or lifecycle change.
- Source Events, Memory, User Model, and ContextPack policies are not rewritten
  or globally declassified.
- A manual action can disclose the selected private content to DeepSeek. It is
  therefore unavailable when the exact disclosure authorization, policy,
  durable permit, request binding, or API credential is absent.
- Provider-side deletion and retention remain outside HAVRE's local database
  guarantees. The UI must explain this boundary before manual use.
- 9201 remains the daily-use default because the ceiling experiment showed
  better difficult reasoning from Strong Brain but weaker casual naturalness.

## Validation gate

Synthetic/mock end-to-end evidence may prove exact admission, idempotency,
privacy rejection, durable disclosure state, Core delivery, and same-timeline
persistence. It does not prove the provider's future behavior or authorize a
real owner-data request by an agent. Only an explicit owner UI action may make
that request.
