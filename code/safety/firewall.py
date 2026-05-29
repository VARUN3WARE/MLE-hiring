"""Orchestrate safety classification for untrusted ticket text."""

from __future__ import annotations

from safety.detectors import (
    detect_adversarial_signals,
    detect_risk_topic_signals,
    is_adversarial_signal,
)
from safety.models import SafetyAssessment
from safety.pii_detectors import detect_pii_signals
from safety.redaction import redact_text

# Signals that alone warrant critical handling.
_CRITICAL_SIGNALS = frozenset(
    {
        "risk:legal_threat",
        "risk:identity_theft",
        "risk:account_compromise",
        "risk:privacy_breach",
        "exfiltration:system_prompt",
        "exfiltration:tool_or_api",
        "prompt_injection:system_override",
    }
)

_HIGH_SIGNALS = frozenset(
    {
        "risk:security_vulnerability",
        "risk:fraud",
        "encoding:base64_instruction_payload",
        "encoding:url_or_spaced_override",
        "encoding:rot13_override",
        "prompt_injection:multilingual_override",
        "exfiltration:internal_tools_phrase",
        "exfiltration:debug_or_internal_state",
    }
)


def _compute_risk_level(
    signals: tuple[str, ...],
    *,
    is_adversarial: bool,
    pii_detected: bool,
) -> str:
    signal_set = set(signals)
    if is_adversarial and signal_set & _CRITICAL_SIGNALS:
        return "critical"
    if signal_set & _CRITICAL_SIGNALS:
        return "critical"
    if is_adversarial or signal_set & _HIGH_SIGNALS:
        return "high"
    if signal_set & {"risk:legal_threat", "risk:identity_theft", "risk:account_compromise"}:
        return "high"
    if pii_detected or any(s.startswith("risk:") for s in signals):
        return "medium"
    return "low"


def _build_notes(
    signals: tuple[str, ...],
    *,
    is_adversarial: bool,
    pii_detected: bool,
) -> tuple[str, ...]:
    notes: list[str] = []
    if is_adversarial:
        notes.append("Route as adversarial: refuse instruction injection and internal disclosure.")
    if pii_detected:
        notes.append("PII detected: use redacted_text only for downstream processing.")
    adv_count = sum(1 for s in signals if is_adversarial_signal(s))
    if adv_count:
        notes.append(f"Adversarial indicator count: {adv_count}.")
    if not notes:
        notes.append("No elevated safety signals.")
    return tuple(notes)


def classify_ticket(text: str) -> SafetyAssessment:
    """
    Classify untrusted ticket text before retrieval or generation.

    Treats ``text`` as data, not instructions. Does not execute embedded commands.
    """
    raw = text or ""
    redacted = redact_text(raw)

    pii_signals = detect_pii_signals(raw)
    adversarial_signals = detect_adversarial_signals(raw)
    risk_signals = detect_risk_topic_signals(raw)

    all_signals = sorted(set(pii_signals + adversarial_signals + risk_signals))
    adversarial = any(is_adversarial_signal(s) for s in all_signals)
    pii_found = bool(pii_signals)

    risk_level = _compute_risk_level(
        tuple(all_signals),
        is_adversarial=adversarial,
        pii_detected=pii_found,
    )
    notes = _build_notes(
        tuple(all_signals),
        is_adversarial=adversarial,
        pii_detected=pii_found,
    )

    return SafetyAssessment(
        is_adversarial=adversarial,
        pii_detected=pii_found,
        risk_signals=tuple(all_signals),
        redacted_text=redacted,
        recommended_risk_level=risk_level,
        notes=notes,
    )
