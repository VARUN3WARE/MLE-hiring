"""Redact sensitive substrings from untrusted ticket text."""

from __future__ import annotations

import re
from typing import Callable

from safety.pii_detectors import PII_MATCHERS

# Order matters: longer / more specific patterns first where overlaps exist.
_REDACTION_RULES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (pattern, label) for label, pattern in PII_MATCHERS
)


def redact_text(text: str) -> str:
    """Return text with detected PII replaced by typed redaction tokens."""
    if not text:
        return ""

    redacted = text
    for pattern, label in _REDACTION_RULES:
        redacted = pattern.sub(label, redacted)
    return redacted
