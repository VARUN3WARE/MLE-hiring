"""Reusable PII detectors (generic patterns only — no row-specific literals)."""

from __future__ import annotations

import re

# (redaction_label, compiled_pattern)
PII_MATCHERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "[REDACTED_EMAIL]",
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    ),
    ("[REDACTED_SSN]", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    (
        "[REDACTED_CARD]",
        re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
    ),
    (
        "[REDACTED_PHONE]",
        re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3}[-.\s]?\d{3,4}\b"),
    ),
    (
        "[REDACTED_DOB]",
        re.compile(
            r"\b(?:0?[1-9]|1[0-2])[/-](?:0?[1-9]|[12]\d|3[01])[/-](?:19|20)\d{2}\b",
            re.IGNORECASE,
        ),
    ),
    (
        "[REDACTED_ADDRESS]",
        re.compile(
            r"\b\d{1,6}\s+[A-Za-z0-9.'-]+(?:\s+[A-Za-z0-9.'-]+){0,6}\s+"
            r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "[REDACTED_TOKEN]",
        re.compile(
            r"\b(?:sk-[A-Za-z0-9]{10,}|pk_(?:live|test)_[A-Za-z0-9]{10,}|"
            r"cs_(?:live|test)_[A-Za-z0-9]{6,}|Bearer\s+[A-Za-z0-9._-]{10,})\b",
            re.IGNORECASE,
        ),
    ),
    (
        "[REDACTED_ACCOUNT_ID]",
        re.compile(
            r"\b(?:account|acct|user|member|card|order|txn|transaction)"
            r"[\s_-]*(?:id|number|no|#)?\s*[:#]?\s*[A-Za-z0-9][A-Za-z0-9_-]{5,}\b",
            re.IGNORECASE,
        ),
    ),
    ("[REDACTED_ID]", re.compile(r"\b\d{8,}\b")),
)

PII_SIGNAL_BY_LABEL: dict[str, str] = {
    "[REDACTED_EMAIL]": "pii:email",
    "[REDACTED_SSN]": "pii:ssn",
    "[REDACTED_CARD]": "pii:payment_card",
    "[REDACTED_PHONE]": "pii:phone",
    "[REDACTED_DOB]": "pii:date_of_birth",
    "[REDACTED_ADDRESS]": "pii:address",
    "[REDACTED_TOKEN]": "pii:api_token",
    "[REDACTED_ACCOUNT_ID]": "pii:account_identifier",
    "[REDACTED_ID]": "pii:numeric_identifier",
}


def detect_pii_signals(text: str) -> list[str]:
    """Return sorted unique PII signal codes found in text."""
    if not text:
        return []
    found: set[str] = set()
    for label, pattern in PII_MATCHERS:
        if pattern.search(text):
            found.add(PII_SIGNAL_BY_LABEL[label])
    return sorted(found)
