"""Shared deterministic tokenization for retrieval."""

from __future__ import annotations

import re
from collections import Counter

_TOKEN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")

STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "how",
        "i",
        "in",
        "is",
        "it",
        "my",
        "of",
        "on",
        "or",
        "the",
        "to",
        "was",
        "what",
        "when",
        "where",
        "who",
        "with",
        "your",
        "please",
        "can",
        "could",
        "would",
        "should",
    }
)


def tokenize(text: str) -> list[str]:
    if not text:
        return []
    return [t for t in _TOKEN.findall(text.lower()) if t not in STOPWORDS and len(t) > 1]


def tokenize_weighted_fields(
    *,
    title: str = "",
    headings: str = "",
    body: str = "",
    title_weight: int = 3,
    heading_weight: int = 2,
) -> list[str]:
    """Expand tokens by field weight for BM25 document representation."""
    tokens: list[str] = []
    tokens.extend(tokenize(title) * title_weight)
    tokens.extend(tokenize(headings) * heading_weight)
    tokens.extend(tokenize(body))
    return tokens


def counter_from_tokens(tokens: list[str]) -> Counter[str]:
    return Counter(tokens)
