"""Conservative placeholder decisions for the deterministic baseline scaffold."""

from __future__ import annotations

import json
from typing import Any

from issue_parser import ParsedIssue, combined_user_text, parse_issue
from pii import detect_pii

# Fixed seeds for deterministic placeholder fields.
BASELINE_CONFIDENCE = "0.25"
BASELINE_LANGUAGE = "en"
BASELINE_PRODUCT_AREA = "general_support"

PLACEHOLDER_RESPONSE = (
    "Thank you for contacting support. Your request has been queued for review by a "
    "support specialist. We will follow up after verifying the details in our "
    "documentation and account systems."
)

PLACEHOLDER_JUSTIFICATION = (
    "Baseline scaffold: conservative escalation with no corpus retrieval. "
    "Manual review required before a grounded reply can be sent."
)

INVALID_ISSUE_JUSTIFICATION = (
    "Baseline scaffold: issue conversation could not be parsed safely; "
    "escalating for manual review."
)


def normalize_input_row(row: dict[str, str]) -> dict[str, str]:
    """Map CSV headers to canonical lowercase keys."""
    lowered = {k.strip().lower(): (v if v is not None else "") for k, v in row.items()}
    return {
        "issue": lowered.get("issue", ""),
        "subject": lowered.get("subject", ""),
        "company": lowered.get("company", ""),
    }


def build_baseline_row(input_row: dict[str, str]) -> dict[str, str]:
    """Produce one output CSV row with safe structural placeholders."""
    normalized = normalize_input_row(input_row)
    parsed = parse_issue(normalized["issue"])
    body_text = combined_user_text(parsed)
    full_text = "\n".join(
        part for part in (normalized["subject"], body_text) if part
    )
    pii_found = detect_pii(full_text)

    if parsed.parse_error:
        request_type = "invalid"
        status = "escalated"
        justification = INVALID_ISSUE_JUSTIFICATION
        risk_level = "medium"
    else:
        request_type = "product_issue"
        status = "escalated"
        justification = PLACEHOLDER_JUSTIFICATION
        risk_level = "high" if pii_found else "medium"

    actions = _default_actions(status)
    product_area = _product_area_for_company(normalized["company"])

    return {
        "issue": normalized["issue"],
        "subject": normalized["subject"],
        "company": normalized["company"],
        "response": PLACEHOLDER_RESPONSE,
        "product_area": product_area,
        "status": status,
        "request_type": request_type,
        "justification": justification,
        "confidence_score": BASELINE_CONFIDENCE,
        "source_documents": "",
        "risk_level": risk_level,
        "pii_detected": "true" if pii_found else "false",
        "language": BASELINE_LANGUAGE,
        "actions_taken": json.dumps(actions, separators=(",", ":"), sort_keys=True),
    }


def _product_area_for_company(company: str) -> str:
    key = (company or "").strip().lower()
    mapping = {
        "devplatform": "devplatform_general",
        "claude": "claude_general",
        "visa": "visa_general",
        "none": BASELINE_PRODUCT_AREA,
    }
    return mapping.get(key, BASELINE_PRODUCT_AREA)


def _default_actions(status: str) -> list[dict[str, Any]]:
    if status == "escalated":
        return [
            {
                "action": "escalate_to_human",
                "parameters": {
                    "priority": "normal",
                    "department": "general",
                    "summary": "Baseline scaffold escalation for manual review.",
                },
            }
        ]
    return []
