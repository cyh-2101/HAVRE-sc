"""Exact release-component bindings shared by build and runtime preflight."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from companion.hashing import content_hash
from companion.operations import ComponentPromotionAuthorization, ComponentReference
from services.api.settings import Settings
from mlsys.contracts import ProviderVersion


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def component_promotion_authorizations(
    settings: Settings,
) -> tuple[ComponentPromotionAuthorization, ...]:
    path = settings.component_promotion_authorizations_path
    if path is None:
        return ()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("component promotion authorizations must be a JSON array")
    authorizations = tuple(
        ComponentPromotionAuthorization.model_validate(item) for item in payload
    )
    identities = {(item.component, item.version, item.artifact_hash) for item in authorizations}
    if len(identities) != len(authorizations):
        raise ValueError("component promotion authorizations contain duplicates")
    return authorizations


def _lifecycle(
    *,
    authorizations: tuple[ComponentPromotionAuthorization, ...],
    component: str,
    version: str,
    artifact_hash: str,
    promotable: bool = True,
) -> str:
    if promotable and any(
        item.component == component
        and item.version == version
        and item.artifact_hash == artifact_hash
        for item in authorizations
    ):
        return "approved"
    return "candidate_fixture"


def required_component_promotion_authorizations(
    *,
    components: tuple[ComponentReference, ...] | list[ComponentReference],
    settings: Settings,
) -> tuple[ComponentPromotionAuthorization, ...]:
    governed = {"provider", "foundation_model", "adapter", "tokenizer"}
    authorizations = component_promotion_authorizations(settings)
    required = []
    for component in components:
        if component.component not in governed or component.lifecycle_status != "approved":
            continue
        match = next(
            (
                item
                for item in authorizations
                if item.component == component.component
                and item.version == component.version
                and item.artifact_hash == component.artifact_hash
            ),
            None,
        )
        if match is None:
            raise ValueError(
                f"approved {component.component} lacks an exact Product Owner authorization"
            )
        required.append(match)
    return tuple(required)


def expected_release_components(
    *,
    settings: Settings,
    source_snapshot_hash: str,
    migration_path: Path,
    environment: str | None = None,
    runtime_image_reference: str | None = None,
    runtime_image_digest: str | None = None,
) -> tuple[ComponentReference, ...]:
    from companion import __version__

    authorizations = component_promotion_authorizations(settings)
    provider_hash = content_hash(
        {
            "provider_id": settings.provider_id,
            "base_url": settings.self_hosted_base_url,
        }
    )

    components = [
        ComponentReference(
            component="companion_core",
            version=__version__,
            artifact_hash=source_snapshot_hash,
            lifecycle_status="approved",
        ),
        ComponentReference(
            component="database_schema",
            version=migration_path.name,
            artifact_hash=file_sha256(migration_path),
            lifecycle_status="approved",
        ),
        ComponentReference(
            component="provider",
            version=settings.provider_id,
            artifact_hash=provider_hash,
            lifecycle_status=_lifecycle(
                authorizations=authorizations,
                component="provider",
                version=settings.provider_id,
                artifact_hash=provider_hash,
                promotable=settings.provider_id != "deterministic-local",
            ),
        ),
    ]
    if settings.provider_id == "self-hosted-openai-compatible":
        model = json.loads(
            settings.self_hosted_model_manifest.read_text(encoding="utf-8")
        )
        engine = json.loads(
            settings.self_hosted_engine_manifest.read_text(encoding="utf-8")
        )
        model_hash = model.get("artifact", {}).get("sha256")
        model_revision = model.get("upstream", {}).get("revision")
        engine_id = engine.get("manifest_id")
        if not all(
            isinstance(value, str) and value
            for value in (model_hash, model_revision, engine_id)
        ):
            raise ValueError("self-hosted release manifests are incomplete")
        components.extend(
            (
                ComponentReference(
                    component="foundation_model",
                    version=str(model["manifest_id"]),
                    artifact_hash=str(model_hash),
                    lifecycle_status=_lifecycle(
                        authorizations=authorizations,
                        component="foundation_model",
                        version=str(model["manifest_id"]),
                        artifact_hash=str(model_hash),
                    ),
                ),
                ComponentReference(
                    component="tokenizer",
                    version=(
                        f"{model['upstream']['repository']}@{model_revision}:"
                        "embedded-gguf-tokenizer"
                    ),
                    artifact_hash=str(model_hash),
                    lifecycle_status=_lifecycle(
                        authorizations=authorizations,
                        component="tokenizer",
                        version=(
                            f"{model['upstream']['repository']}@{model_revision}:"
                            "embedded-gguf-tokenizer"
                        ),
                        artifact_hash=str(model_hash),
                    ),
                ),
                ComponentReference(
                    component="serving_engine",
                    version=str(engine_id),
                    artifact_hash=file_sha256(settings.self_hosted_engine_manifest),
                    lifecycle_status="approved",
                ),
            )
        )
    elif settings.provider_id != "deterministic-local":
        raise ValueError("release binding does not recognize the configured provider")
    if settings.runtime_adapter_version is not None:
        adapter_hash = str(settings.runtime_adapter_hash)
        components.append(
            ComponentReference(
                component="adapter",
                version=settings.runtime_adapter_version,
                artifact_hash=adapter_hash,
                lifecycle_status=_lifecycle(
                    authorizations=authorizations,
                    component="adapter",
                    version=settings.runtime_adapter_version,
                    artifact_hash=adapter_hash,
                    promotable=settings.provider_id == "self-hosted-openai-compatible",
                ),
            )
        )
    target_environment = environment or settings.deployment_environment
    if target_environment in {"staging", "production"}:
        image_reference = runtime_image_reference or settings.runtime_image_reference
        image_digest = runtime_image_digest or settings.runtime_image_digest
        if not image_reference or not image_digest:
            raise ValueError("runtime image identity is required")
        components.append(
            ComponentReference(
                component="deployment_image",
                version=image_reference,
                artifact_hash=image_digest,
                lifecycle_status="approved",
            )
        )
        for component_name, reference in (
            ("database_image", settings.postgres_image_reference),
            ("proxy_image", settings.caddy_image_reference),
            ("operations_image", settings.operations_image_reference),
        ):
            if not reference:
                raise ValueError("all deployment image identities are required")
            digest = reference.rsplit("@", 1)[-1]
            components.append(
                ComponentReference(
                    component=component_name,
                    version=reference,
                    artifact_hash=digest,
                    lifecycle_status="approved",
                )
            )
    return tuple(components)


def require_provider_version_binding(
    *,
    components: tuple[ComponentReference, ...],
    provider_version: ProviderVersion,
) -> None:
    indexed = {item.component: item for item in components}
    provider = indexed.get("provider")
    if provider is None or provider.version != provider_version.provider_id:
        raise ValueError("active provider does not match the release manifest")
    model = indexed.get("foundation_model")
    if model is not None and (
        model.version != provider_version.model_version_id
        or model.artifact_hash != provider_version.model_artifact_hash
    ):
        raise ValueError("active foundation model does not match the release manifest")
    tokenizer = indexed.get("tokenizer")
    if tokenizer is not None and tokenizer.version != provider_version.tokenizer_version_id:
        raise ValueError("active tokenizer does not match the release manifest")
    adapter = indexed.get("adapter")
    if adapter is None:
        if (
            provider_version.active_adapter_version_id is not None
            or provider_version.active_adapter_artifact_hash is not None
        ):
            raise ValueError("provider reports an adapter absent from the release manifest")
    elif (
        adapter.version != provider_version.active_adapter_version_id
        or adapter.artifact_hash != provider_version.active_adapter_artifact_hash
    ):
        raise ValueError("active adapter does not match the release manifest")
