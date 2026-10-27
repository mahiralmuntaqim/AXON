"""Text embeddings for technique specs and the current state (SEGMENT 3/4).

An :class:`Embedder` turns text into a fixed-length vector. Two implementations ship:

* :class:`HashingEmbedder` — deterministic, dependency-free, offline. Good enough for retrieval
  in tests and reproducible runs; NOT semantically strong.
* :class:`SentenceTransformerEmbedder` — STUB for a real sentence-embedding model.

Construction fails loudly if the embedder is unavailable, rather than storing empty embeddings
(SEGMENT 3 corner case).
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol, Sequence


class Embedder(Protocol):
    dim: int

    def embed(self, text: str) -> list[float]: ...


class EmbeddingUnavailable(RuntimeError):
    """Raised when no embedding backend is available at construction time."""


_TOKEN = re.compile(r"[a-z0-9]+")


class HashingEmbedder(Embedder):
    """Deterministic bag-of-tokens hashing embedder (the "hashing trick"), L2-normalized.

    Each token is hashed into a bucket; buckets form the vector. Same text -> same vector,
    always, with no model download — which is exactly what reproducible offline tests need.
    """

    def __init__(self, dim: int = 384) -> None:
        if dim <= 0:
            raise ValueError("embedding dim must be positive")
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for tok in _TOKEN.findall(text.lower()):
            h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=8).digest(), "big")
            idx = h % self.dim
            sign = 1.0 if (h >> 63) & 1 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0.0:
            return vec
        return [v / norm for v in vec]


class SentenceTransformerEmbedder(Embedder):
    """STUB: wrap a real sentence-embedding model here (inference only)."""

    def __init__(self, model_name: str, dim: int = 384) -> None:
        self.model_name = model_name
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        raise EmbeddingUnavailable(
            "STUB: SentenceTransformerEmbedder is not wired to a model. Install and load a "
            "real embedder, or use HashingEmbedder for offline runs."
        )


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity. Assumes equal length; returns 0 for a zero vector."""
    if len(a) != len(b):
        raise ValueError("vectors must be the same length")
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)
