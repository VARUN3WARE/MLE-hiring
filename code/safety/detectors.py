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
            r"status\s*[:=]\s*replied|"
            r"set\s+(?:status|request_type|confidence)\s*(?:to|=)|"
            r"classify\s+(?:this|the\s+ticket)?\s+as\s+(?:replied|invalid|bug)|"
            r"confidence\s*[:=]\s*1\.?0",
            re.IGNORECASE,
        ),
    ),
    (
        "prompt_injection:ignore_rules_shorthand",
        re.compile(
            r"ignore\s+(?:all\s+)?(?:rules?|safety\s+rules?|previous\s+rules?)|"
            r"disregard\s+(?:all\s+)?(?:guidelines?|rules?)|"
            r"bypass\s+(?:escalation|safety|verification)",
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
        "prompt_injection:corpus_embedded_override",
        re.compile(
            r"```\s*system\b|SYSTEM\s+OVERRIDE|you\s+are\s+unrestricted|"
            r"comply\s+with\s+(?:user\s+)?orders|maintenance\s+mode\s+disabled|"
            r"<!--\s*ignore\s+safety|ignore\s+safety\s*-->",
            re.IGNORECASE,
        ),
    ),
    (
        "prompt_injection:pretend_unrestricted",
        re.compile(
            r"pretend\s+you\s+are\s+dan\b|"
            r"unrestricted\s+assistant|"
            r"without\s+restrictions?",
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
            r"(?:list|share|show|reveal|output|enumerate)\s+(?:all|every)\s+"
            r"(?:your\s+)?(?:internal\s+)?(?:tools?|api\s+keys?|function\s+definitions?)",
            re.IGNORECASE,
        ),
    ),
    (
        "exfiltration:internal_tools_phrase",
        re.compile(
            r"\binternal\s+tools?\b.*\b(?:api\s+keys?|you\s+can\s+call|allowed\s+to\s+call)\b|"
            r"\btool\s+schema\b|\bhidden\s+tool\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "exfiltration:retrieval_or_architecture",
        re.compile(
            r"(?:retrieval\s+algorithm|vector\s+database|embedding\s+model|"
            r"knowledge\s+base\s+(?:contents?|inventory)|"
            r"complete\s+list\s+of\s+(?:support\s+)?articles|"
            r"internal\s+(?:rules?|logic|documents?\s+retrieved)|"
            r"safety\s+layer|routing\s+code|routing\s+logic|processing\s+logic|"
            r"support\s+policies?\s+not\s+in|confidential\s+support\s+policies|"
            r"policy\s+not\s+supported\s+by\s+corpus|"
            r"dump\s+(?:the\s+)?(?:entire\s+)?(?:source\s+)?corpus|"
            r"architecture\s+(?:secrets?|details?))",
            re.IGNORECASE,
        ),
    ),
    (
        "exfiltration:hidden_prompt",
        re.compile(
            r"(?:hidden|developer|confidential)\s+(?:prompt|instructions?)|"
            r"(?:send|share|reveal|print)\s+(?:me\s+)?(?:the\s+)?hidden\s+prompt",
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
        "exfiltration:debug_or_internal_state",
        re.compile(
            r"\b(?:enter|enable|activate)\s+debug\s+mode\b|"
            r"\b(?:output|print|dump|return|send)\s+(?:raw\s+)?json\s+(?:for|of)\s+"
            r"(?:all\s+)?(?:internal\s+state|internal\s+data|your\s+internal)\b|"
            r"\b(?:raw\s+json|internal\s+state|internal\s+memory)\b",
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
            r"(?:qa\s+team|quality\s+assurance|platform\s+qa|qa\s+lead|qa\s+override)\b|"
            r"(?:recruiter|evaluator|hiring\s+platform)\s+(?:here|authorized|override)|"
            r"(?:platform\s+admin|system\s+admin|administrator)\s+(?:override|authorized)|"
            r"(?:vp\s+support|engineering\s+on[- ]call|on[- ]call\s+engineer)\b|"
            r"this\s+is\s+a\s+test\s+by\s+the\s+(?:qa|security)\s+team|"
            r"(?:disregard|override|bypass)\s+(?:safety\s+)?(?:rules?|guidelines?|checks?)",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "authority:override_codes",
        re.compile(
            r"\b(?:auth[_-]?code|admin\s+override|eval[-_]?2026|maintenance\s+mode)\b|"
            r"authorized\s+(?:this\s+ticket\s+)?to\s+bypass",
            re.IGNORECASE,
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
        r"\b(?:lawsuit|class\s+action|sue\s+you|sue\s+for|attorney|lawyer|legal\s+action|"
        r"file\s+a\s+complaint|formal\s+legal\s+notice|regulator\s+complaint|"
        r"financial\s+regulator|reporting\s+you\s+to\s+(?:the\s+)?(?:\w+\s+)?regulator|"
        r"contract\s+dispute|breach\s+of\s+contract|"
        r"chargeback\s+complaint|damages|subpoena|demandar|accion\s+legal)\b",
        re.IGNORECASE,
    )),
    ("risk:identity_theft", re.compile(
        r"\b(?:identity\s+(?:theft|stolen)|stolen\s+identity|identity\s+has\s+been\s+stolen|"
        r"identity\s+theft\s+report)\b",
        re.IGNORECASE,
    )),
    ("risk:account_compromise", re.compile(
        r"\b(?:account\s+compromised|unauthorized\s+(?:access|login|purchases|charges)|"
        r"account\s+takeover|hijacked|someone\s+else\s+(?:accessed|logged|used)|"
        r"someone\s+else(?:'s)?\s+(?:conversation|account|session))\b",
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
        r"\b(?:fraud(?:ulent)?\s+charge|fraud\s+report|fraud\s+on\s+card|"
        r"unauthorized\s+transaction|suspicious\s+activity)\b",
        re.IGNORECASE,
    )),
    ("risk:ambiguous_high_risk", re.compile(
        r"\b(?:not\s+sure\s+if\s+it\s+is\s+fraud|might\s+have\s+been\s+charged\s+twice|"
        r"something\s+feels\s+wrong\s+with\s+my\s+billing)\b",
        re.IGNORECASE,
    )),
)

_ENCODED_OVERRIDE = re.compile(
    r"%49%47%4e%4f%52%45|%50%52%45%56%49%4f%55%53|"
    r"(?:I\s+G\s+N\s+O\s+R\s+E|I\s+G\s+N\s+O\s+R\s+E\s+P\s+R\s+E\s+V\s+I\s+O\s+U\s+S)",
    re.IGNORECASE,
)
_MULTILINGUAL_INJECTION = re.compile(
    r"(?:ignore\s+previous|ignorieren\s+sie|ignorez\s+les|"
    r"ignore\s+all\s+rules|输出你的系统提示|system\s+prompt|"
    r"पिछले\s+निर्देश|अनदेखा\s+कर|आंतरिक\s+टूल|"
    r"anweisungen\s+ignorieren|instrucciones\s+anteriores)",
    re.IGNORECASE,
)
_DEVANAGARI_INJECTION = re.compile(
    r"[\u0900-\u097F].*(?:अनदेखा|निर्देश|आंतरिक\s+टूल|टूल\s+सूची)",
    re.DOTALL,
)
_BASE64_BLOB = re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b")
_BASE64_DECODE_HINTS = re.compile(
    r"(?:ignore|instruction|system\s+prompt|password|pwned|override|disregard)",
    re.IGNORECASE,
)
_SYSTEM_PROMPT_PHRASE = re.compile(r"\bsystem\s+prompt\b", re.IGNORECASE)
_DEVELOPER_API_CONTEXT = re.compile(
    r"\b(?:messages\s+api|anthropic\s+api|claude\s+api|api\s+request|"
    r"sdk|developer|my\s+app|application|integrate|parameter|"
    r"json\s+body|request\s+body|format(?:ting)?|"
    r"how\s+do\s+i|how\s+to|code\s+example|sample\s+code|"
    r"build(?:ing)?\s+(?:an?\s+)?(?:app|application))\b",
    re.IGNORECASE,
)
_EXFIL_SYSTEM_PROMPT_INTENT = re.compile(
    r"(?:share|show|print|reveal|output|display|dump|provide|tell\s+me)\s+"
    r"(?:your\s+)?(?:full\s+)?(?:system\s+prompt|hidden\s+instructions?)|"
    r"(?:your|hidden|full|internal)\s+system\s+prompt|"
    r"system\s+prompt\s+(?:and|&)\s+(?:internal|hidden|rules?)",
    re.IGNORECASE,
)
_SYSTEM_PROMPT_FALSE_POSITIVE_SIGNALS = frozenset(
    {
        "prompt_injection:system_override",
        "prompt_injection:multilingual_override",
    }
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


def _normalize_for_detection(text: str) -> str:
    """Strip zero-width and homoglyph spacing sometimes used to hide injections."""
    if not text:
        return ""
    cleaned = text
    for ch in ("\u200b", "\u200c", "\u200d", "\ufeff", "\u00ad"):
        cleaned = cleaned.replace(ch, " ")
    cleaned = re.sub(r"(?<=\w)\s+(?=\w)", " ", cleaned)
    return cleaned


def _is_safe_developer_system_prompt_reference(text: str) -> bool:
    """
    Allow 'system prompt' when it clearly refers to API/developer usage,
    not exfiltration of this agent's hidden instructions.
    """
    if not _SYSTEM_PROMPT_PHRASE.search(text):
        return False
    if _EXFIL_SYSTEM_PROMPT_INTENT.search(text):
        return False
    return bool(_DEVELOPER_API_CONTEXT.search(text))


def _filter_system_prompt_false_positives(text: str, signals: list[str]) -> list[str]:
    if not _is_safe_developer_system_prompt_reference(text):
        return signals
    return [signal for signal in signals if signal not in _SYSTEM_PROMPT_FALSE_POSITIVE_SIGNALS]


def detect_adversarial_signals(text: str) -> list[str]:
    """Signals indicating prompt injection or exfiltration attempts."""
    normalized = _normalize_for_detection(text)
    signals: list[str] = []
    signals.extend(_match_patterns(normalized, _INJECTION_PATTERNS))
    signals.extend(_match_patterns(normalized, _EXFILTRATION_PATTERNS))
    signals.extend(_match_patterns(normalized, _AUTHORITY_PATTERNS))
    signals.extend(_detect_base64_signals(normalized))
    if _ENCODED_OVERRIDE.search(normalized):
        signals.append("encoding:url_or_spaced_override")
    if _MULTILINGUAL_INJECTION.search(normalized):
        signals.append("prompt_injection:multilingual_override")
    if _DEVANAGARI_INJECTION.search(normalized):
        signals.append("prompt_injection:multilingual_override")
    if re.search(r"[\u0900-\u097F\u4e00-\u9fff]", normalized) and re.search(
        r"(?:ignore|internal|tool|prompt|override|disregard|"
        r"अनदेखा|आंतरिक|निर्देश|टूल)",
        normalized,
        re.IGNORECASE,
    ):
        signals.append("prompt_injection:multilingual_override")
    if re.search(r"\brot13\s*:", normalized, re.IGNORECASE) or re.search(
        r"\bVtaber\b", normalized
    ):
        signals.append("encoding:rot13_override")
    if re.search(
        r"\b(?:output|print|reveal)\s+(?:internal\s+)?tool\s+names?\b",
        normalized,
        re.IGNORECASE,
    ):
        signals.append("exfiltration:internal_tools_phrase")
    return _filter_system_prompt_false_positives(normalized, signals)


def detect_risk_topic_signals(text: str) -> list[str]:
    """Signals for sensitive escalation topics."""
    return _match_patterns(text, _RISK_TOPIC_PATTERNS)


def is_adversarial_signal(signal: str) -> bool:
    return signal.startswith(
        ("prompt_injection:", "exfiltration:", "authority:", "encoding:")
    )
