"""Environment-driven configuration for the optional LLM polisher."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from paths import REPO_ROOT

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_PROVIDER = "openai"
DEFAULT_TIMEOUT_SECS = 8.0
DEFAULT_MAX_OUTPUT_TOKENS = 600


def _parse_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_dotenv_file(path: Path | None = None) -> None:
    """Load KEY=VALUE pairs from repo .env without overriding existing env vars."""
    env_path = path or (REPO_ROOT / ".env")
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ[key] = value


@dataclass(frozen=True)
class LLMConfig:
    enabled: bool
    provider: str
    model: str
    temperature: float
    timeout_secs: float
    max_output_tokens: int
    api_key: str | None
    max_polish_calls: int | None
    debug: bool


_CACHED: LLMConfig | None = None


def load_llm_config(*, load_env_file: bool = True, force_reload: bool = False) -> LLMConfig:
    global _CACHED
    if _CACHED is not None and not force_reload:
        return _CACHED

    if load_env_file:
        load_dotenv_file()

    use_llm_raw = os.environ.get("USE_LLM_POLISHER")
    if use_llm_raw is not None:
        enabled = _parse_bool(use_llm_raw, default=False)
    elif os.environ.get("LLM_ENABLED") is not None:
        # Back-compat with earlier .env.example name when USE_LLM_POLISHER is unset.
        enabled = _parse_bool(os.environ.get("LLM_ENABLED"), default=True)
    else:
        enabled = True

    max_polish_raw = os.environ.get("LLM_MAX_POLISH", "").strip()
    max_polish = int(max_polish_raw) if max_polish_raw.isdigit() else None

    try:
        timeout = float(os.environ.get("LLM_TIMEOUT_SECS", str(DEFAULT_TIMEOUT_SECS)))
    except ValueError:
        timeout = DEFAULT_TIMEOUT_SECS

    try:
        max_tokens = int(os.environ.get("LLM_MAX_OUTPUT_TOKENS", str(DEFAULT_MAX_OUTPUT_TOKENS)))
    except ValueError:
        max_tokens = DEFAULT_MAX_OUTPUT_TOKENS

    temperature_raw = os.environ.get("LLM_TEMPERATURE", "0")
    try:
        temperature = float(temperature_raw)
    except ValueError:
        temperature = 0.0

    provider = (os.environ.get("LLM_PROVIDER") or DEFAULT_PROVIDER).strip().lower()
    model = (os.environ.get("LLM_MODEL") or DEFAULT_MODEL).strip()

    api_key = (os.environ.get("OPENAI_API_KEY") or "").strip() or None

    _CACHED = LLMConfig(
        enabled=enabled,
        provider=provider,
        model=model,
        temperature=temperature,
        timeout_secs=max(1.0, timeout),
        max_output_tokens=max(64, max_tokens),
        api_key=api_key,
        max_polish_calls=max_polish,
        debug=_parse_bool(os.environ.get("LLM_DEBUG")),
    )
    return _CACHED


def reset_llm_config_cache() -> None:
    global _CACHED
    _CACHED = None
