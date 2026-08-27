# Stage 6/7 second acceptance correction checkpoint

Date: **2026-08-19**
Status: **Two additional P1 blockers corrected and technically reverified; pending Product Owner reacceptance**
Execution-source snapshot: `sha256:8ba8b94632ae181c2966acc3d6c498d8f7a63337d2e8558629b47dd440386f9c`

## Scope and findings

The preceding `0021` correction candidate remained unaccepted. A later review reproduced two additional blockers:

1. A queued Stage 6 work item could retain an older enabled preference after the owner saved a newer globally disabled revision, so a new execution could still return `SEND_NOW`.
2. A direct lifecycle-evidence insert could race source erasure because the database admission trigger checked revocation without taking the erasure transaction locks.

No real proactive contact, external delivery, external Context Source, private-data transfer, automatic Memory mutation, training activation, governance-policy change, or Stage 8 work was enabled.

## Additive correction

Migration `0022_stage67_second_acceptance_corrections.sql` preserves `0001`–`0021` byte-for-byte and adds:

- `proactive_preference_heads`, one authoritative owner-qualified current head over immutable preference revisions;
- database guards requiring an exact stored revision and monotonic head advancement;
- owner/source advisory transaction locks inside offline evidence admission before the revocation check.

Runtime corrections now:

- serialize preference saving and new proactive execution on the same owner lock;
- resolve the authoritative current preference only after that lock is held, while retaining the command's requested revision solely as immutable input/idempotency material;
- make queued work saved under revision 1 adopt a later revision 2 disable before any new decision or delivery;
- take the offline owner lock in manual lifecycle proposal creation;
- take the identical owner-then-source lock order in privileged erasure and sort lifecycle evidence IDs before insertion.

An idempotent replay of an already completed proactive request still returns its immutable historical result and creates no new effect. Every genuinely new execution uses the current head.

## Direct regression evidence

The final focused Stage 6/7 PostgreSQL integration run passed **18/18** tests. The new regressions proved:

- an enabled revision 1 command was enqueued, revision 2 globally disabled was then saved, and the worker succeeded with revision 2, `DROP`, and no delivery attempt;
- a lifecycle proposal inserted without the Python owner lock held the database admission transaction locks while erasure waited; after release, erasure removed the proposal/evidence, leaving one revocation, zero evidence, and `audit_provenance_integrity() == []`.

## Fresh installation

- Dedicated disposable database; migrations `0001`–`0022`.
- Complete PostgreSQL-backed suite: **228 passed, 0 failed, 0 skipped** in **15.491 s**.
- Migration reapplication: `{"applied": []}`.
- Provenance audit: `[]`.
- Stage 4, 5, 6, and 7 foreign-key-index audits: `[]` for each stage.

## Populated `0021` to `0022` upgrade

- A `0001`–`0021` database contained immutable proactive preference revisions 1 and 4 plus one Stage 7 Reflection evidence edge and one lifecycle evidence edge.
- Applying current source added only `0022_stage67_second_acceptance_corrections.sql`.
- The new head resolved to revision 4 and its exact revision ID; both pre-upgrade evidence edges remained readable (`1`, `1`).
- Complete PostgreSQL-backed suite: **228 passed, 0 failed, 0 skipped** in **15.064 s**.
- Migration reapplication: `{"applied": []}`.
- Provenance audit and Stage 4/5/6/7 foreign-key-index audits: `[]`.

## Additional checks and limits

- `pip check`, contract schema export, bytecode compilation, and `git diff --check` passed.
- PostgreSQL 18.4 and pgvector 0.8.6 were used on the repository-owned local cluster.
- Stage 6 remains local, Web-inbox-only, simulation-only, and structurally `external_delivery_authorized=false`.
- Stage 7 remains deterministic and proposal-only; it cannot send, mutate Memory, or activate training.
- The earlier `STAGE67_ACCEPTANCE_CORRECTION_CHECKPOINT.md` and initial Stage 6/7 checkpoints are historical rejected evidence.

This checkpoint is not self-accepted. The next allowed action is Product Owner reacceptance review or another bounded correction request. Stage 8 remains unauthorized.
