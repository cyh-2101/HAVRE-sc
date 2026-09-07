from __future__ import annotations

import unittest

from companion.context import CONTEXT_PRESENTATION_VERSION
from companion.identity import IdentityLoader
from evals.strong_cloud_brain_broader import (
    MAX_OUTPUT_TOKENS,
    _request_for_case,
    current_prompt_messages,
    prompt_comparability,
)
from mlsys.training.stage9a_provenance import PROJECT_ROOT
from mlsys.training.stage9a_unseen_v7 import load_and_verify_unseen


class StrongCloudBrainBroaderTests(unittest.TestCase):
    def test_exact_existing_80_case_public_suite_and_current_context(self) -> None:
        manifest, cases = load_and_verify_unseen()
        self.assertEqual(len(cases), 80)
        self.assertTrue(all(case["privacy_class"] == "SYNTHETIC" for case in cases))
        self.assertTrue(all(case["contains_user_data"] is False for case in cases))
        identity = IdentityLoader(PROJECT_ROOT / "identity").load().system_text()
        comparison = prompt_comparability(cases, identity)
        self.assertEqual(comparison["exact_same_provider_facing_prompt_case_count"], 0)
        self.assertEqual(comparison["same_case_messages_and_targets_count"], 80)
        self.assertEqual(comparison["identity_system_text_changed_case_count"], 80)
        self.assertGreater(comparison["current_memory_presentation_case_count"], 0)
        memory_case = next(case for case in cases if case["memory_context"])
        request, messages, prompt_hash = _request_for_case(
            memory_case,
            identity=identity,
            manifest_hash=manifest["content_hash"],
        )
        self.assertEqual(request.generation.max_output_tokens, MAX_OUTPUT_TOKENS)
        self.assertEqual(
            request.metadata["context_presentation_version"],
            CONTEXT_PRESENTATION_VERSION,
        )
        self.assertEqual(messages, current_prompt_messages(memory_case, identity))
        self.assertTrue(prompt_hash.startswith("sha256:"))
        self.assertEqual(request.constraints.effective_data_policy.privacy_class.value, "PUBLIC")


if __name__ == "__main__":
    unittest.main()
