"""OpenAI chat provider for the optional LLM polisher (stdlib HTTP only)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from llm.config import LLMConfig

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"


class LLMProviderError(Exception):
    """Raised when the provider call fails."""


class OpenAIChatProvider:
    """Minimal OpenAI chat completions client using urllib."""

    def __init__(self, config: LLMConfig) -> None:
        self._config = config

    def complete_json(self, *, system: str, user: str) -> str:
        if not self._config.api_key:
            raise LLMProviderError("missing_api_key")

        payload: dict[str, Any] = {
            "model": self._config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self._config.temperature,
            "max_tokens": self._config.max_output_tokens,
            "response_format": {"type": "json_object"},
        }
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            OPENAI_CHAT_URL,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._config.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._config.timeout_secs) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise LLMProviderError(f"http_{exc.code}:{detail}") from exc
        except urllib.error.URLError as exc:
            raise LLMProviderError(f"network_error:{exc.reason}") from exc
        except TimeoutError as exc:
            raise LLMProviderError("timeout") from exc

        try:
            parsed = json.loads(raw)
            return str(parsed["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise LLMProviderError("malformed_provider_response") from exc


def get_provider(config: LLMConfig) -> OpenAIChatProvider:
    if config.provider != "openai":
        raise LLMProviderError(f"unsupported_provider:{config.provider}")
    return OpenAIChatProvider(config)
