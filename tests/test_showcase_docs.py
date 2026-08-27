from __future__ import annotations

import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHOWCASE_DOCUMENTS = (
    PROJECT_ROOT / "README.md",
    PROJECT_ROOT / "docs" / "RESUME_EVIDENCE.md",
    PROJECT_ROOT / "docs" / "SHOWCASE_DEMO.md",
    PROJECT_ROOT / "docs" / "PUBLIC_RELEASE_AUDIT.md",
)


class ShowcaseDocumentationTests(unittest.TestCase):
    def test_local_links_in_showcase_documents_resolve(self) -> None:
        pattern = re.compile(r"(?<!!)\[[^]]+\]\(([^)]+)\)")
        for document in SHOWCASE_DOCUMENTS:
            text = document.read_text(encoding="utf-8")
            for raw_target in pattern.findall(text):
                target = raw_target.split("#", 1)[0]
                if not target or "://" in target:
                    continue
                resolved = (document.parent / target).resolve()
                self.assertTrue(
                    resolved.exists(),
                    f"{document.relative_to(PROJECT_ROOT)} -> {raw_target}",
                )

    def test_readme_preserves_claim_and_publication_boundaries(self) -> None:
        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertRegex(readme, r"Major development is\s+paused")
        self.assertIn("public-safe synthetic demo", readme)
        self.assertRegex(readme, r"does\s+not prove model quality")
        self.assertIn("PUBLIC_RELEASE_AUDIT.md", readme)
        self.assertIn("no behavioral adapter was promoted", readme)

    def test_release_audit_is_bound_to_sanitized_public_mirror(self) -> None:
        audit = (PROJECT_ROOT / "docs" / "PUBLIC_RELEASE_AUDIT.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("PUBLICATION CANDIDATE: PASS", audit)
        self.assertIn("cyh-2101/HAVRE-sc", audit)
        self.assertIn("Apache-2.0", audit)
        self.assertIn("new root commit", audit)
        self.assertIn("private archive remains authoritative", audit)

    def test_public_documents_do_not_embed_owner_paths_or_email(self) -> None:
        for document in SHOWCASE_DOCUMENTS:
            text = document.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"[A-Za-z]:\\(?:Users|projects)\\")
            self.assertNotRegex(text, r"/home/[A-Za-z0-9._-]+")
            self.assertNotRegex(text, r"@[A-Za-z0-9.-]+\.(?:com|net|org)")


if __name__ == "__main__":
    unittest.main()
