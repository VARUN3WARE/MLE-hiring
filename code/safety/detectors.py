"""Adversarial and high-risk signal detectors for untrusted ticket text."""

from __future__ import annotations

import base64
import re

# --- Prompt injection / instruction override ---
_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "prompt_injection:instruction_override",
        re.compile(
            r"(?:ignore|disregard|forget|override)\s+(?:all\s+)?(?:previous|prior|above|earlier)"
            r"\s+(?:instructions?|rules?|guidelines?|directives?|prompts?)",
            re.IGNORECASE,
        ),
    ),
    (
        "prompt_injection:system_override",
        re.compile(
            r"\[?\s*system\s*(?:override|message|prompt)\s*\]?|"
            r"<\s*system\s*>|"
            r"system\s+override",
            re.IGNORECASE,
        ),
    ),
    (
        "prompt_injection:roleplay_jailbreak",
        re.compile(
            r"you\s+are\s+now\s+(?:dan\b|unrestricted|jailbroken|in\s+maintenance\s+mode)|"
            r"do\s+anything\s+now|"
            r"override\s+safety\s+protocols?|"
            r"without\s+restrictions?",
            re.IGNORECASE,
        ),
    ),
    (
        "prompt_injection:forced_output",
        re.compile(
            r"(?:output|respond|reply|print|return)\s+(?:exactly|verbatim|the\s+following)|"
            r"status\s*:\s*replied|"
            r"classify\s+(?:this|the\s+ticket)?\s+as\s+replied",
            re.IGNORECASE,
        ),
    ),
    (
        "prompt_injection:json_manipulation",
        re.compile(
            r"json\s+for\s+all\s+(?:remaining\s+)?tickets|"
            r"\"status\"\s*:\s*\"replied\"",
            re.IGNORECASE,
        ),
    ),
    (
        "prompt_injection:pretend_authority",
        re.compile(
            r"pretend\s+(?:you\s+are|to\s+be)|"
            r"act\s+as\s+(?:if\s+you\s+are\s+)?(?:an?\s+)?(?:admin|root|developer|engineer)",
            re.IGNORECASE,
        ),
    ),
)

# --- Exfiltration of internal assets ---
_EXFILTRATION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "exfiltration:system_prompt",
        re.compile(
            r"(?:share|show|print|reveal|output|display|dump|provide|tell\s+me)\s+"
            r"(?:your\s+)?(?:full\s+)?(?:system\s+prompt|hidden\s+instructions?|internal\s+instructions?)",
            re.IGNORECASE,
        ),
    ),
    (
        "exfiltration:tool_or_api",
        re.compile(
            r"(?:list|share|show|reveal|output)\s+(?:all\s+)?(?:your\s+)?"
            r"(?:tools?|api\s+keys?|function\s+definitions?|internal\s+tools?)",
            re.IGNORECASE,
        ),
    ),
    (
        "exfiltration:retrieval_or_architecture",
        re.compile(
            r"(?:retrieval\s+algorithm|vector\s+database|embedding\s+model|"
            r"knowledge\s+base\s+(?:contents?|inventory)|"
            r"complete\s+list\s+of\s+(?:support\s+)?articles|"
            r"internal\s+(?:rules?|logic|documents?\s+retrieved))",
            re.IGNORECASE,
        ),
    ),
    (
        "exfiltration:corpus_dump",
        re.compile(
            r"(?:all|every)\s+(?:documents?|articles?|files?)\s+(?:in|from)\s+"
            r"(?:your\s+)?(?:knowledge\s+base|corpus|repository)",
            re.IGNORECASE,
        ),
    ),
    (
        "exfiltration:multilingual_internal_rules",
        re.compile(
            r"(?:r[eè]gles\s+internes|documents?\s+r[eé]cup[eé]r[eé]s|"
            r"logique\s+exacte|affiche\s+toutes\s+les\s+r[eè]gles)",
            re.IGNORECASE,
        ),
    ),
)

# --- Fake authority / social engineering ---
_AUTHORITY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "authority:fake_qa_or_admin",
        re.compile(
            r"(?:qa\s+team|quality\s+assurance)\s+.*(?:disregard|override|test)|"
            r"this\s+is\s+a\s+test\s+by\s+the\s+(?:qa|security)\s+team",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "authority:automated_system_spoof",
        re.compile(
            r"automated\s+message\s+from\s+your\s+(?:monitoring|security)\s+system|"
            r"to\s+acknowledge\s+this\s+alert.*output\s+the\s+string",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "authority:impersonation_claim",
        re.compile(
            r"\b(?:i\s+am|this\s+is)\s+(?:from|with)\s+"
            r"(?:anthropic|openai|visa|devplatform)\s+(?:engineering|security|legal)\b",
            re.IGNORECASE,
        ),
    ),
)

# --- High-risk topics (not always adversarial) ---
_RISK_TOPIC_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("risk:legal_threat", re.compile(
        r"\b(?:lawsuit|class\s+action|sue\s+you|attorney|lawyer|legal\s+action|"
        r"file\s+a\s+complaint|damages|subpoena)\b",
        re.IGNORECASE,
    )),
    ("risk:identity_theft", re.compile(
        r"\bidentity\s+(?:theft|stolen)|stolen\s+identity\b",
        re.IGNORECASE,
    )),
    ("risk:account_compromise", re.compile(
        r"\b(?:account\s+compromised|unauthorized\s+access|account\s+takeover|"
        r"someone\s+else(?:'s)?\s+(?:conversation|account))\b",
        re.IGNORECASE,
    )),
    ("risk:privacy_breach", re.compile(
        r"\b(?:data\s+breach|privacy\s+breach|leaked\s+data|"
        r"gdpr|right\s+to\s+erasure|ico\s+complaint)\b",
        re.IGNORECASE,
    )),
    ("risk:security_vulnerability", re.compile(
        r"\b(?:security\s+vulnerability|zero[- ]day|cve-\d{4}-\d+|bug\s+bounty|"
        r"responsible\s+disclosure)\b",
        re.IGNORECASE,
    )),
    ("risk:fraud", re.compile(
        r"\b(?:fraud(?:ulent)?\s+charge|fraud\s+report|unauthorized\s+transaction)\b",
        re.IGNORECASE,
    )),
)

_BASE64_BLOB = re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b")
_BASE64_DECODE_HINTS = re.compile(
    r"(?:ignore|instruction|system\s+prompt|password|pwned|override|disregard)",
    re.IGNORECASE,
)


def _detect_base64_signals(text: str) -> list[str]:
    signals: list[str] = []
    for match in _BASE64_BLOB.finditer(text):
        blob = match.group(0)
        try:
            padded = blob + "=" * (-len(blob) % 4)
            decoded = base64.b64decode(padded, validate=True).decode("utf-8", errors="ignore")
            if len(decoded) >= 8 and _BASE64_DECODE_HINTS.search(decoded):
                signals.append("encoding:base64_instruction_payload")
            elif len(blob) >= 60:
                signals.append("encoding:suspicious_base64_blob")
        except (ValueError, UnicodeDecodeError):
            if len(blob) >= 60:
                signals.append("encoding:suspicious_base64_blob")
    return signals


def _match_patterns(
    text: str,
    pattern_groups: tuple[tuple[str, re.Pattern[str]], ...],
) -> list[str]:
    found: list[str] = []
    for signal, pattern in pattern_groups:
        if pattern.search(text):
            found.append(signal)
    return found


def detect_adversarial_signals(text: str) -> list[str]:
    """Signals indicating prompt injection or exfiltration attempts."""
    signals: list[str] = []
    signals.extend(_match_patterns(text, _INJECTION_PATTERNS))
    signals.extend(_match_patterns(text, _EXFILTRATION_PATTERNS))
    signals.extend(_match_patterns(text, _AUTHORITY_PATTERNS))
    signals.extend(_detect_base64_signals(text))
    return signals


def detect_risk_topic_signals(text: str) -> list[str]:
    """Signals for sensitive escalation topics."""
    return _match_patterns(text, _RISK_TOPIC_PATTERNS)


def is_adversarial_signal(signal: str) -> bool:
    return signal.startswith(
        ("prompt_injection:", "exfiltration:", "authority:", "encoding:")
    )
