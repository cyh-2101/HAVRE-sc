"""Stage 5 Scene application service."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from companion.persistence.scenes import ScenePostgresStore
from companion.policy import PrivacyClass
from companion.policy.intervention import (
    AvoidanceAssessment,
    CoercionAssessment,
    DangerAssessment,
    EnergyAssessment,
    GoalAlignment,
    GoalUrgency,
    SceneSignalType,
)


class SceneService:
    version = "scene-service-v1"

    def __init__(self, *, store: ScenePostgresStore) -> None:
        self.store = store

    def create(self, **kwargs):
        return self.store.create(**kwargs)

    def get(self, *, scene_session_id: UUID):
        return self.store.get(scene_session_id=scene_session_id)

    def transition(
        self,
        *,
        scene_session_id: UUID,
        expected_revision: int,
        action: Literal["start", "pause", "resume", "after", "close"],
        reason: str,
        terminal_status: Literal["completed", "abandoned", "cancelled"] | None,
        idempotency_key: str,
        traceparent: str | None = None,
    ):
        return self.store.transition(
            scene_session_id=scene_session_id,
            expected_revision=expected_revision,
            action=action,
            reason=reason,
            terminal_status=terminal_status,
            idempotency_key=idempotency_key,
            traceparent=traceparent,
        )

    def signal(self, **kwargs):
        return self.store.signal(**kwargs)

    def record_action(self, **kwargs):
        return self.store.record_action(**kwargs)

    def record_outcome(self, **kwargs):
        return self.store.record_outcome(**kwargs)

    def reflect(self, **kwargs):
        return self.store.reflect(**kwargs)
