"""Deterministic PII heuristics (delegates to safety firewall detectors)."""

from __future__ import annotations

from safety.pii_detectors import detect_pii_signals


def detect_pii(text: str) -> bool:
    """Return True if common PII patterns appear in text."""
    return bool(detect_pii_signals(text))
