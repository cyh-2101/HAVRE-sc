from pathlib import Path
import unittest
from datetime import UTC, date, datetime
from uuid import uuid4

from companion.product.diary_intelligence import DiaryIntelligenceService

from companion.context.experience import OWNER_EXPERIENCE_GUIDANCE
from companion.context.persona import follow_up_persona
from companion.identity import IdentityLoader
from companion.policy import DataPolicy, PrivacyClass, combine_policies


ROOT = Path(__file__).resolve().parents[1]


class FollowUpPersonaTests(unittest.TestCase):
    def test_reuses_exact_canonical_identity_without_outreach_authority(self):
        identity = IdentityLoader(ROOT / "identity").load()
        persona = follow_up_persona(identity)
        self.assertIn(identity.system_text(), persona.text)
        self.assertIn(OWNER_EXPERIENCE_GUIDANCE, persona.text)
        self.assertIn("follow_up_suggestion.message only", persona.text)
        self.assertIn("must remain the owner's first-person account", persona.text)
        self.assertIn("does not authorize a follow-up", persona.text)
        for artifact in (identity.constitution, identity.identity, identity.values):
            self.assertIn(
                f"{artifact.artifact_kind}/{artifact.version_id}@{artifact.content_hash}",
                persona.source_refs,
            )
        self.assertFalse(any(ref.startswith("owner-alignment/") for ref in persona.source_refs))
        self.assertFalse(persona.data_policy.memory_eligible)
        self.assertFalse(persona.data_policy.training_eligible)

    def test_guidance_retains_its_own_policy_when_source_is_public_or_local(self):
        persona = follow_up_persona(IdentityLoader(ROOT / "identity").load())
        public = combine_policies((DataPolicy.owner_default(PrivacyClass.PUBLIC), persona.data_policy))
        self.assertEqual(public.privacy_class, PrivacyClass.NORMAL)
        local = combine_policies((DataPolicy.owner_default(PrivacyClass.LOCAL_ONLY), persona.data_policy))
        self.assertEqual(local.privacy_class, PrivacyClass.LOCAL_ONLY)
        self.assertFalse(local.cloud_eligible)


class DiaryFollowUpPersonaIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.identity = IdentityLoader(ROOT / "identity").load()
        self.owner = uuid4()
        self.event_id = uuid4()
        self.event = {
            "event_id": self.event_id, "role": "user", "content": "Synthetic public experience.",
            "recorded_at": datetime(2026, 9, 6, 12, tzinfo=UTC), "privacy_class": "PUBLIC",
        }

    def _request(self, *, identity, memory_only=False):
        service = DiaryIntelligenceService(
            repository=None, owner_id=self.owner, provider=None,
            embedding_provider=None, identity=identity,
        )
        return service._request(
            local_date=date(2026, 9, 6), timezone_name="America/Chicago",
            source_set_hash="sha256:" + "a" * 64,
            cloud_events=[self.event], private_count=2, memory_only=memory_only,
        )

    def test_diary_follow_up_gets_identity_without_additional_private_evidence(self):
        before = self._request(identity=None)
        after = self._request(identity=self.identity)
        self.assertEqual(len(after.messages), len(before.messages))
        # Reuse exactly the already eligible transcript. Persona injection must
        # never add private events, Memory retrieval, or original OA70 examples.
        self.assertEqual(after.messages[1], before.messages[1])
        self.assertEqual(after.generation, before.generation)
        self.assertEqual(after.purpose, before.purpose)
        system = after.messages[0].content_parts[0].text
        self.assertIn(self.identity.system_text(), system)
        self.assertIn("follow_up_suggestion.message only", system)
        self.assertIn("must remain the owner's first-person account", system)
        self.assertIn("follow_up_persona_version", after.metadata)
        self.assertEqual(after.constraints.effective_data_policy.privacy_class, PrivacyClass.NORMAL)
        self.assertFalse(after.constraints.effective_data_policy.training_eligible)
        self.assertFalse(any(ref.startswith("owner-alignment/")
                             for ref in after.messages[0].source_refs))

    def test_daily_source_fingerprint_binds_persona_but_realtime_does_not(self):
        source = dict(self.event, content_hash="sha256:" + "c" * 64, disposition="cloud_summary")
        before = DiaryIntelligenceService(
            repository=None, owner_id=self.owner, provider=None, embedding_provider=None,
        )
        after = DiaryIntelligenceService(
            repository=None, owner_id=self.owner, provider=None, embedding_provider=None,
            identity=self.identity,
        )
        self.assertNotEqual(before._source_set_hash([source], []), after._source_set_hash([source], []))
        self.assertEqual(
            before._source_set_hash([source], [], memory_only=True),
            after._source_set_hash([source], [], memory_only=True),
        )
        changed_identity = self.identity.model_copy(update={
            "identity": self.identity.identity.model_copy(update={
                "content_hash": "sha256:" + "d" * 64,
            }),
        })
        changed = DiaryIntelligenceService(
            repository=None, owner_id=self.owner, provider=None, embedding_provider=None,
            identity=changed_identity,
        )
        self.assertNotEqual(after._source_set_hash([source], []), changed._source_set_hash([source], []))

    def test_realtime_memory_only_prompt_does_not_inherit_outreach_persona(self):
        before = self._request(identity=None, memory_only=True)
        after = self._request(identity=self.identity, memory_only=True)
        self.assertEqual(after.messages, before.messages)
        self.assertEqual(after.purpose, "memory_intelligence")
        self.assertNotIn("follow_up_persona_version", after.metadata)
        self.assertEqual(after.constraints.effective_data_policy.privacy_class, PrivacyClass.PUBLIC)


if __name__ == "__main__":
    unittest.main()
