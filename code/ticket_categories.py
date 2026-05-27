"""Reusable ticket category detectors (no row-specific literals)."""

from __future__ import annotations

import re
from pathlib import Path

HUB_PAGE_NAMES = frozenset({"index.md", "support.md"})

# Imperative account / billing actions that require human or verified tooling.
_ACCOUNT_ACTION_PHRASES: tuple[str, ...] = (
    "refund me",
    "give me my money",
    "issue a refund",
    "reverse the charge",
    "chargeback",
    "cancel my subscription",
    "upgrade my plan",
    "downgrade my plan",
    "ban the seller",
    "restore my access",
    "increase my score",
    "move me to the next round",
    "tell the company to",
    "modify my subscription",
    "lock my account",
    "freeze my account",
    "dispute this charge",
    "dispute the charge",
    "unauthorized charges",
    "fraud report",
)

# Policy / FAQ style questions (informational, not executing an action).
_POLICY_FAQ_MARKERS: tuple[str, ...] = (
    "how do i",
    "how can i",
    "what is",
    "what are",
    "can merchants",
    "does visa",
    "policy cover",
    "rules say",
    "minimum spend",
    "zero liability",
    "where can i find",
)

_OUT_OF_SCOPE_PHRASES: tuple[str, ...] = (
    "just wanted to say",
    "keep it up",
    "great work",
    "amazing",
    "no issue",
    "thank you for understanding",
    "links only",
)

_INVESTMENT_OUT_OF_SCOPE = re.compile(
    r"\b(?:investment advice|investment advice needed|should i buy|stock tip|financial advice|crypto)\b",
    re.IGNORECASE,
)

_LINK_HEAVY = re.compile(r"https?://", re.IGNORECASE)


def is_hub_path(path: str) -> bool:
    return Path(path).name.lower() in HUB_PAGE_NAMES


def is_harmless_out_of_scope(text: str) -> bool:
    """Praise, link dumps, or non-support requests that need a polite clarification."""
    low = (text or "").lower().strip()
    if not low:
        return False

    if _INVESTMENT_OUT_OF_SCOPE.search(low):
        return True
    if "investment" in low and "advice" in low:
        return True

    if any(phrase in low for phrase in _OUT_OF_SCOPE_PHRASES):
        return True

    # Mostly URLs with little user question text.
    urls = _LINK_HEAVY.findall(low)
    if len(urls) >= 2 and len(low.split()) < 45:
        return True

    return False


def requires_account_action_escalation(text: str) -> bool:
    """
    User is asking the agent to perform account/billing actions, not just read policy.
    """
    low = (text or "").lower()
    if not low:
        return False

    has_action = any(phrase in low for phrase in _ACCOUNT_ACTION_PHRASES)
    if not has_action:
        return False

    # Pure policy questions without action imperatives should not force escalation.
    looks_like_faq = any(marker in low for marker in _POLICY_FAQ_MARKERS)
    imperative = any(
        p in low
        for p in (
            "please ",
            "can you ",
            "i need you to",
            "help me get",
            "give me",
            "refund",
            "today",
            "immediately",
            "asap",
        )
    )
    if looks_like_faq and not imperative:
        return False

    return True


def is_multilingual(text: str) -> bool:
    return any(ord(ch) > 127 for ch in (text or ""))
