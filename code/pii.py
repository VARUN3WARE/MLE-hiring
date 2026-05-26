"""Deterministic PII heuristics (scaffold-level, not production-grade)."""

from __future__ import annotations

import re

# Patterns are generic; they do not encode ticket-specific answers.
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CARD = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
_PHONE = re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")

# Shared patterns for PII detection and leak checks (generic, not ticket-specific).
SENSITIVE_PATTERNS = (_EMAIL, _SSN, _CARD, _PHONE)


def detect_pii(text: str) -> bool:
    """Return True if common PII patterns appear in text."""
    if not text:
        return False
    return any(pattern.search(text) for pattern in SENSITIVE_PATTERNS)
