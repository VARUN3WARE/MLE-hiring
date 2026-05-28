#!/usr/bin/env python3
"""Lightweight checks for the deterministic corpus indexer."""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running as `python code/tests/test_*.py` from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paths import REPO_ROOT  # noqa: E402
from retrieval import build_index, search  # noqa: E402
from retrieval.indexer import verify_index_paths  # noqa: E402


def main() -> int:
    failures: list[str] = []

    index = build_index()
    if index.file_count < 100:
        failures.append(f"expected >=100 markdown files, got {index.file_count}")
    if index.chunk_count < index.file_count:
        failures.append("expected at least one chunk per file on average")
    if index.build_time_ms > 30_000:
        failures.append(f"index build too slow: {index.build_time_ms:.0f}ms")

    missing = verify_index_paths(index)
    if missing:
        failures.append(f"missing paths: {missing[:3]}")

    for chunk in index.chunks[:50]:
        if chunk.path.startswith("/") or "\\" in chunk.path:
            failures.append(f"path not posix repo-relative: {chunk.path}")
            break
        if not (REPO_ROOT / chunk.path).is_file():
            failures.append(f"chunk path missing: {chunk.path}")
            break

    hits = search("how to get support", index=index, filters={"domain": "claude"}, top_k=5)
    if not hits:
        failures.append("expected support query to return hits for claude")
    elif not all("claude" in h.chunk.domain_hints for h in hits):
        failures.append("domain filter allowed non-claude chunks")

    run1 = build_index()
    run2 = build_index()
    if len(run1.chunks) != len(run2.chunks):
        failures.append("non-deterministic chunk count between builds")
    elif run1.chunks[0].chunk_id != run2.chunks[0].chunk_id:
        failures.append("non-deterministic chunk ordering/content")

    if failures:
        print("❌ FAIL:")
        for item in failures:
            print(f"  • {item}")
        return 1

    print("✅ PASS: corpus index checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())

