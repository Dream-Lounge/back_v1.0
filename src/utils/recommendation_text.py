from __future__ import annotations

import re
from itertools import pairwise

SPACE_RE = re.compile(r"\s+")
TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def normalize_text(text: str) -> str:
    return SPACE_RE.sub(" ", text.strip().lower())


def keyword_tokens(text: str) -> list[str]:
    tokens = TOKEN_RE.findall(normalize_text(text))
    features: list[str] = []
    for token in tokens:
        features.append(token)
        features.extend(token[index : index + 2] for index in range(max(0, len(token) - 1)))
        features.extend(token[index : index + 3] for index in range(max(0, len(token) - 2)))
    features.extend(f"{left}_{right}" for left, right in pairwise(tokens))
    return features


def split_sentences(text: str) -> list[str]:
    return [part.strip() for part in SENTENCE_SPLIT_RE.split(text) if part.strip()]
