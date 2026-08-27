"""Create one reviewed memory, retrieve it in a later request, and print evidence."""

from __future__ import annotations

import asyncio
import json

from fastapi.encoders import jsonable_encoder

from companion.application import InteractionCommand
from companion.ids import uuid7
from companion.policy import PrivacyClass
from services.api.runtime import build_runtime
from services.api.settings import Settings


async def main() -> None:
    settings = Settings.from_env()
    runtime = build_runtime(settings)
    try:
        source = await runtime.service.interact(
            InteractionCommand(
                message="For piano practice I use a slow metronome and repeat the difficult measure.",
                privacy_class=PrivacyClass.NORMAL,
                channel="cli",
                idempotency_key=f"stage2-demo-source-{uuid7()}",
            )
        )
        runtime.memory_worker.run_once()
        candidate = next(
            item
            for item in runtime.memory_service.list_candidates(
                owner_id=settings.owner_id,
                status="pending",
            )
            if item["source_event_id"] == source.user_event_id
        )
        memory = runtime.memory_service.accept_candidate(
            owner_id=settings.owner_id,
            candidate_id=candidate["candidate_id"],
            reason="Stage 2 checkpoint demonstration",
        )
        query = await runtime.service.interact(
            InteractionCommand(
                message="What was my piano practice method with the metronome?",
                privacy_class=PrivacyClass.NORMAL,
                memory_eligible=False,
                channel="cli",
                idempotency_key=f"stage2-demo-query-{uuid7()}",
            )
        )
        evidence = runtime.repository.evidence(
            query.request_id,
            owner_id=settings.owner_id,
        )
        print(
            json.dumps(
                jsonable_encoder(
                    {
                        "source_request": source,
                        "candidate": candidate,
                        "accepted_memory": memory,
                        "retrieval_request": query,
                        "stored_user_and_assistant_events": evidence["events"],
                        "stored_retrieval_result": evidence["retrieval_result"],
                        "stored_context_pack": evidence["context_pack"],
                        "provider_and_model": {
                            "provider_id": evidence["inference"]["provider_id"],
                            "model_version_id": evidence["inference"]["model_version_id"],
                            "embedding_version_id": evidence["retrieval_result"]["embedding_version_id"],
                            "algorithm_version": evidence["retrieval_result"]["algorithm_version"],
                        },
                        "metrics": {
                            "retrieval_timing_ms": evidence["retrieval_result"]["timing_ms"],
                            "inference_timing_ms": evidence["inference"]["timing_ms"],
                            "usage": evidence["inference"]["usage"],
                        },
                    }
                ),
                indent=2,
                ensure_ascii=False,
            )
        )
    finally:
        runtime.close()


if __name__ == "__main__":
    asyncio.run(main())
