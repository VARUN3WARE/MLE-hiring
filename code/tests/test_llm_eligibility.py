#!/usr/bin/env python3
"""Show which visible tickets would be eligible for gated LLM polishing.

Does not call an LLM. Selectors are by stable subject markers (no row numbers).
"""

from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

# Allow running as `python code/tests/test_*.py` from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from issue_parser import combined_user_text, parse_issue  # noqa: E402
from llm.eligibility import LLMRowContext, is_llm_eligible  # noqa: E402
from retrieval.evidence import retrieve_evidence  # noqa: E402
from routing import route_ticket  # noqa: E402


CSV_PATH = Path("support_tickets/support_tickets.csv")

SELECT_SUBJECTS: tuple[str, ...] = (
    # Should be blocked
    "System Maintenance Alert",
    "Identity Theft",
    "GDPR Data Deletion Demand",
    "Give me my money",
    "Links only — please read",
    # Potentially eligible (low-risk FAQ-ish)
    "Why are my mock interviews not working",
)


def _normalize(row: dict[str, str]) -> dict[str, str]:
    return {
        "issue": row.get("Issue") or row.get("issue") or "",
        "subject": row.get("Subject") or row.get("subject") or "",
        "company": row.get("Company") or row.get("company") or "",
    }


def main() -> int:
    with CSV_PATH.open(newline="", encoding="utf-8") as handle:
        rows = [_normalize(r) for r in csv.DictReader(handle)]

    print("=" * 60)
    print("LLM Eligibility (gated, no LLM calls)")
    print("=" * 60)

    counts = Counter()
    eligible_total = 0

    for row in rows:
        parsed = parse_issue(row["issue"])
        body = combined_user_text(parsed)
        ticket_text = "\n".join(p for p in (row["subject"], body) if p)

        decision = route_ticket(**row)
        retrieval = retrieve_evidence(
            issue=row["issue"], subject=row["subject"], company=row["company"]
        )
        ctx = LLMRowContext(decision=decision, retrieval=retrieval, ticket_text=ticket_text)
        eligible, reasons = is_llm_eligible(ctx)
        eligible_total += int(eligible)

        for r in reasons:
            counts[r] += 1

    print(f"Eligible rows: {eligible_total}/{len(rows)}")
    print("Top block reasons:")
    for reason, n in counts.most_common(12):
        print(f"  - {reason}: {n}")

    print("\nSelected examples:")
    wanted = set(SELECT_SUBJECTS)
    for row in rows:
        if row["subject"] not in wanted:
            continue
        parsed = parse_issue(row["issue"])
        body = combined_user_text(parsed)
        ticket_text = "\n".join(p for p in (row["subject"], body) if p)
        decision = route_ticket(**row)
        retrieval = retrieve_evidence(
            issue=row["issue"], subject=row["subject"], company=row["company"]
        )
        ctx = LLMRowContext(decision=decision, retrieval=retrieval, ticket_text=ticket_text)
        eligible, reasons = is_llm_eligible(ctx)
        print(
            f"\n- subject={row['subject']!r} company={row['company']!r} "
            f"status={decision.status} eligible={eligible}"
        )
        print(f"  reasons={reasons}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

