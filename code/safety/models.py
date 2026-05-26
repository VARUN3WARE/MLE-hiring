"""Structured safety classification result."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SafetyAssessment:
    """
    Output of the safety firewall for downstream routing.

    Ticket text is untrusted; use redacted_text for retrieval/LLM prompts.
    notes are for internal logging — never expose to end users verbatim.
    """

    is_adversarial: bool
    pii_detected: bool
    risk_signals: tuple[str, ...]
    redacted_text: str
    recommended_risk_level: str
    notes: tuple[str, ...]
