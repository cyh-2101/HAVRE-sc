"""Run HAVRE's public-safe synthetic evidence flow on a local demo database.

This uses the existing deterministic acceptance provider. It demonstrates the
durable system path and evidence lineage, not model or conversational quality.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from psycopg.conninfo import conninfo_to_dict

from companion.application import InteractionCommand
from companion.feedback import FeedbackRating, FeedbackReasonCode
from companion.ids import uuid7
from companion.policy import PrivacyClass
from services.api.runtime import build_runtime
from services.api.settings import Settings


DEMO_DATABASE_PREFIX = "havre_showcase_"
DEMO_SOURCE_MESSAGE = (
    "For piano practice I use a slow metronome and repeat the difficult measure."
)
DEMO_QUERY_MESSAGE = "What was my piano practice method from last time with the metronome?"
DEMO_OWNER_EDIT = (
    "You said a slow metronome and repeating the difficult measure helped your "
    "piano practice."
)


def validate_showcase_database_url(database_url: str) -> dict[str, str]:
    """Refuse remote or non-showcase databases before any migration or write."""

    values = conninfo_to_dict(database_url)
    host = values.get("host", "")
    port = values.get("port", "5432")
    database = values.get("dbname", "")
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("showcase demo database must be loopback-only")
    if port != "55432":
        raise ValueError("showcase demo requires the verified local port 55432")
    if re.fullmatch(r"havre_showcase_[a-z0-9_]+", database) is None:
        raise ValueError(
            f"showcase database name must match {DEMO_DATABASE_PREFIX!r}[a-z0-9_]+"
        )
    return values


def _settings(database_url: str, owner_id: UUID) -> Settings:
    base = Settings.from_env(
        require_owner_api_token=False,
        enable_erasure_ledger=False,
        require_context_device=False,
    )
    values = base.model_dump()
    values.update(
        database_url=database_url,
        owner_id=owner_id,
        provider_id="deterministic-local",
        runtime_adapter_version=None,
        runtime_adapter_hash=None,
        deployment_environment="development",
        release_manifest_path=None,
        require_owner_api_token=False,
        enable_erasure_ledger=False,
    )
    return Settings.model_validate(values)


def _event_summary(event: dict) -> dict:
    payload = event.get("payload") or {}
    text = "".join(
        str(part.get("text", ""))
        for part in payload.get("content_parts", [])
        if part.get("type") == "text"
    )
    return {
        "event_id": event.get("event_id"),
        "event_type": event.get("event_type"),
        "request_id": event.get("request_id"),
        "trace_id": event.get("trace_id"),
        "content": text,
        "content_hash": event.get("content_hash"),
        "privacy_class": event.get("privacy_class"),
        "training_eligible": event.get("training_eligible"),
    }


def _context_section_summary(section: dict) -> dict:
    return {
        "section_id": section.get("section_id"),
        "section_type": section.get("section_type"),
        "source_refs": section.get("source_refs"),
        "selection_reason": section.get("selection_reason"),
        "estimated_tokens": section.get("estimated_tokens"),
    }


async def run_showcase(
    *,
    database_url: str,
    validate_database_url: bool = True,
) -> dict[str, object]:
    if validate_database_url:
        validate_showcase_database_url(database_url)
    owner_id = uuid7()
    session_id = uuid7()
    runtime = build_runtime(_settings(database_url, owner_id))
    try:
        source = await runtime.service.interact(
            InteractionCommand(
                message=DEMO_SOURCE_MESSAGE,
                privacy_class=PrivacyClass.NORMAL,
                memory_eligible=True,
                session_id=session_id,
                channel="api",
                idempotency_key=f"showcase-source-{owner_id}",
            )
        )
        worker_result = runtime.memory_worker.run_once()
        if worker_result is None:
            raise RuntimeError("synthetic source did not produce a Memory candidate")
        candidate = next(
            item
            for item in runtime.memory_service.list_candidates(
                owner_id=owner_id,
                status="pending",
            )
            if item["source_event_id"] == source.user_event_id
        )
        memory = runtime.memory_service.accept_candidate(
            owner_id=owner_id,
            candidate_id=candidate["candidate_id"],
            reason="Public-safe synthetic showcase demo",
            importance=0.7,
        )

        query = await runtime.service.interact(
            InteractionCommand(
                message=DEMO_QUERY_MESSAGE,
                privacy_class=PrivacyClass.NORMAL,
                memory_eligible=False,
                session_id=session_id,
                channel="api",
                idempotency_key=f"showcase-query-{owner_id}",
            )
        )
        evidence = runtime.repository.evidence(query.request_id, owner_id=owner_id)
        if evidence is None:
            raise RuntimeError("query evidence was not persisted")
        selected_memory_ids = {
            str(item["memory_id"])
            for item in evidence["retrieval_result"]["candidates"]
        }
        if str(memory.memory_id) not in selected_memory_ids:
            raise RuntimeError("accepted synthetic Memory was not retrieved")
        memory_sections = [
            section
            for section in evidence["context_pack"]["sections"]
            if section["section_type"] == "episodic_memory"
        ]
        if not any(
            str(memory.memory_id) in section["section_id"]
            for section in memory_sections
        ):
            raise RuntimeError("retrieved synthetic Memory did not enter ContextPack")

        feedback = runtime.feedback_service.save(
            assistant_event_id=query.assistant_event_id,
            rating=FeedbackRating.MIXED,
            reason_codes=(FeedbackReasonCode.TOO_AI,),
            reason_text="The deterministic acceptance response does not use the memory naturally.",
            owner_revision_text=DEMO_OWNER_EDIT,
            expected_revision=0,
        )
        history = runtime.feedback_service.conversation(session_id=session_id)
        closed_episode = runtime.feedback_service.close_episode(
            session_id=session_id,
            boundary_reason="owner_closed",
        )
        episode = next(
            item
            for item in runtime.feedback_service.list_episodes()
            if item["episode_id"] == closed_episode["episode_id"]
        )
        provenance_violations = runtime.repository.audit_provenance_integrity()
        if provenance_violations:
            raise RuntimeError(
                f"provenance audit returned {len(provenance_violations)} violation(s)"
            )

        source_evidence = runtime.repository.evidence(
            source.request_id,
            owner_id=owner_id,
        )
        if source_evidence is None:
            raise RuntimeError("source evidence was not persisted")

        return jsonable_encoder(
            {
                "schema_version": 1,
                "demo_id": str(owner_id),
                "scope": "public_safe_synthetic_showcase",
                "claim_boundary": (
                    "The deterministic local provider proves pipeline execution, "
                    "durability, retrieval admission, feedback lineage, and provenance. "
                    "It does not prove conversational quality or production readiness."
                ),
                "flow": {
                    "synthetic_user_interactions": [
                        DEMO_SOURCE_MESSAGE,
                        DEMO_QUERY_MESSAGE,
                    ],
                    "events_and_history": {
                        "session_id": session_id,
                        "events": [
                            *map(_event_summary, source_evidence["events"]),
                            *map(_event_summary, evidence["events"]),
                        ],
                        "conversation_roles": [item["role"] for item in history],
                    },
                    "reviewed_memory": {
                        "candidate_id": candidate["candidate_id"],
                        "source_event_id": candidate["source_event_id"],
                        "memory_id": memory.memory_id,
                        "revision": memory.revision,
                        "content_text": memory.content_text,
                        "content_hash": memory.content_hash,
                        "training_eligible": memory.data_policy.training_eligible,
                    },
                    "retrieval_and_context": {
                        "retrieval_result_id": evidence["retrieval_result"][
                            "retrieval_result_id"
                        ],
                        "algorithm_version": evidence["retrieval_result"][
                            "algorithm_version"
                        ],
                        "selection_policy_version": evidence["retrieval_result"][
                            "selection_policy_version"
                        ],
                        "selected_candidates": evidence["retrieval_result"][
                            "candidates"
                        ],
                        "context_pack_id": evidence["context_pack"]["context_pack_id"],
                        "context_sections": [
                            _context_section_summary(section)
                            for section in evidence["context_pack"]["sections"]
                        ],
                    },
                    "model_response": {
                        "assistant_event_id": query.assistant_event_id,
                        "content": query.content,
                        "provider_id": query.provider_id,
                        "model_version_id": query.model_version_id,
                        "adapter_version_id": query.adapter_version_id,
                        "training_eligible": query.training_eligible,
                    },
                    "feedback_and_owner_edit": {
                        "feedback_id": feedback.feedback_id,
                        "revision": feedback.revision,
                        "rating": feedback.rating,
                        "reason_codes": feedback.reason_codes,
                        "owner_revision_text": feedback.owner_revision_text,
                        "training_eligible": feedback.training_eligible,
                        "content_hash": feedback.content_hash,
                    },
                    "episode_and_provenance": {
                        "episode_id": episode["episode_id"],
                        "message_count": episode["message_count"],
                        "member_event_ids": [
                            member["event_id"] for member in episode["members"]
                        ],
                        "training_eligible": episode["training_eligible"],
                        "provenance_audit": provenance_violations,
                    },
                },
            }
        )
    finally:
        await runtime.aclose()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        required=True,
        help="Loopback PostgreSQL URL whose database name starts with havre_showcase_",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("var/showcase/latest.json"),
        help="Ignored local JSON evidence output path",
    )
    return parser


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = _parser().parse_args()
    result = asyncio.run(run_showcase(database_url=args.database_url))
    encoded = json.dumps(result, indent=2, ensure_ascii=False)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    print(f"\nSynthetic evidence written to {args.output}")


if __name__ == "__main__":
    main()
