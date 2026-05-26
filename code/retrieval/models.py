"""Data structures for the corpus index."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CorpusChunk:
    """One searchable slice of a corpus document."""

    chunk_id: str
    path: str  # repo-relative, forward slashes (e.g. data/claude/...)
    title: str
    headings: tuple[str, ...]
    body: str
    domain_hints: tuple[str, ...]
    metadata: tuple[tuple[str, str], ...]


@dataclass
class CorpusIndex:
    """In-memory deterministic corpus index."""

    chunks: list[CorpusChunk] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)
    build_time_ms: float = 0.0

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)

    @property
    def file_count(self) -> int:
        return len(self.source_files)


@dataclass(frozen=True)
class SearchHit:
    """Ranked retrieval result."""

    chunk: CorpusChunk
    score: float
    rank: int
