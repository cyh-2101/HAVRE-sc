"""Composition root for the active HAVRE Stage 10 modular monolith."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg

from companion.application import InteractionService
from companion.context import ContextBuilder
from companion.consolidation.service import ConsolidationService
from companion.goals.service import GoalService
from companion.feedback import FeedbackService
from companion.hashing import content_hash
from companion.identity import IdentityLoader
from companion.memory import DeterministicEmbeddingProvider, DeterministicEpisodicExtractor
from companion.memory.service import MemoryService, MemoryWorker
from companion.state.service import CurrentStateService
from companion.scenes.service import SceneService
from companion.user_model.service import UserModelService
from companion.persistence import PostgresRepository, apply_migrations
from companion.persistence import Stage10PostgresStore
from companion.persistence import Stage12ContextStore
from companion.persistence.scenes import ScenePostgresStore
from companion.persistence.proactive import ProactivePostgresStore
from companion.persistence.offline import Stage7PostgresStore
from mlsys.serving import (
    RuntimeAttestation,
    DeterministicLocalProvider,
    ModelProvider,
    OpenAICompatibleProvider,
    Stage1Router,
    attest_active_runtime,
    write_runtime_attestation,
)
from mlsys.retrieval.service import RetrievalService
from companion.operations import ReleaseManifest
from companion.operations.ledger import ErasureLedger
from services.api.release_binding import (
    expected_release_components,
    required_component_promotion_authorizations,
)
from services.api.settings import Settings


@dataclass
class Runtime:
    settings: Settings
    repository: PostgresRepository
    service: InteractionService
    memory_service: MemoryService
    memory_worker: MemoryWorker
    retrieval_service: RetrievalService
    user_model_service: UserModelService
    consolidation_service: ConsolidationService
    current_state_service: CurrentStateService
    goal_service: GoalService
    scene_service: SceneService
    proactive_store: ProactivePostgresStore
    offline_store: Stage7PostgresStore
    operations_store: Stage10PostgresStore
    context_store: Stage12ContextStore
    feedback_service: FeedbackService
    erasure_ledger: ErasureLedger | None
    release_manifest: ReleaseManifest | None

    def close(self) -> None:
        asyncio.run(self.aclose())

    async def aclose(self) -> None:
        try:
            await self.service.provider.aclose()
        finally:
            self.repository.close()


def _database_role(database_url: str) -> tuple[str, bool, bool, bool, bool]:
    with psycopg.connect(database_url) as connection:
        return connection.execute(
            """
            SELECT current_user,
                   pg_has_role(current_user,'havre_privileged_erasure','MEMBER'),
                   has_table_privilege(current_user,'havre.events','DELETE'),
                   pg_has_role(current_user,'havre_release_operator','MEMBER'),
                   has_table_privilege(
                       current_user,'havre.release_approval_records','INSERT'
                   )
            """
        ).fetchone()


def _validate_deployment_database_roles(settings: Settings) -> None:
    if settings.deployment_environment not in {"staging", "production"}:
        return
    app_user, app_privileged, app_delete, app_release, app_approve = _database_role(
        settings.database_url
    )
    if app_privileged or app_delete or app_release or app_approve:
        raise ValueError("ordinary application database credential is over-privileged")
    if settings.privileged_database_url is None:
        return
    (
        erasure_user,
        erasure_privileged,
        erasure_delete,
        erasure_release,
        erasure_approve,
    ) = _database_role(
        settings.privileged_database_url
    )
    if (
        erasure_user == app_user
        or not erasure_privileged
        or not erasure_delete
        or erasure_release
        or erasure_approve
    ):
        raise ValueError("privileged erasure credential is not a distinct erasure role")


def _open_repository(database_url: str) -> PostgresRepository:
    repository = PostgresRepository(database_url)
    repository.open()
    return repository


def _read_manifest(path: Path, *, artifact_kind: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"cannot load {artifact_kind} manifest at {path}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{artifact_kind} manifest must be a JSON object")
    if payload.get("schema_version") != 1:
        raise ValueError(f"{artifact_kind} manifest schema_version must be 1")
    if payload.get("artifact_kind") != artifact_kind:
        raise ValueError(f"expected {artifact_kind} manifest")
    if payload.get("immutable") is not True:
        raise ValueError(f"{artifact_kind} manifest must be immutable")
    return payload


def _load_release_manifest(settings: Settings, identity) -> ReleaseManifest | None:
    if settings.release_manifest_path is None:
        return None
    try:
        manifest = ReleaseManifest.model_validate_json(
            settings.release_manifest_path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as error:
        raise ValueError("cannot load the immutable release manifest") from error
    if manifest.environment != settings.deployment_environment:
        raise ValueError("release manifest environment does not match runtime")
    project_root = Path(__file__).resolve().parents[2]
    source_marker = project_root / ".havre-source-revision"
    snapshot_marker = project_root / ".havre-source-snapshot"
    if source_marker.is_file():
        revision = source_marker.read_text(encoding="utf-8").strip()
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("image source revision marker is invalid")
        if not snapshot_marker.is_file():
            raise ValueError("image source snapshot marker is missing")
        source_snapshot = snapshot_marker.read_text(encoding="utf-8").strip()
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", source_snapshot):
            raise ValueError("image source snapshot marker is invalid")
    else:
        from services.api.source_provenance import (
            current_source_revision,
            deployment_source_snapshot_revision,
            git_head_revision,
        )

        revision = git_head_revision(project_root)
        if current_source_revision(project_root) != revision:
            raise ValueError("release manifest requires an exact clean source tree")
        source_snapshot = deployment_source_snapshot_revision(project_root)
    if manifest.source_revision != revision:
        raise ValueError("release manifest source does not match the runtime image")
    migration = sorted((project_root / "db" / "migrations").glob("*.sql"))[-1]
    expected_components = expected_release_components(
        settings=settings,
        source_snapshot_hash=source_snapshot,
        migration_path=migration,
    )
    if manifest.migration_head != migration.name:
        raise ValueError("release manifest migration head does not match runtime")
    if manifest.components != expected_components:
        raise ValueError("release manifest components do not match runtime artifacts")
    expected_authorization_hashes = tuple(
        item.content_hash
        for item in required_component_promotion_authorizations(
            components=expected_components,
            settings=settings,
        )
    )
    if manifest.component_promotion_authorization_hashes != expected_authorization_hashes:
        raise ValueError("release component authorizations do not match runtime artifacts")
    if (
        manifest.constitution_version_id != identity.constitution.version_id
        or manifest.identity_version_id != identity.identity.version_id
        or manifest.values_version_id != identity.values.version_id
    ):
        raise ValueError("release manifest governance versions do not match runtime")
    return manifest


def attest_self_hosted_runtime(
    settings: Settings, *, write: bool = False
) -> RuntimeAttestation:
    project_root = Path(__file__).resolve().parents[2]
    runtime_root = project_root / ".runtime" / "stage3"
    attestation = attest_active_runtime(
        runtime_root=runtime_root,
        runtime_state_path=runtime_root / "runtime-state.json",
        runtime_pid_path=runtime_root / "run" / "llama-server.pid",
        model_manifest_path=settings.self_hosted_model_manifest,
        engine_manifest_path=settings.self_hosted_engine_manifest,
        adapter_manifest_path=settings.self_hosted_adapter_manifest,
    )
    if write:
        write_runtime_attestation(
            attestation,
            runtime_root / "run" / "runtime-attestation.json",
        )
    return attestation


def _self_hosted_provider(settings: Settings) -> OpenAICompatibleProvider:
    model = _read_manifest(settings.self_hosted_model_manifest, artifact_kind="model")
    engine = _read_manifest(
        settings.self_hosted_engine_manifest,
        artifact_kind="serving_engine",
    )
    profile = model.get("serving_profile")
    artifact = model.get("artifact")
    upstream_model = model.get("upstream")
    upstream_engine = engine.get("upstream")
    api = engine.get("api")
    if not all(
        isinstance(value, dict)
        for value in (profile, artifact, upstream_model, upstream_engine, api)
    ):
        raise ValueError("self-hosted manifests are missing required objects")
    if profile["serving_engine_manifest_id"] != engine.get("manifest_id"):
        raise ValueError("model and serving-engine manifests are not linked")
    if model.get("lifecycle_status") != "candidate":
        raise ValueError("Stage 3 self-hosted model must remain a candidate")
    model_hash = artifact.get("sha256")
    if not isinstance(model_hash, str) or not model_hash.startswith("sha256:"):
        raise ValueError("model manifest requires an exact SHA-256")
    model_revision = upstream_model.get("revision")
    engine_tag = upstream_engine.get("release_tag")
    engine_commit = upstream_engine.get("commit")
    if not all(isinstance(item, str) and item for item in (
        model_revision, engine_tag, engine_commit
    )):
        raise ValueError("self-hosted manifests require exact upstream revisions")
    runtime_attestation = attest_self_hosted_runtime(settings, write=True)
    if (
        runtime_attestation.active_adapter_version_id
        != settings.runtime_adapter_version
        or runtime_attestation.active_adapter_artifact_hash
        != settings.runtime_adapter_hash
    ):
        raise ValueError("active runtime adapter does not match configured release binding")
    return OpenAICompatibleProvider(
        base_url=settings.self_hosted_base_url,
        transport_model_id=str(model["alias"]),
        model_version_id=str(model["manifest_id"]),
        tokenizer_version_id=(
            f"{upstream_model['repository']}@{model_revision}:embedded-gguf-tokenizer"
        ),
        serving_engine="llama.cpp",
        serving_engine_version=f"{engine_tag}@{engine_commit}",
        serving_config_version=content_hash(profile),
        provider_id=settings.provider_id,
        model_artifact_hash=model_hash,
        adapter_version_id=settings.runtime_adapter_version,
        adapter_artifact_hash=settings.runtime_adapter_hash,
        api_key=settings.self_hosted_api_key,
        max_context_tokens=int(profile["context_tokens"]),
        max_output_tokens=min(4096, int(profile["context_tokens"])),
        health_path=str(api["health_path"]),
        version_path="/props",
        completions_path=str(api["chat_completions_path"]),
        expected_build_substring=f"{engine_tag}-{engine_commit[:8]}",
        runtime_attestation=runtime_attestation,
    )


def _build_provider(settings: Settings) -> ModelProvider:
    if settings.provider_id == DeterministicLocalProvider.provider_id:
        return DeterministicLocalProvider(
            active_adapter_version_id=settings.runtime_adapter_version,
            active_adapter_artifact_hash=settings.runtime_adapter_hash,
        )
    if settings.provider_id == "self-hosted-openai-compatible":
        return _self_hosted_provider(settings)
    if settings.provider_id == "stage9a-candidate-local":
        from mlsys.serving.stage9a_candidate import build_stage9a_candidate_provider

        return build_stage9a_candidate_provider(settings)
    raise ValueError(f"unknown HAVRE provider_id {settings.provider_id!r}")


def build_runtime(settings: Settings, *, migrate: bool = True) -> Runtime:
    project_root = Path(__file__).resolve().parents[2]
    if migrate:
        apply_migrations(settings.database_url, project_root / "db" / "migrations")
    _validate_deployment_database_roles(settings)
    identity = IdentityLoader(settings.identity_root).load()
    repository = PostgresRepository(settings.database_url)
    repository.open()
    repository.bootstrap_owner_and_identity(
        owner_id=settings.owner_id,
        identity=identity,
    )
    try:
        provider = _build_provider(settings)
    except Exception:
        repository.close()
        raise
    runtime_attestation = getattr(provider, "runtime_attestation", None)
    if runtime_attestation is not None:
        repository.register_runtime_attestation(runtime_attestation)
    embedding_provider = DeterministicEmbeddingProvider()
    memory_service = MemoryService(
        repository=repository,
        embedding_provider=embedding_provider,
    )
    retrieval_service = RetrievalService(
        repository=repository,
        embedding_provider=embedding_provider,
    )
    memory_worker = MemoryWorker(
        repository=repository,
        extractor=DeterministicEpisodicExtractor(),
        owner_id=settings.owner_id,
    )
    user_model_service = UserModelService(repository=repository)
    consolidation_service = ConsolidationService(
        repository=repository,
        embedding_provider=embedding_provider,
    )
    current_state_service = CurrentStateService(repository=repository)
    goal_service = GoalService(repository=repository)
    scene_service = SceneService(
        store=ScenePostgresStore(
            repository=repository,
            owner_id=settings.owner_id,
            identity=identity,
        )
    )
    release_manifest = _load_release_manifest(settings, identity)
    operations_store = Stage10PostgresStore(
        repository=repository,
        owner_id=settings.owner_id,
        erasure_repository_factory=(
            None
            if settings.privileged_database_url is None
            else lambda: _open_repository(settings.privileged_database_url)
        ),
    )
    if (
        release_manifest is not None
        and settings.deployment_environment in {"staging", "production"}
    ):
        operations_store.require_release_preflight(release_manifest)
    erasure_ledger = (
        ErasureLedger(settings.erasure_ledger_path)
        if settings.enable_erasure_ledger
        else None
    )
    proactive_store = ProactivePostgresStore(
        repository=repository,
        owner_id=settings.owner_id,
        identity=identity,
    )
    offline_store = Stage7PostgresStore(
        repository=repository,
        owner_id=settings.owner_id,
    )
    def resolve_context_device_secret(device_binding_id: str) -> bytes:
        if (
            settings.context_device_binding_id != device_binding_id
            or settings.context_device_secret is None
        ):
            raise KeyError(device_binding_id)
        return settings.context_device_secret.encode("utf-8")

    context_store = Stage12ContextStore(
        repository=repository,
        owner_id=settings.owner_id,
        device_secret_resolver=resolve_context_device_secret,
    )
    service = InteractionService(
        owner_id=settings.owner_id,
        identity=identity,
        repository=repository,
        context_builder=ContextBuilder(
            max_input_tokens=settings.context_token_budget,
            reserved_output_tokens=settings.reserved_output_tokens,
        ),
        router=Stage1Router(),
        provider=provider,
        retrieval_service=retrieval_service,
        inference_timeout_ms=settings.inference_timeout_ms,
    )
    feedback_service = FeedbackService(
        repository=repository,
        owner_id=settings.owner_id,
    )
    return Runtime(
        settings=settings,
        repository=repository,
        service=service,
        memory_service=memory_service,
        memory_worker=memory_worker,
        retrieval_service=retrieval_service,
        user_model_service=user_model_service,
        consolidation_service=consolidation_service,
        current_state_service=current_state_service,
        goal_service=goal_service,
        scene_service=scene_service,
        proactive_store=proactive_store,
        offline_store=offline_store,
        operations_store=operations_store,
        context_store=context_store,
        feedback_service=feedback_service,
        erasure_ledger=erasure_ledger,
        release_manifest=release_manifest,
    )
