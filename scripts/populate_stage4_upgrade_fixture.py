"""Populate an exact 0008 database before the Stage 4 0009 upgrade."""

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


def event_ref(event_id) -> EvidenceRef:
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
                    "SELECT migration_id FROM havre.schema_migrations "
                    "ORDER BY migration_id"
                ).fetchall()
            ]
        if not migrations or migrations[-1] != "0008_stage4_acceptance_corrections.sql":
            raise RuntimeError(
                "upgrade fixture requires an exact 0001-0008 database before 0009"
            )

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
            return await interactions.interact(InteractionCommand(
                message=text,
                privacy_class=PrivacyClass.NORMAL,
                memory_eligible=True,
                channel="api",
                client_created_at=occurred_at,
                idempotency_key=f"stage4-upgrade-{uuid.uuid4()}",
            ))

        first = await source(
            "Slow piano practice helped on the first observed day.",
            datetime(2026, 7, 1, tzinfo=UTC),
        )
        second = await source(
            "Slow piano practice helped again on another observed day.",
            datetime(2026, 7, 8, tzinfo=UTC),
        )
        first_ref = event_ref(first.user_event_id)
        second_ref = event_ref(second.user_event_id)

        user_model = UserModelService(repository=repository)
        belief = user_model.propose_belief(
            owner_id=owner_id,
            belief_key=f"upgrade-piano-{uuid.uuid4()}",
            statement="Slow piano practice may help the owner continue.",
            belief_type=BeliefType.PATTERN,
            confidence=0.55,
            evidence=(first_ref,),
            reason="Populate the 0007 upgrade fixture",
            valid_from=datetime(2026, 7, 1, tzinfo=UTC),
        )
        # Current application writes require the additive 0009 transition-ID
        # column. Populate one authentic immutable pre-0009 transition through
        # the exact 0008 schema so the upgrade must fail closed by consuming it.
        with repository.pool.connection() as connection, connection.transaction():
            current = connection.execute(
                """
                SELECT revision.*, head.status AS effective_status,
                       event.session_id, event.request_id,
                       event.event_id AS anchor_event_id
                FROM havre.belief_heads AS head
                JOIN havre.user_belief_revisions AS revision
                  ON revision.owner_id = head.owner_id
                 AND revision.belief_id = head.belief_id
                 AND revision.revision = head.current_revision
                JOIN havre.events AS event
                  ON event.owner_id = revision.owner_id
                 AND event.event_id = revision.created_event_id
                WHERE head.owner_id = %s AND head.belief_id = %s
                FOR UPDATE OF head
                """,
                (owner_id, belief.belief_id),
            ).fetchone()
            assert current is not None
            transition_event, transition = repository._build_belief_transition(
                owner_id=owner_id,
                belief_id=belief.belief_id,
                revision=1,
                transition_type=BeliefTransitionType.ACTIVATED,
                reason="Populate an immutable pre-0009 activation transition",
                occurred_at=datetime.now(UTC),
                policy=repository._policy_from_row(current),
                anchor=current,
            )
            repository._insert_event(connection, transition_event)
            transition = repository._insert_belief_transition(connection, transition)
            connection.execute(
                """
                UPDATE havre.belief_heads
                SET status = 'active', updated_at = GREATEST(
                    clock_timestamp(), updated_at + interval '1 microsecond',
                    %s::timestamptz + interval '1 second'
                )
                WHERE owner_id = %s AND belief_id = %s
                """,
                (transition.recorded_at, owner_id, belief.belief_id),
            )

        state = CurrentStateService(repository=repository).estimate(
            owner_id=owner_id,
            summary="Prefer a small piano step today.",
            state={"piano_step": "small"},
            uncertainty=0.2,
            estimated_at=datetime(2026, 7, 8, tzinfo=UTC),
            expires_at=datetime(2026, 7, 8, tzinfo=UTC) + timedelta(hours=2),
            evidence=(second_ref,),
        )
        goals = GoalService(repository=repository)
        goal = goals.create(
            owner_id=owner_id,
            track=GoalTrack.REALITY,
            title="Practice piano slowly",
            why="Build consistency with a bounded step.",
            source_event_id=first.user_event_id,
            next_action="Practice for five minutes.",
        )
        goal = goals.update(
            owner_id=owner_id,
            goal_id=goal.goal_id,
            expected_revision=1,
            reason="Populate an event-backed Goal revision",
            next_action="Practice one measure for five minutes.",
        )
        progress = goals.record_progress(
            owner_id=owner_id,
            goal_id=goal.goal_id,
            expected_goal_revision=2,
            direction="toward",
            summary="Completed the five-minute step.",
            observed_at=datetime(2026, 7, 8, 1, tzinfo=UTC),
            evidence=(second_ref,),
        )

        consolidation = ConsolidationService(
            repository=repository, embedding_provider=embedding
        )
        proposal = consolidation.propose(
            owner_id=owner_id,
            memory_class="pattern",
            content_text="Slow piano practice helped on two observed dates.",
            evidence=(first_ref, second_ref),
            detector_version="pattern-proposal-distinct-days-v1",
        )
        memory = consolidation.accept(
            owner_id=owner_id,
            proposal_id=proposal.proposal_id,
            reason="Populate reviewed proposal relationships",
            confidence=0.6,
        )
        violations = repository.audit_provenance_integrity()
        if violations:
            raise RuntimeError(f"upgrade fixture provenance violations: {violations}")
        return {
            "owner_id": str(owner_id),
            "belief_id": str(belief.belief_id),
            "belief_revision": belief.revision,
            "pre_0009_transition_id": str(transition.belief_transition_id),
            "state_snapshot_id": str(state.state_snapshot_id),
            "goal_id": str(goal.goal_id),
            "goal_revision": goal.revision,
            "progress_record_id": str(progress.progress_record_id),
            "proposal_id": str(proposal.proposal_id),
            "accepted_memory_id": str(memory.memory_id),
            "provenance_audit": violations,
        }
    finally:
        repository.close()


def main() -> int:
    database_url = os.getenv("HAVRE_TEST_DATABASE_URL")
    if not database_url or "havre_s4_reaccept_0009_upgrade_" not in database_url:
        raise RuntimeError(
            "HAVRE_TEST_DATABASE_URL must name a dedicated "
            "havre_s4_reaccept_0009_upgrade_ database"
        )
    print(json.dumps(asyncio.run(populate(database_url)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
