"""Conservative placeholder decisions for the deterministic baseline scaffold."""

from __future__ import annotations

import json
from typing import Any

from issue_parser import combined_user_text, parse_issue
from retrieval.evidence import retrieve_evidence, source_document_paths
from safety import classify_ticket
from safety.models import SafetyAssessment

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
    parsed = parse_issue(normalized["issue"])
    body_text = combined_user_text(parsed)
    full_text = "\n".join(
        part for part in (normalized["subject"], body_text) if part
    )

    # Safety firewall runs before any future retrieval / generation step.
    assessment = classify_ticket(full_text)

    if parsed.parse_error:
        request_type = "invalid"
        status = "escalated"
        justification = INVALID_ISSUE_JUSTIFICATION
        response = PLACEHOLDER_RESPONSE
        confidence = BASELINE_CONFIDENCE
    elif assessment.is_adversarial:
        request_type = "invalid"
        status = "escalated"
        justification = ADVERSARIAL_JUSTIFICATION
        response = ADVERSARIAL_SAFE_RESPONSE
        confidence = ADVERSARIAL_CONFIDENCE
    else:
        request_type = "product_issue"
        status = "escalated"
        justification = PLACEHOLDER_JUSTIFICATION
        response = PLACEHOLDER_RESPONSE
        confidence = BASELINE_CONFIDENCE

    risk_level = assessment.recommended_risk_level
    actions = _default_actions(status, assessment)
    product_area = _product_area_for_company(normalized["company"])

    source_documents = ""
    if not parsed.parse_error and not assessment.is_adversarial:
        retrieval = retrieve_evidence(
            issue=normalized["issue"],
            subject=normalized["subject"],
            company=normalized["company"],
        )
        if retrieval.overall_grade in ("strong", "weak"):
            source_documents = source_document_paths(retrieval)

    return {
        "issue": normalized["issue"],
        "subject": normalized["subject"],
        "company": normalized["company"],
        "response": response,
        "product_area": product_area,
        "status": status,
        "request_type": request_type,
        "justification": justification,
        "confidence_score": confidence,
        "source_documents": source_documents,
        "risk_level": risk_level,
        "pii_detected": "true" if assessment.pii_detected else "false",
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


def _default_actions(status: str, assessment: SafetyAssessment) -> list[dict[str, Any]]:
    if status != "escalated":
        return []

    department = "security" if assessment.is_adversarial else "general"
    priority = "urgent" if assessment.recommended_risk_level == "critical" else "high"
    if assessment.is_adversarial and priority != "urgent":
        priority = "high"

    summary = (
        "Adversarial or high-risk ticket flagged by safety firewall."
        if assessment.is_adversarial
        else "Baseline scaffold escalation for manual review."
    )
    return [
        {
            "action": "escalate_to_human",
            "parameters": {
                "priority": priority,
                "department": department,
                "summary": summary,
            },
        }
    ]
