"""Deterministic BM25 search over the corpus index (backward-compatible API)."""

from __future__ import annotations

from retrieval.bm25 import BM25Index
from retrieval.evidence import retrieve_evidence
from retrieval.indexer import build_index
from retrieval.models import CorpusChunk, CorpusIndex, SearchHit
from retrieval.query import build_retrieval_query
from retrieval.ranking import domain_boost, path_penalty, specificity_boost
from retrieval.tokenize import tokenize


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
    Rank chunks with BM25 plus deterministic boosts/penalties.

    ``filters`` supports: ``domain``, ``domains`` (list), ``path_prefix``.
    """
    if not query.strip():
        return []

    corpus = index or build_index()
    bm25_index = BM25Index.from_corpus(corpus)
    retrieval_query = build_retrieval_query(issue=query, subject="", company="")
    if filters and filters.get("domain"):
        retrieval_query = build_retrieval_query(
            issue=query,
            subject="",
            company=str(filters["domain"]),
        )

    query_terms = list(retrieval_query.tokens) or tokenize(query)
    hits: list[tuple[float, str, str, CorpusChunk]] = []

    for idx, chunk in enumerate(corpus.chunks):
        if not _matches_filters(chunk, filters):
            continue
        raw = bm25_index.score_chunk(query_terms, idx)
        if raw <= 0:
            continue
        score = (
            raw
            * path_penalty(chunk.path)
            * domain_boost(chunk, retrieval_query)
            * specificity_boost(chunk)
        )
        hits.append((score, chunk.path, chunk.chunk_id, chunk))

    hits.sort(key=lambda item: (-item[0], item[1], item[2]))
    return [
        SearchHit(chunk=chunk, score=round(score, 6), rank=rank + 1)
        for rank, (score, _path, _cid, chunk) in enumerate(hits[:top_k])
    ]


def search_ticket(
    *,
    issue: str,
    subject: str = "",
    company: str = "",
    index: CorpusIndex | None = None,
    top_k: int = 5,
):
    """Preferred API: full ticket context with evidence grading."""
    return retrieve_evidence(
        issue=issue,
        subject=subject,
        company=company,
        index=index,
        top_k=top_k,
    )
