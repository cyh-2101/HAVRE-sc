# ADR-0023: Private tailnet access and governed generic Web Push

- Status: Accepted
- Accepted: 2026-08-27 by Product Owner
- Date: 2026-08-27
- Decision owners: Product Owner/System Architect
- Extends: ADR-0016 and ADR-0018

## Decision

During the owner-PC-awake phase, HAVRE Web is exposed only through Tailscale
Serve HTTPS to authenticated devices in the owner's private tailnet. The API
continues to listen on loopback and PostgreSQL is never served. Funnel, public
port forwarding, public reverse proxies, VPS, and cloud-hosted Core are outside
this decision.

The existing Stage 6 web_inbox lifecycle remains canonical. After SEND_NOW has
produced exactly one durable proactive ASSISTANT_MESSAGE, a separate
owner-authorized web_push dispatch may be created for each active, paired
subscription. The dispatch is durable before network I/O and uses an
owner-scoped claim/lease, expiry, bounded retry/backoff, and immutable
attempt/receipt evidence.

Delivery, device/subscription revocation, and source erasure share one
owner-scoped serialization fence. A claimed worker re-reads current Event
privacy and live device/subscription state under that fence and holds it
through the bounded provider call and exact-generation completion. Every
expired lease generation is closed with durable outcome-unknown evidence
before retry or dead transition.

Subscription registration and inbox delivery eligibility use DB-authored
timestamps. Messages created before subscription authorization, or after the
proposal/decision delivery window, cannot become an external dispatch. This
prevents historical Web inbox backlog from being pushed to a newly paired
device.

The only authorized payload policy in this phase is generic-private-preview-v1:
title HAVRE, body HAVRE 有条消息给你, a random delivery locator, and a same-origin
/chat#delivery path. The locator is resolved after authenticated app launch to
the canonical Event. Message text, Event IDs, Context Packs, Memory, User
Model, Goals, Calendar, prompts, and credentials do not leave in the Push
payload. LOCAL_ONLY and unknown source privacy fail before a dispatch exists.

One owner-local VAPID key version is active at a time. The private key is stored
with Windows DPAPI current-user protection outside Git/database/logs; the
public key, version, hash, and Product Owner authorization are traceable.

The iPhone-only endpoint policy permits normalized Apple Push HTTPS endpoints
and is enforced at registration, durable admission, and send. Delivery follows
no redirect, inherits no ambient proxy configuration, and times out before its
lease. The accepted desktop path requires the exact signed Program Files
Tailscale CLI. Before startup and on protected requests/sends, live status must
show the exact ts.net DNS identity and Serve target with no Funnel permission.
No positive attestation cache is used; loss fails closed.

## Semantics and limits

Web Push is at-least-once. A crash after endpoint acceptance but before receipt
commit can cause a retry; the stable delivery locator is also the notification
tag for client-side coalescing, but no exactly-once external-display claim is
made. Provider acceptance is not proof of Lock Screen display.

Tailscale HTTPS certificates disclose the complete machine and tailnet DNS name
through Certificate Transparency. The machine name must be nonsensitive and an
official randomized/opaque tailnet DNS name is preferred before certificate
issuance. Tailnet access control still limits reachability.

PC sleep/off means Core cannot create new Reach Out work. An already accepted
Push may still be delivered by the endpoint, but HAVRE is not alive while the
PC/backend is unavailable.

## Validation gate

Implementation and synthetic/provider-bound evidence do not equal activation.
Only a real background/closed iPhone Home Screen app Lock Screen arrival,
notification tap, canonical message location, desktop same-Event check, and
durable receipt can establish Real Web Push activated.
