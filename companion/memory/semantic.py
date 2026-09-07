"""Pinned, offline multilingual embeddings; no provider calls or text cache."""

from __future__ import annotations

import hashlib
from pathlib import Path
from threading import RLock

from companion.hashing import content_hash
from companion.memory.embedding import DeterministicEmbeddingProvider, EmbeddingVersion

MODEL_REPOSITORY = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MODEL_REVISION = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
MODEL_FILES = {
    "onnx/model_quint8_avx2.onnx": "98a01d88b7de996cdea58c32ca71208c09968d143798814b2ea09d3439dc334f",
    "tokenizer.json": "2c3387be76557bd40970cec13153b3bbf80407865484b209e655e5e4729076b8",
}


class LocalSemanticEmbeddingProvider:
    """CPU-only mean pooling with the model's 128-token training window."""

    dimension = 384
    semantic = True
    version = EmbeddingVersion(
        embedding_version_id="embedding-minilm-multilingual-int8-v1",
        provider_id="local-onnx",
        model_revision=f"{MODEL_REPOSITORY}@{MODEL_REVISION}",
        dimension=384, distance_metric="cosine", normalization="l2",
        tokenizer_version=f"minilm-tokenizer@{MODEL_FILES['tokenizer.json']}",
        implementation_hash=content_hash({
            "files": MODEL_FILES, "pooling": "attention-masked-mean-l2",
            "max_length": 128, "runtime": "onnxruntime-1.29.0-cpu",
            "tokenizers": "0.23.2", "version": 1,
        }),
    )
    pgvector = staticmethod(DeterministicEmbeddingProvider.pgvector)

    def __init__(self, model_root: Path) -> None:
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self._np = np
        root = model_root.resolve(strict=True)
        for name, digest in MODEL_FILES.items():
            path = (root / name).resolve(strict=True)
            if not path.is_relative_to(root):
                raise ValueError("encoder artifact escapes model root")
            with path.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                    raise ValueError(f"semantic embedding artifact mismatch: {name}")
        self._lock = RLock()
        self._tokenizer = Tokenizer.from_file(str(root / "tokenizer.json"))
        self._tokenizer.enable_truncation(max_length=128)
        self._tokenizer.enable_padding()
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        self._session = ort.InferenceSession(
            str(root / "onnx/model_quint8_avx2.onnx"),
            sess_options=options, providers=["CPUExecutionProvider"],
        )

    def embed_many(self, texts: list[str]) -> list[tuple[float, ...]]:
        np = self._np
        result = []
        with self._lock:
            for start in range(0, len(texts), 16):
                encoded = self._tokenizer.encode_batch(texts[start:start + 16])
                values = {
                    "input_ids": np.asarray([x.ids for x in encoded], dtype=np.int64),
                    "attention_mask": np.asarray([x.attention_mask for x in encoded], dtype=np.int64),
                    "token_type_ids": np.asarray([x.type_ids for x in encoded], dtype=np.int64),
                }
                feed = {x.name: values[x.name] for x in self._session.get_inputs()}
                hidden = self._session.run(None, feed)[0]
                mask = values["attention_mask"][..., None]
                pooled = (hidden * mask).sum(axis=1) / np.maximum(mask.sum(axis=1), 1)
                pooled /= np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12)
                if not np.isfinite(pooled).all() or pooled.shape[1] != self.dimension:
                    raise ValueError("invalid semantic embedding")
                result.extend(tuple(float(v) for v in row) for row in pooled)
        return result

    def embed(self, text: str) -> tuple[float, ...]:
        return self.embed_many([text])[0]
