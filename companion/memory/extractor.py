"""Transparent Stage 2 episodic candidate extraction."""

from __future__ import annotations

from companion.events import EventEnvelope, UserMessagePayload
from companion.memory.models import MemoryCandidate
from companion.policy import DataPolicy


class DeterministicEpisodicExtractor:
    version = "episodic-extractor-rule-v1"
    confidence_method = "source-message-direct-v1"
    importance_policy_version = "uniform-owner-review-v1"

    def extract(self, *, event: EventEnvelope, job_id) -> MemoryCandidate:
        if not isinstance(event.payload, UserMessagePayload):
            raise TypeError("episodic extraction requires USER_MESSAGE")
        if not event.data_policy.memory_eligible:
            raise ValueError("source event is not memory eligible")
        text = "\n".join(part.text for part in event.payload.content_parts).strip()
        derived_policy = DataPolicy(
            privacy_class=event.data_policy.privacy_class,
            memory_eligible=event.data_policy.memory_eligible,
            training_eligible=False,
            cloud_eligible=(
                event.data_policy.cloud_eligible
                and event.data_policy.privacy_class.value
                in {"PUBLIC", "NORMAL", "PRIVATE"}
            ),
            policy_version=event.data_policy.policy_version,
            decision_source="derived_conservative",
        )
        return MemoryCandidate(
            owner_id=event.owner_id,
            source_event_id=event.event_id,
            source_request_id=event.request_id,
            job_id=job_id,
            content={
                "schema_version": 1,
                "kind": "user_reported_episode",
                "text": text,
                "language": event.payload.language,
            },
            content_text=text,
            confidence=0.9,
            confidence_method=self.confidence_method,
            importance=0.5,
            importance_policy_version=self.importance_policy_version,
            extractor_version=self.version,
            data_policy=derived_policy,
            trace_id=event.trace_id,
        )
