"""Eligibility gate for optional LLM response polishing.

The deterministic pipeline remains authoritative for:
- safety (adversarial + PII)
- retrieval + sources
- routing decision (reply vs escalate)
- tool plan (actions_taken)

This module only decides whether a row is safe to send to an LLM for *polishing*
the already-grounded deterministic response.
"""

from __future__ import annotations

from dataclasses import dataclass

from retrieval.evidence import RetrievalResult
from routing import RouteDecision
from ticket_categories import is_multilingual, requires_account_action_escalation


@dataclass(frozen=True)
class LLMRowContext:
    decision: RouteDecision
    retrieval: RetrievalResult
    ticket_text: str


def is_llm_eligible(ctx: LLMRowContext) -> tuple[bool, list[str]]:
    """
    Return (eligible, reasons). Reasons are *blocking* explanations when not eligible.

    This is deliberately conservative: it should be hard to become eligible.
    """
    reasons: list[str] = []
    decision = ctx.decision
    assessment = decision.assessment

    # Must not change routing decisions: only allow polishing of replied rows.
    if decision.status != "replied":
        reasons.append("status_not_replied")

    # Invalid/out-of-scope should not use LLM.
    if decision.request_type == "invalid":
        reasons.append("request_type_invalid")

    # Block adversarial/exfiltration rows.
    if assessment.is_adversarial:
        reasons.append("adversarial_detected")

    # Block any detected PII.
    if assessment.pii_detected:
        reasons.append("pii_detected")

    # Block legal/security/privacy/fraud/account compromise topics.
    if any(s.startswith("risk:") for s in assessment.risk_signals):
        reasons.append("risk_signals_present")

    if decision.risk_level in ("high", "critical"):
        reasons.append("risk_level_high_or_critical")

    # Require strong evidence only.
    if ctx.retrieval.overall_grade != "strong":
        reasons.append(f"evidence_not_strong:{ctx.retrieval.overall_grade}")

    # Require real citations already selected.
    if not decision.source_documents:
        reasons.append("missing_source_documents")

    # Never allow if any tool actions were planned.
    if decision.actions:
        reasons.append("has_actions_taken")

    # Account/billing action requests are blocked (verification-sensitive).
    if requires_account_action_escalation(ctx.ticket_text):
        reasons.append("account_action_requested")

    # Multilingual rows are blocked initially (higher prompt-injection / policy hallucination risk).
    if is_multilingual(ctx.ticket_text):
        reasons.append("multilingual_blocked")

    eligible = len(reasons) == 0
    return eligible, reasons

