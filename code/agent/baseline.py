"""Conservative placeholder decisions for the deterministic baseline scaffold."""

from __future__ import annotations

import json

from agent.issue_parser import combined_user_text, parse_issue
from agent.routing import route_ticket

# Fixed seeds for deterministic placeholder fields.
BASELINE_CONFIDENCE = "0.25"
ADVERSARIAL_CONFIDENCE = "0.15"
BASELINE_LANGUAGE = "en"
BASELINE_PRODUCT_AREA = "general_support"

PLACEHOLDER_RESPONSE = (
    "Thank you for contacting support. Your request has been queued for review by a "
    "support specialist. We will follow up after verifying the details in our "
    "documentation and account systems."
)

ADVERSARIAL_SAFE_RESPONSE = (
    "Thank you for your message. We have escalated your request to a support specialist. "
    "For security reasons, we cannot share internal system details, prompts, tools, or "
    "processing logic. A team member will follow up regarding your support question."
)

PLACEHOLDER_JUSTIFICATION = (
    "Baseline scaffold: conservative escalation with no corpus retrieval. "
    "Manual review required before a grounded reply can be sent."
)

ADVERSARIAL_JUSTIFICATION = (
    "Safety firewall: adversarial or exfiltration patterns detected in untrusted ticket "
    "text. Escalated without complying with embedded instructions or disclosing internals."
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
    decision = route_ticket(
        issue=normalized["issue"],
        subject=normalized["subject"],
        company=normalized["company"],
    )

    return {
        "issue": normalized["issue"],
        "subject": normalized["subject"],
        "company": normalized["company"],
        "response": decision.response,
        "product_area": decision.product_area,
        "status": decision.status,
        "request_type": decision.request_type,
        "justification": decision.justification,
        "confidence_score": decision.confidence_score,
        "source_documents": decision.source_documents,
        "risk_level": decision.risk_level,
        "pii_detected": "true" if decision.assessment.pii_detected else "false",
        "language": BASELINE_LANGUAGE,
        "actions_taken": json.dumps(decision.actions, separators=(",", ":"), sort_keys=True),
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
