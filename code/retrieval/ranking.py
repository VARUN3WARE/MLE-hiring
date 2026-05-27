"""Post-BM25 ranking adjustments: domain boost and document-quality penalties."""

from __future__ import annotations

from pathlib import Path

from retrieval.models import CorpusChunk
from retrieval.query import RetrievalQuery

_INDEX_PAGE_NAMES = frozenset({"index.md", "support.md"})
_LOW_QUALITY_SEGMENTS = (
    "deprecated",
    "deprecation",
    "changelog",
    "uncategorized",
    "comprehensive-history",
    "primer",
    "hackerrank-subscription-management",
)


def path_penalty(path: str) -> float:
    """Penalize broad index pages and low-trust doc types."""
    name = Path(path).name.lower()
    if name in _INDEX_PAGE_NAMES:
        return 0.35

    low_path = path.lower()
    factor = 1.0
    for segment in _LOW_QUALITY_SEGMENTS:
        if segment in low_path:
            factor = min(factor, 0.6)
    if "changelog" in low_path or "comprehensive-history" in low_path:
        factor = min(factor, 0.55)
    return factor


def domain_boost(chunk: CorpusChunk, query: RetrievalQuery) -> float:
    """
    Boost chunks aligned with text-inferred domains; soften misleading company hints.
    """
    if not chunk.domain_hints:
        return 1.0

    boost = 1.0
    text_domains = {d for d, _score in query.text_domain_scores}
    company = query.company_domain

    if text_domains:
        if text_domains.intersection(chunk.domain_hints):
            boost = max(boost, 1.2)
        elif company and company in chunk.domain_hints and company not in text_domains:
            # Company field points here but ticket text does not — likely misleading company.
            boost = min(boost, 0.75)
        elif company and company not in chunk.domain_hints and text_domains:
            boost = min(boost, 0.85)

    if company and company in chunk.domain_hints:
        boost *= 1.08

    if text_domains and not text_domains.intersection(chunk.domain_hints):
        # Cross-domain doc when text is confident about another domain.
        if max((s for _, s in query.text_domain_scores), default=0) >= 2:
            boost *= 0.7

    return boost


def specificity_boost(chunk: CorpusChunk) -> float:
    """Prefer article pages over shallow section stubs."""
    parts = Path(chunk.path).parts
    if len(parts) >= 4 and parts[-1] not in _INDEX_PAGE_NAMES:
        return 1.05
    return 1.0
