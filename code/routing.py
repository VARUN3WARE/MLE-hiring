"""Deterministic routing + internal tool planning for baseline agent.

This module maps a ticket to:
- output fields (status, request_type, risk_level, product_area)
- safe tool plan (actions_taken) that conforms to internal_tools.json

No network calls; ticket text is treated as untrusted data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from issue_parser import combined_user_text, parse_issue
from retrieval.evidence import RetrievalResult, retrieve_evidence
from response import compose_escalation, compose_out_of_scope, compose_reply
from ticket_categories import (
    is_harmless_out_of_scope,
    is_hub_path,
    requires_account_action_escalation,
)
from safety import classify_ticket
from safety.models import SafetyAssessment


VALID_STATUS = {"replied", "escalated"}
VALID_REQUEST_TYPE = {"product_issue", "feature_request", "bug", "invalid"}
VALID_RISK_LEVEL = {"low", "medium", "high", "critical"}

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3}[-.\s]?\d{3,4}\b")


@dataclass(frozen=True)
class RouteDecision:
    status: str
    request_type: str
    risk_level: str
    product_area: str
    response: str
    justification: str
    confidence_score: str
    source_documents: str
    actions: list[dict[str, Any]]
    assessment: SafetyAssessment


def route_ticket(*, issue: str, subject: str, company: str) -> RouteDecision:
    """Route one ticket deterministically."""
    parsed = parse_issue(issue)
    body = combined_user_text(parsed)
    # Safety classification should not over-trust `subject` (it may be misleading).
    raw_for_safety = "\n".join(p for p in (body, parsed.raw if parsed.parse_error else "") if p)
    assessment = classify_ticket(raw_for_safety)

    if parsed.parse_error:
        return _route_invalid_issue(subject=subject, company=company, assessment=assessment)

    # High-risk topics: always escalate.
    if _is_high_risk(assessment):
        return _route_escalate(
            subject=subject,
            company=company,
            assessment=assessment,
            reason="High-risk safety signals detected (legal/security/privacy/account compromise).",
            department=_department_for_signals(assessment),
            priority=_priority_for_risk(assessment.recommended_risk_level),
        )

    # Adversarial / exfiltration: escalate security.
    if assessment.is_adversarial:
        return _route_escalate(
            subject=subject,
            company=company,
            assessment=assessment,
            reason="Adversarial or internal-disclosure patterns detected; refusing embedded instructions.",
            department="security",
            priority="high",
            force_invalid=True,
        )

    ticket_text = "\n".join(p for p in (subject, body) if p)
    request_type = _infer_request_type(ticket_text)
    product_area = _infer_product_area(ticket_text, company)

    if is_harmless_out_of_scope(ticket_text):
        composed = compose_out_of_scope(assessment=assessment)
        return RouteDecision(
            status="replied",
            request_type="invalid",
            risk_level="low",
            product_area=product_area,
            response=composed.response,
            justification=composed.justification,
            confidence_score=composed.confidence_score,
            source_documents="",
            actions=[],
            assessment=assessment,
        )

    # Tool planning for non-destructive account flows (reset password) only when safe and parameters exist.
    tool_plan = plan_tools(text=ticket_text, assessment=assessment)

    # Evidence retrieval (citation-safe). If insufficient, route conservative escalation.
    retrieval = retrieve_evidence(issue=issue, subject=subject, company=company)

    if requires_account_action_escalation(ticket_text):
        return _route_escalate(
            subject=subject,
            company=company,
            assessment=assessment,
            reason="Account-level or billing action requested; escalating for verification and specialist review.",
            department="billing",
            priority="high",
            request_type=request_type,
            product_area=product_area,
            retrieval=retrieval,
            missing_prereqs=bool(tool_plan),
        )

    if _should_reply(assessment, retrieval, tool_plan):
        composed = compose_reply(retrieval=retrieval, assessment=assessment)
        return RouteDecision(
            status="replied",
            request_type=request_type,
            risk_level=assessment.recommended_risk_level if assessment.recommended_risk_level in VALID_RISK_LEVEL else "low",
            product_area=product_area,
            response=composed.response,
            justification=composed.justification,
            confidence_score=composed.confidence_score,
            source_documents=composed.source_documents,
            actions=tool_plan,
            assessment=assessment,
        )

    return _route_escalate(
        subject=subject,
        company=company,
        assessment=assessment,
        reason="Insufficient grounded evidence to reply safely; escalating for review.",
        department=_department_for_company(company),
        priority="normal",
        request_type=request_type,
        product_area=product_area,
        retrieval=retrieval,
    )


def plan_tools(*, text: str, assessment: SafetyAssessment) -> list[dict[str, Any]]:
    """
    Plan internal tool calls deterministically.

    Guardrails:
    - Never output destructive actions (refund/modify) without verify_identity.
    - Only output tools when required parameters can be extracted.
    """
    if assessment.is_adversarial:
        return []

    low = (text or "").lower()
    actions: list[dict[str, Any]] = []

    email = _first_match(_EMAIL, text)
    phone = _first_match(_PHONE, text)

    # Account compromise / identity theft -> lock if identifier present, else escalate in routing layer.
    if any(s in assessment.risk_signals for s in ("risk:account_compromise", "risk:identity_theft")):
        identifier = email or _extract_account_identifier(text)
        if identifier:
            actions.append(
                {
                    "action": "lock_account",
                    "parameters": {"user_identifier": identifier, "lock_reason": "suspected_fraud"},
                }
            )
        return actions

    # Password reset: only when explicitly asked and safe.
    if ("reset password" in low or "forgot password" in low) and email:
        actions.append({"action": "reset_password", "parameters": {"user_email": email}})
        return actions

    # Refund / subscription modifications: require verify_identity + full required params.
    if any(k in low for k in ("refund", "chargeback", "cancel subscription", "upgrade plan", "downgrade plan")):
        target, method = _verification_target(email=email, phone=phone)
        if target and method:
            actions.append({"action": "verify_identity", "parameters": {"method": method, "target": target}})
        # Do not attempt issue_refund/modify_subscription unless all required fields are present.
        return actions

    return actions


def _route_invalid_issue(*, subject: str, company: str, assessment: SafetyAssessment) -> RouteDecision:
    return _route_escalate(
        subject=subject,
        company=company,
        assessment=assessment,
        reason="Issue conversation could not be parsed as valid JSON array; escalating for manual review.",
        department="general",
        priority="normal",
        force_invalid=True,
        retrieval=None,
    )


def _route_escalate(
    *,
    subject: str,
    company: str,
    assessment: SafetyAssessment,
    reason: str,
    department: str,
    priority: str,
    force_invalid: bool = False,
    request_type: str | None = None,
    product_area: str | None = None,
    source_documents: str = "",
    retrieval: RetrievalResult | None = None,
    missing_prereqs: bool = False,
) -> RouteDecision:
    if force_invalid:
        req_type = "invalid"
    else:
        req_type = request_type or "product_issue"

    prod_area = product_area or _infer_product_area(subject, company)
    status = "escalated"

    if status not in VALID_STATUS:
        status = "escalated"
    if req_type not in VALID_REQUEST_TYPE:
        req_type = "invalid"

    risk = assessment.recommended_risk_level if assessment.recommended_risk_level in VALID_RISK_LEVEL else "medium"
    composed = compose_escalation(
        assessment=assessment,
        reason=reason,
        retrieval=retrieval,
        has_tool_actions=True,
        missing_prereqs=missing_prereqs,
    )
    actions = [
        {
            "action": "escalate_to_human",
            "parameters": {"priority": priority, "department": department, "summary": reason[:240]},
        }
    ]
    return RouteDecision(
        status=status,
        request_type=req_type,
        risk_level=risk,
        product_area=prod_area,
        response=composed.response,
        justification=composed.justification,
        confidence_score=composed.confidence_score,
        source_documents=composed.source_documents or source_documents,
        actions=actions,
        assessment=assessment,
    )


def _is_high_risk(assessment: SafetyAssessment) -> bool:
    high_signals = {
        "risk:legal_threat",
        "risk:identity_theft",
        "risk:account_compromise",
        "risk:privacy_breach",
        "risk:security_vulnerability",
        "risk:fraud",
    }
    return bool(high_signals.intersection(assessment.risk_signals)) or assessment.recommended_risk_level in ("high", "critical")


def _department_for_signals(assessment: SafetyAssessment) -> str:
    signals = set(assessment.risk_signals)
    if "risk:legal_threat" in signals or "risk:privacy_breach" in signals:
        return "legal"
    if "risk:security_vulnerability" in signals or "risk:account_compromise" in signals:
        return "security"
    if "risk:fraud" in signals:
        return "billing"
    return "general"


def _priority_for_risk(risk_level: str) -> str:
    return "urgent" if risk_level == "critical" else "high"


def _department_for_company(company: str) -> str:
    key = (company or "").strip().lower()
    if key == "visa":
        return "billing"
    if key == "devplatform":
        return "technical"
    if key == "claude":
        return "general"
    return "general"


def _infer_request_type(text: str) -> str:
    low = (text or "").lower()
    if any(k in low for k in ("feature request", "would be great if", "please add", "add a feature")):
        return "feature_request"
    if any(k in low for k in ("bug", "error", "doesn't work", "not working", "crash", "blocked", "unable")):
        return "bug"
    return "product_issue"


def _infer_product_area(text: str, company: str) -> str:
    low = (text or "").lower()
    if any(k in low for k in ("billing", "refund", "invoice", "payment", "subscription", "charge")):
        return "billing"
    if any(k in low for k in ("login", "password", "access", "seat", "workspace", "sso", "scim")):
        return "account_access"
    if any(k in low for k in ("test", "assessment", "codescreen", "codepair", "challenge", "submission")):
        return "assessment"
    if any(k in low for k in ("privacy", "gdpr", "delete", "erasure", "data retention", "export")):
        return "privacy"
    if any(k in low for k in ("fraud", "unauthorized", "stolen", "identity theft", "cve", "vulnerability", "breach")):
        return "security"
    # Fallback: domain-based generic
    c = (company or "").strip().lower()
    if c == "visa":
        return "payments"
    if c == "devplatform":
        return "platform"
    if c == "claude":
        return "claude_app"
    return "general_support"


def _should_reply(assessment: SafetyAssessment, retrieval: RetrievalResult, tool_plan: list[dict[str, Any]]) -> bool:
    if assessment.pii_detected:
        return False
    if assessment.recommended_risk_level in ("high", "critical"):
        return False
    if retrieval.overall_grade != "strong":
        return False
    # If we planned any tools, keep conservative (avoid accidental actions).
    if tool_plan:
        return False
    non_hub_items = [item for item in retrieval.items if not is_hub_path(item.path)]
    if not non_hub_items:
        return False

    if retrieval.items and is_hub_path(retrieval.items[0].path):
        # Top hit is a broad hub page — only reply if a specific article is clearly better.
        if len(retrieval.items) < 2 or is_hub_path(retrieval.items[1].path):
            return False
        if retrieval.items[0].score - retrieval.items[1].score < 3.0:
            return False
    return True


#
# Reply composition and confidence calibration now live in code/response.py
#


def _first_match(pattern: re.Pattern[str], text: str) -> str:
    if not text:
        return ""
    match = pattern.search(text)
    return match.group(0) if match else ""


def _verification_target(*, email: str, phone: str) -> tuple[str, str]:
    if email:
        return email, "email_otp"
    if phone:
        return phone, "sms_otp"
    return "", ""


def _extract_account_identifier(text: str) -> str:
    # Conservative fallback: use an email if present; otherwise empty.
    return _first_match(_EMAIL, text)

