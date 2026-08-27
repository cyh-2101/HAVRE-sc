"""Populate an exact Stage 4 database before the Stage 5 migration."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from companion.application import InteractionCommand, InteractionService
from companion.consolidation.service import ConsolidationService
from companion.context import ContextBuilder
from companion.evidence import EvidenceRef, EvidenceRelation, EvidenceSourceKind
from companion.goals import GoalTrack
from companion.goals.service import GoalService
from companion.identity import IdentityLoader
from companion.memory import DeterministicEmbeddingProvider
from companion.persistence import PostgresRepository
from companion.policy import PrivacyClass
from companion.state.service import CurrentStateService
from companion.user_model import BeliefTransitionType, BeliefType
from companion.user_model.service import UserModelService
from mlsys.retrieval.service import RetrievalService
from mlsys.serving import DeterministicLocalProvider, Stage1Router


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _event_ref(event_id) -> EvidenceRef:
    return EvidenceRef(
        source_kind=EvidenceSourceKind.EVENT,
        source_id=event_id,
        relation=EvidenceRelation.SUPPORTS,
    )


async def populate(database_url: str) -> dict[str, object]:
    repository = PostgresRepository(database_url)
    repository.open()
    try:
        with repository.pool.connection() as connection:
            migrations = [
                row["migration_id"]
                for row in connection.execute(
                    "SELECT migration_id FROM havre.schema_migrations ORDER BY migration_id"
                ).fetchall()
            ]
        if len(migrations) != 12 or migrations[-1] != (
            "0012_stage4_required_provenance_guards.sql"
        ):
            raise RuntimeError("fixture requires exact migrations 0001 through 0012")

        owner_id = uuid.uuid4()
        identity = IdentityLoader(PROJECT_ROOT / "identity").load()
        repository.bootstrap_owner_and_identity(owner_id=owner_id, identity=identity)
        embedding = DeterministicEmbeddingProvider()
        repository.register_embedding_version(embedding.version)
        interactions = InteractionService(
            owner_id=owner_id,
            identity=identity,
            repository=repository,
            context_builder=ContextBuilder(
                max_input_tokens=4096, reserved_output_tokens=256
            ),
            router=Stage1Router(),
            provider=DeterministicLocalProvider(),
            retrieval_service=RetrievalService(
                repository=repository, embedding_provider=embedding
            ),
        )

        async def source(text: str, occurred_at: datetime):
            return await interactions.interact(
                InteractionCommand(
                    message=text,
                    privacy_class=PrivacyClass.NORMAL,
                    memory_eligible=True,
                    channel="api",
                    client_created_at=occurred_at,
                    idempotency_key=f"stage5-upgrade-{uuid.uuid4()}",
                )
            )

        first = await source(
            "A small rehearsal helped before the first difficult conversation.",
            datetime(2026, 8, 1, tzinfo=UTC),
        )
        second = await source(
            "A second small rehearsal also helped on a different day.",
            datetime(2026, 8, 8, tzinfo=UTC),
        )
        first_ref = _event_ref(first.user_event_id)
        second_ref = _event_ref(second.user_event_id)

        user_model = UserModelService(repository=repository)
        belief = user_model.propose_belief(
            owner_id=owner_id,
            belief_key=f"stage5-upgrade-rehearsal-{uuid.uuid4()}",
            statement="A small rehearsal may help before difficult conversations.",
            belief_type=BeliefType.PATTERN,
            confidence=0.55,
            evidence=(first_ref,),
            reason="Populate the exact Stage 4 upgrade fixture",
            valid_from=datetime(2026, 8, 1, tzinfo=UTC),
        )
        user_model.transition(
            owner_id=owner_id,
            belief_id=belief.belief_id,
            revision=belief.revision,
            transition_type=BeliefTransitionType.ACTIVATED,
            reason="Owner activation in the upgrade fixture",
        )
        state = CurrentStateService(repository=repository).estimate(
            owner_id=owner_id,
            summary="Preparing for one bounded conversation step.",
            state={"preparation": "small_rehearsal"},
            uncertainty=0.25,
            estimated_at=datetime(2026, 8, 8, tzinfo=UTC),
            expires_at=datetime(2026, 8, 8, tzinfo=UTC) + timedelta(hours=2),
            evidence=(second_ref,),
        )
        goals = GoalService(repository=repository)
        goal = goals.create(
            owner_id=owner_id,
            track=GoalTrack.REALITY,
            title="Practice one bounded conversation opening",
            why="Prepare without turning discomfort into danger.",
            source_event_id=first.user_event_id,
            next_action="Rehearse one sentence.",
        )
        goal = goals.update(
            owner_id=owner_id,
            goal_id=goal.goal_id,
            expected_revision=1,
            reason="Retain an event-backed historical Goal revision",
            next_action="Rehearse the opening once.",
        )
        progress = goals.record_progress(
            owner_id=owner_id,
            goal_id=goal.goal_id,
            expected_goal_revision=goal.revision,
            direction="toward",
            summary="Completed the bounded rehearsal.",
            observed_at=datetime(2026, 8, 8, 1, tzinfo=UTC),
            evidence=(second_ref,),
        )
        consolidation = ConsolidationService(
            repository=repository, embedding_provider=embedding
        )
        proposal = consolidation.propose(
            owner_id=owner_id,
            memory_class="pattern",
            content_text="Small rehearsal helped on two distinct observed dates.",
            evidence=(first_ref, second_ref),
            detector_version="pattern-proposal-distinct-days-v1",
        )
        memory = consolidation.accept(
            owner_id=owner_id,
            proposal_id=proposal.proposal_id,
            reason="Populate reviewed Stage 4 lineage before Stage 5",
            confidence=0.6,
        )
        violations = repository.audit_provenance_integrity()
        if violations:
            raise RuntimeError(f"upgrade fixture provenance violations: {violations}")
        return {
            "owner_id": str(owner_id),
            "event_count": 2,
            "belief_id": str(belief.belief_id),
            "state_snapshot_id": str(state.state_snapshot_id),
            "goal_id": str(goal.goal_id),
            "progress_record_id": str(progress.progress_record_id),
            "proposal_id": str(proposal.proposal_id),
            "accepted_memory_id": str(memory.memory_id),
            "provenance_audit": violations,
        }
    finally:
        repository.close()


def main() -> int:
    database_url = os.getenv("HAVRE_TEST_DATABASE_URL")
    if not database_url or "havre_s5_upgrade_" not in database_url:
        raise RuntimeError(
            "HAVRE_TEST_DATABASE_URL must name a dedicated havre_s5_upgrade_ database"
        )
    print(json.dumps(asyncio.run(populate(database_url)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
