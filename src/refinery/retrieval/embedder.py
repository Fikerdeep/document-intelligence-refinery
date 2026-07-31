"""Embeddings behind one protocol, cached by content hash.

The cache means every chunk is embedded exactly once, ever — re-runs and
store rebuilds are free, and switching providers only re-pays for chunks
the new model has not seen. The hash embedder is the offline fallback:
deterministic character-ngram folding, useful for tests and demos, honest
about not being semantic.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Protocol

from refinery.config import EmbeddingRules
from refinery.models.ldu import content_hash


class Embedder(Protocol):
    """Anything that turns texts into fixed-size vectors."""

    name: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashEmbedder:
    """Deterministic, offline, NOT semantic: ngrams folded into a fixed vector."""

    def __init__(self, dim: int = 256):
        self.name = f"hash-{dim}"
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            vector = [0.0] * self.dim
            lowered = " ".join(text.lower().split())
            for n in (3, 5):
                for i in range(len(lowered) - n + 1):
                    bucket = int(hashlib.md5(lowered[i:i + n].encode()).hexdigest(), 16)
                    vector[bucket % self.dim] += 1.0
            norm = math.sqrt(sum(v * v for v in vector)) or 1.0
            vectors.append([v / norm for v in vector])
        return vectors


class APIEmbedder:
    """OpenAI-compatible /embeddings endpoint; key from the environment only."""

    def __init__(self, rules: EmbeddingRules, api_key: str):
        self.name = rules.model
        self.dim = rules.dim
        self._rules = rules
        self._key = api_key

    def embed(self, texts: list[str]) -> list[list[float]]:
        import httpx

        reply = httpx.post(f"{self._rules.base_url}/embeddings",
                           headers={"Authorization": f"Bearer {self._key}"},
                           json={"model": self._rules.model, "input": texts},
                           timeout=60).json()
        return [item["embedding"] for item in reply["data"]]


class CachedEmbedder:
    """Wraps any embedder with a content-hash cache under .refinery/embeddings/."""

    def __init__(self, inner: Embedder, cache_dir: Path | str = ".refinery/embeddings"):
        self.name = inner.name
        self.dim = inner.dim
        self._inner = inner
        self._dir = Path(cache_dir) / inner.name.replace("/", "_")
        self._dir.mkdir(parents=True, exist_ok=True)

    def embed(self, texts: list[str]) -> list[list[float]]:
        keys = [content_hash(text) for text in texts]
        vectors: dict[int, list[float]] = {}
        missing: list[int] = []
        for i, key in enumerate(keys):
            path = self._dir / f"{key}.json"
            if path.exists():
                vectors[i] = json.loads(path.read_text())
            else:
                missing.append(i)
        if missing:
            fresh = self._inner.embed([texts[i] for i in missing])
            for i, vector in zip(missing, fresh):
                vectors[i] = vector
                (self._dir / f"{keys[i]}.json").write_text(json.dumps(vector))
        return [vectors[i] for i in range(len(texts))]
