"""Composition root for the active HAVRE Stage 10 modular monolith."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

import psycopg

from companion.application import InteractionService
from companion.commitments.service import CommitmentBroker
from companion.context import ContextBuilder, load_owner_example_bank
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
from companion.proactive.evaluator import ProactiveTriggerEvaluator
from companion.persistence.offline import Stage7PostgresStore
from companion.product import (
    DailyCompanionStore,
    DiaryIntelligenceService,
    ManualStrongBrainService,
    WebPushDeliveryProvider,
)
from companion.product.strong import MANUAL_STRONG_RESERVED_OUTPUT_TOKENS
from companion.product.tailscale import TailscaleServeAttestor
from mlsys.serving import (
    RuntimeAttestation,
    DeepSeekCloudProvider,
    CodexCliProvider,
    DeterministicLocalProvider,
    ModelProvider,
    OpenAICompatibleProvider,
    PrivacyClassRouter,
    Stage1Router,
    attest_active_runtime,
    write_runtime_attestation,
)
from mlsys.retrieval.service import RetrievalService
from mlsys.serving.openai_compatible import llama_context_tokens_per_slot
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
    commitment_broker: CommitmentBroker
    scene_service: SceneService
    proactive_store: ProactivePostgresStore
    proactive_evaluator: ProactiveTriggerEvaluator
    offline_store: Stage7PostgresStore
    operations_store: Stage10PostgresStore
    context_store: Stage12ContextStore
    feedback_service: FeedbackService
    daily_companion_store: DailyCompanionStore
    diary_intelligence_service: DiaryIntelligenceService | None
    conversation_continuation_service: object | None
    web_push_provider: WebPushDeliveryProvider
    strong_brain_service: ManualStrongBrainService | None
    erasure_ledger: ErasureLedger | None
    release_manifest: ReleaseManifest | None
    realtime_memory_service: object | None = None

    def close(self) -> None:
        asyncio.run(self.aclose())

    async def aclose(self) -> None:
        try:
            configured = getattr(
                self.service,
                "providers",
                {self.service.provider.provider_id: self.service.provider},
            )
            closed: set[int] = set()
            for provider in configured.values():
                if id(provider) in closed:
                    continue
                closed.add(id(provider))
                await provider.aclose()
            if self.strong_brain_service is not None:
                strong_provider = (
                    self.strong_brain_service.interaction_service.provider
                )
                if id(strong_provider) not in closed:
                    await strong_provider.aclose()
            if self.diary_intelligence_service is not None:
                diary_provider = self.diary_intelligence_service.provider
                if id(diary_provider) not in closed:
                    await diary_provider.aclose()
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


LOCAL_PRIVACY_PROVIDER_ID = "self-hosted-openai-compatible"
LOCAL_PRIVACY_MODEL_VERSION_ID = "model-qwen3-8b-gguf-q4-k-m-7c41481f"
LOCAL_PRIVACY_MODEL_ARTIFACT_HASH = (
    "sha256:d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785"
)


def _self_hosted_provider(
    settings: Settings,
    *,
    provider_id: str | None = None,
    require_unadapted_qwen3_8b: bool = False,
) -> OpenAICompatibleProvider:
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
    if require_unadapted_qwen3_8b:
        if (
            model.get("manifest_id") != LOCAL_PRIVACY_MODEL_VERSION_ID
            or model_hash != LOCAL_PRIVACY_MODEL_ARTIFACT_HASH
        ):
            raise ValueError(
                "local privacy route requires the exact approved Qwen3-8B base artifact"
            )
        if (
            settings.runtime_adapter_version is not None
            or settings.runtime_adapter_hash is not None
            or settings.self_hosted_adapter_manifest is not None
        ):
            raise ValueError(
                "local privacy route forbids every HAVRE adapter binding"
            )
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
        provider_id=provider_id or settings.provider_id,
        model_artifact_hash=model_hash,
        adapter_version_id=settings.runtime_adapter_version,
        adapter_artifact_hash=settings.runtime_adapter_hash,
        api_key=settings.self_hosted_api_key,
        max_context_tokens=llama_context_tokens_per_slot(profile),
        max_output_tokens=min(4096, llama_context_tokens_per_slot(profile)),
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
        return _self_hosted_provider(
            settings,
            provider_id=LOCAL_PRIVACY_PROVIDER_ID,
        )
    if settings.provider_id == "stage9a-candidate-local":
        from mlsys.serving.stage9a_candidate import build_stage9a_candidate_provider

        return build_stage9a_candidate_provider(settings)
    if settings.provider_id == "openai-codex-chatgpt":
        from mlsys.serving.codex_cli import (
            CODEX_OWNER_AUTOMATIC_AUTHORIZATION_REF,
        )

        assert settings.codex_cli_path is not None
        return CodexCliProvider(
            executable=settings.codex_cli_path,
            enabled=True,
            explicit_authorization_ref=CODEX_OWNER_AUTOMATIC_AUTHORIZATION_REF,
            reasoning_effort=settings.codex_reasoning_effort,
        )
    raise ValueError(f"unknown HAVRE provider_id {settings.provider_id!r}")


def _manual_strong_brain_enabled(settings: Settings) -> bool:
    """Require an explicit runtime gate in addition to a configured secret."""

    return bool(
        settings.manual_strong_brain_enabled
        and settings.deepseek_api_key is not None
        and settings.deepseek_api_key.strip()
    )


def _build_reply_composition(
    settings: Settings,
    *,
    provider: ModelProvider,
    providers: dict[str, ModelProvider],
) -> tuple[
    ContextBuilder,
    dict[str, ContextBuilder],
    Stage1Router | PrivacyClassRouter,
    dict[str, Any],
]:
    """Build the exact provider-specific Context and request-binding boundary."""

    owner_example_bank = (
        None
        if settings.owner_example_bank_path is None
        else load_owner_example_bank(
            settings.owner_example_bank_path,
            owner_id=settings.owner_id,
        )
    )
    context_builder = ContextBuilder(
        max_input_tokens=settings.context_token_budget,
        reserved_output_tokens=settings.reserved_output_tokens,
        owner_timezone=settings.owner_timezone,
        owner_example_bank=owner_example_bank,
    )
    context_builders = {provider.provider_id: context_builder}
    request_binders: dict[str, Any] = {}
    if settings.provider_id != "openai-codex-chatgpt":
        return context_builder, context_builders, Stage1Router(), request_binders

    from mlsys.serving.codex_cli import (
        CODEX_CLI_PROVIDER_ID,
        bind_codex_cli_request,
    )

    local_provider = providers[LOCAL_PRIVACY_PROVIDER_ID]
    local_output_tokens = min(
        settings.local_reserved_output_tokens,
        local_provider.max_output_tokens,
    )
    context_builders[LOCAL_PRIVACY_PROVIDER_ID] = ContextBuilder(
        max_input_tokens=local_provider.max_context_tokens,
        reserved_output_tokens=local_output_tokens,
        owner_timezone=settings.owner_timezone,
        owner_example_bank=None,
    )
    request_binders[CODEX_CLI_PROVIDER_ID] = partial(
        bind_codex_cli_request,
        reasoning_effort=settings.codex_reasoning_effort,
    )
    router = PrivacyClassRouter(
        cloud_provider_id=CODEX_CLI_PROVIDER_ID,
        local_provider_id=LOCAL_PRIVACY_PROVIDER_ID,
        approved_cloud_provider_ids=frozenset({CODEX_CLI_PROVIDER_ID}),
    )
    return context_builder, context_builders, router, request_binders


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
        providers: dict[str, ModelProvider] = {provider.provider_id: provider}
        if settings.provider_id == "openai-codex-chatgpt":
            local_provider = _self_hosted_provider(
                settings,
                provider_id=LOCAL_PRIVACY_PROVIDER_ID,
                require_unadapted_qwen3_8b=True,
            )
            providers[local_provider.provider_id] = local_provider
    except Exception:
        repository.close()
        raise
    for configured_provider in providers.values():
        runtime_attestation = getattr(
            configured_provider, "runtime_attestation", None
        )
        if runtime_attestation is not None:
            repository.register_runtime_attestation(runtime_attestation)
    if settings.memory_encoder_root is not None:
        from companion.memory.semantic import LocalSemanticEmbeddingProvider
        embedding_provider = LocalSemanticEmbeddingProvider(settings.memory_encoder_root)
        repository.memory_encoder = embedding_provider
    else:
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
    commitment_broker = CommitmentBroker(
        repository=repository,
        owner_id=settings.owner_id,
    )
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
        improvement_review_root=settings.owner_improvement_review_root,
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
        commitment_broker=commitment_broker,
        relational_initiative_enabled=settings.relational_initiative_enabled,
    )
    proactive_evaluator = ProactiveTriggerEvaluator(
        store=proactive_store,
        owner_timezone=settings.owner_timezone,
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
        owner_timezone=settings.owner_timezone,
    )
    daily_companion_store = DailyCompanionStore(
        repository=repository,
        owner_id=settings.owner_id,
    )
    diary_intelligence_service = None
    chat_goal_planner = None
    conversation_continuation_service = None
    if settings.provider_id == "openai-codex-chatgpt":
        from mlsys.serving.codex_cli import (
            CODEX_OWNER_AUTOMATIC_AUTHORIZATION_REF,
        )

        assert settings.codex_cli_path is not None
        diary_intelligence_service = DiaryIntelligenceService(
            repository=repository,
            owner_id=settings.owner_id,
            identity=identity,
            provider=CodexCliProvider(
                executable=settings.codex_cli_path,
                enabled=True,
                explicit_authorization_ref=CODEX_OWNER_AUTOMATIC_AUTHORIZATION_REF,
                reasoning_effort="high",
            ),
            embedding_provider=embedding_provider,
            timeout_ms=max(settings.inference_timeout_ms, 120_000),
            review_root=settings.owner_improvement_review_root,
            proactive_store=proactive_store,
        )
        from companion.product.chat_goals import ExplicitChatGoalPlanner

        chat_goal_planner = ExplicitChatGoalPlanner(
            repository=repository,
            owner_id=settings.owner_id,
            provider=diary_intelligence_service.provider,
            goal_service=goal_service,
            proactive_store=proactive_store,
            owner_timezone=settings.owner_timezone,
            timeout_ms=max(settings.inference_timeout_ms, 120_000),
        )
        if settings.relational_initiative_enabled:
            from companion.product.relationship import (
                ConversationContinuationService,
            )

            legacy_local_continuation_provider = providers.get(
                LOCAL_PRIVACY_PROVIDER_ID
            )
            if legacy_local_continuation_provider is None:
                raise RuntimeError(
                    "relational initiative requires the legacy attested local provider"
                )
            conversation_continuation_service = ConversationContinuationService(
                repository=repository,
                owner_id=settings.owner_id,
                provider=diary_intelligence_service.provider,
                legacy_local_provider=legacy_local_continuation_provider,
                proactive_store=proactive_store,
                commitment_broker=commitment_broker,
                timeout_ms=max(settings.inference_timeout_ms, 120_000),
            )
    web_push_provider = WebPushDeliveryProvider(
        repository=repository,
        owner_id=settings.owner_id,
        public_base_url=settings.public_base_url,
        vapid_private_key=settings.web_push_vapid_private_key,
        vapid_public_key=settings.web_push_vapid_public_key,
        vapid_key_version=settings.web_push_vapid_key_version,
        vapid_subject=settings.web_push_vapid_subject,
        enabled=settings.web_push_enabled,
        tailnet_attestor=(
            None
            if settings.tailscale_cli_path is None or settings.public_base_url is None
            else TailscaleServeAttestor(
                executable=settings.tailscale_cli_path,
                origin=settings.public_base_url,
                cache_seconds=0,
            )
        ),
    )
    (
        context_builder,
        context_builders,
        router,
        request_binders,
    ) = _build_reply_composition(
        settings,
        provider=provider,
        providers=providers,
    )
    service = InteractionService(
        owner_id=settings.owner_id,
        identity=identity,
        repository=repository,
        context_builder=context_builder,
        context_builders=context_builders,
        router=router,
        provider=provider,
        providers=providers,
        retrieval_service=retrieval_service,
        ambient_context_selector=context_store.select_calendar_context,
        request_binders=request_binders,
        inference_timeout_ms=settings.inference_timeout_ms,
        commitment_broker=commitment_broker,
        chat_goal_planner=chat_goal_planner,
        conversation_continuation_service=conversation_continuation_service,
    )
    strong_brain_service = None
    if _manual_strong_brain_enabled(settings):
        from mlsys.serving.deepseek_cloud import (
            DEEPSEEK_PROVIDER_ID,
            OWNER_MANUAL_AUTHORIZATION_REF,
        )

        strong_provider = DeepSeekCloudProvider(
            enabled=True,
            explicit_authorization_ref=OWNER_MANUAL_AUTHORIZATION_REF,
            mode="owner_manual",
            thinking="enabled",
            reasoning_effort="high",
            manual_permit_validator=lambda request: (
                repository.manual_cloud_request_permitted(
                    owner_id=settings.owner_id, request=request
                )
            ),
        )
        # DeepSeek thinking and final-answer tokens share one output budget. Keep
        # the Local input allowance while using the already-evidenced 4096-token
        # thinking/high budget instead of Local's 256-token reply reserve.
        strong_input_allowance = (
            settings.context_token_budget - settings.reserved_output_tokens
        )
        strong_interaction = InteractionService(
            owner_id=settings.owner_id,
            identity=identity,
            repository=repository,
            context_builder=ContextBuilder(
                max_input_tokens=(
                    strong_input_allowance + MANUAL_STRONG_RESERVED_OUTPUT_TOKENS
                ),
                reserved_output_tokens=MANUAL_STRONG_RESERVED_OUTPUT_TOKENS,
            ),
            router=Stage1Router(
                approved_cloud_provider_ids=frozenset({DEEPSEEK_PROVIDER_ID})
            ),
            provider=strong_provider,
            retrieval_service=retrieval_service,
            response_policy=service.response_policy,
            inference_timeout_ms=max(settings.inference_timeout_ms, 120_000),
            manual_strong_only=True,
        )
        strong_brain_service = ManualStrongBrainService(
            owner_id=settings.owner_id,
            repository=repository,
            interaction_service=strong_interaction,
        )
    feedback_service = FeedbackService(
        repository=repository,
        owner_id=settings.owner_id,
    )
    from companion.memory.intelligence import RealtimeMemoryService
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
        commitment_broker=commitment_broker,
        scene_service=scene_service,
        proactive_store=proactive_store,
        proactive_evaluator=proactive_evaluator,
        offline_store=offline_store,
        operations_store=operations_store,
        context_store=context_store,
        feedback_service=feedback_service,
        daily_companion_store=daily_companion_store,
        diary_intelligence_service=diary_intelligence_service,
        realtime_memory_service=(None if diary_intelligence_service is None else RealtimeMemoryService(
            understanding=diary_intelligence_service,timezone_name=settings.owner_timezone)),
        conversation_continuation_service=conversation_continuation_service,
        web_push_provider=web_push_provider,
        strong_brain_service=strong_brain_service,
        erasure_ledger=erasure_ledger,
        release_manifest=release_manifest,
    )
