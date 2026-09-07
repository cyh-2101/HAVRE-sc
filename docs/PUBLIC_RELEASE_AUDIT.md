# Public release and privacy audit

- Date: 2026-09-07
- Target: cyh-2101/HAVRE-sc
- Private source checkpoint: bcdbba9fa7b4d41d5afd439e45247915d0c7ef8e
- Decision: **PUBLICATION CANDIDATE: PASS**

## Scope and controls

The original new root commit established a public-only history; this update
appends to it and never merges private ancestry. Apache-2.0 is retained. Public
noreply author metadata is used. The private archive remains authoritative.

Source code, migrations, contracts and synthetic tests were refreshed. Private
data directories, new case-level research outputs and personal screenshots were
excluded. Detailed owner audits have explicit technical synopses. Known owner
paths were replaced. Embedded references to a specific private OA example were
removed from the public prompt copy; source policies were not changed.

The full candidate-tree credential/path scan found no secret or owner-path
matches. A local comparison with long owner-message substrings found only
technical source hashes, program-generated import-policy text and a synthetic
course-title fixture; these were reviewed as non-transcript matches. No raw
conversation was exported. Such a scan is bounded evidence, not a guarantee for
future additions.

## Verification

- Public matrix: 825 passed, zero failures/errors/skips; 97 documented exclusions.
- Separate private source: 922 passed, zero failures/errors/skips.
- Dedicated synthetic demo completed; provenance violations: zero.
- Verified public encoder artifacts stayed ignored.
- Final documentation/link checks and source whitespace checks passed.
- Generated evidence stays outside public Git.
- PostgreSQL was already running. Only task-created test databases are removed;
  the owner runtime and earlier databases are preserved.

No owner database, OA material, plaintext backup, credential, browser profile,
device origin or model weight may be added to this repository. Publishing this
source snapshot does not establish production quality, physical-iPhone behavior,
long-term usefulness, or authorization for another stage.
