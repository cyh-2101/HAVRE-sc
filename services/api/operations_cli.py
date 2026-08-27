"""Implementation helpers for Stage 10 operational CLI commands."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from uuid import UUID

import psycopg

from companion.operations import (
    DeploymentRecord,
    ReleaseApprovalRecord,
    ReleaseManifest,
)
from companion.operations.backup import BackupService
from companion.operations.ledger import ErasureLedger
from companion.persistence import PostgresRepository, Stage10PostgresStore
from services.api.source_provenance import (
    current_source_revision,
    deployment_source_snapshot_revision,
    git_head_revision,
)
from services.api.release_binding import (
    component_promotion_authorizations,
    expected_release_components,
    required_component_promotion_authorizations,
)
from services.api.runtime import build_runtime
from services.api.settings import Settings


def build_release_manifest(
    *,
    settings: Settings,
    release_id: str,
    environment: str,
    release_scope: str,
    output: Path,
    adapter_version: str | None = None,
    adapter_hash: str | None = None,
    adapter_deployment_authorized: bool = False,
    promotion_approval_ref: str | None = None,
    rollback_manifest_hash: str | None = None,
    runtime_image_reference: str | None = None,
    runtime_image_digest: str | None = None,
) -> ReleaseManifest:
    project_root = Path(__file__).resolve().parents[2]
    head = git_head_revision(project_root)
    if current_source_revision(project_root) != head:
        raise ValueError("release manifests can be built only from a clean source tree")
    migration = sorted((project_root / "db" / "migrations").glob("*.sql"))[-1]
    if (adapter_version is None) != (adapter_hash is None):
        raise ValueError("adapter version and hash must be supplied together")
    if adapter_version is not None and settings.runtime_adapter_version is not None:
        raise ValueError("adapter must be supplied by CLI or runtime settings, not both")
    binding_settings = settings.model_copy(
        update=(
            {}
            if adapter_version is None
            else {
                "runtime_adapter_version": adapter_version,
                "runtime_adapter_hash": adapter_hash,
            }
        )
    )
    components = list(
        expected_release_components(
            settings=binding_settings,
            source_snapshot_hash=deployment_source_snapshot_revision(project_root),
            migration_path=migration,
            environment=environment,
            runtime_image_reference=runtime_image_reference,
            runtime_image_digest=runtime_image_digest,
        )
    )
    adapter = next(
        (item for item in components if item.component == "adapter"),
        None,
    )
    required_authorizations = required_component_promotion_authorizations(
        components=components,
        settings=binding_settings,
    )
    if adapter_deployment_authorized:
        from services.api.release_binding import component_promotion_authorizations

        authorization = next(
            (
                item
                for item in component_promotion_authorizations(binding_settings)
                if item.component == "adapter"
                and item.version == adapter.version
                and item.artifact_hash == adapter.artifact_hash
            ),
            None,
        ) if adapter is not None else None
        if authorization is None or promotion_approval_ref != authorization.content_hash:
            raise ValueError(
                "adapter deployment requires its exact Product Owner promotion artifact"
            )
    manifest = ReleaseManifest(
        release_id=release_id,
        environment=environment,
        release_scope=release_scope,
        source_revision=head,
        migration_head=migration.name,
        components=tuple(components),
        constitution_version_id="constitution-v1",
        identity_version_id="identity-v1",
        values_version_id="values-v1",
        adapter_deployment_authorized=adapter_deployment_authorized,
        promotion_approval_ref=promotion_approval_ref,
        component_promotion_authorization_hashes=tuple(
            item.content_hash for item in required_authorizations
        ),
        rollback_release_manifest_hash=rollback_manifest_hash,
    )
    output = output.resolve()
    if output.exists():
        raise FileExistsError("release manifest output already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        manifest.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest


def load_release_manifest(path: Path) -> ReleaseManifest:
    return ReleaseManifest.model_validate_json(path.read_text(encoding="utf-8"))


def _persist_release_bundle(
    *,
    store: Stage10PostgresStore,
    settings: Settings,
    manifest: ReleaseManifest,
) -> None:
    available = {
        item.content_hash: item
        for item in component_promotion_authorizations(settings)
    }
    if set(manifest.component_promotion_authorization_hashes) - set(available):
        raise ValueError("release references unavailable component authorization bytes")
    for content_hash_value in manifest.component_promotion_authorization_hashes:
        store.persist_component_promotion_authorization(available[content_hash_value])
    store.persist_release_manifest(manifest)


def _release_store(settings: Settings) -> tuple[PostgresRepository, Stage10PostgresStore]:
    url = settings.release_database_url
    if url is None:
        if settings.deployment_environment in {"staging", "production"}:
            raise ValueError("release operator database URL is required")
        url = settings.database_url
    if settings.deployment_environment in {"staging", "production"}:
        with psycopg.connect(url) as connection:
            release_user, release_allowed, release_erasure, release_app = (
                connection.execute(
                    """
                    SELECT current_user,
                           pg_has_role(current_user,'havre_release_operator','MEMBER'),
                           pg_has_role(current_user,'havre_privileged_erasure','MEMBER'),
                           pg_has_role(current_user,'havre_application','MEMBER')
                    """
                ).fetchone()
            )
        if (
            not release_allowed
            or release_erasure
            or release_app
        ):
            raise ValueError("release credential is not an isolated release operator")
    repository = PostgresRepository(url)
    repository.open()
    return repository, Stage10PostgresStore(
        repository=repository,
        owner_id=settings.owner_id,
    )


def record_release_approval(
    *,
    settings: Settings,
    manifest_path: Path,
    approval_scope: str,
    decision: str,
    rationale: str,
) -> ReleaseApprovalRecord:
    manifest = load_release_manifest(manifest_path)
    approval = ReleaseApprovalRecord(
        owner_id=settings.owner_id,
        release_manifest_id=manifest.release_manifest_id,
        release_manifest_hash=manifest.content_hash,
        approval_scope=approval_scope,
        decision=decision,
        rationale=rationale,
    )
    repository, store = _release_store(settings)
    try:
        _persist_release_bundle(store=store, settings=settings, manifest=manifest)
        store.persist_release_approval(approval)
        return approval
    finally:
        repository.close()


def verify_release_preflight(
    *, settings: Settings, manifest_path: Path
) -> dict[str, object]:
    """Verify the actual release login and restored durable gate without writes."""

    manifest = load_release_manifest(manifest_path)
    repository, store = _release_store(settings)
    try:
        store.require_release_preflight(manifest)
        return {
            "release_manifest_hash": manifest.content_hash,
            "environment": manifest.environment,
            "preflight_verified": True,
            "applied_deployment": store.release_activation_status(manifest),
        }
    finally:
        repository.close()


def record_deployment(
    *,
    settings: Settings,
    manifest_path: Path,
    action: str,
    status: str,
    previous_deployment_id: UUID | None,
    health_evidence_path: Path | None,
    failure_code: str | None,
) -> DeploymentRecord:
    manifest = load_release_manifest(manifest_path)
    health_evidence = None
    if health_evidence_path is not None:
        import json

        health_evidence = json.loads(health_evidence_path.read_text(encoding="utf-8"))
        if not isinstance(health_evidence, dict):
            raise ValueError("health evidence must be a JSON object")
    record = DeploymentRecord(
        owner_id=settings.owner_id,
        release_manifest_id=manifest.release_manifest_id,
        release_manifest_hash=manifest.content_hash,
        environment=manifest.environment,
        action=action,
        status=status,
        previous_deployment_id=previous_deployment_id,
        health_evidence=health_evidence,
        failure_code=failure_code,
    )
    repository, store = _release_store(settings)
    try:
        _persist_release_bundle(store=store, settings=settings, manifest=manifest)
        store.record_deployment(record)
        return record
    finally:
        repository.close()


def export_owner(*, settings: Settings, output: Path) -> object:
    runtime = build_runtime(settings)
    try:
        manifest = runtime.operations_store.export_owner_data(
            output,
            erasure_ledger=runtime.erasure_ledger,
        )
        runtime.operations_store.verify_owner_export(output)
        return manifest
    finally:
        runtime.close()


def erase_source(
    *, settings: Settings, source_event_id: UUID, confirmation: str
) -> dict[str, object]:
    if confirmation != "raw_source_and_derived":
        raise ValueError("exact source-erasure confirmation is required")
    if settings.privileged_database_url is None:
        raise ValueError("privileged erasure database URL is required")
    runtime = build_runtime(settings)
    try:
        return runtime.operations_store.erase_source_event(
            source_event_id=source_event_id,
            ledger=runtime.erasure_ledger,
        )
    finally:
        runtime.close()


def erase_context_source(
    *, settings: Settings, source_instance_id: UUID, confirmation: str
) -> dict[str, object]:
    if confirmation != "context_source_and_derived":
        raise ValueError("exact context-source erasure confirmation is required")
    if settings.privileged_database_url is None:
        raise ValueError("privileged erasure database URL is required")
    runtime = build_runtime(settings)
    try:
        return runtime.operations_store.erase_context_source(
            source_instance_id=source_instance_id,
            ledger=runtime.erasure_ledger,
        )
    finally:
        runtime.close()


def expire_context_retention(*, settings: Settings) -> dict[str, object]:
    """Execute only server-time-due canonical context retention."""

    if settings.privileged_database_url is None:
        raise ValueError("privileged erasure database URL is required")
    runtime = build_runtime(settings)
    try:
        return runtime.operations_store.expire_context_retention(
            ledger=runtime.erasure_ledger
        )
    finally:
        runtime.close()


def create_backup(
    *,
    settings: Settings,
    release_manifest_path: Path,
    output: Path,
    expires_days: int,
    pg_dump: Path,
    pg_restore: Path,
) -> dict[str, object]:
    release = load_release_manifest(release_manifest_path)
    repository, store = _release_store(settings)
    try:
        _persist_release_bundle(store=store, settings=settings, manifest=release)
        store.require_release_activation(release)
        service = BackupService(
            pg_dump=pg_dump,
            pg_restore=pg_restore,
            ledger=ErasureLedger(settings.erasure_ledger_path),
        )
        artifact, manifest_path, manifest = service.create_backup(
            database_url=settings.database_url,
            destination=output,
            release=release,
            owner_id=settings.owner_id,
            expires_after=timedelta(days=expires_days),
        )
        store.persist_backup_manifest(
            manifest,
            artifact_uri=f"local://backups/{artifact.name}",
        )
        return {
            "artifact": str(artifact),
            "manifest": str(manifest_path),
            "content_hash": manifest.content_hash,
            "expires_at": manifest.expires_at,
        }
    finally:
        repository.close()


def restore_backup(
    *,
    settings: Settings,
    artifact: Path,
    manifest: Path,
    target_database_url: str,
    restore_id: UUID,
    pg_dump: Path,
    pg_restore: Path,
) -> dict[str, object]:
    with psycopg.connect(target_database_url) as connection:
        (
            restore_user,
            restore_allowed,
            restore_superuser,
            target_owner,
            restore_is_app,
            restore_is_release,
            restore_is_erasure_executor,
        ) = connection.execute(
            """
            SELECT current_user,
                   pg_has_role(current_user,'havre_restore_operator','MEMBER'),
                   (SELECT rolsuper FROM pg_roles WHERE rolname=current_user),
                   pg_get_userbyid(database.datdba),
                   pg_has_role(current_user,'havre_application','MEMBER'),
                   pg_has_role(current_user,'havre_release_operator','MEMBER'),
                   pg_has_role(current_user,'havre_erasure_executor','MEMBER')
            FROM pg_database AS database
            WHERE database.datname=current_database()
            """
        ).fetchone()
    if (
        not restore_allowed
        or restore_superuser
        or restore_user != target_owner
        or restore_is_app
        or restore_is_release
        or restore_is_erasure_executor
    ):
        raise ValueError(
            "restore credential must be the isolated target owner and restore operator"
        )
    service = BackupService(
        pg_dump=pg_dump,
        pg_restore=pg_restore,
        ledger=ErasureLedger(settings.erasure_ledger_path),
    )

    def store_factory(url: str) -> Stage10PostgresStore:
        repository = PostgresRepository(url)
        repository.open()
        return Stage10PostgresStore(
            repository=repository,
            owner_id=settings.owner_id,
            erasure_repository=repository,
        )

    return service.restore_verified_backup(
        artifact=artifact,
        manifest_path=manifest,
        target_database_url=target_database_url,
        restore_id=restore_id,
        store_factory=store_factory,
    )


def prune_backups(
    *,
    settings: Settings,
    root: Path,
    confirmation: str,
    pg_dump: Path,
    pg_restore: Path,
) -> tuple[dict[str, object], ...]:
    service = BackupService(
        pg_dump=pg_dump,
        pg_restore=pg_restore,
        ledger=ErasureLedger(settings.erasure_ledger_path),
    )
    return service.prune_expired_backups(
        root=root,
        confirmed=confirmation == "expired_local_backups",
    )
