"""Deterministic document chunking for long markdown files."""

from __future__ import annotations

import hashlib
import re

from retrieval.models import CorpusChunk
from retrieval.parser import ParsedDocument

CHUNK_MAX_CHARS = 1200
CHUNK_OVERLAP_CHARS = 150

_SECTION_SPLIT = re.compile(r"(?=^#{1,3}\s+)", re.MULTILINE)
_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")


def _chunk_id(path: str, ordinal: int) -> str:
    digest = hashlib.sha256(f"{path}:{ordinal}".encode("utf-8")).hexdigest()
    return digest[:16]


def _split_oversized(text: str) -> list[str]:
    if len(text) <= CHUNK_MAX_CHARS:
        return [text] if text.strip() else []

    parts: list[str] = []
    paragraphs = [p.strip() for p in _PARAGRAPH_SPLIT.split(text) if p.strip()]
    buffer = ""
    for paragraph in paragraphs:
        candidate = f"{buffer}\n\n{paragraph}".strip() if buffer else paragraph
        if len(candidate) <= CHUNK_MAX_CHARS:
            buffer = candidate
            continue
        if buffer:
            parts.append(buffer)
        if len(paragraph) <= CHUNK_MAX_CHARS:
            buffer = paragraph
        else:
            start = 0
            while start < len(paragraph):
                end = min(start + CHUNK_MAX_CHARS, len(paragraph))
                parts.append(paragraph[start:end])
                if end >= len(paragraph):
                    break
                start = end - CHUNK_OVERLAP_CHARS
            buffer = ""
    if buffer:
        parts.append(buffer)
    return parts


def chunk_document(
    doc: ParsedDocument,
    *,
    domain_hints: tuple[str, ...],
) -> list[CorpusChunk]:
    """Split a parsed document into deterministic chunks."""
    if not doc.body.strip():
        return []

    sections = [s.strip() for s in _SECTION_SPLIT.split(doc.body) if s.strip()]
    if not sections:
        sections = [doc.body]

    raw_chunks: list[str] = []
    for section in sections:
        raw_chunks.extend(_split_oversized(section))

    if not raw_chunks:
        return []

    chunks: list[CorpusChunk] = []
    for ordinal, body in enumerate(raw_chunks):
        section_heading = ""
        first_line = body.splitlines()[0] if body else ""
        if first_line.startswith("#"):
            section_heading = first_line.lstrip("#").strip()

        headings = doc.headings
        if section_heading and section_heading not in headings:
            headings = headings + (section_heading,)

        chunks.append(
            CorpusChunk(
                chunk_id=_chunk_id(doc.path, ordinal),
                path=doc.path,
                title=doc.title,
                headings=headings,
                body=body.strip(),
                domain_hints=domain_hints,
                metadata=doc.frontmatter,
            )
        )
    return chunks
