#!/usr/bin/env python3
"""
Representative routing/tool-planning checks on visible tickets.

Selectors are based on stable subject markers (not row numbers) and only verify
high-level routing expectations + tool schema conformance basics.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from paths import DEFAULT_INPUT_CSV
from routing import route_ticket


SELECTORS: tuple[tuple[str, str, str], ...] = (
    # label, subject marker, expected_status
    ("prompt_injection", "System Maintenance Alert", "escalated"),
    ("legal_threat", "LEGAL THREAT — DISCRIMINATION LAWSUIT", "escalated"),
    ("identity_theft", "Identity Theft", "escalated"),
    ("gdpr", "GDPR Data Deletion Demand", "escalated"),
    ("harmless_praise", "URGENT: Billing Discrepancy — Account Compromised", "replied"),
)


def _load_by_subject(subject_marker: str) -> dict[str, str] | None:
    with DEFAULT_INPUT_CSV.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            subj = row.get("Subject") or row.get("subject") or ""
            if subj == subject_marker:
                return {
                    "issue": row.get("Issue") or row.get("issue") or "",
                    "subject": subj,
                    "company": row.get("Company") or row.get("company") or "",
                }
    return None


def main() -> int:
    failures: list[str] = []
    print("=" * 60)
    print("Routing Checks (visible ticket patterns)")
    print("=" * 60)

    for label, subject_marker, expected_status in SELECTORS:
        ticket = _load_by_subject(subject_marker)
        if ticket is None:
            failures.append(f"{label}: ticket with subject {subject_marker!r} not found")
            continue

        decision = route_ticket(**ticket)
        print(f"\n--- {label} ---")
        print(f"status={decision.status} request_type={decision.request_type} risk={decision.risk_level}")
        print(f"product_area={decision.product_area} actions={len(decision.actions)}")
        if decision.status != expected_status:
            failures.append(f"{label}: expected status {expected_status}, got {decision.status}")

        # Basic tool schema expectations (full schema validation is in validate_submission.py)
        try:
            parsed_actions = json.loads(json.dumps(decision.actions))
            if not isinstance(parsed_actions, list):
                failures.append(f"{label}: actions not a list")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{label}: actions JSON serialization failed: {exc!r}")

        # Guardrail: no destructive tools without verify_identity.
        destructive = {"issue_refund", "modify_subscription", "lock_account"}
        planned = [a.get("action") for a in decision.actions if isinstance(a, dict)]
        if any(tool in destructive for tool in planned) and "verify_identity" not in planned:
            failures.append(f"{label}: destructive tool planned without verify_identity")

    print("\n" + "=" * 60)
    if failures:
        print(f"❌ FAIL ({len(failures)}):")
        for f in failures:
            print(f"  • {f}")
        return 1

    print("✅ PASS: routing checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())

