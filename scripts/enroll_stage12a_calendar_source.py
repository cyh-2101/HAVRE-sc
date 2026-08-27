"""Owner-run enrollment for one explicitly approved Calendar capability."""

from __future__ import annotations

import argparse
from pathlib import Path

from apps.windows_agent.offline_queue import read_dpapi_secret, write_dpapi_secret
from companion.life_context import CalendarContextActivationBundle
from companion.persistence import (
    PostgresRepository,
    Stage12ContextStore,
    require_isolated_context_operator,
)


def _secret(path: Path) -> str:
    value = path.resolve().read_text(encoding="utf-8").strip()
    if not value:
        raise ValueError(f"secret file is empty: {path}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context-database-url-file", type=Path, required=True)
    parser.add_argument("--device-secret-file", type=Path, required=True)
    parser.add_argument("--agent-protected-secret-file", type=Path, required=True)
    parser.add_argument("--activation-bundle", type=Path, required=True)
    args = parser.parse_args()

    database_url = _secret(args.context_database_url_file)
    require_isolated_context_operator(database_url)
    device_secret = _secret(args.device_secret_file).encode("utf-8")
    if len(device_secret) < 32:
        raise ValueError("device signing secret must contain at least 32 bytes")
    if args.agent_protected_secret_file.resolve() == args.device_secret_file.resolve():
        raise ValueError("agent DPAPI output must not overwrite the Core secret file")
    bundle = CalendarContextActivationBundle.model_validate_json(
        args.activation_bundle.resolve().read_text(encoding="utf-8")
    )
    protected_path = args.agent_protected_secret_file.resolve()
    protected_created = False
    if protected_path.exists():
        if read_dpapi_secret(protected_path) != device_secret:
            raise ValueError("existing agent DPAPI secret does not match activation secret")
    else:
        write_dpapi_secret(protected_path, device_secret)
        protected_created = True

    repository = PostgresRepository(database_url)
    repository.open()
    try:
        Stage12ContextStore(
            repository=repository,
            owner_id=bundle.source.owner_id,
            device_secret_resolver=lambda binding: (
                device_secret
                if binding == bundle.source.device_binding_id
                else (_ for _ in ()).throw(KeyError(binding))
            ),
        ).activate_calendar_bundle(bundle)
    except BaseException:
        if protected_created and protected_path.exists():
            protected_path.unlink()
        raise
    finally:
        repository.close()
    print({
        "activation_id": str(bundle.activation_id),
        "source_instance_id": str(bundle.source.source_instance_id),
        "bundle_hash": bundle.content_hash,
        "source_access_mode": bundle.source_access_mode,
        "secret_disclosed": False,
        "collection_started": False,
        "agent_secret_protection": "Windows DPAPI current-user scope",
    })


if __name__ == "__main__":
    main()
