"""Build retrieval queries from ticket fields and intent keywords."""

from __future__ import annotations

import re
from dataclasses import dataclass

from issue_parser import combined_user_text, parse_issue
from retrieval.tokenize import tokenize

_COMPANY_TO_DOMAIN = {
    "devplatform": "devplatform",
    "claude": "claude",
    "visa": "visa",
    "none": "",
}

# Intent families expand recall without hardcoding ticket answers.
_INTENT_EXPANSIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("refund", ("refund", "chargeback", "money", "billing", "payment", "dispute")),
    ("access", ("access", "login", "password", "workspace", "seat", "permission")),
    ("fraud", ("fraud", "unauthorized", "stolen", "compromise", "identity")),
    ("test", ("test", "assessment", "interview", "codescreen", "codepair", "submission")),
    ("subscription", ("subscription", "plan", "cancel", "upgrade", "invoice")),
    ("privacy", ("privacy", "gdpr", "data", "deletion", "erase", "export")),
    ("travel", ("travel", "card", "blocked", "merchant", "visa", "transaction")),
    ("support", ("support", "help", "contact", "escalate")),
)

_TEXT_DOMAIN_HINTS: tuple[tuple[str, str], ...] = (
    ("claude", "claude"),
    ("anthropic", "claude"),
    ("workspace", "claude"),
    ("devplatform", "devplatform"),
    ("hackerrank", "devplatform"),
    ("codescreen", "devplatform"),
    ("codepair", "devplatform"),
    ("visa", "visa"),
    ("card", "visa"),
    ("chargeback", "visa"),
    ("merchant", "visa"),
)


@dataclass(frozen=True)
class RetrievalQuery:
    """Structured query context for ranking and grading."""

    text: str
    tokens: tuple[str, ...]
    company_domain: str
    text_domain_scores: tuple[tuple[str, int], ...]
    intent_terms: tuple[str, ...]


def company_to_domain(company: str | None) -> str:
    key = (company or "").strip().lower()
    return _COMPANY_TO_DOMAIN.get(key, "")


def infer_text_domain_scores(text: str) -> dict[str, int]:
    low = text.lower()
    scores: dict[str, int] = {"claude": 0, "devplatform": 0, "visa": 0}
    for keyword, domain in _TEXT_DOMAIN_HINTS:
        if keyword in low:
            scores[domain] += 1
    return scores


def extract_intent_terms(text: str) -> list[str]:
    low = text.lower()
    terms: list[str] = []
    for _label, keywords in _INTENT_EXPANSIONS:
        for kw in keywords:
            if kw in low and kw not in terms:
                terms.append(kw)
    return terms


def build_retrieval_query(
    *,
    issue: str,
    subject: str = "",
    company: str = "",
) -> RetrievalQuery:
    """
    Compose a cleaned query from conversation text, subject, and company hint.

    Adversarial instruction phrases are stripped heuristically (data only).
    """
    parsed = parse_issue(issue)
    body = combined_user_text(parsed)
    parts = [subject.strip(), body.strip()]
    raw = "\n".join(p for p in parts if p)

    cleaned = _strip_instructional_lines(raw)
    company_domain = company_to_domain(company)
    domain_scores = infer_text_domain_scores(cleaned)
    intent_terms = extract_intent_terms(cleaned)

    # Company hint tokens are low weight — may be misleading.
    token_parts = [cleaned]
    if company_domain:
        token_parts.append(company_domain)
    token_parts.extend(intent_terms)
    tokens = tokenize(" ".join(token_parts))

    sorted_domains = tuple(
        sorted(((d, s) for d, s in domain_scores.items() if s > 0), key=lambda x: (-x[1], x[0]))
    )

    return RetrievalQuery(
        text=cleaned,
        tokens=tuple(tokens),
        company_domain=company_domain,
        text_domain_scores=sorted_domains,
        intent_terms=tuple(intent_terms),
    )


def _strip_instructional_lines(text: str) -> str:
    """Remove lines that look like prompt-injection commands (not ticket answers)."""
    cleaned_lines: list[str] = []
    skip_patterns = (
        re.compile(r"ignore\s+(?:all\s+)?previous\s+instructions", re.I),
        re.compile(r"system\s+override", re.I),
        re.compile(r"output\s+(?:exactly|verbatim)", re.I),
        re.compile(r"disregard\s+all", re.I),
        re.compile(r"<\s*system\s*>", re.I),
        re.compile(r"\[system", re.I),
    )
    for line in text.splitlines():
        if any(p.search(line) for p in skip_patterns):
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip()
