"""Local embedding providers for hybrid retrieval.

The default provider is deterministic and dependency-free so the application remains
reproducible offline. Sentence Transformers is an opt-in provider for richer semantic
retrieval when a local model is installed.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Protocol, Sequence


class EmbeddingProvider(Protocol):
    name: str
    dimension: int

    def embed(self, text: str) -> list[float]: ...


@dataclass(frozen=True)
class HashEmbeddingProvider:
    """A stable local feature-hash embedding suitable as a small-corpus fallback."""

    dimension: int = 384
    name: str = "hash"

    def embed(self, text: str) -> list[float]:
        terms = re.findall(r"[\w][\w'-]{1,}", text.lower())
        features = terms + [f"{left}_{right}" for left, right in zip(terms, terms[1:])]
        vector = [0.0] * self.dimension
        for feature in features:
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=16).digest()
            bucket = int.from_bytes(digest[:8], "little") % self.dimension
            sign = 1.0 if digest[8] & 1 else -1.0
            vector[bucket] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector


class SentenceTransformersProvider:
    name = "sentence-transformers"

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError("Sentence Transformers is not installed. Use SPIDER_EMBEDDING_PROVIDER=hash or install the optional semantic extra.") from exc
        self.model_name = model_name
        self.name = f"sentence-transformers:{model_name}"
        self._model = SentenceTransformer(model_name)
        dimension_getter = getattr(self._model, "get_embedding_dimension", self._model.get_sentence_embedding_dimension)
        self.dimension = int(dimension_getter())

    def embed(self, text: str) -> list[float]:
        values = self._model.encode(text, normalize_embeddings=True, show_progress_bar=False)
        return [float(value) for value in values]


def build_embedding_provider(provider: str = "hash", model: str = "sentence-transformers/all-MiniLM-L6-v2", dimension: int = 384) -> EmbeddingProvider:
    normalized = provider.strip().lower()
    if normalized in {"", "hash", "offline"}:
        return HashEmbeddingProvider(dimension=max(8, min(4096, int(dimension))))
    if normalized in {"sentence-transformers", "sentence_transformers", "sbert"}:
        return SentenceTransformersProvider(model)
    raise ValueError(f"Unknown embedding provider: {provider}")


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    return float(sum(a * b for a, b in zip(left, right)))
