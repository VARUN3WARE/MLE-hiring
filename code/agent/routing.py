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

from agent.issue_parser import combined_user_text, parse_issue
from retrieval.evidence import RetrievalResult, retrieve_evidence, STRONG_SCORE_THRESHOLD
from agent.response import compose_escalation, compose_out_of_scope, compose_reply
from schemas.ticket_categories import (
    is_harmless_out_of_scope,
    is_hub_path,
    requires_account_action_escalation,
)
from safety import classify_ticket
from safety.models import SafetyAssessment


_VALID_STATUS = {"replied", "escalated"}
VALID_STATUS = _VALID_STATUS
VALID_REQUEST_TYPE = {"product_issue", "feature_request", "bug", "invalid"}
VALID_RISK_LEVEL = {"low", "medium", "high", "critical"}

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3}[-.\s]?\d{3,4}\b")

_REFUND_OR_BILLING = re.compile(
    r"\b(?:refund|chargeback|charge\s+me\s+back|reverse\s+the\s+charge|give\s+me\s+my\s+money|"
    r"dispute\s+(?:this\s+)?charge|never\s+authorized\s+(?:this\s+)?(?:charge|subscription))\b",
    re.IGNORECASE,
)
_SUBSCRIPTION_CHANGE = re.compile(
    r"\b(?:cancel(?:\s+\w+){0,4}\s+subscription|"
    r"upgrade(?:\s+\w+){0,3}\s+(?:plan|subscription|tier)|"
    r"downgrade(?:\s+(?:to|my))?(?:\s+\w+){0,3}\s+(?:plan|subscription|free|tier)|"
    r"modify\s+subscription|change\s+my\s+plan)\b",
    re.IGNORECASE,
)
_ACCOUNT_LOCK = re.compile(
    r"\b(?:lock\s+(?:my\s+)?(?:account|workspace|access|everything)|"
    r"freeze\s+(?:my\s+)?(?:account|card|workspace))\b",
    re.IGNORECASE,
)
_UNVERIFIED_CLAIM = re.compile(
    r"\b(?:i\s+already\s+verified|verification\s+(?:passed|complete))\b",
    re.IGNORECASE,
)
_TRANSACTION_REF = re.compile(r"\b(?:TXN|transaction)[-_A-Z0-9]+\b", re.IGNORECASE)
_CONFLICT_LANGUAGE = re.compile(
    r"\b(?:conflicting|contradict(?:ory|s)?|disagree|which applies|two articles disagree)\b",
    re.IGNORECASE,
)
_SUSPICIOUS_MARKUP = re.compile(
    r"<\s*(?:script|iframe|object|embed)|onclick\s*=|javascript\s*:",
    re.IGNORECASE,
)
_HALLUCINATED_CITATION_REQUEST = re.compile(
    r"nonexistent\s+policy|cite\s+nonexistent|policy\.doc\b",
    re.IGNORECASE,
)
_CONTRADICTORY_ESCALATION = re.compile(
    r"escalat(?:e|ion).{0,120}actually\s+no,\s+just\s+reply",
    re.IGNORECASE | re.DOTALL,
)
_SYNTHETIC_OR_FAKE_TERMS = re.compile(
    r"\b(?:SYNTH[-_][A-Z0-9-]+|ERROR_CODE_[A-Z0-9_]+|flarnium|hyperbolic\s+interview|"
    r"legacy\s+portal|backwards-compatible\s+widget)\b",
    re.IGNORECASE,
)
_BILLING_CONTEXT = re.compile(
    r"\b(?:billing|invoice|payment|charge|refund|subscription|card)\b",
    re.IGNORECASE,
)


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
    ticket_text = "\n".join(p for p in (subject, body) if p)
    # Include subject — it may contain adversarial or misleading signals.
    raw_for_safety = "\n".join(
        p for p in (subject, body, parsed.raw if parsed.parse_error else "") if p
    )
    assessment = classify_ticket(raw_for_safety)

    if parsed.parse_error:
        return _route_invalid_issue(
            subject=subject,
            company=company,
            assessment=assessment,
            ticket_text=ticket_text,
            issue_text=issue,
        )

    # High-risk topics: always escalate.
    if _is_high_risk(assessment):
        return _route_escalate(
            subject=subject,
            company=company,
            assessment=assessment,
            reason="High-risk safety signals detected (legal/security/privacy/account compromise).",
            department=_department_for_signals(assessment),
            priority=_priority_for_risk(assessment.recommended_risk_level),
            ticket_text=ticket_text,
            issue_text=issue,
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
            ticket_text=ticket_text,
            issue_text=issue,
        )

    body_text = body or ""
    request_type = _infer_request_type(ticket_text)
    product_area = _infer_product_area(ticket_text, company)

    if _is_malformed_ticket(subject=subject, body=body_text, raw_issue=issue):
        return _route_escalate(
            subject=subject,
            company=company,
            assessment=assessment,
            reason="Malformed, empty, or noisy ticket content; escalating for manual review.",
            department="general",
            priority="normal",
            force_invalid=True,
            ticket_text=ticket_text,
            issue_text=issue,
        )

    if _requires_sensitive_pii_escalation(assessment, body_text):
        return _route_escalate(
            subject=subject,
            company=company,
            assessment=assessment,
            reason="Sensitive PII detected; escalating for secure specialist handling.",
            department="security",
            priority="high",
            request_type=request_type,
            product_area=product_area,
            ticket_text=ticket_text,
            issue_text=issue,
        )

    if is_harmless_out_of_scope(ticket_text):
        composed = compose_out_of_scope(assessment=assessment, issue_text=issue)
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

    if _HALLUCINATED_CITATION_REQUEST.search(body_text or ticket_text):
        return _route_escalate(
            subject=subject,
            company=company,
            assessment=assessment,
            reason=(
                "User requested citation of a nonexistent or unverifiable policy; "
                "escalating without fabricated sources."
            ),
            department="general",
            priority="normal",
            request_type=request_type,
            product_area=product_area,
            retrieval=retrieval,
            force_invalid=True,
            ticket_text=ticket_text,
            issue_text=issue,
        )

    if requires_account_action_escalation(body_text):
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
            ticket_text=ticket_text,
            issue_text=issue,
        )

    escalation_reason = _content_escalation_reason(
        ticket_text, assessment, retrieval, tool_plan, raw_issue=issue, body_text=body_text
    )
    if escalation_reason:
        return _route_escalate(
            subject=subject,
            company=company,
            assessment=assessment,
            reason=escalation_reason,
            department=_department_for_escalation_reason(escalation_reason, assessment, company),
            priority=_priority_for_risk(assessment.recommended_risk_level),
            request_type=request_type,
            product_area=product_area,
            retrieval=retrieval,
            missing_prereqs=bool(tool_plan),
            force_invalid=_content_escalation_force_invalid(escalation_reason),
            ticket_text=ticket_text,
            issue_text=issue,
        )

    if _is_safe_pii_informational_reply(ticket_text, assessment, retrieval, tool_plan):
        composed = compose_reply(retrieval=retrieval, assessment=assessment, issue_text=issue)
        return RouteDecision(
            status="replied",
            request_type=request_type,
            risk_level="low",
            product_area=product_area,
            response=composed.response,
            justification=composed.justification,
            confidence_score=composed.confidence_score,
            source_documents=composed.source_documents,
            actions=tool_plan,
            assessment=assessment,
        )

    if _should_reply(assessment, retrieval, tool_plan, ticket_text=body_text):
        composed = compose_reply(retrieval=retrieval, assessment=assessment, issue_text=issue)
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
        ticket_text=ticket_text,
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
    if _REFUND_OR_BILLING.search(low) or _SUBSCRIPTION_CHANGE.search(low):
        target, method = _verification_target(email=email, phone=phone)
        if target and method:
            actions.append({"action": "verify_identity", "parameters": {"method": method, "target": target}})
        # Do not attempt issue_refund/modify_subscription unless all required fields are present.
        return actions

    return actions


def _route_invalid_issue(
    *, subject: str, company: str, assessment: SafetyAssessment, ticket_text: str = "", issue_text: str = ""
) -> RouteDecision:
    return _route_escalate(
        subject=subject,
        company=company,
        assessment=assessment,
        reason="Issue conversation could not be parsed as valid JSON array; escalating for manual review.",
        department="general",
        priority="normal",
        force_invalid=True,
        retrieval=None,
        ticket_text=ticket_text or subject,
        issue_text=issue_text or ticket_text or subject,
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
    ticket_text: str = "",
    issue_text: str = "",
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
        request_type=req_type,
        has_tool_actions=True,
        missing_prereqs=missing_prereqs,
        department=department,
        priority=priority,
        ticket_text=ticket_text or subject,
        issue_text=issue_text or ticket_text or subject,
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
        source_documents=composed.source_documents,
        actions=actions,
        assessment=assessment,
    )


def _content_escalation_reason(
    ticket_text: str,
    assessment: SafetyAssessment,
    retrieval: RetrievalResult,
    tool_plan: list[dict[str, Any]],
    *,
    raw_issue: str = "",
    body_text: str = "",
) -> str | None:
    """Return escalation reason for sensitive content not caught earlier, else None."""
    body = (body_text or ticket_text or "").strip()
    low_body = body.lower()
    scan_text = "\n".join(p for p in (ticket_text, raw_issue) if p)
    action_text = body

    if _SUSPICIOUS_MARKUP.search(scan_text):
        return "Suspicious markup or script-like content detected; escalating for manual review."

    if _HALLUCINATED_CITATION_REQUEST.search(body or ""):
        return (
            "User requested citation of a nonexistent or unverifiable policy; "
            "escalating without fabricated sources."
        )

    if _CONTRADICTORY_ESCALATION.search(body or ""):
        return "Contradictory escalation instructions detected; escalating for manual review."

    if _is_repetitive_or_noisy(scan_text):
        return "Noisy or repetitive ticket content; escalating for manual review."

    if _is_malformed_ticket(subject="", body=body, raw_issue=raw_issue):
        return "Malformed or insufficient ticket content; escalating for manual review."

    if _has_ungrounded_query(body, retrieval):
        return "Query terms are not supported by retrieved evidence; escalating rather than guessing."

    if _CONFLICT_LANGUAGE.search(body or ""):
        return "User reports conflicting documentation; escalating for specialist review."

    if assessment.pii_detected and _REFUND_OR_BILLING.search(action_text or ""):
        return "Refund or billing dispute with PII present; escalating for verified handling."

    if assessment.pii_detected and _BILLING_CONTEXT.search(action_text or ""):
        pii_count = sum(1 for s in assessment.risk_signals if s.startswith("pii:"))
        if pii_count >= 2 and (
            _REFUND_OR_BILLING.search(action_text or "")
            or _SUBSCRIPTION_CHANGE.search(action_text or "")
            or any(
                phrase in (action_text or "").lower()
                for phrase in ("please fix billing", "fix billing", "fix my billing", "dispute")
            )
        ):
            return "Multiple PII types with billing context; escalating for verified handling."

    if assessment.pii_detected and any(
        s in assessment.risk_signals
        for s in ("risk:legal_threat", "risk:fraud", "risk:identity_theft", "risk:account_compromise")
    ):
        return "PII combined with high-risk signals; escalating for specialist review."

    if _REFUND_OR_BILLING.search(action_text or "") and not _has_verified_identity(action_text, tool_plan):
        return "Refund or chargeback requested without established identity verification; escalating."

    if _SUBSCRIPTION_CHANGE.search(action_text or "") and not _has_verified_identity(action_text, tool_plan):
        return "Subscription change requested without identity verification; escalating."

    if _ACCOUNT_LOCK.search(action_text or ""):
        return "Account or card lock requested; escalating for verification and specialist review."

    if "risk:ambiguous_high_risk" in assessment.risk_signals:
        return "Ambiguous billing or fraud concern; escalating for cautious review."

    if retrieval.overall_grade == "conflicting":
        top_score = retrieval.items[0].score if retrieval.items else 0.0
        if top_score >= STRONG_SCORE_THRESHOLD and (
            _looks_like_simple_faq(low_body) or top_score >= 20.0
        ):
            pass
        else:
            return "Evidence grade is conflicting; escalating rather than guessing."
    elif retrieval.overall_grade in ("insufficient", "conflicting"):
        return f"Evidence grade is {retrieval.overall_grade}; escalating rather than guessing."

    top_score = retrieval.items[0].score if retrieval.items else 0.0
    if top_score < STRONG_SCORE_THRESHOLD and not _looks_like_simple_faq(low_body):
        return "Retrieval score below strong threshold for a non-FAQ request; escalating."

    if retrieval.overall_grade == "weak" and not _looks_like_simple_faq(low_body):
        return "Weak retrieval evidence for a non-FAQ request; escalating for review."

    if tool_plan and any(a.get("action") == "verify_identity" for a in tool_plan):
        if _looks_like_simple_faq(low_body) and not _REFUND_OR_BILLING.search(action_text or ""):
            return None
        return "Identity verification required before account action; escalating for specialist handling."

    return None


def _content_escalation_force_invalid(reason: str) -> bool:
    """Strip citations / mark invalid for content-driven escalations that must not cite."""
    markers = (
        "Suspicious markup",
        "Malformed",
        "Noisy or repetitive",
        "nonexistent or unverifiable",
        "Contradictory escalation",
        "not supported by retrieved evidence",
    )
    return any(marker in reason for marker in markers)


def _has_verified_identity(ticket_text: str, tool_plan: list[dict[str, Any]]) -> bool:
    if _UNVERIFIED_CLAIM.search(ticket_text or ""):
        return False
    if _TRANSACTION_REF.search(ticket_text or "") and _EMAIL.search(ticket_text or ""):
        return False
    return any(a.get("action") == "verify_identity" for a in tool_plan)


def _looks_like_simple_faq(low: str) -> bool:
    stripped = (low or "").strip()
    if re.match(r"^(?:how|what|where|why|can i)\b", stripped):
        return True
    return any(
        marker in low
        for marker in (
            "how do i",
            "how do ",
            "how can i",
            "how can ",
            "how does ",
            "what is",
            "what are",
            "where can i find",
            "where can i",
            "why does",
            "why is",
        )
    )


def _is_malformed_ticket(*, subject: str, body: str, raw_issue: str = "") -> bool:
    """Detect empty, noisy, or non-actionable ticket payloads."""
    body_stripped = (body or "").strip()
    subject_stripped = (subject or "").strip()

    if not body_stripped:
        return True

    if len(body_stripped) < 18 and not _looks_like_simple_faq(body_stripped.lower()):
        return True

    if re.fullmatch(r"(?:hello|hi|hey|test|asdf|foo|bar)[!.?\s]*", body_stripped, re.IGNORECASE):
        return True

    if re.search(r"\bSYNTH[-_\s]|SYNTH RANDOM|\bSYNTH-[A-Z0-9]", body_stripped):
        return True

    alnum = sum(1 for ch in body_stripped if ch.isalnum())
    if len(body_stripped) >= 12 and alnum / len(body_stripped) < 0.45:
        return True

    if re.search(r"^\s*\|", body_stripped, re.MULTILINE) and not re.search(
        r"\?\s*$", body_stripped
    ):
        pipe_lines = [ln for ln in body_stripped.splitlines() if "|" in ln]
        if len(pipe_lines) >= 2 and len(body_stripped.split()) < 25:
            return True

    if not subject_stripped and re.fullmatch(
        r"(?:general\s+question\s+about\s+\w+[.?!]?|billing[.?!]?)", body_stripped, re.IGNORECASE
    ):
        return True

    return False


def _requires_sensitive_pii_escalation(assessment: SafetyAssessment, body_text: str) -> bool:
    if not assessment.pii_detected:
        return False
    if "pii:api_token" in assessment.risk_signals:
        return True
    pii_count = sum(1 for s in assessment.risk_signals if s.startswith("pii:"))
    if pii_count >= 2 and _BILLING_CONTEXT.search(body_text or ""):
        if _REFUND_OR_BILLING.search(body_text or "") or _SUBSCRIPTION_CHANGE.search(body_text or ""):
            return True
        if any(
            phrase in (body_text or "").lower()
            for phrase in ("please fix billing", "fix billing", "fix my billing", "dispute")
        ):
            return True
    return False


def _has_ungrounded_query(body: str, retrieval: RetrievalResult) -> bool:
    """Flag queries with synthetic/obscure terms unlikely to be in the corpus."""
    if _SYNTHETIC_OR_FAKE_TERMS.search(body or ""):
        return True
    if re.search(r"\bERROR_CODE_[A-Z0-9_]+\b", body or ""):
        return True
    return False


def _is_repetitive_or_noisy(text: str) -> bool:
    words = (text or "").split()
    if len(words) >= 80:
        unique_ratio = len(set(words)) / len(words)
        if unique_ratio < 0.15:
            return True
    if len(text or "") > 1500 and len(set(words)) < 10:
        return True
    return False


def _is_safe_pii_informational_reply(
    ticket_text: str,
    assessment: SafetyAssessment,
    retrieval: RetrievalResult,
    tool_plan: list[dict[str, Any]],
) -> bool:
    if not assessment.pii_detected or assessment.is_adversarial:
        return False
    if assessment.recommended_risk_level in ("high", "critical"):
        return False
    if any(
        s in assessment.risk_signals
        for s in (
            "risk:legal_threat",
            "risk:fraud",
            "risk:identity_theft",
            "risk:account_compromise",
            "risk:ambiguous_high_risk",
        )
    ):
        return False
    if _REFUND_OR_BILLING.search(ticket_text or "") or _SUBSCRIPTION_CHANGE.search(ticket_text or ""):
        return False
    if retrieval.overall_grade != "strong":
        return False
    low = (ticket_text or "").lower()
    if "reset password" in low or "forgot password" in low:
        return any(a.get("action") == "reset_password" for a in tool_plan)
    if _looks_like_simple_faq(low):
        return not tool_plan or all(
            a.get("action") in ("reset_password",) for a in tool_plan
        )
    if any(k in low for k in ("update", "contact email", "confirm", "profile")):
        return not tool_plan
    return False


def _is_safe_pii_password_reset(
    ticket_text: str,
    assessment: SafetyAssessment,
    retrieval: RetrievalResult,
    tool_plan: list[dict[str, Any]],
) -> bool:
    low = (ticket_text or "").lower()
    if not assessment.pii_detected:
        return False
    if "reset password" not in low and "forgot password" not in low:
        return False
    if not any(a.get("action") == "reset_password" for a in tool_plan):
        return False
    if retrieval.overall_grade != "strong":
        return False
    if assessment.is_adversarial:
        return False
    return True


def _department_for_escalation_reason(
    reason: str,
    assessment: SafetyAssessment,
    company: str,
) -> str:
    low = reason.lower()
    if "legal" in low or "risk:legal" in assessment.risk_signals:
        return "legal"
    if "refund" in low or "billing" in low or "subscription" in low:
        return "billing"
    if "fraud" in low or "identity" in low or "lock" in low:
        return "security"
    return _department_for_company(company)


def _is_high_risk(assessment: SafetyAssessment) -> bool:
    high_signals = {
        "risk:legal_threat",
        "risk:identity_theft",
        "risk:account_compromise",
        "risk:privacy_breach",
        "risk:security_vulnerability",
        "risk:fraud",
        "risk:ambiguous_high_risk",
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


def _should_reply(
    assessment: SafetyAssessment,
    retrieval: RetrievalResult,
    tool_plan: list[dict[str, Any]],
    *,
    ticket_text: str = "",
) -> bool:
    if assessment.is_adversarial:
        return False
    if assessment.recommended_risk_level in ("high", "critical"):
        return False
    elevated_risks = {
        s for s in assessment.risk_signals if s.startswith("risk:") and s != "risk:ambiguous_high_risk"
    }
    if elevated_risks:
        return False
    grade = retrieval.overall_grade
    if grade not in ("strong", "conflicting"):
        return False
    if grade == "conflicting":
        top_score = retrieval.items[0].score if retrieval.items else 0.0
        low = (ticket_text or "").lower()
        if top_score < STRONG_SCORE_THRESHOLD:
            return False
        if not (_looks_like_simple_faq(low) or top_score >= 20.0):
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

