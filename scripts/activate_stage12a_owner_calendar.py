"""Activate and import one owner-provided ICS through canonical Stage 12A.

This owner-local command provisions one narrow context-operator login, persists
its secrets only under an ignored local state directory, and stores only the
availability projection produced by the existing Stage 12A adapter.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import secrets
from urllib.parse import quote, urlparse

import psycopg
from psycopg import sql

from apps.calendar_agent.calendar import CalendarAvailabilityAdapter, opaque_manual_calendar_binding
from apps.calendar_agent.ics import IcsCalendarProvider
from apps.windows_agent.offline_queue import read_dpapi_secret, write_dpapi_secret
from companion.life_context import (
    CalendarContextActivationBundle,
    CalendarImportPolicy,
    ConsentScopeRevision,
    ContextSourceCapability,
    ContextSourceDescriptor,
    RetentionPolicy,
)
from companion.persistence import PostgresRepository, Stage12ContextStore, require_isolated_context_operator
from companion.policy import DataPolicy, PrivacyClass


LOGIN = "havre_context_calendar_local"


def _instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("calendar window values must be timezone-aware")
    return parsed.astimezone(UTC)


def _write_private(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)


def _provision_context_login(admin_url: str, password: str) -> str:
    parsed = urlparse(admin_url)
    database = parsed.path.lstrip("/")
    if parsed.hostname not in {"127.0.0.1", "localhost"} or not database.startswith("havre_local_"):
        raise ValueError("owner Calendar activation requires an exact loopback havre_local_* database")
    with psycopg.connect(admin_url) as connection, connection.transaction():
        identity = connection.execute(
            "SELECT current_setting('data_directory') AS data_directory, current_database() AS database"
        ).fetchone()
        owners = connection.execute("SELECT owner_id FROM havre.owners ORDER BY owner_id").fetchall()
        if len(owners) != 1:
            raise ValueError("owner-local Calendar activation requires exactly one owner")
        exists = connection.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (LOGIN,)).fetchone()
        if exists is None:
            connection.execute(sql.SQL("CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE").format(sql.Identifier(LOGIN)))
        memberships = connection.execute(
            """SELECT parent.rolname FROM pg_auth_members membership
               JOIN pg_roles child ON child.oid=membership.member
               JOIN pg_roles parent ON parent.oid=membership.roleid
               WHERE child.rolname=%s""",
            (LOGIN,),
        ).fetchall()
        unexpected = {row[0] for row in memberships} - {"havre_context_operator"}
        if unexpected:
            raise ValueError(f"existing Calendar login has unexpected role memberships: {sorted(unexpected)}")
        connection.execute(
            sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                sql.Identifier(LOGIN), sql.Literal(password)
            )
        )
        connection.execute(sql.SQL("ALTER ROLE {} INHERIT").format(sql.Identifier(LOGIN)))
        connection.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO havre_context_operator").format(
                sql.Identifier(database)
            )
        )
        connection.execute(
            sql.SQL("GRANT havre_context_operator TO {} WITH INHERIT TRUE").format(
                sql.Identifier(LOGIN)
            )
        )
        owner_id = owners[0][0]
    port = parsed.port or 5432
    return (
        f"postgresql://{LOGIN}:{quote(password, safe='')}@{parsed.hostname}:{port}/{database}",
        owner_id,
        identity[0],
    )


def _ingest_through_core(*, admin_url: str, owner_id, secret: bytes, draft):
    """Core validates the signed draft; the isolated source role never writes observations."""
    repository = PostgresRepository(admin_url)
    repository.open()
    try:
        return Stage12ContextStore(
            repository=repository,
            owner_id=owner_id,
            device_secret_resolver=lambda _binding: secret,
        ).ingest(draft)
    finally:
        repository.close()


def _resume_import(args, *, state_dir: Path, window_from: datetime, window_to: datetime):
    bundle = CalendarContextActivationBundle.model_validate_json(
        (state_dir / "activation-bundle.json").read_text(encoding="utf-8")
    )
    secret = read_dpapi_secret(state_dir / "device-secret.dpapi")
    context_url, _owner_id, _data_directory = _provision_context_login(
        args.admin_database_url, secrets.token_urlsafe(36)
    )
    require_isolated_context_operator(context_url)
    repository = PostgresRepository(context_url)
    repository.open()
    try:
        store = Stage12ContextStore(
            repository=repository,
            owner_id=bundle.source.owner_id,
            device_secret_resolver=lambda binding: secret if binding == bundle.source.device_binding_id else (_ for _ in ()).throw(KeyError(binding)),
        )
        collection = CalendarAvailabilityAdapter(
            source=bundle.source,
            capability=bundle.capability,
            consent=bundle.consent,
            signing_secret=secret,
            provider=IcsCalendarProvider(path=args.ics, default_timezone=args.default_timezone),
            permit_resolver=lambda: store.current_collection_permit(
                source_instance_id=bundle.source.source_instance_id,
                device_binding_id=bundle.source.device_binding_id,
            ),
        ).collect(window_from=window_from, window_to=window_to)
    finally:
        repository.close()
    return bundle, collection, _ingest_through_core(
        admin_url=args.admin_database_url,
        owner_id=bundle.source.owner_id,
        secret=secret,
        draft=collection.draft,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--admin-database-url", required=True)
    parser.add_argument("--ics", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, default=Path("var/calendar"))
    parser.add_argument("--window-from", default="2026-08-01T00:00:00Z")
    parser.add_argument("--window-to", default="2027-01-15T00:00:00Z")
    parser.add_argument("--default-timezone", default="America/Chicago")
    parser.add_argument("--authorization-ref", default="po-daily-companion-stage12a-owner-ics-2026-08-27")
    parser.add_argument("--resume", action="store_true", help="resume the locally stored activation without creating another source")
    args = parser.parse_args()

    window_from, window_to = _instant(args.window_from), _instant(args.window_to)
    if window_to <= window_from or window_to - window_from > timedelta(days=200):
        raise ValueError("Calendar import window must be positive and no longer than 200 days")
    state_dir = args.state_dir.resolve()
    state_dir.mkdir(parents=True, exist_ok=True)
    if args.resume:
        bundle, collected, ingested = _resume_import(
            args, state_dir=state_dir, window_from=window_from, window_to=window_to
        )
        receipt = {
            "schema_version": 1,
            "status": "activated_and_imported",
            "source_instance_id": str(bundle.source.source_instance_id),
            "activation_id": str(bundle.activation_id),
            "bundle_hash": bundle.content_hash,
            "observation_id": str(ingested.observation.observation_id),
            "window_from": window_from.isoformat(),
            "window_to": window_to.isoformat(),
            "calendar_files_seen": collected.calendars_seen,
            "provider_rows_seen": collected.provider_rows_seen,
            "retained_busy_intervals": collected.retained_busy_intervals,
            "content_included": False,
            "source_native_file_copied": False,
            "network_provider_used": False,
            "privacy_class": "LOCAL_ONLY",
            "memory_eligible": False,
            "training_eligible": False,
            "cloud_eligible": False,
            "isolated_context_login": LOGIN,
        }
        (state_dir / "activation-receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        print(json.dumps(receipt, indent=2))
        return
    password = secrets.token_urlsafe(36)
    context_url, owner_id, data_directory = _provision_context_login(args.admin_database_url, password)
    require_isolated_context_operator(context_url)
    secret = secrets.token_urlsafe(48).encode("utf-8")
    write_dpapi_secret(state_dir / "device-secret.dpapi", secret)
    now = datetime.now(UTC).replace(microsecond=0)
    source = ContextSourceDescriptor(
        owner_id=owner_id,
        source_kind="calendar",
        provider_id="manual-ics",
        device_binding_id=f"calendar:manual-ics:{secrets.token_hex(16)}",
        adapter_version="manual-ics-calendar-v1",
        source_version="rfc5545-bounded-v1",
        provider_tenant_binding=opaque_manual_calendar_binding("owner-local-manual-ics"),
        provider_account_binding=opaque_manual_calendar_binding("owner-local-fall-2026-course-calendar"),
    )
    capability = ContextSourceCapability(
        owner_id=owner_id,
        source_instance_id=source.source_instance_id,
        capability_id="calendar.read_availability.v1",
        observation_kind="calendar_availability_window",
        allowed_fields=("busy_intervals",),
        precision="availability_only_no_content",
        sampling_modes=("owner_initiated_import",),
        conformance_version="calendar-availability-adapter-conformance-v1",
    )
    policy = DataPolicy(
        privacy_class=PrivacyClass.LOCAL_ONLY,
        memory_eligible=False,
        training_eligible=False,
        cloud_eligible=False,
        decision_source="owner_explicit",
        authorization_ref=args.authorization_ref,
    )
    consent = ConsentScopeRevision(
        owner_id=owner_id,
        source_instance_id=source.source_instance_id,
        capability_revision_id=capability.capability_revision_id,
        revision=1,
        status="active",
        allowed_observation_kinds=("calendar_availability_window",),
        allowed_fields=("busy_intervals",),
        sampling_policy=CalendarImportPolicy(
            policy_version="manual-ics-semester-import-v1",
            max_coverage_seconds=17_280_000,
            max_clock_skew_seconds=300,
            offline_buffer_seconds=300,
        ),
        retention_policy=RetentionPolicy(
            policy_version="calendar-canonical-retention-v1",
            normalized_draft_retention_seconds=0,
            canonical_retention_days=240,
        ),
        data_policy=policy,
        effective_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(days=200),
        authorization_ref=args.authorization_ref,
    )
    bundle = CalendarContextActivationBundle(
        source=source,
        capability=capability,
        consent=consent,
        owner_activation_ref=args.authorization_ref,
    )
    _write_private(state_dir / "activation-bundle.json", bundle.model_dump_json(indent=2))

    repository = PostgresRepository(context_url)
    repository.open()
    try:
        store = Stage12ContextStore(
            repository=repository,
            owner_id=owner_id,
            device_secret_resolver=lambda binding: secret if binding == source.device_binding_id else (_ for _ in ()).throw(KeyError(binding)),
        )
        store.activate_calendar_bundle(bundle)
        permit = store.current_collection_permit(
            source_instance_id=source.source_instance_id,
            device_binding_id=source.device_binding_id,
        )
        collected = CalendarAvailabilityAdapter(
            source=source,
            capability=capability,
            consent=consent,
            signing_secret=secret,
            provider=IcsCalendarProvider(path=args.ics, default_timezone=args.default_timezone),
            permit_resolver=lambda: store.current_collection_permit(
                source_instance_id=source.source_instance_id,
                device_binding_id=source.device_binding_id,
            ),
        ).collect(window_from=window_from, window_to=window_to)
    finally:
        repository.close()
    ingested = _ingest_through_core(
        admin_url=args.admin_database_url,
        owner_id=owner_id,
        secret=secret,
        draft=collected.draft,
    )

    receipt = {
        "schema_version": 1,
        "status": "activated_and_imported",
        "source_instance_id": str(source.source_instance_id),
        "activation_id": str(bundle.activation_id),
        "bundle_hash": bundle.content_hash,
        "observation_id": str(ingested.observation.observation_id),
        "window_from": window_from.isoformat(),
        "window_to": window_to.isoformat(),
        "calendar_files_seen": collected.calendars_seen,
        "provider_rows_seen": collected.provider_rows_seen,
        "retained_busy_intervals": collected.retained_busy_intervals,
        "content_included": False,
        "source_native_file_copied": False,
        "network_provider_used": False,
        "privacy_class": "LOCAL_ONLY",
        "memory_eligible": False,
        "training_eligible": False,
        "cloud_eligible": False,
        "isolated_context_login": LOGIN,
        "postgres_data_directory": data_directory,
    }
    (state_dir / "activation-receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
