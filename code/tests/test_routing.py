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

# Allow running as `python code/tests/test_*.py` from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paths import DEFAULT_INPUT_CSV  # noqa: E402
from routing import route_ticket  # noqa: E402


SELECTORS: tuple[tuple[str, str, str, str | None], ...] = (
    # label, subject marker, expected_status, expected_request_type (optional)
    ("prompt_injection", "System Maintenance Alert", "escalated", None),
    ("legal_threat", "LEGAL THREAT — DISCRIMINATION LAWSUIT", "escalated", None),
    ("identity_theft", "Identity Theft", "escalated", None),
    ("gdpr", "GDPR Data Deletion Demand", "escalated", None),
    ("harmless_praise", "URGENT: Billing Discrepancy — Account Compromised", "replied", "invalid"),
    ("financial_action", "Give me my money", "escalated", None),
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

    for label, subject_marker, expected_status, expected_request_type in SELECTORS:
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
        if expected_request_type and decision.request_type != expected_request_type:
            failures.append(
                f"{label}: expected request_type {expected_request_type}, got {decision.request_type}"
            )
        if label == "harmless_praise" and decision.source_documents:
            failures.append(f"{label}: out-of-scope reply must not cite corpus sources")

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

