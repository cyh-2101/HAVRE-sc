"""Stage 6 controlled context strategies and prefix/cache instrumentation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from companion.hashing import content_hash


@dataclass(frozen=True)
class ContextStrategyResult:
    strategy_version: str
    selected_refs: tuple[str, ...]
    rendered_sections: tuple[dict[str, object], ...]
    estimated_tokens: int
    prefix_hash: str
    cache_key: str
    cache_eligible: bool


class ControlledContextStrategy:
    """Deterministic selection; cache eligibility requires a stable public prefix."""

    def __init__(
        self,
        *,
        mode: Literal["raw_top_k", "summary_top_k", "compressed_top_k"],
        top_k: int,
    ) -> None:
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        self.mode = mode
        self.top_k = top_k
        self.version = f"context-strategy-{mode}-k{top_k}-v1"

    def build(
        self,
        *,
        identity_version: str,
        policy_version: str,
        candidates: tuple[tuple[str, str, int], ...],
    ) -> ContextStrategyResult:
        selected = tuple(sorted(candidates, key=lambda item: (-item[2], item[0]))[: self.top_k])
        prefix = (
            {"section": "identity", "version": identity_version},
            {"section": "policy", "version": policy_version},
        )
        evidence: list[dict[str, object]] = []
        for ref, text, score in selected:
            if self.mode == "raw_top_k":
                rendered = text
            elif self.mode == "summary_top_k":
                rendered = text[:160]
            else:
                rendered = " ".join(text.split())[:96]
            evidence.append({"ref": ref, "content": rendered, "score": score})
        sections = (*prefix, *evidence)
        prefix_hash = content_hash(prefix)
        return ContextStrategyResult(
            strategy_version=self.version,
            selected_refs=tuple(item[0] for item in selected),
            rendered_sections=sections,
            estimated_tokens=max(1, sum(len(str(section)) for section in sections) // 4),
            prefix_hash=prefix_hash,
            cache_key=content_hash({"strategy": self.version, "prefix": prefix_hash}),
            cache_eligible=True,
        )
