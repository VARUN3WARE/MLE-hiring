"""Infer product/domain hints without trusting directory placement alone."""

from __future__ import annotations

from pathlib import Path

_TOP_LEVEL_DOMAINS = frozenset({"claude", "devplatform", "visa"})

_PATH_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("hackerrank", "devplatform"),
    ("devplatform", "devplatform"),
    ("codescreen", "devplatform"),
    ("codepair", "devplatform"),
    ("anthropic", "claude"),
    ("claude", "claude"),
    ("amazon-bedrock", "claude"),
    ("visa.co.in", "visa"),
    ("/visa/", "visa"),
)


def infer_domain_hints(
    rel_path: str,
    *,
    breadcrumbs: tuple[str, ...],
    title: str,
    body: str,
) -> tuple[str, ...]:
    """
    Combine weak signals: top-level data folder, path keywords, breadcrumbs, title/body.
    Folder location is a hint only — not authoritative.
    """
    hints: set[str] = set()
    parts = Path(rel_path).parts

    if len(parts) >= 2 and parts[0] == "data" and parts[1] in _TOP_LEVEL_DOMAINS:
        hints.add(parts[1])

    combined = f"{rel_path}\n{title}\n{' '.join(breadcrumbs)}\n{body[:500]}".lower()
    for keyword, domain in _PATH_KEYWORDS:
        if keyword in combined:
            hints.add(domain)

    for crumb in breadcrumbs:
        low = crumb.lower()
        if "claude" in low or "anthropic" in low:
            hints.add("claude")
        if "devplatform" in low or "hackerrank" in low:
            hints.add("devplatform")
        if "visa" in low:
            hints.add("visa")

    if not hints and len(parts) >= 2 and parts[0] == "data":
        hints.add("unknown")

    return tuple(sorted(hints))
