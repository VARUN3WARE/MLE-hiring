"""JSON shape validation for optional LLM polisher output (no API calls)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from llm.packet import OUTPUT_FIELD_SCHEMA

REQUIRED_OUTPUT_KEYS = frozenset(OUTPUT_FIELD_SCHEMA.keys())
ALLOWED_OUTPUT_KEYS = REQUIRED_OUTPUT_KEYS

MAX_RESPONSE_CHARS = 4000

_PATH_IN_TEXT = re.compile(r"\bdata/[A-Za-z0-9_./-]+\.md\b")


@dataclass(frozen=True)
class ValidatedLLMOutput:
    response: str
    used_sources: tuple[str, ...]
    changed_meaning: bool
    pii_echo_risk: bool


def parse_llm_json(raw: str) -> tuple[dict[str, Any] | None, list[str]]:
    """Parse LLM body as JSON object."""
    errors: list[str] = []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, [f"invalid_json:{exc.msg}"]

    if not isinstance(parsed, dict):
        return None, ["root_not_object"]
    return parsed, errors


def validate_llm_output(
    payload: dict[str, Any] | str,
    *,
    approved_sources: frozenset[str],
) -> tuple[ValidatedLLMOutput | None, list[str]]:
    """
    Validate LLM polish output against the locked contract.

    Returns (validated_output, errors). On failure, validated_output is None.
    """
    errors: list[str] = []

    if isinstance(payload, str):
        parsed, parse_errors = parse_llm_json(payload)
        if parse_errors:
            return None, parse_errors
        assert parsed is not None
        payload = parsed

    if not isinstance(payload, dict):
        return None, ["root_not_object"]

    keys = set(payload.keys())
    missing = REQUIRED_OUTPUT_KEYS - keys
    if missing:
        errors.extend(f"missing_key:{k}" for k in sorted(missing))
    extra = keys - ALLOWED_OUTPUT_KEYS
    if extra:
        errors.extend(f"extra_key:{k}" for k in sorted(extra))
    if errors:
        return None, errors

    response = payload["response"]
    if not isinstance(response, str):
        errors.append("response_not_string")
    elif not response.strip():
        errors.append("response_empty")
    elif len(response) > MAX_RESPONSE_CHARS:
        errors.append("response_too_long")

    used_sources = payload["used_sources"]
    if not isinstance(used_sources, list):
        errors.append("used_sources_not_list")
    else:
        for idx, item in enumerate(used_sources):
            if not isinstance(item, str):
                errors.append(f"used_sources_{idx}_not_string")
            elif item not in approved_sources:
                errors.append(f"unapproved_source:{item}")

    for flag in ("changed_meaning", "pii_echo_risk"):
        value = payload[flag]
        if not isinstance(value, bool):
            errors.append(f"{flag}_not_boolean")
        elif value is True:
            errors.append(f"{flag}_true")

    if isinstance(response, str):
        for path in _PATH_IN_TEXT.findall(response):
            if path not in approved_sources:
                errors.append(f"unapproved_path_in_response:{path}")

    if errors:
        return None, errors

    assert isinstance(response, str)
    normalized_sources = tuple(
        str(s) for s in used_sources if isinstance(s, str) and s in approved_sources
    )
    return (
        ValidatedLLMOutput(
            response=response.strip(),
            used_sources=normalized_sources,
            changed_meaning=bool(payload["changed_meaning"]),
            pii_echo_risk=bool(payload["pii_echo_risk"]),
        ),
        [],
    )
