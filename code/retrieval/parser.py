"""Parse local markdown corpus files (frontmatter, title, headings, body)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class ParsedDocument:
    path: str
    title: str
    headings: tuple[str, ...]
    body: str
    frontmatter: tuple[tuple[str, str], ...]
    breadcrumbs: tuple[str, ...]


def parse_frontmatter(raw: str) -> tuple[dict[str, str], str]:
    """Parse simple YAML-like frontmatter between --- markers."""
    if not raw.startswith("---"):
        return {}, raw

    end = raw.find("\n---", 3)
    if end == -1:
        return {}, raw

    block = raw[3:end].strip()
    body = raw[end + 4 :].lstrip("\n")
    metadata: dict[str, str] = {}
    current_key: str | None = None

    for line in block.splitlines():
        if not line.strip():
            continue
        if line.startswith("  - ") and current_key == "breadcrumbs":
            item = line[4:].strip().strip('"').strip("'")
            metadata.setdefault("breadcrumbs", "")
            metadata["breadcrumbs"] += ("|" if metadata["breadcrumbs"] else "") + item
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        metadata[key] = value
        current_key = key

    return metadata, body


def extract_title(frontmatter: dict[str, str], body: str) -> str:
    if frontmatter.get("title"):
        return frontmatter["title"]
    match = _HEADING.search(body)
    if match:
        return match.group(2).strip()
    return ""


def extract_headings(body: str) -> tuple[str, ...]:
    headings: list[str] = []
    for match in _HEADING.finditer(body):
        headings.append(match.group(2).strip())
    return tuple(headings)


def parse_markdown_file(abs_path: Path, repo_root: Path) -> ParsedDocument:
    raw = abs_path.read_text(encoding="utf-8", errors="replace")
    frontmatter, body = parse_frontmatter(raw)
    breadcrumbs_raw = frontmatter.get("breadcrumbs", "")
    breadcrumbs = tuple(b for b in breadcrumbs_raw.split("|") if b) if breadcrumbs_raw else ()

    fm_tuple = tuple(sorted((k, v) for k, v in frontmatter.items() if k != "breadcrumbs"))
    rel_path = abs_path.relative_to(repo_root).as_posix()

    return ParsedDocument(
        path=rel_path,
        title=extract_title(frontmatter, body),
        headings=extract_headings(body),
        body=body.strip(),
        frontmatter=fm_tuple,
        breadcrumbs=breadcrumbs,
    )
