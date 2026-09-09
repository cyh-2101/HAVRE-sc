# Chat, context and PWA update — September 8, 2026

This public technical summary describes source changes. It excludes operational
records, personal conversations, owner-review content and private style examples.
It is not a copy of the private audit and does not carry the audit's content hash.

## Included changes

- Explicit requests to consult a diary, Goal or User Model obtain bounded,
  source-qualified records through the existing context path. The model has no
  arbitrary SQL access and the request does not widen privacy permissions.
- Multi-turn Goal/reminder requests preserve their exact source messages.
  Core checks successful action receipts before allowing a claim that an action
  was saved or scheduled. Continuing a reply does not repeat that action.
- A continuation button uses `input_origin=continuation_button` and the exact
  completed parent reply. It remains an auditable control event but is not shown
  as a typed user message, admitted as diary testimony, or used as evidence for
  new realtime understanding. Typed continuation text retains its normal role.
- Waiting uses three animated dots. New bubbles and visible preceding messages
  move together over 460 ms. Keyed rows remain attached during unrelated updates.
  Four-second paragraph pacing, complete code/detail, reduced motion and recovery
  remain part of the existing interaction contract.
- Online PWA navigation reads fresh HTML and respects exact asset versions.
  Version checks, a persistent update action and guarded idle activation prevent
  a successfully updated server from being mistaken for an updated open client.
  Drafts and active requests block automatic reload. Offline caches contain only
  the public application shell.

Migrations 0072–0075 are additive. The existing production context architecture,
retrieval thresholds and model configuration were retained. Conversation style
and long-term usefulness are still unresolved product questions. No new training,
model promotion, private case publication or live rollout to a public service is
part of this showcase refresh.

## Inspect one change end to end

- [Ingress and interaction contract](../companion/application/service.py)
- [Requested context reads](../companion/context/lookup.py)
- [Continuation selection](../companion/context/continuation.py)
- [Goal intake](../companion/product/chat_goals.py)
- [Action receipt policy](../companion/policy/response.py)
- [Button/source regression](../tests/test_continuation_button.py)
- [Rendered-frame motion regression](../tests/pwa_bubble_motion_browser.cjs)
- [Service Worker upgrade regression](../tests/pwa_update_browser.cjs)

Public verification is recorded in [PUBLIC_TESTING.md](PUBLIC_TESTING.md).
Synthetic and automated checks establish specific behavior, not independently
verified human implementation skill, model naturalness or physical-phone feel.
