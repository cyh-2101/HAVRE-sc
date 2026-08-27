# Stage 10 owner-controlled deployment

This deployment runs the existing HAVRE modular monolith behind Caddy HTTPS.
It does not promote an adapter. `deterministic-local` is an integration fixture;
production behavioral traffic remains quarantined because its components are
not Product Owner-promoted. The provider and adapter remain replaceable release
components, and no Stage 9 seed is named here.

## Exact build and configuration

Run from an exact clean commit. Never build from the repository root directly:
the root `.dockerignore` is deny-all. Generate the committed-only context and
use the Dockerfiles exported inside it. The API build installs the exact
Linux runtime dependency lock and fails on `pip check`:

```powershell
.\.venv\Scripts\python.exe -m scripts.build_stage10_image_context --output var/stage10-image-context
docker build -f var/stage10-image-context/deploy/Dockerfile var/stage10-image-context `
  --build-arg PYTHON_IMAGE=python@sha256:<digest> `
  --build-arg HAVRE_SOURCE_REVISION=<clean-commit> `
  --build-arg HAVRE_SOURCE_SNAPSHOT=<snapshot-from-context-manifest> `
  -t owner/havre:<build-id>
docker build -f var/stage10-image-context/deploy/Operations.Dockerfile var/stage10-image-context `
  --build-arg HAVRE_API_IMAGE=owner/havre@sha256:<api-digest> `
  --build-arg POSTGRES_CLIENT_IMAGE=pgvector/pgvector@sha256:<same-database-image-digest> `
  --build-arg HAVRE_SOURCE_REVISION=<clean-commit> `
  --build-arg HAVRE_SOURCE_SNAPSHOT=<snapshot-from-context-manifest> `
  -t owner/havre-operations:<build-id>
```

The operations image copies the source-bound API runtime onto an exact
PostgreSQL 18 client image, so `pg_dump` and `pg_restore` match the deployed
server major version. Resolve both resulting digests and pin them,
PostgreSQL+pgvector, and Caddy in a private `.env` copied from `.env.example`.
Build the release manifest from the same clean checkout, then run the
executable preflight before every Compose action:

```powershell
.\.venv\Scripts\havre.exe release-build --release-id <id> --environment production --scope infrastructure_only --output deploy/release-manifest.json --runtime-image-reference owner/havre@sha256:<api-digest> --runtime-image-digest sha256:<api-digest>
.\.venv\Scripts\python.exe -m scripts.verify_stage10_deployment_config
docker compose --env-file deploy/.env -f deploy/compose.yaml config
```

The preflight rejects mutable image tags and checks the exact committed compose,
Caddy, role, Docker recipe, application, migration, and validator bytes against
`companion_core` in the release manifest. Dirty host deployment files fail
closed.

## Secrets and roles

Keep mode-600 secret files outside Git. Use distinct LOGIN identities for
migration, application, erasure, release operation, and offline restore. After migrations, apply
the checked group-role grants as database owner; create and grant the separate
LOGIN users outside this repository:

```powershell
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d postgres
docker compose --env-file deploy/.env -f deploy/compose.yaml run --rm migrate
Get-Content deploy/bootstrap_roles.sql | docker compose --env-file deploy/.env -f deploy/compose.yaml exec -T postgres psql -U postgres -d havre -v DBNAME=havre
```

The checked migrate unit uses `migrate --bootstrap-owner`: after applying the
checksum-verified migrations it provisions the configured owner and the
already-approved Constitution, Identity, and Values. This makes the subsequent
release-manifest foreign key and preflight checks explicit and non-circular;
plain `havre migrate` remains migration-only.

The secretless, network-disabled `storage-init` one-shot grants UID 10001
ownership only on the three named owner-operation volumes before API, backup,
or restore uses them. Long-running and operational services stay non-root.

Only the API receives the erasure credential and owner bearer token. The
behavior worker receives neither the bearer token nor the erasure ledger;
offline release, backup, and restore units also receive no bearer token.
Release operations receive only the release credential, backup receives app
read plus release credentials, and restore receives only its explicit target.

## Explicit release and rollback

1. Record the Product Owner infrastructure decision with `release-operations
   release-approval-record ... --scope infrastructure_production_release`.
2. Start API and Caddy. `/health/live`, `/health/preflight`, and
   `/health/ready` may pass for the approved infrastructure while the readiness
   payload reports `release_active: false`; all behavioral routes remain 503.
3. Capture a `deployment-health-evidence-v1` JSON bound to the exact manifest,
   environment, source revision, API image digest, passing checks, and time.
4. Mount it read-only and run `release-operations deployment-record ...
   --action deploy --status applied --health-evidence /run/havre/health.json`.
5. Recheck that readiness now reports `release_active: true`, plus metrics and
   controlled failure/load evidence. Start the
   `behavior` profile only for an exact applied behavioral release. The current
   infrastructure-only candidate fixture must never start it.

A rollback manifest names the exact target hash. Roll back only from the latest
applied deployment using `--action rollback --previous-deployment-id <latest>`
and passing health evidence. The database rejects stale or unapproved targets.
Rollback is also a real runtime transition: atomically restore the pinned prior
manifest plus its API and operations image digests in `.env`, rerun the source
and image preflight, force-recreate API and Caddy, and capture health evidence
from that prior image before appending the rollback record. Changing only the
database ledger is not a deployment rollback.

The one-shot commands are run against the internal network without publishing
PostgreSQL. For example:

```powershell
docker compose --env-file deploy/.env -f deploy/compose.yaml run --rm release-operations release-approval-record /run/havre/release-manifest.json --scope infrastructure_production_release --decision approved --rationale "Product Owner infrastructure approval"
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d api caddy
docker compose --env-file deploy/.env -f deploy/compose.yaml run --rm -v <absolute-health-json>:/run/havre/health.json:ro release-operations deployment-record /run/havre/release-manifest.json --action deploy --status applied --health-evidence /run/havre/health.json
# For rollback, first atomically restore the prior manifest/API/operations digests in deploy/.env.
.\.venv\Scripts\python.exe -m scripts.verify_stage10_deployment_config
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d --force-recreate api caddy
docker compose --env-file deploy/.env -f deploy/compose.yaml run --rm -v <absolute-prior-health-json>:/run/havre/health.json:ro release-operations deployment-record /run/havre/release-manifest.json --action rollback --status applied --previous-deployment-id <latest-applied-deployment-id> --health-evidence /run/havre/health.json
```

## Backup, restore, export, and erasure

`backup-operations backup-create` writes a checksum-bound custom dump and
manifest to `owner_backups`, binds it to the current applied release, and records
the completed external erasure-ledger watermark. Expired backups fail restore
closed and are pruned only with `--confirm expired_local_backups`.

Restore is explicitly offline: stop API/worker traffic, provide an empty target
through `havre_restore_database_url`, then run `restore-operations
backup-restore` with the artifact, manifest, target secret, and new restore ID.
It verifies bytes, restores, replays all owners' erasure directives under the
shared lock, audits absence/provenance, and persists replay evidence before
traffic resumes. Because the dump intentionally excludes privileges, the
database administrator must apply the checked `bootstrap_roles.sql` to the
restored database and verify the actual application, release, erasure, and
restore login boundaries before changing any service secret or resuming
traffic. A data-only restore is not a completed cutover.

Because `pg_restore --no-owner` temporarily makes the isolated restore LOGIN
the owner of restored objects, the administrator must first run the checked
`finalize_restore.sql`. It verifies the target/login identities, reassigns all
restored objects and the database to the administrator, and fails if the
restore LOGIN retains ownership. `bootstrap_roles.sql` then revokes database
CONNECT from `PUBLIC` and grants only the four named operational groups.

Before restore, a database administrator must create the separate target owned
by the restore login and preinstall `vector` there. The restore process rejects
a target with HAVRE tables or without that extension; it uses `--no-owner`,
`--no-privileges`, and `--no-comments`, so the unprivileged restore login does
not need to own the administrator-created extension. Discard and recreate the
target after any failed restore attempt.
Grant the restore LOGIN only the checked `havre_restore_operator` group in
addition to ownership of its separate target database. That group carries the
transaction-gated immutable-erasure capability needed for deletion replay, but
no SELECT privilege on owner data in the source database.

```powershell
docker compose --env-file deploy/.env -f deploy/compose.yaml run --rm backup-operations backup-create --release-manifest /run/havre/release-manifest.json --output /var/lib/havre-backups/current --expires-days 30 --pg-dump /usr/lib/postgresql/18/bin/pg_dump --pg-restore /usr/lib/postgresql/18/bin/pg_restore
docker compose --env-file deploy/.env -f deploy/compose.yaml stop caddy api worker
docker compose --env-file deploy/.env -f deploy/compose.yaml run --rm restore-operations backup-restore --artifact <volume-dump-path> --manifest <volume-manifest-path> --target-database-url-file /run/secrets/havre_restore_database_url --restore-id <new-uuidv7> --pg-dump /usr/lib/postgresql/18/bin/pg_dump --pg-restore /usr/lib/postgresql/18/bin/pg_restore
Get-Content deploy/finalize_restore.sql | docker compose --env-file deploy/.env -f deploy/compose.yaml exec -T postgres psql -U postgres -d <restored-database> -v DBNAME=<restored-database> -v RESTORE_LOGIN=havre_restore
Get-Content deploy/bootstrap_roles.sql | docker compose --env-file deploy/.env -f deploy/compose.yaml exec -T postgres psql -U postgres -d <restored-database> -v DBNAME=<restored-database>
# With Caddy and the worker still stopped, atomically repoint all four database URL secret files to the restored database, then recreate the internal API.
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d --force-recreate api
docker compose --env-file deploy/.env -f deploy/compose.yaml exec -T api python -c "import json,urllib.request; print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/health/preflight')))"
docker compose --env-file deploy/.env -f deploy/compose.yaml run --rm release-operations release-preflight /run/havre/release-manifest.json
```

Before cutover, run the checked role-boundary verifier against the restored
database with the real deployment login secrets. Internal API startup verifies
that the application and erasure logins are distinct and have their exact
memberships; `release-preflight` independently opens the release secret,
requires its isolated role, and checks the restored immutable release and
approval records. The already completed restore verified the isolated restore
login. Resume the worker and Caddy only after both commands pass and the exact
applied release reports `applied_deployment: true`. A mixed source/target secret
set must never be started.

Owner export verifies exact manifest membership, including owner-qualified
spans; extra files and symlinks fail. Source erasure requires the exact
`raw_source_and_derived` confirmation and appends the durable external directive
before database closure deletion.

`/metrics` is content-free and bearer-protected. PostgreSQL and API expose no
host ports; only Caddy exposes 443. The bearer token is a bounded single-owner
Stage 10 credential, not the final multi-device identity design.
