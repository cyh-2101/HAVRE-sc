from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from mlsys.serving.stage9a_candidate import build_stage9a_candidate_provider
from mlsys.serving.stage9a_candidate_server import _messages
from services.api.cli import run_owner_chat_loop


class Stage9ACandidateBoundaryTests(unittest.TestCase):
    def test_candidate_provider_is_development_only(self) -> None:
        settings = SimpleNamespace(
            deployment_environment="production",
            release_manifest_path=Path("release.json"),
        )
        with self.assertRaisesRegex(ValueError, "development-only"):
            build_stage9a_candidate_provider(settings)

    def test_candidate_provider_rejects_release_manifest_even_in_development(self) -> None:
        settings = SimpleNamespace(
            deployment_environment="development",
            release_manifest_path=Path("release.json"),
        )
        with self.assertRaisesRegex(ValueError, "cannot consume a release manifest"):
            build_stage9a_candidate_provider(settings)

    def test_candidate_server_accepts_only_explicit_text_parts(self) -> None:
        self.assertEqual(
            _messages(
                {
                    "messages": [
                        {
                            "role": "system",
                            "content": [{"type": "text", "text": "Identity"}],
                        },
                        {
                            "role": "user",
                            "content": [{"type": "text", "text": "Hello"}],
                        },
                    ]
                }
            ),
            [
                {"role": "system", "content": "Identity"},
                {"role": "user", "content": "Hello"},
            ],
        )
        with self.assertRaisesRegex(ValueError, "only non-empty text parts"):
            _messages(
                {
                    "messages": [
                        {
                            "role": "user",
                            "content": [{"type": "image", "text": "private"}],
                        }
                    ]
                }
            )


class _FakeService:
    def __init__(self) -> None:
        self.commands = []

    async def interact(self, command):
        self.commands.append(command)
        return SimpleNamespace(
            content="A short candidate response.",
            user_event_id=uuid4(),
        )


class _FakeWorker:
    def __init__(self, service: _FakeService) -> None:
        self.service = service
        self.candidate_id = uuid4()

    def run_once(self):
        result_event = self.service.commands[-1]
        # run_owner_chat_loop compares against the result's user_event_id. The
        # fake service exposes that through a stable field below.
        return {
            "candidate_id": self.candidate_id,
            "source_event_id": self.service.last_event_id,
            "content_text": result_event.message,
        }


class _OwnerChatService(_FakeService):
    async def interact(self, command):
        self.commands.append(command)
        self.last_event_id = uuid4()
        return SimpleNamespace(
            content="A short candidate response.",
            user_event_id=self.last_event_id,
        )


class _FakeMemoryService:
    def __init__(self) -> None:
        self.accepted = []
        self.rejected = []

    def accept_candidate(self, **kwargs):
        self.accepted.append(kwargs)
        return SimpleNamespace(memory_id=uuid4())

    def reject_candidate(self, **kwargs):
        self.rejected.append(kwargs)
        return {"status": "rejected"}

    def list_active(self, **_kwargs):
        return []

    def list_candidates(self, **_kwargs):
        return []


class OwnerReviewedMemoryChatTests(unittest.IsolatedAsyncioTestCase):
    async def test_owner_chat_marks_input_memory_eligible_but_requires_acceptance(self) -> None:
        service = _OwnerChatService()
        memory = _FakeMemoryService()
        runtime = SimpleNamespace(
            service=service,
            memory_worker=_FakeWorker(service),
            memory_service=memory,
            settings=SimpleNamespace(owner_id=uuid4()),
        )
        inputs = iter(["I practice piano on Sundays.", "a", "/exit"])
        output: list[str] = []
        await run_owner_chat_loop(
            runtime,
            input_fn=lambda _prompt: next(inputs),
            output_fn=output.append,
        )
        self.assertEqual(len(service.commands), 1)
        self.assertTrue(service.commands[0].memory_eligible)
        self.assertEqual(service.commands[0].privacy_class.value, "LOCAL_ONLY")
        self.assertEqual(len(memory.accepted), 1)
        self.assertEqual(len(memory.rejected), 0)

    async def test_owner_chat_keeps_candidate_pending_without_explicit_decision(self) -> None:
        service = _OwnerChatService()
        memory = _FakeMemoryService()
        runtime = SimpleNamespace(
            service=service,
            memory_worker=_FakeWorker(service),
            memory_service=memory,
            settings=SimpleNamespace(owner_id=uuid4()),
        )
        inputs = iter(["A fact that still needs review.", "", "/exit"])
        output: list[str] = []
        await run_owner_chat_loop(
            runtime,
            input_fn=lambda _prompt: next(inputs),
            output_fn=output.append,
        )
        self.assertEqual(memory.accepted, [])
        self.assertEqual(memory.rejected, [])
        self.assertTrue(any("kept pending" in line for line in output))


if __name__ == "__main__":
    unittest.main()
