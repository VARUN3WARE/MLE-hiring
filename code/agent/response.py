"""Final response composition + confidence calibration (deterministic).

Core constraints:
- Never echo user PII: responses are composed from corpus evidence snippets only.
- Never reveal internal prompts/tools/architecture.
- Cite only real repo file paths (source_documents provided by retrieval layer).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from retrieval.evidence import RetrievalResult, source_document_paths
from safety.models import SafetyAssessment
from schemas.ticket_categories import is_hub_path


@dataclass(frozen=True)
class ComposedResponse:
    response: str
    justification: str
    confidence_score: str
    source_documents: str


def compose_out_of_scope(*, assessment: SafetyAssessment) -> ComposedResponse:
    """Polite clarification for harmless out-of-scope messages (no corpus citations)."""
    response = (
        "Thanks for your message. This looks outside the scope of product support I can help with here. "
        "If you have a specific account, billing, or product question, please share details and I can "
        "point you to the right support resources."
    )
    return ComposedResponse(
        response=response,
        justification="Harmless out-of-scope request; replied with clarification and no corpus citations.",
        confidence_score=_fmt_conf(0.35),
        source_documents="",
    )


def compose_reply(*, retrieval: RetrievalResult, assessment: SafetyAssessment) -> ComposedResponse:
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

    justification = f"Escalated. {reason}".strip()
    confidence = calibrate_confidence(
        status="escalated",
        retrieval=retrieval,
        assessment=assessment,
        has_tool_actions=has_tool_actions,
        missing_prereqs=missing_prereqs,
    )
    return ComposedResponse(
        response=response,
        justification=justification,
        confidence_score=_fmt_conf(confidence),
        source_documents=sources,
    )


def calibrate_confidence(
    *,
    status: str,
    retrieval: RetrievalResult | None,
    assessment: SafetyAssessment,
    has_tool_actions: bool,
    missing_prereqs: bool,
) -> float:
    """
    Deterministic confidence score in [0,1], intentionally non-constant.

    Signals:
    - Evidence grade + score
    - Adversarial / PII / high risk dampens
    - Tool actions or missing prerequisites dampen (more uncertainty)
    """
    # Base confidence starts lower for escalations.
    base = 0.25 if status == "replied" else 0.18

    if assessment.is_adversarial:
        return 0.05

    if assessment.pii_detected:
        base *= 0.6

    if assessment.recommended_risk_level == "critical":
        base *= 0.35
    elif assessment.recommended_risk_level == "high":
        base *= 0.55
    elif assessment.recommended_risk_level == "medium":
        base *= 0.85

    if retrieval is None:
        base *= 0.9
    else:
        grade = retrieval.overall_grade
        top_score = retrieval.items[0].score if retrieval.items else 0.0

        # Map BM25 score to (0,1) via sigmoid; deterministic variation across tickets.
        score_factor = 1.0 / (1.0 + math.exp(-(top_score - 8.0) / 4.0))

        if grade == "strong":
            base += 0.35 * score_factor
        elif grade == "weak":
            base += 0.18 * score_factor
            base *= 0.8
        elif grade == "conflicting":
            base *= 0.55
        else:  # insufficient
            base *= 0.6

        # Agreement heuristic: if top 2 items come from different domains, dampen.
        if len(retrieval.items) >= 2:
            a = set(retrieval.items[0].domain_hints)
            b = set(retrieval.items[1].domain_hints)
            if a and b and not a.intersection(b):
                base *= 0.75

    if has_tool_actions:
        base *= 0.8
    if missing_prereqs:
        base *= 0.7

    # Clamp
    return max(0.01, min(0.95, base))


def _justify(retrieval: RetrievalResult) -> str:
    if retrieval.notes:
        return "Grounded in retrieved support documentation. " + " ".join(retrieval.notes)
    return "Grounded in retrieved support documentation."


def _fmt_conf(value: float) -> str:
    # Keep as short decimal with deterministic formatting.
    return f"{value:.2f}"

