"""Load approved identity content from version-controlled source artifacts."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from companion.hashing import content_hash
from companion.identity.models import ApprovedTextArtifact, IdentityBundle


class IdentityLoader:
    CONSTITUTION_FILES = ("constitution.md",)
    IDENTITY_FILES = (
        "mission.md",
        "personality.md",
        "boundaries.md",
        "communication_style.md",
    )
    VALUES_FILES = ("principles.md",)

    def __init__(self, root: Path) -> None:
        self.root = root

    def load(self) -> IdentityBundle:
        governance = json.loads(
            (self.root / "governance.json").read_text(encoding="utf-8")
        )
        if governance["approved_by"] != "owner":
            raise ValueError("identity governance must be owner-approved")
        approved_at = datetime.fromisoformat(
            governance["approved_at"].replace("Z", "+00:00")
        )
        return IdentityBundle(
            constitution=self._artifact(
                "constitution", "constitution-v1", self.CONSTITUTION_FILES, approved_at
            ),
            identity=self._artifact(
                "identity", "identity-v1", self.IDENTITY_FILES, approved_at
            ),
            values=self._artifact("values", "values-v1", self.VALUES_FILES, approved_at),
            governance_version=governance["governance_version"],
        )

    def _artifact(
        self,
        kind: str,
        version_id: str,
        names: tuple[str, ...],
        approved_at: datetime,
    ) -> ApprovedTextArtifact:
        content = "\n\n".join(
            (self.root / name).read_text(encoding="utf-8").strip()
            for name in names
        )
        return ApprovedTextArtifact(
            artifact_kind=kind,
            version_id=version_id,
            content=content,
            content_hash=content_hash(content),
            approved_by="owner",
            approved_at=approved_at,
            source_files=names,
        )
