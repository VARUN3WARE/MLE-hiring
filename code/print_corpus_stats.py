#!/usr/bin/env python3
"""Print corpus index statistics and verify indexed paths exist."""

from __future__ import annotations

import sys
from collections import Counter

from retrieval import build_index, search
from retrieval.indexer import verify_index_paths


def main() -> int:
    index = build_index()
    missing = verify_index_paths(index)

    domain_counts: Counter[str] = Counter()
    for chunk in index.chunks:
        for hint in chunk.domain_hints:
            domain_counts[hint] += 1

    print("=" * 60)
    print("Corpus Index Statistics")
    print("=" * 60)
    print(f"Markdown files indexed: {index.file_count}")
    print(f"Total chunks:           {index.chunk_count}")
    print(f"Build time (ms):        {index.build_time_ms:.1f}")
    print(f"Avg chunks / file:      {index.chunk_count / max(index.file_count, 1):.2f}")
    print("\nChunks by domain hint (multi-label allowed):")
    for domain, count in sorted(domain_counts.items()):
        print(f"  {domain:15} {count}")

    sample = search("refund unauthorized transaction", index=index, filters={"domain": "visa"}, top_k=3)
    print("\nSample search (visa / refund):")
    for hit in sample:
        print(f"  #{hit.rank} score={hit.score} path={hit.chunk.path}")

    if missing:
        print(f"\n❌ Missing paths ({len(missing)}):")
        for path in missing[:10]:
            print(f"   • {path}")
        return 1

    print("\n✅ All indexed paths exist on disk.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
