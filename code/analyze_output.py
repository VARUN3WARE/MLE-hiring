#!/usr/bin/env python3
"""Summarize agent output by reusable failure categories (no row hardcoding)."""

from __future__ import annotations

import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

from issue_parser import combined_user_text, parse_issue
from paths import DEFAULT_INPUT_CSV, DEFAULT_OUTPUT_CSV
from retrieval.evidence import retrieve_evidence
from routing import route_ticket
from safety import classify_ticket
from ticket_categories import (
    is_harmless_out_of_scope,
    is_hub_path,
    is_multilingual,
    requires_account_action_escalation,
)


def main() -> int:
    categories: dict[str, list[str]] = defaultdict(list)

    with DEFAULT_INPUT_CSV.open(encoding="utf-8") as handle:
        inputs = list(csv.DictReader(handle))

    with DEFAULT_OUTPUT_CSV.open(encoding="utf-8") as handle:
        outputs = list(csv.DictReader(handle))

    for row_in, row_out in zip(inputs, outputs):
        issue = row_in.get("Issue") or row_in.get("issue") or ""
        subject = row_in.get("Subject") or row_in.get("subject") or ""
        company = row_in.get("Company") or row_in.get("company") or ""
        body = combined_user_text(parse_issue(issue))
        text = "\n".join(p for p in (subject, body) if p)
        safety = classify_ticket(body or text)
        retrieval = retrieve_evidence(issue=issue, subject=subject, company=company)
        decision = route_ticket(issue=issue, subject=subject, company=company)

        cats: list[str] = []
        if safety.is_adversarial:
            cats.append("adversarial")
        if safety.pii_detected:
            cats.append("pii")
        if requires_account_action_escalation(text):
            cats.append("financial/account action")
        if any(s.startswith("risk:") for s in safety.risk_signals):
            cats.append("legal/security/privacy")
        if is_harmless_out_of_scope(text):
            cats.append("out-of-scope")
        if retrieval.overall_grade in ("weak", "insufficient", "conflicting"):
            cats.append("weak retrieval")
        if is_multilingual(text):
            cats.append("multilingual")
        if not cats:
            cats.append("general")

        label = f"{subject[:40]!r} -> {decision.status}"
        for cat in cats:
            categories[cat].append(label)

    print("=" * 60)
    print("Output analysis by category")
    print("=" * 60)
    print("Status distribution:", Counter(r["status"] for r in outputs))
    hub_cited = sum(
        1
        for r in outputs
        if r["status"] == "replied" and "support.md" in (r.get("source_documents") or "")
    )
    print("Replied rows citing support.md hub:", hub_cited)

    for cat in sorted(categories):
        print(f"\n{cat} ({len(categories[cat])})")
        for item in categories[cat][:5]:
            print(f"  - {item}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
