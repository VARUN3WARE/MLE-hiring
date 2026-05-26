"""Build a deterministic in-memory index over data/**/*.md."""

from __future__ import annotations

import time
from pathlib import Path

from paths import REPO_ROOT
from retrieval.chunker import chunk_document
from retrieval.domain import infer_domain_hints
from retrieval.models import CorpusIndex
from retrieval.parser import parse_markdown_file

DEFAULT_DATA_DIR = REPO_ROOT / "data"


def _iter_markdown_files(data_dir: Path) -> list[Path]:
    files = sorted(data_dir.rglob("*.md"), key=lambda p: p.as_posix())
    return [p for p in files if p.is_file()]


def build_index(data_dir: Path | None = None) -> CorpusIndex:
    """
    Load and chunk all local markdown under ``data/``.

    Returns repo-relative paths only. Skips files that disappear during read.
    """
    root = data_dir or DEFAULT_DATA_DIR
    if not root.is_dir():
        raise FileNotFoundError(f"Corpus directory not found: {root}")

    started = time.perf_counter()
    index = CorpusIndex()
    markdown_files = _iter_markdown_files(root)

    for abs_path in markdown_files:
        rel = abs_path.relative_to(REPO_ROOT)
        if not abs_path.is_file():
            continue
        doc = parse_markdown_file(abs_path, REPO_ROOT)
        hints = infer_domain_hints(
            doc.path,
            breadcrumbs=doc.breadcrumbs,
            title=doc.title,
            body=doc.body,
        )
        chunks = chunk_document(doc, domain_hints=hints)
        index.chunks.extend(chunks)
        index.source_files.append(doc.path)

    index.chunks.sort(key=lambda c: (c.path, c.chunk_id))
    index.source_files.sort()
    index.build_time_ms = (time.perf_counter() - started) * 1000
    return index


def verify_index_paths(index: CorpusIndex) -> list[str]:
    """Return repo-relative paths that do not exist on disk."""
    missing: list[str] = []
    seen: set[str] = set()
    for path in index.source_files:
        if path in seen:
            continue
        seen.add(path)
        if not (REPO_ROOT / path).is_file():
            missing.append(path)
    for chunk in index.chunks:
        if not (REPO_ROOT / chunk.path).is_file():
            missing.append(chunk.path)
    return sorted(set(missing))
