"""Safe parsing of ticket issue JSON conversation histories."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ParsedIssue:
    """Result of parsing an issue column."""

    messages: tuple[dict[str, str], ...]
    parse_error: str | None
    raw: str


def parse_issue(raw: str | None) -> ParsedIssue:
    """
    Parse the issue field as a JSON array of conversation turns.

    Never raises. Malformed, empty, or non-array payloads return parse_error set.
    """
    text = (raw or "").strip()
    if not text:
        return ParsedIssue((), "empty_issue", raw or "")

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return ParsedIssue((), f"json_error:{exc.msg}", text)

    if not isinstance(data, list):
        return ParsedIssue((), "issue_not_array", text)

    messages: list[dict[str, str]] = []
    for index, item in enumerate(data):
        normalized = _normalize_turn(item, index)
        if normalized is not None:
            messages.append(normalized)

    if not messages and data:
        return ParsedIssue((), "no_valid_turns", text)

    return ParsedIssue(tuple(messages), None, text)


def _normalize_turn(item: Any, index: int) -> dict[str, str] | None:
    if isinstance(item, dict):
        role = item.get("role", "user")
        content = item.get("content", "")
        return {
            "role": str(role) if role is not None else "user",
            "content": str(content) if content is not None else "",
        }
    if isinstance(item, str):
        return {"role": "user", "content": item}
    if item is None:
        return None
    return {"role": "unknown", "content": str(item)}


def combined_user_text(parsed: ParsedIssue) -> str:
    """Concatenate user-role message text for lightweight heuristics."""
    parts: list[str] = []
    for message in parsed.messages:
        if message.get("role") == "user" and message.get("content"):
            parts.append(message["content"])
    if not parts and parsed.messages:
        for message in parsed.messages:
            if message.get("content"):
                parts.append(message["content"])
    return "\n".join(parts)
