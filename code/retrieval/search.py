"""Deterministic lexical search over the corpus index."""

from __future__ import annotations

import math
import re
from collections import Counter

from retrieval.indexer import build_index
from retrieval.models import CorpusChunk, CorpusIndex, SearchHit

_TOKEN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")

_STOPWORDS = frozenset(
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
    }
)


def _tokenize(text: str) -> list[str]:
    tokens = [t for t in _TOKEN.findall(text.lower()) if t not in _STOPWORDS and len(t) > 1]
    return tokens


def _chunk_text(chunk: CorpusChunk) -> str:
    heading_text = " ".join(chunk.headings)
    return f"{chunk.title}\n{heading_text}\n{chunk.body}"


def _matches_filters(chunk: CorpusChunk, filters: dict[str, object] | None) -> bool:
    if not filters:
        return True

    domain = filters.get("domain")
    if domain and domain not in chunk.domain_hints:
        return False

    domains = filters.get("domains")
    if domains:
        domain_set = {str(d) for d in domains}  # type: ignore[union-attr]
        if not domain_set.intersection(chunk.domain_hints):
            return False

    path_prefix = filters.get("path_prefix")
    if path_prefix and not chunk.path.startswith(str(path_prefix)):
        return False

    return True


def search(
    query: str,
    *,
    index: CorpusIndex | None = None,
    filters: dict[str, object] | None = None,
    top_k: int = 8,
) -> list[SearchHit]:
    """
  Rank chunks by deterministic lexical overlap (no embeddings, no network).

  ``filters`` supports: ``domain``, ``domains`` (list), ``path_prefix``.
  """
    if not query.strip():
        return []

    corpus = index or build_index()
    query_terms = _tokenize(query)
    if not query_terms:
        return []

    query_counts = Counter(query_terms)
    hits: list[tuple[float, str, str, CorpusChunk]] = []

    for chunk in corpus.chunks:
        if not _matches_filters(chunk, filters):
            continue

        title_tokens = _tokenize(chunk.title)
        heading_tokens = _tokenize(" ".join(chunk.headings))
        body_tokens = _tokenize(chunk.body)

        score = 0.0
        for tokens, field_weight in (
            (title_tokens, 3.0),
            (heading_tokens, 2.0),
            (body_tokens, 1.0),
        ):
            counts = Counter(tokens)
            for token, tf in counts.items():
                if token in query_counts:
                    # BM25-ish saturation without corpus statistics for determinism.
                    score += field_weight * (1.0 + math.log1p(tf))

        if score <= 0:
            continue

        hits.append((score, chunk.path, chunk.chunk_id, chunk))

    hits.sort(key=lambda item: (-item[0], item[1], item[2]))
    return [
        SearchHit(chunk=chunk, score=round(score, 6), rank=rank + 1)
        for rank, (score, _path, _cid, chunk) in enumerate(hits[:top_k])
    ]
