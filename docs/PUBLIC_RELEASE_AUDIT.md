# Public Release and Privacy Audit

- Audit date: 2026-08-26
- Target: cyh-2101/HAVRE-sc
- Source snapshot: private archival commit
  58fa49b4ccb6fbf7d01b76e6d293b5121ead8eeb
- Decision: **PUBLICATION CANDIDATE: PASS**

This report applies only to the sanitized, squashed public mirror. It is not an
authorization to publish the private HAVRE repository or its Git history.

## Publication controls

- The mirror was created from the exact committed source snapshot with Git
  archive; the private .git directory and all prior author metadata are absent.
- The new root commit must use the GitHub noreply identity for cyh-2101.
- Apache-2.0 is present at the repository root. Checked-in fixture records that
  declare CC0-1.0 retain that separate license; referenced external models and
  dependencies are not relicensed.
- Owner-specific Windows and WSL paths were replaced with stable placeholders
  only in the public mirror.
- Owner-private chats, Memory, feedback text, databases, backups, logs, tokens,
  credentials, cookies, device identifiers, model weights, and runtime state
  are absent.
- OA case text, case-level outputs, scoring, and private review notes are
  absent. Public documents may retain a bounded statement that a physically
  separate private evaluation existed.
- Rejected and superseded conclusions remain visible. Sanitization does not
  turn a rejected candidate into a release or make private evidence public.

## Evidence integrity boundary

Some historical checkpoint and report files originally recorded owner-local
paths. Their public copies replace those paths with placeholders and therefore
are not byte-identical to the private archival evidence. Hashes printed inside
the documents remain references to the private canonical artifacts; the public
mirror does not claim that a redacted copy has the same hash.

The private archive remains authoritative for Product Owner decisions, exact
immutable bytes, and non-public evaluation evidence. The public mirror is the
research showcase and reproducibility surface.

## Public-safe contents

- source code, migrations, typed contracts, and generated schemas;
- architecture, ADRs, state/roadmap boundaries, and checkpoint conclusions;
- repository-owned synthetic/public fixtures and aggregate measurements;
- deterministic synthetic showcase runner and Web UI;
- resume claim-to-evidence map and explicit prohibited overclaims.

## Never add to this mirror

- owner data, real conversations, private feedback, Memory, or screenshots;
- OA material or any case-level private evaluation artifact;
- .env files, keys, tokens, cookies, credentials, signing material, or device
  identifiers;
- var, databases, backups, logs, model weights, local serving state, or process
  attestations containing machine paths;
- private archival commits or author metadata.

## Required verification before each push

1. Scan the complete public tree and Git history for secrets, owner paths,
   private/OA filenames, large files, and personal author metadata.
2. Run the public-compatible matrix and focused documentation checks on the
   exact publication snapshot. Confirm every private-artifact-bound exclusion
   still matches `docs/PUBLIC_TESTING.md`; never report excluded tests as passed.
3. Run the synthetic demo on a dedicated loopback-only showcase database.
4. Confirm generated runtime output remains ignored and PostgreSQL is restored
   to its prior state.
5. Review the final staged file list and diff.

## Exact pre-push verification

- Public-compatible matrix: **433 tests passed**, zero failures and zero skips
  in the selected matrix; **90 tests were explicitly excluded** because they
  require private/local artifacts listed in `docs/PUBLIC_TESTING.md`.
- Provenance audit on the migrated disposable database: `[]`.
- Public-safe synthetic demo: completed all six declared flow sections with the
  deterministic provider and zero provenance violations.
- Wrapper and documentation checks: PowerShell parse passed; showcase docs and
  demo boundary tests passed.
- Environment and source checks: `pip check`, `compileall`, and
  `git diff --check` passed.
- PostgreSQL: both disposable databases were deleted and the verified local
  cluster was restored to its prior stopped state.

For transparency, raw archival discovery was also attempted before the public
runner was added. It ran 443 primary-environment tests and reported one failure
and 13 errors where ignored Stage 2 benchmark output, private OA/unseen/dataset
artifacts, or pre-normalization Windows line endings were unavailable. Those
results were not called passing. LF normalization fixed the public fixture
hash mismatch; private-artifact dependencies remain intentionally excluded.

Passing this report does not establish production quality, capacity, legal
advice, or permission to publish future private artifacts.
