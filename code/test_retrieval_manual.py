#!/usr/bin/env python3
"""
Manual retrieval checks on visible ticket patterns (no row-number hardcoding).

Verifies returned source paths exist on disk.
"""

from __future__ import annotations

import csv
import sys
from collections.abc import Callable
from pathlib import Path

from paths import DEFAULT_INPUT_CSV, REPO_ROOT
from retrieval import build_index, retrieve_evidence, verify_index_paths

# Select tickets by stable subject/content markers, not row indices.
TICKET_SELECTORS: tuple[
    tuple[str, Callable[[dict[str, str]], bool], str | None],
    ...,
] = (
    ("claude_workspace_access", lambda r: (r.get("Subject") or "") == "Claude access lost", "strong"),
    (
        "visa_merchant_refund",
        lambda r: (r.get("Subject") or "") == "Help" and "Visa" in (r.get("Company") or ""),
        "strong",
    ),
    ("devplatform_test_dispute", lambda r: "Test Score Dispute" in (r.get("Subject") or ""), "strong"),
    ("prompt_injection_override", lambda r: "System Maintenance Alert" in (r.get("Subject") or ""), "insufficient"),
    ("gdpr_deletion", lambda r: "GDPR Data Deletion Demand" in (r.get("Subject") or ""), "strong"),
)


def _normalize_row(row: dict[str, str]) -> dict[str, str]:
    return {
        "issue": row.get("issue") or row.get("Issue") or "",
        "subject": row.get("subject") or row.get("Subject") or "",
        "company": row.get("company") or row.get("Company") or "",
    }


def _load_ticket(selector: Callable[[dict[str, str]], bool]) -> dict[str, str] | None:
    with DEFAULT_INPUT_CSV.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if selector(row):
                return _normalize_row(row)
    return None


def main() -> int:
    index = build_index()
    missing = verify_index_paths(index)
    if missing:
        print(f"❌ Index missing paths: {missing[:3]}")
        return 1

    failures: list[str] = []
    print("=" * 60)
    print("Retrieval Manual Checks (visible ticket patterns)")
    print("=" * 60)

    for label, selector, expected_grade in TICKET_SELECTORS:
        ticket = _load_ticket(selector)
        if ticket is None:
            failures.append(f"{label}: ticket not found in CSV")
            continue

        result = retrieve_evidence(
            issue=ticket["issue"],
            subject=ticket["subject"],
            company=ticket["company"],
            index=index,
            top_k=3,
        )
        print(f"\n--- {label} ---")
        print(f"company={ticket['company']!r} grade={result.overall_grade}")
        print(f"text_domains={result.query.text_domain_scores}")
        if expected_grade and result.overall_grade != expected_grade:
            failures.append(
                f"{label}: expected grade {expected_grade}, got {result.overall_grade}"
            )
        if not result.items:
            print("  (no evidence items)")
            continue

        for item in result.items:
            exists = (REPO_ROOT / item.path).is_file()
            flag = "ok" if exists else "MISSING"
            print(f"  [{flag}] score={item.score} path={item.path}")
            print(f"       title={item.title[:70]!r}")
            if not exists:
                failures.append(f"{label}: missing path {item.path}")
            if Path(item.path).name == "index.md" and result.overall_grade == "strong":
                failures.append(f"{label}: strong grade on index.md only")

    print("\n" + "=" * 60)
    if failures:
        print(f"❌ FAIL ({len(failures)}):")
        for msg in failures:
            print(f"  • {msg}")
        return 1

    print("✅ PASS: manual retrieval checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
