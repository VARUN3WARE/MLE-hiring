#!/usr/bin/env python3
"""Fallback and gating tests for the optional LLM polisher (no network)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.routing import route_ticket  # noqa: E402
from llm.config import LLMConfig, load_llm_config, reset_llm_config_cache  # noqa: E402
from llm.polisher import maybe_polish_response, reset_polish_stats  # noqa: E402


def _disabled_config() -> LLMConfig:
    return LLMConfig(
        enabled=False,
        provider="openai",
        model="gpt-4o-mini",
        temperature=0.0,
        timeout_secs=8.0,
        max_output_tokens=600,
        api_key=None,
        max_polish_calls=None,
        debug=False,
    )


def test_disabled_preserves_deterministic() -> None:
    reset_polish_stats()
    decision = route_ticket(
        issue='[{"role":"user","content":"How do I reset my password?"}]',
        subject="Password help",
        company="devplatform",
    )
    deterministic = decision.response
    out = maybe_polish_response(
        issue='[{"role":"user","content":"How do I reset my password?"}]',
        subject="Password help",
        company="devplatform",
        decision=decision,
        deterministic_response=deterministic,
        config=_disabled_config(),
    )
    assert out == deterministic


def test_missing_key_preserves_deterministic() -> None:
    reset_polish_stats()
    cfg = LLMConfig(
        enabled=True,
        provider="openai",
        model="gpt-4o-mini",
        temperature=0.0,
        timeout_secs=8.0,
        max_output_tokens=600,
        api_key=None,
        max_polish_calls=None,
        debug=False,
    )
    decision = route_ticket(
        issue='[{"role":"user","content":"How do I get started with Claude?"}]',
        subject="Getting started",
        company="claude",
    )
    out = maybe_polish_response(
        issue='[{"role":"user","content":"How do I get started with Claude?"}]',
        subject="Getting started",
        company="claude",
        decision=decision,
        deterministic_response=decision.response,
        config=cfg,
    )
    assert out == decision.response


def test_validation_failure_preserves_deterministic() -> None:
    reset_polish_stats()
    cfg = LLMConfig(
        enabled=True,
        provider="openai",
        model="gpt-4o-mini",
        temperature=0.0,
        timeout_secs=8.0,
        max_output_tokens=600,
        api_key="test-key",
        max_polish_calls=None,
        debug=False,
    )
    decision = route_ticket(
        issue='[{"role":"user","content":"How do I get started with Claude?"}]',
        subject="Getting started",
        company="claude",
    )
    bad_json = '{"response":"x","used_sources":[],"changed_meaning":true,"pii_echo_risk":false}'
    with patch("llm.polisher.get_provider") as mock_get:
        mock_get.return_value.complete_json.return_value = bad_json
        out = maybe_polish_response(
            issue='[{"role":"user","content":"How do I get started with Claude?"}]',
            subject="Getting started",
            company="claude",
            decision=decision,
            deterministic_response=decision.response,
            config=cfg,
        )
    assert out == decision.response


def test_env_flag_alias() -> None:
    reset_llm_config_cache()
    with patch.dict(os.environ, {"USE_LLM_POLISHER": "false", "LLM_ENABLED": "true"}, clear=False):
        reset_llm_config_cache()
        cfg = load_llm_config(force_reload=True)
    assert cfg.enabled is True


def main() -> int:
    tests = [
        test_disabled_preserves_deterministic,
        test_missing_key_preserves_deterministic,
        test_validation_failure_preserves_deterministic,
        test_env_flag_alias,
    ]
    failures: list[str] = []
    for test in tests:
        try:
            test()
            print(f"PASS: {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{test.__name__}: {exc}")
            print(f"FAIL: {test.__name__}: {exc}")

    if failures:
        print(f"\n{len(failures)} test(s) failed.")
        return 1
    print(f"\nAll {len(tests)} test(s) passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
