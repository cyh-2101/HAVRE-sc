from __future__ import annotations

import json
import unittest
from pathlib import Path

from mlsys.training.stage9a_provenance import MODEL_MANIFEST, load_model_manifest


class Stage9AProvenanceTests(unittest.TestCase):
    def test_model_manifest_pins_exact_revision_and_shards(self) -> None:
        manifest = load_model_manifest()
        self.assertEqual(manifest["repository"], "Qwen/Qwen3-8B")
        self.assertEqual(
            manifest["revision"], "b968826d9c46dd6066d109eabc6255188de91218"
        )
        self.assertEqual(manifest["license"]["identifier"], "Apache-2.0")
        shards = [
            item for item in manifest["files"] if item["path"].endswith(".safetensors")
        ]
        self.assertEqual(len(shards), 5)
        self.assertTrue(all(len(item["lfs_sha256"]) == 64 for item in shards))

    def test_manifest_total_is_exact(self) -> None:
        manifest = json.loads(MODEL_MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(
            sum(item["size_bytes"] for item in manifest["files"]),
            manifest["expected_total_size_bytes"],
        )


if __name__ == "__main__":
    unittest.main()
