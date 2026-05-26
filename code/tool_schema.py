"""Load and validate tool calls against data/api_specs/internal_tools.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from paths import REPO_ROOT

DEFAULT_TOOLS_PATH = REPO_ROOT / "data" / "api_specs" / "internal_tools.json"


def load_tool_specs(tools_path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Return mapping of tool name -> parameters schema object."""
    path = tools_path or DEFAULT_TOOLS_PATH
    with path.open(encoding="utf-8") as handle:
        tools = json.load(handle)
    return {tool["name"]: tool["parameters"] for tool in tools}


def validate_actions(
    actions: list[Any],
    specs: dict[str, dict[str, Any]],
    row_index: int,
) -> list[str]:
    """Return human-readable errors for invalid actions in one row."""
    errors: list[str] = []
    prefix = f"Row {row_index}"

    if not isinstance(actions, list):
        return [f"{prefix}: actions_taken must be a JSON array"]

    for action_index, item in enumerate(actions, start=1):
        if not isinstance(item, dict):
            errors.append(f"{prefix} action {action_index}: expected object, got {type(item).__name__}")
            continue

        tool_name = item.get("action") or item.get("name")
        if not tool_name or not isinstance(tool_name, str):
            errors.append(f"{prefix} action {action_index}: missing 'action' tool name")
            continue

        if tool_name not in specs:
            allowed = ", ".join(sorted(specs))
            errors.append(f"{prefix} action {action_index}: unknown tool '{tool_name}' (allowed: {allowed})")
            continue

        parameters = item.get("parameters")
        if parameters is None:
            parameters = item.get("params", {})
        if not isinstance(parameters, dict):
            errors.append(f"{prefix} action {action_index}: 'parameters' must be an object")
            continue

        schema = specs[tool_name]
        required = schema.get("required", [])
        for key in required:
            if key not in parameters or parameters[key] in (None, ""):
                errors.append(
                    f"{prefix} action {action_index}: tool '{tool_name}' missing required parameter '{key}'"
                )

        allowed_props = set(schema.get("properties", {}))
        for key in parameters:
            if key not in allowed_props:
                errors.append(
                    f"{prefix} action {action_index}: tool '{tool_name}' has unexpected parameter '{key}'"
                )

    return errors
