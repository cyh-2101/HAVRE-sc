"""Versioned local deterministic embedding baseline for Stage 2 measurement."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass

from companion.hashing import content_hash


TOKEN_RE = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True)
class EmbeddingVersion:
    embedding_version_id: str
    provider_id: str
    model_revision: str
    dimension: int
    distance_metric: str
    normalization: str
    tokenizer_version: str
    implementation_hash: str


class DeterministicEmbeddingProvider:
    """A dependency-free signed feature hash, not a claimed semantic model."""

    dimension = 64
    version = EmbeddingVersion(
        embedding_version_id="embedding-deterministic-hash-v1",
        provider_id="local-deterministic",
        model_revision="signed-token-chargram-hash-v1",
        dimension=dimension,
        distance_metric="cosine",
        normalization="l2",
        tokenizer_version="unicode-word-chargram-v1",
        implementation_hash=content_hash(
            {
                "algorithm": "signed-token-chargram-hash",
                "dimension": dimension,
                "features": ["word", "character-trigram"],
                "normalization": "l2",
            }
        ),
    )

    def embed(self, text: str) -> tuple[float, ...]:
        normalized = " ".join(text.casefold().split())
        tokens = TOKEN_RE.findall(normalized)
        features = [f"w:{token}" for token in tokens]
        for token in tokens:
            padded = f"^{token}$"
            features.extend(
                f"c3:{padded[index:index + 3]}"
                for index in range(max(1, len(padded) - 2))
            )
        values = [0.0] * self.dimension
        for feature in features:
            digest = hashlib.sha256(feature.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] & 1 else -1.0
            values[index] += sign
        norm = math.sqrt(sum(value * value for value in values))
        if norm == 0:
            return tuple(values)
        return tuple(round(value / norm, 10) for value in values)

    @staticmethod
    def pgvector(vector: tuple[float, ...]) -> str:
        return "[" + ",".join(format(value, ".10g") for value in vector) + "]"
