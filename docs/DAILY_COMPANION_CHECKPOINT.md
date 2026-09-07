# Daily Companion Product Checkpoint

Date: 2026-08-27

## Result

HAVRE now exposes one continuous owner-to-HAVRE conversation instead of chat
threads. Every paired device projects the same canonical Event Store timeline
with keyset pagination, timestamps, date separators, feedback, and durable
proactive assistant messages. The mobile-first installable PWA adds Diary, a
human-readable Memory view, and compact Settings without changing canonical
Event, Memory, Context, User Model, Goal, or Core semantics.

9201 remains the default Local Daily Brain. Strong Cloud Brain stays manual and
fails closed for real owner data. No training, routing, promotion, deployment,
Stage 9B, v8, or candidate lifecycle change occurred.

## Windows, iPhone, and sync

Start the existing 9201 owner-local runtime with
scripts/start_havre_candidate_local.ps1 and open /chat. Windows can use the
browser or its Install action. The desktop launcher sends its one-time
bootstrap secret in a POST body and stores an HttpOnly cookie; no credential
enters a URL.

An iPhone can install the same trusted HTTPS origin through Safari Share > Add
to Home Screen. Settings > Devices creates an eight-digit, short-lived,
one-time pairing challenge. Five wrong attempts lock it. A successful claim
creates a revocable HttpOnly/Secure device session. Paired devices may chat,
read Diary/Memory, submit feedback, manage their own Push subscription, and
request Strong rethink. Device administration, privacy export/erasure,
settings mutation, and workers remain owner-primary only.

PostgreSQL Event and Memory stores are canonical. Clients hold display state, a
per-device read cursor, and a revocable session, not another history.
Concurrent sends retain request idempotency and Event ordering.

## Product surfaces

Chat opens newest canonical messages and paginates upward by recorded_at plus
event_id. Engineering sessions are hidden. Phone and desktop read the same
timeline. Proactive ASSISTANT_MESSAGE Events enter it exactly once.
Notification-shaped links contain only /chat#message-event-id. Provider lineage
stays out of bubbles; feedback, owner revisions, and ADR-0022 delivery
provenance remain intact.

Diary is an Event-derived daily view, not a Memory store. A local day gets one
head only after real owner/HAVRE conversation. More conversation creates an
immutable revision; a new date gets a new entry. Each revision binds exact
source Events and exposes the ordered transcript. Source erasure removes
affected Diary derivatives. Diary cannot bypass Memory review or automatically
become Semantic/Pattern Memory.

Memory groups current Memories, pending candidates, User Model beliefs, Goals,
non-expired Current State, and Pattern proposals. Cards show readable content,
status, evidence, canonical confidence, and collapsible technical details.
Correction/retraction use existing immutable service and deletion paths; the UI
never updates canonical rows directly.

Settings contains notification preview preference, Reach Out enable/cooldown
and owner-timezone quiet hours, device pairing/revoke, Calendar
status/disable, Strong Brain privacy status, and a Memory link. Paired-device
Settings hides and backend-denies owner-primary mutations.

## Governed Reach Out and Web Push boundary

The accepted active path remains:

Events, Goals, State, Calendar, Memory to Trigger, ProactiveProposal,
InterruptionPolicy to DROP, DEFER, or SEND_NOW to durable ASSISTANT_MESSAGE and
web_inbox simulation evidence.

This milestone implements Push subscription rotation/revoke/expiry, minimal
payload validation, delivery attempt/receipt storage, preview privacy, and a
fail-closed WebPushDeliveryProvider. It does not activate external Push. Stage
6 permits only web_inbox, simulation_only=true, and
external_delivery_authorized=false. The provider requires exact external
authorization and therefore selects zero current records. API and UI report
subscription readiness separately from delivery activation.

Before external Web Push can be activated, a separate Product Owner
architecture/privacy decision must approve:

1. a reachable trusted HTTPS origin and its trust boundary;
2. an additive lifecycle that produces an authorized web_push attempt without
   weakening LOCAL_ONLY;
3. a durable pre-send claim/lease plus retry/backoff worker so concurrent
   workers cannot duplicate a notification; and
4. exact privacy classification of external event ID and payload.

The intended payload is database-limited to title, body, event_id, and url. It
cannot carry ContextPack, Memory, User Model, history, credentials, or arbitrary
evidence. Private preview is “HAVRE 有条消息给你”; detailed preview would remain
limited to admitted PUBLIC/NORMAL content. These contracts are tested, but no
real notification was sent or claimed.

## Owner-local Calendar activation

The canonical Stage 12A manual-ICS implementation was reused. Core issues a
permit before the file is opened. The file is not copied and no Calendar
network provider runs. The helper provisions a narrow context login with a
rotated, non-persisted password; the signing secret remains only as owner-local
DPAPI ciphertext for resume.

Actual supplied Fall 2026 activation:

- source 01a041c7-6ccb-7011-b13e-577755286512;
- observation 01a041c9-bc3b-7a2a-b822-f606cec17262;
- one local file, six provider rows, 205 minimized intervals;
- coverage 2026-08-01 through 2027-01-15;
- source copy false; network false;
- LOCAL_ONLY; Memory, training, and cloud eligibility false.

Migrations 0040/0041 raised undersized historical bounds; 0042 supersedes them
at 256 KiB, sufficient for the typed maximum 512 intervals. PostgreSQL-backed
regression persists all 512.

Context Builder v10 admits Calendar only for a LOCAL_ONLY turn with explicit
schedule intent, current consent, unexpired freshness/retention, enabled
states, and healthy evidence bound to the exact observation. Time words alone
do not trigger it. Today, tomorrow, this/next week, and ISO-date queries select
matching intervals. Missing/stale evidence is unknown, not free time. Disable
is always allowed; re-enable requires a governed import.

## Host availability and stop boundary

- PC awake and backend running: Chat, Diary, Memory, pairing, Calendar Context,
  and simulation-only Reach Out work through the reachable origin.
- PC asleep or off: Core cannot create Reach Out and clients cannot fetch.
- External Web Push is inactive in every host state at this checkpoint.

Always-on remains separate: keep Windows awake behind owner-managed HTTPS; use
an owner-controlled home server; or use a VPS/cloud Core. The latter choices
add hardware/maintenance or a persistent private-data trust boundary and need
separate authorization.

Public-safe synthetic viewport evidence:

- assets/daily-companion/chat-mobile-390x844.png
- assets/daily-companion/chat-desktop-1440x960.png
- assets/daily-companion/diary-mobile-390x844.png

The in-app browser controller could not initialize its Windows sandbox helper;
installed headless Chrome produced the real viewport artifacts.

Final evidence:

- focused product/security/Calendar/Stage 10/11 suite: 85/85, zero skips;
- complete non-Torch environment: 513/513 with the dedicated PostgreSQL URL;
- the three excluded Stage 9A modules in the pinned Torch environment: 62/62;
- combined coverage: all 575 repository test methods, zero database skips;
- test and owner database provenance audits: both empty;
- Stage 12A synthetic benchmark: 1000/1000 projections, passed, no network or
  real Calendar content;
- migration head 0042 applied to both exact databases and schemas re-exported;
- pip check, Python compileall, both JavaScript syntax checks, screenshot
  dimensions, and git diff check passed;
- independent final review: P1=0 and P2=0.
- the exact disposable test database was dropped and the repository-owned
  PostgreSQL cluster was returned to its pre-task stopped state.

The main environment alone lacks Torch and therefore reports 10 historical
Stage 9A import errors; those exact modules are covered by the passing pinned
Torch run above. The real ICS is absent from tests and tracked assets.

No external HTTPS/tunnel provider, external proactive activation, VPS, native
iOS/APNs, public Push, automatic cloud routing, private-data cloud
authorization, Stage 12B, training, promotion, or deployment is included.
