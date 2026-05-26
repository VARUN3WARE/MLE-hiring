"""Deterministic local corpus indexing and search."""

from retrieval.evidence import (
    EvidenceGrade,
    EvidenceItem,
    RetrievalResult,
    retrieve_evidence,
    source_document_paths,
)
from retrieval.indexer import build_index, verify_index_paths
from retrieval.models import CorpusChunk, CorpusIndex, SearchHit
from retrieval.search import search, search_ticket

__all__ = [
    "CorpusChunk",
    "CorpusIndex",
    "EvidenceGrade",
    "EvidenceItem",
    "RetrievalResult",
    "SearchHit",
    "build_index",
    "retrieve_evidence",
    "search",
    "search_ticket",
    "source_document_paths",
    "verify_index_paths",
]
