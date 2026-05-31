"""Final response composition + confidence calibration (deterministic).

Core constraints:
- Never echo user PII: responses are composed from corpus evidence snippets only.
- Never reveal internal prompts/tools/architecture.
- Cite only real repo file paths (source_documents provided by retrieval layer).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from retrieval.evidence import RetrievalResult, source_document_paths
from safety.models import SafetyAssessment
from schemas.ticket_categories import is_hub_path

_ADVERSARIAL_SUBLABELS: dict[str, str] = {
    "exfiltration:system_prompt": "exfiltration attempt",
    "exfiltration:tool_or_api": "internal tool exfiltration",
    "exfiltration:internal_tools_phrase": "internal tool disclosure",
    "exfiltration:retrieval_or_architecture": "architecture disclosure",
    "exfiltration:hidden_prompt": "hidden prompt exfiltration",
    "exfiltration:corpus_dump": "corpus dump request",
    "exfiltration:debug_or_internal_state": "internal state disclosure",
    "exfiltration:multilingual_internal_rules": "internal rules exfiltration",
    "prompt_injection:instruction_override": "instruction override",
    "prompt_injection:system_override": "system override injection",
    "prompt_injection:roleplay_jailbreak": "jailbreak attempt",
    "prompt_injection:forced_output": "forced output manipulation",
    "prompt_injection:ignore_rules_shorthand": "safety rule bypass",
    "prompt_injection:json_manipulation": "output schema manipulation",
    "prompt_injection:corpus_embedded_override": "corpus injection",
    "prompt_injection:pretend_unrestricted": "unrestricted mode probe",
    "prompt_injection:multilingual_override": "multilingual override",
    "authority:fake_qa_or_admin": "fake authority claim",
    "authority:override_codes": "override code spoofing",
    "authority:automated_system_spoof": "automated system spoofing",
    "authority:impersonation_claim": "impersonation claim",
    "encoding:base64_instruction_payload": "encoded instruction payload",
    "encoding:suspicious_base64_blob": "suspicious encoded payload",
    "encoding:url_or_spaced_override": "obfuscated override text",
    "encoding:rot13_override": "rot13-encoded override",
}

_RISK_SUBLABELS: dict[str, str] = {
    "risk:legal_threat": "legal threat detected",
    "risk:identity_theft": "identity theft reported",
    "risk:account_compromise": "account compromise reported",
    "risk:privacy_breach": "privacy or data breach concern",
    "risk:security_vulnerability": "security vulnerability report",
    "risk:fraud": "fraud concern",
    "risk:ambiguous_high_risk": "ambiguous high-risk billing concern",
}

_PII_LABELS: dict[str, str] = {
    "pii:ssn": "SSN",
    "pii:email": "email",
    "pii:payment_card": "payment card",
    "pii:phone": "phone number",
    "pii:date_of_birth": "date of birth",
    "pii:address": "address",
    "pii:api_token": "API token",
    "pii:account_identifier": "account identifier",
    "pii:numeric_identifier": "numeric identifier",
}

_KEYWORD_HINTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(lawsuit|class action|attorney|lawyer|sue|legal action)\b", re.IGNORECASE), "legal"),
    (re.compile(r"\b(unauthorized(?:\s+\w+){0,3}\s+(?:access|purchases|charges|login))\b", re.IGNORECASE), "account"),
    (re.compile(r"\b(identity\s+(?:theft|stolen)|stolen\s+identity)\b", re.IGNORECASE), "identity"),
    (re.compile(r"\b(refund|chargeback|subscription\s+cancel)\b", re.IGNORECASE), "billing"),
    (re.compile(r"\b(lock\s+(?:my\s+)?(?:account|card|workspace))\b", re.IGNORECASE), "account lock"),
)

_DEPARTMENT_LABELS: dict[str, str] = {
    "legal": "legal dept",
    "security": "security",
    "billing": "billing",
    "technical": "technical support",
    "general": "general support",
}

_GENERIC_REASON_MARKERS: tuple[str, ...] = (
    "High-risk safety signals detected",
    "Adversarial or internal-disclosure patterns detected",
    "Sensitive PII detected",
    "Account-level or billing action requested",
    "Insufficient grounded evidence to reply safely",
)

_INSUFFICIENT_ESCALATION_MARKERS: tuple[str, ...] = (
    "Insufficient grounded evidence",
    "Evidence grade is insufficient",
    "Evidence grade is weak",
    "Weak retrieval evidence",
    "Retrieval score below strong threshold",
    "Query terms are not supported",
    "ungrounded query terms",
    "insufficient retrieval evidence",
)

_CONFIDENCE_MIN = 0.20
_CONFIDENCE_MAX = 0.95


@dataclass(frozen=True)
class ComposedResponse:
    response: str
    justification: str
    confidence_score: str
    source_documents: str


def compose_out_of_scope(*, assessment: SafetyAssessment, issue_text: str = "") -> ComposedResponse:
    """Polite clarification for harmless out-of-scope messages (no corpus citations)."""
    response = (
        "Thanks for your message. This looks outside the scope of product support I can help with here. "
        "If you have a specific account, billing, or product question, please share details and I can "
        "point you to the right support resources."
    )
    return ComposedResponse(
        response=response,
        justification="Harmless out-of-scope request; replied with clarification and no corpus citations.",
        confidence_score=_fmt_conf(
            calibrate_confidence(
                status="replied",
                retrieval=None,
                assessment=assessment,
                has_tool_actions=False,
                missing_prereqs=False,
                issue_text=issue_text,
                reason="harmless out-of-scope clarification",
            )
        ),
        source_documents="",
    )


def compose_reply(
    *,
    retrieval: RetrievalResult,
    assessment: SafetyAssessment,
    issue_text: str = "",
) -> ComposedResponse:
    """
    Compose a concise, grounded reply from retrieval snippets.

    Assumes caller already ensured: not adversarial, not high risk, no PII echo risk.
    """
    sources = (
        source_document_paths(retrieval, exclude_hubs=True)
        if retrieval.overall_grade in ("strong", "weak", "conflicting")
        else ""
    )
    snippet_lines: list[str] = []
    for item in retrieval.items:
        if is_hub_path(item.path):
            continue
        if item.snippet:
            snippet_lines.append(f"- {item.snippet}")
        if len(snippet_lines) >= 2:
            break

    if snippet_lines:
        body = "Here’s what the support documentation says:\n\n" + "\n".join(snippet_lines)
    else:
        body = (
            "I’m not finding enough relevant information in the provided support documentation to answer confidently. "
            "I’ve escalated this for review."
        )

    if sources:
        body = f"{body}\n\nSources: {sources}"

    justification = _justify(retrieval)
    confidence = calibrate_confidence(
        status="replied",
        retrieval=retrieval,
        assessment=assessment,
        has_tool_actions=False,
        missing_prereqs=False,
        issue_text=issue_text,
    )
    return ComposedResponse(
        response=body,
        justification=justification,
        confidence_score=_fmt_conf(confidence),
        source_documents=sources,
    )


def _escalation_sources_allowed(
    *,
    assessment: SafetyAssessment,
    request_type: str,
) -> bool:
    """Strip citations only for adversarial or invalid/out-of-scope rows."""
    if assessment.is_adversarial:
        return False
    if (request_type or "").strip().lower() == "invalid":
        return False
    return True


def compose_escalation(
    *,
    assessment: SafetyAssessment,
    reason: str,
    retrieval: RetrievalResult | None = None,
    request_type: str = "product_issue",
    has_tool_actions: bool = True,
    missing_prereqs: bool = False,
    department: str = "general",
    priority: str = "normal",
    ticket_text: str = "",
    issue_text: str = "",
) -> ComposedResponse:
    response = (
        "Thank you for reaching out. I’m escalating this to a support specialist for review. "
        "For safety and privacy reasons, we may need additional verification before taking any account-level actions."
    )
    if assessment.is_adversarial:
        response = (
            "Thank you for your message. I’m escalating this to a support specialist. "
            "For security reasons, I can’t help with requests to reveal internal system details, prompts, tools, or processing logic."
        )

    if assessment.pii_detected:
        response += " Please avoid sharing sensitive personal information in chat. If verification is needed, support will guide you securely."

    sources = ""
    if (
        _escalation_sources_allowed(assessment=assessment, request_type=request_type)
        and retrieval is not None
        and retrieval.overall_grade in ("strong", "conflicting")
    ):
        sources = source_document_paths(retrieval, exclude_hubs=True)
        if sources:
            snippet_lines: list[str] = []
            for item in retrieval.items:
                if is_hub_path(item.path):
                    continue
                if item.snippet:
                    snippet_lines.append(f"- {item.snippet}")
                if len(snippet_lines) >= 2:
                    break
            if snippet_lines:
                response += (
                    "\n\nRelevant support documentation while we review:\n\n"
                    + "\n".join(snippet_lines)
                )
            response += f"\n\nSources: {sources}"

    justification = _format_escalation_justification(
        assessment=assessment,
        reason=reason,
        retrieval=retrieval,
        department=department,
        priority=priority,
        ticket_text=ticket_text,
    )
    confidence = calibrate_confidence(
        status="escalated",
        retrieval=retrieval,
        assessment=assessment,
        has_tool_actions=has_tool_actions,
        missing_prereqs=missing_prereqs,
        issue_text=issue_text or ticket_text,
        reason=reason,
    )
    return ComposedResponse(
        response=response,
        justification=justification,
        confidence_score=_fmt_conf(confidence),
        source_documents=sources,
    )


def _format_escalation_justification(
    *,
    assessment: SafetyAssessment,
    reason: str,
    retrieval: RetrievalResult | None,
    department: str,
    priority: str,
    ticket_text: str,
) -> str:
    primary = _primary_escalation_reason(
        assessment=assessment,
        reason=reason,
        retrieval=retrieval,
        ticket_text=ticket_text,
    )
    action = _escalation_action_phrase(
        assessment=assessment,
        department=department,
        priority=priority,
    )
    return f"Escalated — {primary}. {action}"


def _primary_escalation_reason(
    *,
    assessment: SafetyAssessment,
    reason: str,
    retrieval: RetrievalResult | None,
    ticket_text: str,
) -> str:
    if not any(marker in reason for marker in _GENERIC_REASON_MARKERS):
        return _normalize_primary_clause(reason)

    if assessment.is_adversarial:
        return _adversarial_primary_reason(assessment.risk_signals, ticket_text)

    risk_signal = _first_signal(assessment.risk_signals, _RISK_SUBLABELS)
    if risk_signal:
        return _risk_primary_reason(risk_signal, ticket_text)

    if assessment.pii_detected:
        return _pii_primary_reason(assessment.risk_signals, reason)

    if "Account-level or billing action" in reason:
        hint = _keyword_hint(ticket_text, _KEYWORD_HINTS, preferred="billing")
        base = "account or billing action requested without verification"
        return f"{base} ({hint})" if hint else base

    if "Insufficient grounded evidence" in reason and retrieval is not None:
        grade = retrieval.overall_grade
        return f"insufficient retrieval evidence ({grade} grade)"

    if "Sensitive PII detected" in reason:
        return _pii_primary_reason(assessment.risk_signals, reason)

    return _normalize_primary_clause(reason)


def _adversarial_primary_reason(signals: tuple[str, ...], ticket_text: str) -> str:
    for signal in signals:
        if signal in _ADVERSARIAL_SUBLABELS:
            sublabel = _ADVERSARIAL_SUBLABELS[signal]
            if signal.startswith("exfiltration:"):
                return f"adversarial probe ({sublabel})"
            if signal.startswith(("prompt_injection:", "authority:", "encoding:")):
                return f"adversarial probe ({sublabel})"
    for signal in signals:
        if signal.startswith(("exfiltration:", "prompt_injection:", "authority:", "encoding:")):
            category = signal.split(":", 1)[0].replace("_", " ")
            return f"adversarial probe ({category})"
    hint = _keyword_hint(ticket_text, _KEYWORD_HINTS)
    base = "adversarial or internal-disclosure patterns detected"
    return f"{base} ({hint})" if hint else base


def _risk_primary_reason(signal: str, ticket_text: str) -> str:
    label = _RISK_SUBLABELS[signal]
    hint = _keyword_hint(ticket_text, _KEYWORD_HINTS)
    return f"{label} ({hint})" if hint else label


def _pii_primary_reason(signals: tuple[str, ...], reason: str) -> str:
    pii_types = [
        _PII_LABELS[s]
        for s in signals
        if s.startswith("pii:") and s in _PII_LABELS
    ]
    if pii_types:
        joined = ", ".join(dict.fromkeys(pii_types))
        return f"sensitive PII detected ({joined})"
    if "billing" in reason.lower():
        return "sensitive PII with billing context"
    return "sensitive PII detected in ticket"


def _escalation_action_phrase(
    *,
    assessment: SafetyAssessment,
    department: str,
    priority: str,
) -> str:
    if assessment.is_adversarial:
        return "Safety override engaged."
    dept = _DEPARTMENT_LABELS.get((department or "general").strip().lower(), department or "general support")
    priority_label = (priority or "normal").strip().lower()
    if priority_label in ("urgent", "high"):
        return f"Routed to {dept} with {priority_label} priority."
    return f"Routed to {dept} for manual review."


def _first_signal(signals: tuple[str, ...], labels: dict[str, str]) -> str | None:
    for signal in signals:
        if signal in labels:
            return signal
    return None


def _keyword_hint(
    ticket_text: str,
    patterns: tuple[tuple[re.Pattern[str], str], ...],
    *,
    preferred: str | None = None,
) -> str | None:
    text = ticket_text or ""
    if preferred:
        for pattern, _ in patterns:
            match = pattern.search(text)
            if match:
                return f"'{match.group(1).lower()}'"
        return None
    for pattern, _ in patterns:
        match = pattern.search(text)
        if match:
            return f"'{match.group(1).lower()}'"
    return None


def _normalize_primary_clause(reason: str) -> str:
    cleaned = (reason or "").strip()
    replacements = (
        ("Suspicious markup or script-like content detected; escalating for manual review.", "suspicious markup or script content detected"),
        ("Malformed, empty, or noisy ticket content; escalating for manual review.", "malformed or noisy ticket content"),
        ("Malformed or insufficient ticket content; escalating for manual review.", "malformed or insufficient ticket content"),
        ("Malformed, empty, or noisy ticket content; escalating for manual review.", "malformed or noisy ticket content"),
        ("Issue conversation could not be parsed as valid JSON array; escalating for manual review.", "unparseable issue JSON"),
        ("User requested citation of a nonexistent or unverifiable policy; escalating without fabricated sources.", "nonexistent policy citation requested"),
        ("Contradictory escalation instructions detected; escalating for manual review.", "contradictory escalation instructions"),
        ("Noisy or repetitive ticket content; escalating for manual review.", "noisy or repetitive ticket content"),
        ("Query terms are not supported by retrieved evidence; escalating rather than guessing.", "ungrounded query terms"),
        ("User reports conflicting documentation; escalating for specialist review.", "conflicting documentation reported"),
        ("Refund or billing dispute with PII present; escalating for verified handling.", "refund or billing dispute with PII present"),
        ("Multiple PII types with billing context; escalating for verified handling.", "multiple PII types with billing context"),
        ("PII combined with high-risk signals; escalating for specialist review.", "PII combined with high-risk signals"),
        ("Refund or chargeback requested without established identity verification; escalating.", "refund or chargeback without identity verification"),
        ("Subscription change requested without identity verification; escalating.", "subscription change without identity verification"),
        ("Account or card lock requested; escalating for verification and specialist review.", "account or card lock requested without verification"),
        ("Ambiguous billing or fraud concern; escalating for cautious review.", "ambiguous billing or fraud concern"),
        ("Evidence grade is conflicting; escalating rather than guessing.", "conflicting retrieval evidence"),
        ("Retrieval score below strong threshold for a non-FAQ request; escalating.", "weak retrieval score for non-FAQ request"),
        ("Weak retrieval evidence for a non-FAQ request; escalating for review.", "weak retrieval evidence"),
        ("Identity verification required before account action; escalating for specialist handling.", "identity verification required before account action"),
        ("Account-level or billing action requested; escalating for verification and specialist review.", "account or billing action requested without verification"),
        ("Sensitive PII detected; escalating for secure specialist handling.", "sensitive PII detected in ticket"),
    )
    for old, new in replacements:
        if cleaned == old or cleaned.rstrip(".") == old.rstrip("."):
            return new
    if cleaned.startswith("Evidence grade is "):
        grade = cleaned.removeprefix("Evidence grade is ").split(";", 1)[0].strip()
        return f"insufficient retrieval evidence ({grade})"
    normalized = cleaned.rstrip(".")
    return normalized[0].lower() + normalized[1:] if normalized else "manual review required"


def _deterministic_micro_variation(issue_text: str) -> float:
    """Stable +/- 0.05 jitter from issue text (hash-stable across runs)."""
    payload = (issue_text or "").encode("utf-8")
    bucket = int.from_bytes(hashlib.sha256(payload).digest()[:4], "big") % 101
    return (bucket - 50) / 1000.0


def _is_insufficient_info_escalation(reason: str, retrieval: RetrievalResult | None) -> bool:
    if any(marker in (reason or "") for marker in _INSUFFICIENT_ESCALATION_MARKERS):
        return True
    if retrieval is not None and retrieval.overall_grade in ("insufficient", "weak"):
        if "Insufficient grounded evidence" in (reason or ""):
            return True
        if any(
            phrase in (reason or "")
            for phrase in (
                "Evidence grade is",
                "Weak retrieval evidence",
                "Retrieval score below",
                "Query terms are not supported",
            )
        ):
            return True
    return False


def _clamp_confidence(value: float) -> float:
    return max(_CONFIDENCE_MIN, min(_CONFIDENCE_MAX, value))


def calibrate_confidence(
    *,
    status: str,
    retrieval: RetrievalResult | None,
    assessment: SafetyAssessment,
    has_tool_actions: bool,
    missing_prereqs: bool,
    issue_text: str = "",
    reason: str = "",
) -> float:
    """
    Deterministic confidence score in [0.20, 0.95] with per-row micro-variation.

    Baselines reflect routing certainty:
    - replied + strong/conflicting/weak evidence
    - escalated adversarial, safe escalation, or insufficient-info paths
    """
    _ = (has_tool_actions, missing_prereqs)  # retained for API compatibility

    if status == "replied":
        grade = retrieval.overall_grade if retrieval is not None else "insufficient"
        if grade == "strong":
            baseline = 0.85
        elif grade == "conflicting":
            baseline = 0.60
        elif grade == "weak":
            baseline = 0.45
        else:
            baseline = 0.30
    elif status == "escalated":
        if assessment.is_adversarial:
            baseline = 0.95
        elif _is_insufficient_info_escalation(reason, retrieval):
            baseline = 0.30
        else:
            baseline = 0.65
    else:
        baseline = 0.30

    if "harmless out-of-scope" in (reason or "").lower():
        baseline = 0.40

    return _clamp_confidence(baseline + _deterministic_micro_variation(issue_text))


def _justify(retrieval: RetrievalResult) -> str:
    if retrieval.notes:
        return "Grounded in retrieved support documentation. " + " ".join(retrieval.notes)
    return "Grounded in retrieved support documentation."


def _fmt_conf(value: float) -> str:
    # Keep as short decimal with deterministic formatting.
    return f"{value:.2f}"

