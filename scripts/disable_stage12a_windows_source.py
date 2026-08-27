"""Owner-run append-only source/device revocation; no device key is required."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from companion.life_context import ContextSourceStateRevision
from companion.persistence import (
    PostgresRepository, Stage12ContextStore, require_isolated_context_operator,
)
from companion.policy import DataPolicy


def _secret(path: Path) -> str:
    value = path.resolve().read_text(encoding="utf-8").strip()
    if not value:
        raise ValueError(f"secret file is empty: {path}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context-database-url-file", type=Path, required=True)
    parser.add_argument("--owner-id", type=UUID, required=True)
    parser.add_argument("--source-instance-id", type=UUID, required=True)
    parser.add_argument(
        "--reason", choices=("owner_disabled", "lost_device", "key_rotated"),
        required=True,
    )
    parser.add_argument("--authorization-ref", required=True)
    args = parser.parse_args()

    database_url = _secret(args.context_database_url_file)
    require_isolated_context_operator(database_url)
    repository = PostgresRepository(database_url)
    repository.open()
    try:
        with repository.pool.connection() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(max(state.revision),0) AS revision,
                       consent.data_policy
                FROM havre.context_source_state_revisions state
                JOIN LATERAL (
                    SELECT data_policy FROM havre.context_consent_scope_revisions
                    WHERE owner_id=state.owner_id
                      AND source_instance_id=state.source_instance_id
                    ORDER BY revision DESC LIMIT 1
                ) consent ON true
                WHERE state.owner_id=%s AND state.source_instance_id=%s
                GROUP BY consent.data_policy
                """,
                (args.owner_id, args.source_instance_id),
            ).fetchone()
        if row is None or row["revision"] < 1:
            raise ValueError("registered source with consent is required")
        policy = DataPolicy.model_validate(
            row["data_policy"] | {"authorization_ref": args.authorization_ref}
        )
        store = Stage12ContextStore(
            repository=repository,
            owner_id=args.owner_id,
            device_secret_resolver=lambda _binding: (_ for _ in ()).throw(KeyError()),
        )
        event_id = store.save_source_state(
            ContextSourceStateRevision(
                owner_id=args.owner_id,
                source_instance_id=args.source_instance_id,
                revision=row["revision"] + 1,
                status="disabled",
                reason=args.reason,
                effective_at=datetime.now(UTC),
                authorization_ref=args.authorization_ref,
            ),
            data_policy=policy,
        )
    finally:
        repository.close()
    print({
        "source_instance_id": str(args.source_instance_id),
        "decision_event_id": str(event_id),
        "status": "disabled",
        "secret_required": False,
    })


if __name__ == "__main__":
    main()
