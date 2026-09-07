"""Environment-backed runtime configuration without secret persistence."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _secret_or_value(name: str, default: str | None = None) -> tuple[str | None, bool]:
    direct = os.getenv(name)
    file_name = os.getenv(f"{name}_FILE")
    if direct is not None and file_name is not None:
        raise ValueError(f"{name} and {name}_FILE cannot both be set")
    if file_name is not None:
        path = Path(file_name).resolve()
        if not path.is_file():
            raise ValueError(f"{name}_FILE does not name a readable file")
        value = path.read_text(encoding="utf-8").strip()
        if not value:
            raise ValueError(f"{name}_FILE is empty")
        return value, True
    return (direct if direct is not None else default), False


def _vapid_private_key() -> tuple[str | None, bool, bool]:
    dpapi_file = os.getenv("HAVRE_WEB_PUSH_VAPID_PRIVATE_KEY_DPAPI_FILE")
    direct = os.getenv("HAVRE_WEB_PUSH_VAPID_PRIVATE_KEY")
    plain_file = os.getenv("HAVRE_WEB_PUSH_VAPID_PRIVATE_KEY_FILE")
    if sum(value is not None for value in (dpapi_file, direct, plain_file)) > 1:
        raise ValueError("configure exactly one VAPID private-key source")
    if dpapi_file is not None:
        from apps.windows_agent.offline_queue import read_dpapi_secret

        value = read_dpapi_secret(Path(dpapi_file)).decode("ascii")
        return value, False, True
    value, from_file = _secret_or_value("HAVRE_WEB_PUSH_VAPID_PRIVATE_KEY")
    return value, from_file, False


def _is_exact_private_tailnet_origin(value: str | None) -> bool:
    if value is None:
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme == "https"
        and parsed.hostname is not None
        and re.fullmatch(r"[a-z0-9-]+[.][a-z0-9-]+[.]ts[.]net", parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and port is None
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
    )


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    database_url: str
    owner_id: UUID
    identity_root: Path
    provider_id: str
    runtime_adapter_version: str | None = None
    runtime_adapter_hash: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    component_promotion_authorizations_path: Path | None = None
    self_hosted_base_url: str
    self_hosted_model_manifest: Path
    self_hosted_engine_manifest: Path
    self_hosted_adapter_manifest: Path | None = None
    self_hosted_api_key: str | None = None
    deepseek_api_key: str | None = Field(default=None, repr=False)
    deepseek_api_key_from_secret_file: bool = False
    manual_strong_brain_enabled: bool = False
    codex_cli_path: Path | None = None
    codex_reasoning_effort: Literal["low", "medium", "high", "xhigh"] = "medium"
    owner_example_bank_path: Path | None = None
    memory_encoder_root: Path | None = None
    context_token_budget: int = Field(gt=0)
    reserved_output_tokens: int = Field(gt=0)
    local_reserved_output_tokens: int = Field(default=1024, gt=0)
    inference_timeout_ms: int = Field(gt=0)
    deployment_environment: Literal["development", "staging", "production"] = (
        "development"
    )
    public_base_url: str | None = None
    release_manifest_path: Path | None = None
    runtime_image_reference: str | None = None
    runtime_image_digest: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    postgres_image_reference: str | None = None
    caddy_image_reference: str | None = None
    operations_image_reference: str | None = None
    erasure_ledger_path: Path = Path("var/operations/erasure-ledger.sqlite3")
    database_url_from_secret_file: bool = False
    privileged_database_url: str | None = None
    privileged_database_url_from_secret_file: bool = False
    release_database_url: str | None = None
    release_database_url_from_secret_file: bool = False
    provider_api_key_from_secret_file: bool = False
    owner_api_token: str | None = None
    owner_api_token_from_secret_file: bool = False
    desktop_bootstrap_token: str | None = None
    desktop_bootstrap_token_from_secret_file: bool = False
    owner_timezone: str = "America/Chicago"
    device_session_days: int = Field(default=180, ge=1, le=365)
    web_push_enabled: bool = False
    web_push_vapid_public_key: str | None = None
    web_push_vapid_private_key: str | None = None
    web_push_vapid_private_key_from_file: bool = False
    web_push_vapid_private_key_from_dpapi: bool = False
    web_push_vapid_key_version: str | None = Field(
        default=None, pattern=r"^vapid-[a-z0-9][a-z0-9._-]{1,63}$"
    )
    web_push_vapid_subject: str | None = None
    tailscale_cli_path: Path | None = None
    context_device_binding_id: str | None = Field(
        default=None, pattern=r"^[a-z][a-z0-9_.:-]{2,127}$"
    )
    context_device_secret: str | None = None
    context_device_secret_from_file: bool = False
    owner_export_root: Path = Path("var/exports")
    owner_improvement_review_root: Path = Path("owner_improvement_reviews")
    relational_initiative_enabled: bool = False
    require_owner_api_token: bool = True
    enable_erasure_ledger: bool = True
    require_context_device: bool = False

    @model_validator(mode="after")
    def validate_deployment_boundary(self) -> "Settings":
        adapter_values = (
            self.runtime_adapter_version,
            self.runtime_adapter_hash,
        )
        if any(value is not None for value in adapter_values) and not all(
            value is not None for value in adapter_values
        ):
            raise ValueError("runtime adapter version and hash are atomic")
        context_values = (self.context_device_binding_id, self.context_device_secret)
        if any(value is not None for value in context_values) and not all(
            value is not None for value in context_values
        ):
            raise ValueError("context device binding and signing secret are atomic")
        if self.context_device_secret is not None and len(self.context_device_secret) < 32:
            raise ValueError("context device signing secret must contain at least 32 characters")
        if self.require_owner_api_token and (
            self.owner_api_token is None or len(self.owner_api_token) < 32
        ):
            raise ValueError("owner-authenticated API requires a strong owner token")
        loopback_public_url = (
            self.public_base_url is not None
            and re.match(
                r"^https?://(?:localhost|127\.0\.0\.1|\[::1\])(?::\d+)?(?:/|$)",
                self.public_base_url,
            )
            is not None
        )
        if not self.require_owner_api_token and (
            self.web_push_enabled
            or (self.public_base_url is not None and not loopback_public_url)
        ):
            raise ValueError(
                "public Daily Companion and Web Push require owner authentication"
            )
        if self.desktop_bootstrap_token is not None:
            if len(self.desktop_bootstrap_token) < 32 or self.owner_api_token is None:
                raise ValueError(
                    "desktop bootstrap requires strong bootstrap and owner API tokens"
                )
            if self.deployment_environment != "development":
                raise ValueError("desktop bootstrap is development-loopback only")
        if self.manual_strong_brain_enabled and (
            self.deepseek_api_key is None or not self.deepseek_api_key.strip()
        ):
            raise ValueError(
                "manual Strong Brain enablement requires a DeepSeek API key"
            )
        if self.provider_id == "openai-codex-chatgpt":
            if self.deployment_environment != "development":
                raise ValueError("ChatGPT/Codex replies are owner-local development only")
            if (
                self.codex_cli_path is None
                or not self.codex_cli_path.is_absolute()
                or not self.codex_cli_path.is_file()
            ):
                raise ValueError("ChatGPT/Codex replies require an exact Codex CLI path")
        if self.owner_example_bank_path is not None and (
            not self.owner_example_bank_path.is_absolute()
            or not self.owner_example_bank_path.is_file()
        ):
            raise ValueError("owner example bank must name an existing absolute file")
        if self.web_push_enabled:
            expected_tailscale = (
                Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
                / "Tailscale" / "tailscale.exe"
            ).resolve()
            if (
                not _is_exact_private_tailnet_origin(self.public_base_url)
                or not self.web_push_vapid_public_key
                or not self.web_push_vapid_private_key
                or not self.web_push_vapid_key_version
                or not self.web_push_vapid_subject
                or not self.web_push_vapid_private_key_from_dpapi
                or self.tailscale_cli_path is None
                or not self.tailscale_cli_path.is_absolute()
                or self.tailscale_cli_path.resolve() != expected_tailscale
            ):
                raise ValueError(
                    "Web Push requires exact private ts.net, DPAPI-only VAPID, and official Tailscale CLI settings"
                )
        if self.deployment_environment in {"staging", "production"}:
            if not self.public_base_url or not self.public_base_url.startswith("https://"):
                raise ValueError("staging/production requires an HTTPS public base URL")
            if not self.database_url_from_secret_file:
                raise ValueError("staging/production database URL must use a secret file")
            if (
                self.privileged_database_url is not None
                and not self.privileged_database_url_from_secret_file
            ):
                raise ValueError(
                    "staging/production privileged database URL must use a secret file"
                )
            if (
                self.release_database_url is not None
                and not self.release_database_url_from_secret_file
            ):
                raise ValueError(
                    "staging/production release database URL must use a secret file"
                )
            if self.release_manifest_path is None:
                raise ValueError("staging/production requires an immutable release manifest")
            if (
                not self.runtime_image_reference
                or not self.runtime_image_digest
                or not self.runtime_image_digest.startswith("sha256:")
                or len(self.runtime_image_digest) != 71
            ):
                raise ValueError(
                    "staging/production requires an exact runtime image reference and digest"
                )
            image_match = re.fullmatch(
                r"[^\s@]+@(?P<digest>sha256:[0-9a-f]{64})",
                self.runtime_image_reference,
            )
            if (
                image_match is None
                or image_match.group("digest") != self.runtime_image_digest
            ):
                raise ValueError(
                    "runtime image reference must contain the exact configured digest"
                )
            for name, reference in (
                ("PostgreSQL", self.postgres_image_reference),
                ("Caddy", self.caddy_image_reference),
                ("operations", self.operations_image_reference),
            ):
                if not reference or re.fullmatch(
                    r"[^\s@]+@sha256:[0-9a-f]{64}", reference
                ) is None:
                    raise ValueError(f"{name} image must use an exact digest reference")
            if self.require_owner_api_token and not self.owner_api_token_from_secret_file:
                raise ValueError("staging/production requires an owner token secret file")
            if (
                self.context_device_secret is not None
                and not self.context_device_secret_from_file
            ):
                raise ValueError(
                    "staging/production context device secret must use a secret file"
                )
            if self.web_push_enabled and not self.web_push_vapid_private_key_from_dpapi:
                raise ValueError(
                    "staging/production Web Push private key must use Windows DPAPI"
                )
            if self.require_context_device and not all(context_values):
                raise ValueError(
                    "staging/production context API requires one exact device binding secret"
                )
        return self

    @classmethod
    def from_env(
        cls,
        *,
        require_owner_api_token: bool = True,
        enable_erasure_ledger: bool = True,
        require_context_device: bool = False,
    ) -> "Settings":
        project_root = Path(__file__).resolve().parents[2]
        database_url, database_from_file = _secret_or_value(
            "HAVRE_DATABASE_URL",
            "postgresql://postgres@127.0.0.1:55432/havre",
        )
        api_key, api_key_from_file = _secret_or_value("HAVRE_SELF_HOSTED_API_KEY")
        deepseek_key, deepseek_key_from_file = _secret_or_value("DEEPSEEK_API_KEY")
        owner_token, owner_token_from_file = _secret_or_value("HAVRE_OWNER_API_TOKEN")
        desktop_bootstrap_token, desktop_bootstrap_from_file = _secret_or_value(
            "HAVRE_DESKTOP_BOOTSTRAP_TOKEN"
        )
        (
            vapid_private_key,
            vapid_private_key_from_file,
            vapid_private_key_from_dpapi,
        ) = _vapid_private_key()
        context_device_secret, context_device_secret_from_file = _secret_or_value(
            "HAVRE_CONTEXT_DEVICE_SECRET"
        )
        privileged_url, privileged_from_file = _secret_or_value(
            "HAVRE_PRIVILEGED_DATABASE_URL"
        )
        release_url, release_from_file = _secret_or_value(
            "HAVRE_RELEASE_DATABASE_URL"
        )
        release_path = os.getenv("HAVRE_RELEASE_MANIFEST_PATH")
        ledger_path = Path(
            os.getenv(
                "HAVRE_ERASURE_LEDGER_PATH",
                str(project_root / "var" / "operations" / "erasure-ledger.sqlite3"),
            )
        )
        return cls(
            memory_encoder_root=(Path(os.environ["HAVRE_MEMORY_ENCODER_ROOT"]).resolve()
                                 if os.getenv("HAVRE_MEMORY_ENCODER_ROOT") else None),
            database_url=str(database_url),
            owner_id=UUID(
                os.getenv(
                    "HAVRE_OWNER_ID", "00000000-0000-7000-8000-000000000001"
                )
            ),
            identity_root=Path(
                os.getenv("HAVRE_IDENTITY_ROOT", str(project_root / "identity"))
            ),
            provider_id=os.getenv("HAVRE_PROVIDER_ID", "deterministic-local"),
            runtime_adapter_version=(
                os.getenv("HAVRE_RUNTIME_ADAPTER_VERSION") or None
            ),
            runtime_adapter_hash=os.getenv("HAVRE_RUNTIME_ADAPTER_HASH") or None,
            component_promotion_authorizations_path=(
                None
                if not os.getenv("HAVRE_COMPONENT_PROMOTION_AUTHORIZATIONS_PATH")
                else Path(
                    os.environ["HAVRE_COMPONENT_PROMOTION_AUTHORIZATIONS_PATH"]
                ).resolve()
            ),
            self_hosted_base_url=os.getenv(
                "HAVRE_SELF_HOSTED_BASE_URL", "http://127.0.0.1:8080"
            ),
            self_hosted_model_manifest=Path(
                os.getenv(
                    "HAVRE_SELF_HOSTED_MODEL_MANIFEST",
                    str(
                        project_root
                        / "mlsys"
                        / "serving"
                        / "manifests"
                        / "qwen3-8b-q4-k-m.json"
                    ),
                )
            ),
            self_hosted_engine_manifest=Path(
                os.getenv(
                    "HAVRE_SELF_HOSTED_ENGINE_MANIFEST",
                    str(
                        project_root
                        / "mlsys"
                        / "serving"
                        / "manifests"
                        / "llama-cpp-b10405-win-cuda-12.4-x64.json"
                    ),
                )
            ),
            self_hosted_adapter_manifest=(
                None
                if not os.getenv("HAVRE_SELF_HOSTED_ADAPTER_MANIFEST")
                else Path(os.environ["HAVRE_SELF_HOSTED_ADAPTER_MANIFEST"]).resolve()
            ),
            self_hosted_api_key=api_key,
            deepseek_api_key=deepseek_key,
            deepseek_api_key_from_secret_file=deepseek_key_from_file,
            manual_strong_brain_enabled=os.getenv(
                "HAVRE_MANUAL_STRONG_BRAIN_ENABLED", "false"
            ).lower()
            in {"1", "true", "yes"},
            codex_cli_path=(
                None
                if not os.getenv("HAVRE_CODEX_CLI_PATH")
                else Path(os.environ["HAVRE_CODEX_CLI_PATH"]).resolve()
            ),
            codex_reasoning_effort=os.getenv(
                "HAVRE_CODEX_REASONING_EFFORT", "medium"
            ),
            owner_example_bank_path=(
                None
                if not os.getenv("HAVRE_OWNER_EXAMPLE_BANK_PATH")
                else Path(os.environ["HAVRE_OWNER_EXAMPLE_BANK_PATH"]).resolve()
            ),
            context_token_budget=int(os.getenv("HAVRE_CONTEXT_TOKEN_BUDGET", "4096")),
            reserved_output_tokens=int(
                os.getenv("HAVRE_RESERVED_OUTPUT_TOKENS", "256")
            ),
            local_reserved_output_tokens=int(
                os.getenv("HAVRE_LOCAL_RESERVED_OUTPUT_TOKENS", "1024")
            ),
            inference_timeout_ms=int(os.getenv("HAVRE_INFERENCE_TIMEOUT_MS", "20000")),
            deployment_environment=os.getenv(
                "HAVRE_DEPLOYMENT_ENVIRONMENT", "development"
            ),
            public_base_url=os.getenv("HAVRE_PUBLIC_BASE_URL"),
            release_manifest_path=(
                None if release_path is None else Path(release_path).resolve()
            ),
            runtime_image_reference=os.getenv("HAVRE_RUNTIME_IMAGE_REFERENCE"),
            runtime_image_digest=os.getenv("HAVRE_RUNTIME_IMAGE_DIGEST"),
            postgres_image_reference=os.getenv("HAVRE_POSTGRES_IMAGE"),
            caddy_image_reference=os.getenv("HAVRE_CADDY_IMAGE"),
            operations_image_reference=os.getenv("HAVRE_OPERATIONS_IMAGE"),
            erasure_ledger_path=ledger_path.resolve(),
            database_url_from_secret_file=database_from_file,
            privileged_database_url=privileged_url,
            privileged_database_url_from_secret_file=privileged_from_file,
            release_database_url=release_url,
            release_database_url_from_secret_file=release_from_file,
            provider_api_key_from_secret_file=api_key_from_file,
            owner_api_token=owner_token,
            owner_api_token_from_secret_file=owner_token_from_file,
            desktop_bootstrap_token=desktop_bootstrap_token,
            desktop_bootstrap_token_from_secret_file=desktop_bootstrap_from_file,
            owner_timezone=os.getenv("HAVRE_OWNER_TIMEZONE", "America/Chicago"),
            device_session_days=int(os.getenv("HAVRE_DEVICE_SESSION_DAYS", "180")),
            web_push_enabled=os.getenv("HAVRE_WEB_PUSH_ENABLED", "false").lower()
            in {"1", "true", "yes"},
            web_push_vapid_public_key=os.getenv("HAVRE_WEB_PUSH_VAPID_PUBLIC_KEY"),
            web_push_vapid_private_key=vapid_private_key,
            web_push_vapid_private_key_from_file=vapid_private_key_from_file,
            web_push_vapid_private_key_from_dpapi=vapid_private_key_from_dpapi,
            web_push_vapid_key_version=os.getenv("HAVRE_WEB_PUSH_VAPID_KEY_VERSION"),
            web_push_vapid_subject=os.getenv("HAVRE_WEB_PUSH_VAPID_SUBJECT"),
            tailscale_cli_path=(
                None if not os.getenv("HAVRE_TAILSCALE_CLI_PATH")
                else Path(os.environ["HAVRE_TAILSCALE_CLI_PATH"]).resolve()
            ),
            context_device_binding_id=os.getenv("HAVRE_CONTEXT_DEVICE_BINDING_ID"),
            context_device_secret=context_device_secret,
            context_device_secret_from_file=context_device_secret_from_file,
            owner_export_root=Path(
                os.getenv(
                    "HAVRE_OWNER_EXPORT_ROOT", str(project_root / "var" / "exports")
                )
            ).resolve(),
            owner_improvement_review_root=Path(
                os.getenv(
                    "HAVRE_OWNER_IMPROVEMENT_REVIEW_ROOT",
                    str(project_root / "owner_improvement_reviews"),
                )
            ).resolve(),
            relational_initiative_enabled=os.getenv(
                "HAVRE_RELATIONAL_INITIATIVE_ENABLED", "false"
            ).lower() in {"1", "true", "yes"},
            require_owner_api_token=require_owner_api_token,
            enable_erasure_ledger=enable_erasure_ledger,
            require_context_device=require_context_device,
        )
