from __future__ import annotations

import hashlib
import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from threading import Lock
from typing import Protocol

from src.utils.recommendation_text import keyword_tokens

logger = logging.getLogger(__name__)


class Embedder(Protocol):
    model_name: str
    backend: str

    def encode(self, texts: Sequence[str], *, role: str = "passage") -> list[list[float]]: ...


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else vector


@dataclass
class HashingEmbedder:
    model_name: str = "fallback"
    backend: str = "hashing"
    dim: int = 384

    def encode(self, texts: Sequence[str], *, role: str = "passage") -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vector = [0.0] * self.dim
            for token in keyword_tokens(text):
                digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
                index = int.from_bytes(digest[:4], "little") % self.dim
                vector[index] += 1.0 if digest[4] % 2 == 0 else -1.0
            vectors.append(_normalize(vector))
        return vectors


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str, cache_dir: str | None = None) -> None:
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self.backend = "sentence-transformers"
        kwargs = {"cache_folder": cache_dir} if cache_dir else {}
        try:
            self._model = SentenceTransformer(model_name, **kwargs)
        except ValueError as exc:
            if "trust_remote_code=True" not in str(exc):
                raise
            self._model = SentenceTransformer(model_name, trust_remote_code=True, **kwargs)
        # Club descriptions can be long. A bounded sequence and small batch
        # avoid a large first-request memory spike on CPU-only deployments.
        self._model.max_seq_length = min(self._model.max_seq_length, 256)
        # PyTorch/SentenceTransformer inference may stall when the same model
        # instance is entered concurrently from FastAPI worker threads.
        self._encode_lock = Lock()

    def encode(self, texts: Sequence[str], *, role: str = "passage") -> list[list[float]]:
        values = list(texts)
        if "e5" in self.model_name.lower():
            prefix = "query: " if role == "query" else "passage: "
            values = [f"{prefix}{text}" for text in values]
        with self._encode_lock:
            embeddings = self._model.encode(
                values,
                batch_size=8,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        return [list(vector) for vector in embeddings]


@lru_cache(maxsize=4)
def build_embedder(model_name: str, cache_dir: str | None = None) -> Embedder:
    if model_name == "fallback":
        return HashingEmbedder()
    try:
        return SentenceTransformerEmbedder(model_name, cache_dir)
    except Exception:
        logger.exception("Recommendation model failed to load; using hashing fallback")
        return HashingEmbedder()


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(a * b for a, b in zip(left, right)) if left and right else 0.0
