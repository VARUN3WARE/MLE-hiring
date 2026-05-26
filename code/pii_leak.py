"""Detect obvious PII fragments from ticket text echoed in responses."""

from __future__ import annotations

import re

from issue_parser import combined_user_text, parse_issue
from safety.pii_detectors import PII_MATCHERS

# Long digit/alphanumeric tokens often include order IDs and account numbers.
_TOKEN = re.compile(r"\b[A-Za-z0-9][A-Za-z0-9_-]{7,}\b")
_MIN_FRAGMENT_LEN = 8
_REDACTION_MARKERS = ("[REDACTED_",)


def input_text_for_row(issue: str, subject: str) -> str:
    parsed = parse_issue(issue)
    body = combined_user_text(parsed)
    parts = [subject or "", body or ""]
    if parsed.raw and parsed.parse_error:
        parts.append(parsed.raw)
    return "\n".join(p for p in parts if p)


def extract_sensitive_fragments(text: str) -> list[str]:
    """
    Extract substrings from input that should not be repeated verbatim in responses.

    Uses generic patterns only (no ticket-specific literals).
    """
    if not text:
        return []

    fragments: set[str] = set()

    for _label, pattern in PII_MATCHERS:
        for match in pattern.finditer(text):
            fragment = match.group(0)
            if not any(marker in fragment for marker in _REDACTION_MARKERS):
                fragments.add(fragment)

    for match in _TOKEN.finditer(text):
        token = match.group(0)
        if len(token) >= _MIN_FRAGMENT_LEN and any(ch.isdigit() for ch in token):
            fragments.add(token)

    # Long pure-digit runs (e.g. card fragments without separators).
    for match in re.finditer(r"\d{8,}", text):
        fragments.add(match.group(0))

    return sorted(fragments, key=len, reverse=True)


def find_pii_leaks(input_text: str, response: str) -> list[str]:
    """Return fragments from input that appear verbatim in the response."""
    if not input_text or not response:
        return []

    response_lower = response.lower()
    leaks: list[str] = []
    for fragment in extract_sensitive_fragments(input_text):
        if len(fragment) < 6:
            continue
        if fragment in response or fragment.lower() in response_lower:
            leaks.append(fragment)
    return leaks
